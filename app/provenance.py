"""Candidate provenance: each authority candidate's one private baseline.

Product Specification §4 and Agent Context as the Project Asset §3: for each
authority candidate Charter keeps one **candidate baseline** — the exact text
Charter last wrote for it, the kind of Charter action that wrote it, and the
date — so a person can see that the candidate's file differs from the version
Charter last wrote, and how.

  * Replaced whenever Charter writes the candidate — Create candidate, Revise,
    Edit, accepting an Agent Proposal into a candidate or a revision
    candidate, a change set's withdrawal — and by Mark as seen; discarded when
    the candidate is retired, retired through an accepted proposal, or used up
    by a change set. Every one of those is written in the same transaction as
    the candidate itself, so a rolled-back action leaves the baseline as it was.
  * One version only: no earlier baseline, no record of when or how often a
    file changed, no modification time, no editor identity. Nothing watches or
    polls candidate files; a candidate is compared with its baseline, as
    line-ending-normalized text, only when a person views it, and the
    comparison is never recorded.
  * A candidate with no baseline has none until Charter next writes it:
    Charter never adopts its current text on its own. A baseline whose
    candidate no longer exists is never shown, and the next Charter action
    discards it.
  * Private manager state, for the console only: never governing context, never
    in the Agent Context folder, never served through MCP, `charter read` or file
    access, never activity or Recent, and never part of the approved-context
    check. A difference blocks nothing.
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Optional

from . import agent_context as ac
from . import private_store as ps
from . import transaction as tx
from .docs import today

RECORD_VERSION = 1

# The kinds of Charter action a baseline records, and how a person reads each
# (UI Standards: "[event] is one of …").
CREATED, REVISED, EDITED, ACCEPTED, UPDATED, WITHDRAWN, SEEN = (
    "created", "revised", "edited", "accepted", "updated", "withdrawn", "seen")
EVENT_LABELS = {
    CREATED: "created",
    REVISED: "created through Revise",
    EDITED: "edited",
    ACCEPTED: "accepted from an Agent Proposal",
    UPDATED: "updated from an Agent Proposal",
    WITHDRAWN: "returned to candidate status by a withdrawal",
    SEEN: "marked as seen",
}

# A candidate's provenance, as the console shows it.
MATCHING, CHANGED, NONE, UNREADABLE = "matching", "changed", "none", "unreadable"

# What `against` names to compare a candidate with its baseline.
CHARTER_VERSION = "charter-version"
CHARTER_VERSION_TITLE = "Charter's version"


def record_path(logical: str) -> str:
    """A candidate's baseline record, relative to its context's private state."""
    return f"{ps.BASELINES}/{ps.candidate_name(logical)}.json"


def _logical_of(record_name: str) -> Optional[str]:
    if not record_name.endswith(".json"):
        return None
    name = record_name[:-len(".json")]
    return None if ps.name_problem(name) else ps.logical_candidate(name)


def render(text: str, event: str, day: str) -> str:
    """A baseline record: the text, LF-normalized, the event and the date."""
    return json.dumps({"version": RECORD_VERSION, "event": event, "date": day,
                       "text": text.replace("\r\n", "\n")},
                      ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def read(cs: ps.ContextState, logical: str) -> Optional[Dict[str, str]]:
    """A candidate's baseline — `{text, event, date}` — or None when it has
    none, or its record cannot be read or is not one Charter wrote. Never
    raises: a baseline is advisory and never stops anything."""
    try:
        with open(cs.path(*record_path(logical).split("/")), "rb") as fh:
            data = json.loads(fh.read().decode("utf-8"))
    except (OSError, ValueError, ps.PrivateStateError):
        return None
    if not isinstance(data, dict) or data.get("version") != RECORD_VERSION \
            or data.get("event") not in EVENT_LABELS or not isinstance(data.get("date"), str) \
            or not isinstance(data.get("text"), str):
        return None
    return {"text": data["text"].replace("\r\n", "\n"), "event": data["event"], "date": data["date"]}


def state(cs: ps.ContextState, logical: str, text: str) -> Dict[str, str]:
    """How the candidate's current `text` stands against its baseline: matching,
    changed, or none, with the baseline's event (as a person reads it) and
    date. Compared as line-ending-normalized text; nothing is written."""
    base = read(cs, logical)
    if base is None:
        return {"state": NONE, "event": "", "date": ""}
    same = base["text"] == text.replace("\r\n", "\n")
    return {"state": MATCHING if same else CHANGED, "event": EVENT_LABELS[base["event"]],
            "date": base["date"]}


def changed(cs: ps.ContextState, logical: str, text: str) -> bool:
    return state(cs, logical, text)["state"] == CHANGED


def _event_for(kind: str, old: Optional[str]) -> Optional[str]:
    """The baseline event for a candidate an action of `kind` writes."""
    if kind == "add":
        return CREATED
    if kind == "revise":
        return REVISED
    if kind == "edit-candidate":
        return EDITED
    if kind == "accept-proposal":
        return ACCEPTED if old is None else UPDATED
    if kind == "changeset":
        return WITHDRAWN  # the only candidate a change set writes is a withdrawn one
    return None


def writes(cs: ps.ContextState, kind: str, changes: Iterable[Any],
           day: Optional[str] = None) -> List[tx.Write]:
    """The baseline writes that go with an action's own: for each candidate it
    writes, its text as the new baseline; for each candidate it removes, and
    each baseline whose candidate no longer exists, the baseline removed. Made
    in the action's transaction, so they succeed or roll back with it."""
    day = day or today()
    out: List[tx.Write] = []
    touched = set()
    prefix = ps.CANDIDATES + "/"
    for c in changes:
        if c.root != tx.PRIVATE or not c.path.startswith(prefix):
            continue
        logical = ps.logical_candidate(c.path[len(prefix):])
        touched.add(logical)
        if c.new is None:
            if _has_record(cs, logical):
                out.append(tx.Write(tx.PRIVATE, record_path(logical), None))
            continue
        event = _event_for(kind, c.old)
        if event is not None:
            out.append(tx.Write(tx.PRIVATE, record_path(logical), render(c.new, event, day)))
    present = set(cs.candidates())
    for logical in _recorded(cs):
        if logical not in present and logical not in touched:
            out.append(tx.Write(tx.PRIVATE, record_path(logical), None))
    return out


