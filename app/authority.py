"""Authority actions on an Agent Context, without Git.

Product Specification §3.2–§3.3 and the Scope Authoring and Revision Workflow.
New or revised material is first an authority candidate, kept in private
state. A person may retire a candidate, archiving it privately, directly.

Governing context changes only through a coordinated change set
(`changeset`), in which:

  * a candidate governs alongside the existing documents, or replaces one
    governing document the person selects: it takes that document's path,
    and the replaced version is archived privately;
  * a governing document may be withdrawn, returning it to candidate status;
    and every other governing document is retained.

There is no direct grant, replace or withdraw action. A change set started
from one candidate includes it, its decision not yet made; one started from
a governing document withdraws it.

A governing document's title, body and scope are never edited in place:
**Revise** files a candidate prefilled from it, applied through replace like
any other. Candidates may be added and edited freely; neither changes what
governs.

Every action is first a plan: what governs before and after, every file it
writes with its diff, scope continuity, and why it cannot apply, if it cannot.
A plan is identified by a hash of its inputs and result, apart from the dates
it writes, which are the day of writing; applying a plan whose inputs have
changed since it was shown is refused as stale. Applying writes
through one `transaction`, holding this context's writer lock, after
recovering any interrupted earlier write. A context-changing action requires
the person to type `change governing context` and requires a valid, clean
Agent Context to start from; it writes the governing documents and
regenerates `AGENT-CONTEXT.md` and `.agent-context.json`, and nothing else in
the folder. Retiring or editing a candidate changes no governing context and
needs only an ordinary deliberate confirmation. Nothing here operates Git.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import agent_context as ac
from . import private_store as ps
from . import transaction as tx
from .docs import Document, leading_front_matter, not_text, parse_front_matter, slugify, today, unique_id

CONFIRM_PHRASE = "change governing context"

# Dates the actions write — a candidate's `created` and `updated`, an archived
# or governing version's `updated` — are the day of writing. A plan is
# identified by a build of it dated NEUTRAL_DAY, so the same preview still
# applies after local midnight; what is shown and written is dated the day it
# is built. Only the dates differ between the two.
NEUTRAL_DAY = "2000-01-01"
APPLY_DATE_NOTE = "Candidate dates are assigned when this change is applied."
# A change set's preview carries no such note: it shows only what a person
# needs to decide (UI Standards).

KINDS = ("add", "revise", "edit-candidate", "retire", "accept-proposal", "reject-proposal",
         "changeset")
# Governing context changes only through a coordinated change set: granting,
# replacing and withdrawing are its outcomes, never actions of their own.
GOVERNING_KINDS = ("changeset",)


class ActionRefused(ValueError):
    """The action cannot be planned or applied, said for the person."""


class StalePlan(ActionRefused):
    """What the plan was built from has changed since it was shown."""


class ApplyFailed(ActionRefused):
    """Writing failed and was rolled back. `restored` says whether everything
    is as it was; `unrestored` names files left as someone else changed them."""

    def __init__(self, message: str, restored: bool, unrestored: List[str]) -> None:
        super().__init__(message)
        self.restored = restored
        self.unrestored = unrestored


# --- what the action starts from ---------------------------------------------------

@dataclass
class Situation:
    folder: str
    exam: ac.Examination
    cs: ps.ContextState
    # Logical candidate path -> (document, text).
    candidates: Dict[str, Tuple[Document, str]]
    archived: List[str]
    governing_names: List[str]

    @property
    def governing(self) -> Dict[str, Document]:
        return {d.path: d for d in self.exam.documents}

    def all_ids(self) -> set:
        ids = {d.id for d in self.exam.documents}
        ids |= {doc.id for doc, _text in self.candidates.values()}
        for name in self.archived:
            text = self.cs.read_archived(name) or ""
            meta, _body = parse_front_matter(text)
            if meta and meta.get("id"):
                ids.add(str(meta["id"]))
        return ids


def _authoritative_paths(folder: str) -> List[str]:
    """Every Markdown path under `authoritative/`, valid or not, so that new
    names never collide with anything there."""
    base = os.path.join(folder, ac.AUTHORITATIVE)
    out = []
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            if name.lower().endswith(ac.DOCUMENT_SUFFIXES):
                out.append(os.path.relpath(os.path.join(dirpath, name), folder)
                           .replace("\\", "/"))
    return sorted(out)


def situation(folder: str, state: Optional[ps.PrivateState] = None) -> Situation:
    state = state or ps.PrivateState.default()
    cs = state.for_context(folder)
    exam = ac.examine(cs.folder)
    candidates: Dict[str, Tuple[Document, str]] = {}
    for logical in cs.candidates():
        text = cs.read_candidate(logical) or ""
        meta, body = parse_front_matter(text)
        candidates[logical] = (Document(path=logical, meta=meta or {}, body=body), text)
    return Situation(folder=cs.folder, exam=exam, cs=cs, candidates=candidates,
                     archived=cs.archived(), governing_names=_authoritative_paths(cs.folder))


# --- plans ----------------------------------------------------------------------------

@dataclass
class Change:
    root: str           # tx.CONTEXT or tx.PRIVATE
    path: str           # where it is written, relative to its root
    label: str          # what the person sees: a context path, or a private item
    old: Optional[str]
    new: Optional[str]

    @property
    def action(self) -> str:
        if self.old is None:
            return "create"
        return "delete" if self.new is None else "modify"

    def diff(self) -> str:
        return "".join(difflib.unified_diff(
            (self.old or "").splitlines(keepends=True), (self.new or "").splitlines(keepends=True),
            fromfile=self.label if self.old is not None else "/dev/null",
            tofile=self.label if self.new is not None else "/dev/null"))

    def to_json(self) -> Dict[str, Any]:
        return {"location": "Agent Context" if self.root == tx.CONTEXT else "private state",
                "path": self.label, "action": self.action, "diff": self.diff()}


@dataclass
class Plan:
    kind: str
    request: Dict[str, Any]
    summary: str
    changes: List[Change] = field(default_factory=list)
    before: List[Dict[str, str]] = field(default_factory=list)
    after: List[Dict[str, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)
    governing_change: bool = False
    expected_hashes: Dict[str, str] = field(default_factory=dict)
    plan_id: str = ""
    # Rebuild only, when the metadata is lost: the settings offered for the
    # person to confirm or change, and where they come from.
    settings_proposal: Optional[Dict[str, Any]] = None

    @property
    def blocked(self) -> bool:
        return bool(self.problems)

    @property
    def confirm_phrase(self) -> str:
        return CONFIRM_PHRASE if self.governing_change else ""

    def to_json(self) -> Dict[str, Any]:
        return {"plan_id": self.plan_id, "kind": self.kind, "summary": self.summary,
                "governing_change": self.governing_change,
                "confirm_phrase": self.confirm_phrase, "blocked": self.blocked,
                "problems": list(self.problems), "notes": list(self.notes),
                "before": self.before, "after": self.after,
                "changes": [c.to_json() for c in self.changes],
                "settings_proposal": self.settings_proposal}


def _listing(docs: List[Document]) -> List[Dict[str, str]]:
    return [{"path": d.path, "title": d.title, "scope": str(d.meta.get("scope") or "")}
            for d in sorted(docs, key=lambda d: d.path)]


def _render(meta: Dict[str, Any], body: str) -> str:
    return Document(path="", meta=meta, body=body).render()


def _sha(text: Optional[str]) -> str:
    return "" if text is None else hashlib.sha256(text.encode("utf-8")).hexdigest()


def _candidate_meta(doc_id: str, title: str, scope: str, day: str,
                    base: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = dict(base or {})
    meta.update({"id": doc_id, "title": title, "status": "active",
                 "authority": "non-authoritative", "scope": scope})
    meta.setdefault("created", day)
    meta["updated"] = day
    return meta


def _text_field(request: Dict[str, Any], key: str, required: bool = False) -> Optional[str]:
    value = request.get(key)
    if value is None:
        if required:
            raise ActionRefused(f"`{key}` is required.")
        return None
    if not isinstance(value, str):
        raise ActionRefused(f"`{key}` must be text.")
    return value


FRONT_MATTER_IN_BODY = ("The text begins with a front-matter block. Remove it: the title and scope are "
                        "set in their own fields, and Charter assigns everything else.")


def _body(value: Optional[str]) -> Optional[str]:
    """A candidate's text as given: never with a front-matter block of its
    own at the top, which would be a second one inside the candidate."""
    if value is not None and leading_front_matter(value) is not None:
        raise ActionRefused(FRONT_MATTER_IN_BODY)
    if value is not None and not_text(value):
        raise ActionRefused(f"The text cannot be filed: {not_text(value)}. It may have been read "
                            "with the wrong encoding; correct it, or save the file as UTF-8.")
    return value


def _single_line(value: str, what: str) -> str:
    value = value.strip()
    if "\n" in value or "\r" in value:
        raise ActionRefused(f"The {what} must be one line.")
    if not_text(value):
        raise ActionRefused(f"The {what} cannot be filed: {not_text(value)}.")
    return value


def _governable(doc: Document, text: str) -> None:
    """A candidate whose text is not text never governs: one filed before
    Charter refused such text is stopped here, to be edited or retired."""
    problem = not_text(text)
    if problem:
        raise ActionRefused(f"“{doc.title}” cannot govern: {problem}. Edit it, or retire it.")


class _Builder:
    def __init__(self, sit: Situation, kind: str, request: Dict[str, Any], day: str) -> None:
        self.sit = sit
        # The date this build writes: today(), or NEUTRAL_DAY for the plan id.
        self.day = day
        self.plan = Plan(kind=kind, request=request, summary="")
        # The resulting governing documents: path -> (document, text).
        self.result: Dict[str, Tuple[Document, str]] = {
            d.path: (d, sit.exam.texts[d.path]) for d in sit.exam.documents}

    def private(self, store_path: str, label: str, old: Optional[str],
                new: Optional[str]) -> None:
        self.plan.changes.append(Change(tx.PRIVATE, store_path, label, old, new))

    def candidate_store(self, logical: str) -> str:
        return f"{ps.CANDIDATES}/{ps.candidate_name(logical)}"

    def require_candidate(self, logical: Any) -> Tuple[Document, str]:
        if not isinstance(logical, str) or logical not in self.sit.candidates:
            raise ActionRefused("There is no such authority candidate.")
        return self.sit.candidates[logical]

    def require_governing(self, path: Any) -> Document:
        if not isinstance(path, str) or path not in self.sit.governing:
            raise ActionRefused("There is no such governing document.")
        return self.sit.governing[path]

    def new_id(self, base: str, extra: Optional[set] = None) -> str:
        return unique_id(base or "document", self.sit.all_ids() | (extra or set()))

    def archive_name(self, stem: str, taken: Optional[List[str]] = None) -> str:
        """A free archive name from `stem`: `stem.md`, else the first free
        numbered one. A stem no private name may use — a governing file name
        with spaces, accents or a leading underscore, or one too long once a
        suffix is added — is made safe and shortened, and a crowded name is
        refused after a bounded number of tries rather than searched for
        forever (`private_store.free_name`)."""
        used = self.sit.cs.taken_names(self.sit.governing_names) | set(taken or [])
        try:
            return ps.free_name(stem, used)
        except ps.PrivateStateError as exc:
            raise ActionRefused(str(exc))

    def finish(self) -> Plan:
        plan, sit = self.plan, self.sit
        plan.before = _listing(sit.exam.documents)
        if plan.governing_change:
            if not sit.exam.valid:
                plan.problems.append(
                    "The Agent Context is not valid and clean now, so its governing context "
                    "cannot change. " + "; ".join(f"{i['path'] or 'folder'}: {i['message']}"
                                                  for i in sit.exam.errors))
            settings = sit.exam.settings or ac.Settings.make("Agent Context")
            docs = [d for d, _t in self.result.values()]
            problems = ac.document_problems(docs)
            for path, found in sorted(problems.items()):
                plan.problems.append(f"`{path}` could not govern: " + "; ".join(found) + ".")
            texts = {p: t for p, (_d, t) in self.result.items()}
            generated = ac.render_generated(settings, docs, texts)
            before_paths = set(sit.exam.texts)
            for path in sorted(set(texts) | (before_paths - {ac.CONTEXT_MAP})):
                old = sit.exam.texts.get(path) if path != ac.CONTEXT_MAP else None
                new = texts.get(path)
                if old != new:
                    plan.changes.append(Change(tx.CONTEXT, path, path, old, new))
            for path in (ac.CONTEXT_MAP, ac.METADATA):
                old = sit.exam.texts.get(path) if path == ac.CONTEXT_MAP else \
                    _read_folder_text(sit.folder, ac.METADATA)
                if old != generated[path]:
                    plan.changes.append(Change(tx.CONTEXT, path, path, old, generated[path]))
            plan.expected_hashes = {p: ac.sha256_text(t) for p, t in texts.items()}
            plan.expected_hashes[ac.CONTEXT_MAP] = ac.sha256_text(generated[ac.CONTEXT_MAP])
            plan.after = _listing(docs)
        else:
            plan.after = plan.before
        plan.problems += tx.path_problems(
            sit.cs, [tx.Write(c.root, c.path, c.new) for c in plan.changes])
        digest = hashlib.sha256()
        digest.update(json.dumps({"kind": plan.kind, "request": plan.request},
                                 sort_keys=True).encode("utf-8"))
        digest.update(json.dumps(sorted(sit.exam.hashes.items())).encode("utf-8"))
        digest.update(sit.exam.state.encode("utf-8"))
        for c in plan.changes:
            digest.update(f"\0{c.root}\0{c.path}\0{_sha(c.old)}\0{_sha(c.new)}".encode("utf-8"))
        for p in plan.problems:
            digest.update(p.encode("utf-8"))
        plan.plan_id = digest.hexdigest()[:20]
        return plan


def _read_folder_text(folder: str, rel: str) -> Optional[str]:
    return ac.read_text(folder, rel)


# --- the actions --------------------------------------------------------------------

def _add(b: _Builder, req: Dict[str, Any]) -> None:
    title = _single_line(_text_field(req, "title", True) or "", "title")
    if not title:
        raise ActionRefused("A document needs a title.")
    scope = _single_line(_text_field(req, "scope") or "", "scope")
    body = _body(_text_field(req, "body", True) or "")
    logical = b.sit.cs.new_candidate_path(slugify(title), b.sit.governing_names)
    meta = _candidate_meta(b.new_id(slugify(title)), title, scope, b.day)
    source = _text_field(req, "source")
    if source:
        meta["source"] = _single_line(source, "source")
    b.private(b.candidate_store(logical), logical, None, _render(meta, body))
    b.plan.summary = f"Create candidate: “{title}” becomes a private authority candidate."


def _revise(b: _Builder, req: Dict[str, Any]) -> None:
    """A candidate prefilled from a governing document. The person may change
    its title, scope and body before it is filed; the document is untouched."""
    doc = b.require_governing(req.get("path"))
    title = _text_field(req, "title")
    title = doc.title if title is None else _single_line(title, "title")
    if not title:
        raise ActionRefused("A document needs a title.")
    scope = _text_field(req, "scope")
    scope = str(doc.meta.get("scope") or "") if scope is None else _single_line(scope, "scope")
    body = _body(_text_field(req, "body"))
    logical = b.sit.cs.new_candidate_path(slugify(title), b.sit.governing_names)
    meta = _candidate_meta(b.new_id(f"{doc.id}-revision"), title, scope, b.day)
    meta["created"] = b.day
    # The one governing document it was made from, which a person may be
    # offered as a target; never chosen for them. Dropped when the candidate
    # governs.
    meta[REVISES] = doc.id
    meta[REVISES_SHA] = b.sit.exam.hashes.get(doc.path, "")
    b.private(b.candidate_store(logical), logical, None,
              _render(meta, doc.body if body is None else body))
    b.plan.summary = (f"Revise “{doc.title}”: file a candidate prefilled from it. The governing "
                      "document does not change.")


def _edit_candidate(b: _Builder, req: Dict[str, Any]) -> None:
    logical = req.get("candidate")
    doc, text = b.require_candidate(logical)
    meta = dict(doc.meta)
    title = _text_field(req, "title")
    scope = _text_field(req, "scope")
    # A title- or scope-only edit leaves the text as it is.
    body = _body(_text_field(req, "body"))
    if title is not None:
        title = _single_line(title, "title")
        if not title:
            raise ActionRefused("A document needs a title.")
        meta["title"] = title
    if scope is not None:
        meta["scope"] = _single_line(scope, "scope")
    meta["updated"] = b.day
    new = _render(meta, doc.body if body is None else body)
    b.private(b.candidate_store(logical), logical, text, new)
    b.plan.summary = f"Edit the authority candidate “{doc.title}”. It does not govern."


def _retire(b: _Builder, req: Dict[str, Any]) -> None:
    logical = req.get("candidate")
    doc, text = b.require_candidate(logical)
    name = ps.candidate_name(logical)
    if name in b.sit.archived:
        name = b.archive_name(name[:-3])
    meta = dict(doc.meta, status="retired", authority="non-authoritative", updated=b.day)
    b.private(b.candidate_store(logical), logical, text, None)
    b.private(f"{ps.ARCHIVE}/{name}", f"archive/{name}", None, _render(meta, doc.body))
    b.plan.summary = f"Retire the authority candidate “{doc.title}” to the private archive."


# A candidate's private note of the governing document Revise made it from,
# and of that document's exact text then: a governing document's id changes
# with every revision, and its text may change outside Charter.
REVISES = "revises"
REVISES_SHA = "revises_sha256"
# What a candidate records about where it came from: the file it was created
# from or the Agent Proposal and agent that filed it. Private manager state
# (UI Standards), so never carried into a governing document.
PRIVATE_KEYS = (REVISES, REVISES_SHA, "source")
# The source a governing document withdrawn by a change set records, once it
# is an authority candidate again.
WITHDRAWN_SOURCE = "Withdrawn governing document"


def revision_lineage(meta: Dict[str, Any], documents: List[Document], hashes: Dict[str, str],
                     archived: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The governing document a revision candidate revises now, followed
    through every revision or replacement since it was made: `revises_path`
    and `revises_title` name it, and `revises_current` is False when the
    candidate was made from an earlier version, or from text since changed
    outside Charter, so applying it would undo what changed since. A
    candidate whose document no longer governs keeps only its title."""
    out = {"revises_path": "", "revises_title": "", "revises_current": True}
    revises = str(meta.get(REVISES) or "")
    if not revises:
        return out
    by_id = {d.id: d for d in documents}
    successor: Dict[str, str] = {}
    for m in archived:
        after = m.get("superseded_by")
        if m.get("id") and isinstance(after, list) and len(after) == 1:
            successor[str(m["id"])] = str(after[0])
    for d in documents:
        for before in d.meta.get("supersedes") or []:
            successor[str(before)] = d.id
    current, steps = revises, 0
    while current not in by_id and current in successor and steps <= len(successor):
        current, steps = successor[current], steps + 1
    doc = by_id.get(current)
    if doc is None:
        title = next((str(m.get("title") or "") for m in archived if str(m.get("id")) == revises), "")
        return dict(out, revises_title=title, revises_current=False)
    base = str(meta.get(REVISES_SHA) or "")
    same = steps == 0 and (not base or base == hashes.get(doc.path, base))
    return {"revises_path": doc.path, "revises_title": doc.title, "revises_current": same}


