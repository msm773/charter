"""Candidate files Charter cannot use. Run: python -m tests.candidate_files

An authority candidate is private, non-governing material. A candidate file
that cannot be read — not UTF-8 text, or refused by the operating system — and
an entry among the candidates that cannot be one — a name no candidate may
have, a folder, or a link — never make unrelated work fail:

  * the governing context stays served: `charter check`, MCP and `charter read`
    are unaffected;
  * every other candidate stays usable, and unrelated actions — Create
    candidate, Retire, proposal intake, a change set without it — still apply;
  * the unreadable candidate is marked `unreadable` in the console's documents,
    refused by name with a plain reason, and never offered to a change set; a
    draft that includes it is stale with `candidate-unreadable`;
  * other entries are listed by name only, as `unusable_candidate_files`;
  * observing any of it writes nothing: no candidate condition becomes a
    governing-context failure, a record, or a repair.
"""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import agent_proposals as apx  # noqa: E402
from app import api_changeset  # noqa: E402
from app import authority as au  # noqa: E402
from app import changeset  # noqa: E402
from app import console  # noqa: E402
from app import manager as mg  # noqa: E402
from app import mcp  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import propose  # noqa: E402
from app import read  # noqa: E402
from tests.agent_context import context  # noqa: E402
from tests.authority import make_link, remove_link  # noqa: E402
from tests.harness import isolated_private_state  # noqa: E402
from tests.mcp import Session  # noqa: E402

OK = "ok"
ALPHA = "authority-candidates/kappa.md"
BETA = "authority-candidates/lambda.md"


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def refusal(fn, *args, **kwargs) -> str:
    """The message `fn` refuses with, or "" when it does not."""
    try:
        fn(*args, **kwargs)
    except (au.ActionRefused, changeset.ChangeSetError, console.ApiError) as exc:
        return str(exc)
    return ""


def apply(folder: str, kind: str, request: dict) -> dict:
    p = au.plan(folder, kind, request)
    confirm = au.CONFIRM_PHRASE if p.governing_change else True
    return au.apply(folder, kind, p.request, p.plan_id, confirm)


def add(folder: str, title: str) -> None:
    apply(folder, "add", {"title": title, "scope": f"{title} scope.", "body": f"# {title}\n\nBody.\n"})


def setup() -> tuple:
    folder = context()
    add(folder, "Kappa")
    add(folder, "Lambda")
    return folder, ps.PrivateState.default().for_context(folder)


def private_files(cs: ps.ContextState) -> dict:
    """Every private file for this context but its locks, with its bytes."""
    out = {}
    for d, _dirs, names in os.walk(cs.base):
        for n in names:
            rel = os.path.relpath(os.path.join(d, n), cs.base)
            if rel.split(os.sep)[0] == ps.LOCKS:
                continue
            with open(os.path.join(d, n), "rb") as fh:
                out[rel] = fh.read()
    return out


class Unreadable:
    """The operating system refuses to open one private file — a candidate's,
    or an archived document's — as for a file another program holds or a
    person may not read."""

    def __init__(self, cs: ps.ContextState, logical: str = "", archived: str = "") -> None:
        path = cs.archive_file(archived) if archived else cs.candidate_file(logical)
        self.target = os.path.normcase(os.path.abspath(path))

    def __enter__(self):
        real = open

        def guarded(path, *args, **kwargs):
            if isinstance(path, str) and os.path.normcase(os.path.abspath(path)) == self.target:
                raise PermissionError(13, "Permission denied", path)
            return real(path, *args, **kwargs)
        ps.open = guarded  # private_store's own `open`, shadowing the builtin
        return self

    def __exit__(self, *exc) -> None:
        del ps.open


def not_utf8(cs: ps.ContextState, logical: str = "", archived: str = "") -> None:
    with open(cs.archive_file(archived) if archived else cs.candidate_file(logical), "wb") as fh:
        fh.write(b"---\ntitle: \xff\xfe\n---\n\nNot UTF-8 \x81.\n")


def served(folder: str) -> bool:
    session = Session(folder, record=False)
    result = session.call("get_context")
    data, code = read.result(["--context", folder])
    return (not result.get("isError") and code == 0 and data.endswith(b"<<<END CHARTER READ>>>\n")
            and mg.check(folder, git=False)["agents_served"] and ac.examine(folder).valid)


def candidate_entries(folder: str) -> dict:
    state = console.state(console.Session(folder))
    return {d["path"]: d for d in state["documents"] if d["kind"] == "candidate"}


