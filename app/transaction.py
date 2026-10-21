"""One all-or-nothing write across an Agent Context folder and its private state.

Product Specification §3.3: a context-changing action leaves the Agent Context
internally consistent or rolls back its own writes. This module is how.

  * Every file to replace or remove is first copied to a backup in private
    state, and every temporary file, backup, folder to create and folder to
    remove is recorded in a durable journal in private state, before anything
    in the Agent Context folder changes.
  * A write may say what its target must hold — the text the plan was built
    from, or nothing for a file the plan creates. A target that no longer
    matches is refused before anything is written, and again immediately
    before it is replaced or removed, so a change made meanwhile by a person
    or another program is never overwritten.
  * New content is written to a temporary file beside its target, under the
    reserved name `.charter-txn-<id>-<n>`, flushed, and then renamed over the
    target, so each file is replaced whole. Before anything is written, every
    temporary, backup and journal path is checked against the platform's path
    limit; an action that could not write safely is refused up front.
  * On any failure the journal rolls the writes back in this process. If the
    process dies instead, the journal survives, and `recover` rolls the
    interrupted transaction back before Charter writes again.
  * Rollback deletes only the temporary files and backups its own journal
    names, and restores a file only while it still holds exactly what this
    transaction wrote. Anything else it finds is left untouched: it may be a
    person's change. Without the journal nothing is guessed, cleaned up or
    overwritten; a leftover temporary file is a stray, and agents are refused
    until a person deals with it.
  * A journal is private state, but recovery treats it as untrusted: every
    path, name and identifier in it must have exactly the shape this module
    writes, lie inside the Agent Context or this context's private state, and
    reach there through plain folders — no link, junction or other reparse
    point — checked before anything is done and again immediately before each
    step. A journal that fails any check is refused whole: nothing is touched,
    and agents stay refused until a person deals with it.

A direct reader may see some files replaced and not others while a transaction
runs; `agent_context.examine` then reports a hash mismatch or a stray, so MCP
refuses the context until the transaction finishes or is rolled back.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from . import agent_context as ac
from . import host_state as hs
from . import private_store as ps
from .private_store import STAGING as ps_STAGING, ContextState

JOURNAL_KIND = "journal"
JOURNAL_FILE = "journal.json"
BACKUPS = "backups"
JOURNAL_VERSION = 1

CONTEXT = "context"
PRIVATE = "private"

# A write's `expected` for a target the plan creates: it must not exist.
ABSENT = "absent"

# Bounds on what recovery will read from a journal. A transaction writes one
# entry per changed file; no real action comes near these.
MAX_ENTRIES = 10000
MAX_JOURNAL_BYTES = 16 * 1024 * 1024

_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class TransactionError(RuntimeError):
    """A transaction did not apply. `restored` says whether everything it
    touched is as it was; `unrestored` names what is not; `concurrent` names
    targets that changed meanwhile, which it did not write."""

    def __init__(self, message: str, restored: bool = True,
                 unrestored: Optional[List[str]] = None,
                 concurrent: Optional[List[str]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.restored = restored
        self.unrestored = unrestored or []
        self.concurrent = concurrent or []


class ConcurrentChange(TransactionError):
    """A target no longer holds what the plan was built from."""

    def __init__(self, paths: List[str]) -> None:
        super().__init__("`" + "`, `".join(paths) + "` changed while Charter was writing, so "
                         "Charter did not overwrite it", concurrent=list(paths))


class _Unsafe(TransactionError):
    """A path is not where, or not what, the journal's shape promises."""

    def __init__(self, why: str) -> None:
        super().__init__(why, restored=False)


@dataclass
class Write:
    """One file to write (`text`) or remove (`text is None`). `path` is
    relative to its root, with forward slashes. `expected`, when given, is
    what the target must hold before it is replaced or removed: `expect()` of
    the text the plan was built from, or ABSENT for a file the plan creates."""
    root: str
    path: str
    text: Optional[str]
    expected: Optional[str] = None


def expect(text: Optional[str]) -> str:
    """The `expected` value for a target the plan saw holding `text`, or
    missing when `text` is None. Line endings are ignored, as every context
    hash ignores them."""
    return ABSENT if text is None else ac.sha256_text(text)


def _matches(data: Optional[bytes], expected: str) -> bool:
    if expected == ABSENT:
        return data is None
    if data is None:
        return False
    try:
        return ac.sha256_text(data.decode("utf-8")) == expected
    except UnicodeDecodeError:
        return False


def _sha(data: Optional[bytes]) -> Optional[str]:
    return None if data is None else hashlib.sha256(data).hexdigest()


