"""Open, create, check, outside changes, Rebuild Agent Context and Settings.
Run: python -m tests.manager

Product Specification §3.1 and §3.5, Agent Context as the Project Asset §4 and
§7, UI Standards, and the Phase 4 decisions:

  * opening recovers an interrupted Charter write, validates, and says whether
    agents are served, in ordinary language;
  * a new Agent Context is created in an empty folder, never inside another;
  * an edit to a governing document leaves the context invalid until the
    person uses Rebuild Agent Context; Rebuild previews, needs ordinary
    deliberate confirmation, writes only the map and metadata, may create a
    missing metadata file after asking for the project name, and refuses
    while any document problem or stray remains;
  * after Rebuild, or any valid outside change, the context is shown as
    changed outside Charter until the person acknowledges it; with no private
    record its origin is unknown;
  * settings change the map and metadata through a previewed plan;
  * `check` changes nothing; Git information is read-only.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import authority as au  # noqa: E402
from app import manager as mg  # noqa: E402
from app import private_store as ps  # noqa: E402
from tests.agent_context import context, doc_text, generate, read, snapshot, write  # noqa: E402
from tests.harness import isolated_private_state, seeded  # noqa: E402

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


class Crash(BaseException):
    pass


def rebuild(folder: str, project_name=None) -> dict:
    p = mg.rebuild_plan(folder, project_name)
    return mg.rebuild_apply(folder, p.plan_id, True, project_name)


def case_create() -> None:
    print("\ncreating an Agent Context")
    with isolated_private_state():
        parent = tempfile.mkdtemp(prefix="charter-create-")
        folder = os.path.join(parent, "context")
        status = mg.create(folder, "Booking service")
        check(status["state"] == ac.VALID and status["agents_served"]
              and status["headline"] == mg.SERVED and status["name"] == "Booking service",
              "a new Agent Context in a new folder is valid, and agents read it")
        check(sorted(os.listdir(folder)) == [".agent-context.json", "AGENT-CONTEXT.md"],
              "it holds only the map and metadata; `authoritative/` comes with the first grant")
        check(json.loads(read(folder, ac.METADATA))["agent_guidance"] == ac.default_guidance(),
              "the guidance settings start from their defaults")
        check(not status["outside"]["changed_outside"] and status["outside"]["known"],
              "and it is not marked as changed outside")

        existing = os.path.join(parent, "repo-context")
        os.makedirs(os.path.join(existing, ".git"))
        write(existing, ".gitignore", b"")
        check(mg.create(existing, "In a repository")["agents_served"],
              "a folder holding only Git and system tooling files can be used")
        busy = os.path.join(parent, "busy")
        write(busy, "notes.txt", b"x")
        check(raises(au.ActionRefused, mg.create, busy, "Busy") and
              sorted(os.listdir(busy)) == ["notes.txt"],
              "a folder with other content is refused, and left alone")
        check(raises(au.ActionRefused, mg.create, os.path.join(folder, "authoritative", "inner"),
                     "Inner"), "a folder inside another Agent Context is refused")
        check(raises(au.ActionRefused, mg.create, os.path.join(parent, "x"), " "),
              "an empty project name is refused")
        check(raises(au.ActionRefused, mg.create, os.path.join(parent, "no", "such"), "X"),
              "a folder whose parent does not exist is refused")
        shutil.rmtree(parent)


def case_open() -> None:
    print("\nopening an Agent Context")
    with isolated_private_state() as root:
        folder = context()
        status = mg.open_context(folder)
        check(status["agents_served"] and status["headline"] == mg.SERVED
              and [d["path"] for d in status["governing"]] == ["authoritative/a.md",
                                                               "authoritative/b.md"],
              "a valid folder opens, serving agents, with its governing documents")
        check(not status["outside"]["known"] and "origin of its current content is unknown"
              in status["outside"]["message"],
              "a context this computer has no record of is of unknown origin")
        check(status["agents_served"] and not status["outside"]["changed_outside"]
              and not status["outside"]["paths"] and not status["rebuild"]["available"]
              and status["state"] == "valid",
              "and that alone is not a change outside Charter, not invalid, and needs no Rebuild")

        cand = au.plan(folder, "add", {"title": "Gamma", "body": "x\n"})
        au.apply(folder, "add", cand.request, cand.plan_id, True)
        req = seeded(folder, {"alongside": "authority-candidates/gamma.md"})
        p = au.plan(folder, "changeset", req)
        try:
            au.apply(folder, "changeset", req, p.plan_id, PHRASE,
                     fault=lambda n: (_ for _ in ()).throw(Crash())
                     if n == "replace:AGENT-CONTEXT.md" else None)
        except Crash:
            pass
        checked = mg.check(folder)
        check(checked["interrupted"] and not checked["agents_served"]
              and "interrupted" in checked["headline"]
              and (checked["headline_title"], checked["headline_detail"]) == mg.INTERRUPTED
              and checked["headline_title"] == "Charter can’t serve this Agent Context yet"
              and checked["headline_detail"] == ("A Charter write to this folder was interrupted. Open the "
                                                 "Agent Context in Charter to recover it."),
              "an interrupted write is reported, in plain words, and agents are refused")
        status = mg.open_context(folder)
        check(status["recovered"] and status["agents_served"] and not status["interrupted"],
              "opening recovers it, and agents are served again")

        write(folder, "drafts/idea.md", b"# idea\n")
        status = mg.open_context(folder)
        check(not status["agents_served"] and status["strays"] == ["drafts/"]
              and "leaves them untouched" in status["headline"],
              "a stray is named, agents are refused, and the stray is left alone")
        stray = [i for i in status["issues"] if i["path"] == "drafts/"][0]
        check(status["headline_title"] == "Charter can’t serve this Agent Context yet"
              and status["headline_detail"] == ("This folder contains files that are not part of the Agent "
                                                "Context. Charter leaves them untouched.")
              and status["headline"] == status["headline_title"] + ". " + status["headline_detail"]
              and stray["message"] == "isn’t part of this Agent Context."
              and stray["fix"] == "Move it out of the context folder or delete it, then try again."
              and "Agents are refused" not in status["headline"],
              "in plain words: Charter can’t serve it yet, why, and for the file, what to do")
        shutil.rmtree(os.path.join(folder, "drafts"))
        check(raises(au.ActionRefused, mg.open_context, os.path.join(folder, "missing")),
              "a folder that does not exist cannot be opened")
        shutil.rmtree(folder)
        del root


def case_outside_edit_and_rebuild() -> None:
    print("\nan ordinary edit, then Rebuild Agent Context")
    with isolated_private_state():
        folder = context()
        mg.open_context(folder)
        cs = ps.PrivateState.default().for_context(folder)
        exam = ac.examine(folder)
        cs.record_observed(exam.fingerprint, exam.hashes, "charter", [])

        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited in an editor.\n"))
        status = mg.open_context(folder)
        check(status["state"] == ac.INVALID and not status["agents_served"],
              "an edited governing document leaves the context invalid: agents are refused")
        check(status["rebuild"]["available"] and "Rebuild Agent Context" in status["headline"]
              and status["headline_title"] == mg.NOT_YET
              and status["headline_detail"] == ("The map and metadata don’t match the governing documents. "
                                                "Check that the documents are what you intend, then use "
                                                "Rebuild Agent Context."),
              "and Rebuild Agent Context is offered, the mismatch said plainly")
        check(status["outside"]["paths"] == ["authoritative/a.md"],
              "the edited document is named as changed outside Charter")

        before = snapshot(folder)
        p = mg.rebuild_plan(folder)
        check(not p.blocked and not p.governing_change and p.confirm_phrase == "",
              "Rebuild needs ordinary confirmation, not the typed phrase")
        check({c.label for c in p.changes} == {".agent-context.json"} and
              all(c.diff() for c in p.changes),
              "its preview shows each generated file it rewrites, with a diff")
        check(any("authoritative/a.md" in n and "changed outside" in n for n in p.notes),
              "and says the edited document stays marked as changed outside")
        check(raises(au.ActionRefused, mg.rebuild_apply, folder, p.plan_id, PHRASE) and
              raises(au.ActionRefused, mg.rebuild_apply, folder, p.plan_id, None) and
              snapshot(folder) == before, "it needs a deliberate confirmation")
        status = mg.rebuild_apply(folder, p.plan_id, True)
        check(status["agents_served"] and status["outside"]["changed_outside"]
              and status["outside"]["rebuilt"]
              and status["outside"]["paths"] == ["authoritative/a.md"],
              "after Rebuild it is valid, and shown as changed outside Charter")
        changed = {k for k in snapshot(folder) if snapshot(folder)[k] != before.get(k)}
        check(changed == {".agent-context.json"},
              "Rebuild wrote only the generated files; the edited document is as it was")

        logical = "authority-candidates/new.md"
        a = au.plan(folder, "add", {"title": "New", "body": "x\n"})
        au.apply(folder, "add", a.request, a.plan_id, True)
        g = au.plan(folder, "changeset", seeded(folder, {"alongside": logical}))
        au.apply(folder, "changeset", g.request, g.plan_id, PHRASE)
        status = mg.check(folder)
        check(status["outside"]["paths"] == ["authoritative/a.md"],
              "a later Charter action keeps the unacknowledged outside change visible")
        status = mg.acknowledge(folder)
        check(not status["outside"]["changed_outside"] and status["outside"]["message"] == "",
              "until the person acknowledges it")
        shutil.rmtree(folder)


def case_plain_refusals() -> None:
    print("\nwhy agents are not served, in plain words: a heading, then what it means and what to do")
    with isolated_private_state():
        folder = context()
        write(folder, "authoritative/a.md", b"no front matter\n")
        status = mg.check(folder, git=False)
        check(not status["agents_served"] and status["state"] == ac.INVALID
              and (status["headline_title"], status["headline_detail"]) == mg.NOT_VALID
              and status["headline_detail"] == ("Something in this folder isn’t valid. Each problem, and how "
                                                "to fix it, is listed below."),
              "a document problem nothing can rebuild past: the problems are listed below")
        check(status["headline"] == status["headline_title"] + ". " + status["headline_detail"],
              "`charter check` and Connect agents get the heading and its detail as one line")
        shutil.rmtree(folder)
    every = [mg.INTERRUPTED, mg.PRIVATE_UNUSABLE, mg.CHARTER_OUTDATED, mg.LEGACY, mg.MAP_OUTDATED,
             mg.MISMATCH, mg.NOT_VALID, (mg.STRAY_TITLE, mg.STRAY_DETAIL)]
    check(not any("Agents are refused" in t + d or "Agents are not served" in t + d for t, d in every)
          and "Agents are refused" not in ac.MAP_OUTDATED + ac.LEGACY_MAP,
          "no status, or the map's own messages, says “Agents are refused” any more")


def case_map_format_updates() -> None:
    print("\nafter an update: an older map is rebuilt, quietly; a newer one is never written")
    from tests.agent_context import with_map_format
    with isolated_private_state():
        folder = context()
        mg.open_context(folder)
        with_map_format(folder, 1)
        cs = ps.PrivateState.default().for_context(folder)
        # As this computer last saw it, before the update: Charter's own map.
        exam = ac.examine(folder)
        cs.record_observed(ac.context_fingerprint(exam.hashes), exam.hashes, "charter", [])
        status = mg.open_context(folder)
        check(not status["agents_served"] and "out of date" in status["headline"]
              and status["headline_title"] == "This Agent Context’s map is out of date"
              and status["headline_detail"].startswith("An earlier version of Charter generated it, so Charter "
                                                       "can’t serve the context until it’s rebuilt.")
              and status["rebuild"]["available"] and not status["outside"]["changed_outside"],
              "an older map format is out of date: Rebuild is offered, and nothing is called an outside change")
        documents = {k: v for k, v in snapshot(folder).items() if k.startswith("authoritative/")}
        p = mg.rebuild_plan(folder)
        status = mg.rebuild_apply(folder, p.plan_id, True)
        check(status["agents_served"] and not status["outside"]["changed_outside"]
              and status["outside"]["message"] == ""
              and {k: v for k, v in snapshot(folder).items() if k.startswith("authoritative/")} == documents,
              "after Rebuild it is served, and Charter recognizes its own output: no false outside-change notice")
        check(not mg.check(folder)["outside"]["changed_outside"], "nor on a later check")

        # A document edited outside Charter is still news after a Rebuild.
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited in an editor.\n"))
        p = mg.rebuild_plan(folder)
        status = mg.rebuild_apply(folder, p.plan_id, True)
        check(status["agents_served"] and status["outside"]["changed_outside"]
              and status["outside"]["paths"] == ["authoritative/a.md"]
              and ac.CONTEXT_MAP not in status["outside"]["paths"],
              "a document changed outside Charter is still named after a Rebuild; Charter's own files are not")

        with_map_format(folder, 3)
        before = snapshot(folder)
        status = mg.open_context(folder)
        check(not status["agents_served"] and "newer version of Charter" in status["headline"]
              and "not at fault" in status["headline"] and not status["rebuild"]["available"]
              and status["headline_title"] == "This copy of Charter is out of date"
              and status["headline_detail"].startswith("A newer version of Charter generated this Agent "
                                                       "Context, so this copy can’t check or serve it."),
              "a newer map format: this copy is out of date, the context is not at fault, and no Rebuild is offered")
        p = mg.rebuild_plan(folder)
        check(p.blocked and raises(au.ActionRefused, mg.rebuild_apply, folder, p.plan_id, True),
              "Rebuild is refused outright")
        check(raises(au.ActionRefused, mg.settings_plan, folder, project_name="Other")
              and snapshot(folder) == before, "and so is every other write: the folder is untouched")
        shutil.rmtree(folder)


def as_earlier_name(folder: str) -> None:
    """Make a valid Agent Context's map and metadata exactly what Agent Context
    Manager, Charter's earlier name, generated for it, and record that, as
    Agent Context Manager did, under the earlier name."""
    exam = ac.examine(folder)
    legacy = ac.render_legacy_map(exam.settings, exam.documents)
    hashes = dict(exam.hashes, **{ac.CONTEXT_MAP: ac.sha256_text(legacy)})
    write(folder, ac.CONTEXT_MAP, legacy.encode("utf-8"))
    write(folder, ac.METADATA, ac.render_metadata(exam.settings, hashes).encode("utf-8"))
    cs = ps.PrivateState.default().for_context(folder)
    cs.record_observed(ac.context_fingerprint(hashes), hashes, "acm", [])


def case_earlier_name_map() -> None:
    print("\na map generated by Agent Context Manager, Charter's earlier name")
    from app import mcp
    with isolated_private_state():
        folder = context()
        mg.open_context(folder)
        documents = {k: v for k, v in snapshot(folder).items() if k.startswith("authoritative/")}
        as_earlier_name(folder)
        check(b"Generated by Agent Context Manager" in read(folder, ac.CONTEXT_MAP)
              and b"\nacm propose --context .\n" in read(folder, ac.CONTEXT_MAP),
              "the fixture is the earlier map: the earlier product, and its `acm` command")
        before = snapshot(folder)
        exam = ac.examine(folder)
        check(exam.state == ac.INVALID and exam.legacy_map
              and [i["message"] for i in exam.errors] == [ac.LEGACY_MAP],
              "it is not valid, for exactly one reason: the earlier name generated the map")
        status = mg.open_context(folder)
        check(not status["agents_served"] and "Charter’s earlier name" in status["headline"]
              and status["headline_title"] == mg.NOT_YET
              and "governing documents are unchanged" in status["headline"]
              and status["rebuild"]["available"] and not status["rebuild"]["blockers"],
              "agents are refused, the person is told why in words, and Rebuild is offered")
        try:
            mcp.examine(folder)
            refusal = ""
        except mcp.Refusal as exc:
            refusal = exc.reason
        check(refusal == "context-invalid", "MCP fails closed: `context-invalid`, as for any stale map")
        mg.check(folder, git=False)
        mg.open_context(folder)
        check(snapshot(folder) == before, "checking and opening it rewrite nothing: it is never "
                                          "regenerated silently")

        p = mg.rebuild_plan(folder)
        check(not p.blocked and {c.label for c in p.changes} == {ac.CONTEXT_MAP, ac.METADATA}
              and all(c.diff() for c in p.changes),
              "Rebuild's preview rewrites only AGENT-CONTEXT.md and .agent-context.json, with diffs")
        check(any("Charter's earlier name" in n for n in p.notes),
              "and says why: the earlier name generated the map")
        check(raises(au.ActionRefused, mg.rebuild_apply, folder, p.plan_id, None)
              and snapshot(folder) == before, "it waits for a deliberate confirmation")
        status = mg.rebuild_apply(folder, p.plan_id, True)
        after = snapshot(folder)
        changed = {k for k in after if after[k] != before.get(k)}
        check(status["agents_served"] and changed == {ac.CONTEXT_MAP, ac.METADATA}
              and {k: v for k, v in after.items() if k.startswith("authoritative/")} == documents,
              "after Rebuild agents are served; only the two generated files changed")
        check(b"Generated by Charter" in after[ac.CONTEXT_MAP]
              and b"\ncharter propose --context .\n" in after[ac.CONTEXT_MAP]
              and b"Agent Context Manager" not in after[ac.CONTEXT_MAP]
              and b"acm propose" not in after[ac.CONTEXT_MAP],
              "the new map names Charter and `charter propose`, and nothing of the earlier name")
        check(not status["outside"]["changed_outside"]
              and ps.PrivateState.default().for_context(folder).observed()["source"] == "charter",
              "regenerating only the earlier name's wording is Charter's own write, not a change "
              "made outside")
        shutil.rmtree(folder)

    with isolated_private_state():
        folder = context()
        mg.open_context(folder)
        as_earlier_name(folder)
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited in an editor.\n"))
        exam = ac.examine(folder)
        status = mg.check(folder, git=False)
        check(not exam.legacy_map and len(exam.errors) > 1
              and "earlier name" not in status["headline"]
              and status["headline_title"] == mg.NOT_YET
              and status["headline_detail"] in (mg.MISMATCH[1], mg.NOT_VALID[1]),
              "with a document also edited, it is not only an earlier-name map: the ordinary "
              "headline, every problem listed")
        shutil.rmtree(folder)


def case_rebuild_refusals() -> None:
    print("\nwhat Rebuild refuses")
    with isolated_private_state():
        folder = context()
        check(mg.rebuild_plan(folder).blocked and
              any("nothing to rebuild" in m for m in mg.rebuild_plan(folder).problems),
              "a valid context has nothing to rebuild")
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited.\n"))
        write(folder, "scratch.txt", b"mine")
        before = snapshot(folder)
        p = mg.rebuild_plan(folder)
        check(p.blocked and any("scratch.txt" in m for m in p.problems),
              "a stray blocks Rebuild, named")
        check(raises(au.ActionRefused, mg.rebuild_apply, folder, p.plan_id, True)
              and snapshot(folder) == before, "and nothing is written, the stray included")
        os.remove(os.path.join(folder, "scratch.txt"))
        write(folder, "authoritative/b.md",
              doc_text("b", "Beta", body="<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> topic\n"))
        p = mg.rebuild_plan(folder)
        check(p.blocked and any("conflict" in m for m in p.problems),
              "a merge conflict in a governing document blocks Rebuild")
        write(folder, "authoritative/b.md", doc_text("b", "Beta", authority="non-authoritative"))
        check(mg.rebuild_plan(folder).blocked,
              "so does a document whose metadata says it does not govern")
        write(folder, "authoritative/b.md", doc_text("b", "Beta"))
        p = mg.rebuild_plan(folder)
        cs = ps.PrivateState.default().for_context(folder)
        cs.record_observed("x" * 64, {}, "seen", [])
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited again.\n"))
        check(raises(au.StalePlan, mg.rebuild_apply, folder, p.plan_id, True),
              "a document edited after the preview makes it stale")
        shutil.rmtree(folder)


def case_rebuild_generated_damage() -> None:
    print("\nRebuild replaces damaged or missing generated files")
    with isolated_private_state():
        folder = context(guidance={"review_newly_discovered_material": True})
        text = read(folder, ac.CONTEXT_MAP).decode()
        write(folder, ac.CONTEXT_MAP, "<<<<<<< HEAD\n" + text + "=======\nother\n>>>>>>> b\n")
        check(rebuild(folder)["agents_served"], "a conflicted map is regenerated")

        os.remove(os.path.join(folder, ac.CONTEXT_MAP))
        check(rebuild(folder)["agents_served"], "a missing map is regenerated")

        remembered = {"project_name": "Test project",
                      "agent_guidance": dict(ac.default_guidance(),
                                             review_newly_discovered_material=True)}
        os.remove(os.path.join(folder, ac.METADATA))
        p = mg.rebuild_plan(folder)
        offer = p.settings_proposal
        check(p.blocked and offer["source"] == "last-known" and offer["label"] == mg.LAST_KNOWN
              and {k: offer[k] for k in remembered} == remembered,
              "a lost metadata file: the preview offers the settings last known on this computer")
        check(any("Confirm or change" in m for m in p.problems),
              "and Rebuild waits for the person to confirm or change them")
        check(raises(au.ActionRefused, mg.rebuild_apply, folder, p.plan_id, True),
              "they are never reused silently")
        check(mg.rebuild_plan(folder, "Test project", {"context_check_in": True}).blocked,
              "every guidance setting must be given")
        check(mg.rebuild_plan(folder, " ", remembered["agent_guidance"]).blocked,
              "and an empty project name is refused")
        p = mg.rebuild_plan(folder, **remembered)
        check(not p.blocked and any("as offered (Last known on this computer.), confirmed by you"
                                    in n for n in p.notes), "confirming them is noted")
        status = mg.rebuild_apply(folder, p.plan_id, True, **remembered)
        meta = json.loads(read(folder, ac.METADATA))
        check(status["agents_served"] and meta["project_name"] == "Test project"
              and meta["agent_guidance"] == remembered["agent_guidance"],
              "and the rebuilt context has the confirmed settings")

        text = read(folder, ac.METADATA).decode()
        write(folder, ac.METADATA, "<<<<<<< HEAD\n" + text + "=======\n{}\n>>>>>>> other\n")
        p = mg.rebuild_plan(folder)
        check(p.settings_proposal["source"] == "last-known",
              "a metadata merge conflict offers the last known settings too")
        changed = {"project_name": "Renamed in rebuild",
                   "agent_guidance": ac.default_guidance()}
        p = mg.rebuild_plan(folder, **changed)
        check(any(n == "Settings: as you chose them." for n in p.notes),
              "the person may change them instead")
        mg.rebuild_apply(folder, p.plan_id, True, **changed)
        meta = json.loads(read(folder, ac.METADATA))
        check(meta["project_name"] == "Renamed in rebuild"
              and meta["agent_guidance"] == ac.default_guidance(), "and their choice is used")
        check(mg.rebuild_plan(folder, "Other name", ac.default_guidance()).blocked,
              "with readable metadata, settings are not changed through Rebuild")
        shutil.rmtree(folder)

    with isolated_private_state():
        empty = tempfile.mkdtemp(prefix="charter-adopt-")
        write(empty, "authoritative/policy.md", doc_text("policy", "Policy"))
        p = mg.rebuild_plan(empty)
        offer = p.settings_proposal
        check(offer["source"] == "defaults" and offer["project_name"] == ""
              and offer["agent_guidance"] == ac.default_guidance()
              and "being initialized" in offer["label"],
              "with no private record, the defaults are offered and settings are initialized")
        check(p.blocked, "and the person must still name the project and confirm them")
        p = mg.rebuild_plan(empty, "Adopted", ac.default_guidance())
        status = mg.rebuild_apply(empty, p.plan_id, True, "Adopted", ac.default_guidance())
        check(status["agents_served"] and [d["path"] for d in status["governing"]] ==
              ["authoritative/policy.md"],
              "governing documents placed in a folder become an Agent Context through Rebuild")
        shutil.rmtree(empty)


def case_settings() -> None:
    print("\nsettings")
    with isolated_private_state():
        folder = context()
        p = mg.settings_plan(folder, agent_guidance={"proposal_context_impact_check": True})
        check(not p.blocked and p.confirm_phrase == "" and
              {c.label for c in p.changes} == {ac.CONTEXT_MAP, ac.METADATA},
              "turning on a guidance setting previews the map and metadata it rewrites")
        status = mg.settings_apply(folder, p.plan_id, True,
                                   agent_guidance={"proposal_context_impact_check": True})
        check(status["agents_served"] and status["settings"]["agent_guidance"]
              ["proposal_context_impact_check"] and "- **Assess proposal impact.**" in
              read(folder, ac.CONTEXT_MAP).decode(),
              "and the map then carries its instruction, headed by its Settings name")
        same = mg.settings_plan(folder, agent_guidance={"proposal_context_impact_check": True})
        check(same.blocked and not same.changes
              and same.problems == ["Nothing to save: these are already this Agent Context's settings."],
              "saving unchanged settings says plainly that there is nothing to save")
        check(not status["outside"]["changed_outside"], "a settings change is Charter's own")
        p = mg.settings_plan(folder, project_name="Renamed")
        mg.settings_apply(folder, p.plan_id, True, project_name="Renamed")
        check(read(folder, ac.CONTEXT_MAP).decode().startswith("# Renamed — Agent Context"),
              "the project name can be changed")
        for bad in ({"agent_guidance": {"free_text": True}}, {"project_name": "a\nb"},
                    {"agent_guidance": {"context_check_in": "yes"}}):
            check(raises(au.ActionRefused, mg.settings_plan, folder, **bad),
                  f"{bad} is refused")
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited.\n"))
        check(raises(au.ActionRefused, mg.settings_plan, folder, project_name="X"),
              "settings cannot change while the context is invalid")
        shutil.rmtree(folder)


def case_check_changes_nothing() -> None:
    print("\nchecking changes nothing")
    with isolated_private_state() as root:
        folder = context()
        before = snapshot(folder)
        status = mg.check(folder)
        check(status["agents_served"] and snapshot(folder) == before and not os.path.exists(root),
              "check reads the folder and creates no private state")
        shutil.rmtree(folder)


def case_git_read_only() -> None:
    print("\nGit information is read-only")
    with isolated_private_state():
        repo = tempfile.mkdtemp(prefix="charter-repo-")
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}

        def git(*args):
            return subprocess.run(["git", "-C", repo, *args], capture_output=True, env=env,
                                  check=True).stdout.decode().strip()
        git("init", "-q", "-b", "main")
        folder = os.path.join(repo, "context")
        mg.create(folder, "Repo context")
        git("add", "-A")
        git("commit", "-q", "-m", "context")
        git("checkout", "-q", "-b", "feature")
        write(folder, "authoritative/a.md", doc_text("a", "Alpha"))
        index = os.path.join(repo, ".git", "index")
        index_before = os.stat(index).st_mtime_ns

        calls = []
        real = subprocess.run

        def spy(args, *a, **k):
            calls.append(list(args))
            return real(args, *a, **k)
        subprocess.run = spy  # type: ignore[assignment]
        try:
            status = mg.open_context(folder)
            p = mg.rebuild_plan(folder)
            status = mg.rebuild_apply(folder, p.plan_id, True)
        finally:
            subprocess.run = real  # type: ignore[assignment]
        check(status["git"]["state"] == mg.GIT_CHECKOUT and status["git"]["branch"] == "feature",
              "the checkout's branch is shown")
        check(sorted(status["git"]["changed"]) == ["context/.agent-context.json",
                                                   "context/AGENT-CONTEXT.md",
                                                   "context/authoritative/a.md"],
              "and the context files Git reports as changed")
        subcommands = {c[c.index("-C") + 2] for c in calls if c[:1] == ["git"]}
        check(subcommands and subcommands <= set(mg.GIT_READ_ONLY),
              f"only read-only Git subcommands run ({', '.join(sorted(subcommands))})")
        check(os.stat(index).st_mtime_ns == index_before and git("rev-parse", "--abbrev-ref",
                                                                 "HEAD") == "feature"
              and git("diff", "--cached", "--name-only") == "",
              "Git's index, branch and history are untouched")
        check(raises(ValueError, mg._git, folder, "commit", "-m", "x"),
              "any other Git subcommand is refused outright")
        git("add", "-A")
        git("commit", "-q", "-m", "rebuilt")
        clean = mg.git_info(folder)
        check(clean == {"state": mg.GIT_CHECKOUT, "branch": "feature", "changed": []},
              "a checkout with no changed context files reports none: 0, known")

        def failing_status(args, *a, **k):
            if "status" in args:
                return subprocess.CompletedProcess(args, 128, b"", b"fatal")
            return real(args, *a, **k)
        subprocess.run = failing_status  # type: ignore[assignment]
        try:
            unread = mg.git_info(folder)
        finally:
            subprocess.run = real  # type: ignore[assignment]
        check(unread == {"state": mg.GIT_UNREADABLE, "branch": "feature"},
              "when Git status fails it is said to be unreadable, never as no changes")

        def no_git(args, *a, **k):
            raise FileNotFoundError("git")
        subprocess.run = no_git  # type: ignore[assignment]
        try:
            missing = mg.git_info(folder)
        finally:
            subprocess.run = real  # type: ignore[assignment]
        check(missing == {"state": mg.GIT_UNAVAILABLE}, "when Git cannot be run, Git is unavailable")

        plain = tempfile.mkdtemp(prefix="charter-plain-")
        check(mg.check(plain)["git"] == {"state": mg.GIT_NOT_CHECKOUT},
              "outside a Git checkout it says so, with no branch or changes")
        broken = os.path.join(plain, "broken")
        os.makedirs(broken)
        with open(os.path.join(broken, ".git"), "w") as fh:
            fh.write("gitdir: " + os.path.join(plain, "nowhere") + "\n")
        check(mg.git_info(broken) == {"state": mg.GIT_UNREADABLE, "branch": ""},
              "a folder Git cannot read despite its .git is unreadable, not 'not a checkout'")
        shutil.rmtree(plain)
        shutil.rmtree(repo, ignore_errors=True)


def case_git_config_cannot_run_code() -> None:
    print("\na repository's own Git config cannot run a command during check or status")
    if shutil.which("git") is None:
        print("  SKIPPED: Git is not installed.")
        return
    with isolated_private_state():
        repo = tempfile.mkdtemp(prefix="charter-repo-fsm-")
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"}

        def git(*args):
            return subprocess.run(["git", "-C", repo, *args], capture_output=True, env=env,
                                  check=True).stdout.decode().strip()
        git("init", "-q", "-b", "main")
        folder = os.path.join(repo, "context")
        mg.create(folder, "Repo context")
        git("add", "-A")
        git("commit", "-q", "-m", "context")
        # core.fsmonitor is a program Git runs while refreshing the index for
        # `status`. A folder received as an archive or synced with its `.git`
        # could carry a hostile one. Charter must never execute it.
        marker = os.path.join(repo, "fsmonitor-ran.txt").replace("\\", "/")
        probe = f'cmd /c echo ran> "{marker}"' if os.name == "nt" else f"touch '{marker}'"
        git("config", "core.fsmonitor", probe)
        if os.path.exists(marker):
            os.remove(marker)
        mg.check(folder)                       # the console's own state path consults Git
        mg.check(folder, git=False)            # the `charter check` path does not consult Git at all
        mg.open_context(folder)
        check(not os.path.exists(marker),
              "core.fsmonitor is never executed by check, open or status")
        check(mg.check(folder, git=False)["git"] is None,
              "and `charter check` reports no Git information, so it asks Git nothing")
        shutil.rmtree(repo, ignore_errors=True)


def case_read_text_helper() -> None:
    print("\none shared folder-text reader")
    with isolated_private_state():
        folder = context()
        check(ac.read_text(folder, ac.CONTEXT_MAP) is not None, "reads a context file as LF text")
        check(ac.read_text(folder, "no-such.md") is None, "a missing file reads as None")
        write(folder, "bad.bin", b"\xff\xfe\x00not utf-8")
        check(ac.read_text(folder, "bad.bin") is None,
              "invalid UTF-8 reads as None (strict), never silently replaced")
        shutil.rmtree(folder)


def case_enclosing_context_helper() -> None:
    print("\none shared enclosing-context predicate")
    with isolated_private_state():
        outer = context()  # a valid Agent Context root
        child = os.path.join(outer, "authoritative")  # inside it
        plain = tempfile.mkdtemp(prefix="charter-plain-")  # not a context
        check(ac.is_context_root(outer) and not ac.is_context_root(plain)
              and not ac.is_context_root(child),
              "is_context_root is true only for a folder that itself holds the generated files")
        check(ac.enclosing_context(child) == outer and ac.enclosing_context(outer) == ""
              and ac.enclosing_context(plain) == "",
              "enclosing_context finds the nearest ancestor context, and none for a context root or a plain folder")
        check(ac.enclosing_context(outer, include_self=True) == outer
              and ac.enclosing_context(child, include_self=True) == outer,
              "with include_self, a context root reports itself")
        shutil.rmtree(plain, ignore_errors=True)
        shutil.rmtree(outer)


def case_nested_context_refused() -> None:
    print("\na context nested inside another is refused for open and rebuild")
    with isolated_private_state():
        outer = context()  # a valid Agent Context
        nested = os.path.join(outer, "authoritative", "sub")
        os.makedirs(nested)
        check(raises(au.ActionRefused, mg.open_context, nested),
              "opening a folder inside another Agent Context is refused")
        plan = mg.rebuild_plan(nested)
        check(any("another Agent Context" in pr for pr in plan.problems) and not plan.changes,
              "and rebuilding one is blocked with no writes, so it cannot take the enclosing context offline")
        check(not os.path.exists(os.path.join(nested, ac.CONTEXT_MAP))
              and not os.path.exists(os.path.join(nested, ac.METADATA)),
              "no nested map or metadata was written into the enclosing context")
        # independence: a context inside an ordinary project still opens and serves.
        project = tempfile.mkdtemp(prefix="charter-project-")
        write(project, "README.md", b"a project, not an Agent Context\n")
        inner = os.path.join(project, "ctx")
        mg.create(inner, "Inner")
        check(mg.open_context(inner)["agents_served"],
              "a context inside an ordinary project still opens and serves")
        shutil.rmtree(project, ignore_errors=True)
        shutil.rmtree(outer)


def case_long_path_refused_cleanly() -> None:
    print("\nan over-long context path is refused in words, leaving nothing behind")
    from app import transaction as tx
    limit = tx.path_limit()
    if limit > 1000:
        print(f"  SKIPPED: this system's path limit ({limit}) is too high to exercise here.")
        return
    with isolated_private_state():
        parent = tempfile.mkdtemp(prefix="charter-long-")
        try:
            # The folder path itself fits the folder limit, but the temporary
            # file of a generated write would exceed the overall path limit.
            name = "x" * max(1, tx.dir_limit() - len(parent) - 1)
            folder = os.path.join(parent, name)
            check(raises(au.ActionRefused, mg.create, folder, "Too Long"),
                  "creating a context with an over-long path is refused, not a raw OS error")
            check(not os.path.isdir(folder),
                  "and no folder is left behind for the refused create")
        finally:
            shutil.rmtree(parent, ignore_errors=True)


def case_untrusted_private_state() -> None:
    print("\nprivate state that is there but cannot be trusted stops open, apply and propose")
    from app import agent_proposals as apx
    from app import transaction as tx
    add = {"title": "Gamma", "body": "x\n"}
    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        write(cs.base, ps.CONTEXT_RECORD, b"{broken")
        before = snapshot(folder)
        try:
            mg.open_context(folder)
            said = ""
        except ps.PrivateStateError as exc:
            said = str(exc)
        check("cannot be used" in said and cs.base in said and snapshot(folder) == before,
              "an unreadable folder record: opening refuses, naming the state for the person")
        check(raises(ValueError, au.plan, folder, "add", add)
              and raises(ValueError, au.apply, folder, "add", add, "x", True)
              and raises(apx.Unavailable, apx.open_target, folder),
              "and nothing plans, applies or files a proposal")
        with open(cs.path(ps.CONTEXT_RECORD), "rb") as fh:
            check(fh.read() == b"{broken", "the record is left as it was found")
        report = mg.check(folder, git=False)
        with open(cs.path(ps.CONTEXT_RECORD), "rb") as fh:
            untouched = fh.read() == b"{broken"
        check(not report["agents_served"]
              and report["headline_title"] == "Charter can’t serve this Agent Context yet"
              and report["headline_detail"].startswith("Charter’s local records for this folder can’t be "
                                                       "used, so it can’t tell whether a write was interrupted.")
              and untouched and snapshot(folder) == before,
              "`charter check` agrees with MCP: agents refused, changing nothing")
        write(cs.base, ps.CONTEXT_RECORD, json.dumps({"version": 1, "folder": folder + "-x"}))
        check(raises(ps.PrivateStateError, mg.open_context, folder),
              "a folder record naming another folder: opening refuses too")
        shutil.rmtree(folder)

    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        jdir = cs.staging_dir(tx.JOURNAL_KIND)
        os.makedirs(os.path.join(jdir, tx.JOURNAL_FILE))
        status = mg.open_context(folder)
        check(status["recovered"] and "cannot be trusted" in status["recovered"]["problem"]
              and status["interrupted"] and not status["agents_served"],
              "a journal that cannot be read: opening says so, and agents are refused")
        check(raises(au.ActionRefused, au.apply, folder, "add", add, "x", True),
              "applying refuses in words rather than guessing")
        try:
            apx.open_target(folder)
            code = ""
        except apx.Unavailable as exc:
            code = exc.code
        check(code == "context_invalid", "and proposals are not filed")
        os.rmdir(os.path.join(jdir, tx.JOURNAL_FILE))
        check(mg.open_context(folder)["agents_served"], "once resolved, it opens and serves again")
        shutil.rmtree(folder)


def case_generated_writes_guarded() -> None:
    """Rebuild and Settings replace a file only if it still holds what the
    preview was built from; a failure to record the change afterwards is said
    beside the success, never as though nothing changed."""
    print("\nRebuild and Settings: a change made meanwhile is refused; a failed record follows the success")
    from app import observation
    from app import transaction as tx
    with isolated_private_state():
        folder = context()
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited outside.\n"))
        p = mg.rebuild_plan(folder)
        original = tx.Transaction.run
        meddled = "{\"edited\": \"meanwhile\"}\n"

        def interleaved(self, *args, **kwargs):
            # Someone else writes the metadata after the plan was checked, before any write.
            with open(os.path.join(folder, ac.METADATA), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(meddled)
            return original(self, *args, **kwargs)

        tx.Transaction.run = interleaved
        try:
            refused = raises(au.ActionRefused, mg.rebuild_apply, folder, p.plan_id, True)
        finally:
            tx.Transaction.run = original
        with open(os.path.join(folder, ac.METADATA), encoding="utf-8") as fh:
            kept = fh.read() == meddled
        check(refused and kept, "the metadata changed meanwhile: Rebuild refuses and leaves that change as it is")

        generate(folder)
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited again.\n"))
        p = mg.rebuild_plan(folder)
        recorded = observation.record_rebuild

        def broken(*_args, **_kwargs):
            raise OSError("disk full")

        observation.record_rebuild = broken
        try:
            status = mg.rebuild_apply(folder, p.plan_id, True)
        finally:
            observation.record_rebuild = recorded
        check(status["agents_served"] and status["follow_up"] == [mg.OBSERVATION_FAILED],
              "the record of a rebuild cannot be written: the rebuild still stands, and the failure is said with it")
        p = mg.settings_plan(folder, "Renamed")
        status = mg.settings_apply(folder, p.plan_id, True, "Renamed")
        check(status["follow_up"] == [] and status["name"] == "Renamed",
              "an ordinary settings change has no follow-up")
        shutil.rmtree(folder)


def run() -> None:
    case_create()
    case_open()
    case_untrusted_private_state()
    case_generated_writes_guarded()
    case_read_text_helper()
    case_enclosing_context_helper()
    case_nested_context_refused()
    case_long_path_refused_cleanly()
    case_outside_edit_and_rebuild()
    case_plain_refusals()
    case_map_format_updates()
    case_earlier_name_map()
    case_rebuild_refusals()
    case_rebuild_generated_damage()
    case_settings()
    case_check_changes_nothing()
    case_git_read_only()
    case_git_config_cannot_run_code()
    print(f"\n{OK} All Agent Context manager checks passed.")


if __name__ == "__main__":
    run()
