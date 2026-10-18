"""The Charter console's API and server.
Run: python -m tests.console

The API is checked directly and over real HTTP. The page itself is checked by
`python -m tests.ui`, against this API's real answers.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import api_changeset as api  # noqa: E402
from app import console  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import server  # noqa: E402
from tests.agent_context import context, doc_text, read, snapshot, write  # noqa: E402
from tests.harness import isolated_private_state  # noqa: E402

OK = "ok"
PHRASE = "change governing context"


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def refused(fn, *args) -> str:
    try:
        fn(*args)
    except console.ApiError as exc:
        return exc.message
    return ""


def do(session, kind, request, confirm=None):
    plan = console.plan(session, {"kind": kind, "request": request})
    if confirm is None:
        confirm = PHRASE if plan["confirm_phrase"] else True
    return plan, console.apply(session, {"kind": kind, "request": request,
                                         "plan_id": plan["plan_id"], "confirm": confirm})


def case_api() -> None:
    print("\nthe console API")
    with isolated_private_state():
        folder = context()
        session = console.Session()
        closed = console.state(session)
        check(not closed["open"] and "documents" not in closed, "with nothing open, the page is told so")
        check("Choose the Agent Context folder" in refused(console.open_context, session, {}),
              "opening needs a folder")
        empty = os.path.join(os.path.dirname(folder), os.path.basename(folder) + "-new")
        check("Name the project" in refused(console.create_context, session,
                                            {"path": empty, "project_name": "  "})
              and not os.path.exists(empty), "creating needs a project name, and writes nothing without one")
        console.open_context(session, {"path": folder})
        st = console.state(session)
        check(st["open"] and st["status"]["agents_served"] and
              [d["path"] for d in st["documents"] if d["governing"]] ==
              ["authoritative/a.md", "authoritative/b.md"], "an opened Agent Context is described")
        check({d["location"] for d in st["documents"]} == {"Agent Context"},
              "governing documents are said to be in the Agent Context")

        plan, _ = do(session, "add", {"title": "Gamma rules", "scope": "Gamma.", "body": "Rule.\n"})
        check(plan["changes"][0]["reason"] == "Private local state — not agent-visible",
              "a candidate's change is labelled private, not agent-visible")
        st = console.state(session)
        candidate = next(d for d in st["documents"] if d["kind"] == "candidate")
        check(candidate["path"] == "authority-candidates/gamma-rules.md"
              and candidate["location"] == "private state", "candidates are listed as private")
        before = snapshot(folder)
        for kind, request in (("grant", {"candidate": candidate["path"]}),
                              ("replace", {"candidate": candidate["path"], "replaces": "authoritative/a.md"}),
                              ("withdraw", {"path": "authoritative/a.md"})):
            for route in (console.plan, console.apply):
                try:
                    route(session, {"kind": kind, "request": request, "plan_id": "0" * 20, "confirm": PHRASE})
                    got = None
                except console.ApiError as exc:
                    got = exc
                check(got is not None and got.status == 409 and got.payload.get("change_set_only")
                      and "only through a change set" in got.message,
                      f"a page from before asking to {route.__name__} `{kind}` is told to use a change set")
        check(snapshot(folder) == before
              and candidate["path"] in [d["path"] for d in console.state(session)["documents"]],
              "and nothing was written")

        made = api.create(session, {"start": {"candidate": candidate["path"]}})
        draft = api.update(session, {"id": made["draft"]["id"], "revision": made["draft"]["revision"],
                                     "decisions": {candidate["path"]: {"decision": "govern-alongside"}}})["draft"]
        request = {"draft_id": draft["id"], "draft_revision": draft["revision"]}
        plan = console.plan(session, {"kind": "changeset", "request": request})
        check(plan["confirm_phrase"] == PHRASE and plan["governing_change"]
              and {c["reason"] for c in plan["changes"]} ==
              {"Agent Context — what agents read", "Private local state — not agent-visible"},
              "a change set started from a candidate previews, saying which writes agents will read")
        check("only through a change set" in refused(console.apply, session, {
                  "kind": "changeset", "request": request, "plan_id": plan["plan_id"], "confirm": PHRASE})
              and snapshot(folder) == before,
              "a change set is never applied through the general route, which does not hold its lock")
        check("Type" in refused(api.apply, session, {"id": draft["id"], "revision": draft["revision"],
                                                     "plan_id": plan["plan_id"], "confirm": True}),
              "its own route needs the typed phrase")
        stale = dict(plan)
        write(folder, "authoritative/b.md", doc_text("b", "Beta", body="Edited outside.\n"))
        try:
            api.apply(session, {"id": draft["id"], "revision": draft["revision"],
                                "plan_id": stale["plan_id"], "confirm": PHRASE})
            got = None
        except console.ApiError as exc:
            got = exc
        check(got is not None and "not valid" in got.message,
              "a preview applied after an outside edit is refused: the context is not valid now")
        st = console.state(session)
        check(not st["status"]["agents_served"] and st["status"]["rebuild"]["available"],
              "an outside edit leaves agents refused, with Rebuild offered")

        draft = console.draft(session, {"path": candidate["path"]})
        check(draft["title"] == "Gamma rules" and draft["body"] == "Rule.\n",
              "a candidate's draft is its title, scope and text")
        check("Only a governing document" in refused(console.draft, session,
                                                    {"path": "../outside.md"}),
              "nothing else can be drafted from")
        shown = console.preview(session, {"source": "document", "path": candidate["path"]})
        check(shown["state"] == "candidate" and "not context" in shown["banner"]["title"],
              "a candidate is read with a banner saying it is not context")
        check("Only documents" in refused(console.preview, session,
                                          {"source": "document", "path": "AGENTS.md"}),
              "a path the page does not list is refused")
        staged = console.stage(session, {"filename": "notes.md",
                                         "content_b64": "IyBTaXRlIG5vdGVzCgpUZXh0Lgo="})
        check(staged["suggested_title"] == "Site notes" and staged["markdown"] == "# Site notes\n\nText.\n",
              "a staged file is converted, its heading kept, and nothing is written")
        check(not os.path.exists(os.path.join(folder, "authority-candidates")),
              "no candidate folder ever appears in the Agent Context")
        shutil.rmtree(folder)


LEGACY_KEYS = ("id", "status", "authority", "source", "source_sha256", "created", "updated", "supersedes",
               "superseded_by", "revises")


def stage_text(session, name: str, data) -> dict:
    raw = data if isinstance(data, bytes) else data.encode("utf-8")
    return console.stage(session, {"filename": name, "content_b64": base64.b64encode(raw).decode()})


def case_stage_front_matter() -> None:
    print("\nconverting a file with front matter: title and scope suggested, nothing else carried over")
    with isolated_private_state():
        folder = context()
        session = console.Session(folder)
        exported = ('---\nid: supplier-policy\ntitle: "Supplier policy"\nstatus: active\nauthority: authoritative\n'
                    'scope: "Supplier choice and onboarding."\nsource: "Imported from the old wiki"\n'
                    'source_sha256: 0123abcd\ncreated: 2026-01-02\nupdated: 2026-03-04\nsupersedes:\n'
                    '  - supplier-policy-v1\nsuperseded_by: []\nrevises: old\n---\n\n# Supplier policy\n\n'
                    'Choose suppliers with care.\n')
        staged = stage_text(session, "supplier-policy.md", exported)
        check(staged["suggested_title"] == "Supplier policy"
              and staged["suggested_scope"] == "Supplier choice and onboarding.",
              "an exported governing document: its title and scope are suggested")
        check(staged["markdown"] == "# Supplier policy\n\nChoose suppliers with care.\n"
              and not any(f"{k}:" in staged["markdown"] for k in LEGACY_KEYS),
              "its front matter is gone from the text, its heading stays, and none of its other "
              "metadata is text")
        check(staged["front_matter"] == {"removed": True, "used": ["title", "scope"],
                                         "dropped": list(LEGACY_KEYS)}
              and any("Not carried over: id, status" in n for n in staged["notes"])
              and not any("only front matter is added" in n for n in staged["notes"]),
              "and it says what was used and what was not carried over")

        windows = ("﻿" + "---\r\ntitle: Windows file\r\nscope: From Windows.\r\n---\r\n\r\nBody.\r\n")
        staged = stage_text(session, "win.md", windows.encode("utf-8"))
        check(staged["suggested_title"] == "Windows file" and staged["suggested_scope"] == "From Windows."
              and staged["markdown"] == "Body.\n",
              "a byte-order mark and CRLF line endings are handled")

        staged = stage_text(session, "blank.md", "\n\n   \n---\ntitle: After blanks\n---\nText.\n")
        check(staged["suggested_title"] == "After blanks" and staged["markdown"] == "Text.\n",
              "leading blank lines before the block are allowed")

        unclosed = "---\ntitle: Never closed\nscope: Nope.\n\nText.\n"
        staged = stage_text(session, "unclosed.md", unclosed)
        check(staged["front_matter"] is None and staged["markdown"] == unclosed
              and staged["suggested_scope"] == "" and staged["suggested_title"] == "unclosed",
              "a block that is never closed is ordinary text: kept, nothing suggested")

        rule = "---\nSome prose after a thematic break.\n---\n\nMore.\n"
        staged = stage_text(session, "rule.md", rule)
        check(staged["front_matter"] is None and staged["markdown"] == rule,
              "Markdown that opens with a thematic break is kept exactly")

        odd = "---\ntitle: \"Line one\\nLine two\"\nscope:\n  - a\n  - b\n---\n# Heading title\n\nText.\n"
        staged = stage_text(session, "odd.md", odd)
        check(staged["front_matter"]["used"] == [] and set(staged["front_matter"]["dropped"]) == {"title", "scope"}
              and staged["suggested_scope"] == "" and staged["suggested_title"] == "Heading title"
              and staged["markdown"] == "# Heading title\n\nText.\n",
              "a multi-line title or list-valued scope is not suggested, and the block is still removed")

        jekyll = "---\nlayout: post\npermalink: /notes/\n---\n\nNotes text.\n"
        staged = stage_text(session, "notes.md", jekyll)
        check(staged["front_matter"] == {"removed": True, "used": [], "dropped": ["layout", "permalink"]}
              and staged["markdown"] == "Notes text.\n" and staged["suggested_title"] == "notes"
              and staged["suggested_scope"] == "",
              "a Jekyll-only block is removed, suggesting nothing")

        differs = "---\ntitle: Front title\n---\n# A different heading\n\nText.\n"
        staged = stage_text(session, "differs.md", differs)
        check(staged["suggested_title"] == "Front title"
              and staged["markdown"] == "# A different heading\n\nText.\n",
              "a heading that differs from the suggested title stays in the text")

        staged = stage_text(session, "plain.md", "# Plain title\n\nPlain text.\n")
        check(staged["front_matter"] is None and staged["suggested_title"] == "Plain title"
              and staged["markdown"] == "# Plain title\n\nPlain text.\n" and staged["suggested_scope"] == "",
              "a leading # heading suggests the title and stays in the text, as a proposal's body keeps it")
        check(not os.path.exists(os.path.join(folder, "authority-candidates"))
              and not ps.PrivateState.default().for_context(folder).candidates(),
              "staging writes nothing")
        shutil.rmtree(folder)


def case_recent_while_open() -> None:
    print("\nRecent: the console's state offers Agent Contexts opened here, whether or not one is open")
    with isolated_private_state():
        folder = context()
        session = console.Session()
        console.open_context(session, {"path": folder})
        opened = console.state(session)
        check(opened["open"] and folder in opened.get("recent", []),
              "with an Agent Context open, its state still lists Recent, so Open Agent Context… shows it")
        closed = console.state(console.Session())
        check(not closed["open"] and folder in closed.get("recent", []),
              "with none open, Recent lists the same Agent Contexts")
        shutil.rmtree(folder)


def case_clear_recent() -> None:
    print("\nClear Recent: the list empties, and every Agent Context and its private state stay")
    with isolated_private_state() as root:
        folder, other = context(), context()
        session = console.Session()
        console.open_context(session, {"path": other})
        console.open_context(session, {"path": folder})
        cs = ps.PrivateState.default().for_context(folder)
        before = sorted(os.listdir(cs.base))
        console.clear_recent(session, {})
        state = console.state(session)
        check(state["open"] and state["root"] == folder and state["recent"] == [],
              "Clear empties Recent, and the open Agent Context stays open")
        check(sorted(os.listdir(cs.base)) == before
              and os.path.normcase(folder) in map(os.path.normcase, ps.PrivateState.default().known_contexts()),
              "its private state is untouched")
        check(console.state(console.Session())["recent"] == [], "Recent stays cleared for a later console")
        console.open_context(console.Session(), {"path": other})
        check(console.state(session)["recent"] == [other],
              "opening an Agent Context again lists it again, and only it")
        shutil.rmtree(folder)
        shutil.rmtree(other)


def case_recent_order() -> None:
    print("\nRecent: the most recently opened Agent Context first")
    with isolated_private_state():
        first, second, third = context(), context(), context()
        session = console.Session()
        for folder in (first, second, third):
            console.open_context(session, {"path": folder})
        check(console.state(session)["recent"] == [third, second, first],
              "the last opened heads Recent, then the one before it")
        console.open_context(session, {"path": first})
        check(console.state(console.Session())["recent"] == [first, third, second],
              "opening an Agent Context again moves it to the top, for a later console too")
        created = os.path.join(tempfile.mkdtemp(prefix="charter-new-"), "new")
        os.makedirs(created)
        console.create_context(session, {"path": created, "project_name": "New"})
        check(console.state(session)["recent"][0] == session.folder, "creating one puts it first")
        for folder in (first, second, third, os.path.dirname(created)):
            shutil.rmtree(folder)


def case_import_duplicate() -> None:
    print("\nimporting an exact duplicate of a waiting proposal: named for the person, replaced in place")
    with isolated_private_state():
        from app import agent_proposals as apx
        folder = context()
        session = console.Session(folder)
        text = json.dumps({"agent": "chat-agent", "operation": "create",
                           "target_path": "authority-candidates/waiting.md", "reason": "Needed.",
                           "proposed_meta": {"title": "Waiting rule"}, "proposed_body": "# Waiting rule\n\nText.\n"})
        filed = apx.file(folder, json.loads(text), source=apx.AGENT, submitted=text.encode("utf-8"))
        check(filed["result"] == "pending", "an agent files it through `charter propose`")
        cs = ps.PrivateState.default().for_context(folder)
        pending = os.path.join(cs.base, ps.PROPOSALS, apx.PENDING)
        before = sorted(os.listdir(pending))
        dup = console.import_file(session, {"json": text, "confirm": True})
        check(dup["result"] == "duplicate"
              and dup["waiting"] == {"proposal_id": filed["proposal_id"], "title": "Waiting rule"}
              and sorted(os.listdir(pending)) == before,
              "the same text imported is not filed: the person is told which proposal waits, by its title")
        check(console.import_file(session, {"json": text + "\n", "confirm": True})["result"] == "pending",
              "a trailing newline makes it a distinct proposal")
        replaced = console.import_file(session, {"json": text, "confirm": True,
                                                 "replace": filed["proposal_id"]})
        listed = apx.listing(folder)
        same = [p for p in listed["pending"] + listed["imported"] if p["proposal_id"] == filed["proposal_id"]]
        check(replaced == {"result": "pending", "proposal_id": filed["proposal_id"]}
              and len(same) == 1 and same[0]["source"] == apx.IMPORTED
              and len(os.listdir(pending)) == len(before) + 1,
              "Replace updates that proposal in place, now imported: still one, and no extra record")
        check(console.import_file(session, {"json": text + "  ", "confirm": True,
                                            "replace": filed["proposal_id"]})["result"] == "refused",
              "only an identical submission can replace it")
        shutil.rmtree(folder)


def case_stage_leaves_nothing() -> None:
    print("\nconverting an upload keeps nothing on this computer, so abandoning it leaves nothing to clean up")

    def tree(root: str) -> dict:
        out = {}
        for base, _dirs, files in os.walk(root):
            for name in files:
                path = os.path.join(base, name)
                with open(path, "rb") as fh:
                    out[os.path.relpath(path, root)] = fh.read()
        return out

    with isolated_private_state() as state_root:
        folder = context()
        session = console.Session(folder)
        console.state(session)  # the private state an open Agent Context ordinarily has
        before_state, before_folder = tree(state_root), tree(folder)
        answers = [stage_text(session, "site-notes.md", "# Site notes\n\nGround conditions.\n"),
                   stage_text(session, "notes.txt", "Plain notes.\n"),
                   stage_text(session, "fm.md", "---\ntitle: T\nscope: S.\n---\nBody.\n")]
        check(tree(state_root) == before_state and tree(folder) == before_folder,
              "staging three files writes nothing to the Agent Context or Charter's private state")
        check(all(set(a) == {"filename", "kind", "bytes", "sha256", "markdown", "notes", "suggested_title",
                             "suggested_scope", "front_matter"} for a in answers),
              "the answer is the converted text itself, with no upload or session id that would need cleaning up")
        shutil.rmtree(folder)


def _http(port: int, method: str, path: str, body=None, header=True):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if header:
        req.add_header("X-Charter-Console", "person")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def case_command_route() -> None:
    print("\nthe Charter command status: its own route, independent of the Agent Context's health")
    from app import connect
    other = tempfile.mkdtemp(prefix="charter-other-")
    found = {"ready": os.path.join(connect.on_path.LAUNCHERS, "charter.cmd" if os.name == "nt" else "charter"),
             "other": os.path.join(other, "charter.cmd" if os.name == "nt" else "charter"), "missing": None}
    real = connect.found_by_name
    with isolated_private_state():
        folder = context()
        session = console.Session(folder)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(session))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            status, _ = _http(port, "GET", "/api/command", header=False)
            check(status == 403, "it answers only the console's own page")
            for health in ("ready", "unclean"):
                if health == "unclean":
                    write(folder, "notes.txt", b"mine")
                served = json.loads(_http(port, "GET", "/api/state")[1])["status"]["agents_served"]
                for state, path in found.items():
                    connect.found_by_name = lambda windows, registry=None, p=path: p
                    status, body = _http(port, "GET", "/api/command")
                    c = json.loads(body)
                    check(status == 200 and c["state"] == state and folder not in body.decode()
                          and (state == "ready") == ("remedy" not in c),
                          f"context {health} (agents {'served' if served else 'refused'}), `charter` "
                          f"{state}: Charter command {state}, from PATH alone")
                    after = json.loads(_http(port, "GET", "/api/state")[1])["status"]["agents_served"]
                    check(after == served, "and the Agent Context's own status is unchanged by it")
            connect.found_by_name = lambda windows, registry=None: found["other"]
            d = json.loads(_http(port, "GET", "/api/diagnostics")[1])
            check(d["on_path"]["text"] == f"another copy, from {other}" and set(d["on_path"]) == {"this_copy", "text"},
                  "Diagnostics states which copy `charter` runs, as a fact, without the remedy")
        finally:
            connect.found_by_name = real
            httpd.shutdown()
            httpd.server_close()
            shutil.rmtree(other, ignore_errors=True)
        shutil.rmtree(folder)


def case_server() -> None:
    print("\nthe console server")
    with isolated_private_state():
        folder = context()
        session = console.Session(folder)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(session))
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            status, body = _http(port, "GET", "/")
            check(status == 200 and b"Charter" in body, "the page is served")
            status, _ = _http(port, "GET", "/workspace.js")
            check(status == 404, "the surfaces page script is gone")
            status, body = _http(port, "GET", "/api/state", header=False)
            check(status == 403, "state, which shows private local state, answers only the console")
            status, body = _http(port, "GET", "/api/state")
            check(status == 200 and json.loads(body)["open"], "the console's own page is answered")
            status, _ = _http(port, "POST", "/api/apply", {"kind": "add"}, header=False)
            check(status == 403, "an action from anywhere else is refused")
            for route in ("/api/plan", "/api/apply"):
                status, body = _http(port, "POST", route, {"kind": "grant", "request": {
                    "candidate": "authority-candidates/x.md"}, "plan_id": "0" * 20, "confirm": PHRASE})
                check(status == 409 and json.loads(body).get("change_set_only"),
                      f"`{route}` answers an old page's direct grant: use a change set")
            for gone in ("/api/surface/publish", "/api/identity/overview", "/api/migration/preview",
                         "/api/cgu-changes/commit", "/api/integrations/apply"):
                status, _ = _http(port, "POST", gone, {})
                check(status == 404, f"`{gone}` no longer exists")
        finally:
            httpd.shutdown()
            httpd.server_close()
        shutil.rmtree(folder)


def case_page_routes() -> None:
    print("\nevery route the page calls is served, and Add a review works through the server")
    page = open(os.path.join(server.STATIC_DIR, "app.js"), encoding="utf-8").read()
    called = set(re.findall(r"""["'](/api/[a-z0-9/_-]+)["']""", page))
    unserved = sorted(p for p in called if p not in server.POST_ROUTES and p not in console.GET_ROUTES)
    check(len(called) > 20 and not unserved,
          f"each of the page's {len(called)} API paths is a registered route"
          + (f" — not served: {', '.join(unserved)}" if unserved else ""))
    check("/api/changeset/review/add" in called and "/api/changeset/review/add" in server.POST_ROUTES,
          "the page's Add a review route is registered with the server")
    with isolated_private_state():
        folder = context()
        session = console.Session(folder)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(session))
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            status, body = _http(port, "POST", "/api/changeset/create", {})
            made = json.loads(body)
            check(status == 200 and made["reports"] == [], "a new draft has no review")
            status, body = _http(port, "POST", "/api/changeset/review/add", {"id": made["draft"]["id"]})
            added = json.loads(body)
            check(status == 200 and len(added.get("reports", [])) == 1
                  and added["reports"][0]["label"] == "" and added["reports"][0]["text"] == "",
                  "Add a review, through the server, adds one empty review")
            status, body = _http(port, "POST", "/api/changeset/review/add", {})
            check(status == 400 and b"Unknown endpoint" not in body,
                  "a request without a draft is refused by the route, not as an unknown endpoint")
        finally:
            httpd.shutdown()
            httpd.server_close()
        shutil.rmtree(folder)


