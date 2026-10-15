"""`charter compare`: the read-only Git-base comparison, in the terminal.

    charter compare --context <folder> --base <revision>
                    [--prompt | --packet <destination> [--accept-git-warning]] [--json]

Coordinated Context Changes and Advisory Review, "Git comparison and
promotion": an advanced, developer-oriented operation, not part of the
ordinary console. `app.git_compare` makes the comparison; this module only
chooses what to print, and saves a packet where the person says.

By default it prints a summary. `--prompt` prints only the copyable review
prompt, when it fits one message; past that limit, `--packet` saves one
portable review packet at the destination the person names, under the same
rules as a change set's packet. `--json` prints one JSON object instead of
text: the prompt's text only where `--prompt` would print it, never a packet's.

Strictly read-only apart from that packet: nothing is written to the Agent
Context, Git or Charter's private state, and private state is neither adopted
nor created. Exit 0 when a comparison was made, 1 when it could not be made or
the material asked for could not be produced, 2 for an unusable command line.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from . import git_compare as gc
from . import host_state as hs
from . import impact
from . import private_store as ps
from . import review_packet


def secrets(folder: str) -> List[str]:
    """What review material must never hold: this folder, the home folder,
    and where Charter's private state is, or would be. Works the locations
    out; creates nothing. `app.git_compare` adds the Git checkout and every
    other spelling of each."""
    state = ps.PrivateState.default()
    canon = hs.canonical(folder)
    return [folder, os.path.realpath(folder), canon, os.path.expanduser("~"), state.root,
            state.legacy_root, os.path.join(state.root, ps.CONTEXTS, hs.location_key(canon))]


def _counts(s: Dict[str, int]) -> str:
    def n(k: int, one: str, many: str) -> str:
        return f"{k} {one if k == 1 else many}"
    return (f"{n(s['added'], 'document added', 'documents added')}, {s['changed']} changed, "
            f"{s['removed']} removed, {s['unchanged']} unchanged")


def summary(result: Dict[str, Any]) -> List[str]:
    """The person-facing report of a comparison, or of why there is none."""
    if not result["available"]:
        lines = ["No comparison was made.", "", result["reason"]]
        current = result.get("current_problems") or []
        if current:
            # As `charter check` lists them.
            lines += ["", "Problems:"]
            for i in current:
                lines.append(f"  - {i['path'] or 'the folder'}: {i['message']}")
                if i.get("fix"):
                    lines.append(f"    {i['fix']}")
        problems = result.get("base_problems") or []
        if problems:
            lines += ["", "At that base:"] + [f"  - {p}" for p in problems]
        return lines
    base = result["base"]
    lines = [f"Agent Context: {result['project']}", f"Base:          {base}", ""]
    if result["same"]:
        lines.append(f"At “{base}”, the governing context is the same as now.")
    else:
        lines.append(f"Since “{base}”: {_counts(result['summary'])}.")
        for row in result["rows"]:
            if row["change"] == "unchanged":
                continue
            lines.append(f"  {row['change']:<8} {row['path']} — {row['title']}")
            if row["scope"]:
                lines.append(f"           Scope: {row['scope']}")
            if row["change"] == "changed" and row["base_scope"] != row["scope"]:
                lines.append(f"           Scope at the base: {row['base_scope'] or '(none)'}")
        if result["settings_changed"]:
            lines.append("The project name or agent guidance in the context map changed.")
    lines += ["", result["advisory"], result["read_only"], "", *material_lines(result)]
    return lines


def material_lines(result: Dict[str, Any]) -> List[str]:
    p = result["review_prompt"]
    if not p.get("ready"):
        return [p.get("reason") or "There is no review material."]
    if not p["over_limit"]:
        return [f"Review material: a review prompt of {p['size_chars']:,} characters, about "
                f"{p['approx_tokens']:,} tokens, that fits in one message. Print it with --prompt."]
    return [f"Review material: {p['size_chars']:,} characters, past the practical single-message "
            f"limit of {p['limit']:,}. Save it as one review packet with --packet <file or folder>, "
            "outside every Agent Context and Charter's private state."]


def _as_json(result: Dict[str, Any], prompt_text: bool) -> Dict[str, Any]:
    out = dict(result)
    if isinstance(out.get("review_prompt"), dict):
        material = dict(out["review_prompt"])
        if not prompt_text:
            material.pop("text", None)
        out["review_prompt"] = material
    return out


class _Refused(Exception):
    """The material asked for cannot be produced, in words for the person."""


def _prompt(folder: str, result: Dict[str, Any], hidden: List[str]) -> Dict[str, Any]:
    p = result["review_prompt"]
    if not p.get("ready"):
        raise _Refused(p.get("reason") or "There is no review material.")
    if p["over_limit"]:
        raise _Refused(material_lines(result)[0] + " No prompt was printed.")
    return gc.recheck(folder, result["base"], result["comparison_fingerprint"], hidden)


def _packet(folder: str, result: Dict[str, Any], hidden: List[str], where: str,
            accept_warning: bool) -> Dict[str, Any]:
    p = result["review_prompt"]
    if not p.get("ready"):
        raise _Refused(p.get("reason") or "There is no review material.")
    if not p["over_limit"]:
        raise _Refused("This review fits in one message: print it with --prompt instead. "
                       "Nothing was saved.")
    try:
        dest = review_packet.destination(folder, os.path.abspath(os.path.expanduser(where)),
                                         p["file_name"], contents=gc.PACKET_CONTENTS)
    except review_packet.PacketDestinationError as exc:
        raise _Refused(str(exc))
    if dest.warning and not accept_warning:
        raise _Refused(f"{dest.warning} Nothing was saved. To save it there anyway, run the same "
                       "command with --accept-git-warning.")
    # The file name goes to the agent with the request, so a name the person
    # chose is checked with the documents, in the comparison made again now.
    now = gc.recheck(folder, result["base"], result["comparison_fingerprint"], hidden,
                     extra=[("the packet's file name", dest.name)])
    try:
        # The destination is checked again immediately before the write, and
        # the write never replaces a file.
        name = review_packet.write(dest, now["review_prompt"]["text"])
    except review_packet.PacketDestinationError as exc:
        raise _Refused(str(exc))
    # Everything said about the packet names the file as saved, which a taken
    # name or the person's own name makes different from the suggested one.
    return {"name": name, "folder": dest.folder, "path": os.path.join(dest.folder, name),
            "renamed": name != dest.name, "warning": dest.warning,
            "size_bytes": now["review_prompt"]["size_bytes"],
            "request": impact.packet_request(name, result["comparison_fingerprint"])}


def _why(exc: BaseException) -> str:
    """A refusal in words for the person: Charter's own, or, for a failure
    reading or writing, the system's reason without a location."""
    if isinstance(exc, (_Refused, gc.CompareError, review_packet.PacketDestinationError)):
        return str(exc)
    return ("The review material could not be produced" + gc._cause(exc)
            + ". Nothing was printed or saved.")


