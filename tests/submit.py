"""MCP `submit_proposal`: filing one Agent Proposal for review. Run: python -m tests.submit

MCP Context Access Specification §3.1, Product Specification §3.2–§3.3 and §6,
and Agent Context as the Project Asset §7 (map-format version 5):

  * a fifth tool on every registration, annotated write-capable but
    non-destructive, whose arguments are exactly the typed proposal fields;
  * the same checker, `proposal_sha256` duplicate matching, intake lock and
    filing as `charter propose` and Import, as an ordinary agent proposal,
    keeping no `submitted_sha256`;
  * `pending`, `refused`, `duplicate` and `unavailable` as ordinary tool
    results with the intake's codes; protocol errors only for an invocation
    proposal processing cannot take;
  * `context_invalid`, `map_outdated` and `server_outdated` not retryable;
    `intake_busy` and an unexpected failure retryable once, which the
    duplicate match makes safe; no attempt count, no activity;
  * no physical path, private-state location, or candidate or archived name in
    anything the server says, even when an exception is injected;
  * map format 5, with format 4 out of date until one Rebuild.
"""
from __future__ import annotations

import errno
import importlib.util
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import agent_proposals as apx  # noqa: E402
from app import host_state as hs  # noqa: E402
from app import manager as mg  # noqa: E402
from app import mcp  # noqa: E402
from app import mcp_activity as activity  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import propose  # noqa: E402
from tests.agent_context import generate, read, snapshot, with_map_format, write  # noqa: E402
from tests.harness import isolated_private_state  # noqa: E402
from tests.mcp import Session, fixture, with_candidate  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OK = "ok"
POLICY = "authoritative/policy.md"
# §8 of the MCP Context Access Specification, exactly.
GOVERNING_INSTRUCTIONS = (
    "This server gives read-only access to this Agent Context and files Agent Proposals for a "
    "person's review. Call `get_context` before work, then use the listed document tools as "
    "needed. To propose a change, use `submit_proposal`; it never changes governing context. "
    "Authority candidates, archives, and Agent Proposals are not governing context.")


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def create(name: str = "new-rule", **more) -> dict:
    return dict({"agent": "codex", "operation": "create",
                 "target_path": f"authority-candidates/{name}.md", "reason": "Needed.",
                 "proposed_body": f"# {name}\n\nText café.\n"}, **more)


def submit(session: Session, arguments) -> dict:
    """The tool result; asserts it is an ordinary result whose text is its
    structured content as JSON, and returns that one result object."""
    result = session.call(mcp.SUBMIT, arguments)
    assert "isError" in result and result["isError"] is False, result
    structured = result.get("structuredContent")
    assert structured is not None and json.loads(result["content"][0]["text"]) == structured, result
    return structured


def cli(folder: str, proposal) -> dict:
    data = proposal if isinstance(proposal, bytes) else json.dumps(proposal).encode("utf-8")
    return propose.submit(["--context", folder], data)


def context_state(folder: str) -> ps.ContextState:
    return ps.PrivateState.default().for_context(folder)


def pending(cs: ps.ContextState) -> dict:
    folder = cs.path(ps.PROPOSALS, apx.PENDING)
    out = {}
    for name in sorted(os.listdir(folder)) if os.path.isdir(folder) else []:
        if name.endswith(".json"):
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                out[name[:-5]] = json.load(fh)
    return out


def state_files(cs: ps.ContextState) -> dict:
    """Every private file for this context but its lock files, with its bytes."""
    out = {}
    for d, _dirs, names in os.walk(cs.base):
        for n in names:
            rel = os.path.relpath(os.path.join(d, n), cs.base)
            if rel.split(os.sep)[0] == ps.LOCKS:
                continue
            with open(os.path.join(d, n), "rb") as fh:
                out[rel] = fh.read()
    return out


def secrets(folder: str, state_root: str) -> list:
    """What no MCP reply may contain: physical locations Charter knows, in the
    spellings a reply could carry them, and private candidate names."""
    places = [folder, state_root, os.path.dirname(state_root), mcp.LAUNCHER,
              os.path.dirname(mcp.LAUNCHER), sys.executable, os.path.dirname(sys.executable)]
    out = []
    for p in places:
        for form in (p, p.replace("\\", "/"), p.replace("\\", "\\\\"), json.dumps(p)[1:-1]):
            out += [form, form.lower()]
    return sorted(set(out) | {"secret-draft", "Secret draft", "old-idea", "Old idea",
                              "CANDIDATE-ONLY-TEXT", "ARCHIVE-ONLY-TEXT"}, key=len, reverse=True)