def case_change_set_count() -> None:
    print("\nthe navigation's change-set count: active drafts only")
    from app import authority as au
    from tests.changeset import setup
    with isolated_private_state():
        folder, ctx, _revision, newcomer, spare = setup()
        session = console.Session(folder)
        check(console.state(session)["change_sets"] == {"active": 0}
              and api.list_drafts(session, {})["drafts"] == [],
              "with no change set, the count is 0 and the index has nothing to group")
        waiting = api.create(session, {})
        stale = api.create(session, {"start": {"candidate": spare, "decision": "govern-alongside"}})
        started = api.create(session, {"start": {"candidate": newcomer}})
        ready = api.update(session, {"id": started["draft"]["id"], "revision": started["draft"]["revision"],
                                     "decisions": {newcomer: {"decision": "govern-alongside"}}})
        plan = console.plan(session, {"kind": "changeset", "request": {
            "draft_id": ready["draft"]["id"], "draft_revision": ready["draft"]["revision"]}})
        api.apply(session, {"id": ready["draft"]["id"], "revision": ready["draft"]["revision"],
                            "plan_id": plan["plan_id"], "confirm": PHRASE})
        abandoned = api.create(session, {})
        api.abandon(session, {"id": abandoned["draft"]["id"]})
        p = au.plan(folder, "edit-candidate", {"candidate": spare, "scope": "Spare, changed."})
        au.apply(folder, "edit-candidate", p.request, p.plan_id, True)
        with open(ctx.cs.path(ps.CHANGESETS, "0123456789abcdef.json"), "w", encoding="utf-8") as fh:
            fh.write("{not json")
        listed = api.list_drafts(session, {})["drafts"]
        states = {d["id"]: d.get("state", "unreadable") for d in listed}
        check(sorted(states.values()) == ["abandoned", "active", "active", "applied", "unreadable"],
              "there are two active drafts, an applied one, an abandoned one and an unreadable record")
        check(states[abandoned["draft"]["id"]] == "abandoned" and states[ready["draft"]["id"]] == "applied"
              and "final_outcomes" in next(d for d in listed if d["id"] == ready["draft"]["id"])
              and "final_outcomes" not in next(d for d in listed if d["id"] == abandoned["draft"]["id"]),
              "the index tells an abandoned draft from an applied change set, which alone has a receipt")
        now_stale = api.get(session, {"id": stale["draft"]["id"]})
        check(bool(now_stale["stale"]) and api.get(session, {"id": waiting["draft"]["id"]})["lifecycle"]
              != "structurally valid", "one active draft is stale and the other is incomplete")
        check(console.state(session)["change_sets"] == {"active": 2},
              "both count; the applied receipt, the abandoned draft and the unreadable record do not")
        shutil.rmtree(folder)


