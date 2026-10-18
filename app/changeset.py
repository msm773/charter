"""Coordinated change sets.

Coordinated Context Changes and Advisory Review, and the Product
Specification §3.4. A person may apply several related authority changes as
one coordinated transition: one preview of the whole governing set before and
after, one typed `change governing context`, and one all-or-nothing write of
the Agent Context's governing documents, map and metadata. Nothing here stages,
commits or otherwise operates Git, and nothing is published anywhere.

A change set is built from the candidates it includes. For each one the
person chooses exactly one decision: replace — one governing document they
select, at that document's governing path — or govern alongside, at the
candidate's own new path. The plan may also withdraw governing documents; a
withdrawal uses no candidate. Every governing document no candidate replaces
and no withdrawal names is retained, unchanged, without a separate decision.
Revise is candidate authoring, never a decision here: a revision candidate is
applied through replace like any other, and its lineage may suggest, never
select, its target. Charter never infers, selects or pre-selects a decision,
a candidate or a target — from names, versions, metadata, Agent Proposals or
advisory reports.

A draft recorded in the earlier form (record version 1) declared an outcome
for every governing document — retain, revise, replace or withdraw — and keeps
that meaning. Applied and abandoned ones are shown exactly as recorded. An
active one can be viewed, abandoned or deleted, but is never refreshed,
previewed, applied or reviewed until the person explicitly converts it
(`conversion`, `convert`); Charter never converts it automatically.

A draft is private local state, kept for this user on this computer: never in
the Agent Context, never committed, never served to agents and never
governing context. It pins the context fingerprint, and the hash of every
governing document and candidate the person reviewed; a change to any makes
the draft, and the review evidence attached to it, stale until the person
refreshes it. The plan fingerprint covers the planned rows, declared outcomes
and candidate relationships — not the title or rationale. Once applied, the
draft is kept as an immutable receipt: its final outcomes, the governing set
before and after, its advisory evidence as it stood, and a copyable summary.
"""
from __future__ import annotations

import contextlib
import datetime
import hashlib
import json
import os
import re
import uuid
from typing import Any, Dict, Iterator, List, Optional, Tuple

from . import agent_context as ac
from . import host_state as hs
from . import impact
from . import private_store as ps
from .docs import Document, parse_front_matter

RETAIN, REVISE, REPLACE, WITHDRAW = "retain", "revise", "replace", "withdraw"
# The per-document outcomes of the earlier form, kept so its records read as recorded.
OUTCOMES = (RETAIN, REVISE, REPLACE, WITHDRAW)
ALONGSIDE = "govern-alongside"
# A candidate's decision in the current form.
DECISIONS = (REPLACE, ALONGSIDE)

CURRENT, EARLIER = "current", "earlier"

ACTIVE, APPLIED, ABANDONED = "active", "applied", "abandoned"

# The lifecycle a draft is shown in.
WAITING = "waiting for required candidates or decisions"
VALID = "structurally valid"
BLOCKED = "blocked"

MAX_PROMPTS = 5
MAX_REPORTS = 10
MAX_TEXT = 20_000
RECORD_VERSION = 2
EARLIER_RECORD_VERSION = 1
_ID = re.compile(r"^[0-9a-f]{16}$")

UNTITLED = "Untitled change set"
# Decisions that only wait for the person; any other reason blocks.
_WAITING_CODES = {"decision-not-chosen", "target-not-chosen", "nothing-to-apply"}

EARLIER_FORM = ("This change set was recorded in the earlier form, which declared an outcome for "
                "every governing document. It can be viewed, abandoned or deleted. To refresh, "
                "review, preview or apply it, convert it to the current form first: Charter shows "
                "every change before it converts anything.")

PRIVATE_NOTE = ("Change-set drafts, the reports attached to them and their receipts are private "
                "local state, kept only on this computer. They are never part of the Agent "
                "Context, never committed and never served to agents; losing them loses no "
                "approved context.")