def archived_metas(cs: ps.ContextState) -> List[Dict[str, Any]]:
    """The front matter of every archived document, for following lineage."""
    out = []
    for name in cs.archived():
        meta, _body = parse_front_matter(cs.read_archived(name) or "")
        if isinstance(meta, dict):
            out.append(meta)
    return out


def change_summary(body: str, base: Optional[str] = None) -> str:
    """A short, stable description of a candidate's text: for a revision, how
    many lines it changes from the governing text it now revises."""
    lines = (body or "").split("\n")
    if base is None:
        count = len([line for line in lines if line.strip()])
        return f"{count} line{'' if count == 1 else 's'} of text"
    before = (base or "").split("\n")
    matcher = difflib.SequenceMatcher(None, before, lines, autojunk=False)
    edits = [op for op in matcher.get_opcodes() if op[0] != "equal"]
    changed = sum(max(i2 - i1, j2 - j1) for _op, i1, i2, j1, j2 in edits)
    if not changed:
        return "no text changes"
    # The first line it writes, or else removes: what tells two revisions apart.
    added = [line.strip() for _op, _i1, _i2, j1, j2 in edits for line in lines[j1:j2] if line.strip()]
    removed = [line.strip() for _op, i1, i2, _j1, _j2 in edits for line in before[i1:i2] if line.strip()]
    quoted = added[0] if added else removed[0] if removed else ""
    if len(quoted) > 48:
        quoted = quoted[:47] + "…"
    what = (f": “{quoted}”" if added else f", removing “{quoted}”") if quoted else ""
    return f"changes {changed} line{'' if changed == 1 else 's'}{what}"


