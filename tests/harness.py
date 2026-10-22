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


def start_of(start: dict) -> dict:
    """A one-document start as the current change-set form takes it. Tests may
    still say what they mean the old way — govern `alongside`, or a governing
    `document` to replace, revise or withdraw — and a revise is a replace."""
    if "alongside" in start:
        return {"candidate": start["alongside"], "decision": "govern-alongside"}
    if "document" in start:
        if start.get("outcome") == "withdraw":
            return {"withdraw": start["document"]}
        return {"candidate": start.get("candidate"), "decision": "replace",
                "target": start["document"]}
    return start


def seeded(folder: str, start: dict) -> dict:
    """A new change set prefilled with the one candidate decision or
    withdrawal `start` names — every other governing document retained, as it
    always is — as the request that plans and applies it."""
    from app import changeset as chs
    ctx = chs.Ctx(folder)
    draft = chs.create(ctx, "", start_of(start))
    return {"draft_id": draft["id"], "draft_revision": draft["revision"]}


def govern(folder: str, start: dict) -> dict:
    """Plan and apply a one-document change set started from `start`, with the
    typed phrase: how governing context changes."""
    from app import authority as au
    request = seeded(folder, start)
    plan = au.plan(folder, "changeset", request)
    return au.apply(folder, "changeset", request, plan.plan_id, au.CONFIRM_PHRASE)


class HeldOpen:
    """A lock-free reader's handle on one file, opened as Charter's readers
    open files: on Windows, without delete sharing, so while it is open the
    file cannot be renamed over or removed. Real filesystem behaviour, ordered
    by events, never by time.

    `open()` takes the handle — from a transaction's fault hook, once the file
    exists. While the context is active, every refusal of `os.replace` or
    `os.remove` because a handle has the file open is counted in `refusals`
    (with its Windows error code); with `release="after-refusal"` the handle
    is closed at the first one — a reader that finishes — so the attempt after
    it can succeed, and with `release="never"` it stays open until the context
    ends — a reader that does not. On other systems an open handle refuses
    nothing, so `refusals` stays empty."""

    def __init__(self, release: str = "after-refusal") -> None:
        assert release in ("after-refusal", "never")
        self.release = release
        self.fd = None
        self.path = ""
        self.refusals = []

    def open(self, path: str) -> None:
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
        os.read(self.fd, 1 << 16)

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def __enter__(self) -> "HeldOpen":
        self._real = {name: getattr(os, name) for name in ("replace", "remove")}

        def watched(name):
            real = self._real[name]

            def op(*args, **kwargs):
                try:
                    return real(*args, **kwargs)
                except OSError as exc:
                    if self.fd is not None and getattr(exc, "winerror", None) in (5, 32, 33):
                        self.refusals.append((name, os.path.basename(str(args[0])), exc.winerror))
                        if self.release == "after-refusal":
                            self.close()
                    raise
            return op
        for name in self._real:
            setattr(os, name, watched(name))
        return self

    def __exit__(self, *exc) -> None:
        for name, real in self._real.items():
            setattr(os, name, real)
        self.close()
