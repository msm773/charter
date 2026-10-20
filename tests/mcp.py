"""Read-only MCP access to an Agent Context folder. Run: python -m tests.mcp

MCP Context Access Specification:

  * one selected Agent Context folder is served directly: no copy, binding or
    registration, and the host never names private state;
  * exactly four read-only tools, the exact instructions, protocol versions;
  * every call revalidates the whole folder and verifies the bytes it
    returns; an invalid, unclean or interrupted context is refused, even
    when its files look valid;
  * only the eight reason codes; nothing private is ever disclosed;
  * bounded, private activity; `--check` diagnoses without writing,
    creating private state or recovering anything;
  * a real stdio process speaks only JSON-RPC on standard output.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import authority as au  # noqa: E402
from app import mcp  # noqa: E402
from app import mcp_activity  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import transaction as tx  # noqa: E402
from tests.agent_context import context, doc_text, generate, read, write  # noqa: E402
from tests.harness import isolated_private_state, seeded  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OK = "ok"
CODES = {"context-invalid", "context-unclean", "changed-during-read", "not-governing",
         "unsafe-path", "heading-missing", "heading-ambiguous", "bad-arguments"}

SECTIONED = """# Policy

Intro.

## Boundaries

Inside the lines.

### Detail

Fine print.

## Exceptions

None.

## exceptions

Duplicate, differently cased.

