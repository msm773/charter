"""Which copy of Charter is running (Product Specification §6, "Identity").

Several copies of Charter can live on one computer, and an agent host keeps
running the copy it started. Every copy can therefore say what it is: its
product version; its build identity; the full paths of its launcher and of the
Python interpreter running it; and the map-format version it generates.

A release's build identity is recorded when the release is built, in
`app/build.json`: the time it was built and, when it was available, the commit
it was built from. A development checkout has no such file. It says it is a
development checkout, with its commit when Git can tell, and marks a working
tree with uncommitted changes as dirty. That is learned by asking Git about
this checkout only, read-only: no optional locks are taken, no index is
refreshed, and no repository hook or file-system monitor runs.

This is detail for `charter --version`, `charter check`, `charter mcp --check`
and the console's Diagnostics; ordinary statuses never show it.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Dict, List, Optional

from . import __version__
from . import agent_context as ac
from . import on_path

BUILD_FILE = "build.json"
GIT_TIMEOUT = 5.0


def launcher(windows: Optional[bool] = None) -> str:
    """This copy's launcher, by its full path: `charter.cmd` on Windows,
    `charter` elsewhere."""
    windows = os.name == "nt" if windows is None else windows
    return os.path.join(on_path.LAUNCHERS, on_path.NAME + (".cmd" if windows else ""))


def script() -> str:
    """This copy's `charter.py`, by its full path."""
    return os.path.join(on_path.LAUNCHERS, on_path.NAME + ".py")


def interpreter() -> str:
    """The Python interpreter running Charter, by its full path."""
    return os.path.abspath(sys.executable) if sys.executable else ""


def _release_build(folder: str) -> Optional[Dict[str, Any]]:
    try:
        with open(os.path.join(folder, "app", BUILD_FILE), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    built = data.get("built") if isinstance(data.get("built"), str) else ""
    commit = data.get("commit") if isinstance(data.get("commit"), str) else ""
    return {"kind": "release", "built": built, "commit": commit, "dirty": bool(data.get("dirty"))}


def _git(folder: str, *args: str) -> Optional[str]:
    """One read-only Git question about this checkout, or None."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
    try:
        done = subprocess.run(["git", "--no-optional-locks", "-c", "core.fsmonitor=false",
                               "-c", "core.hooksPath=", "-C", folder, *args],
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT,
                              env=env)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    return done.stdout.decode("utf-8", "replace")


def commit_of(folder: str) -> Dict[str, Any]:
    """A checkout's short commit and whether it has uncommitted changes, asked
    read-only; empty and None when Git cannot tell."""
    head = _git(folder, "rev-parse", "--short=12", "HEAD")
    if head is None:
        return {"commit": "", "dirty": None}
    porcelain = _git(folder, "status", "--porcelain", "--untracked-files=normal")
    return {"commit": head.strip(), "dirty": None if porcelain is None else bool(porcelain.strip())}


def development_checkout(folder: str = "") -> bool:
    folder = folder or on_path.LAUNCHERS
    return os.path.exists(os.path.join(folder, ".git"))


def build(folder: str = "") -> Dict[str, Any]:
    """This copy's build identity: a release's recorded build, a development
    checkout's commit, or an unknown build."""
    folder = folder or on_path.LAUNCHERS
    release = _release_build(folder)
    if release is not None:
        return release
    if development_checkout(folder):
        return dict({"kind": "development", "built": ""}, **commit_of(folder))
    return {"kind": "unknown", "built": "", "commit": "", "dirty": None}


def describe_build(b: Dict[str, Any]) -> str:
    if b["kind"] == "release":
        parts = ["release"]
        if b.get("built"):
            parts.append(f"built {b['built']}")
        if b.get("commit"):
            parts.append(f"from commit {b['commit']}" + (" (with uncommitted changes)" if b.get("dirty") else ""))
        return ", ".join(parts)
    if b["kind"] == "development":
        if not b.get("commit"):
            return "development checkout (commit unavailable)"
        state = {True: ", dirty: uncommitted changes", False: ", clean", None: ""}[b.get("dirty")]
        return f"development checkout, commit {b['commit']}{state}"
    return "unknown build: no build record, and not a development checkout"


def identity(exam: Optional[ac.Examination] = None,
             map_status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Everything a person needs to tell this copy of Charter from another,
    with the map format an Agent Context records when one is given."""
    out = {"version": __version__, "build": build(), "launcher": launcher(),
           "script": script(), "python": interpreter(),
           "map_format": ac.MAP_FORMAT_VERSION}
    out["build_text"] = describe_build(out["build"])
    if exam is not None:
        map_status = {"recorded": exam.recorded_map_format, "relation": exam.map_format}
    if map_status is not None:
        out["context_map_format"] = map_status.get("recorded")
        out["context_map_relation"] = map_status.get("relation") or ""
    return out


RELATION = {ac.FORMAT_CURRENT: "the format this Charter generates",
            ac.FORMAT_OLDER: "older than this Charter's: rebuild the Agent Context",
            ac.FORMAT_NEWER: "newer than this Charter's: this copy is out of date"}


def lines(ident: Dict[str, Any]) -> List[str]:
    """The identity as aligned `label: value` lines, for the command line."""
    out = [f"Charter {ident['version']}",
           f"  build        {ident['build_text']}",
           f"  launcher     {ident['launcher']}",
           f"  charter.py   {ident['script']}",
           f"  python       {ident['python']}",
           f"  map format   {ident['map_format']} (generated by this Charter)"]
    if "context_map_format" in ident:
        recorded = ident["context_map_format"]
        relation = RELATION.get(ident.get("context_map_relation") or "", "")
        out.append(f"  context map  {recorded if recorded is not None else 'not recorded'}"
                   + (f" ({relation})" if relation and recorded is not None else ""))
    return out
