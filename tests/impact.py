"""Advisory context-impact review. Run: python -m tests.impact

Coordinated Context Changes and Advisory Review:

  * `charter-context-impact-prompt/1` and `charter-context-impact-report/1`;
  * the context fingerprint is over the generated map and the governing
    documents, by logical path and LF-normalized content; the plan
    fingerprint covers rows, outcomes and candidate relationships only;
  * one copyable prompt when practical, else one portable UTF-8 packet, with
    the complete reviewed material, hashes, untrusted-data markers and the
    Charter terminal marker, and no private location;
  * reports are checked mechanically only, stay advisory, go stale when the
    reviewed inputs change, and can disagree side by side;
  * a packet is saved only outside every Agent Context and private state,
    never overwriting anything.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import api_changeset as api  # noqa: E402
from app import authority as au  # noqa: E402
from app import changeset as chs  # noqa: E402
from app import console  # noqa: E402
from app import host_state as hs  # noqa: E402
from app import impact  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import review_packet  # noqa: E402
from tests.agent_context import context, doc_text, generate, read, write  # noqa: E402
from tests.changeset import add, setup, three_outcomes  # noqa: E402
from tests.harness import isolated_private_state  # noqa: E402

OK = "ok"


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def raises(exc, fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
    except exc:
        return True
    return False


def report_for(identity, material, planned, **change) -> str:
    """A well-formed report for exactly this review."""
    docs = identity["documents"]
    data = {
        "schema": impact.REPORT_SCHEMA, "prompt_schema": impact.PROMPT_SCHEMA,
        "project": identity["project"], "context_fingerprint": identity["fingerprint"],
        "plan_fingerprint": planned,
        "documents": [{"path": d["path"], "sha256": d["sha256"]} for d in docs],
        "candidates": [{"path": c["path"], "sha256": c["sha256"]} for c in material.values()],
        "coverage": [{"path": d["path"], "status": "affected"} for d in docs],
        "impact": {"related_documents": [docs[0]["path"]], "overlap": "none", "conflict": "none found",
                   "recommended_relationship": "replace", "unresolved_decision": "none"},
        "claims": [{"kind": "overlap", "path": docs[0]["path"], "quote": "Body.", "explanation": "Same."}],
        "recommendations": [{"path": docs[0]["path"], "action": "revise"}],
        "limitations": [],
    }
    data.update(change)
    return "Here is my review.\n\n```json\n" + json.dumps(data, indent=2) + "\n```\n"


def case_material() -> None:
    print("\nthe review material")
    with isolated_private_state() as root:
        folder, ctx, revision, newcomer, _spare = setup()
        draft = three_outcomes(ctx, chs.create(ctx, "Restructure"), revision, newcomer)
        now = chs.Now(ctx)
        identity = impact.context_identity(now)
        exam = ac.examine(folder)
        expected = ac.context_fingerprint({p: ac.sha256_text(t) for p, t in exam.texts.items()})
        check(identity["fingerprint"] == exam.fingerprint == expected
              and set(exam.hashes) == {"AGENT-CONTEXT.md", "authoritative/a.md", "authoritative/b.md",
                                       "authoritative/c.md"},
              "the context fingerprint is over the map and governing documents, by logical path")
        detail = api.detail(ctx, draft)
        p = detail["review_prompt"]
        check(p["ready"] and not p["over_limit"] and p["mode"] == impact.SELF_CONTAINED,
              "a review that fits in one message is a prompt to copy")
        text = p["text"]
        check(f"`{impact.PROMPT_SCHEMA}`" in text and f'"schema": "{impact.REPORT_SCHEMA}"' in text,
              "it names charter-context-impact-prompt/1 and asks for charter-context-impact-report/1")
        check(text.rstrip("\n").endswith(f"<<<END OF Charter REVIEW PROMPT {detail['plan_fingerprint'][:16]}>>>"),
              "it ends with its terminal marker")
        check(all(d["sha256"] in text for d in identity["documents"])
              and ac.sha256_text(ctx.cs.read_candidate(revision)) in text
              and identity["fingerprint"] in text and detail["plan_fingerprint"] in text,
              "it carries every hash and both fingerprints")
        fences = [ln for ln in text.splitlines() if ln.startswith("<<<BEGIN UNTRUSTED DATA ")]
        check(len(fences) == 3 + 2 and "Alpha two body." in text,
              "every governing document and candidate is fenced as untrusted data, in full")
        check("revise `authoritative/a.md` with candidate" in text and "withdraw `authoritative/b.md`" in text
              and "govern alongside" in text, "and the complete planned change, as a plan, not a decision")
        for secret in (folder, root, ctx.cs.base, "contexts", "commit "):
            check(secret not in text, f"it holds no {secret if len(secret) < 12 else 'local path'!r}")
        check(impact.private_leaks("see " + folder + "/x", ctx.secrets()),
              "a local path quoted in the material would be caught")

        big = "Long line of governing text. " * 2500
        write(folder, "authoritative/c.md", read(folder, "authoritative/c.md").decode() + big)
        from tests.agent_context import generate
        generate(folder)
        api.refresh(console.Session(folder), {"id": draft["id"]})
        p = api.detail(ctx, chs.load(ctx, draft["id"]))["review_prompt"]
        check(p["ready"] and p["over_limit"] and "text" not in p
              and p["file_name"].startswith("charter-review-packet-") and p["file_name"].endswith(".md")
              and f"<<<END OF Charter REVIEW PACKET {p['plan_fingerprint'][:16]}>>>" in p["request"],
              "past the practical limit it is one review packet, never sent to the page")
        material = chs.packet_material(ctx, draft["id"], p["plan_fingerprint"])
        check(material["text"].rstrip("\n").endswith(f"<<<END OF Charter REVIEW PACKET {p['plan_fingerprint'][:16]}>>>")
              and material["mode"] == impact.PACKET, "the packet ends with the Charter terminal marker")
        check(raises(chs.ChangeSetError, chs.packet_material, ctx, draft["id"], "0" * 64),
              "a packet is prepared only for the plan the person is looking at")
        shutil.rmtree(folder)


def case_reports() -> None:
    print("\nreports: checked for form only, advisory, side by side")
    with isolated_private_state():
        folder, ctx, revision, newcomer, _spare = setup()
        draft = three_outcomes(ctx, chs.create(ctx, "Restructure"), revision, newcomer)
        now = chs.Now(ctx)
        identity = impact.context_identity(now)
        material = {c["path"]: c for c in chs.candidate_material(ctx, draft, now)}
        planned = chs.plan_fingerprint(draft)
        good = report_for(identity, material, planned)
        check(impact.check_report(good, identity, material, planned)["status"] == "well-formed",
              "a report that matches the review passes its form checks")
        cases = (
            ("an older schema", dict(schema="cgu-context-impact-report/2"), "malformed"),
            ("another project", dict(project="Other"), "stale"),
            ("another context", dict(context_fingerprint="0" * 64), "stale"),
            ("another plan", dict(plan_fingerprint="0" * 64), "stale"),
            ("a quote not in the document", dict(claims=[{"kind": "conflict", "path": "authoritative/a.md",
                                                          "quote": "Never said."}]), "issues"),
            ("an uncovered document", dict(coverage=[]), "issues"),
            ("an unknown action", dict(recommendations=[{"path": "authoritative/a.md", "action": "merge"}]),
             "issues"),
        )
        for label, change, status in cases:
            got = impact.check_report(report_for(identity, material, planned, **change), identity, material, planned)
            check(got["status"] == status, f"{label}: {status}")
        check(impact.check_report("No JSON here.", identity, material, planned)["status"] == "malformed",
              "a response with no report is malformed")

        session = console.Session(folder)
        api.attach_report(session, {"id": draft["id"], "text": good, "label": "Agent one"})
        disagree = report_for(identity, material, planned, recommendations=[
            {"path": "authoritative/a.md", "action": "retain"}])
        detail = api.attach_report(session, {"id": draft["id"], "text": disagree, "label": "Agent two"})
        check([r["status"] for r in detail["reports"]] == ["well-formed", "well-formed"]
              and detail["rows"][0]["outcome"] == "revise",
              "two reports that disagree are both kept, and neither changes an outcome")
        p = au.plan(folder, "edit-candidate", {"candidate": revision, "scope": "Changed."})
        au.apply(folder, "edit-candidate", p.request, p.plan_id, True)
        api.refresh(session, {"id": draft["id"]})
        detail = api.get(session, {"id": draft["id"]})
        check(all(r["status"] == "stale" for r in detail["reports"]),
              "a changed candidate makes every attached report stale, even after refresh")
        draft = chs.load(ctx, draft["id"])
        planned = chs.plan_fingerprint(draft)
        detail = api.prompt_copied(session, {"id": draft["id"], "mode": "self-contained",
                                             "plan_fingerprint": planned})
        check(detail["copied"][-1]["current"] and detail["review_stage"] == "report attached",
              "copying the prompt is remembered, for this plan")
        detail = api.update(session, {"id": draft["id"], "revision": detail["draft"]["revision"],
                                      "alongside": []})
        check(not detail["copied"][-1]["current"], "and once the plan changes, that copy is for an earlier plan")
        shutil.rmtree(folder)


def case_packet_destinations() -> None:
    print("\nwhere a packet may be saved")
    with isolated_private_state() as root:
        folder = context()
        ps.PrivateState.default().for_context(folder)
        other = context()
        ps.PrivateState.default().for_context(other)
        outside = tempfile.mkdtemp(prefix="charter-packets-")
        for label, path in (("this Agent Context", os.path.join(folder, "p.md")),
                            ("inside it", os.path.join(folder, "authoritative", "p.md")),
                            ("another Agent Context", os.path.join(other, "p.md")),
                            ("the private state", os.path.join(root, "p.md")),
                            ("a folder that contains an Agent Context", os.path.dirname(folder))):
            check(raises(review_packet.PacketDestinationError, review_packet.destination, folder, path, "x.md"),
                  f"{label} is refused")
        unknown = tempfile.mkdtemp(prefix="charter-unknown-context-")
        write(unknown, "AGENT-CONTEXT.md", "# x\n")
        check(raises(review_packet.PacketDestinationError, review_packet.destination, folder,
                     os.path.join(unknown, "p.md"), "x.md"),
              "so is any folder holding an Agent Context this computer does not know")
        check(raises(review_packet.PacketDestinationError, review_packet.destination, folder, "relative.md", "x.md"),
              "a relative path is refused")
        dest = review_packet.destination(folder, outside, "charter-review-packet-x.md")
        check(dest.warning == "" and dest.name == "charter-review-packet-x.md", "an ordinary folder outside is allowed")
        first = review_packet.write(dest, "# Packet\r\nline\n")
        second = review_packet.write(dest, "# Another\n")
        check(first == "charter-review-packet-x.md" and second == "charter-review-packet-x (2).md"
              and open(os.path.join(outside, first), "rb").read() == b"# Packet\nline\n",
              "a packet is UTF-8 with LF, and nothing is ever overwritten")
        repo = tempfile.mkdtemp(prefix="charter-repo-")
        subprocess.run(["git", "init", "-q", repo], check=True)
        check(review_packet.destination(folder, repo, "x.md").warning == review_packet.GIT_WARNING,
              "inside a Git repository it is allowed, with a warning")
        for path in (folder, other, outside, unknown, repo):
            shutil.rmtree(path, ignore_errors=True)


def files_under(root: str) -> dict:
    """Every file below `root` with its size, to show a refusal wrote nothing."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            out[os.path.relpath(path, root)] = os.path.getsize(path)
    return out


