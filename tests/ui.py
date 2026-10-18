"""The Charter console page, run against real payloads.
Run: python -m tests.ui

A real Agent Context is built in each state the page must show, and the
console API's own answers for it are captured here and handed to
`tests/ui.test.js`, which runs the page's own JavaScript against them. The
Markdown renderer's checks, `tests/markdown.test.js`, run too.

The assertions for the one area the console has deliberately not wired yet —
MCP activity — are kept, not run, in `tests/deferred/`.
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
from app import console  # noqa: E402
from app import host_state as hs  # noqa: E402
from tests.agent_context import context, doc_text, generate, write  # noqa: E402
from tests.harness import isolated_private_state  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PHRASE = "change governing context"

# A governing document using everything the viewer renders, and some HTML it
# must show as text.
RICH_BODY = """# Suppliers

How suppliers are chosen.

## Criteria

- **Price** first
- Delivery second

| Supplier | Region |
| --- | --- |
| Acme | North |

```text
order --dry-run
```

<script>alert("not run")</script>
"""


def do(session, kind, request, confirm=None):
    plan = console.plan(session, {"kind": kind, "request": request})
    if confirm is None:
        confirm = PHRASE if plan["confirm_phrase"] else True
    return plan, console.apply(session, {"kind": kind, "request": request,
                                         "plan_id": plan["plan_id"], "confirm": confirm})


def refused(fn, *args) -> str:
    try:
        fn(*args)
    except console.ApiError as exc:
        return exc.message
    return ""


def build_fixture() -> dict:
    out: dict = {}
    folder = context()
    write(folder, "authoritative/suppliers.md",
          doc_text("suppliers", "Suppliers", scope="Supplier choice.", body=RICH_BODY))
    generate(folder)
    # As private state records it, so as the recent list shows it: canonical,
    # which on macOS is /private/var/… for a temporary folder made as /var/….
    out["folder"] = hs.canonical(folder)
    session = console.Session()
    # Whether this computer has a folder dialog is the page's input, not the
    # test machine's: the start screen is captured without one, and with one.
    out["state_closed"] = dict(console.state(session), folder_picker=False)
    out["open_missing_error"] = refused(console.open_context, session,
                                        {"path": os.path.join(folder, "missing")})
    console.open_context(session, {"path": folder})
    do(session, "add", {"title": "Gamma rules", "scope": "Gamma decisions.", "body": "Rule.\n"})
    do(session, "add", {"title": "Unscoped idea", "scope": "", "body": "Idea.\n"})
    do(session, "add", {"title": "Old draft", "scope": "", "body": "Old.\n"})
    _plan, out["apply_candidate"] = do(session, "retire", {"candidate": "authority-candidates/old-draft.md"})
    # Made with Revise… from Beta: offered first, labelled, never chosen.
    do(session, "revise", {"path": "authoritative/b.md", "title": "Beta revised", "scope": "",
                           "body": "Clearer Beta.\n"})

    # Agent Proposals: one waiting, one that went stale, one imported, and a
    # file among the records that intake never filed.
    from app import agent_proposals as apx
    from app import private_store as ps
    out["proposal_pending"] = apx.file(folder, {
        "agent": "codex", "operation": "create", "target_path": "authority-candidates/release-rule.md",
        "reason": "Releases need a written rule.", "proposed_body": "# Release rule\n\nTag every release.\n",
        "expected_context_impact": {"related": ["authoritative/a.md"], "overlap": "none",
                                    "conflict": "none", "recommended_relationship": "alongside",
                                    "unresolved_decision": "none"}})["proposal_id"]
    # A create that proposes its title, with a reason far longer than one line.
    out["proposal_titled_reason"] = ("Releases are checked by hand today, and steps are missed. " * 12).strip()
    out["proposal_titled"] = apx.file(folder, {
        "agent": "codex", "operation": "create", "target_path": "authority-candidates/release-checklist.md",
        "reason": out["proposal_titled_reason"], "proposed_body": "# Release checklist\n\nCheck each step.\n",
        "proposed_meta": {"title": "Release checklist", "scope": "How a release is checked."}})["proposal_id"]
    # An amend of a candidate, which then changes, so the proposal goes stale.
    # (A create is never stale for a name collision: candidate names are private
    # and a collision is resolved when the proposal is accepted.)
    idea_path = "authority-candidates/unscoped-idea.md"
    idea_sha = ac.sha256_text(ps.PrivateState.default().for_context(folder).read_candidate(idea_path))
    out["proposal_stale"] = apx.file(folder, {
        "agent": "claude", "operation": "amend", "target_path": idea_path,
        "reason": "Refine the idea.", "base_sha256": idea_sha,
        "proposed_body": "A refined idea.\n"})["proposal_id"]
    do(session, "edit-candidate", {"candidate": idea_path, "body": "The idea, changed.\n"})
    returned = {"agent": "chat-agent", "operation": "amend", "target_path": "authoritative/b.md",
                "reason": "Clarify Beta.", "base_sha256": ac.sha256_text(
                    open(os.path.join(folder, "authoritative", "b.md"), encoding="utf-8").read()),
                "proposed_body": "Clearer Beta.\n"}
    out["proposal_imported"] = console.import_file(session, {"json": json.dumps(returned),
                                                             "confirm": True})["proposal_id"]
    # Creates with no supplied title: one imported whose body opens with a
    # first-level heading, which titles it, and one filed directly with no
    # heading at all, which falls back to its logical path.
    out["proposal_imported_create"] = console.import_file(session, {"json": json.dumps({
        "agent": "chat-agent", "operation": "create", "target_path": "authority-candidates/imported-rule.md",
        "reason": "Write the imported rule down.", "proposed_body": "Intro line.\n\n# Imported rule\n\nText.\n"}),
        "confirm": True})["proposal_id"]
    out["proposal_untitled"] = apx.file(folder, {
        "agent": "codex", "operation": "create", "target_path": "authority-candidates/untitled-rule.md",
        "reason": "A rule with no heading.", "proposed_body": "Just the rule, with no heading.\n"})["proposal_id"]
    cs = ps.PrivateState.default().for_context(folder)
    with open(cs.path(ps.PROPOSALS, apx.PENDING, "dropped-in.json"), "w", encoding="utf-8") as fh:
        fh.write('{"agent": "unknown", "operation": "create"}\n')
    out["proposals"] = console.proposals(session, {})
    out["unexpected_view"] = console.unexpected(session, {"name": "dropped-in.json"})
    out["import_check_ok"] = console.import_check(session, {"json": json.dumps(dict(
        returned, reason="Another clarification."))})
    out["import_check_bad"] = console.import_check(session, {"json": json.dumps(dict(
        returned, base_commit="abc123"))})
    out["import_returned"] = json.dumps(dict(returned, reason="Another clarification."))
    out["state_valid"] = console.state(session)
    # Connect agents, as the console answers it here, and as it answers on each
    # platform: the page shows whichever it is given.
    out["connect_ready"] = console.connect_agents(session)
    out.update(connect_payloads(folder))
    out["state_closed_recent"] = console.state(console.Session())
    # The open/create screen peeks at a chosen folder (read-only): an existing
    # Agent Context answers with its name; an empty folder is offered to create.
    empty_folder = os.path.join(folder, "empty-peek")
    os.makedirs(empty_folder, exist_ok=True)
    out["peek_existing"] = console.peek(session, {"path": folder})
    out["peek_empty"] = console.peek(session, {"path": empty_folder})
    shutil.rmtree(empty_folder, ignore_errors=True)
    candidate = "authority-candidates/gamma-rules.md"
    out["candidate"] = candidate
    out["unscoped"] = "authority-candidates/unscoped-idea.md"
    out["governing"] = "authoritative/a.md"
    out["rich"] = "authoritative/suppliers.md"

    def plan(kind, request):
        return console.plan(session, {"kind": kind, "request": request})

    add_request = {"title": "Site notes", "scope": "", "body": "Ground conditions on the north boundary.\n",
                   "source": "site-notes.md (sha256 0123456789ab)"}
    out["plans"] = {
        "add": plan("add", add_request),
        "retire": plan("retire", {"candidate": candidate}),
        "revise": plan("revise", {"path": "authoritative/a.md", "title": "Alpha",
                                  "scope": "A scope.", "body": "Body.\n"}),
        "edit-candidate": plan("edit-candidate", {"candidate": candidate, "title": "Gamma rules",
                                                  "scope": "Gamma.", "body": "Rule.\n"}),
        "accept-proposal": plan("accept-proposal", {"proposal_id": out["proposal_pending"]}),
        "reject-proposal": plan("reject-proposal", {"proposal_id": out["proposal_pending"],
                                                    "reason": "Not now."}),
        "settings": plan("settings", {"project_name": "Renamed",
                                      "agent_guidance": {"context_check_in": True,
                                                         "proposal_context_impact_check": True,
                                                         "review_newly_discovered_material": False}}),
    }
    filed = out["plans"]["add"]["changes"][0]["path"]
    out["add_filed"] = filed
    out["drafts"] = {"authoritative/a.md": console.draft(session, {"path": "authoritative/a.md"}),
                     candidate: console.draft(session, {"path": candidate})}
    out["previews"] = {
        "context": console.preview(session, {"source": "context"}),
        candidate: console.preview(session, {"source": "document", "path": candidate}),
        "authoritative/a.md": console.preview(session, {"source": "document",
                                                        "path": "authoritative/a.md"}),
        out["rich"]: console.preview(session, {"source": "document", "path": out["rich"]}),
        "archive/old-draft.md": console.preview(session, {"source": "document",
                                                          "path": "archive/old-draft.md"}),
        "planned:" + filed: console.preview(session, {
            "source": "plan", "kind": "add", "request": add_request,
            "plan_id": out["plans"]["add"]["plan_id"], "path": filed}),
    }
    accepted_path = out["plans"]["accept-proposal"]["changes"][0]["path"]
    out["accepted_path"] = accepted_path
    out["previews"]["planned:" + accepted_path] = console.preview(session, {
        "source": "plan", "kind": "accept-proposal", "request": {"proposal_id": out["proposal_pending"]},
        "plan_id": out["plans"]["accept-proposal"]["plan_id"], "path": accepted_path})
    out["stage"] = console.stage(session, {"filename": "site-notes.md",
                                           "content_b64": "IyBTaXRlIG5vdGVzCgpHcm91bmQgY29uZGl0aW9ucyBvbiB0aGUgbm9ydGggYm91bmRhcnkuCg=="})
    # Every governing change is a change set, started here from one candidate,
    # undecided, or from a governing document to withdraw: real answers to each
    # start, and to the decisions the person then makes.
    from app import api_changeset as api
    revised = next(d["path"] for d in out["state_valid"]["documents"] if d["title"] == "Beta revised")
    out["cs_start_withdraw"] = api.create(session, {"start": {"withdraw": "authoritative/b.md"}})
    pending = api.create(session, {"start": {"candidate": revised}})
    out["cs_start_candidate"] = pending
    out["cs_start_replace_pending"] = api.update(session, {
        "id": pending["draft"]["id"], "revision": pending["draft"]["revision"],
        "decisions": {revised: {"decision": "replace", "target": ""}}})
    out["cs_start_replaced"] = api.update(session, {
        "id": pending["draft"]["id"], "revision": out["cs_start_replace_pending"]["draft"]["revision"],
        "decisions": {revised: {"decision": "replace", "target": "authoritative/b.md"}}})
    started = api.create(session, {"start": {"candidate": candidate}})
    out["cs_start_alongside"] = started
    ready = api.update(session, {"id": started["draft"]["id"], "revision": started["draft"]["revision"],
                                 "decisions": {candidate: {"decision": "govern-alongside"}}})
    out["cs_start_ready"] = ready
    out["start_request"] = {"draft_id": ready["draft"]["id"], "draft_revision": ready["draft"]["revision"]}
    out["start_plan"] = plan("changeset", out["start_request"])
    api.apply(session, {"id": ready["draft"]["id"], "revision": ready["draft"]["revision"],
                        "plan_id": out["start_plan"]["plan_id"], "confirm": PHRASE})
    out["cs_start_applied"] = api.get(session, {"id": ready["draft"]["id"]})

    write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited in an editor.\n"))
    out["state_invalid"] = console.state(session)
    out["connect_invalid"] = console.connect_agents(session)
    out["plan_rebuild"] = plan("rebuild", {})
    console.apply(session, {"kind": "rebuild", "request": {},
                            "plan_id": out["plan_rebuild"]["plan_id"], "confirm": True})
    out["state_rebuilt"] = console.state(session)

    write(folder, "notes.txt", b"mine")
    out["state_unclean"] = console.state(session)
    out["connect_unclean"] = console.connect_agents(session)
    os.remove(os.path.join(folder, "notes.txt"))

    text = open(os.path.join(folder, ac.METADATA), encoding="utf-8").read()
    os.remove(os.path.join(folder, ac.METADATA))
    out["state_lost_metadata"] = console.state(session)
    out["plan_rebuild_lost"] = plan("rebuild", {})
    offered = out["plan_rebuild_lost"]["settings_proposal"]
    out["plan_rebuild_confirmed"] = plan("rebuild", {
        "project_name": offered["project_name"], "agent_guidance": offered["agent_guidance"]})
    with open(os.path.join(folder, ac.METADATA), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

    # A map-format mismatch, each way: the map out of date, or this copy of
    # Charter out of date. Then the context as it was.
    from tests.agent_context import with_map_format
    map_text = open(os.path.join(folder, ac.CONTEXT_MAP), encoding="utf-8").read()
    with_map_format(folder, 1)
    out["state_map_outdated"] = console.state(session)
    with_map_format(folder, 3)
    out["state_charter_outdated"] = console.state(session)
    for rel, kept in ((ac.CONTEXT_MAP, map_text), (ac.METADATA, text)):
        with open(os.path.join(folder, rel), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(kept)
    out["diagnostics"] = console.diagnostics(session)
    out["diagnostics_closed"] = console.diagnostics(console.Session())

    # Variants of real payloads for states this folder cannot be put in here:
    # a Git checkout, a recovered write, and a computer with a folder dialog.
    valid = out["state_valid"]
    out["state_git"] = dict(valid, status=dict(valid["status"], git={
        "state": "checkout", "branch": "feature/scope", "changed": ["context/authoritative/a.md"]}))
    out["state_git_clean"] = dict(valid, status=dict(valid["status"], git={
        "state": "checkout", "branch": "main", "changed": []}))
    out["state_git_unreadable"] = dict(valid, status=dict(valid["status"], git={
        "state": "unreadable", "branch": "main"}))
    out["state_git_unavailable"] = dict(valid, status=dict(valid["status"], git={"state": "unavailable"}))
    out["state_recovered"] = dict(valid, recovered={"transaction": "1a2b3c", "unrestored": []})
    out["state_closed_picker"] = dict(out["state_closed_recent"], folder_picker=True)
    return out


class _Registry:
    """This user's PATH as a newly started program would get it, made up."""

    def __init__(self, path: str) -> None:
        self.path = path

    def user_path(self):
        return self.path, 2

    def machine_path(self):
        return ""