def _plain_file(st: os.stat_result) -> bool:
    return stat.S_ISREG(st.st_mode) and not getattr(st, "st_file_attributes", 0) & _REPARSE


def _plain_dir(st: os.stat_result) -> bool:
    return stat.S_ISDIR(st.st_mode) and not getattr(st, "st_file_attributes", 0) & _REPARSE


def _read(path: str) -> Optional[bytes]:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if not _plain_file(st):
        raise TransactionError("A file to be written is not a regular file.")
    fd = os.open(path, os.O_RDONLY | _O_BINARY | _O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        if (opened.st_ino, opened.st_dev) != (st.st_ino, st.st_dev):
            raise TransactionError("A file to be written changed while it was read.")
        chunks = []
        while True:
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _write_new(path: str, data: bytes) -> None:
    """Create `path` (which must not exist) holding `data`, flushed."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY, 0o644)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)


def path_limit() -> int:
    """The longest absolute path this process can create. Windows allows 259
    characters unless long paths are enabled for the system."""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SYSTEM\CurrentControlSet\Control\FileSystem") as key:
                if winreg.QueryValueEx(key, "LongPathsEnabled")[0] == 1:
                    return 32766
        except OSError:
            pass
        return 259
    try:
        return int(os.pathconf("/", "PC_PATH_MAX")) - 1
    except (OSError, ValueError, AttributeError):
        return 4095


def dir_limit() -> int:
    """The longest folder path this process can create: Windows keeps twelve
    characters of a short path in reserve for a folder's own files."""
    limit = path_limit()
    return limit - 12 if os.name == "nt" and limit == 259 else limit


def _temp_name(txid: str, n: int, restore: bool = False) -> str:
    return f"{ac.TRANSACTION_PREFIX}{txid}-{n}{'r' if restore else ''}"


# Longest name `host_state.write_json_atomic` gives the journal's temporary file.
_JOURNAL_TEMP = f".{JOURNAL_FILE}.{'9' * 10}.{'f' * 32}.tmp"
_TXID_LENGTH = 6


def path_problems(cs: ContextState, writes: List["Write"]) -> List[str]:
    """Why these writes could not be made safely within the platform's path
    limit, worded for the person, or []. Checked before anything is written."""
    limit = path_limit()
    roots = {CONTEXT: cs.folder, PRIVATE: cs.base}
    jdir = cs.path(ps_STAGING, JOURNAL_KIND)
    worst_id = "f" * _TXID_LENGTH
    problems: List[str] = []
    private_paths = [os.path.join(jdir, _JOURNAL_TEMP)]
    for n, w in enumerate(writes):
        target = os.path.join(roots.get(w.root, cs.base), *w.path.split("/"))
        temp = os.path.join(os.path.dirname(target), _temp_name(worst_id, n, restore=True))
        private_paths.append(os.path.join(jdir, BACKUPS, worst_id, str(n)))
        longest = max(len(target), len(temp))
        new_dir = "" if os.path.isdir(os.path.dirname(target)) else os.path.dirname(target)
        if new_dir and len(new_dir) > dir_limit() and w.root == CONTEXT:
            problems.append(
                f"The Agent Context's folder path is too long for Charter to create "
                f"the folder for `{w.path}`: it would need {len(new_dir)} characters, and this "
                f"system allows {dir_limit()} for a folder. Move the Agent Context to a folder "
                "with a shorter path" + (", or enable long paths in Windows."
                                         if os.name == "nt" else "."))
        elif longest > limit and w.root == CONTEXT:
            problems.append(
                f"The Agent Context's folder path is too long for Charter to write "
                f"`{w.path}` safely: its temporary file would need {longest} characters, and "
                f"this system allows {limit}. Move the Agent Context to a folder with a shorter "
                "path" + (", or enable long paths in Windows." if os.name == "nt" else "."))
        elif longest > limit:
            private_paths.append(temp)
    if any(len(p) > limit for p in private_paths):
        problems.append("Charter's private state path is too long for this system "
                        f"to write safely (it allows {limit} characters).")
    return problems


# --- what may be written, and what a journal may name --------------------------------------

# Names Windows treats as devices, whatever follows the first dot.
_DEVICE = re.compile(r"^(con|prn|aux|nul|conin\$|conout\$|com[0-9¹²³]"
                     r"|lpt[0-9¹²³])$", re.IGNORECASE)


def _component_problem(part: str) -> bool:
    """Whether one path component is not a plain name: empty, `.` or `..`, a
    separator or control character, or — on Windows, where they alias other
    files or devices — an alternate data stream (`:`), a wildcard or reserved
    character, a trailing dot or space, or a device name."""
    if part in ("", ".", "..") or "/" in part or "\\" in part:
        return True
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in part):
        return True
    if os.name == "nt":
        if any(ch in ':<>"|?*' for ch in part) or part != part.rstrip(" ."):
            return True
        if _DEVICE.match(part.split(".", 1)[0].rstrip(" ")):
            return True
    return False