def case_request_boundary() -> None:
    print("\nthe request trust boundary: Host, Origin, a per-launch token, and safe errors")
    with isolated_private_state():
        folder = context()
        session = console.Session(folder)
        token = "test-token-1234567890"
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(session, token))
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()

        def req(method, path, body=None, host=None, origin=None, console_header=True, tok=token):
            data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
            r = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
            r.add_header("Host", host if host is not None else f"127.0.0.1:{port}")
            if body is not None:
                r.add_header("Content-Type", "application/json")
            if origin is not None:
                r.add_header("Origin", origin)
            if console_header:
                r.add_header("X-Charter-Console", "person")
            if tok is not None:
                r.add_header("X-Charter-Console-Token", tok)
            try:
                with urllib.request.urlopen(r, timeout=10) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as exc:
                return exc.code, exc.read()

        try:
            status, body = req("GET", "/api/state")
            check(status == 200 and json.loads(body)["open"],
                  "the console's own request — right Host and token — is answered")
            for bad in ("evil.example", f"evil.example:{port}", "127.0.0.1:1",
                        f"127.0.0.1.attacker.test:{port}"):
                status, _ = req("GET", "/api/state", host=bad)
                check(status == 403, f"a foreign Host ({bad}) is refused — a rebinding page cannot read state")
            status, page = req("GET", "/", console_header=False, tok=None)
            check(status == 200 and token.encode() in page,
                  "the page is served to the right Host and carries the per-launch token for its own use")
            status, _ = req("GET", "/", host="evil.example")
            check(status == 403, "the page itself is not served to a foreign Host, so the token cannot be read cross-origin")
            status, _ = req("GET", "/api/state", tok=None)
            check(status == 403, "without the per-launch token, an API request is refused even with the console header")
            status, _ = req("GET", "/api/state", tok="wrong")
            check(status == 403, "a wrong token is refused")
            earlier = urllib.request.Request(f"http://127.0.0.1:{port}/api/state", method="GET")
            earlier.add_header("X-ACM-Console", "person")
            earlier.add_header("X-ACM-Console-Token", token)
            try:
                with urllib.request.urlopen(earlier, timeout=10) as resp:
                    status = resp.status
            except urllib.error.HTTPError as exc:
                status = exc.code
            check(status == 403 and server.TOKEN_HEADER == "X-Charter-Console-Token"
                  and console.CONSOLE_HEADER == "X-Charter-Console"
                  and server.TOKEN_PLACEHOLDER == b"__CHARTER_CONSOLE_TOKEN__",
                  "the console's headers are Charter's: the earlier name's headers, even with the "
                  "right token, are refused")
            status, _ = req("POST", "/api/proposals", {}, origin="http://evil.example")
            check(status == 403, "a POST carrying a foreign Origin is refused")
            status, _ = req("POST", "/api/proposals", {}, origin=f"http://127.0.0.1:{port}")
            check(status == 200, "a POST from the console's own Origin is allowed")
            # B5: an unexpected failure is a generic 500 — never exception text or a local path.
            status, raw = req("POST", "/api/plan", b"[" * 60000)
            text = raw.decode("utf-8", "replace")
            check(status == 500 and "unexpected problem" in text and "RecursionError" not in text
                  and "Traceback" not in text and "authority-candidates" not in text,
                  "an unexpected error is a generic 500, with no exception name or local path")
            # B4: a non-finite JSON value in an imported proposal is a clean refusal, not a 500.
            inner = ('{"agent":"a","operation":"create","target_path":"authority-candidates/n.md",'
                     '"reason":"r","proposed_body":"x","expected_context_impact":[Infinity]}')
            status, raw = req("POST", "/api/proposals/import/check", {"json": inner})
            check(status == 400, "a non-finite value inside an imported proposal is refused as not valid JSON, not a 500")
        finally:
            httpd.shutdown()
            httpd.server_close()
        shutil.rmtree(folder)


