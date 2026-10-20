"""The Agent Context format and validator. Run: python -m tests.agent_context

Agent Context as the Project Asset §2, §6, §7 and the Product Specification
§3.3:

  * a valid Agent Context is exactly `AGENT-CONTEXT.md`, `.agent-context.json`
    and `authoritative/`, plus the tolerated tooling files;
  * an empty context is valid, with or without `authoritative/`;
  * every other file or folder is a stray: the context is unclean, the stray is
    named and left untouched;
  * the map and metadata are the only record of what governs: a recorded file
    that changed, is missing or cannot be read, an unrecorded document, a map
    whose own hash fails, and a map and metadata that disagree all need
    review, and Rebuild clears none of them; only a map whose own hash is the
    sole failure may be regenerated;
  * with no usable map, no document governs, whatever its front matter says;
  * the metadata holds only versions, project name, guidance and hashes;
  * examining a folder never writes to it.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app.docs import render_front_matter  # noqa: E402

OK = "ok"


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def doc_text(doc_id: str, title: str, scope: str = "A scope.", body: str = "Body.\n",
             authority: str = "authoritative", status: str = "active") -> str:
    meta = {"id": doc_id, "title": title, "status": status, "authority": authority,
            "scope": scope, "created": "2026-10-06", "updated": "2026-10-06"}
    return render_front_matter(meta) + "\n" + body


def write(root: str, rel: str, data, newline: str = "\n") -> None:
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if isinstance(data, str):
        data = data.replace("\n", newline).encode("utf-8")
    with open(path, "wb") as fh:
        fh.write(data)


def read(root: str, rel: str) -> bytes:
    with open(os.path.join(root, *rel.split("/")), "rb") as fh:
        return fh.read()


def with_map_format(root: str, version: int) -> None:
    """Rewrite a valid context's map and metadata as a Charter generating
    map-format `version` would have: an older supported version's own wording,
    or the current map for a newer one (whose wording this Charter cannot
    know). The metadata records that version and hashes consistent with the
    files, as that Charter would have written them."""
    exam = ac.examine(root)
    text = ac.render_map_version(exam.settings, exam.documents, version) \
        if version in ac.OLDER_MAP_FORMATS else ac.render_map(exam.settings, exam.documents)
    hashes = dict(exam.hashes, **{ac.CONTEXT_MAP: ac.sha256_text(text)})
    meta = json.loads(ac.render_metadata(exam.settings, hashes))
    meta["map_format_version"] = version
    write(root, ac.CONTEXT_MAP, text)
    write(root, ac.METADATA, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")


def generate(root: str, project: str = "Test project", guidance=None) -> None:
    """Write the map and metadata for the documents now in `authoritative/`, as
    Rebuild Agent Context will."""
    settings = ac.Settings.make(project, guidance)
    docs, texts = [], {}
    base = os.path.join(root, ac.AUTHORITATIVE)
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            if not name.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root).replace("\\", "/")
            text = read(root, rel).decode("utf-8").replace("\r\n", "\n")
            from app.docs import parse_document
            docs.append(parse_document(rel, text))
            texts[rel] = text
    for rel, text in ac.render_generated(settings, docs, texts).items():
        write(root, rel, text)


def context(docs=(("a.md", "Alpha"), ("b.md", "Beta")), **kwargs) -> str:
    root = tempfile.mkdtemp(prefix="charter-context-")
    for name, title in docs:
        write(root, f"authoritative/{name}", doc_text(name[:-3], title))
    generate(root, **kwargs)
    return root


def snapshot(root: str) -> dict:
    out = {}
    for dirpath, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(dirpath, name)
            out[os.path.relpath(path, root)] = read(root, os.path.relpath(path, root)) \
                if os.path.isfile(path) else None
    return out


def kinds(exam: ac.Examination) -> set:
    return {(i["kind"], i["path"]) for i in exam.errors}


def case_valid_contexts() -> None:
    print("\nvalid Agent Contexts")
    root = context()
    exam = ac.examine(root)
    check(exam.valid and not exam.errors, "a generated context with two governing documents is valid")
    check([d.path for d in exam.documents] == ["authoritative/a.md", "authoritative/b.md"],
          "and its governing documents are the ones under `authoritative/`")
    meta = json.loads(read(root, ac.METADATA))
    check(meta["sha256"] == exam.hashes and set(meta["sha256"]) ==
          {"AGENT-CONTEXT.md", "authoritative/a.md", "authoritative/b.md"},
          "the metadata records the hash of the map and of each governing document")
    check(exam.fingerprint == ac.context_fingerprint(meta["sha256"]) and len(exam.fingerprint) == 64,
          "the context fingerprint is computed from those hashes")
    shutil.rmtree(root)

    empty = context(docs=())
    check(not os.path.exists(os.path.join(empty, "authoritative")) and ac.examine(empty).valid,
          "an empty context is valid without `authoritative/`, as after a Git clone")
    os.mkdir(os.path.join(empty, "authoritative"))
    check(ac.examine(empty).valid, "and with an empty `authoritative/`")
    check("_None._" in read(empty, ac.CONTEXT_MAP).decode(), "its map lists no governing document")
    shutil.rmtree(empty)

    nested = context(docs=())
    write(nested, "authoritative/area/c.md", doc_text("c", "Gamma"))
    generate(nested)
    check(ac.examine(nested).valid, "a governing document may sit in a subfolder of `authoritative/`")
    shutil.rmtree(nested)


def case_line_endings() -> None:
    print("\nline endings")
    root = context()
    before = ac.examine(root).fingerprint
    for rel in ("AGENT-CONTEXT.md", ".agent-context.json", "authoritative/a.md",
                "authoritative/b.md"):
        write(root, rel, read(root, rel).decode("utf-8"), newline="\r\n")
    exam = ac.examine(root)
    check(exam.valid and exam.fingerprint == before,
          "a checkout with CRLF line endings is still valid, with the same fingerprint")
    shutil.rmtree(root)


def case_tolerated_files() -> None:
    print("\ntolerated tooling files")
    root = context()
    os.mkdir(os.path.join(root, ".git"))
    write(root, ".git/config", "[core]\n")
    for rel in (".gitignore", ".gitattributes", ".DS_Store", "Thumbs.db", "desktop.ini",
                "authoritative/.DS_Store", "authoritative/thumbs.db", "authoritative/Desktop.ini",
                "authoritative/.gitattributes"):
        write(root, rel, b"x")
    check(ac.examine(root).valid, "a `.git` folder, Git files and system files are tolerated")
    shutil.rmtree(os.path.join(root, ".git"))
    write(root, ".git", "gitdir: elsewhere\n")
    check(ac.examine(root).valid, "and so is a worktree's `.git` file")
    shutil.rmtree(root)


def case_strays() -> None:
    print("\nstrays")
    for rel, label, reported in (
            ("notes.txt", "a file at the root", "notes.txt"),
            ("README.md", "a README at the root", "README.md"),
            ("AGENTS.md", "an agent instruction file", "AGENTS.md"),
            (".cgu-surface.json", "a CGU surface manifest", ".cgu-surface.json"),
            ("drafts/x.md", "a folder at the root", "drafts/"),
            ("authoritative/.gitkeep", "a `.gitkeep`", "authoritative/.gitkeep"),
            ("authoritative/diagram.png", "a file that is not Markdown", "authoritative/diagram.png"),
            ("authoritative/loose.md", "Markdown without governance front matter",
             "authoritative/loose.md")):
        root = context()
        write(root, rel, b"# loose\n")
        before = snapshot(root)
        exam = ac.examine(root)
        check(exam.state == ac.UNCLEAN and exam.strays == [reported] and not exam.fingerprint,
              f"{label} is a stray: the context is unclean and it is named")
        check(snapshot(root) == before, "  and nothing in the folder changed")
        shutil.rmtree(root)
    root = context()
    os.makedirs(os.path.join(root, "authoritative", "empty"))
    check(ac.examine(root).strays == ["authoritative/empty/"],
          "an empty subfolder of `authoritative/` is a stray")
    write(root, "authoritative/empty/.DS_Store", b"x")
    write(root, "authoritative/empty/deeper/Thumbs.db", b"x")
    check(ac.examine(root).valid,
          "a subfolder holding only tolerated tooling files is incidental and valid")
    write(root, "authoritative/empty/notes.txt", b"x")
    check(ac.examine(root).strays == ["authoritative/empty/notes.txt"],
          "but any other file in it is still a stray")
    shutil.rmtree(root)


def case_invalid_front_matter() -> None:
    print("\nan unmapped document is not in the approved context, whatever its front matter")
    root = context()
    write(root, "authoritative/draft.md",
          "---\ntitle: Draft\nstatus: draft\nauthority: authoritative\n---\n\n# Draft\n")
    exam = ac.examine(root)
    found = [i for i in exam.errors if i["path"] == "authoritative/draft.md"]
    check(exam.state == ac.INVALID and not exam.strays and len(found) == 1
          and found[0]["kind"] == ac.INTEGRITY and found[0]["state"] == ac.UNRECORDED
          and found[0]["label"] == "Not in approved context",
          "governance front matter without `id`: one chip, Not in approved context")
    check("cannot govern" not in found[0]["message"] and "invalid" not in found[0]["message"].lower(),
          "  and it is never called invalid: its shape is not what is wrong")
    os.remove(os.path.join(root, "authoritative", "draft.md"))
    write(root, "authoritative/open.md", "---\nid: open\ntitle: Open\n\n# Never closed\n")
    exam = ac.examine(root)
    message = next((i["message"] for i in exam.errors if i["path"] == "authoritative/open.md"), "")
    check(exam.state == ac.INVALID and not exam.strays and "never closes" in message,
          "a front-matter block that is never closed is named as malformed")
    os.remove(os.path.join(root, "authoritative", "open.md"))
    write(root, "authoritative/page.md", "---\nlayout: page\ntitle: Page\n---\n\n# Page\n")
    exam = ac.examine(root)
    check(exam.strays == ["authoritative/page.md"]
          and any("no governance front matter" in i["message"] for i in exam.errors),
          "front matter with no governance field is still Markdown without governance front matter")
    shutil.rmtree(root)


def attention(exam: ac.Examination) -> dict:
    """Each file that needs review, by path, with its observed state."""
    return {i["path"]: i["state"] for i in exam.integrity}


def rebuildable(exam: ac.Examination) -> bool:
    """Whether the console would offer Rebuild Agent Context."""
    return any(i["kind"] == ac.GENERATED_KIND for i in exam.errors) and not exam.rebuild_blockers


def needs_review(exam: ac.Examination, expected: dict, label: str) -> None:
    check(exam.state == ac.INVALID and exam.needs_review and attention(exam) == expected
          and not rebuildable(exam) and not exam.map_regenerable and not exam.fingerprint,
          f"{label}: context changes need review, and neither Rebuild nor Regenerate map is offered")


def case_context_changes_need_review() -> None:
    print("\ncontext changes need review: each kind of mismatch fails closed")
    root = context()
    before = snapshot(root)
    recorded = json.loads(read(root, ac.METADATA))["sha256"]
    write(root, "authoritative/a.md", doc_text("a", "Alpha", body="Edited.\n"))
    exam = ac.examine(root)
    needs_review(exam, {"authoritative/a.md": ac.CHANGED}, "a governing document whose text changed")
    row = exam.integrity[0]
    check(row["label"] == "Does not match approved context"
          and row["recorded_sha256"] == recorded["authoritative/a.md"]
          and row["current_sha256"] == ac.sha256_text(read(root, "authoritative/a.md").decode()),
          "  it does not match the approved context, with its recorded and current hashes")
    words = (row["message"] + " " + row["fix"]).lower()
    check(not any(w in words for w in ("outside charter", "edited by", "changed by", "someone",
                                       "agent changed", "modified", "mtime", "modification")),
          "  and nothing says who or what changed it, or when")
    check("authoritative/a.md" in {d.path for d in exam.documents},
          "  it stays readable for Revise, which files its current text as a candidate")
    write(root, "authoritative/a.md", before["authoritative" + os.sep + "a.md"])
    check(ac.examine(root).valid, "restoring the approved text makes the context valid again")

    os.remove(os.path.join(root, "authoritative", "b.md"))
    exam = ac.examine(root)
    needs_review(exam, {"authoritative/b.md": ac.MISSING}, "a recorded document missing from disk")
    check(exam.integrity[0]["label"] == "Missing from context"
          and exam.integrity[0]["recorded_sha256"] == recorded["authoritative/b.md"]
          and "withdraw it through a change set once the Agent Context is valid again"
          in exam.integrity[0]["fix"],
          "  a synthetic row for the missing path: restore it, then withdraw it if intended")
    write(root, "authoritative/b.md", before["authoritative" + os.sep + "b.md"])

    write(root, "authoritative/c.md", doc_text("c", "Gamma"))
    exam = ac.examine(root)
    needs_review(exam, {"authoritative/c.md": ac.UNRECORDED}, "a valid document the map does not list")
    check(exam.integrity[0]["label"] == "Not in approved context"
          and "invalid" not in exam.integrity[0]["message"].lower()
          and "authoritative/c.md" not in {d.path for d in exam.documents},
          "  not in the approved context, never called invalid, and never governing")
    os.remove(os.path.join(root, "authoritative", "c.md"))

    write(root, "authoritative/a.md", b"---\nid: a\n\xff\n---\n")
    exam = ac.examine(root)
    needs_review(exam, {"authoritative/a.md": ac.UNVERIFIABLE}, "a recorded file that cannot be read")
    check(exam.integrity[0]["label"] == "Cannot verify file" and not exam.integrity[0]["current_sha256"],
          "  Cannot verify file, without claiming its text changed")
    write(root, "authoritative/a.md", "﻿" + before["authoritative" + os.sep + "a.md"].decode())
    needs_review(ac.examine(root), {"authoritative/a.md": ac.CHANGED},
                 "a recorded document saved with a byte-order mark")
    write(root, "authoritative/a.md", doc_text("a", "Alpha", body="<<<<<<< ours\nx\n=======\ny\n>>>>>>> theirs\n"))
    needs_review(ac.examine(root), {"authoritative/a.md": ac.CHANGED},
                 "a recorded document left with merge-conflict markers")
    write(root, "authoritative/a.md", before["authoritative" + os.sep + "a.md"])

    meta = json.loads(read(root, ac.METADATA))
    meta["sha256"]["authoritative/b.md"] = "0" * 64
    write(root, ac.METADATA, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    needs_review(ac.examine(root), {"authoritative/b.md": ac.CHANGED},
                 "a recorded hash changed in the metadata")
    write(root, ac.METADATA, before[ac.METADATA])

    write(root, "authoritative/c.md", doc_text("c", "Gamma"))
    meta = json.loads(read(root, ac.METADATA))
    meta["sha256"]["authoritative/c.md"] = ac.sha256_text(doc_text("c", "Gamma"))
    write(root, ac.METADATA, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    needs_review(ac.examine(root), {ac.METADATA: ac.CHANGED},
                 "metadata that records a document the map does not list")
    write(root, ac.METADATA, before[ac.METADATA])
    os.remove(os.path.join(root, "authoritative", "c.md"))

    meta = json.loads(read(root, ac.METADATA))
    del meta["sha256"][ac.CONTEXT_MAP]
    write(root, ac.METADATA, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    needs_review(ac.examine(root), {ac.METADATA: ac.CHANGED}, "metadata that records no hash for the map")
    write(root, ac.METADATA, before[ac.METADATA])

    check(ac.examine(root).valid, "with every file restored, the context is valid")
    check(snapshot(root) == before, "and examining never wrote anything")
    shutil.rmtree(root)

    print("\nRegenerate map: only for a map whose own hash is the sole failure")
    root = context()
    text = read(root, ac.CONTEXT_MAP).decode()
    write(root, ac.CONTEXT_MAP, text + "\nA note added by hand.\n")
    exam = ac.examine(root)
    check(exam.needs_review and attention(exam) == {ac.CONTEXT_MAP: ac.CHANGED}
          and exam.map_regenerable and not rebuildable(exam),
          "a map edited by hand, still listing the recorded documents, which all match: regenerable")
    check(ac.restored_map(exam) == text and ac.sha256_text(ac.restored_map(exam)) == exam.recorded_map_sha256
          == json.loads(read(root, ac.METADATA))["sha256"][ac.CONTEXT_MAP],
          "  the restored map is the approved one, byte for byte, with exactly the recorded hash")
    meta_text = read(root, ac.METADATA)
    meta = json.loads(meta_text)
    meta["agent_guidance"]["review_newly_discovered_material"] = True
    write(root, ac.METADATA, json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
    exam = ac.examine(root)
    check(exam.needs_review and ac.restored_map(exam) is None and not exam.map_regenerable,
          "  but when the recorded settings no longer produce the recorded hash, nothing can be "
          "restored, and it is not regenerable")
    write(root, ac.METADATA, meta_text)
    exam = ac.examine(root)
    for rel, t in ac.render_generated(exam.settings, exam.documents, exam.texts).items():
        write(root, rel, t)
    check(ac.examine(root).valid, "regenerated from the recorded documents, it is valid again")
    for label, edit in (
            ("drops a listed document",
             lambda t: t.replace("| [Beta](authoritative/b.md) | A scope. | `authoritative/b.md` |\n", "")),
            ("adds an unrecorded document",
             lambda t: t.replace("| [Beta](authoritative/b.md) | A scope. | `authoritative/b.md` |\n",
                                 "| [Beta](authoritative/b.md) | A scope. | `authoritative/b.md` |\n"
                                 "| [Gamma](authoritative/c.md) | A scope. | `authoritative/c.md` |\n")),
            ("has no readable listing", lambda t: t.replace("## Current governing documents", "## Other"))):
        write(root, ac.CONTEXT_MAP, edit(text))
        exam = ac.examine(root)
        check(exam.needs_review and not exam.map_regenerable and not rebuildable(exam)
              and attention(exam).get(ac.METADATA) == ac.CHANGED,
              f"a map that {label} does not list what the metadata records: not regenerable")
    write(root, ac.CONTEXT_MAP, text + "\nA note.\n")
    write(root, "authoritative/a.md", doc_text("a", "Alpha", body="Edited.\n"))
    check(not ac.examine(root).map_regenerable, "nor when a document also does not match")
    write(root, "authoritative/a.md", doc_text("a", "Alpha"))
    write(root, "authoritative/c.md", doc_text("c", "Gamma"))
    check(not ac.examine(root).map_regenerable, "nor when an unrecorded document is present")
    os.remove(os.path.join(root, "authoritative", "c.md"))
    os.remove(os.path.join(root, "authoritative", "b.md"))
    check(not ac.examine(root).map_regenerable, "nor when a recorded document is missing")
    shutil.rmtree(root)

    print("\nno usable map: no document governs, whatever its front matter")
    for label, damage in (
            ("no metadata", lambda r: os.remove(os.path.join(r, ac.METADATA))),
            ("no map", lambda r: os.remove(os.path.join(r, ac.CONTEXT_MAP))),
            ("neither file", lambda r: [os.remove(os.path.join(r, n)) for n in ac.GENERATED]),
            ("unusable metadata", lambda r: write(r, ac.METADATA, "{not json")),
            ("a map with merge-conflict markers",
             lambda r: write(r, ac.CONTEXT_MAP, "<<<<<<< ours\n" + read(r, ac.CONTEXT_MAP).decode()
                             + ">>>>>>> theirs\n"))):
        root = context()
        damage(root)
        exam = ac.examine(root)
        check(exam.no_record and exam.record_mode == ac.NO_RECORD and not exam.documents
              and attention(exam) == {"authoritative/a.md": ac.UNRECORDED,
                                      "authoritative/b.md": ac.UNRECORDED}
              and not rebuildable(exam) and not exam.map_regenerable,
              f"{label}: each document is not in an approved context, and no Rebuild is offered")
        generated = [i for i in exam.errors if i["kind"] == ac.GENERATED_KIND]
        check(generated and all(i["fix"] == ac.NO_RECORD_FIX and "Use Rebuild" not in i["fix"]
                                for i in generated),
              "  and the missing or unusable generated file says to restore it, never to rebuild it")
        shutil.rmtree(root)
    root = context()
    for name in ac.GENERATED:
        os.remove(os.path.join(root, name))
    shutil.rmtree(os.path.join(root, "authoritative"))
    os.mkdir(os.path.join(root, "authoritative"))
    exam = ac.examine(root)
    check(ac.is_incomplete_context(root) and not exam.needs_review and rebuildable(exam)
          and not exam.documents,
          "once no document remains, Rebuild may establish an empty context, governing nothing")
    shutil.rmtree(root)

    print("\nan internally consistent checkout is served, whatever produced it")
    root = context()
    write(root, "authoritative/a.md", doc_text("a", "Alpha", body="Merged from another branch.\n"))
    write(root, "authoritative/c.md", doc_text("c", "Gamma"))
    generate(root)  # as another machine's Charter wrote it, then committed and pulled
    exam = ac.examine(root)
    check(exam.valid and not exam.needs_review and len(exam.documents) == 3,
          "a context another Charter generated, as Git delivers it, is valid and served")
    shutil.rmtree(root)


def case_invalid_documents() -> None:
    print("\nunmapped and unreadable documents")
    for label, text in (
            ("a non-authoritative document in `authoritative/`",
             doc_text("c", "Gamma", authority="non-authoritative")),
            ("a superseded document in `authoritative/`", doc_text("c", "Gamma", status="superseded")),
            ("an unknown status", doc_text("c", "Gamma", status="draft")),
            ("a missing required field", doc_text("c", "Gamma").replace("created: 2026-10-06\n", "")),
            ("a duplicate id", doc_text("a", "Gamma"))):
        root = context()
        write(root, "authoritative/c.md", text)
        exam = ac.examine(root)
        check(exam.state == ac.INVALID and attention(exam) == {"authoritative/c.md": ac.UNRECORDED}
              and exam.rebuild_blockers and [d.path for d in exam.documents]
              == ["authoritative/a.md", "authoritative/b.md"],
              f"{label}, unmapped, is not in the approved context, and blocks a rebuild")
        shutil.rmtree(root)
    for label, text in (
            ("unresolved merge-conflict markers",
             doc_text("c", "Gamma", body="<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> topic\n")),
            ("a byte-order mark", "\ufeff" + doc_text("c", "Gamma")),
            ("text that is not UTF-8", b"---\nid: c\n\xff\n---\n")):
        root = context()
        write(root, "authoritative/c.md", text)
        exam = ac.examine(root)
        check(exam.state == ac.INVALID and ("document", "authoritative/c.md") in kinds(exam)
              and exam.rebuild_blockers and not exam.documents,
              f"an unmapped file with {label} cannot be read as a document, and blocks a rebuild")
        shutil.rmtree(root)

    root = context()
    write(root, "authoritative/A.md", doc_text("A", "Upper"))
    if not os.path.exists(os.path.join(root, "authoritative", "a.md")) or \
            read(root, "authoritative/a.md") != read(root, "authoritative/A.md"):
        exam = ac.examine(root)
        check(exam.state == ac.INVALID and attention(exam) == {"authoritative/A.md": ac.UNRECORDED},
              "a path that differs from a governing one only by letter case is not in the approved "
              "context")
    else:
        print("  - letter-case collision not checked: this filesystem ignores case")
    shutil.rmtree(root)

    root = context()
    target = os.path.join(tempfile.mkdtemp(prefix="charter-outside-"), "x.md")
    write(os.path.dirname(target), "x.md", doc_text("x", "Outside"))
    try:
        os.symlink(target, os.path.join(root, "authoritative", "x.md"))
    except (OSError, NotImplementedError):
        print("  - links not checked: this account cannot create a symbolic link")
    else:
        exam = ac.examine(root)
        check(exam.state == ac.INVALID and "authoritative/x.md" in {i["path"] for i in exam.errors},
              "a link is invalid and never followed")
    shutil.rmtree(root)
    shutil.rmtree(os.path.dirname(target))

    missing = os.path.join(tempfile.gettempdir(), "charter-no-such-folder-9f3c")
    check(ac.examine(missing).state == ac.INVALID, "a folder that does not exist is invalid")


def case_scope_warning() -> None:
    print("\nscope")
    root = context(docs=())
    write(root, "authoritative/c.md", doc_text("c", "Gamma", scope=""))
    generate(root)
    exam = ac.examine(root)
    check(exam.valid and any(i["level"] == "warning" for i in exam.issues),
          "a governing document without a scope is valid, with a warning")
    check("_scope not stated_" in read(root, ac.CONTEXT_MAP).decode(),
          "and the map says its scope is not stated")
    shutil.rmtree(root)


def case_metadata() -> None:
    print("\nthe metadata file")
    root = context()
    meta = json.loads(read(root, ac.METADATA))
    check(list(meta) == list(ac.METADATA_KEYS),
          "it holds only format and map-format versions, project name, guidance and hashes")
    raw = read(root, ac.METADATA).decode()
    check(root not in raw and root.replace("\\", "\\\\") not in raw and "2026" not in raw,
          "it holds no local path and no time")
    check(ac.METADATA not in meta["sha256"], "and never hashes its own bytes")

    def refused(change) -> bool:
        data = dict(meta)
        data.update(change)
        try:
            ac.parse_metadata(json.dumps(data))
        except ac.MetadataError:
            return True
        return False

    for label, change in (
            ("an unknown field", {"context_id": "abc"}),
            ("another format version", {"format_version": 2}),
            ("a version given as true", {"format_version": True}),
            ("another map-format version", {"map_format_version": 0}),
            ("an empty project name", {"project_name": " "}),
            ("a multi-line project name", {"project_name": "a\nb"}),
            ("a guidance setting that does not exist", {"agent_guidance": {**meta["agent_guidance"],
                                                                         "free_text": True}}),
            ("a missing guidance setting", {"agent_guidance": {"context_check_in": True}}),
            ("guidance that is not true or false", {"agent_guidance": {**meta["agent_guidance"],
                                                                      "context_check_in": 1}}),
            ("a hash that is not SHA-256", {"sha256": {"AGENT-CONTEXT.md": "abc"}})):
        check(refused(change), f"{label} is refused")
    try:
        ac.parse_metadata('{"format_version": 1, "format_version": 1}')
        duplicate = False
    except ac.MetadataError:
        duplicate = True
    check(duplicate, "a field named twice is refused")

    write(root, ac.METADATA, json.dumps(meta))
    exam = ac.examine(root)
    check(exam.state == ac.INVALID and ("generated", ac.METADATA) in kinds(exam),
          "metadata with the right content in another form is invalid until rebuilt")
    shutil.rmtree(root)


def case_map() -> None:
    print("\nthe generated map")
    root = context(project="Café | studio")
    text = read(root, ac.CONTEXT_MAP).decode()
    check(text.startswith("# Café \\| studio — Agent Context\n"), "it is titled with the project name")
    check("Generated by Charter" in text and "Rebuild Agent Context" in text,
          "it says it is generated, and how it is regenerated")
    check("active document with authoritative\nmetadata under `authoritative/`" in text,
          "it states the governing predicate")
    check("| [Alpha](authoritative/a.md) | A scope. | `authoritative/a.md` |" in text,
          "it lists each governing document with title, scope and logical path")
    check("read\n`AGENT-CONTEXT.md` again once and start over" in text and ".agent-context.json" in text,
          "it tells a direct reader to reread once and start over on a missing link or hash mismatch")
    flat = " ".join(text.split())
    check("If it still does not match, stop: do not rely on anything you read from this Agent "
          "Context earlier, and tell the person that the Agent Context no longer matches its map, "
          "rather than guessing or continuing." in flat,
          "and, if it still does not match, to stop, not rely on what it read, and tell the person")
    check("charter propose --context ." in text, "its proposal route is `charter propose --context .`")
    for word in ("cgu", "CGU", "Context Governance", "base_commit", "surface", "publish",
                 "workspace", "`created`", "related_finding", "archive"):
        check(word not in text, f"it never mentions {word}")
    check("| `agent` | always |" in text and "| `reason` | always |" in text,
          "`agent` and `reason` are required")
    check("No other field is accepted" in text and "assigns the `proposal_id`" in text,
          "other fields are refused, and the proposal id is assigned")
    check(ac.render_map(ac.Settings.make("X"), []) == ac.render_map(ac.Settings.make("X"), []),
          "rendering twice gives the same text")
    shutil.rmtree(root)

    print("\nagent guidance")
    check(ac.GUIDANCE_IDS == ("context_check_in", "proposal_context_impact_check",
                              "review_newly_discovered_material"),
          "the three settings have the specification's names, in order")
    check(ac.default_guidance() == {"context_check_in": True,
                                    "proposal_context_impact_check": False,
                                    "review_newly_discovered_material": False},
          "only the context check-in is on by default")
    default = ac.render_map(ac.Settings.make("X"), [])
    check("## Agent guidance" in default and ac.CONTEXT_CHECK_LINE in default
          and "Assess proposal impact" not in default, "the default map has the check-in only")
    none = ac.render_map(ac.Settings.make("X", {"context_check_in": False}), [])
    check("## Agent guidance" not in none, "with every setting off there is no guidance section")
    every = ac.render_map(ac.Settings.make("X", {g: True for g in ac.GUIDANCE_IDS}), [])
    check(every.index("- **Context check-in.**") < every.index("- **Assess proposal impact.**")
          < every.index("- **Review discovered material.**"),
          "enabled settings appear in their fixed order, each headed by its Settings name")
    check([g["label"] for g in ac.AGENT_GUIDANCE]
          == ["Context check-in", "Assess proposal impact", "Review discovered material"]
          and all(g["text"].startswith(f"- **{g['label']}.**") for g in ac.AGENT_GUIDANCE)
          and "Context-impact check before a proposal" not in every
          and "Review newly discovered material" not in every,
          "each setting has one name: its Settings label is its map heading")
    check("- `duplicate`: not filed, because an identical proposal is already awaiting" in every,
          "the map tells an agent what a `duplicate` result means")

    print("\nmap-format versions: older is out of date, newer means this Charter is")
    check(ac.MAP_FORMAT_VERSION == 5 and ac.OLDER_MAP_FORMATS == (1, 2, 3, 4),
          "this Charter generates map-format version 5 and recognizes versions 1 to 4 as older")
    root = context(guidance={g: True for g in ac.GUIDANCE_IDS})
    exam = ac.examine(root)
    check(exam.valid and exam.map_format == ac.FORMAT_CURRENT and exam.recorded_map_format == 5,
          "a context it generates records map-format version 5")
    current = ac.render_map(exam.settings, exam.documents)
    rule = ("Write each proposal as ASCII JSON: encode every non-ASCII character with\n"
            "valid JSON Unicode escape sequences such as `" + chr(92) + "uXXXX`.")
    mcp_route = ("If you received this file through MCP, submit each proposal with the\n"
                 "`submit_proposal` tool of the same MCP server, giving the fields below as\n"
                 "its arguments rather than as JSON text. Do not run `charter propose`, even if\n"
                 "you know the folder that holds this file, and do not search for the folder\n"
                 "or guess. If the tool returns `unavailable` with `retryable` `true`, submit\n"
                 "the exact same proposal once more: `duplicate` then means it is already\n"
                 "awaiting review, so stop. If the tool is not listed or is denied, returns\n"
                 "`unavailable` that is not retryable, or the retry returns neither `pending`\n"
                 "nor `duplicate`, do not file the proposal any other way: return the\n"
                 "complete proposal JSON object in your response, so that a person can import\n"
                 "it, and after a retry tell the person that it may already be awaiting\n"
                 "review.\n\n"
                 "If you received this file through any other tool, do not run\n"
                 "`charter propose`, even if you know the folder that holds it, and do not\n"
                 "search for the folder or guess: return the complete proposal JSON object in\n"
                 "your response, so that a person can import it.")
    check(current.count("If you received this file through `charter read`, submit each proposal to\n"
                        "the `charter propose` command your project instructions give, exactly as\n"
                        "given. If they give none, do not run `charter propose`: return the complete\n"
                        "proposal JSON object in your response") == 1
          and current.count(rule) == 1
          and current.count("\ncharter propose --context .\n") == 1,
          "version 5 keeps the command-line and folder routes: a `charter read` agent uses the "
          "command its project instructions give, or returns JSON when they give none; the folder "
          "route stays `--context .`; and JSON sent to `charter propose` is ASCII JSON, verbatim")
    check(current.count(mcp_route) == 1
          and "If you received this file through MCP or any tool other than" not in current
          and current.count("Either command prints, and the `submit_proposal` tool returns, one JSON\n"
                            "object whose `result` is:") == 1,
          "version 5: an MCP agent submits with `submit_proposal`, retries a retryable `unavailable` "
          "once, and returns JSON for import when the tool is missing, denied or fails again; any "
          "other tool still returns JSON; the results mean the same for the command and the tool")
    check(not any(c in current.split("## Making an Agent Proposal")[1] for c in (":\\", "/home/", "/Users/")),
          "  the proposal instructions name no machine-specific path")
    v4 = ac.render_map_version(exam.settings, exam.documents, 4)
    check("submit_proposal" not in v4
          and v4.count("If you received this file through MCP or any tool other than "
                       "`charter read`,\ndo not run `charter propose`, even if you know the folder") == 1
          and "Either command prints one JSON object whose `result` is:" in v4
          and v4.count(rule) == 1 and "If you received this file through `charter read`" in v4,
          "version 4 sent an MCP agent to return JSON for import, and had no `submit_proposal`")
    # Exactly what the format-4 Charter rendered for these inputs: Regenerate map
    # and stale-map recognition depend on reproducing every earlier format exactly.
    fixed = ac.Settings.make("Proj | X — Ü", {g: True for g in ac.GUIDANCE_IDS})
    pinned = {4: "09821893b25eab25cd2db3d1d4944fd871592fbf0d8139a7aca0a9f8e9616513",
              3: "d2f89a34cb989c2efdd249ef18874c2f7673c5f42e61a8bf22b55261fe97667d",
              1: "2920d7b159c79ba2d51251876c9280c1b8857965dc4a6e8447e49fbb66c3bad9"}
    check(all(hashlib.sha256(ac.render_map_version(fixed, [], v).encode("utf-8")).hexdigest() == h
              for v, h in pinned.items())
          and hashlib.sha256(ac.render_legacy_map(fixed, []).encode("utf-8")).hexdigest()
          == "91d0ed1a673020324fd852ae9f79f3898cb976416ac8662b24a1d935da0d503f",
          "formats 4, 3 and 1, and the legacy map, are byte-for-byte what earlier Charter rendered")
    v3 = ac.render_map_version(exam.settings, exam.documents, 3)
    check("`charter read`" not in v3 and "ASCII JSON" not in v3
          and "If you received this file through MCP or another tool, do not run\n`charter propose`" in v3
          and "It prints one JSON object whose `result` is:" in v3 and "stop:" in v3,
          "version 3 had no `charter read` route and no ASCII rule, and sent every other agent to import")
    previous = ac.render_previous_map(exam.settings, exam.documents)
    check("Context-impact check before a proposal" in previous and "`duplicate`" not in previous
          and "and do not know the\nfolder that holds it" in previous
          and "Do not run `charter propose`, even if\nyou know the folder" in current,
          "version 1 had the earlier headings, no duplicate result, and let an MCP agent run "
          "`charter propose`; later versions tell it not to")
    v2 = ac.render_map_version(exam.settings, exam.documents, 2)
    check("read\n`AGENT-CONTEXT.md` again and start over." in v2 and "stop:" not in v2
          and "`duplicate`" in v2 and "do not run\n`charter propose`" in v2,
          "version 2 told a direct reader only to reread and start over; version 3 adds when to stop")
    for version in ac.OLDER_MAP_FORMATS:
        generate(root, guidance={g: True for g in ac.GUIDANCE_IDS})
        with_map_format(root, version)
        exam = ac.examine(root)
        check(not exam.valid and exam.map_format == ac.FORMAT_OLDER and exam.map_outdated
              and [i["message"] for i in exam.errors] == [ac.MAP_OUTDATED]
              and exam.errors[0]["kind"] == ac.GENERATED_KIND and not exam.rebuild_blockers
              and exam.settings is not None and not exam.needs_review,
              f"a version-{version} context is out of date, for exactly that reason: Rebuild is "
              "offered, with its settings kept")
        for rel, text in ac.render_generated(exam.settings, exam.documents, exam.texts).items():
            write(root, rel, text)
        check(ac.examine(root).valid and ac.examine(root).recorded_map_format == 5,
              "  regenerated, it is current, in version 5, and valid again")
    check(not any(ch.isdigit() for ch in ac.MAP_OUTDATED), "the message names no version number")

    with_map_format(root, ac.MAP_FORMAT_VERSION + 1)
    exam = ac.examine(root)
    check(not exam.valid and exam.charter_outdated and not exam.map_outdated
          and [i["message"] for i in exam.errors] == [ac.CHARTER_OUTDATED]
          and exam.errors[0]["kind"] == ac.NEWER_KIND and exam.rebuild_blockers
          and "not at fault" in ac.CHARTER_OUTDATED and not any(ch.isdigit() for ch in ac.CHARTER_OUTDATED),
          "a newer map format is this copy being out of date, never damage, and blocks Rebuild")
    meta = json.loads(read(root, ac.METADATA))
    meta["future_field"] = True
    write(root, ac.METADATA, json.dumps(meta))
    check(ac.examine(root).charter_outdated,
          "a newer format's own new fields do not make it look damaged")
    for label, value in (("version 0", 0), ("a string", "2"), ("true", True), ("a fraction", 1.5)):
        meta = json.loads(read(root, ac.METADATA))
        meta.pop("future_field", None)
        meta["map_format_version"] = value
        write(root, ac.METADATA, json.dumps(meta))
        exam = ac.examine(root)
        check(not exam.valid and not exam.charter_outdated and not exam.map_outdated
              and any("not one this version of Charter recognizes" in i["message"] for i in exam.errors),
              f"a map-format version that is {label} is invalid metadata, to be repaired")
    generate(root, guidance={g: True for g in ac.GUIDANCE_IDS})
    with_map_format(root, 1)
    write(root, "authoritative/a.md", read(root, "authoritative/a.md") + b"Edited.\n")
    exam = ac.examine(root)
    check(not exam.valid and not exam.map_outdated and exam.needs_review
          and attention(exam) == {"authoritative/a.md": ac.CHANGED} and not rebuildable(exam),
          "an older map whose document no longer matches its hash needs review, not just a rebuild")
    shutil.rmtree(root)
    root = context(guidance={"review_newly_discovered_material": True})
    check(json.loads(read(root, ac.METADATA))["agent_guidance"]["review_newly_discovered_material"]
          is True and ac.examine(root).valid, "the metadata records the settings the map renders")
    shutil.rmtree(root)


def case_fingerprint() -> None:
    print("\nthe context fingerprint")
    a, b = context(), context()
    check(ac.examine(a).fingerprint == ac.examine(b).fingerprint,
          "two contexts with the same map and documents have the same fingerprint")
    write(b, "authoritative/a.md", doc_text("a", "Alpha", body="Changed.\n"))
    generate(b)
    check(ac.examine(a).fingerprint != ac.examine(b).fingerprint,
          "changing a governing document changes it")
    shutil.rmtree(a)
    shutil.rmtree(b)


def run() -> None:
    case_valid_contexts()
    case_line_endings()
    case_tolerated_files()
    case_strays()
    case_invalid_front_matter()
    case_context_changes_need_review()
    case_invalid_documents()
    case_scope_warning()
    case_metadata()
    case_map()
    case_fingerprint()
    print(f"\n{OK} All Agent Context checks passed.")


if __name__ == "__main__":
    run()