def _plain_relative(rel: Any) -> bool:
    return isinstance(rel, str) and not hs.escapes_relative(rel) \
        and not any(_component_problem(p) for p in rel.split("/"))


def _allowed_context_path(rel: str) -> bool:
    """Charter writes only the generated files and governing
    Markdown under `authoritative/`. The shared `host_state.escapes_relative`
    rejects anything absolute, traversing or malformed; the allow-list below is
    what remains writable."""
    if not _plain_relative(rel):
        return False
    parts = rel.split("/")
    if rel in ac.GENERATED:
        return True
    return parts[0] == ac.AUTHORITATIVE and len(parts) > 1 and \
        parts[-1].lower().endswith(ac.DOCUMENT_SUFFIXES) and \
        not parts[-1].startswith(ac.TRANSACTION_PREFIXES)


_RECORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json$")
_RECORD_FOLDER = re.compile(r"^[a-z][a-z-]{0,31}$")


def _allowed_private_path(rel: str) -> bool:
    """The private records an action writes, and nothing else: a candidate or
    archived document by its document name, a candidate's baseline, a change
    set's record, or an Agent Proposal record in one of its decision folders.
    Never `context.json`,
    staging, locks, observations or anything another folder's state holds."""
    if not _plain_relative(rel):
        return False
    parts = rel.split("/")
    if len(parts) == 2 and parts[0] in (ps.CANDIDATES, ps.ARCHIVE):
        return not ps.name_problem(parts[1])
    if len(parts) == 2 and parts[0] == ps.CHANGESETS:
        return bool(_RECORD.match(parts[1]))
    if len(parts) == 2 and parts[0] == ps.BASELINES:
        # A candidate's baseline, by the candidate's own document name.
        return parts[1].endswith(".json") and not ps.name_problem(parts[1][:-len(".json")])
    if len(parts) == 3 and parts[0] == ps.PROPOSALS:
        return bool(_RECORD_FOLDER.match(parts[1]) and _RECORD.match(parts[2]))
    return False


def _allowed(root: Any, rel: Any) -> bool:
    if root == CONTEXT:
        return isinstance(rel, str) and _allowed_context_path(rel)
    if root == PRIVATE:
        return isinstance(rel, str) and _allowed_private_path(rel)
    return False


# --- guarded filesystem steps -----------------------------------------------------------------

def _contained(root: str, rel_parts: List[str]) -> str:
    """The absolute path of `rel_parts` under `root`, after checking that
    `root` and every folder on the way that exists is a plain folder — not a
    link, junction or other reparse point — and that the parent canonically
    lies inside `root`. Called before acting and again immediately before each
    step, so a folder swapped for a link meanwhile is caught."""
    try:
        st = os.lstat(root)
    except OSError:
        raise _Unsafe("a folder it names is not there")
    if not _plain_dir(st):
        raise _Unsafe("a folder it names is a link or not a folder")
    probe = root
    for part in rel_parts[:-1]:
        probe = os.path.join(probe, part)
        try:
            st = os.lstat(probe)
        except FileNotFoundError:
            break  # the rest of the way does not exist yet
        except OSError:
            raise _Unsafe("a folder it names cannot be examined")
        if not _plain_dir(st):
            raise _Unsafe("a folder it names is a link or not a folder")
    path = os.path.join(root, *rel_parts)
    if not hs.inside(os.path.dirname(path), root):
        raise _Unsafe("a file it names is outside the folder it belongs to")
    return path


def _remove_file(root: str, rel_parts: List[str]) -> Optional[str]:
    """Remove the plain file at `rel_parts` under `root`, if there is one.
    Returns None when removed or absent, or why it was left."""
    path = _contained(root, rel_parts)
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    if not _plain_file(st):
        return "not a plain file"
    os.remove(path)
    return None


def _plain_dirs(base: str, *chain: str) -> bool:
    """Whether each folder of `chain` under `base` is absent or a plain
    folder: True when all exist and are plain, False when one is absent.
    Raises _Unsafe for anything else."""
    probe = base
    for part in ("",) + chain:
        probe = os.path.join(probe, part) if part else probe
        try:
            st = os.lstat(probe)
        except FileNotFoundError:
            return False
        except OSError:
            raise _Unsafe("Charter's private staging folder cannot be examined")
        if not _plain_dir(st):
            raise _Unsafe("Charter's private staging folder is a link or not a folder")
    return True


