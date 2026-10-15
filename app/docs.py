"""The document model: governing documents and authority candidates.

Documents are Markdown files with a restricted, deterministic front-matter
block. The codec here is intentionally not a general YAML implementation: we
only emit what we can parse back, so rendering is stable and round-trips
byte-for-byte. Which documents govern is decided by `agent_context`.
"""
from __future__ import annotations

import hashlib
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


# `active`: a current candidate, or a document that governs today.
# `superseded`: replaced by another document; says which in `superseded_by`.
# `retired`: kept for history, with no active role.
LIFECYCLE = ("active", "superseded", "retired")
RETIRED = ("superseded", "retired")

SCALAR_FIELDS = [
    "id",
    "title",
    "status",
    "authority",
    "scope",
    "source",
    "source_sha256",
    "created",
    "updated",
]
# The only relationship a document records: which document it replaced, and
# which replaced it. Both sides are always written in the same act.
RELATIONSHIP_FIELDS = ["supersedes", "superseded_by"]
LIST_FIELDS = RELATIONSHIP_FIELDS
FIELD_ORDER = SCALAR_FIELDS + LIST_FIELDS

REQUIRED = ["id", "title", "authority", "created", "updated"]
VALID_AUTHORITY = {"authoritative", "non-authoritative"}

FENCE = "---"
_SAFE_SCALAR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 _.,/@()+&':-]*$")


# --- front matter codec ------------------------------------------------------

def _quote(value: str) -> str:
    if value == "":
        return '""'
    if _SAFE_SCALAR.match(value) and not value.endswith(" "):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"':
        body = raw[1:-1]
        out, i = [], 0
        while i < len(body):
            ch = body[i]
            if ch == "\\" and i + 1 < len(body):
                nxt = body[i + 1]
                out.append({"n": "\n", '"': '"', "\\": "\\"}.get(nxt, nxt))
                i += 2
            else:
                out.append(ch)
                i += 1
        return "".join(out)
    return raw


def render_front_matter(meta: Dict[str, Any]) -> str:
    lines = [FENCE]
    keys = [k for k in FIELD_ORDER if k in meta]
    keys += sorted(k for k in meta if k not in FIELD_ORDER)
    for key in keys:
        value = meta[key]
        if key in LIST_FIELDS or isinstance(value, list):
            items = [str(v) for v in (value or [])]
            if not items:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}:")
                for item in items:
                    lines.append(f"  - {_quote(item)}")
        else:
            lines.append(f"{key}: {_quote('' if value is None else str(value))}")
    lines.append(FENCE)
    return "\n".join(lines) + "\n"


def is_front_matter_fence(line: str) -> bool:
    """Whether `line` is a front-matter fence: `---`, ignoring a trailing carriage
    return or spaces. The one fence rule shared by validation, legacy-block
    detection and MCP body extraction, so they agree on where front matter ends."""
    return line.rstrip() == FENCE


