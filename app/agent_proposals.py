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
  * `unavailable` — nothing was filed because intake could not run now; only
    then, and only when `retryable` is true, may it be submitted again unchanged.

The fields are `agent`, `operation` (`create`, `amend`, `retire`),
`target_path` and `reason`, always; `proposed_body` for a create, and for an
amend unless exact-once `replacements` are given; `base_sha256` for an amend
or retire; optional `proposed_meta` with only `title` and `scope`, for a create
or amend; and optional advisory `expected_context_impact`. Any other field is
refused. Staleness is decided by content hashes alone.

Filed records live only in private state, never in the Agent Context. Each is
also entered, with the hash of its bytes, in a private intake ledger. A file
found among the records that the ledger does not vouch for — written some other
way, changed since, or unreadable — is never treated as a proposal: it is shown
to the person as unexpected local material and left unchanged.

A person may import a proposal an agent returned as JSON instead; it is checked
exactly as the command checks it, and filed as imported. Accepting a proposal
files, updates or retires an authority candidate, after a previewed ordinary
confirmation; it never changes governing context. Rejecting it records why.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
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

PENDING, ACCEPTED, REJECTED = "pending", "accepted", "rejected"
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


def open_target(folder: str, state: Optional[ps.PrivateState] = None) -> Target:
    """The Agent Context at `folder` exactly — never a folder above it — ready
    for intake, or Unavailable."""
    folder = os.path.abspath(folder)
    if not os.path.isdir(folder) or not ac.is_context_root(folder):
        raise Unavailable("context_not_found",
                          "This folder is not an Agent Context: run the command in the folder "
                          "that holds AGENT-CONTEXT.md.", retryable=False)
    exam = ac.examine(folder)
    if not exam.valid:
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


def file(folder: str, raw: Any, source: str = AGENT,
         state: Optional[ps.PrivateState] = None) -> Dict[str, Any]:
    """Check one proposal and file it as an untrusted private review record.
    Returns the one result object."""
    try:
        target = open_target(folder, state)
        proposal, problems = check(raw, target)
        if problems:
            return refused_result(problems)
        cs = target.cs
        with cs.lock("intake", INTAKE_TIMEOUT) as held:
            if not held:
                raise Unavailable("intake_busy", "Another proposal is being filed. Submit this "
                                                 "one again, unchanged.", retryable=True)
            proposal_id = new_id()
            while os.path.exists(cs.path(ps.PROPOSALS, PENDING, proposal_id + ".json")):
                proposal_id = new_id()
            record = {"version": RECORD_VERSION, "proposal_id": proposal_id, "source": source,
                      "received": _now(), "proposal": proposal}
            data = _record_bytes(record)
            ledger = _ledger(cs)
            # The ledger vouches for the record before the record exists: a write
            # cut short leaves no record, or one the ledger does not match.
            ledger[proposal_id] = {"sha256": hashlib.sha256(data).hexdigest(), "source": source}
            hs.write_json_atomic(cs.path(ps.PROPOSALS, LEDGER),
                                 {"version": RECORD_VERSION, "records": ledger})
            hs.write_json_atomic(cs.path(ps.PROPOSALS, PENDING, proposal_id + ".json"), record)
        return pending_result(proposal_id)
    except Unavailable as exc:
        return unavailable_result(exc)
    except (ps.PrivateStateError, hs.HostStateError, OSError) as exc:
        return unavailable_result(write_failure(exc))


# --- reviewing ---------------------------------------------------------------------------

def _read_record(path: str) -> Tuple[Optional[bytes], Optional[Dict[str, Any]]]:
    try:
        with open(path, "rb") as fh:
            data = fh.read(MAX_INPUT + 1)
    except OSError:
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
        data, record = _read_record(path)
        entry = ledger.get(name[:-5]) if name.endswith(".json") else None
        why = ""
        if not os.path.isfile(path) or os.path.islink(path):
            why = "It is not a regular file."
        elif data is None or record is None:
            why = "It cannot be read as a proposal record."
        elif not isinstance(entry, dict) or record.get("proposal_id") != name[:-5]:
            why = "Charter's intake did not file it."
        elif hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            why = "It changed after Charter filed it."
        if why:
            unexpected.append({"name": name, "bytes": len(data or b""), "why": why})
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
    """An unexpected file's text, for the person to inspect. Read only."""
    folder = cs.path(ps.PROPOSALS, PENDING)
    if name not in os.listdir(folder) or "/" in name or "\\" in name:
        raise ValueError("No such unexpected record.")
    with open(os.path.join(folder, name), "rb") as fh:
        return fh.read(limit).decode("utf-8", "replace")


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


# Where a decided record's time goes until it is written: the preview, and the
# plan it is identified by, must not change merely because the clock moved.
DECIDED_AT = "@@CHARTER-DECIDED-AT@@"


def _record_text(out: Dict[str, Any]) -> str:
    return json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def decided(record: Dict[str, Any], decision: str, **detail: Any) -> str:
    """The record as it is kept once a person has decided it, its time left
    for `stamp` to fill in when it is written."""
    out = {k: v for k, v in record.items() if k != "source"}
    out["source"] = record.get("source", AGENT)
    out["decision"] = dict({"decision": decision, "decided": DECIDED_AT}, **detail)
    return _record_text(out)


def stamp(text: str) -> str:
    """A decided record with the time it is written. Only the decision's own
    time is set: nothing an agent wrote is touched."""
    out = json.loads(text)
    decision = out.get("decision") if isinstance(out, dict) else None
    if not isinstance(decision, dict) or decision.get("decided") != DECIDED_AT:
        return text
    decision["decided"] = _now()
    return _record_text(out)