def discloses(replies, forbidden) -> list:
    text = json.dumps(replies, ensure_ascii=False)
    lowered = text.lower()
    return [s for s in forbidden if s and (s in text or s.lower() in lowered)]


def case_listing() -> None:
    print("\nthe fifth tool: listed on every registration, typed, write-capable but non-destructive")
    with isolated_private_state() as state_root:
        folder = fixture()
        for version in ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"):
            session = Session(folder, record=False, version=version)
            init = session.replies[0]["result"]
            tools = session.ask("tools/list")["result"]["tools"]
            check([t["name"] for t in tools] == ["get_context", "list_governing_documents", "get_document",
                                                 "get_document_section", "submit_proposal"]
                  and (("outputSchema" in tools[4]) == (version >= mcp.STRUCTURED_SINCE)),
                  f"{version}: five tools, `submit_proposal` last, with an output schema only where "
                  "structured content exists")
            check(init["instructions"] == GOVERNING_INSTRUCTIONS
                  and init["serverInfo"] == {"name": "charter", "title": "Charter",
                                             "version": init["serverInfo"]["version"]},
                  "  the server instructions are the governing text exactly, and server information "
                  "is the name, title and version")
        tool = tools[4]
        check(tool["annotations"] == {"readOnlyHint": False, "destructiveHint": False,
                                      "idempotentHint": True, "openWorldHint": False,
                                      "title": "Submit an Agent Proposal"},
              "annotated readOnlyHint false, destructiveHint false, idempotentHint true, "
              "openWorldHint false")
        check(all(t["annotations"]["readOnlyHint"] is True and t["annotations"]["destructiveHint"] is False
                  and t["annotations"]["idempotentHint"] is True and t["annotations"]["openWorldHint"] is False
                  for t in tools[:4]),
              "the four retrieval tools stay annotated read-only")
        schema = tool["inputSchema"]
        check(set(schema["properties"]) == set(apx.FIELDS) and "task" not in schema["properties"]
              and schema["additionalProperties"] is False
              and schema["required"] == ["agent", "operation", "target_path", "reason"]
              and schema["properties"]["operation"]["enum"] == ["create", "amend", "retire"]
              and schema["properties"]["replacements"]["items"]["additionalProperties"] is False
              and schema["properties"]["proposed_meta"]["additionalProperties"] is False
              and schema["properties"]["expected_context_impact"]["type"] == ["string", "object", "array"],
              "its input schema is exactly the typed proposal fields: no `task`, no other property")
        out = tools[4] if "outputSchema" in tools[4] else \
            Session(folder, record=False).ask("tools/list")["result"]["tools"][4]
        check(out["outputSchema"]["properties"]["result"]["enum"]
              == ["pending", "refused", "duplicate", "unavailable"],
              "its output schema is the proposal result: pending, refused, duplicate or unavailable")
        check(not discloses(session.replies, secrets(folder, state_root)),
              "neither the handshake nor the listing names a path Charter knows")
        shutil.rmtree(folder)