def unaffected_work(folder: str, cs: ps.ContextState, label: str) -> None:
    """Everything that does not use the affected candidate still works."""
    check(served(folder), f"{label}: the governing context is still served — check, MCP and read")
    entries = candidate_entries(folder)
    check(entries[BETA]["title"] == "Lambda" and not entries[BETA].get("unreadable"),
          f"{label}: the console still lists every other candidate as usual")
    apply(folder, "add", {"title": "Gamma", "body": "# Gamma\n"})
    apply(folder, "retire", {"candidate": "authority-candidates/gamma.md"})
    check("authority-candidates/gamma.md" not in cs.candidates(),
          f"{label}: Create candidate and Retire still apply to other candidates")
    filed = propose.submit(["--context", folder], json.dumps({
        "agent": "codex", "operation": "create", "target_path": "authority-candidates/new.md",
        "reason": f"Needed ({label}).", "proposed_body": "# New\n"}).encode("utf-8"))
    by_mcp = Session(folder, record=False).call(mcp.SUBMIT, {
        "agent": "codex", "operation": "create", "target_path": "authority-candidates/other.md",
        "reason": f"Also needed ({label}).", "proposed_body": "# Other\n"})["structuredContent"]
    check(filed["result"] == "pending" and by_mcp["result"] == "pending",
          f"{label}: proposals are still filed, by `charter propose` and by `submit_proposal`")
    ctx = changeset.Ctx(folder)
    draft = changeset.create(ctx, start={"candidate": BETA, "decision": "govern-alongside"})
    view = api_changeset.detail(ctx, changeset.load(ctx, draft["id"]))
    check(not view["stale"] and view["valid"], f"{label}: a change set without it is ready to apply")
    loaded = changeset.load(ctx, draft["id"])
    result = apply(folder, "changeset", {"draft_id": loaded["id"], "draft_revision": loaded["revision"]})
    check(result["applied"] and "authoritative/lambda.md" in {d.path for d in ac.examine(folder).documents},
          f"{label}: and applies, making another candidate govern")


def refused_everywhere(folder: str, cs: ps.ContextState, label: str) -> None:
    """The affected candidate itself: marked, never offered, refused by name."""
    entry = candidate_entries(folder)[ALPHA]
    check(entry.get("unreadable") is True and entry["title"] == ALPHA and entry["scope"] == "",
          f"{label}: the console lists it by its logical path, marked unreadable, with nothing read from it")
    session = console.Session(folder)
    for what, fn, body in (("Read", console.preview, {"source": "document", "path": ALPHA}),
                           ("Edit", console.draft, {"path": ALPHA}),
                           ("Compare", console.compare, {"candidate": ALPHA, "against": BETA})):
        check(refusal(fn, session, body) == console.CANNOT_READ,
              f"{label}: {what} refuses it plainly, never with an internal error")
    check(refusal(au.plan, folder, "retire", {"candidate": ALPHA}) == au.UNREADABLE_CANDIDATE
          and refusal(au.plan, folder, "edit-candidate", {"candidate": ALPHA, "title": "X"})
          == au.UNREADABLE_CANDIDATE,
          f"{label}: an action on it is refused, saying why, and changes nothing")
    ctx = changeset.Ctx(folder)
    check("cannot be read" in refusal(changeset.create, ctx, start={"candidate": ALPHA}),
          f"{label}: a change set cannot start from it")
    draft = changeset.create(ctx, start={"withdraw": "authoritative/a.md"})
    check("cannot be read" in refusal(changeset.update, ctx, draft["id"], draft["revision"],
                                      {"candidates": [ALPHA]}),
          f"{label}: nor include it")
    view = api_changeset.detail(ctx, changeset.load(ctx, draft["id"]))
    check(ALPHA not in {c["path"] for c in view["available_candidates"]}
          and BETA in {c["path"] for c in view["available_candidates"]},
          f"{label}: the change-set picker never offers it, and still offers the others")
    changeset.delete(ctx, draft["id"])
    amend = {"agent": "codex", "operation": "amend", "target_path": ALPHA, "reason": "Edit.",
             "base_sha256": "0" * 64, "proposed_body": "# Alpha\n"}
    unknown = dict(amend, target_path="authority-candidates/never-was.md")
    got = propose.submit(["--context", folder], json.dumps(amend).encode("utf-8"))
    nothing = propose.submit(["--context", folder], json.dumps(unknown).encode("utf-8"))
    check(got["result"] == "refused" and [p["code"] for p in got["problems"]]
          == [p["code"] for p in nothing["problems"]] == ["target_unavailable"],
          f"{label}: a proposal to amend it is refused exactly as one for a name that does not exist")


