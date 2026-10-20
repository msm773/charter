"""Connect agents: copy-ready text for connecting an agent to one Agent Context.

Everything here is text for a person to copy: an MCP configuration that runs
`charter mcp --context <folder>`, the `claude mcp add` command that registers it
for one project, Codex's TOML entry, a check command, a startup pointer for a
project's own instruction file, a prompt that verifies an agent retrieved the
context, the `charter read` instruction for an agent without MCP that can run
commands, and an instruction that points a file-reading agent at
`AGENT-CONTEXT.md`. Producing it reads the folder's status and, on Windows,
this user's PATH; it writes nothing anywhere. Charter never
creates or changes `AGENTS.md`, `CLAUDE.md`, a host's configuration or an MCP
registration, and never runs a command it shows.

What it says is limited to what it checked: the folder. It never says a host is
configured or that an agent has read the context, since it cannot know either.

The text is offered only while the folder is ready: valid, clean, with no
interrupted Charter write, so agents are served. Otherwise the
reason is given instead, and nothing to copy. A path no host configuration can
carry gets file access only, said plainly.

What the default `charter` command runs is not Connect agents' to say: the
header's Charter command status reports it (`command_status`), with its remedy
in a dialog of its own (UI Standards).
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
from . import identity
from .docs import slugify

# Connect agents holds only the immediate actions: choose a host, copy its
# setup, confirm retrieval. Explanation, troubleshooting, scopes, launchers
# and the trust boundary are the README's.

CONFIG_NOTE = "Add this using your host's MCP instructions."

# Product Specification §6: where Charter lives, and what moving it means.
INSTALL_NOTE = ("These start this copy of Charter by its full path. Keep Charter in one folder and "
                "update it there: registrations keep working. If you move Charter, or change the "
                "Python it runs with, connect your agents again.")

CODEX_NOTE = "Add this to your Codex configuration, then restart Codex."

POINTER_NOTE = ("Add this to your project’s instruction file: `CLAUDE.md` for Claude Code, `AGENTS.md` "
                "for Codex, or your agent host’s equivalent. Do not put it in `AGENT-CONTEXT.md` or "
                "anywhere inside the Agent Context folder.")

FILES_NOTE = "Requires direct read access to the Agent Context folder. See the README for guidance."

# Agent Context as the Project Asset §9: where Command-Line Access text goes, and nothing else.
COMMAND_NOTE = ("Add this to your project’s instruction file, such as `CLAUDE.md` or `AGENTS.md`. "
                "Do not put it in `AGENT-CONTEXT.md` or anywhere inside the Agent Context folder.")

# Never says a host is configured, or that an agent retrieved or follows the context.
READY = "This context is ready to connect."
FILES_ONLY = "Agent Context ready for file access. MCP access cannot be set up for this folder."

# Characters Command Prompt acts on wherever they are, quoted or not: a
# registration command typed there cannot carry them reliably, so only
# PowerShell's form is offered for a path that holds one.
CMD_UNSAFE = set("%&|<>^\"")

# PowerShell takes these as they are when unquoted; anything else is quoted.
_PS_PLAIN = on_path.PS_PLAIN
# Command Prompt: quoted unless it is plain.
_CMD_PLAIN = _PS_PLAIN


def _native(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def server_name(project_name: str) -> str:
    """`charter-` and the project's name: each Agent Context's server is told apart."""
    return "charter-" + slugify(project_name, fallback="context")


# --- quoting -----------------------------------------------------------------

powershell_arg = on_path.powershell_arg


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


# --- the Charter command -------------------------------------------------------

COMMAND_READY, COMMAND_OTHER, COMMAND_MISSING = "ready", "other", "missing"


def found_by_name(windows: bool, registry: Any = None) -> Optional[str]:
    """What a newly started program runs as `charter`: on Windows, by the PATH
    Windows gives it; elsewhere, by this process's. Reads; changes nothing."""
    try:
        if windows and os.name == "nt":
            return on_path.resolve(on_path.NAME, on_path.fresh_path(registry or on_path.Registry()))
        return on_path.resolve(on_path.NAME, os.environ.get("PATH", ""))
    except OSError:
        return None