def case_results() -> None:
    print("\npending and duplicate: one shared intake, as an ordinary agent proposal")
    with isolated_private_state() as state_root:
        folder = fixture()
        with_candidate(folder)
        cs = context_state(folder)
        candidates = sorted(cs.candidates())
        before = snapshot(folder)
        session = Session(folder, record=False)
        proposal = create(expected_context_impact={"related": [POLICY], "conflict": "none"})
        result = submit(session, proposal)
        check(set(result) == {"result", "proposal_id"} and result["result"] == "pending"
              and result["proposal_id"].startswith("p-"),
              "pending: exactly the result `charter propose` prints, with the assigned `proposal_id`")
        record = pending(cs)[result["proposal_id"]]
        check(set(record) == {"version", "proposal_id", "source", "received", "proposal", "proposal_sha256"}
              and record["source"] == apx.AGENT and record["proposal"] == proposal
              and record["proposal_sha256"] == apx.proposal_fingerprint(proposal),
              "its record is an ordinary agent proposal with `proposal_sha256`, no `submitted_sha256`, "
              "and no route label")
        filed, unexpected = apx.records(cs)
        check([r["proposal_id"] for r in filed] == [result["proposal_id"]] and not unexpected
              and filed[0]["source"] == apx.AGENT,
              "the intake ledger vouches for it, as for any agent proposal")
        listing = apx.listing(folder)
        check(json.dumps(listing).count(result["proposal_id"]) >= 1,
              "it is listed in Agent Proposals for a person to decide")
        check(snapshot(folder) == before and sorted(cs.candidates()) == candidates,
              "nothing in the Agent Context changed, and no candidate was created or accepted")
        again = submit(session, dict(reversed(list(proposal.items()))))
        check(again == {"result": "duplicate", "problem": {
            "code": "duplicate", "message": apx.DUPLICATE_MESSAGE + apx.DUPLICATE_AFTER_RETRY}}
              and len(pending(cs)) == 1,
              "the same proposal again, its keys in another order: duplicate, saying nothing about "
              "the waiting one, and stop if this was the one retry; nothing more filed")
        check(cli(folder, proposal)["problem"]["message"] == apx.DUPLICATE_MESSAGE,
              "  `charter propose` keeps its own duplicate message")
        taken = submit(session, create("secret-draft"))
        check(taken["result"] == "pending",
              "a create naming a candidate that exists is filed, never revealing that it exists")
        old = Session(folder, record=False, version="2025-03-26")
        raw = old.call(mcp.SUBMIT, create("older-host"))
        check(raw["isError"] is False and "structuredContent" not in raw
              and json.loads(raw["content"][0]["text"])["result"] == "pending",
              "a host on a protocol without structured content gets the same result object as JSON text")
        check(not discloses(session.replies + old.replies, secrets(folder, state_root)),
              "no reply names a path Charter knows, or a candidate or archived name")
        shutil.rmtree(folder)


def _refusals(folder: str) -> list:
    text = read(folder, POLICY).decode("utf-8")
    base = ac.sha256_text(text)
    body = apx.body_of(text)
    heading = body.splitlines()[0]
    amend = {"agent": "codex", "operation": "amend", "target_path": POLICY, "reason": "Fix.",
             "base_sha256": base}
    good = create()
    return [
        ("no fields at all", {}),
        ("a `task` label", dict(good, task="label")),
        ("an unknown field", dict(good, priority=1)),
        ("`agent` not text", dict(good, agent=5)),
        ("`agent` on two lines", dict(good, agent="a\nb")),
        ("`agent` too long", dict(good, agent="x" * (apx.MAX_AGENT + 1))),
        ("an empty `reason`", dict(good, reason=" ")),
        ("an unknown operation", dict(good, operation="delete")),
        ("`target_path` not text", dict(good, target_path=7)),
        ("a create outside authority-candidates/", dict(good, target_path="authoritative/x.md")),
        ("a create without a body", {k: v for k, v in good.items() if k != "proposed_body"}),
        ("a create with `base_sha256`", dict(good, base_sha256=base)),
        ("a body beginning with front matter", dict(good, proposed_body="---\nid: x\n---\n# X\n")),
        ("a body that is not text", dict(good, proposed_body="# X\n\u0000\n")),
        ("an amend against a changed text", dict(amend, base_sha256="0" * 64, replacements=[
            {"find": heading, "replace": heading + "!"}])),
        ("an amend with no usable hash", dict(amend, base_sha256="abc", proposed_body="# X\n")),
        ("an amend with body and replacements", dict(amend, proposed_body="# X\n", replacements=[
            {"find": heading, "replace": "x"}])),
        ("an empty replacements list", dict(amend, replacements=[])),
        ("a replacement that matches nothing", dict(amend, replacements=[
            {"find": "NOT-IN-THE-BODY", "replace": "y"}])),
        ("a replacement that matches twice", dict(amend, replacements=[{"find": "e", "replace": "E"}])),
        ("a replacement missing `replace`", dict(amend, replacements=[{"find": heading}])),
        ("a replacement with an empty `find`", dict(amend, replacements=[{"find": "", "replace": "y"}])),
        ("replacements leaving front matter", dict(amend, replacements=[
            {"find": heading, "replace": "---\nid: x\n---\n" + heading}])),
        ("`replacements` not a list", dict(amend, replacements="find this")),
        ("a retire of a governing document", {"agent": "a", "operation": "retire",
                                              "target_path": POLICY, "reason": "r", "base_sha256": base}),
        ("an amend of a candidate, stale", dict(amend, target_path="authority-candidates/secret-draft.md",
                                                proposed_body="# X\n")),
        ("an amend of a name that does not exist", dict(amend, target_path="authority-candidates/nope.md",
                                                        proposed_body="# X\n")),
        ("`proposed_meta` not an object", dict(good, proposed_meta="Title")),
        ("`proposed_meta` with another key", dict(good, proposed_meta={"title": "T", "owner": "me"})),
        ("`proposed_meta` on a retire", {"agent": "a", "operation": "retire",
                                         "target_path": "authority-candidates/secret-draft.md",
                                         "reason": "r", "base_sha256": base, "proposed_meta": {"title": "T"}}),
        ("`expected_context_impact` a number", dict(good, expected_context_impact=5)),
        ("`expected_context_impact` too long", dict(good, expected_context_impact="x" * (apx.MAX_IMPACT + 1))),
        ("a whole proposal as JSON text", {"proposal": json.dumps(good)}),
    ]