class ChangeSetError(ValueError):
    """A refusal about a draft, in words for the person."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class ChangeSetStale(ChangeSetError):
    """The draft no longer matches what it was prepared from."""

    def __init__(self, message: str, reasons: List[Dict[str, Any]]):
        super().__init__(message, 409)
        self.reasons = reasons


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


class Ctx:
    """One Agent Context and its private state."""

    def __init__(self, folder: str, state: Optional[ps.PrivateState] = None) -> None:
        self.cs = (state or ps.PrivateState.default()).for_context(folder)
        self.folder = self.cs.folder

    def secrets(self) -> List[str]:
        """What review material must never hold: local locations, in every
        spelling of each (`hs.spellings`), since the folder kept here is canonical."""
        root = os.path.dirname(os.path.dirname(self.cs.base))
        return list(dict.fromkeys(s for loc in (self.folder, self.cs.base, root)
                                  for s in hs.spellings(loc)))


# --- the private store ----------------------------------------------------------------

def _dir(ctx: Ctx) -> str:
    return ctx.cs.path(ps.CHANGESETS)


def _file(ctx: Ctx, draft_id: str) -> str:
    if not isinstance(draft_id, str) or not _ID.match(draft_id):
        raise ChangeSetError("No such change-set draft.", 404)
    return os.path.join(_dir(ctx), draft_id + ".json")


@contextlib.contextmanager
def _locked(ctx: Ctx) -> Iterator[None]:
    os.makedirs(_dir(ctx), exist_ok=True)
    with hs.file_lock(os.path.join(_dir(ctx), ".lock"), 5.0) as got:
        if not got:
            raise ChangeSetError("Another Charter window is changing change-set "
                                 "drafts. Try again in a moment.", 409)
        yield


def _read(ctx: Ctx, draft_id: str) -> Dict[str, Any]:
    path = _file(ctx, draft_id)
    if not os.path.exists(path):
        raise ChangeSetError("No such change-set draft on this computer.", 404)
    try:
        raw = hs.read_json(path, None)
    except (hs.HostStateError, OSError, ValueError, RecursionError):
        raw = None
    version = raw.get("version") if isinstance(raw, dict) else None
    draft = raw.get("draft") if isinstance(raw, dict) else None
    if version not in (RECORD_VERSION, EARLIER_RECORD_VERSION) or not isinstance(draft, dict) \
            or not _well_shaped(draft, version == EARLIER_RECORD_VERSION) \
            or draft.get("id") != draft_id:
        raise ChangeSetError("This change-set draft could not be read. It is private local state, "
                             "so no approved context is affected; delete it and start again.", 409)
    # Which form the record is in follows from its version alone, never from
    # what it holds; it is not stored in an earlier-form record.
    draft["form"] = EARLIER if version == EARLIER_RECORD_VERSION else CURRENT
    return draft


def earlier(draft: Dict[str, Any]) -> bool:
    """Whether the draft was recorded in the earlier form."""
    return draft.get("form") == EARLIER


def _well_shaped(draft: Dict[str, Any], earlier_form: bool = False) -> bool:
    """Whether a draft that parsed has the structure every reader relies on, so a
    record that is valid JSON but mis-shaped is refused as unreadable rather than
    raising deep in a consumer."""
    pins = draft.get("pins")
    if not (isinstance(draft.get("id"), str) and _ID.match(draft["id"]) and isinstance(pins, dict)
            and isinstance(pins.get("candidates"), dict)
            and isinstance(pins.get("governing"), (dict, list))):
        return False
    # Every other field a reader touches, when present, has the type it relies on.
    def texts(value: Any) -> bool:
        return isinstance(value, list) and all(isinstance(v, str) for v in value)

    def records(value: Any) -> bool:
        return isinstance(value, list) and all(isinstance(v, dict) for v in value)

    optional = {"title": lambda v: isinstance(v, str), "created": lambda v: isinstance(v, str),
                "updated": lambda v: isinstance(v, str), "rationale": lambda v: isinstance(v, str),
                "revision": lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0,
                "state": lambda v: v in (ACTIVE, APPLIED, ABANDONED),
                "candidates": texts, "retained": texts, "prompts": records,
                "applied": lambda v: v is None or isinstance(v, dict)}
    if any(key in draft and not ok(draft[key]) for key, ok in optional.items()):
        return False
    if earlier_form:
        if not (isinstance(draft.get("outcomes"), dict) and isinstance(draft.get("alongside"), list)):
            return False
        if not all(isinstance(path, str) and isinstance(o, dict)
                   and o.get("outcome", "") in ("",) + OUTCOMES
                   and isinstance(o.get("candidate") or "", str)
                   for path, o in draft["outcomes"].items()):
            return False
        if not texts(draft["alongside"]):
            return False
    else:
        decisions = draft.get("decisions")
        if not (texts(draft.get("candidates")) and texts(draft.get("withdrawals"))
                and isinstance(decisions, dict)):
            return False
        if not all(isinstance(c, str) and isinstance(d, dict)
                   and d.get("decision", "") in ("",) + DECISIONS
                   and isinstance(d.get("target", ""), str)
                   for c, d in decisions.items()):
            return False
    if not all(isinstance(p, str) and isinstance(s, str) for p, s in pins["candidates"].items()):
        return False
    reports = draft.get("reports", [])
    if not records(reports) or not all(isinstance(r.get("id"), str) and isinstance(r.get("text", ""), str)
                                       and isinstance(r.get("label", ""), str) for r in reports):
        return False
    if draft.get("state") == APPLIED:
        receipt = (draft.get("applied") or {}).get("receipt")
        if not (isinstance(receipt, dict) and records(receipt.get("outcomes"))
                and isinstance(receipt.get("before"), list) and isinstance(receipt.get("after"), list)
                and isinstance(receipt.get("summary", ""), str)
                and records(receipt.get("reports", [])) and records(receipt.get("prompts", []))):
            return False
    return True


def _record(draft: Dict[str, Any]) -> Dict[str, Any]:
    """A draft as it is stored: an earlier-form record stays one, exactly in
    its own shape."""
    if earlier(draft):
        return {"version": EARLIER_RECORD_VERSION,
                "draft": {k: v for k, v in draft.items() if k != "form"}}
    return {"version": RECORD_VERSION, "draft": dict(draft, form=CURRENT)}


def _write(ctx: Ctx, draft: Dict[str, Any]) -> Dict[str, Any]:
    draft["revision"] = int(draft.get("revision") or 0) + 1
    draft["updated"] = _now()
    hs.write_json_atomic(_file(ctx, draft["id"]), _record(draft))
    return draft


def decision_of(draft: Dict[str, Any], candidate: str) -> Dict[str, str]:
    """A candidate's decision in a current-form draft: `decision` is replace,
    govern-alongside or "" (not yet chosen); `target` is the governing document
    a replace names, or ""."""
    d = (draft.get("decisions") or {}).get(candidate) or {}
    decision = d.get("decision", "")
    return {"decision": decision, "target": d.get("target", "") if decision == REPLACE else ""}


def members(draft: Dict[str, Any]) -> List[str]:
    """The candidates the plan includes, in order."""
    if not earlier(draft):
        return list(draft["candidates"])
    out: List[str] = []
    for o in draft["outcomes"].values():
        cand = o.get("candidate") or ""
        if o.get("outcome") in (REVISE, REPLACE) and cand and cand not in out:
            out.append(cand)
    for cand in draft["alongside"]:
        if cand not in out:
            out.append(cand)
    return out


def _sync_members(draft: Dict[str, Any], now: Optional["Now"]) -> None:
    """Each included candidate is pinned as it is when it joins; one the plan
    no longer includes is let go."""
    wanted = members(draft)
    pins = draft["pins"]["candidates"]
    for path in wanted:
        if path not in pins and now is not None and path in now.candidates:
            pins[path] = now.sha(path)
    for path in [p for p in pins if p not in wanted]:
        del pins[path]
    draft["candidates"] = wanted


def rows(draft: Dict[str, Any]) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    """What the plan does to governing documents, keyed by governing path —
    `{outcome, candidate?}` — and the candidates it governs alongside. For a
    current-form draft, the replacements its candidates name and its
    withdrawals; for an earlier-form one, its rows as recorded."""
    if earlier(draft):
        return draft["outcomes"], draft["alongside"]
    outcomes: Dict[str, Dict[str, str]] = {}
    alongside: List[str] = []
    for cand in draft["candidates"]:
        d = decision_of(draft, cand)
        if d["decision"] == REPLACE and d["target"]:
            outcomes.setdefault(d["target"], {"outcome": REPLACE, "candidate": cand})
        elif d["decision"] == ALONGSIDE:
            alongside.append(cand)
    for gov in draft["withdrawals"]:
        outcomes.setdefault(gov, {"outcome": WITHDRAW})
    return outcomes, alongside


def others(draft: Dict[str, Any]) -> List[str]:
    """The governing documents the plan neither replaces nor withdraws: in the
    current form, every one of them is retained."""
    outcomes, _alongside = rows(draft)
    return sorted(g for g in draft["pins"]["governing"] if g not in outcomes)


def others_retained(draft: Dict[str, Any]) -> bool:
    """Whether every governing document the plan has no row for is retained:
    always, in the current form; by the explicit choice, in the earlier one."""
    if not earlier(draft):
        return True
    kept = set(draft.get("retained") or [])
    return all(g in kept for g in others(draft))


def plan_fingerprint(draft: Dict[str, Any]) -> str:
    """The plan: every planned governing path, declared outcome and candidate
    relationship. Not its title or rationale, and not a candidate's content,
    which its hash covers. A current-form plan is never fingerprinted like an
    earlier-form one, so converting a draft makes its review evidence stale."""
    if earlier(draft):
        plan: Dict[str, Any] = {
            "rows": sorted([g, o.get("outcome", ""), o.get("candidate", "") or ""]
                           for g, o in draft["outcomes"].items()),
            "alongside": sorted(draft["alongside"]),
            "retained": sorted(g for g in draft.get("retained") or [] if g not in draft["outcomes"]),
        }
    else:
        plan = {
            "form": CURRENT,
            "candidates": sorted([c, decision_of(draft, c)["decision"], decision_of(draft, c)["target"]]
                                 for c in draft["candidates"]),
            "withdrawals": sorted(draft["withdrawals"]),
            "retained": others(draft),
        }
    raw = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def list_drafts(ctx: Ctx) -> List[Dict[str, Any]]:
    """Every draft for this Agent Context on this computer, newest first. A
    record that cannot be read is listed as such."""
    try:
        names = sorted(n for n in os.listdir(_dir(ctx)) if n.endswith(".json"))
    except OSError:
        return []
    out = []
    for name in names:
        draft_id = name[:-5]
        if not _ID.match(draft_id):
            continue
        try:
            d = _read(ctx, draft_id)
        except ChangeSetError as exc:
            out.append({"id": draft_id, "title": "", "unreadable": str(exc), "updated": ""})
            continue
        changes = (len(d["outcomes"]) + len(d["alongside"]) if earlier(d)
                   else len(d["candidates"]) + len(d["withdrawals"]))
        item = {"id": d["id"], "title": d.get("title", ""), "state": d.get("state", ACTIVE),
                "updated": d.get("updated", ""), "form": d["form"], "changes": changes,
                "reports": len(d.get("reports") or [])}
        receipt = (d.get("applied") or {}).get("receipt") if d.get("state") == APPLIED else None
        if isinstance(receipt, dict):
            # What it did, from its receipt: the outcomes that changed
            # something, and the governing documents it established.
            item["final_outcomes"] = sum(1 for o in receipt.get("outcomes") or []
                                         if o.get("effect") != RETAIN)
            item["established"] = len(receipt.get("after") or [])
        out.append(item)
    return sorted(out, key=lambda d: d.get("updated") or "", reverse=True)


# --- the context now ----------------------------------------------------------------------

class Now:
    """The Agent Context now: its governing documents and private candidates,
    with the hash of each one's whole text, as `base_sha256` is defined."""

    def __init__(self, ctx: Ctx):
        self.ctx = ctx
        self.exam = ac.examine(ctx.folder)
        self.valid = self.exam.valid
        self.fingerprint = self.exam.fingerprint
        self.governing: Dict[str, Document] = {d.path: d for d in self.exam.documents} \
            if self.valid else {}
        self._texts: Dict[str, str] = {p: t for p, t in self.exam.texts.items()
                                       if p in self.governing}
        self.candidates: Dict[str, Document] = {}
        for logical in ctx.cs.candidates():
            text = ctx.cs.read_candidate(logical) or ""
            meta, body = parse_front_matter(text)
            self.candidates[logical] = Document(path=logical, meta=meta or {}, body=body)
            self._texts[logical] = text
        self.by_path = dict(self.governing, **self.candidates)

    def text(self, path: str) -> str:
        return self._texts.get(path, "")

    def sha(self, path: str) -> str:
        return ac.sha256_text(self.text(path))