def case_unreadable_kinds() -> None:
    for label, spoil in (("not UTF-8", lambda cs: (not_utf8(cs, ALPHA), None)[1]),
                         ("refused by the system", lambda cs: Unreadable(cs, ALPHA).__enter__())):
        print(f"\nA candidate file that cannot be read: {label}")
        with isolated_private_state():
            folder, cs = setup()
            guard = spoil(cs)
            try:
                before = cs.readable_candidates()
                check(before[1] == [ALPHA] and BETA in before[0],
                      f"{label}: it is set aside; every other candidate is read")
                refused_everywhere(folder, cs, label)
                unaffected_work(folder, cs, label)
            finally:
                if guard is not None:
                    guard.__exit__(None, None, None)


def case_malformed_text() -> None:
    print("\nA candidate whose text is readable but has no usable front matter is still listed and usable")
    with isolated_private_state():
        folder, cs = setup()
        with open(cs.candidate_file(ALPHA), "w", encoding="utf-8") as fh:
            fh.write("No front matter at all.\n")
        entry = candidate_entries(folder)[ALPHA]
        check(not entry.get("unreadable") and entry["title"] == ALPHA,
              "it is shown by its logical path, and is not marked unreadable")
        unaffected_work(folder, cs, "no front matter")


def case_stale_draft() -> None:
    print("\nA change set that already includes the candidate becomes stale, and says why")
    with isolated_private_state():
        folder, cs = setup()
        ctx = changeset.Ctx(folder)
        draft = changeset.create(ctx, start={"candidate": ALPHA, "decision": "govern-alongside"})
        check(not api_changeset.detail(ctx, changeset.load(ctx, draft["id"]))["stale"],
              "before: the draft is ready")
        not_utf8(cs, ALPHA)
        view = api_changeset.detail(ctx, changeset.load(ctx, draft["id"]))
        codes = [r["code"] for r in view["reasons"]]
        check(view["stale"] and "candidate-unreadable" in codes and "candidate-missing" not in codes
              and not view["valid"],
              "after: it is stale with candidate-unreadable, not ready, and never treated as missing")
        row = next(c for c in view["candidates"] if c["path"] == ALPHA)
        check(row["unreadable"] is True and row["present"] is False,
              "its row is marked unreadable, so the page says Cannot read file")
        refreshed = changeset.refresh(ctx, draft["id"])
        check(any(c["document"] == ALPHA and "cannot be read" in c["change"] for c in refreshed["changed"])
              and ALPHA in refreshed["draft"]["candidates"]
              and changeset.stale_reasons(refreshed["draft"], changeset.Now(ctx))[0]["code"]
              == "candidate-unreadable",
              "Refresh says its file cannot be read and keeps it until the person removes it; it stays stale")
        request = {"draft_id": draft["id"], "draft_revision": refreshed["draft"]["revision"]}
        check(all("stale" in m and "cannot be read" in m for m in (
                  refusal(changeset.load_for_apply, ctx, request["draft_id"], request["draft_revision"]),
                  refusal(au.plan, folder, "changeset", request))),
              "and it can be neither previewed nor applied: the refusal names the unreadable file")
        removed = changeset.update(ctx, draft["id"], refreshed["draft"]["revision"], {"candidates": []})
        check(ALPHA not in removed["candidates"], "the person can still remove it from the change set")
        check(served(folder), "throughout, the governing context is served")


def case_unusable_entries() -> None:
    print("\nEntries among the candidates that cannot be one: listed by name only")
    with isolated_private_state():
        folder, cs = setup()
        base = cs.path(ps.CANDIDATES)
        with open(os.path.join(base, "Kappa copy.md"), "w", encoding="utf-8") as fh:
            fh.write("---\ntitle: Copy\n---\n\nSECRET-COPY-TEXT\n")
        os.makedirs(os.path.join(base, "nested", "deeper"))
        with open(os.path.join(base, "nested", "inner.md"), "w", encoding="utf-8") as fh:
            fh.write("NESTED-TEXT\n")
        os.makedirs(os.path.join(base, "folder.md"))
        with open(os.path.join(base, "notes.txt"), "w", encoding="utf-8") as fh:
            fh.write("text\n")
        with open(os.path.join(base, "desktop.ini"), "w", encoding="utf-8") as fh:
            fh.write("[.ShellClassInfo]\n")
        outside = os.path.join(os.path.dirname(cs.base), "outside-target")
        os.makedirs(outside)
        linked = make_link(os.path.join(base, "linked.md"), outside)
        expected = sorted(["Kappa copy.md", "folder.md", "nested", "notes.txt"]
                          + (["linked.md"] if linked else []))
        try:
            check(cs.unusable_candidate_files() == expected,
                  "invalid names, folders, other files" + (" and links" if linked else "")
                  + " are listed; an operating-system file such as desktop.ini is not")
            state = console.state(console.Session(folder))
            text = json.dumps(state)
            check(state["unusable_candidate_files"] == expected
                  and "SECRET-COPY-TEXT" not in text and "NESTED-TEXT" not in text,
                  "the console's state lists those names and nothing read from them")
            check(sorted(p for p, d in candidate_entries(folder).items()) == [ALPHA, BETA],
                  "none of them is an authority candidate, and the candidates are unchanged")
            apply(folder, "add", {"title": "Folder", "body": "# Folder\n"})
            check("authority-candidates/folder-2.md" in cs.candidates()
                  and os.path.isdir(os.path.join(base, "folder.md")),
                  "a new candidate never lands on an entry already there: it takes a free name")
            unaffected_work(folder, cs, "unusable entries")
        finally:
            if linked:
                remove_link(os.path.join(base, "linked.md"))
            shutil.rmtree(outside, ignore_errors=True)