_BACKUP_FILE = re.compile(r"^(0|[1-9][0-9]{0,4})$")
_TXID = re.compile(r"^[0-9a-f]{6,32}$")


def _clear_backups(jdir: str, txid: str) -> List[str]:
    """Remove one transaction's backups: only plain files named as this module
    names them, then the folder if that leaves it empty. Anything else is left
    where it is and named."""
    left: List[str] = []
    try:
        if not _TXID.match(txid) or not _plain_dirs(jdir, BACKUPS, txid):
            return left
        folder = os.path.join(jdir, BACKUPS, txid)
        for name in os.listdir(folder):
            path = os.path.join(folder, name)
            st = os.lstat(path)
            if _BACKUP_FILE.match(name) and _plain_file(st):
                os.remove(path)
            else:
                left.append(f"{BACKUPS}/{txid}/{name}")
        if not left:
            os.rmdir(folder)
    except (OSError, TransactionError):
        left.append(f"{BACKUPS}/{txid}")
    return left


def _clear_orphan_backups(jdir: str) -> List[str]:
    """Backups no journal names were never referenced by one: the process
    stopped before journaling, and nothing in the folder changed. Only
    transaction folders and backup files of the shape this module writes are
    removed; anything else is left."""
    left: List[str] = []
    try:
        if not _plain_dirs(jdir, BACKUPS):
            return left
        for name in os.listdir(os.path.join(jdir, BACKUPS)):
            if _TXID.match(name):
                left += _clear_backups(jdir, name)
            else:
                left.append(f"{BACKUPS}/{name}")
    except (OSError, TransactionError):
        left.append(BACKUPS)
    return left