def case_refused() -> None:
    print("\nrefused: the same checker, field by field, never a protocol error")
    with isolated_private_state() as state_root:
        folder = fixture()
        with_candidate(folder)
        cs = context_state(folder)
        session = Session(folder, record=False)
        before_state, before_folder = state_files(cs), snapshot(folder)
        seen = set()
        for label, arguments in _refusals(folder):
            result = submit(session, arguments)
            expected = cli(folder, arguments)
            seen |= {p["code"] for p in result.get("problems", [])}
            check(result["result"] == "refused" and result == expected,
                  f"{label}: refused, exactly as `charter propose` refuses it "
                  f"({', '.join(sorted({p['code'] for p in result['problems']}))})")
        candidate, unknown = (submit(session, a) for _l, a in _refusals(folder)[25:27])
        check(candidate == unknown and [p["code"] for p in candidate["problems"]] == ["target_unavailable"],
              "a stale candidate and a name that does not exist are refused alike: no oracle")
        check(seen >= {"missing", "unknown_field", "not_text", "not_one_line", "too_long",
                       "operation_unknown", "target_invalid", "not_used", "front_matter_in_body",
                       "stale", "base_invalid", "body_or_replacements", "replacements_invalid",
                       "replacement_no_match", "replacement_ambiguous", "replacement_malformed",
                       "replacement_empty", "target_governing", "target_unavailable", "meta_invalid",
                       "impact_invalid"},
              f"every checker problem code is reachable through the tool ({len(seen)} codes)")
        check(state_files(cs) == before_state and snapshot(folder) == before_folder,
              "a refusal writes nothing: no record, no ledger entry, no folder change")
        omitted = session.ask("tools/call", {"name": mcp.SUBMIT})["result"]
        check(omitted["isError"] is False and omitted["structuredContent"]["result"] == "refused"
              and {p["field"] for p in omitted["structuredContent"]["problems"]}
              == {"agent", "operation", "target_path", "reason"},
              "arguments left out are an empty proposal: refused, listing the four required fields")
        check(not discloses(session.replies, secrets(folder, state_root)),
              "no refusal names a path Charter knows, or a candidate or archived name")
        shutil.rmtree(folder)


def case_protocol_errors() -> None:
    print("\nprotocol errors: only for what proposal processing cannot take at all")
    with isolated_private_state() as state_root:
        folder = fixture()
        cs = context_state(folder)
        session = Session(folder, record=False)
        before = state_files(cs)
        for label, arguments in (("a list", [create()]), ("a string", json.dumps(create())),
                                 ("a number", 7), ("true", True)):
            reply = session.ask("tools/call", {"name": mcp.SUBMIT, "arguments": arguments})
            check(reply.get("error", {}).get("code") == mcp.INVALID_PARAMS and "result" not in reply,
                  f"arguments that are {label}, not an object: invalid params, a protocol error")
        reply = session.ask("tools/call", {"name": "submit_proposals", "arguments": create()})
        check(reply["error"] == {"code": mcp.INVALID_PARAMS, "message": "Unknown tool."},
              "an unknown tool name: a protocol error")
        reply = session.ask("tools/call", [mcp.SUBMIT])
        check(reply["error"]["code"] == mcp.INVALID_PARAMS, "params that are not an object: a protocol error")
        reply = session.server.handle({"jsonrpc": "1.0", "id": 9, "method": "tools/call",
                                       "params": {"name": mcp.SUBMIT, "arguments": create()}})
        check(reply["error"]["code"] == mcp.INVALID_REQUEST, "a message that is not JSON-RPC 2.0: invalid request")
        reply = session.ask("proposals/submit", create())
        check(reply["error"]["code"] == mcp.METHOD_NOT_FOUND, "an unknown method: method not found")
        check(state_files(cs) == before, "none of them filed or wrote anything")
        check(not discloses(session.replies, secrets(folder, state_root)),
              "no protocol error names a path Charter knows")
        shutil.rmtree(folder)


