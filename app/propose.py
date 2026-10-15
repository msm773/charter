"""`charter propose --context .`: submit one Agent Proposal for a person's review.

    charter propose --context <agent-context-folder>     one JSON proposal on stdin
    charter propose --help

Run at the Agent Context's root, with `.`: the folder named is the Agent
Context itself, never one found above it. The command prints exactly one JSON
result object on standard output, and nothing on standard error, for every
outcome — a bad command line included:

    pending       filed for review; exit 0
    refused       not filed; correct each problem and submit again; exit 3
    unavailable   not filed; submit again unchanged only if `retryable`; exit 4

See `agent_proposals` for the fields and the rules.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

from . import agent_proposals as apx
from . import host_state as hs

EXIT = {"pending": 0, "refused": 3, "unavailable": 4}

USAGE = """usage: charter propose --context <agent-context-folder>

Submit one Agent Proposal, as one JSON object on standard input, for a person's
review. Run it in the folder that holds AGENT-CONTEXT.md, as `charter propose
--context .`. AGENT-CONTEXT.md describes the fields.

It prints one JSON object whose `result` is `pending` (filed; exit 0),
`refused` (not filed: correct each problem; exit 3) or `unavailable` (not
filed; submit again unchanged only if `retryable` is true; exit 4).
"""


def _context_argument(argv: List[str]) -> Optional[str]:
    if len(argv) == 2 and argv[0] == "--context" and argv[1]:
        return argv[1]
    if len(argv) == 1 and argv[0].startswith("--context=") and len(argv[0]) > len("--context="):
        return argv[0][len("--context="):]
    return None


def submit(argv: List[str], data: bytes) -> Dict[str, Any]:
    """The one result for this command line and standard input."""
    folder = _context_argument(argv)
    if folder is None:
        return apx.refused_result([apx._problem(
            "bad_command", "Run `charter propose --context .` in the folder that holds "
                           "AGENT-CONTEXT.md, with one JSON proposal on standard input.")])
    if len(data) > apx.MAX_INPUT:
        return apx.refused_result([apx._problem("too_large", "The proposal is too large.")])
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return apx.refused_result([apx._problem("not_utf8", "Standard input is not UTF-8 text.")])
    text = text.lstrip("\ufeff").strip()
    try:
        raw = hs.loads_strict(text)
    except ValueError:
        return apx.refused_result([apx._problem("not_json", "Standard input is not one JSON "
                                                            "object.")])
    return apx.file(os.path.abspath(os.path.expanduser(folder)), raw, source=apx.AGENT)


def main(argv: List[str]) -> int:
    if argv in (["--help"], ["-h"]):
        sys.stdout.write(USAGE)
        return 0
    out = sys.stdout
    sys.stderr = open(os.devnull, "w")  # nothing on standard error, ever
    try:
        data = sys.stdin.buffer.read(apx.MAX_INPUT + 1)
        result = submit(argv, data)
    except Exception as exc:  # noqa: BLE001 — still exactly one result
        # An unexpected failure is retryable only when its cause passes on its own.
        result = apx.unavailable_result(apx.write_failure(exc))
    # Exactly one JSON result, always. `ensure_ascii=True` keeps it pure ASCII,
    # and it is written as bytes to the underlying buffer, so a non-UTF-8 console
    # code page can never turn the result into a crash or a lost line.
    line = (json.dumps(result, ensure_ascii=True, separators=(",", ":")) + "\n").encode("ascii")
    try:
        out.buffer.write(line)
        out.buffer.flush()
    except AttributeError:  # a replaced stdout without a byte buffer (e.g. a test)
        out.write(line.decode("ascii"))
        out.flush()
    return EXIT[result["result"]]
