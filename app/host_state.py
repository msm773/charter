"""This computer's private-location helpers, for Charter.

Canonical paths and containment, private folders restricted to this user,
exclusive cross-process locks, atomic JSON files, and the operating system's
own answer for where per-user application data lives. `private_store` builds
Charter's private state on these; nothing here knows about any
Agent Context.

The application-data location is found only from the operating system: on
Windows the LocalAppData known folder, asked for with this process's own
token; elsewhere the account's home directory as the password database
reports it. No environment variable can move it.
"""
from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
import random
import re
import stat
import subprocess
import time
import uuid
from typing import Any, Iterator, List, Optional

_O_BINARY = getattr(os, "O_BINARY", 0)


class HostStateError(ValueError):
    """A host-local state problem, worded for the person, never for an agent."""


# --- per-user application data ------------------------------------------------------------

def _known_local_app_data() -> str:
    """Windows LocalAppData for the account this process runs as.

    The shell's known-folder API is given this process's access token, so it
    reads the account's own profile from the registry. Called without a token
    it expands `%USERPROFILE%` from the process environment, which would let an
    environment variable move private state."""
    from ctypes import wintypes
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                          ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    token = wintypes.HANDLE()
    TOKEN_QUERY, TOKEN_IMPERSONATE, TOKEN_DUPLICATE = 0x0008, 0x0004, 0x0002
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                     TOKEN_QUERY | TOKEN_IMPERSONATE | TOKEN_DUPLICATE,
                                     ctypes.byref(token)):
        raise HostStateError("Windows did not report this user's identity.")
    guid = uuid.UUID("f1b32785-6fba-4fcf-9d55-7b8e7f157091")  # FOLDERID_LocalAppData
    folder_id = (ctypes.c_byte * 16).from_buffer_copy(guid.bytes_le)
    path = ctypes.c_wchar_p()
    shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
    try:
        result = shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, token,
                                              ctypes.byref(path))
        if result != 0 or not path.value:
            raise HostStateError("Windows did not report a LocalAppData folder for this user.")
        return path.value
    finally:
        if path:
            ctypes.windll.ole32.CoTaskMemFree(path)  # type: ignore[attr-defined]
        kernel32.CloseHandle(token)


def _account_home() -> str:
    """The account's home directory from the password database, not HOME."""
    import pwd  # POSIX only
    return pwd.getpwuid(os.getuid()).pw_dir


def _decode(raw: Optional[bytes]) -> str:
    """Decode a tool's output ourselves: UTF-8, never the platform default."""
    return (raw or b"").decode("utf-8", "replace")


# --- paths -----------------------------------------------------------

def _strip_extended_prefix(path: str) -> str:
    """Windows extended-length prefixes name the same location as the plain
    path, but `realpath` keeps them, so `\\\\?\\C:\\x` would key, lock and
    compare as a different place than `C:\\x` — and a containment check across
    the two raises (different "drives") and fails open. Normalize them away so
    one folder has one canonical spelling. Harmless off Windows: these prefixes
    never appear there."""
    if path.startswith("\\\\?\\UNC\\"):
        return "\\\\" + path[len("\\\\?\\UNC\\"):]
    if path.startswith("\\\\?\\"):
        return path[len("\\\\?\\"):]
    return path


def canonical(path: str) -> str:
    """The canonical location of `path`: links, junctions, letter case, short
    names and extended-length prefixes resolved (Product Specification §3A.7).
    Missing trailing parts are kept as given below the deepest existing
    ancestor."""
    resolved = os.path.realpath(os.path.abspath(os.path.expanduser(path)))
    return _strip_extended_prefix(resolved)


def location_key(path: str) -> str:
    """A one-way key for a canonical location, used to name locks and staging.

    Keys never reveal the location they name."""
    norm = os.path.normcase(canonical(path))
    return hashlib.sha256(norm.encode("utf-8", "surrogatepass")).hexdigest()[:32]


def _existing_ancestor(path: str) -> str:
    probe = canonical(path)
    while not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    return probe


def inside(child: str, parent: str) -> bool:
    """Whether `child` is `parent` or lies inside it, canonically."""
    c, p = os.path.normcase(canonical(child)), os.path.normcase(canonical(parent))
    try:
        return os.path.commonpath([c, p]) == p
    except ValueError:  # different drives
        return False


def overlaps(a: str, b: str) -> bool:
    return inside(a, b) or inside(b, a)


_DRIVE = re.compile(r"^[A-Za-z]:")


