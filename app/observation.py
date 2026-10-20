"""Whether an Agent Context changed outside Charter.

Agent Context as the Project Asset §7 and UI Standards ("Validation, strays,
and recovery"). A valid change made through Git or another ordinary tool
governs for its checkout, but it is not a Charter-approved authority action, and
Charter cannot prove who made it. Charter shows that distinction:

  * it remembers, in private state, the context as it last wrote or saw it;
  * a difference from that record is a change made outside Charter, listed by
    path, until the person acknowledges it, even across a Rebuild Agent
    Context or a later Charter action;
  * with no record on this computer, the origin of the content is unknown.

Nothing here decides validity or whether agents are served; `agent_context`
does that from the folder alone.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from . import agent_context as ac
from .private_store import ContextState


def _changed(old: Dict[str, str], new: Dict[str, str]) -> List[str]:
    return sorted(p for p in set(old) | set(new) if old.get(p) != new.get(p))


def outside_since(record: Optional[Dict[str, Any]], exam: ac.Examination) -> List[str]:
    """Paths changed outside Charter and not yet acknowledged: those the record
    still carries, and those that differ from it now."""
    if record is None:
        return []
    return sorted(set(record.get("outside", [])) | set(_changed(record["sha256"], exam.hashes)))


def remember_settings(cs: ContextState, exam: ac.Examination) -> None:
    """Keep a valid context's settings, to offer if its metadata is lost."""
    if exam.valid and exam.settings is not None:
        cs.remember_settings(exam.settings.project_name, exam.settings.guidance_map)


def record_charter_write(cs: ContextState, before: ac.Examination, after: ac.Examination) -> None:
    """After a Charter authority action, Create or settings change: remember the
    result, carrying forward any outside change not yet acknowledged."""
    carry = outside_since(cs.observed(), before)
    cs.record_observed(after.fingerprint, after.hashes, "charter", carry)
    remember_settings(cs, after)


def record_rebuild(cs: ContextState, before: ac.Examination, after: ac.Examination) -> None:
    """After Rebuild Agent Context: the documents changed outside Charter stay
    marked as such. The generated files are Charter's again."""
    carry = [p for p in outside_since(cs.observed(), before) if p not in ac.GENERATED]
    cs.record_observed(after.fingerprint, after.hashes, "rebuild", carry)
    remember_settings(cs, after)


def acknowledge(cs: ContextState, exam: ac.Examination) -> None:
    """The person has seen the change made outside Charter."""
    if not exam.valid:
        raise ValueError("Only a valid Agent Context can be acknowledged.")
    cs.record_observed(exam.fingerprint, exam.hashes, "seen", [])
    remember_settings(cs, exam)


def status(cs: Optional[ContextState], exam: ac.Examination) -> Dict[str, Any]:
    """What the person is told about where the current content came from."""
    record = cs.observed() if cs is not None else None
    if record is None:
        # No record of the content, though the folder may well be known here,
        # opened in the console or listed in Recent: say which record is missing.
        return {"known": False, "changed_outside": False, "rebuilt": False, "paths": [],
                "message": "Charter has no record on this computer of how this content was "
                           "created or changed, so its origin is unknown."}
    rebuilt = record["source"] == "rebuild" and record["fingerprint"] == exam.fingerprint
    if not exam.valid:
        # "Changed outside Charter" is only the notice for a valid outside
        # change, which is still served (UI Standards). An unavailable context
        # says what does not match instead; the record is kept, unacknowledged,
        # for when the context is valid again.
        return {"known": True, "changed_outside": False, "rebuilt": rebuilt, "paths": [],
                "message": ""}
    paths = outside_since(record, exam)
    # Only documents changed outside Charter, not yet acknowledged, are news. A
    # Rebuild's own map and metadata are Charter's output: a Rebuild that only
    # regenerated them, over documents Charter saw, says nothing.
    changed = bool(paths)
    message = ""
    if changed:
        message = ("This Agent Context changed outside Charter. Its current files "
                   "govern for this checkout, but they were not changed through a Charter "
                   "authority action, and it cannot tell who changed them.")
        if rebuilt:
            message += " Rebuild Agent Context regenerated its map and metadata."
    return {"known": True, "changed_outside": changed, "rebuilt": rebuilt,
            "paths": paths, "message": message}
