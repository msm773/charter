"""This computer's private-location helpers. Run: python -m tests.host_state

The helpers `private_store` builds Charter's private state on:

  * containment is by canonical path components, never a string prefix;
  * location keys are one-way and never reveal the location they name;
  * a folder is made this user's alone whatever permissions it was created
    with, and one opened to other accounts afterwards is reported, not repaired;
  * locks are exclusive across processes, bounded, independent per file, and
    released by the operating system when their holder dies;
  * JSON records are replaced in one rename, and an unreadable one is refused.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import host_state  # noqa: E402
from app.host_state import HostStateError  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK = "ok"

# A separate process that takes a lock and holds it until it is killed.
HOLDER = r"""
import sys, time
sys.path.insert(0, sys.argv[1])
from app import host_state
with host_state.file_lock(sys.argv[2], timeout=5) as held:
    print("held" if held else "refused", flush=True)
    time.sleep(120)
"""


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def case_paths() -> None:
    print("\npaths: canonical containment and one-way keys")
    base = tempfile.mkdtemp(prefix="charter-paths-")
    try:
        static = os.path.join(base, "static")
        sibling = os.path.join(base, "static-private")
        os.mkdir(static)
        os.mkdir(sibling)
        check(host_state.inside(os.path.join(static, "a", "b"), static)
              and host_state.inside(static, static), "a path inside a folder, and the folder itself, are inside it")
        check(not host_state.inside(sibling, static), "a sibling sharing a name prefix is not inside")
        check(host_state.overlaps(static, os.path.join(static, "x")) and not host_state.overlaps(static, sibling),
              "overlap is containment either way")
        key = host_state.location_key(static)
        check(len(key) == 32 and "static" not in key and key == host_state.location_key(static + os.sep),
              "a location key is stable, fixed-length and does not reveal the location")
        check(host_state.canonical(os.path.join(static, "..", "static")) == host_state.canonical(static),
              "canonical paths resolve `..`")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def case_escapes_relative() -> None:
    print("\none shared check for a relative path that escapes its folder")
    for bad in ("", "/x", "\\x", "a\\b", "C:/x", "D:x", "../x", "a/../b", "a/./b", "a//b",
                ".", "..", "a/\x00b", "a/\x7f/c", "\x01"):
        check(host_state.escapes_relative(bad), f"{bad!r} is rejected as escaping or malformed")
    for ok in ("a.md", "authoritative/a.md", "sub/dir/file.md", "a-b_c.md", "x.y.md"):
        check(not host_state.escapes_relative(ok), f"{ok!r} is accepted as an ordinary relative path")


def case_extended_prefix() -> None:
    print("\nextended-length (\\\\?\\) paths are one location, and containment fails closed")
    base = tempfile.mkdtemp(prefix="charter-ext-")
    try:
        inner = os.path.join(base, "state")
        os.mkdir(inner)
        if os.name != "nt":
            check(True, "(the \\\\?\\ prefix is a Windows path form; nothing to strip here)")
            return
        prefixed = "\\\\?\\" + inner
        check(host_state.canonical(prefixed) == host_state.canonical(inner),
              "a \\\\?\\ path canonicalizes to the same location as its plain spelling")
        check(host_state.location_key(prefixed) == host_state.location_key(inner),
              "so one folder keeps one identity: one lock, one private state, whichever spelling")
        child = os.path.join(inner, "ctx")
        check(host_state.overlaps(prefixed, child) and host_state.overlaps("\\\\?\\" + child, inner),
              "overlap is still detected through the prefix, so a containment guard cannot be evaded")
        unc = "\\\\?\\UNC\\server\\share\\x"
        check(not host_state.canonical(unc).startswith("\\\\?\\"),
              "the \\\\?\\UNC\\ prefix is normalized away too")
    finally:
        shutil.rmtree(base, ignore_errors=True)


EVERYONE = "*S-1-1-0"


def broaden(folder: str) -> None:
    """Open a private folder to other accounts, as someone might afterwards."""
    if os.name == "nt":
        subprocess.run(["icacls", folder, "/grant", f"{EVERYONE}:(OI)(CI)R"], check=True, capture_output=True)
    else:
        os.chmod(folder, 0o755)


def case_private_folders() -> None:
    print("\na folder is made this user's alone, whatever it was created with")
    base = tempfile.mkdtemp(prefix="charter-private-")
    try:
        folder = os.path.join(base, "made")
        os.mkdir(folder)
        if os.name == "nt":
            # What `os.mkdir(mode=0o700)` gives a folder on Python 3.12.4 and
            # later: explicit entries for SYSTEM, Administrators and OWNER RIGHTS.
            host_state._set_protected_dacl(folder, "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)")
            check(host_state.private_problem(folder) != "", "(such a folder is not private)")
        else:
            os.chmod(folder, 0o755)
            check(host_state.private_problem(folder) != "", "(a world-readable folder is not private)")
        host_state.restrict_to_owner(folder)
        check(host_state.private_problem(folder) == "", "restricting it leaves this user alone")
        broaden(folder)
        check("another account" in host_state.private_problem(folder)
              or "other accounts" in host_state.private_problem(folder),
              "opened to other accounts afterwards, it is reported — and not repaired by reading")
        host_state.restrict_to_owner(folder)
        file_path = os.path.join(base, "file.txt")
        open(file_path, "w").close()
        check(host_state.private_problem(file_path) == "it is not a plain folder",
              "a file is not a private folder")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def case_locks() -> None:
    print("\nlocks are exclusive, bounded, and released when their holder dies")
    base = tempfile.mkdtemp(prefix="charter-locks-")
    lock = os.path.join(base, "writer.lock")
    holder = subprocess.Popen([sys.executable, "-c", HOLDER, ROOT, lock], stdout=subprocess.PIPE)
    try:
        check(holder.stdout.readline().strip() == b"held", "another process holds the lock")
        start = time.monotonic()
        with host_state.file_lock(lock, timeout=0.5) as held:
            waited = time.monotonic() - start
        check(not held and 0.4 <= waited < 3.0, "a second holder is refused within its bound")
        with host_state.file_lock(os.path.join(base, "intake.lock"), timeout=0.5) as held:
            check(held, "a different lock file is independent")
    finally:
        holder.kill()
        holder.wait(timeout=30)
    with host_state.file_lock(lock, timeout=5) as held:
        check(held, "after the holder is killed, the lock is free again")
    check(os.path.isfile(lock), "the lock file itself is never deleted")
    shutil.rmtree(base, ignore_errors=True)


def case_json() -> None:
    print("\nJSON records")
    base = tempfile.mkdtemp(prefix="charter-json-")
    try:
        path = os.path.join(base, "sub", "record.json")
        check(host_state.read_json(path, {"none": True}) == {"none": True}, "a missing record reads as the default")
        host_state.write_json_atomic(path, {"b": 1, "a": "é"})
        check(host_state.read_json(path) == {"a": "é", "b": 1}
              and os.listdir(os.path.dirname(path)) == ["record.json"],
              "a record is written whole, with no temporary file left beside it")
        with open(path, "wb") as fh:
            fh.write(b"{not json")
        try:
            host_state.read_json(path)
            refused = False
        except HostStateError as exc:
            refused = "could not be read" in str(exc)
        check(refused, "an unreadable record is refused, in words")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def run() -> None:
    case_paths()
    case_escapes_relative()
    case_extended_prefix()
    case_private_folders()
    case_locks()
    case_json()
    print(f"\n{OK} All private-location helper checks passed.")


if __name__ == "__main__":
    run()