def _governing_meta(meta: Dict[str, Any], day: str) -> Dict[str, Any]:
    out = dict(meta, authority="authoritative", status="active", updated=day)
    for key in PRIVATE_KEYS:
        out.pop(key, None)
    out.setdefault("supersedes", [])
    out.setdefault("superseded_by", [])
    return out


# --- Agent Proposals: a person's decision ------------------------------------------------

PROPOSAL_NOTE = ("Accepting an Agent Proposal changes only an authority candidate, which is not "
                 "context. It never changes governing context: making a candidate govern is a "
                 "separate decision, in a change set.")


def _proposal(b: _Builder, req: Dict[str, Any]):
    from . import agent_proposals as apx
    if not b.sit.exam.valid:
        raise ActionRefused("Agent Proposals are reviewed against a valid Agent Context. Correct "
                            "it first.")
    try:
        record, text = apx.trusted(b.sit.cs, req.get("proposal_id"))
    except ValueError as exc:
        raise ActionRefused(str(exc))
    return apx, record, text


def _move_record(b: _Builder, apx, record: Dict[str, Any], text: str, decision: str,
                 **detail: Any) -> None:
    pid = record["proposal_id"]
    b.private(f"{ps.PROPOSALS}/{apx.PENDING}/{pid}.json", f"Agent Proposal {pid}", text, None)
    b.private(f"{ps.PROPOSALS}/{decision}/{pid}.json", f"Agent Proposal {pid} ({decision})",
              None, apx.decided(record, decision, **detail))


