"""The Agent Context format and validator. Run: python -m tests.agent_context

Agent Context as the Project Asset §2, §6, §7 and the Product Specification
§3.3:

  * a valid Agent Context is exactly `AGENT-CONTEXT.md`, `.agent-context.json`
    and `authoritative/`, plus the tolerated tooling files;
  * an empty context is valid, with or without `authoritative/`;
  * every other file or folder is a stray: the context is unclean, the stray is
    named and left untouched;
  * the map and metadata must be what the documents and settings generate, and
    the metadata's LF-normalized hashes must match, so an edit to a governing
    document leaves the context invalid until it is rebuilt;
  * the metadata holds only versions, project name, guidance and hashes;
  * examining a folder never writes to it.
"""
from __future__ import annotations

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
    map-format `version` would have: version 1's own wording for 1, the current
    map for a newer one (whose wording this Charter cannot know). The metadata
    records that version and hashes consistent with the files."""
    exam = ac.examine(root)
    text = ac.render_previous_map(exam.settings, exam.documents) if version == 1 \
        else ac.render_map(exam.settings, exam.documents)
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


def case_outside_edits_need_rebuild() -> None:
    print("\nchanges made outside Charter")
    root = context()
    write(root, "authoritative/a.md", doc_text("a", "Alpha", body="Edited.\n"))
    exam = ac.examine(root)
    check(exam.state == ac.INVALID and ("generated", "authoritative/a.md") in kinds(exam),
          "an edit to a governing document leaves the context invalid: its hash no longer matches")
    check(not exam.rebuild_blockers, "and Rebuild Agent Context is what clears it")
    generate(root)
    check(ac.examine(root).valid, "after regeneration the edited context is valid")

    write(root, "authoritative/c.md", doc_text("c", "Gamma"))
    exam = ac.examine(root)
    check(exam.state == ac.INVALID and ("generated", "authoritative/c.md") in kinds(exam),
          "a governing document added by hand is invalid until rebuilt: it is not recorded")
    generate(root)
    os.remove(os.path.join(root, "authoritative", "b.md"))
    exam = ac.examine(root)
    check(exam.state == ac.INVALID and ("generated", "authoritative/b.md") in kinds(exam),
          "a governing document deleted by hand is invalid until rebuilt")
    generate(root)

    text = read(root, ac.CONTEXT_MAP).decode().replace("Alpha", "Alfa")
    write(root, ac.CONTEXT_MAP, text)
    exam = ac.examine(root)
    check(exam.state == ac.INVALID and ("generated", ac.CONTEXT_MAP) in kinds(exam),
          "a hand edit to the map is invalid")
    generate(root)
    os.remove(os.path.join(root, ac.METADATA))
    exam = ac.examine(root)
    check(exam.state == ac.INVALID and ("generated", ac.METADATA) in kinds(exam)
          and not exam.rebuild_blockers, "a missing metadata file is invalid, and rebuildable")
    generate(root)
    os.remove(os.path.join(root, ac.CONTEXT_MAP))
    check(ac.examine(root).state == ac.INVALID, "a missing map is invalid")
    shutil.rmtree(root)


def case_invalid_documents() -> None:
    print("\ninvalid documents")
    for label, text in (
            ("a non-authoritative document in `authoritative/`",
             doc_text("c", "Gamma", authority="non-authoritative")),
            ("a superseded document in `authoritative/`", doc_text("c", "Gamma", status="superseded")),
            ("an unknown status", doc_text("c", "Gamma", status="draft")),
            ("a missing required field", doc_text("c", "Gamma").replace("created: 2026-10-06\n", "")),
            ("a duplicate id", doc_text("a", "Gamma")),
            ("unresolved merge-conflict markers",
             doc_text("c", "Gamma", body="<<<<<<< HEAD\nours\n=======\ntheirs\n>>>>>>> topic\n")),
            ("a byte-order mark", "\ufeff" + doc_text("c", "Gamma"))):
        root = context()
        write(root, "authoritative/c.md", text)
        exam = ac.examine(root)
        check(exam.state == ac.INVALID and ("document", "authoritative/c.md") in kinds(exam)
              and exam.rebuild_blockers and not exam.documents,
              f"{label} is invalid, and blocks a rebuild")
        shutil.rmtree(root)
    root = context()
    write(root, "authoritative/c.md", b"---\nid: c\n\xff\n---\n")
    check(ac.examine(root).state == ac.INVALID, "a document that is not UTF-8 is invalid")
    shutil.rmtree(root)

    root = context()
    write(root, "authoritative/A.md", doc_text("A", "Upper"))
    if not os.path.exists(os.path.join(root, "authoritative", "a.md")) or \
            read(root, "authoritative/a.md") != read(root, "authoritative/A.md"):
        exam = ac.examine(root)
        check(exam.state == ac.INVALID and any("letter case" in i["message"] for i in exam.errors),
              "two paths that differ only by letter case are invalid")
    else:
        print("  - letter-case collision not checked: this filesystem ignores case")
    shutil.rmtree(root)

    root = context()
    map_text = read(root, ac.CONTEXT_MAP).decode()
    write(root, ac.CONTEXT_MAP, "<<<<<<< HEAD\n" + map_text + ">>>>>>> topic\n")
    exam = ac.examine(root)
    check(exam.state == ac.INVALID and not exam.rebuild_blockers,
          "a conflicted map is invalid, and only the generated files need rebuilding")
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
    check("read\n`AGENT-CONTEXT.md` again and start over" in text and ".agent-context.json" in text,
          "it tells a direct reader to start over on a missing link or hash mismatch")
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
    check(ac.MAP_FORMAT_VERSION == 2 and ac.OLDER_MAP_FORMATS == (1,),
          "this Charter generates map-format version 2 and recognizes version 1 as older")
    root = context(guidance={g: True for g in ac.GUIDANCE_IDS})
    exam = ac.examine(root)
    check(exam.valid and exam.map_format == ac.FORMAT_CURRENT and exam.recorded_map_format == 2,
          "a context it generates records map-format version 2")
    previous = ac.render_previous_map(exam.settings, exam.documents)
    check("Context-impact check before a proposal" in previous and "`duplicate`" not in previous
          and "and do not know the\nfolder that holds it" in previous
          and "do not run\n`charter propose`" in ac.render_map(exam.settings, exam.documents),
          "version 1 had the earlier headings, no duplicate result, and let an MCP agent run "
          "`charter propose`; version 2 tells it not to")
    with_map_format(root, 1)
    exam = ac.examine(root)
    check(not exam.valid and exam.map_format == ac.FORMAT_OLDER and exam.map_outdated
          and [i["message"] for i in exam.errors] == [ac.MAP_OUTDATED]
          and exam.errors[0]["kind"] == ac.GENERATED_KIND and not exam.rebuild_blockers
          and exam.settings is not None,
          "a version-1 context is out of date, for exactly that reason: Rebuild is offered, with its settings kept")
    check(not any(ch.isdigit() for ch in ac.MAP_OUTDATED), "and the message names no version number")
    for rel, text in ac.render_generated(exam.settings, exam.documents, exam.texts).items():
        write(root, rel, text)
    check(ac.examine(root).valid, "regenerated, it is current and valid again")

    with_map_format(root, 3)
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
    check(not exam.valid and not exam.map_outdated
          and any("does not match the hash" in i["message"] for i in exam.errors),
          "an older map whose document no longer matches its hash is a real mismatch, not just out of date")
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
    case_outside_edits_need_rebuild()
    case_invalid_documents()
    case_scope_warning()
    case_metadata()
    case_map()
    case_fingerprint()
    print(f"\n{OK} All Agent Context checks passed.")


if __name__ == "__main__":
    run()