def escapes_relative(rel: str) -> bool:
    """Whether `rel` is not a plain, contained relative path: it is absolute or
    drive-qualified, holds a backslash or a control character, or has an empty,
    `.` or `..` component. Lexical only — nothing is joined to a path or opened.
    One definition shared by the MCP document-reference check, the Git-base
    listing check and the transaction write-path allow-list, so they cannot
    drift (a separate concern from `private_store.name_problem`, which validates
    a single document file name's exact format)."""
    if not rel or rel.startswith(("/", "\\")) or _DRIVE.match(rel) or "\\" in rel:
        return True
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in rel):
        return True
    return any(part in ("", ".", "..") for part in rel.split("/"))


def in_git_worktree(path: str) -> bool:
    """Whether `path` lies inside any Git working tree (or `.git` directory)."""
    probe = _existing_ancestor(path)
    try:
        proc = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", f"core.hooksPath={os.devnull}",
                               "-c", "protocol.ext.allow=never", "-C", probe, "rev-parse",
                               "--is-inside-work-tree", "--is-inside-git-dir"],
                              capture_output=True,
                              env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"})
    except OSError:
        return False
    return proc.returncode == 0 and "true" in _decode(proc.stdout).split()


# --- privacy -----------------------------------------------------------------------

def _current_user_sid() -> str:
    proc = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True)
    if proc.returncode != 0:
        raise HostStateError("Windows did not report the current user's identity.")
    fields = [f.strip().strip('"') for f in _decode(proc.stdout).strip().split(",")]
    sid = fields[-1] if fields else ""
    if not sid.startswith("S-"):
        raise HostStateError("Windows did not report the current user's identity.")
    return sid


_USER_SID: List[str] = []


def _user_sid() -> str:
    if not _USER_SID:
        _USER_SID.append(_current_user_sid())
    return _USER_SID[0]


def _sddl(path: str) -> str:
    """The owner and DACL of `path` as SDDL, read without changing anything."""
    from ctypes import wintypes
    adv = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.LocalFree.restype = ctypes.c_void_p
    owner, dacl, sd = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    what = 0x1 | 0x4  # OWNER_ and DACL_SECURITY_INFORMATION
    if adv.GetNamedSecurityInfoW(ctypes.c_wchar_p(path), 1, what, ctypes.byref(owner), None,
                                 ctypes.byref(dacl), None, ctypes.byref(sd)) != 0:
        raise OSError("the security descriptor could not be read")
    text = ctypes.c_wchar_p()
    try:
        if not adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                sd, 1, what, ctypes.byref(text), ctypes.byref(wintypes.ULONG())):
            raise OSError("the security descriptor could not be read")
        value = text.value or ""
        k32.LocalFree(ctypes.cast(text, ctypes.c_void_p))
        return value
    finally:
        k32.LocalFree(sd)


def private_problem(path: str) -> str:
    """Why the folder `path` is not this user's alone, as `restrict_to_owner`
    left it, or "" when it still is. Reads only; never repairs.

    POSIX: a plain folder owned by this user, with no group or other access.
    Windows: a plain folder owned by this user whose DACL is protected (no
    inherited entries) and grants access to this user alone; deny entries,
    which only narrow access, are allowed."""
    try:
        st = os.lstat(path)
    except OSError:
        return "it cannot be examined"
    if stat.S_ISLNK(st.st_mode) or (getattr(st, "st_file_attributes", 0) & 0x400) \
            or not stat.S_ISDIR(st.st_mode):
        return "it is not a plain folder"
    if os.name != "nt":
        if st.st_uid != os.geteuid():
            return "it belongs to another account"
        if st.st_mode & 0o077:
            return f"other accounts may use it (mode {stat.S_IMODE(st.st_mode):o})"
        return ""
    try:
        sddl, user = _sddl(path), _user_sid()
    except (OSError, HostStateError, AttributeError):
        return "its permissions cannot be read"
    owner = sddl[2:sddl.index("D:")] if sddl.startswith("O:") and "D:" in sddl else ""
    if owner != user:
        return "it is owned by another account"
    dacl = sddl[sddl.index("D:") + 2:] if "D:" in sddl else ""
    flags = dacl.split("(", 1)[0]
    if "NO_ACCESS_CONTROL" in dacl or "P" not in flags:
        return "its permissions are inherited or open to every account"
    entries = [e.split(";") for e in dacl[len(flags):].strip("()").split(")(") if e]
    allows = [e for e in entries if len(e) == 6 and e[0] == "A"]
    if any(len(e) != 6 or e[0] not in ("A", "D") for e in entries) \
            or any(e[5] != user or "ID" in e[1] for e in allows):
        return "another account has been given access"
    if not any(e[2] in ("FA", "0x1f01ff") for e in allows):
        return "this user no longer has full control"
    return ""