MU = "mu.md"


def archive_mu(folder: str) -> None:
    """A retired candidate, now an archived document."""
    add(folder, "Mu")
    apply(folder, "retire", {"candidate": "authority-candidates/mu.md"})


def case_unreadable_archive() -> None:
    for label, spoil in (("not UTF-8", lambda cs: (not_utf8(cs, archived=MU), None)[1]),
                         ("refused by the system", lambda cs: Unreadable(cs, archived=MU).__enter__())):
        print(f"\nAn archived document that cannot be read: {label}")
        with isolated_private_state():
            folder, cs = setup()
            archive_mu(folder)
            apply(folder, "add", {"title": "Nu", "body": "# Nu\n"})
            apply(folder, "retire", {"candidate": "authority-candidates/nu.md"})
            guard = spoil(cs)
            try:
                texts, unreadable = cs.readable_archived()
                check(unreadable == [MU] and "nu.md" in texts,
                      f"{label}: it is set aside; every other archived document is read")
                state = console.state(console.Session(folder))
                archived = {d["path"]: d for d in state["documents"] if d["kind"] == "archived"}
                check(archived["archive/mu.md"].get("unreadable") is True
                      and archived["archive/mu.md"]["title"] == "archive/mu.md"
                      and not archived["archive/nu.md"].get("unreadable")
                      and archived["archive/nu.md"]["status"] == "retired",
                      f"{label}: the console's state marks it unreadable, and lists the readable one as before")
                session = console.Session(folder)
                check(refusal(console.preview, session, {"source": "document", "path": "archive/mu.md"})
                      == console.CANNOT_READ_ARCHIVED
                      and console.preview(session, {"source": "document", "path": "archive/nu.md"})["state"]
                      == "archived",
                      f"{label}: reading it is refused in plain words; a readable one still reads")
                with open(cs.archive_file(MU), "rb") as fh:
                    spoiled = fh.read() if guard is None else None
                add(folder, "Mu")
                check("authority-candidates/mu-2.md" in cs.candidates(),
                      f"{label}: a new candidate never takes its name")
                apply(folder, "retire", {"candidate": "authority-candidates/mu-2.md"})
                check(cs.read_archived("mu-2.md") is not None
                      and (guard is not None or open(cs.archive_file(MU), "rb").read() == spoiled),
                      f"{label}: retiring that one archives it beside it, leaving it untouched")
                apply(folder, "revise", {"path": "authoritative/a.md", "body": "# Alpha\n\nRevised.\n"})
                entries = candidate_entries(folder)
                check(any(d.get("revises_title") == "Alpha" for d in entries.values())
                      and entries[BETA]["title"] == "Lambda",
                      f"{label}: candidates, revision lineage included, are listed as usual")
                unaffected_work(folder, cs, label)
            finally:
                if guard is not None:
                    guard.__exit__(None, None, None)


