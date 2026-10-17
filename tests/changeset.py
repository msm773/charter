"""Coordinated change sets on an Agent Context. Run: python -m tests.changeset

Coordinated Context Changes and Advisory Review; UI Standards:

  * drafts, attached reports and receipts are private local state only;
  * the plan is candidate-first: the person chooses Replace, with its target,
    or Govern alongside for each candidate, and may withdraw governing
    documents; every other governing document is retained without a
    decision; revise is never a decision, and nothing is inferred;
  * a draft recorded in the earlier form is shown as recorded, can be
    abandoned or deleted, and is refreshed, reviewed or applied only once the
    person explicitly converts it;
  * pins are hashes: a changed governing document, candidate, map, settings
    or plan makes the draft and its review evidence stale; refresh repins;
  * applying is one previewed, all-or-nothing write of the governing
    documents, map and metadata, confirmed by the typed phrase, operating no
    Git; it leaves an immutable private receipt.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import api_changeset as api  # noqa: E402
from app import authority as au  # noqa: E402
from app import changeset as chs  # noqa: E402
from app import console  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import transaction as tx  # noqa: E402
from tests.agent_context import context, doc_text, generate, snapshot, write  # noqa: E402
from tests.harness import isolated_private_state  # noqa: E402

OK = "ok"
PHRASE = au.CONFIRM_PHRASE


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def raises(exc, fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
    except exc:
        return True
    return False


def add(folder: str, title: str, scope: str = "") -> str:
    p = au.plan(folder, "add", {"title": title, "scope": scope, "body": f"{title} body.\n"})
    au.apply(folder, "add", p.request, p.plan_id, True)
    return [c for c in ps.PrivateState.default().for_context(folder).candidates()
            if title.lower().replace(" ", "-") in c][0]


def setup():
    """Three governing documents and three candidates."""
    folder = context(docs=(("a.md", "Alpha"), ("b.md", "Beta"), ("c.md", "Gamma")))
    revision = add(folder, "Alpha two", "Alpha, revised.")
    newcomer = add(folder, "Delta", "Delta things.")
    spare = add(folder, "Spare")
    ctx = chs.Ctx(folder)
    return folder, ctx, revision, newcomer, spare


def three_outcomes(ctx, draft, revision, newcomer):
    """Replace `a.md` with its revision, withdraw `b.md`, and govern a newcomer
    alongside; `c.md` is retained."""
    return chs.update(ctx, draft["id"], draft["revision"], {
        "candidates": [revision, newcomer],
        "decisions": {revision: {"decision": "replace", "target": "authoritative/a.md"},
                      newcomer: {"decision": "govern-alongside"}},
        "withdrawals": ["authoritative/b.md"]})


def case_private_and_explicit() -> None:
    print("\nprivate drafts, candidate-first decisions, every other document retained")
    with isolated_private_state() as root:
        folder, ctx, revision, newcomer, spare = setup()
        before = snapshot(folder)
        draft = chs.create(ctx)
        check(draft["title"] == chs.UNTITLED and draft["candidates"] == [] and draft["decisions"] == {}
              and draft["withdrawals"] == [] and draft["form"] == chs.CURRENT,
              "a new change set is an empty, untitled plan in the current form")
        with open(ctx.cs.path(ps.CHANGESETS, draft["id"] + ".json"), encoding="utf-8") as fh:
            stored = json.load(fh)
        check(stored["version"] == chs.RECORD_VERSION == 2 and "outcomes" not in stored["draft"]
              and "retained" not in stored["draft"],
              "it is recorded as version 2, with no per-document outcomes and no retained list")
        check(snapshot(folder) == before and os.path.isfile(ctx.cs.path(ps.CHANGESETS, draft["id"] + ".json"))
              and ctx.cs.base.startswith(root), "it lives in private state; the Agent Context is unchanged")
        detail = api.detail(ctx, draft)
        check(detail["lifecycle"] == chs.WAITING and not detail["valid"]
              and {r["code"] for r in detail["reasons"]} == {"nothing-to-apply"}
              and [r["path"] for r in detail["retained"]] == ["authoritative/a.md", "authoritative/b.md",
                                                              "authoritative/c.md"],
              "nothing is asked of the governing documents: every one is retained without a decision")
        draft = chs.update(ctx, draft["id"], draft["revision"], {"candidates": [revision]})
        check(draft["candidates"] == [revision] and chs.decision_of(draft, revision)["decision"] == ""
              and any(r["code"] == "decision-not-chosen" and r["document"] == revision
                      for r in api.detail(ctx, draft)["reasons"]),
              "a candidate joins the plan with its decision not yet made")
        draft = chs.update(ctx, draft["id"], draft["revision"],
                           {"decisions": {revision: {"decision": "replace"}}})
        check(any(r["code"] == "target-not-chosen" for r in api.detail(ctx, draft)["reasons"]),
              "Replace waits for the person to choose the governing document it replaces")
        for decision, why in (("revise", "Revise is not a change-set decision"),
                              ("retain", "Retain is not a decision"),
                              ("withdraw", "A withdrawal uses no candidate"),
                              ("merge", "replace or govern-alongside")):
            try:
                chs.update(ctx, draft["id"], draft["revision"],
                           {"decisions": {revision: {"decision": decision}}})
                refused = ""
            except chs.ChangeSetError as exc:
                refused = str(exc)
            check(why in refused, f"`{decision}` is refused as a decision, saying why")
        for old in ("outcomes", "alongside", "retain_others"):
            check(raises(chs.ChangeSetError, chs.update, ctx, draft["id"], draft["revision"], {old: {}}),
                  f"the earlier form's `{old}` is refused")
        check(raises(chs.ChangeSetError, chs.update, ctx, draft["id"], draft["revision"],
                     {"decisions": {spare: {"decision": "govern-alongside"}}}),
              "a decision for a candidate not in the plan is refused")
        check(raises(chs.ChangeSetError, chs.update, ctx, draft["id"], draft["revision"],
                     {"decisions": {revision: {"decision": "replace", "target": "authoritative/zz.md"}}}),
              "a replacement target must be a governing document")
        check(raises(chs.ChangeSetError, chs.update, ctx, draft["id"], draft["revision"],
                     {"withdrawals": [spare]}), "only a governing document can be withdrawn")
        check(raises(chs.ChangeSetError, chs.update, ctx, draft["id"], draft["revision"] - 1, {"title": "x"}),
              "an edit against an older revision is refused")
        draft = chs.update(ctx, draft["id"], draft["revision"], {
            "candidates": [revision, spare],
            "decisions": {revision: {"decision": "replace", "target": "authoritative/a.md"},
                          spare: {"decision": "replace", "target": "authoritative/a.md"}}})
        check(any(r["code"] == "target-replaced-twice" for r in api.detail(ctx, draft)["reasons"])
              and api.detail(ctx, draft)["lifecycle"] == chs.BLOCKED,
              "a governing document replaced twice blocks the plan")
        draft = chs.update(ctx, draft["id"], draft["revision"], {
            "candidates": [revision], "withdrawals": ["authoritative/a.md"]})
        check(draft["decisions"] == {revision: {"decision": "replace", "target": "authoritative/a.md"}}
              and any(r["code"] == "target-replaced-and-withdrawn" for r in api.detail(ctx, draft)["reasons"]),
              "a candidate removed from the plan takes its decision with it; replacing and withdrawing "
              "one document blocks the plan")
        draft = chs.update(ctx, draft["id"], draft["revision"], {"withdrawals": ["authoritative/b.md"]})
        detail = api.detail(ctx, draft)
        check(detail["lifecycle"] == chs.VALID and [r["path"] for r in detail["retained"]] == ["authoritative/c.md"]
              and [(e["effect"], e["document"]) for e in detail["effects"]] ==
              [("replace", "authoritative/a.md"), ("withdraw", "authoritative/b.md"),
               ("retain", "authoritative/c.md")],
              "with each candidate decided, the plan is valid and the document left alone is retained")
        fp = chs.plan_fingerprint(draft)
        draft = chs.update(ctx, draft["id"], draft["revision"], {"title": "Renamed", "rationale": "Why."})
        check(chs.plan_fingerprint(draft) == fp, "the plan fingerprint ignores the title and rationale")
        check([d["id"] for d in chs.list_drafts(ctx)] == [draft["id"]]
              and chs.list_drafts(ctx)[0]["form"] == chs.CURRENT, "drafts are listed for this context")
        shutil.rmtree(folder)


def case_prefilled_start() -> None:
    print("\na change set started from one candidate or document, prefilled with what the person chose")
    with isolated_private_state():
        folder, ctx, revision, newcomer, spare = setup()
        session = console.Session(folder)
        # A candidate Revise made from `a.md`: its origin is never chosen for the person.
        p = au.plan(folder, "revise", {"path": "authoritative/a.md", "title": "Alpha from Revise"})
        au.apply(folder, "revise", p.request, p.plan_id, True)
        origin = next(c for c in ctx.cs.candidates() if "alpha-from-revise" in c)

        before = snapshot(folder)
        made = api.create(session, {"start": {"candidate": origin}})
        draft = chs.load(ctx, made["draft"]["id"])
        check(draft["title"] == chs.UNTITLED and made["draft"]["untitled"] and draft["candidates"] == [origin]
              and chs.decision_of(draft, origin) == {"decision": "", "target": ""}
              and draft["withdrawals"] == [] and set(draft["pins"]["candidates"]) == {origin},
              "started from a Revise candidate: it is included with its decision not yet made, no "
              "target is inferred from its origin, and the draft is not named from it")
        check(made["lifecycle"] == chs.WAITING
              and {r["code"] for r in made["reasons"]} == {"decision-not-chosen"}
              and snapshot(folder) == before,
              "it waits only for that decision; nothing is written to the Agent Context")
        made = api.create(session, {"start": {"withdraw": "authoritative/c.md"}})
        draft = chs.load(ctx, made["draft"]["id"])
        check(draft["title"] == chs.UNTITLED and draft["withdrawals"] == ["authoritative/c.md"]
              and draft["candidates"] == [] and made["lifecycle"] == chs.VALID,
              "started from Withdraw in a change set: an unnamed withdrawal in an ordinary change set, ready to preview")

        starts = [
            ({"candidate": newcomer, "decision": "govern-alongside"}, "govern alongside",
             {newcomer: {"decision": "govern-alongside", "target": ""}}),
            ({"candidate": revision, "decision": "replace", "target": "authoritative/a.md"},
             "replace",
             {revision: {"decision": "replace", "target": "authoritative/a.md"}}),
        ]
        for start, label, decisions in starts:
            made = api.create(session, {"start": start})
            draft = chs.load(ctx, made["draft"]["id"])
            check(draft["title"] == chs.UNTITLED and draft["decisions"] == decisions
                  and made["lifecycle"] == chs.VALID,
                  f"{label}: the decision the person chose is kept, every other document retained, and the "
                  "draft left unnamed")
            hand = chs.create(ctx, "By hand")
            hand = chs.update(ctx, hand["id"], hand["revision"],
                              {"candidates": list(decisions), "decisions": decisions})
            check(chs.plan_fingerprint(draft) == chs.plan_fingerprint(hand)
                  and chs.evaluate(ctx, draft)["effects"] == chs.evaluate(ctx, hand)["effects"],
                  f"{label}: the same plan as one built by hand")
            chs.delete(ctx, hand["id"])

        made = api.create(session, {"start": {"candidate": origin}, "title": "My own name"})
        draft = chs.load(ctx, made["draft"]["id"])
        draft = chs.update(ctx, draft["id"], draft["revision"],
                           {"decisions": {origin: {"decision": "govern-alongside"}},
                            "withdrawals": ["authoritative/b.md"]})
        p = au.plan(folder, "changeset", {"draft_id": draft["id"], "draft_revision": draft["revision"]})
        check(draft["title"] == "My own name" and api.detail(ctx, draft)["lifecycle"] == chs.VALID
              and not p.blocked, "the person's own name is kept, and a related withdrawal can be added "
                                 "before preview")
        au.apply(folder, "changeset", p.request, p.plan_id, PHRASE)
        governing = {d.path for d in ac.examine(folder).documents}
        check("authoritative/alpha-from-revise.md" in governing and "authoritative/b.md" not in governing
              and "authoritative/a.md" in governing,
              "and both apply as one change set")

        before = snapshot(folder)
        drafts = len(chs.list_drafts(ctx))
        refused = [
            ("not an object", "withdraw"),
            ("empty", {}),
            ("an unknown candidate", {"candidate": "authority-candidates/nope.md"}),
            ("a governing path as a candidate", {"candidate": "authoritative/a.md"}),
            ("a document that does not govern", {"withdraw": "authoritative/zz.md"}),
            ("a candidate to withdraw", {"withdraw": spare}),
            ("revise as a decision", {"candidate": spare, "decision": "revise", "target": "authoritative/a.md"}),
            ("retain as a decision", {"candidate": spare, "decision": "retain"}),
            ("a replacement of a document that does not govern",
             {"candidate": spare, "decision": "replace", "target": "authoritative/zz.md"}),
            ("the earlier form's alongside", {"alongside": spare}),
            ("the earlier form's document outcome", {"document": "authoritative/a.md", "outcome": "withdraw"}),
            ("both shapes at once", {"candidate": spare, "withdraw": "authoritative/a.md"}),
            ("an unknown field", {"candidate": spare, "why": "x"}),
            ("a list of candidates", {"candidate": [spare]}),
        ]
        for what, start in refused:
            check(raises(console.ApiError, api.create, session, {"start": start}),
                  f"a seed with {what} is refused")
        for key, value in (("candidates", [spare]), ("decisions", {}), ("withdrawals", ["authoritative/a.md"]),
                           ("alongside", [spare]), ("outcomes", {"authoritative/a.md": {"outcome": "withdraw"}}),
                           ("retain_others", True)):
            check(raises(console.ApiError, api.create, session, {key: value}),
                  f"`{key}` without a seed is refused: candidates join only through an explicit choice")
            check(raises(console.ApiError, api.create, session, {"start": {"candidate": spare}, key: value}),
                  f"`{key}` beside a seed is refused too")
        check(snapshot(folder) == before and len(chs.list_drafts(ctx)) == drafts,
              "a refused seed writes nothing: no draft, and no change to the Agent Context")

        write(folder, "authoritative/b.md", doc_text("b", "Beta", body="Edited outside.\n"))
        check(raises(console.ApiError, api.create, session, {"start": {"candidate": spare}})
              and len(chs.list_drafts(ctx)) == drafts,
              "no seed is accepted while the Agent Context is not valid")
        shutil.rmtree(folder)


def case_three_outcomes() -> None:
    print("\nthree outcomes, previewed and applied as one")
    with isolated_private_state():
        folder, ctx, revision, newcomer, spare = setup()
        draft = three_outcomes(ctx, chs.create(ctx, "Restructure"), revision, newcomer)
        detail = api.detail(ctx, draft)
        check(detail["valid"] and detail["lifecycle"] == chs.VALID, "a complete plan is structurally valid")
        check([(a["path"], a["effect"]) for a in detail["after"]] ==
              [("authoritative/a.md", "replaced"), ("authoritative/c.md", "retained"),
               ("authoritative/delta.md", "added")], "the governing set after is shown, with each effect")
        effects = {e["document"]: e for e in detail["effects"]}
        check(effects["authoritative/a.md"]["archived_to"] == "archive/a-superseded.md"
              and effects["authoritative/b.md"]["withdrawn_to"] == "authority-candidates/b.md",
              "each effect says where things go")
        plan = au.plan(folder, "changeset", {"draft_id": draft["id"], "draft_revision": draft["revision"]})
        check(plan.governing_change and plan.confirm_phrase == PHRASE and not plan.blocked,
              "applying is confirmed by typing the phrase")
        context_writes = {c.path for c in plan.changes if c.root == "context"}
        check(context_writes == {"authoritative/a.md", "authoritative/b.md", "authoritative/delta.md",
                                 "AGENT-CONTEXT.md", ".agent-context.json"},
              "it writes only governing documents, the map and the metadata in the folder")
        check(raises(au.ActionRefused, au.apply, folder, "changeset", plan.request, plan.plan_id, True),
              "an ordinary confirmation is refused")

        session = console.Session(folder)
        calls = []
        real = subprocess.run

        def spy(args, *a, **k):
            calls.append(list(args) if isinstance(args, (list, tuple)) else [args])
            return real(args, *a, **k)
        subprocess.run = spy  # type: ignore[assignment]
        try:
            result = api.apply(session, {"id": draft["id"], "revision": draft["revision"],
                                         "plan_id": plan.plan_id, "confirm": PHRASE})
        finally:
            subprocess.run = real  # type: ignore[assignment]
        check(result["applied"] and not any(c[:1] == ["git"] for c in calls), "it applied, running no Git")
        exam = ac.examine(folder)
        check(exam.valid and [d.path for d in exam.documents] == ["authoritative/a.md", "authoritative/c.md",
                                                                  "authoritative/delta.md"]
              and next(d for d in exam.documents if d.path == "authoritative/a.md").meta["supersedes"] == ["a"],
              "the Agent Context is valid with the new governing set")
        cs = ctx.cs
        check("archive/a-superseded.md".split("/")[1] in cs.archived() and "authority-candidates/b.md" in cs.candidates()
              and revision not in cs.candidates() and newcomer not in cs.candidates(),
              "candidates were consumed, the replaced version archived and the withdrawn one returned privately")
        receipt = api.get(session, {"id": draft["id"]})
        check(receipt["lifecycle"] == chs.APPLIED and receipt["receipt"]["at"]
              and [o["effect"] for o in receipt["receipt"]["outcomes"]] == ["replace", "withdraw", "retain",
                                                                           "govern-alongside"],
              "an immutable receipt keeps the final outcomes")
        check(receipt["receipt"]["summary"].startswith("Change set: Restructure")
              and "The person decided every outcome." in receipt["receipt"]["summary"]
              and "commit" not in receipt["receipt"]["summary"].lower(), "and a copyable summary, with no commit")
        check("\nFinal outcomes:\n" in receipt["receipt"]["summary"]
              and "Declared outcomes" not in receipt["receipt"]["summary"],
              "its summary names the final outcomes, not declared ones")
        listed = next(d for d in chs.list_drafts(ctx) if d["id"] == draft["id"])
        check(listed["final_outcomes"] == 3 and listed["established"] == len(receipt["receipt"]["after"]) == 3,
              "the index counts what it did: three final outcomes, three established governing documents")
        check(all("final_outcomes" not in d for d in chs.list_drafts(ctx) if d["state"] != chs.APPLIED),
              "a draft not yet applied has no final outcomes to count")
        check(raises(chs.ChangeSetError, chs.update, ctx, draft["id"], None, {"title": "x"})
              and raises(chs.ChangeSetError, chs.attach_report, ctx, draft["id"], "{}"),
              "an applied change set never changes")
        shutil.rmtree(folder)


def case_stale() -> None:
    print("\nstale, then refreshed")
    with isolated_private_state():
        folder, ctx, revision, newcomer, spare = setup()
        draft = three_outcomes(ctx, chs.create(ctx, "Restructure"), revision, newcomer)
        plan = au.plan(folder, "changeset", {"draft_id": draft["id"], "draft_revision": draft["revision"]})
        p = au.plan(folder, "edit-candidate", {"candidate": newcomer, "scope": "Delta, narrower."})
        au.apply(folder, "edit-candidate", p.request, p.plan_id, True)
        detail = api.detail(ctx, draft)
        check(detail["stale"] and any(r["code"] == "candidate-changed" and r["refreshable"] for r in detail["reasons"]),
              "a changed candidate makes the draft stale")
        check(raises(au.ActionRefused, au.apply, folder, "changeset", plan.request, plan.plan_id, PHRASE),
              "and a stale draft cannot be applied")
        refreshed = api.refresh(console.Session(folder), {"id": draft["id"]})
        check(not refreshed["stale"] and refreshed["refreshed"][0]["change"].startswith("candidate text changed"),
              "refresh repins, saying what changed")

        write(folder, "authoritative/c.md", doc_text("c", "Gamma", body="Edited outside.\n"))
        generate(folder)
        detail = api.detail(ctx, chs.load(ctx, draft["id"]))
        check(any(r["code"] == "governing-changed" and r["document"] == "authoritative/c.md" for r in detail["reasons"]),
              "a governing document changed outside makes it stale, even one only retained")
        api.refresh(console.Session(folder), {"id": draft["id"]})
        s = console.Session(folder)
        p = console.plan(s, {"kind": "settings", "request": {"agent_guidance": {"review_newly_discovered_material": True}}})
        console.apply(s, {"kind": "settings", "request": {"agent_guidance": {"review_newly_discovered_material": True}},
                          "plan_id": p["plan_id"], "confirm": True})
        detail = api.detail(ctx, chs.load(ctx, draft["id"]))
        check([r["code"] for r in detail["reasons"]] == ["context-changed"],
              "a changed map or settings makes it stale too")
        api.refresh(s, {"id": draft["id"]})
        write(folder, "notes.txt", b"x")
        check(any(r["code"] == "context-invalid" for r in api.detail(ctx, chs.load(ctx, draft["id"]))["reasons"])
              and raises(console.ApiError, api.refresh, s, {"id": draft["id"]}),
              "an invalid Agent Context blocks it, and cannot be refreshed against")
        os.remove(os.path.join(folder, "notes.txt"))

        # A document that starts governing after the draft was prepared is
        # retained once the draft is refreshed, with no decision asked for.
        write(folder, "authoritative/e.md", doc_text("e", "Epsilon", body="Epsilon rules.\n"))
        generate(folder)
        detail = api.detail(ctx, chs.load(ctx, draft["id"]))
        check(any(r["code"] == "new-governing" and r["document"] == "authoritative/e.md"
                  and "retained" in r["message"] for r in detail["reasons"]),
              "a document that started governing makes the draft stale, saying it will be retained")
        refreshed = api.refresh(s, {"id": draft["id"]})
        check(any(c["document"] == "authoritative/e.md" and "retained" in c["change"]
                  for c in refreshed["refreshed"])
              and refreshed["lifecycle"] == chs.VALID
              and "authoritative/e.md" in [r["path"] for r in refreshed["retained"]]
              and ("retain", "authoritative/e.md") in [(e["effect"], e["document"]) for e in refreshed["effects"]],
              "refreshed, it is retained without a decision, and the plan is ready again")
        shutil.rmtree(folder)


def case_atomic() -> None:
    print("\nall or nothing")
    with isolated_private_state():
        folder, ctx, revision, newcomer, spare = setup()
        draft = three_outcomes(ctx, chs.create(ctx, "Restructure"), revision, newcomer)
        before, private = snapshot(folder), sorted(ctx.cs.candidates())
        plan = au.plan(folder, "changeset", {"draft_id": draft["id"], "draft_revision": draft["revision"]})

        def fault(step: str) -> None:
            if step == "replace:AGENT-CONTEXT.md":
                raise RuntimeError("disk full")
        check(raises(au.ApplyFailed, au.apply, folder, "changeset", plan.request, plan.plan_id, PHRASE, fault=fault)
              and snapshot(folder) == before and sorted(ctx.cs.candidates()) == private
              and not tx.interrupted(ctx.cs), "a failure part-way restores the folder and private state")
        check(chs.load(ctx, draft["id"])["state"] == chs.ACTIVE, "and the draft stays active")
        shutil.rmtree(folder)


class Crash(BaseException):
    """The process dying at a step: no in-process rollback runs."""


def _world(folder: str, ctx) -> tuple:
    """Everything a change set may touch: the folder, the private candidates
    and archive, and the change-set records."""
    private = {}
    for sub in (ps.CANDIDATES, ps.ARCHIVE, ps.CHANGESETS):
        for name in sorted(os.listdir(ctx.cs.path(sub))):
            if name.endswith((".md", ".json")):
                with open(ctx.cs.path(sub, name), "rb") as fh:
                    private[f"{sub}/{name}"] = fh.read()
    return snapshot(folder), private


def _prepared():
    folder, ctx, revision, newcomer, spare = setup()
    draft = three_outcomes(ctx, chs.create(ctx, "Restructure"), revision, newcomer)
    draft = chs.attach_report(ctx, draft["id"], "An agent's response, not a report.", "Agent one")
    request = {"draft_id": draft["id"], "draft_revision": draft["revision"]}
    return folder, ctx, draft, request


def case_receipt_is_part_of_the_transaction() -> None:
    print("\nthe receipt is written in the same transaction as the change set")
    with isolated_private_state():
        folder, ctx, draft, request = _prepared()
        plan = au.plan(folder, "changeset", request)
        record = [c for c in plan.changes if c.path == chs.record_path(draft["id"])]
        check(len(record) == 1 and record[0].root == "private"
              and json.loads(record[0].new)["draft"]["state"] == chs.APPLIED,
              "the applied draft, with its receipt, is one of the plan's own writes")
        check(au.plan(folder, "changeset", request).plan_id == plan.plan_id,
              "the receipt's time is set only when written, so the preview and the apply are one plan")
        steps = []
        recorded_id = draft["id"]
        au.apply(folder, "changeset", request, plan.plan_id, PHRASE, fault=steps.append)
        applied = chs.load(ctx, draft["id"])
        receipt = applied["applied"]["receipt"]
        check(applied["state"] == chs.APPLIED and chs.APPLIED_AT not in json.dumps(applied)
              and applied["applied"]["fingerprint"] == ac.examine(folder).fingerprint,
              "once applied, the draft is its receipt, stamped, naming the context it produced")
        check([o["effect"] for o in receipt["outcomes"]] == ["replace", "withdraw", "retain", "govern-alongside"]
              and [d["path"] for d in receipt["before"]] == ["authoritative/a.md", "authoritative/b.md",
                                                            "authoritative/c.md"]
              and [(d["path"], d["effect"]) for d in receipt["after"]] ==
              [("authoritative/a.md", "replaced"), ("authoritative/c.md", "retained"),
               ("authoritative/delta.md", "added")]
              # A response that is not a structurally valid report is never attached evidence.
              and receipt["reports"] == [] and "- No advisory report attached." in receipt["summary"]
              and receipt["summary"].startswith("Change set: Restructure"),
              "the receipt holds the final outcomes, before and after, the evidence and the summary")
        shutil.rmtree(folder)
    check(steps[:2] == ["before-journal", "after-journal"] and steps[-3:] == ["before-validate",
                                                                             "before-commit", "after-commit"]
          and "replace:" + chs.record_path(draft["id"]) in steps
          and any(s.startswith("replace:candidates/") for s in steps)
          and any(s.startswith("replace:archive/") for s in steps)
          and "replace:AGENT-CONTEXT.md" in steps,
          f"its {len(steps)} steps span context writes, private candidates and archive, the receipt, "
          "and completion")

    print("\nafter a crash at any step, exactly one safe result")
    for step in steps:
        with isolated_private_state():
            folder, ctx, draft, request = _prepared()
            before = _world(folder, ctx)
            plan = au.plan(folder, "changeset", request)

            here = step.replace(recorded_id, draft["id"])  # each run has its own draft

            def fault(name, here=here):
                if name == here:
                    raise Crash()
            try:
                au.apply(folder, "changeset", request, plan.plan_id, PHRASE, fault=fault)
            except Crash:
                pass
            au.recover(folder)  # what opening the Agent Context does first
            after = _world(folder, ctx)
            state = chs.load(ctx, draft["id"])["state"]
            exam = ac.examine(folder)
            rolled_back = after == before and state == chs.ACTIVE
            complete = (state == chs.APPLIED and exam.valid
                        and [d.path for d in exam.documents] == ["authoritative/a.md", "authoritative/c.md",
                                                                 "authoritative/delta.md"]
                        and chs.load(ctx, draft["id"])["applied"]["receipt"]["outcomes"]
                        and not tx.interrupted(ctx.cs))
            expected = "complete" if step == "after-commit" else "rolled back"
            check((rolled_back if expected == "rolled back" else complete)
                  and not (rolled_back and complete),
                  f"dying at {step}: {expected}" + (", the draft still active and unchanged"
                                                    if expected == "rolled back" else
                                                    ", context and receipt both in place"))
            shutil.rmtree(folder)

    print("\nand after an ordinary failure at any step, rolled back")
    for step in [s for s in steps if s not in ("before-journal", "after-commit")]:
        with isolated_private_state():
            folder, ctx, draft, request = _prepared()
            before = _world(folder, ctx)
            plan = au.plan(folder, "changeset", request)

            here = step.replace(recorded_id, draft["id"])

            def fail(name, here=here):
                if name == here:
                    raise RuntimeError("disk full")
            check(raises(au.ApplyFailed, au.apply, folder, "changeset", request, plan.plan_id, PHRASE,
                         fault=fail) and _world(folder, ctx) == before
                  and chs.load(ctx, draft["id"])["state"] == chs.ACTIVE,
                  f"failing at {step}: everything, receipt included, is as it was")
            shutil.rmtree(folder)

    with isolated_private_state():
        folder, ctx, draft, request = _prepared()
        plan = au.plan(folder, "changeset", request)
        chs.update(ctx, draft["id"], draft["revision"], {"rationale": "Changed after the preview."})
        unchanged = snapshot(folder)
        check(raises(au.ActionRefused, au.apply, folder, "changeset", request, plan.plan_id, PHRASE)
              and snapshot(folder) == unchanged
              and chs.load(ctx, draft["id"])["state"] == chs.ACTIVE,
              "a draft changed after its preview is refused, and nothing is written")
        shutil.rmtree(folder)


def case_reports_and_lifecycle() -> None:
    print("\nreports, abandoning and deleting")
    with isolated_private_state():
        folder, ctx, revision, newcomer, spare = setup()
        draft = three_outcomes(ctx, chs.create(ctx, "Restructure"), revision, newcomer)
        for n in range(chs.MAX_REPORTS):
            draft = chs.attach_report(ctx, draft["id"], "not a report", f"R{n}")
        check(raises(chs.ChangeSetError, chs.attach_report, ctx, draft["id"], "x"), "reports are bounded")
        draft = chs.remove_report(ctx, draft["id"], draft["reports"][0]["id"])
        check(len(draft["reports"]) == chs.MAX_REPORTS - 1, "a report can be removed")
        check(all(r["status"] == "malformed" for r in api.detail(ctx, draft)["reports"]),
              "each report is checked for form only")
        abandoned = chs.abandon(ctx, draft["id"])
        check(abandoned["state"] == chs.ABANDONED and raises(chs.ChangeSetError, chs.update, ctx,
                                                             draft["id"], None, {"title": "x"}),
              "an abandoned draft no longer changes")
        check(raises(console.ApiError, api.delete, console.Session(folder), {"id": draft["id"]}),
              "deleting needs explicit confirmation")
        api.delete(console.Session(folder), {"id": draft["id"], "confirm": True})
        check(chs.list_drafts(ctx) == [], "and removes the private draft")
        bad = ctx.cs.path(ps.CHANGESETS, "0123456789abcdef.json")
        with open(bad, "w") as fh:
            fh.write("{broken")
        check(chs.list_drafts(ctx)[0].get("unreadable"), "a draft that cannot be read is listed as such")
        shutil.rmtree(folder)


def case_corrupt_records_refused_not_crash() -> None:
    print("\na private record that parses but is mis-shaped is refused, never a crash")
    from app import transaction as tx
    with isolated_private_state():
        folder, ctx, _revision, _newcomer, _spare = setup()
        # A draft that is valid JSON with the right version but missing inner keys.
        with open(ctx.cs.path(ps.CHANGESETS, "0123456789abcdef.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": chs.RECORD_VERSION, "draft": {"id": "0123456789abcdef"}}, fh)
        entry = next(d for d in chs.list_drafts(ctx) if d["id"] == "0123456789abcdef")
        check(entry.get("unreadable"),
              "a mis-shaped draft is listed as unreadable, not raising a KeyError")
        check(raises(chs.ChangeSetError, chs.load, ctx, "0123456789abcdef"),
              "and reading it is a worded refusal, not a crash")
        # A journal with the right version but a mis-shaped entry.
        jdir = ctx.cs.staging_dir(tx.JOURNAL_KIND)
        os.makedirs(jdir, exist_ok=True)
        with open(os.path.join(jdir, tx.JOURNAL_FILE), "w", encoding="utf-8") as fh:
            json.dump({"version": tx.JOURNAL_VERSION, "entries": [{"root": "context"}]}, fh)
        check(raises(tx.TransactionError, tx.recover, ctx.cs),
              "a mis-shaped interrupted-write record is a worded TransactionError, not a KeyError")
        shutil.rmtree(folder)


def case_every_field_validated() -> None:
    """Each stored field a reader relies on is checked: one malformed record is
    shown in its own unreadable group, and every other draft still lists,
    opens and counts."""
    print("\nevery field of a stored draft is checked; a malformed record never breaks the others")
    with isolated_private_state():
        folder, ctx, _revision, _newcomer, _spare = setup()
        good = chs.create(ctx, "Good draft")
        session = console.Session(folder)
        record = json.loads(chs.record_text(good))["draft"]
        applied = dict(record, state=chs.APPLIED, applied={"at": "x", "fingerprint": "y"})
        earlier = {k: v for k, v in record.items() if k not in ("form", "decisions", "withdrawals")}
        earlier.update(outcomes={}, alongside=[], retained=[])
        variants = {
            "a title that is a number": (2, dict(record, title=7)),
            "a revision that is text": (2, dict(record, revision="3")),
            "a revision that is true": (2, dict(record, revision=True)),
            "an unknown state": (2, dict(record, state="published")),
            "candidates that is text": (2, dict(record, candidates="all")),
            "a decision that is not a dict": (2, dict(record, decisions={"x": "replace"})),
            "revise as a decision": (2, dict(record, decisions={"x": {"decision": "revise"}})),
            "a target that is a list": (2, dict(record, decisions={"x": {"decision": "replace",
                                                                          "target": ["y"]}})),
            "withdrawals naming a number": (2, dict(record, withdrawals=[3])),
            "no decisions at all": (2, {k: v for k, v in record.items() if k != "decisions"}),
            "a pin that is not a hash": (2, dict(record, pins=dict(record["pins"], candidates={"x": 1}))),
            "a report that is text": (2, dict(record, reports=["report"])),
            "a report without an id": (2, dict(record, reports=[{"text": "t"}])),
            "prompts that is a dict": (2, dict(record, prompts={})),
            "applied, with no receipt": (2, applied),
            "an id that is not its file's": (2, dict(record, id="ffffffffffffffff")),
            "an unknown record version": (3, record),
            "earlier form: an outcome that is not a dict": (1, dict(earlier, outcomes={"authoritative/a.md": "revise"})),
            "earlier form: an unknown outcome": (1, dict(earlier, outcomes={"authoritative/a.md": {"outcome": "grant"}})),
            "earlier form: a candidate that is a list": (1, dict(earlier, outcomes={"authoritative/a.md": {
                "outcome": "revise", "candidate": ["x"]}})),
            "earlier form: alongside naming a number": (1, dict(earlier, alongside=[3])),
            "earlier form: retained that is text": (1, dict(earlier, retained="all")),
            "earlier form: no outcomes at all": (1, record),
        }
        names = {}
        for n, (label, (version, draft)) in enumerate(variants.items()):
            draft_id = f"{n + 1:016x}"
            if label != "an id that is not its file's":
                draft = dict(draft, id=draft_id)
            with open(ctx.cs.path(ps.CHANGESETS, f"{draft_id}.json"), "w", encoding="utf-8") as fh:
                json.dump({"version": version, "draft": draft}, fh)
            names[draft_id] = label
        with open(ctx.cs.path(ps.CHANGESETS, "00000000000000ff.json"), "wb") as fh:
            fh.write(b'{"version": 1, "draft": ' + b"[" * 100_000 + b"]" * 100_000 + b"}")
        names["00000000000000ff"] = "nesting deep enough to exhaust the parser"
        listed = {d["id"]: d for d in chs.list_drafts(ctx)}
        for draft_id, label in names.items():
            check(listed.get(draft_id, {}).get("unreadable")
                  and raises(chs.ChangeSetError, chs.load, ctx, draft_id),
                  f"{label}: listed as unreadable, and opening it is a worded refusal")
        check(not listed[good["id"]].get("unreadable") and chs.load(ctx, good["id"])["title"] == "Good draft",
              "the well-formed draft still lists and opens beside them")
        shown = api.list_drafts(session, {})["drafts"]
        check(sum(1 for d in shown if d.get("unreadable")) == len(names)
              and api.get(session, {"id": good["id"]})["draft"]["id"] == good["id"],
              "the console lists them all, unreadable apart, and still opens the good draft")
        check(console._active_change_sets(folder) == 1,
              "and only the good draft counts as active")
        shutil.rmtree(folder)


def case_no_review_material_for_a_blocked_plan() -> None:
    """Advisory review material is prepared only for a structurally valid plan:
    a blocked one has no resulting context to review."""
    print("\nno review prompt or packet for a blocked plan")
    with isolated_private_state():
        folder, ctx, _revision, _newcomer, _spare = setup()
        before = set(ctx.cs.candidates())
        add(folder, "Alpha")  # would govern beside the governing "Alpha"
        twin = (set(ctx.cs.candidates()) - before).pop()
        draft = chs.create(ctx, "", {"candidate": twin, "decision": "govern-alongside"})
        session = console.Session(folder)
        shown = api.get(session, {"id": draft["id"]})
        check(shown["lifecycle"] == chs.BLOCKED
              and any("share one title" in r["message"] for r in shown["reasons"]),
              "two governing documents sharing a title block the plan")
        check(not shown["review_prompt"]["ready"] and "text" not in shown["review_prompt"]
              and "blocked" in shown["review_prompt"]["reason"],
              "and no review prompt is prepared for it, saying why")
        check(raises(chs.ChangeSetError, chs.packet_material, ctx, draft["id"], chs.plan_fingerprint(draft)),
              "nor any review packet")
        draft = chs.update(ctx, draft["id"], draft["revision"], {
            "candidates": [_newcomer], "decisions": {_newcomer: {"decision": "govern-alongside"}}})
        check(api.get(session, {"id": draft["id"]})["review_prompt"]["ready"],
              "once the plan is structurally valid, its review prompt is prepared")
        shutil.rmtree(folder)


def case_applied_receipt_is_immutable() -> None:
    print("\nan applied change-set receipt cannot be deleted")
    with isolated_private_state():
        folder, ctx, draft, request = _prepared()
        plan = au.plan(folder, "changeset", request)
        au.apply(folder, "changeset", request, plan.plan_id, PHRASE)
        check(chs.load(ctx, draft["id"])["state"] == chs.APPLIED,
              "the change set is applied and kept as a receipt")
        check(raises(console.ApiError, api.delete, console.Session(folder),
                     {"id": draft["id"], "confirm": True}),
              "deleting an applied receipt is refused through the console, even with confirmation")
        check(raises(chs.ChangeSetError, chs.delete, ctx, draft["id"]),
              "and refused at the store level too")
        check(chs.load(ctx, draft["id"])["state"] == chs.APPLIED,
              "the receipt is still there, unchanged")
        shutil.rmtree(folder)


def _earlier_record(ctx, draft_id: str, **fields) -> dict:
    """A draft as the earlier change-set form recorded it — version 1, an
    outcome for each governing document — written as that form wrote it."""
    now = chs.Now(ctx)
    draft = {"id": draft_id, "title": "Earlier plan", "created": "2026-01-01T00:00:00+00:00",
             "updated": "2026-01-01T00:00:00+00:00", "revision": 3, "state": chs.ACTIVE,
             "candidates": [], "outcomes": {}, "alongside": [], "retained": [], "rationale": "Kept.",
             "pins": chs._pins(now, []), "prompts": [], "reports": [], "applied": None}
    draft.update(fields)
    draft["pins"] = chs._pins(now, draft["candidates"])
    with open(ctx.cs.path(ps.CHANGESETS, draft_id + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "draft": draft}, fh, indent=1, sort_keys=True)
    return draft


def case_earlier_form() -> None:
    print("\na change set recorded in the earlier form: shown as recorded, converted only on request")
    with isolated_private_state():
        folder, ctx, revision, newcomer, spare = setup()
        session = console.Session(folder)
        a, b, c = "authoritative/a.md", "authoritative/b.md", "authoritative/c.md"
        old = _earlier_record(ctx, "00000000000000e1", candidates=[revision, spare, newcomer], outcomes={
            a: {"outcome": "revise", "candidate": revision},
            b: {"outcome": "replace", "candidate": spare},
            c: {"outcome": "retain"}}, alongside=[newcomer],
            prompts=[{"mode": "self-contained", "copied": "2026-01-02T00:00:00+00:00",
                      "plan_fingerprint": "f" * 64}],
            reports=[{"id": "r1", "label": "Earlier report", "attached": "2026-01-02T00:00:00+00:00",
                      "text": "not a report"}])
        path = ctx.cs.path(ps.CHANGESETS, old["id"] + ".json")
        with open(path, "rb") as fh:
            original_bytes = fh.read()
        listed = next(d for d in chs.list_drafts(ctx) if d["id"] == old["id"])
        check(not listed.get("unreadable") and listed["form"] == chs.EARLIER and listed["state"] == chs.ACTIVE,
              "an active version 1 draft is listed as an earlier-form active draft, never as unreadable")
        check(console._active_change_sets(folder) == 1, "and it counts as an active draft")
        shown = api.get(session, {"id": old["id"]})
        check(shown["form"] == chs.EARLIER and shown["lifecycle"] == chs.BLOCKED
              and [r["code"] for r in shown["reasons"]] == ["earlier-form"]
              and [(r["path"], r["outcome"]) for r in shown["earlier"]["rows"]] ==
              [(a, "revise"), (b, "replace"), (c, "retain")]
              and [x["path"] for x in shown["earlier"]["alongside"]] == [newcomer],
              "it is shown exactly as recorded, with one reason: convert it first")
        check(not shown["review_prompt"]["ready"] and "text" not in shown["review_prompt"]
              and "convert it" in shown["review_prompt"]["reason"],
              "no review material is prepared for it")
        before = snapshot(folder)
        blocked = [
            ("refreshed", lambda: chs.refresh(ctx, old["id"])),
            ("edited", lambda: chs.update(ctx, old["id"], None, {"title": "x"})),
            ("given a decision", lambda: chs.update(ctx, old["id"], None, {"candidates": [spare]})),
            ("recorded as a copied prompt", lambda: chs.record_copy(ctx, old["id"], "self-contained",
                                                                    chs.plan_fingerprint(chs.load(ctx, old["id"])))),
            ("recorded as a saved packet", lambda: chs.record_packet(ctx, old["id"], chs.plan_fingerprint(chs.load(ctx, old["id"])))),
            ("saved as a packet", lambda: chs.packet_material(ctx, old["id"], chs.plan_fingerprint(chs.load(ctx, old["id"])))),
            ("given a report", lambda: chs.attach_report(ctx, old["id"], "text")),
            ("relieved of its report", lambda: chs.remove_report(ctx, old["id"], "r1")),
            ("loaded to apply", lambda: chs.load_for_apply(ctx, old["id"], 3)),
        ]
        for what, fn in blocked:
            check(raises(chs.ChangeSetError, fn), f"it cannot be {what}")
        check(raises(au.ActionRefused, au.plan, folder, "changeset", {"draft_id": old["id"], "draft_revision": 3}),
              "nor previewed or applied")
        with open(path, "rb") as fh:
            check(fh.read() == original_bytes and snapshot(folder) == before,
                  "none of that touched the record or the Agent Context")

        conversion = shown["conversion"]
        check([(x["change"], x["from"], x["to"], x["document"], x["candidate"]) for x in conversion["changes"]] ==
              [("converted", "revise", "replace", a, revision),
               ("kept", "replace", "replace", b, spare),
               ("removed", "retain", "", c, ""),
               ("kept", "govern-alongside", "govern-alongside", "", newcomer)],
              "the conversion lists every change: revise becomes replace, replace stays replace of the "
              "same document by the same candidate, govern alongside is kept, retain is removed")
        check(all(x["text"] for x in conversion["changes"])
              and "becomes Replace “Alpha” with “Alpha two”" in conversion["changes"][0]["text"]
              and "kept as declared" in conversion["changes"][1]["text"]
              and "retained without a decision" in conversion["changes"][2]["text"],
              "each change is worded for the person, by title")
        check(raises(console.ApiError, api.convert, session, {"id": old["id"], "revision": 3}),
              "converting needs explicit confirmation")
        check(raises(console.ApiError, api.convert, session, {"id": old["id"], "revision": 2, "confirm": True}),
              "and is refused against an older revision of the draft")
        with open(path, "rb") as fh:
            check(fh.read() == original_bytes, "nothing converts automatically")

        earlier_fp = chs.plan_fingerprint(chs.load(ctx, old["id"]))
        converted = api.convert(session, {"id": old["id"], "revision": 3, "confirm": True})
        new = chs.load(ctx, old["id"])
        with open(path, encoding="utf-8") as fh:
            stored = json.load(fh)
        check(stored["version"] == chs.RECORD_VERSION and new["form"] == chs.CURRENT
              and new["candidates"] == [revision, spare, newcomer]
              and new["decisions"] == {revision: {"decision": "replace", "target": a},
                                       spare: {"decision": "replace", "target": b},
                                       newcomer: {"decision": "govern-alongside", "target": ""}}
              and new["withdrawals"] == [] and "outcomes" not in new and "retained" not in new,
              "once confirmed, it is a current-form draft: the replace row kept, the revise row a replace, "
              "the alongside kept")
        check(new["title"] == "Earlier plan" and new["rationale"] == "Kept." and new["revision"] == 4
              and converted["converted"] and snapshot(folder) == before,
              "its name and rationale are kept, and no governing context changed")
        check(new["prompts"] == old["prompts"] and [r["id"] for r in new["reports"]] == ["r1"]
              and chs.plan_fingerprint(new) != earlier_fp
              and converted["copied"] == [{"mode": "self-contained", "copied": "2026-01-02T00:00:00+00:00",
                                           "exported": None, "current": False}],
              "its prompt records and reports are kept as historical evidence, and are stale: the plan changed")
        check(raises(console.ApiError, api.convert, session, {"id": old["id"], "revision": 4, "confirm": True}),
              "a current-form draft is not converted again")
        detail = api.get(session, {"id": old["id"]})
        check(detail["lifecycle"] == chs.VALID and [r["path"] for r in detail["retained"]] == [c],
              "converted, the plan is ready to review and preview, with the retained document shown")
        plan = au.plan(folder, "changeset", {"draft_id": old["id"], "draft_revision": new["revision"]})
        au.apply(folder, "changeset", plan.request, plan.plan_id, PHRASE)
        exam = ac.examine(folder)
        check(exam.valid and [d.path for d in exam.documents] == [a, b, c, "authoritative/delta.md"]
              and {d.path: d.title for d in exam.documents}[a] == "Alpha two"
              and {d.path: d.title for d in exam.documents}[b] == "Spare",
              "and it applies like any other change set")

        e2 = _earlier_record(ctx, "00000000000000e2", candidates=[], outcomes={
            "authoritative/a.md": {"outcome": "withdraw"},
            "authoritative/b.md": {"outcome": ""},
            "authoritative/c.md": {"outcome": "replace", "candidate": ""}})
        e3 = _earlier_record(ctx, "00000000000000e3", candidates=[newcomer], outcomes={
            "authoritative/a.md": {"outcome": "replace", "candidate": newcomer}},
            alongside=[newcomer], retained=["authoritative/b.md", "authoritative/c.md"])
        out2, out3 = chs.conversion(chs.load(ctx, e2["id"])), chs.conversion(chs.load(ctx, e3["id"]))
        check([(x["change"], x.get("why", "")) for x in out2["changes"]] ==
              [("kept", ""), ("removed", "undecided"), ("removed", "candidate-not-chosen")]
              and out2["draft"]["withdrawals"] == ["authoritative/a.md"] and out2["draft"]["candidates"] == [],
              "withdraw is kept; a row never decided, and a replace with no candidate, are removed and listed")
        check([(x["change"], x.get("why", "")) for x in out3["changes"]] ==
              [("kept", ""), ("removed", "candidate-used-twice"), ("removed", "retained")]
              and out3["changes"][2]["documents"] == ["authoritative/b.md", "authoritative/c.md"]
              and out3["draft"]["candidates"] == [newcomer],
              "a candidate used twice keeps its first decision; Retain all other governing documents is "
              "removed and listed")

        chs.abandon(ctx, e2["id"])
        with open(ctx.cs.path(ps.CHANGESETS, e2["id"] + ".json"), encoding="utf-8") as fh:
            stored = json.load(fh)
        check(stored["version"] == 1 and "form" not in stored["draft"] and stored["draft"]["state"] == chs.ABANDONED
              and stored["draft"]["outcomes"] == e2["outcomes"],
              "abandoning one keeps it in the earlier form, exactly as recorded")
        abandoned = api.get(session, {"id": e2["id"]})
        check(abandoned["lifecycle"] == chs.ABANDONED and abandoned["reasons"] == []
              and abandoned["conversion"] is None
              and [r["outcome"] for r in abandoned["earlier"]["rows"]] == ["withdraw", "", "replace"],
              "an abandoned earlier-form draft is shown as recorded, with nothing to convert")
        api.delete(session, {"id": e3["id"], "confirm": True})
        check(all(d["id"] != e3["id"] for d in chs.list_drafts(ctx)), "and an earlier-form draft can be deleted")

        receipt = {"outcomes": [{"effect": "revise", "document": a, "title": "Alpha",
                                 "candidate": revision, "candidate_title": "Alpha two",
                                 "archived_to": "archive/a-superseded.md"},
                                {"effect": "retain", "document": c, "title": "Gamma"}],
                   "before": [], "after": [], "summary": "Change set: Old\n\nDeclared outcomes:\n- Revise\n",
                   "reports": [], "prompts": []}
        _earlier_record(ctx, "00000000000000e4", state=chs.APPLIED,
                        applied={"at": "2026-01-03T00:00:00+00:00", "fingerprint": "0" * 64, "receipt": receipt})
        shown = api.get(session, {"id": "00000000000000e4"})
        check(shown["lifecycle"] == chs.APPLIED and shown["receipt"]["outcomes"] == receipt["outcomes"]
              and shown["receipt"]["summary"] == receipt["summary"],
              "an earlier-form receipt is shown exactly as recorded, Revised included")
        shutil.rmtree(folder)


def run() -> None:
    case_private_and_explicit()
    case_prefilled_start()
    case_three_outcomes()
    case_stale()
    case_atomic()
    case_receipt_is_part_of_the_transaction()
    case_corrupt_records_refused_not_crash()
    case_every_field_validated()
    case_no_review_material_for_a_blocked_plan()
    case_applied_receipt_is_immutable()
    case_reports_and_lifecycle()
    case_earlier_form()
    print(f"\n{OK} All change-set checks passed.")


if __name__ == "__main__":
    run()
