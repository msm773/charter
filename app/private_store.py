"""Charter's private, per-machine state.

Agent Context as the Project Asset §3 and the Product Specification §4: authority
candidates and drafts, archived documents, Agent Proposal records and
decisions, change sets and receipts, cached observations,
locks, staging and activity live in the operating system's application-data
location. They are never part of an Agent Context, never committed, never
served to agents, and disposable: losing them never destroys approved context.

Private state is associated with an Agent Context folder by that folder's
canonical location on this computer, and nothing else. Nothing is written into
the folder to identify it: no id, binding or registration. Reopening the same
folder finds the same state; a copied, moved or cloned folder starts fresh.

The state root is found only from the operating system, through `host_state`,
and is restricted to this user. No environment variable, configuration
or argument can move it. `PrivateState.default()` is the only way shipped code
obtains one; tests isolate it through the verification harness.

Charter was developed as Agent Context Manager, whose state root is the
`ACM` folder (`acm` on Linux) beside Charter's own (Agent Context as the
Project Asset §3). The first operation that writes private state adopts it:
one rename of that folder into Charter's place, so every record moves at once
or none does. Charter never starts a fresh root while only the earlier one
exists, and never deletes it. When both exist, Charter uses its own and
reports the earlier one. Read-only operations adopt and create nothing; they
read the earlier root while it is the only one.

Layout, under the state root:

    contexts/<key>/
        context.json          the folder this state belongs to
        candidates/<name>.md  authority candidates, by logical path
                              `authority-candidates/<name>.md`
        archive/<name>.md     replaced, withdrawn-then-retired, retired documents
        candidate-baselines/<name>.json
                              each candidate's one baseline: the text Charter
                              last wrote for it, the kind of action, the date
        proposals/            Agent Proposal records and decisions
        changesets/           change-set drafts and applied receipts
        observed.json         the context as Charter last saw it
        staging/              private staging for writes in progress
        locks/                cross-process locks
    recent-cleared.json       folders cleared from the console's Recent list
    recent-opened.json        when each folder was last opened, to order Recent
"""
from __future__ import annotations

import contextlib
import os
import re
import stat
import sys
import time
import unicodedata
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from . import host_state as hs

CONTEXTS = "contexts"
CONTEXT_RECORD = "context.json"
# Marks state created under the rule that Recent lists only Agent Contexts
# opened or created in the console (UI and Interaction Standards, criterion
# 22): such a folder is listed once the console opens it, never merely because
# MCP, `charter check`, `charter propose` or another command made its state.
# State without the mark predates the rule; it stays listed as it was.
CONSOLE_RECENT = "recent_when_opened"
OBSERVED = "observed.json"
LAST_SETTINGS = "settings.json"
CANDIDATES = "candidates"
ARCHIVE = "archive"
PROPOSALS = "proposals"
CHANGESETS = "changesets"
STAGING = "staging"
LOCKS = "locks"
SUBFOLDERS = (CANDIDATES, ARCHIVE, PROPOSALS, CHANGESETS, STAGING, LOCKS)
# Each authority candidate's one baseline — the text Charter last wrote for it,
# with the kind of action and the date (Product Specification §4) — as
# `candidate-baselines/<candidate name>.json`. Created when first written.
BASELINES = "candidate-baselines"
# Files an operating system may leave in any folder it shows, as the Agent
# Context tolerates them (`agent_context.SYSTEM_FILES`): never reported as
# candidates Charter cannot use.
_SYSTEM_FILES = (".ds_store", "thumbs.db", "desktop.ini")
# Beside `contexts/`: the folders the person cleared from the Recent list.
RECENT_CLEARED = "recent-cleared.json"
# Beside it: when each folder was last opened in the console, to order Recent.
RECENT_OPENED = "recent-opened.json"

# The proposal schema's logical prefix for a candidate. It names no folder in
# the Agent Context and none an agent can read.
CANDIDATE_PREFIX = "authority-candidates/"

# `charter`: Charter itself wrote it. `acm` is the same, recorded under the
# earlier product name; kept so those records stay readable.
OBSERVED_SOURCES = ("charter", "acm", "rebuild", "seen")

