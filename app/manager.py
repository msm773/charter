"""Opening, creating, checking and rebuilding an Agent Context.

Product Specification §3.1, §3.5 and §5; Agent Context as the Project Asset §4,
§7 and §8; UI Standards. The person-facing operations around authority
actions:

  * **Open Agent Context**: recover any interrupted Charter write, validate the
    folder, and say whether agents are served, what is wrong and what to do
    next, and whether the content changed outside Charter;
  * **Create** a new, empty Agent Context in a folder the person chooses;
  * **Check** a folder without changing anything, for `charter check`;
  * **Rebuild Agent Context**, after ordinary edits, merges or recovery: when the
    governing documents are valid and the folder is clean, regenerate
    `AGENT-CONTEXT.md` and `.agent-context.json`, after a previewed, ordinary
    deliberate confirmation. It never changes a governing document, never
    touches a stray, and never repairs anything silently;
  * **Settings**: the project name and the three agent guidance settings,
    recorded in the metadata and rendered into the map.

Git information is read-only and limited to the Agent Context folder: the
branch and the context files Git reports as changed. Nothing here operates Git.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from typing import Any, Dict, List, Optional, Tuple

from . import agent_context as ac
from . import host_state as hs
from . import observation
from . import private_store as ps
from . import transaction as tx
from .authority import ActionRefused, ApplyFailed, Change, Plan, StalePlan, _listing

SERVED = "Agents read this folder's current context."


# --- read-only Git information -----------------------------------------------------

# The only Git subcommands Charter runs. None writes; `status`
# runs without optional locks, so it does not refresh the index either.
GIT_READ_ONLY = ("rev-parse", "symbolic-ref", "status")

# Options that stop a folder's own `.git/config` from running a program while
# Charter reads Git: `core.fsmonitor` is a command `status` spawns, and these also
# keep hooks, a pager and protocol helpers from running. Passed on the command
# line, where repository config cannot override them.
GIT_SAFE = ("-c", "core.fsmonitor=false", "-c", f"core.hooksPath={os.devnull}",
            "-c", "protocol.ext.allow=never")


# What the console can say about Git for an Agent Context folder.
GIT_CHECKOUT = "checkout"          # the branch and the changed context files are known
GIT_NOT_CHECKOUT = "not-checkout"  # no Git working tree holds the folder
GIT_UNAVAILABLE = "unavailable"    # Git could not be run on this computer
GIT_UNREADABLE = "unreadable"      # a Git checkout, whose status could not be read

# Set when Git itself could not be started, as opposed to Git answering with a failure.
_GIT_MISSING = object()


def _git_run(folder: str, *args: str) -> Any:
    """Git's output, None when Git ran and failed (or did not finish), or
    `_GIT_MISSING` when Git could not be started."""
    if args[0] not in GIT_READ_ONLY:
        raise ValueError(f"Charter does not run `git {args[0]}`.")
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"}
    try:
        proc = subprocess.run(["git", *GIT_SAFE, "--no-optional-locks", "-C", folder, *args],
                              capture_output=True, env=env, timeout=10)
    except OSError:
        return _GIT_MISSING
    except subprocess.SubprocessError:
        return None
    if proc.returncode != 0:
        return None
    # Only line endings are trimmed: `status --porcelain` columns begin with a space.
    return proc.stdout.decode("utf-8", "replace").rstrip("\r\n")


def _git(folder: str, *args: str) -> Optional[str]:
    out = _git_run(folder, *args)
    return None if out is _GIT_MISSING else out


def _git_marker(folder: str) -> bool:
    """Whether the folder or one above it holds `.git`: a checkout Git failed
    to read, rather than no checkout at all. Looks only at names."""
    here = os.path.abspath(folder)
    while True:
        if os.path.lexists(os.path.join(here, ".git")):
            return True
        parent = os.path.dirname(here)
        if parent == here:
            return False
        here = parent


def git_info(folder: str) -> Dict[str, Any]:
    """Read-only, secondary Git information for the folder, as a `state`:
    a checkout, with its branch and the context files Git reports as changed;
    not a checkout; Git unavailable; or a checkout whose status could not be
    read. A failure is never reported as an empty list of changes."""
    inside = _git_run(folder, "rev-parse", "--is-inside-work-tree")
    if inside is _GIT_MISSING:
        return {"state": GIT_UNAVAILABLE}
    if inside != "true":
        return ({"state": GIT_UNREADABLE, "branch": ""} if inside is None and _git_marker(folder)
                else {"state": GIT_NOT_CHECKOUT})
    branch = _git(folder, "symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch:
        head = _git(folder, "rev-parse", "--short", "HEAD")
        branch = f"detached at {head}" if head else "no commits yet"
    porcelain = _git(folder, "status", "--porcelain=v1", "--untracked-files=all", "--", ".")
    if porcelain is None:
        return {"state": GIT_UNREADABLE, "branch": branch}
    changed = [line[3:] for line in porcelain.splitlines() if len(line) > 3]
    return {"state": GIT_CHECKOUT, "branch": branch, "changed": changed}


# --- status ------------------------------------------------------------------------------

# Why agents are not served, in person-facing terms (UI Standards): a heading,
# then what it means and the next safe action. Agents get an unavailable
# answer instead of governing material until it is resolved.
NOT_YET = "Charter can’t serve this Agent Context yet"
STRAY_TITLE = NOT_YET
STRAY_DETAIL = ("This folder contains files that are not part of the Agent Context. Charter leaves "
                "them untouched.")
INTERRUPTED = (NOT_YET, "A Charter write to this folder was interrupted. Open the Agent Context in "
                        "Charter to recover it.")
PRIVATE_UNUSABLE = (NOT_YET, "Charter’s local records for this folder can’t be used, so it can’t "
                             "tell whether a write was interrupted. Open the Agent Context in Charter "
                             "to see what to do.")
# The map's format, each way: governed to say which is out of date (UI Standards).
CHARTER_OUTDATED = ("This copy of Charter is out of date",
                    "A newer version of Charter generated this Agent Context, so this copy can’t check "
                    "or serve it. The Agent Context is not at fault. Use the current Charter "
                    "installation.")
LEGACY = (NOT_YET, "Its map was generated by Agent Context Manager, Charter’s earlier name. The "
                   "governing documents are unchanged. Use Rebuild Agent Context to regenerate the "
                   "map and metadata.")
MAP_OUTDATED = ("This Agent Context’s map is out of date",
                "An earlier version of Charter generated it, so Charter can’t serve the context until "
                "it’s rebuilt. The governing documents are unchanged. Use Rebuild Agent Context to "
                "bring it up to date.")
MISMATCH = (NOT_YET, "The map and metadata don’t match the governing documents. Check that the "
                     "documents are what you intend, then use Rebuild Agent Context.")
NOT_VALID = (NOT_YET, "Something in this folder isn’t valid. Each problem, and how to fix it, is "
                      "listed below.")


def _headline_parts(exam: ac.Examination, interrupted: bool) -> Tuple[str, str]:
    """The status's heading, and the sentences that follow it on their own."""
    if interrupted:
        return INTERRUPTED
    if exam.valid:
        return SERVED, ""
    if exam.state == ac.UNCLEAN:
        return STRAY_TITLE, STRAY_DETAIL
    if exam.charter_outdated:
        return CHARTER_OUTDATED
    if exam.legacy_map:
        return LEGACY
    if exam.map_outdated:
        return MAP_OUTDATED
    if exam.errors and not exam.rebuild_blockers:
        return MISMATCH
    return NOT_VALID


