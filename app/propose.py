"""`charter propose --context <folder>`: submit one Agent Proposal for a person's review.

    charter propose --context <agent-context-folder>     one JSON proposal on stdin
    charter propose --help

Product Specification §3.3. `<folder>` names the Agent Context root: `.`, run
at that root, for an agent working in the folder, or, for Command-Line Access,
its absolute path, in the full-path command the agent's project instructions
give. The folder named is the Agent Context itself, never one above or below
it, and nothing searches for one or tells an agent to. The command prints exactly one JSON
result object on standard output, and nothing on standard error, for every
outcome — a bad command line included:

    pending       filed for review; exit 0
    refused       not filed; correct each problem and submit again; exit 3
    unavailable   not filed; submit again unchanged only if `retryable`; exit 4
    duplicate     not filed; an identical proposal already awaits review; exit 5

A duplicate is decided on the checked proposal's content, never on how its JSON
was written: whitespace, key order, escaping and byte-order marks make no
proposal distinct (Product Specification §3.2). Standard input is read by
`agent_proposals.read_submission`, as every route reads a submission.

See `agent_proposals` for the fields and the rules.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional

from . import agent_proposals as apx
from .read import absolute

EXIT = {"pending": 0, "refused": 3, "unavailable": 4, "duplicate": 5}

USAGE = """usage: charter propose --context <agent-context-folder>

Submit one Agent Proposal, as one JSON object on standard input, for a person's
review. `--context` names the Agent Context: `.` when run in the folder that
holds AGENT-CONTEXT.md, or its full path. AGENT-CONTEXT.md describes the
fields. Send the JSON as ASCII JSON, with every non-ASCII character encoded as
a JSON Unicode escape sequence such as \\uXXXX.

It prints one JSON object whose `result` is `pending` (filed; exit 0),
`refused` (not filed: correct each problem; exit 3), `unavailable` (not
filed; submit again unchanged only if `retryable` is true; exit 4) or
`duplicate` (not filed: an identical proposal is already awaiting review;
change the proposal, or ask a person to replace it in the console; exit 5).
"""


MALFORMED = {"too_large": "The proposal is too large.",
             "not_utf8": "Standard input is not UTF-8 text.",
             "not_json": "Standard input is not one JSON object."}


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
            "bad_command", "Name the Agent Context with `--context`, exactly as your project "
                           "instructions or the context map give, with one JSON proposal on "
                           "standard input. Do not search for an Agent Context.")])
    # `.` or a full path, nothing else: `..`, `sub\folder`, `C:folder` and
    # `\folder` would each name a folder relative to wherever the command ran.
    if folder != "." and not absolute(folder):
        return apx.refused_result([apx._problem(
            "bad_command", "`--context` names the Agent Context as `.` or by its full path, and "
                           "this is neither, so nothing was filed. Run the exact command your "
                           "project instructions or the context map give. Do not search for an "
                           "Agent Context.")])
    try:
        raw = apx.read_submission(data)
    except apx.Malformed as exc:
        return apx.refused_result([apx._problem(exc.code, MALFORMED[exc.code])])
    # The transport digest is of the bytes exactly as given, before the mark
    # and surrounding whitespace were set aside for parsing; duplicates are
    # matched on the checked content (`agent_proposals.proposal_fingerprint`).
    return apx.file(os.path.abspath(folder), raw, source=apx.AGENT,
                    submitted=bytes(data))


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
