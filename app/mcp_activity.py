"""Private, bounded activity metadata about MCP access to an Agent Context.

MCP Context Access Specification §7. Charter may record, about
MCP connections and calls: the time, a per-process session identifier, the
host's self-reported label, an optional task label, the tool, the result
status, the reason code, and — only for a resolved governing document — its
path, title and matched heading. Nothing else: never governing text, prompts,
responses, credentials or raw arguments.

Activity is private local state, kept with the Agent Context's other private
state on this computer. It is never governing context, never committed, never
served to agents, and may be lost without affecting the Agent Context.
Recording never delays or fails a retrieval: an event that cannot be written
promptly is dropped. A record proves only that the server handled a request,
not who the agent was, or that it understood or followed anything.
"""
from __future__ import annotations

import json
import os
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import host_state as hs
from . import private_store as ps

SCHEMA = 1
FOLDER = "activity"
LOG = "mcp-activity.jsonl"
ROTATED = "mcp-activity.1.jsonl"
LOCK_TIMEOUT = 0.5
MAX_LOG_BYTES = 1024 * 1024          # rotate past this; one previous file is kept
MAX_LINE_BYTES = 2048
TAIL_BYTES = 64 * 1024

HOST_LIMIT = 60
TASK_LIMIT = 80
FIELD_LIMIT = 200

EVENTS = ("connect", "tool")
TOOLS = ("get_context", "list_governing_documents", "get_document", "get_document_section",
         "unknown")
STATUSES = ("ok", "refused")
REASONS = ("", "context-invalid", "context-unclean", "changed-during-read", "not-governing",
           "unsafe-path", "heading-missing", "heading-ambiguous", "bad-arguments")
FIELDS = ("v", "ts", "session", "host", "task", "event", "tool", "status", "reason", "path",
          "title", "heading")

_O_BINARY = getattr(os, "O_BINARY", 0)


def clean_label(value: Any, limit: int) -> str:
    """A display label: printable, one line, whitespace collapsed, bounded."""
    text = "" if value is None else str(value)
    text = "".join(" " if unicodedata.category(ch).startswith(("C", "Z")) else ch for ch in text)
    return " ".join(text.split())[:limit].strip()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def event(**fields: Any) -> Dict[str, Any]:
    """One event, restricted to the permitted fields, each bounded. Values
    outside the fixed vocabularies are refused rather than recorded."""
    out: Dict[str, Any] = {"v": SCHEMA, "ts": _now()}
    for key in FIELDS[2:]:
        value = fields.get(key)
        if value in (None, ""):
            continue
        limit = {"host": HOST_LIMIT, "task": TASK_LIMIT}.get(key, FIELD_LIMIT)
        out[key] = clean_label(value, limit)
    # A connection names no tool; every tool call names one.
    tools = ("",) if out.get("event") == "connect" else TOOLS
    for key, allowed in (("event", EVENTS), ("tool", tools), ("status", STATUSES),
                         ("reason", REASONS)):
        if out.get(key, "") not in allowed:
            raise ValueError(f"`{key}` is not a recorded value")
    unknown = set(fields) - set(FIELDS[2:])
    if unknown:
        raise ValueError("not an activity field: " + ", ".join(sorted(unknown)))
    return out


def _files(cs: ps.ContextState):
    folder = cs.path(FOLDER)
    return folder, os.path.join(folder, LOG), os.path.join(folder, ROTATED), \
        os.path.join(folder, ".lock")


def record(folder: str, entry: Dict[str, Any]) -> bool:
    """Append one event to the private activity of the Agent Context at
    `folder`. Dropped, returning False, when it cannot be written promptly or
    the folder is not there. Never raises."""
    try:
        if not os.path.isdir(folder):
            return False
        cs = ps.PrivateState.default().for_context(folder)
        directory, log, rotated, lock = _files(cs)
        data = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(data) > MAX_LINE_BYTES:
            return False
        os.makedirs(directory, mode=0o700, exist_ok=True)
        with hs.file_lock(lock, LOCK_TIMEOUT) as held:
            if not held:
                return False
            try:
                if os.path.getsize(log) >= MAX_LOG_BYTES:
                    os.replace(log, rotated)
            except OSError:
                pass  # absent, or open in a reader on Windows: rotate next time
            fd = os.open(log, os.O_RDWR | os.O_APPEND | os.O_CREAT | _O_BINARY, 0o600)
            try:
                end = os.lseek(fd, 0, os.SEEK_END)
                if end:
                    os.lseek(fd, end - 1, os.SEEK_SET)
                    if os.read(fd, 1) != b"\n":
                        data = b"\n" + data  # a writer killed mid-line: start afresh
                os.write(fd, data)
            finally:
                os.close(fd)
        return True
    except Exception:  # noqa: BLE001 — activity never fails a retrieval
        return False


def _tail(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - TAIL_BYTES))
            raw = fh.read()
    except OSError:
        return []
    lines = raw.split(b"\n")
    if size > TAIL_BYTES:
        lines = lines[1:]  # the first may be cut
    out = []
    for line in lines:
        try:
            item = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(item, dict) and item.get("v") == SCHEMA:
            out.append({k: item[k] for k in FIELDS if k in item})
    return out


def recent(folder: str, limit: int = 30) -> List[Dict[str, Any]]:
    """The newest events for the Agent Context at `folder`, newest first, at
    most `limit`. For the person only; never returned to an agent. Reads
    without creating private state."""
    cs: Optional[ps.ContextState] = ps.PrivateState.default().find_context(folder)
    if cs is None:
        return []
    _directory, log, rotated, _lock = _files(cs)
    events = _tail(log)
    if len(events) < limit:
        events = _tail(rotated) + events
    return list(reversed(events[-limit:]))
