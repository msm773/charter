"""Connect agents: copy-ready text for connecting an agent to one Agent Context.

Everything here is text for a person to copy: an MCP configuration that runs
`charter mcp --context <folder>`, the `claude mcp add` command that registers it
for one project, Codex's TOML entry, a check command, a startup pointer for a
project's own instruction file, a prompt that verifies an agent retrieved the
context, and an instruction that points a file-reading agent at
`AGENT-CONTEXT.md`. Producing it reads the folder's status and, on Windows,
this user's PATH; it writes nothing anywhere. Charter never
creates or changes `AGENTS.md`, `CLAUDE.md`, a host's configuration or an MCP
registration, and never runs a command it shows.

What it says is limited to what it checked: the folder, and whether a newly
started program can run `charter`. It never says a host is configured or that an
agent has read the context, since it cannot know either.

The text is offered only while the folder is ready: valid, clean, with no
interrupted Charter write, so agents are served. Otherwise the
reason is given instead, and nothing to copy. A ready folder is not yet ready
for MCP while a newly started program cannot run `charter`, or, on Windows, while
its path is one `cmd /c` cannot carry; each is said plainly.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from typing import Any, Callable, Dict, List, Optional

from . import agent_context as ac
from . import manager as mg
from . import on_path
from .docs import slugify

# Connect agents holds only the immediate actions: choose a host, copy its
# setup, confirm retrieval. Explanation, troubleshooting, scopes, launchers
# and the trust boundary are the README's.

CONFIG_NOTE = "Add this using your host's MCP instructions."

CODEX_NOTE = "Add this to your Codex configuration, then restart Codex."

POINTER_NOTE = ("Copy this into the project instructions or system context your agent receives—for "
                "example, `CLAUDE.md`, `AGENTS.md`, or your agent host’s equivalent. Do not put it in "
                "`AGENT-CONTEXT.md` or anywhere inside the Agent Context folder.")

FILES_NOTE = "Requires direct read access to the Agent Context folder. See the README for guidance."

RESTART_NOTE = (
    "Afterwards, quit and reopen the agent host, every window of it: a program that is already "
    "running keeps the PATH it started with. `charter add-to-path --check` says what a newly started "
    "program runs as `charter`.")

# Never says a host is configured, or that an agent retrieved or follows the context.
READY = "This context is ready to connect."
NEEDS_PATH = "Agent Context ready. Add Charter to your PATH before a new agent host can connect."
OTHER_COPY = ("Agent Context ready. Another copy of Charter comes first on your PATH: a new agent host "
              "would run that one, not this one.")
FILES_ONLY = ("Agent Context ready for file access. MCP access cannot be set up for this folder on "
              "Windows.")

# Characters that Command Prompt acts on wherever they are, or when a host
# passes the folder to `cmd /c` without quotes: no configuration through
# `cmd /c` can carry them reliably.
CMD_UNSAFE = set("%&|<>^\"")

# PowerShell takes these as they are when unquoted; anything else is quoted.
_PS_PLAIN = re.compile(r"[A-Za-z0-9_.:\\/-]+")
# Command Prompt: quoted unless it is plain.
_CMD_PLAIN = _PS_PLAIN


def _native(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def server_name(project_name: str) -> str:
    """`charter-` and the project's name: each Agent Context's server is told apart."""
    return "charter-" + slugify(project_name, fallback="context")


# --- quoting -----------------------------------------------------------------

def powershell_arg(arg: str) -> str:
    """One argument as typed at a PowerShell prompt. Quoted unless it is plain,
    and always for `--`: PowerShell drops a bare `--` passed to a script, and
    a `claude` installed by npm is one."""
    if arg == "--" or not _PS_PLAIN.fullmatch(arg):
        return "'" + arg.replace("'", "''") + "'"
    return arg


def cmd_arg(arg: str) -> str:
    """One argument as typed at a Command Prompt. Only for arguments with
    nothing in `CMD_UNSAFE`, which double quotes do not protect."""
    if CMD_UNSAFE & set(arg):
        raise ValueError(f"Command Prompt cannot carry {arg!r} reliably.")
    return arg if arg and _CMD_PLAIN.fullmatch(arg) else f'"{arg}"'


def posix_arg(arg: str) -> str:
    return shlex.quote(arg)


def command_line(parts: List[str], quote: Callable[[str], str]) -> str:
    return " ".join(quote(p) for p in parts)


# --- readiness ---------------------------------------------------------------

def _launcher(windows: bool, registry: Any = None) -> Dict[str, Any]:
    """Whether a newly started program finds this copy's `charter` by name, as an
    agent host must. Reads PATH; changes nothing."""
    try:
        if windows and os.name == "nt":
            found = on_path.resolve(on_path.NAME,
                                    on_path.fresh_path(registry or on_path.Registry()))
        else:
            found = on_path.resolve(on_path.NAME, os.environ.get("PATH", ""))
    except OSError:
        found = None
    ok = on_path.is_launcher(found, on_path.LAUNCHERS)
    if ok:
        note = "New programs run this copy of Charter as `charter`."
    elif found:
        note = (f"A newly started program runs another copy of Charter as `charter`, from "
                f"{os.path.dirname(found)}. Remove that folder from PATH, or run `python charter.py "
                f"add-to-path` in {on_path.LAUNCHERS}.")
    else:
        note = ("A newly started program cannot run `charter` yet, and an agent host starts the MCP "
                "server by that name. Run `charter add-to-path` in a terminal. If the terminal does not "
                f"find `charter` either, run `python charter.py add-to-path` in {on_path.LAUNCHERS}.")
    return {"on_path": ok, "found": found or "", "note": note, "fix": "charter add-to-path",
            "restart": RESTART_NOTE}


def _not_ready(status: Dict[str, Any]) -> List[str]:
    reasons = [status["headline"]]
    for issue in (status.get("issues") or [])[:5]:
        message = str(issue.get("message") or "")
        if message:
            path = str(issue.get("path") or "")
            reasons.append(f"`{path}`: {message}" if path else message)
    if len(status.get("issues") or []) > 5:
        reasons.append(f"And {len(status['issues']) - 5} more.")
    return reasons


# --- the text ------------------------------------------------------------------

def instruction(folder: str) -> str:
    """For any agent that reads files: where the governing context is."""
    map_path = os.path.join(folder, ac.CONTEXT_MAP)
    return "\n".join([
        "This project's governing context is an Agent Context, in this folder:",
        f"  {folder}",
        "",
        "Before beginning work, read its context map:",
        f"  {map_path}",
        "",
        "It lists the governing documents and how to use them. Treat only the governing documents "
        "it lists as authoritative. If the Charter MCP tools are available, "
        "`get_context` returns the same map.",
    ]) + "\n"


def mcp_pointer(name: str) -> str:
    """For a project's instruction file: where an MCP-connected agent finds the
    governing context. It names the server, never a local path."""
    return "\n".join([
        f"This project's governing context is served by the `{name}` MCP server (Charter).",
        "Before beginning work, call its `get_context` tool, then retrieve the governing documents "
        "relevant to your task. Treat only the governing documents it lists as authoritative.",
    ]) + "\n"


VERIFY_PROMPT = (
    "Before doing anything else, retrieve this project's Agent Context. Tell me the project name "
    "it gives, and which of its governing documents apply to this task: [describe a small task]. "
    "If you cannot retrieve it, say so; do not guess.\n")


def toml_string(value: str) -> str:
    """A TOML basic string. JSON's string escapes are TOML's for every character
    `json.dumps` writes, so this is exact."""
    return json.dumps(value, ensure_ascii=False)


def codex_toml(name: str, command: str, args: List[str]) -> str:
    """Codex's `[mcp_servers.<name>]` table for this server."""
    key = name if re.fullmatch(r"[A-Za-z0-9_-]+", name) else toml_string(name)
    return "\n".join([f"[mcp_servers.{key}]", f"command = {toml_string(command)}",
                      "args = [" + ", ".join(toml_string(a) for a in args) + "]"]) + "\n"