def connect_payloads(folder: str) -> dict:
    """Connect agents for a ready Agent Context, on each platform: with this copy
    first on PATH, and with another copy first; for a folder only PowerShell's
    registration command can carry; and a path no host can carry exactly. The
    PATH a new program would get is made up, so the payloads do not depend on
    this computer's."""
    from app import connect, on_path
    from app import manager as mg
    out = {}
    saved = os.environ.get("PATH", "")
    other = tempfile.mkdtemp(prefix="charter-ui-other-")
    open(os.path.join(other, "charter.cmd" if os.name == "nt" else "charter"), "w").close()
    if os.name != "nt":
        os.chmod(os.path.join(other, "charter"), 0o755)
    try:
        for name, path in (("", on_path.LAUNCHERS), ("_conflict", os.pathsep.join([other, on_path.LAUNCHERS]))):
            os.environ["PATH"] = path
            out["connect_windows" + name] = connect.connection(folder, windows=True,
                                                               registry=_Registry(path.replace(os.pathsep, ";")))
            out["connect_posix" + name] = connect.connection(folder, windows=False,
                                                             registry=_Registry(path.replace(os.pathsep, ";")))
        out["connect_other_copy"] = other
        # The header's Charter command status, in each state, from the same made-up PATHs.
        for name, path in (("ready", on_path.LAUNCHERS), ("other", os.pathsep.join([other, on_path.LAUNCHERS])),
                           ("missing", "")):
            os.environ["PATH"] = path
            out["command_" + name] = connect.command_status(windows=True, registry=_Registry(path.replace(os.pathsep, ";")),
                                                            python=r"C:\Program Files\Python 3.12\python.exe")
            out["command_" + name + "_posix"] = connect.command_status(windows=False)
        os.environ["PATH"] = on_path.LAUNCHERS
        odd = os.path.join(tempfile.mkdtemp(prefix="charter-ui-"), "R&D 100%")
        mg.create(odd, "Odd")
        out["connect_powershell_only"] = connect.connection(odd, windows=True,
                                                            registry=_Registry(on_path.LAUNCHERS))
        out["connect_files_only"] = connect.connection(odd, windows=True, registry=_Registry(on_path.LAUNCHERS),
                                                       python="C:\\Py\nthon\\python.exe")
        shutil.rmtree(os.path.dirname(odd))
    finally:
        os.environ["PATH"] = saved
        shutil.rmtree(other, ignore_errors=True)
    return out


