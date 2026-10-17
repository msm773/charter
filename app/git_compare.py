"""Optional, read-only comparison of an Agent Context against a Git base.

Coordinated Context Changes and Advisory Review: "Charter may use read-only Git
information to prepare a comparison against a base the person selects." It is
a command-line operation, `charter compare` (see `app.compare`), never part of
the ordinary console. When the Agent Context is inside a Git checkout, the
person may name a base
revision — a branch, tag or commit they choose — and Charter
compares the current, valid Agent Context with that base's Agent Context in
the same folder, and prepares advisory review material for the result.

Charter never chooses the base, and never creates, switches,
fetches, pulls, merges, rebases, commits, stages or otherwise alters Git. It
runs only the read-only commands in `allowed()`, each from the Agent Context
folder, and reads only that folder's subtree at the base: `ls-tree` lists the
subtree (`-- .` from the folder), and `cat-file` reads only the objects that
listing returned. Nothing outside the Agent Context is read or shown.

A comparison is advisory-review input only. It does not establish authority,
approve a merge, or make a change set current. Its review material identifies
the base by its context fingerprint alone: Charter adds no commit, branch,
revision text, local location or private state of its own, and embeds the
reviewed documents exactly as they read.
"""
from __future__ import annotations

import difflib
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from . import agent_context as ac
from . import host_state as hs
from . import impact
from . import manager as mg
from . import private_store as ps

COMPARISON_VERSION = "charter-base-comparison/1"

ADVISORY = ("Advisory review input only. A Git-base comparison does not establish authority, "
            "approve a merge, or make a change set current: a person still decides what governs, "
            "in this Agent Context.")
READ_ONLY = ("Charter only reads Git here, and only this Agent Context's folder at the "
             "base you name. It does not fetch, switch, merge, rebase, commit or change anything.")
DISCLOSURE = ("This review material includes the full text of the current governing documents and "
              "of the base versions of those changed or removed since the base. Sharing it shares "
              "that text with the service you choose. Charter adds no commit, branch, revision or "
              "local location of its own; the documents are included as they read. Charter sends "
              "nothing.")
# What a comparison's packet carries, for the Git-repository warning.
PACKET_CONTENTS = ("the current governing documents and the base versions the packet includes")

# Bounds on what one comparison reads.
MAX_FILES = 2000
MAX_BYTES = 32 * 1024 * 1024
TIMEOUT = 20

_HEX = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
# A revision as a person types it: a branch, tag, commit, or one with ~ ^ @{…}.
# No leading dash (never an option), no `:` (never a path), no spaces.
_REVISION = re.compile(r"[A-Za-z0-9@][A-Za-z0-9._/@{}~^+-]{0,199}")


class CompareError(ValueError):
    """A comparison that cannot be made, in words for the person."""


# --- the read-only Git allow-list ------------------------------------------------------

def valid_revision(text: Any) -> str:
    """The base revision as the person typed it, if it is one Charter
    will pass to Git; otherwise a refusal."""
    rev = text.strip() if isinstance(text, str) else ""
    if not rev:
        raise CompareError("Name the base to compare with: a branch, tag or commit.")
    if not _REVISION.fullmatch(rev) or ".." in rev or rev.endswith((".lock", "/", ".")):
        raise CompareError("That is not a revision Charter can look up. Give a branch, "
                           "tag or commit name, such as main.")
    return rev