def _print(args: argparse.Namespace, result: Dict[str, Any], **extra: Any) -> None:
    if args.json:
        print(json.dumps(dict(_as_json(result, False), **extra), ensure_ascii=False, indent=2))
    else:
        print("\n".join(summary(result)))


def run(args: argparse.Namespace) -> int:
    folder = os.path.abspath(os.path.expanduser(args.context))
    try:
        hidden = secrets(folder)
    except gc._UNREADABLE as exc:
        _print(args, gc._refused("Charter could not work out where its private state is"
                                 + gc._cause(exc) + ", so no comparison was made. Nothing was "
                                 "changed."))
        return 1
    result = gc.compare(folder, args.base, hidden)
    if not result["available"]:
        _print(args, result)
        return 1
    try:
        if args.prompt:
            now = _prompt(folder, result, hidden)
            if args.json:
                print(json.dumps(dict(_as_json(now, True), disclosure=gc.DISCLOSURE),
                                 ensure_ascii=False, indent=2))
            else:
                # Only the prompt goes to standard output, so it can be piped
                # or copied whole; the disclosure warning goes beside it.
                print(gc.DISCLOSURE, file=sys.stderr)
                sys.stdout.write(now["review_prompt"]["text"])
            return 0
        if args.packet is not None:
            saved = _packet(folder, result, hidden, args.packet, args.accept_git_warning)
            if args.json:
                out = _as_json(result, False)
                out["review_prompt"].update(file_name=saved["name"], request=saved["request"])
                print(json.dumps(dict(out, packet=saved, disclosure=gc.DISCLOSURE),
                                 ensure_ascii=False, indent=2))
            else:
                lines = summary(result)[:-1]
                lines += [f"Saved the review packet “{saved['name']}”"
                          + (" — a file with that name was already there, so nothing was replaced"
                             if saved["renamed"] else "") + ":", f"  {saved['path']}"]
                if saved["warning"]:
                    lines.append(saved["warning"])
                lines += [gc.DISCLOSURE, "", "Attach it to the agent you choose, with this request:",
                          "", saved["request"]]
                print("\n".join(lines))
            return 0
    except (_Refused, *gc._UNREADABLE) as exc:
        if args.json:
            print(json.dumps(dict(_as_json(result, False), refused=_why(exc)),
                             ensure_ascii=False, indent=2))
        else:
            print("\n".join(summary(result)[:-1] + [_why(exc)]))
        return 1
    _print(args, result)
    return 0


def add_parser(sub: Any) -> None:
    c = sub.add_parser(
        "compare", help="compare this Agent Context with its folder at a Git base you name, and "
                        "prepare advisory review material; reads Git only, changes nothing",
        description="Compare the Agent Context with its folder at a Git branch, tag or commit you "
                    "name, already in this checkout's history. Advisory review input only: it "
                    "reads Git, never fetches or changes it, and establishes no authority.")
    c.add_argument("--context", required=True, metavar="FOLDER",
                   help="the Agent Context folder; `.` is the current folder")
    c.add_argument("--base", required=True, metavar="REVISION",
                   help="the branch, tag or commit to compare with")
    what = c.add_mutually_exclusive_group()
    what.add_argument("--prompt", action="store_true",
                      help="print only the review prompt, when it fits one message")
    what.add_argument("--packet", metavar="DESTINATION",
                      help="save one review packet, when the review is past the single-message "
                           "limit, to this file or existing folder outside every Agent Context")
    c.add_argument("--accept-git-warning", action="store_true",
                   help="with --packet: save there even though the folder is inside a Git repository")
    c.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    c.set_defaults(func=_checked(c))


def _checked(parser: argparse.ArgumentParser):
    def func(args: argparse.Namespace) -> int:
        if args.accept_git_warning and args.packet is None:
            parser.error("--accept-git-warning applies only with --packet")
        return run(args)
    return func
