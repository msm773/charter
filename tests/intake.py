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

import base64
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import agent_proposals as apx  # noqa: E402
from app import authority as au  # noqa: E402
from app import console  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import transaction as tx  # noqa: E402
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


def case_unexpected_not_files() -> None:
    print("\nan unexpected record that is not a file: listed, described, never read or followed")
    import threading
    with isolated_private_state():
        folder, cs, _cand = setup()
        pending = cs.path(ps.PROPOSALS, apx.PENDING)
        os.makedirs(os.path.join(pending, "a-folder"))
        secret = os.path.join(tempfile.mkdtemp(prefix="charter-secret-"), "secret.txt")
        with open(secret, "w", encoding="utf-8") as fh:
            fh.write("SECRET-OUTSIDE-PRIVATE-STATE")
        kinds = {"a-folder": "a folder"}
        try:
            os.symlink(secret, os.path.join(pending, "linked.json"))
            kinds["linked.json"] = "a link"
        except (OSError, NotImplementedError):
            pass  # links need a privilege on some Windows accounts
        if hasattr(os, "mkfifo"):
            os.mkfifo(os.path.join(pending, "pipe.json"))
            kinds["pipe.json"] = "a special file"
        got = {}
        lister = threading.Thread(target=lambda: got.update(apx.listing(folder)), daemon=True)
        lister.start()
        lister.join(10)
        check(not lister.is_alive(), "listing never opens a pipe, so it never waits on one")
        listed = {u["name"]: u for u in got.get("unexpected", [])}
        check(sorted(listed) == sorted(kinds)
              and all(u["regular"] is False and "not a regular file" in u["why"] for u in listed.values()),
              "each is listed as unexpected and not a regular file")
        session = console.Session(folder)
        for name, kind in kinds.items():
            view = console.unexpected(session, {"name": name})
            check(view["regular"] is False and view["text"] is None and f"is {kind}, not a regular file" in view["message"]
                  and "SECRET" not in json.dumps(view),
                  f"viewing {kind} says what it is, shows no contents and follows nothing")
        check(os.path.isdir(os.path.join(pending, "a-folder")) and open(secret).read().startswith("SECRET"),
              "and each is left unchanged")
        shutil.rmtree(os.path.dirname(secret))
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

        def row(proposal) -> dict:
            text = proposal if isinstance(proposal, str) else json.dumps(proposal)
            return console.import_check(session, {"items": [{"text": text}]})["items"][0]

        def imp(proposal, **more) -> dict:
            return console.import_file(session, dict({"items": [{"text": json.dumps(proposal)}]}, **more))

        checked = row(bad)
        check(checked["status"] == "refused" and ("unknown_field", "base_commit") in
              {(p["code"], p.get("field")) for p in checked["problems"]},
              "it is checked exactly as `charter propose` checks it")
        checked = row(good)
        check(checked["status"] == "ready" and checked["summary"]["operation"] == "amend"
              and apx.listing(folder)["imported"] == [], "checking files nothing")
        check(raises(console.ApiError, imp, good), "filing needs the person's confirmation")
        filed = imp(good, confirm=True)
        check(filed["result"] == "pending" and
              [p["proposal_id"] for p in apx.listing(folder)["imported"]] == filed["proposal_ids"],
              "confirmed, it is filed as imported")
        check(row("{not json") == {"status": "malformed", "message": "This is not JSON."},
              "text that is not JSON is Malformed")

        imported = len(apx.listing(folder)["imported"])
        for what, body in (("front matter", "---\ntitle: Clearer\nauthority: authoritative\n---\n\nClearer.\n"),
                           ("front matter after a byte-order mark and blank lines",
                            "﻿\n\n---\nid: x\n---\nClearer.\n")):
            fronted = dict(good, proposed_body=body)
            checked = row(fronted)
            check(checked["status"] == "refused"
                  and [p["code"] for p in checked["problems"]] == ["front_matter_in_body"]
                  and "Remove it and submit again" in checked["problems"][0]["message"],
                  f"an imported body beginning with {what} is refused, with the correction")
            filed = imp(fronted, confirm=True)
            check(filed["result"] == "refused" and len(apx.listing(folder)["imported"]) == imported,
                  f"and confirming it files nothing ({what})")
        created = {"agent": "chat-agent", "operation": "create", "target_path": "authority-candidates/new-rule.md",
                   "reason": "A rule.", "proposed_body": "---\nlayout: post\n---\n\nRule.\n"}
        check(row(created)["status"] == "refused",
              "so is an imported create whose body begins with another tool's front matter")
        ruled = dict(created, proposed_body="---\nA thematic break, then prose.\n---\n\nRule.\n")
        check(row(ruled)["status"] == "ready",
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
        check(apx.listing(folder)["pending"] == [] and inbox_files(cs) == []
              and not any(os.path.exists(cs.path(ps.PROPOSALS, d)) for d in apx.LEGACY_DECIDED)
              and apx._ledger(cs) == {},
              "each accepted proposal leaves the inbox: no record, decided copy or ledger entry is kept")
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
        candidates = cs.candidates()
        decide(folder, "reject-proposal", {"proposal_id": bare})
        check(bare not in {p["proposal_id"] for p in apx.listing(folder)["pending"]}
              and not os.path.exists(cs.path(ps.PROPOSALS, apx.PENDING, bare + ".json"))
              and bare not in apx._ledger(cs),
              "rejecting needs no reason, and removes the proposal: no record or ledger entry is kept")
        # A request that still carries a reason, as an earlier console sent: it is not stored.
        decide(folder, "reject-proposal", {"proposal_id": pid, "reason": "Out of scope."})
        decide(folder, "reject-proposal", {"proposal_id": blank})
        check(cs.candidates() == candidates and apx.listing(folder)["pending"] == []
              and not any(os.path.exists(cs.path(ps.PROPOSALS, d)) for d in apx.LEGACY_DECIDED)
              and not any("Out of scope." in open(os.path.join(d, n), encoding="utf-8", errors="replace").read()
                          for d, _dirs, names in os.walk(cs.base) for n in names),
              "no rejection reason is stored anywhere, and nothing else changes")

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
            rejecting = au.plan(folder, "reject-proposal", {"proposal_id": beta_again})
            check(not any(apx._now() in c.new for p in shown.values() for c in p.changes if c.new),
                  "a preview carries no decision time")
            apx._now = lambda: "2026-01-01T00:00:09Z"
            au.apply(folder, "accept-proposal", {"proposal_id": first}, shown[first].plan_id, True)
            check(first not in {p["proposal_id"] for p in apx.listing(folder)["pending"]},
                  "with three others pending, accepting right after the preview applies")
            au.apply(folder, "accept-proposal", {"proposal_id": beta}, shown[beta].plan_id, True)
            check(beta not in {p["proposal_id"] for p in apx.listing(folder)["pending"]},
                  "another's preview, whose inputs did not change, still applies")
            check(raises(au.StalePlan, au.apply, folder, "accept-proposal", {"proposal_id": alpha_again},
                         shown[alpha_again].plan_id, True),
                  "one whose planned candidate name has since been taken is stale")
            au.apply(folder, "reject-proposal", rejecting.request, rejecting.plan_id, True)
            check(beta_again not in {p["proposal_id"] for p in apx.listing(folder)["pending"]}
                  and not os.path.exists(cs.path(ps.PROPOSALS, apx.PENDING, beta_again + ".json")),
                  "rejecting right after its preview applies too, and keeps no record")

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
            if step.startswith("replace:candidates/"):
                raise RuntimeError("disk full")
        check(raises(au.ApplyFailed, au.apply, folder, "accept-proposal", plan.request, plan.plan_id, True,
                     fault=fault), "a failure part-way fails the acceptance")
        check("authority-candidates/n.md" not in cs.candidates()
              and [p["proposal_id"] for p in apx.listing(folder)["pending"]] == [pid],
              "and rolls it back: no candidate, and the proposal still pending")
        shutil.rmtree(folder)


def inbox_files(cs) -> list:
    folder = cs.path(ps.PROPOSALS, apx.PENDING)
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def state_files(cs) -> dict:
    """Every private file for this context, with its bytes: what a refused
    submission must leave exactly as it was."""
    out = {}
    for d, _dirs, names in os.walk(cs.base):
        for n in names:
            with open(os.path.join(d, n), "rb") as fh:
                out[os.path.relpath(os.path.join(d, n), cs.base)] = fh.read()
    return out


def case_duplicates() -> None:
    print("\nduplicates: an exact match of a proposal still awaiting review")
    with isolated_private_state():
        folder, cs, _cand = setup()
        text = json.dumps({"agent": "codex", "operation": "create", "target_path": "authority-candidates/dup.md",
                           "reason": "Once.", "proposed_body": "# Dup\n\nText.\n"})
        raw = json.loads(text)
        first = apx.file(folder, raw, submitted=text.encode("utf-8"))
        check(first["result"] == "pending", "the first submission is filed")
        before = state_files(cs)
        again = apx.file(folder, raw, submitted=text.encode("utf-8"))
        check(again == apx.duplicate_result() and set(again) == {"result", "problem"}
              and again["problem"]["code"] == "duplicate", "the same text again is a duplicate, and says no more")
        check(state_files(cs) == before, "and nothing at all was written")
        imported = apx.file(folder, raw, source=apx.IMPORTED, submitted=text)
        check(imported["result"] == "duplicate" and state_files(cs) == before,
              "the same text imported in the console matches across sources")
        reordered = json.dumps(dict(reversed(list(raw.items()))))
        escaped = json.dumps(raw, ensure_ascii=True).replace("Dup", "\\u0044up")
        for label, variant in (("a trailing newline", text + "\n"), ("a leading space", " " + text),
                               ("a byte-order mark", "\ufeff" + text),
                               ("two byte-order marks, as bytes", b"\xef\xbb\xbf" * 2 + text.encode()),
                               ("different spacing", json.dumps(raw, indent=1)),
                               ("its keys reordered", reordered),
                               ("JSON escapes for the same characters", escaped)):
            result = apx.file(folder, apx.read_submission(
                variant if isinstance(variant, bytes) else variant.encode("utf-8")),
                submitted=variant)
            check(result == apx.duplicate_result(),
                  f"{label}: the same checked content, so a duplicate (Product Specification \u00a73.2)")
        check(state_files(cs) == before, "  and none of them wrote anything")
        check(apx.file(folder, raw) == apx.duplicate_result(),
              "a filing with no submitted bytes is matched by its content too")
        for field, value in (("agent", "other"), ("reason", "Twice."),
                             ("expected_context_impact", {"related": []}),
                             ("proposed_body", "# Dup\n\nText. \n")):
            result = apx.file(folder, dict(raw, **{field: value}))
            check(result["result"] == "pending", f"a different `{field}` makes a distinct proposal")
        check(apx.file(folder, dict(raw, expected_context_impact={"related": []}))
              == apx.duplicate_result(), "  and the same impact again is a duplicate of that one")
        check(apx.file(folder, dict(raw, proposed_meta=None)) == apx.duplicate_result()
              and apx.file(folder, dict(raw, expected_context_impact=None)) == apx.duplicate_result(),
              "an optional `proposed_meta` or `expected_context_impact` given as null is the same as "
              "one left out")
        check(len(apx.listing(folder)["pending"]) == 5, "five distinct proposals now wait")

        print("\nthe record keeps both digests; matching recomputes the content one")
        record = json.loads(open(cs.path(ps.PROPOSALS, apx.PENDING, first["proposal_id"] + ".json"),
                                 encoding="utf-8").read())
        check(record["submitted_sha256"] == apx.submission_identity(text.encode("utf-8"))
              and record["proposal_sha256"] == apx.proposal_fingerprint(raw)
              and record["proposal"] == raw and record["version"] == apx.RECORD_VERSION,
              "a new record keeps `submitted_sha256`, the bytes' digest, beside `proposal_sha256`")
        check(apx.proposal_fingerprint(dict(raw, expected_context_impact="\u00e9"))
              == apx.proposal_fingerprint(json.loads(json.dumps(dict(raw, expected_context_impact="\u00e9"),
                                                                ensure_ascii=False))),
              "raw and escaped non-ASCII text have one fingerprint")
        # A record an earlier Charter filed: without `proposal_sha256`, and once
        # without either digest. Written exactly as that Charter wrote them, and
        # vouched for by the ledger, as it would have been.
        for pid, extra, label in (("p-20250101-cccccccc", {}, "neither digest"),
                                  ("p-20250101-dddddddd", {"submitted_sha256": "e" * 64},
                                   "only its `submitted_sha256`")):
            old_raw = {"agent": "old", "operation": "create",
                       "target_path": "authority-candidates/old.md", "reason": pid,
                       "proposed_body": "# Old\n"}
            old_record = dict({"version": 1, "proposal_id": pid, "source": apx.AGENT,
                               "received": "2025-01-01T00:00:00Z", "proposal": old_raw}, **extra)
            data = apx._record_bytes(old_record)
            with open(cs.path(ps.PROPOSALS, apx.PENDING, pid + ".json"), "wb") as fh:
                fh.write(data)
            ledger = apx._ledger(cs)
            ledger[pid] = {"sha256": hashlib.sha256(data).hexdigest(), "source": apx.AGENT}
            apx._write_ledger(cs, ledger)
            pending_before = sorted(inbox_files(cs))
            check(apx.file(folder, json.loads(json.dumps(old_raw, indent=3)), submitted=b"{}")
                  == apx.duplicate_result() and sorted(inbox_files(cs)) == pending_before
                  and open(cs.path(ps.PROPOSALS, apx.PENDING, pid + ".json"), "rb").read() == data,
                  f"a waiting record an earlier Charter filed, with {label}, is matched by its content, "
                  "and left byte for byte as it was")
        for pid in ("p-20250101-cccccccc", "p-20250101-dddddddd"):
            decide(folder, "reject-proposal", {"proposal_id": pid})

        print("\ndecided proposals never match")
        pid = first["proposal_id"]
        decide(folder, "reject-proposal", {"proposal_id": pid})
        after_reject = apx.file(folder, raw, submitted=text.encode("utf-8"))
        check(after_reject["result"] == "pending" and after_reject["proposal_id"] != pid,
              "once rejected, the same text is a new proposal")
        decide(folder, "accept-proposal", {"proposal_id": after_reject["proposal_id"]})
        after_accept = apx.file(folder, raw, submitted=text.encode("utf-8"))
        check(after_accept["result"] == "pending", "once accepted, the same text is a new proposal again")

        print("\nreplacing the waiting proposal, in the console")
        waiting = after_accept["proposal_id"]
        old = json.loads(open(cs.path(ps.PROPOSALS, apx.PENDING, waiting + ".json"), encoding="utf-8").read())
        real_now = apx._now
        try:
            apx._now = lambda: "2030-01-01T00:00:00Z"
            replaced = apx.replace(folder, raw, waiting, source=apx.IMPORTED, submitted=text)
        finally:
            apx._now = real_now
        new = json.loads(open(cs.path(ps.PROPOSALS, apx.PENDING, waiting + ".json"), encoding="utf-8").read())
        listed = [p for p in apx.listing(folder)["imported"] + apx.listing(folder)["pending"]
                  if p["proposal_id"] == waiting]
        check(replaced == {"result": "pending", "proposal_id": waiting}
              and old["source"] == apx.AGENT and new["source"] == apx.IMPORTED
              and new["received"] == "2030-01-01T00:00:00Z" and new["proposal"] == raw
              and len(listed) == 1 and listed[0]["source"] == apx.IMPORTED,
              "Replace updates that one proposal in place: its received time and source are the new ones")
        check(len(inbox_files(cs)) == len(apx._ledger(cs)) and f"{waiting}.json" in inbox_files(cs)
              and not any(os.path.exists(cs.path(ps.PROPOSALS, d)) for d in apx.LEGACY_DECIDED),
              "one record, one ledger entry: no second proposal, and no record of what it replaced")
        check(new["proposal_sha256"] == apx.proposal_fingerprint(raw)
              and new["submitted_sha256"] == apx.submission_identity(text),
              "  the replaced record carries this submission's digests")
        check(apx.replace(folder, raw, waiting, submitted=text + " ")["result"] == "pending",
              "the same content written differently may replace it too")
        check(apx.replace(folder, dict(raw, reason="Other."), waiting, submitted=text)["result"]
              == "refused", "only a submission with the same content can replace it")
        check(apx.replace(folder, raw, pid, submitted=text)["result"] == "refused",
              "and only a proposal still awaiting review")
        shutil.rmtree(folder)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _session(folder: str):
    session = console.Session()
    console.open_context(session, {"path": folder})
    return session


def case_submission_parity() -> None:
    print("\none reading of submitted bytes: `charter propose`, pasted JSON and a chosen file")
    with isolated_private_state() as state_root:
        folder, cs, _cand = setup()
        session = _session(folder)
        launch = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_launch.py")

        def cli(data: bytes) -> dict:
            p = subprocess.run([sys.executable, launch, os.path.dirname(state_root), "propose",
                                "--context", folder], input=data, capture_output=True)
            return json.loads(p.stdout)

        def proposal(name: str, **more) -> dict:
            return dict({"agent": "parity", "operation": "create",
                         "target_path": f"authority-candidates/{name}.md", "reason": "Parity.",
                         "proposed_body": f"# {name.title()} caf\u00e9\n\nText.\n"}, **more)

        bom = b"\xef\xbb\xbf"
        cases = [
            ("UTF-8 without a byte-order mark", json.dumps(proposal("plain")).encode(), "ready"),
            ("one leading UTF-8 byte-order mark", bom + json.dumps(proposal("one-bom")).encode(), "ready"),
            ("two leading byte-order marks", bom * 2 + json.dumps(proposal("two-bom")).encode(), "ready"),
            ("whitespace, then a byte-order mark", b"  " + bom + json.dumps(proposal("ws-bom")).encode(),
             "not_json"),
            ("malformed UTF-8", json.dumps(proposal("bad")).encode().replace(b"Parity", b"P\xffrity"),
             "not_utf8"),
            ("UTF-16 with its byte-order mark", ("\ufeff" + json.dumps(proposal("utf16"))).encode("utf-16-le"),
             "not_utf8"),
            ("raw non-ASCII UTF-8", json.dumps(proposal("raw"), ensure_ascii=False).encode("utf-8"), "ready"),
            ("escaped non-ASCII", json.dumps(proposal("escaped"), ensure_ascii=True).encode("ascii"), "ready"),
            ("not one object", b"[1, 2]", "not_an_object"),
        ]
        for label, data, expected in cases:
            items = [{"bytes": _b64(data)}]
            try:
                items.append({"text": data.decode("utf-8")})
            except UnicodeDecodeError:
                pass
            before = state_files(cs)
            rows = console.import_check(session, {"items": items})["items"]
            check(state_files(cs) == before, f"{label}: checking it wrote nothing")
            statuses = {r["status"] for r in rows}
            if expected == "ready":
                # The file is checked first; its pasted text is the same content.
                check([r["status"] for r in rows] == ["ready", "same"],
                      f"  as a file it is Ready, and as pasted text the same content")
                out = cli(data)
                check(out["result"] == "pending", "  `charter propose` files the same bytes")
                record = json.load(open(cs.path(ps.PROPOSALS, apx.PENDING, out["proposal_id"] + ".json"),
                                        encoding="utf-8"))
                check(record["submitted_sha256"] == hashlib.sha256(data).hexdigest(),
                      "  its transport digest is of the bytes exactly as given")
                again = console.import_check(session, {"items": items})["items"]
                check(all(r["status"] == "awaiting" for r in again),
                      "  then, as a file or pasted, it is Already awaiting review: one queue")
            else:
                cli_code = cli(data)["problems"][0]["code"]
                message = console.MALFORMED_MESSAGES[expected]
                check(statuses == {"malformed"} and all(r["message"] == message for r in rows)
                      and cli_code == expected,
                      f"  Malformed ({message}) in the console, and `{expected}` from `charter propose`")
        rows = console.import_check(session, {"items": [
            {"bytes": _b64(json.dumps(proposal("raw")).encode())},
            {"text": json.dumps(proposal("raw"), indent=4, ensure_ascii=False)},
            {"text": json.dumps(dict(reversed(list(proposal("raw").items()))))}]})["items"]
        check([r["status"] for r in rows] == ["awaiting"] * 3,
              "escaped, reindented and reordered copies of a filed proposal all match it")
        oversized = b" " * apx.MAX_INPUT + b"{}"
        rows = console.import_check(session, {"items": [{"bytes": _b64(oversized)}]})["items"]
        check(rows == [{"status": "malformed", "message": "This proposal is too large."}]
              and cli(oversized)["problems"][0]["code"] == "too_large",
              "more than the input limit is too large on both routes")
        shutil.rmtree(folder)


def case_console_import() -> None:
    print("\nImport Agent Proposals: per-item checks, then the selected items, all or none")
    with isolated_private_state():
        folder, cs, cand = setup()
        session = _session(folder)
        gov = ac.examine(folder).documents[0]
        gov_text = ac.read_text(folder, gov.path)
        cand_text = cs.read_candidate(cand)

        def create(name: str, **more) -> dict:
            return dict({"agent": "importer", "operation": "create",
                         "target_path": f"authority-candidates/{name}.md", "reason": f"Add {name}.",
                         "proposed_body": f"# {name}\n\nText.\n"}, **more)

        waiting = create("waiting")
        check(apx.file(folder, waiting)["result"] == "pending", "a proposal is already waiting")
        ready = create("ready")
        items = [
            {"text": json.dumps(ready)},
            {"bytes": _b64(b"\xef\xbb\xbf" + json.dumps(ready, indent=2).encode())},
            {"text": json.dumps(waiting)},
            {"text": json.dumps({"agent": "a", "operation": "amend", "target_path": gov.path,
                                 "reason": "Late.", "base_sha256": "0" * 64,
                                 "proposed_body": "New.\n"})},
            {"text": json.dumps(dict(ready, base_commit="abc"))},
            {"bytes": _b64(b"not json")},
        ]
        before = state_files(cs)
        answer = console.import_check(session, {"items": items})
        statuses = [r["status"] for r in answer["items"]]
        check(answer["unavailable"] is None
              and statuses == ["ready", "same", "awaiting", "stale", "refused", "malformed"],
              "statuses: Ready, Same as another item, Already awaiting review, Stale, Refused, Malformed")
        check(state_files(cs) == before, "checking wrote nothing")
        rows = answer["items"]
        check(rows[0]["summary"] == {"title": "ready", "agent": "importer", "operation": "create"}
              and rows[1]["same_as"] == 0 and rows[2]["waiting"]["title"] == "waiting"
              and rows[3]["problems"][0]["code"] == "stale"
              and rows[4]["problems"][0]["code"] == "unknown_field"
              and not re.search(r"[0-9a-f]{64}", json.dumps(answer))
              and cs.base not in json.dumps(answer),
              "each row says only what the person needs: no digest or private location")
        for bad in ({"bytes": _b64(b"{}"), "name": "proposal.json"}, {"path": "C:/x.json"}, "text"):
            try:
                console.import_check(session, {"items": [bad]})
                refused = False
            except console.ApiError:
                refused = True
            check(refused, f"an item carrying anything but its text or bytes is refused: {bad!r}")
        try:
            console.import_check(session, {"items": [{"text": "{}"}] * (apx.MAX_BATCH + 1)})
            too_many = False
        except console.ApiError:
            too_many = True
        check(too_many, f"at most {apx.MAX_BATCH} items are checked at a time")

        print("\n  the import files the selected items, all or none")
        second = create("second")
        done = console.import_file(session, {"items": [items[0], {"text": json.dumps(second)}],
                                             "confirm": True})
        check(done["result"] == "pending" and done["count"] == 2,
              "two selected Ready items: both filed")
        listed = {p["proposal_id"]: p for p in apx.listing(folder)["imported"]}
        check(set(done["proposal_ids"]) <= set(listed) and len(apx._ledger(cs)) == len(inbox_files(cs)),
              "  as imported proposals, each vouched for by the ledger")
        check(ac.read_text(folder, gov.path) == gov_text and cs.read_candidate(cand) == cand_text
              and not os.path.exists(cs.path(ps.PROPOSALS, "accepted")),
              "  nothing accepted: no governing document, candidate or change set changed")
        before = state_files(cs)
        third, fourth = create("third"), create("fourth")
        mixed = console.import_file(session, {"items": [{"text": json.dumps(third)},
                                                        {"text": json.dumps(waiting)}], "confirm": True})
        check(mixed["result"] == "refused" and [r["status"] for r in mixed["items"]] == ["ready", "awaiting"]
              and state_files(cs) == before,
              "a selection with one item not ready files nothing, and says what each item is now")
        amend_cand = {"agent": "a", "operation": "amend", "target_path": cand, "reason": "Tweak.",
                      "base_sha256": ac.sha256_text(cand_text), "proposed_body": "Tweaked.\n"}
        pair = [{"text": json.dumps(fourth)}, {"text": json.dumps(amend_cand)}]
        check([r["status"] for r in console.import_check(session, {"items": pair})["items"]]
              == ["ready", "ready"], "two items check Ready")
        plan = au.plan(folder, "edit-candidate", {"candidate": cand, "body": "Changed meanwhile.\n"})
        au.apply(folder, "edit-candidate", plan.request, plan.plan_id, True)
        before = state_files(cs)
        late = console.import_file(session, {"items": pair, "confirm": True})
        check(late["result"] == "refused" and [r["status"] for r in late["items"]] == ["ready", "refused"]
              and state_files(cs) == before,
              "a target changed between the check and the import: nothing filed, not even the other item")
        try:
            console.import_file(session, {"items": pair})
            unconfirmed = False
        except console.ApiError:
            unconfirmed = True
        check(unconfirmed, "an import needs the person's confirmation")

        print("\n  a failure part-way leaves none of them")
        fifth, sixth = create("fifth"), create("sixth")
        batch = [(fifth, json.dumps(fifth).encode()), (sixth, json.dumps(sixth).encode())]
        ledger_before = apx._ledger(cs)
        before_files = inbox_files(cs)
        seen = []

        def fail_second(step: str) -> None:
            if step.startswith("replace:"):
                seen.append(step)
                if len(seen) == 2:
                    raise RuntimeError("disk full")
        result = apx.file_batch(folder, batch, fault=fail_second)
        check(len(seen) == 2 and result["result"] == "unavailable" and result["retryable"] is True
              and inbox_files(cs) == before_files and apx._ledger(cs) == ledger_before,
              "the second record failing after the first was written: both are gone, the ledger as it was")

        class Died(BaseException):
            pass

        def die_second(step: str) -> None:
            if step.startswith("replace:"):
                seen.append(step)
                if len(seen) == 4:
                    raise Died()
        try:
            apx.file_batch(folder, batch, fault=die_second)
            died = False
        except Died:
            died = True
        check(died and tx.interrupted(cs), "the process dying part-way leaves its journal")
        check(apx.file(folder, create("meanwhile"))["result"] == "unavailable",
              "  intake refuses until the write is recovered")
        au.recover(folder)
        check(not tx.interrupted(cs) and inbox_files(cs) == before_files
              and {r["proposal_id"] for r in apx.records(cs)[0]} == {f[:-5] for f in before_files},
              "  and recovery removes every record it wrote: none of the batch is left")
        done = apx.file_batch(folder, batch)
        check(done["result"] == "pending" and len(done["proposal_ids"]) == 2, "  then it files cleanly")

        print("\n  Replace, one item at a time")
        replaced = console.import_replace(session, {"item": {"bytes": _b64(json.dumps(waiting, indent=1).encode())},
                                                    "replace": answer["items"][2]["waiting"]["proposal_id"],
                                                    "confirm": True})
        record = json.load(open(cs.path(ps.PROPOSALS, apx.PENDING, replaced["proposal_id"] + ".json"),
                                encoding="utf-8"))
        check(replaced["result"] == "pending" and record["source"] == apx.IMPORTED
              and record["submitted_sha256"] == hashlib.sha256(json.dumps(waiting, indent=1).encode()).hexdigest(),
              "a waiting proposal is replaced in place by one item of the same content")

        print("\n  an Agent Context that cannot accept proposals")
        write(folder, "notes.txt", "stray")
        answer = console.import_check(session, {"items": [{"text": json.dumps(create("x"))}]})
        check(answer["items"] == [] and answer["unavailable"]["message"],
              "it is Unavailable, once, and no item has a status")
        check(console.import_file(session, {"items": [{"text": json.dumps(create("x"))}],
                                            "confirm": True})["result"] == "unavailable",
              "  and nothing can be imported")
        shutil.rmtree(folder)


def case_readme_import() -> None:
    print("\nthe README describes content duplicates and Import Agent Proposals")
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md"),
              encoding="utf-8") as fh:
        readme = fh.read()
    check("character for character" not in readme
          and "Charter compares the proposal's fields, not how the JSON was written" in readme
          and "a different `agent`, `reason`, `expected_context_impact`, or any other field does" in readme,
          "a duplicate is the same content, every field counting")
    check("choose **Import agent proposals…**" in readme and "**Choose files…**" in readme
          and "A file's name appears only in that row: Charter never receives or keeps it." in readme
          and "files all of them or none" in readme
          and all(f"| **{s}** |" in readme for s in ("Ready", "Already awaiting review",
                                                     "Same as another selected item", "Stale",
                                                     "Refused", "Malformed"))
          and "**Unavailable**" in readme and "up to 20 proposals at a time" in readme,
          "importing: paste, choose or drop; each status; all or none; file names stay in the browser")