def _joined(title: str, detail: str) -> str:
    return f"{title}. {detail}" if detail else title


def _headline(exam: ac.Examination, interrupted: bool) -> str:
    """The heading and its detail as one line, for `charter check` and Connect agents."""
    return _joined(*_headline_parts(exam, interrupted))


def _status(folder: str, cs: Optional[ps.ContextState], exam: ac.Examination,
            recovered: Optional[Dict[str, Any]] = None, git: bool = True) -> Dict[str, Any]:
    interrupted = bool(cs is not None and tx.interrupted(cs))
    generated = [i for i in exam.errors if i["kind"] == ac.GENERATED_KIND]
    settings = exam.settings
    title, detail = _headline_parts(exam, interrupted)
    return {
        "path": folder,
        "name": settings.project_name if settings else os.path.basename(folder),
        "state": exam.state,
        "agents_served": exam.valid and not interrupted,
        "headline": _headline(exam, interrupted),
        "headline_title": title,
        "headline_detail": detail,
        "interrupted": interrupted,
        "recovered": recovered,
        "issues": exam.issues,
        "strays": exam.strays,
        "rebuild": {"available": bool(generated) and not exam.rebuild_blockers
                    and not interrupted,
                    "blockers": exam.rebuild_blockers,
                    "needs_project_name": settings is None},
        "governing": _listing(exam.documents),
        "settings": None if settings is None else {
            "project_name": settings.project_name, "agent_guidance": settings.guidance_map},
        "outside": observation.status(cs, exam),
        # For Diagnostics only: ordinary statuses never name a version.
        "map_format": {"generated": ac.MAP_FORMAT_VERSION, "recorded": exam.recorded_map_format,
                       "relation": exam.map_format},
        "git": git_info(folder) if git else None,
        "legacy_state": ps.PrivateState.default().legacy(),
    }


