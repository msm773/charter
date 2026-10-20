"""The Charter console's API: what the page asks of the server.

One console session has at most one Agent Context open. Every rule lives in
`manager`, `authority` and `agent_context`; this module shapes their answers
for the page and turns their refusals into messages for the person.

The page reads the current state, previews an action as a plan, and applies
exactly the plan it showed, with the person's confirmation. Nothing here
operates Git, and nothing here exposes private manager state to agents: the
console is the person's own view, on this computer.
"""
from __future__ import annotations

import base64
import binascii
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import agent_context as ac
from . import agent_proposals as apx
from . import authority as au
from . import changeset
from . import connect
from . import convert
from . import host_state as hs
from . import manager as mg
from . import private_store as ps
from .docs import leading_front_matter, parse_front_matter

MAX_UPLOAD = 48 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400,
                 payload: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.payload = payload or {}


class Session:
    """The console's one open Agent Context, if any."""

    def __init__(self, folder: str = "") -> None:
        self.folder = ""
        self.recovered: Optional[Dict[str, Any]] = None
        if folder:
            open_context(self, {"path": folder})

    def require(self) -> str:
        if not self.folder:
            raise ApiError("No Agent Context is open.", 409)
        return self.folder


def _refusal(exc: Exception) -> ApiError:
    if isinstance(exc, au.StalePlan):
        return ApiError(str(exc), 409, {"stale": True})
    if isinstance(exc, au.ApplyFailed):
        return ApiError(str(exc), 409, {"restored": exc.restored, "unrestored": exc.unrestored})
    return ApiError(str(exc))