LOCK_TIMEOUT = 5.0
RECORD_VERSION = 1
MAX_NAME = 120
# How many numbered names (`name-2.md`, `name-3.md`, …) are tried before a new
# private document name is refused as unavailable, rather than searched forever.
MAX_NAME_TRIES = 1000

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.md$")
# Names Windows reserves for devices, with any extension.
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)),
             *(f"lpt{i}" for i in range(1, 10))}


class PrivateStateError(ValueError):
    """A private-state problem, worded for the person, never for an agent."""


STATE_UNUSABLE = (
    "Charter's private state for this Agent Context cannot be used ({why}), so Charter will "
    "not act on this folder or serve it to agents until it is resolved. Nothing was changed. "
    "The state is at {base}; it is disposable. Move that folder aside, and Charter starts "
    "afresh for this Agent Context; its candidates, archive and proposals stay in the folder "
    "you moved.")


def _plain_folder(path: str) -> Optional[bool]:
    """True for a plain folder, False when nothing is there, None for anything
    else: a link, junction or other reparse point, a file, or a folder that
    cannot be examined."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError:
        return None
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    if not stat.S_ISDIR(st.st_mode) or getattr(st, "st_file_attributes", 0) & reparse:
        return None
    return True


def _record_folder(record: Any) -> Optional[str]:
    if not isinstance(record, dict) or not isinstance(record.get("folder"), str):
        return None
    return os.path.normcase(record["folder"])


def _journal_may_exist(base: str) -> bool:
    """Whether an interrupted-write record may be in this state: present, or
    its folder not examinable. Mirrors `transaction.journal_state`, which this
    module cannot import."""
    journal = os.path.join(base, STAGING, "journal")
    for folder in (os.path.join(base, STAGING), journal):
        exists = _plain_folder(folder)
        if exists is False:
            return False
        if exists is None:
            return True
    try:
        os.lstat(os.path.join(journal, "journal.json"))
        return True
    except FileNotFoundError:
        pass
    except OSError:
        return True
    try:
        os.listdir(journal)
    except OSError:
        return True
    return False


# --- the state root ------------------------------------------------------------

def _default_root() -> str:
    if os.name == "nt":
        return os.path.join(hs._known_local_app_data(), "Charter")
    home = hs._account_home()
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Application Support", "Charter")
    return os.path.join(home, ".local", "state", "charter")


def _legacy_root(root: str) -> str:
    """Where Agent Context Manager kept this state: the folder beside `root`
    named for the earlier product. Derived from `root`, so whatever isolates
    Charter's root isolates the earlier one with it."""
    linux = os.name != "nt" and sys.platform != "darwin"
    return os.path.join(os.path.dirname(root), "acm" if linux else "ACM")


ADOPT_FAILED = (
    "Charter could not take over the private state that Agent Context Manager, its earlier "
    "name, left at {legacy} ({why}). Nothing was moved and nothing was written. Close every "
    "program still running Agent Context Manager — an agent host using an earlier `acm` "
    "connection, or an `acm serve` window — and try again.")


# --- candidate names -----------------------------------------------------------------

def name_problem(name: str) -> str:
    """Why `name` cannot name a candidate or archived document, or ""."""
    if not isinstance(name, str) or not _NAME.match(name):
        return ("A document name uses letters, digits, `.`, `_` or `-`, starts with a letter "
                "or digit, and ends in `.md`.")
    if len(name) > MAX_NAME:
        return f"A document name is at most {MAX_NAME} characters."
    if name.split(".", 1)[0].lower() in _RESERVED:
        return f"`{name}` is a name Windows reserves for a device."
    return ""


def candidate_name(logical: str) -> str:
    """The file name a logical candidate path `authority-candidates/<name>.md`
    names, or PrivateStateError."""
    if not isinstance(logical, str) or not logical.startswith(CANDIDATE_PREFIX):
        raise PrivateStateError("A candidate is named `authority-candidates/<name>.md`.")
    name = logical[len(CANDIDATE_PREFIX):]
    problem = name_problem(name)
    if problem:
        raise PrivateStateError(problem)
    return name


def logical_candidate(name: str) -> str:
    return CANDIDATE_PREFIX + name