def _pins(now: Now, candidates: List[str]) -> Dict[str, Any]:
    return {"context": now.fingerprint,
            "candidates": {p: now.sha(p) for p in candidates if p in now.candidates},
            "governing": {p: now.sha(p) for p in sorted(now.governing)}}


# --- creating and changing a draft -------------------------------------------------------

def _require_active(draft: Dict[str, Any]) -> None:
    if draft.get("state", ACTIVE) != ACTIVE:
        raise ChangeSetError(f"This change set is {draft.get('state')}; it can no longer change.")


def _clean_text(value: Any, field: str, limit: int = MAX_TEXT) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ChangeSetError(f"`{field}` must be text.")
    if len(value) > limit:
        raise ChangeSetError(f"`{field}` is too long.")
    return value


def _title(value: Any) -> str:
    title = " ".join(_clean_text(value, "title", 200).split())
    if not title:
        raise ChangeSetError("Give the change set a name. It heads the change summary.")
    return title


def _seed(now: Now, start: Any) -> Dict[str, Any]:
    """A one-document start the person chose explicitly — a candidate to
    include, with its decision not yet made unless they chose one, or a
    governing document to withdraw — as the changes it makes to a new draft.
    Nothing is inferred: not the decision, not the target, not the candidate,
    and not the draft's name."""
    if not isinstance(start, dict) or not start:
        raise ChangeSetError("`start` names one candidate to include, or one governing document "
                             "to withdraw.")
    if not now.valid:
        raise ChangeSetError("The Agent Context is not valid and clean now, so no change to its "
                             "governing context can be planned. Correct it first.", 409)
    keys = set(start)
    if keys == {"withdraw"}:
        gov = start["withdraw"]
        if not isinstance(gov, str) or gov not in now.governing:
            raise ChangeSetError(f"`{gov}` is not a governing document now.")
        return {"withdrawals": [gov]}
    unknown = keys - {"candidate", "decision", "target"}
    if unknown or "candidate" not in keys:
        raise ChangeSetError("`start` is either `candidate` — with an optional `decision` and "
                             "`target` — or `withdraw`.")
    cand = start["candidate"]
    if not isinstance(cand, str) or cand not in now.candidates:
        raise ChangeSetError(f"`{cand}` is not an authority candidate now.")
    changes: Dict[str, Any] = {"candidates": [cand]}
    if "decision" in keys or "target" in keys:
        changes["decisions"] = {cand: {"decision": start.get("decision", ""),
                                       "target": start.get("target", "")}}
    return changes


def create(ctx: Ctx, title: Any = "", start: Any = None) -> Dict[str, Any]:
    """A new plan, named only by the person: untitled until they name it,
    whatever it starts from (UI Standards). Empty, or prefilled with the one
    candidate or withdrawal `start` names. Every governing document the plan
    neither replaces nor withdraws is retained."""
    now = Now(ctx)
    changes: Dict[str, Any] = {}
    if start is not None:
        changes = _seed(now, start)
    title = _title(title) if isinstance(title, str) and title.strip() else UNTITLED
    draft = {
        "id": uuid.uuid4().hex[:16], "title": title, "created": _now(), "revision": 0,
        "state": ACTIVE, "form": CURRENT, "candidates": [], "decisions": {}, "withdrawals": [],
        "rationale": "", "pins": _pins(now, []), "prompts": [], "reports": [],
        "applied": None,
    }
    _change(draft, now, changes)
    with _locked(ctx):
        return _write(ctx, draft)


