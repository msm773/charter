"""`charter add-to-path`: make `charter` a command this user's new programs can run.

    charter add-to-path            Windows: put the launchers' folder on this user's PATH;
                                   macOS and Linux: say what line to add, and where
    charter add-to-path --check    say what a newly started program runs as `charter`

The context map tells agents to run `charter propose --context .`, so `charter` must be
found by name, from any folder, in the shells agent hosts start. Nothing else
puts it there: a release is an unpacked folder, and the launchers in it are
found only once that folder is on PATH.

On Windows the folder is appended to the user's `Path` in the registry (its
value type kept), and the change is broadcast so programs started afterwards
see it. A program that is already running keeps the environment it started
with, and passes that on to what it starts: a terminal, VS Code, Claude or
Codex must be quit and reopened before their agent sessions can run `charter`.

Elsewhere Charter changes neither PATH nor any file: it prints the `export`
line to add and the shell startup file to add it to. A terminal reads that file
when it opens; a program started from the desktop may not, and on many Linux
desktops gets PATH from `~/.profile`, which is read only at login. There, both
forms exit 0 only when this shell already runs this copy as `charter`, so 1
means something is left to do, and the output says what.
"""
from __future__ import annotations

import os
import shlex
import sys
from typing import Any, List, Optional, Tuple

# The folder that holds the launchers `charter`, `charter.cmd` and `charter.py`.
LAUNCHERS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The command this copy's launchers provide.
NAME = "charter"

USER_KEY = "Environment"
MACHINE_KEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"

RESTART = """`charter` is found by programs started from now on. Programs already running keep
the PATH they started with, and so do the terminals and agents they start:

  - open a new terminal window;
  - quit and reopen VS Code, Claude, Codex or any other agent host (every
    window), so that their agent sessions can run `charter`.

Then `charter add-to-path --check` says what a new program runs as `charter`."""


# --- PATH values ----------------------------------------------------------------

def _expand(value: str) -> str:
    """A PATH entry as the system reads it: Windows expands `%VAR%` in the
    registry's PATH, but a POSIX shell takes each entry literally, `$` included."""
    if os.name == "nt":
        import winreg
        return winreg.ExpandEnvironmentStrings(value)
    return value


def _same(entry: str, folder: str) -> bool:
    def norm(p: str) -> str:
        p = _expand(p.strip().strip('"'))
        return os.path.normcase(os.path.normpath(p)) if p else ""
    return bool(entry.strip()) and norm(entry) == norm(folder)


def entries(value: str) -> List[str]:
    return [e for e in value.split(os.pathsep) if e.strip()]


def contains(value: str, folder: str) -> bool:
    return any(_same(e, folder) for e in entries(value))


def appended(value: str, folder: str) -> str:
    """`value` with `folder` last, unless it is already there."""
    if contains(value, folder):
        return value
    kept = value.rstrip(os.pathsep)
    return f"{kept}{os.pathsep}{folder}" if kept else folder


def resolve(name: str, path_value: str, pathext: str = "") -> Optional[str]:
    """What a shell started with `path_value` runs as `name`: the first match in
    PATH order. Unlike `shutil.which` before Python 3.12, never the current
    folder, which a new shell does not search."""
    exts = [""]
    if os.name == "nt":
        exts = [e.lower() for e in (pathext or os.environ.get("PATHEXT") or DEFAULT_PATHEXT).split(";")
                if e]
    for entry in entries(path_value):
        folder = _expand(entry.strip().strip('"'))
        for ext in exts:
            candidate = os.path.join(folder, name + ext)
            if os.path.isfile(candidate) and (os.name == "nt" or os.access(candidate, os.X_OK)):
                return candidate
    return None


def not_executable(name: str, path_value: str) -> Optional[str]:
    """Outside Windows: the first file named `name` on PATH that shells pass over
    because it is not executable, or None. A shell that finds only such a file
    says `Permission denied` rather than running it."""
    if os.name == "nt":
        return None
    for entry in entries(path_value):
        candidate = os.path.join(_expand(entry.strip().strip('"')), name)
        if os.path.isfile(candidate) and not os.access(candidate, os.X_OK):
            return candidate
    return None