LONG_SCOPE = ("Supplier selection, onboarding, contract renewal and termination for every external "
              "vendor, including the evidence each decision needs, the people who sign it off, how "
              "exceptions are recorded, how long records are kept, and how all of this applies to "
              "subcontractors, framework agreements, emergency purchases, sole-source justifications, "
              "pilot projects, open-source dependencies and any service that processes customer data "
              "on the project's behalf, wherever it is hosted and however it is paid for.")


def changeset_payloads() -> dict:
    """Real change-set payloads, from a context of their own: three governing
    documents, three candidates, a draft taken through every state."""
    from app import api_changeset as api
    from app import changeset as chs
    from app import private_store as ps
    from tests.changeset import setup
    from tests.impact import report_for
    folder, ctx, revision, newcomer, spare = setup()
    session = console.Session(folder)
    out: dict = {"cs_folder": folder}
    # Long scopes, as a person may write them: one line each, far longer than
    # a plan card is wide.
    from app import authority as au
    for path, scope in ((revision, LONG_SCOPE), (newcomer, "Delta: " + LONG_SCOPE)):
        p = au.plan(folder, "edit-candidate", {"candidate": path, "scope": scope})
        au.apply(folder, "edit-candidate", p.request, p.plan_id, True)
    out["cs_long_scope"] = LONG_SCOPE
    out["cs_drafts"] = {path: console.draft(session, {"path": path}) for path in (revision, newcomer)}
    # A blank candidate scope replacing a document inherits that document's.
    out["cs_blank"] = api.create(session, {"start": {"candidate": spare, "decision": "replace",
                                                     "target": "authoritative/c.md"}})
    created = api.create(session, {})
    out["cs_created"] = created
    did = created["draft"]["id"]
    out["cs_row"] = api.update(session, {"id": did, "revision": created["draft"]["revision"],
                                         "candidates": [revision]})
    valid = api.update(session, {"id": did, "revision": out["cs_row"]["draft"]["revision"],
                                 "title": "Restructure", "candidates": [revision, newcomer],
                                 "decisions": {revision: {"decision": "replace", "target": "authoritative/a.md"},
                                               newcomer: {"decision": "govern-alongside"}},
                                 "withdrawals": ["authoritative/b.md"]})
    out["cs_valid"] = valid
    out["cs_list"] = api.list_drafts(session, {})
    now = chs.Now(ctx)
    draft = chs.load(ctx, did)
    identity = chs.impact.context_identity(now)
    material = {c["path"]: c for c in chs.candidate_material(ctx, draft, now)}
    planned = chs.plan_fingerprint(draft)
    api.attach_report(session, {"id": did, "label": "Agent one",
                                "text": report_for(identity, material, planned)})
    out["cs_reports"] = api.attach_report(session, {"id": did, "label": "Agent two", "text": report_for(
        identity, material, planned, recommendations=[{"path": "authoritative/a.md", "action": "retain"}])})
    # A third review, added empty, then saved with text that is not a report:
    # kept as written, and never attached evidence.
    out["cs_review_added"] = api.add_review(session, {"id": did})
    out["cs_review_invalid"] = api.save_review(session, {
        "id": did, "report_id": out["cs_review_added"]["reports"][-1]["id"],
        "label": "Third agent", "text": "not a report"})
    out["cs_plan"] = console.plan(session, {"kind": "changeset", "request": {
        "draft_id": did, "draft_revision": out["cs_review_invalid"]["draft"]["revision"]}})
    p = au.plan(folder, "edit-candidate", {"candidate": newcomer, "scope": "Delta, narrower."})
    au.apply(folder, "edit-candidate", p.request, p.plan_id, True)
    out["cs_stale"] = api.get(session, {"id": did})
    out["cs_refreshed"] = api.refresh(session, {"id": did})
    # The person copied the review prompt before applying: a fact the receipt keeps.
    copied = api.prompt_copied(session, {"id": did, "mode": "self-contained",
                                         "plan_fingerprint": out["cs_refreshed"]["plan_fingerprint"]})
    plan = console.plan(session, {"kind": "changeset", "request": {
        "draft_id": did, "draft_revision": copied["draft"]["revision"]}})
    api.apply(session, {"id": did, "revision": copied["draft"]["revision"],
                        "plan_id": plan["plan_id"], "confirm": PHRASE})
    out["cs_applied"] = api.get(session, {"id": did})
    out["cs_applied_list"] = api.list_drafts(session, {})
    # A draft recorded in the earlier form: shown as recorded, then converted.
    from tests.changeset import _earlier_record
    earlier = _earlier_record(ctx, "00000000000000e1", candidates=[spare], outcomes={
        "authoritative/a.md": {"outcome": "retain"},
        "authoritative/c.md": {"outcome": "revise", "candidate": spare}})
    out["cs_earlier"] = api.get(session, {"id": earlier["id"]})
    out["cs_converted"] = api.convert(session, {"id": earlier["id"], "revision": earlier["revision"],
                                                "confirm": True})
    api.delete(session, {"id": earlier["id"], "confirm": True})
    # An active draft, an applied receipt and an abandoned draft: only the
    # first is counted in the navigation.
    gone = api.create(session, {})
    api.abandon(session, {"id": gone["draft"]["id"]})
    out["cs_mixed_list"] = api.list_drafts(session, {})
    out["cs_mixed_state"] = console.state(session)
    # A record that cannot be read is none of the groups: it is listed last.
    with open(ctx.cs.path(ps.CHANGESETS, "0123456789abcdef.json"), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    out["cs_unreadable_list"] = api.list_drafts(session, {})
    return out


# An existing document with front matter of its own, as another Agent Context
# exported it: everything but its title and scope is left behind.
EXPORTED = ('---\nid: supplier-policy\ntitle: "Supplier policy"\nstatus: active\nauthority: authoritative\n'
            'scope: "Supplier choice and onboarding."\nsource: "Imported from the old wiki"\n'
            'created: 2026-01-02\nupdated: 2026-03-04\nsupersedes:\n  - supplier-policy-v1\n'
            'superseded_by: []\n---\n\n# Supplier policy\n\nChoose suppliers with care.\n')
LEGACY = ('---\nid: old-rule\nstatus: active\nauthority: authoritative\ncreated: 2025-12-01\n---\n\n'
          'Old rule text.\n')


def conversion_payloads() -> dict:
    """Real answers for converting a file with front matter, and for editing a
    candidate filed before conversion removed it, from a context of their own."""
    import base64
    from app import authority as au
    from app import private_store as ps
    folder = context()
    session = console.Session(folder)
    out: dict = {"conv_folder": folder}
    out["stage_front_matter"] = console.stage(session, {
        "filename": "supplier-policy.md", "content_b64": base64.b64encode(EXPORTED.encode()).decode()})
    p = au.plan(folder, "add", {"title": "Old rule", "scope": "Old things.", "body": "Placeholder.\n"})
    au.apply(folder, "add", p.request, p.plan_id, True)
    logical = "authority-candidates/old-rule.md"
    cs = ps.PrivateState.default().for_context(folder)
    text = cs.read_candidate(logical).replace("Placeholder.\n", LEGACY)
    with open(cs.candidate_file(logical), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    out["legacy_path"] = logical
    out["legacy_draft"] = console.draft(session, {"path": logical})
    d = out["legacy_draft"]
    out["legacy_edit_plan"] = console.plan(session, {"kind": "edit-candidate", "request": {
        "candidate": logical, "title": d["title"], "scope": d["scope"], "body": d["body"]}})
    return out


def _dump(fixture: dict) -> str:
    handle = tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8", delete=False)
    with handle as fh:
        json.dump(fixture, fh)
    return handle.name


def _luminance(hexv: str) -> float:
    chans = [int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _token(css: str, name: str) -> str:
    import re
    m = re.search(name + r":\s*(#[0-9a-fA-F]{6})", css)
    if not m:
        raise AssertionError(f"token {name} not found in styles.css")
    return m.group(1)


def check_contrast() -> int:
    """Measured WCAG contrast for the secondary text, authority chip and rail
    focus ring (UI-08/UI-09)."""
    print("\n--- contrast (WCAG AA) ---")
    css = open(os.path.join(ROOT, "app", "static", "styles.css"), encoding="utf-8").read()
    failed = 0
    for label, fg, bg, minimum in (
            ("secondary text on the sunk surface", "--ink-faint", "--surface-sunk", 4.5),
            ("secondary text on the surface", "--ink-faint", "--surface", 4.5),
            ("authority chip text", "--brass-ink", "--brass-wash", 4.5),
            ("rail focus ring", "--focus-rail", "--ink", 3.0)):
        try:
            r = _ratio(_token(css, fg), _token(css, bg))
            ok = r >= minimum
        except AssertionError as exc:
            r, ok = 0.0, False
            print(f"  FAILED: {exc}")
        print(f"  {'ok' if ok else 'FAILED'} {label}: {r:.2f}:1 (need {minimum}:1)")
        failed |= 0 if ok else 1
    try:
        fg, bg = _error_dismiss_colours(css)
        r = _ratio(fg, bg)
        ok = r >= 4.5
    except AssertionError as exc:
        r, ok = 0.0, False
        print(f"  FAILED: {exc}")
    print(f"  {'ok' if ok else 'FAILED'} an error toast's Dismiss label on its button: {r:.2f}:1 (need 4.5:1)")
    failed |= 0 if ok else 1
    return failed


def _error_dismiss_colours(css: str) -> tuple:
    """The text and background an error toast's Dismiss button ends up with: the
    shared `.btn` treatment, then any rule naming `.toast-dismiss`, in order."""
    import re

    def colour(value: str) -> str:
        value = value.strip()
        m = re.fullmatch(r"var\((--[\w-]+)\)", value)
        if m:
            return _token(css, m.group(1))
        if re.fullmatch(r"#[0-9a-fA-F]{3}", value):
            return "#" + "".join(c * 2 for c in value[1:])
        if re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            return value
        raise AssertionError(f"unsupported colour {value!r} for the error toast's Dismiss button")

    found = {}
    plain = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", plain):
        names = [s.strip() for s in selectors.split(",")]
        if not any(n == ".btn" or ("toast-dismiss" in n and ".toast.error" in n.replace(" ", "")
                                   or n in (".toast .toast-dismiss", ".toast-dismiss")) for n in names):
            continue
        for prop, value in re.findall(r"(?:^|;)\s*(color|background(?:-color)?)\s*:\s*([^;]+)", body):
            found["fg" if prop == "color" else "bg"] = colour(value)
    if "fg" not in found or "bg" not in found:
        raise AssertionError("the shared .btn treatment's colour and background were not found")
    return found["fg"], found["bg"]


def run() -> int:
    if shutil.which("node") is None:
        print("SKIPPED: Node is not installed, so the page's own JavaScript cannot be run.\n"
              "         Install Node and re-run: python -m tests.ui")
        return 0
    if check_contrast():
        return 1
    with isolated_private_state():
        fixture = build_fixture()
        fixture.update(changeset_payloads())
        fixture.update(conversion_payloads())
        path = _dump(fixture)
        failed = 0
        try:
            for script, args in (("markdown.test.js", []), ("ui.test.js", [path])):
                print(f"\n--- {script} ---")
                failed |= subprocess.run(["node", os.path.join(HERE, script), *args],
                                         cwd=ROOT).returncode
        finally:
            os.remove(path)
            shutil.rmtree(fixture["folder"], ignore_errors=True)
            shutil.rmtree(fixture["cs_folder"], ignore_errors=True)
            shutil.rmtree(fixture["conv_folder"], ignore_errors=True)
    if failed:
        return 1
    print("\nAll front-end checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