def link_folder(link: str, target: str) -> str:
    """Make `link` a junction (Windows) or symbolic link to the folder
    `target`. Returns what was made, or "" when this computer does not allow it."""
    if os.name == "nt":
        made = subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True)
        if made.returncode == 0:
            return "junction"
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        return ""
    return "symbolic link"


def case_packet_sibling_folders() -> None:
    print("\na packet beside an Agent Context, not around it")
    machine = tempfile.mkdtemp(prefix="charter-machine-")
    products = os.path.join(machine, "Products")
    folder = os.path.join(products, "charter-context")
    home = os.path.join(machine, "Users", "test-user")
    downloads = os.path.join(home, "Downloads")
    elsewhere = os.path.join(home, "Elsewhere")
    local = os.path.join(home, "AppData", "Local")
    for path in (downloads, elsewhere, local):
        os.makedirs(path)
    big = "Long line of governing text. " * 2500
    for name, title in (("a.md", "Alpha"), ("b.md", "Beta"), ("c.md", "Gamma")):
        write(folder, f"authoritative/{name}", doc_text(name[:-3], title, body=big if name == "c.md" else "Body.\n"))
    generate(folder)
    try:
        with isolated_private_state(local) as root:
            # Opening an ordinary folder by mistake records it in private state.
            try:
                console.Session(downloads)
            except console.ApiError:
                pass
            state = ps.PrivateState.default()
            check(hs.canonical(downloads) in state.known_contexts(),
                  "opening an ordinary folder records it, as Downloads was")
            revision, newcomer = add(folder, "Alpha two", "Alpha, revised."), add(folder, "Delta", "Delta things.")
            ctx = chs.Ctx(folder)
            draft = three_outcomes(ctx, chs.create(ctx, "Restructure"), revision, newcomer)
            session = console.Session(folder)
            planned = api.detail(ctx, chs.load(ctx, draft["id"]))["review_prompt"]["plan_fingerprint"]

            def save(path):
                return api.save_packet(session, {"id": draft["id"], "plan_fingerprint": planned, "path": path})

            def refused(path, why, label):
                before = files_under(machine)
                try:
                    save(path)
                except console.ApiError as exc:
                    check(why in exc.message and files_under(machine) == before,
                          f"{label}: refused, and nothing written")
                    return
                check(False, f"{label}: refused")

            got = save(downloads)
            name = got["saved"]["name"]
            check(name.startswith("charter-review-packet-") and os.path.normcase(got["saved"]["folder"])
                  == os.path.normcase(hs.canonical(downloads))
                  and open(os.path.join(downloads, name), "rb").read().rstrip(b"\n").endswith(
                      f"<<<END OF Charter REVIEW PACKET {planned[:16]}>>>".encode()),
                  "a sibling folder such as Downloads, recorded only because it was opened, takes the packet")
            check(got["saved"]["warning"] == "" and chs.load(ctx, draft["id"])["prompts"][-1]["mode"] == impact.PACKET,
                  "and the draft remembers that a packet was saved")
            check(f"“{name}”" in got["saved"]["request"] or name in got["saved"]["request"],
                  "the request to send with it names the saved file")
            again = save(downloads)["saved"]
            check(again["renamed"] and again["name"] != name and again["name"] in again["request"]
                  and name not in again["request"].replace(again["name"], ""),
                  "saved again beside it: renamed, and its request names the renamed file, never the first")

            context_named = "this Agent Context"
            for label, path in (("the Agent Context itself", folder),
                                ("a folder inside it", os.path.join(folder, "authoritative")),
                                ("a file path inside it", os.path.join(folder, "authoritative", "p.md")),
                                ("its parent folder", products),
                                ("a folder above both", machine)):
                refused(path, "cannot be saved there", label)
            refused(folder, context_named, "the Agent Context is named as the reason")
            private_named = "private state"
            for label, path in (("the private state itself", root),
                                ("a folder inside it", os.path.join(root, ps.CONTEXTS)),
                                ("a folder above it", local)):
                refused(path, private_named, f"{label}")

            for sep in (os.sep, os.sep * 2) + (("/",) if os.name == "nt" else ()):
                refused(folder + sep, context_named, f"the Agent Context with a trailing {sep!r}")
                refused(root + sep, private_named, f"the private state with a trailing {sep!r}")
            refused(os.path.join(downloads, "..", "..", "..", "Products", "charter-context"), context_named,
                    "a path that climbs back into the Agent Context")
            refused(os.path.join(folder, ".", "authoritative", "."), context_named, "a path with `.` segments")
            if os.path.isdir(folder.swapcase()):
                refused(folder.swapcase(), context_named, "the Agent Context in other letter case")
                refused(root.upper(), private_named, "the private state in other letter case")
                check(save(downloads.swapcase() + os.sep)["saved"]["name"].startswith("charter-review-packet-"),
                      "while Downloads in other letter case, with a trailing separator, is still allowed")
            here = os.getcwd()
            os.chdir(products)
            try:
                for path in ("charter-context", os.path.join("charter-context", "p.md"), os.path.join("..", "Products"),
                             "p.md") + ((os.path.splitdrive(folder)[0] + "p.md",) if os.name == "nt" else ()):
                    refused(path, "full path", f"the relative path {path!r}")
            finally:
                os.chdir(here)

            for target, why, what in ((folder, context_named, "the Agent Context"),
                                      (products, context_named, "a folder above the Agent Context"),
                                      (root, private_named, "the private state")):
                link = os.path.join(downloads, f"to-{os.path.basename(target)}")
                kind = link_folder(link, target)
                if not kind:
                    print(f"  (skipped: this computer does not allow a link to {what})")
                    continue
                refused(link, why, f"a {kind} in Downloads to {what}")
                refused(os.path.join(link, "p.md"), why, f"a file path through a {kind} to {what}")
            if link_folder(os.path.join(downloads, "to-elsewhere"), elsewhere):
                check(save(os.path.join(downloads, "to-elsewhere"))["saved"]["folder"].lower()
                      == hs.canonical(elsewhere).lower(), "a link to an ordinary folder is followed and allowed")

            # An opened folder with anything else in private state still counts.
            try:
                console.Session(elsewhere)
            except console.ApiError:
                pass
            check(review_packet.destination(folder, elsewhere, "x.md").folder == hs.canonical(elsewhere),
                  "another folder recorded only because it was opened is allowed")
            kept = state.find_context(elsewhere).path(ps.CHANGESETS, "0123456789abcdef.json")
            with open(kept, "w") as fh:
                fh.write("{}")
            refused(elsewhere, "an Agent Context", "one whose private state holds a draft is still an Agent Context")
            os.remove(kept)
            os.makedirs(os.path.join(elsewhere, ac.AUTHORITATIVE))
            refused(elsewhere, "an Agent Context", "so is one that now holds `authoritative/`")
    finally:
        for name in os.listdir(downloads) if os.path.isdir(downloads) else ():
            if name.startswith("to-"):  # remove each link alone, never what it points to
                link = os.path.join(downloads, name)
                try:
                    os.unlink(link) if os.path.islink(link) else os.rmdir(link)
                except OSError:
                    pass
        shutil.rmtree(machine, ignore_errors=True)


def run() -> None:
    case_material()
    case_reports()
    case_packet_destinations()
    case_packet_sibling_folders()
    print(f"\n{OK} All impact checks passed.")


if __name__ == "__main__":
    run()