def _accept_proposal(b: _Builder, req: Dict[str, Any]) -> None:
    apx, record, text = _proposal(b, req)
    p = record["proposal"]
    target = apx.Target(b.sit.folder, b.sit.cs, b.sit.exam)
    stale = apx.staleness(p, target)
    if stale:
        raise ActionRefused("This proposal cannot be accepted as written: " + " ".join(stale)
                            + " Reject it, or ask the agent to propose again.")
    pid, agent, op, path = record["proposal_id"], p.get("agent", ""), p["operation"], p["target_path"]
    meta_in = p.get("proposed_meta") or {}
    source = f"Agent Proposal {pid} ({agent}, self-reported)"
    if op == "retire":
        doc, cand_text = b.require_candidate(path)
        name = ps.candidate_name(path)
        if name in b.sit.archived:
            name = b.archive_name(name[:-3])
        meta = dict(doc.meta, status="retired", authority="non-authoritative", updated=b.day)
        b.private(b.candidate_store(path), path, cand_text, None)
        b.private(f"{ps.ARCHIVE}/{name}", f"archive/{name}", None, _render(meta, doc.body))
        outcome = f"archive/{name}"
        b.plan.summary = (f"Accept the proposal: the authority candidate “{doc.title}” is retired to "
                          "the private archive.")
    else:
        current = target.text_of(path) if op == "amend" else None
        body = p.get("proposed_body")
        if body is None:
            body = apx.apply_replacements(apx.body_of(current or ""), p.get("replacements"), [])
            if body is None:
                raise ActionRefused("The replacements no longer apply to the current text.")
        # A proposal filed before intake refused this is refused here, never
        # rewritten: the agent corrects it.
        if leading_front_matter(body) is not None:
            raise ActionRefused("This proposal cannot be accepted as written: its body begins with "
                                "a front-matter block, which would be a second one inside the "
                                "candidate. Reject it, and ask the agent to propose again without it.")
        if op == "create":
            title = meta_in.get("title") or apx.first_heading(body) or path.rsplit("/", 1)[-1][:-3]
            # Intake never refuses a create for a name already in use (candidate
            # and archived names are private), so a collision is resolved here:
            # the requested name when it is free, otherwise a fresh free name.
            requested = ps.candidate_name(path)
            logical = path if not b.sit.cs.name_in_use(requested, b.sit.governing_names) \
                else b.sit.cs.new_candidate_path(slugify(title), b.sit.governing_names)
            meta = _candidate_meta(b.new_id(slugify(title)), title, meta_in.get("scope", ""), b.day)
            meta["source"] = source
            b.private(b.candidate_store(logical), logical, None, _render(meta, body))
            b.plan.summary = f"Accept as candidate: “{' '.join(title.split())}” becomes a private authority candidate."
        elif path in b.sit.governing:
            doc = b.sit.governing[path]
            title = meta_in.get("title") or doc.title
            scope = meta_in["scope"] if "scope" in meta_in else str(doc.meta.get("scope") or "")
            logical = b.sit.cs.new_candidate_path(slugify(title), b.sit.governing_names)
            meta = _candidate_meta(b.new_id(f"{doc.id}-revision"), title, scope, b.day)
            meta["created"] = b.day
            meta["source"] = source
            # The same revision lineage a candidate made with Revise records: the
            # governing document this amendment revises, by its id and text, not a
            # filename (Scope Authoring and Revision Workflow).
            meta[REVISES] = doc.id
            meta[REVISES_SHA] = b.sit.exam.hashes.get(doc.path, "")
            b.private(b.candidate_store(logical), logical, None, _render(meta, body))
            b.plan.summary = (f"Accept as candidate: a revision of “{doc.title}”, titled “{title}”, "
                              "becomes a private authority candidate. “" + doc.title + "” keeps governing "
                              "unchanged.")
        else:
            logical = path
            doc, cand_text = b.require_candidate(path)
            meta = dict(doc.meta, updated=b.day)
            if "title" in meta_in:
                meta["title"] = meta_in["title"]
            if "scope" in meta_in:
                meta["scope"] = meta_in["scope"]
            b.private(b.candidate_store(logical), logical, cand_text, _render(meta, body))
            b.plan.summary = f"Accept as candidate: the private authority candidate “{doc.title}” is updated."
        outcome = logical
    _move_record(b, apx, record, text, apx.ACCEPTED, outcome=outcome)
    b.plan.notes.append(PROPOSAL_NOTE)