def safe_stem(text: str) -> str:
    """A document-name stem made from any text — a governing file name may use
    spaces, accents or a leading underscore that a private name may not:
    accents dropped, every other character outside letters, digits, `.`, `_`
    and `-` made a `-`, starting with a letter or digit, never a Windows
    device name, and short enough to take a numbered suffix. `document` when
    nothing usable is left."""
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    stem = re.sub(r"-{2,}", "-", re.sub(r"[^A-Za-z0-9._-]+", "-", plain))
    stem = re.sub(r"^[^A-Za-z0-9]+", "", stem)[:MAX_NAME - 8].rstrip("-.")
    if not stem:
        stem = "document"
    if stem.split(".", 1)[0].lower() in _RESERVED:
        stem = f"{stem}-document"
    return stem


NO_FREE_NAME = ("Charter could not find a free private name for “{stem}”: `{stem}.md` and the "
                "next {tries} numbered names are all taken by governing documents, authority "
                "candidates or archived documents. Retire or remove some of those with similar "
                "names, then try again. Nothing was changed.")


def free_name(stem: str, taken: Iterable[str], first: str = "") -> str:
    """A valid document name not in `taken` (compared ignoring letter case):
    `first` when it is one, else `stem.md`, `stem-2.md`, … — each shortened to
    fit MAX_NAME with its suffix, and `stem` made safe first when it could
    never name a document. PrivateStateError after MAX_NAME_TRIES names, so a
    crowded or unusable name is refused instead of searched for forever."""
    folded = {_fold(t) for t in taken}
    if first and not name_problem(first) and _fold(first) not in folded:
        return first
    if name_problem(f"{stem[:MAX_NAME - 3]}.md"):
        stem = safe_stem(stem)
    for n in range(1, MAX_NAME_TRIES + 1):
        suffix = "" if n == 1 else f"-{n}"
        name = f"{stem[:MAX_NAME - 3 - len(suffix)]}{suffix}.md"
        if not name_problem(name) and _fold(name) not in folded:
            return name
    raise PrivateStateError(NO_FREE_NAME.format(stem=stem, tries=MAX_NAME_TRIES - 1))


def _fold(name: str) -> str:
    return name.casefold()


# --- state ---------------------------------------------------------------------------------