def case_unavailable() -> None:
    print("\nunavailable, not retryable: the context cannot accept proposals")
    with isolated_private_state() as state_root:
        folder = fixture()
        forbidden = secrets(folder, state_root)
        cs = context_state(folder)
        session = Session(folder, record=False)
        replies = []

        def unavailable(code: str, label: str, also: str = "") -> dict:
            before_state, before_folder = state_files(cs), snapshot(folder)
            result = submit(session, create())
            replies.append(result)
            message = result.get("problem", {}).get("message", "")
            check(result.get("result") == "unavailable" and result["retryable"] is False
                  and result["problem"]["code"] == code and also in message
                  and "--context" not in message and "charter propose" not in message
                  and state_files(cs) == before_state and snapshot(folder) == before_folder,
                  f"{label}: `{code}`, not retryable, nothing filed or written; the message names no "
                  "command or option")
            return result

        write(folder, "notes.txt", b"x")
        unavailable("context_invalid", "a stray file: not clean")
        os.remove(os.path.join(folder, "notes.txt"))
        original = read(folder, POLICY)
        write(folder, POLICY, original + b"Edited outside Charter.\n")
        r = unavailable("context_invalid", "a governing document changed outside Charter",
                        also="Do not rely on Charter context you retrieved earlier in this session.")
        check("no longer match its approved context map" in r["problem"]["message"]
              and "Report to the person" in r["problem"]["message"],
              "  it says the files no longer match the map, not to rely on earlier context, and to "
              "tell the person")
        write(folder, POLICY, original)
        saved = {rel: read(folder, rel) for rel in (ac.CONTEXT_MAP, ac.METADATA)}
        for rel in saved:
            os.remove(os.path.join(folder, rel))
        unavailable("context_invalid", "documents and no usable map",
                    also="has documents but no usable map")
        for rel, data in saved.items():
            write(folder, rel, data)
        with_map_format(folder, 4)
        unavailable("map_outdated", "a format-4 map, under this format-5 Charter", also="rebuild")
        check(session.refused("get_context") == "map-outdated"
              and cli(folder, create())["problem"]["code"] == "map_outdated",
              "  as retrieval refuses it `map-outdated` and `charter propose` answers `map_outdated`")
        with_map_format(folder, ac.MAP_FORMAT_VERSION + 1)
        unavailable("server_outdated", "a newer map than this server understands",
                    also="restart the agent host, or reconnect it to the current Charter installation")
        check(session.refused("get_context") == "server-outdated"
              and cli(folder, create())["problem"]["code"] == "charter_outdated"
              and all(r["problem"]["code"] != "charter_outdated" for r in replies),
              "  retrieval refuses it `server-outdated`, the command names its own copy "
              "`charter_outdated`, and the tool never does")
        generate(folder)

        gone = Session(os.path.join(folder, "no-such-folder"), record=False)
        replies.append(submit(gone, create()))
        empty = Session("", record=False)
        replies.append(submit(empty, create()))
        check(all(r["result"] == "unavailable" and r["problem"]["code"] == "context_invalid"
                  and not r["retryable"] for r in replies[-2:]),
              "a registered folder that is gone, or none at all: `context_invalid`, not retryable")

        def raising(error):
            def failing(*_args, **_kwargs):
                raise error
            return failing

        write_json, hs.write_json_atomic = hs.write_json_atomic, raising(
            PermissionError(errno.EACCES, "denied", folder))
        try:
            result = submit(session, create("denied"))
        finally:
            hs.write_json_atomic = write_json
        replies.append(result)
        check(result["result"] == "unavailable" and result["retryable"] is False
              and result["problem"]["code"] == "intake_unavailable" and not pending(cs),
              "private state a person must correct: `intake_unavailable`, not retryable")
        check(not discloses(replies + session.replies + gone.replies, forbidden),
              "no unavailable result names a path Charter knows, even an error carrying the folder's")
        shutil.rmtree(folder)


