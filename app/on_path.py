"""`charter add-to-path`: make `charter` a command this user's new programs can run.

    charter add-to-path            put the launchers' folder on this user's PATH
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

Elsewhere Charter does not edit shell profiles; it prints the line to add.
"""
from __future__ import annotations

import os
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
    if os.name == "nt":
        import winreg
        return winreg.ExpandEnvironmentStrings(value)
    return os.path.expandvars(value)


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


def is_launcher(found: Optional[str], folder: str) -> bool:
    return bool(found) and _same(os.path.dirname(found or ""), folder)


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


# --- the command ------------------------------------------------------------------

def report(folder: str = LAUNCHERS, registry: Any = None, out: Any = None) -> int:
    """`--check`: 0 when a newly started program runs this launcher as `charter`."""
    out = out or sys.stdout
    now = resolve(NAME, os.environ.get("PATH", ""))
    print(f"Launchers:            {folder}", file=out)
    if os.name != "nt":
        print(f"This shell runs:      {now or 'nothing: `charter` is not found'}", file=out)
        return 0 if is_launcher(now, folder) else 1
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
        print("Charter does not edit shell profiles. Add this line to yours (for example "
              "~/.profile or ~/.zshrc), then open a new terminal:\n\n"
              f'    export PATH="{folder}:$PATH"')
        return 1
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
