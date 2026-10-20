"""Agent Proposals: untrusted requests for a person's review.

Product Specification §3.2–§3.3 and the Proposal Review Standard. An agent
proposes a change to an Agent Context with

    charter propose --context .

run at the Agent Context's root, giving one JSON object on standard input. The
command prints exactly one result object:

  * `pending` — an untrusted review record was filed in this context's private
    state, under a `proposal_id` Charter assigned;
  * `refused` — nothing was filed: the request is invalid or stale, with one
    problem per field;
  * `duplicate` — nothing was filed: a proposal with exactly the same text is
    already awaiting a decision in this Agent Context;
  * `unavailable` — nothing was filed because intake could not run now; only
    then, and only when `retryable` is true, may it be submitted again unchanged.

The fields are `agent`, `operation` (`create`, `amend`, `retire`),
`target_path` and `reason`, always; `proposed_body` for a create, and for an
amend unless exact-once `replacements` are given; `base_sha256` for an amend
or retire; optional `proposed_meta` with only `title` and `scope`, for a create
or amend; and optional advisory `expected_context_impact`. Any other field is
refused. Staleness is decided by content hashes alone.

Agent Proposals are an operational inbox (Product Specification §3.2): each is
temporary work awaiting a person's decision. Filed records live only in private
state, never in the Agent Context. Each is also entered, with the hash of its
bytes, in a private intake ledger. A file found among the records that the
ledger does not vouch for — written some other way, changed since, or
unreadable — is never treated as a proposal: it is shown to the person as
unexpected local material and left unchanged.

An agent that received the context through MCP submits with the
`submit_proposal` tool instead (MCP Context Access Specification §3.1): the same
fields, as typed tool arguments, checked, matched, locked and filed here exactly
as the command's, as an ordinary agent proposal with no route label.

A person may import a proposal an agent returned as JSON instead; it is checked
exactly as the command checks it, and filed as imported. Accepting a proposal
files, updates or retires an authority candidate, after a previewed ordinary
confirmation; it never changes governing context. Accepting or rejecting it
removes the proposal: Charter keeps no proposal history, no decided record and
no rejection reason.

A proposal is a duplicate when its checked content is the same as that of a
proposal still awaiting a decision in the same Agent Context, however either
was submitted (Product Specification §3.2): its `proposal_sha256`, the SHA-256
of one canonical serialization of the checked proposal, every field included,
equals the one recomputed from the waiting record's stored proposal. So
whitespace, key order, JSON escaping and leading byte-order marks never make a
proposal distinct, while a different `agent`, `reason` or impact always does.
Records filed before `proposal_sha256` existed take part unchanged: it is
recomputed, never read back, and no record is rewritten. Decided proposals are
gone, so they never match. `charter propose` refuses a duplicate, changing
nothing; in the console a person may instead replace the waiting proposal in
place.

Each record that arrived as bytes also keeps `submitted_sha256`, the SHA-256
of the exact bytes submitted — standard input, a chosen file, or pasted text as
UTF-8 — which is how an earlier copy of Charter, sharing this private state,
still recognizes a byte-identical resubmission. Every such route reads those
bytes the same way (`read_submission`). A record filed through the MCP tool
keeps none: its arguments never were submitted bytes.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import stat
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from . import agent_context as ac
from . import host_state as hs
from . import private_store as ps
from . import transaction as tx
from .docs import Document, leading_front_matter, not_text, parse_front_matter

OPERATIONS = ("create", "amend", "retire")
FIELDS = ("agent", "operation", "target_path", "reason", "proposed_body", "replacements",
          "base_sha256", "proposed_meta", "expected_context_impact")
REQUIRED = ("agent", "operation", "target_path", "reason")
META_KEYS = ("title", "scope")

PENDING = "pending"
# Where an earlier Charter kept decided records. Nothing reads or writes them
# now: they are left as they are, never treated as proposals or history.
LEGACY_DECIDED = ("accepted", "rejected")
LEDGER = "intake.json"
RECORD_VERSION = 1
AGENT, IMPORTED = "agent", "imported"

MAX_INPUT = 2 * 1024 * 1024
MAX_AGENT = 80
MAX_REASON = 4000
MAX_IMPACT = 8000
MAX_LINE = 300
INTAKE_TIMEOUT = 5.0
_SHA = re.compile(r"^[0-9a-f]{64}$")


class Unavailable(Exception):
    def __init__(self, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable


def _problem(code: str, message: str, field: str = "") -> Dict[str, Any]:
    out = {"code": code, "message": message}
    if field:
        out["field"] = field
    return out


def pending_result(proposal_id: str) -> Dict[str, Any]:
    return {"result": "pending", "proposal_id": proposal_id}


def refused_result(problems: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"result": "refused", "problems": problems}


DUPLICATE_MESSAGE = ("An identical proposal is already awaiting review in this Agent Context, so "
                     "this one was not filed. Do not submit it again unchanged: change the "
                     "proposal, or ask a person to replace the waiting proposal in "
                     "Charter's console.")


# Through the MCP tool, `duplicate` is also what the one retry after a
# retryable `unavailable` returns when the first attempt was filed.
DUPLICATE_AFTER_RETRY = (" If you submitted it again after a retryable `unavailable`, stop: it "
                         "is awaiting review.")


def duplicate_result(route: str = "command") -> Dict[str, Any]:
    """Nothing about the waiting proposal beyond that it exists: not its id,
    title, source or time."""
    message = DUPLICATE_MESSAGE + (DUPLICATE_AFTER_RETRY if route == "mcp" else "")
    return {"result": "duplicate", "problem": {"code": "duplicate", "message": message}}


def submission_identity(submitted: Any) -> str:
    """The transport digest, `submitted_sha256`: the SHA-256 of the submitted
    bytes exactly as given — text as its UTF-8 — with nothing trimmed,
    decoded or re-serialized. Kept in every record so that an earlier copy of
    Charter still matches a byte-identical resubmission; this copy matches by
    `proposal_fingerprint` instead."""
    data = submitted if isinstance(submitted, (bytes, bytearray)) else str(submitted).encode("utf-8")
    return hashlib.sha256(bytes(data)).hexdigest()


FINGERPRINT_PREFIX = "charter-proposal/1\n"
_NULL_AS_ABSENT = ("proposed_meta", "expected_context_impact")


def proposal_fingerprint(proposal: Dict[str, Any]) -> str:
    """`proposal_sha256`: the checked proposal's content identity (Product
    Specification §3.2). Every field counts. The fields are serialized with
    sorted keys, no whitespace and ASCII escapes, so nothing about how the JSON
    was written — whitespace, key order, escaping, a byte-order mark — can
    change it; an optional field given as null counts as absent. Characters are
    compared exactly, with no Unicode normalization. The prefix names this
    form, so a later form can never match it by accident."""
    fields = {k: v for k, v in proposal.items() if not (k in _NULL_AS_ABSENT and v is None)}
    canonical = json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                           allow_nan=False)
    return hashlib.sha256((FINGERPRINT_PREFIX + canonical).encode("ascii")).hexdigest()


class Malformed(Exception):
    """Submitted bytes that are not one proposal's JSON: `too_large`,
    `not_utf8` or `not_json`."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def read_submission(data: bytes) -> Any:
    """The JSON value a submission's bytes hold, read exactly as `charter
    propose` reads its standard input, for every route: at most MAX_INPUT
    bytes, strict UTF-8, every leading U+FEFF (byte-order mark) removed, then
    surrounding whitespace, then one strict JSON value. Raises Malformed. A
    value that is not an object is the checker's `not_an_object`."""
    if len(data) > MAX_INPUT:
        raise Malformed("too_large")
    try:
        text = bytes(data).decode("utf-8")
    except UnicodeDecodeError:
        raise Malformed("not_utf8")
    text = text.lstrip("﻿").strip()
    try:
        return hs.loads_strict(text)
    except (ValueError, RecursionError):
        raise Malformed("not_json")