def restrict_to_owner(path: str) -> None:
    """Make `path` accessible to this user only, or raise.

    POSIX: mode 0700. Windows: the folder's whole DACL is replaced by one
    protected entry granting full control to the current user, whatever it held
    before — Python 3.12.4 and later give `mkdir(mode=0o700)` explicit entries
    for SYSTEM, Administrators and OWNER RIGHTS, which granting this user alone
    would leave in place. The result is checked with `private_problem`. This is
    non-discoverability hygiene, not access control: software running as the
    same user can still read it."""
    if os.name != "nt":
        os.chmod(path, stat.S_IRWXU)
        return
    try:
        _set_protected_dacl(path, f"D:P(A;OICI;FA;;;{_user_sid()})")
    except OSError:
        raise HostStateError("Charter could not restrict the folder to this user.")
    if private_problem(path):
        raise HostStateError("Charter could not restrict the folder to this user.")


def _set_protected_dacl(path: str, sddl: str) -> None:
    """Replace the DACL of `path` with the one `sddl` describes, protected
    from inheritance."""
    from ctypes import wintypes
    adv = ctypes.WinDLL("advapi32", use_last_error=True)  # type: ignore[attr-defined]
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k32.LocalFree.argtypes = [ctypes.c_void_p]
    k32.LocalFree.restype = ctypes.c_void_p
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    adv.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    adv.GetSecurityDescriptorDacl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
                                              ctypes.POINTER(ctypes.c_void_p),
                                              ctypes.POINTER(wintypes.BOOL)]
    adv.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    adv.SetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
                                          ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.c_void_p]
    adv.SetNamedSecurityInfoW.restype = wintypes.DWORD
    sd = ctypes.c_void_p()
    if not adv.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(sd),
                                                                     None):
        raise OSError("the permissions could not be prepared")
    try:
        present, defaulted, dacl = wintypes.BOOL(), wintypes.BOOL(), ctypes.c_void_p()
        if not adv.GetSecurityDescriptorDacl(sd, ctypes.byref(present), ctypes.byref(dacl),
                                             ctypes.byref(defaulted)) or not present:
            raise OSError("the permissions could not be prepared")
        # SE_FILE_OBJECT; DACL_ and PROTECTED_DACL_SECURITY_INFORMATION
        if adv.SetNamedSecurityInfoW(path, 1, 0x4 | 0x80000000, None, None, dacl, None) != 0:
            raise OSError("the permissions could not be set")
    finally:
        k32.LocalFree(sd)


# --- locks -----------------------------------------------------------------------------

@contextlib.contextmanager
def file_lock(path: str, timeout: float) -> Iterator[bool]:
    """An exclusive cross-process lock on `path`; yields whether it was had.

    Held on an open handle (`msvcrt.locking` or `flock`), so the operating
    system releases it if the process dies. The lock file is never deleted."""
    fd = os.open(path, os.O_RDWR | os.O_CREAT | _O_BINARY, 0o600)
    acquired = False
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.001 + random.random() * 0.004)
        yield acquired
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
        os.close(fd)


# --- atomic JSON records ----------------------------------------------------------------

def write_json_atomic(path: str, data: Any) -> None:
    """Replace `path` with `data` as JSON, flushed, in one rename."""
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, f".{os.path.basename(path)}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    raw = (json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_BINARY, 0o600)
    try:
        os.write(fd, raw)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _reject_nonfinite(token: str) -> float:
    raise ValueError(f"non-finite JSON value: {token}")


def _strict_float(token: str) -> float:
    value = float(token)
    if value != value or value in (float("inf"), float("-inf")):
        raise ValueError(f"non-finite JSON number: {token}")
    return value


def loads_strict(text: str) -> Any:
    """`json.loads`, except any non-finite value is a `ValueError`: the literals
    `NaN`, `Infinity` and `-Infinity`, and a magnitude that overflows to
    infinity such as `1e999`. Python round-trips these, but no browser's
    `JSON.parse` accepts them, so a single one filed through intake would make a
    console response unparseable. Rejecting them at every entry point keeps what
    Charter stores and returns within the JSON every client can read."""
    return json.loads(text, parse_constant=_reject_nonfinite, parse_float=_strict_float)


def read_json(path: str, default: Any = None) -> Any:
    try:
        with open(path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        raise HostStateError("A private Charter record could not be read.")