def is_launcher(found: Optional[str], folder: str) -> bool:
    """Whether `found` is this folder's launcher: in it, or, outside Windows, a
    symlink to it, such as ~/.local/bin/charter, which the launcher follows."""
    if not found:
        return False
    if _same(os.path.dirname(found), folder):
        return True
    return os.name != "nt" and os.path.realpath(found) == os.path.realpath(os.path.join(folder, NAME))


# --- the Windows registry -------------------------------------------------------

class Registry:
    """This user's and this computer's persistent environment."""

    def user_path(self) -> Tuple[str, int]:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_KEY) as key:
            try:
                value, kind = winreg.QueryValueEx(key, "Path")
            except FileNotFoundError:
                return "", winreg.REG_EXPAND_SZ
        return str(value), kind

    def set_user_path(self, value: str, kind: int) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_KEY, 0,
                            winreg.KEY_READ | winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Path", 0, kind, value)

    def machine_path(self) -> str:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, MACHINE_KEY) as key:
                return str(winreg.QueryValueEx(key, "Path")[0])
        except OSError:
            return ""

    def announce(self) -> bool:
        """Tell running programs, Explorer among them, that the environment
        changed, so the programs they start from now on get the new PATH."""
        try:
            import ctypes
            from ctypes import wintypes
            result = wintypes.DWORD()
            sent = ctypes.windll.user32.SendMessageTimeoutW(
                0xFFFF, 0x001A, 0, "Environment", 0x0002, 5000, ctypes.byref(result))
            return bool(sent)
        except Exception:  # noqa: BLE001 - the PATH is saved either way
            return False


def fresh_path(registry: Any) -> str:
    """The PATH Windows gives a newly started program: the computer's, then
    the user's."""
    return os.pathsep.join(v for v in (registry.machine_path(), registry.user_path()[0]) if v)


def add(folder: str = LAUNCHERS, registry: Any = None) -> Tuple[bool, str]:
    """Append `folder` to the user's PATH. Returns (changed, the new value)."""
    registry = registry or Registry()
    value, kind = registry.user_path()
    if contains(value, folder):
        return False, value
    new = appended(value, folder)
    registry.set_user_path(new, kind)
    registry.announce()
    return True, new


# --- macOS and Linux: what to add, and where -------------------------------------

def startup_file(shell: str = "", platform: str = "") -> str:
    """The file a new terminal of this user's shell reads: `~/.zshrc` for zsh;
    for bash `~/.bashrc`, or `~/.bash_profile` on macOS, whose terminals start
    login shells that do not read `~/.bashrc`. "" for any other shell."""
    name = os.path.basename(shell or os.environ.get("SHELL", ""))
    if name == "zsh":
        return "~/.zshrc"
    if name == "bash":
        return "~/.bash_profile" if (platform or sys.platform) == "darwin" else "~/.bashrc"
    return ""


def export_line(folder: str) -> str:
    """The line to add. The folder is double-quoted so `$PATH` still expands, with
    its own backslash, quote, `$` and backquote escaped: the same in bash and zsh."""
    quoted = "".join("\\" + c if c in '\\"$`' else c for c in folder)
    return f'export PATH="{quoted}:$PATH"'


def desktop_note(rc: str, platform: str = "") -> str:
    if (platform or sys.platform) == "darwin":
        return (f"Apps started from the Dock or Finder may not read {rc}. If an agent host there "
                "cannot run `charter`, quit it and start it from a new terminal.")
    return (f"Agent hosts started from the desktop rather than a terminal may not read {rc}. On many "
            "Linux desktops they get PATH from ~/.profile, which is read only when you log in: add "
            "the line there too, then log out and back in.")


def _blockers(folder: str, now: Optional[str], path_value: str) -> List[str]:
    """What stops this shell running this copy as `charter`, other than the
    folder being missing from PATH, each with what to do."""
    found = []
    if os.pathsep in folder:
        found.append(f"This folder's path contains `{os.pathsep}`, which separates PATH entries, so it "
                     "cannot be put on PATH. Move or rename the folder, then run this again.")
    own = os.path.join(folder, NAME)
    if os.path.isfile(own) and not os.access(own, os.X_OK):
        found.append("This copy's `charter` launcher is not executable, so shells pass over it "
                     "(running it says `Permission denied`). Make it executable:\n\n"
                     f"    chmod +x {shlex.quote(own)}")
    if now and not is_launcher(now, folder) and contains(path_value, folder):
        found.append(f"Another `charter` comes first on PATH: {now}. Remove {os.path.dirname(now)} "
                     "from PATH, or use that copy.")
    return found