def case_one_retry() -> None:
    print("\nretryable once: a busy intake or an unexpected failure, and the retry is safe")
    with isolated_private_state() as state_root:
        folder = fixture()
        forbidden = secrets(folder, state_root)
        cs = context_state(folder)
        session = Session(folder, record=False)
        replies = []

        proposal = create("busy")
        with cs.lock("intake"):
            apx.INTAKE_TIMEOUT, saved = 0.2, apx.INTAKE_TIMEOUT
            try:
                first = submit(session, proposal)
            finally:
                apx.INTAKE_TIMEOUT = saved
        retry = submit(session, proposal)
        replies += [first, retry]
        check(first["result"] == "unavailable" and first["retryable"] is True
              and first["problem"]["code"] == "intake_busy" and retry["result"] == "pending"
              and len(pending(cs)) == 1,
              "the intake lock held: `intake_busy`, retryable; the one retry files it")

        # Filed, then a failure Charter did not foresee: the retry answers duplicate.
        proposal = create("filed-then-failed")
        write_json = hs.write_json_atomic

        def write_then_fail(path, *args, **kwargs):
            write_json(path, *args, **kwargs)
            if os.sep + apx.PENDING + os.sep in path:
                raise RuntimeError(f"unforeseen, in {path} under {folder}")

        hs.write_json_atomic = write_then_fail
        try:
            first = submit(session, proposal)
        finally:
            hs.write_json_atomic = write_json
        retry = submit(session, proposal)
        replies += [first, retry]
        filed = [r for r in pending(cs).values() if r["proposal"] == proposal]
        check(first == {"result": "unavailable", "retryable": True,
                        "problem": {"code": "intake_unavailable", "message": mcp.UNEXPECTED.message}}
              and "may already have been filed" in first["problem"]["message"]
              and retry["result"] == "duplicate" and len(filed) == 1,
              "filed, then an unexpected failure: `intake_unavailable`, retryable, saying it may "
              "already be filed; the retry answers `duplicate`, and exactly one is waiting")

        # A failure before anything was written: the retry files it, and nothing
        # about the failed attempt was kept.
        proposal = create("failed-first")
        before = state_files(cs)
        find = apx.find_duplicate

        def fail_once(*_args, **_kwargs):
            apx.find_duplicate = find
            raise KeyError(folder)

        apx.find_duplicate = fail_once
        try:
            first = submit(session, proposal)
        finally:
            apx.find_duplicate = find
        kept = state_files(cs)
        retry = submit(session, proposal)
        replies += [first, retry]
        check(first["result"] == "unavailable" and first["retryable"] is True
              and first["problem"]["code"] == "intake_unavailable" and kept == before
              and retry["result"] == "pending",
              "an unexpected failure before filing: retryable, nothing kept — no attempt count — and "
              "the retry files it")

        examine = ac.examine
        ac.examine = lambda *_a, **_k: (_ for _ in ()).throw(ValueError(f"cannot read {folder}"))
        try:
            first = submit(session, create("examine-failed"))
        finally:
            ac.examine = examine
        replies.append(first)
        check(first["result"] == "unavailable" and first["retryable"] is True
              and first["problem"] == {"code": "intake_unavailable", "message": mcp.UNEXPECTED.message},
              "an exception while examining the context is the same unexpected failure")
        transient = OSError(errno.EBUSY, "busy", folder)
        hs.write_json_atomic = lambda *_a, **_k: (_ for _ in ()).throw(transient)
        try:
            first = submit(session, create("transient"))
        finally:
            hs.write_json_atomic = write_json
        replies.append(first)
        check(first["result"] == "unavailable" and first["retryable"] is True
              and first["problem"]["code"] == "intake_unavailable",
              "a write that fails for a moment: `intake_unavailable`, retryable, as for `charter propose`")
        check(not discloses(replies + session.replies, forbidden),
              "no result names a path Charter knows, though every injected error carried the folder's")
        shutil.rmtree(folder)