# Said beside a success when only Charter's private record of it failed.
OBSERVATION_FAILED = ("The change was made, and agents read the new context. Charter could not "
                      "update its private record of what it last saw in this folder, so it may "
                      "show this change as made outside Charter until you acknowledge it.")

NESTED = ("This folder is inside another Agent Context, at {enclosing}. Open that Agent Context "
          "instead: an Agent Context cannot hold another one.")


def open_context(folder: str, state: Optional[ps.PrivateState] = None) -> Dict[str, Any]:
    """Open Agent Context: recover an interrupted Charter write, then report."""
    folder = hs.canonical(folder)
    if not os.path.isdir(folder):
        raise ActionRefused("There is no folder here. Choose the folder that holds "
                            "AGENT-CONTEXT.md, or create a new Agent Context.")
    enclosing = _enclosing_context(folder)
    if enclosing:
        # Create already refuses this; Open must too, or Rebuild from the opened
        # folder would write a nested map and metadata and take the enclosing
        # context offline. An ordinary project folder is not an Agent Context,
        # so a context kept inside a project still opens.
        raise ActionRefused(NESTED.format(enclosing=enclosing))
    cs = (state or ps.PrivateState.default()).for_context(folder)
    recovered = None
    with cs.lock("writer", timeout=1.0) as held:
        if held:
            try:
                recovered = tx.recover(cs)
            except tx.TransactionError as exc:
                recovered = {"problem": exc.message}
    exam = ac.examine(folder)
    observation.remember_settings(cs, exam)
    return _status(folder, cs, exam, recovered)


def check(folder: str, state: Optional[ps.PrivateState] = None, git: bool = True) -> Dict[str, Any]:
    """The status of a folder, changing nothing anywhere: no recovery, and no
    private state created. For `charter check --context <folder>`. Without `git`,
    Git is not asked about the folder at all."""
    folder = hs.canonical(folder)
    try:
        cs = (state or ps.PrivateState.default()).find_context(folder, strict=True)
    except ps.PrivateStateError as exc:
        # Private state that exists but cannot be trusted may hide an
        # interrupted write: refused, exactly as MCP refuses it.
        status = _status(folder, None, ac.examine(folder), recovered={"problem": str(exc)}, git=git)
        status.update(agents_served=False, interrupted=True, headline=_joined(*PRIVATE_UNUSABLE),
                      headline_title=PRIVATE_UNUSABLE[0], headline_detail=PRIVATE_UNUSABLE[1])
        return status
    return _status(folder, cs, ac.examine(folder), git=git)


def acknowledge(folder: str, state: Optional[ps.PrivateState] = None) -> Dict[str, Any]:
    """The person has seen the change made outside Charter."""
    cs = (state or ps.PrivateState.default()).for_context(folder)
    exam = ac.examine(cs.folder)
    if not exam.valid:
        raise ActionRefused("Only a valid Agent Context's outside changes can be acknowledged.")
    # Under the writer lock, so recording what was seen cannot race a change-set
    # apply that is rewriting the same observed-state record.
    with cs.lock("writer") as held:
        if not held:
            raise ActionRefused("Another Charter action on this folder is in "
                                "progress.")
        observation.acknowledge(cs, exam)
    return _status(cs.folder, cs, exam)


# --- create ------------------------------------------------------------------------------

def _enclosing_context(folder: str) -> str:
    return ac.enclosing_context(folder)