def command_status(windows: Optional[bool] = None, registry: Any = None,
                   python: Optional[str] = None, launchers: Optional[str] = None) -> Dict[str, Any]:
    """The header's Charter command status (UI Standards): whether the default
    `charter` command — what a new terminal, or an agent running `charter
    propose`, finds on PATH — runs this installation. `ready` only when it does;
    another copy, compatible or not, is `other`, and none is `missing`. Either
    comes with the remedy: one command that runs this copy by its full paths —
    on Windows the Python running Charter with this copy's `charter.py`, as
    typed in PowerShell, elsewhere this copy's launcher (`on_path.this_copy`)
    — never a bare `charter` or `py`, which PATH could route to another copy.
    Writes nothing."""
    windows = (os.name == "nt") if windows is None else windows
    launchers = on_path.LAUNCHERS if launchers is None else launchers
    found = found_by_name(windows, registry)
    if on_path.is_launcher(found, launchers):
        return {"state": COMMAND_READY, "found": found}
    # The same command `charter add-to-path --check` gives.
    remedy = on_path.this_copy(launchers, ["add-to-path"], windows, python or identity.interpreter())
    return {"state": COMMAND_OTHER if found else COMMAND_MISSING, "found": found or "",
            "other_folder": os.path.dirname(found) if found else "", "this_copy": launchers,
            "shell": "PowerShell" if windows else "Terminal", "remedy": remedy,
            "changes_path": windows}


def _not_ready(status: Dict[str, Any]) -> List[str]:
    reasons = [status["headline"]]
    for issue in (status.get("issues") or [])[:5]:
        message = str(issue.get("message") or "")
        if message:
            if issue.get("label"):
                message = f"{issue['label']}. {message}"
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
        "",
        # Agent Context as the Project Asset §7: a mismatch that remains after
        # one reread means stop and report, never reread and continue.
        "If a document it lists is missing or does not match its recorded hash, read the map "
        "again once. If it still does not match, stop: do not rely on what you read from it "
        "earlier, and tell the person that the Agent Context no longer matches its map.",
    ]) + "\n"


def mcp_pointer(name: str) -> str:
    """For a project's instruction file: where an MCP-connected agent finds the
    governing context. It names the server, never a local path."""
    return "\n".join([
        f"This project's governing context is served by the `{name}` MCP server (Charter).",
        "Before beginning work, call its `get_context` tool, then retrieve the governing documents "
        "relevant to your task. Treat only the governing documents it lists as authoritative.",
    ]) + "\n"


def command_instruction(command: str, propose: str) -> str:
    """For a project's instruction file: the `charter read` command, by full
    paths, that a shell-capable agent without MCP runs for the governing
    context, and the matching `charter propose` command it submits proposals
    with (Agent Context as the Project Asset §9)."""
    from .read import END_MARKER
    return "\n".join([
        "This project's governing context is an Agent Context, served by Charter. Before beginning "
        "work, run this command, which prints its context map:",
        "",
        f"  {command}",
        "",
        "Then retrieve the governing documents relevant to your task by running the same command "
        "with `--list`, or with `--document <path-or-id>`, adding `--heading <heading>` for one "
        "section. Treat only the governing documents it lists as authoritative.",
        "",
        f"Rely on its output only when its last line is `{END_MARKER}`. If it refuses, do what it "
        "says. If the command cannot run, or reports that Charter context is unavailable, stop and "
        "tell the person: do not read the Agent Context's files instead.",
        "",
        "To propose a change, follow \"Making an Agent Proposal\" in the context map, sending the "
        "proposal JSON to this command:",
        "",
        f"  {propose}",
    ]) + "\n"