def case_pending_proposal_status() -> None:
    print("\nA pending proposal whose candidate target cannot be read says so, to the person only")
    with isolated_private_state():
        folder, cs = setup()
        add(folder, "Xi")
        xi = "authority-candidates/xi.md"

        def amend(logical: str) -> dict:
            return {"agent": "codex", "operation": "amend", "target_path": logical, "reason": "Edit it.",
                    "base_sha256": ac.sha256_text(cs.read_candidate(logical)), "proposed_body": "# Edited\n"}
        for logical in (ALPHA, xi):
            check(propose.submit(["--context", folder], json.dumps(amend(logical)).encode("utf-8"))
                  ["result"] == "pending", f"an amendment of {logical} is filed")
        not_utf8(cs, ALPHA)
        os.remove(cs.candidate_file(xi))
        listed = {p["target_path"]: p for p in apx.listing(folder)["pending"]}
        unreadable, removed = listed[ALPHA], listed[xi]
        check(unreadable["stale"] and unreadable["target_unreadable"] is True
              and unreadable["stale_reasons"] == [apx.TARGET_UNREADABLE]
              and not any("no longer exists" in r for r in unreadable["stale_reasons"]),
              "the console says Charter cannot read its target's file, never that the target no longer exists")
        check(removed["stale"] and removed["target_unreadable"] is False
              and removed["stale_reasons"] == ["Its target no longer exists."],
              "one whose target was removed still says it no longer exists")
        message = refusal(apply, folder, "accept-proposal", {"proposal_id": unreadable["proposal_id"]})
        check(apx.TARGET_UNREADABLE in message and "no longer exists" not in message,
              "accepting it is refused with the same accurate reason")
        again = dict(amend(BETA), target_path=ALPHA)
        nowhere = dict(again, target_path="authority-candidates/never-was.md")
        answers = [propose.submit(["--context", folder], json.dumps(p).encode("utf-8")) for p in (again, nowhere)]
        answers += [Session(folder, record=False).call(mcp.SUBMIT, p)["structuredContent"]
                    for p in (again, nowhere)]
        shapes = [[(q["code"], q["message"], q.get("field")) for q in a["problems"]] for a in answers]
        check(all(a["result"] == "refused" for a in answers) and shapes[0] == shapes[1]
              and shapes[2] == shapes[3] and [c for c, _m, _f in shapes[0]] == ["target_unavailable"],
              "an agent submitting against it is answered exactly as for a name that does not exist, by either route")
        told = json.dumps(answers)
        check(apx.TARGET_UNREADABLE not in told and "cannot be read" not in told and "UTF-8" not in told
              and cs.base not in told and json.dumps(cs.base)[1:-1] not in told and "kappa" not in told,
              "and is told nothing about the file, its readability, its name, or where private state is")


def case_observing_writes_nothing() -> None:
    print("\nObserving a candidate or archived document Charter cannot use writes nothing")
    with isolated_private_state() as root:
        folder, cs = setup()
        archive_mu(folder)
        session = console.Session(folder)
        console.state(session)  # opening the console's state once, as the page does
        check(propose.submit(["--context", folder], json.dumps({
            "agent": "codex", "operation": "amend", "target_path": ALPHA, "reason": "Edit.",
            "base_sha256": ac.sha256_text(cs.read_candidate(ALPHA)), "proposed_body": "# K\n"})
            .encode("utf-8"))["result"] == "pending", "a proposal awaits review against the candidate")
        not_utf8(cs, ALPHA)
        not_utf8(cs, archived=MU)
        os.makedirs(cs.path(ps.CANDIDATES, "nested"))
        context_before = {p: ac.read_text(folder, p) for p in ac.examine(folder).texts}
        before = private_files(cs)
        roots = sorted(os.listdir(os.path.join(root, ps.CONTEXTS)))
        ctx = changeset.Ctx(folder)
        for _ in range(2):
            console.state(session)
            refusal(console.preview, session, {"source": "document", "path": ALPHA})
            refusal(console.preview, session, {"source": "document", "path": "archive/mu.md"})
            apx.listing(folder)
            refusal(au.plan, folder, "retire", {"candidate": ALPHA})
            au.plan(folder, "add", {"title": "Unfiled", "body": "x"})
            changeset.Now(ctx)
            mg.check(folder, git=False)
            served(folder)
        check(private_files(cs) == before and sorted(os.listdir(os.path.join(root, ps.CONTEXTS))) == roots,
              "no private file is written, changed or removed — the unreadable files' bytes included")
        check({p: ac.read_text(folder, p) for p in ac.examine(folder).texts} == context_before
              and ac.examine(folder).valid and not ac.examine(folder).errors,
              "the Agent Context is untouched, and no candidate condition is a context problem")
        check(ps._default_root() == root, "all of it ran against isolated private state")


def main() -> None:
    case_unreadable_kinds()
    case_malformed_text()
    case_stale_draft()
    case_unusable_entries()
    case_unreadable_archive()
    case_pending_proposal_status()
    case_observing_writes_nothing()
    print("\nAll candidate file checks passed.")


if __name__ == "__main__":
    main()