def _guard(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except (au.ActionRefused, ps.PrivateStateError, convert.ConversionError, ValueError) as exc:
        raise _refusal(exc)


# --- state -------------------------------------------------------------------------

GUIDANCE_SUMMARY = {
    "context_check_in": "After reading the context map and relevant governing documents, the agent "
                        "sends a brief check-in naming the documents it read.",
    "proposal_context_impact_check": "Before proposing a change, the agent checks for duplication, "
                                     "overlap, conflicts, and unresolved decisions.",
    "review_newly_discovered_material": "The agent compares relevant non-governing material with the "
                                        "governing documents and raises material concerns for human "
                                        "review.",
}


def _document(doc_meta: Dict[str, Any], path: str, kind: str) -> Dict[str, Any]:
    return {"path": path, "kind": kind, "governing": kind == "governing",
            "id": str(doc_meta.get("id") or ""), "title": str(doc_meta.get("title") or path),
            "scope": str(doc_meta.get("scope") or ""), "status": str(doc_meta.get("status") or ""),
            "authority": str(doc_meta.get("authority") or ""),
            "location": "Agent Context" if kind == "governing" else "private state",
            "updated": str(doc_meta.get("updated") or "")}


_PROPOSAL_SOURCE = re.compile(r"^Agent Proposal \S+ \((.*), self-reported\)$")


def candidate_source(meta: Dict[str, Any]) -> Tuple[str, str]:
    """The candidate's human-facing origin — an accepted Agent Proposal, a
    governing document withdrawn by a change set, a Revise, or Create
    candidate — and, for a proposal, the agent's self-reported name when it
    supplied one. Never an invented identity. Private manager state, for the
    console only."""
    source = str(meta.get("source") or "")
    if source.startswith("Agent Proposal"):
        m = _PROPOSAL_SOURCE.match(source)
        return "proposal", (m.group(1).strip() if m else "")
    if source == au.WITHDRAWN_SOURCE:
        return "withdrawn", ""
    if meta.get(au.REVISES):
        return "revise", ""
    # Withdrawn before withdrawals recorded their source: a governing
    # document's own supersession keys, which no candidate Charter creates has.
    if not source and ("supersedes" in meta or "superseded_by" in meta):
        return "withdrawn", ""
    return "create", ""


def _documents(folder: str, cs: ps.ContextState, exam: ac.Examination) -> List[Dict[str, Any]]:
    docs = [_document(d.meta, d.path, "governing") for d in exam.documents]
    body_by_path = {d.path: d.body for d in exam.documents}
    archived = au.archived_metas(cs)
    candidates = []
    revises_count: Dict[str, int] = {}
    for logical in cs.candidates():
        meta, body = parse_front_matter(cs.read_candidate(logical) or "")
        meta = meta or {}
        entry = _document(meta, logical, "candidate")
        # Revision lineage: the governing document this candidate revises, by its
        # id and text, followed through every revision since to the document
        # that governs now (a Revise or an accepted Agent Proposal amendment both
        # record it). Never a filename.
        entry.update(au.revision_lineage(meta, exam.documents, exam.hashes, archived))
        entry["source_kind"], entry["source_agent"] = candidate_source(meta)
        entry["created"] = str(meta.get("created") or "")
        entry["change_summary"] = au.change_summary(body, body_by_path.get(entry["revises_path"]))
        if entry["revises_path"]:
            revises_count[entry["revises_path"]] = revises_count.get(entry["revises_path"], 0) + 1
        candidates.append(entry)
    for entry in candidates:
        # How many *other* candidates revise the same governing document.
        entry["co_revisions"] = max(0, revises_count.get(entry["revises_path"], 0) - 1) \
            if entry["revises_path"] else 0
        docs.append(entry)
    for name in cs.archived():
        meta, _body = parse_front_matter(cs.read_archived(name) or "")
        docs.append(_document(meta or {}, f"archive/{name}", "archived"))
    return docs


def _active_change_sets(folder: str) -> int:
    """Drafts still being worked on, including a waiting, blocked or stale one
    that a refresh can bring up to date. An applied change set is a private
    receipt and an abandoned one is finished: neither counts, and neither does
    a record that cannot be read."""
    try:
        drafts = changeset.list_drafts(changeset.Ctx(folder))
    except (OSError, ps.PrivateStateError, changeset.ChangeSetError):
        return 0
    return sum(1 for d in drafts if not d.get("unreadable")
               and d.get("state") not in (changeset.APPLIED, changeset.ABANDONED))


def folder_name(path: str, windows: Optional[bool] = None) -> str:
    """The final folder name of `path`, by this platform's rules unless
    `windows` says which: a trailing separator is ignored, a backslash
    separates only on Windows (elsewhere it may be part of a name), and a path
    with no final name, such as `/` or `C:\\`, is given whole. The header and
    rail name the open Agent Context by it; its full path stays where precision
    matters (UI Standards)."""
    import ntpath
    import posixpath
    windows = (os.name == "nt") if windows is None else windows
    flavour = ntpath if windows else posixpath
    seps = "\\/" if windows else "/"
    trimmed = path.rstrip(seps)
    if windows and trimmed.endswith(":"):
        trimmed = ""  # `C:` is a drive, not a folder name
    name = flavour.basename(trimmed) if trimmed else ""
    return name or path


def state(session: Session) -> Dict[str, Any]:
    base = {"pdf_support": convert.pdf_available(), "folder_picker": folder_picker_available(),
            "confirm_phrase": au.CONFIRM_PHRASE}
    private = ps.PrivateState.default()
    base["legacy_state"] = private.legacy()
    # Recent: the Agent Contexts opened on this computer, the most recent first,
    # whether or not one is open now, so Open Agent Context… always offers them.
    known = [p for p in private.recent_contexts() if os.path.isdir(p)]
    base["recent"] = known[:8]  # the most recently opened first
    if not session.folder:
        return dict(base, open=False)
    folder = session.folder
    if not os.path.isdir(folder):
        session.folder = ""
        return dict(base, open=False,
                    closed_because="The Agent Context's folder is no longer there.")
    status = mg.check(folder)
    cs = ps.PrivateState.default().for_context(folder)
    exam = ac.examine(folder)
    settings = exam.settings
    guidance = settings.guidance_map if settings else {}
    recovered, session.recovered = session.recovered, None
    try:
        listed = apx.listing(folder)
        proposals = {"pending": len(listed["pending"]), "imported": len(listed["imported"]),
                     "unexpected": len(listed["unexpected"]),
                     "stale": sum(1 for p in listed["pending"] + listed["imported"] if p["stale"])}
    except (OSError, ps.PrivateStateError):
        proposals = {"pending": 0, "imported": 0, "unexpected": 0, "stale": 0}
    return dict(base, open=True, root=folder, folder_name=folder_name(folder),
                project_name=status["name"], status=status,
                proposals=proposals, change_sets={"active": _active_change_sets(folder)},
                recovered=recovered, issues=exam.issues,
                documents=_documents(folder, cs, exam),
                agent_guidance=[{"id": g["id"], "label": g["label"],
                                 "on": bool(guidance.get(g["id"])),
                                 "summary": GUIDANCE_SUMMARY[g["id"]]}
                                for g in ac.AGENT_GUIDANCE],
                authoritative_dir=ac.AUTHORITATIVE, candidates_dir="authority-candidates",
                archive_dir="archive")


# --- opening and creating ---------------------------------------------------------------

def _folder_from(body: Dict[str, Any]) -> str:
    raw = str(body.get("path") or "").strip()
    if not raw:
        raise ApiError("Choose the Agent Context folder first.")
    return hs.canonical(raw)


def open_context(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    folder = _folder_from(body)
    status = _guard(lambda: mg.open_context(folder))
    session.folder = status["path"]
    session.recovered = status.get("recovered")
    _back_in_recent(status["path"])
    return {"opened": status["path"], "name": status["name"], "headline": status["headline"]}


def _back_in_recent(folder: str) -> None:
    """An Agent Context the person opens or creates heads Recent, listed again
    if it was cleared. The list is a convenience: failing to update it never
    fails the open."""
    try:
        ps.PrivateState.default().note_opened(folder)
    except (OSError, ps.PrivateStateError, hs.HostStateError):
        pass


def clear_recent(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Clear the Recent list. No Agent Context, and none of its private state,
    is opened, closed or changed."""
    try:
        _guard(lambda: ps.PrivateState.default().clear_recent())
    except OSError:
        raise ApiError("Charter could not clear the Recent list. Nothing else was changed.")
    return {"cleared": True}


def peek(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """A read-only look at a folder the person is choosing on the open/create
    screen: whether it already holds an Agent Context, whether it is valid now,
    and the name it already has. Creates no private state and writes nothing, so
    the screen can fill in an existing context's name without opening it."""
    raw = str(body.get("path") or "").strip()
    blank = {"exists": False, "has_context": False, "valid": False, "name": ""}
    if not raw:
        return blank
    folder = hs.canonical(raw)
    if not os.path.isdir(folder):
        return blank
    if ac.is_incomplete_context(folder):
        # Authored documents in authoritative/ and no map yet: an existing,
        # incomplete Agent Context, to open, never to create over.
        return {"exists": True, "has_context": True, "incomplete": True, "valid": False, "name": ""}
    if not ac.is_context_root(folder):
        return {"exists": True, "has_context": False, "valid": False, "name": ""}
    status = mg.check(folder, git=False)
    settings = status.get("settings")
    return {"exists": True, "has_context": True, "valid": bool(status["agents_served"]),
            "name": settings["project_name"] if settings else ""}


def create_context(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    folder = _folder_from(body)
    name = str(body.get("project_name") or "").strip()
    if not name:
        raise ApiError("Name the project to create an Agent Context.")
    status = _guard(lambda: mg.create(folder, name))
    session.folder = status["path"]
    _back_in_recent(status["path"])
    return {"created": status["path"], "name": status["name"], "headline": status["headline"],
            "follow_up": status.get("follow_up", [])}


# --- reading documents --------------------------------------------------------------

BANNERS = {
    "governing": ("Governing document — current context",
                  "Agents read it as current context, within its scope."),
    "candidate": ("Authority candidate — not context",
                  "Kept in private local state on this computer. Agents never see it, and it "
                  "governs nothing until a person applies a change set that makes it govern."),
    "archived": ("Archived — not context",
                 "Kept in private local state on this computer, for history. It governs nothing."),
    "map": ("Generated routing map — not a governing document",
            "Charter generates AGENT-CONTEXT.md from the governing documents and "
            "this Agent Context's settings. Agents read it first."),
    "planned": ("As this preview would leave it — nothing is written yet",
                "Applying the preview writes exactly this."),
}


def _banner(state_name: str) -> Dict[str, str]:
    title, text = BANNERS[state_name]
    return {"title": title, "text": text}


def _read_folder(folder: str, rel: str) -> Optional[str]:
    return ac.read_text(folder, os.path.join(*rel.split("/")))


def _title_of(text: str, fallback: str) -> str:
    meta, _body = parse_front_matter(text)
    return str((meta or {}).get("title") or fallback)


def preview(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Text for the read-only viewer: a document by the exact path the page
    lists, the map by name, or one file as a shown plan would leave it."""
    folder = session.require()
    source = body.get("source")
    if source == "context":
        text = _read_folder(folder, ac.CONTEXT_MAP)
        if text is None:
            raise ApiError("This Agent Context has no readable AGENT-CONTEXT.md.")
        return {"title": "AGENT-CONTEXT.md", "path": ac.CONTEXT_MAP, "text": text,
                "state": "map", "banner": _banner("map")}
    path = body.get("path")
    if not isinstance(path, str) or not path:
        raise ApiError("Name a document exactly as the page lists it.")
    if source == "document":
        cs = ps.PrivateState.default().for_context(folder)
        exam = ac.examine(folder)
        if path in {d.path for d in exam.documents}:
            text, kind = exam.texts[path], "governing"
        elif path in cs.candidates():
            text, kind = cs.read_candidate(path) or "", "candidate"
        elif path.startswith("archive/") and path[len("archive/"):] in cs.archived():
            text, kind = cs.read_archived(path[len("archive/"):]) or "", "archived"
        else:
            raise ApiError("Only documents this page lists can be read here, named exactly as it "
                           "lists them.")
        return {"title": _title_of(text, path), "path": path, "text": text, "state": kind,
                "banner": _banner(kind)}
    if source == "plan":
        plan = _plan(session, body.get("kind", ""), body.get("request") or {})
        if plan.plan_id != body.get("plan_id"):
            raise ApiError("This preview has changed. Preview the action again.", 409)
        change = next((c for c in plan.changes if c.label == path), None)
        if change is None or change.new is None or not path.endswith(".md"):
            raise ApiError("This preview leaves no Markdown document at that path to read.")
        return {"title": _title_of(change.new, path), "path": path, "text": change.new,
                "state": "planned", "banner": _banner("planned")}
    raise ApiError("Unknown source.")


def _body_only(text: str) -> str:
    _meta, body = parse_front_matter(text or "")
    return body[1:] if body.startswith("\n") else body


def compare(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """A human-only text comparison of an authority candidate with the governing
    document it revises, or with a competing candidate. Reads only; console-only,
    so this lineage view is never exposed through MCP or to agents."""
    folder = session.require()
    cand = body.get("candidate")
    against = body.get("against")
    cs = ps.PrivateState.default().for_context(folder)
    exam = ac.examine(folder)
    governing = {d.path: d for d in exam.documents}
    if not isinstance(cand, str) or cand not in cs.candidates():
        raise ApiError("Only an authority candidate this page lists can be compared.")
    left = cs.read_candidate(cand) or ""
    left_title = _title_of(left, cand)
    if isinstance(against, str) and against in governing:
        right, right_title = exam.texts[against], governing[against].title
    elif isinstance(against, str) and against != cand and against in cs.candidates():
        right = cs.read_candidate(against) or ""
        right_title = _title_of(right, against)
    else:
        raise ApiError("Compare against a governing document this map lists, or another candidate.")
    diff = "\n".join(difflib.unified_diff(
        _body_only(right).splitlines(), _body_only(left).splitlines(),
        fromfile=right_title, tofile=left_title, lineterm=""))
    return {"left": {"path": cand, "title": left_title},
            "right": {"path": against, "title": right_title},
            "diff": diff or "(no textual difference in the document body)"}


def draft(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """What a Revise or Edit candidate form starts from: the title, scope and
    body of a governing document or a candidate. Reads only."""
    folder = session.require()
    path = body.get("path")
    cs = ps.PrivateState.default().for_context(folder)
    exam = ac.examine(folder)
    if isinstance(path, str) and path in {d.path for d in exam.documents}:
        text, kind = exam.texts[path], "governing"
    elif isinstance(path, str) and path in cs.candidates():
        text, kind = cs.read_candidate(path) or "", "candidate"
    else:
        raise ApiError("Only a governing document or an authority candidate can be drafted from, "
                       "named exactly as the page lists it.")
    meta, text_body = parse_front_matter(text)
    meta = meta or {}
    # The blank line after the front matter separates it; it is not text.
    text_body = text_body[1:] if text_body.startswith("\n") else text_body
    legacy = None
    if kind == "candidate":
        # A candidate filed before conversion removed front matter may still
        # carry an old block at the top of its text. It is left out of what
        # the Edit form starts from, and the person is told; the candidate
        # itself changes only if they save, after a preview that shows it.
        found = leading_front_matter(text_body)
        if found is not None:
            text_body = found[1]
            legacy = {"removed": True, "keys": list(dict.fromkeys(found[2]))}
    return {"path": path, "kind": kind, "title": str(meta.get("title") or ""),
            "scope": str(meta.get("scope") or ""), "body": text_body,
            "legacy_front_matter": legacy}


# --- intake ------------------------------------------------------------------------------

def stage(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Convert an uploaded file to Markdown for the person to check. Writes
    nothing: the text is filed only through the Create candidate plan."""
    session.require()
    filename = os.path.basename(str(body.get("filename") or "").strip())
    if not filename:
        raise ApiError("No filename.")
    try:
        data = base64.b64decode(str(body.get("content_b64") or ""), validate=True)
    except (binascii.Error, ValueError):
        raise ApiError("The file could not be read.")
    if len(data) > MAX_UPLOAD:
        raise ApiError("That file is too large to add.", 413)
    markdown, notes = _guard(lambda: convert.to_markdown(filename, data))
    front = None
    if convert.extension(filename) in (".md", ".markdown", ".txt", ".text"):
        # An existing document's front matter is never kept as body text: its
        # title and scope are offered as editable suggestions, nothing else.
        markdown, front = convert.remove_front_matter(markdown)
    suggested = (front or {}).get("title") or ""
    # A leading heading suggests the title, but stays in the text as written,
    # as an accepted proposal's body keeps it: the document keeps its section.
    heading, _rest = convert.strip_leading_title(markdown)
    # What became of the front matter is said once, by the page's own note
    # beside Title and Scope, from `front_matter`: never again among `notes`.
    return {"filename": filename, "kind": convert.extension(filename).lstrip(".").upper(),
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "markdown": markdown, "notes": notes,
            "suggested_title": suggested or heading or os.path.splitext(filename)[0],
            "suggested_scope": (front or {}).get("scope") or "",
            "front_matter": None if front is None else
            {"removed": True, "used": front["used"], "dropped": front["dropped"]}}


# --- plans and applying ---------------------------------------------------------------------

# Grant, replace and withdraw are outcomes of a change set, never actions of
# their own; a page from before that may still ask for them.
RETIRED_KINDS = ("grant", "replace", "withdraw")
CHANGE_SET_ONLY = ("Governing context changes only through a change set: plan it in Change Sets, "
                   "preview it, and apply it from its editor. Nothing was changed.")


def _plan(session: Session, kind: str, request: Dict[str, Any]) -> au.Plan:
    folder = session.require()
    if not isinstance(request, dict):
        raise ApiError("The request must be an object.")
    if kind == "rebuild":
        return _guard(lambda: mg.rebuild_plan(folder, request.get("project_name"),
                                              request.get("agent_guidance")))
    if kind == "settings":
        return _guard(lambda: mg.settings_plan(folder, request.get("project_name"),
                                               request.get("agent_guidance")))
    if kind == "regenerate-map":
        return _guard(lambda: mg.regenerate_plan(folder))
    if kind in RETIRED_KINDS:
        raise ApiError(CHANGE_SET_ONLY, 409, {"change_set_only": True})
    if kind not in au.KINDS:
        raise ApiError("Unknown action.")
    return _guard(lambda: au.plan(folder, kind, request))


def _shown(plan: au.Plan) -> Dict[str, Any]:
    out = plan.to_json()
    for change, raw in zip(out["changes"], plan.changes):
        change["reason"] = ("Agent Context — what agents read" if raw.root == "context"
                            else "Private local state — not agent-visible")
        change["preview"] = {"available": raw.new is not None and raw.label.endswith(".md"),
                             "why": "" if raw.new is not None else "Removed by this action."}
    # A plan's problems are about the action, not one file: shown as sentences.
    out["issues"] = [{"level": "error", "path": "", "message": m, "fix": "", "general": True}
                     for m in plan.problems]
    return out


def plan(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    return _shown(_plan(session, str(body.get("kind") or ""), body.get("request") or {}))


def apply(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    folder = session.require()
    kind = str(body.get("kind") or "")
    request = body.get("request") or {}
    plan_id = str(body.get("plan_id") or "")
    confirm = body.get("confirm")
    if not isinstance(request, dict):
        raise ApiError("The request must be an object.")
    if kind == "rebuild":
        status = _guard(lambda: mg.rebuild_apply(folder, plan_id, confirm,
                                                 request.get("project_name"),
                                                 request.get("agent_guidance")))
        return {"applied": True, "kind": kind, "headline": status["headline"],
                "follow_up": status.get("follow_up", [])}
    if kind == "settings":
        status = _guard(lambda: mg.settings_apply(folder, plan_id, confirm,
                                                  request.get("project_name"),
                                                  request.get("agent_guidance")))
        return {"applied": True, "kind": kind, "headline": status["headline"],
                "follow_up": status.get("follow_up", [])}
    if kind == "regenerate-map":
        status = _guard(lambda: mg.regenerate_apply(folder, plan_id, confirm))
        return {"applied": True, "kind": kind, "headline": status["headline"],
                "follow_up": status.get("follow_up", [])}
    if kind in RETIRED_KINDS or kind in au.GOVERNING_KINDS:
        # A change set applies only from its own route, which holds the
        # change-set lock so that no draft changes while it applies.
        raise ApiError(CHANGE_SET_ONLY, 409, {"change_set_only": True})
    if kind not in au.KINDS:
        raise ApiError("Unknown action.")
    return _guard(lambda: au.apply(folder, kind, request, plan_id, confirm))


# --- Agent Proposals ------------------------------------------------------------------------

def proposals(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Pending and imported proposals, and unexpected local records."""
    folder = session.require()
    return _guard(lambda: apx.listing(folder))


# Import Agent Proposals (UI Standards, Agent Proposals): each item is one pasted
# text or one chosen file. A file's bytes arrive base64-encoded, never decoded by
# the page, and every item is then read exactly as `charter propose` reads its
# standard input (`agent_proposals.read_submission`). No item carries a file
# name: the page keeps those to itself.
MALFORMED_MESSAGES = {
    "too_large": "This proposal is too large.",
    "not_utf8": "This is not UTF-8 text.",
    "not_json": "This is not JSON.",
    "not_an_object": "This is not one JSON object.",
}
_MAX_B64 = (apx.MAX_INPUT + 2) // 3 * 4


def _item_bytes(item: Any) -> bytes:
    """One item's submitted bytes, or apx.Malformed: a file's bytes exactly, or a
    pasted text's UTF-8."""
    if not isinstance(item, dict) or len(item) != 1 or not ({"bytes", "text"} & set(item)):
        raise ApiError("Each item is one pasted text or one file.")
    if "text" in item:
        if not isinstance(item["text"], str):
            raise ApiError("Each item is one pasted text or one file.")
        try:
            return item["text"].encode("utf-8")
        except UnicodeEncodeError:  # a lone surrogate: no UTF-8 text holds one
            raise apx.Malformed("not_utf8")
    encoded = item["bytes"]
    if not isinstance(encoded, str):
        raise ApiError("Each item is one pasted text or one file.")
    if len(encoded) > _MAX_B64:
        raise apx.Malformed("too_large")
    try:
        return base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise ApiError("A file could not be read.")


def _import_items(body: Dict[str, Any]) -> List[Tuple[Any, Any]]:
    """(the JSON value each item holds, or its Malformed; its submitted bytes)."""
    items = body.get("items")
    if not isinstance(items, list) or not items:
        raise ApiError("Add a proposal to check: paste its JSON, or choose or drop a file.")
    if len(items) > apx.MAX_BATCH:
        raise ApiError(f"Check at most {apx.MAX_BATCH} proposals at a time.")
    out: List[Tuple[Any, Any]] = []
    for item in items:
        try:
            data = _item_bytes(item)
        except apx.Malformed as exc:
            out.append((exc, None))
            continue
        try:
            out.append((apx.read_submission(data), data))
        except apx.Malformed as exc:
            out.append((exc, data))
    return out


def _import_rows(assessed: List[Dict[str, Any]], target: Any) -> List[Dict[str, Any]]:
    """Each item's status for the page: no record, path or digest beyond what
    the person needs \u2014 a waiting proposal's id and title, for Replace."""
    out = []
    for a in assessed:
        row: Dict[str, Any] = {"status": a["status"]}
        if a["status"] == apx.MALFORMED:
            code = a.get("code") or "not_an_object"
            row["message"] = MALFORMED_MESSAGES[code]
        elif a["status"] in (apx.STALE, apx.REFUSED):
            row["problems"] = [{k: p[k] for k in ("code", "message", "field") if k in p}
                               for p in a["problems"]]
        elif a["status"] == apx.AWAITING:
            title, _kind = apx.title_of(a["waiting"]["proposal"], target, target.cs)
            row["waiting"] = {"proposal_id": a["waiting"]["proposal_id"], "title": title}
        elif a["status"] == apx.SAME:
            row["same_as"] = a["same_as"]
        else:
            p = a["proposal"]
            title, _kind = apx.title_of(p, target, target.cs)
            row["summary"] = {"title": title, "agent": p["agent"], "operation": p["operation"]}
        out.append(row)
    return out


def import_check(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Check each item exactly as `charter propose` would, writing nothing.
    When the Agent Context cannot accept proposals now, the answer says so once
    (`unavailable`) and gives no item a status."""
    folder = session.require()
    items = _import_items(body)
    try:
        target = apx.open_target(folder)
    except apx.Unavailable as exc:
        return {"unavailable": {"message": exc.message}, "items": []}
    return {"unavailable": None, "items": _import_rows(apx.assess(target, [r for r, _ in items]), target)}


def import_file(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """File the selected items as imported proposals, all of them or none,
    after the person has checked them (`agent_proposals.file_batch`). Nothing
    is accepted, and no candidate or change set is made."""
    folder = session.require()
    if body.get("confirm") is not True:
        raise ApiError("Confirm the import to file it.")
    items = _import_items(body)
    result = apx.file_batch(folder, items, source=apx.IMPORTED)
    if result["result"] == "refused" and "items" in result:
        try:
            target = apx.open_target(folder)
        except apx.Unavailable as exc:
            return apx.unavailable_result(exc)
        return {"result": "refused", "items": _import_rows(result["items"], target)}
    if result["result"] == "pending":
        return {"result": "pending", "count": len(result["proposal_ids"]),
                "proposal_ids": result["proposal_ids"]}
    return result


def import_replace(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Replace one waiting proposal with one item of the same content, in place
    (UI Standards: separately from any import of selected rows)."""
    folder = session.require()
    if body.get("confirm") is not True:
        raise ApiError("Confirm the replacement to make it.")
    [(raw, data)] = _import_items({"items": [body.get("item")]})
    if isinstance(raw, apx.Malformed):
        raise ApiError(MALFORMED_MESSAGES[raw.code])
    return apx.replace(folder, raw, body.get("replace"), source=apx.IMPORTED, submitted=data)


def unexpected(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """An unexpected local record's text, to inspect. It is left unchanged."""
    folder = session.require()
    name = body.get("name")
    cs = ps.PrivateState.default().for_context(folder)
    try:
        return {"name": name, "regular": True, "text": apx.unexpected_text(cs, str(name or ""))}
    except apx.NotRegular as exc:
        # Listed, but not a file: say what it is rather than that it is missing.
        return {"name": name, "regular": False, "text": None, "message": str(exc)}
    except ValueError:
        raise ApiError("There is no such unexpected record. It may have been removed; "
                       "choose Agent Proposals to look again.")
    except OSError as exc:
        raise ApiError(f"Charter couldn't read this record ({exc.strerror or exc}). "
                       "It is left unchanged.")


def acknowledge(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    folder = session.require()
    status = _guard(lambda: mg.acknowledge(folder))
    return {"acknowledged": True, "headline": status["headline"]}


# --- the folder dialog ---------------------------------------------------------------------

_PICKER = r"""
import sys, tkinter
from tkinter import filedialog
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
chosen = filedialog.askdirectory(parent=root, title=sys.argv[1], initialdir=sys.argv[2] or None,
                                 mustexist=False)
sys.stdout.write(chosen or "")
"""


def folder_picker_available() -> bool:
    import importlib.util
    if os.environ.get("CHARTER_FOLDER_PICKER", "").strip() in ("0", "false", "no"):
        return False
    if importlib.util.find_spec("tkinter") is None:
        return False
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY")
                                                  or os.environ.get("WAYLAND_DISPLAY")):
        return False
    return True


def pick_folder(session: Session, body: Dict[str, Any]) -> Dict[str, Any]:
    """Ask this computer for a folder. Reads nothing in it and writes nothing."""
    if not folder_picker_available():
        raise ApiError("No folder dialog is available here. Type the path instead.", 501)
    initial = str(body.get("initial") or "").strip()
    initial = os.path.abspath(os.path.expanduser(initial)) if initial else ""
    if initial and not os.path.isdir(initial):
        initial = ""
    try:
        proc = subprocess.run([sys.executable, "-c", _PICKER, "Choose the Agent Context folder",
                               initial], capture_output=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired):
        raise ApiError("The folder dialog could not be opened here. Type the path instead.", 501)
    if proc.returncode != 0:
        raise ApiError("The folder dialog could not be opened here. Type the path instead.", 501)
    chosen = proc.stdout.decode("utf-8", "replace").strip()
    return {"path": os.path.normpath(chosen) if chosen else "", "cancelled": not chosen}


# A Save As dialog. It never asks to replace a file: the caller saves under a
# free name instead.
_SAVE_PICKER = r"""
import sys, tkinter
from tkinter import filedialog
root = tkinter.Tk()
root.withdraw()
root.attributes("-topmost", True)
chosen = filedialog.asksaveasfilename(parent=root, title=sys.argv[1], initialdir=sys.argv[2] or None,
                                      initialfile=sys.argv[3], defaultextension=".md",
                                      filetypes=[("Markdown", "*.md")], confirmoverwrite=False)
sys.stdout.write(chosen or "")
"""


def pick_save_file(title: str, suggested: str) -> str:
    """Ask this computer where to save a file, starting in the person's
    Downloads or home folder. Reads and writes nothing; "" when cancelled."""
    if not folder_picker_available():
        raise ApiError("No Save dialog is available here. Type the full path instead.", 501,
                       {"type_path": True})
    home = os.path.expanduser("~")
    downloads = os.path.join(home, "Downloads")
    initial = downloads if os.path.isdir(downloads) else home
    try:
        proc = subprocess.run([sys.executable, "-c", _SAVE_PICKER, title, initial, suggested],
                              capture_output=True, timeout=900)
    except (OSError, subprocess.TimeoutExpired):
        raise ApiError("The Save dialog could not be opened here. Type the full path instead.", 501,
                       {"type_path": True})
    if proc.returncode != 0:
        raise ApiError("The Save dialog could not be opened here. Type the full path instead.", 501,
                       {"type_path": True})
    chosen = proc.stdout.decode("utf-8", "replace").strip()
    return os.path.normpath(chosen) if chosen else ""


def connect_agents(session: Session) -> Dict[str, Any]:
    """Connect agents: copy-ready text for the open Agent Context, offered only
    while it is ready. Reads; writes nothing anywhere."""
    return connect.connection(session.require())


def diagnostics(session: Session) -> Dict[str, Any]:
    """Diagnostics: which copy of Charter this is, the map format the open Agent
    Context records, and, as a fact, what `charter` by name runs for a new
    program. Its remedy is the Charter command dialog's alone, never repeated
    here (UI Standards). Reads; writes nothing."""
    from . import identity
    exam = ac.examine(session.folder) if session.folder and os.path.isdir(session.folder) else None
    ident = identity.identity(exam)
    command = connect.command_status()
    if command["state"] == connect.COMMAND_READY:
        on_path_text = "this copy"
    elif command["state"] == connect.COMMAND_OTHER:
        on_path_text = f"another copy, from {command['other_folder']}"
    else:
        on_path_text = "not found: `charter` is not on PATH for new programs"
    return {"identity": ident, "relation": identity.RELATION.get(ident.get("context_map_relation") or "", ""),
            "on_path": {"this_copy": command["state"] == connect.COMMAND_READY, "text": on_path_text},
            # The open Agent Context's exact folder: the header and rail name it
            # by its folder's name only (UI Standards).
            "folder": session.folder if exam is not None else ""}


def command(session: Session) -> Dict[str, Any]:
    """The header's Charter command status, and its remedy when it needs
    attention. Independent of the Agent Context's status: it reads PATH, never
    the folder, and changes nothing."""
    return connect.command_status()


GET_ROUTES = {"/api/state": state, "/api/connect": connect_agents, "/api/diagnostics": diagnostics,
              "/api/command": command}
POST_ROUTES = {
    "/api/open": open_context, "/api/create": create_context, "/api/peek": peek,
    "/api/pick-folder": pick_folder, "/api/recent/clear": clear_recent,
    "/api/preview": preview, "/api/draft": draft, "/api/candidate/compare": compare,
    "/api/intake/stage": stage,
    "/api/plan": plan, "/api/apply": apply, "/api/acknowledge": acknowledge,
    "/api/proposals": proposals, "/api/proposals/import/check": import_check,
    "/api/proposals/import": import_file, "/api/proposals/import/replace": import_replace,
    "/api/proposals/unexpected": unexpected,
}
# Every route that changes anything, or reads private state, answers only the
# console's own page.
CONSOLE_HEADER = "X-Charter-Console"
CONSOLE_HEADER_VALUE = "person"
