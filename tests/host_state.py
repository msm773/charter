"""This computer's private-location helpers. Run: python -m tests.host_state

The helpers `private_store` builds Charter's private state on:

  * containment is by canonical path components, never a string prefix;
  * location keys are one-way and never reveal the location they name;
  * a folder is made this user's alone whatever permissions it was created
    with, and one opened to other accounts afterwards is reported, not repaired;
  * locks are exclusive across processes, bounded, independent per file, and
    released by the operating system when their holder dies;
  * JSON records are replaced in one rename, and an unreadable one is refused;
  * every low-level write writes every byte or raises: a short write is
    continued, and one that makes no progress, or reports a count it cannot
    have written, fails, so a record cut short is never taken for a whole one.
"""
from __future__ import annotations

import errno
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import host_state  # noqa: E402
from app.host_state import HostStateError  # noqa: E402
from tests.harness import ScriptedWrites  # noqa: E402

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


def case_write_all() -> None:
    print("\nwriting every byte")
    base = tempfile.mkdtemp(prefix="charter-write-")
    data = bytes(range(256)) * 40

    def written(script) -> tuple:
        """(what reached the file, the exception raised or None, the calls)."""
        path = os.path.join(base, "out.bin")
        if os.path.exists(path):
            os.remove(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | getattr(os, "O_BINARY", 0))
        with ScriptedWrites(lambda _p, d: script(d)) as writes:
            try:
                host_state.write_all(fd, data)
                raised = None
            except OSError as exc:
                raised = exc
            finally:
                os.close(fd)
        with open(path, "rb") as fh:
            return fh.read(), raised, writes.calls

    try:
        sizes = iter([1, 7, 1000, 3])
        got, raised, calls = written(lambda d: min(len(d), next(sizes, len(d))))
        check(got == data and raised is None and [c[2] for c in calls] == [1, 7, 1000, 3,
                                                                          len(data) - 1011],
              "a sequence of partial writes continues from where each stopped until every byte "
              "is written, in order")
        check(written(lambda d: min(len(d), 1))[0] == data, "  even one byte at a time")
        for label, action in (("no progress", 0), ("a negative count", -1),
                              ("a count larger than asked", len(data) + 1),
                              ("True as its count", True), ("text as its count", "10")):
            got, raised, _calls = written(lambda d, a=action: a)
            check(isinstance(raised, host_state.IncompleteWrite) and raised.errno == errno.EIO
                  and got == b"", f"a write reporting {label} fails as an OSError, never success")
        calls_seen = iter([100, 0])
        got, raised, calls = written(lambda d: next(calls_seen))
        check(isinstance(raised, host_state.IncompleteWrite) and got == data[:100]
              and "100 of" in str(raised) and len(calls) == 2,
              "a write that stops part-way fails, saying how far it got")
        disk_full = OSError(errno.ENOSPC, "No space left on device")
        got, raised, _calls = written(lambda d: disk_full)
        check(raised is disk_full, "an error the system reports is raised exactly as it was")
        null = os.open(os.devnull, os.O_WRONLY)
        try:
            with ScriptedWrites(lambda _p, d: 0) as writes:
                host_state.write_all(null, b"")
        finally:
            os.close(null)
        check(writes.calls == [], "nothing to write calls no write and succeeds")

        path = os.path.join(base, "record.json")
        host_state.write_json_atomic(path, {"v": 1})
        with ScriptedWrites(lambda p, d: min(len(d), 5)):
            host_state.write_json_atomic(path, {"v": 2, "text": "é" * 100})
        check(host_state.read_json(path) == {"v": 2, "text": "é" * 100} and os.listdir(base)
              == ["out.bin", "record.json"],
              "a private JSON record written in partial writes is whole")
        for label, script in (("makes no progress", lambda p, d: 0),
                              ("stops part-way", lambda p, d: 0 if os.path.getsize(p) else 9),
                              ("fails", lambda p, d: OSError(errno.ENOSPC, "full"))):
            try:
                with ScriptedWrites(script):
                    host_state.write_json_atomic(path, {"v": 3})
                raised = None
            except OSError as exc:
                raised = exc
            check(raised is not None and host_state.read_json(path) == {"v": 2, "text": "é" * 100}
                  and sorted(os.listdir(base)) == ["out.bin", "record.json"],
                  f"a private JSON write that {label} raises, keeps the record it would have "
                  "replaced, and leaves no temporary file")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def case_spellings() -> None:
    print("\none location, every spelling: root links both ways, and the letter case stored")
    base = tempfile.mkdtemp(prefix="charter-spell-")
    real = os.path.join(base, "real data")
    os.mkdir(real)
    ctx = os.path.join(real, "My Ctx")
    os.mkdir(ctx)
    alias = os.path.join(base, "alias")
    resolved = os.path.realpath(ctx)
    try:
        # A made-up root link, `alias` for `real data`, as macOS's /var is for
        # /private/var: the same on every platform, whatever its own root holds.
        saved = host_state._root_links
        host_state._root_links = lambda: [(alias, os.path.realpath(real))]
        try:
            forms = host_state.spellings(ctx)
            back = host_state.spellings(os.path.join(alias, "My Ctx"))
        finally:
            host_state._root_links = saved
        check(ctx in forms and resolved in forms and os.path.join(alias, "My Ctx") in forms,
              "the folder as given, as resolved, and through the link to it")
        check(resolved in back, "and given through the link, its target spelling too")
        check(host_state.spellings("") == [], "nothing for no location")
        if sys.platform == "darwin" and os.path.islink("/var"):
            tmp = os.path.realpath(tempfile.gettempdir())
            if tmp.startswith("/private/var/"):
                check(tmp[len("/private"):] in host_state.spellings(tmp),
                      "macOS: /private/var/… is also spelled /var/…")
                check(tmp in host_state.spellings(tmp[len("/private"):]),
                      "and /var/… is also spelled /private/var/…")
        if os.path.isdir(ctx.swapcase()):
            # A case-insensitive volume, as macOS's is by default.
            check(host_state.canonical(ctx.swapcase()) == host_state.canonical(ctx) == resolved,
                  "a case-insensitive volume: any letter case is the stored one")
            check(host_state.location_key(ctx.swapcase()) == host_state.location_key(ctx),
                  "so one folder has one key, however its case is typed")
            check(host_state.canonical(os.path.join(ctx.upper(), "not yet"))
                  == os.path.join(resolved, "not yet"),
                  "and a missing part below it is kept as given")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def case_shared_files() -> None:
    """A file another handle has open (Windows refuses to rename over or
    remove it) is tried again briefly, then the refusal is raised as it was;
    nothing else is retried, and an atomic write never leaves its temporary
    file behind."""
    print("\nfiles another handle has open: a short, bounded retry, and nothing left behind")
    from tests.harness import HeldOpen
    windows = os.name == "nt"
    base = tempfile.mkdtemp(prefix="charter-shared-")
    try:
        path = os.path.join(base, "record.json")
        host_state.write_json_atomic(path, {"v": 1})
        with HeldOpen("after-refusal") as reader:
            reader.open(path)
            host_state.write_json_atomic(path, {"v": 2})
        check(host_state.read_json(path) == {"v": 2} and os.listdir(base) == ["record.json"]
              and (not windows or [r[2] for r in reader.refusals] in ([5], [32])),
              "a reader that finishes: the write is refused once"
              + (f" (WinError {reader.refusals[0][2]})" if reader.refusals else "")
              + ", tried again, and succeeds, with no temporary file left")

        with HeldOpen("never") as reader:
            reader.open(path)
            started = time.monotonic()
            try:
                host_state.write_json_atomic(path, {"v": 3})
                raised = None
            except OSError as exc:
                raised = exc
            took = time.monotonic() - started
        if windows:
            check(raised is not None and host_state.sharing_violation(raised) and len(reader.refusals) == 10
                  and took < 2.0 and host_state.read_json(path) == {"v": 2} and os.listdir(base) == ["record.json"],
                  f"a reader that does not finish: ten attempts in {took:.2f}s, then the refusal itself is "
                  "raised; the record is as it was and the temporary file is removed")
        else:
            check(raised is None, "(elsewhere an open handle refuses nothing: the write succeeds)")

        attempts = []

        def missing() -> None:
            attempts.append(1)
            os.replace(os.path.join(base, "absent"), os.path.join(base, "other"))
        try:
            host_state.retry_shared(missing)
            other = None
        except FileNotFoundError as exc:
            other = exc
        check(other is not None and attempts == [1], "any other failure is raised at once, never retried")

        if windows:
            held = os.open(path, os.O_RDONLY)
            stopped = []
            try:
                def stop() -> None:
                    stopped.append(1)
                    raise RuntimeError("no longer the same operation")
                try:
                    host_state.retry_shared(os.remove, path, revalidate=stop)
                except RuntimeError:
                    pass
            finally:
                os.close(held)
            check(stopped == [1] and os.path.exists(path),
                  "before trying again, the operation is confirmed still the same, and stopped if not")

            # A real permission problem: a read-only file cannot be replaced, and
            # access denied looks like the sharing refusal. It is never success.
            locked = os.path.join(base, "locked.json")
            host_state.write_json_atomic(locked, {"v": 1})
            os.chmod(locked, stat_readonly())
            try:
                try:
                    host_state.write_json_atomic(locked, {"v": 2})
                    denied = None
                except OSError as exc:
                    denied = exc
            finally:
                os.chmod(locked, 0o600)
            # Opening a record that is being renamed over that moment: the C
            # runtime reports the refusal as errno EACCES alone (a folder opened
            # as a file gives the same real error). Read briefly refused, the
            # record is still read; refused for good, it is never read as missing.
            try:
                open(base, "rb")
                errno_only = None
            except PermissionError as exc:
                errno_only = exc
            check(errno_only is not None and getattr(errno_only, "winerror", None) is None
                  and host_state.sharing_violation(errno_only),
                  "an open refused with errno EACCES alone counts as the same passing refusal")
            refusals = []

            def opens_after_one_refusal(*args):
                if not refusals:
                    refusals.append(1)
                    raise errno_only
                return open(*args)
            host_state.open = opens_after_one_refusal
            try:
                reread = host_state.read_json(path)
            finally:
                del host_state.open
            check(refusals == [1] and reread == {"v": 2},
                  "a record read the moment it is renamed over: refused once, then read — never taken as missing")
            try:
                host_state.read_json(base)
                unread = None
            except HostStateError as exc:
                unread = exc
            check(unread is not None, "  one that cannot be opened at all is still refused, after the same few tries")

            check(denied is not None and getattr(denied, "winerror", None) == 5
                  and host_state.read_json(locked) == {"v": 1}
                  and sorted(os.listdir(base)) == ["locked.json", "record.json"],
                  "a persistent access denial fails after the same bounded tries, the file unchanged and "
                  "nothing left behind: never reported as written")
    finally:
        shutil.rmtree(base, ignore_errors=True)


def stat_readonly() -> int:
    import stat
    return stat.S_IREAD


def run() -> None:
    case_paths()
    case_spellings()
    case_escapes_relative()
    case_extended_prefix()
    case_private_folders()
    case_locks()
    case_json()
    case_write_all()
    case_shared_files()
    print(f"\n{OK} All private-location helper checks passed.")


if __name__ == "__main__":
    run()