def unavailable_result(exc: Unavailable) -> Dict[str, Any]:
    return {"result": "unavailable", "retryable": exc.retryable,
            "problem": {"code": exc.code, "message": exc.message}}


# --- what a proposal is checked against ---------------------------------------------

class Target:
    """The current context a proposal is checked against: the governing
    documents, the private candidates, and the names in use."""

    def __init__(self, folder: str, cs: ps.ContextState, exam: ac.Examination) -> None:
        self.folder, self.cs, self.exam = folder, cs, exam
        self.governing = {d.path: d for d in exam.documents}
        self.candidates = set(cs.candidates())
        self.names = sorted(set(exam.texts) - {ac.CONTEXT_MAP})

    def text_of(self, path: str) -> Optional[str]:
        """The target's whole current text, LF-normalized, or None."""
        if path in self.governing:
            return self.exam.texts[path]
        if path in self.candidates:
            return self.cs.read_candidate(path)
        return None


# The submitting route, which decides only the wording of what the agent is
# told: `charter propose`, or the MCP `submit_proposal` tool (MCP Context Access
# Specification §3.1). Checking, duplicate matching, locking and filing are the
# same for both. An MCP message never names `--context`, a command, or a place.
COMMAND, MCP = "command", "mcp"

_DO_NOT_RELY = (" Do not rely on Charter context you retrieved earlier in this session. Report to "
                "the person that Charter context is unavailable, rather than guessing or continuing "
                "from earlier context.")
_MCP_NOT_VALID = ("This Agent Context is not valid now, so nothing was filed. A person must "
                  "correct it in Charter.")
_MCP_SERVER_OUTDATED = ("This Agent Context was generated by a newer version of Charter than this "
                        "server, so nothing was filed; the Agent Context is not at fault. A person "
                        "must restart the agent host, or reconnect it to the current Charter "
                        "installation.")


def _mcp_integrity(exam: ac.Examination) -> str:
    """For MCP: the context needs review, or has documents and no usable map."""
    if exam.no_record:
        cause = ("This Agent Context has documents but no usable map, so nothing was filed. A "
                 "person must review it in Charter.")
    else:
        cause = ("This Agent Context's files no longer match its approved context map, so nothing "
                 "was filed. A person must review the changes in Charter.")
    return cause + _DO_NOT_RELY