def case_busy_port() -> None:
    print("\na second serve on a busy port is refused cleanly, with a non-zero exit")
    with isolated_private_state():
        folder = context()
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if os.name == "nt":
            holder.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        holder.bind(("127.0.0.1", 0))
        port = holder.getsockname()[1]
        holder.listen()
        try:
            rc, raised = None, False
            try:
                rc = server.serve(folder, port=port)  # bind must fail fast, never serve_forever
            except OSError:
                raised = True
            check(not raised and rc not in (0, None),
                  "the busy port is reported and serve returns a non-zero exit, not a traceback")
        finally:
            holder.close()
        shutil.rmtree(folder)


def case_restart_port() -> None:
    print("\na console stopped after serving the page restarts at once on the same port")
    with isolated_private_state():
        folder = context()
        session = console.Session()
        console.open_context(session, {"path": folder})
        httpd = server.ConsoleServer(("127.0.0.1", 0), server.make_handler(session))
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        for _ in range(3):  # the server closes each connection, leaving it in TIME_WAIT
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10).read()
        httpd.shutdown()
        httpd.server_close()
        thread.join(10)
        if os.name == "nt":
            check(not server.ConsoleServer.allow_reuse_address,
                  "on Windows the port is still taken exclusively, never shared")
        else:
            again = None
            try:
                again = server.ConsoleServer(("127.0.0.1", port), server.make_handler(session))
            except OSError:
                pass
            check(again is not None, "the restarted console binds the port its last run used")
            if again is not None:
                again.server_close()
            holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            holder.bind(("", 0))
            busy = holder.getsockname()[1]
            holder.listen()
            try:
                refused = False
                try:
                    server.ConsoleServer(("127.0.0.1", busy), server.make_handler(session)).server_close()
                except OSError:
                    refused = True
                check(refused, "a port another program listens on, on every address, is still refused")
            finally:
                holder.close()
        shutil.rmtree(folder)