def parse_front_matter(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """Return (meta, body). meta is None when there is no front matter. Line
    endings — CRLF and a lone CR — are normalized first, so a document saved with
    any convention parses the same way."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalised.split("\n")
    if not lines or lines[0] != FENCE:
        return None, text
    close = next((i for i in range(1, len(lines)) if is_front_matter_fence(lines[i])), -1)
    if close == -1:
        return None, text
    rest = "\n".join(lines[close + 1:])

    meta: Dict[str, Any] = {}
    current_list: Optional[str] = None
    for line in lines[1:close]:
        if not line.strip():
            continue
        if line.startswith(("  - ", "- ")) and current_list:
            meta[current_list].append(_unquote(line.split("- ", 1)[1]))
            continue
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        key = key.strip()
        raw = raw.strip()
        if raw == "":
            meta[key] = []
            current_list = key
        elif raw == "[]":
            meta[key] = []
            current_list = None
        elif raw.startswith("[") and raw.endswith("]"):
            inner = raw[1:-1].strip()
            meta[key] = [_unquote(p.strip()) for p in inner.split(",")] if inner else []
            current_list = None
        else:
            meta[key] = _unquote(raw)
            current_list = None
    return meta, rest


_LEGACY_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t].*)?$")
_LEGACY_ITEM = re.compile(r"^[ \t]*- ")
# A front-matter block is recognized only within the first lines of a text.
_LEGACY_LINES = 200


# Characters that are never text in a document: NUL and the other C0 controls
# apart from tab, line breaks and page breaks, and DEL. Text that holds them
# was decoded wrongly or is not text at all, and is refused, never repaired.
_NOT_TEXT = re.compile(r"[\x00-\x08\x0e-\x1f\x7f]")


def not_text(text: str) -> str:
    """How `text` holds characters that are not text, worded for the person,
    or "" when it holds none."""
    found = _NOT_TEXT.search(text or "")
    if not found:
        return ""
    return f"it holds a character that is not text (U+{ord(found.group()):04X})"


def leading_front_matter(text: str) -> Optional[Tuple[Dict[str, Any], str, List[str]]]:
    """A recognizable front-matter block at the top of `text` — after any BOM
    and blank lines — as (meta, the text after it, its keys in order); or None.

    Recognized only when it is unmistakable: an opening line that is exactly
    `---`, a closing line that is exactly `---` within the first lines, at
    least one key, and nothing between but `key: value`, `key:` and `- item`
    lines. Ordinary Markdown that opens with a thematic break, and a block that
    is never closed or holds anything else, is not front matter."""
    norm = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    lines = norm.split("\n")
    start = 0
    while start < len(lines) and not lines[start].strip():
        start += 1
    if start >= len(lines) or not is_front_matter_fence(lines[start]):
        return None
    keys: List[str] = []
    for end in range(start + 1, min(len(lines), start + 1 + _LEGACY_LINES)):
        line = lines[end]
        if is_front_matter_fence(line):
            if not keys:
                return None
            meta, _rest = parse_front_matter("\n".join(lines[start:end + 1]) + "\n")
            return meta or {}, "\n".join(lines[end + 1:]).lstrip("\n"), keys
        if not line.strip():
            continue
        match = _LEGACY_KEY.match(line)
        if match:
            keys.append(match.group(1))
        elif not (keys and _LEGACY_ITEM.match(line)):
            return None
    return None


def single_line(value: Any) -> str:
    """`value` as a usable title or scope: one non-empty line of text, or ''."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return "" if not value or "\n" in value or "\r" in value else value


# --- document ----------------------------------------------------------------

@dataclass
class Document:
    path: str  # repo-relative, forward slashes
    meta: Dict[str, Any] = field(default_factory=dict)
    body: str = ""
    # Why this document may not govern despite its metadata. Set when an
    # Agent Context is examined: "" means checked and eligible, None means not
    # checked yet, and an unchecked document never governs.
    ineligible: Optional[str] = None

    @property
    def id(self) -> str:
        return str(self.meta.get("id") or self.path)

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or os.path.basename(self.path))

    @property
    def status(self) -> str:
        """Lifecycle: active, superseded or retired. Anything else is reported
        as it is, and validation refuses it."""
        return str(self.meta.get("status") or "active")

    @property
    def retired(self) -> bool:
        """Superseded or retired: kept for history, in `archive/`."""
        return self.status in RETIRED

    @property
    def authority(self) -> str:
        return str(self.meta.get("authority") or "non-authoritative")

    @property
    def claims_authority(self) -> bool:
        """What the front matter says, before anything checks it."""
        return self.authority == "authoritative"

    def render(self) -> str:
        body = self.body.replace("\r\n", "\n")
        if not body.endswith("\n"):
            body += "\n"
        return render_front_matter(self.meta) + "\n" + body.lstrip("\n")


def parse_document(path: str, text: str) -> Optional[Document]:
    meta, body = parse_front_matter(text)
    if not meta or "id" not in meta:
        return None
    return Document(path=path.replace("\\", "/"), meta=meta, body=body)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- deterministic naming ----------------------------------------------------

def slugify(value: str, fallback: str = "untitled") -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    value = re.sub(r"-{2,}", "-", value)
    return value[:80] or fallback


def unique_id(base: str, existing: set) -> str:
    candidate = base
    n = 2
    while candidate in existing:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def today() -> str:
    return date.today().isoformat()