class PrivateState:
    """This user's Charter state on this computer."""

    __slots__ = ("_root", "_legacy")

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("PrivateState is obtained with PrivateState.default().")

    @classmethod
    def _create(cls, root: str) -> "PrivateState":
        self = object.__new__(cls)
        object.__setattr__(self, "_root", root)
        object.__setattr__(self, "_legacy", _legacy_root(root))
        return self

    @classmethod
    def default(cls) -> "PrivateState":
        return cls._create(_default_root())

    @property
    def root(self) -> str:
        return self._root

    @property
    def legacy_root(self) -> str:
        """Where Agent Context Manager kept this state, whether or not it is there."""
        return self._legacy

    def _read_root(self) -> str:
        """The root a read-only operation reads: Charter's, or the earlier one
        while it is the only one, not yet adopted."""
        if not os.path.isdir(self._root) and os.path.isdir(self._legacy):
            return self._legacy
        return self._root

    def legacy(self) -> Dict[str, str]:
        """Whether Agent Context Manager's state is still on this computer:
        `pending` while it is the only state, to be adopted on the next write;
        `left` when Charter has its own and the earlier folder is also there.
        Reads only."""
        if not os.path.isdir(self._legacy):
            return {"status": "", "path": "", "message": ""}
        if not os.path.isdir(self._root):
            return {"status": "pending", "path": self._legacy, "message": (
                f"Private state from Agent Context Manager, Charter's earlier name, is at "
                f"{self._legacy}. Charter takes it over, unchanged, the next time it saves "
                "anything.")}
        return {"status": "left", "path": self._legacy, "message": (
            f"Private state from Agent Context Manager, Charter's earlier name, is still at "
            f"{self._legacy}. Charter uses its own state at {self._root} and has not read or "
            "changed the earlier folder. Keep what you need from it, then remove it yourself.")}

    def _adopt(self) -> None:
        """Move Agent Context Manager's state into Charter's place: one rename,
        so every record moves or none does. Refuses, writing nothing, when it
        cannot."""
        if os.path.islink(self._legacy):
            raise PrivateStateError(ADOPT_FAILED.format(
                legacy=self._legacy, why="it is a link, which Charter does not follow"))
        try:
            os.rename(self._legacy, self._root)
        except OSError as exc:
            if os.path.isdir(self._root) and not os.path.isdir(self._legacy):
                return  # another Charter process adopted it a moment ago
            raise PrivateStateError(ADOPT_FAILED.format(legacy=self._legacy,
                                                        why=exc.strerror or exc))

    def ensure(self) -> None:
        """Create the state root, restricted to this user, or refuse to use one
        that is no longer private. Adopts the earlier name's state first,
        when it is the only state here."""
        if not os.path.isdir(self._root) and (os.path.isdir(self._legacy)
                                               or os.path.islink(self._legacy)):
            self._adopt()
        if not os.path.isdir(self._root):
            os.makedirs(self._root, mode=0o700, exist_ok=True)
            try:
                hs.restrict_to_owner(self._root)
            except hs.HostStateError:
                os.rmdir(self._root)
                raise PrivateStateError("Charter could not make its private "
                                        "state folder private to this user.")
        problem = hs.private_problem(self._root)
        if problem:
            raise PrivateStateError(f"Charter's private state folder is no longer "
                                    f"private to this user: {problem}.")

    def for_context(self, folder: str) -> "ContextState":
        """The private state for the Agent Context at `folder`, created on first
        use. Writes nothing in `folder`. Refuses, creating nothing more, when
        state is already there but cannot be read or belongs to another folder:
        it is never silently replaced."""
        folder = hs.canonical(folder)
        if hs.overlaps(folder, self._root) or hs.overlaps(folder, self._legacy):
            raise PrivateStateError("An Agent Context cannot be inside Charter's "
                                    "private state, or contain it.")
        self.ensure()
        key = hs.location_key(folder)
        base = os.path.join(self._root, CONTEXTS, key)
        exists = _plain_folder(base)
        if exists is None:
            raise PrivateStateError(STATE_UNUSABLE.format(
                why="it is a link, not a folder, or cannot be examined", base=base))
        try:
            record = hs.read_json(os.path.join(base, CONTEXT_RECORD), None) if exists else None
        except hs.HostStateError:
            raise PrivateStateError(STATE_UNUSABLE.format(
                why="its record of which folder it belongs to cannot be read", base=base))
        if record is not None and _record_folder(record) != os.path.normcase(folder):
            raise PrivateStateError("Charter's private state for this folder "
                                    "belongs to another folder. " + STATE_UNUSABLE.format(
                                        why="it names another folder", base=base))
        for sub in SUBFOLDERS:
            os.makedirs(os.path.join(base, sub), mode=0o700, exist_ok=True)
        if record is None:
            hs.write_json_atomic(os.path.join(base, CONTEXT_RECORD),
                                 {"version": RECORD_VERSION, "folder": folder, CONSOLE_RECENT: True})
        return ContextState(folder, base)

    def find_context(self, folder: str, strict: bool = False) -> Optional["ContextState"]:
        """The existing private state for `folder`, or None. Creates nothing:
        for read-only checks.

        Without `strict`, state that cannot be read or belongs to another folder
        is None, as if absent. With `strict` -- wherever an interrupted write
        must not be missed, such as before MCP serves -- only state that is
        truly absent is None; state that is there but unreadable, mismatched or
        reached through a link is PrivateStateError, so the caller fails
        closed."""
        folder = hs.canonical(folder)
        base = os.path.join(self._read_root(), CONTEXTS, hs.location_key(folder))

        def unusable(why: str) -> None:
            if strict:
                raise PrivateStateError(STATE_UNUSABLE.format(why=why, base=base))

        exists = _plain_folder(base)
        if exists is False:
            return None
        if exists is None:
            unusable("it is a link, not a folder, or cannot be examined")
            return None
        try:
            record = hs.read_json(os.path.join(base, CONTEXT_RECORD), None)
        except hs.HostStateError:
            unusable("its record of which folder it belongs to cannot be read")
            return None
        if record is None:
            # Created, but its record never written or since lost. Nothing can
            # have been journaled without it, unless the record was lost.
            if strict and _journal_may_exist(base):
                unusable("it holds a record of an interrupted write but not of which folder "
                         "it belongs to")
            return None
        if _record_folder(record) != os.path.normcase(folder):
            unusable("it names another folder")
            return None
        return ContextState(folder, base)

    def known_contexts(self) -> List[str]:
        """The folders this computer has private state for. A folder may no
        longer exist."""
        return [folder for folder, _record in self._known_records()]

    def _known_records(self) -> List[Tuple[str, Dict[str, Any]]]:
        """Each folder this computer has private state for, with its record."""
        top = os.path.join(self._read_root(), CONTEXTS)
        found: List[Tuple[str, Dict[str, Any]]] = []
        if not os.path.isdir(top):
            return found
        for key in sorted(os.listdir(top)):
            try:
                record = hs.read_json(os.path.join(top, key, CONTEXT_RECORD), None)
            except hs.HostStateError:
                continue
            if isinstance(record, dict) and isinstance(record.get("folder"), str):
                found.append((record["folder"], record))
        return found

    # --- the Recent list ---

    def _cleared_recent(self) -> List[str]:
        """The folders the person cleared from Recent. A record that cannot be
        read clears nothing: Recent is a convenience, never a safeguard."""
        try:
            data = hs.read_json(os.path.join(self._read_root(), RECENT_CLEARED), None)
        except hs.HostStateError:
            return []
        folders = data.get("folders") if isinstance(data, dict) else None
        return [f for f in folders if isinstance(f, str)] if isinstance(folders, list) else []

    def _opened_recent(self) -> Dict[str, int]:
        """When each folder was last opened or created in the console, by its
        case-folded path, in nanoseconds. Unreadable, it orders nothing."""
        try:
            data = hs.read_json(os.path.join(self._read_root(), RECENT_OPENED), None)
        except hs.HostStateError:
            return {}
        opened = data.get("opened") if isinstance(data, dict) else None
        if not isinstance(opened, dict):
            return {}
        return {os.path.normcase(f): t for f, t in opened.items()
                if isinstance(f, str) and isinstance(t, int) and not isinstance(t, bool)}

    def recent_contexts(self) -> List[str]:
        """The folders opened or created in the console, and the legacy
        entries listed before Recent was limited to those, less any the person
        cleared since last opened; the most recently opened first, then any
        legacy entry never opened since, in its earlier order. A folder whose
        state was made under the console-only rule by anything but the console
        is not listed. Reading changes nothing: no entry is rewritten or
        removed."""
        cleared = {os.path.normcase(f) for f in self._cleared_recent()}
        opened = self._opened_recent()
        listed = [f for f, record in self._known_records()
                  if os.path.normcase(f) not in cleared
                  and (os.path.normcase(f) in opened or record.get(CONSOLE_RECENT) is not True)]
        return sorted(listed, key=lambda f: -opened.get(os.path.normcase(f), -1))

    def clear_recent(self) -> None:
        """Clear Recent. Only this one record changes: every Agent Context and
        its private state stay exactly as they are."""
        self.ensure()
        folders = sorted(set(self._cleared_recent()) | set(self.known_contexts()))
        hs.write_json_atomic(os.path.join(self._root, RECENT_CLEARED),
                             {"version": RECORD_VERSION, "folders": folders})

    def note_opened(self, folder: str) -> None:
        """The person opened or created `folder`: it heads Recent, listed again
        if it had been cleared. Only the two Recent records change."""
        folder = hs.canonical(folder)
        key = os.path.normcase(folder)
        self.ensure()
        opened = self._opened_recent()
        opened[key] = max([time.time_ns()] + [t + 1 for t in opened.values()])
        hs.write_json_atomic(os.path.join(self._root, RECENT_OPENED),
                             {"version": RECORD_VERSION, "opened": opened})
        cleared = self._cleared_recent()
        kept = [f for f in cleared if os.path.normcase(f) != key]
        if len(kept) != len(cleared):
            hs.write_json_atomic(os.path.join(self._root, RECENT_CLEARED),
                                 {"version": RECORD_VERSION, "folders": kept})