def allowed(args: Sequence[str], oids: Optional[set] = None) -> bool:
    """Whether `git <args>` is one of the read-only commands a comparison may
    run. Every one is exact in shape: nothing else is ever run."""
    args = list(args)
    if args == ["rev-parse", "--is-inside-work-tree"]:
        return True
    if len(args) == 4 and args[:3] == ["rev-parse", "--verify", "--quiet"]:
        rev = args[3]
        if not rev.endswith("^{commit}"):
            return False
        try:
            valid_revision(rev[:-len("^{commit}")])
        except CompareError:
            return False
        return True
    if args == ["symbolic-ref", "--quiet", "HEAD"]:
        return True
    if len(args) == 3 and args[:2] == ["rev-parse", "--symbolic-full-name"]:
        try:
            valid_revision(args[2])
        except CompareError:
            return False
        return args[2] == args[2].strip()
    if len(args) == 6 and args[:3] == ["ls-tree", "-r", "-z"] and args[4:] == ["--", "."]:
        return bool(_HEX.fullmatch(args[3]))
    if len(args) == 3 and args[:2] == ["cat-file", "blob"]:
        return bool(_HEX.fullmatch(args[2])) and (oids is None or args[2] in oids)
    return False


def _git(folder: str, args: Sequence[str], oids: Optional[set] = None) -> Optional[bytes]:
    """Run one allowed read-only Git command from the Agent Context folder.
    None when Git fails or is not there."""
    if not allowed(args, oids):
        raise CompareError(f"Charter does not run `git {' '.join(args)}`.")
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0",
           "GIT_PAGER": "cat", "GIT_NO_REPLACE_OBJECTS": "1"}
    # The folder's own `.git/config` cannot run a program during a comparison:
    # no fsmonitor, hook, pager or protocol helper.
    safe = ["-c", "core.fsmonitor=false", "-c", f"core.hooksPath={os.devnull}",
            "-c", "protocol.ext.allow=never"]
    try:
        proc = subprocess.run(["git", *safe, "--no-optional-locks", "-C", folder, *args],
                              capture_output=True, env=env, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout if proc.returncode == 0 else None


def in_checkout(folder: str) -> bool:
    out = _git(folder, ["rev-parse", "--is-inside-work-tree"])
    return out is not None and out.strip() == b"true"


def _resolve(folder: str, rev: str) -> str:
    out = _git(folder, ["rev-parse", "--verify", "--quiet", rev + "^{commit}"])
    oid = (out or b"").decode("ascii", "replace").strip()
    if not _HEX.fullmatch(oid):
        raise CompareError(f"“{rev}” cannot be resolved to a commit in this checkout's history. "
                           "Check the name; Charter does not fetch.")
    return oid


def _escapes_folder(rel: str) -> bool:
    """Whether a path `git ls-tree` listed would leave the Agent Context folder
    if joined to it. Git refuses such trees on checkout, but it lists and reads
    the objects of a crafted or fetched tree verbatim, so every component is
    checked: the shared `host_state.escapes_relative` rejects an absolute, drive,
    backslash, control-character, empty, `.` or `..` path, and a colon in any
    component is rejected too (an NTFS alternate-data-stream name or a drive
    letter mid-path)."""
    return hs.escapes_relative(rel) or any(":" in part for part in rel.split("/"))


def _base_files(folder: str, commit: str) -> Dict[str, bytes]:
    """The Agent Context folder's files at `commit`, by path relative to it."""
    listing = _git(folder, ["ls-tree", "-r", "-z", commit, "--", "."])
    if listing is None:
        raise CompareError("That base's files are not available in this checkout's history, for "
                           "example in a shallow clone. Charter does not fetch.")
    entries = []
    for record in listing.split(b"\0"):
        if not record:
            continue
        meta, tab, path = record.partition(b"\t")
        fields = meta.decode("ascii", "replace").split(" ")
        if not tab or len(fields) != 3:
            raise CompareError("Git listed that base's files in a form Charter does not "
                               "recognise, so nothing was compared.")
        mode, kind, oid = fields
        rel = path.decode("utf-8", "replace")
        if _escapes_folder(rel):
            raise CompareError("Git listed a file outside this Agent Context, so nothing was read.")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise CompareError(f"At that base, `{rel}` is not an ordinary file (a link or a "
                               "submodule), so the base's Agent Context cannot be compared.")
        entries.append((rel, oid))
    if not entries:
        raise CompareError("That base has no files in this Agent Context's folder, so there is no "
                           "Agent Context there to compare with.")
    if len(entries) > MAX_FILES:
        raise CompareError("That base holds too many files in this folder to compare.")
    oids = {oid for _rel, oid in entries}
    files: Dict[str, bytes] = {}
    total = 0
    for rel, oid in entries:
        data = _git(folder, ["cat-file", "blob", oid], oids)
        if data is None:
            raise CompareError("That base's files are not available in this checkout's history, "
                               "for example in a shallow clone. Charter does not "
                               "fetch.")
        total += len(data)
        if total > MAX_BYTES:
            raise CompareError("That base's Agent Context is too large to compare.")
        files[rel] = data
    return files


def _examine_base(files: Dict[str, bytes]) -> ac.Examination:
    """Validate the base's Agent Context, rebuilt in a private temporary
    folder that is removed afterwards. Its location never leaves this call."""
    tmp = tempfile.mkdtemp(prefix="charter-base-")
    try:
        root = os.path.join(tmp, "context")
        os.mkdir(root)
        root_real = os.path.realpath(root)
        for rel, data in files.items():
            target = os.path.normpath(os.path.join(root, *rel.split("/")))
            # Nothing is ever written outside the private comparison folder,
            # whatever `rel` holds: `_base_files` already rejects such paths,
            # and this is the second line that makes a write-escape impossible.
            if os.path.commonpath([root_real, os.path.realpath(target)]) != root_real:
                raise CompareError("Git listed a file outside this Agent Context, so nothing "
                                   "was read.")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(data)
        return ac.examine(root)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --- the comparison -------------------------------------------------------------------

def _documents(exam: ac.Examination) -> Dict[str, Dict[str, Any]]:
    return {d.path: {"path": d.path, "id": d.id, "title": d.title,
                     "scope": str(d.meta.get("scope") or ""), "sha256": exam.hashes[d.path],
                     "text": exam.texts[d.path]} for d in exam.documents}


def _diff(path: str, before: str, after: str) -> str:
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"base/{path}", tofile=f"current/{path}"))


