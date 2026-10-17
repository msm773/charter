"""Console endpoints for coordinated change sets and advisory context-impact
review, for the person in the console only.

Preparing, refreshing or abandoning a draft, copying a review prompt, saving a
review packet and attaching a report change no governing context and need no
phrase. Applying a change set goes through the same plan → apply path as every
authority action, confirmed once by typing `change governing context`. An
applied change set is shown as its immutable receipt.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from . import authority as au
from . import changeset
from . import host_state as hs
from . import impact, review_packet
from .console import ApiError, Session, candidate_source, pick_save_file


def _guard(fn: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    try:
        return fn()
    except changeset.ChangeSetStale as exc:
        raise ApiError(str(exc), 409, {"changeset_reasons": exc.reasons})
    except changeset.ChangeSetError as exc:
        raise ApiError(str(exc), exc.status)
    except impact.ImpactError as exc:
        raise ApiError(str(exc))
    except au.StalePlan as exc:
        raise ApiError(str(exc), 409, {"stale": True})
    except au.ApplyFailed as exc:
        raise ApiError(str(exc), 409, {"restored": exc.restored, "unrestored": exc.unrestored})
    except au.ActionRefused as exc:
        raise ApiError(str(exc))
    except hs.HostStateError as exc:
        raise ApiError(f"{exc} No approved context is affected.", 409)


def _ctx(session: Session) -> changeset.Ctx:
    return changeset.Ctx(session.require())


def _id(body: Dict[str, Any]) -> str:
    value = body.get("id")
    if not isinstance(value, str) or not value:
        raise ApiError("`id` is required.")
    return value


def _public(draft: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: draft.get(k) for k in ("id", "title", "created", "updated", "revision", "state",
                                     "rationale")}
    out["untitled"] = draft.get("title") == changeset.UNTITLED
    return out


def detail(ctx: changeset.Ctx, draft: Dict[str, Any]) -> Dict[str, Any]:
    """A draft as the person sees it. Active: the plan's rows, every reason it
    is not ready, the governing set before and after, the review material
    prepared from it, and each report's form checks apart from its claims.
    Applied: its receipt, as it was applied."""
    if draft.get("state") == changeset.APPLIED:
        return receipt_detail(draft)
    now = changeset.Now(ctx)
    review = changeset.review_checks(ctx, draft, now)
    ev = changeset.evaluate(ctx, draft, now, review)
    identity = review["identity"]
    plan = ev["plan"]
    active = draft.get("state", changeset.ACTIVE) == changeset.ACTIVE

    governing_docs = list(now.governing.values())
    archived = au.archived_metas(ctx.cs)

    def candidate(path: str) -> Dict[str, Any]:
        doc = now.candidates.get(path)
        source = str(doc.meta.get("source") or "") if doc else ""
        source_kind, source_agent = candidate_source(doc.meta) if doc else ("create", "")
        lineage = au.revision_lineage(doc.meta, governing_docs, now.exam.hashes, archived) \
            if doc else {"revises_path": "", "revises_title": "", "revises_current": True}
        base = now.governing.get(lineage["revises_path"])
        return {"path": path, "title": doc.title if doc else path,
                "scope": str(doc.meta.get("scope") or "") if doc else "",
                "present": doc is not None,
                "origin": "agent-proposal" if source.startswith("Agent Proposal ") else "",
                "source_kind": source_kind,
                "source_agent": source_agent,
                "created": str(doc.meta.get("created") or "") if doc else "",
                "change_summary": au.change_summary(doc.body, base.body if base else None)
                if doc else "",
                **lineage}

    def governing(path: str) -> Dict[str, Any]:
        doc = now.governing.get(path)
        return {"path": path, "title": doc.title if doc else path,
                "scope": str(doc.meta.get("scope") or "") if doc else "", "governs": doc is not None}

    plan_view: Dict[str, Any]
    if changeset.earlier(draft):
        # As recorded: per-document outcomes, never re-decided here.
        retained = set(draft.get("retained") or [])
        plan_view = {"earlier": {
            "rows": [dict(governing(path), outcome=draft["outcomes"][path].get("outcome", ""),
                          candidate=candidate(draft["outcomes"][path]["candidate"])
                          if draft["outcomes"][path].get("candidate") else None)
                     for path in sorted(draft["outcomes"])],
            "alongside": [candidate(p) for p in draft["alongside"]],
            "others": [dict(governing(p), retained=p in retained) for p in changeset.others(draft)],
            "others_retained": changeset.others_retained(draft)},
            "conversion": conversion_view(now, draft) if active else None}
    else:
        plan_view = {
            "plan_candidates": [dict(candidate(p), **changeset.decision_of(draft, p),
                                     target_title=(governing(changeset.decision_of(draft, p)["target"])
                                                   ["title"] if changeset.decision_of(draft, p)["target"]
                                                   else ""))
                                for p in draft["candidates"]],
            "withdrawals": [governing(p) for p in draft["withdrawals"]],
            "retained": [governing(p) for p in changeset.others(draft)]}
    used = set(draft["candidates"])
    available = [dict(candidate(p), used=p in used)
                 for p in sorted(now.candidates, key=lambda p: (now.candidates[p].title.casefold(), p))]

    review_prompt: Dict[str, Any] = {"ready": False, "reason": ""}
    if active:
        why = changeset.prompt_unavailable(draft, ev, identity)
        if why:
            review_prompt["reason"] = why
        else:
            try:
                prompt = changeset.prepare_prompt(ctx, draft, now, identity)
            except (changeset.ChangeSetError, impact.ImpactError) as exc:
                review_prompt["reason"] = str(exc)
            else:
                review_prompt = dict(prompt, ready=True, reason="")
                if prompt["over_limit"]:
                    # Past the limit there is nothing to copy: the packet is
                    # saved to a file, and its text never travels to the page.
                    review_prompt.pop("text")
    copied = [p for p in draft.get("prompts") or [] if p.get("copied") or p.get("exported")]
    planned = changeset.plan_fingerprint(draft)
    return {
        "draft": _public(draft),
        "form": draft.get("form", changeset.CURRENT),
        "lifecycle": changeset.lifecycle(draft, ev),
        "review_stage": changeset.review_stage(draft, review),
        "stale": ev["stale"],
        "reasons": ev["reasons"],
        **plan_view,
        "governing": [governing(p) for p in sorted(now.governing,
                                                   key=lambda p: (now.governing[p].title.casefold(), p))],
        "candidates": [candidate(p) for p in draft["candidates"]],
        "available_candidates": available,
        "before": ev["before"],
        "after": ev["after"],
        "effects": ev["effects"],
        "summary": ev["summary"],
        "valid": plan is not None and not plan.blocked and not ev["reasons"],
        "reports": review["reports"],
        "plan_fingerprint": planned,
        "review_prompt": review_prompt,
        "copied": [{"mode": p.get("mode"), "copied": p.get("copied"), "exported": p.get("exported"),
                    "current": p.get("plan_fingerprint") == planned} for p in copied],
        "context": ({"project": identity["project"], "fingerprint": identity["fingerprint"]}
                    if identity else None),
        "private_note": changeset.PRIVATE_NOTE,
        "disclosure_warning": impact.DISCLOSURE_WARNING,
        "packet_disclosure": impact.PACKET_DISCLOSURE,
    }


_FROM_WORDS = {changeset.REVISE: "Revise", changeset.REPLACE: "Replace",
               changeset.WITHDRAW: "Withdraw", changeset.RETAIN: "Retain",
               changeset.ALONGSIDE: "Govern alongside"}


def conversion_view(now: changeset.Now, draft: Dict[str, Any]) -> Dict[str, Any]:
    """Every change converting an earlier-form draft would make, in words for
    the person, before they confirm it."""
    out = changeset.conversion(draft)

    def gov(path: str) -> str:
        return f"“{now.governing[path].title}”" if path in now.governing else f"`{path}`"

    def cand(path: str) -> str:
        return f"“{now.candidates[path].title}”" if path in now.candidates else f"`{path}`"

    lines = []
    for c in out["changes"]:
        was = _FROM_WORDS.get(c["from"], "")
        if c["change"] == "converted":
            text = (f"Revise {gov(c['document'])} with {cand(c['candidate'])} becomes Replace "
                    f"{gov(c['document'])} with {cand(c['candidate'])}.")
        elif c["change"] == "kept" and c["to"] == changeset.REPLACE:
            text = f"Replace {gov(c['document'])} with {cand(c['candidate'])} is kept as declared."
        elif c["change"] == "kept" and c["to"] == changeset.WITHDRAW:
            text = f"Withdraw {gov(c['document'])} is kept as declared."
        elif c["change"] == "kept":
            text = f"Govern alongside {cand(c['candidate'])} is kept as declared."
        elif c["from"] == "retain-others":
            n = len(c["documents"])
            text = (f"Retain all other governing documents ({n}) is removed: "
                    f"{'they are' if n != 1 else 'it is'} retained without a decision.")
        elif c["why"] == "retained":
            text = f"Retain {gov(c['document'])} is removed: it is retained without a decision."
        elif c["why"] == "candidate-used-twice":
            where = f" for {gov(c['document'])}" if c["document"] else ""
            text = (f"{was} {cand(c['candidate'])}{where} is removed: a candidate has one decision, "
                    "and this one is already used above"
                    + (f"; {gov(c['document'])} is retained." if c["document"] else "."))
        elif c["why"] == "candidate-not-chosen":
            text = (f"{was} {gov(c['document'])}, with no candidate chosen, is removed: it is "
                    "retained.")
        else:
            text = f"{gov(c['document'])}, not yet decided, is removed: it is retained."
        lines.append(dict(c, text=text))
    return {"changes": lines, "plan_fingerprint": out["plan_fingerprint"]}


def convert(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an earlier-form draft to the current form, once the person has
    seen every change and confirms. No governing context changes."""
    ctx = _ctx(session)
    if body.get("confirm") is not True:
        raise ApiError("Converting a change set needs your explicit confirmation, after you have "
                       "seen every change it makes.")

    def run() -> Dict[str, Any]:
        out = changeset.convert(ctx, _id(body), body.get("revision"))
        return dict(detail(ctx, out["draft"]), converted=True)
    return _guard(run)