def case_cross_route() -> None:
    print("\none queue: MCP, `charter propose` and Import match one another's proposals")
    with isolated_private_state():
        folder = fixture()
        cs = context_state(folder)
        session = Session(folder, record=False)
        a = create("from-mcp")
        filed = submit(session, a)
        spaced = json.dumps(dict(reversed(list(a.items()))), indent=3, ensure_ascii=True).encode("ascii")
        check(filed["result"] == "pending" and cli(folder, b"\xef\xbb\xbf" + spaced)["result"] == "duplicate",
              "filed through MCP, then sent to `charter propose` reindented, reordered, escaped and "
              "with a byte-order mark: duplicate")
        target = apx.open_target(folder)
        check([r["status"] for r in apx.assess(target, [json.loads(spaced)])] == [apx.AWAITING],
              "  and Import sees it as Already awaiting review")
        b = create("from-command")
        check(cli(folder, b)["result"] == "pending" and submit(session, b)["result"] == "duplicate",
              "filed by `charter propose`, then submitted through MCP: duplicate")
        c = create("from-import")
        imported = apx.file_batch(folder, [(c, json.dumps(c).encode("utf-8"))])
        check(imported["result"] == "pending" and submit(session, c)["result"] == "duplicate",
              "imported, then submitted through MCP: duplicate")
        d = create("null-impact")
        check(cli(folder, d)["result"] == "pending"
              and submit(session, dict(d, expected_context_impact=None, proposed_meta=None))["result"]
              == "duplicate",
              "an optional field given as null is the same as one left out")
        check(submit(session, dict(a, agent="another-agent"))["result"] == "pending",
              "a different `agent` is a different proposal")
        records = pending(cs)
        by_name = {r["proposal"]["target_path"].split("/")[-1][:-3]: r for r in records.values()
                   if r["proposal"]["agent"] == "codex"}
        check("submitted_sha256" not in by_name["from-mcp"]
              and "submitted_sha256" in by_name["from-command"] and "submitted_sha256" in by_name["from-import"]
              and all(r["proposal_sha256"] == apx.proposal_fingerprint(r["proposal"]) for r in records.values()),
              "MCP records keep no `submitted_sha256`; command and import records still keep it; every "
              "record keeps `proposal_sha256`")
        sources = {r["proposal"]["target_path"]: entry["source"] for r, entry in
                   ((r, apx._ledger(cs)[pid]) for pid, r in records.items())}
        check(sources["authority-candidates/from-mcp.md"] == apx.AGENT
              and sources["authority-candidates/from-command.md"] == apx.AGENT
              and sources["authority-candidates/from-import.md"] == apx.IMPORTED,
              "MCP and the command both file as `agent`; Import as `imported`")

        head = subprocess.run(["git", "show", "HEAD:app/agent_proposals.py"], capture_output=True, cwd=ROOT)
        if head.returncode != 0 or b"route: str = COMMAND" in head.stdout \
                or b"proposal_sha256" not in head.stdout:
            print("  skip: no earlier committed copy, from before MCP submission, to compare with")
        else:
            spec = importlib.util.spec_from_loader("app._earlier_agent_proposals", loader=None)
            earlier = importlib.util.module_from_spec(spec)
            earlier.__package__ = "app"
            exec(compile(head.stdout.decode("utf-8"), "earlier agent_proposals.py", "exec"), earlier.__dict__)
            listed, unexpected = earlier.records(cs)
            text = json.dumps(a)
            check(filed["proposal_id"] in {r["proposal_id"] for r in listed} and not unexpected
                  and earlier.file(folder, json.loads(text), submitted=text.encode())["result"] == "duplicate",
                  "an earlier copy of Charter sharing this private state lists the MCP record as filed, "
                  "and its `charter propose` matches it by `proposal_sha256`")
        shutil.rmtree(folder)


def case_no_activity() -> None:
    print("\nno activity, and no change to the Agent Context folder")
    with isolated_private_state():
        folder = fixture()
        cs = context_state(folder)
        session = Session(folder, record=True)
        connected = activity.recent(folder, 1000)
        before = snapshot(folder)
        submit(session, create("watched"))
        submit(session, create("watched"))
        submit(session, {"agent": "a"})
        with cs.lock("intake"):
            apx.INTAKE_TIMEOUT, saved = 0.2, apx.INTAKE_TIMEOUT
            try:
                submit(session, create("busy"))
            finally:
                apx.INTAKE_TIMEOUT = saved
        session.ask("tools/call", {"name": mcp.SUBMIT, "arguments": [1]})
        check(activity.recent(folder, 1000) == connected and [e["event"] for e in connected] == ["connect"],
              "pending, duplicate, refused, unavailable and a protocol error: no activity recorded, "
              "only the connection")
        check(snapshot(folder) == before, "the Agent Context folder's bytes are unchanged")
        session.call("get_context")
        check([e["event"] for e in activity.recent(folder, 1000)] == ["tool", "connect"]
              and activity.recent(folder, 1)[0]["tool"] == "get_context",
              "retrieval is still recorded as before")
        shutil.rmtree(folder)