def open_target(folder: str, state: Optional[ps.PrivateState] = None,
                route: str = COMMAND) -> Target:
    """The Agent Context at `folder` exactly — never a folder above or below
    it — ready for intake, or Unavailable. `folder` may be `.` or an absolute
    path (Product Specification §3.3); nothing here searches for one, and no
    message tells an agent to move into, search for or find one."""
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder) or not ac.is_context_root(folder):
        if route == MCP:
            # The registered folder, examined as retrieval examines it: documents
            # with no usable map are named as such, with the same instruction.
            exam = ac.examine(folder) if os.path.isdir(folder) else None
            raise Unavailable("context_invalid", _mcp_integrity(exam) if exam is not None
                              and exam.needs_review else _MCP_NOT_VALID, retryable=False)
        raise Unavailable("context_not_found",
                          "The folder `--context` names is not an Agent Context, so nothing was "
                          "filed. Do not search for one: return the complete proposal JSON for a "
                          "person to import.", retryable=False)
    exam = ac.examine(folder)
    # A map-format mismatch is named, never filed against (Product Specification
    # §6): decided before private state is touched, so nothing is written.
    if exam.charter_outdated:
        if route == MCP:
            # The running server is the out-of-date copy: restart or reconnect
            # the host. Never `charter_outdated`, which names a command's copy.
            raise Unavailable("server_outdated", _MCP_SERVER_OUTDATED, retryable=False)
        raise Unavailable("charter_outdated", "This Agent Context was generated by a newer version of "
                                              "Charter than the one this command ran, so nothing was "
                                              "filed. That copy of Charter is out of date: return the "
                                              "proposal JSON for a person to import, and tell them.",
                          retryable=False)
    if exam.map_outdated:
        raise Unavailable("map_outdated", "This Agent Context's map was generated by an earlier "
                                          "version of Charter, so nothing was filed. A person must "
                                          "rebuild it in Charter first; until then, return the "
                                          "proposal JSON for a person to import.", retryable=False)
    if not exam.valid:
        if route == MCP and exam.needs_review:
            raise Unavailable("context_invalid", _mcp_integrity(exam), retryable=False)
        raise Unavailable("context_invalid", "This Agent Context is not valid now, so proposals "
                                             "cannot be checked against it. A person must correct "
                                             "it in Charter.", retryable=False)
    try:
        cs = (state or ps.PrivateState.default()).for_context(folder)
    except (ps.PrivateStateError, hs.HostStateError, OSError):
        raise Unavailable("intake_unavailable", "Charter cannot file proposals on "
                                                "this computer now.", retryable=False)
    if tx.interrupted(cs):
        raise Unavailable("context_invalid", "A Charter write to this Agent Context "
                                             "was interrupted. A person must open it in Charter "
                                             "first.", retryable=False)
    return Target(folder, cs, exam)


# --- checking one proposal --------------------------------------------------------------

def _single_line(value: Any, field: str, limit: int, problems: List[Dict[str, Any]],
                 required: bool = True) -> str:
    if not isinstance(value, str) or (required and not value.strip()):
        problems.append(_problem("missing" if value in (None, "") else "not_text",
                                 f"`{field}` must be non-empty text.", field))
        return ""
    if "\n" in value or "\r" in value or len(value) > limit:
        problems.append(_problem("too_long" if len(value) > limit else "not_one_line",
                                 f"`{field}` must be one line of at most {limit} characters.",
                                 field))
        return ""
    if not_text(value):
        problems.append(_problem("not_text", f"`{field}` cannot be filed: {not_text(value)}.",
                                 field))
        return ""
    return value.strip()


def apply_replacements(body: str, replacements: Any,
                       problems: List[Dict[str, Any]]) -> Optional[str]:
    """`body` with each exact-once replacement made, or None after recording why not."""
    if not isinstance(replacements, list) or not replacements:
        problems.append(_problem("replacements_invalid", "`replacements` must be a non-empty list "
                                                        "of {\"find\", \"replace\"} objects.",
                                 "replacements"))
        return None
    text = body
    for index, rep in enumerate(replacements, start=1):
        if not isinstance(rep, dict) or set(rep) != {"find", "replace"} \
                or not isinstance(rep["find"], str) or not isinstance(rep["replace"], str):
            problems.append(_problem("replacement_malformed", f"Replacement {index} must be an "
                                     "object with only text `find` and `replace`.", "replacements"))
            return None
        if not rep["find"]:
            problems.append(_problem("replacement_empty", f"Replacement {index} has an empty "
                                                          "`find`.", "replacements"))
            return None
        count = text.count(rep["find"])
        if count != 1:
            problems.append(_problem("replacement_no_match" if count == 0 else
                                     "replacement_ambiguous",
                                     f"Replacement {index} matches {count} times in the current "
                                     "body; it must match exactly once.", "replacements"))
            return None
        text = text.replace(rep["find"], rep["replace"], 1)
    return text


FRONT_MATTER_IN_BODY = ("`proposed_body` begins with a front-matter block. Remove it and submit "
                        "again: an Agent Proposal's body is Markdown text only, because "
                        "Charter sets a candidate's metadata itself. Give a title or "
                        "scope in `proposed_meta` instead.")
FRONT_MATTER_FROM_REPLACEMENTS = ("The `replacements` would leave the body beginning with a "
                                  "front-matter block. Change them and submit again: Charter "
                                  "sets a candidate's metadata itself. Give a title or "
                                  "scope in `proposed_meta` instead.")


def body_of(text: str) -> str:
    """A document's body: its text after the front matter and the blank line
    that separates them."""
    from .docs import parse_front_matter
    _meta, body = parse_front_matter(text)
    return body[1:] if body.startswith("\n") else body