def _reject_proposal(b: _Builder, req: Dict[str, Any]) -> None:
    apx, record, text = _proposal(b, req)
    reason = (_text_field(req, "reason") or "").strip()
    # Optional (UI Standards): kept privately with the rejection only when given.
    _move_record(b, apx, record, text, apx.REJECTED, **({"reason": reason} if reason else {}))
    title, _kind = apx.title_of(record["proposal"], apx.Target(b.sit.folder, b.sit.cs, b.sit.exam)
                                if b.sit.exam.valid else None, b.sit.cs)
    b.plan.summary = f"Reject the proposal for “{title}”. Nothing else changes."


# --- coordinated change sets ------------------------------------------------------------

def _free_candidate(b: _Builder, name: str, exclude: str, taken: List[str]) -> str:
    """A logical candidate path for a withdrawn document: its own file name
    when free everywhere and usable as a private name, else the first free
    name made from it — made safe and shortened when the governing file name
    could not name a candidate — refused after a bounded number of tries
    (`private_store.free_name`)."""
    others = [p for p in b.sit.governing_names if p != exclude]
    used = b.sit.cs.taken_names(others) | set(taken)
    try:
        return ps.logical_candidate(ps.free_name(name.rsplit(".", 1)[0], used, first=name))
    except ps.PrivateStateError as exc:
        raise ActionRefused(str(exc))


