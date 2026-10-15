"""Verification harness: isolated private state for tests. NOT SHIPPED.

This module, `tests/_launch.py` and every other file under `tests/` belong to
the verification bundle only. The end-user release contains no route —
environment variable, configuration, argument, importable helper or test code —
that moves Charter's private state; `app.private_store` finds it
only from the operating system.

Tests isolate it by replacing the operating-system lookup inside their own
process, for the duration of a `with isolated_private_state():` block.
"""
from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from typing import Iterator


@contextlib.contextmanager
def isolated_private_state(root: str = "") -> Iterator[str]:
    """Point this process's Charter private state at a fresh
    private folder."""
    from app import private_store
    owned = not root
    base = root or tempfile.mkdtemp(prefix="charter-state-")
    state_root = os.path.join(base, "state")
    original = private_store._default_root
    private_store._default_root = lambda: state_root  # type: ignore[assignment]
    try:
        yield state_root
    finally:
        private_store._default_root = original  # type: ignore[assignment]
        if owned:
            shutil.rmtree(base, ignore_errors=True)


def seeded(folder: str, start: dict, retain_others: bool = True) -> dict:
    """A new change set prefilled with the one outcome `start` names, every
    other governing document retained as a person would tick it, as the
    request that plans and applies it."""
    from app import changeset as chs
    ctx = chs.Ctx(folder)
    draft = chs.create(ctx, "", start)
    if retain_others:
        draft = chs.update(ctx, draft["id"], draft["revision"], {"retain_others": True})
    return {"draft_id": draft["id"], "draft_revision": draft["revision"]}


def govern(folder: str, start: dict) -> dict:
    """Plan and apply a one-document change set started from `start`, with the
    typed phrase: how governing context changes."""
    from app import authority as au
    request = seeded(folder, start)
    plan = au.plan(folder, "changeset", request)
    return au.apply(folder, "changeset", request, plan.plan_id, au.CONFIRM_PHRASE)
