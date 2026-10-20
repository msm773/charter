"""The launchers start Charter with a real Python.
Run: python -m tests.launchers

  * `charter` (bash) passes over a `python3` that is not Python — such as the
    Microsoft Store alias on Windows, which prints a notice and exits 49 — and
    runs the next real Python 3.9 or later;
  * standard output and the exit status pass straight through: `charter check`
    exits 0 for a valid Agent Context and 1 otherwise, from any folder;
  * with no usable Python at all, `charter` says so on stderr and exits 127;
  * `charter.cmd` runs Charter on Windows, with the same
    pass-through; so does every Python 3.9 or later the `py` launcher lists;
  * `charter check` changes nothing: no file in the folder, no private state, no
    recovery of an interrupted write;
  * installed on PATH, `charter` is found by name;
  * on Windows, `charter add-to-path` appends the launchers' folder to the user's
    PATH once, keeping its entries and value type; after it, a new PowerShell
    with the PATH Windows gives a new program finds the release's `charter.cmd` as
    `charter` from an unrelated folder, and `--check` reports a different `charter`
    that would come first;
  * there is no `cgu` command.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OK = "ok"


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def find_bash() -> str:
    candidates = [shutil.which("bash") or ""]
    if os.name == "nt":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            candidates.append(os.path.join(base, "Git", "bin", "bash.exe"))
    for c in candidates:
        if c and os.path.isfile(c) and "WindowsApps" not in c and "System32" not in c:
            return c
    return ""


def fake_store_alias(folder: str) -> None:
    """A `python3` that behaves like the Microsoft Store alias: not Python."""
    path = os.path.join(folder, "python3")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("#!/usr/bin/env bash\n"
                 "echo 'Python was not found; run without arguments to install from the "
                 "Microsoft Store' >&2\nexit 49\n")
    os.chmod(path, 0o755)


def unix_path(bash: str, path: str) -> str:
    if os.name != "nt":
        return path
    out = subprocess.run([bash, "-c", 'cygpath -u "$1"', "_", path], capture_output=True)
    return out.stdout.decode("utf-8").strip() or path


def run_bash(bash: str, script: str, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run([bash, "-c", script], stdin=subprocess.DEVNULL, capture_output=True,
                          env=env, timeout=60)


def valid_context(base: str) -> str:
    """A valid Agent Context, as Create would leave it, written without private state."""
    sys.path.insert(0, ROOT)
    from app import agent_context as ac
    folder = os.path.join(base, "context")
    os.makedirs(folder)
    for rel, text in ac.render_generated(ac.Settings.make("Launcher test"), [], {}).items():
        with open(os.path.join(folder, rel), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    return folder


def case_bash_launcher() -> None:
    print("\nthe bash launcher `charter`")
    bash = find_bash()
    if not bash:
        print("  skip: no bash on this computer")
        return
    with open(os.path.join(ROOT, "charter"), "rb") as fh:
        raw = fh.read()
    check(b"\r\n" not in raw and b'"$here/charter.py"' in raw, "`charter` has Unix line endings, and runs charter.py")
    with tempfile.TemporaryDirectory(prefix="charter-launch-") as tmp:
        fake = os.path.join(tmp, "fakebin")
        os.mkdir(fake)
        fake_store_alias(fake)
        # The fallback the launcher should reach: a real Python, named `python`.
        python = os.path.join(fake, "python")
        with open(python, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f'#!/usr/bin/env bash\nexec "{unix_path(bash, sys.executable)}" "$@"\n')
        os.chmod(python, 0o755)
        env = dict(os.environ)
        charter = unix_path(bash, os.path.join(ROOT, "charter"))
        prefix = f'export PATH="{unix_path(bash, fake)}:$PATH"; '

        out = run_bash(bash, prefix + f'"{charter}" --help', env)
        check(out.returncode == 0 and out.stdout.startswith(b"usage: charter ")
              and b"Charter" in out.stdout,
              "a python3 that is not Python is passed over; Charter starts")

        ctx = os.path.join(tmp, "not-a-context")
        os.mkdir(ctx)
        out = run_bash(bash, prefix + f'cd "{unix_path(bash, ctx)}" && "{charter}" check --context .', env)
        check(b"Agents:        unavailable" in out.stdout and out.stderr == b"" and out.returncode == 1,
              "`charter check` output passes straight through, with its own exit status, 1")
        good = valid_context(tmp)
        out = run_bash(bash, prefix + f'"{charter}" check --context "{unix_path(bash, good)}"', env)
        check(out.returncode == 0 and b"Agents:        served" in out.stdout,
              "and exit 0 for a valid Agent Context")

        empty = os.path.join(tmp, "emptybin")
        os.mkdir(empty)
        fake_store_alias(empty)
        # Only the alias, bash's own tools and nothing that is Python.
        tools = unix_path(bash, os.path.dirname(bash))
        out = run_bash(bash, f'export PATH="{unix_path(bash, empty)}:{tools}"; "{charter}" --help', env)
        check(out.returncode == 127 and b"charter: Python 3.9 or later was not found" in out.stderr,
              "with no real Python, it says so and exits 127")


def windows_pythons() -> list:
    """Every Python 3.9 or later the `py` launcher lists, as (version, path)."""
    try:
        out = subprocess.run(["py", "-0p"], capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in out.decode("utf-8", "replace").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("-V:3."):
            version = parts[0][3:]
            minor = version.split(".")[1].split("-")[0]
            if minor.isdigit() and int(minor) >= 9 and os.path.isfile(parts[-1]):
                found.append((version, parts[-1]))
    return found


# A test-only `charter.py` beside the release's `charter.cmd`: this tree's Charter,
# with its private state moved to an isolated folder.
SHIM = r"""import sys
sys.path.insert(0, {root!r})
from app import private_store
private_store._default_root = lambda: {state!r}
from app.__main__ import main
raise SystemExit(main(sys.argv[1:]))
"""


def case_cmd_launcher() -> None:
    print("\nthe Windows launcher `charter.cmd`")
    if os.name != "nt":
        print("  skip: not Windows")
        return
    from tests.package import release_bytes
    with tempfile.TemporaryDirectory(prefix="charter-launch-") as tmp:
        state = os.path.join(tmp, "state")
        bin_dir = os.path.join(tmp, "bin")
        os.mkdir(bin_dir)
        with open(os.path.join(ROOT, "charter.cmd"), "rb") as fh:
            launcher = release_bytes("charter.cmd", fh.read())
        with open(os.path.join(bin_dir, "charter.cmd"), "wb") as fh:
            fh.write(launcher)
        with open(os.path.join(bin_dir, "charter.py"), "w", encoding="utf-8") as fh:
            fh.write(SHIM.format(root=ROOT, state=state))
        ctx = os.path.join(tmp, "not-a-context")
        os.mkdir(ctx)
        good = valid_context(tmp)

        out = subprocess.run(["cmd", "/c", os.path.join(bin_dir, "charter.cmd"), "check", "--context", "."],
                             cwd=ctx, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        check(out.returncode == 1 and b"Agents:        unavailable" in out.stdout and out.stderr == b"",
              "`charter.cmd check --context .` passes its report and exit status, 1, through")
        out = subprocess.run(["cmd", "/c", os.path.join(bin_dir, "charter.cmd"), "check", "--context", good],
                             cwd=tmp, stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        check(out.returncode == 0 and b"Agents:        served" in out.stdout,
              "and 0 for a valid Agent Context")
        env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ.get("PATH", ""))
        out = subprocess.run("charter check --context .", cwd=good, stdin=subprocess.DEVNULL,
                             capture_output=True, env=env, shell=True, timeout=120)
        check(out.returncode == 0 and b"Agents:        served" in out.stdout,
              "installed on PATH, `charter` is found by name")
        system = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")
        out = subprocess.run(["cmd", "/c", os.path.join(bin_dir, "charter.cmd"), "check", "--context", good],
                             stdin=subprocess.DEVNULL, capture_output=True, timeout=120,
                             env=dict(os.environ, PATH=system))
        check(out.returncode == 9009 and out.stdout == b""
              and b"charter: Python 3.9 or later was not found" in out.stderr,
              "with no `py` or `python` on PATH, it says so on stderr and exits 9009, running nothing")
        for version, python in windows_pythons():
            out = subprocess.run([python, os.path.join(bin_dir, "charter.py"), "check", "--context", good],
                                 stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
            check(out.returncode == 0, f"Python {version} runs it too")
        check(not os.path.exists(state)
              and sorted(os.listdir(good)) == [".agent-context.json", "AGENT-CONTEXT.md"],
              "`charter check` created no private state and wrote nothing in the folder")
        out = subprocess.run("cgu --help", cwd=tmp, stdin=subprocess.DEVNULL, capture_output=True,
                             env=dict(os.environ, PATH=bin_dir), shell=True, timeout=60)
        check(out.returncode != 0 and not os.path.exists(os.path.join(ROOT, "cgu.cmd")),
              "there is no `cgu` command")
        out = subprocess.run("acm --help", cwd=tmp, stdin=subprocess.DEVNULL, capture_output=True,
                             env=dict(os.environ, PATH=bin_dir), shell=True, timeout=60)
        check(out.returncode != 0 and b"usage:" not in out.stdout,
              "and no `acm` command: the earlier name is not an alias for Charter")


def case_no_earlier_launcher() -> None:
    print("\nCharter's launchers, and none under the earlier name")
    from tests.package import CRLF, EXECUTABLE, NAME, TOP_FILES
    from app import __version__
    launchers = ("charter", "charter.cmd", "charter.py")
    check(all(os.path.isfile(os.path.join(ROOT, n)) for n in launchers),
          "`charter`, `charter.cmd` and `charter.py` are here")
    check(not any(os.path.lexists(os.path.join(ROOT, n)) for n in ("acm", "acm.cmd", "acm.py")),
          "there is no `acm`, `acm.cmd` or `acm.py`: no alias or stub for the earlier name")
    check(NAME == f"charter-{__version__}" and set(launchers) <= set(TOP_FILES)
          and EXECUTABLE == ("charter", "charter.py") and CRLF == ("charter.cmd",)
          and not any(n.startswith("acm") for n in TOP_FILES + EXECUTABLE + CRLF),
          f"the release would be `{NAME}.zip`, carrying Charter's launchers and none named `acm`")
    attributes = os.path.join(ROOT, ".gitattributes")
    if os.path.isfile(attributes):
        with open(attributes, encoding="utf-8") as fh:
            rules = [line.split()[0] for line in fh if line.strip() and not line.startswith("#")]
        check(rules == ["charter", "charter.cmd"], "the line-ending rules name Charter's launchers")
    else:
        # An extracted release: `.gitattributes` is a source checkout's file and
        # the release does not carry it, so check what its rules protect.
        with open(os.path.join(ROOT, "charter"), "rb") as fh:
            bash = fh.read()
        with open(os.path.join(ROOT, "charter.cmd"), "rb") as fh:
            cmd = fh.read()
        check(".gitattributes" not in TOP_FILES and b"\r" not in bash
              and b"\n" not in cmd.replace(b"\r\n", b""),
              "a release without `.gitattributes` still has `charter` with LF and `charter.cmd` "
              "with CRLF line endings")
    with open(os.path.join(ROOT, "charter.py"), encoding="utf-8") as fh:
        text = fh.read()
    check("from app.__main__ import main" in text and "acm" not in text.lower().replace("charter", ""),
          "`charter.py` starts Charter, and names nothing of the earlier name")


def case_found_through_path() -> None:
    print("\nthe installed launcher, found through PATH")
    if os.name == "nt":
        print("  (on Windows, covered with `charter.cmd` above)")
        return
    bash = shutil.which("bash")
    if not bash:
        print("  skip: no bash on this computer")
        return
    with tempfile.TemporaryDirectory(prefix="charter-launch-") as tmp:
        good = valid_context(tmp)
        shim = os.path.join(tmp, "bin")
        os.mkdir(shim)
        with open(os.path.join(shim, "charter"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f'#!/bin/sh\nexec "{bash}" "{os.path.join(ROOT, "charter")}" "$@"\n')
        os.chmod(os.path.join(shim, "charter"), 0o755)
        env = dict(os.environ, PATH=shim + os.pathsep + os.environ.get("PATH", ""))
        out = subprocess.run(["charter", "check", "--context", "."], cwd=good, stdin=subprocess.DEVNULL,
                             capture_output=True, env=env, timeout=60)
        check(out.returncode == 0 and b"Agents:        served" in out.stdout,
              "`charter check --context .` by name, exit 0 for a valid Agent Context")


def case_launchers_are_executable() -> None:
    print("\nthe launchers are executable, and run by name directly")
    git = shutil.which("git")
    if git and os.path.isdir(os.path.join(ROOT, ".git")):
        listed = subprocess.run([git, "-C", ROOT, "ls-files", "-s", "--", "charter", "charter.py"],
                                capture_output=True, text=True).stdout.split("\n")
        modes = {line.split("\t")[-1]: line.split()[0] for line in listed if line.strip()}
        check(modes == {"charter": "100755", "charter.py": "100755"},
              f"Git records `charter` and `charter.py` as executable, 100755 (got {modes})")
    else:
        print("  (not a Git checkout: the release check covers the archived modes)")
    if os.name == "nt":
        print("  (on Windows, `charter.cmd` needs no executable mode)")
        return
    check(all(os.access(os.path.join(ROOT, n), os.X_OK) for n in ("charter", "charter.py")),
          "`charter` and `charter.py` are executable here")
    with tempfile.TemporaryDirectory(prefix="charter-launch-") as tmp:
        good = valid_context(tmp)
        env = dict(os.environ, PATH=ROOT + os.pathsep + os.environ.get("PATH", ""))
        out = subprocess.run(["charter", "check", "--context", "."], cwd=good, stdin=subprocess.DEVNULL,
                             capture_output=True, env=env, timeout=60)
        check(out.returncode == 0 and b"Agents:        served" in out.stdout,
              "with this folder on PATH, `charter` itself runs by name, with no shell named: exit 0")


def case_symlinked_launcher() -> None:
    print("\n`charter` reached through a symlink, such as ~/.local/bin/charter")
    if os.name == "nt":
        print("  skip: Windows")
        return
    from app import on_path
    with tempfile.TemporaryDirectory(prefix="charter-launch-") as tmp:
        good = valid_context(tmp)
        absolute = os.path.join(tmp, "local bin")
        chained = os.path.join(tmp, "a b", "bin")
        middle = os.path.join(tmp, "c d")
        for d in (absolute, chained, middle):
            os.makedirs(d)
        os.symlink(os.path.join(ROOT, "charter"), os.path.join(absolute, "charter"))
        os.symlink(os.path.join(ROOT, "charter"), os.path.join(middle, "link"))
        os.symlink(os.path.join("..", "..", "c d", "link"), os.path.join(chained, "charter"))
        for label, folder in (("an absolute symlink", absolute), ("a chain with a relative link", chained)):
            env = dict(os.environ, PATH=folder + os.pathsep + os.environ.get("PATH", ""))
            out = subprocess.run(["charter", "check", "--context", "."], cwd=good,
                                 stdin=subprocess.DEVNULL, capture_output=True, env=env, timeout=60)
            check(out.returncode == 0 and b"Agents:        served" in out.stdout,
                  f"{label}, in a folder whose name has a space: charter.py is found, exit 0")
            out = subprocess.run(["charter", "add-to-path", "--check"], cwd=tmp, stdin=subprocess.DEVNULL,
                                 capture_output=True, env=env, timeout=60)
            check(out.returncode == 0 and b"a link to this copy" in out.stdout,
                  "and `add-to-path --check` counts it as this copy, exit 0")
        stray = os.path.join(absolute, "elsewhere")
        open(stray, "w").close()
        check(not on_path.is_launcher(stray, ROOT),
              "a file beside the link that is not a link to this copy is not this copy")


def case_posix_path_guidance() -> None:
    print("\nmacOS and Linux: `add-to-path` and `--check` say what to do, and change nothing")
    if os.name == "nt":
        print("  skip: Windows")
        return
    import contextlib
    import io
    from app import on_path
    with tempfile.TemporaryDirectory(prefix="charter-home-") as home:
        check(on_path.startup_file("/bin/bash", "linux", home) == "~/.bashrc"
              and on_path.startup_file("/usr/bin/zsh", "linux", home) == "~/.zshrc"
              and on_path.startup_file("/bin/zsh", "darwin", home) == "~/.zshrc"
              and on_path.startup_file("/bin/bash", "darwin", home) == "~/.bash_profile"
              and on_path.startup_file("/usr/bin/fish", "linux", home) == "",
              "the startup file a new terminal reads: ~/.bashrc, ~/.zshrc, or ~/.bash_profile for "
              "bash on macOS; none named for another shell")
        # macOS bash login shells read only the first of these that exists.
        said = []
        for rc in (".profile", ".bash_login", ".bash_profile"):
            open(os.path.join(home, rc), "w").close()
            said.append(on_path.startup_file("/bin/bash", "darwin", home))
        check(said == ["~/.profile", "~/.bash_login", "~/.bash_profile"]
              and on_path.startup_file("/bin/bash", "linux", home) == "~/.bashrc",
              "bash on macOS: the login file it reads, so an existing ~/.profile is never shadowed "
              "by a new ~/.bash_profile")
    check("~/.profile" in on_path.desktop_note("~/.bashrc", "linux")
          and "log out and back in" in on_path.desktop_note("~/.bashrc", "linux")
          and "~/.profile" not in on_path.desktop_note("~/.zshrc", "darwin"),
          "on Linux, desktop-started hosts are pointed to ~/.profile and a new login session")

    home = tempfile.mkdtemp(prefix="charter-home-")  # no startup files: each shell's default

    def run(folder: str, path: str, check_only: bool, shell: str = "/bin/bash") -> tuple:
        saved = {k: os.environ.get(k) for k in ("PATH", "SHELL", "HOME")}
        os.environ.update(PATH=path, SHELL=shell, HOME=home)
        try:
            with contextlib.redirect_stdout(io.StringIO()) as said:
                code = on_path.main(check_only, folder=folder)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        return code, said.getvalue()

    with tempfile.TemporaryDirectory(prefix="charter-path-") as tmp:
        odd = os.path.join(tmp, 'Tools $HOME "q" `x` \\ é')
        os.makedirs(odd)
        launcher = os.path.join(odd, "charter")
        shutil.copyfile(os.path.join(ROOT, "charter"), launcher)
        os.chmod(launcher, 0o644)
        before = sorted(os.listdir(odd)), os.environ.get("PATH")

        code, said = run(odd, "/usr/bin:/bin", False)
        line = on_path.export_line(odd)
        macos = sys.platform == "darwin"
        rc = "~/.bash_profile" if macos else "~/.bashrc"
        note = "Dock or Finder" if macos else "~/.profile"
        check(code == 1 and "does not change PATH or edit shell startup files" in said
              and f"add this line to {rc}" in said and line in said and note in said
              and "chmod +x " + shlex.quote(launcher) in said,
              f"`add-to-path`, off PATH: exit 1, the export line for {rc}, the desktop note naming "
              f"{note}, and the chmod its non-executable launcher needs")
        interpreted = on_path.this_copy(odd, ["add-to-path", "--check"], windows=False)
        check(interpreted == " ".join(shlex.quote(a) for a in (
                  os.path.abspath(sys.executable), os.path.join(odd, "charter.py"), "add-to-path", "--check"))
              and "\n    " + interpreted + "\n" in said and "`charter add-to-path" not in said,
              "while the launcher is not executable, the check to run afterwards is this Python with "
              "this copy's charter.py, each by its full path")
        code, said = run(odd, "/usr/bin:/bin", False, shell="/usr/bin/zsh")
        check("add this line to ~/.zshrc" in said and "~/.bashrc" not in said,
              "for zsh, the line goes in ~/.zshrc")
        code, said = run(odd, odd + ":/usr/bin:/bin", True)
        check(code == 1 and "This shell's PATH:    includes it" in said
              and f"nothing: {launcher} is not executable" in said and "chmod +x" in said
              and "is not found" not in said,
              "`--check`, on PATH but not executable: exit 1, naming the file and the chmod, "
              "not `not found`")
        os.chmod(launcher, 0o755)
        code, said = run(odd, "/usr/bin:/bin", True)
        check(code == 1 and "does not include it" in said
              and "\n    " + shlex.quote(launcher) + " add-to-path\n" in said
              and "python3 charter.py" not in said,
              "`--check`, off PATH: exit 1, and this copy's launcher, by its full path, for the line to add")
        code, said = run(odd, odd + ":/usr/bin:/bin", True)
        check(code == 0 and f"This shell runs:      {launcher}" in said,
              "`--check`, on PATH and executable: exit 0")
        code, said = run(odd, odd + ":/usr/bin:/bin", False)
        check(code == 0 and "already runs this copy" in said,
              "`add-to-path` when this shell already runs it: exit 0, nothing to add")
        check((sorted(os.listdir(odd)), os.environ.get("PATH")) == before,
              "nothing was written, and this process's PATH is as it was")

        shells = [s for s in ("bash", "zsh", "sh") if shutil.which(s)]
        for name in shells:
            out = subprocess.run([shutil.which(name) or name, "-c", line + '; printf %s "${PATH%%:*}"'],
                                 env=dict(os.environ, PATH="/usr/bin:/bin"), capture_output=True)
            check(out.returncode == 0 and out.stdout.decode("utf-8") == odd,
                  f"{name}: the export line puts the folder first on PATH exactly, "
                  "with its space, $, quotes, backquote and backslash")
        if "zsh" not in shells:
            print("  (zsh is not installed here: the line uses only syntax bash, zsh and sh share)")
    shutil.rmtree(home, ignore_errors=True)


def case_check_is_read_only() -> None:
    print("\n`charter check` changes nothing")
    sys.path.insert(0, ROOT)
    from app import agent_context as ac
    from app import authority as au
    from app import transaction as tx
    from app.__main__ import main
    from tests.harness import isolated_private_state, seeded
    import contextlib
    import io

    with isolated_private_state() as root, tempfile.TemporaryDirectory(prefix="charter-check-") as tmp:
        good = valid_context(tmp)
        with contextlib.redirect_stdout(io.StringIO()) as said:
            code = main(["check", "--context", good])
        check(code == 0 and "Agents:        served" in said.getvalue() and not os.path.exists(root),
              "a valid Agent Context: exit 0, and no private state is created")

        # An interrupted write, left for recovery: check reports it, and recovers nothing.
        a = au.plan(good, "add", {"title": "New", "body": "x\n"})
        au.apply(good, "add", a.request, a.plan_id, True)
        g = au.plan(good, "changeset", seeded(good, {"alongside": "authority-candidates/new.md"}))

        class Crash(BaseException):
            pass

        def fault(step: str) -> None:
            if step == "replace:AGENT-CONTEXT.md":
                raise Crash()
        try:
            au.apply(good, "changeset", g.request, g.plan_id, au.CONFIRM_PHRASE, fault=fault)
        except Crash:
            pass
        before = {n: open(os.path.join(dp, n), "rb").read()
                  for dp, _d, files in os.walk(good) for n in files}
        with contextlib.redirect_stdout(io.StringIO()) as said:
            code = main(["check", "--context", good])
        after = {n: open(os.path.join(dp, n), "rb").read()
                 for dp, _d, files in os.walk(good) for n in files}
        from app import private_store as ps
        cs = ps.PrivateState.default().find_context(good)
        check(code == 1 and "interrupted" in said.getvalue() and before == after and tx.interrupted(cs),
              "an interrupted write is reported, exit 1, and left for recovery: nothing changed")
        check(not ac.examine(good).valid, "the folder is still as the interruption left it")


class FakeRegistry:
    """The user's and the computer's persistent PATH, held in memory."""

    def __init__(self, user, kind, machine=""):
        self.user, self.kind, self.machine = user, kind, machine
        self.writes, self.announced = 0, 0

    def user_path(self):
        return self.user, self.kind

    def set_user_path(self, value, kind):
        self.user, self.kind, self.writes = value, kind, self.writes + 1

    def machine_path(self):
        return self.machine

    def announce(self):
        self.announced += 1
        return True


def case_add_to_path_edits_the_user_path() -> None:
    print("\n`charter add-to-path` appends the launchers' folder to the user's PATH, once")
    if os.name != "nt":
        print("  skip: not Windows")
        return
    import winreg
    from app import on_path
    folder = os.path.join(tempfile.gettempdir(), "Charter release", "charter")
    reg = FakeRegistry("", winreg.REG_EXPAND_SZ)
    check(on_path.add(folder, reg) == (True, folder) and reg.kind == winreg.REG_EXPAND_SZ
          and reg.announced == 1, "an empty user PATH becomes the folder, and the change is announced")
    reg = FakeRegistry(r"C:\a;C:\b;", winreg.REG_SZ)
    on_path.add(folder, reg)
    check(reg.user == rf"C:\a;C:\b;{folder}" and reg.kind == winreg.REG_SZ,
          "an existing PATH keeps its entries, order and value type; the folder goes last")
    check(on_path.add(folder, reg)[0] is False and reg.writes == 1, "a second run changes nothing")
    for same in (folder.upper() + "\\", f'"{folder}"',
                 folder.replace(tempfile.gettempdir(), "%TEMP%")):
        reg = FakeRegistry(rf"C:\a;{same}", winreg.REG_EXPAND_SZ)
        on_path.add(folder, reg)
        check(reg.writes == 0, f"already present as {same!r}: nothing written")


def case_fresh_discovery_of_the_release() -> None:
    print("\nafter `charter add-to-path`, a new PowerShell finds the release's `charter` from any folder")
    if os.name != "nt":
        print("  skip: not Windows")
        return
    import contextlib
    import io
    import winreg
    from app import on_path
    from tests.package import NAME, members, release_file
    powershell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                              "WindowsPowerShell", "v1.0", "powershell.exe")
    with tempfile.TemporaryDirectory(prefix="charter-launch-") as tmp:
        # The release as a person unpacks it, outside this checkout, under a
        # folder whose name has a space.
        release = os.path.join(tmp, "Charter release", NAME)
        for rel in members():
            target = os.path.join(release, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(release_file(rel))
        reg = FakeRegistry(r"C:\NoSuchTools", winreg.REG_EXPAND_SZ, on_path.Registry().machine_path())
        check(on_path.resolve("charter", on_path.fresh_path(reg)) is None,
              "before: a new program finds no `charter`")
        with contextlib.redirect_stdout(io.StringIO()) as said:
            code = on_path.main(False, folder=release, registry=reg)
        check(code == 0 and "quit and reopen" in said.getvalue() and "`charter`" in said.getvalue()
              and "cgu" not in said.getvalue(),
              "`add-to-path` succeeds and says running agent hosts must be reopened")
        out = io.StringIO()
        check(on_path.report(release, reg, out) == 0 and "charter.cmd" in out.getvalue(),
              "`add-to-path --check` agrees")

        env = dict(os.environ, PATH=on_path.fresh_path(reg))
        good = valid_context(tmp)

        def ps(script: str) -> subprocess.CompletedProcess:
            return subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script],
                                  cwd=good, env=env, stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=120)

        found = ps("(Get-Command charter).Source").stdout.decode("utf-8", "replace").strip()
        check(os.path.normcase(found) == os.path.normcase(os.path.join(release, "charter.cmd")),
              f"`Get-Command charter` is the release's charter.cmd (got {found!r})")
        out = ps("charter check --context .; exit $LASTEXITCODE")
        check(out.returncode == 0 and b"Agents:        served" in out.stdout,
              "`charter check --context .` runs the release from the Agent Context's folder, exit 0")
        missing = ps("Get-Command cgu -ErrorAction SilentlyContinue | Where-Object { $_.Source -like '*"
                     + NAME + "*' }")
        check(missing.stdout.strip() == b"", "and the release provides no `cgu`")

        other = os.path.join(tmp, "other")
        os.mkdir(other)
        with open(os.path.join(other, "charter.cmd"), "w", encoding="utf-8") as fh:
            fh.write("@echo off\r\n")
        reg.machine = other + ";" + reg.machine
        out = io.StringIO()
        check(on_path.report(release, reg, out) == 1 and "Another `charter` comes first" in out.getvalue(),
              "a different `charter` earlier on PATH is reported, not passed over")
        said = out.getvalue()
        check(f"Remove {other} from your PATH" in said and "`charter add-to-path`" not in said
              and "use that copy" not in said and "from that copy" not in said,
              "and the fix is to remove that folder from PATH, never a bare `charter` command")


def displayed(said: str) -> list:
    """The commands a message gives to copy: each on a line of its own, indented."""
    return [line[4:] for line in said.splitlines() if line.startswith("    ") and line.strip()]


def bare(command: str, *full: str) -> bool:
    """Whether a command, its full paths taken out, still runs something by
    name: `py`, `python`, `python3`, `charter` or `cmd /c`."""
    for path in sorted(full, key=len, reverse=True):
        command = command.replace(path, "")
    return bool(re.search(r"(^|[\s&'\"])(py|python3?|charter|cmd)(\.exe)?(\s|$)|/c\b", command))


def case_path_remedies_use_full_paths() -> None:
    print("\n`add-to-path` and `--check` give remedies that run this copy by its full paths")
    sys.path.insert(0, ROOT)
    import contextlib
    import io
    from app import connect, on_path
    folder = os.path.join(tempfile.gettempdir(), "Charter release's copy", "charter 2")
    python = os.path.join(tempfile.gettempdir(), "Py Thon 3", "python.exe")
    script = os.path.join(folder, "charter.py")
    launcher = os.path.join(folder, "charter")

    win = on_path.this_copy(folder, ["add-to-path", "--check"], windows=True, python=python)
    check(win == "& " + " ".join(on_path.powershell_arg(a) for a in (python, script, "add-to-path", "--check"))
          and win.startswith("& '" + python + "' '" + script.replace("'", "''") + "' ")
          and not bare(win, on_path.powershell_arg(python), on_path.powershell_arg(script)),
          "Windows: the Python running Charter and this copy's charter.py, each by its full path and "
          "quoted for PowerShell, spaces and all, run with `&`")
    posix = on_path.this_copy(folder, ["add-to-path"], windows=False, python=python)
    check(posix == shlex.quote(launcher) + " add-to-path" and not bare(posix, shlex.quote(launcher)),
          "macOS and Linux: this copy's launcher by its full path, quoted for the shell")
    for windows in (True, False):
        for already in (True, False):
            text = on_path.earlier_copy(os.path.join("C:\\Old" if windows else "/old", "charter"),
                                        folder, already, windows=windows)
            commands = displayed(text)
            check(len(commands) == (1 if already else 2)
                  and all(c == on_path.this_copy(folder, c.split()[-1:] if c.endswith("add-to-path")
                                                 else ["add-to-path", "--check"], windows)
                          for c in commands)
                  and all(not bare(c, on_path.powershell_arg(on_path.interpreter()), on_path.powershell_arg(script),
                                   shlex.quote(launcher)) for c in commands)
                  and not re.search(r"`(charter add-to-path|py |python3? )", text),
                  f"{'Windows' if windows else 'elsewhere'}, {'on PATH' if already else 'not on PATH'}: "
                  "another copy first is answered with this copy's own full-path commands only")

    if os.name != "nt":
        print("  skip: `--check` against the registry is Windows only")
        return
    import winreg
    with tempfile.TemporaryDirectory(prefix="charter-remedy-") as tmp:
        here = os.path.join(tmp, "Charter release's copy", "charter 2")
        os.makedirs(here)
        with open(os.path.join(here, "charter.cmd"), "w", encoding="utf-8") as fh:
            fh.write("@echo off\r\n")
        other = os.path.join(tmp, "other")
        os.mkdir(other)
        with open(os.path.join(other, "charter.cmd"), "w", encoding="utf-8") as fh:
            fh.write("@echo off\r\n")
        listing = sorted(os.listdir(here)), os.environ.get("PATH")
        mine = os.path.join(here, "charter.py")
        for label, reg, already in (
                ("`charter` not found", FakeRegistry(r"C:\NoSuchTools", winreg.REG_EXPAND_SZ), False),
                ("another copy first, this one off PATH", FakeRegistry(other, winreg.REG_EXPAND_SZ), False),
                ("another copy first, this one on PATH too",
                 FakeRegistry(other + ";" + here, winreg.REG_EXPAND_SZ), True)):
            out = io.StringIO()
            code = on_path.report(here, reg, out)
            said = out.getvalue()
            commands = displayed(said)
            put = on_path.this_copy(here, ["add-to-path"], windows=True)
            check(code == 1 and reg.writes == 0 and reg.announced == 0
                  and (put in commands) == (not already) and commands
                  and all(not bare(c, on_path.powershell_arg(on_path.interpreter()), on_path.powershell_arg(mine))
                          for c in commands)
                  and "in PowerShell:" in said and "`charter add-to-path" not in said,
                  f"`--check`, {label}: exit 1, nothing written or announced, and every command given "
                  "runs this Python with this copy's charter.py by full path")
        reg = FakeRegistry(r"C:\NoSuchTools", winreg.REG_EXPAND_SZ)
        with contextlib.redirect_stdout(io.StringIO()):
            on_path.main(True, folder=here, registry=reg)
        check(reg.writes == 0 and reg.announced == 0 and (sorted(os.listdir(here)), os.environ.get("PATH")) == listing,
              "`add-to-path --check` writes nothing: no PATH, no announcement, no file")
        with contextlib.redirect_stdout(io.StringIO()) as said:
            code = on_path.main(False, folder=here, registry=FakeRegistry(other, winreg.REG_EXPAND_SZ))
        commands = [c for c in displayed(said.getvalue()) if "add-to-path" in c]
        check(code == 1 and len(commands) == 2
              and all(c == on_path.this_copy(here, ["add-to-path", "--check"], windows=True) for c in commands),
              "`add-to-path`, with another copy first: the checks it gives run this copy by full path")
        with found_nowhere() as nowhere:
            check(connect.command_status(windows=True, registry=nowhere, launchers=here)["remedy"]
                  == on_path.this_copy(here, ["add-to-path"], windows=True),
                  "the Charter command dialog gives the same command as `--check`")


class found_nowhere:
    """A registry under which no new program finds `charter`."""

    def __enter__(self):
        import winreg
        return FakeRegistry(r"C:\NoSuchTools", winreg.REG_EXPAND_SZ)

    def __exit__(self, *exc):
        return False


def case_windows_remedy_runs_in_powershell() -> None:
    print("\nthe remedies `--check` displays run in a real PowerShell exactly as shown")
    if os.name != "nt":
        print("  skip: not Windows")
        return
    import io
    import json
    import winreg
    from app import on_path
    from tests.package import NAME, members, release_file
    powershell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                              "WindowsPowerShell", "v1.0", "powershell.exe")
    real = on_path.Registry()

    def ps(line: str) -> subprocess.CompletedProcess:
        return subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command",
                               "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + line + "; exit $LASTEXITCODE"],
                              cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=120)

    before = real.user_path()
    with tempfile.TemporaryDirectory(prefix="charter-ps-") as tmp:
        # A stand-in charter.py that says what it was given, so the displayed
        # `add-to-path` runs as shown and changes no PATH.
        stand_in = os.path.join(tmp, "Stand in's copy", "charter 2")
        os.makedirs(stand_in)
        with open(os.path.join(stand_in, "charter.py"), "w", encoding="utf-8") as fh:
            fh.write("import json, os, sys\n"
                     "print(json.dumps([os.path.abspath(sys.executable), os.path.abspath(__file__)] + sys.argv[1:]))\n")
        out = io.StringIO()
        on_path.report(stand_in, FakeRegistry(r"C:\NoSuchTools", winreg.REG_EXPAND_SZ), out)
        shown = [c for c in displayed(out.getvalue()) if c.endswith(" add-to-path")]
        check(len(shown) == 1, f"`--check` displays one `add-to-path` command: {shown}")
        done = ps(shown[0])
        got = json.loads(done.stdout.decode("utf-8") or "null")
        check(done.returncode == 0 and got == [os.path.abspath(sys.executable),
                                               os.path.join(stand_in, "charter.py"), "add-to-path"],
              f"PowerShell runs this Python with this copy's charter.py and `add-to-path`, exactly: {shown[0]}")

        # The release as unpacked, under a path with a space and an apostrophe:
        # its displayed `--check` runs for real, and reads only.
        release = os.path.join(tmp, "Charter release's copy", NAME)
        for rel in members():
            target = os.path.join(release, *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(release_file(rel))
        listing = sorted(os.path.join(dp, n) for dp, _d, files in os.walk(release) for n in files)
        os.mkdir(os.path.join(tmp, "other"))
        with open(os.path.join(tmp, "other", "charter.cmd"), "w", encoding="utf-8") as fh:
            fh.write("@echo off\r\n")
        out = io.StringIO()
        on_path.report(release, FakeRegistry(os.path.join(tmp, "other"), winreg.REG_EXPAND_SZ), out)
        shown = [c for c in displayed(out.getvalue()) if c.endswith(" add-to-path --check")]
        check(len(shown) == 1, f"`--check` displays one check to run afterwards: {shown}")
        done = ps(shown[0])
        said = done.stdout.decode("utf-8", "replace")
        check(done.returncode in (0, 1) and f"Launchers:            {release}" in said
              and "Your user PATH:" in said,
              f"PowerShell runs this copy's own `--check`, by its full paths: {shown[0]}")
        after = sorted(os.path.join(dp, n) for dp, _d, files in os.walk(release) for n in files
                       if "__pycache__" not in dp)
        check(after == [p for p in listing if "__pycache__" not in p] and real.user_path() == before,
              "and it wrote nothing: the release's files and the real user PATH are as they were")


def case_identity() -> None:
    print("\n`charter --version`, and `charter check`, say which copy of Charter this is")
    sys.path.insert(0, ROOT)
    from app import __version__
    from app import agent_context as ac
    from app import identity
    from tests.package import NAME, members, release_file

    def version_of(charter_py: str) -> tuple:
        done = subprocess.run([sys.executable, charter_py, "--version"], stdin=subprocess.DEVNULL,
                              capture_output=True, timeout=60)
        return done.returncode, done.stdout.decode("utf-8", "replace")

    git_dir = os.path.join(ROOT, ".git")
    if os.path.isfile(git_dir):  # a worktree's `.git` names its own Git folder
        with open(git_dir, encoding="utf-8") as fh:
            pointed = fh.read().strip().split("gitdir:", 1)[-1].strip()
        git_dir = pointed if os.path.isabs(pointed) else os.path.join(ROOT, pointed)
    index = os.path.join(git_dir, "index") if os.path.isfile(os.path.join(git_dir, "index")) else None
    before = open(index, "rb").read() if index else None
    code, said = version_of(os.path.join(ROOT, "charter.py"))
    lines = said.splitlines()
    check(code == 0 and lines[0] == f"Charter {__version__}"
          and f"launcher     {os.path.join(ROOT, 'charter.cmd' if os.name == 'nt' else 'charter')}" in said
          and f"charter.py   {os.path.join(ROOT, 'charter.py')}" in said
          and f"python       {os.path.abspath(sys.executable)}" in said
          and f"map format   {ac.MAP_FORMAT_VERSION} (generated by this Charter)" in said,
          "exit 0: the version, launcher, charter.py, Python and map format, each by its full path")
    if identity.development_checkout(ROOT):
        check("build        development checkout" in said
              and ("commit unavailable" in said or re.search(r"commit [0-9a-f]{7,}, (dirty: uncommitted changes|clean)", said)),
              "this checkout says it is a development checkout, with its commit and whether it is dirty")
    if index:
        check(open(index, "rb").read() == before and not os.path.exists(os.path.join(git_dir, "index.lock")),
              "asking Git who this checkout is writes nothing: the index is byte for byte the same, and no lock is left")

    with tempfile.TemporaryDirectory(prefix="charter id ") as tmp:
        release = os.path.join(tmp, "Program Files", NAME)
        bare = os.path.join(tmp, "copied by hand")
        for rel in members():
            for where in (release, bare):
                if where == bare and rel.endswith("build.json"):
                    continue
                target = os.path.join(where, *rel.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "wb") as fh:
                    fh.write(release_file(rel))
        code, said = version_of(os.path.join(release, "charter.py"))
        check(code == 0 and re.search(r"build        release, built \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", said)
              and f"launcher     {os.path.join(release, 'charter.cmd' if os.name == 'nt' else 'charter')}" in said,
              "a release, in a folder with spaces, reports its build time and its own launcher")
        code, said = version_of(os.path.join(bare, "charter.py"))
        check(code == 0 and "build        unknown build" in said,
              "a copy with no build record and no checkout says its build is unknown, rather than guessing")
        context = valid_context(tmp)
        done = subprocess.run([sys.executable, os.path.join(release, "charter.py"), "check", "--context", context],
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=60)
        out = done.stdout.decode("utf-8", "replace")
        check(done.returncode == 0 and f"Charter {__version__}" in out and "build        release" in out
              and f"context map  {ac.MAP_FORMAT_VERSION} (the format this Charter generates)" in out,
              "`charter check` reports the same identity, with the map format the Agent Context records")


def case_shorthand_through_launchers() -> None:
    """The person's shorthand, `charter <absolute folder> …`, reaches Charter
    through each launcher and shell with its folder intact — spaces included —
    and answers exactly as `charter read --context` does."""
    print("\nthe shorthand through each launcher and shell")
    with tempfile.TemporaryDirectory(prefix="charter launch ") as tmp:
        state = os.path.join(tmp, "state")
        good = valid_context(os.path.join(tmp, "with space"))
        direct = [sys.executable, os.path.join(ROOT, "charter.py")]
        want = subprocess.run(direct + ["read", "--context", good, "--list"],
                              stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
        check(want.returncode == 0 and want.stdout.endswith(b"<<<END CHARTER READ>>>\n"),
              "`charter read --context <folder with a space> --list` serves")
        out = subprocess.run(direct + [good, "--list"], stdin=subprocess.DEVNULL,
                             capture_output=True, timeout=120)
        check((out.returncode, out.stdout, out.stderr) == (0, want.stdout, b""),
              "`python charter.py <folder> --list`: the same bytes and exit code")
        if os.name == "nt":
            from tests.package import release_bytes
            bin_dir = os.path.join(tmp, "bin")
            os.mkdir(bin_dir)
            with open(os.path.join(ROOT, "charter.cmd"), "rb") as fh:
                launcher = release_bytes("charter.cmd", fh.read())
            with open(os.path.join(bin_dir, "charter.cmd"), "wb") as fh:
                fh.write(launcher)
            with open(os.path.join(bin_dir, "charter.py"), "w", encoding="utf-8") as fh:
                fh.write(SHIM.format(root=ROOT, state=state))
            env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ.get("PATH", ""))
            # Command Prompt, as a person types it: the folder quoted.
            out = subprocess.run(f'charter "{good}" --list', cwd=tmp, stdin=subprocess.DEVNULL,
                                 capture_output=True, env=env, shell=True, timeout=120)
            check((out.returncode, out.stdout, out.stderr) == (0, want.stdout, b""),
                  'Command Prompt: `charter "C:\\…\\with space\\context" --list` answers exactly '
                  "as `charter read --context` does")
            slashed = good.replace("\\", "/")
            out = subprocess.run(f'charter "{slashed}" --list', cwd=tmp, stdin=subprocess.DEVNULL,
                                 capture_output=True, env=env, shell=True, timeout=120)
            check(out.returncode == 0 and out.stdout == want.stdout,
                  "  and with forward slashes, `C:/…/context`")
            out = subprocess.run("charter context --list", cwd=os.path.dirname(good),
                                 stdin=subprocess.DEVNULL, capture_output=True, env=env, shell=True,
                                 timeout=120)
            check(out.returncode == 2 and out.stdout == b"" and out.stderr.startswith(
                b"context is not a command or a full path."),
                  "  a relative folder name gets the hint and exit 2, even run from beside it")
            powershell = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32",
                                      "WindowsPowerShell", "v1.0", "powershell.exe")
            quoted = "'" + good.replace("'", "''") + "'"
            out = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command",
                                  f"charter {quoted} --list; exit $LASTEXITCODE"],
                                 cwd=tmp, stdin=subprocess.DEVNULL, capture_output=True, env=env,
                                 timeout=120)
            check(out.returncode == 0 and out.stdout.replace(b"\r\n", b"\n") == want.stdout,
                  "PowerShell: `charter 'C:\\…\\with space\\context' --list` answers the same, exit 0")
            check(not os.path.exists(state), "  none of them created private state")
        bash = find_bash()
        if not bash:
            print("  skip: no bash on this computer")
            return
        charter = unix_path(bash, os.path.join(ROOT, "charter"))
        for form, label in ((unix_path(bash, good), "a POSIX path"),) + (
                ((good, "a quoted Windows path"),) if os.name == "nt" else ()):
            out = run_bash(bash, f'"{charter}" "{form}" --list', dict(os.environ))
            check(out.returncode == 0 and out.stdout == want.stdout and out.stderr == b"",
                  f"Bash: `charter` with {label} that holds a space answers exactly as `charter read "
                  "--context` does")


def run() -> None:
    case_bash_launcher()
    case_cmd_launcher()
    case_shorthand_through_launchers()
    case_no_earlier_launcher()
    case_found_through_path()
    case_launchers_are_executable()
    case_symlinked_launcher()
    case_posix_path_guidance()
    case_check_is_read_only()
    case_add_to_path_edits_the_user_path()
    case_fresh_discovery_of_the_release()
    case_path_remedies_use_full_paths()
    case_windows_remedy_runs_in_powershell()
    case_identity()
    print(f"\n{OK} All launcher checks passed.")


if __name__ == "__main__":
    run()