def comparison_fingerprint(base_fp: str, current_fp: str) -> str:
    """What the review material reviews: the transition from the base's
    context to the current one. Both are context fingerprints."""
    return hashlib.sha256(f"{COMPARISON_VERSION}\n{base_fp}\n{current_fp}\n".encode()).hexdigest()


def _refused(reason: str, **extra: Any) -> Dict[str, Any]:
    return dict({"available": False, "reason": reason, "advisory": ADVISORY,
                 "read_only": READ_ONLY}, **extra)


def _cause(exc: BaseException) -> str:
    """Why reading failed, for the person: the system's reason, or Charter's
    own person-facing words, never a raw location."""
    if isinstance(exc, OSError) and exc.strerror:
        return f" ({exc.strerror})"
    if isinstance(exc, (hs.HostStateError, ps.PrivateStateError)) and str(exc):
        return f" ({exc})"
    return ""


# Failures reading files, private state or Git that end a comparison with a
# reason rather than an error: the command's result is always one answer.
_UNREADABLE = (OSError, ValueError, subprocess.SubprocessError)


# --- what review material never discloses -------------------------------------------

# Git's shortest default abbreviation of a commit; a shorter hex word is not
# taken for one.
MIN_ABBREV = 7

COMMIT = "a Git commit identifier"
REVISION = "a branch name, or the base revision as you typed it"
LOCATION = "a local location: a folder on this computer, or Charter's private state"

_WORD = re.compile(r"[A-Za-z0-9]+")
_HEXWORD = re.compile(r"[0-9a-f]+")
_DRIVE_PATH = re.compile(r"([a-z]):(/.*)")
# A branch, tag or revision name is matched as a whole token: not inside a
# longer name (`maintain` for `main`, `feature-base` for `base`), and not as
# the stem of a file name (`main.md`), but still at the end of a sentence and
# after a slash (`origin/main`).
_NAME_BEFORE = r"(?<![A-Za-z0-9_.\-])"
_NAME_AFTER = r"(?![A-Za-z0-9_\-/]|\.[A-Za-z0-9_])"
# A location is matched the same way, after letter case, separators and URL
# escapes are normalised: never as the start of a longer folder name.
_PATH_BEFORE = r"(?<![a-z0-9_.\-])"
_PATH_AFTER = r"(?![a-z0-9_\-]|\.[a-z0-9_])"