def case_stdio_process() -> None:
    print("\nthe real server process: five tools, a filed proposal, and no path said")
    with isolated_private_state() as state_root:
        folder = fixture()
        launch = os.path.join(HERE, "_launch.py")
        messages = [
            {"jsonrpc": "2.0", "id": 0, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": mcp.SUBMIT, "arguments": create("over-stdio")}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": mcp.SUBMIT, "arguments": create("over-stdio")}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": mcp.SUBMIT, "arguments": "{}"}},
        ]
        data = "".join(json.dumps(m) + "\n" for m in messages).encode("utf-8") + b"not json\n"
        proc = subprocess.run([sys.executable, launch, os.path.dirname(state_root), "mcp", "--context", folder],
                              input=data, capture_output=True, timeout=120)
        replies = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
        by_id = {r.get("id"): r for r in replies}
        check(proc.returncode == 0 and proc.stderr == b"" and len(replies) == 6,
              "every message answered on standard output; nothing on standard error")
        check([t["name"] for t in by_id[1]["result"]["tools"]][-1] == mcp.SUBMIT
              and by_id[2]["result"]["structuredContent"]["result"] == "pending"
              and by_id[3]["result"]["structuredContent"]["result"] == "duplicate"
              and by_id[4]["error"]["code"] == mcp.INVALID_PARAMS
              and replies[-1]["error"]["code"] == mcp.PARSE_ERROR,
              "listed; pending, then duplicate; non-object arguments and a bad line are protocol errors")
        check(not discloses(replies, secrets(folder, state_root)),
              "nothing the process said names a path Charter knows")
        shutil.rmtree(folder)


def case_map_format_5() -> None:
    print("\nmap format 5: format 4 is out of date, Rebuild brings it current, and waiting proposals stay")
    with isolated_private_state():
        folder = fixture()
        cs = context_state(folder)
        session = Session(folder, record=False)
        served = session.call("get_context")["structuredContent"]["text"]
        check("If you received this file through MCP, submit each proposal with the\n`submit_proposal` tool"
              in served and json.loads(read(folder, ac.METADATA))["map_format_version"] == 5,
              "a context generated now is map format 5, and sends an MCP agent to `submit_proposal`")
        waiting = submit(session, create("before-rebuild"))["proposal_id"]
        with_map_format(folder, 4)
        v4 = read(folder, ac.CONTEXT_MAP).decode("utf-8")
        check("submit_proposal" not in v4 and session.refused("get_context") == "map-outdated"
              and submit(session, create("while-outdated"))["problem"]["code"] == "map_outdated",
              "a format-4 context: retrieval refuses it `map-outdated`, and the tool files nothing")
        damaged = v4 + "Edited.\n"
        write(folder, ac.CONTEXT_MAP, damaged)
        exam = ac.examine(folder)
        check(exam.map_regenerable and ac.restored_map(exam) == v4,
              "  a damaged format-4 map is regenerated exactly as format 4 wrote it")
        write(folder, ac.CONTEXT_MAP, v4)
        documents = {rel: read(folder, rel) for rel in (POLICY, "authoritative/a.md", "authoritative/b.md")}
        plan = mg.rebuild_plan(folder)
        status = mg.rebuild_apply(folder, plan.plan_id, True)
        check(status["agents_served"] and status["map_format"]["recorded"] == 5
              and all(read(folder, rel) == data for rel, data in documents.items())
              and list(pending(cs)) == [waiting],
              "one Rebuild brings it to format 5; every governing document is byte-for-byte as it was, "
              "and the proposal awaiting review is still there")
        check("`submit_proposal` tool of the same MCP server" in session.call("get_context")["structuredContent"]["text"]
              and submit(session, create("after-rebuild"))["result"] == "pending",
              "  after Rebuild, the map gives the MCP route, and the tool files")

        # A server from before this release: it understands only format 4.
        saved = ac.MAP_FORMAT_VERSION, ac.OLDER_MAP_FORMATS
        ac.MAP_FORMAT_VERSION, ac.OLDER_MAP_FORMATS = 4, (1, 2, 3)
        try:
            old = Session(folder, record=False)
            refusal = old.call("get_context")
            command = cli(folder, create("older-copy"))
        finally:
            ac.MAP_FORMAT_VERSION, ac.OLDER_MAP_FORMATS = saved
        check(refusal["isError"] and refusal["content"][0]["text"].startswith("server-outdated:")
              and command["problem"]["code"] == "charter_outdated",
              "a format-4 copy refuses the rebuilt context: its MCP server `server-outdated`, its "
              "`charter propose` `charter_outdated`")
        shutil.rmtree(folder)


def run() -> None:
    case_listing()
    case_results()
    case_refused()
    case_protocol_errors()
    case_unavailable()
    case_one_retry()
    case_cross_route()
    case_no_activity()
    case_stdio_process()
    case_map_format_5()
    print("\nAll MCP proposal submission checks passed.")


if __name__ == "__main__":
    run()