def load(ctx: Ctx, draft_id: str) -> Dict[str, Any]:
    return _read(ctx, draft_id)


def _check_revision(draft: Dict[str, Any], revision: Any) -> None:
    if revision is not None and revision != draft.get("revision"):
        raise ChangeSetError("This change set changed since you last loaded it. Reload it, review "
                             "it, and try again. Nothing was written.", 409)


def _require_current(draft: Dict[str, Any]) -> None:
    """Refused for a draft recorded in the earlier form, until it is converted."""
    if earlier(draft):
        raise ChangeSetError(EARLIER_FORM, 409)


def update(ctx: Ctx, draft_id: str, revision: Any, changes: Dict[str, Any]) -> Dict[str, Any]:
    """Change the person's own choices. Nothing here ever chooses for them."""
    with _locked(ctx):
        draft = _read(ctx, draft_id)
        _require_active(draft)
        _require_current(draft)
        _check_revision(draft, revision)
        _change(draft, Now(ctx), changes)
        return _write(ctx, draft)


_NOT_A_DECISION = {
    REVISE: ("Revise is not a change-set decision. Revise… on a governing document makes a "
             "revision candidate; include it here and choose Replace, with the document it "
             "replaces."),
    RETAIN: ("Retain is not a decision: every governing document the plan neither replaces nor "
             "withdraws is retained."),
    WITHDRAW: "A withdrawal uses no candidate: add the governing document under `withdrawals`.",
}


def _change(draft: Dict[str, Any], now: Now, changes: Dict[str, Any]) -> None:
    """Apply the person's choices to a current-form draft in memory, refusing
    any that are not valid now."""
    _require_current(draft)
    for old in ("outcomes", "alongside", "retain_others"):
        if old in changes:
            raise ChangeSetError(f"`{old}` belongs to the earlier change-set form. Include "
                                 "candidates, choose Replace or Govern alongside for each, and "
                                 "list withdrawals; every other governing document is retained.")
    if "scopes" in changes:
        raise ChangeSetError("A candidate's scope is its own metadata. Change it with Edit on "
                             "the candidate; the change set uses it as it is.")
    if "title" in changes:
        draft["title"] = _title(changes["title"])
    if "rationale" in changes:
        draft["rationale"] = _clean_text(changes["rationale"], "rationale")
    if "candidates" in changes:
        given = changes["candidates"]
        if not isinstance(given, list) or not all(isinstance(c, str) for c in given):
            raise ChangeSetError("`candidates` must list authority candidates.")
        kept: List[str] = []
        for path in given:
            if path not in now.candidates and path not in draft["candidates"]:
                raise ChangeSetError(f"`{path}` is not an authority candidate now.")
            if path not in kept:
                kept.append(path)
        draft["candidates"] = kept
        draft["decisions"] = {c: d for c, d in draft["decisions"].items() if c in kept}
    if "decisions" in changes:
        given = changes["decisions"]
        if not isinstance(given, dict):
            raise ChangeSetError("`decisions` must map included candidates to their decisions.")
        for cand, d in given.items():
            if cand not in draft["candidates"]:
                raise ChangeSetError(f"`{cand}` is not in this change set. Include it first.")
            if not isinstance(d, dict) or not set(d) <= {"decision", "target"}:
                raise ChangeSetError("Each decision is `{decision, target}`.")
            decision, target = d.get("decision", ""), d.get("target", "")
            if decision in _NOT_A_DECISION:
                raise ChangeSetError(_NOT_A_DECISION[decision])
            if decision not in ("",) + DECISIONS:
                raise ChangeSetError("Each candidate's decision is replace or govern-alongside.")
            if not isinstance(target, str):
                raise ChangeSetError("`target` names a governing document.")
            if decision != REPLACE:
                target = ""
            elif target and target not in draft["pins"]["governing"]:
                raise ChangeSetError(f"`{target}` is not a governing document in this change set.")
            draft["decisions"][cand] = {"decision": decision, "target": target}
    if "withdrawals" in changes:
        given = changes["withdrawals"]
        if not isinstance(given, list) or not all(isinstance(g, str) for g in given):
            raise ChangeSetError("`withdrawals` must list governing documents.")
        kept = []
        for gov in given:
            if gov not in draft["pins"]["governing"]:
                raise ChangeSetError(f"`{gov}` is not a governing document in this change set.")
            if gov not in kept:
                kept.append(gov)
        draft["withdrawals"] = kept
    _sync_members(draft, now)


def refresh(ctx: Ctx, draft_id: str) -> Dict[str, Any]:
    """Pin the draft to the Agent Context now, saying what changed. A
    withdrawal or replacement target that no longer governs leaves the plan; a
    document that started governing is retained, unless the person then
    replaces or withdraws it. Attached reports are kept, and checked against
    the new pins."""
    with _locked(ctx):
        draft = _read(ctx, draft_id)
        _require_active(draft)
        _require_current(draft)
        now = Now(ctx)
        if not now.valid:
            raise ChangeSetError("The Agent Context is not valid now, so the change set cannot be "
                                 "refreshed against it. Correct it first.")
        old = draft["pins"]
        changed: List[Dict[str, str]] = []
        for path in draft["candidates"]:
            if path not in now.candidates:
                changed.append({"document": path, "change": "is no longer an authority candidate; "
                                                            "remove it from this change set"})
            elif old["candidates"].get(path) != now.sha(path):
                changed.append({"document": path, "change": "candidate text changed; review it"})
        for path in old["governing"]:
            if path not in now.governing:
                changed.append({"document": path, "change": "no longer governs; it left the plan"})
                draft["withdrawals"] = [g for g in draft["withdrawals"] if g != path]
                for cand in draft["candidates"]:
                    if decision_of(draft, cand)["target"] == path:
                        draft["decisions"][cand] = {"decision": REPLACE, "target": ""}
            elif old["governing"][path] != now.sha(path):
                changed.append({"document": path, "change": "governing text changed; review its "
                                                            "place in the plan"})
        for path in now.governing:
            if path not in old["governing"]:
                changed.append({"document": path, "change": "now governs; it is retained unless "
                                                            "you replace or withdraw it"})
        if old.get("context") != now.fingerprint and not changed:
            changed.append({"document": "", "change": "the Agent Context's map or settings "
                                                      "changed; nothing in this change set "
                                                      "changed"})
        draft["pins"] = _pins(now, draft["candidates"])
        draft = _write(ctx, draft)
        return {"draft": draft, "changed": changed}


def abandon(ctx: Ctx, draft_id: str) -> Dict[str, Any]:
    with _locked(ctx):
        draft = _read(ctx, draft_id)
        _require_active(draft)
        draft["state"] = ABANDONED
        return _write(ctx, draft)