class ContextState:
    """The private state of one Agent Context folder."""

    def __init__(self, folder: str, base: str) -> None:
        self.folder = folder
        self.base = base

    def path(self, *parts: str) -> str:
        return os.path.join(self.base, *parts)

    def holds_records(self) -> bool:
        """Whether anything is kept here beyond the record that the folder was
        opened and its locks: settings, observations, candidates, archive,
        proposals, drafts or staging. True when that cannot be read."""
        try:
            for entry in os.scandir(self.base):
                if entry.name in (CONTEXT_RECORD, LOCKS):
                    continue
                if not entry.is_dir(follow_symlinks=False):
                    return True
                for _dirpath, dirs, files in os.walk(entry.path, onerror=_raise):
                    if files or any(os.path.islink(os.path.join(_dirpath, d)) for d in dirs):
                        return True
        except OSError:
            return True
        return False

    # --- candidates and archive ---

    def candidate_file(self, logical: str) -> str:
        return self.path(CANDIDATES, candidate_name(logical))

    def archive_file(self, name: str) -> str:
        problem = name_problem(name)
        if problem:
            raise PrivateStateError(problem)
        return self.path(ARCHIVE, name)

    def _markdown(self, sub: str) -> List[str]:
        folder = self.path(sub)
        if not os.path.isdir(folder):
            return []
        return sorted(n for n in os.listdir(folder)
                      if not name_problem(n) and os.path.isfile(os.path.join(folder, n))
                      and not os.path.islink(os.path.join(folder, n)))

    def _entries(self, sub: str) -> List[str]:
        folder = self.path(sub)
        if not os.path.isdir(folder):
            return []
        return os.listdir(folder)

    def candidates(self) -> List[str]:
        """Every candidate's logical path."""
        return [logical_candidate(n) for n in self._markdown(CANDIDATES)]

    def archived(self) -> List[str]:
        """Every archived document's name."""
        return self._markdown(ARCHIVE)

    def read_candidate(self, logical: str) -> Optional[str]:
        return _read_text(self.candidate_file(logical))

    def readable_candidates(self) -> Tuple[Dict[str, str], List[str]]:
        """Every candidate's text by logical path, and the logical paths of
        those whose file cannot be read as UTF-8 text. One such file never
        stops the others being read, and is never repaired, moved or removed;
        a candidate removed meanwhile is in neither."""
        texts: Dict[str, str] = {}
        unreadable: List[str] = []
        for logical in self.candidates():
            try:
                text = self.read_candidate(logical)
            except PrivateStateError:
                unreadable.append(logical)
                continue
            if text is not None:
                texts[logical] = text
        return texts, unreadable

    def unusable_candidate_files(self) -> List[str]:
        """The name of every entry among the candidates that cannot be one: a
        name no candidate may have, a folder, or a link. Names only — nothing
        is opened, followed or changed. Operating-system files such as
        `desktop.ini` are not listed."""
        folder = self.path(CANDIDATES)
        try:
            names = os.listdir(folder)
        except OSError:
            return []
        usable = set(self._markdown(CANDIDATES))
        return sorted(n for n in names if n not in usable and n.lower() not in _SYSTEM_FILES)

    def read_archived(self, name: str) -> Optional[str]:
        return _read_text(self.archive_file(name))

    def readable_archived(self) -> Tuple[Dict[str, str], List[str]]:
        """Every archived document's text by name, and the names of those whose
        file cannot be read as UTF-8 text, as `readable_candidates` does for
        candidates: set aside, never repaired, moved or removed."""
        texts: Dict[str, str] = {}
        unreadable: List[str] = []
        for name in self.archived():
            try:
                text = self.read_archived(name)
            except PrivateStateError:
                unreadable.append(name)
                continue
            if text is not None:
                texts[name] = text
        return texts, unreadable

    def taken_names(self, governing_paths: Iterable[str] = ()) -> set:
        """Every document file name taken by a governing document, a candidate
        or an archived document, letter case folded."""
        # Every entry among the candidates, usable or not, so that a new
        # candidate never lands on a folder, link or unreadable file.
        taken = {_fold(n) for n in self._entries(CANDIDATES)}
        taken |= {_fold(n) for n in self._markdown(ARCHIVE)}
        taken |= {_fold(p.rsplit("/", 1)[-1]) for p in governing_paths}
        return taken

    def name_in_use(self, name: str, governing_paths: Iterable[str] = ()) -> bool:
        """Whether a document file name is taken by a governing document, a
        candidate or an archived document, ignoring letter case, so that
        granting, withdrawing, replacing or retiring never collides."""
        return _fold(name) in self.taken_names(governing_paths)

    def new_candidate_path(self, slug: str, governing_paths: Iterable[str] = ()) -> str:
        """A new candidate's logical path with a name free everywhere: `untitled`
        when `slug` could never name one. PrivateStateError when every
        numbered name is taken (`free_name`)."""
        slug = (slug or "untitled")[:MAX_NAME - 8]
        if name_problem(f"{slug}.md"):
            slug = "untitled"
        return logical_candidate(free_name(slug, self.taken_names(governing_paths)))

    # --- the last observed context ---

    def observed(self) -> Optional[Dict[str, Any]]:
        """What Charter last saw or wrote, or None."""
        try:
            data = hs.read_json(self.path(OBSERVED), None)
        except hs.HostStateError:
            return None
        if not isinstance(data, dict) or not isinstance(data.get("fingerprint"), str)                 or not isinstance(data.get("sha256"), dict)                 or data.get("source") not in OBSERVED_SOURCES                 or not isinstance(data.get("outside"), list):
            return None
        return data

    def record_observed(self, fingerprint: str, hashes: Dict[str, str], source: str,
                        outside: Iterable[str] = ()) -> None:
        """Remember the context as Charter now sees it.

        `source` is `charter` when an authority action, Create or a settings change
        produced it; `rebuild` when Rebuild Agent Context regenerated the map
        and metadata over changes made outside; `seen` when the person
        acknowledged a change made outside. `outside` names the paths changed
        outside Charter that the person has not acknowledged."""
        if source not in OBSERVED_SOURCES:
            raise ValueError(source)
        hs.write_json_atomic(self.path(OBSERVED), {
            "version": RECORD_VERSION, "fingerprint": fingerprint,
            "sha256": dict(sorted(hashes.items())), "source": source,
            "outside": sorted(set(outside))})

    # --- the last valid settings ---

    def last_settings(self) -> Optional[Dict[str, Any]]:
        """The project name and guidance settings of the last valid Agent
        Context seen here, or None. Offered, never applied, when the metadata
        that records them is lost."""
        try:
            data = hs.read_json(self.path(LAST_SETTINGS), None)
        except hs.HostStateError:
            return None
        if not isinstance(data, dict):
            return None
        from . import agent_context as ac
        guidance = data.get("agent_guidance")
        if not isinstance(guidance, dict) or set(guidance) != set(ac.GUIDANCE_IDS):
            return None
        try:
            settings = ac.Settings.make(data.get("project_name"), guidance)
        except (ValueError, TypeError):
            return None
        return {"project_name": settings.project_name, "agent_guidance": settings.guidance_map}

    def remember_settings(self, project_name: str, agent_guidance: Dict[str, bool]) -> None:
        if self.last_settings() == {"project_name": project_name,
                                    "agent_guidance": dict(agent_guidance)}:
            return
        hs.write_json_atomic(self.path(LAST_SETTINGS), {
            "version": RECORD_VERSION, "project_name": project_name,
            "agent_guidance": dict(agent_guidance)})

    # --- locks and staging ---

    @contextlib.contextmanager
    def lock(self, kind: str, timeout: float = LOCK_TIMEOUT) -> Iterator[bool]:
        """Hold the `kind` lock (`writer`, `intake`, ...) for this context."""
        if not re.match(r"^[a-z][a-z-]*$", kind):
            raise ValueError(kind)
        with hs.file_lock(self.path(LOCKS, f"{kind}.lock"), timeout) as held:
            yield held

    def staging_dir(self, kind: str) -> str:
        """A staging folder for one kind of write. Callers hold the matching
        lock while they use it."""
        if not re.match(r"^[a-z][a-z-]*$", kind):
            raise ValueError(kind)
        folder = self.path(STAGING, kind)
        os.makedirs(folder, mode=0o700, exist_ok=True)
        return folder


def _raise(exc: OSError) -> None:
    raise exc


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return None
    except OSError:
        raise PrivateStateError("A private document could not be read.")
    try:
        return raw.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        raise PrivateStateError("A private document is not UTF-8 text.")


def default() -> PrivateState:
    return PrivateState.default()
