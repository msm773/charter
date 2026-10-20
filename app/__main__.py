"""Charter's command line.

    charter serve [<agent-context-folder>] [--port 8765]
    charter check --context <agent-context-folder>
    charter mcp --context <agent-context-folder> [--check]
    charter compare --context <agent-context-folder> --base <revision>
                    [--prompt | --packet <destination> [--accept-git-warning]] [--json]
    charter propose --context .              (one Agent Proposal, as JSON on stdin)
    charter add-to-path [--check]
    charter --version

`python charter.py …` runs the same commands from any directory.
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

PROG = "charter"


def cmd_serve(args: argparse.Namespace) -> int:
    from . import server
    return server.serve(args.folder or "", port=args.port)


def _report(status: Dict[str, Any]) -> List[str]:
    lines = [f"Agent Context: {status['name']}",
             f"Folder:        {status['path']}",
             f"Agents:        {'served' if status['agents_served'] else 'unavailable'}",
             "", status["headline"]]
    errors = [i for i in status["issues"] if i["level"] == "error"]
    warnings = [i for i in status["issues"] if i["level"] == "warning"]
    for title, found in (("Problems", errors), ("Warnings", warnings)):
        if not found:
            continue
        lines += ["", f"{title}:"]
        for i in found:
            label = f"{i['label']}. " if i.get("label") else ""
            lines.append(f"  - {i['path'] or 'the folder'}: {label}{i['message']}")
            if i.get("fix"):
                lines.append(f"    {i['fix']}")
    if status["rebuild"]["available"]:
        lines += ["", "Rebuild Agent Context can regenerate the map and metadata. Use it in the "
                      "console (`charter serve`); the governing documents stay as they are."]
    if status["regenerate"]["available"]:
        lines += ["", "Only the map does not match; every governing document does. Regenerate map, "
                      "in the console (`charter serve`), can restore it exactly as the approved "
                      "context records it, without changing `.agent-context.json`."]
    outside = status["outside"]
    if outside["message"]:
        lines += ["", outside["message"]]
        lines += [f"  - {p}" for p in outside["paths"]]
    legacy = status.get("legacy_state") or {}
    if legacy.get("message"):
        lines += ["", legacy["message"]]
    return lines


def cmd_check(args: argparse.Namespace) -> int:
    """Report whether a folder is a valid, clean Agent Context agents can be
    served, and which Charter checked it. Read-only: it writes nothing
    anywhere, creates no private state, and recovers nothing. Exit 0 when
    agents are served, 1 otherwise."""
    from . import identity, manager
    folder = os.path.abspath(os.path.expanduser(args.context))
    # `charter check` never reports the folder's Git information, so it asks
    # Git nothing about it: a folder's own `.git/config` cannot run during a
    # check. Only this copy's own checkout is asked who it is (`identity`).
    status = manager.check(folder, git=False)
    print("\n".join(_report(status)))
    print("\n" + "\n".join(identity.lines(identity.identity(map_status=status["map_format"]))))
    return 0 if status["agents_served"] else 1


def cmd_version() -> int:
    """Which copy of Charter this is: version, build, launcher, interpreter
    and map format. Reads only."""
    from . import identity
    print("\n".join(identity.lines(identity.identity())))
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Optional local MCP server over stdio, read-only; see `app.mcp`."""
    from . import mcp
    folder = os.path.abspath(os.path.expanduser(args.context))
    return mcp.check(folder) if args.check else mcp.run(folder)


def cmd_add_to_path(args: argparse.Namespace) -> int:
    from . import on_path
    return on_path.main(args.check)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=PROG, description="Charter: one trusted context "
                                                       "for every AI agent on your project.")
    # Handled in `main` before parsing; listed here for --help.
    p.add_argument("--version", action="store_true",
                   help="say which copy of Charter this is: version, build, launcher, Python and "
                        "map format")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("serve", help="run the console on this computer")
    s.add_argument("folder", nargs="?", default="", help="an Agent Context folder to open")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(func=cmd_serve)

    c = sub.add_parser("check", help="say whether a folder is a valid, clean Agent Context that "
                                     "agents can be served; changes nothing")
    c.add_argument("--context", required=True, metavar="FOLDER",
                   help="the Agent Context folder; `.` is the current folder")
    c.set_defaults(func=cmd_check)

    m = sub.add_parser("mcp", help="serve this Agent Context to a local agent over MCP (stdio, "
                                   "read-only)")
    m.add_argument("--context", required=True, metavar="FOLDER",
                   help="the Agent Context folder to serve; `.` is the current folder")
    m.add_argument("--check", action="store_true",
                   help="do not serve: say whether this command can serve an agent now, and why "
                        "not; changes nothing")
    m.set_defaults(func=cmd_mcp)

    from . import compare
    compare.add_parser(sub)

    # Listed for --help only; `main` hands it to `propose` before parsing.
    sub.add_parser("propose", add_help=False,
                   help="submit an Agent Proposal for a person's review: `charter propose --context .`"
                        " with one JSON object on stdin")

    a = sub.add_parser("add-to-path", help="let new terminals and agent sessions run `charter`: on "
                                           "Windows, put this copy's launchers on your user PATH; on "
                                           "macOS and Linux, print the line to add to your shell "
                                           "startup file, changing nothing")
    a.add_argument("--check", action="store_true",
                   help="change nothing: say what a newly started program runs as `charter`")
    a.set_defaults(func=cmd_add_to_path)
    return p


def _utf8_stdio() -> None:
    """Make standard output and error carry any character, whatever the console
    code page. On a redirected Windows pipe they default to the ANSI code page,
    where a name with an arrow or CJK text would crash a plain `print`."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main(argv=None) -> int:
    _utf8_stdio()
    words = list(sys.argv[1:] if argv is None else argv)
    if words == ["--version"]:
        return cmd_version()
    if words[:1] == ["propose"]:
        # Its own contract: exactly one JSON result on stdout and nothing on
        # stderr, for a bad command line too, so argparse never sees it.
        from . import propose
        return propose.main(words[1:])
    args = parser().parse_args(words)
    if not getattr(args, "func", None):
        parser().print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