```text
## Boundaries
```
"""


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


class Session:
    """One server, driven message by message, with every reply kept."""

    def __init__(self, folder: str, record: bool = True, version: str = "2025-06-18"):
        self.server = mcp.Server(folder, record=record)
        self.replies: list = []
        self.next = 0
        self.ask("initialize", {"protocolVersion": version, "capabilities": {},
                                "clientInfo": {"name": "test-host", "version": "1.0"}})

    def ask(self, method: str, params=None):
        self.next += 1
        reply = self.server.handle({"jsonrpc": "2.0", "id": self.next, "method": method,
                                    "params": params or {}})
        self.replies.append(reply)
        return reply

    def call(self, tool: str, arguments=None):
        reply = self.ask("tools/call", {"name": tool, "arguments": arguments})
        return reply.get("result") or reply

    def refused(self, tool: str, arguments=None) -> str:
        result = self.call(tool, arguments)
        if not result.get("isError"):
            return ""
        return result["content"][0]["text"].split(":", 1)[0]


def fixture() -> str:
    folder = context()
    write(folder, "authoritative/policy.md", doc_text("policy", "Policy", scope="Policy scope.",
                                                      body=SECTIONED))
    generate(folder)
    return folder


def with_candidate(folder: str) -> str:
    """A private candidate and an archived document, which must never be served."""
    a = au.plan(folder, "add", {"title": "Secret draft", "body": "CANDIDATE-ONLY-TEXT\n"})
    au.apply(folder, "add", a.request, a.plan_id, True)
    b = au.plan(folder, "add", {"title": "Old idea", "body": "ARCHIVE-ONLY-TEXT\n"})
    au.apply(folder, "add", b.request, b.plan_id, True)
    r = au.plan(folder, "retire", {"candidate": "authority-candidates/old-idea.md"})
    au.apply(folder, "retire", r.request, r.plan_id, True)
    return "authority-candidates/secret-draft.md"


def case_handshake() -> None:
    print("\nthe handshake and the tool list")
    with isolated_private_state():
        folder = fixture()
        s = Session(folder)
        init = s.replies[0]["result"]
        check(init["serverInfo"]["name"] == "charter" and init["serverInfo"]["title"] == "Charter",
              "the server is Charter")
        check(init["instructions"] == ("This server gives read-only access to this Agent Context. "
                                       "Call `get_context` before work, then use the listed "
                                       "document tools as needed. Authority candidates, archives, "
                                       "and Agent Proposals are not governing context."),
              "its instructions are the specification's, exactly")
        check(init["protocolVersion"] == "2025-06-18" and init["capabilities"] == {"tools": {"listChanged": False}},
              "it answers the protocol version asked for, with tools only")
        check(Session(folder, version="1999-01-01").replies[0]["result"]["protocolVersion"]
              == mcp.PROTOCOL_VERSIONS[0], "an unknown version is answered with the newest")
        tools = s.ask("tools/list")["result"]["tools"]
        check([t["name"] for t in tools] == ["get_context", "list_governing_documents",
                                            "get_document", "get_document_section"],
              "exactly four tools")
        check(all(t["annotations"]["readOnlyHint"] and not t["annotations"]["destructiveHint"]
                  and t["inputSchema"]["additionalProperties"] is False for t in tools),
              "each read-only, refusing undeclared arguments")
        check(s.ask("resources/list")["error"]["code"] == mcp.METHOD_NOT_FOUND
              and s.ask("prompts/list")["error"]["code"] == mcp.METHOD_NOT_FOUND,
              "no resources and no prompts")
        unknown = s.ask("tools/call", {"name": "write_document", "arguments": {}})
        check(unknown["error"]["code"] == mcp.INVALID_PARAMS, "any other tool is unknown")
        old = Session(folder, version="2024-11-05")
        check("outputSchema" not in old.ask("tools/list")["result"]["tools"][0]
              and "structuredContent" not in old.call("get_context"),
              "an older client gets no structured output")
        shutil.rmtree(folder)


def case_retrieval() -> None:
    print("\nretrieval")
    with isolated_private_state():
        folder = fixture()
        candidate = with_candidate(folder)
        s = Session(folder)
        got = s.call("get_context")
        check(got["content"][0]["text"] == read(folder, ac.CONTEXT_MAP).decode()
              and got["structuredContent"] == {"path": "AGENT-CONTEXT.md",
                                               "text": read(folder, ac.CONTEXT_MAP).decode()},
              "get_context returns AGENT-CONTEXT.md unchanged")
        listed = s.call("list_governing_documents")["structuredContent"]["documents"]
        check([d["path"] for d in listed] == ["authoritative/a.md", "authoritative/b.md",
                                             "authoritative/policy.md"]
              and listed[2] == {"id": "policy", "title": "Policy", "scope": "Policy scope.",
                                "path": "authoritative/policy.md"},
              "list_governing_documents gives each one's id, title, scope and path")
        by_path = s.call("get_document", {"document": "authoritative/policy.md"})
        by_id = s.call("get_document", {"document": "policy"})
        check(by_path["structuredContent"]["text"] == read(folder, "authoritative/policy.md").decode()
              and by_id["structuredContent"] == by_path["structuredContent"],
              "get_document returns the whole document, by path or by id")
        section = s.call("get_document_section", {"document": "policy", "heading": "boundaries"})
        check(section["structuredContent"]["text"] == "## Boundaries\n\nInside the lines.\n\n### Detail\n\nFine print.\n\n"
              and section["structuredContent"]["level"] == 2,
              "a section runs to the next heading of its level, subsections included, case ignored")
        check(s.refused("get_document_section", {"document": "policy", "heading": "Nowhere"})
              == "heading-missing" and "## Boundaries" in s.call("get_document_section", {
                  "document": "policy", "heading": "Nowhere"})["content"][0]["text"],
              "a missing heading is refused, listing the document's headings")
        check(s.refused("get_document_section", {"document": "policy", "heading": "exceptions"})
              == "heading-ambiguous", "an ambiguous heading is refused")
        check(s.call("get_document_section", {"document": "policy", "heading": "### Detail"})
              ["structuredContent"]["text"] == "### Detail\n\nFine print.\n\n",
              "leading #s pin the level")
        check(s.refused("get_document_section", {"document": "policy", "heading": "### Boundaries"})
              == "heading-missing", "a heading inside fenced code is not a heading")

        for name, code in ((candidate, "not-governing"), ("archive/old-idea.md", "not-governing"),
                           ("AGENT-CONTEXT.md", "not-governing"), (".agent-context.json", "not-governing"),
                           ("authoritative/missing.md", "not-governing"), ("secret-draft", "not-governing"),
                           ("../outside.md", "unsafe-path"), ("/etc/passwd", "unsafe-path"),
                           ("C:\\Windows\\win.ini", "unsafe-path"), ("authoritative\\a.md", "unsafe-path"),
                           ("authoritative/./a.md", "unsafe-path")):
            check(s.refused("get_document", {"document": name}) == code, f"`{name}`: {code}")

        for tool, args in (("get_context", {"extra": "x"}), ("get_context", {"task": 3}),
                           ("get_document", {}), ("get_document", {"document": 1}),
                           ("get_document", {"document": "x" * 2000}),
                           ("get_document_section", {"document": "policy"}),
                           ("get_document_section", {"document": "policy", "heading": "h" * 600}),
                           ("list_governing_documents", "not an object")):
            check(s.refused(tool, args) == "bad-arguments", f"{tool} {str(args)[:40]}: bad-arguments")

        crlf = context(docs=())
        write(crlf, "authoritative/c.md", doc_text("c", "Gamma"))
        generate(crlf)
        for rel in ("AGENT-CONTEXT.md", ".agent-context.json", "authoritative/c.md"):
            write(crlf, rel, read(crlf, rel).decode(), newline="\r\n")
        s2 = Session(crlf)
        check(s2.call("get_context")["content"][0]["text"] == read(crlf, ac.CONTEXT_MAP).decode()
              and "\r\n" in s2.call("get_document", {"document": "c"})["content"][0]["text"],
              "a CRLF checkout is served, its bytes unchanged")
        shutil.rmtree(crlf)
        shutil.rmtree(folder)


def case_revalidation() -> None:
    print("\nevery call revalidates the whole folder")
    with isolated_private_state():
        folder = fixture()
        s = Session(folder)
        check(not s.call("get_context").get("isError"), "a valid, clean Agent Context is served")
        write(folder, "notes.txt", b"mine")
        check(all(s.refused(t, a) == "context-unclean" for t, a in (
            ("get_context", {}), ("list_governing_documents", {}), ("get_document", {"document": "a"}))),
            "a stray: every tool refuses `context-unclean`")
        os.remove(os.path.join(folder, "notes.txt"))
        check(not s.call("get_context").get("isError"), "removed, the next call is served")
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited.\n"))
        check(s.refused("get_document", {"document": "b"}) == "context-invalid",
              "an edited governing document: `context-invalid` until rebuilt")
        generate(folder)
        check(not s.call("get_document", {"document": "a"}).get("isError"), "rebuilt, it is served")
        text = read(folder, ac.CONTEXT_MAP).decode()
        write(folder, ac.CONTEXT_MAP, "<<<<<<< HEAD\n" + text + ">>>>>>> other\n")
        check(s.refused("get_context") == "context-invalid", "a merge conflict: `context-invalid`")
        generate(folder)

        real = mcp._read_once
        mcp._read_once = lambda f, rel: real(f, rel) + b"changed"
        try:
            check(s.refused("get_document", {"document": "a"}) == "changed-during-read"
                  and s.refused("get_context") == "changed-during-read",
                  "bytes that differ from the validated hash: `changed-during-read`")
        finally:
            mcp._read_once = real
        try:
            os.symlink(os.path.join(folder, "authoritative", "b.md"),
                       os.path.join(folder, "authoritative", "link.md"))
        except (OSError, NotImplementedError):
            print("  - links not checked: this account cannot create a symbolic link")
        else:
            check(s.refused("get_document", {"document": "b"}) == "context-invalid",
                  "a link in the folder: `context-invalid`, never followed")
            os.remove(os.path.join(folder, "authoritative", "link.md"))
        shutil.rmtree(folder)

    print("\nan interrupted write is refused until it is rolled back")
    with isolated_private_state():
        folder = fixture()
        a = au.plan(folder, "add", {"title": "New", "body": "x\n"})
        au.apply(folder, "add", a.request, a.plan_id, True)
        g = au.plan(folder, "changeset", seeded(folder, {"alongside": "authority-candidates/new.md"}))

        class Crash(BaseException):
            pass

        def fault(step: str) -> None:
            if step == "before-commit":
                raise Crash()
        try:
            au.apply(folder, "changeset", g.request, g.plan_id, au.CONFIRM_PHRASE, fault=fault)
        except Crash:
            pass
        cs = ps.PrivateState.default().for_context(folder)
        check(ac.examine(folder).valid and tx.interrupted(cs),
              "every file is written and the folder looks valid, but the write was interrupted")
        s = Session(folder)
        check(s.refused("get_context") == "context-invalid"
              and s.refused("list_governing_documents") == "context-invalid",
              "so every tool refuses `context-invalid`")
        au.recover(folder)
        check(not s.call("get_context").get("isError")
              and "authoritative/new.md" not in json.dumps(s.call("list_governing_documents")),
              "once rolled back, the previous context is served")
        shutil.rmtree(folder)


def case_nothing_private() -> None:
    print("\nnothing private is ever disclosed")
    with isolated_private_state() as state_root:
        folder = fixture()
        with_candidate(folder)
        s = Session(folder)
        s.call("get_context")
        s.call("list_governing_documents")
        s.call("get_document", {"document": "authority-candidates/secret-draft.md"})
        s.call("get_document", {"document": "archive/old-idea.md"})
        s.call("get_document", {"document": "../" + state_root})
        write(folder, "notes.txt", b"x")
        s.call("get_context")
        os.remove(os.path.join(folder, "notes.txt"))
        s.call("get_document_section", {"document": "policy", "heading": "nope"})
        everything = json.dumps(s.replies, ensure_ascii=False)
        for secret in ("CANDIDATE-ONLY-TEXT", "ARCHIVE-ONLY-TEXT", "Secret draft", "Old idea",
                       "secret-draft.md", "old-idea", state_root, os.path.basename(state_root),
                       "contexts", "journal", "notes.txt", "private state"):
            check(secret not in everything, f"no reply mentions {secret!r}")
        codes = {r["result"]["content"][0]["text"].split(":", 1)[0] for r in s.replies
                 if "result" in r and r["result"].get("isError")}
        check(codes <= CODES, f"every refusal uses one of the eight codes ({', '.join(sorted(codes))})")
        shutil.rmtree(folder)


def case_activity() -> None:
    print("\nprivate, bounded activity")
    with isolated_private_state() as state_root:
        folder = fixture()
        before = sorted(os.listdir(folder))
        s = Session(folder)
        s.call("get_context", {"task": "Review\nthe   plan " + "x" * 200})
        s.call("get_document_section", {"document": "policy", "heading": "Boundaries"})
        s.call("get_document", {"document": "../nope"})
        events = list(reversed(mcp_activity.recent(folder)))
        check([e["event"] for e in events] == ["connect", "tool", "tool", "tool"]
              and events[0]["host"] == "test-host 1.0", "the connection and each call are recorded")
        check(events[1]["task"].startswith("Review the plan x") and len(events[1]["task"]) <= 80,
              "a task label is one line, bounded")
        check(events[2] == {k: events[2][k] for k in events[2] if k in mcp_activity.FIELDS}
              and events[2]["path"] == "authoritative/policy.md" and events[2]["heading"] == "Boundaries"
              and "text" not in events[2], "a resolved document's path, title and heading, never its text")
        check(events[3]["status"] == "refused" and events[3]["reason"] == "unsafe-path"
              and "path" not in events[3], "a refusal's reason, and no unresolved name")
        log = json.dumps(events)
        check("Inside the lines" not in log and "../nope" not in log, "no governing text and no raw argument")
        check(sorted(os.listdir(folder)) == before and state_root in
              ps.PrivateState.default().find_context(folder).base,
              "activity lives in private state, never in the Agent Context folder")

        real = mcp_activity.record
        mcp_activity.record = lambda f, e: False
        try:
            check(not s.call("get_context").get("isError"), "a retrieval succeeds when activity is dropped")
        finally:
            mcp_activity.record = real
        quiet = mcp.Server(folder, record=False)
        count = len(mcp_activity.recent(folder, 100))
        quiet.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        check(len(mcp_activity.recent(folder, 100)) == count, "a server told not to record, records nothing")
        shutil.rmtree(folder)


def case_check() -> None:
    print("\n`charter mcp --check` diagnoses and changes nothing")
    with isolated_private_state() as state_root:
        folder = fixture()

        def run_check(where: str) -> tuple:
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = mcp.check(where)
            return code, out.getvalue()

        code, said = run_check(folder)
        check(code == 0 and "valid and clean: 3 governing documents" in said
              and "listed 4 tools" in said, "a valid Agent Context: exit 0, the handshake and stdio both answer")
        check(not os.path.exists(state_root) and state_root not in said,
              "no private state was created, and none is named")
        # Whatever this machine's PATH holds: a clean installation has no `charter` on it.
        check(any(f"  note  {n}" in said for n in ("`charter`, typed in a new terminal, runs this copy",
                                                   "`charter`, typed in a new terminal, runs another copy",
                                                   "`charter` is not on PATH for new terminals"))
              and mcp.NOT_CHECKED_BY_CHECK in said and "did not check your agent host" in said,
              "it says what `charter` by name runs, and that it did not check the agent host")
        if os.name != "nt":  # Windows reads PATH from the registry, not this process
            empty, other = tempfile.mkdtemp(prefix="charter-none-"), tempfile.mkdtemp(prefix="charter-other-")
            with open(os.path.join(other, "charter"), "w") as fh:
                fh.write("#!/bin/sh\n")
            os.chmod(os.path.join(other, "charter"), 0o755)
            notes = {}
            saved = os.environ.get("PATH")
            try:
                for state, path in (("none", empty), ("this", ROOT), ("other", other)):
                    os.environ["PATH"] = path
                    notes[state] = run_check(folder)[1]
            finally:
                if saved is None:
                    os.environ.pop("PATH", None)
                else:
                    os.environ["PATH"] = saved
                shutil.rmtree(other)
                os.rmdir(empty)
            check("  note  `charter` is not on PATH for new terminals; agent hosts set up with Connect "
                  "Agents do not need it" in notes["none"]
                  and "  note  `charter`, typed in a new terminal, runs this copy" in notes["this"]
                  and f"runs another copy, from {other}; remove {other} from PATH" in notes["other"],
                  "the note follows PATH: none on it, this copy, or another copy")
        check(f"Charter {mcp.__version__}: MCP check" in said
              and all(f"  {k}" in said for k in ("build ", "launcher ", "charter.py ", "python ", "map format "))
              and f"  context map  {ac.MAP_FORMAT_VERSION} (the format this Charter generates)" in said,
              "it identifies the running Charter: version, build, launcher, Python, and both map formats")
        write(folder, "notes.txt", b"x")
        code, said = run_check(folder)
        check(code == 1 and "context-unclean" in said and "notes.txt" in said,
              "an unclean context: exit 1, naming the stray for the person")
        os.remove(os.path.join(folder, "notes.txt"))
        a = au.plan(folder, "add", {"title": "New", "body": "x\n"})
        au.apply(folder, "add", a.request, a.plan_id, True)
        g = au.plan(folder, "changeset", seeded(folder, {"alongside": "authority-candidates/new.md"}))

        class Crash(BaseException):
            pass
        try:
            au.apply(folder, "changeset", g.request, g.plan_id, au.CONFIRM_PHRASE,
                     fault=lambda step: (_ for _ in ()).throw(Crash()) if step == "before-commit" else None)
        except Crash:
            pass
        cs = ps.PrivateState.default().find_context(folder)
        code, said = run_check(folder)
        check(code == 1 and "interrupted" in said and tx.interrupted(cs) and state_root not in said,
              "an interrupted write is reported, left for recovery, and private state is not named")
        shutil.rmtree(folder)


def case_stdio_process() -> None:
    print("\na real stdio process")
    with tempfile.TemporaryDirectory(prefix="charter-mcp-") as tmp:
        from tests.harness import isolated_private_state as iso
        with iso(tmp):
            folder = fixture()
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "stdio-test", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "get_context", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "get_document", "arguments": {"document": "policy"}}},
        ]
        stdin = b"\xef\xbb\xbf" + b"\n".join(json.dumps(m).encode() for m in lines) + b"\nnot json\n"
        proc = subprocess.run([sys.executable, os.path.join(HERE, "_launch.py"), tmp, "mcp",
                               "--context", folder], input=stdin, capture_output=True, timeout=120)
        replies = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
        check(proc.returncode == 0 and proc.stderr == b"", "it exits 0 when the host closes stdin, saying nothing on stderr")
        check([r.get("id") for r in replies] == [1, 2, 3, 4, None]
              and replies[-1]["error"]["code"] == mcp.PARSE_ERROR,
              "every message is answered on stdout as one JSON line; a notification is not")
        check(replies[2]["result"]["content"][0]["text"] == read(folder, ac.CONTEXT_MAP).decode()
              and replies[3]["result"]["structuredContent"]["id"] == "policy",
              "it serves the folder named on its command line")
        with iso(tmp):
            events = mcp_activity.recent(folder)
        check(events and events[-1]["event"] == "connect" and events[-1]["host"] == "stdio-test 1",
              "and records its activity privately")
        proc = subprocess.run([sys.executable, os.path.join(ROOT, "charter.py"), "mcp", "--context",
                               os.path.join(tmp, "no-such-folder")],
                              input=json.dumps(lines[0]).encode() + b"\n" + json.dumps(lines[3]).encode() + b"\n",
                              capture_output=True, timeout=120)
        replies = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines()]
        check(replies[0]["result"]["instructions"] == mcp.INSTRUCTIONS
              and replies[1]["result"]["content"][0]["text"].startswith("context-invalid:")
              and "no-such-folder" not in proc.stdout.decode("utf-8") and proc.stderr == b"",
              "a folder that is not there: the handshake completes, every tool refuses")


def case_front_matter_boundary() -> None:
    print("\nMCP agrees with validation on where front matter ends")
    with isolated_private_state():
        # ARCH-07: a close fence with a trailing space validates, so MCP must
        # also treat it as the end of front matter and find the body's sections.
        folder = context()
        # A body with a later `---` thematic break: a close fence with a trailing
        # space must still end the front matter, or MCP would mistake the break
        # for the close and lose the earlier headings (ARCH-07).
        body = ("# Policy\n\nIntro.\n\n## Boundaries\n\nInside the lines.\n\n---\n\n"
                "## Later\n\nAfter the break.\n")
        td = doc_text("policy", "Policy", scope="s", body=body).replace(
            "---\n\n# Policy", "--- \n\n# Policy")
        write(folder, "authoritative/policy.md", td)
        generate(folder)
        s = Session(folder)
        sec = s.call("get_document_section", {"document": "policy", "heading": "Boundaries"})
        check(not sec.get("isError") and "Inside the lines" in sec["content"][0]["text"],
              "a trailing-space close fence still yields the document's sections, not just the part "
              "after a later thematic break")
        shutil.rmtree(folder)
    with isolated_private_state():
        # CM-09: a governing document with CR-only line endings (same LF-normalized
        # content and hash) must still be served whole, not 'changed-during-read'.
        folder = context()
        write(folder, "authoritative/policy.md", doc_text("policy", "Policy", body=SECTIONED))
        generate(folder)
        write(folder, "authoritative/policy.md", doc_text("policy", "Policy", body=SECTIONED),
              newline="\r")
        s = Session(folder)
        got = s.call("get_document", {"document": "policy"})
        check(not got.get("isError"),
              "a CR-only governing document is served whole, not 'changed-during-read'")
        shutil.rmtree(folder)


def case_resilience() -> None:
    print("\nthe server survives hostile JSON-RPC and keeps its read-only boundary")
    # A reply with an id that cannot be UTF-8 encoded still serializes.
    data = mcp._encode({"jsonrpc": "2.0", "id": "\ud800", "result": {}})
    check(isinstance(data, bytes) and data.endswith(b"}"),
          "a reply carrying an unencodable id still serializes, so it cannot end the session")
    with isolated_private_state():
        folder = fixture()
        srv = mcp.Server(folder, record=False)
        srv.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        nested = [{"jsonrpc": "2.0", "id": 1, "method": "ping"}]
        for _ in range(3000):
            nested = [nested]
        reply = srv.handle(nested)
        check(isinstance(reply, list) and reply
              and reply[0].get("error", {}).get("code") == mcp.INVALID_REQUEST,
              "a deeply nested batch is one Invalid Request, not a stack-exhausting crash")
        check(srv.handle([]).get("error", {}).get("code") == mcp.INVALID_REQUEST,
              "an empty batch is an Invalid Request")
        for bad in (1.5, True, {"a": 1}, [1]):
            r = srv.handle({"jsonrpc": "2.0", "id": bad, "method": "ping"})
            check(r.get("id") is None and r.get("error", {}).get("code") == mcp.INVALID_REQUEST,
                  f"an id of {bad!r} is refused and never echoed back")
        ok = srv.handle({"jsonrpc": "2.0", "id": "after", "method": "ping"})
        check(ok.get("id") == "after" and "result" in ok, "and the session keeps working afterward")
        # Over the transport: a non-finite value is a parse error, and an
        # over-long line is refused, with the next line still served.
        out = io.BytesIO()
        oversized = b'{"jsonrpc":"2.0","id":2,"method":"' + b"x" * (9 * 1024 * 1024) + b'"}\n'
        stdin = (b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":Infinity}}\n'
                 + oversized + b'{"jsonrpc":"2.0","id":3,"method":"ping"}\n')
        srv.serve(io.BytesIO(stdin), out)
        replies = [json.loads(line) for line in out.getvalue().splitlines()]
        check(replies[0].get("error", {}).get("code") == mcp.PARSE_ERROR
              and replies[1].get("error", {}).get("code") == mcp.PARSE_ERROR
              and replies[-1].get("id") == 3,
              "a non-finite value and an over-long line are parse errors, and the next line is still served")
        shutil.rmtree(folder)


TOOL_CALLS = (("get_context", {}), ("list_governing_documents", {}),
              ("get_document", {"document": "policy"}),
              ("get_document_section", {"document": "policy", "heading": "Boundaries"}))


@contextlib.contextmanager
def _after_answering(meddle):
    """Run `meddle` once a call has its answer, before the response is returned."""
    real = mcp.Server._answer

    def answer(self, name, args, exam):
        out = real(self, name, args, exam)
        meddle()
        return out
    mcp.Server._answer = answer
    try:
        yield
    finally:
        mcp.Server._answer = real


def case_settled_before_response() -> None:
    print("\nthe whole context is validated again immediately before every response")

    def edit_other(folder):
        write(folder, "authoritative/b.md", doc_text("b", "Beta", body="Changed meanwhile.\n"))
        generate(folder)

    def edit_stale(folder):
        write(folder, "authoritative/b.md", doc_text("b", "Beta", body="Changed, map stale.\n"))

    def stray(folder):
        write(folder, "notes.txt", b"mine")

    def journal(folder):
        cs = ps.PrivateState.default().for_context(folder)
        write(cs.staging_dir(tx.JOURNAL_KIND), tx.JOURNAL_FILE, b"{}")

    def settings(folder):
        generate(folder, project="Renamed meanwhile")

    changes = (("another governing document changed, still valid", edit_other),
               ("another governing document changed, the map stale", edit_stale),
               ("a stray added", stray), ("a write begun (a journal created)", journal),
               ("the settings changed, still valid", settings))
    for tool, args in TOOL_CALLS:
        for label, change in changes:
            with isolated_private_state():
                folder = fixture()
                s = Session(folder, record=False)
                if change is edit_other:
                    check(not s.call(tool, args).get("isError"),
                          f"{tool}: served while nothing changes")
                with _after_answering(lambda: change(folder)):
                    code = s.refused(tool, args)
                check(code == "changed-during-read",
                      f"{tool}: {label} while answering: `changed-during-read`")
                shutil.rmtree(folder)
    with isolated_private_state():
        folder = fixture()
        s = Session(folder)
        with _after_answering(lambda: stray(folder)):
            s.refused("get_document", {"document": "policy"})
        recent = mcp_activity.recent(folder, 1)[0]
        check(recent["status"] == "refused" and recent["reason"] == "changed-during-read"
              and recent["path"] == "authoritative/policy.md",
              "the refusal is what activity records, never a success")
        shutil.rmtree(folder)


def _deny_listing(path: str):
    """Deny this user listing `path`; returns how to undo it, or None when this
    system will not."""
    if os.name == "nt":
        from app import host_state as hs
        sid = "*" + hs._user_sid()
        done = subprocess.run(["icacls", path, "/deny", f"{sid}:(RD)"], capture_output=True)
        if done.returncode != 0:
            return None
        try:
            os.listdir(path)
        except OSError:
            return lambda: subprocess.run(["icacls", path, "/remove:d", sid], capture_output=True)
        subprocess.run(["icacls", path, "/remove:d", sid], capture_output=True)
        return None
    os.chmod(path, 0)
    try:
        os.listdir(path)
    except OSError:
        return lambda: os.chmod(path, 0o700)
    os.chmod(path, 0o700)
    return None


def case_private_state_fails_closed() -> None:
    print("\nprivate state that is there but cannot be trusted is refused; absent state is served")
    from tests.authority import make_link, remove_link
    with isolated_private_state() as root:
        folder = fixture()
        s = Session(folder, record=False)
        check(not s.call("get_context").get("isError") and not os.path.exists(root),
              "no private state at all: served, and nothing is created")
        shutil.rmtree(folder)

    def refused_with(prepare, label):
        with isolated_private_state():
            folder = fixture()
            cs = ps.PrivateState.default().for_context(folder)
            undo = prepare(folder, cs)
            if undo is False:
                print(f"  - not checked: {label} (this system would not set it up)")
                shutil.rmtree(folder)
                return
            try:
                s = Session(folder, record=False)
                codes = {s.refused(t, a) for t, a in TOOL_CALLS}
                check(codes == {"context-invalid"}, f"{label}: every tool refuses `context-invalid`")
            finally:
                if callable(undo):
                    undo()
            shutil.rmtree(folder)

    def unreadable_record(folder, cs, journal=True):
        write(cs.base, ps.CONTEXT_RECORD, b"{broken")
        if journal:
            write(cs.staging_dir(tx.JOURNAL_KIND), tx.JOURNAL_FILE, b"{}")

    def other_folder(folder, cs):
        write(cs.base, ps.CONTEXT_RECORD, json.dumps({"version": 1, "folder": folder + "-other"}))

    def record_lost(folder, cs):
        os.remove(cs.path(ps.CONTEXT_RECORD))
        write(cs.staging_dir(tx.JOURNAL_KIND), tx.JOURNAL_FILE, b"{}")

    def staging_a_file(folder, cs):
        shutil.rmtree(cs.path(ps.STAGING))
        write(cs.base, ps.STAGING, b"not a folder")

    def journal_a_folder(folder, cs):
        os.makedirs(os.path.join(cs.staging_dir(tx.JOURNAL_KIND), tx.JOURNAL_FILE))

    def unlistable(folder, cs):
        return _deny_listing(cs.staging_dir(tx.JOURNAL_KIND)) or False

    def base_a_link(folder, cs):
        real = cs.base + "-real"
        os.rename(cs.base, real)
        if not make_link(cs.base, real):
            os.rename(real, cs.base)
            return False
        return lambda: remove_link(cs.base)

    refused_with(unreadable_record, "an unreadable folder record, with a journal")
    refused_with(lambda f, c: unreadable_record(f, c, journal=False),
                 "an unreadable folder record, even without a journal")
    refused_with(other_folder, "a folder record naming another folder")
    refused_with(record_lost, "a lost folder record beside a journal")
    refused_with(staging_a_file, "a staging folder that is a file")
    refused_with(journal_a_folder, "a journal that is a folder")
    refused_with(unlistable, "a journal folder that cannot be listed")
    refused_with(base_a_link, "this context's private state reached through a link")

    with isolated_private_state():
        folder = fixture()
        cs = ps.PrivateState.default().for_context(folder)
        os.remove(cs.path(ps.CONTEXT_RECORD))
        check(not Session(folder, record=False).call("get_context").get("isError"),
              "a lost folder record with no journal anywhere: still served")
        shutil.rmtree(folder)


def case_map_format() -> None:
    print("\na map-format mismatch, in both directions, is refused with its own remedy")
    from app import mcp_activity
    from tests.agent_context import with_map_format
    with isolated_private_state():
        folder = fixture()
        for version, code, remedy in ((1, "map-outdated", "Rebuild Agent Context"),
                                      (2, "map-outdated", "Rebuild Agent Context"),
                                      (ac.MAP_FORMAT_VERSION + 1, "server-outdated",
                                       "restart the agent host")):
            with_map_format(folder, version)
            session = Session(folder)
            result = session.call("get_context")
            text = result["content"][0]["text"]
            check(result.get("isError") and text.startswith(code + ":") and remedy in text,
                  f"map-format version {version} against this server: `{code}`, naming the remedy")
            message = mcp.MESSAGES[code]
            check(not any(ch.isdigit() for ch in message) and folder not in text
                  and len([x for x in message.split(". ") if x]) <= 3,
                  f"`{code}`: plain and short, with no version number or path")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                exit_code = mcp.check(folder)
            said = out.getvalue()
            check(exit_code == 1 and f"(agents see `{code}`)" in said
                  and f"  context map  {version} " in said,
                  f"`--check` says which code agents see, and shows the map format this context records")
            check(mcp_activity.recent(folder, 1)[0]["reason"] == code,
                  f"the refusal is recorded privately as `{code}`")
        check("not at fault" in mcp.MESSAGES["server-outdated"]
              and "context-invalid" not in (mcp.MESSAGES["server-outdated"] + mcp.MESSAGES["map-outdated"]),
              "a server older than the context says the context is not at fault")
        # A genuine mismatch with an older map format is still `context-invalid`.
        generate(folder)
        with_map_format(folder, 1)
        write(folder, "authoritative/a.md", read(folder, "authoritative/a.md") + b"Edited.\n")
        result = Session(folder).call("get_context")
        check(result["content"][0]["text"].startswith("context-invalid:"),
              "an older map whose documents no longer match is genuinely invalid: `context-invalid`")
        shutil.rmtree(folder)


def case_integrity_refusal() -> None:
    print("\ncontext changes need review: every tool revalidates, refuses, and returns no context")
    with isolated_private_state():
        folder = fixture()
        approved = {rel: read(folder, rel) for rel in (
            "authoritative/a.md", "authoritative/b.md", "authoritative/policy.md",
            ac.CONTEXT_MAP, ac.METADATA)}
        session = Session(folder)
        served = [session.call("get_context"), session.call("list_governing_documents"),
                  session.call("get_document", {"document": "authoritative/policy.md"}),
                  session.call("get_document_section", {"document": "authoritative/policy.md",
                                                        "heading": "Boundaries"})]
        check(not any(r.get("isError") for r in served),
              "a session retrieves the valid context with every tool first")
        tools = (("get_context", None), ("list_governing_documents", None),
                 ("get_document", {"document": "authoritative/policy.md"}),
                 ("get_document_section", {"document": "authoritative/policy.md", "heading": "Boundaries"}))
        # Nothing an agent could use as context: no path, title, scope, excerpt or map text.
        leaks = ("authoritative", ".md", "AGENT-CONTEXT", ".agent-context", folder, "Policy", "Alpha",
                 "Beta", "Gamma", "scope", "Inside the lines", "Boundaries", "Current governing",
                 "Test project", "sha256")

        def restore() -> None:
            for name in ("c.md",):
                path = os.path.join(folder, "authoritative", name)
                if os.path.exists(path):
                    os.remove(path)
            for rel, data in approved.items():
                write(folder, rel, data)

        for label, damage, observed in (
                ("a governing document changed",
                 lambda: write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited.\n")),
                 "1 file does not match the approved context"),
                ("a governing document missing",
                 lambda: os.remove(os.path.join(folder, "authoritative", "b.md")),
                 "1 document is missing from it"),
                ("an unrecorded document present",
                 lambda: write(folder, "authoritative/c.md", doc_text("c", "Gamma")),
                 "1 document is not in it"),
                ("a recorded file that cannot be read",
                 lambda: write(folder, "authoritative/b.md", b"---\nid: b\n\xff\n---\n"),
                 "1 file cannot be verified"),
                ("two changed and one missing",
                 lambda: (write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="x\n")),
                          write(folder, "authoritative/policy.md", doc_text("policy", "Policy", body="y\n")),
                          os.remove(os.path.join(folder, "authoritative", "b.md"))),
                 "2 files do not match the approved context, 1 document is missing from it"),
                ("only the map's own hash",
                 lambda: write(folder, ac.CONTEXT_MAP, approved[ac.CONTEXT_MAP] + b"\nA note.\n"),
                 "1 file does not match the approved context"),
                ("no usable map",
                 lambda: os.remove(os.path.join(folder, ac.METADATA)),
                 "3 documents are not in an approved context")):
            damage()
            texts = []
            for tool, arguments in tools:
                result = session.call(tool, arguments)
                texts.append(result["content"][0]["text"] if result.get("isError") else "")
            check(all(t.startswith("context-invalid: ") for t in texts) and len(set(texts)) == 1,
                  f"{label}: every one of the four tools refuses with `context-invalid`, on the same session")
            text = texts[0]
            check(observed in text and "Charter context is unavailable now" in text,
                  f"  saying Charter context is unavailable, by kind and count: {observed}")
            check("Do not rely on Charter context you retrieved earlier in this session." in text
                  and "Report to the person that Charter context is unavailable, rather than guessing "
                      "or continuing from earlier context." in text,
                  "  telling the agent not to rely on earlier Charter context, and to tell the person")
            found = [w for w in leaks if w.lower() in text.lower()]
            check(not found, "  and returning no path, title, scope, excerpt or map text"
                  + (f" (found {found})" if found else ""))
            restore()
            check(not session.call("get_context").get("isError"),
                  "  restored outside Charter, the same session is served again")
        check(set(mcp.MESSAGES) == CODES | {"map-outdated", "server-outdated"},
              "the refusal codes are exactly the governed ten: `context-invalid` is kept, and no code "
              "is added for this condition")
        shutil.rmtree(folder)


def run() -> None:
    case_handshake()
    case_integrity_refusal()
    case_retrieval()
    case_revalidation()
    case_settled_before_response()
    case_private_state_fails_closed()
    case_map_format()
    case_nothing_private()
    case_activity()
    case_check()
    case_front_matter_boundary()
    case_resilience()
    case_stdio_process()
    print(f"\n{OK} All MCP checks passed.")


if __name__ == "__main__":
    run()
