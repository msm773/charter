"""Candidate provenance. Run: python -m tests.provenance

Product Specification §4, Agent Context as the Project Asset §3 and the UI
and Interaction Standards: for each authority candidate Charter keeps one
private baseline — the exact text it last wrote, the kind of action, and the
date.

  * every Charter write of a candidate replaces it — Create candidate,
    Revise, Edit, accepting a proposal into a candidate, a revision candidate
    or an update, and a change set's withdrawal — in the same transaction, so a
    rolled-back action leaves it as it was; retiring a candidate, retiring it
    through a proposal, and a change set using it up discard it;
  * a candidate is compared with it as line-ending-normalized text, only when
    viewed: matching, changed, none, or unreadable; a candidate with no
    baseline is never adopted, and viewing writes nothing;
  * Read compares a changed candidate with Charter's version, whole text, and
    Mark as seen makes the text the person read the new baseline, changing
    nothing else;
  * a change set using a changed candidate warns, by title, and still applies;
  * none of it is ever served to an agent, written into the Agent Context,
    recorded as activity or listed in Recent, and a changed candidate never
    makes the context invalid.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import authority as au  # noqa: E402
from app import changeset  # noqa: E402
from app import console  # noqa: E402
from app import manager as mg  # noqa: E402
from app import mcp  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import propose  # noqa: E402
from app import provenance as prov  # noqa: E402
from app import read  # noqa: E402
from app.docs import today  # noqa: E402
from tests.agent_context import context, snapshot  # noqa: E402
from tests.harness import isolated_private_state  # noqa: E402
from tests.mcp import Session  # noqa: E402

OK = "ok"
KAPPA = "authority-candidates/kappa.md"
MARKER = "PROVENANCE-ONLY-TEXT"


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


class Crash(BaseException):
    """The process dying at a step: no in-process rollback runs."""


def refusal(fn, *args, **kwargs) -> str:
    try:
        fn(*args, **kwargs)
    except (au.ActionRefused, changeset.ChangeSetError, console.ApiError) as exc:
        return str(exc)
    return ""


def apply(folder: str, kind: str, request: dict, fault=None) -> dict:
    p = au.plan(folder, kind, request)
    confirm = au.CONFIRM_PHRASE if p.governing_change else True
    return au.apply(folder, kind, p.request, p.plan_id, confirm, fault=fault)


def cs_of(folder: str) -> ps.ContextState:
    return ps.PrivateState.default().for_context(folder)


def add(folder: str, title: str, body: str = "") -> str:
    apply(folder, "add", {"title": title, "scope": f"{title} scope.", "body": body or f"# {title}\n\nBody.\n"})
    return ps.logical_candidate(f"{title.lower()}.md")


def record_file(cs: ps.ContextState, logical: str) -> str:
    return cs.path(*prov.record_path(logical).split("/"))


def edit_by_hand(cs: ps.ContextState, logical: str, append: str = "\nA paragraph added by hand.\n") -> None:
    with open(cs.candidate_file(logical), "ab") as fh:
        fh.write(append.encode("utf-8"))


def entries(folder: str) -> dict:
    state = console.state(console.Session(folder))
    return {d["path"]: d for d in state["documents"] if d["kind"] == "candidate"}


def private_files(cs: ps.ContextState) -> dict:
    out = {}
    for d, _dirs, names in os.walk(cs.base):
        for n in names:
            rel = os.path.relpath(os.path.join(d, n), cs.base)
            if rel.split(os.sep)[0] == ps.LOCKS:
                continue
            with open(os.path.join(d, n), "rb") as fh:
                out[rel] = fh.read()
    return out


def proposal_id(result: dict) -> str:
    assert result["result"] == "pending", result
    return result["proposal_id"]


def file_proposal(folder: str, proposal: dict) -> str:
    return proposal_id(propose.submit(["--context", folder], json.dumps(proposal).encode("utf-8")))


def case_lifecycle() -> None:
    print("\nEvery Charter write of a candidate sets its baseline; every removal discards it")
    with isolated_private_state():
        folder = context()
        cs = cs_of(folder)
        day = today()

        def baseline(logical):
            return prov.read(cs, logical)

        def exact(logical, event):
            b = baseline(logical)
            return b is not None and b["event"] == event and b["date"] == day \
                and b["text"] == cs.read_candidate(logical)

        kappa = add(folder, "Kappa")
        check(exact(kappa, prov.CREATED), "Create candidate: its exact text, as created, today")
        apply(folder, "edit-candidate", {"candidate": kappa, "body": "# Kappa\n\nEdited.\n"})
        check(exact(kappa, prov.EDITED), "Edit: replaced by the edited text")
        apply(folder, "revise", {"path": "authoritative/a.md"})
        revision = next(c for c in cs.candidates() if c != kappa)
        check(exact(revision, prov.REVISED), "Revise: the new revision candidate's text")

        created = file_proposal(folder, {"agent": "codex", "operation": "create",
                                         "target_path": "authority-candidates/from-agent.md",
                                         "reason": "Needed.", "proposed_body": "# From agent\n"})
        apply(folder, "accept-proposal", {"proposal_id": created})
        check(exact("authority-candidates/from-agent.md", prov.ACCEPTED),
              "accepting a proposal that creates a candidate: accepted from an Agent Proposal")
        amend_gov = file_proposal(folder, {
            "agent": "codex", "operation": "amend", "target_path": "authoritative/b.md", "reason": "Better.",
            "base_sha256": ac.sha256_text(ac.read_text(folder, "authoritative/b.md")),
            "proposed_body": "# Beta\n\nBetter.\n"})
        before = set(cs.candidates())
        apply(folder, "accept-proposal", {"proposal_id": amend_gov})
        rev2 = (set(cs.candidates()) - before).pop()
        check(exact(rev2, prov.ACCEPTED), "accepting an amendment of a governing document: the revision "
                                          "candidate, accepted from an Agent Proposal")
        amend_cand = file_proposal(folder, {
            "agent": "codex", "operation": "amend", "target_path": kappa, "reason": "Update.",
            "base_sha256": ac.sha256_text(cs.read_candidate(kappa)), "proposed_body": "# Kappa\n\nUpdated.\n"})
        apply(folder, "accept-proposal", {"proposal_id": amend_cand})
        check(exact(kappa, prov.UPDATED), "accepting an amendment of a candidate: updated from an Agent Proposal")

        retire_by_agent = file_proposal(folder, {
            "agent": "codex", "operation": "retire", "target_path": "authority-candidates/from-agent.md",
            "reason": "Not needed.",
            "base_sha256": ac.sha256_text(cs.read_candidate("authority-candidates/from-agent.md"))})
        apply(folder, "accept-proposal", {"proposal_id": retire_by_agent})
        check(baseline("authority-candidates/from-agent.md") is None
              and not os.path.exists(record_file(cs, "authority-candidates/from-agent.md")),
              "a candidate retired through an accepted proposal: its baseline is discarded")
        apply(folder, "retire", {"candidate": revision})
        check(not os.path.exists(record_file(cs, revision)), "Retire: its baseline is discarded")

        ctx = changeset.Ctx(folder)
        draft = changeset.create(ctx, start={"withdraw": "authoritative/a.md"})
        draft = changeset.update(ctx, draft["id"], draft["revision"], {
            "candidates": [kappa, rev2],
            "decisions": {kappa: {"decision": "govern-alongside"},
                          rev2: {"decision": "replace", "target": "authoritative/b.md"}}})
        apply(folder, "changeset", {"draft_id": draft["id"], "draft_revision": draft["revision"]})
        withdrawn = [c for c in cs.candidates()]
        check(len(withdrawn) == 1 and exact(withdrawn[0], prov.WITHDRAWN),
              "a change set's withdrawal: the returned candidate, returned to candidate status")
        check(not os.path.exists(record_file(cs, kappa)) and not os.path.exists(record_file(cs, rev2)),
              "and the candidates it used up, by govern-alongside and replace, lose theirs")
        check(sorted(os.listdir(cs.path(ps.BASELINES))) == [ps.candidate_name(withdrawn[0]) + ".json"],
              "exactly one baseline per candidate remains: no earlier version is kept")
        record = json.load(open(record_file(cs, withdrawn[0]), encoding="utf-8"))
        check(sorted(record) == ["date", "event", "text", "version"],
              "a baseline holds only its text, the event and the date: no time, identity or history")


def case_states() -> None:
    print("\nMatching, changed, none and unreadable, compared only as the person views them")
    with isolated_private_state():
        folder = context()
        cs = cs_of(folder)
        kappa = add(folder, "Kappa")
        lam = add(folder, "Lambda")
        mu = add(folder, "Mu")
        nu = add(folder, "Nu")
        e = entries(folder)
        check(all(e[c]["provenance"]["state"] == "matching" for c in (kappa, lam, mu, nu))
              and e[kappa]["provenance"]["event"] == "created" and e[kappa]["provenance"]["date"] == today(),
              "after Charter writes them, every candidate matches, with its event and date")
        edit_by_hand(cs, kappa)
        text = cs.read_candidate(lam)
        with open(cs.candidate_file(lam), "wb") as fh:
            fh.write(text.replace("\n", "\r\n").encode("utf-8"))
        os.remove(record_file(cs, mu))  # as if filed before Charter kept baselines
        with open(cs.candidate_file(nu), "wb") as fh:
            fh.write(b"\xff\xfe not text")
        before = private_files(cs)
        e = entries(folder)
        check(e[kappa]["provenance"]["state"] == "changed", "a direct edit: changed")
        check(e[lam]["provenance"]["state"] == "matching", "a line-ending-only resave: still matching")
        check(e[mu]["provenance"] == {"state": "none", "event": "", "date": ""},
              "no baseline: none, with no event or date")
        check(e[nu]["provenance"]["state"] == "unreadable" and e[nu].get("unreadable"),
              "a file Charter cannot read: unreadable, not changed")
        with open(cs.path(ps.CANDIDATES, "by-hand.md"), "w", encoding="utf-8") as fh:
            fh.write("---\ntitle: By hand\n---\n\n# By hand\n")
        check(entries(folder)["authority-candidates/by-hand.md"]["provenance"]["state"] == "none",
              "a candidate placed by hand has none")
        session = console.Session(folder)
        for path in (kappa, mu, "authority-candidates/by-hand.md"):
            console.preview(session, {"source": "document", "path": path})
        after = private_files(cs)
        after.pop(os.path.join(ps.CANDIDATES, "by-hand.md"))
        check(after == before and not os.path.exists(record_file(cs, mu))
              and not os.path.exists(record_file(cs, "authority-candidates/by-hand.md")),
              "viewing writes nothing: a candidate with no baseline is never adopted")
        check(e[kappa]["title"] == "Kappa" and not refusal(au.plan, folder, "retire", {"candidate": kappa})
              and not refusal(au.plan, folder, "edit-candidate", {"candidate": kappa, "title": "K"}),
              "a changed candidate is listed and usable as before")
        exam = ac.examine(folder)
        check(exam.valid and not exam.errors and mg.check(folder, git=False)["agents_served"],
              "and the Agent Context stays valid and served")


def case_read_and_compare() -> None:
    print("\nRead shows one provenance line; Compare shows the change from Charter's version")
    with isolated_private_state():
        folder = context()
        cs = cs_of(folder)
        kappa = add(folder, "Kappa")
        session = console.Session(folder)
        shown = console.preview(session, {"source": "document", "path": kappa})["provenance"]
        check(shown["state"] == "matching" and shown["event"] == "created" and shown["date"] == today()
              and shown["sha"] == ac.sha256_text(cs.read_candidate(kappa)),
              "a matching candidate: its event, date, and the hash of the text read")
        text = cs.read_candidate(kappa)
        with open(cs.candidate_file(kappa), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text.replace("title: Kappa", "title: Kappa by hand") + "\nAdded by hand.\n")
        shown = console.preview(session, {"source": "document", "path": kappa})["provenance"]
        check(shown["state"] == "changed", "after a direct edit: changed")
        cmp = console.compare(session, {"candidate": kappa, "against": prov.CHARTER_VERSION})
        check(cmp["right"]["title"] == "Charter's version" and "+Added by hand." in cmp["diff"]
              and "-title: Kappa" in cmp["diff"] and "+title: Kappa by hand" in cmp["diff"],
              "Compare with Charter's version shows the whole change, the edited title included")
        os.remove(record_file(cs, kappa))
        check(console.preview(session, {"source": "document", "path": kappa})["provenance"]["state"] == "none"
              and refusal(console.compare, session, {"candidate": kappa, "against": prov.CHARTER_VERSION})
              == "Charter has no earlier version of this candidate recorded.",
              "with no baseline, Read says so and there is nothing to compare with")
        governing = console.preview(session, {"source": "document", "path": "authoritative/a.md"})
        check("provenance" not in governing, "a governing document has no provenance line")


def case_mark_as_seen() -> None:
    print("\nMark as seen makes the text the person read the baseline, and changes nothing else")
    with isolated_private_state():
        folder = context()
        cs = cs_of(folder)
        kappa = add(folder, "Kappa")
        lam = add(folder, "Lambda")
        ctx = changeset.Ctx(folder)
        draft = changeset.create(ctx, start={"candidate": lam, "decision": "govern-alongside"})
        edit_by_hand(cs, kappa)
        session = console.Session(folder)
        read_sha = console.preview(session, {"source": "document", "path": kappa})["provenance"]["sha"]
        world = {"context": snapshot(folder), "candidate": cs.read_candidate(kappa),
                 "draft": changeset.load(ctx, draft["id"]),
                 "recent": ps.PrivateState.default().recent_contexts()}
        edit_by_hand(cs, kappa, "\nAnd once more.\n")
        check("changed after you read it" in refusal_stale(
            console.mark_candidate_seen, session, {"candidate": kappa, "sha": read_sha}),
            "text changed since it was read: refused, so only what was read is ever marked")
        check(prov.read(cs, kappa)["event"] == "created", "and the baseline is unchanged")
        read_sha = console.preview(session, {"source": "document", "path": kappa})["provenance"]["sha"]
        world["candidate"] = cs.read_candidate(kappa)
        result = console.mark_candidate_seen(session, {"candidate": kappa, "sha": read_sha})
        base = prov.read(cs, kappa)
        check(result == {"seen": True, "changed": True} and base["event"] == prov.SEEN
              and base["date"] == today() and base["text"] == cs.read_candidate(kappa),
              "it becomes the baseline, recorded as marked as seen, today")
        check(entries(folder)[kappa]["provenance"] == {"state": "matching", "event": "marked as seen",
                                                        "date": today()},
              "so the candidate matches again, and Read says it was last marked as seen")
        check(snapshot(folder) == world["context"] and cs.read_candidate(kappa) == world["candidate"]
              and changeset.load(ctx, draft["id"]) == world["draft"]
              and ps.PrivateState.default().recent_contexts() == world["recent"],
              "no candidate text, governing context, change set or Recent entry changed")
        check(os.listdir(cs.path(ps.BASELINES)).count(ps.candidate_name(kappa) + ".json") == 1
              and sorted(os.listdir(cs.path(ps.BASELINES))) == sorted(
                  ps.candidate_name(c) + ".json" for c in (kappa, lam)),
              "and no earlier baseline is kept")
        again = console.mark_candidate_seen(session, {"candidate": kappa, "sha": read_sha})
        check(again == {"seen": True, "changed": False}, "marking a matching candidate writes nothing")
        with open(cs.candidate_file(lam), "wb") as fh:
            fh.write(b"\xff not text")
        check(refusal(console.mark_candidate_seen, session, {"candidate": lam, "sha": "0" * 64})
              == au.UNREADABLE_CANDIDATE and prov.read(cs, lam)["event"] == "created",
              "an unreadable candidate cannot be marked, and its baseline is left as it was")
        check(refusal(console.mark_candidate_seen, session, {"candidate": "authority-candidates/no.md",
                                                             "sha": "0" * 64})
              == "There is no such authority candidate.", "nor can a candidate that does not exist")


def refusal_stale(fn, *args) -> str:
    try:
        fn(*args)
    except console.ApiError as exc:
        return str(exc)
    return ""


def case_change_set_warning() -> None:
    print("\nA change set using a changed candidate warns, by title, and still applies")
    with isolated_private_state():
        folder = context()
        cs = cs_of(folder)
        kappa = add(folder, "Kappa")
        lam = add(folder, "Lambda")
        ctx = changeset.Ctx(folder)
        draft = changeset.create(ctx, start={"candidate": kappa, "decision": "govern-alongside"})
        draft = changeset.update(ctx, draft["id"], draft["revision"], {
            "candidates": [kappa, lam],
            "decisions": {kappa: {"decision": "govern-alongside"},
                          lam: {"decision": "replace", "target": "authoritative/b.md"}}})
        request = {"draft_id": draft["id"], "draft_revision": draft["revision"]}
        check(not au.plan(folder, "changeset", request).notes, "with nothing changed outside, no warning")
        edit_by_hand(cs, lam, "\nLAMBDA-HAND-EDIT\n")
        draft = changeset.refresh(ctx, draft["id"])["draft"]
        request = {"draft_id": draft["id"], "draft_revision": draft["revision"]}
        plan = au.plan(folder, "changeset", request)
        check(plan.notes == [au.changed_outside_note("Lambda")] and not plan.blocked,
              "the changed candidate is named in one warning, and the plan is not blocked")
        check(plan.to_json()["attention"] == plan.to_json()["notes"],
              "  marked advisory, for the non-blocking attention treatment of its candidate chip")
        resulting = next(c.new for c in plan.changes if c.path == "authoritative/b.md")
        check("LAMBDA-HAND-EDIT" in resulting, "the preview shows its current text, which is what applies")
        au.apply(folder, "changeset", request, plan.plan_id, au.CONFIRM_PHRASE)
        check("LAMBDA-HAND-EDIT" in ac.read_text(folder, "authoritative/b.md") and ac.examine(folder).valid
              and not os.path.exists(record_file(cs, lam)) and not os.path.exists(record_file(cs, kappa)),
              "it applies, and both candidates' baselines are discarded with them")


def case_rollback() -> None:
    print("\nA rolled-back action leaves the baseline exactly as it was")
    with isolated_private_state():
        folder = context()
        cs = cs_of(folder)
        kappa = add(folder, "Kappa")
        record_before = open(record_file(cs, kappa), "rb").read()
        text_before = cs.read_candidate(kappa)
        step = f"replace:{prov.record_path(kappa)}"

        def fault(name):
            if name == step:
                raise Crash()
        try:
            apply(folder, "edit-candidate", {"candidate": kappa, "body": "# Kappa\n\nNot kept.\n"}, fault=fault)
        except Crash:
            pass
        au.recover(folder)
        check(cs.read_candidate(kappa) == text_before and open(record_file(cs, kappa), "rb").read()
              == record_before and prov.state(cs, kappa, cs.read_candidate(kappa))["state"] == "matching",
              "an edit interrupted while writing the baseline: candidate and baseline both restored")
        step = f"replace:{ps.CANDIDATES}/{ps.candidate_name(kappa)}"
        try:
            apply(folder, "retire", {"candidate": kappa}, fault=fault)
        except Crash:
            pass
        au.recover(folder)
        check(kappa in cs.candidates() and open(record_file(cs, kappa), "rb").read() == record_before,
              "a retirement interrupted: the candidate and its baseline are both still there")


def case_orphan_and_privacy() -> None:
    print("\nA baseline is never shown without its candidate, and never reaches an agent")
    with isolated_private_state() as root:
        folder = context()
        cs = cs_of(folder)
        kappa = add(folder, "Kappa", body=f"# Kappa\n\n{MARKER}\n")
        lam = add(folder, "Lambda")
        os.remove(cs.candidate_file(lam))
        check(lam not in entries(folder) and os.path.exists(record_file(cs, lam)),
              "a candidate removed by hand: its baseline is never shown")
        add(folder, "Mu")
        check(not os.path.exists(record_file(cs, lam)), "and the next Charter action discards it")
        edit_by_hand(cs, kappa, f"\n{MARKER}-EDITED\n")
        recent = ps.PrivateState.default().recent_contexts()  # the console opened it, as a person does
        session = Session(folder, record=True)
        replies = [session.call("get_context"), session.call("list_governing_documents"),
                   session.call("get_document", {"document": "authoritative/a.md"})]
        outputs = [read.result(["--context", folder])[0], read.result(["--context", folder, "--list"])[0]]
        told = json.dumps(replies) + b"".join(outputs).decode("utf-8")
        check(MARKER not in told and ps.BASELINES not in told and "Charter's version" not in told,
              "MCP and `charter read` serve no candidate or baseline text")
        check(not any(ps.BASELINES in p or MARKER.encode() in (v or b"") for p, v in snapshot(folder).items()),
              "nothing of it is in the Agent Context folder")
        activity = ""
        for d, _dirs, names in os.walk(cs.base):
            for n in names:
                if "activity" in d or "activity" in n:
                    activity += open(os.path.join(d, n), encoding="utf-8", errors="replace").read()
        check(MARKER not in activity and ps.BASELINES not in activity, "nor in activity")
        console.compare(console.Session(folder), {"candidate": kappa, "against": prov.CHARTER_VERSION})
        check(ps.PrivateState.default().recent_contexts() == recent
              and not any(ps.BASELINES in r for r in recent),
              "nor is anything added to Recent by agents reading or a person comparing")
        with open(record_file(cs, kappa), "w", encoding="utf-8") as fh:
            fh.write("not a baseline")
        exam = ac.examine(folder)
        check(exam.valid and entries(folder)[kappa]["provenance"]["state"] == "none",
              "a baseline Charter cannot read is no baseline, and never touches the context's validity")
        check(ps._default_root() == root, "all of it ran against isolated private state")


_MISSING = object()


def malformed_records(day: str) -> list:
    """(what is wrong, the record's bytes): every way a baseline record can fail
    to be exactly one Charter wrote."""
    good = {"version": prov.RECORD_VERSION, "event": prov.CREATED, "date": day, "text": "# Kappa\n"}

    def rec(**changes) -> bytes:
        d = dict(good)
        for k, v in changes.items():
            if v is _MISSING:
                d.pop(k)
            else:
                d[k] = v
        return json.dumps(d).encode("utf-8")
    deep = 200000
    cases = [
        ("the review's record: an event that is a list", rec(event=[], text="x")),
        ("not JSON", b"not a baseline"),
        ("JSON cut short", rec()[:-7]),
        ("an empty file", b""),
        ("not UTF-8", rec(text="café").replace("\\u00e9".encode(), b"\xff")),
        ("a byte-order mark before it", b"\xef\xbb\xbf" + rec()),
        ("JSON nested past any parser's depth", b"[" * deep + b"]" * deep),
        ("a field nested past any parser's depth",
         rec()[:-1] + b', "deep": ' + b"[" * deep + b"]" * deep + b"}"),
        ("a repeated key", rec()[:-1] + b', "event": "created"}'),
        ("an extra field", rec(note="extra")),
        ("a lone surrogate in its text", rec(text="\ud800")),
    ]
    for top in ([], {}, "text", 1, None, True):
        cases.append((f"{json.dumps(top)} rather than an object", json.dumps(top).encode()))
    for field in ("version", "event", "date", "text"):
        cases.append((f"no `{field}`", rec(**{field: _MISSING})))
    wrong = {"version": [[], {}, "1", 1.0, True, None, 0, 2],
             "event": [[], {}, 1, None, True, "", "Created", "unknown", ["created"]],
             "date": [[], {}, 20261021, None, True, "", "21-10-2026", "2026-13-01", "2026-02-30",
                      "２０２６-10-21", day + "\n", day + "T00:00:00"],
             "text": [[], {}, 1, None, True, ["# Kappa\n"]]}
    for field, values in wrong.items():
        for value in values:
            cases.append((f"`{field}` {json.dumps(value)}", rec(**{field: value})))
    return cases


def case_malformed_baselines() -> None:
    print("\nA baseline record that is not one Charter wrote is no baseline, and stops nothing")
    with isolated_private_state():
        folder = context()
        cs = cs_of(folder)
        kappa = add(folder, "Kappa")
        lam = add(folder, "Lambda")
        edit_by_hand(cs, lam)  # an unrelated candidate, with a valid baseline, changed
        ctx = changeset.Ctx(folder)
        draft = changeset.create(ctx, start={"candidate": kappa, "decision": "govern-alongside"})
        request = {"draft_id": draft["id"], "draft_revision": draft["revision"]}
        session = console.Session(folder)
        record = record_file(cs, kappa)
        none = {"state": "none", "event": "", "date": ""}
        cases = malformed_records(today())
        failed = []
        for label, data in cases:
            with open(record, "wb") as fh:
                fh.write(data)
            before = private_files(cs)
            try:
                listed = entries(folder)  # the console's whole state, as the page asks for it
                shown = console.preview(session, {"source": "document", "path": kappa})["provenance"]
                compared = refusal(console.compare, session, {"candidate": kappa, "against": prov.CHARTER_VERSION})
                seen = console.mark_candidate_seen(session, {"candidate": kappa, "sha": shown["sha"]})
                planned = au.plan(folder, "changeset", request)
                ok = (prov.read(cs, kappa) is None and listed[kappa]["provenance"] == none
                      and listed[lam]["provenance"]["state"] == "changed"
                      and dict(shown, sha=None) == dict(none, sha=None)
                      and compared == "Charter has no earlier version of this candidate recorded."
                      and seen == {"seen": True, "changed": False}
                      and not planned.blocked and not planned.notes
                      and mg.check(folder, git=False)["agents_served"]
                      and private_files(cs) == before)
            except Exception as exc:  # noqa: BLE001 — reported as this case's failure
                ok, label = False, f"{label} ({type(exc).__name__}: {str(exc)[:80]})"
            if not ok:
                failed.append(label)
        check(not failed, f"each of {len(cases)} malformed records is no baseline: console state, Read, Compare, "
                          "Mark as seen, a change set and agent access all work, and viewing writes nothing"
                          + (f" — failed: {failed}" if failed else ""))

        print("\n  records that are not regular files, or too large")
        valid = prov.render(cs.read_candidate(kappa), prov.CREATED, today())
        with open(record, "w", encoding="utf-8", newline="") as fh:
            fh.write(valid)
        check(prov.read(cs, kappa) is not None, "(a valid record reads as a baseline)")
        real = prov.MAX_RECORD_BYTES
        prov.MAX_RECORD_BYTES = len(valid.encode("utf-8")) - 1
        try:
            check(prov.read(cs, kappa) is None and entries(folder)[kappa]["provenance"] == none,
                  "a record larger than any Charter writes is not read: no baseline")
        finally:
            prov.MAX_RECORD_BYTES = real
        os.remove(record)
        os.mkdir(record)
        before = private_files(cs)
        check(prov.read(cs, kappa) is None and entries(folder)[kappa]["provenance"] == none
              and os.path.isdir(record) and private_files(cs) == before,
              "a folder where the record should be: no baseline, and left as it is")
        os.rmdir(record)
        elsewhere = os.path.join(cs.base, "elsewhere.json")
        with open(elsewhere, "w", encoding="utf-8", newline="") as fh:
            fh.write(valid)
        try:
            os.symlink(elsewhere, record)
            linked = True
        except (OSError, NotImplementedError):
            linked = False
        if linked:
            check(prov.read(cs, kappa) is None and entries(folder)[kappa]["provenance"] == none
                  and os.path.islink(record), "a link to a valid record is not followed: no baseline")
            os.remove(record)
        else:
            print("  SKIPPED: this system does not let this account create a link, so a linked record "
                  "is not exercised here.")
        if hasattr(os, "mkfifo"):
            os.mkfifo(record)
            check(prov.read(cs, kappa) is None and entries(folder)[kappa]["provenance"] == none,
                  "a pipe where the record should be is never opened for reading: no baseline, no wait")
            os.remove(record)
        else:
            print("  SKIPPED: this system has no named pipes to put where a record should be.")
        os.remove(elsewhere)

        print("\n  Charter's own next write replaces it; nothing else does")
        with open(record, "wb") as fh:
            fh.write(cases[0][1])
        decided = au.plan(folder, "reject-proposal", {"proposal_id": file_proposal(folder, {
            "agent": "a", "operation": "create", "target_path": "authority-candidates/new.md",
            "reason": "R.", "proposed_body": "# New\n"})})
        au.apply(folder, "reject-proposal", decided.request, decided.plan_id, True)
        check(open(record, "rb").read() == cases[0][1],
              "an unrelated action, here rejecting a proposal, leaves the record exactly as it was")
        apply(folder, "edit-candidate", {"candidate": kappa, "title": "Kappa", "scope": "Kappa scope.",
                                         "body": "# Kappa\n\nEdited in Charter.\n"})
        base = prov.read(cs, kappa)
        check(base is not None and base["event"] == prov.EDITED and base["text"] == cs.read_candidate(kappa)
              and entries(folder)[kappa]["provenance"]["state"] == "matching",
              "editing the candidate in Charter writes a new baseline, as every Charter write does")


def case_valid_baselines_exact() -> None:
    print("\nA record Charter wrote reads exactly as before")
    with isolated_private_state():
        folder = context()
        cs = cs_of(folder)
        kappa = add(folder, "Kappa")
        text = cs.read_candidate(kappa)
        record = record_file(cs, kappa)
        for event, label in prov.EVENT_LABELS.items():
            with open(record, "w", encoding="utf-8", newline="") as fh:
                fh.write(prov.render(text.replace("\n", "\r\n"), event, "2026-01-31"))
            base = prov.read(cs, kappa)
            listed = entries(folder)[kappa]["provenance"]
            check(base == {"text": text, "event": event, "date": "2026-01-31"}
                  and listed == {"state": "matching", "event": label, "date": "2026-01-31"},
                  f"`{event}`: its text line-ending-normalized, read as “{label}” on its date, and matching")
        with open(record, "w", encoding="utf-8", newline="") as fh:
            fh.write(prov.render("# Earlier\n", prov.SEEN, "2024-02-29"))
        check(entries(folder)[kappa]["provenance"] == {"state": "changed", "event": "marked as seen",
                                                       "date": "2024-02-29"},
              "a leap day is a date; a record of other text is changed")


def main() -> None:
    case_lifecycle()
    case_states()
    case_read_and_compare()
    case_mark_as_seen()
    case_change_set_warning()
    case_rollback()
    case_orphan_and_privacy()
    case_malformed_baselines()
    case_valid_baselines_exact()
    print("\nAll candidate provenance checks passed.")


if __name__ == "__main__":
    main()