def command_access(program: List[str], folder: str, windows: bool) -> List[Dict[str, str]]:
    """The Command-Line Access instruction for each shell an agent may run it in:
    `program` — this copy by its full paths — with `read --context <folder>`,
    and the same program with `propose --context <folder>`, each exactly as
    listed. Never a bare `charter`, `py` or `cmd /c`. A shell that cannot carry
    the paths exactly is not offered."""
    read_parts = program + ["read", "--context", folder]
    propose_parts = program + ["propose", "--context", folder]
    if any(not p or any(ord(c) < 32 for c in p) for p in read_parts):
        return []
    forms = []
    if windows:
        forms.append(("powershell", "PowerShell", lambda parts: "& " + command_line(parts, powershell_arg)))
        if not any(CMD_UNSAFE & set(p) for p in read_parts):
            forms.append(("cmd", "Command Prompt", lambda parts: command_line(parts, cmd_arg)))
        forms.append(("bash", "Bash", lambda parts: command_line(parts, posix_arg)))
    else:
        forms.append(("posix", "Terminal", lambda parts: command_line(parts, posix_arg)))
    out = []
    for shell, label, typed in forms:
        command, propose = typed(read_parts), typed(propose_parts)
        out.append({"shell": shell, "label": label, "command": command, "propose_command": propose,
                    "instruction": command_instruction(command, propose)})
    return out


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
               status: Optional[Dict[str, Any]] = None,
               launchers: Optional[str] = None, python: Optional[str] = None) -> Dict[str, Any]:
    """What Connect agents shows for `folder`. Writes nothing.

    Every setup runs this copy by its full path, so PATH can never route an
    agent to another copy, and PATH plays no part here.

    `ready` is whether the Agent Context itself is ready: when it is not, the
    reasons are given and there is nothing to copy. `connect` says what an
    agent can do with a ready one:

      ready          file access, and MCP once pasted into a host
      files-only     a path holding a control character, which no host
                     configuration can carry: file access only, and the
                     concrete MCP limitation instead of MCP text"""
    windows = (os.name == "nt") if windows is None else windows
    folder = _native(folder) if not windows or os.name == "nt" else folder
    launchers = on_path.LAUNCHERS if launchers is None else launchers
    python = python or identity.interpreter()
    status = status or mg.check(folder, git=False)
    base = {"folder": folder, "map": os.path.join(folder, ac.CONTEXT_MAP),
            "state": status["state"],
            "headline": status["headline"]}
    if not status["agents_served"]:
        return dict(base, ready=False, connect="not-ready", reasons=_not_ready(status))
    files = dict(base, ready=True, reasons=[], project_name=status["name"],
                 instruction=instruction(folder), files_note=FILES_NOTE,
                 verify_prompt=VERIFY_PROMPT)

    # One program and an exact list of arguments, never a command line for a
    # shell (Product Specification §6): on Windows the Python running Charter
    # with this copy's charter.py, elsewhere this copy's launcher, each by its
    # full path, so PATH can never route an agent to another copy.
    name = server_name(status["name"])
    args = ["mcp", "--context", folder]
    if windows:
        command, launch = python, [os.path.join(launchers, on_path.NAME + ".py")] + args
    else:
        command, launch = os.path.join(launchers, on_path.NAME), args
    unusable = [p for p in [command] + launch if not p or any(ord(c) < 32 for c in p)]
    if unusable:
        return dict(files, connect="files-only", status_text=FILES_ONLY, command_access=[],
                    command_note=COMMAND_NOTE, mcp_limitation=(
            "A path the agent host would need holds a line break or another control character, "
            "which no host configuration can carry exactly. No MCP configuration is offered. "
            "Agents can read the folder's files as below; for MCP access, use a folder whose path "
            "has none."))
    config = {"mcpServers": {name: {"command": command, "args": launch}}}
    # Claude Code's default scope, local: this project only, for this person.
    # The host stores the program and arguments exactly; only the command a
    # person types to register it passes through their shell.
    register = ["claude", "mcp", "add", name, "--", command] + launch
    check = [command] + launch + ["--check"]
    if windows:
        shells = [{"shell": "powershell", "label": "PowerShell",
                   "claude_code": command_line(register, powershell_arg),
                   "check": command_line(check, powershell_arg)}]
        # Command Prompt cannot carry % & | < > ^ " reliably, quoted or not:
        # where a path holds one, only PowerShell's form is offered.
        if not any(CMD_UNSAFE & set(p) for p in register):
            shells.append({"shell": "cmd", "label": "Command Prompt",
                           "claude_code": command_line(register, cmd_arg),
                           "check": command_line(check, cmd_arg)})
    else:
        shells = [{"shell": "posix", "label": "Terminal",
                   "claude_code": command_line(register, posix_arg),
                   "check": command_line(check, posix_arg)}]
    # PATH decides nothing here: a host starts this copy by its full path.
    return dict(
        files, connect="ready", status_text=READY, server_name=name,
        codex_toml=codex_toml(name, command, launch), codex_note=CODEX_NOTE,
        pointer=mcp_pointer(name), pointer_note=POINTER_NOTE,
        command=command, args=launch, launch_line=command_line([command] + launch, powershell_arg
                                                               if windows else posix_arg),
        config=config, config_text=json.dumps(config, indent=2, ensure_ascii=False) + "\n",
        config_note=CONFIG_NOTE, install_note=INSTALL_NOTE,
        shells=shells,
        # Command-Line Access (§9): the same program, `read` or `propose`, and the folder's full path.
        command_access=command_access([command] + launch[:len(launch) - len(args)], folder, windows),
        command_note=COMMAND_NOTE)