def case_older_copy_reads_new_records() -> None:
    print("\nan earlier copy of Charter, sharing this private state, reads the new records")
    head = subprocess.run(["git", "show", "HEAD:app/agent_proposals.py"], capture_output=True,
                          cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if head.returncode != 0 or b"proposal_sha256" in head.stdout:
        print("  skip: no earlier committed copy to compare with")
        return
    spec = importlib.util.spec_from_loader("app._earlier_agent_proposals", loader=None)
    earlier = importlib.util.module_from_spec(spec)
    earlier.__package__ = "app"
    exec(compile(head.stdout.decode("utf-8"), "earlier agent_proposals.py", "exec"), earlier.__dict__)
    with isolated_private_state():
        folder, cs, _cand = setup()
        text = json.dumps({"agent": "a", "operation": "create", "target_path": "authority-candidates/e.md",
                           "reason": "Both copies.", "proposed_body": "# E\n"})
        new = apx.file(folder, json.loads(text), submitted=text.encode())
        imported = apx.file_batch(folder, [(json.loads(text.replace("E", "F")), text.replace("E", "F").encode())])
        filed, unexpected = earlier.records(cs)
        ids = {r["proposal_id"] for r in filed}
        check(new["proposal_id"] in ids and set(imported["proposal_ids"]) <= ids and unexpected == [],
              "the earlier copy lists every new record as filed: the ledger vouches for them")
        check(earlier.file(folder, json.loads(text), submitted=text.encode()) == earlier.duplicate_result(),
              "it still matches a byte-identical resubmission by `submitted_sha256`")
        shutil.rmtree(folder)


def case_legacy_records() -> None:
    print("\nrecords an earlier Charter kept: decided ones left alone, and never history")
    with isolated_private_state():
        folder, cs, _cand = setup()
        old_pending = file(folder, {"agent": "a", "operation": "create", "target_path": "authority-candidates/o.md",
                                    "reason": "Old.", "proposed_body": "x\n"})
        # An earlier Charter kept decided records, and their ledger entries.
        for decided, pid in (("accepted", "p-20250101-aaaaaaaa"), ("rejected", "p-20250101-bbbbbbbb")):
            os.makedirs(cs.path(ps.PROPOSALS, decided), exist_ok=True)
            with open(cs.path(ps.PROPOSALS, decided, pid + ".json"), "w", encoding="utf-8") as fh:
                fh.write(json.dumps({"proposal_id": pid, "decision": {"decision": decided, "reason": "Old."}}))
        ledger = apx._ledger(cs)
        ledger.update({"p-20250101-aaaaaaaa": {"sha256": "0" * 64, "source": "agent"},
                       "p-20250101-bbbbbbbb": {"sha256": "1" * 64, "source": "agent"}})
        apx._write_ledger(cs, ledger)
        legacy = {d: sorted(os.listdir(cs.path(ps.PROPOSALS, d))) for d in apx.LEGACY_DECIDED}
        legacy_bytes = {d: [open(cs.path(ps.PROPOSALS, d, n), "rb").read() for n in names]
                        for d, names in legacy.items()}
        check([p["proposal_id"] for p in apx.listing(folder)["pending"]] == [old_pending]
              and apx.listing(folder)["unexpected"] == [],
              "decided records are never listed, as proposals or as unexpected material")
        text = json.dumps({"agent": "a", "operation": "create", "target_path": "authority-candidates/o.md",
                           "reason": "Old.", "proposed_body": "x\n"})
        check(apx.file(folder, json.loads(text), submitted=text) == apx.duplicate_result(),
              "a proposal filed before Charter kept submission identities is matched by its content")
        check(apx.file(folder, dict(json.loads(text), reason="New."), submitted=text)["result"]
              == "pending", "  and a different one is filed")
        check(set(apx._ledger(cs)) == {p["proposal_id"] for p in apx.listing(folder)["pending"]},
              "filing drops ledger entries for decided proposals: it vouches only for those waiting")
        check({d: sorted(os.listdir(cs.path(ps.PROPOSALS, d))) for d in apx.LEGACY_DECIDED} == legacy
              and {d: [open(cs.path(ps.PROPOSALS, d, n), "rb").read() for n in names]
                   for d, names in legacy.items()} == legacy_bytes,
              "and the decided records themselves are left exactly as they were")
        shutil.rmtree(folder)


def run() -> None:
    case_listing()
    case_unexpected_not_files()
    case_titles()
    case_import()
    case_older_front_matter()
    case_accept()
    case_reject_and_stale()
    case_preview_then_decide()
    case_atomic()
    case_duplicates()
    case_submission_parity()
    case_console_import()
    case_older_copy_reads_new_records()
    case_readme_import()
    case_legacy_records()
    print(f"\n{OK} All proposal review checks passed.")


if __name__ == "__main__":
    run()