def check(raw: Any, target: Target) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """(the proposal as it would be filed, problems). Filed only when there is
    no problem: a stale proposal is refused, not filed."""
    problems: List[Dict[str, Any]] = []
    if not isinstance(raw, dict):
        return None, [_problem("not_an_object", "Submit one JSON object.")]
    for key in sorted(set(raw) - set(FIELDS)):
        problems.append(_problem("unknown_field", f"`{key}` is not a proposal field. Remove it.",
                                 key))
    for key in REQUIRED:
        if key not in raw:
            problems.append(_problem("missing", f"`{key}` is required.", key))
    agent = _single_line(raw.get("agent"), "agent", MAX_AGENT, problems) if "agent" in raw else ""
    reason = raw.get("reason")
    if "reason" in raw and (not isinstance(reason, str) or not reason.strip()
                            or len(reason) > MAX_REASON):
        problems.append(_problem("not_text", f"`reason` must be non-empty text of at most "
                                             f"{MAX_REASON} characters.", "reason"))
    operation = raw.get("operation")
    if "operation" in raw and operation not in OPERATIONS:
        problems.append(_problem("operation_unknown", "`operation` must be `create`, `amend` or "
                                                      "`retire`.", "operation"))
        operation = None
    target_path = raw.get("target_path")
    if "target_path" in raw and not isinstance(target_path, str):
        problems.append(_problem("not_text", "`target_path` must be text.", "target_path"))
        target_path = None

    impact = raw.get("expected_context_impact")
    if impact is not None and (not isinstance(impact, (str, dict, list))
                               or len(json.dumps(impact, ensure_ascii=False)) > MAX_IMPACT):
        problems.append(_problem("impact_invalid", "`expected_context_impact` must be text or "
                                 f"JSON of at most {MAX_IMPACT} characters.",
                                 "expected_context_impact"))
    meta = raw.get("proposed_meta")
    if meta is not None:
        if operation == "retire":
            problems.append(_problem("not_used", "A retire takes no `proposed_meta`.",
                                     "proposed_meta"))
        elif not isinstance(meta, dict):
            problems.append(_problem("meta_invalid", "`proposed_meta` must be an object with only "
                                                     "`title` and `scope`.", "proposed_meta"))
        else:
            for key in sorted(set(meta) - set(META_KEYS)):
                problems.append(_problem("unknown_field", f"`proposed_meta.{key}` is not "
                                         "accepted: only `title` and `scope`.",
                                         f"proposed_meta.{key}"))
            for key in META_KEYS:
                if key in meta:
                    _single_line(meta[key], f"proposed_meta.{key}", MAX_LINE, problems,
                                 required=(key == "title"))

    body = raw.get("proposed_body")
    replacements = raw.get("replacements")
    base = raw.get("base_sha256")
    for field, used_by in (("proposed_body", ("create", "amend")), ("replacements", ("amend",)),
                           ("base_sha256", ("amend", "retire"))):
        if field in raw and operation and operation not in used_by:
            problems.append(_problem("not_used", f"A {operation} takes no `{field}`.", field))
    # A body is never stripped or rewritten here: the agent corrects it.
    if operation in ("create", "amend") and isinstance(body, str) \
            and leading_front_matter(body) is not None:
        problems.append(_problem("front_matter_in_body", FRONT_MATTER_IN_BODY, "proposed_body"))
    if isinstance(body, str) and not_text(body):
        problems.append(_problem("not_text", f"`proposed_body` cannot be filed: {not_text(body)}. "
                                             "Send Markdown text only.", "proposed_body"))
    if isinstance(replacements, list) and any(
            isinstance(r, dict) and isinstance(r.get("replace"), str) and not_text(r["replace"])
            for r in replacements):
        problems.append(_problem("not_text", "A `replace` value holds a character that is not "
                                             "text. Send Markdown text only.", "replacements"))

    current: Optional[str] = None
    if operation and isinstance(target_path, str):
        if operation == "create":
            name = target_path[len(ps.CANDIDATE_PREFIX):] \
                if target_path.startswith(ps.CANDIDATE_PREFIX) else ""
            if not name or ps.name_problem(name):
                problems.append(_problem("target_invalid", "A create's `target_path` is "
                                         "`authority-candidates/<name>.md`, with a name of "
                                         "letters, digits, `.`, `_` or `-`.", "target_path"))
            # A name already in use is NOT reported: authority-candidate and
            # archived names are private (Product Specification §3.3), and
            # saying one is taken would reveal it. Acceptance assigns a free
            # name when the requested one is in use.
            if not isinstance(body, str) or not body.strip():
                problems.append(_problem("missing", "A create needs the complete "
                                                    "`proposed_body`.", "proposed_body"))
        else:
            is_governing = target_path in target.governing
            current = target.text_of(target_path)
            if operation == "retire" and is_governing:
                problems.append(_problem("target_governing", "Only an authority candidate can be "
                                         "retired. A governing document is never retired by a "
                                         "proposal.", "target_path"))
            base_ok = isinstance(base, str) and bool(_SHA.match(base))
            if not base_ok:
                problems.append(_problem("missing" if base is None else "base_invalid",
                                         f"An `{operation}` proposal needs `base_sha256`: the lowercase "
                                         "SHA-256 of the target's whole current text.",
                                         "base_sha256"))
            matches = current is not None and base_ok and base == ac.sha256_text(current)
            if is_governing:
                # A governing document is listed in the map, so its existence is
                # public: a wrong hash is reported plainly as stale.
                if base_ok and current is not None and not matches:
                    problems.append(_problem("stale", "The target changed after you read it. Read "
                                                      "it again and propose against its current "
                                                      "text.", "base_sha256"))
            elif not matches:
                # A candidate or archived name is private: one result for an
                # unknown target and a stale one alike, revealing neither whether
                # a name exists nor whether it merely changed.
                problems.append(_problem("target_unavailable",
                                         "`target_path` is not a governing document this map lists. "
                                         "To amend or retire an authority candidate, use the exact "
                                         "logical path and current text a person gave you, with its "
                                         "current `base_sha256`; read it again if it may have "
                                         "changed. Charter does not say whether a "
                                         "candidate or archived document of a given name exists.",
                                         "target_path"))
            usable = matches
            if operation == "amend":
                if ("proposed_body" in raw) == ("replacements" in raw):
                    problems.append(_problem("body_or_replacements", "An amend gives either the "
                                             "complete `proposed_body` or `replacements`, not "
                                             "both and not neither.", "proposed_body"))
                elif "proposed_body" in raw and (not isinstance(body, str) or not body.strip()):
                    problems.append(_problem("missing", "`proposed_body` must be the complete "
                                                        "new body.", "proposed_body"))
                elif "replacements" in raw and usable:
                    # Only a usable target's body is examined, so a failed match
                    # cannot become an oracle for a private candidate's contents.
                    amended = apply_replacements(body_of(current), replacements, problems)
                    if amended is not None and leading_front_matter(amended) is not None:
                        problems.append(_problem("front_matter_in_body",
                                                 FRONT_MATTER_FROM_REPLACEMENTS, "replacements"))
    if problems:
        return None, problems
    proposal = {k: raw[k] for k in FIELDS if k in raw}
    proposal["agent"] = agent
    return proposal, []