def connection(folder: str, windows: Optional[bool] = None, registry: Any = None,
               status: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What Connect agents shows for `folder`. Writes nothing.

    `ready` is whether the Agent Context itself is ready: when it is not, the
    reasons are given and there is nothing to copy. `connect` says what an
    agent can do with a ready one:

      ready          file access, and MCP once pasted into a host
      needs-path     file access; the MCP text is shown, but a newly started
                     agent host cannot run `charter` until it is on PATH
      files-only     Windows, a path `cmd /c` cannot carry: file access only,
                     and the concrete MCP limitation instead of MCP text"""
    windows = (os.name == "nt") if windows is None else windows
    folder = _native(folder) if not windows or os.name == "nt" else folder
    status = status or mg.check(folder, git=False)
    base = {"folder": folder, "map": os.path.join(folder, ac.CONTEXT_MAP),
            "state": status["state"],
            "headline": status["headline"]}
    if not status["agents_served"]:
        return dict(base, ready=False, connect="not-ready", reasons=_not_ready(status))
    files = dict(base, ready=True, reasons=[], project_name=status["name"],
                 instruction=instruction(folder), files_note=FILES_NOTE,
                 verify_prompt=VERIFY_PROMPT)
    if windows and CMD_UNSAFE & set(folder):
        bad = " ".join(sorted(CMD_UNSAFE & set(folder)))
        return dict(files, connect="files-only", status_text=FILES_ONLY, mcp_limitation=(
            f"This folder's path contains {bad}. On Windows an agent host starts `charter` through "
            "`cmd /c`, and Command Prompt treats these characters specially wherever they are, so "
            "the MCP server would not be given this folder. No MCP configuration is offered for "
            "it. Agents can read the folder's files as below; for MCP access, move or rename the "
            "folder so its path has none of % & | < > ^ \", then open it again."))

    name = server_name(status["name"])
    args = ["mcp", "--context", folder]
    command, launch = ("cmd", ["/c", "charter"] + args) if windows else ("charter", args)
    config = {"mcpServers": {name: {"command": command, "args": launch}}}
    # Claude Code's default scope, local: this project only, for this person.
    register = ["claude", "mcp", "add", name, "--", command] + launch
    check = ["charter"] + args + ["--check"]
    if windows:
        shells = [
            {"shell": "powershell", "label": "PowerShell",
             "claude_code": command_line(register, powershell_arg),
             "check": command_line(check, powershell_arg)},
            {"shell": "cmd", "label": "Command Prompt",
             "claude_code": command_line(register, cmd_arg),
             "check": command_line(check, cmd_arg)},
        ]
    else:
        shells = [{"shell": "posix", "label": "Terminal",
                   "claude_code": command_line(register, posix_arg),
                   "check": command_line(check, posix_arg)}]
    launcher = _launcher(windows, registry)
    state, text = (("ready", READY) if launcher["on_path"] else
                   ("needs-path", OTHER_COPY if launcher["found"] else NEEDS_PATH))
    return dict(
        files, connect=state, status_text=text, server_name=name,
        codex_toml=codex_toml(name, command, launch), codex_note=CODEX_NOTE,
        pointer=mcp_pointer(name), pointer_note=POINTER_NOTE,
        command=command, args=launch, launch_line=" ".join(["charter", "mcp", "--context",
                                       folder if _PS_PLAIN.fullmatch(folder) else f'"{folder}"']),
        config=config, config_text=json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        config_note=CONFIG_NOTE,
        shells=shells, launcher=launcher)