def _has_record(cs: ps.ContextState, logical: str) -> bool:
    return os.path.isfile(cs.path(*record_path(logical).split("/")))


def _recorded(cs: ps.ContextState) -> List[str]:
    """Every candidate that has a baseline record, by logical path."""
    folder = cs.path(ps.BASELINES)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    out = []
    for name in sorted(names):
        logical = _logical_of(name)
        if logical and os.path.isfile(os.path.join(folder, name)) \
                and not os.path.islink(os.path.join(folder, name)):
            out.append(logical)
    return out


SEEN_STALE = ("This candidate changed after you read it, so it was not marked as seen. Read it "
              "again first.")


def mark_seen(folder: str, logical: str, sha: Any,
              state_: Optional[ps.PrivateState] = None) -> Dict[str, Any]:
    """Mark as seen: the candidate's current text, exactly as the person read
    it (`sha`), becomes its baseline, recorded as marked as seen today. It
    changes no candidate text, governing context, change set or authority, and
    keeps no earlier baseline."""
    from . import authority as au
    cs = (state_ or ps.PrivateState.default()).for_context(folder)
    with cs.lock("writer") as held:
        if not held:
            raise au.ActionRefused("Another Charter action on this Agent Context is "
                                   "in progress. Try again when it has finished.")
        au._recover(cs)
        if not isinstance(logical, str) or logical not in cs.candidates():
            raise au.ActionRefused("There is no such authority candidate.")
        try:
            text = cs.read_candidate(logical)
        except ps.PrivateStateError:
            raise au.ActionRefused(au.UNREADABLE_CANDIDATE)
        if text is None:
            raise au.ActionRefused("There is no such authority candidate.")
        if not isinstance(sha, str) or sha != ac.sha256_text(text):
            raise au.StalePlan(SEEN_STALE)
        if not changed(cs, logical, text):
            return {"seen": True, "changed": False}
        try:
            tx.Transaction(cs, [tx.Write(tx.PRIVATE, record_path(logical),
                                         render(text, SEEN, today()))]).run()
        except tx.TransactionError as exc:
            raise au.ActionRefused(f"It could not be marked as seen ({exc.message}). Nothing "
                                   "was changed.")
        return {"seen": True, "changed": True}