def create(folder: str, project_name: str,
           state: Optional[ps.PrivateState] = None) -> Dict[str, Any]:
    """Create a new, empty Agent Context at `folder`, which must be empty but
    for tolerated tooling files, or not exist yet inside an existing folder."""
    problem = ac.project_name_problem(project_name)
    if problem:
        raise ActionRefused(problem)
    folder = hs.canonical(folder)
    if os.path.exists(folder):
        if not os.path.isdir(folder) or os.path.islink(folder):
            raise ActionRefused("This is not a folder.")
        extra = sorted(n for n in os.listdir(folder)
                       if n != ".git" and not ac._tolerated_file(n))
        if extra:
            raise ActionRefused(
                "An Agent Context is created in an empty folder, and this one holds "
                + ", ".join(f"`{n}`" for n in extra[:5]) + (" and more" if len(extra) > 5 else "")
                + ". Choose an empty folder. To make an Agent Context of governing documents you "
                "already have, put them in `authoritative/` here and use Rebuild Agent Context.")
    elif not os.path.isdir(os.path.dirname(folder)):
        raise ActionRefused("The folder above it does not exist.")
    enclosing = _enclosing_context(folder)
    if enclosing:
        raise ActionRefused(f"This folder is inside another Agent Context, at {enclosing}. An "
                            "Agent Context cannot hold another one.")
    state = state or ps.PrivateState.default()
    state.ensure()
    if hs.overlaps(folder, state.root):
        raise ActionRefused("An Agent Context cannot be inside Charter's private "
                            "state, or contain it.")
    settings = ac.Settings.make(project_name)
    generated = ac.render_generated(settings, [], {})
    # Every file is new: one that appears meanwhile is never replaced.
    writes = [tx.Write(tx.CONTEXT, p, t, tx.ABSENT) for p, t in generated.items()]
    # Check every path against this system's limit before creating anything, so a
    # path too long for Windows (where long paths are off) is refused in the
    # person's words — never a raw operating-system error, and never leaving an
    # empty folder or a half-made context behind.
    try:
        cs = state.for_context(folder)
        problems = tx.path_problems(cs, writes)
        if problems:
            raise ActionRefused(" ".join(problems))
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        raise ActionRefused("The Agent Context could not be created here "
                            f"({exc.strerror or exc}). Choose a folder with a shorter path"
                            + (", or enable long paths in Windows." if os.name == "nt" else "."))
    with cs.lock("writer") as held:
        if not held:
            raise ActionRefused("Another Charter action on this folder is in "
                                "progress.")
        tx.recover(cs)

        def validate() -> None:
            if not ac.examine(folder).valid:
                raise ActionRefused("The new Agent Context did not validate.")
        transaction = tx.Transaction(cs, writes, validate=validate)
        try:
            transaction.run()
        except tx.TransactionError as exc:
            raise ApplyFailed(f"The Agent Context was not created ({exc.message}).",
                              exc.restored, exc.unrestored)
        after = ac.examine(folder)
        follow_up = list(transaction.follow_up)
        try:
            cs.record_observed(after.fingerprint, after.hashes, "charter", [])
            observation.remember_settings(cs, after)
        except Exception:  # noqa: BLE001 — the context is created; only the record failed
            follow_up.append(OBSERVATION_FAILED)
    status = _status(folder, cs, after)
    status["follow_up"] = follow_up
    return status


# --- generated-file plans: Rebuild and Settings ---------------------------------------------

def _read_raw_text(folder: str, rel: str) -> Optional[str]:
    # Reads only Charter's own generated files (always valid UTF-8); strict decoding
    # via the shared reader is equivalent here and keeps one definition.
    return ac.read_text(folder, rel)


def _generated_plan(kind: str, request: Dict[str, Any], exam: ac.Examination,
                    settings: Optional[ac.Settings], cs: ps.ContextState) -> Plan:
    plan = Plan(kind=kind, request=request, summary="")
    plan.before = _listing(exam.documents)
    plan.after = plan.before
    if settings is not None and not plan.problems:
        texts = {d.path: exam.texts[d.path] for d in exam.documents}
        generated = ac.render_generated(settings, exam.documents, texts)
        for path in ac.GENERATED:
            old = _read_raw_text(exam.root, path)
            if old != generated[path]:
                plan.changes.append(Change(tx.CONTEXT, path, path, old, generated[path]))
        plan.expected_hashes = dict(
            {d.path: ac.sha256_text(texts[d.path]) for d in exam.documents},
            **{ac.CONTEXT_MAP: ac.sha256_text(generated[ac.CONTEXT_MAP])})
        plan.problems += tx.path_problems(
            cs, [tx.Write(c.root, c.path, c.new) for c in plan.changes])
    return plan


def _finish(plan: Plan, exam: ac.Examination) -> Plan:
    digest = hashlib.sha256()
    digest.update(json.dumps({"kind": plan.kind, "request": plan.request},
                             sort_keys=True).encode("utf-8"))
    digest.update(json.dumps(sorted(exam.hashes.items())).encode("utf-8"))
    digest.update(exam.state.encode("utf-8"))
    for c in plan.changes:
        digest.update(f"\0{c.path}\0{c.old}\0{c.new}".encode("utf-8"))
    for p in plan.problems:
        digest.update(p.encode("utf-8"))
    plan.plan_id = digest.hexdigest()[:20]
    return plan