@dataclass
class Undisclosed:
    """What review material must never contain."""
    commits: Set[str] = field(default_factory=set)  # full object names, lower case
    names: Set[str] = field(default_factory=set)    # branch, tag and revision text, as spelt
    paths: Set[str] = field(default_factory=set)    # local locations, normalised, every spelling

    def patterns(self) -> Tuple[Any, Any]:
        names = sorted((n for n in self.names if n), key=len, reverse=True)
        paths = sorted((p for p in self.paths if p), key=len, reverse=True)
        return (re.compile(_NAME_BEFORE + "(?:" + "|".join(map(re.escape, names)) + ")"
                           + _NAME_AFTER) if names else None,
                re.compile(_PATH_BEFORE + "(?:" + "|".join(map(re.escape, paths)) + ")"
                           + _PATH_AFTER) if paths else None)


def _normal_location(text: str) -> str:
    """A location, or text that may quote one, in one spelling: forward
    slashes, folded case, URL escapes decoded, no repeated slash."""
    t = urllib.parse.unquote(text) if "%" in text else text
    return re.sub(r"/+", "/", t.replace("\\", "/").casefold())


def location_forms(path: str, home: str = "") -> Set[str]:
    """Every spelling of a local location that review material is checked
    for: as Windows or POSIX writes it, with or without an extended-length
    prefix; as Git Bash, MSYS, Cygwin or WSL writes a drive path, and without
    its drive; inside a `file:` URL (by containment); and relative to the home
    folder (`~`, `$HOME`, `%USERPROFILE%`)."""
    n = _normal_location(path).rstrip("/")
    if n.startswith("/?/unc/"):
        n = "/" + n[len("/?/unc/"):]
    elif n.startswith("/?/"):
        n = n[len("/?/"):]
    forms = {n}
    drive = _DRIVE_PATH.fullmatch(n)
    if drive:
        letter, rest = drive.groups()
        forms |= {f"/{letter}{rest}", f"/mnt/{letter}{rest}", f"/cygdrive/{letter}{rest}", rest}
    h = _normal_location(home).rstrip("/") if home else ""
    if h and n.startswith(h + "/"):
        rel = n[len(h):]
        forms |= {f"{p}{rel}" for p in ("~", "$home", "${home}", "%userprofile%")}

    # A drive or filesystem root alone, or one bare folder name, says nothing
    # about this computer and would match ordinary prose.
    def specific(form: str) -> bool:
        parts = [c for c in form.split("/") if c and not c.endswith(":")]
        return len(form) >= 4 and (len(parts) >= 2 or form[0] in "~$%")
    return {f for f in forms if specific(f)}


def _repository_roots(folder: str) -> List[str]:
    """The Git checkout's top folder, found by looking for `.git` above the
    Agent Context, so Git is never asked for a location: as reached through
    the folder given, and as resolved, which differ when a link leads there."""
    roots = []
    for probe in (os.path.abspath(folder), os.path.realpath(folder)):
        while True:
            if os.path.lexists(os.path.join(probe, ".git")):
                roots.append(probe)
                break
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
    return list(dict.fromkeys(roots))


def _ref_names(listing: Optional[bytes], into: "Undisclosed") -> None:
    """The names a full ref name is also known by: `refs/heads/x` is `x`;
    `refs/remotes/origin/x` is `origin/x` and `x`."""
    for line in (listing or b"").decode("utf-8", "replace").splitlines():
        ref = line.strip()
        if not ref:
            continue
        if _HEX.fullmatch(ref.lower()):
            into.commits.add(ref.lower())
            continue
        into.names.add(ref)
        for prefix in ("refs/heads/", "refs/tags/", "refs/remotes/", "refs/"):
            if ref.startswith(prefix) and len(ref) > len(prefix):
                short = ref[len(prefix):]
                into.names.add(short)
                if prefix == "refs/remotes/" and "/" in short:
                    into.names.add(short.split("/", 1)[1])
                break