def receipt_detail(draft: Dict[str, Any]) -> Dict[str, Any]:
    """An applied change set: what it did, as recorded when it applied."""
    applied = draft.get("applied") or {}
    receipt = applied.get("receipt") or {"outcomes": [], "before": [], "after": [], "summary": "",
                                         "reports": [], "prompts": []}
    return {
        "draft": _public(draft),
        "lifecycle": changeset.APPLIED,
        "receipt": dict(receipt, at=applied.get("at", "")),
        "private_note": changeset.PRIVATE_NOTE,
    }


def list_drafts(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _ctx(session)
    return _guard(lambda: {"drafts": changeset.list_drafts(ctx),
                           "private_note": changeset.PRIVATE_NOTE})


def create(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """A new draft: empty, or prefilled with the one candidate or withdrawal
    the person chose as `start`. Candidates join only through that explicit
    choice."""
    ctx = _ctx(session)
    unseeded = [k for k in ("candidates", "decisions", "withdrawals", "outcomes", "alongside",
                            "retain_others") if k in body]
    if unseeded:
        raise ApiError("A change set starts empty, or with the one candidate or withdrawal named "
                       "as `start`. Add more to it once it is open.")
    return _guard(lambda: detail(ctx, changeset.create(ctx, body.get("title", ""),
                                                       body.get("start"))))


def get(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _ctx(session)
    return _guard(lambda: detail(ctx, changeset.load(ctx, _id(body))))


def update(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _ctx(session)
    changes = {k: body[k] for k in ("title", "rationale", "candidates", "decisions", "withdrawals",
                                    "outcomes", "alongside", "retain_others", "scopes") if k in body}
    return _guard(lambda: detail(ctx, changeset.update(ctx, _id(body), body.get("revision"),
                                                       changes)))


def refresh(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _ctx(session)

    def run() -> Dict[str, Any]:
        out = changeset.refresh(ctx, _id(body))
        return dict(detail(ctx, out["draft"]), refreshed=out["changed"])
    return _guard(run)


def abandon(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _ctx(session)
    return _guard(lambda: detail(ctx, changeset.abandon(ctx, _id(body))))


def delete(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _ctx(session)
    if body.get("confirm") is not True:
        raise ApiError("Deleting a draft needs your explicit confirmation.")

    def run() -> Dict[str, Any]:
        changeset.delete(ctx, _id(body))
        return {"deleted": True}
    return _guard(run)


def save_packet(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Save the review packet where the person chooses: in the Save dialog, or
    at a path they typed when no dialog is available. Refused inside or around
    any Agent Context or Charter's private state; inside a Git
    repository, saved only once the person accepts the warning. The draft
    remembers only that a packet was saved, when, and for which plan."""
    ctx = _ctx(session)
    draft_id = _id(body)
    planned = body.get("plan_fingerprint")

    def run() -> Dict[str, Any]:
        material = changeset.packet_material(ctx, draft_id, planned)
        path = body.get("path")
        if not path:
            path = pick_save_file("Save review packet", material["file_name"])
            if not path:
                return {"saved": False, "cancelled": True}
        try:
            dest = review_packet.destination(ctx.folder, path, material["file_name"])
            if dest.warning and body.get("accept_warning") is not True:
                return {"saved": False, "needs_confirmation": True, "path": path,
                        "warning": dest.warning}
            name = review_packet.write(dest, material["text"])
        except review_packet.PacketDestinationError as exc:
            raise ApiError(str(exc), 400, {"path": path})
        out = detail(ctx, changeset.record_packet(ctx, draft_id, planned))
        out["saved"] = {"name": name, "folder": dest.folder,
                        "renamed": name != dest.name, "warning": dest.warning,
                        "size_bytes": material["size_bytes"],
                        # The request names the file as saved, renamed or not.
                        "request": impact.packet_request(name, planned)}
        return out
    return _guard(run)


def prompt_copied(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _ctx(session)
    return _guard(lambda: detail(ctx, changeset.record_copy(ctx, _id(body), body.get("mode"),
                                                            body.get("plan_fingerprint"))))


def attach_report(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _ctx(session)
    return _guard(lambda: detail(ctx, changeset.attach_report(ctx, _id(body), body.get("text"),
                                                              body.get("label", ""))))


def add_review(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _ctx(session)
    return _guard(lambda: detail(ctx, changeset.add_review(ctx, _id(body))))


def save_review(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Autosave one review: its reviewing agent and its text, as written."""
    ctx = _ctx(session)
    return _guard(lambda: detail(ctx, changeset.save_review(ctx, _id(body), body.get("report_id"),
                                                            body.get("label"), body.get("text"))))


def remove_report(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    ctx = _ctx(session)
    return _guard(lambda: detail(ctx, changeset.remove_report(ctx, _id(body),
                                                              body.get("report_id"))))


def apply(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a draft through the ordinary authority path, with the typed
    phrase, then keep its immutable receipt."""
    ctx = _ctx(session)
    draft_id = _id(body)

    def run() -> Dict[str, Any]:
        # The change set and its immutable receipt are one transaction (see
        # `authority._changeset`). No draft changes while it applies.
        with changeset.holding(ctx):
            return au.apply(ctx.folder, "changeset",
                            {"draft_id": draft_id, "draft_revision": body.get("revision")},
                            str(body.get("plan_id") or ""), body.get("confirm"))
    return _guard(run)


ROUTES: Dict[str, Callable[[Session, Dict[str, Any]], Dict[str, Any]]] = {
    "/api/changesets/list": list_drafts,
    "/api/changeset/create": create,
    "/api/changeset/get": get,
    "/api/changeset/update": update,
    "/api/changeset/refresh": refresh,
    "/api/changeset/abandon": abandon,
    "/api/changeset/convert": convert,
    "/api/changeset/delete": delete,
    "/api/changeset/prompt/copied": prompt_copied,
    "/api/changeset/packet/save": save_packet,
    "/api/changeset/report/attach": attach_report,
    "/api/changeset/report/remove": remove_report,
    "/api/changeset/review/add": add_review,
    "/api/changeset/review/save": save_review,
    "/api/changeset/apply": apply,
}