def delete(ctx: Ctx, draft_id: str) -> None:
    with _locked(ctx):
        path = _file(ctx, draft_id)
        if not os.path.exists(path):
            raise ChangeSetError("No such change-set draft on this computer.", 404)
        # An applied change set is an immutable receipt (Coordinated Context
        # Changes: "an immutable local receipt"). A draft that cannot be read,
        # or an abandoned or active draft, remains removable. A record whose
        # JSON will not parse is removable too, so a broken file is not stuck.
        try:
            state = _read(ctx, draft_id).get("state")
        except ChangeSetError:
            state = None
        if state == APPLIED:
            raise ChangeSetError("An applied change set is an immutable receipt and cannot be "
                                 "deleted.", 409)
        os.remove(path)


# --- converting an earlier-form draft -------------------------------------------------------

def conversion(draft: Dict[str, Any]) -> Dict[str, Any]:
    """What converting an active earlier-form draft would do, every change
    listed, and the current-form draft it would become. Reads only.

    Coordinated Context Changes: each revise becomes replace of the same
    governing document by the same candidate; each replace remains replace of
    the same document by the same candidate; each govern-alongside and
    withdraw is kept as declared; each retain entry, and each entry without a
    chosen outcome or candidate, is removed and listed, leaving that document
    retained."""
    if not earlier(draft):
        raise ChangeSetError("This change set is already in the current form.")
    _require_active(draft)
    changes: List[Dict[str, Any]] = []
    candidates: List[str] = []
    decisions: Dict[str, Dict[str, str]] = {}
    withdrawals: List[str] = []
    for gov in sorted(draft["outcomes"]):
        o = draft["outcomes"][gov]
        outcome, cand = o.get("outcome", ""), o.get("candidate") or ""
        entry = {"document": gov, "candidate": cand, "from": outcome}
        if outcome in (REVISE, REPLACE) and cand and cand not in candidates:
            candidates.append(cand)
            decisions[cand] = {"decision": REPLACE, "target": gov}
            changes.append(dict(entry, to=REPLACE, change="converted" if outcome == REVISE else "kept"))
        elif outcome in (REVISE, REPLACE) and cand:
            # One candidate, one decision: a second row naming it cannot be kept.
            changes.append(dict(entry, to="", change="removed", why="candidate-used-twice"))
        elif outcome == WITHDRAW:
            withdrawals.append(gov)
            changes.append(dict(entry, to=WITHDRAW, change="kept"))
        elif outcome == RETAIN:
            changes.append(dict(entry, to="", change="removed", why="retained"))
        else:
            changes.append(dict(entry, to="", change="removed",
                                why="candidate-not-chosen" if outcome else "undecided"))
    for cand in draft["alongside"]:
        entry = {"document": "", "candidate": cand, "from": ALONGSIDE}
        if cand in candidates:
            changes.append(dict(entry, to="", change="removed", why="candidate-used-twice"))
            continue
        candidates.append(cand)
        decisions[cand] = {"decision": ALONGSIDE, "target": ""}
        changes.append(dict(entry, to=ALONGSIDE, change="kept"))
    retained = sorted(g for g in draft.get("retained") or [] if g not in draft["outcomes"])
    if retained:
        changes.append({"document": "", "candidate": "", "documents": retained, "from": "retain-others",
                        "to": "", "change": "removed", "why": "retained"})
    converted = {k: v for k, v in draft.items() if k not in ("outcomes", "alongside", "retained")}
    converted.update(form=CURRENT, candidates=candidates, decisions=decisions,
                     withdrawals=withdrawals, pins=json.loads(json.dumps(draft["pins"])))
    _sync_members(converted, None)
    return {"changes": changes, "draft": converted,
            "plan_fingerprint": plan_fingerprint(converted)}


def convert(ctx: Ctx, draft_id: str, revision: Any) -> Dict[str, Any]:
    """Convert an active earlier-form draft to the current form, exactly as
    `conversion` lists it, once the person confirms. Changes no governing
    context. The plan changes, so attached reports and prompt records become
    stale; they are kept as historical evidence."""
    with _locked(ctx):
        draft = _read(ctx, draft_id)
        _require_active(draft)
        _check_revision(draft, revision)
        out = conversion(draft)
        return {"draft": _write(ctx, out["draft"]), "changes": out["changes"]}


def receipt_of(draft: Dict[str, Any], ev: Dict[str, Any], review: Dict[str, Any]) -> Dict[str, Any]:
    """What an applied change set keeps: its final outcomes, the governing set
    before and after, its summary, and its advisory evidence as it stood when
    it applied. Never changed afterwards."""
    keep = ("effect", "document", "title", "candidate", "candidate_title", "archived_to",
            "withdrawn_to", "scope_before", "scope_proposed", "scope_after")
    return {
        "outcomes": [{k: e[k] for k in keep if k in e} for e in ev["effects"]],
        "before": ev["before"], "after": ev["after"], "summary": ev["summary"],
        "plan_fingerprint": plan_fingerprint(draft),
        "reports": [{k: r.get(k) for k in ("id", "label", "attached", "status", "issues", "claims")}
                    for r in attached(review)],
        "prompts": [{k: p[k] for k in ("mode", "copied", "exported") if k in p}
                    for p in draft.get("prompts") or []],
    }


# The time an applied record says it was applied is known only when it is
# written; a plan carries this placeholder, so a preview and its apply are the
# same plan, and the transaction writes the time.
APPLIED_AT = "@@CHARTER-APPLIED-AT@@"


def record_path(draft_id: str) -> str:
    """A draft's record, relative to the context's private state."""
    return f"{ps.CHANGESETS}/{draft_id}.json"