class Transaction:
    """Apply `writes` atomically. `validate`, when given, runs after every
    write and before the transaction is final; raising rolls it back.
    `precondition`, when given, runs after the temporary files are written and
    immediately before the first file is replaced or removed; raising —
    `ConcurrentChange` for something changed meanwhile — rolls it back with
    nothing in the folder replaced.

    `fault`, for tests only, is called with a step name before each step; an
    exception it raises that is not an `Exception` simulates the process dying
    there, leaving the journal for `recover`.

    After `run`, `follow_up` lists anything that went wrong once the
    transaction was final, worded for the person; it never undoes it."""

    def __init__(self, cs: ContextState, writes: List[Write],
                 validate: Optional[Callable[[], None]] = None,
                 fault: Optional[Callable[[str], None]] = None,
                 precondition: Optional[Callable[[], None]] = None) -> None:
        self.cs = cs
        self.writes = writes
        self.validate = validate
        self.precondition = precondition
        self.fault = fault or (lambda _step: None)
        self.roots = {CONTEXT: cs.folder, PRIVATE: cs.base}
        self.follow_up: List[str] = []

    # --- locations ---

    def _abs(self, root: str, rel: str) -> str:
        return os.path.join(self.roots[root], *rel.split("/"))

    def _check(self, w: Write) -> None:
        if w.root == CONTEXT:
            if not _allowed_context_path(w.path):
                raise TransactionError(f"`{w.path}` is not a file Charter writes.")
        elif w.root == PRIVATE:
            target = self._abs(PRIVATE, w.path)
            if not _allowed_private_path(w.path) or not hs.inside(target, self.cs.base):
                raise TransactionError("A private write is outside this context's private state.")
        else:
            raise TransactionError("Unknown write location.")

    def _missing_dirs(self, root: str, rel: str) -> List[str]:
        """Folders above `rel` that do not exist yet, outermost first."""
        parts = rel.split("/")[:-1]
        out = []
        for i in range(1, len(parts) + 1):
            sub = "/".join(parts[:i])
            if not os.path.isdir(self._abs(root, sub)):
                out.append(sub)
        return out

    def _emptied_dirs(self, removed: List[str]) -> List[str]:
        """Subfolders of `authoritative/` that removing `removed` leaves with
        nothing in them, innermost first. An empty subfolder would be a stray;
        `authoritative/` itself may be empty. A folder that still holds
        anything, even a tolerated system file, is left alone."""
        gone = {os.path.normcase(self._abs(CONTEXT, rel)) for rel in removed}
        subs = set()
        for rel in removed:
            parts = rel.split("/")[:-1]
            for i in range(2, len(parts) + 1):
                subs.add("/".join(parts[:i]))
        pruned: List[str] = []
        for sub in sorted(subs, key=lambda s: (-s.count("/"), s)):
            folder = self._abs(CONTEXT, sub)
            try:
                names = os.listdir(folder)
            except OSError:
                continue
            left = [n for n in names
                    if os.path.normcase(os.path.join(folder, n)) not in gone
                    and f"{sub}/{n}" not in pruned]
            if not left:
                pruned.append(sub)
        return pruned

    # --- the journal ---

    def _journal_dir(self) -> str:
        _plain_dirs(self.cs.base, ps_STAGING, JOURNAL_KIND)
        return self.cs.staging_dir(JOURNAL_KIND)

    def _unchanged(self, e: Dict[str, Any]) -> None:
        """Immediately before `e`'s target is replaced or removed: it must
        still hold exactly what was backed up, through plain folders."""
        target = _contained(self.roots[e["root"]], e["path"].split("/"))
        try:
            current = _sha(_read(target))
        except (TransactionError, OSError):
            current = "unreadable"
        if current != e["old"]:
            raise ConcurrentChange([e["path"]])

    def run(self) -> None:
        for w in self.writes:
            self._check(w)
        problems = path_problems(self.cs, self.writes)
        if problems:
            raise TransactionError(" ".join(problems))
        try:
            jdir = self._journal_dir()
        except _Unsafe as exc:
            raise TransactionError(f"Charter did not write anything: {exc.message}.")
        txid = uuid.uuid4().hex[:_TXID_LENGTH]
        backup_dir = os.path.join(jdir, BACKUPS, txid)
        os.makedirs(backup_dir, mode=0o700, exist_ok=True)

        entries: List[Dict[str, Any]] = []
        created: List[List[str]] = []
        changed: List[str] = []
        try:
            for n, w in enumerate(self.writes):
                target = self._abs(w.root, w.path)
                old = _read(target)
                if w.expected is not None and not _matches(old, w.expected):
                    changed.append(w.path)
                    continue
                new = None if w.text is None else w.text.encode("utf-8")
                if old == new:
                    continue
                if new is None and old is None:
                    continue
                entry: Dict[str, Any] = {"root": w.root, "path": w.path, "old": _sha(old),
                                         "new": _sha(new),
                                         "temp": _temp_name(txid, n),
                                         "restore_temp": _temp_name(txid, n, restore=True),
                                         "backup": None}
                if old is not None:
                    backup = os.path.join(backup_dir, str(n))
                    _write_new(backup, old)
                    entry["backup"] = os.path.relpath(backup, jdir).replace("\\", "/")
                for sub in self._missing_dirs(w.root, w.path):
                    if [w.root, sub] not in created:
                        created.append([w.root, sub])
                entries.append(entry)
        except BaseException:
            _clear_backups(jdir, txid)
            raise
        if changed:
            # Refused before anything was written: nothing to roll back.
            _clear_backups(jdir, txid)
            raise ConcurrentChange(changed)
        if not entries:
            _clear_backups(jdir, txid)
            return
        removed = [e["path"] for e in entries if e["root"] == CONTEXT and e["new"] is None]
        pruned = self._emptied_dirs(removed)
        journal = {"version": JOURNAL_VERSION, "id": txid, "entries": entries,
                   "created_dirs": created, "pruned_dirs": pruned}
        self.fault("before-journal")
        hs.write_json_atomic(os.path.join(jdir, JOURNAL_FILE), journal)

        try:
            self.fault("after-journal")
            for root, sub in created:
                _contained(self.roots[root], sub.split("/") + ["-"])
                os.makedirs(self._abs(root, sub), exist_ok=True)
            for e, w in self._pairs(entries):
                if w.text is not None:
                    _contained(self.roots[e["root"]], e["path"].split("/"))
                    _write_new(self._sibling(e, "temp"), w.text.encode("utf-8"))
                    self.fault(f"temp:{e['path']}")
            # Nothing has been replaced yet. Every target must still be what
            # was backed up, and whatever else the caller relies on unchanged.
            for e in entries:
                self._unchanged(e)
            if self.precondition:
                self.precondition()
            for e, w in self._pairs(entries):
                self._unchanged(e)
                target = self._abs(e["root"], e["path"])
                if w.text is None:
                    os.remove(target)
                else:
                    os.replace(self._sibling(e, "temp"), target)
                self.fault(f"replace:{e['path']}")
            for sub in pruned:
                _contained(self.cs.folder, sub.split("/") + ["-"])
                os.rmdir(self._abs(CONTEXT, sub))
            self.fault("before-validate")
            if self.validate:
                self.validate()
            self.fault("before-commit")
            # Final: once the journal is gone, the transaction cannot roll back.
            os.remove(os.path.join(jdir, JOURNAL_FILE))
        except Exception as exc:
            concurrent = list(getattr(exc, "concurrent", []) or [])
            message = getattr(exc, "message", "") or str(exc) or exc.__class__.__name__
            try:
                unrestored = rollback(self.cs, journal, untouched=concurrent)
            except (TransactionError, OSError) as stop:
                why = getattr(stop, "message", "") or getattr(stop, "strerror", "") or str(stop)
                raise TransactionError(
                    f"{message}; Charter then stopped undoing its own writes because {why}. "
                    "Its record of the write is kept, so agents are refused until the Agent "
                    "Context is opened in Charter again", restored=False, concurrent=concurrent)
            raise TransactionError(message, restored=not unrestored, unrestored=unrestored,
                                   concurrent=concurrent)
        try:
            self.fault("after-commit")
            left = _clear_backups(jdir, txid)
            if left:
                self.follow_up.append("Charter could not remove its private backup of the "
                                      "files this action replaced. It is not needed and does "
                                      "not affect the Agent Context.")
        except Exception:  # noqa: BLE001 — the transaction is final; never report it as failed
            self.follow_up.append("Charter could not finish tidying its private copy of the "
                                  "files this action replaced. The Agent Context is not "
                                  "affected.")

    def _pairs(self, entries: List[Dict[str, Any]]):
        by_key = {(w.root, w.path): w for w in self.writes}
        return [(e, by_key[(e["root"], e["path"])]) for e in entries]

    def _sibling(self, entry: Dict[str, Any], which: str) -> str:
        target = self._abs(entry["root"], entry["path"])
        return os.path.join(os.path.dirname(target), entry[which])


