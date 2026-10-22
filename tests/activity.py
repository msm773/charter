"""Private, bounded MCP activity. Run: python -m tests.activity

MCP Context Access Specification §7:

  * only the permitted fields, each bounded, from fixed vocabularies;
  * kept in the Agent Context's private state, never in its folder;
  * written promptly or dropped, never failing or delaying a retrieval;
  * bounded on disk: rotated, one previous file kept;
  * read for the person only, without creating private state.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import host_state as hs  # noqa: E402
from app import mcp_activity as act  # noqa: E402
from app import private_store as ps  # noqa: E402
from tests.agent_context import context, snapshot  # noqa: E402
from tests.harness import ScriptedWrites, isolated_private_state  # noqa: E402

OK = "ok"


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def refused(**fields) -> bool:
    try:
        act.event(**fields)
    except ValueError:
        return True
    return False


def case_fields() -> None:
    print("\nonly the permitted fields")
    connect = act.event(session="s1", host="claude-code 2.1", event="connect", status="ok")
    check(set(connect) == {"v", "ts", "session", "host", "event", "status"},
          "a connection: time, session, host, event and status")
    call = act.event(session="s1", host="h", task="t", event="tool", tool="get_document",
                     status="ok", path="authoritative/a.md", title="Alpha", heading="Scope")
    check(set(call) <= set(act.FIELDS), "a call: only the specification's fields")
    check(refused(event="tool", status="ok"), "a tool call must name its tool")
    check(refused(event="connect", tool="get_context", status="ok"), "a connection names no tool")
    for label, fields in (("an unknown event", {"event": "write", "status": "ok"}),
                          ("an unknown tool", {"event": "tool", "tool": "put", "status": "ok"}),
                          ("an unknown status", {"event": "connect", "status": "maybe"}),
                          ("a reason outside the eight", {"event": "connect", "status": "refused",
                                                         "reason": "surface-unbound"}),
                          ("governing text", {"event": "connect", "status": "ok", "text": "x"}),
                          ("raw arguments", {"event": "connect", "status": "ok", "arguments": "{}"}),
                          ("a client label", {"event": "connect", "status": "ok", "client": "x"})):
        check(refused(**fields), f"{label} is refused")
    label = act.event(event="tool", tool="get_context", status="ok",
                      task="line\none\ttab " + "x" * 300, host="h\x00ost")
    check(label["task"].startswith("line one tab ") and len(label["task"]) <= act.TASK_LIMIT
          and label["host"] == "h ost", "labels are one printable line, bounded")


def case_storage() -> None:
    print("\nkept privately, bounded, never in the way")
    with isolated_private_state() as root:
        folder = context()
        before = snapshot(folder)
        entry = act.event(session="s", event="connect", status="ok")
        check(act.record(folder, entry) and snapshot(folder) == before,
              "an event is recorded, and the Agent Context folder is unchanged")
        cs = ps.PrivateState.default().find_context(folder)
        log = os.path.join(cs.base, act.FOLDER, act.LOG)
        check(os.path.isfile(log) and log.startswith(root), "in the context's private state")
        check(not act.record(os.path.join(folder, "missing"), entry),
              "nothing is recorded for a folder that is not there")

        with hs.file_lock(os.path.join(cs.base, act.FOLDER, ".lock"), 1.0):
            started = time.monotonic()
            check(not act.record(folder, entry) and time.monotonic() - started < 2,
                  "while another writer holds the log, the event is dropped promptly")

        with open(log, "ab") as fh:
            fh.write(b'{"v": 1, "ts": "cut short')  # a writer killed mid-line
        act.record(folder, act.event(session="s", event="tool", tool="get_context", status="ok"))
        events = act.recent(folder)
        check(events[0]["tool"] == "get_context" and all(isinstance(e, dict) for e in events),
              "a line cut short is skipped, and the next event starts afresh")

        progress = iter([6])
        with ScriptedWrites(lambda path, data: next(progress, 0) if path == log else None):
            dropped = act.record(folder, act.event(session="s", event="tool",
                                                   tool="get_document", status="ok"))
        with ScriptedWrites(lambda path, data: min(len(data), 4) if path == log else None):
            kept = act.record(folder, act.event(session="s", event="tool",
                                                tool="list_governing_documents", status="ok"))
        events = act.recent(folder)
        check(not dropped and kept and events[0]["tool"] == "list_governing_documents"
              and "get_document" not in [e.get("tool") for e in events],
              "a line the system stops writing part-way is dropped, never raised, and one "
              "written in partial writes is recorded whole after it")

        with open(log, "ab") as fh:
            fh.write(b"x" * act.MAX_LOG_BYTES)
        act.record(folder, act.event(session="s2", event="connect", status="ok"))
        rotated = os.path.join(cs.base, act.FOLDER, act.ROTATED)
        check(os.path.isfile(rotated) and os.path.getsize(log) < 4096,
              "past its size limit the log rotates, keeping one previous file")
        check(act.recent(folder)[0]["session"] == "s2", "and the newest event is read first")
        shutil.rmtree(folder)

    with isolated_private_state() as root:
        folder = context()
        check(act.recent(folder) == [] and not os.path.exists(root),
              "reading activity creates no private state")
        shutil.rmtree(folder)


def case_never_served() -> None:
    print("\nactivity is never served to an agent")
    from app import mcp
    with isolated_private_state():
        folder = context()
        server = mcp.Server(folder)
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"clientInfo": {"name": "probe"}}})
        reply = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                               "params": {"name": "get_document",
                                          "arguments": {"document": "activity/mcp-activity.jsonl"}}})
        check(reply["result"]["isError"] and "probe" not in json.dumps(reply),
              "no tool returns activity")
        check([e["event"] for e in reversed(act.recent(folder))] == ["connect", "tool"],
              "while the person can read it")
        shutil.rmtree(folder)


def run() -> None:
    case_fields()
    case_storage()
    case_never_served()
    print(f"\n{OK} All activity checks passed.")


if __name__ == "__main__":
    run()