def undisclosed(folder: str, rev: str, commit: str, secrets: Sequence[str] = ()) -> Undisclosed:
    """Everything review material from this comparison must not contain: the
    base's commit and the checked-out commit, in full or abbreviated; the
    current branch, the ref the base resolved to, and the base as typed; and
    this folder, its Git checkout, the home folder and private state, in every
    spelling. Asks Git only read-only questions on the allow-list."""
    out = Undisclosed(commits={commit.lower()})
    head = _git(folder, ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"])
    oid = (head or b"").decode("ascii", "replace").strip().lower()
    if _HEX.fullmatch(oid):
        out.commits.add(oid)
    out.names.add(rev)
    stem = re.split(r"[~^@]", rev, maxsplit=1)[0]
    if stem:
        out.names.add(stem)
    _ref_names(_git(folder, ["rev-parse", "--symbolic-full-name", rev]), out)
    _ref_names(_git(folder, ["symbolic-ref", "--quiet", "HEAD"]), out)
    home = os.path.expanduser("~")
    for loc in (*secrets, folder, os.path.realpath(folder), hs.canonical(folder),
                *_repository_roots(folder), home):
        if isinstance(loc, str) and loc:
            # A secret may be canonical: each spelling of the same place, such
            # as macOS's /var for /private/var, is refused too.
            for spelling in hs.spellings(loc):
                out.paths |= location_forms(spelling, home)
    return out


def disclosed(text: str, und: Undisclosed, names: bool = True,
              compiled: Optional[Tuple[Any, Any]] = None) -> str:
    """Which kind of undisclosable value `text` holds, or "". A commit
    counts from MIN_ABBREV hex digits, as a whole word or after `git
    describe`'s `g`. Names count only when `names`: Charter's own wording
    around the documents may use any ordinary word."""
    for m in _WORD.finditer(text):
        word = m.group().lower()
        for hexword in (word, word[1:] if word.startswith("g") else ""):
            if (len(hexword) >= MIN_ABBREV and _HEXWORD.fullmatch(hexword)
                    and any(c.startswith(hexword) for c in und.commits)):
                return COMMIT
    name_re, path_re = compiled or und.patterns()
    if names and name_re is not None and name_re.search(text):
        return REVISION
    if path_re is not None and path_re.search(_normal_location(text)):
        return LOCATION
    return ""


def disclosure_refusal(units: Sequence[Tuple[str, str]], framing: str, und: Undisclosed) -> str:
    """The person-facing refusal when Charter itself would add an
    undisclosable value to review material, or "". `units` are what Charter
    sends with the material beyond its own wording, each `(where, text)`, such
    as a packet's file name, checked for every kind of value; `framing` is
    Charter's own wording and metadata around the reviewed content
    (`impact.comparison_framing`), checked for commits and locations. The
    reviewed documents, their logical paths and the project name are content
    under review and are never checked: their own text may quote any value.
    The refusal names the kind of value and where it is, never the value."""
    compiled = und.patterns()
    found, where = "", ""
    for label, text in units:
        found = disclosed(text, und, compiled=compiled)
        if found:
            # Where it is must not itself disclose it.
            where = label if not disclosed(label, und, compiled=compiled) else "what is sent with it"
            break
    if not found:
        found, where = disclosed(framing, und, names=False, compiled=compiled), "Charter's own wording"
    if not found:
        return ""
    return (f"The review material would contain {found}, in {where}, so Charter did not prepare "
            "it: Charter never adds a commit, branch, revision or local location of its own to "
            "review material. Nothing was printed or saved.")


# --- the comparison -------------------------------------------------------------------

def _problems(issues: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """What is wrong with an Agent Context, as `charter check` lists it."""
    return [{"path": i.get("path") or "", "message": i["message"], "fix": i.get("fix") or ""}
            for i in issues if i.get("level") == "error"]


def _not_comparable(status: Dict[str, Any]) -> Dict[str, Any]:
    problems = _problems(status.get("issues") or [])
    reason = "The Agent Context is not valid and clean now, so it cannot be compared."
    if status.get("interrupted"):
        reason += (" A Charter write to it was interrupted: open it in Charter (`charter serve`) "
                   "to recover it, then compare again.")
    elif problems:
        reason += (" Correct the problems listed below, then compare again; `charter check` "
                   "lists them too.")
    else:
        reason += " `charter check` says why."
    return _refused(reason, current_problems=problems)


def compare(folder: str, base: Any, secrets: Sequence[str] = (),
            extra: Sequence[Tuple[str, str]] = ()) -> Dict[str, Any]:
    """Compare the current Agent Context at `folder` with its folder at the
    base the person named, and prepare review material for the result.
    Writes nothing to the Agent Context, its private state or Git.

    Not available — with the reason, and no material — when the folder is not
    in a Git checkout, is not valid and clean now, the base does not resolve
    or is not in this checkout's history, the base has no valid Agent Context
    in this folder, or what the comparison reads cannot be read.

    `extra`: further `(where, text)` sent with the material, such as a
    packet's file name, checked for disclosure with the documents."""
    try:
        rev = valid_revision(base)
    except CompareError as exc:
        return _refused(str(exc))
    try:
        return _compare(folder, rev, secrets, extra)
    except CompareError as exc:
        return _refused(str(exc))
    except _UNREADABLE as exc:
        return _refused("Charter could not read what the comparison needs" + _cause(exc)
                        + ", so no comparison was made. Nothing was changed.")


def _compare(folder: str, rev: str, secrets: Sequence[str],
             extra: Sequence[Tuple[str, str]]) -> Dict[str, Any]:
    if not in_checkout(folder):
        return _refused("This Agent Context is not in a Git checkout, so there is no base to "
                        "compare with.")
    try:
        status = mg.check(folder, git=False)
        if not status["agents_served"]:
            return _not_comparable(status)
        current = ac.examine(folder)
    except _UNREADABLE as exc:
        raise CompareError("Charter could not read this Agent Context or its private state now"
                           + _cause(exc) + ", so it cannot be compared. Nothing was changed.")
    if not current.valid or current.settings is None:
        return _not_comparable({"issues": current.issues})
    commit = _resolve(folder, rev)
    files = _base_files(folder, commit)
    try:
        base = _examine_base(files)
    except CompareError:
        raise
    except _UNREADABLE as exc:
        raise CompareError("Charter could not rebuild that base's Agent Context in a private "
                           "temporary folder to check it" + _cause(exc) + ", so it cannot be "
                           "compared. Nothing was changed.")
    if not base.valid:
        problems = [f"`{i['path']}`: {i['message']}" if i.get("path") else i["message"]
                    for i in base.issues[:5]]
        return _refused("At that base, this folder does not hold a valid Agent Context, so there "
                        "is nothing to compare it with.", base_problems=problems)

    before, after = _documents(base), _documents(current)
    rows = []
    for path in sorted(set(before) | set(after)):
        b, a = before.get(path), after.get(path)
        if b and a and b["sha256"] == a["sha256"]:
            change = "unchanged"
        elif b and a:
            change = "changed"
        elif a:
            change = "added"
        else:
            change = "removed"
        rows.append({"path": path, "change": change,
                     "title": (a or b)["title"], "scope": (a or b)["scope"],
                     "base_title": b["title"] if b else "", "base_scope": b["scope"] if b else "",
                     "diff": "" if change == "unchanged" else _diff(
                         path, b["text"] if b else "", a["text"] if a else "")})
    summary = {k: sum(1 for r in rows if r["change"] == k)
               for k in ("added", "changed", "removed", "unchanged")}
    settings_changed = (base.settings.project_name != current.settings.project_name
                        or base.settings.guidance_map != current.settings.guidance_map)
    fingerprint = comparison_fingerprint(base.fingerprint, current.fingerprint)
    out = {"available": True, "reason": "", "advisory": ADVISORY, "read_only": READ_ONLY,
           "base": rev, "project": current.settings.project_name,
           "base_fingerprint": base.fingerprint, "current_fingerprint": current.fingerprint,
           "comparison_fingerprint": fingerprint, "rows": rows, "summary": summary,
           "settings_changed": settings_changed, "same": base.fingerprint == current.fingerprint}
    if out["same"]:
        out["review_prompt"] = {"ready": False, "reason": "The governing context at that base is "
                                "the same as now: there is nothing to review."}
        return out
    out["review_prompt"] = prepare_material(current, before, rows, fingerprint, base.fingerprint,
                                            settings_changed,
                                            undisclosed(folder, rev, commit, secrets), extra)
    return out


def prepare_material(current: ac.Examination, before: Dict[str, Dict[str, Any]],
                     rows: List[Dict[str, Any]], fingerprint: str, base_fp: str,
                     settings_changed: bool, und: Undisclosed,
                     extra: Sequence[Tuple[str, str]] = ()) -> Dict[str, Any]:
    """The review material for a comparison: a copyable prompt within the
    practical limit, and past it one portable packet. Charter adds no commit,
    branch, revision text or local location of its own; the documents are
    embedded exactly as they read, whatever they quote."""
    identity = {"project": current.settings.project_name, "fingerprint": current.fingerprint,
                "documents": [dict(d) for d in sorted(_documents(current).values(),
                                                      key=lambda d: d["path"])]}
    base_docs = [before[r["path"]] for r in rows if r["change"] in ("changed", "removed")]
    lines = [f"{r['change']} `{r['path']}`" for r in rows if r["change"] != "unchanged"]
    if settings_changed:
        lines.append("the project name or agent guidance in the context map changed")
    prompt = impact.generate_comparison_prompt(identity, base_fp, base_docs, lines, fingerprint)
    over = prompt["size_chars"] > impact.PRACTICAL_LIMIT_CHARS
    if over:
        prompt = impact.generate_comparison_prompt(identity, base_fp, base_docs, lines, fingerprint,
                                                   packet=True)
    # Only what Charter itself writes is checked: its own wording and metadata
    # around the reviewed content, and what is sent with the material. The
    # documents, their paths and the project name are reviewed content.
    framing = impact.comparison_framing(identity, base_fp, base_docs, lines, fingerprint,
                                        packet=over)
    refusal = disclosure_refusal(list(extra), framing, und)
    if refusal:
        return {"ready": False, "reason": refusal}
    prompt.update(ready=True, reason="", over_limit=over, limit=impact.PRACTICAL_LIMIT_CHARS,
                  comparison_fingerprint=fingerprint,
                  includes={"documents": len(identity["documents"]), "base_documents": len(base_docs)})
    if over:
        name = impact.packet_file_name(identity["project"], fingerprint, kind="base-review")
        prompt.update(file_name=name, request=impact.packet_request(name, fingerprint))
    return prompt


def recheck(folder: str, base: Any, fingerprint: str, secrets: Sequence[str] = (),
            extra: Sequence[Tuple[str, str]] = ()) -> Dict[str, Any]:
    """The comparison made again, just before its review material is printed
    or saved: refused unless it is still the comparison just made, so material
    never mixes what was read before a change with what was read after, and
    unless its material can still be prepared."""
    result = compare(folder, base, secrets, extra)
    if not result["available"] or result["comparison_fingerprint"] != fingerprint:
        raise CompareError("The Agent Context or the base changed while they were being compared, "
                           "so no review material was printed or saved. Compare again.")
    if not result["review_prompt"].get("ready"):
        raise CompareError(result["review_prompt"].get("reason")
                           or "There is no review material. Nothing was printed or saved.")
    return result