LAST_KNOWN = "Last known on this computer."
INITIALIZING = ("No settings for this Agent Context are known on this computer, so they are being "
                "initialized: name the project, and confirm or change the default guidance.")


def rebuild_plan(folder: str, project_name: Optional[str] = None,
                 agent_guidance: Optional[Dict[str, Any]] = None,
                 state: Optional[ps.PrivateState] = None) -> Plan:
    """Preview Rebuild Agent Context.

    When `.agent-context.json` is missing or unreadable, its settings are lost.
    The preview then offers the last valid settings known on this computer, or
    the defaults when there are none, and Rebuild applies only with the project
    name and every guidance setting given explicitly by the person: offered
    settings are never reused silently. Otherwise the recorded settings are
    kept, and neither may be given."""
    cs = (state or ps.PrivateState.default()).for_context(folder)
    exam = ac.examine(cs.folder)
    request = {"project_name": project_name, "agent_guidance": agent_guidance}
    settings = exam.settings
    problems: List[str] = []
    notes: List[str] = []
    proposal: Optional[Dict[str, Any]] = None
    enclosing = _enclosing_context(cs.folder)
    if enclosing:
        problems.append(NESTED.format(enclosing=enclosing))
    if tx.interrupted(cs):
        problems.append("A Charter write was interrupted. Open the Agent Context "
                        "to recover it first.")
    for i in exam.rebuild_blockers:
        problems.append(f"{i['path'] or 'The folder'}: {i['message']} {i['fix']}".strip())
    if settings is None:
        last = cs.last_settings()
        proposal = dict(last, source="last-known", label=LAST_KNOWN) if last else {
            "project_name": "", "agent_guidance": ac.default_guidance(),
            "source": "defaults", "label": INITIALIZING}
        if project_name is None or agent_guidance is None:
            problems.append("`.agent-context.json` is missing or unreadable, so its settings are "
                            "lost. Confirm or change the project name and agent guidance "
                            "settings offered here to rebuild.")
        elif not isinstance(agent_guidance, dict) or set(agent_guidance) != set(ac.GUIDANCE_IDS):
            problems.append("Give every agent guidance setting: "
                            + ", ".join(f"`{g}`" for g in ac.GUIDANCE_IDS) + ".")
        else:
            try:
                settings = ac.Settings.make(project_name, agent_guidance)
            except ValueError as exc:
                problems.append(str(exc))
            else:
                offered = {"project_name": proposal["project_name"],
                           "agent_guidance": proposal["agent_guidance"]}
                chosen = {"project_name": settings.project_name,
                          "agent_guidance": settings.guidance_map}
                notes.append(f"Settings: as offered ({proposal['label']}), confirmed by you."
                             if chosen == offered else "Settings: as you chose them.")
    elif project_name is not None or agent_guidance is not None:
        problems.append("Rebuild keeps the settings `.agent-context.json` records. Change them "
                        "in Settings.")
    plan = _generated_plan("rebuild", request, exam, settings if not problems else None, cs)
    plan.problems = problems + plan.problems
    plan.notes = notes
    plan.settings_proposal = proposal
    if not plan.problems and not plan.changes:
        plan.problems.append("The map and metadata already match the governing documents. "
                             "There is nothing to rebuild.")
    plan.summary = ("Rebuild Agent Context: regenerate AGENT-CONTEXT.md and .agent-context.json "
                    "from the governing documents now in the folder.")
    if exam.legacy_map:
        plan.notes.append("The map was generated by Agent Context Manager, Charter's earlier name. "
                          "Rebuild rewrites only AGENT-CONTEXT.md and .agent-context.json, in "
                          "Charter's wording; the governing documents and settings stay as they "
                          "are.")
    outside = observation.outside_since(cs.observed(), exam)
    docs_outside = [p for p in outside if p not in ac.GENERATED]
    plan.notes.append("Rebuild changes no governing document and approves nothing. The governing "
                      "documents stay as they are in the folder"
                      + (", and these, changed outside Charter, stay marked as "
                         "such: " + ", ".join(docs_outside) + "." if docs_outside else "."))
    return _finish(plan, exam)