def rollback(cs: ContextState, journal: Dict[str, Any],
             untouched: Iterable[str] = ()) -> List[str]:
    """Undo what `journal` describes, as far as is safe. Returns the paths
    left as they are because they no longer hold what the transaction wrote.
    Removes the journal and its backups when done. `untouched` names targets
    this process knows it never wrote, which are left alone and not reported.

    Every step checks its path again first (`_contained`). A path that is no
    longer safe stops rollback with `_Unsafe`, keeping the journal, so nothing
    is done through a link and the write stays known to be interrupted."""
    roots = {CONTEXT: cs.folder, PRIVATE: cs.base}
    jdir = cs.path(ps_STAGING, JOURNAL_KIND)
    unrestored: List[str] = []
    skip = set(untouched)

    def parts(rel: str) -> List[str]:
        return rel.split("/")

    entries = journal.get("entries", [])
    for e in entries:
        folder = parts(e["path"])[:-1]
        for which in ("temp", "restore_temp"):
            why = _remove_file(roots[e["root"]], folder + [e[which]])
            if why:
                unrestored.append("/".join(folder + [e[which]]))
    for sub in journal.get("pruned_dirs", []):
        _contained(cs.folder, parts(sub) + ["-"])
        os.makedirs(os.path.join(cs.folder, *parts(sub)), exist_ok=True)
    for e in reversed(entries):
        if e["path"] in skip:
            continue
        root = roots[e["root"]]
        target = _contained(root, parts(e["path"]))
        try:
            current = _sha(_read(target))
        except TransactionError:
            unrestored.append(e["path"])
            continue
        if current == e["old"]:
            continue  # never changed, or already restored
        if current != e["new"]:
            unrestored.append(e["path"])  # changed by someone else: leave it
            continue
        if e["old"] is None:
            why = _remove_file(root, parts(e["path"]))
            if why:
                unrestored.append(e["path"])
            continue
        backup = _contained(jdir, parts(e["backup"]))
        try:
            data = _read(backup)
        except TransactionError:
            data = None
        if data is None or _sha(data) != e["old"]:
            unrestored.append(e["path"])
            continue
        _contained(root, parts(e["path"]))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        temp = os.path.join(os.path.dirname(target), e["restore_temp"])
        _write_new(temp, data)
        _contained(root, parts(e["path"]))
        os.replace(temp, target)
    for root, sub in reversed(journal.get("created_dirs", [])):
        folder = _contained(roots[root], parts(sub) + ["-"])
        path = os.path.dirname(folder)
        try:
            if _plain_dir(os.lstat(path)):
                os.rmdir(path)
        except OSError:
            pass  # not empty, or already gone: leave it
    try:
        _remove_file(jdir, [JOURNAL_FILE])
    except FileNotFoundError:
        pass
    _clear_backups(jdir, str(journal.get("id", "")))
    return unrestored