def _report_posix(folder: str, now: Optional[str], path_value: str, out: Any) -> int:
    blocked = not_executable(NAME, path_value)
    runs = now or (f"nothing: {blocked} is not executable" if blocked
                   else "nothing: `charter` is not found")
    if is_launcher(now, folder) and not _same(os.path.dirname(now or ""), folder):
        runs += ", a link to this copy"
    print(f"This shell's PATH:    {'includes it' if contains(path_value, folder) else 'does not include it'}",
          file=out)
    print(f"This shell runs:      {runs}", file=out)
    if is_launcher(now, folder):
        return 0
    todo = _blockers(folder, now, path_value)
    if not contains(path_value, folder) and os.pathsep not in folder:
        todo.append("Run `python3 charter.py add-to-path` in this folder for the line to add to your "
                    "shell startup file.")
    for item in todo:
        print(f"\n{item}", file=out)
    return 1


def _guide_posix(folder: str) -> int:
    """`add-to-path` outside Windows: say what to do, change nothing."""
    path_value = os.environ.get("PATH", "")
    now = resolve(NAME, path_value)
    if is_launcher(now, folder):
        print(f"This shell already runs this copy as `charter`: {now}\nNothing to add.")
        return 0
    print("On macOS and Linux, Charter does not change PATH or edit shell startup files.")
    todo = _blockers(folder, now, path_value)
    if not contains(path_value, folder) and os.pathsep not in folder:
        rc = startup_file()
        where = rc or "your shell's startup file (~/.bashrc for bash, ~/.zshrc for zsh)"
        todo.append(f"To run `charter` from any folder, add this line to {where}:\n\n"
                    f"    {export_line(folder)}\n\n"
                    "Then open a new terminal, restart any agent host, and run "
                    "`charter add-to-path --check`.\n\n" + desktop_note(rc or "that file"))
    for item in todo:
        print(f"\n{item}")
    return 1


# --- the command ------------------------------------------------------------------

def report(folder: str = LAUNCHERS, registry: Any = None, out: Any = None) -> int:
    """`--check`: 0 when a newly started program runs this launcher as `charter`."""
    out = out or sys.stdout
    now = resolve(NAME, os.environ.get("PATH", ""))
    print(f"Launchers:            {folder}", file=out)
    if os.name != "nt":
        return _report_posix(folder, now, os.environ.get("PATH", ""), out)
    registry = registry or Registry()
    user, _kind = registry.user_path()
    fresh = resolve(NAME, fresh_path(registry))
    print(f"Your user PATH:       {'includes it' if contains(user, folder) else 'does not include it'}",
          file=out)
    print(f"New programs run:     {fresh or 'nothing: `charter` is not found'}", file=out)
    print(f"This program runs:    {now or 'nothing: `charter` is not found'}", file=out)
    if is_launcher(fresh, folder):
        if not is_launcher(now, folder):
            print("\nThis program started before the change: open a new terminal, or quit and "
                  "reopen the agent host.", file=out)
        return 0
    if fresh:
        print(f"\nAnother `charter` comes first on PATH. Remove {os.path.dirname(fresh)} from PATH, "
              "or run `charter add-to-path` from that copy instead.", file=out)
    else:
        print("\nRun `python charter.py add-to-path` in this folder to put it on your PATH.", file=out)
    return 1


def main(check_only: bool, folder: str = LAUNCHERS, registry: Any = None) -> int:
    if check_only:
        return report(folder, registry)
    if os.name != "nt":
        return _guide_posix(folder)
    if not os.path.isfile(os.path.join(folder, NAME + ".cmd")):
        print(f"error: {folder} has no charter.cmd launcher", file=sys.stderr)
        return 1
    changed, _value = add(folder, registry)
    print(f"{'Added to' if changed else 'Already on'} your user PATH: {folder}\n")
    print(RESTART)
    registry = registry or Registry()
    fresh = resolve(NAME, fresh_path(registry))
    if not is_launcher(fresh, folder):
        print(f"\nBut another `charter` comes first on PATH: {fresh}. Remove "
              f"{os.path.dirname(fresh or '')} from PATH, or use that copy.")
        return 1
    return 0