def case_banner_piped() -> None:
    print("\nthe console's address is written at once, also when its output is not a terminal")
    import subprocess
    import tempfile
    tmp = tempfile.mkdtemp(prefix="charter-banner-")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    launch = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_launch.py")
    proc = subprocess.Popen([sys.executable, launch, tmp, "serve", "--port", str(port)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    seen = []

    def read() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            seen.append(line.decode("utf-8", "replace"))
            if "open:" in seen[-1]:
                return
    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        reader.join(30)
        running = proc.poll() is None
        check(running and any(f"open:          http://127.0.0.1:{port}" in s for s in seen),
              "piped, as by an agent host or `> log`: the address arrives while the console runs")
    finally:
        proc.kill()
        proc.wait(30)
        proc.stdout.close()  # type: ignore[union-attr]
        shutil.rmtree(tmp, ignore_errors=True)


def case_candidate_lineage() -> None:
    print("\ncandidate lineage, source, competing revisions, and comparison (console-only)")
    from app import agent_context as ac
    from app import agent_proposals as apx
    from app import authority as au
    with isolated_private_state():
        folder = context()  # governing authoritative/a.md (Alpha), b.md (Beta)
        session = console.Session(folder)
        r = au.plan(folder, "revise", {"path": "authoritative/a.md", "title": "Alpha (revise)",
                                       "scope": "", "body": "Revised alpha body.\n"})
        au.apply(folder, "revise", r.request, r.plan_id, True)
        a_sha = ac.sha256_text(read(folder, "authoritative/a.md").decode("utf-8"))
        pid = apx.file(folder, {"agent": "codex", "operation": "amend",
                                "target_path": "authoritative/a.md", "reason": "Clarify.",
                                "base_sha256": a_sha,
                                "replacements": [{"find": "Body.", "replace": "Proposed alpha body."}],
                                "proposed_meta": {"title": "Alpha (proposed)"}})["proposal_id"]
        ap = au.plan(folder, "accept-proposal", {"proposal_id": pid})
        au.apply(folder, "accept-proposal", ap.request, ap.plan_id, True)

        docs = console.state(session)["documents"]
        cands = [d for d in docs if d["kind"] == "candidate"]
        rev = next(d for d in cands if d["source_kind"] == "revise")
        prop = next(d for d in cands if d["source_kind"] == "proposal")
        check(rev["revises_path"] == "authoritative/a.md" and rev["revises_title"] == "Alpha",
              "a Revise candidate records the governing document it revises, resolved to its title")
        check(prop["revises_path"] == "authoritative/a.md" and prop["revises_title"] == "Alpha",
              "a proposal-amendment candidate records the same revision lineage")
        check(rev["co_revisions"] == 1 and prop["co_revisions"] == 1,
              "each flags one other revision candidate for the same document")

        c1 = console.compare(session, {"candidate": rev["path"], "against": "authoritative/a.md"})
        check(c1["diff"] and c1["right"]["title"] == "Alpha" and "Revised alpha body" in c1["diff"],
              "compare: a candidate against the governing document it revises")
        c2 = console.compare(session, {"candidate": rev["path"], "against": prop["path"]})
        check(c2["diff"] and "Revised alpha body" in c2["diff"] and "Proposed alpha body" in c2["diff"],
              "compare: competing revision candidates, both bodies shown")
        try:
            console.compare(session, {"candidate": rev["path"], "against": "authoritative/zzz.md"})
            refused_bad = False
        except console.ApiError:
            refused_bad = True
        check(refused_bad, "comparing against something the page does not list is refused")

        # The agent-facing map and metadata carry governing documents only: no
        # candidate title, and no per-document "revises" lineage key. (The map's
        # fixed proposal instructions legitimately use the words "Agent Proposal".)
        mp = read(folder, ac.CONTEXT_MAP).decode("utf-8")
        md = read(folder, ac.METADATA).decode("utf-8")
        check("Alpha (revise)" not in mp and "Alpha (proposed)" not in mp
              and "Alpha (revise)" not in md and "Alpha (proposed)" not in md
              and "revises" not in md,
              "candidate titles and revision lineage are never written into the agent-facing map or metadata")
        shutil.rmtree(folder)


def case_candidate_sources() -> None:
    print("\neach candidate's source tag: what Charter knows, never an invented identity")
    from app import agent_context as ac
    from app import authority as au
    from tests.changeset import setup
    src = console.candidate_source
    check(src({"source": "Agent Proposal p-1 (codex, self-reported)"}) == ("proposal", "codex")
          and src({"source": "Agent Proposal p-1 (, self-reported)"}) == ("proposal", "")
          and src({"source": "Agent Proposal p-1"}) == ("proposal", ""),
          "an Agent Proposal names its self-reported agent only when one was supplied")
    check(src({au.REVISES: "a"}) == ("revise", "") and src({}) == ("create", "")
          and src({"source": "Created from notes.md"}) == ("create", ""),
          "a Revise candidate is a revision; one a person created directly is created by a person")
    check(src({"source": au.WITHDRAWN_SOURCE}) == ("withdrawn", "")
          and src({"supersedes": [], "superseded_by": []}) == ("withdrawn", ""),
          "a withdrawn governing document is recognised, including one withdrawn before this was recorded")
    with isolated_private_state():
        folder, ctx, _revision, _newcomer, _spare = setup()
        session = console.Session(folder)
        made = api.create(session, {"start": {"withdraw": "authoritative/c.md"}})
        plan = console.plan(session, {"kind": "changeset", "request": {
            "draft_id": made["draft"]["id"], "draft_revision": made["draft"]["revision"]}})
        api.apply(session, {"id": made["draft"]["id"], "revision": made["draft"]["revision"],
                            "plan_id": plan["plan_id"], "confirm": PHRASE})
        gamma = next(d for d in console.state(session)["documents"]
                     if d["kind"] == "candidate" and d["title"] == "Gamma")
        check(gamma["source_kind"] == "withdrawn" and gamma["source_agent"] == "",
              "a governing document withdrawn by a change set is tagged a withdrawn governing document")
        created = au.plan(folder, "add", {"title": "Plain note", "scope": "", "body": "Text.\n"})
        check(created.summary == "Create candidate: “Plain note” becomes a private authority candidate."
              and "File “" not in created.summary,
              "Create candidate's summary names the candidate by friendly title, never “File <name>”")
        mp = read(folder, ac.CONTEXT_MAP).decode("utf-8")
        row = next(ln for ln in mp.splitlines() if ln.startswith("| `expected_context_impact` |"))
        check("advisory review material, retained privately with the proposal" in row
              and "shown to the reviewer" not in row,
              "the generated map describes expected context impact as retained advisory review material")
        shutil.rmtree(folder)


def case_competing_revisions() -> None:
    """End to end: two revisions of one document, one applied. The other still
    names the document it revises, can still be compared with it, and is never
    offered or previewed as an ordinary revision: it was made from an earlier
    version, so applying it would undo the one applied."""
    print("\ncompeting revisions: once one governs, the other is known to be made from an earlier version")
    from app import agent_context as ac
    from app import agent_proposals as apx
    from app import authority as au
    from app import changeset as chs
    from tests.harness import govern, seeded

    def revise(folder, body):
        before = set(ps.PrivateState.default().for_context(folder).candidates())
        r = au.plan(folder, "revise", {"path": "authoritative/a.md", "body": body})
        au.apply(folder, "revise", r.request, r.plan_id, True)
        return (set(ps.PrivateState.default().for_context(folder).candidates()) - before).pop()

    def candidate(session, path):
        return next(d for d in console.state(session)["documents"] if d["path"] == path)

    with isolated_private_state():
        folder = context()
        session = console.Session(folder)
        first = revise(folder, "Use two spaces.\n")
        second = revise(folder, "Use tabs.\n")
        a, b = candidate(session, first), candidate(session, second)
        check(a["title"] == b["title"] == "Alpha" and a["revises_current"] and b["revises_current"]
              and a["co_revisions"] == b["co_revisions"] == 1,
              "two revisions of Alpha, both made from its current version, flag each other")
        check(a["change_summary"] == "changes 1 line: “Use two spaces.”"
              and b["change_summary"] == "changes 1 line: “Use tabs.”",
              "and each says what it changes, which tells two same-titled revisions apart")

        govern(folder, {"document": "authoritative/a.md", "outcome": chs.REVISE, "candidate": first})
        b = candidate(session, second)
        check(b["revises_path"] == "authoritative/a.md" and b["revises_title"] == "Alpha"
              and b["revises_current"] is False and b["source_kind"] == "revise",
              "after the first is applied, the second still revises Alpha, made from an earlier version")
        compared = console.compare(session, {"candidate": second, "against": b["revises_path"]})
        check("Use two spaces." in compared["diff"] and "Use tabs." in compared["diff"],
              "and it can still be compared with the governing document, showing what it would undo")

        third = revise(folder, "Use two spaces, never tabs.\n")
        b, c = candidate(session, second), candidate(session, third)
        check(b["co_revisions"] == c["co_revisions"] == 1 and c["revises_current"] and not b["revises_current"],
              "a revision made from the new version competes with it, and only the old one is flagged")

        request = seeded(folder, {"document": "authoritative/a.md", "outcome": chs.REVISE,
                                  "candidate": second})
        plan = au.plan(folder, "changeset", request)
        check(any("made from an earlier version" in n and "undone" in n for n in plan.notes),
              "the preview says applying it undoes what changed since: never an ordinary revision")
        ctx = chs.Ctx(folder)
        from app import api_changeset as api_cs
        detail = api_cs.detail(ctx, chs.load(ctx, request["draft_id"]))
        chosen = detail["plan_candidates"][0]
        offered = {c["path"]: c for c in detail["available_candidates"]}
        check(chosen["revises_current"] is False and offered[third]["revises_current"] is True
              and chosen["revises_title"] == "Alpha",
              "and the change set's candidate details carry the same lineage, to label and warn")

        # Text changed outside Charter, then rebuilt: made from text that no longer governs.
        fourth = revise(folder, "Use spaces.\n")
        path = os.path.join(folder, "authoritative", "a.md")
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write("\nEdited outside Charter.\n")
        from tests.agent_context import generate
        generate(folder)
        check(candidate(session, fourth)["revises_current"] is False,
              "a revision made before an outside edit is flagged too")

        # Provenance stays private: a governing document carries no source, proposal or agent.
        governed = read(folder, "authoritative/a.md").decode("utf-8")
        a_sha = ac.sha256_text(governed)
        pid = apx.file(folder, {"agent": "secret-agent-label", "operation": "amend",
                                "target_path": "authoritative/a.md", "reason": "r", "base_sha256": a_sha,
                                "replacements": [{"find": "Edited outside Charter.", "replace": "Fixed."}]})["proposal_id"]
        ap = au.plan(folder, "accept-proposal", {"proposal_id": pid})
        au.apply(folder, "accept-proposal", ap.request, ap.plan_id, True)
        promoted = (set(ps.PrivateState.default().for_context(folder).candidates())
                    - {second, third, fourth}).pop()
        govern(folder, {"document": "authoritative/a.md", "outcome": chs.REVISE, "candidate": promoted})
        governed = read(folder, "authoritative/a.md").decode("utf-8")
        everything = "".join(read(folder, rel).decode("utf-8") for rel in
                             ("authoritative/a.md", "authoritative/b.md", ac.CONTEXT_MAP, ac.METADATA))
        check("Fixed." in governed and pid not in everything and "secret-agent-label" not in everything
              and not any(f"\n{k}:" in governed for k in au.PRIVATE_KEYS),
              "a promoted proposal's governing document names no proposal, agent, source or lineage")
        shutil.rmtree(folder)


def case_peek() -> None:
    print("\nthe open/create screen's read-only peek at a chosen folder")
    with isolated_private_state():
        folder = context()  # a real Agent Context named "Test project"
        session = console.Session()
        before = snapshot(folder)
        existing = console.peek(session, {"path": folder})
        check(existing == {"exists": True, "has_context": True, "valid": True,
                           "name": "Test project"},
              "an existing Agent Context answers with its name, ready to open")
        empty = os.path.join(folder, "sub-empty")
        os.makedirs(empty)
        check(console.peek(session, {"path": empty})
              == {"exists": True, "has_context": False, "valid": False, "name": ""},
              "an empty folder is offered to create, with no name to carry over")
        missing = os.path.join(folder, "nope")
        check(console.peek(session, {"path": missing})
              == {"exists": False, "has_context": False, "valid": False, "name": ""},
              "a folder that is not there answers blank")
        check(console.peek(session, {"path": " "})
              == {"exists": False, "has_context": False, "valid": False, "name": ""},
              "a blank path answers blank")
        shutil.rmtree(empty)
        check(not session.folder and snapshot(folder) == before,
              "peeking opens nothing and writes nothing in the folder")
        shutil.rmtree(folder)


def case_archived_listing() -> None:
    print("\nan archived document, as the Authority Candidates archive shows it")
    with isolated_private_state():
        folder = context()
        session = console.Session()
        console.open_context(session, {"path": folder})
        before = [d for d in console.state(session)["documents"] if d["kind"] == "archived"]
        do(session, "add", {"title": "Old draft", "scope": "", "body": "Old.\n"})
        do(session, "retire", {"candidate": "authority-candidates/old-draft.md"})
        archived = [d for d in console.state(session)["documents"] if d["kind"] == "archived"]
        check(not before and len(archived) == 1, "the archive counts each retired document")
        doc = archived[0]
        check(doc["path"] == "archive/old-draft.md" and doc["title"] == "Old draft"
              and doc["location"] == "private state" and not doc["governing"],
              "it is listed by title, in private state, governing nothing")
        check(re.fullmatch(r"\d{4}-\d{2}-\d{2}", doc["updated"]) is not None,
              "it carries the date it was archived, as its own field")
        shown = console.preview(session, {"source": "document", "path": doc["path"]})
        check(shown["state"] == "archived" and "not context" in shown["banner"]["title"],
              "Read shows it with a banner saying it is not context")
        check(not os.path.exists(os.path.join(folder, "archive")),
              "nothing archived is written into the Agent Context")
        shutil.rmtree(folder)


def case_conversion_errors() -> None:
    print("\na malformed upload converts to a worded refusal, never a raw parser crash")
    import io
    import zipfile
    from app import convert

    def docx(xml: bytes) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("word/document.xml", xml)
        return buf.getvalue()

    cases = [("bad.pdf", b"%PDF-1.4\nnot a real pdf"),
             ("truncated.docx", docx(b"<w:document xmlns:w='x'><w:body>")),  # unterminated XML
             ("notzip.docx", b"this is not a zip")]
    for name, data in cases:
        try:
            convert.to_markdown(name, data)
            refused = False
        except convert.ConversionError:
            refused = True
        except Exception as exc:  # noqa: BLE001
            refused = False
            print(f"  (raised {type(exc).__name__} instead of ConversionError)")
        check(refused, f"{name} is a worded ConversionError, not a raw parser exception")


def case_text_encodings() -> None:
    """A text file is read in the encoding it declares, or as UTF-8, or as
    unmistakable UTF-16; anything else is refused, never decoded with
    replacement characters. Windows PowerShell 5.1's `Out-File` and `>` write
    UTF-16 LE with a byte-order mark and CRLF, so that is the case that matters."""
    print("\nUTF-16 and other encodings: read correctly, or refused, never silently corrupted")
    import subprocess
    import tempfile
    from app import agent_proposals as apx
    from app import authority as au
    from tests.harness import govern
    text = "# Onboarding Guide\r\n\r\nNew starters read the café handbook.\r\n"
    expected = "# Onboarding Guide\n\nNew starters read the café handbook.\n"
    with isolated_private_state():
        folder = context()
        session = console.Session(folder)
        powershell = b"\xff\xfe" + text.encode("utf-16-le")
        if os.name == "nt" and shutil.which("powershell"):
            with tempfile.TemporaryDirectory(prefix="charter-utf16-") as tmp:
                target = os.path.join(tmp, "out.md")
                made = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                       "$t = \"# Onboarding Guide`r`n`r`nNew starters read the caf\" + "
                                       "[char]0xE9 + \" handbook.\"; $t | Out-File -FilePath $env:OUT"],
                                      env=dict(os.environ, OUT=target), capture_output=True)
                if made.returncode == 0 and os.path.isfile(target):
                    with open(target, "rb") as fh:
                        powershell = fh.read()
                    print("  (Windows PowerShell's own Out-File bytes)")
        check(powershell.startswith(b"\xff\xfe"), "the PowerShell file is UTF-16 LE with a byte-order mark")
        for name, data, label in (
                ("powershell.md", powershell, "UTF-16"),
                ("utf16be.md", b"\xfe\xff" + text.encode("utf-16-be"), "UTF-16"),
                ("utf16-no-bom.txt", text.encode("utf-16-le"), "UTF-16"),
                ("utf32.md", b"\xff\xfe\x00\x00" + text.encode("utf-32-le"), "UTF-32"),
                ("utf8-bom.md", b"\xef\xbb\xbf" + text.encode("utf-8"), "")):
            staged = stage_text(session, name, data)
            check(staged["markdown"] == expected and staged["suggested_title"] == "Onboarding Guide"
                  and "\x00" not in staged["markdown"] and "�" not in staged["markdown"]
                  and (any(f"Read as {label} text" in n for n in staged["notes"]) if label
                       else not any("Read as" in n for n in staged["notes"])),
                  f"{name}: decoded exactly" + (f", and said to be {label}" if label else ""))
        for name, data, why in (
                ("cp1252.md", "Café rules.\r\n".encode("cp1252"), "Windows-1252 bytes"),
                ("nul.md", b"Text\x00with a NUL\n", "a NUL in UTF-8 text"),
                ("bad-utf16.md", b"\xff\xfe\x00\xd8", "a byte-order mark over bytes that are not UTF-16"),
                ("odd.txt", b"\x80\x81\x82", "bytes that are not text at all")):
            message = refused(stage_text, session, name, data)
            check(message and ("not UTF-8 or UTF-16" in message or "not text" in message)
                  and "Nothing was filed" in message, f"{why}: refused, saying why, nothing filed")
        check(ps.PrivateState.default().for_context(folder).candidates() == [],
              "no candidate exists after any refusal")

        # Every other route to a candidate refuses text that is not text.
        message = refused(do, session, "add", {"title": "T", "body": "a\x00b\n"})
        check(message and "not text" in message, "Create candidate with a NUL in its text is refused")
        message = refused(do, session, "add", {"title": "T\x01", "body": "b\n"})
        check(message and "not text" in message, "and a control character in a title is refused")
        result = apx.file(folder, {"agent": "a", "operation": "create",
                                   "target_path": "authority-candidates/n.md", "reason": "r",
                                   "proposed_body": "a\x00b\n"})
        check(result["result"] == "refused"
              and ("not_text", "proposed_body") in {(p["code"], p.get("field")) for p in result["problems"]},
              "an Agent Proposal with a NUL in its body is refused, so the agent can correct it")

        # A candidate filed before Charter refused such text never governs.
        do(session, "add", {"title": "Old", "body": "Clean.\n"})
        cs = ps.PrivateState.default().for_context(folder)
        stored = cs.read_candidate("authority-candidates/old.md")
        with open(cs.path(ps.CANDIDATES, "old.md"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(stored.replace("Clean.", "Cl\x00ean."))
        before = snapshot(folder)
        try:
            govern(folder, {"alongside": "authority-candidates/old.md"})
            governed = True
        except au.ActionRefused as exc:
            governed = False
            reason = str(exc)
        check(not governed and "cannot govern" in reason and snapshot(folder) == before,
              "a stored candidate holding a NUL cannot govern, and the Agent Context is unchanged")

        # What the README says private state holds is what it holds: a candidate
        # from a file records its name and fingerprint, and keeps no copy of it.
        staged = stage_text(session, "kept.md", b"# Kept\n\nText.\n")
        do(session, "add", {"title": "Kept", "body": staged["markdown"],
                            "source": f"kept.md (sha256 {staged['sha256'][:12]})"})
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "README.md"),
                  encoding="utf-8") as fh:
            readme = fh.read()
        original = b"# Kept\n\nText.\n"
        kept = [os.path.join(d, n) for d, subs, names in os.walk(cs.base) for n in names + subs
                if n == "originals" or (os.path.isfile(os.path.join(d, n))
                                        and open(os.path.join(d, n), "rb").read() == original)]
        check(not kept and not hasattr(ps, "ORIGINALS")
              and "Kept originals" not in readme and "not a copy of the file" in readme,
              "no copy of an imported file is kept anywhere in private state, and the README says so")
        shutil.rmtree(folder)


def run() -> int:
    case_api()
    case_text_encodings()
    case_candidate_lineage()
    case_candidate_sources()
    case_competing_revisions()
    case_peek()
    case_archived_listing()
    case_conversion_errors()
    case_stage_front_matter()
    case_stage_leaves_nothing()
    case_recent_while_open()
    case_clear_recent()
    case_import_duplicate()
    case_recent_order()
    case_change_set_count()
    case_server()
    case_command_route()
    case_page_routes()
    case_request_boundary()
    case_busy_port()
    case_restart_port()
    case_banner_piped()
    print(f"\n{OK} All console API and server checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