def _reserved_temp(name: str) -> bool:
    return name.startswith(ac.TRANSACTION_PREFIXES) and os.path.basename(name) == name \
        and "/" not in name and "\\" not in name and name not in (".", "..")


_ENTRY_KEYS = {"root", "path", "old", "new", "temp", "restore_temp", "backup"}
_JOURNAL_KEYS = {"version", "id", "entries", "created_dirs", "pruned_dirs"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _temp_index(name: Any, txid: str, restore: bool) -> Optional[int]:
    """The write index `name` encodes, when it is exactly a reserved
    temporary name of transaction `txid`, Charter's or the one its earlier
    name, Agent Context Manager, used; otherwise None."""
    if not isinstance(name, str) or not _reserved_temp(name):
        return None
    for prefix in ac.TRANSACTION_PREFIXES:
        m = re.match(re.escape(prefix) + re.escape(txid) + r"-(0|[1-9][0-9]{0,4})" +
                     ("r" if restore else "") + r"$", name)
        if m:
            return int(m.group(1))
    return None


def _proper_ancestor(sub: Any, paths: List[str]) -> bool:
    """Whether `sub` is a folder strictly above one of `paths`."""
    if not _plain_relative(sub):
        return False
    return any(p.startswith(sub + "/") for p in paths)


def journal_problem(journal: Any) -> str:
    """Why an interrupted-write record is not exactly the shape `run` writes,
    or "". Everything is checked before recovery does anything: the version
    and id; each entry's root, an allowed path inside it, hashes, its
    temporary and restore names, which must be this transaction's reserved
    names for one write index, and its backup name, which must be exactly
    the one that index is given; no duplicates; folders to create or recreate
    only above the entry paths they serve; and bounded sizes."""
    if not isinstance(journal, dict) or set(journal) - _JOURNAL_KEYS:
        return "it is not a record Charter writes"
    if type(journal.get("version")) is not int or journal["version"] != JOURNAL_VERSION:
        return "it is from a version Charter does not know"
    txid = journal.get("id")
    if not isinstance(txid, str) or not _TXID.match(txid):
        return "its identifier is not one Charter writes"
    entries = journal.get("entries")
    if not isinstance(entries, list) or not entries or len(entries) > MAX_ENTRIES:
        return "its list of files is missing, empty or too long"
    seen_paths, seen_index = set(), set()
    for e in entries:
        if not isinstance(e, dict) or set(e) != _ENTRY_KEYS:
            return "a file entry is not shaped as Charter writes it"
        if not _allowed(e["root"], e["path"]):
            return "a file entry names a file Charter never writes"
        key = (e["root"], os.path.normcase(e["path"]).casefold())
        if key in seen_paths:
            return "a file is named twice"
        seen_paths.add(key)
        if not all(v is None or (isinstance(v, str) and _SHA256.match(v))
                   for v in (e["old"], e["new"])) or e["old"] == e["new"]:
            return "a file entry's content record is not one Charter writes"
        n = _temp_index(e["temp"], txid, restore=False)
        if n is None or n >= MAX_ENTRIES or _temp_index(e["restore_temp"], txid, restore=True) != n:
            return "a temporary file name is not one Charter writes"
        if n in seen_index:
            return "a temporary file is named twice"
        seen_index.add(n)
        expected_backup = None if e["old"] is None else f"{BACKUPS}/{txid}/{n}"
        if e["backup"] != expected_backup:
            return "a backup name is not one Charter writes"
    by_root: Dict[str, List[str]] = {CONTEXT: [], PRIVATE: []}
    for e in entries:
        by_root[e["root"]].append(e["path"])
    removed = [e["path"] for e in entries if e["root"] == CONTEXT and e["new"] is None]
    created = journal.get("created_dirs", [])
    if not isinstance(created, list) or len(created) > MAX_ENTRIES:
        return "its list of folders is not one Charter writes"
    seen_dirs = set()
    for item in created:
        if not isinstance(item, list) or len(item) != 2 or item[0] not in (CONTEXT, PRIVATE) \
                or not _proper_ancestor(item[1], by_root[item[0]]):
            return "a folder it would remove is not one Charter creates"
        key = (item[0], os.path.normcase(item[1]))
        if key in seen_dirs:
            return "a folder is named twice"
        seen_dirs.add(key)
    pruned = journal.get("pruned_dirs", [])
    if not isinstance(pruned, list) or len(pruned) > MAX_ENTRIES \
            or len(set(map(str, pruned))) != len(pruned):
        return "its list of folders is not one Charter writes"
    for sub in pruned:
        if not _proper_ancestor(sub, removed) or not sub.startswith(ac.AUTHORITATIVE + "/"):
            return "a folder it would recreate is not one Charter removes"
    return ""


def _no_duplicate_keys(pairs: List[Tuple[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


_UNREAD = object()


def _load_journal(path: str) -> Any:
    """The journal at `path`: None when there is none, `_UNREAD` when it is
    not a plain file Charter could read and parse whole."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None
    except OSError:
        return _UNREAD
    if not _plain_file(st) or st.st_size > MAX_JOURNAL_BYTES:
        return _UNREAD
    try:
        raw = _read(path)
        if raw is None or len(raw) > MAX_JOURNAL_BYTES:
            return _UNREAD
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicate_keys,
                          parse_constant=hs._reject_nonfinite)
    except (OSError, ValueError, TransactionError, RecursionError):
        return _UNREAD


def journal_state(cs: ContextState) -> str:
    """`none` when no write to this context was interrupted; `present` when
    a journal is there; `unknown` when that cannot be established — the staging
    folders are links, not folders, or cannot be examined. Only looks: it
    creates nothing, not even the staging folder."""
    staging = cs.path(ps_STAGING)
    jdir = os.path.join(staging, JOURNAL_KIND)
    for folder in (cs.base, staging, jdir):
        try:
            st = os.lstat(folder)
        except FileNotFoundError:
            return "none"
        except OSError:
            return "unknown"
        if not _plain_dir(st):
            return "unknown"
    try:
        os.lstat(os.path.join(jdir, JOURNAL_FILE))
        return "present"
    except FileNotFoundError:
        pass
    except OSError:
        return "unknown"
    try:
        os.listdir(jdir)
    except OSError:
        return "unknown"
    return "none"


def interrupted(cs: ContextState) -> bool:
    """Whether a transaction on this context was interrupted and not yet
    recovered — or whether that cannot be established, which is treated the
    same. Its files may all be in place and valid; it will still be rolled
    back, so MCP refuses the context until it is. Only looks: it creates
    nothing, not even the staging folder."""
    return journal_state(cs) != "none"


def _refused(cs: ContextState, why: str) -> TransactionError:
    record = os.path.join(cs.path(ps_STAGING, JOURNAL_KIND), JOURNAL_FILE)
    return TransactionError(
        f"Charter's record of an interrupted write cannot be trusted ({why}), so it will not "
        "guess how to undo it, and changed nothing. Charter can’t serve this Agent Context until "
        "this is resolved. "
        "Check the Agent Context's files, delete any `.charter-txn-` or `.acm-txn-` file in it "
        f"yourself, and then remove the record, {record}.", restored=False)


def recover(cs: ContextState) -> Optional[Dict[str, Any]]:
    """Roll back a transaction an earlier process did not finish. Call while
    holding the writer lock, before writing. Returns what was done, or None
    when nothing was interrupted. Refuses, changing nothing, when the record
    of the write or any path it names cannot be trusted."""
    try:
        if not _plain_dirs(cs.base, ps_STAGING, JOURNAL_KIND):
            return None  # no staging folder: nothing was ever journaled
        jdir = cs.path(ps_STAGING, JOURNAL_KIND)
        journal = _load_journal(os.path.join(jdir, JOURNAL_FILE))
        if journal is None:
            if journal_state(cs) != "none":
                raise _Unsafe("its folder cannot be read")
            _clear_orphan_backups(jdir)
            return None
        if journal is _UNREAD:
            raise _Unsafe("it cannot be read")
        problem = journal_problem(journal)
        if problem:
            raise _Unsafe(problem)
        # Every path, before anything is done: inside its root, through plain
        # folders only. `rollback` checks each again immediately before acting.
        roots = {CONTEXT: cs.folder, PRIVATE: cs.base}
        for e in journal["entries"]:
            _contained(roots[e["root"]], e["path"].split("/"))
            if e["backup"]:
                _contained(jdir, e["backup"].split("/"))
        for root, sub in journal.get("created_dirs", []):
            _contained(roots[root], sub.split("/") + ["-"])
        for sub in journal.get("pruned_dirs", []):
            _contained(cs.folder, sub.split("/") + ["-"])
        unrestored = rollback(cs, journal)
    except _Unsafe as exc:
        raise _refused(cs, exc.message)
    except TransactionError:
        raise
    except OSError as exc:
        raise _refused(cs, f"it could not be undone: {exc.strerror or exc.__class__.__name__}")
    return {"transaction": journal.get("id"), "unrestored": unrestored}