def _compose_changeset(b: _Builder, draft: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every declared outcome of a change set, composed into one plan, with
    what each does: each candidate's replacement or governing alongside, each
    withdrawal, and every other governing document retained. Outcomes are the
    person's, exactly as declared."""
    from . import changeset as chs
    b.plan.governing_change = True
    effects: List[Dict[str, Any]] = []
    archived_taken: List[str] = []
    candidates_taken: List[str] = []
    outcomes, alongside = chs.rows(draft)
    declared = dict(outcomes)
    for gov in chs.others(draft):
        declared[gov] = {"outcome": chs.RETAIN}
    for gov in sorted(declared):
        o = declared[gov]
        old = b.require_governing(gov)
        old_scope = str(old.meta.get("scope") or "").strip()
        base = {"effect": o["outcome"], "document": gov, "title": old.title,
                "scope_before": old_scope}
        if o["outcome"] in (chs.REVISE, chs.REPLACE):
            doc, text = b.require_candidate(o.get("candidate"))
            _governable(doc, text)
            if doc.meta.get(REVISES):
                lineage = revision_lineage(doc.meta, b.sit.exam.documents, b.sit.exam.hashes,
                                           archived_metas(b.sit.cs))
                if not lineage["revises_current"]:
                    # Never an ordinary-looking revision: what changed since is undone.
                    b.plan.notes.append(
                        f"“{doc.title}” was made from an earlier version of "
                        f"“{lineage['revises_title'] or old.title}”. Applying it replaces "
                        f"{gov} with its text, so whatever changed in that document since — "
                        "including any revision applied since — is undone unless the candidate "
                        "repeats it. Compare them before you apply.")
            if doc.id == old.id:
                raise ActionRefused(f"“{doc.title}” has the same id as `{gov}`, which it would "
                                    "replace.")
            meta = _governing_meta(doc.meta, b.day)
            cand_scope = str(doc.meta.get("scope") or "").strip()
            meta["scope"] = cand_scope or old_scope
            meta["supersedes"] = [old.id]
            meta["superseded_by"] = []
            new_doc = Document(path=old.path, meta=meta, body=doc.body)
            b.result[old.path] = (new_doc, new_doc.render())
            stem = old.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            name = b.archive_name(f"{stem}-superseded", taken=archived_taken)
            archived_taken.append(name)
            archived = dict(old.meta, status="superseded", authority="non-authoritative",
                            superseded_by=[doc.id], updated=b.day)
            b.private(b.candidate_store(o["candidate"]), o["candidate"], text, None)
            b.private(f"{ps.ARCHIVE}/{name}", f"archive/{name}", None, _render(archived, old.body))
            effects.append(dict(base, candidate=o["candidate"], candidate_title=doc.title,
                                candidate_id=doc.id, archived_to=f"archive/{name}",
                                scope_proposed=cand_scope, scope_after=meta["scope"]))
        elif o["outcome"] == chs.WITHDRAW:
            del b.result[gov]
            logical = _free_candidate(b, gov.rsplit("/", 1)[-1], gov, candidates_taken)
            candidates_taken.append(ps.candidate_name(logical))
            meta = dict(old.meta, authority="non-authoritative", status="active", updated=b.day,
                        source=WITHDRAWN_SOURCE)
            b.private(b.candidate_store(logical), logical, None, _render(meta, old.body))
            effects.append(dict(base, withdrawn_to=logical))
        else:
            effects.append(dict(base, scope_after=old_scope))
    for logical in alongside:
        doc, text = b.require_candidate(logical)
        _governable(doc, text)
        path = f"{ac.AUTHORITATIVE}/{ps.candidate_name(logical)}"
        if path in b.result or any(p.casefold() == path.casefold() for p in b.sit.governing_names):
            raise ActionRefused(f"`{path}` is already in use, so “{doc.title}” cannot govern "
                                "there.")
        meta = _governing_meta(doc.meta, b.day)
        new_doc = Document(path=path, meta=meta, body=doc.body)
        b.result[path] = (new_doc, new_doc.render())
        b.private(b.candidate_store(logical), logical, text, None)
        effects.append({"effect": chs.ALONGSIDE, "document": path, "title": doc.title,
                        "candidate": logical, "candidate_title": doc.title, "candidate_id": doc.id,
                        "scope_after": str(meta.get("scope") or "")})
    b.plan.summary = f"Apply change set “{draft['title']}”"
    return effects


def _changeset(b: _Builder, req: Dict[str, Any]) -> None:
    """Apply a change set: every declared outcome, and — in the same
    transaction — the draft becoming its immutable receipt. Either all of it
    happens, or none of it."""
    from . import changeset as chs
    ctx = chs.Ctx(b.sit.folder)
    try:
        draft = chs.load_for_apply(ctx, req.get("draft_id"), req.get("draft_revision"))
    except chs.ChangeSetError as exc:
        raise ActionRefused(str(exc))
    now = chs.Now(ctx)
    review = chs.review_checks(ctx, draft, now)
    before = _listing(b.sit.exam.documents)
    effects = _compose_changeset(b, draft)
    effect_of = {e["document"]: e["effect"] for e in effects}
    after = [dict(d, effect=("added" if effect_of.get(d["path"]) == chs.ALONGSIDE else
                             "revised" if effect_of.get(d["path"]) == chs.REVISE else
                             "replaced" if effect_of.get(d["path"]) == chs.REPLACE else "retained"))
             for d in _listing([doc for doc, _t in b.result.values()])]
    receipt = chs.receipt_of(draft, {"effects": effects, "before": before, "after": after,
                                     "summary": chs.summary_text(draft, effects, review,
                                                                 applied=True)}, review)
    # The fingerprint the applied context will have, from the planned result.
    settings = b.sit.exam.settings
    texts = {p: t for p, (_d, t) in b.result.items()}
    generated = ac.render_generated(settings, [d for d, _t in b.result.values()], texts)
    hashes = {p: ac.sha256_text(t) for p, t in texts.items()}
    hashes[ac.CONTEXT_MAP] = ac.sha256_text(generated[ac.CONTEXT_MAP])
    record = chs.record_path(draft["id"])
    old = b.sit.cs.path(*record.split("/"))
    with open(old, encoding="utf-8") as fh:
        current = fh.read()
    b.private(record, f"Change set “{draft['title']}” (receipt)", current,
              chs.applied_record(draft, receipt, ac.context_fingerprint(hashes)))


def changeset_plan(folder: str, draft: Dict[str, Any], summary_fn: Any = None,
                   review: Any = None, state: Optional[ps.PrivateState] = None):
    """The one plan that applies `draft`, as `plan(folder, "changeset", …)`
    builds it, and what each outcome does. For previewing a draft."""
    sit = situation(folder, state)
    if not sit.exam.valid:
        raise ActionRefused("The Agent Context is not valid and clean now.")
    request = {"draft_id": draft["id"], "draft_revision": draft["revision"]}

    def build(day: str):
        b = _Builder(sit, "changeset", request, day)
        effects = _compose_changeset(b, draft)
        return b.finish(), effects

    neutral, _effects = build(NEUTRAL_DAY)
    shown, effects = build(today())
    shown.plan_id = neutral.plan_id
    return shown, effects


# The kinds whose writes carry a date this module assigns.
_DATED_KINDS = ("add", "revise", "edit-candidate", "retire", "accept-proposal", "changeset")

_BUILDERS: Dict[str, Callable[[_Builder, Dict[str, Any]], None]] = {
    "add": _add, "revise": _revise, "edit-candidate": _edit_candidate, "retire": _retire,
    "accept-proposal": _accept_proposal, "reject-proposal": _reject_proposal,
    "changeset": _changeset}


def plan(folder: str, kind: str, request: Dict[str, Any],
         state: Optional[ps.PrivateState] = None) -> Plan:
    """Plan an action without writing anything."""
    if kind not in _BUILDERS:
        raise ActionRefused(f"`{kind}` is not an authority action.")
    if not isinstance(request, dict):
        raise ActionRefused("The request must be an object.")
    return _plan(situation(folder, state), kind, request)


def _plan(sit: Situation, kind: str, request: Dict[str, Any]) -> Plan:
    if kind in GOVERNING_KINDS and not sit.exam.valid:
        raise ActionRefused(
            "The Agent Context is not valid and clean now, so its governing context cannot "
            "change until that is corrected. "
            + " ".join(f"{i['path'] or 'The folder'}: {i['message']}" for i in sit.exam.errors))
    neutral = _build(sit, kind, request, NEUTRAL_DAY)
    shown = _build(sit, kind, request, today())
    shown.plan_id = neutral.plan_id
    return shown


def _build(sit: Situation, kind: str, request: Dict[str, Any], day: str) -> Plan:
    b = _Builder(sit, kind, request, day)
    _BUILDERS[kind](b, request)
    if kind != "changeset" and kind in _DATED_KINDS:
        b.plan.notes.append(APPLY_DATE_NOTE)
    return b.finish()


# --- applying ------------------------------------------------------------------------

def recover(folder: str, state: Optional[ps.PrivateState] = None) -> Optional[Dict[str, Any]]:
    """Roll back an interrupted earlier write, if there is one: what opening an
    Agent Context does first. Returns what was done, or None."""
    cs = (state or ps.PrivateState.default()).for_context(folder)
    with cs.lock("writer") as held:
        if not held:
            raise ActionRefused("Another Charter action on this Agent Context is "
                                "in progress. Try again when it has finished.")
        return _recover(cs)


def _recover(cs: ps.ContextState) -> Optional[Dict[str, Any]]:
    """`transaction.recover`, its refusal worded as an ActionRefused: a record of
    an interrupted write that cannot be trusted stops every action, and
    changes nothing."""
    try:
        return tx.recover(cs)
    except tx.TransactionError as exc:
        raise ActionRefused(exc.message)


def _unchanged_since_plan(folder: str, current: Plan, targets: List[str]) -> Callable[[], None]:
    """Immediately before the first file is replaced: every governing document
    and generated file the plan relied on but does not write must still be what
    it was planned from. A change made meanwhile refuses the action, with
    nothing replaced."""
    def check() -> None:
        if not current.governing_change:
            return
        changed = [p for p, h in sorted(current.expected_hashes.items())
                   if p not in targets and ac.sha256_text(ac.read_text(folder, p) or "\0") != h]
        if changed:
            raise tx.ConcurrentChange(changed)
    return check


def apply(folder: str, kind: str, request: Dict[str, Any], plan_id: str, confirm: Any,
          state: Optional[ps.PrivateState] = None,
          fault: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
    """Apply the plan the person saw as `plan_id`, with their confirmation:
    the typed phrase for a context-changing action, `True` otherwise."""
    state = state or ps.PrivateState.default()
    cs = state.for_context(folder)
    with cs.lock("writer") as held:
        if not held:
            raise ActionRefused("Another Charter action on this Agent Context is "
                                "in progress. Try again when it has finished.")
        recovered = _recover(cs)
        current = plan(folder, kind, request, state)
        if current.plan_id != plan_id:
            raise StalePlan("The Agent Context or its candidates changed after this preview was "
                            "shown. Review the new preview before applying.")
        if current.blocked:
            raise ActionRefused("This action cannot apply: " + " ".join(current.problems))
        if current.governing_change:
            if confirm != CONFIRM_PHRASE:
                raise ActionRefused(f"Type “{CONFIRM_PHRASE}” to change the governing context.")
        elif confirm is not True:
            raise ActionRefused("Confirm the action to apply it.")

        # Each write carries what its target held when the plan was built (or
        # that it was absent), so a target changed since is refused, not
        # overwritten (`transaction.Write.expected`).
        writes = [tx.Write(c.root, c.path, c.new, tx.expect(c.old)) for c in current.changes]
        if kind == "changeset":
            # The applied receipt says when it was written.
            from . import changeset as chs
            writes = [tx.Write(w.root, w.path, chs.stamp(w.text), w.expected)
                      if w.text and chs.APPLIED_AT in w.text else w for w in writes]
        elif kind in ("accept-proposal", "reject-proposal"):
            # The decided record says when it was decided.
            from . import agent_proposals as apx
            writes = [tx.Write(w.root, w.path, apx.stamp(w.text), w.expected)
                      if w.root == tx.PRIVATE and w.text and w.path.startswith(f"{ps.PROPOSALS}/")
                      else w for w in writes]
        labels = {c.path: c.label for c in current.changes}
        before = ac.examine(cs.folder)

        def validate() -> None:
            if not current.governing_change:
                return
            exam = ac.examine(cs.folder)
            if not exam.valid or exam.hashes != current.expected_hashes:
                raise ActionRefused("After writing, the Agent Context was not exactly the "
                                    "planned valid context.")

        targets = [w.path for w in writes if w.root == tx.CONTEXT]
        transaction = tx.Transaction(cs, writes, validate=validate, fault=fault,
                                     precondition=_unchanged_since_plan(cs.folder, current, targets))
        try:
            transaction.run()
        except tx.TransactionError as exc:
            if exc.concurrent and exc.restored:
                raise StalePlan(
                    "Something this action replaces or relies on changed while it was being "
                    "applied: " + ", ".join(f"`{labels.get(p, p)}`" for p in exc.concurrent)
                    + ". Charter overwrote nothing, and nothing was changed. Review the new "
                    "preview before applying.")
            where = ("Everything it wrote was rolled back." if exc.restored else
                     "It was rolled back except for files changed meanwhile by someone else, "
                     "left as they are: " + ", ".join(exc.unrestored) + "." if exc.unrestored
                     else "")
            raise ApplyFailed(f"The action did not apply ({exc.message}). {where}".rstrip(),
                              exc.restored, exc.unrestored)
        # The action is final from here. Anything that fails now is reported
        # alongside its success, never as though nothing changed.
        result: Dict[str, Any] = {"applied": True, "kind": kind, "summary": current.summary,
                                  "governing_change": current.governing_change,
                                  "recovered": recovered,
                                  "follow_up": list(transaction.follow_up)}
        if current.governing_change:
            try:
                from . import observation
                exam = ac.examine(cs.folder)
                result["fingerprint"] = exam.fingerprint
                observation.record_charter_write(cs, before, exam)
            except Exception:  # noqa: BLE001 — the change is applied; say what did not follow
                result["follow_up"].append(
                    "The change was applied, and agents read the new context. Charter could not "
                    "update its private record of what it last saw in this folder, so it may "
                    "show this change as made outside Charter until you acknowledge it.")
        return result