def settings_plan(folder: str, project_name: Optional[str] = None,
                  agent_guidance: Optional[Dict[str, Any]] = None,
                  state: Optional[ps.PrivateState] = None) -> Plan:
    """Preview a change to the project name or agent guidance settings."""
    cs = (state or ps.PrivateState.default()).for_context(folder)
    exam = ac.examine(cs.folder)
    request = {"project_name": project_name, "agent_guidance": agent_guidance}
    enclosing = _enclosing_context(cs.folder)
    if enclosing:
        raise ActionRefused(NESTED.format(enclosing=enclosing))
    if not exam.valid or exam.settings is None:
        raise ActionRefused("Settings can change only while the Agent Context is valid and clean.")
    current = exam.settings
    guidance = current.guidance_map
    if agent_guidance is not None:
        if not isinstance(agent_guidance, dict):
            raise ActionRefused("The agent guidance settings must be an object.")
        guidance.update(agent_guidance)
    try:
        settings = ac.Settings.make(current.project_name if project_name is None else project_name,
                                    guidance)
    except ValueError as exc:
        raise ActionRefused(str(exc))
    plan = _generated_plan("settings", request, exam, settings, cs)
    if not plan.changes:
        plan.problems.append("Nothing to save: these are already this Agent Context's settings.")
    plan.summary = "Change the Agent Context's settings and regenerate its map and metadata."
    return _finish(plan, exam)


def _apply_generated(folder: str, kind: str, replan, plan_id: str, confirm: Any,
                     state: Optional[ps.PrivateState]) -> Dict[str, Any]:
    cs = (state or ps.PrivateState.default()).for_context(folder)
    with cs.lock("writer") as held:
        if not held:
            raise ActionRefused("Another Charter action on this Agent Context is "
                                "in progress. Try again when it has finished.")
        tx.recover(cs)
        current = replan()
        if current.plan_id != plan_id:
            raise StalePlan("The Agent Context changed after this preview was shown. Review the "
                            "new preview before applying.")
        if current.blocked:
            raise ActionRefused(" ".join(current.problems))
        if confirm is not True:
            raise ActionRefused("Confirm the action to apply it.")
        before = ac.examine(cs.folder)

        def validate() -> None:
            exam = ac.examine(cs.folder)
            if not exam.valid or exam.hashes != current.expected_hashes:
                raise ActionRefused("After writing, the Agent Context was not exactly the "
                                    "planned valid context.")
        # Each file must still hold what the preview was built from: a change
        # made since is refused before anything is replaced.
        transaction = tx.Transaction(cs, [tx.Write(c.root, c.path, c.new, tx.expect(c.old))
                                          for c in current.changes], validate=validate)
        try:
            transaction.run()
        except tx.TransactionError as exc:
            raise ApplyFailed(f"Nothing was changed ({exc.message}).", exc.restored,
                              exc.unrestored)
        after = ac.examine(cs.folder)
        follow_up = list(transaction.follow_up)
        try:
            if kind == "rebuild" and before.legacy_map and cs.observed() is not None \
                    and not observation.outside_since(cs.observed(), before):
                # Only the earlier name's wording was regenerated, over documents
                # this computer saw Charter (or Agent Context Manager) write: not a
                # change made outside Charter.
                observation.record_charter_write(cs, before, after)
            elif kind == "rebuild":
                observation.record_rebuild(cs, before, after)
            else:
                observation.record_charter_write(cs, before, after)
        except Exception:  # noqa: BLE001 — the change is made; only the record failed
            follow_up.append(OBSERVATION_FAILED)
    status = _status(cs.folder, cs, after)
    status["follow_up"] = follow_up
    return status


def rebuild_apply(folder: str, plan_id: str, confirm: Any, project_name: Optional[str] = None,
                  agent_guidance: Optional[Dict[str, Any]] = None,
                  state: Optional[ps.PrivateState] = None) -> Dict[str, Any]:
    """Apply the Rebuild the person previewed, with ordinary confirmation."""
    return _apply_generated(folder, "rebuild",
                            lambda: rebuild_plan(folder, project_name, agent_guidance, state),
                            plan_id, confirm, state)


def settings_apply(folder: str, plan_id: str, confirm: Any, project_name: Optional[str] = None,
                   agent_guidance: Optional[Dict[str, Any]] = None,
                   state: Optional[ps.PrivateState] = None) -> Dict[str, Any]:
    """Apply the settings change the person previewed, with ordinary confirmation."""
    return _apply_generated(folder, "settings",
                            lambda: settings_plan(folder, project_name, agent_guidance, state),
                            plan_id, confirm, state)
