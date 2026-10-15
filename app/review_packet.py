"""Where a portable review packet may be saved, and saving it.

Coordinated Context Changes and Advisory Review. A packet is one UTF-8
Markdown file, written only to a destination the person chooses, outside
every Agent Context and outside Charter's private state. It is
never committed, served through MCP, kept with a change-set draft, or removed
later: once saved, it is the person's file. Saving it contacts no service.

A packet is never overwritten. When the chosen name is taken, the packet is
saved under the first free name with a numbered suffix. A destination inside
some Git repository is allowed, with a warning, since committing the packet
there would carry what it includes into that repository's history.

The destination is checked when it is chosen and again immediately before the
packet is written: if the folder has since become, or been replaced by, an
Agent Context, private state, another location, or a Git repository the
person was not warned about, nothing is written.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Tuple

from . import agent_context as ac
from . import host_state as hs_mod
from . import private_store as ps

# What a change set's packet carries. A Git-base comparison's packet names
# its own contents (`git_compare.PACKET_CONTENTS`), so the warning is accurate.
CONTENTS = "the candidate content and governing documents the packet includes"


def git_warning(contents: str = CONTENTS) -> str:
    return ("This folder is inside a Git repository. Charter will not commit the packet, but if "
            f"that repository's changes are committed, {contents} go into its history.")


GIT_WARNING = git_warning()

_MAX_SUFFIX = 1000


class PacketDestinationError(ValueError):
    """A destination the packet may not be saved to, in words for the person."""


@dataclass(frozen=True)
class Destination:
    folder: str  # canonical
    name: str    # the name chosen, before any suffix
    warning: str
    # What the destination was checked for, so it can be checked again just
    # before the write. A Destination made without them is not rechecked.
    context: str = ""
    contents: str = CONTENTS
    state: Any = field(default=None, compare=False, repr=False)


def _forbidden(folder: str, state: ps.PrivateState) -> List[Tuple[str, str]]:
    """Every location a packet may not be inside, contain or overlap."""
    out: List[Tuple[str, str]] = [(folder, "this Agent Context")]
    out += [(f, "an Agent Context") for f in state.known_contexts() if _known_context(f, state)]
    out.append((state.root, "Charter's private state"))
    out.append((state.legacy_root, "the private state of Agent Context Manager, Charter's "
                                   "earlier name"))
    return out


def _known_context(folder: str, state: ps.PrivateState) -> bool:
    """Whether a folder this computer has private state for is an Agent
    Context. Opening any existing folder records it, so a folder recorded only
    because it was opened, which holds no Agent Context files and nothing in
    private state beyond that record, is not one. Anything uncertain is one."""
    if any(os.path.lexists(os.path.join(folder, n)) for n in ac.GENERATED + (ac.AUTHORITATIVE,)):
        return True
    cs = state.find_context(folder)
    return cs is None or cs.holds_records()


def _context_above(folder: str) -> bool:
    """Whether `folder`, or any folder above it, holds an Agent Context's
    generated files."""
    return bool(ac.enclosing_context(folder, include_self=True))


def destination(folder: str, path: str, suggested: str,
                state: "ps.PrivateState" = None, contents: str = CONTENTS) -> Destination:
    """Check the person's chosen file path, or a folder, for the packet named
    `suggested`, for the Agent Context at `folder`. Writes nothing.
    `contents` says what the packet carries, for the Git-repository warning."""
    state = state or ps.PrivateState.default()
    if not isinstance(path, str) or not path.strip():
        raise PacketDestinationError("Choose where to save the review packet.")
    path = os.path.expanduser(path.strip())
    if not os.path.isabs(path):
        raise PacketDestinationError("Give the full path where the review packet should be saved.")
    if os.path.isdir(path):
        where, name = path, suggested
    else:
        where, name = os.path.split(path)
        if not name.casefold().endswith(".md"):
            name += ".md"
    if not os.path.isdir(where):
        raise PacketDestinationError("That folder does not exist. Choose an existing folder.")
    if name.strip(" .") == "" or any(c in name for c in '<>:"/\\|?*\0'):
        raise PacketDestinationError("That file name cannot be used. Choose another name.")
    canon = hs_mod.canonical(where)
    for root, what in _forbidden(folder, state):
        if root and hs_mod.overlaps(canon, root):
            raise PacketDestinationError(
                f"The review packet cannot be saved there: that folder is inside, contains or is "
                f"{what}. Choose a folder outside every Agent Context and Charter's "
                "private state. Nothing was saved.")
    if _context_above(canon):
        raise PacketDestinationError(
            "The review packet cannot be saved there: that folder is, or is inside, an Agent "
            "Context. Choose another folder. Nothing was saved.")
    warning = git_warning(contents) if hs_mod.in_git_worktree(canon) else ""
    return Destination(folder=canon, name=name, warning=warning, context=folder,
                       contents=contents, state=state)


def revalidate(dest: Destination) -> None:
    """Check the destination again, immediately before writing: refused if
    the folder is gone, now leads somewhere else, has become or is now inside
    an Agent Context or private state, or is now inside a Git repository the
    person was not warned about. Writes nothing."""
    if not dest.context:
        return
    if not os.path.isdir(dest.folder):
        raise PacketDestinationError("The destination changed before the packet was written: that "
                                     "folder does not exist any more. Nothing was saved.")
    try:
        again = destination(dest.context, dest.folder, dest.name, dest.state, dest.contents)
    except PacketDestinationError as exc:
        raise PacketDestinationError("The destination changed before the packet was written. "
                                     + str(exc)) from None
    if os.path.normcase(again.folder) != os.path.normcase(dest.folder):
        raise PacketDestinationError("The destination changed before the packet was written: that "
                                     "folder now leads somewhere else. Nothing was saved.")
    if again.warning and not dest.warning:
        raise PacketDestinationError("The destination changed before the packet was written: that "
                                     "folder is now inside a Git repository. Nothing was saved.")


def _numbered(name: str, n: int) -> str:
    stem, ext = os.path.splitext(name)
    return name if n == 1 else f"{stem} ({n}){ext}"


def _place(tmp: str, target: str, data: bytes) -> None:
    """Move `tmp` to `target` only if nothing is there: never replace a file."""
    if os.name == "nt":
        os.rename(tmp, target)  # refuses an existing target
        return
    try:
        os.link(tmp, target)  # refuses an existing target
    except FileExistsError:
        raise
    except OSError:
        # No hard links here (some network or FAT volumes): create the target
        # exclusively instead, so a file that appeared meanwhile is never
        # replaced. Only a file this call created is removed on failure.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                     0o644)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
        except OSError:
            _discard(target)
            raise
    os.remove(tmp)


def write(dest: Destination, text: str) -> str:
    """Save the packet as UTF-8 without a BOM, with LF line endings, under the
    first free name. Returns the name it was saved under. Removes only its own
    unfinished temporary file, never anything else."""
    data = text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    for n in range(1, _MAX_SUFFIX + 1):
        name = _numbered(dest.name, n)
        target = os.path.join(dest.folder, name)
        if os.path.lexists(target):
            continue
        tmp = os.path.join(dest.folder, f".{name}.{uuid.uuid4().hex[:8]}.partial")
        created = False
        try:
            # Immediately before anything is written there.
            revalidate(dest)
            with open(tmp, "xb") as fh:
                created = True
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            _place(tmp, target, data)
        except FileExistsError:
            if created:
                _discard(tmp)
            continue
        except OSError as exc:
            if created:
                _discard(tmp)
            raise PacketDestinationError(f"The review packet could not be saved there "
                                         f"({exc.strerror or exc}). Nothing was saved.")
        return name
    raise PacketDestinationError("Every name for the review packet is taken in that folder. "
                                 "Choose another name or folder.")


def _discard(tmp: str) -> None:
    try:
        os.remove(tmp)
    except OSError:
        pass
