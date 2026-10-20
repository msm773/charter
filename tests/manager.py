"""Open, create, check, outside changes, Rebuild Agent Context and Settings.
Run: python -m tests.manager

Product Specification §3.1 and §3.5, Agent Context as the Project Asset §4 and
§7, UI Standards, and the Phase 4 decisions:

  * opening recovers an interrupted Charter write, validates, and says whether
    agents are served, in ordinary language;
  * a new Agent Context is created in an empty folder, never inside another;
  * an edit to a governing document needs review: agents are refused,
    Rebuild never accepts it, and the route is Revise, restore the approved
    text outside Charter, then an ordinary change set;
  * Rebuild previews, needs ordinary deliberate confirmation, writes only the
    map and metadata, corrects only problems that change no document's
    approved status or text, and with no usable map only once no document
    remains; Regenerate map rewrites only a map whose own hash is the sole
    failure;
  * a valid outside change is shown as changed outside Charter until the
    person acknowledges it; with no private record its origin is unknown;
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
        check(not status["outside"]["known"] and "how this content was created or changed"
              in status["outside"]["message"] and "origin is unknown" in status["outside"]["message"]
              and "record of this Agent Context" not in status["outside"]["message"],
              "content this computer has no record of is of unknown origin, said of the content, "
              "not of the folder the person just opened")
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


def case_outside_edit_needs_review() -> None:
    print("\nan edit made outside Charter needs review: Revise, restore, then a change set")
    with isolated_private_state():
        folder = context()
        mg.open_context(folder)
        cs = ps.PrivateState.default().for_context(folder)
        exam = ac.examine(folder)
        cs.record_observed(exam.fingerprint, exam.hashes, "charter", [])
        approved = read(folder, "authoritative/a.md")

        edited = doc_text("a", "Alpha", body="Edited in an editor.\n")
        write(folder, "authoritative/a.md", edited)
        status = mg.open_context(folder)
        check(status["state"] == ac.INVALID and not status["agents_served"] and status["needs_review"]
              and status["headline_title"] == mg.REVIEW_TITLE == "Context changes need review"
              and status["headline_detail"] == mg.REVIEW_DETAIL,
              "an edited governing document: agents are refused, and context changes need review")
        rows = [i for i in status["issues"] if i["kind"] == ac.INTEGRITY]
        check([(r["path"], r["label"]) for r in rows]
              == [("authoritative/a.md", "Does not match approved context")],
              "the document is listed, with the one chip Does not match approved context")
        check(not status["rebuild"]["available"] and not status["regenerate"]["available"]
              and not status["outside"]["changed_outside"] and status["outside"]["message"] == "",
              "neither Rebuild nor Regenerate map is offered, and it is not called a served outside change")

        before = snapshot(folder)
        p = mg.rebuild_plan(folder)
        check(p.blocked and mg.REBUILD_NEVER_ACCEPTS in p.problems
              and raises(au.ActionRefused, mg.rebuild_apply, folder, p.plan_id, True)
              and snapshot(folder) == before,
              "Rebuild is refused outright: it never accepts the changed text, and writes nothing")
        r = mg.regenerate_plan(folder)
        check(r.blocked and mg.NOT_REGENERABLE in r.problems
              and raises(au.ActionRefused, mg.regenerate_apply, folder, r.plan_id, True)
              and snapshot(folder) == before, "Regenerate map is refused too")

        revise = au.plan(folder, "revise", {"path": "authoritative/a.md"})
        check(not revise.blocked and not revise.governing_change,
              "Revise stays available while the context is unavailable, and changes no governing context")
        au.apply(folder, "revise", revise.request, revise.plan_id, True)
        logical = next(c for c in ps.PrivateState.default().for_context(folder).candidates())
        cs = ps.PrivateState.default().for_context(folder)
        candidate = cs.read_candidate(logical) or ""
        check("Edited in an editor." in candidate and snapshot(folder) == before
              and not mg.check(folder)["agents_served"],
              "it files the current checked-out text as a revision candidate; the folder is untouched "
              "and agents are still refused")
        from app import changeset as chs
        try:
            blocked = au.plan(folder, "changeset", seeded(folder, {"document": "authoritative/a.md",
                                                                   "candidate": logical})).blocked
        except (au.ActionRefused, chs.ChangeSetError):
            blocked = True
        check(blocked, "no change set can be applied while the context needs review: there is no "
                       "invalid-context exception")

        write(folder, "authoritative/a.md", approved)  # restored outside Charter, as with Git
        status = mg.open_context(folder)
        check(status["agents_served"] and not status["needs_review"]
              and not status["outside"]["changed_outside"],
              "restoring the approved text makes the context valid and served again")
        g = au.plan(folder, "changeset", seeded(folder, {"document": "authoritative/a.md",
                                                         "candidate": logical}))
        check(not g.blocked and g.governing_change and g.confirm_phrase == PHRASE
              and any("was made from an earlier version of" in n for n in g.notes),
              "an ordinary change set replaces it with the revision, warning that the candidate was "
              "made from another version, to be compared before applying")
        check(any(c.label == "authoritative/a.md" and c.diff() for c in g.changes),
              "and its preview compares the candidate with the restored governing document")
        au.apply(folder, "changeset", g.request, g.plan_id, PHRASE)
        status = mg.check(folder)
        check(status["agents_served"] and b"Edited in an editor." in read(folder, "authoritative/a.md"),
              "applied through the reviewed change set, the revision governs")
        shutil.rmtree(folder)

    print("\na valid outside change, made consistently, is served and flagged until seen")
    with isolated_private_state():
        folder = context()
        mg.open_context(folder)
        cs = ps.PrivateState.default().for_context(folder)
        exam = ac.examine(folder)
        cs.record_observed(exam.fingerprint, exam.hashes, "charter", [])
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="From another checkout.\n"))
        generate(folder)  # as Git delivers a context another Charter generated
        status = mg.open_context(folder)
        check(status["agents_served"] and status["outside"]["changed_outside"]
              and status["outside"]["paths"] == ["authoritative/a.md"]
              and "cannot tell who changed them" in status["outside"]["message"],
              "a consistent checkout governs, and is shown as changed outside Charter, never attributed")

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


def case_regenerate_map() -> None:
    print("\nRegenerate map: only the derived map, only when its own hash is the sole failure")
    with isolated_private_state():
        folder = context()
        mg.open_context(folder)
        approved = snapshot(folder)
        text = read(folder, ac.CONTEXT_MAP).decode()
        write(folder, ac.CONTEXT_MAP, text.replace("Do not edit it by hand", "Edited by hand"))
        status = mg.open_context(folder)
        check(not status["agents_served"] and status["needs_review"]
              and status["regenerate"]["available"] and not status["rebuild"]["available"]
              and status["headline_title"] == mg.REVIEW_TITLE
              and status["headline_detail"] == mg.REVIEW_MAP_ONLY,
              "a map edited by hand, every document still matching: Regenerate map is the one repair")
        before = snapshot(folder)
        p = mg.regenerate_plan(folder)
        check(not p.blocked and not p.governing_change and p.confirm_phrase == ""
              and [c.label for c in p.changes] == [ac.CONTEXT_MAP] and p.changes[0].diff(),
              "its preview rewrites only the map, with a diff, under ordinary confirmation: the "
              "map it generates is the approved one, whose hash the metadata already records")
        check(raises(au.ActionRefused, mg.regenerate_apply, folder, p.plan_id, None)
              and snapshot(folder) == before, "it waits for a deliberate confirmation")
        check(ac.sha256_text(p.changes[0].new) == json.loads(read(folder, ac.METADATA))["sha256"][ac.CONTEXT_MAP]
              and all(c.path != ac.METADATA for c in p.changes),
              "the map it would write has exactly the hash the metadata already records, and the "
              "metadata is not among the files it writes")
        metadata_before = read(folder, ac.METADATA)
        status = mg.regenerate_apply(folder, p.plan_id, True)
        after = snapshot(folder)
        check(status["agents_served"] and after == approved and read(folder, ac.METADATA) == metadata_before,
              "afterwards the context is exactly the approved one: the map restored to its recorded "
              "hash, and `.agent-context.json` byte for byte unchanged")

        # A record whose settings no longer produce its own recorded map: the
        # recorded hash cannot be reproduced, so nothing is regenerated.
        meta = json.loads(read(folder, ac.METADATA))
        meta["project_name"] = "Renamed by hand"
        write(folder, ac.METADATA, (json.dumps(meta, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
        write(folder, ac.CONTEXT_MAP, text + "\nA note.\n")
        before = snapshot(folder)
        status = mg.open_context(folder)
        p = mg.regenerate_plan(folder)
        check(not status["regenerate"]["available"] and status["needs_review"]
              and not ac.examine(folder).map_regenerable and ac.restored_map(ac.examine(folder)) is None,
              "when the regenerated map would not have the recorded hash, Regenerate map is not offered")
        check(p.blocked and mg.NOT_REGENERABLE in p.problems and not p.changes
              and raises(au.ActionRefused, mg.regenerate_apply, folder, p.plan_id, True)
              and snapshot(folder) == before and not mg.check(folder)["agents_served"],
              "its preview is refused, applying writes nothing, the metadata is never changed to fit, "
              "and the context stays unavailable")
        for rel, data in approved.items():
            if data is not None:
                write(folder, rel.replace(os.sep, "/"), data)

        # A record in an older map format: restored in that format, byte for byte.
        from tests.agent_context import with_map_format
        with_map_format(folder, 2)
        older = snapshot(folder)
        write(folder, ac.CONTEXT_MAP, read(folder, ac.CONTEXT_MAP) + b"\nA note.\n")
        p = mg.regenerate_plan(folder)
        status = mg.regenerate_apply(folder, p.plan_id, True)
        check(snapshot(folder) == older and status["headline_title"] == mg.MAP_OUTDATED[0]
              and status["rebuild"]["available"],
              "a map recorded in format 2 is restored as that format 2 map, its metadata unchanged; "
              "the context is then simply out of date, for Rebuild")
        for rel, data in approved.items():
            if data is not None:
                write(folder, rel.replace(os.sep, "/"), data)

        for label, damage in (
                ("a governing document also changed",
                 lambda: write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="x\n"))),
                ("the map is missing", lambda: os.remove(os.path.join(folder, ac.CONTEXT_MAP))),
                ("the map lists another document",
                 lambda: write(folder, ac.CONTEXT_MAP, text.replace("`authoritative/b.md` |",
                                                                    "`authoritative/z.md` |")))):
            write(folder, ac.CONTEXT_MAP, text + "\nA note.\n")
            damage()
            before = snapshot(folder)
            p = mg.regenerate_plan(folder)
            check(not mg.check(folder)["regenerate"]["available"] and p.blocked
                  and raises(au.ActionRefused, mg.regenerate_apply, folder, p.plan_id, True)
                  and snapshot(folder) == before,
                  f"when {label}, Regenerate map is not offered, and is refused, writing nothing")
            for rel, data in approved.items():
                if data is not None:
                    write(folder, rel.replace(os.sep, "/"), data)
        check(mg.check(folder)["agents_served"], "restored, the context is served again")
        shutil.rmtree(folder)


def case_plain_refusals() -> None:
    print("\nwhy agents are not served, in plain words: a heading, then what it means and what to do")
    with isolated_private_state():
        folder = context()
        write(folder, "authoritative/c.md", "﻿" + doc_text("c", "Gamma"))
        status = mg.check(folder, git=False)
        check(not status["agents_served"] and status["state"] == ac.INVALID and not status["needs_review"]
              and (status["headline_title"], status["headline_detail"]) == mg.NOT_VALID
              and status["headline_detail"] == ("Something in this folder isn’t valid. Each problem, and how "
                                                "to fix it, is listed below."),
              "a document problem nothing can rebuild past: the problems are listed below")
        check(status["headline"] == status["headline_title"] + ". " + status["headline_detail"],
              "`charter check` and Connect agents get the heading and its detail as one line")
        shutil.rmtree(folder)
    every = [mg.INTERRUPTED, mg.PRIVATE_UNUSABLE, mg.CHARTER_OUTDATED, mg.LEGACY, mg.MAP_OUTDATED,
             mg.MISMATCH, mg.NOT_VALID, (mg.STRAY_TITLE, mg.STRAY_DETAIL),
             (mg.REVIEW_TITLE, mg.REVIEW_DETAIL), (mg.REVIEW_TITLE, mg.REVIEW_MAP_ONLY),
             (mg.REVIEW_TITLE, mg.REVIEW_NO_MAP)]
    review = " ".join((mg.REVIEW_DETAIL, mg.REVIEW_MAP_ONLY, mg.REVIEW_NO_MAP)).lower()
    check(not any(w in review for w in ("outside charter", "someone", "an agent", "edited by",
                                        "changed by", "modified", "invalid")),
          "the review statuses say what was observed: never who changed it, and never “invalid”")
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

        with_map_format(folder, 2)
        status = mg.open_context(folder)
        check(not status["agents_served"] and status["headline_title"] == mg.MAP_OUTDATED[0]
              and status["rebuild"]["available"],
              "a map in format 2, generated before format 3, is out of date too: Rebuild is offered")
        p = mg.rebuild_plan(folder)
        status = mg.rebuild_apply(folder, p.plan_id, True)
        check(status["agents_served"] and status["map_format"]["recorded"] == ac.MAP_FORMAT_VERSION == 3,
              "rebuilt, it records format 3 and is served")

        # An older map whose document also changed needs review, not just a rebuild.
        with_map_format(folder, 2)
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited in an editor.\n"))
        status = mg.open_context(folder)
        p = mg.rebuild_plan(folder)
        check(status["needs_review"] and not status["rebuild"]["available"] and p.blocked,
              "an older map whose document no longer matches needs review: Rebuild is refused")
        generate(folder)

        with_map_format(folder, ac.MAP_FORMAT_VERSION + 1)
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
        check(not exam.legacy_map and exam.needs_review
              and "earlier name" not in status["headline"]
              and status["headline_title"] == mg.REVIEW_TITLE and not status["rebuild"]["available"],
              "with a document also edited, it is not only an earlier-name map: context changes "
              "need review, and no Rebuild is offered")
        shutil.rmtree(folder)


def case_incomplete_context() -> None:
    print("\nauthored documents in authoritative/, no map: opened, never created, never rebuilt into governance")
    with isolated_private_state():
        def authored(files: dict) -> str:
            folder = tempfile.mkdtemp(prefix="charter-authored-")
            os.makedirs(os.path.join(folder, "authoritative"))
            for rel, text in files.items():
                write(folder, rel, text.encode("utf-8"))
            return folder

        plain = authored({"authoritative/notes.md": "# Notes\n\nNo front matter.\n"})
        check(ac.is_incomplete_context(plain) and not ac.is_context_root(plain),
              "a folder with authoritative/ and no map or metadata is an incomplete Agent Context")
        before = snapshot(plain)
        check(raises(au.ActionRefused, mg.create, plain, "Typed") and snapshot(plain) == before,
              "Create refuses it, and writes nothing")
        try:
            mg.create(plain, "Typed")
        except au.ActionRefused as exc:
            check("Open Agent Context" in str(exc) and "incomplete" in str(exc),
                  "and says to open it with Open Agent Context")
        status = mg.open_context(plain)
        check(snapshot(plain) == before, "opening it writes nothing in the folder")
        issues = " ".join(f"{i.get('path', '')} {i['message']}" for i in status["issues"])
        check(not status["agents_served"] and status["headline_title"] == mg.INCOMPLETE_TITLE
              and "AGENT-CONTEXT.md" in issues and ".agent-context.json" in issues
              and "authoritative/notes.md" in issues,
              "it is unavailable, naming what is missing and the document that cannot govern")
        blocked = mg.rebuild_plan(plain, "Typed")
        check(not status["rebuild"]["available"] and blocked.blocked
              and any("authoritative/notes.md" in p for p in blocked.problems)
              and raises(Exception, mg.rebuild_apply, plain, blocked.plan_id, True, "Typed")
              and snapshot(plain) == before,
              "with a document that cannot govern, Rebuild is not offered, its preview is blocked, "
              "and applying it is refused, writing nothing")

        def confirmed(folder: str, name: str) -> dict:
            p = mg.rebuild_plan(folder, name, ac.default_guidance())
            return mg.rebuild_apply(folder, p.plan_id, True, name, ac.default_guidance())

        rules_text = doc_text("rules", "Rules")
        ready = authored({"authoritative/rules.md": rules_text})
        before = snapshot(ready)
        status = mg.open_context(ready)
        rows = {i["path"]: i["label"] for i in status["issues"] if i["kind"] == ac.INTEGRITY}
        check(not status["agents_served"] and status["needs_review"]
              and status["headline_title"] == mg.REVIEW_TITLE and status["headline_detail"] == mg.REVIEW_NO_MAP
              and rows == {"authoritative/rules.md": "Not in approved context"}
              and not status["governing"] and snapshot(ready) == before,
              "valid governing front matter but no map: unavailable, the document not in an approved "
              "context and not governing, and nothing written")
        detail = status["headline_detail"]
        row = next(i for i in status["issues"] if i["path"] == "authoritative/rules.md")
        check("If an approved map and metadata for them exist elsewhere" in detail
              and "If the documents are newly authored or were never mapped, there is no map to restore"
              in detail and "were lost" not in detail
              and "If an approved map and metadata for it exist elsewhere, restore them" in row["fix"]
              and "newly authored or was never mapped, move it out" in row["fix"],
              "the status and the row give both routes: restore a map that exists elsewhere, or, for "
              "newly authored material, move it out and govern it as a candidate; neither assumes a "
              "map was lost")
        p = mg.rebuild_plan(ready, "Rules project", ac.default_guidance())
        check(not status["rebuild"]["available"] and p.blocked and mg.REBUILD_NEVER_ACCEPTS in p.problems
              and raises(au.ActionRefused, mg.rebuild_apply, ready, p.plan_id, True, "Rules project",
                         ac.default_guidance())
              and snapshot(ready) == before,
              "Rebuild never maps the document into governance: not offered, its preview blocked, "
              "applying refused, nothing written")

        # The route: move the document out, establish an empty context, then govern it as a candidate.
        outside = tempfile.mkdtemp(prefix="charter-moved-out-")
        write(outside, "rules.md", read(ready, "authoritative/rules.md"))
        os.remove(os.path.join(ready, "authoritative", "rules.md"))
        status = mg.open_context(ready)
        waiting = mg.rebuild_plan(ready).problems
        check(status["rebuild"]["available"] and status["headline_detail"] == mg.INCOMPLETE_READY
              and status["rebuild"]["needs_project_name"]
              and mg.NO_SETTINGS_YET in waiting and not any("lost" in p for p in waiting),
              "once no document remains, Rebuild is offered, asking for the project name and settings")
        check(raises(au.ActionRefused, rebuild, ready, "Rules project"),
              "Rebuild applies only once the person also confirms the agent guidance")
        status = confirmed(ready, "Rules project")
        check(status["agents_served"] and not status["governing"],
              "Rebuild establishes an empty Agent Context, which governs nothing")
        a = au.plan(ready, "add", {"title": "Rules", "body": rules_text.split("---\n", 2)[2]})
        au.apply(ready, "add", a.request, a.plan_id, True)
        logical = next(iter(ps.PrivateState.default().for_context(ready).candidates()))
        g = au.plan(ready, "changeset", seeded(ready, {"alongside": logical}))
        au.apply(ready, "changeset", g.request, g.plan_id, PHRASE)
        status = mg.check(ready)
        check(status["agents_served"] and [d["title"] for d in status["governing"]] == ["Rules"],
              "added as an authority candidate and governed through a change set, it governs")
        shutil.rmtree(outside)
        os.remove(os.path.join(ready, ".agent-context.json"))
        p = mg.rebuild_plan(ready)
        check(p.blocked and mg.SETTINGS_UNREADABLE in p.problems and mg.check(ready)["needs_review"],
              "once it has a map, missing metadata makes the settings unusable and its document "
              "not in an approved context: no Rebuild")

        empty = authored({})
        status = mg.open_context(empty)
        check(status["rebuild"]["available"] and confirmed(empty, "Empty")["agents_served"],
              "with no documents, Rebuild makes a valid, empty Agent Context")

        stray = authored({"authoritative/rules.md": doc_text("rules", "Rules"), "README.md": "x\n"})
        status = mg.open_context(stray)
        check(not status["rebuild"]["available"] and status["strays"],
              "anything else in the folder keeps Rebuild from being offered")
        for folder in (plain, ready, empty, stray):
            shutil.rmtree(folder)


def case_rebuild_refusals() -> None:
    print("\nwhat Rebuild refuses")
    with isolated_private_state():
        folder = context()
        check(mg.rebuild_plan(folder).blocked and
              any("nothing to rebuild" in m for m in mg.rebuild_plan(folder).problems),
              "a valid context has nothing to rebuild")
        out_of_form(folder)
        check(not mg.rebuild_plan(folder).blocked, "metadata out of form alone is rebuildable")
        write(folder, "scratch.txt", b"mine")
        before = snapshot(folder)
        p = mg.rebuild_plan(folder)
        check(p.blocked and any("scratch.txt" in m for m in p.problems),
              "a stray blocks Rebuild, named")
        check(raises(au.ActionRefused, mg.rebuild_apply, folder, p.plan_id, True)
              and snapshot(folder) == before, "and nothing is written, the stray included")
        os.remove(os.path.join(folder, "scratch.txt"))
        approved_b = read(folder, "authoritative/b.md")
        for label, text in (
                ("a merge conflict in a governing document",
                 doc_text("b", "Beta", body="<<<<<<< HEAD\nx\n=======\ny\n>>>>>>> topic\n")),
                ("a governing document whose metadata now says it does not govern",
                 doc_text("b", "Beta", authority="non-authoritative")),
                ("an ordinary edit to a governing document", doc_text("b", "Beta", body="Edited.\n"))):
            write(folder, "authoritative/b.md", text)
            p = mg.rebuild_plan(folder)
            check(p.blocked and mg.REBUILD_NEVER_ACCEPTS in p.problems
                  and any("authoritative/b.md" in m and "does not match" in m for m in p.problems),
                  f"{label} needs review: Rebuild is refused, naming it")
        write(folder, "authoritative/c.md", doc_text("c", "Gamma"))
        write(folder, "authoritative/b.md", approved_b)
        p = mg.rebuild_plan(folder)
        check(p.blocked and any("authoritative/c.md" in m for m in p.problems),
              "so is a governing document added by hand: Rebuild never maps it")
        os.remove(os.path.join(folder, "authoritative", "c.md"))
        p = mg.rebuild_plan(folder)
        cs = ps.PrivateState.default().for_context(folder)
        cs.record_observed("x" * 64, {}, "seen", [])
        out_of_form(folder)
        write(folder, ac.METADATA, read(folder, ac.METADATA) + b" ")
        check(raises(au.StalePlan, mg.rebuild_apply, folder, p.plan_id, True),
              "a generated file changed after the preview makes it stale")
        shutil.rmtree(folder)


def case_rebuild_generated_damage() -> None:
    print("\nRebuild replaces damaged or missing generated files only while no document is at stake")
    with isolated_private_state():
        folder = context()
        text = read(folder, ac.CONTEXT_MAP).decode()
        for label, damage in (
                ("a conflicted map", lambda: write(folder, ac.CONTEXT_MAP, "<<<<<<< HEAD\n" + text
                                                   + "=======\nother\n>>>>>>> b\n")),
                ("a missing map", lambda: os.remove(os.path.join(folder, ac.CONTEXT_MAP))),
                ("a missing metadata file", lambda: os.remove(os.path.join(folder, ac.METADATA)))):
            damage()
            status = mg.open_context(folder)
            check(status["needs_review"] and not status["rebuild"]["available"]
                  and mg.rebuild_plan(folder, "Test project", ac.default_guidance()).blocked,
                  f"{label}, with documents present: no usable map, so no Rebuild maps them")
            generate(folder)
        shutil.rmtree(folder)

        folder = context(docs=(), guidance={"review_newly_discovered_material": True})
        text = read(folder, ac.CONTEXT_MAP).decode()
        write(folder, ac.CONTEXT_MAP, "<<<<<<< HEAD\n" + text + "=======\nother\n>>>>>>> b\n")
        check(rebuild(folder)["agents_served"], "with no document, a conflicted map is regenerated")

        os.remove(os.path.join(folder, ac.CONTEXT_MAP))
        check(rebuild(folder)["agents_served"], "and so is a missing map")

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
        before = snapshot(empty)
        p = mg.rebuild_plan(empty, "Adopted", ac.default_guidance())
        check(p.blocked and mg.REBUILD_NEVER_ACCEPTS in p.problems
              and raises(au.ActionRefused, mg.rebuild_apply, empty, p.plan_id, True, "Adopted",
                         ac.default_guidance())
              and snapshot(empty) == before,
              "but documents placed in a folder never become governing through Rebuild, even with "
              "every setting confirmed: nothing is written")
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
        generate(folder, "Repo context")  # a consistent change, as another checkout delivers it
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
            status = mg.check(folder)
        finally:
            subprocess.run = real  # type: ignore[assignment]
        check(status["agents_served"], "the consistent change governs for the feature checkout")
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


def out_of_form(folder: str) -> None:
    """A problem Rebuild Agent Context may correct: the metadata holds exactly
    what it should, in a form Charter does not write. No document's approved
    status or text is in question."""
    write(folder, ac.METADATA, json.dumps(json.loads(read(folder, ac.METADATA))).encode("utf-8"))


def case_generated_writes_guarded() -> None:
    """Rebuild and Settings replace a file only if it still holds what the
    preview was built from; a failure to record the change afterwards is said
    beside the success, never as though nothing changed."""
    print("\nRebuild and Settings: a change made meanwhile is refused; a failed record follows the success")
    from app import observation
    from app import transaction as tx
    with isolated_private_state():
        folder = context()
        out_of_form(folder)
        p = mg.rebuild_plan(folder)
        check(not p.blocked, "metadata out of Charter's form is a problem Rebuild may correct")
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
        out_of_form(folder)
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
    case_outside_edit_needs_review()
    case_regenerate_map()
    case_plain_refusals()
    case_map_format_updates()
    case_earlier_name_map()
    case_incomplete_context()
    case_rebuild_refusals()
    case_rebuild_generated_damage()
    case_settings()
    case_check_changes_nothing()
    case_git_read_only()
    case_git_config_cannot_run_code()
    print(f"\n{OK} All Agent Context manager checks passed.")


if __name__ == "__main__":
    run()
