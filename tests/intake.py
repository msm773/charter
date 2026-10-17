"""Reviewing Agent Proposals. Run: python -m tests.intake

Product Specification §3.2–§3.3, the Proposal Review Standard, UI Standards:

  * pending, imported and unexpected records are kept apart; a file among the
    records that intake did not file, or that changed since, is never a
    proposal, and is left unchanged;
  * an imported proposal is checked exactly as `charter propose` checks it;
  * accepting creates, amends or retires a candidate only, after a previewed
    ordinary confirmation, and never changes governing context; rejecting
    records why; a stale proposal cannot be accepted as written;
  * every write is private, through one transaction.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import agent_proposals as apx  # noqa: E402
from app import authority as au  # noqa: E402
from app import console  # noqa: E402
from app import private_store as ps  # noqa: E402
from app.docs import parse_front_matter  # noqa: E402
from tests.agent_context import context, doc_text, read, snapshot, write  # noqa: E402
from tests.harness import isolated_private_state  # noqa: E402

OK = "ok"


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


def sha(folder: str, rel: str) -> str:
    return ac.sha256_text(read(folder, rel).decode("utf-8"))


def file(folder: str, proposal: dict) -> str:
    result = apx.file(folder, proposal)
    assert result["result"] == "pending", result
    return result["proposal_id"]


def decide(folder: str, kind: str, request: dict):
    plan = au.plan(folder, kind, request)
    return plan, au.apply(folder, kind, request, plan.plan_id, True)


def meta(text: str) -> dict:
    return parse_front_matter(text)[0]


def setup() -> tuple:
    folder = context()
    a = au.plan(folder, "add", {"title": "Draft", "scope": "Drafts.", "body": "Draft body.\n"})
    au.apply(folder, "add", a.request, a.plan_id, True)
    return folder, ps.PrivateState.default().for_context(folder), "authority-candidates/draft.md"


def case_listing() -> None:
    print("\npending, imported and unexpected, apart")
    with isolated_private_state():
        folder, cs, _cand = setup()
        pid = file(folder, {"agent": "codex", "operation": "create", "target_path": "authority-candidates/n.md",
                            "reason": "New.", "proposed_body": "# N\n\nText.\n",
                            "expected_context_impact": "No overlap."})
        imported = apx.file(folder, {"agent": "claude", "operation": "create",
                                     "target_path": "authority-candidates/m.md", "reason": "Returned.",
                                     "proposed_body": "x\n"}, source=apx.IMPORTED)["proposal_id"]
        pending = cs.path(ps.PROPOSALS, apx.PENDING)
        with open(os.path.join(pending, "dropped-in.json"), "w", encoding="utf-8") as fh:
            json.dump({"agent": "x", "operation": "create"}, fh)
        with open(os.path.join(pending, "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("hello")
        listed = apx.listing(folder)
        check([p["proposal_id"] for p in listed["pending"]] == [pid]
              and listed["pending"][0]["expected_context_impact"] == "No overlap."
              and not listed["pending"][0]["stale"], "a proposal from an agent is pending, with its claims")
        check([p["proposal_id"] for p in listed["imported"]] == [imported], "an imported one is listed apart")
        check(sorted(u["name"] for u in listed["unexpected"]) == ["dropped-in.json", "notes.txt"]
              and all("did not file" in u["why"] or "cannot be read" in u["why"] for u in listed["unexpected"]),
              "files intake did not file are unexpected, never proposals")
        with open(os.path.join(pending, pid + ".json"), "a", encoding="utf-8") as fh:
            fh.write(" ")
        listed = apx.listing(folder)
        check(pid not in [p["proposal_id"] for p in listed["pending"]]
              and any(u["name"] == pid + ".json" and "changed after" in u["why"] for u in listed["unexpected"]),
              "a record changed after it was filed becomes unexpected")
        check(raises(au.ActionRefused, au.plan, folder, "accept-proposal", {"proposal_id": pid})
              and raises(au.ActionRefused, au.plan, folder, "accept-proposal", {"proposal_id": "dropped-in"}),
              "and neither can be accepted")
        before = {n: open(os.path.join(pending, n), "rb").read() for n in os.listdir(pending)}
        apx.listing(folder)
        session = console.Session(folder)
        console.unexpected(session, {"name": "notes.txt"})
        check({n: open(os.path.join(pending, n), "rb").read() for n in os.listdir(pending)} == before,
              "looking at them changes nothing")
        check(raises(console.ApiError, console.unexpected, session, {"name": "../intake.json"}),
              "only an unexpected record can be viewed, by its name")
        shutil.rmtree(folder)


def case_titles() -> None:
    print("\neach listed proposal names the document it concerns, for the person")
    with isolated_private_state():
        folder, cs, cand = setup()
        gov = ac.examine(folder).documents[0]
        ids = {
            "amend of a governing document": file(folder, {
                "agent": "codex", "operation": "amend", "target_path": gov.path, "reason": "Clarify.",
                "base_sha256": sha(folder, gov.path), "proposed_body": "Clearer.\n",
                "proposed_meta": {"title": "A new title", "scope": "Scope."}}),
            "amend of a candidate": file(folder, {
                "agent": "codex", "operation": "amend", "target_path": cand, "reason": "Refine.",
                "base_sha256": ac.sha256_text(cs.read_candidate(cand)), "proposed_body": "Refined.\n"}),
            "retire of a candidate": file(folder, {
                "agent": "codex", "operation": "retire", "target_path": cand, "reason": "Unneeded.",
                "base_sha256": ac.sha256_text(cs.read_candidate(cand))}),
            "create with a proposed title": file(folder, {
                "agent": "codex", "operation": "create", "target_path": "authority-candidates/n.md",
                "reason": "New.", "proposed_body": "Text.\n", "proposed_meta": {"title": "  New   rule ", "scope": ""}}),
            "create with no title": file(folder, {
                "agent": "codex", "operation": "create", "target_path": "authority-candidates/m.md",
                "reason": "New.", "proposed_body": "Text.\n"}),
            "create titled by its first heading": file(folder, {
                "agent": "codex", "operation": "create", "target_path": "authority-candidates/h.md",
                "reason": "New.", "proposed_body": "Lead line.\n\n#   Heading   rule\n\n## Not this one\n"}),
            "imported create titled by its first heading": apx.file(folder, {
                "agent": "chat-agent", "operation": "create", "target_path": "authority-candidates/i.md",
                "reason": "New.", "proposed_body": "# Imported heading\n\nText.\n"}, source=apx.IMPORTED)["proposal_id"],
        }
        listing = apx.listing(folder)
        listed = {p["proposal_id"]: p for p in listing["pending"] + listing["imported"]}
        expected = {"amend of a governing document": (gov.title, "current"),
                    "amend of a candidate": ("Draft", "current"),
                    "retire of a candidate": ("Draft", "current"),
                    "create with a proposed title": ("New rule", "proposed"),
                    "create with no title": ("authority-candidates/m.md", "path"),
                    "create titled by its first heading": ("Heading rule", "proposed"),
                    "imported create titled by its first heading": ("Imported heading", "proposed")}
        for label, pid in ids.items():
            got = (listed[pid]["title"], listed[pid]["title_kind"])
            check(got == expected[label], f"{label}: {got[1]} title {got[0]!r}")
        check(listed[ids["amend of a governing document"]]["target_path"] == gov.path,
              "the logical target path is still given beside the title")
        summaries = {label: au.plan(folder, "accept-proposal", {"proposal_id": pid}).summary
                     for label, pid in ids.items()}
        check(summaries["create titled by its first heading"]
              == "Accept as candidate: “Heading rule” becomes a private authority candidate."
              and summaries["imported create titled by its first heading"]
              == "Accept as candidate: “Imported heading” becomes a private authority candidate.",
              "accepting a create titled by its heading files the candidate under the title its card showed")
        check(summaries["create with a proposed title"]
              == "Accept as candidate: “New rule” becomes a private authority candidate."
              and f"a revision of “{gov.title}”" in summaries["amend of a governing document"]
              and "keeps governing unchanged" in summaries["amend of a governing document"]
              and "“Draft” is updated" in summaries["amend of a candidate"]
              and all("file “" not in s.lower() and "authority-candidates/" not in s
                      and "does not govern" not in s for s in summaries.values()),
              "each acceptance summary names the candidate by friendly title, never “file <name>”, "
              "with no appended “does not govern” sentence")
        reject = au.plan(folder, "reject-proposal", {"proposal_id": ids["amend of a candidate"], "reason": "No."})
        check(reject.summary == "Reject the proposal for “Draft”. Nothing else changes.",
              "the rejection preview names the proposal by its title")
        write(folder, gov.path, doc_text("x", "Edited outside", body="Changed.\n"))
        listed = {p["proposal_id"]: p for p in apx.listing(folder)["pending"]}
        check((listed[ids["amend of a governing document"]]["title"],
               listed[ids["amend of a governing document"]]["title_kind"]) == (gov.path, "path")
              and listed[ids["amend of a candidate"]]["title"] == "Draft",
              "while the Agent Context is not valid, a governing target falls back to its path; a candidate "
              "still has its title")
        shutil.rmtree(folder)


def case_import() -> None:
    print("\nimporting a returned proposal")
    with isolated_private_state():
        folder, cs, _cand = setup()
        session = console.Session(folder)
        good = {"agent": "chat-agent", "operation": "amend", "target_path": "authoritative/a.md",
                "reason": "Clarify.", "base_sha256": sha(folder, "authoritative/a.md"),
                "proposed_body": "Clearer.\n"}
        bad = dict(good, base_commit="abc")
        checked = console.import_check(session, {"json": json.dumps(bad)})
        check(not checked["ok"] and ("unknown_field", "base_commit") in
              {(p["code"], p.get("field")) for p in checked["problems"]},
              "it is checked exactly as `charter propose` checks it")
        checked = console.import_check(session, {"json": json.dumps(good)})
        check(checked["ok"] and checked["summary"]["target_path"] == "authoritative/a.md"
              and apx.listing(folder)["imported"] == [], "checking files nothing")
        check(raises(console.ApiError, console.import_file, session, {"json": json.dumps(good)}),
              "filing needs the person's confirmation")
        filed = console.import_file(session, {"json": json.dumps(good), "confirm": True})
        check(filed["result"] == "pending" and
              [p["proposal_id"] for p in apx.listing(folder)["imported"]] == [filed["proposal_id"]],
              "confirmed, it is filed as imported")
        check(raises(console.ApiError, console.import_check, session, {"json": "{not json"}),
              "text that is not JSON is refused")

        imported = len(apx.listing(folder)["imported"])
        for what, body in (("front matter", "---\ntitle: Clearer\nauthority: authoritative\n---\n\nClearer.\n"),
                           ("front matter after a byte-order mark and blank lines",
                            "﻿\n\n---\nid: x\n---\nClearer.\n")):
            fronted = dict(good, proposed_body=body)
            checked = console.import_check(session, {"json": json.dumps(fronted)})
            check(not checked["ok"] and [p["code"] for p in checked["problems"]] == ["front_matter_in_body"]
                  and "Remove it and submit again" in checked["problems"][0]["message"],
                  f"an imported body beginning with {what} is refused, with the correction")
            filed = console.import_file(session, {"json": json.dumps(fronted), "confirm": True})
            check(filed["result"] == "refused" and len(apx.listing(folder)["imported"]) == imported,
                  f"and confirming it files nothing ({what})")
        created = {"agent": "chat-agent", "operation": "create", "target_path": "authority-candidates/new-rule.md",
                   "reason": "A rule.", "proposed_body": "---\nlayout: post\n---\n\nRule.\n"}
        check(not console.import_check(session, {"json": json.dumps(created)})["ok"],
              "so is an imported create whose body begins with another tool's front matter")
        ruled = dict(created, proposed_body="---\nA thematic break, then prose.\n---\n\nRule.\n")
        check(console.import_check(session, {"json": json.dumps(ruled)})["ok"],
              "a body that only opens with a thematic break is accepted for import")
        shutil.rmtree(folder)


def case_older_front_matter() -> None:
    print("\na pending proposal filed before intake refused front matter is refused when accepted")
    with isolated_private_state():
        folder, cs, _cand = setup()
        real = apx.leading_front_matter
        apx.leading_front_matter = lambda text: None  # as intake was before
        try:
            pid = file(folder, {"agent": "codex", "operation": "create", "target_path": "authority-candidates/old.md",
                                "reason": "r", "proposed_body": "---\nid: old\nstatus: active\n---\n\nOld.\n"})
        finally:
            apx.leading_front_matter = real
        candidates = cs.candidates()
        check(raises(au.ActionRefused, au.plan, folder, "accept-proposal", {"proposal_id": pid})
              and cs.candidates() == candidates
              and pid in {p["proposal_id"] for p in apx.listing(folder)["pending"]},
              "it cannot be accepted as written, nothing is filed, and it stays pending to reject")
        _plan, _ = decide(folder, "reject-proposal", {"proposal_id": pid, "reason": "Front matter in the body."})
        check(pid not in {p["proposal_id"] for p in apx.listing(folder)["pending"]}, "it can still be rejected")
        shutil.rmtree(folder)


def case_accept() -> None:
    print("\naccepting changes a candidate only")
    with isolated_private_state():
        folder, cs, cand = setup()
        governing_before = {rel: read(folder, rel) for rel in ac.examine(folder).texts}
        before = snapshot(folder)

        create = file(folder, {"agent": "codex", "operation": "create", "target_path": "authority-candidates/new-rule.md",
                               "reason": "Needed.", "proposed_body": "# New rule\n\nText.\n",
                               "proposed_meta": {"scope": "Rules."}})
        plan = au.plan(folder, "accept-proposal", {"proposal_id": create})
        check(not plan.governing_change and plan.confirm_phrase == "" and not plan.blocked,
              "accepting is not a governing change, and needs no typed phrase")
        check(any("never changes governing context" in n for n in plan.notes)
              and {c.root for c in plan.changes} == {"private"},
              "its preview says so, and every write is private")
        check(raises(au.ActionRefused, au.apply, folder, "accept-proposal", plan.request, plan.plan_id, None),
              "it needs a deliberate confirmation")
        au.apply(folder, "accept-proposal", plan.request, plan.plan_id, True)
        text = cs.read_candidate("authority-candidates/new-rule.md")
        m = meta(text)
        check(m["title"] == "New rule" and m["scope"] == "Rules." and m["authority"] == "non-authoritative"
              and f"Agent Proposal {create}" in m["source"] and text.endswith("# New rule\n\nText.\n"),
              "a create files a new candidate, titled from its body, with where it came from")

        amend = file(folder, {"agent": "claude", "operation": "amend", "target_path": "authoritative/a.md",
                              "reason": "Clarify.", "base_sha256": sha(folder, "authoritative/a.md"),
                              "replacements": [{"find": "Body.", "replace": "Clearer body."}],
                              "proposed_meta": {"title": "Alpha, clarified"}})
        decide(folder, "accept-proposal", {"proposal_id": amend})
        revision = [c for c in cs.candidates() if "alpha" in c][0]
        rm = meta(cs.read_candidate(revision))
        check(rm["title"] == "Alpha, clarified" and rm["scope"] == "A scope." and rm["id"] != "a"
              and cs.read_candidate(revision).endswith("Clearer body.\n"),
              "an amend of a governing document files a revision candidate")
        check(rm.get(au.REVISES) == "a",
              "and records the governing document it revises, by its stable id (same lineage as Revise)")

        cand_sha = ac.sha256_text(cs.read_candidate(cand))
        upd = file(folder, {"agent": "claude", "operation": "amend", "target_path": cand, "reason": "Better.",
                            "base_sha256": cand_sha, "proposed_body": "Better draft.\n",
                            "proposed_meta": {"scope": "Better drafts."}})
        decide(folder, "accept-proposal", {"proposal_id": upd})
        um = meta(cs.read_candidate(cand))
        check(um["scope"] == "Better drafts." and um["title"] == "Draft"
              and cs.read_candidate(cand).endswith("Better draft.\n"), "an amend of a candidate updates it")

        retire = file(folder, {"agent": "claude", "operation": "retire", "target_path": cand, "reason": "Done.",
                               "base_sha256": ac.sha256_text(cs.read_candidate(cand))})
        decide(folder, "accept-proposal", {"proposal_id": retire})
        check(cand not in cs.candidates() and "draft.md" in cs.archived()
              and meta(cs.read_archived("draft.md"))["status"] == "retired",
              "a retire moves the candidate to the private archive")

        check(snapshot(folder) == before and {rel: read(folder, rel) for rel in ac.examine(folder).texts}
              == governing_before, "through all four, the governing context and the folder never changed")
        accepted = sorted(os.listdir(cs.path(ps.PROPOSALS, apx.ACCEPTED)))
        check(accepted == sorted(f"{p}.json" for p in (create, amend, upd, retire))
              and apx.listing(folder)["pending"] == [], "each accepted record is kept, privately, decided")
        record = json.loads(open(cs.path(ps.PROPOSALS, apx.ACCEPTED, create + ".json"), encoding="utf-8").read())
        check(record["decision"]["decision"] == "accepted"
              and record["decision"]["outcome"] == "authority-candidates/new-rule.md",
              "with the decision and its outcome")
        shutil.rmtree(folder)


def case_reject_and_stale() -> None:
    print("\nrejecting, and stale proposals")
    with isolated_private_state():
        folder, cs, _cand = setup()
        pid = file(folder, {"agent": "a", "operation": "amend", "target_path": "authoritative/b.md", "reason": "r",
                            "base_sha256": sha(folder, "authoritative/b.md"), "proposed_body": "New.\n"})
        blank = file(folder, {"agent": "a", "operation": "create", "target_path": "authority-candidates/blank.md",
                              "reason": "r", "proposed_body": "x\n"})
        bare = file(folder, {"agent": "a", "operation": "create", "target_path": "authority-candidates/bare.md",
                             "reason": "r", "proposed_body": "y\n"})
        decide(folder, "reject-proposal", {"proposal_id": blank, "reason": "   "})
        decide(folder, "reject-proposal", {"proposal_id": bare})
        for rid in (blank, bare):
            rec = json.loads(open(cs.path(ps.PROPOSALS, apx.REJECTED, rid + ".json"), encoding="utf-8").read())
            check(rec["decision"]["decision"] == apx.REJECTED and "reason" not in rec["decision"],
                  f"rejecting needs no reason: rejected with {'a blank' if rid == blank else 'no'} reason, none recorded")
        candidates = cs.candidates()
        decide(folder, "reject-proposal", {"proposal_id": pid, "reason": "Out of scope."})
        record = json.loads(open(cs.path(ps.PROPOSALS, apx.REJECTED, pid + ".json"), encoding="utf-8").read())
        check(record["decision"]["reason"] == "Out of scope." and cs.candidates() == candidates
              and apx.listing(folder)["pending"] == [],
              "a reason given is kept privately with the rejection, and nothing else changes")

        stale = file(folder, {"agent": "a", "operation": "amend", "target_path": "authoritative/b.md", "reason": "r",
                              "base_sha256": sha(folder, "authoritative/b.md"), "proposed_body": "Other.\n"})
        name_taken = file(folder, {"agent": "a", "operation": "create", "target_path": "authority-candidates/later.md",
                                   "reason": "r", "proposed_body": "x\n"})
        write(folder, "authoritative/b.md", doc_text("b", "Beta", body="Edited by a person.\n"))
        from tests.agent_context import generate
        generate(folder)
        a = au.plan(folder, "add", {"title": "Later", "body": "y\n"})
        au.apply(folder, "add", a.request, a.plan_id, True)
        listed = {p["proposal_id"]: p for p in apx.listing(folder)["pending"]}
        check(listed[stale]["stale"] and "changed after" in listed[stale]["stale_reasons"][0]
              and not listed[name_taken]["stale"],
              "a changed target makes a proposal stale; a create whose name was since taken does not "
              "(the name is private, and resolved when accepted)")
        check(raises(au.ActionRefused, au.plan, folder, "accept-proposal", {"proposal_id": stale}),
              "a stale proposal cannot be accepted as written")
        decide(folder, "reject-proposal", {"proposal_id": stale, "reason": "Stale."})
        check(stale not in {p["proposal_id"] for p in apx.listing(folder)["pending"]}, "but it can be rejected")

        write(folder, "notes.txt", b"x")
        check(raises(au.ActionRefused, au.plan, folder, "accept-proposal", {"proposal_id": name_taken}),
              "nothing is accepted while the Agent Context is not valid")
        shutil.rmtree(folder)


def case_preview_then_decide() -> None:
    print("\na preview stays current while only the clock moves")
    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)

        def amend(target: str, replace: str) -> str:
            return file(folder, {"agent": "a", "operation": "amend", "target_path": target, "reason": "r",
                                 "base_sha256": sha(folder, target),
                                 "replacements": [{"find": "Body.", "replace": replace}]})
        first, beta, alpha_again, beta_again = (
            amend("authoritative/a.md", "A1."), amend("authoritative/b.md", "B1."),
            amend("authoritative/a.md", "A2."), amend("authoritative/b.md", "B2."))
        real_now = apx._now
        try:
            apx._now = lambda: "2026-01-01T00:00:00Z"
            shown = {pid: au.plan(folder, "accept-proposal", {"proposal_id": pid})
                     for pid in (first, beta, alpha_again)}
            rejecting = au.plan(folder, "reject-proposal", {"proposal_id": beta_again, "reason": "No."})
            check(not any(apx._now() in c.new for p in shown.values() for c in p.changes if c.new),
                  "a preview carries no decision time")
            apx._now = lambda: "2026-01-01T00:00:09Z"
            au.apply(folder, "accept-proposal", {"proposal_id": first}, shown[first].plan_id, True)
            record = json.loads(open(cs.path(ps.PROPOSALS, apx.ACCEPTED, first + ".json"),
                                     encoding="utf-8").read())
            check(record["decision"]["decided"] == "2026-01-01T00:00:09Z",
                  "with three others pending, accepting right after the preview applies, timed when written")
            au.apply(folder, "accept-proposal", {"proposal_id": beta}, shown[beta].plan_id, True)
            check(beta not in {p["proposal_id"] for p in apx.listing(folder)["pending"]},
                  "another's preview, whose inputs did not change, still applies")
            check(raises(au.StalePlan, au.apply, folder, "accept-proposal", {"proposal_id": alpha_again},
                         shown[alpha_again].plan_id, True),
                  "one whose planned candidate name has since been taken is stale")
            au.apply(folder, "reject-proposal", rejecting.request, rejecting.plan_id, True)
            record = json.loads(open(cs.path(ps.PROPOSALS, apx.REJECTED, beta_again + ".json"),
                                     encoding="utf-8").read())
            check(record["decision"]["decided"] == "2026-01-01T00:00:09Z", "rejecting is timed when written too")

            again = au.plan(folder, "accept-proposal", {"proposal_id": alpha_again})
            a = au.plan(folder, "add", {"title": "Alpha", "body": "Taken.\n"})
            au.apply(folder, "add", a.request, a.plan_id, True)
            check(raises(au.StalePlan, au.apply, folder, "accept-proposal", again.request, again.plan_id, True),
                  "a candidate change after the preview is still refused")
            again = au.plan(folder, "accept-proposal", {"proposal_id": alpha_again})
            write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited by a person.\n"))
            from tests.agent_context import generate
            generate(folder)
            check(raises(au.ActionRefused, au.apply, folder, "accept-proposal", again.request, again.plan_id, True)
                  and alpha_again in {p["proposal_id"] for p in apx.listing(folder)["pending"]},
                  "and so is a governing-context change: nothing is accepted")
        finally:
            apx._now = real_now
        shutil.rmtree(folder)


def case_atomic() -> None:
    print("\naccepting is one transaction")
    with isolated_private_state():
        folder, cs, _cand = setup()
        pid = file(folder, {"agent": "a", "operation": "create", "target_path": "authority-candidates/n.md",
                            "reason": "r", "proposed_body": "x\n"})
        plan = au.plan(folder, "accept-proposal", {"proposal_id": pid})

        def fault(step: str) -> None:
            if step.startswith("replace:proposals/accepted"):
                raise RuntimeError("disk full")
        check(raises(au.ApplyFailed, au.apply, folder, "accept-proposal", plan.request, plan.plan_id, True,
                     fault=fault), "a failure part-way fails the acceptance")
        check("authority-candidates/n.md" not in cs.candidates()
              and [p["proposal_id"] for p in apx.listing(folder)["pending"]] == [pid],
              "and rolls it back: no candidate, and the proposal still pending")
        shutil.rmtree(folder)


def run() -> None:
    case_listing()
    case_titles()
    case_import()
    case_older_front_matter()
    case_accept()
    case_reject_and_stale()
    case_preview_then_decide()
    case_atomic()
    print(f"\n{OK} All proposal review checks passed.")


if __name__ == "__main__":
    run()