# --- filing -----------------------------------------------------------------------------

def _record_bytes(record: Dict[str, Any]) -> bytes:
    """Exactly what `host_state.write_json_atomic` writes."""
    return (json.dumps(record, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode("utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id() -> str:
    return "p-" + datetime.now(timezone.utc).strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8]


def _ledger(cs: ps.ContextState) -> Dict[str, Any]:
    try:
        data = hs.read_json(cs.path(ps.PROPOSALS, LEDGER), None)
    except hs.HostStateError:
        return {}
    records = data.get("records") if isinstance(data, dict) else None
    return records if isinstance(records, dict) else {}


# Failures that pass on their own: another program holding the file for a
# moment, or a call interrupted. Only these are worth submitting again
# unchanged; a path too long, a denied permission or a missing folder fails
# the same way every time until a person changes something.
_TRANSIENT_ERRNO = {errno.EAGAIN, errno.EBUSY, errno.EINTR, errno.ETIMEDOUT, errno.EWOULDBLOCK}
_TRANSIENT_WINERROR = {32, 33}  # sharing violation, lock violation


def _transient(exc: BaseException) -> bool:
    seen = 0
    while exc is not None and seen < 8:
        if isinstance(exc, OSError):
            if getattr(exc, "winerror", None) in _TRANSIENT_WINERROR:
                return True
            if exc.errno in _TRANSIENT_ERRNO and getattr(exc, "winerror", None) is None:
                return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


def write_failure(exc: BaseException) -> "Unavailable":
    """The `unavailable` result for a failure to write the record: retryable
    only when the cause passes on its own."""
    if _transient(exc):
        return Unavailable("intake_unavailable", "Charter could not file the proposal now. "
                                                 "Submit it again, unchanged.", retryable=True)
    return Unavailable("intake_unavailable", "Charter cannot file proposals for this Agent "
                                             "Context on this computer until a person corrects "
                                             "its private state. Submitting again will not help.",
                       retryable=False)


def _write_ledger(cs: ps.ContextState, ledger: Dict[str, Any]) -> None:
    hs.write_json_atomic(cs.path(ps.PROPOSALS, LEDGER), {"version": RECORD_VERSION, "records": ledger})


def _active_ledger(cs: ps.ContextState) -> Dict[str, Any]:
    """The ledger's entries for proposals still awaiting a decision. Entries
    whose record is gone — decided, or kept by an earlier Charter for decided
    proposals — vouch for nothing and are dropped when the ledger is next
    written. Call with the intake lock held: the ledger vouches for a record
    before the record is written."""
    folder = cs.path(ps.PROPOSALS, PENDING)
    return {pid: entry for pid, entry in _ledger(cs).items()
            if os.path.isfile(os.path.join(folder, pid + ".json"))}


def record_fingerprint(record: Dict[str, Any]) -> Optional[str]:
    """`proposal_fingerprint` of a filed record's stored proposal, recomputed —
    never read from the record — so every waiting record takes part, however
    old, without being rewritten. None for a stored proposal it cannot read."""
    proposal = record.get("proposal")
    if not isinstance(proposal, dict):
        return None
    try:
        return proposal_fingerprint(proposal)
    except (TypeError, ValueError):
        return None


def find_duplicate(cs: ps.ContextState, fingerprint: str) -> Optional[Dict[str, Any]]:
    """The waiting proposal with this checked content (`proposal_fingerprint`),
    or None. Only records the intake ledger vouches for are compared."""
    filed, _unexpected = records(cs)
    return next((r for r in filed if record_fingerprint(r) == fingerprint), None)


def _new_record(cs: ps.ContextState, proposal_id: str, source: str, proposal: Dict[str, Any],
                fingerprint: str, submitted: Any) -> Dict[str, Any]:
    record = {"version": RECORD_VERSION, "proposal_id": proposal_id, "source": source,
              "received": _now(), "proposal": proposal, "proposal_sha256": fingerprint}
    if submitted is not None:
        record["submitted_sha256"] = submission_identity(submitted)
    return record


def _unused_id(cs: ps.ContextState, taken: Optional[set] = None) -> str:
    proposal_id = new_id()
    while os.path.exists(cs.path(ps.PROPOSALS, PENDING, proposal_id + ".json")) \
            or proposal_id in (taken or ()):
        proposal_id = new_id()
    return proposal_id


def _busy() -> Unavailable:
    return Unavailable("intake_busy", "Another proposal is being filed. Submit this one again, "
                                      "unchanged.", retryable=True)


def file(folder: str, raw: Any, source: str = AGENT,
         state: Optional[ps.PrivateState] = None, submitted: Any = None,
         route: str = COMMAND) -> Dict[str, Any]:
    """Check one proposal and file it as an untrusted private review record,
    unless its checked content duplicates one still awaiting a decision.
    `submitted` is the bytes or text exactly as given, kept only as the
    record's transport digest; None — as for the MCP tool, whose arguments
    never arrived as bytes — keeps none. `route` words what the agent is told
    and nothing else. Returns the one result object."""
    try:
        target = open_target(folder, state, route)
        proposal, problems = check(raw, target)
        if problems:
            return refused_result(problems)
        fingerprint = proposal_fingerprint(proposal)
        cs = target.cs
        with cs.lock("intake", INTAKE_TIMEOUT) as held:
            if not held:
                raise _busy()
            if find_duplicate(cs, fingerprint) is not None:
                return duplicate_result(route)  # nothing written
            proposal_id = _unused_id(cs)
            record = _new_record(cs, proposal_id, source, proposal, fingerprint, submitted)
            data = _record_bytes(record)
            ledger = _active_ledger(cs)
            # The ledger vouches for the record before the record exists: a write
            # cut short leaves no record, or one the ledger does not match.
            ledger[proposal_id] = {"sha256": hashlib.sha256(data).hexdigest(), "source": source}
            _write_ledger(cs, ledger)
            hs.write_json_atomic(cs.path(ps.PROPOSALS, PENDING, proposal_id + ".json"), record)
        return pending_result(proposal_id)
    except Unavailable as exc:
        return unavailable_result(exc)
    except (ps.PrivateStateError, hs.HostStateError, OSError) as exc:
        return unavailable_result(write_failure(exc))


def replace(folder: str, raw: Any, proposal_id: Any, source: str = IMPORTED,
            state: Optional[ps.PrivateState] = None, submitted: Any = None) -> Dict[str, Any]:
    """Replace a waiting proposal with a submission of the same checked
    content, in place: the same proposal, now with this submission's received
    time, source, checked content and digests. No second proposal, and no
    record of what it replaced. Refused unless `proposal_id` still awaits a
    decision with the same content."""
    try:
        target = open_target(folder, state)
        proposal, problems = check(raw, target)
        if problems:
            return refused_result(problems)
        fingerprint = proposal_fingerprint(proposal)
        cs = target.cs
        with cs.lock("intake", INTAKE_TIMEOUT) as held:
            if not held:
                raise _busy()
            waiting = find_duplicate(cs, fingerprint)
            if waiting is None or waiting["proposal_id"] != proposal_id:
                return refused_result([_problem(
                    "not_duplicate", "That proposal is no longer awaiting review with the same "
                                     "content. Check the proposal again.")])
            record = _new_record(cs, proposal_id, source, proposal, fingerprint, submitted)
            data = _record_bytes(record)
            ledger = _active_ledger(cs)
            ledger[proposal_id] = {"sha256": hashlib.sha256(data).hexdigest(), "source": source}
            _write_ledger(cs, ledger)
            hs.write_json_atomic(cs.path(ps.PROPOSALS, PENDING, proposal_id + ".json"), record)
        return pending_result(proposal_id)
    except Unavailable as exc:
        return unavailable_result(exc)
    except (ps.PrivateStateError, hs.HostStateError, OSError) as exc:
        return unavailable_result(write_failure(exc))


# --- several proposals at once: the console's import ------------------------------------

# Each item's status (UI and Interaction Standards, Agent Proposals).
READY, AWAITING, SAME, STALE, REFUSED, MALFORMED = (
    "ready", "awaiting", "same", "stale", "refused", "malformed")
MAX_BATCH = 20


def assess(target: Target, items: List[Any]) -> List[Dict[str, Any]]:
    """Each item's status against the Agent Context now, writing nothing.

    An item is the JSON value `read_submission` read, or the Malformed it
    raised. One with the same checked content as a waiting proposal is
    AWAITING (with that record); one with the same content as an earlier item
    is SAME; so only the first of several identical items can be READY."""
    out: List[Dict[str, Any]] = []
    seen: Dict[str, int] = {}
    for index, item in enumerate(items):
        if isinstance(item, Malformed):
            out.append({"status": MALFORMED, "code": item.code})
            continue
        proposal, problems = check(item, target)
        if problems:
            codes = {p["code"] for p in problems}
            status = MALFORMED if codes == {"not_an_object"} else \
                STALE if "stale" in codes else REFUSED
            out.append({"status": status, "problems": problems})
            continue
        fingerprint = proposal_fingerprint(proposal)
        waiting = find_duplicate(target.cs, fingerprint)
        if waiting is not None:
            out.append({"status": AWAITING, "waiting": waiting, "fingerprint": fingerprint})
        elif fingerprint in seen:
            out.append({"status": SAME, "same_as": seen[fingerprint], "fingerprint": fingerprint})
        else:
            out.append({"status": READY, "proposal": proposal, "fingerprint": fingerprint})
        seen.setdefault(fingerprint, index)
    return out


def file_batch(folder: str, items: List[Tuple[Any, Any]], source: str = IMPORTED,
               state: Optional[ps.PrivateState] = None,
               fault: Optional[Any] = None) -> Dict[str, Any]:
    """File every item, or none: the console's import of the proposals a
    person selected. Each item is (the value `read_submission` read, or its
    Malformed; the submitted bytes or text). Under the writer and intake
    locks every item is assessed again; unless every one is READY nothing is
    written and the result is `refused` with each item's status. Otherwise
    the ledger vouches for every record first, and the records are written in
    one transaction (`transaction.Transaction`), so a failure — even the
    process dying — leaves none of them: a ledger entry without its record
    vouches for nothing. `fault` is for tests (`Transaction`)."""
    try:
        if not items or len(items) > MAX_BATCH:
            return refused_result([_problem("batch_size", f"Import from 1 to {MAX_BATCH} "
                                                          "proposals at a time.")])
        cs = open_target(folder, state).cs
        with cs.lock("writer", INTAKE_TIMEOUT) as writer:
            if not writer:
                raise _busy()
            with cs.lock("intake", INTAKE_TIMEOUT) as held:
                if not held:
                    raise _busy()
                target = open_target(folder, state)  # the context as it is now, under the locks
                assessed = assess(target, [raw for raw, _submitted in items])
                if any(a["status"] != READY for a in assessed):
                    return {"result": "refused", "items": assessed}
                previous = _ledger(cs)
                ledger = _active_ledger(cs)
                taken: set = set()
                writes = []
                ids = []
                for (raw, submitted), a in zip(items, assessed):
                    proposal_id = _unused_id(cs, taken)
                    taken.add(proposal_id)
                    data = _record_bytes(_new_record(cs, proposal_id, source, a["proposal"],
                                                     a["fingerprint"], submitted))
                    ledger[proposal_id] = {"sha256": hashlib.sha256(data).hexdigest(),
                                           "source": source}
                    writes.append(tx.Write(tx.PRIVATE, f"{ps.PROPOSALS}/{PENDING}/{proposal_id}.json",
                                           data.decode("utf-8"), tx.ABSENT))
                    ids.append(proposal_id)
                _write_ledger(cs, ledger)
                try:
                    tx.Transaction(cs, writes, fault=fault).run()
                except Exception:
                    try:
                        _write_ledger(cs, previous)  # tidy only: unmatched entries vouch for nothing
                    except (ps.PrivateStateError, hs.HostStateError, OSError):
                        pass
                    raise
        return {"result": "pending", "proposal_ids": ids}
    except Unavailable as exc:
        return unavailable_result(exc)
    except tx.TransactionError as exc:
        return unavailable_result(Unavailable(
            "intake_unavailable", "Charter could not file these proposals, so none was filed. "
                                  "Check them again and import them again.", retryable=True)
                                  if exc.restored else write_failure(exc))
    except (ps.PrivateStateError, hs.HostStateError, OSError) as exc:
        return unavailable_result(write_failure(exc))


def forget_decided(cs: ps.ContextState) -> None:
    """After a decision removed a proposal's record, drop its ledger entry, so
    nothing vouches for, or remembers, a decided proposal. Best effort: an
    entry left behind is dropped when the ledger is next written."""
    try:
        with cs.lock("intake", INTAKE_TIMEOUT) as held:
            if held:
                active = _active_ledger(cs)
                if active != _ledger(cs):
                    _write_ledger(cs, active)
    except (ps.PrivateStateError, hs.HostStateError, OSError):
        pass


# --- reviewing ---------------------------------------------------------------------------

class NotRegular(Exception):
    """An unexpected record that is not a regular file: it has no text to show
    or import. Its message says what it is."""


def _not_regular(path: str) -> str:
    """What the entry at `path` is when it is not a regular file — "a folder",
    "a link" or "a special file" — or "" for a regular file. Never follows a
    link."""
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return ""
    if stat.S_ISREG(mode):
        return ""
    if stat.S_ISDIR(mode):
        return "a folder"
    if stat.S_ISLNK(mode):
        return "a link"
    return "a special file"


def _read_regular(path: str, limit: int) -> bytes:
    """Up to `limit` bytes of the regular file at `path`. A link is never
    followed, and a folder, pipe or other special file is never opened for
    reading — which could read another file or wait forever: each raises
    NotRegular, as does an entry replaced by one while it is opened."""
    kind = _not_regular(path)
    if kind:
        raise NotRegular(kind)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) \
        | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as fh:
        if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
            raise NotRegular("a special file")
        return fh.read(limit)


def _read_record(path: str) -> Tuple[Optional[bytes], Optional[Dict[str, Any]]]:
    try:
        data = _read_regular(path, MAX_INPUT + 1)
    except (NotRegular, OSError):
        return None, None
    try:
        record = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return data, None
    return data, record if isinstance(record, dict) else None


def records(cs: ps.ContextState) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """(filed pending records the ledger vouches for, unexpected files)."""
    folder = cs.path(ps.PROPOSALS, PENDING)
    ledger = _ledger(cs)
    filed: List[Dict[str, Any]] = []
    unexpected: List[Dict[str, Any]] = []
    names = sorted(os.listdir(folder)) if os.path.isdir(folder) else []
    for name in names:
        path = os.path.join(folder, name)
        if name.startswith(".") and name.endswith(".tmp"):
            continue  # a write still in progress, or cut short: Charter's own
        regular = not _not_regular(path)
        data, record = _read_record(path) if regular else (None, None)
        entry = ledger.get(name[:-5]) if name.endswith(".json") else None
        why = ""
        if not regular:
            why = "It is not a regular file."
        elif data is None or record is None:
            why = "It cannot be read as a proposal record."
        elif not isinstance(entry, dict) or record.get("proposal_id") != name[:-5]:
            why = "Charter's intake did not file it."
        elif hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            why = "It changed after Charter filed it."
        if why:
            unexpected.append({"name": name, "bytes": len(data or b""), "why": why,
                               "regular": regular})
        else:
            filed.append(dict(record, source=entry.get("source", AGENT)))
    return filed, unexpected


def staleness(proposal: Dict[str, Any], target: Target) -> List[str]:
    """Why a filed proposal no longer applies as written, or []."""
    op, path = proposal["operation"], proposal["target_path"]
    if op == "create":
        # A create is never stale for a name collision: acceptance assigns a free
        # name, so a taken name is resolved rather than reported.
        return []
    current = target.text_of(path)
    if current is None:
        return ["Its target no longer exists."]
    if ac.sha256_text(current) != proposal.get("base_sha256"):
        return ["Its target changed after the proposal was written."]
    return []


def unexpected_text(cs: ps.ContextState, name: str, limit: int = 65536) -> str:
    """An unexpected file's text, for the person to inspect. Read only. A record
    that is not a regular file raises NotRegular, saying what it is."""
    folder = cs.path(ps.PROPOSALS, PENDING)
    if name not in os.listdir(folder) or "/" in name or "\\" in name:
        raise ValueError("No such unexpected record.")
    try:
        data = _read_regular(os.path.join(folder, name), limit)
    except NotRegular as exc:
        raise NotRegular(f"This record is {exc}, not a regular file, so it has no contents to show or "
                         "import. Charter leaves it unchanged; to remove it from the list, delete "
                         "it yourself.") from None
    return data.decode("utf-8", "replace")


def first_heading(body: Any) -> str:
    """The text of a Markdown body's first first-level heading, or "". The
    title a create proposal gets when it supplies none, on its card and when
    it is accepted."""
    if not isinstance(body, str):
        return ""
    return next((" ".join(ln[2:].split()) for ln in body.splitlines() if ln.startswith("# ")), "")


def title_of(p: Dict[str, Any], target: Optional[Target], cs: ps.ContextState) -> Tuple[str, str]:
    """The friendly title a proposal card leads with, and what it is
    (UI Standards): the current title of the governing document or candidate
    it targets (`current`); for a create, the title it supplies, or else its
    body's first-level heading, whether filed directly or imported
    (`proposed`); and only when Charter cannot determine one, its logical
    target path (`path`)."""
    path = p.get("target_path", "")
    if p.get("operation") == "create":
        proposed = (p.get("proposed_meta") or {}).get("title")
        if isinstance(proposed, str) and proposed.strip():
            return " ".join(proposed.split()), "proposed"
        heading = first_heading(p.get("proposed_body"))
        return (heading, "proposed") if heading else (path, "path")
    if target is not None and path in target.governing:
        return target.governing[path].title, "current"
    try:
        text = cs.read_candidate(path) if path in cs.candidates() else None
    except (ps.PrivateStateError, OSError, ValueError):
        text = None
    if text:
        meta, body = parse_front_matter(text)
        if isinstance(meta, dict) and isinstance(meta.get("title"), str) and meta["title"].strip():
            return Document(path=path, meta=meta, body=body).title, "current"
    return path, "path"


def listing(folder: str, state: Optional[ps.PrivateState] = None) -> Dict[str, Any]:
    """Pending and imported proposals, and unexpected local records, for the person."""
    cs = (state or ps.PrivateState.default()).for_context(folder)
    exam = ac.examine(cs.folder)
    filed, unexpected = records(cs)
    target = Target(cs.folder, cs, exam) if exam.valid else None
    shown = []
    for record in sorted(filed, key=lambda r: r.get("received", "")):
        p = record["proposal"]
        stale = staleness(p, target) if target else ["The Agent Context is not valid now."]
        title, title_kind = title_of(p, target, cs)
        shown.append({"proposal_id": record["proposal_id"], "source": record["source"],
                      "title": title, "title_kind": title_kind,
                      "received": record.get("received", ""), "agent": p.get("agent", ""),
                      "operation": p["operation"], "target_path": p["target_path"],
                      "reason": p.get("reason", ""),
                      "expected_context_impact": p.get("expected_context_impact"),
                      "proposed_meta": p.get("proposed_meta") or {},
                      "stale": bool(stale), "stale_reasons": stale})
    return {"pending": [s for s in shown if s["source"] == AGENT],
            "imported": [s for s in shown if s["source"] == IMPORTED],
            "unexpected": unexpected}


def trusted(cs: ps.ContextState, proposal_id: Any) -> Tuple[Dict[str, Any], str]:
    """A filed pending record and its current text, or ValueError."""
    if not isinstance(proposal_id, str):
        raise ValueError("There is no such pending proposal.")
    filed, _unexpected = records(cs)
    for record in filed:
        if record["proposal_id"] == proposal_id:
            path = cs.path(ps.PROPOSALS, PENDING, proposal_id + ".json")
            with open(path, "rb") as fh:
                return record, fh.read().decode("utf-8")
    raise ValueError("There is no such pending proposal.")