def record_text(draft: Dict[str, Any]) -> str:
    """A draft record's text, exactly as `_write` stores it."""
    return json.dumps(_record(draft), ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def applied_record(draft: Dict[str, Any], receipt: Dict[str, Any], fingerprint: str) -> str:
    """The draft as kept once applied: its immutable receipt, written in the
    same transaction as the change set itself."""
    out = dict(draft, state=APPLIED, revision=int(draft.get("revision") or 0) + 1,
               updated=APPLIED_AT,
               applied={"at": APPLIED_AT, "fingerprint": fingerprint, "receipt": receipt})
    return record_text(out)


def stamp(text: str) -> str:
    """An applied record with the time it is written."""
    return text.replace(APPLIED_AT, _now())


@contextlib.contextmanager
def holding(ctx: Ctx) -> Iterator[None]:
    """Hold this context's change-set lock: no draft changes meanwhile."""
    with _locked(ctx):
        yield


# --- what the draft would do -----------------------------------------------------------

def _reason(code: str, message: str, document: str = "", refreshable: bool = False) -> Dict[str, Any]:
    return {"code": code, "message": message, "document": document, "refreshable": refreshable}


def stale_reasons(draft: Dict[str, Any], now: Now) -> List[Dict[str, Any]]:
    """Why the draft no longer matches what the person reviewed."""
    pins = draft["pins"]
    out: List[Dict[str, Any]] = []
    if not now.valid:
        out.append(_reason("context-invalid", "The Agent Context is not valid now. Correct it, "
                                              "then refresh this change set."))
        return out
    for path in draft["candidates"]:
        if path not in now.candidates:
            out.append(_reason("candidate-missing", "This is no longer an authority candidate. "
                                                    "Remove it from this change set.", path))
        elif pins["candidates"].get(path) != now.sha(path):
            out.append(_reason("candidate-changed", "This candidate changed after it was added or "
                                                    "last refreshed.", path, True))
    changed_doc = False
    for path in pins["governing"]:
        if path not in now.governing:
            changed_doc = True
            out.append(_reason("target-no-longer-governs", "This document no longer governs.",
                               path, True))
        elif pins["governing"][path] != now.sha(path):
            changed_doc = True
            out.append(_reason("governing-changed", "This governing document changed after the "
                                                    "change set was prepared.", path, True))
    for path in sorted(now.governing):
        if path not in pins["governing"]:
            changed_doc = True
            out.append(_reason("new-governing", "This document started governing after the change "
                                                "set was prepared. Refresh the change set: it is "
                                                "retained unless you replace or withdraw it.",
                               path, True))
    if pins.get("context") != now.fingerprint and not changed_doc:
        out.append(_reason("context-changed", "The Agent Context's map or settings changed after "
                                              "this change set was prepared.", "", True))
    return out


def decision_reasons(draft: Dict[str, Any], governing: Optional[int] = None) -> List[Dict[str, Any]]:
    """What the person still has to decide, or has decided inconsistently. An
    active earlier-form draft has one reason: it must be converted first.
    `governing`, the number of documents governing now, lets a Replace with
    nothing to replace say so."""
    if earlier(draft):
        if draft.get("state", ACTIVE) != ACTIVE:
            return []
        return [_reason("earlier-form", EARLIER_FORM)]
    out: List[Dict[str, Any]] = []
    replaced: Dict[str, List[str]] = {}
    for cand in draft["candidates"]:
        d = decision_of(draft, cand)
        if not d["decision"]:
            out.append(_reason("decision-not-chosen", "Not yet decided: choose Replace, with the "
                                                      "governing document it replaces, or Govern "
                                                      "alongside.", cand))
        elif d["decision"] == REPLACE and not d["target"] and governing == 0:
            out.append(_reason("target-not-chosen", "No document governs yet, so there is nothing "
                                                    "to replace: choose Govern alongside.", cand))
        elif d["decision"] == REPLACE and not d["target"]:
            out.append(_reason("target-not-chosen", "Choose the governing document this candidate "
                                                    "replaces.", cand))
        elif d["decision"] == REPLACE:
            replaced.setdefault(d["target"], []).append(cand)
    for gov in sorted(replaced):
        if len(replaced[gov]) > 1:
            out.append(_reason("target-replaced-twice", "More than one candidate replaces this "
                                                        "governing document. Each is replaced at "
                                                        "most once.", gov))
        if gov in draft["withdrawals"]:
            out.append(_reason("target-replaced-and-withdrawn", "This governing document is both "
                                                                "replaced and withdrawn. Choose one.",
                               gov))
    if not draft["candidates"] and not draft["withdrawals"]:
        out.append(_reason("nothing-to-apply", "This change set changes nothing yet: include a "
                                               "candidate, or withdraw a governing document."))
    return out


_EFFECT_WORDS = {REVISE: "Revise", REPLACE: "Replace", WITHDRAW: "Withdraw", RETAIN: "Retain",
                 ALONGSIDE: "Govern alongside"}


def summary_text(draft: Dict[str, Any], effects: List[Dict[str, Any]],
                 review: Optional[Dict[str, Any]] = None, applied: bool = False) -> str:
    """The change summary offered to copy: declared outcomes — final once
    applied — rationale and the advisory review. Nothing private."""
    lines = [f"Change set: {' '.join(draft['title'].split())}", "",
             "Final outcomes:" if applied else "Declared outcomes:"]
    order = {REVISE: 0, REPLACE: 1, WITHDRAW: 2, ALONGSIDE: 3, RETAIN: 4}
    for e in sorted(effects, key=lambda e: (order[e["effect"]], e["document"])):
        if e["effect"] in (REVISE, REPLACE):
            lines.append(f"- {_EFFECT_WORDS[e['effect']]} `{e['document']}` (“{e['title']}”) with "
                         f"candidate `{e['candidate']}` (“{e['candidate_title']}”); the replaced "
                         f"version is archived privately as `{e['archived_to']}`.")
        elif e["effect"] == WITHDRAW:
            lines.append(f"- Withdraw `{e['document']}` (“{e['title']}”); it becomes an authority "
                         f"candidate again as `{e['withdrawn_to']}`.")
        elif e["effect"] == ALONGSIDE:
            lines.append(f"- Govern alongside: `{e['candidate']}` (“{e['title']}”) governs at "
                         f"`{e['document']}`.")
        else:
            lines.append(f"- Retain `{e['document']}` (“{e['title']}”), unchanged.")
    rationale = (draft.get("rationale") or "").strip()
    lines += ["", "Context-impact rationale:", rationale or "None given."]
    lines += ["", "Advisory review:"]
    reports = attached(review)
    if not reports:
        lines.append("- No advisory report attached.")
    else:
        counts: Dict[str, int] = {}
        for r in reports:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        described = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
        lines.append(f"- {len(reports)} advisory report(s) attached ({described}). Reports are an "
                     "agent's advisory claims; Charter checked their form only, not "
                     "their conclusions.")
    lines.append("- The person decided every outcome.")
    return "\n".join(lines) + "\n"


def evaluate(ctx: Ctx, draft: Dict[str, Any], now: Optional[Now] = None,
             review: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Everything the person needs to see about a draft: its reasons, the
    governing set before and after, every effect, and the plan when it can be
    built. Reads only."""
    from . import authority as au
    now = now or Now(ctx)
    if review is None:
        review = review_checks(ctx, draft, now)
    # An earlier-form draft is never evaluated against the context now: it
    # is shown as recorded until the person converts it.
    stale = [] if earlier(draft) else stale_reasons(draft, now)
    decisions = decision_reasons(draft, len(now.governing))
    result: Dict[str, Any] = {"stale": bool(stale), "reasons": stale + decisions, "plan": None,
                              "effects": [], "before": [], "after": [], "summary": ""}
    result["before"] = [{"path": d.path, "title": d.title, "id": d.id,
                         "scope": str(d.meta.get("scope") or "")}
                        for d in sorted(now.governing.values(), key=lambda d: d.path)]
    if draft.get("state", ACTIVE) != ACTIVE or stale or decisions:
        return result
    try:
        plan, effects = au.changeset_plan(ctx.folder, draft, summary_text, review)
    except au.ActionRefused as exc:
        result["reasons"].append(_reason("validation", str(exc)))
        return result
    for problem in plan.problems:
        result["reasons"].append(_reason("validation", problem))
    after_titles: Dict[str, List[str]] = {}
    for d in plan.after:
        after_titles.setdefault(" ".join(d["title"].split()).casefold(), []).append(d["path"])
    new_paths = {e["document"] for e in effects if e["effect"] != RETAIN}
    for group in after_titles.values():
        if len(group) > 1 and new_paths.intersection(group):
            result["reasons"].append(_reason("validation", "Governing documents would share one "
                                             "title: " + ", ".join(f"`{p}`" for p in sorted(group))
                                             + ".", sorted(group)[0]))
    effect_of = {e["document"]: e["effect"] for e in effects}
    result["after"] = [dict(d, effect=("added" if effect_of.get(d["path"]) == ALONGSIDE else
                                       "revised" if effect_of.get(d["path"]) == REVISE else
                                       "replaced" if effect_of.get(d["path"]) == REPLACE else
                                       "retained"))
                       for d in plan.after]
    result["effects"] = effects
    result["plan"] = plan
    result["summary"] = summary_text(draft, effects, review)
    return result


def lifecycle(draft: Dict[str, Any], evaluation: Dict[str, Any]) -> str:
    state = draft.get("state", ACTIVE)
    if state != ACTIVE:
        return state
    codes = {r["code"] for r in evaluation["reasons"]}
    if not codes:
        return VALID
    if codes <= _WAITING_CODES:
        return WAITING
    return BLOCKED


def review_stage(draft: Dict[str, Any], review: Optional[Dict[str, Any]] = None) -> str:
    if attached(review) if review is not None else draft.get("reports"):
        return "report attached"
    if draft.get("prompts"):
        last = draft["prompts"][-1]
        return "review packet saved" if last.get("mode") == impact.PACKET else "prompt copied"
    return "no review requested"


def load_for_apply(ctx: Ctx, draft_id: Any, draft_revision: Any) -> Dict[str, Any]:
    """The active draft to apply, refused while stale or incomplete."""
    draft = _read(ctx, draft_id)
    _require_active(draft)
    _require_current(draft)
    _check_revision(draft, draft_revision)
    now = Now(ctx)
    stale = stale_reasons(draft, now)
    if stale:
        raise ChangeSetStale("This change set is stale: "
                             + " ".join(f"{r['document'] or 'Agent Context'}: {r['message']}"
                                        for r in stale[:3])
                             + " Refresh it and review it again. Nothing was written.", stale)
    decisions = decision_reasons(draft, len(now.governing))
    if decisions:
        raise ChangeSetError("This change set cannot be applied yet: "
                             + " ".join(f"{r['document'] or 'Change set'}: {r['message']}"
                                        for r in decisions[:3]))
    return draft


def candidate_material(ctx: Ctx, draft: Dict[str, Any], now: Now) -> List[Dict[str, Any]]:
    """The included candidates as they are now: what a prompt fences and what
    a report's citations are checked against."""
    return [{"path": p, "title": now.candidates[p].title,
             "scope": str(now.candidates[p].meta.get("scope") or ""),
             "sha256": now.sha(p), "text": now.text(p)}
            for p in draft["candidates"] if p in now.candidates]


def review_checks(ctx: Ctx, draft: Dict[str, Any], now: Now) -> Dict[str, Any]:
    """Each attached report, checked for form against the context now. A
    report is never verified as correct; a stale one is never current review
    evidence."""
    identity = impact.context_identity(now) if now.valid else None
    material = {c["path"]: c for c in candidate_material(ctx, draft, now)}
    planned = plan_fingerprint(draft)
    reports = []
    for r in draft.get("reports") or []:
        if identity is None:
            checked = {"status": impact.STALE, "claims": None, "issues": [impact._issue(
                impact.STALE, "The Agent Context is not valid now, so no report can be current.")]}
        else:
            checked = impact.check_report(r.get("text", ""), identity, material, planned)
        text = r.get("text", "")
        if not text.strip():
            # A review added but not yet written: nothing to check, and no evidence.
            checked = {"status": EMPTY, "claims": None, "issues": []}
        reports.append({"id": r["id"], "label": r.get("label", ""), "attached": r.get("attached", ""),
                        "text": text, **checked, "valid": structurally_valid(checked)})
    return {"identity": identity, "reports": reports}


# A review whose text is not yet written.
EMPTY = "empty"


def structurally_valid(checked: Dict[str, Any]) -> bool:
    """Whether a review's text is a structurally valid report (UI Standards:
    only such a review counts as an attached advisory report): it parses as a
    report, with no malformed field. A stale report, or one whose quotes or
    paths do not match, is still a report, shown with those issues."""
    return (checked.get("status") not in (impact.MALFORMED, EMPTY)
            and not any(i.get("category") == impact.MALFORMED for i in checked.get("issues") or []))


def attached(review: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The reviews that count as attached advisory reports: structurally valid
    ones only. Invalid or incomplete text stays in the draft, as written."""
    return [r for r in (review or {}).get("reports") or [] if r.get("valid")]


def plan_lines(draft: Dict[str, Any]) -> List[str]:
    """The complete planned change, one line each, as review material shows it."""
    lines = []
    for cand in draft["candidates"]:
        d = decision_of(draft, cand)
        if d["decision"] == REPLACE:
            lines.append(f"replace `{d['target']}` with candidate `{cand}`")
        else:
            lines.append(f"govern alongside: `{cand}`")
    lines += [f"withdraw `{gov}`" for gov in draft["withdrawals"]]
    rest = others(draft)
    if rest:
        lines.append("retain every other governing document: "
                     + ", ".join(f"`{g}`" for g in rest))
    return lines


def prompt_unavailable(draft: Dict[str, Any], ev: Dict[str, Any],
                       identity: Optional[Dict[str, Any]]) -> str:
    """Why no review material can be prepared now, or "": only a structurally
    complete plan, current with the context, has one."""
    if earlier(draft):
        return EARLIER_FORM
    if identity is None:
        return "The Agent Context is not valid now, so there is no current context to review against."
    if ev["stale"]:
        return "Refresh the change set first: review material is prepared from the context as it is now."
    if any(r["code"] in _WAITING_CODES for r in ev["reasons"]):
        return ("The review is prepared once the plan is complete: every candidate has its "
                "decision, and every replacement its governing document.")
    # A plan that is blocked, or that could not be built and validated, has no
    # resulting context to review: material is prepared only for a
    # structurally valid one.
    if ev["reasons"] or ev.get("plan") is None:
        return ("The plan is blocked: correct what Readiness lists, and the review material is "
                "prepared once the plan is structurally valid.")
    return ""


def prepare_prompt(ctx: Ctx, draft: Dict[str, Any], now: Now,
                   identity: Dict[str, Any]) -> Dict[str, Any]:
    """The review material for the plan as it is now: one self-contained
    prompt while it fits the practical single-message limit, and past it the
    same review as one portable packet. Preparing either sends and keeps
    nothing."""
    material = candidate_material(ctx, draft, now)
    planned = plan_fingerprint(draft)
    lines = plan_lines(draft)
    prompt = impact.generate_prompt(identity, material, lines, planned)
    over = prompt["size_chars"] > impact.PRACTICAL_LIMIT_CHARS
    if over:
        prompt = impact.generate_prompt(identity, material, lines, planned, packet=True)
    # Only Charter's own wording is checked: the reviewed documents and
    # candidates are embedded exactly as they read, whatever they quote.
    if impact.private_leaks(impact.prompt_framing(identity, material, lines, planned, over),
                            ctx.secrets()):
        raise ChangeSetError("The review material would contain a private location in Charter's "
                             "own wording, so it was not prepared.")
    prompt.update(plan_fingerprint=planned, fingerprint=identity["fingerprint"],
                  includes={"documents": len(identity["documents"]), "candidates": len(material),
                            "governing_text": True},
                  limit=impact.PRACTICAL_LIMIT_CHARS, over_limit=over)
    if over:
        name = impact.packet_file_name(identity["project"], planned)
        prompt.update(file_name=name, request=impact.packet_request(name, planned))
    return prompt


def packet_material(ctx: Ctx, draft_id: str, planned: Any) -> Dict[str, Any]:
    """The review packet for this draft's plan as it is now, for the person to
    save: only for a complete, current plan past the practical limit, and only
    for the plan the person is looking at."""
    draft = _read(ctx, draft_id)
    _require_active(draft)
    _require_current(draft)
    if planned != plan_fingerprint(draft):
        raise ChangeSetError("The plan changed after you last loaded it. Review the current plan, "
                             "then save its packet.", 409)
    now = Now(ctx)
    review = review_checks(ctx, draft, now)
    ev = evaluate(ctx, draft, now, review)
    why = prompt_unavailable(draft, ev, review["identity"])
    if why:
        raise ChangeSetError(why)
    material = prepare_prompt(ctx, draft, now, review["identity"])
    if not material["over_limit"]:
        raise ChangeSetError("This review fits in one message: copy the review prompt instead.")
    return material


def _remember(ctx: Ctx, draft_id: str, planned: Any, entry: Dict[str, Any]) -> Dict[str, Any]:
    with _locked(ctx):
        draft = _read(ctx, draft_id)
        _require_active(draft)
        _require_current(draft)
        if planned != plan_fingerprint(draft):
            raise ChangeSetError("The plan changed after this review material was prepared. Use "
                                 "the current material.", 409)
        entry["plan_fingerprint"] = planned
        draft["prompts"] = (draft.get("prompts") or [])[-(MAX_PROMPTS - 1):] + [entry]
        return _write(ctx, draft)


def record_copy(ctx: Ctx, draft_id: str, mode: Any, planned: Any) -> Dict[str, Any]:
    """The person copied the self-contained prompt: their deliberate
    disclosure, remembered with the draft. The prompt's text is not kept."""
    if mode != impact.SELF_CONTAINED:
        raise ChangeSetError("Only the self-contained review prompt is copied.")
    return _remember(ctx, draft_id, planned, {"mode": mode, "copied": _now()})


def record_packet(ctx: Ctx, draft_id: str, planned: Any) -> Dict[str, Any]:
    """The person saved a review packet: only that it happened, when, and for
    which plan — never its content or where."""
    return _remember(ctx, draft_id, planned, {"mode": impact.PACKET, "exported": _now()})


def attach_report(ctx: Ctx, draft_id: str, text: Any, label: Any = "") -> Dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ChangeSetError("Paste the agent's report to attach it.")
    if len(text) > impact.MAX_REPORT_CHARS:
        raise ChangeSetError("This report is too large to attach.")
    label = _clean_text(label, "label", 200).strip()
    with _locked(ctx):
        draft = _read(ctx, draft_id)
        _require_active(draft)
        _require_current(draft)
        reports = draft.get("reports") or []
        if len(reports) >= MAX_REPORTS:
            raise ChangeSetError(f"A change set holds at most {MAX_REPORTS} reports. Remove one first.")
        reports.append({"id": uuid.uuid4().hex[:12], "label": label or f"Report {len(reports) + 1}",
                        "attached": _now(), "text": text})
        draft["reports"] = reports
        return _write(ctx, draft)


def add_review(ctx: Ctx, draft_id: str) -> Dict[str, Any]:
    """Add Another Review: a new, empty review, its reviewing agent not yet
    named. It is private draft state and counts as nothing until its text is
    a structurally valid report."""
    with _locked(ctx):
        draft = _read(ctx, draft_id)
        _require_active(draft)
        _require_current(draft)
        reports = draft.get("reports") or []
        if len(reports) >= MAX_REPORTS:
            raise ChangeSetError(f"A change set holds at most {MAX_REPORTS} reviews. Remove one first.")
        reports.append({"id": uuid.uuid4().hex[:12], "label": "", "attached": _now(), "text": ""})
        draft["reports"] = reports
        return _write(ctx, draft)


def save_review(ctx: Ctx, draft_id: str, report_id: Any, label: Any = None, text: Any = None) -> Dict[str, Any]:
    """Save one review as it is written — its reviewing agent, its text, or
    both — exactly as given, valid or not. Nothing else in the draft changes."""
    if text is not None:
        if not isinstance(text, str):
            raise ChangeSetError("A review's text must be text.")
        if len(text) > impact.MAX_REPORT_CHARS:
            raise ChangeSetError("This review is too large to keep.")
    label = None if label is None else _clean_text(label, "reviewing agent", 200)
    with _locked(ctx):
        draft = _read(ctx, draft_id)
        _require_active(draft)
        _require_current(draft)
        review = next((r for r in draft.get("reports") or [] if r.get("id") == report_id), None)
        if review is None:
            raise ChangeSetError("No such review on this change set.", 404)
        if label is not None:
            review["label"] = label
        if text is not None:
            review["text"] = text
        return _write(ctx, draft)


def remove_report(ctx: Ctx, draft_id: str, report_id: Any) -> Dict[str, Any]:
    with _locked(ctx):
        draft = _read(ctx, draft_id)
        _require_active(draft)
        _require_current(draft)
        kept = [r for r in draft.get("reports") or [] if r.get("id") != report_id]
        if len(kept) == len(draft.get("reports") or []):
            raise ChangeSetError("No such report on this change set.", 404)
        draft["reports"] = kept
        return _write(ctx, draft)
