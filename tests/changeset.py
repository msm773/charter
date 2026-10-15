"""Coordinated change sets on an Agent Context. Run: python -m tests.changeset

Coordinated Context Changes and Advisory Review; UI Standards:

  * drafts, attached reports and receipts are private local state only;
  * the person declares every outcome — retain, revise, replace, withdraw,
    govern alongside — and nothing is inferred; every other governing
    document stays only by an explicit decision;
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
    return chs.update(ctx, draft["id"], draft["revision"], {
        "outcomes": {"authoritative/a.md": {"outcome": "revise", "candidate": revision},
                     "authoritative/b.md": {"outcome": "withdraw"}},
        "alongside": [newcomer], "retain_others": True})


def case_private_and_explicit() -> None:
    print("\nprivate drafts, explicit outcomes")
    with isolated_private_state() as root:
        folder, ctx, revision, newcomer, spare = setup()
        before = snapshot(folder)
        draft = chs.create(ctx)
        check(draft["title"] == chs.UNTITLED and draft["outcomes"] == {} and draft["alongside"] == []
              and draft["retained"] == [], "a new change set is an empty, untitled plan")
        check(snapshot(folder) == before and os.path.isfile(ctx.cs.path(ps.CHANGESETS, draft["id"] + ".json"))
              and ctx.cs.base.startswith(root), "it lives in private state; the Agent Context is unchanged")
        detail = api.detail(ctx, draft)
        check(detail["lifecycle"] == chs.WAITING and not detail["valid"]
              and {r["code"] for r in detail["reasons"]} == {"others-undecided", "nothing-to-apply"},
              "nothing is decided for the person: every other document waits for an explicit decision")
        draft = chs.update(ctx, draft["id"], draft["revision"], {"outcomes": {"authoritative/a.md": {"outcome": ""}}})
        check(any(r["code"] == "undecided" for r in api.detail(ctx, draft)["reasons"]),
              "a row starts undecided")
        draft = chs.update(ctx, draft["id"], draft["revision"],
                           {"outcomes": {"authoritative/a.md": {"outcome": "revise"}}})
        check(any(r["code"] == "candidate-not-chosen" for r in api.detail(ctx, draft)["reasons"]),
              "a revision waits for the person to choose its candidate")
        check(raises(chs.ChangeSetError, chs.update, ctx, draft["id"], draft["revision"],
                     {"candidates": [revision]}),
              "a candidate cannot be added except by choosing it for a row")
        check(raises(chs.ChangeSetError, chs.update, ctx, draft["id"], draft["revision"],
                     {"outcomes": {"authoritative/a.md": {"outcome": "merge"}}}), "only the four outcomes exist")
        check(raises(chs.ChangeSetError, chs.update, ctx, draft["id"], draft["revision"] - 1, {"title": "x"}),
              "an edit against an older revision is refused")
        draft = chs.update(ctx, draft["id"], draft["revision"], {
            "outcomes": {"authoritative/a.md": {"outcome": "revise", "candidate": revision}},
            "alongside": [revision]})
        check(any(r["code"] == "candidate-used-twice" for r in api.detail(ctx, draft)["reasons"]),
              "a candidate used twice is refused")
        draft = chs.update(ctx, draft["id"], draft["revision"], {"alongside": []})
        fp = chs.plan_fingerprint(draft)
        draft = chs.update(ctx, draft["id"], draft["revision"], {"title": "Renamed", "rationale": "Why."})
        check(chs.plan_fingerprint(draft) == fp, "the plan fingerprint ignores the title and rationale")
        draft = chs.update(ctx, draft["id"], draft["revision"], {"retain_others": True})
        check(chs.plan_fingerprint(draft) != fp and draft["retained"] == ["authoritative/b.md", "authoritative/c.md"],
              "retaining the others is an explicit part of the plan")
        check([d["id"] for d in chs.list_drafts(ctx)] == [draft["id"]], "drafts are listed for this context")
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

        starts = [
            ({"alongside": newcomer}, "Govern alongside: “Delta”",
             {}, [newcomer]),
            ({"document": "authoritative/a.md", "outcome": "revise", "candidate": revision},
             "Revise “Alpha” with “Alpha two”",
             {"authoritative/a.md": {"outcome": "revise", "candidate": revision}}, []),
            ({"document": "authoritative/b.md", "outcome": "replace", "candidate": newcomer},
             "Replace “Beta” with “Delta”",
             {"authoritative/b.md": {"outcome": "replace", "candidate": newcomer}}, []),
            ({"document": "authoritative/c.md", "outcome": "withdraw"}, "Withdraw “Gamma”",
             {"authoritative/c.md": {"outcome": "withdraw"}}, []),
        ]
        for start, title, outcomes, along in starts:
            before = snapshot(folder)
            made = api.create(session, {"start": start})
            draft = chs.load(ctx, made["draft"]["id"])
            label = title.split(":")[0].split(" “")[0].lower()
            check(draft["title"] == title and draft["outcomes"] == outcomes
                  and draft["alongside"] == along and draft["retained"] == []
                  and set(draft["pins"]["candidates"]) == set(chs.members(draft)),
                  f"{label}: the valid candidate or document the person chose is accepted, and only it")
            check(made["lifecycle"] == chs.WAITING
                  and {r["code"] for r in made["reasons"]} == {"others-undecided"}
                  and snapshot(folder) == before,
                  f"{label}: every other governing document is left undecided; nothing is written")
            ready = chs.update(ctx, draft["id"], draft["revision"], {"retain_others": True})
            hand = chs.create(ctx, "By hand")
            hand = chs.update(ctx, hand["id"], hand["revision"],
                              {"outcomes": outcomes, "alongside": along, "retain_others": True})
            seeded_eval, hand_eval = chs.evaluate(ctx, ready), chs.evaluate(ctx, hand)
            check(api.detail(ctx, ready)["lifecycle"] == chs.VALID
                  and chs.plan_fingerprint(ready) == chs.plan_fingerprint(hand)
                  and seeded_eval["after"] == hand_eval["after"]
                  and seeded_eval["effects"] == hand_eval["effects"],
                  f"{label}: once the person retains the others, it is the same plan as one built by hand")
            chs.delete(ctx, hand["id"])

        made = api.create(session, {"start": {"alongside": origin}, "title": "My own name"})
        draft = chs.load(ctx, made["draft"]["id"])
        check(draft["title"] == "My own name" and draft["outcomes"] == {} and draft["alongside"] == [origin],
              "a Revise candidate started to govern alongside stays alongside: no target is inferred "
              "from its origin, and the person's own name is kept")
        draft = chs.update(ctx, draft["id"], draft["revision"],
                           {"outcomes": {"authoritative/b.md": {"outcome": "withdraw"}}, "retain_others": True})
        p = au.plan(folder, "changeset", {"draft_id": draft["id"], "draft_revision": draft["revision"]})
        check(api.detail(ctx, draft)["lifecycle"] == chs.VALID and not p.blocked,
              "a related outcome can be added before preview")
        au.apply(folder, "changeset", p.request, p.plan_id, PHRASE)
        governing = {d.path for d in ac.examine(folder).documents}
        check("authoritative/alpha-from-revise.md" in governing and "authoritative/b.md" not in governing
              and "authoritative/a.md" in governing,
              "and both outcomes apply as one change set")

        before = snapshot(folder)
        drafts = len(chs.list_drafts(ctx))
        refused = [
            ("not an object", "withdraw"),
            ("empty", {}),
            ("an unknown candidate", {"alongside": "authority-candidates/nope.md"}),
            ("a governing path as a candidate", {"alongside": "authoritative/a.md"}),
            ("a document that does not govern", {"document": "authoritative/zz.md", "outcome": "withdraw"}),
            ("a candidate as the document", {"document": spare, "outcome": "withdraw"}),
            ("revise without a candidate", {"document": "authoritative/a.md", "outcome": "revise"}),
            ("replace with an empty candidate", {"document": "authoritative/a.md", "outcome": "replace",
                                                 "candidate": ""}),
            ("revise with an unknown candidate", {"document": "authoritative/a.md", "outcome": "revise",
                                                  "candidate": "authority-candidates/nope.md"}),
            ("withdraw with a candidate", {"document": "authoritative/a.md", "outcome": "withdraw",
                                           "candidate": spare}),
            ("retain as a start", {"document": "authoritative/a.md", "outcome": "retain"}),
            ("an unknown outcome", {"document": "authoritative/a.md", "outcome": "merge"}),
            ("no outcome", {"document": "authoritative/a.md"}),
            ("both shapes at once", {"alongside": spare, "document": "authoritative/a.md",
                                     "outcome": "withdraw"}),
            ("an unknown field", {"document": "authoritative/a.md", "outcome": "withdraw", "why": "x"}),
            ("a list of candidates", {"alongside": [spare]}),
        ]
        for what, start in refused:
            check(raises(console.ApiError, api.create, session, {"start": start}),
                  f"a seed with {what} is refused")
        for key, value in (("candidates", [spare]), ("alongside", [spare]),
                           ("outcomes", {"authoritative/a.md": {"outcome": "withdraw"}}),
                           ("retain_others", True)):
            check(raises(console.ApiError, api.create, session, {key: value}),
                  f"`{key}` without a seed is refused: candidates join only through an explicit choice")
            check(raises(console.ApiError, api.create, session, {"start": {"alongside": spare}, key: value}),
                  f"`{key}` beside a seed is refused too")
        check(snapshot(folder) == before and len(chs.list_drafts(ctx)) == drafts,
              "a refused seed writes nothing: no draft, and no change to the Agent Context")

        write(folder, "authoritative/b.md", doc_text("b", "Beta", body="Edited outside.\n"))
        check(raises(console.ApiError, api.create, session, {"start": {"alongside": spare}})
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
              [("authoritative/a.md", "revised"), ("authoritative/c.md", "retained"),
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
              and [o["effect"] for o in receipt["receipt"]["outcomes"]] == ["revise", "withdraw", "retain",
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
        check([o["effect"] for o in receipt["outcomes"]] == ["revise", "withdraw", "retain", "govern-alongside"]
              and [d["path"] for d in receipt["before"]] == ["authoritative/a.md", "authoritative/b.md",
                                                            "authoritative/c.md"]
              and [(d["path"], d["effect"]) for d in receipt["after"]] ==
              [("authoritative/a.md", "revised"), ("authoritative/c.md", "retained"),
               ("authoritative/delta.md", "added")]
              and [(r["label"], r["status"]) for r in receipt["reports"]] == [("Agent one", "malformed")]
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
        variants = {
            "a title that is a number": dict(record, title=7),
            "a revision that is text": dict(record, revision="3"),
            "a revision that is true": dict(record, revision=True),
            "an unknown state": dict(record, state="published"),
            "an outcome that is not a dict": dict(record, outcomes={"authoritative/a.md": "revise"}),
            "an unknown outcome": dict(record, outcomes={"authoritative/a.md": {"outcome": "grant"}}),
            "a candidate that is a list": dict(record, outcomes={"authoritative/a.md":
                                                                {"outcome": "revise", "candidate": ["x"]}}),
            "alongside naming a number": dict(record, alongside=[3]),
            "retained that is text": dict(record, retained="all"),
            "a pin that is not a hash": dict(record, pins=dict(record["pins"], candidates={"x": 1})),
            "a report that is text": dict(record, reports=["report"]),
            "a report without an id": dict(record, reports=[{"text": "t"}]),
            "prompts that is a dict": dict(record, prompts={}),
            "applied, with no receipt": applied,
            "an id that is not its file's": dict(record, id="ffffffffffffffff"),
        }
        names = {}
        for n, (label, draft) in enumerate(variants.items()):
            draft_id = f"{n + 1:016x}"
            if label != "an id that is not its file's":
                draft = dict(draft, id=draft_id)
            with open(ctx.cs.path(ps.CHANGESETS, f"{draft_id}.json"), "w", encoding="utf-8") as fh:
                json.dump({"version": chs.RECORD_VERSION, "draft": draft}, fh)
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
        draft = chs.create(ctx, "", {"alongside": twin})
        draft = chs.update(ctx, draft["id"], draft["revision"], {"retain_others": True})
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
        draft = chs.update(ctx, draft["id"], draft["revision"], {"alongside": []})
        draft = chs.update(ctx, draft["id"], draft["revision"], {"alongside": [_newcomer]})
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
    print(f"\n{OK} All change-set checks passed.")


if __name__ == "__main__":
    run()
