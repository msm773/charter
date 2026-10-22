"""Authority actions without Git, and their transactions. Run: python -m tests.authority

Product Specification §3.2–§3.3, Scope Authoring and Revision Workflow, and
the transaction design approved for Phase 3:

  * new or revised material is a private candidate; it never governs;
  * governing context changes only through a change set — here, one
    prefilled with a single grant, revise, replace or withdraw outcome — with
    the typed phrase, from a valid context, writing only the Agent Context's
    files and private state, and never operating Git; there is no direct
    grant, replace or withdraw action;
  * retire and candidate edits need ordinary confirmation and change no
    context;
  * a plan whose inputs changed is stale;
  * a failure rolls back both the folder and private state; an interrupted
    write is rolled back from the private journal before the next write; only
    files the journal names are deleted; with the journal lost, leftovers stay
    and the context is refused.
"""
from __future__ import annotations

import contextlib
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re  # noqa: E402

from app import agent_context as ac  # noqa: E402
from app import authority as au  # noqa: E402
from app import changeset as chs  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import provenance as prov  # noqa: E402
from app import transaction as tx  # noqa: E402
from app.docs import parse_front_matter  # noqa: E402
from tests.agent_context import context, doc_text, read, snapshot, write  # noqa: E402
from tests.harness import isolated_private_state, seeded  # noqa: E402

OK = "ok"
PHRASE = au.CONFIRM_PHRASE


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


class Crash(BaseException):
    """The process dying at a step: no in-process rollback runs."""


def raises(exc, fn, *args, **kwargs) -> bool:
    try:
        fn(*args, **kwargs)
    except exc:
        return True
    return False


def private_docs(cs: ps.ContextState) -> dict:
    out = {}
    for sub in (ps.CANDIDATES, ps.ARCHIVE):
        for name in sorted(os.listdir(cs.path(sub))):
            with open(cs.path(sub, name), "rb") as fh:
                out[f"{sub}/{name}"] = fh.read()
    return out


def do(folder: str, kind: str, request: dict, confirm=None, fault=None) -> dict:
    p = au.plan(folder, kind, request)
    if confirm is None:
        confirm = PHRASE if p.governing_change else True
    return au.apply(folder, kind, request, p.plan_id, confirm, fault=fault)


def alongside(folder: str, candidate: str) -> dict:
    """A change set prefilled to grant `candidate` alongside the others."""
    return seeded(folder, {"alongside": candidate})


def withdrawal(folder: str, path: str) -> dict:
    """A change set prefilled to withdraw the governing document at `path`."""
    return seeded(folder, {"document": path, "outcome": "withdraw"})


def receipt_label(p: au.Plan) -> str:
    """The one private write that is the change set's own receipt."""
    found = [c.label for c in p.changes if c.label.startswith("Change set “")]
    assert len(found) == 1, found
    return found[0]


def meta_of(text: str) -> dict:
    return parse_front_matter(text)[0]


def add(folder: str, title: str, scope: str = "Cand scope.", body: str = "Cand body.\n") -> str:
    do(folder, "add", {"title": title, "scope": scope, "body": body})
    cs = ps.PrivateState.default().for_context(folder)
    return [c for c in cs.candidates()
            if meta_of(cs.read_candidate(c))["title"] == title][0]


def case_candidates() -> None:
    print("\ncandidates are private and never govern")
    with isolated_private_state():
        folder = context()
        before = snapshot(folder)
        p = au.plan(folder, "add", {"title": "New policy", "scope": "Policies.", "body": "Rule.\n"})
        check(not p.governing_change and p.confirm_phrase == "" and not p.blocked,
              "adding a document is not a governing change")
        check([c.to_json()["location"] for c in p.changes] == ["private state"]
              and p.changes[0].label == "authority-candidates/new-policy.md",
              "its preview shows one private candidate, by logical path")
        check(raises(au.ActionRefused, au.apply, folder, "add", p.request, p.plan_id, None),
              "and applying it needs a deliberate confirmation")
        logical = add(folder, "New policy", "Policies.")
        cs = ps.PrivateState.default().for_context(folder)
        meta = meta_of(cs.read_candidate(logical))
        check(meta["authority"] == "non-authoritative" and meta["status"] == "active",
              "the candidate is non-authoritative")
        check(snapshot(folder) == before and ac.examine(folder).valid,
              "the Agent Context folder is unchanged")

        do(folder, "revise", {"path": "authoritative/a.md"})
        revision = [c for c in cs.candidates() if c != logical][0]
        rmeta = meta_of(cs.read_candidate(revision))
        check(rmeta["title"] == "Alpha" and rmeta["scope"] == "A scope." and rmeta["id"] != "a",
              "Revise files a candidate prefilled from the governing document, with its own id")
        check(snapshot(folder) == before, "and the governing document does not change")

        do(folder, "edit-candidate", {"candidate": revision, "scope": "Narrower.",
                                      "body": "Revised.\n"})
        text = cs.read_candidate(revision)
        check(meta_of(text)["scope"] == "Narrower." and text.endswith("Revised.\n"),
              "a candidate's title, scope and body can be edited")

        p = au.plan(folder, "retire", {"candidate": logical})
        check(raises(au.ActionRefused, au.apply, folder, "retire", p.request, p.plan_id, None),
              "retiring needs a deliberate confirmation")
        au.apply(folder, "retire", p.request, p.plan_id, True)
        check(logical not in cs.candidates() and cs.archived() == ["new-policy.md"]
              and meta_of(cs.read_archived("new-policy.md"))["status"] == "retired",
              "a retired candidate moves to the private archive")
        check(snapshot(folder) == before, "and no governing context changed")
        shutil.rmtree(folder)


def case_grant_and_withdraw() -> None:
    print("\ngranting and withdrawing authority, each in a one-document change set")
    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        logical = add(folder, "Gamma rules", "Gamma.")
        request = alongside(folder, logical)
        p = au.plan(folder, "changeset", request)
        labels = {c.label: c.action for c in p.changes}
        check(p.governing_change and p.confirm_phrase == PHRASE,
              "granting is a governing change confirmed by the typed phrase")
        check(labels == {"authoritative/gamma-rules.md": "create", "AGENT-CONTEXT.md": "modify",
                         ".agent-context.json": "modify", logical: "delete",
                         receipt_label(p): "modify"},
              "its preview lists every file it writes, and the change set's receipt")
        check([d["path"] for d in p.after] == ["authoritative/a.md", "authoritative/b.md",
                                               "authoritative/gamma-rules.md"]
              and len(p.before) == 2, "and the governing set before and after")
        check(all(c.diff() for c in p.changes), "with a diff for each")
        for wrong in (True, "change governing context ", "Change governing context", None):
            check(raises(au.ActionRefused, au.apply, folder, "changeset", request, p.plan_id, wrong),
                  f"confirmation {wrong!r} is refused")
        result = au.apply(folder, "changeset", request, p.plan_id, PHRASE)
        exam = ac.examine(folder)
        check(exam.valid and "authoritative/gamma-rules.md" in exam.hashes,
              "after the grant the Agent Context is valid and the document governs")
        check("Gamma rules" in exam.texts["AGENT-CONTEXT.md"], "the map lists it")
        check(logical not in cs.candidates(), "it is no longer a candidate")
        check(cs.observed()["fingerprint"] == exam.fingerprint == result["fingerprint"]
              and cs.observed()["source"] == "charter", "Charter records what it wrote")

        os.makedirs(os.path.join(folder, "authoritative", "area"))
        write(folder, "authoritative/area/d.md", doc_text("d", "Delta"))
        from tests.agent_context import generate
        generate(folder)
        request = withdrawal(folder, "authoritative/area/d.md")
        p = au.plan(folder, "changeset", request)
        check(p.governing_change and not p.blocked, "withdrawing is a governing change")
        au.apply(folder, "changeset", request, p.plan_id, PHRASE)
        check(not os.path.exists(os.path.join(folder, "authoritative", "area"))
              and ac.examine(folder).valid,
              "withdrawing the only document in a subfolder removes the emptied subfolder")
        check("authority-candidates/d.md" in cs.candidates()
              and meta_of(cs.read_candidate("authority-candidates/d.md"))["authority"]
              == "non-authoritative", "the withdrawn document returns to candidate status")
        for path in ("authoritative/a.md", "authoritative/b.md", "authoritative/gamma-rules.md"):
            do(folder, "changeset", withdrawal(folder, path))
        exam = ac.examine(folder)
        check(exam.valid and not exam.documents and "_None._" in exam.texts["AGENT-CONTEXT.md"],
              "withdrawing every document leaves a valid empty context")
        shutil.rmtree(folder)


def case_replace() -> None:
    print("\nreplacing a governing document in a one-document change set")
    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        do(folder, "revise", {"path": "authoritative/a.md"})
        revision = cs.candidates()[0]
        do(folder, "edit-candidate", {"candidate": revision, "scope": "", "body": "Alpha v2.\n"})
        request = seeded(folder, {"document": "authoritative/a.md", "outcome": "replace",
                                  "candidate": revision})
        p = au.plan(folder, "changeset", request)
        check(not any("replaces" in n or "scope" in n for n in p.notes),
              "the preview adds no scope note: the resulting document carries its scope")
        ctx = chs.Ctx(folder)
        effect = chs.evaluate(ctx, chs.load(ctx, request["draft_id"]))["effects"][0]
        check(effect["scope_before"] == "A scope." and effect["scope_proposed"] == ""
              and effect["scope_after"] == "A scope.",
              "and the change set records current, candidate and resulting scope")
        check({c.label for c in p.changes} == {"authoritative/a.md", ".agent-context.json",
                                               revision, "archive/a-superseded.md",
                                               receipt_label(p)},
              "it rewrites the governing path and archives the replaced version privately")
        check("AGENT-CONTEXT.md" not in {c.label for c in p.changes},
              "with the same title and inherited scope the map is unchanged, so not rewritten")
        au.apply(folder, "changeset", request, p.plan_id, PHRASE)
        exam = ac.examine(folder)
        new = next(d for d in exam.documents if d.path == "authoritative/a.md")
        check(exam.valid and new.body.strip() == "Alpha v2." and new.meta["scope"] == "A scope.",
              "the replacement governs at the same path, with the inherited scope")
        old = meta_of(cs.read_archived("a-superseded.md"))
        check(old["status"] == "superseded" and old["authority"] == "non-authoritative"
              and old["superseded_by"] == [new.id] and new.meta["supersedes"] == ["a"],
              "supersession is recorded on both versions")
        check(not os.path.exists(os.path.join(folder, "archive")),
              "nothing archived is written into the Agent Context")
        shutil.rmtree(folder)


def case_preconditions_and_staleness() -> None:
    print("\npreconditions and stale plans")
    with isolated_private_state():
        folder = context()
        logical = add(folder, "Gamma rules")
        request = alongside(folder, logical)
        p = au.plan(folder, "changeset", request)
        cs = ps.PrivateState.default().for_context(folder)
        with open(cs.candidate_file(logical), "a", encoding="utf-8", newline="\n") as fh:
            fh.write("More.\n")
        before = snapshot(folder)
        check(raises(au.ActionRefused, au.apply, folder, "changeset", request, p.plan_id, PHRASE)
              and snapshot(folder) == before and logical in cs.candidates(),
              "a candidate changed after the preview makes the plan stale, and nothing is written")
        request = alongside(folder, logical)
        p = au.plan(folder, "changeset", request)
        write(folder, "authoritative/b.md", doc_text("b", "Beta", body="Edited outside.\n"))
        check(raises(au.ActionRefused, au.apply, folder, "changeset", request, p.plan_id, PHRASE),
              "a governing document edited outside makes the plan stale")
        check(raises(au.ActionRefused, au.plan, folder, "changeset", request)
              and raises(chs.ChangeSetError, alongside, folder, logical),
              "and an invalid context cannot have its governing context changed, or a change "
              "to it started")
        before = snapshot(folder)
        check(not raises(au.ActionRefused, do, folder, "add", {"title": "Still possible",
                                                              "body": "x\n"}),
              "candidates can still be filed while it is invalid")
        check(snapshot(folder) == before, "without touching the folder")
        write(folder, "notes.txt", b"x")
        check(raises(chs.ChangeSetError, withdrawal, folder, "authoritative/a.md"),
              "an unclean context cannot have a change to its governing context started")
        os.remove(os.path.join(folder, "notes.txt"))
        write(folder, "authoritative/b.md", doc_text("b", "Beta"))
        check(ac.examine(folder).valid
              and raises(chs.ChangeSetError, alongside, folder, "authoritative/a.md"),
              "a governing path is not a candidate")
        shutil.rmtree(folder)


def case_no_git() -> None:
    print("\nno Git")
    with isolated_private_state():
        repo = context(docs=())
        shutil.rmtree(repo)
        os.makedirs(repo)
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}

        def git(*args: str) -> str:
            return subprocess.run(["git", "-C", repo, *args], capture_output=True, env=env,
                                  check=True).stdout.decode()

        git("init", "-q")
        write(repo, "src/app.py", "print('project')\n")
        folder = os.path.join(repo, "context")
        os.makedirs(folder)
        write(folder, "authoritative/a.md", doc_text("a", "Alpha"))
        from tests.agent_context import generate
        generate(folder)
        git("add", "-A")
        git("commit", "-q", "-m", "initial")
        head = git("rev-parse", "HEAD")

        calls = []
        real = subprocess.run, subprocess.Popen

        def spy_run(args, *a, **k):
            calls.append(args)
            return real[0](args, *a, **k)

        subprocess.run = spy_run  # type: ignore[assignment]
        try:
            logical = add(folder, "Gamma rules")
            do(folder, "changeset", alongside(folder, logical))
        finally:
            subprocess.run = real[0]  # type: ignore[assignment]
        check(not any("git" in str(c[:1]) for c in calls), "authority actions run no Git command")
        check(git("rev-parse", "HEAD") == head, "no commit is made")
        check(git("diff", "--cached", "--name-only") == "", "nothing is staged")
        status = git("status", "--porcelain", "--untracked-files=all").split("\n")
        changed = sorted(line[3:] for line in status if line)
        check(changed == ["context/.agent-context.json", "context/AGENT-CONTEXT.md",
                          "context/authoritative/gamma-rules.md"],
              "only the Agent Context's own files changed, unstaged, for the person's Git")
        check(ac.examine(folder).valid, "and the context is valid in the checkout")
        shutil.rmtree(repo, ignore_errors=True)


STEPS_GRANT = ["after-journal", "temp:authoritative/gamma-rules.md",
               "replace:authoritative/gamma-rules.md", "replace:AGENT-CONTEXT.md",
               "replace:.agent-context.json", "before-validate", "before-commit"]


def _setup_grant():
    """A context, and a change set prefilled to grant one candidate alongside,
    as the request that applies it."""
    folder = context()
    logical = add(folder, "Gamma rules")
    cs = ps.PrivateState.default().for_context(folder)
    return folder, alongside(folder, logical), cs


def case_rollback() -> None:
    print("\nrollback in the same process")
    for step in STEPS_GRANT:
        with isolated_private_state():
            folder, request, cs = _setup_grant()
            before, private = snapshot(folder), private_docs(cs)

            def fault(name, step=step):
                if name == step:
                    raise RuntimeError("disk full")
            ok = raises(au.ApplyFailed, do, folder, "changeset", request, fault=fault)
            check(ok and snapshot(folder) == before and private_docs(cs) == private
                  and not os.path.exists(cs.path(ps.STAGING, tx.JOURNAL_KIND, tx.JOURNAL_FILE))
                  and chs.load(chs.Ctx(folder), request["draft_id"])["state"] == chs.ACTIVE,
                  f"a failure at {step} restores the folder and private state exactly, the draft "
                  "still a draft")
            shutil.rmtree(folder)
    with isolated_private_state():
        folder, request, cs = _setup_grant()
        before = snapshot(folder)

        def bad_validate(name):
            if name == "before-validate":
                with open(os.path.join(folder, "authoritative", "a.md"), "a") as fh:
                    fh.write("x")
        try:
            do(folder, "changeset", request, fault=bad_validate)
            failure = None
        except au.ApplyFailed as exc:
            failure = exc
        check(failure is not None and failure.restored,
              "a context that does not validate after writing fails")
        snap = snapshot(folder)
        check(not os.path.exists(os.path.join(folder, "authoritative", "gamma-rules.md"))
              and snap[os.path.join("AGENT-CONTEXT.md")] == before["AGENT-CONTEXT.md"],
              "and is rolled back")
        check(snap[os.path.join("authoritative", "a.md")] != before[os.path.join("authoritative",
                                                                                  "a.md")],
              "except a file someone else changed meanwhile, which is left as they left it")
        shutil.rmtree(folder)


def case_crash_recovery() -> None:
    print("\nrecovery after the process dies")
    for step in STEPS_GRANT:
        with isolated_private_state():
            folder, request, cs = _setup_grant()
            before, private = snapshot(folder), private_docs(cs)

            def fault(name, step=step):
                if name == step:
                    raise Crash()
            try:
                do(folder, "changeset", request, fault=fault)
            except Crash:
                pass
            journal = cs.path(ps.STAGING, tx.JOURNAL_KIND, tx.JOURNAL_FILE)
            exam = ac.examine(folder)
            check(tx.interrupted(cs) and os.path.exists(journal),
                  f"dying at {step} leaves the journal, so the transaction is known interrupted")
            if step in ("temp:authoritative/gamma-rules.md", "replace:authoritative/gamma-rules.md",
                        "replace:AGENT-CONTEXT.md"):
                check(not exam.valid, "  and the folder itself fails validation meanwhile")
            done = tx.recover(cs)
            check(done is not None and not done["unrestored"] and snapshot(folder) == before
                  and private_docs(cs) == private and not os.path.exists(journal),
                  "  recovery restores the folder and private state exactly")
            shutil.rmtree(folder)

    with isolated_private_state():
        folder, request, cs = _setup_grant()
        shown = au.plan(folder, "changeset", request)
        try:
            do(folder, "changeset", request,
               fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "replace:AGENT-CONTEXT.md"
               else None)
        except Crash:
            pass
        result = au.apply(folder, "changeset", shown.request, shown.plan_id, PHRASE)
        check(result["recovered"] and not result["recovered"]["unrestored"]
              and ac.examine(folder).valid,
              "applying a plan shown earlier recovers the interrupted write first, then applies")
        shutil.rmtree(folder)

    with isolated_private_state():
        folder, request, cs = _setup_grant()
        try:
            do(folder, "changeset", request,
               fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "replace:AGENT-CONTEXT.md"
               else None)
        except Crash:
            pass
        check(raises(au.ActionRefused, au.plan, folder, "changeset", request),
              "planning does not recover: it sees the interrupted state and refuses")
        check(au.recover(folder) is not None and au.recover(folder) is None
              and not raises(au.ActionRefused, do, folder, "changeset", request),
              "recovering, as opening the context will, makes the next action possible")
        shutil.rmtree(folder)

    with isolated_private_state():
        folder, request, cs = _setup_grant()
        try:
            do(folder, "changeset", request,
               fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "before-validate" else None)
        except Crash:
            pass
        write(folder, "AGENT-CONTEXT.md", "A person's own edit.\n")
        done = tx.recover(cs)
        with open(os.path.join(folder, "AGENT-CONTEXT.md"), "rb") as fh:
            kept = fh.read()
        check(done["unrestored"] == ["AGENT-CONTEXT.md"] and kept == b"A person's own edit.\n",
              "recovery never overwrites a file that changed after the interrupted write")
        shutil.rmtree(folder)

    with isolated_private_state() as root:
        folder, request, cs = _setup_grant()
        try:
            do(folder, "changeset", request,
               fault=lambda n: (_ for _ in ()).throw(Crash())
               if n == "temp:authoritative/gamma-rules.md" else None)
        except Crash:
            pass
        leftovers = [n for n in os.listdir(os.path.join(folder, "authoritative"))
                     if n.startswith(ac.TRANSACTION_PREFIX)]
        shutil.rmtree(root)
        exam = ac.examine(folder)
        check(leftovers and exam.state == ac.UNCLEAN
              and any("interrupted Charter write" in i["message"]
                      for i in exam.errors),
              "with private state lost, the leftover temporary file is a named stray")
        check(raises(chs.ChangeSetError, withdrawal, folder, "authoritative/a.md"),
              "governing changes are refused until a person deals with it")
        tx.recover(ps.PrivateState.default().for_context(folder))
        check(all(os.path.exists(os.path.join(folder, "authoritative", n)) for n in leftovers),
              "and nothing guesses: the leftover is not deleted")
        shutil.rmtree(folder)

    with isolated_private_state():
        folder, request, cs = _setup_grant()
        journal = cs.path(ps.STAGING, tx.JOURNAL_KIND, tx.JOURNAL_FILE)
        with open(journal, "w") as fh:
            fh.write("{broken")
        before = snapshot(folder)
        check(raises(tx.TransactionError, tx.recover, cs) and snapshot(folder) == before,
              "an unreadable journal is not guessed at, and nothing is touched")
        shutil.rmtree(folder)


def _replace_setup():
    folder = context()
    cs = ps.PrivateState.default().for_context(folder)
    do(folder, "revise", {"path": "authoritative/a.md"})
    revision = cs.candidates()[0]
    do(folder, "edit-candidate", {"candidate": revision, "title": "Alpha 2", "body": "v2\n"})
    return folder, cs, "replace", seeded(folder, {"document": "authoritative/a.md",
                                                   "outcome": "replace", "candidate": revision})


def _withdraw_setup():
    from tests.agent_context import generate
    folder = context()
    write(folder, "authoritative/area/deep/d.md", doc_text("d", "Delta"))
    generate(folder)
    cs = ps.PrivateState.default().for_context(folder)
    return folder, cs, "withdraw", withdrawal(folder, "authoritative/area/deep/d.md")


def _step(name: str) -> str:
    """A transaction step, the same in every run: a change set's own record
    is named by its draft id, which each run makes afresh."""
    return re.sub(r"changesets/[0-9a-f]{16}\.json", "changesets/<draft>.json", name)


def case_crash_at_every_step() -> None:
    print("\nrecovery at every step of a one-document replace and of a nested withdraw")
    for setup in (_replace_setup, _withdraw_setup):
        with isolated_private_state():
            folder, cs, kind, request = setup()
            steps = []
            p = au.plan(folder, "changeset", request)
            au.apply(folder, "changeset", request, p.plan_id, PHRASE,
                     fault=lambda name: steps.append(_step(name)))
            shutil.rmtree(folder)
        check("replace:changesets/<draft>.json" in steps,
              f"{kind}: the change set's receipt is one of the steps")
        for step in steps:
            with isolated_private_state():
                folder, cs, kind, request = setup()
                before, private = snapshot(folder), private_docs(cs)
                draft = chs.load(chs.Ctx(folder), request["draft_id"])

                def fault(name, step=step):
                    if _step(name) == step:
                        raise Crash()
                try:
                    do(folder, "changeset", request, fault=fault)
                except Crash:
                    pass
                done = tx.recover(cs) if tx.interrupted(cs) else {"unrestored": []}
                if step == "after-commit":
                    # Past the commit point the action is complete, and stays so.
                    check(not tx.interrupted(cs) and snapshot(folder) != before
                          and ac.examine(folder).valid,
                          f"{kind}: dying just after it commits leaves it complete")
                else:
                    check(not done["unrestored"] and snapshot(folder) == before
                          and private_docs(cs) == private and ac.examine(folder).valid
                          and chs.load(chs.Ctx(folder), request["draft_id"]) == draft,
                          f"{kind}: dying at {step} is fully recovered, the draft still a draft")
                shutil.rmtree(folder)


def case_tooling_files_in_subfolders() -> None:
    print("\ntooling files in subfolders")
    from tests.agent_context import generate
    with isolated_private_state():
        folder = context()
        write(folder, "authoritative/area/deep/d.md", doc_text("d", "Delta"))
        write(folder, "authoritative/area/deep/.DS_Store", b"finder")
        write(folder, "authoritative/area/desktop.ini", b"[shell]")
        generate(folder)
        check(ac.examine(folder).valid, "tooling files beside a governing document are tolerated")
        do(folder, "changeset", withdrawal(folder, "authoritative/area/deep/d.md"))
        exam = ac.examine(folder)
        check(exam.valid and "authoritative/area/deep/d.md" not in exam.hashes,
              "withdrawing the last document in a subfolder with tooling files succeeds")
        check(os.path.isfile(os.path.join(folder, "authoritative", "area", "deep", ".DS_Store"))
              and os.path.isfile(os.path.join(folder, "authoritative", "area", "desktop.ini")),
              "the tooling files and their folders are left where they are")

        write(folder, "authoritative/other/e.md", doc_text("e", "Epsilon"))
        write(folder, "authoritative/other/notes.txt", b"mine")
        generate(folder)
        check(ac.examine(folder).state == ac.UNCLEAN,
              "an arbitrary file in a subfolder still makes the context unclean")
        shutil.rmtree(folder)


def case_path_limit() -> None:
    print("\nthe platform path limit")
    with isolated_private_state():
        folder = context()
        logical = add(folder, "Gamma rules")
        request = alongside(folder, logical)
        before = snapshot(folder)
        target = os.path.join(folder, "authoritative", "gamma-rules.md")
        real = tx.path_limit
        # A limit the target itself fits within, but its temporary file does not.
        tx.path_limit = lambda: len(target) + 2  # type: ignore[assignment]
        try:
            p = au.plan(folder, "changeset", request)
            check(p.blocked and any("too long" in m and "gamma-rules.md" in m and
                                    "shorter" in m for m in p.problems),
                  "an action whose temporary file would not fit is blocked in its preview")
            check(raises(au.ActionRefused, au.apply, folder, "changeset", request, p.plan_id,
                         PHRASE), "and refused when applied")
            check(raises(tx.TransactionError, tx.Transaction(
                ps.PrivateState.default().for_context(folder),
                [tx.Write(tx.CONTEXT, "authoritative/gamma-rules.md", "x")]).run),
                "the transaction itself refuses before writing")
        finally:
            tx.path_limit = real  # type: ignore[assignment]
        cs = ps.PrivateState.default().for_context(folder)
        backups = cs.path(ps.STAGING, tx.JOURNAL_KIND, tx.BACKUPS)
        check(snapshot(folder) == before and logical in cs.candidates()
              and not tx.interrupted(cs)
              and (not os.path.isdir(backups) or not os.listdir(backups)),
              "nothing was written: no file, journal or backup")
        empty = context(docs=())
        first = alongside(empty, add(empty, "First"))
        real_dir = tx.dir_limit
        tx.dir_limit = lambda: len(os.path.join(empty, "authoritative")) - 1  # type: ignore
        try:
            p = au.plan(empty, "changeset", first)
            check(p.blocked and any("create the folder" in m for m in p.problems),
                  "a folder it would have to create beyond the limit is refused up front too")
        finally:
            tx.dir_limit = real_dir  # type: ignore[assignment]
        shutil.rmtree(empty)
        name = tx._temp_name("f" * tx._TXID_LENGTH, 99, restore=True)
        check(len(name) <= 24 and name.startswith(ac.TRANSACTION_PREFIX),
              f"the reserved temporary name is short ({len(name)} characters at most here)")
        shutil.rmtree(folder)


def case_earlier_name_temporary_files() -> None:
    print("\ntemporary files from Agent Context Manager, Charter's earlier name")
    import json
    with isolated_private_state():
        folder = context()
        check(ac.TRANSACTION_PREFIX == ".charter-txn-"
              and tx._temp_name("abc123", 0).startswith(".charter-txn-"),
              "new writes use Charter's reserved temporary name, `.charter-txn-`")
        for rel in (".acm-txn-1a2b3c-0", "authoritative/.acm-txn-1a2b3c-1r"):
            write(folder, rel, b"half-written")
            exam = ac.examine(folder)
            check(not exam.valid and any(i["path"] == rel and "interrupted Charter write" in i["message"]
                                         for i in exam.issues),
                  f"a leftover `{rel}` from the earlier name is still recognized, and agents are refused")
            os.remove(os.path.join(folder, *rel.split("/")))

        # A journal begun under the earlier name still rolls back: its own names are recorded.
        cs = ps.PrivateState.default().for_context(folder)
        target = os.path.join(folder, "authoritative", "a.md")
        original = read(folder, "authoritative/a.md")
        jdir = cs.staging_dir(tx.JOURNAL_KIND)
        os.makedirs(os.path.join(jdir, tx.BACKUPS, "abc123"), exist_ok=True)
        with open(os.path.join(jdir, tx.BACKUPS, "abc123", "0"), "wb") as fh:
            fh.write(original)
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Half applied.\n"))
        write(folder, "authoritative/.acm-txn-abc123-0", b"half-written")
        new = read(folder, "authoritative/a.md")
        journal = {"version": tx.JOURNAL_VERSION, "id": "abc123", "entries": [{
            "root": tx.CONTEXT, "path": "authoritative/a.md", "old": tx._sha(original),
            "new": tx._sha(new), "temp": ".acm-txn-abc123-0", "restore_temp": ".acm-txn-abc123-0r",
            "backup": "backups/abc123/0"}], "pruned_dirs": [], "created_dirs": []}
        with open(os.path.join(jdir, tx.JOURNAL_FILE), "w", encoding="utf-8") as fh:
            json.dump(journal, fh)
        check(tx.interrupted(cs), "an earlier-name write left a journal")
        tx.recover(cs)
        check(read(folder, "authoritative/a.md") == original and not tx.interrupted(cs)
              and not os.path.exists(os.path.join(folder, "authoritative", ".acm-txn-abc123-0"))
              and ac.examine(folder).valid,
              "recovery rolls it back and removes its `.acm-txn-` temporary file")

        # A journal naming anything but a reserved temporary file is not trusted.
        for bad in ("a.md", "../a.md", "sub/.charter-txn-x-0"):
            journal["entries"][0].update(temp=bad, restore_temp=".charter-txn-abc123-0r")
            with open(os.path.join(jdir, tx.JOURNAL_FILE), "w", encoding="utf-8") as fh:
                json.dump(journal, fh)
            check(raises(tx.TransactionError, tx.recover, cs) and os.path.isfile(target),
                  f"a journal naming `{bad}` as a temporary file is refused; nothing is deleted")
        os.remove(os.path.join(jdir, tx.JOURNAL_FILE))
        shutil.rmtree(folder)


def case_transaction_bounds() -> None:
    print("\nwhat a transaction may write")
    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        for rel in ("notes.txt", "authoritative/x.txt", "../outside.md", "AGENTS.md",
                    "authoritative/.charter-txn-1a2b3c-0", "authoritative/.acm-txn-1a2b3c-0",
                    "authoritative/../a.md"):
            check(raises(tx.TransactionError, tx.Transaction(cs, [tx.Write(tx.CONTEXT, rel, "x")]).run),
                  f"`{rel}` is not written")
        check(raises(tx.TransactionError,
                     tx.Transaction(cs, [tx.Write(tx.PRIVATE, "../escape.md", "x")]).run),
              "nor anything outside private state")
        shutil.rmtree(folder)


def case_revision_origin() -> None:
    print("\na candidate made with Revise… knows the one document it came from")
    from app import console
    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        do(folder, "revise", {"path": "authoritative/a.md", "title": "Alpha revised"})
        revision = next(c for c in cs.candidates() if meta_of(cs.read_candidate(c))["title"] == "Alpha revised")
        check(meta_of(cs.read_candidate(revision)).get(au.REVISES) == "a",
              "Revise records the originating governing document's id with the candidate")
        do(folder, "edit-candidate", {"candidate": revision, "body": "Alpha v2.\n"})
        check(meta_of(cs.read_candidate(revision)).get(au.REVISES) == "a",
              "editing the candidate keeps it")
        plain = add(folder, "Plain addition")
        check(au.REVISES not in meta_of(cs.read_candidate(plain)),
              "Create candidate records no predecessor")
        do(folder, "changeset", withdrawal(folder, "authoritative/b.md"))
        withdrawn = next(c for c in cs.candidates() if meta_of(cs.read_candidate(c))["title"] == "Beta")
        check(au.REVISES not in meta_of(cs.read_candidate(withdrawn)),
              "a withdrawn document returned to candidate status records none")

        from app import agent_proposals as apx
        filed = apx.file(folder, {"agent": "codex", "operation": "create",
                                  "target_path": "authority-candidates/from-agent.md",
                                  "reason": "A rule an agent proposes.", "proposed_body": "# From agent\n\nRule.\n"})
        do(folder, "accept-proposal", {"proposal_id": filed["proposal_id"]})
        proposed = "authority-candidates/from-agent.md"
        check(proposed in cs.candidates() and au.REVISES not in meta_of(cs.read_candidate(proposed)),
              "an accepted Agent Proposal records no predecessor")

        session = console.Session(folder)
        listed = {d["path"]: d for d in console.state(session)["documents"] if d["kind"] == "candidate"}
        check(listed[revision]["revises_path"] == "authoritative/a.md"
              and listed[plain]["revises_path"] == "" and listed[withdrawn]["revises_path"] == ""
              and listed[proposed]["revises_path"] == "",
              "the console resolves it to the governing path it still has; others have none")

        request = seeded(folder, {"candidate": revision, "decision": "replace",
                                  "target": "authoritative/a.md"})
        p = au.plan(folder, "changeset", request)
        check(p.governing_change and p.confirm_phrase == PHRASE,
              "replacing with it is still an ordinary governing change, previewed and confirmed with the phrase")
        check(raises(au.ActionRefused, au.apply, folder, "changeset", request, p.plan_id, True)
              and any(d.path == "authoritative/a.md" and d.id == "a" for d in ac.examine(folder).documents),
              "it is not applied without the typed phrase")
        au.apply(folder, "changeset", request, p.plan_id, PHRASE)
        new = next(d for d in ac.examine(folder).documents if d.path == "authoritative/a.md")
        check(au.REVISES not in new.meta and au.REVISES not in ac.examine(folder).texts["authoritative/a.md"],
              "once it governs, the note is gone from the governing document")

        do(folder, "revise", {"path": "authoritative/a.md", "title": "Alpha again"})
        again = next(c for c in cs.candidates() if meta_of(cs.read_candidate(c))["title"] == "Alpha again")
        do(folder, "changeset", alongside(folder, again))
        granted = [d for d in ac.examine(folder).documents if d.title == "Alpha again"]
        check(granted and au.REVISES not in granted[0].meta and ac.examine(folder).valid,
              "governing alongside drops it too")

        do(folder, "revise", {"path": "authoritative/a.md", "title": "Orphaned"})
        orphan = next(c for c in cs.candidates() if meta_of(cs.read_candidate(c))["title"] == "Orphaned")
        do(folder, "changeset", withdrawal(folder, "authoritative/a.md"))
        listed = {d["path"]: d for d in console.state(session)["documents"] if d["kind"] == "candidate"}
        check(listed[orphan]["revises_path"] == "",
              "when the originating document no longer governs, there is no known predecessor")
        shutil.rmtree(folder)


def case_no_direct_routes() -> None:
    print("\ngoverning context changes only through a change set")
    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        logical = add(folder, "Gamma rules")
        before, candidates = snapshot(folder), cs.candidates()
        for kind, request in (("grant", {"candidate": logical}),
                              ("replace", {"candidate": logical, "replaces": "authoritative/a.md"}),
                              ("withdraw", {"path": "authoritative/a.md"})):
            check(kind not in au.KINDS and raises(au.ActionRefused, au.plan, folder, kind, request)
                  and raises(au.ActionRefused, au.apply, folder, kind, request, "0" * 20, PHRASE),
                  f"there is no direct `{kind}` action to plan or apply")
        check(au.GOVERNING_KINDS == ("changeset",), "the change set is the one governing action")
        check(snapshot(folder) == before and cs.candidates() == candidates, "and nothing was written")
        shutil.rmtree(folder)


def case_front_matter_in_text() -> None:
    print("\na candidate never holds a second front-matter block")
    import base64
    from app import console
    from app.docs import leading_front_matter
    block = "---\nid: legacy\nauthority: authoritative\nstatus: active\n---\n\n"
    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        before, candidates = snapshot(folder), cs.candidates()
        for what, body in (("a front-matter block", block + "Text.\n"),
                           ("one after blank lines", "\n\n" + block + "Text.\n"),
                           ("one after a byte-order mark, with CRLF", "﻿" + block.replace("\n", "\r\n") + "Text.\n")):
            check(raises(au.ActionRefused, au.plan, folder, "add", {"title": "Sent directly", "body": body}),
                  f"Add, sent straight to the server, refuses text beginning with {what}")
        check(raises(au.ActionRefused, au.plan, folder, "revise", {"path": "authoritative/a.md", "body": block + "x\n"}),
              "so does Revise")
        check(snapshot(folder) == before and cs.candidates() == candidates, "and nothing is written")
        p = au.plan(folder, "add", {"title": "Rule first", "body": "---\nA thematic break, then prose.\n---\n"})
        check(not p.blocked, "text that only opens with a thematic break is ordinary Markdown")

        session = console.Session(folder)
        exported = ('---\nid: legacy-supplier-0042\ntitle: "Supplier policy"\nstatus: active\nauthority: authoritative\n'
                    'scope: "Supplier choice and onboarding."\nsource: "Old wiki"\ncreated: 2026-01-02\n'
                    'updated: 2026-03-04\nsupersedes:\n  - supplier-policy-v1\nsuperseded_by: []\n---\n\n'
                    '# Supplier policy\n\nChoose suppliers with care.\n')
        staged = console.stage(session, {"filename": "supplier-policy.md",
                                         "content_b64": base64.b64encode(exported.encode()).decode()})
        request = {"title": staged["suggested_title"], "scope": staged["suggested_scope"],
                   "body": staged["markdown"], "source": "supplier-policy.md (sha256 0123456789ab)"}
        do(folder, "add", request)
        logical = next(c for c in cs.candidates()
                                  if meta_of(cs.read_candidate(c))["title"] == "Supplier policy")
        text = cs.read_candidate(logical)
        meta, body = parse_front_matter(text)
        check(text.count("\n---\n") == 1 and text.startswith("---\n") and leading_front_matter(body) is None,
              "staged and filed, the candidate has exactly one front-matter block, its own")
        check(meta["title"] == "Supplier policy" and meta["scope"] == "Supplier choice and onboarding."
              and meta["id"] != "legacy-supplier-0042" and meta["authority"] == "non-authoritative"
              and meta["created"] != "2026-01-02" and "supersedes" not in meta and "superseded_by" not in meta
              and meta["source"].startswith("supplier-policy.md"),
              "its title and scope came from the file; its identity, authority, dates and lineage did not")
        check("authority: authoritative" not in body and "supplier-policy-v1" not in body,
              "and none of the file's metadata survives as text")

        # A candidate filed before conversion removed front matter.
        do(folder, "add", {"title": "Old rule", "scope": "Old things.", "body": "Placeholder.\n"})
        old = next(c for c in cs.candidates() if meta_of(cs.read_candidate(c))["title"] == "Old rule")
        legacy = cs.read_candidate(old).replace("Placeholder.\n", block + "Old rule text.\n")
        with open(cs.candidate_file(old), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(legacy)
        draft = console.draft(session, {"path": old})
        check(draft["body"] == "Old rule text.\n"
              and draft["legacy_front_matter"] == {"removed": True, "keys": ["id", "authority", "status"]},
              "Edit starts from its text without the old block, and says which keys it held")
        check(cs.read_candidate(old) == legacy, "opening Edit changes nothing in private state")
        do(folder, "edit-candidate", {"candidate": old, "scope": "Old things, narrower."})
        kept = cs.read_candidate(old)
        check(meta_of(kept)["scope"] == "Old things, narrower." and block in kept,
              "a scope-only edit works, leaving the text as it was")
        check(raises(au.ActionRefused, au.plan, folder, "edit-candidate",
                     {"candidate": old, "body": parse_front_matter(kept)[1].lstrip("\n")}),
              "saving the text with the old block still at its top is refused")
        draft = console.draft(session, {"path": old})
        p = au.plan(folder, "edit-candidate", {"candidate": old, "title": draft["title"], "scope": draft["scope"],
                                               "body": draft["body"]})
        diff = p.changes[0].diff()
        check(not p.blocked and "-id: legacy" in diff and "-authority: authoritative" in diff,
              "saving the form as it started previews the removal in the diff")
        au.apply(folder, "edit-candidate", p.request, p.plan_id, True)
        saved = cs.read_candidate(old)
        check(saved.count("\n---\n") == 1 and leading_front_matter(parse_front_matter(saved)[1]) is None
              and saved.endswith("Old rule text.\n") and console.draft(session, {"path": old})["legacy_front_matter"] is None,
              "confirmed, the candidate keeps one front-matter block, its own")
        shutil.rmtree(folder)


def case_preview_survives_midnight() -> None:
    print("\na preview still applies after local midnight; dates are the day of writing")
    from app import agent_proposals as apx
    from app import changeset as chs
    from tests.agent_context import generate
    day1, day2 = "2026-10-07", "2026-10-08"
    real_today = au.today

    def at(day: str) -> None:
        au.today = lambda: day

    def dated(p: au.Plan, day: str) -> bool:
        return any(c.new and f"updated: {day}" in c.new for c in p.changes)

    def across(kind: str, request: dict, confirm=True) -> au.Plan:
        """Preview on day 1, apply the same preview on day 2."""
        at(day1)
        shown = au.plan(folder, kind, request)
        at(day2)
        again = au.plan(folder, kind, request)
        check(again.plan_id == shown.plan_id and again.notes == shown.notes,
              f"{kind}: the same preview, with the same notes, on the next day")
        au.apply(folder, kind, request, shown.plan_id, confirm)
        return shown

    def noted(p: au.Plan, kind: str, note: str = au.APPLY_DATE_NOTE) -> None:
        check(p.notes.count(note) == 1 and dated(p, day1),
              f"{kind}: the preview shows the preview day, and says once that dates are "
              "assigned when it is applied")

    def candidate_titled(title: str) -> str:
        return next(c for c in cs.candidates() if meta_of(cs.read_candidate(c))["title"] == title)

    try:
        with isolated_private_state():
            folder = context(docs=(("a.md", "Alpha"), ("b.md", "Beta"), ("c.md", "Gamma")))
            cs = ps.PrivateState.default().for_context(folder)
            at(day1)
            to_edit = add(folder, "Edit me", "Edit scope.")
            to_retire = add(folder, "Retire me")
            to_amend = add(folder, "Amend me", "Amend scope.", "Amend body.\n")
            to_drop = add(folder, "Drop me")

            p = across("add", {"title": "Fresh", "scope": "Fresh.", "body": "Fresh.\n"})
            noted(p, "add")
            m = meta_of(cs.read_candidate(candidate_titled("Fresh")))
            check(m["created"] == day2 and m["updated"] == day2, "add: the candidate is dated the apply day")

            p = across("revise", {"path": "authoritative/a.md", "title": "Alpha next"})
            noted(p, "revise")
            m = meta_of(cs.read_candidate(candidate_titled("Alpha next")))
            check(m["created"] == day2 and m["updated"] == day2, "revise: the candidate is dated the apply day")

            p = across("edit-candidate", {"candidate": to_edit, "body": "Edited.\n"})
            noted(p, "edit-candidate")
            m = meta_of(cs.read_candidate(to_edit))
            check(m["created"] == day1 and m["updated"] == day2,
                  "edit: the candidate keeps its creation day and is updated on the apply day")

            p = across("retire", {"candidate": to_retire})
            check(au.APPLY_DATE_NOTE not in p.notes and dated(p, day1),
                  "retire: the preview shows only the retirement, with no note about candidate dates")
            check(meta_of(cs.read_archived("retire-me.md"))["updated"] == day2,
                  "retire: the archived candidate is dated the apply day")

            # Every Agent Proposal decision.
            def proposal(**fields) -> str:
                result = apx.file(folder, dict({"agent": "codex", "reason": "r"}, **fields))
                assert result["result"] == "pending", result
                return result["proposal_id"]

            def base(logical: str) -> str:
                return ac.sha256_text(cs.read_candidate(logical))

            created = proposal(operation="create", target_path="authority-candidates/proposed.md",
                               proposed_body="# Proposed\n\nProposed body.\n")
            p = across("accept-proposal", {"proposal_id": created})
            noted(p, "accept a create")
            m = meta_of(cs.read_candidate("authority-candidates/proposed.md"))
            check(m["created"] == day2 and m["updated"] == day2, "accept a create: dated the apply day")

            gov_sha = ac.sha256_text(ac.examine(folder).texts["authoritative/b.md"])
            amended_gov = proposal(operation="amend", target_path="authoritative/b.md", base_sha256=gov_sha,
                                   replacements=[{"find": "Body.", "replace": "Beta, amended."}],
                                   proposed_meta={"title": "Beta amended", "scope": "Beta."})
            p = across("accept-proposal", {"proposal_id": amended_gov})
            noted(p, "accept an amendment of a governing document")
            m = meta_of(cs.read_candidate(candidate_titled("Beta amended")))
            check(m["created"] == day2 and m["updated"] == day2,
                  "accept an amendment of a governing document: its new candidate is dated the apply day")

            amended_cand = proposal(operation="amend", target_path=to_amend, base_sha256=base(to_amend),
                                    proposed_body="Amended by proposal.\n")
            p = across("accept-proposal", {"proposal_id": amended_cand})
            noted(p, "accept an amendment of a candidate")
            m = meta_of(cs.read_candidate(to_amend))
            check(m["created"] == day1 and m["updated"] == day2,
                  "accept an amendment of a candidate: updated on the apply day")

            retired = proposal(operation="retire", target_path=to_drop, base_sha256=base(to_drop))
            p = across("accept-proposal", {"proposal_id": retired})
            noted(p, "accept a retirement")
            check(meta_of(cs.read_archived("drop-me.md"))["updated"] == day2,
                  "accept a retirement: the archived candidate is dated the apply day")

            rejected = proposal(operation="create", target_path="authority-candidates/unwanted.md",
                                proposed_body="Unwanted.\n")
            p = across("reject-proposal", {"proposal_id": rejected, "reason": "Not needed."})
            check(au.APPLY_DATE_NOTE not in p.notes, "reject: writes no date, so no date note")
            check(rejected not in {r["proposal_id"] for r in apx.listing(folder)["pending"]},
                  "reject: the preview applies on the next day")

            # A coordinated change set: replace with a revision, withdraw and govern alongside.
            at(day1)
            revision = add(folder, "Alpha two", "Alpha, revised.")
            newcomer = add(folder, "Delta", "Delta things.")
            ctx = chs.Ctx(folder)
            draft = chs.create(ctx, "Across midnight")
            draft = chs.update(ctx, draft["id"], draft["revision"], {
                "candidates": [revision, newcomer],
                "decisions": {revision: {"decision": "replace", "target": "authoritative/a.md"},
                              newcomer: {"decision": "govern-alongside"}},
                "withdrawals": ["authoritative/c.md"]})
            request = {"draft_id": draft["id"], "draft_revision": draft["revision"]}
            p = across("changeset", request, PHRASE)
            check(not any("dates are assigned" in n for n in p.notes) and dated(p, day1),
                  "change set: the preview shows the preview day, with no note about when dates are assigned")
            exam = ac.examine(folder)
            governing = {d.path: d for d in exam.documents}
            check(exam.valid and governing["authoritative/a.md"].meta["updated"] == day2
                  and governing["authoritative/delta.md"].meta["updated"] == day2,
                  "change set: the context validates, and its new governing versions are dated the apply day")
            archived = [n for n in cs.archived() if n.startswith("a-superseded")]
            check(archived and meta_of(cs.read_archived(archived[0]))["updated"] == day2,
                  "change set: the replaced version is archived with the apply day")
            check(meta_of(cs.read_candidate("authority-candidates/c.md"))["updated"] == day2,
                  "change set: the withdrawn document is a candidate dated the apply day")
            check(chs.APPLIED_AT not in open(cs.path(*chs.record_path(draft["id"]).split("/")),
                                             encoding="utf-8").read(),
                  "change set: its receipt is still timed when written")

            # Real changes after the preview still refuse safely.
            at(day1)
            target = add(folder, "Still watched", "Watched.")
            shown = au.plan(folder, "edit-candidate", {"candidate": target, "scope": "Changed."})
            at(day2)
            do(folder, "edit-candidate", {"candidate": target, "body": "Changed meanwhile.\n"})
            text = cs.read_candidate(target)
            check(raises(au.StalePlan, au.apply, folder, "edit-candidate", shown.request, shown.plan_id, True)
                  and cs.read_candidate(target) == text,
                  "a candidate changed after the preview is still stale on the next day, and nothing is written")

            at(day1)
            shown = au.plan(folder, "revise", {"path": "authoritative/b.md", "title": "Beta again"})
            write(folder, "authoritative/b.md", doc_text("b", "Beta", body="Edited by a person.\n"))
            generate(folder)
            at(day2)
            before = set(cs.candidates())
            check(raises(au.StalePlan, au.apply, folder, "revise", shown.request, shown.plan_id, True)
                  and set(cs.candidates()) == before,
                  "a governing document changed after the preview is still stale, and nothing is written")

            at(day1)
            spare = add(folder, "Spare", "Spare.")
            draft = chs.create(ctx, "Watched set")
            draft = chs.update(ctx, draft["id"], draft["revision"],
                               {"candidates": [spare], "decisions": {spare: {"decision": "govern-alongside"}}})
            request = {"draft_id": draft["id"], "draft_revision": draft["revision"]}
            shown = au.plan(folder, "changeset", request)
            at(day2)
            do(folder, "edit-candidate", {"candidate": spare, "scope": "Spare, changed."})
            before = snapshot(folder)
            check(raises(au.ActionRefused, au.apply, folder, "changeset", request, shown.plan_id, PHRASE)
                  and snapshot(folder) == before,
                  "a change set whose candidate changed after the preview is refused on the next day, "
                  "and the Agent Context is unchanged")
            shutil.rmtree(folder)
    finally:
        au.today = real_today


# --- concurrent edits, hostile journals, bounded names, post-commit follow-up -----------

def _jdir(cs: ps.ContextState) -> str:
    return cs.path(ps.STAGING, tx.JOURNAL_KIND)


def _no_leftovers(cs: ps.ContextState) -> bool:
    """No journal, and no backup left behind."""
    backups = os.path.join(_jdir(cs), tx.BACKUPS)
    return not tx.interrupted(cs) and (not os.path.isdir(backups) or not os.listdir(backups))


@contextlib.contextmanager
def _before_transaction(meddle):
    """Run `meddle` after `apply` has planned, just before the transaction starts."""
    real = tx.Transaction.run

    def run(self):
        meddle()
        return real(self)
    tx.Transaction.run = run
    try:
        yield
    finally:
        tx.Transaction.run = real


def _stale(fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except au.StalePlan as exc:
        return str(exc)
    return ""


def case_concurrent_edits() -> None:
    print("\na target changed between planning and writing is refused, never overwritten")
    with isolated_private_state():
        # Between plan and transaction: the candidate the replace consumes.
        folder, cs, kind, request = _replace_setup()
        revision = chs.rows(chs.load(chs.Ctx(folder), request["draft_id"]))[0][
            "authoritative/a.md"]["candidate"]
        before = snapshot(folder)
        edited = cs.read_candidate(revision) + "A person's late edit.\n"

        def meddle():
            with open(cs.candidate_file(revision), "w", encoding="utf-8", newline="\n") as fh:
                fh.write(edited)
        with _before_transaction(meddle):
            p = au.plan(folder, "changeset", request)
            said = _stale(au.apply, folder, "changeset", request, p.plan_id, PHRASE)
        check(said and revision in said and "nothing was changed" in said,
              "a candidate edited after planning: a stale refusal naming it")
        check(snapshot(folder) == before and cs.read_candidate(revision) == edited
              and _no_leftovers(cs)
              and chs.load(chs.Ctx(folder), request["draft_id"])["state"] == chs.ACTIVE,
              "  the folder is unchanged, the edit kept, no journal or backup left, the draft a draft")
        shutil.rmtree(folder)

    with isolated_private_state():
        # After the journal, before the first destructive write: a governed target.
        folder, cs, kind, request = _replace_setup()
        private = private_docs(cs)
        mine = doc_text("a", "Alpha", body="Edited by a person meanwhile.\n").encode("utf-8")

        def fault(step):
            if step == "after-journal":
                write(folder, "authoritative/a.md", mine)
        expected = dict(snapshot(folder))
        expected[os.path.join("authoritative", "a.md")] = mine
        said = _stale(do, folder, "changeset", request, fault=fault)
        check(said and "authoritative/a.md" in said,
              "a governing document edited after the journal: refused before anything is replaced")
        check(snapshot(folder) == expected and private_docs(cs) == private and _no_leftovers(cs),
              "  only the person's edit is there: nothing replaced, temporary files and backups gone")
        shutil.rmtree(folder)

    with isolated_private_state():
        # Part-way through replacing: a later target changes after an earlier was replaced.
        folder, request, cs = _setup_grant()
        before, private = snapshot(folder), private_docs(cs)
        record = cs.path(*chs.record_path(request["draft_id"]).split("/"))
        with open(record, "rb") as fh:
            draft_record = fh.read()
        mine = b"A person's own map.\n"
        steps = []

        def fault(step):
            if step.startswith("replace:") and not steps:
                steps.append(step)
                write(folder, "AGENT-CONTEXT.md", mine)
        said = _stale(do, folder, "changeset", request, fault=fault)
        with open(record, "rb") as fh:
            record_after = fh.read()
        expected = dict(before)
        expected["AGENT-CONTEXT.md"] = mine
        check(said and "AGENT-CONTEXT.md" in said and steps,
              "a target changed after an earlier one was replaced: refused")
        check(snapshot(folder) == expected and private_docs(cs) == private
              and record_after == draft_record and _no_leftovers(cs),
              "  what was replaced is restored from its backup; the person's file is left as they wrote it")
        shutil.rmtree(folder)

    with isolated_private_state():
        # A name the plan creates is taken meanwhile: the archive of the replaced version.
        folder, cs, kind, request = _replace_setup()
        p = au.plan(folder, "changeset", request)
        archived = [c.path for c in p.changes if c.path.startswith(ps.ARCHIVE + "/")]
        theirs = b"---\nid: theirs\ntitle: Theirs\n---\nNot Charter's.\n"

        def meddle():
            with open(cs.path(*archived[0].split("/")), "wb") as fh:
                fh.write(theirs)
        before = snapshot(folder)
        with _before_transaction(meddle):
            said = _stale(au.apply, folder, "changeset", request, p.plan_id, PHRASE)
        with open(cs.path(*archived[0].split("/")), "rb") as fh:
            kept = fh.read()
        check(said and kept == theirs and snapshot(folder) == before and _no_leftovers(cs),
              "a file the plan would create appears meanwhile: refused, and it is not overwritten")
        shutil.rmtree(folder)

    with isolated_private_state():
        # The change set's own record changes meanwhile.
        folder, request, cs = _setup_grant()
        p = au.plan(folder, "changeset", request)
        record = cs.path(*chs.record_path(request["draft_id"]).split("/"))

        def meddle():
            with open(record, "ab") as fh:
                fh.write(b"\n")
            with open(record, "rb") as fh:
                meddle.kept = fh.read()
        before = snapshot(folder)
        with _before_transaction(meddle):
            said = _stale(au.apply, folder, "changeset", request, p.plan_id, PHRASE)
        with open(record, "rb") as fh:
            now = fh.read()
        check(said and now == meddle.kept and snapshot(folder) == before and _no_leftovers(cs),
              "the change set's record changed meanwhile: refused, and left as it is")
        shutil.rmtree(folder)

    with isolated_private_state():
        # A governing document the plan keeps, but relies on, changes before the first write.
        folder, cs, kind, request = _replace_setup()
        mine = doc_text("b", "Beta", body="Edited meanwhile.\n").encode("utf-8")

        def fault(step):
            if step.startswith("temp:"):
                write(folder, "authoritative/b.md", mine)
        expected = dict(snapshot(folder))
        expected[os.path.join("authoritative", "b.md")] = mine
        said = _stale(do, folder, "changeset", request, fault=fault)
        check(said and "authoritative/b.md" in said and snapshot(folder) == expected
              and _no_leftovers(cs),
              "a retained document changed before the first write: refused, nothing replaced")
        shutil.rmtree(folder)

    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        before = snapshot(folder)
        stale = tx.Write(tx.CONTEXT, "authoritative/a.md", "new", tx.expect("something else"))
        taken = tx.Write(tx.CONTEXT, "authoritative/b.md", "new", tx.ABSENT)
        for w, what in ((stale, "a target whose content is not what was planned"),
                        (taken, "a target planned as absent that exists")):
            try:
                tx.Transaction(cs, [w]).run()
                refused = None
            except tx.ConcurrentChange as exc:
                refused = exc
            check(refused is not None and refused.concurrent == [w.path] and refused.restored
                  and snapshot(folder) == before and _no_leftovers(cs),
                  f"a transaction refuses {what}, writing nothing")
        ok = tx.Write(tx.CONTEXT, "authoritative/a.md",
                      doc_text("a", "Alpha", body="New.\n"), tx.expect(read(folder, "authoritative/a.md")
                                                                       .decode("utf-8")
                                                                       .replace("\n", "\r\n")))
        tx.Transaction(cs, [ok]).run()
        check(b"New." in read(folder, "authoritative/a.md"),
              "and writes a target that matches, line endings aside")
        shutil.rmtree(folder)


def _interrupted_grant():
    """A grant that died just before it was final: the folder written, the
    genuine journal kept."""
    folder, request, cs = _setup_grant()
    before = snapshot(folder)
    try:
        do(folder, "changeset", request,
           fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "before-commit" else None)
    except Crash:
        pass
    with open(os.path.join(_jdir(cs), tx.JOURNAL_FILE), "rb") as fh:
        genuine = fh.read()
    return folder, cs, before, genuine


def _tree(root: str) -> dict:
    """Every file and folder under `root`, with file bytes, not following links."""
    out = {}
    for dirpath, dirs, files in os.walk(root):
        for name in dirs + files:
            path = os.path.join(dirpath, name)
            if os.path.islink(path) or _is_junction(path):
                out[os.path.relpath(path, root)] = "link"
                if name in dirs:
                    dirs.remove(name)
                continue
            if os.path.isfile(path):
                with open(path, "rb") as fh:
                    out[os.path.relpath(path, root)] = fh.read()
            else:
                out[os.path.relpath(path, root)] = None
    return out


def _is_junction(path: str) -> bool:
    try:
        return bool(getattr(os.lstat(path), "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def make_link(link: str, target: str) -> bool:
    """A junction (Windows) or symbolic link at `link` to the folder `target`.
    False when this system refuses to create either."""
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(target, link)
            return True
        except (ImportError, AttributeError, OSError):
            pass
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False


def remove_link(link: str) -> None:
    try:
        os.unlink(link)
    except OSError:
        os.rmdir(link)


def case_hostile_journal() -> None:
    print("\na journal is untrusted: anything not exactly its shape is refused, touching nothing")
    from app import mcp
    with isolated_private_state() as state_root:
        folder, cs, _before, genuine = _interrupted_grant()
        journal = json.loads(genuine.decode("utf-8"))
        txid = journal["id"]
        entries = journal["entries"]
        ctx_i = next(i for i, e in enumerate(entries) if e["root"] == tx.CONTEXT and e["old"])
        priv_i = next(i for i, e in enumerate(entries) if e["root"] == tx.PRIVATE)
        n = int(entries[ctx_i]["temp"].rsplit("-", 1)[1])
        # Sentinels: outside the context, a sibling context's private state.
        outside = tempfile.mkdtemp(prefix="charter-outside-")
        write(outside, "victim.md", b"outside")
        write(outside, f".charter-txn-{txid}-{n}", b"outside temp")
        sibling = context()
        sib = ps.PrivateState.default().for_context(sibling)
        write(sib.path(ps.CANDIDATES), "x.md", b"sibling candidate")
        sib_key = os.path.basename(sib.base)

        def entry(i, **changes):
            def mutate(j):
                j["entries"][i].update(changes)
            return mutate

        def top(**changes):
            def mutate(j):
                j.update(changes)
            return mutate

        bad_paths = ["../victim.md", "/victim.md", outside.replace("\\", "/") + "/victim.md",
                     "//server/share/authoritative/a.md", "\\\\?\\C:\\victim.md",
                     "C:authoritative/a.md", "authoritative/../../victim.md",
                     "authoritative\\a.md", "authoritative/a.txt", "AGENTS.md",
                     "authoritative/.charter-txn-abcdef-0"]
        if os.name == "nt":
            bad_paths += ["authoritative/a.md:stream", "authoritative/con.md", "authoritative/AUX.md",
                          "authoritative/sub./a.md", "authoritative/sub /a.md"]
        private_paths = [f"../{sib_key}/candidates/x.md", "../../contexts", "context.json",
                         f"staging/{tx.JOURNAL_KIND}/{tx.JOURNAL_FILE}", "locks/writer.lock",
                         "observed.json", "candidates/../context.json", "candidates/_x.md",
                         "proposals/../../x.json"]
        mutations = [(f"a context path `{p}`", entry(ctx_i, path=p)) for p in bad_paths]
        mutations += [(f"a private path `{p}`", entry(priv_i, path=p)) for p in private_paths]

        def oversized(j):
            j["entries"] = [dict(entries[0]) for _ in range(tx.MAX_ENTRIES + 1)]

        def duplicate(j):
            j["entries"].append(dict(j["entries"][ctx_i]))

        def same_temp(j):
            other = next(i for i in range(len(entries)) if i != ctx_i)
            for k in ("temp", "restore_temp", "backup"):
                j["entries"][other][k] = j["entries"][ctx_i][k]

        def extra_entry_key(j):
            j["entries"][ctx_i]["note"] = "x"
        mutations += [
            ("an unknown root", entry(ctx_i, root="elsewhere")),
            ("a path that is not text", entry(ctx_i, path=7)),
            ("entries that are not a list", top(entries={"a": 1})),
            ("no entries", top(entries=[])),
            ("an oversized list of entries", oversized),
            ("a file named twice", duplicate),
            ("a temporary file named twice", same_temp),
            ("a content record that is not a hash", entry(ctx_i, old="zz")),
            ("old and new the same", entry(ctx_i, new=entries[ctx_i]["old"])),
            ("a version given as text", top(version="1")),
            ("a version given as true", top(version=True)),
            ("an identifier with traversal", top(id="../x")),
            ("an identifier that is not text", top(id=5)),
            ("an unknown top-level key", top(note="x")),
            ("an unknown entry key", extra_entry_key),
            ("a backup with traversal", entry(ctx_i, backup=f"backups/{txid}/../../../context.json")),
            ("another transaction's backup", entry(ctx_i, backup=f"backups/ffffff/{n}")),
            ("a backup for another index", entry(ctx_i, backup=f"backups/{txid}/{n + 50}")),
            ("a backup name off the pattern", entry(ctx_i, backup=f"backups/{txid}/{n}.bak")),
            ("no backup for a replaced file", entry(ctx_i, backup=None)),
            ("another transaction's temporary file", entry(ctx_i, temp=f".charter-txn-ffffff-{n}")),
            ("a temporary file with a folder", entry(ctx_i, temp=f"../.charter-txn-{txid}-{n}")),
            ("a restore name for another index", entry(ctx_i, restore_temp=f".charter-txn-{txid}-{n + 1}r")),
            ("a temporary index with leading zeros", entry(ctx_i, temp=f".charter-txn-{txid}-0{n}")),
            ("a folder to remove outside the context", top(created_dirs=[["context", "../outside"]])),
            ("a folder to remove that serves no entry", top(created_dirs=[["private", "staging"]])),
            ("a folder entry of the wrong shape", top(created_dirs=[["context"]])),
            ("a folder entry that is not a list", top(created_dirs="authoritative")),
            ("a folder to recreate at the top", top(pruned_dirs=["authoritative"])),
            ("a folder to recreate that nothing removed", top(pruned_dirs=["authoritative/x"])),
            ("a folder to recreate outside", top(pruned_dirs=["../outside"])),
        ]
        jpath = os.path.join(_jdir(cs), tx.JOURNAL_FILE)

        def attempt(raw: bytes, label: str) -> None:
            with open(jpath, "wb") as fh:
                fh.write(raw)
            ctx_before, out_before = _tree(folder), _tree(outside)
            state_before = _tree(state_root)
            try:
                tx.recover(cs)
                refused = ""
            except tx.TransactionError as exc:
                refused = exc.message
            agents = ""
            try:
                mcp.examine(folder)
            except mcp.Refusal as refusal:
                agents = refusal.reason
            check(refused and "cannot be trusted" in refused and tx.JOURNAL_FILE in refused
                  and _tree(folder) == ctx_before and _tree(outside) == out_before
                  and _tree(state_root) == state_before and tx.interrupted(cs)
                  and agents == "context-invalid",
                  f"{label}: refused in words; the context, outside files and every private "
                  "record untouched; agents refused")

        for label, mutate in mutations:
            hostile = copy.deepcopy(journal)
            mutate(hostile)
            attempt(json.dumps(hostile).encode("utf-8"), label)
        text = genuine.decode("utf-8")
        attempt(text.replace('"version": 1', '"version": 1, "version": 1', 1).encode("utf-8"),
                "a duplicated key")
        attempt(text.replace('"version": 1', '"version": NaN', 1).encode("utf-8"),
                "a non-finite number")
        attempt(b"\xff\xfe not json", "bytes that are not UTF-8 JSON")
        real_limit = tx.MAX_JOURNAL_BYTES
        tx.MAX_JOURNAL_BYTES = 64
        try:
            attempt(genuine, "a record larger than any Charter writes")
        finally:
            tx.MAX_JOURNAL_BYTES = real_limit
        os.remove(jpath)
        os.makedirs(jpath)
        try:
            tx.recover(cs)
            refused = False
        except tx.TransactionError:
            refused = True
        check(refused and tx.interrupted(cs) and os.path.isdir(jpath),
              "a record that is a folder: refused and left; agents refused")
        os.rmdir(jpath)

        # The genuine record still recovers everything afterwards.
        with open(jpath, "wb") as fh:
            fh.write(genuine)
        done = tx.recover(cs)
        check(done and not done["unrestored"] and not tx.interrupted(cs) and ac.examine(folder).valid
              and _tree(outside) == {"victim.md": b"outside", f".charter-txn-{txid}-{n}": b"outside temp"},
              "the genuine record still rolls back exactly, and nothing outside was ever touched")
        shutil.rmtree(folder)
        shutil.rmtree(sibling)
        shutil.rmtree(outside)


def case_untrusted_record_wording() -> None:
    print("\nan untrusted record: every step it gives is specific, and following them all restores service")
    from app import mcp

    def refusal(cs) -> str:
        try:
            tx.recover(cs)
        except tx.TransactionError as exc:
            return exc.message
        return ""

    def agents(folder) -> str:
        try:
            mcp.examine(folder)
        except mcp.Refusal as refused:
            return refused.reason
        return "served"

    def quoted(message: str) -> list:
        return re.findall(r"`([^`]*)`", message)

    head = "Charter's record of an interrupted write cannot be trusted ("
    lead = ("), so it will not guess how to undo it, and changed nothing. Charter can’t serve this "
            "Agent Context until this is resolved. Nothing below comes from that record. First "
            "check the Agent Context's documents, and restore any that are not as you approved "
            "them. ")
    tail = (" Then open this Agent Context in Charter again: if agents are still not served, its "
            "status lists what else stops them, with what to do.")
    never = ("*", "any `.", "`.charter-txn-`", "`.acm-txn-`", "file in it", "delete any")
    escaped_backtick = chr(92) + "u0060"

    with isolated_private_state() as state_root:
        folder, cs, _before, genuine = _interrupted_grant()
        journal = json.loads(genuine.decode("utf-8"))
        txid = journal["id"]
        jpath = os.path.join(_jdir(cs), tx.JOURNAL_FILE)
        # Leftovers in both prefix forms, a restore name, in the Agent Context
        # and in this context's private state.
        write(folder, f".charter-txn-{txid}-0", b"temp")
        write(folder, "authoritative/.acm-txn-1a2b3c-1r", b"earlier-name restore temp")
        write(cs.path(ps.CANDIDATES), f".charter-txn-{txid}-2", b"private temp")
        # Look-alikes in the Agent Context: strays, never named for deletion.
        look_alikes = ["authoritative/.charter-txn-ABCDEF-0", "authoritative/.charter-txn-notes.md",
                       ".acm-txn-zz"]
        for rel in look_alikes:
            write(folder, rel, b"not a name Charter gives")
        os.makedirs(os.path.join(folder, f".charter-txn-{txid}-3"))  # a folder, not a file
        odd = "notes `x` here.txt"  # a backtick cannot end its quotation
        write(folder, odd, b"an ordinary stray")
        # Look-alikes that block nothing: in private state, and inside .git.
        write(cs.path(ps.CANDIDATES), ".charter-txn-notes", b"private look-alike")
        write(folder, f".git/.charter-txn-{txid}-4", b"inside .git")
        # A record whose paths and names point elsewhere.
        outside = tempfile.mkdtemp(prefix="charter-outside-")
        write(outside, "victim.md", b"outside")
        write(outside, f".charter-txn-{txid}-9", b"outside temp")
        hostile = copy.deepcopy(journal)
        hostile["entries"][0].update(path="../" + os.path.basename(outside) + "/victim.md",
                                     temp=f"../.charter-txn-{txid}-9", backup="../../elsewhere")
        hostile["created_dirs"] = [["context", "../decoy-folder"]]
        with open(jpath, "w", encoding="utf-8") as fh:
            json.dump(hostile, fh)

        exam = ac.examine(folder)
        by_path = {i["path"]: i for i in exam.issues}
        check(all(by_path[r]["message"] == ac.LOOK_ALIKE and by_path[r]["fix"] == ac.LOOK_ALIKE_FIX
                  for r in look_alikes + [f".charter-txn-{txid}-3/"])
              and "delete" not in ac.LOOK_ALIKE_FIX.lower()
              and by_path[f".charter-txn-{txid}-0"]["message"].startswith("An interrupted Charter write")
              and by_path["authoritative/.acm-txn-1a2b3c-1r"]["message"].startswith("An interrupted Charter write"),
              "the status calls only exact temporary names Charter's; a look-alike is a stray to move out")

        ctx_before, out_before, state_before = _tree(folder), _tree(outside), _tree(state_root)
        message = refusal(cs)
        leftovers = sorted([os.path.join(folder, f".charter-txn-{txid}-0"),
                            os.path.join(folder, "authoritative", ".acm-txn-1a2b3c-1r")]) + \
            [os.path.join(cs.path(ps.CANDIDATES), f".charter-txn-{txid}-2")]
        moved = sorted([os.path.join(folder, *r.split("/")) for r in look_alikes]
                       + [os.path.join(folder, f".charter-txn-{txid}-3") + os.sep,
                          os.path.join(folder, odd)])

        def shown(p):
            return p.replace("`", escaped_backtick)
        why = message[len(head):].split("), so", 1)[0]
        expected = (
            head + why + lead
            + "Then delete these temporary files, which only an interrupted Charter write leaves: "
            + ", ".join(f"`{p}`" for p in leftovers) + ". "
            + f"Then delete the record itself, where Charter keeps it: `{jpath}`. Delete nothing else. "
            + "These are in the Agent Context folder but aren't part of it, and keep agents refused "
              "on their own: " + ", ".join(f"`{shown(p)}`" for p in moved)
            + ". Charter never moves or deletes them: move each out of the folder." + tail)
        check(message == expected and why,
              "the exact wording: delete each listed leftover and the record; move each listed "
              "stray out; then open again")
        check(sorted(quoted(message)) == sorted(leftovers + [jpath] + [shown(p) for p in moved])
              and escaped_backtick in message,
              "every quoted name is a leftover, the record, or a stray Charter's own check found; "
              "a backtick in a name is escaped, so no quotation is broken")
        deletions = message.split("Delete nothing else.")[0]
        check(not any(os.path.basename(p.rstrip(os.sep)) in deletions for p in moved)
              and not any(s in message for s in never)
              and not any(s in message for s in (f"{txid}-4", f"{txid}-9", "victim", "elsewhere",
                                                 "decoy", ".charter-txn-notes`",
                                                 os.path.basename(outside))),
              "no wildcard or pattern; no look-alike is named for deletion; nothing from the "
              "record, in .git or in private-state look-alikes is named")
        check(_tree(folder) == ctx_before and _tree(outside) == out_before
              and _tree(state_root) == state_before and tx.interrupted(cs)
              and agents(folder) == "context-unclean",
              "refusing deletes and changes nothing, and agents stay refused")

        # Following every displayed step, and nothing else, restores service.
        aside = tempfile.mkdtemp(prefix="charter-moved-")
        for p in leftovers + [jpath]:
            os.remove(p)
        for p in moved:
            shutil.move(p.rstrip(os.sep), os.path.join(aside, os.path.basename(p.rstrip(os.sep))))
        check(not tx.interrupted(cs) and tx.recover(cs) is None and agents(folder) == "served"
              and os.path.exists(os.path.join(folder, ".git", f".charter-txn-{txid}-4"))
              and os.path.exists(os.path.join(cs.path(ps.CANDIDATES), ".charter-txn-notes"))
              and _tree(outside) == out_before,
              "after exactly the displayed steps, agents are served: .git, private-state "
              "look-alikes and files outside never blocked, and were never touched")
        shutil.rmtree(folder)
        shutil.rmtree(outside)
        shutil.rmtree(aside)

        # Nothing left to name.
        folder, cs, _before, _genuine = _interrupted_grant()
        jpath = os.path.join(_jdir(cs), tx.JOURNAL_FILE)
        with open(jpath, "wb") as fh:
            fh.write(b"\xff not json")
        message = refusal(cs)
        check("Charter found no temporary file left by an interrupted write." in message
              and quoted(message) == [jpath] and "These are in the Agent Context" not in message
              and not any(s in message for s in never),
              "with nothing left over, it says so and names only the record")
        check(tx.interrupted(cs) and agents(folder) == "context-invalid", "  and agents stay refused")
        os.remove(jpath)
        check(agents(folder) == "served", "  after deleting the record as told, agents are served")
        shutil.rmtree(folder)

        probe = tempfile.mkdtemp(prefix="charter-link-probe-")
        can_link = make_link(os.path.join(probe, "l"), probe)
        if can_link:
            remove_link(os.path.join(probe, "l"))
        shutil.rmtree(probe)
        if not can_link:
            print("  - links not checked: this system refused to create a junction or symbolic link")
            return

        # A link in the Agent Context: never followed, never listed to move or
        # delete, and agents stay refused until the person deals with it.
        folder, cs, _before, _genuine = _interrupted_grant()
        jpath = os.path.join(_jdir(cs), tx.JOURNAL_FILE)
        with open(jpath, "wb") as fh:
            fh.write(b"\xff not json")
        target = tempfile.mkdtemp(prefix="charter-link-target-")
        write(target, f".charter-txn-{txid}-0", b"beyond the link")
        link = os.path.join(folder, "authoritative", "linked")
        make_link(link, target)
        message = refusal(cs)
        check(quoted(message) == [jpath] and "linked" not in message and target not in message
              and os.path.exists(os.path.join(target, f".charter-txn-{txid}-0")),
              "a link: never followed, nothing beyond it named, and nothing there touched")
        os.remove(jpath)
        check(agents(folder) == "context-invalid"
              and any(i["path"] == "authoritative/linked" and "link" in i["message"]
                      for i in ac.examine(folder).issues),
              "  after the record is gone, the link still fails closed, and the status names it")
        remove_link(link)
        check(agents(folder) == "served", "  once the person removes the link, agents are served")
        shutil.rmtree(target)
        shutil.rmtree(folder)

        # A staging folder that is a link: no record is named for deletion.
        folder, cs, _before, _genuine = _interrupted_grant()
        staging = cs.path(ps.STAGING)
        elsewhere = tempfile.mkdtemp(prefix="charter-elsewhere-")
        shutil.copytree(staging, os.path.join(elsewhere, "staging"))
        shutil.rmtree(staging)
        make_link(staging, os.path.join(elsewhere, "staging"))
        message = refusal(cs)
        check(f"`{staging}` is not a plain folder, so Charter names no record to delete" in message
              and tx.JOURNAL_FILE not in message and "delete the record" not in message
              and os.path.exists(os.path.join(elsewhere, "staging", tx.JOURNAL_KIND, tx.JOURNAL_FILE)),
              "a staging folder that is a link: no record is named, and the file it leads to is untouched")
        check(tx.interrupted(cs) and agents(folder) == "context-invalid", "  and agents stay refused")
        remove_link(staging)
        shutil.rmtree(elsewhere)
        shutil.rmtree(folder)

        # A genuine record still recovers by itself, naming nothing to delete.
        folder, cs, before, _genuine = _interrupted_grant()
        check(agents(folder) == "context-invalid", "a genuine interrupted write fails closed until recovered")
        done = tx.recover(cs)
        check(done and not done["unrestored"] and not tx.interrupted(cs) and snapshot(folder) == before
              and agents(folder) == "served",
              "  a genuine record still rolls back exactly, with no person-facing deletion")
        shutil.rmtree(folder)


def case_journal_links() -> None:
    print("\nrecovery never acts through a link, junction or a folder swapped after checking")
    probe = tempfile.mkdtemp(prefix="charter-link-probe-")
    can_link = make_link(os.path.join(probe, "l"), probe)
    if can_link:
        remove_link(os.path.join(probe, "l"))
    shutil.rmtree(probe)
    if not can_link:
        print("  - links not checked: this system refused to create a junction or symbolic link")
        return
    with isolated_private_state():
        # An entry reaching outside through a junction inside the context.
        folder, cs, before, genuine = _interrupted_grant()
        journal = json.loads(genuine.decode("utf-8"))
        txid = journal["id"]
        created = next(e for e in journal["entries"] if e["root"] == tx.CONTEXT and e["old"] is None)
        outside = tempfile.mkdtemp(prefix="charter-outside-")
        with open(os.path.join(folder, *created["path"].split("/")), "rb") as fh:
            write(outside, "x.md", fh.read())
        write(outside, created["temp"], b"outside temp")
        link = os.path.join(folder, "authoritative", "link")
        make_link(link, outside)
        hostile = dict(journal, entries=[dict(e, path="authoritative/link/x.md") if e is created
                                         else e for e in journal["entries"]])
        jpath = os.path.join(_jdir(cs), tx.JOURNAL_FILE)
        with open(jpath, "w", encoding="utf-8") as fh:
            json.dump(hostile, fh)
        out_before = _tree(outside)
        check(raises(tx.TransactionError, tx.recover, cs) and _tree(outside) == out_before
              and tx.interrupted(cs),
              "an entry through a junction in the context: refused; the outside files are untouched")
        remove_link(link)
        with open(jpath, "wb") as fh:
            fh.write(genuine)

        # The journal's own folder is a link elsewhere.
        jdir = _jdir(cs)
        os.rename(jdir, jdir + "-real")
        elsewhere = tempfile.mkdtemp(prefix="charter-elsewhere-")
        write(elsewhere, tx.JOURNAL_FILE, genuine)
        make_link(jdir, elsewhere)
        check(tx.interrupted(cs) and raises(tx.TransactionError, tx.recover, cs)
              and _tree(elsewhere) == {tx.JOURNAL_FILE: genuine},
              "a journal folder that is a link: agents refused, recovery refused, nothing followed")
        remove_link(jdir)
        os.rename(jdir + "-real", jdir)
        shutil.rmtree(elsewhere)

        # A folder swapped for a junction after the checks, before rollback acts.
        decoy = tempfile.mkdtemp(prefix="charter-decoy-")
        for e in journal["entries"]:
            if e["root"] == tx.CONTEXT and e["path"].startswith("authoritative/"):
                with open(os.path.join(folder, *e["path"].split("/")), "rb") as fh:
                    write(decoy, e["path"].split("/", 1)[1], fh.read())
        real_rollback = tx.rollback
        swapped = []

        def swap_then_rollback(*args, **kwargs):
            os.rename(os.path.join(folder, "authoritative"), os.path.join(folder, "moved-aside"))
            make_link(os.path.join(folder, "authoritative"), decoy)
            swapped.append(True)
            return real_rollback(*args, **kwargs)
        tx.rollback = swap_then_rollback
        decoy_before = _tree(decoy)
        try:
            check(raises(tx.TransactionError, tx.recover, cs) and swapped
                  and _tree(decoy) == decoy_before and tx.interrupted(cs),
                  "a folder replaced by a junction after validation: rollback stops before acting "
                  "through it, keeping the journal")
        finally:
            tx.rollback = real_rollback
        remove_link(os.path.join(folder, "authoritative"))
        os.rename(os.path.join(folder, "moved-aside"), os.path.join(folder, "authoritative"))
        done = tx.recover(cs)
        check(done and not done["unrestored"] and snapshot(folder) == before,
              "put back, the genuine record rolls back exactly")
        shutil.rmtree(decoy)
        shutil.rmtree(outside)
        shutil.rmtree(folder)


def case_backup_cleanup() -> None:
    print("\ncleanup removes only the backups a transaction names")
    with isolated_private_state():
        folder, cs, before, genuine = _interrupted_grant()
        txid = json.loads(genuine.decode("utf-8"))["id"]
        backups = os.path.join(_jdir(cs), tx.BACKUPS)
        write(backups, f"{txid}/notes.txt", b"not Charter's")
        write(backups, f"{txid}/keep/inner.md", b"not Charter's either")
        tx.recover(cs)
        check(snapshot(folder) == before and not tx.interrupted(cs)
              and sorted(os.listdir(os.path.join(backups, txid))) == ["keep", "notes.txt"],
              "after recovery its numbered backups are gone; anything else in the folder stays")
        # With no journal: only folders and files shaped as Charter's backups are removed.
        write(backups, "abc123/0", b"orphan backup")
        write(backups, "abc123/extra.txt", b"keep")
        write(backups, "not-a-transaction/0", b"keep")
        check(tx.recover(cs) is None
              and not os.path.exists(os.path.join(backups, "abc123", "0"))
              and os.path.isfile(os.path.join(backups, "abc123", "extra.txt"))
              and os.path.isfile(os.path.join(backups, "not-a-transaction", "0"))
              and os.path.isfile(os.path.join(backups, txid, "notes.txt")),
              "orphaned backups go; unexpected entries stay where they are")
        shutil.rmtree(folder)


def case_candidate_records_path_limit() -> None:
    """A candidate's baseline record is longer than its file. An action whose
    candidate record would not fit the path limit is blocked in its preview,
    naming the candidate, and refused when applied: never a failed apply."""
    print("\na candidate whose private records would not fit the path limit")
    # True of every action, a withdrawal's derived name included: never a
    # promise that the person can shorten a title.
    REMEDY = ("Use a shorter candidate name where this action allows one, or enable long paths "
              "in Windows." if os.name == "nt" else
              "Use a shorter candidate name where this action allows one.")
    long_stem = "l" * 125
    name = f"{long_stem[:117]}.md"
    logical = ps.logical_candidate(name)
    real = tx.path_limit

    def candidate_problems(p: au.Plan, needed: int) -> bool:
        return p.blocked and len(p.problems) == 1 and all(
            f"`{logical}`" in m and f"need {needed} characters" in m and m.endswith(REMEDY)
            and "document title" not in m for m in p.problems)

    with isolated_private_state():
        folder = context(docs=(("a.md", "Alpha"), (f"{long_stem}.md", "Long one")))
        cs = ps.PrivateState.default().for_context(folder)
        record = cs.path(*prov.record_path(logical).split("/"))
        request = withdrawal(folder, f"authoritative/{long_stem}.md")
        before = snapshot(folder)
        check(len(cs.path(ps.CANDIDATES, name)) < len(record) - 1
              and len(os.path.join(folder, "authoritative", f"{long_stem}.md")) + 24 < len(record) - 1,
              "the withdrawn candidate's own file, and every context write, are shorter than its "
              "baseline record")
        # A limit its file fits within but its baseline record does not: this
        # computer's own path lengths play no part.
        tx.path_limit = lambda: len(record) - 1  # type: ignore[assignment]
        try:
            p = au.plan(folder, "changeset", request)
            check(candidate_problems(p, len(record)),
                  "a withdrawal: blocked in its preview, naming the candidate, what it needs and the remedy")
            check(raises(au.ActionRefused, au.apply, folder, "changeset", request, p.plan_id, PHRASE),
                  "and refused when applied, never a failed apply")
            tx.path_limit = lambda: len(record)  # type: ignore[assignment]
            check(not au.plan(folder, "changeset", request).blocked,
                  "one character more and it fits: nothing else was too long")
        finally:
            tx.path_limit = real  # type: ignore[assignment]
        check(snapshot(folder) == before and cs.candidates() == [] and not os.path.exists(record)
              and not tx.interrupted(cs), "nothing was written, in the folder or in private state")
        shutil.rmtree(folder)

    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        new = {"title": "T" * 140, "scope": "", "body": "x\n"}
        [made] = [c.path for c in au.plan(folder, "add", new).changes
                  if c.path.startswith(ps.CANDIDATES + "/")]
        made = ps.logical_candidate(made[len(ps.CANDIDATES) + 1:])
        record = cs.path(*prov.record_path(made).split("/"))
        tx.path_limit = lambda: len(record) - 1  # type: ignore[assignment]
        try:
            p = au.plan(folder, "add", new)
            check(p.blocked and any(f"`{made}`" in m and m.endswith(REMEDY) for m in p.problems),
                  "creating a candidate: blocked at its preview, before anything is filed")
        finally:
            tx.path_limit = real  # type: ignore[assignment]
        check(cs.candidates() == [], "and no candidate was filed")

        # An existing candidate keeps its name and its baseline when an edit
        # would no longer fit: the edit is refused, nothing is renamed.
        existing = add(folder, "Kept as it is")
        file_path = cs.path(ps.CANDIDATES, ps.candidate_name(existing))
        record = cs.path(*prov.record_path(existing).split("/"))
        kept = {p: open(p, "rb").read() for p in (file_path, record)}
        tx.path_limit = lambda: len(record) - 1  # type: ignore[assignment]
        try:
            p = au.plan(folder, "edit-candidate", {"candidate": existing, "title": "Kept as it is",
                                                    "scope": "Cand scope.", "body": "Edited.\n"})
            check(p.blocked and any(f"`{existing}`" in m for m in p.problems),
                  "editing an existing candidate whose baseline would not fit: blocked in its preview")
            with open(file_path, "ab") as fh:
                fh.write(b"Changed outside Charter.\n")
            kept[file_path] = open(file_path, "rb").read()
            sha = ac.sha256_text(cs.read_candidate(existing))
            try:
                prov.mark_seen(folder, existing, sha)
                said = ""
            except au.ActionRefused as exc:
                said = str(exc)
            check(f"`{existing}`" in said and "Nothing was changed" in said,
                  "Mark as seen: refused in words, naming the candidate")
        finally:
            tx.path_limit = real  # type: ignore[assignment]
        check(cs.candidates() == [existing] and {p: open(p, "rb").read() for p in kept} == kept,
              "the candidate keeps its name, its text and its baseline, byte for byte")
        shutil.rmtree(folder)

    # A real long private-state root, where long paths are off: only the
    # baseline record is past this system's own limit.
    limit = tx.path_limit()
    if limit > 1000:
        print(f"  SKIPPED: this system's path limit ({limit}) is too high to exercise a real long root.")
        return
    parent = tempfile.mkdtemp(prefix="charter-root-")
    try:
        with isolated_private_state(parent) as probe:
            folder = context(docs=(("a.md", "Alpha"), (f"{long_stem}.md", "Long one")))
            offset = len(ps.PrivateState.default().for_context(folder).base) - len(parent)
        shutil.rmtree(probe, ignore_errors=True)
        tail = len(os.sep + ps.BASELINES + os.sep + name + ".json")
        # Exactly one character over where the temporary folder allows it, and
        # at least one over however long the temporary folder already is.
        pad = max(1, limit + 1 - (len(parent) + 1 + offset + tail))
        root = os.path.join(parent, "p" * pad)
        with isolated_private_state(root):
            cs = ps.PrivateState.default().for_context(folder)
            record = cs.path(*prov.record_path(logical).split("/"))
            if len(cs.path(ps.CANDIDATES, name)) > limit:
                print("  SKIPPED: the temporary folder is too long for even the candidate's own "
                      "file to fit; the limits above cover it.")
                shutil.rmtree(folder)
                return
            p = au.plan(folder, "changeset", withdrawal(folder, f"authoritative/{long_stem}.md"))
            check(len(record) > limit >= len(cs.path(ps.CANDIDATES, name))
                  and candidate_problems(p, len(record)),
                  f"a {len(cs.base)}-character private-state root: the withdrawal is blocked in its "
                  "preview with this system's own limit")
            check(raises(au.ActionRefused, au.apply, folder, "changeset", p.request, p.plan_id, PHRASE)
                  and cs.candidates() == [] and not tx.interrupted(cs) and ac.examine(folder).valid,
                  "and refused when applied: nothing written, and the context still governs as it did")
        shutil.rmtree(folder)
    finally:
        shutil.rmtree(parent, ignore_errors=True)


def _bounded_long_names() -> None:
    with isolated_private_state():
        long_stem = "l" * 125
        folder = context(docs=(("a.md", "Alpha"), (f"{long_stem}.md", "Long one"),
                               ("_Ünï code notes.md", "Odd name")))
        cs = ps.PrivateState.default().for_context(folder)
        check(ac.examine(folder).valid, "a governing file name too long or too odd for a private "
                                        "name is still a valid governing document")
        record = cs.path(*prov.record_path(ps.logical_candidate(f"{long_stem[:117]}.md")).split("/"))
        if len(record) > tx.path_limit():
            # This system's private-state root is too long for the longest name's
            # records: the preview says so, and the rest cannot be exercised here.
            p = au.plan(folder, "changeset", withdrawal(folder, f"authoritative/{long_stem}.md"))
            check(p.blocked and any("too long" in m for m in p.problems),
                  "the longest private name does not fit this private-state root: blocked in its "
                  "preview, not a failed apply")
            over = len(record) - tx.path_limit()
            print(f"  SKIPPED: the rest needs a private-state root {over} "
                  f"character{'' if over == 1 else 's'} shorter.")
            shutil.rmtree(folder)
            return
        for path in (f"authoritative/{long_stem}.md", "authoritative/_Ünï code notes.md"):
            do(folder, "changeset", withdrawal(folder, path))
        names = [ps.candidate_name(c) for c in cs.candidates()]
        check(any(n == f"{long_stem[:117]}.md" for n in names) and "Uni-code-notes.md" in names
              and all(not ps.name_problem(n) for n in names),
              "withdrawn: each returns as a candidate under a valid, bounded name")
        long_c = ps.logical_candidate(f"{long_stem[:117]}.md")
        odd_c = ps.logical_candidate("Uni-code-notes.md")
        do(folder, "changeset", alongside(folder, long_c))
        do(folder, "changeset", alongside(folder, odd_c))
        exam = ac.examine(folder)
        check(exam.valid, "granted back under those names")
        # Replacing them archives the replaced versions under valid names.
        for gov in (f"authoritative/{long_stem[:117]}.md", "authoritative/Uni-code-notes.md"):
            do(folder, "revise", {"path": gov})
        revisions = [c for c in cs.candidates() if c not in (long_c, odd_c)]
        for rev in revisions:
            meta = meta_of(cs.read_candidate(rev))
            gov = next(d.path for d in ac.examine(folder).documents if d.id == meta["revises"])
            do(folder, "changeset", seeded(folder, {"document": gov, "outcome": "replace",
                                                    "candidate": rev}))
        check(all(not ps.name_problem(n) and len(n) <= ps.MAX_NAME for n in cs.archived())
              and "Uni-code-notes-superseded.md" in cs.archived() and len(cs.archived()) == 2,
              "replaced: their archived versions have valid, bounded names")
        shutil.rmtree(folder)


def case_bounded_names() -> None:
    print("\nnames for archived and withdrawn documents are bounded and always valid")
    _bounded_long_names()
    with isolated_private_state():
        # The same governing name written straight into a context, never seen by Charter.
        folder = context(docs=(("a.md", "Alpha"),))
        cs = ps.PrivateState.default().for_context(folder)
        real = ps.MAX_NAME_TRIES
        ps.MAX_NAME_TRIES = 3
        try:
            for name in ("a-superseded.md", "a-superseded-2.md", "a-superseded-3.md"):
                write(cs.path(ps.ARCHIVE), name, b"taken")
            revision = add(folder, "Alpha again")
            request = seeded(folder, {"document": "authoritative/a.md", "outcome": "replace",
                                      "candidate": revision})
            try:
                au.plan(folder, "changeset", request)
                said = ""
            except au.ActionRefused as exc:
                said = str(exc)
            check("free private name" in said and "Nothing was changed" in said,
                  "every archive name taken: a worded refusal, not an endless search")
            for name in ("a.md", "a-2.md", "a-3.md"):
                write(cs.path(ps.CANDIDATES), name, b"taken")
            try:
                au.plan(folder, "changeset", withdrawal(folder, "authoritative/a.md"))
                said = ""
            except au.ActionRefused as exc:
                said = str(exc)
            check("free private name" in said, "every withdrawal name taken: refused the same way")
            for name in ("busy.md", "busy-2.md", "busy-3.md"):
                write(cs.path(ps.CANDIDATES), name, b"taken")
            check(raises(ps.PrivateStateError, au.plan, folder, "add",
                         {"title": "Busy", "body": "x\n"}),
                  "every new candidate name taken: refused the same way")
        finally:
            ps.MAX_NAME_TRIES = real
        shutil.rmtree(folder)


def case_post_commit_follow_up() -> None:
    print("\na committed change is reported as applied, whatever fails after it")
    from app import observation
    from app import api_changeset
    from app import console
    with isolated_private_state():
        folder, request, cs = _setup_grant()
        real = observation.record_charter_write

        def broken(*_args, **_kwargs):
            raise OSError("disk full")
        observation.record_charter_write = broken
        try:
            result = do(folder, "changeset", request)
        finally:
            observation.record_charter_write = real
        check(result["applied"] and result["governing_change"] and result["follow_up"]
              and "was applied" in result["follow_up"][0]
              and os.path.isfile(os.path.join(folder, "authoritative", "gamma-rules.md"))
              and ac.examine(folder).valid and not tx.interrupted(cs),
              "its observation record fails after commit: applied, with the failure as a follow-up")
        shutil.rmtree(folder)

    with isolated_private_state():
        folder, request, cs = _setup_grant()

        def after(step):
            if step == "after-commit":
                raise RuntimeError("cleanup failed")
        result = do(folder, "changeset", request, fault=after)
        check(result["applied"] and result["follow_up"] and ac.examine(folder).valid
              and not tx.interrupted(cs),
              "tidying after commit fails: applied, with a follow-up, never rolled back")
        shutil.rmtree(folder)

    with isolated_private_state():
        folder, request, cs = _setup_grant()
        p = au.plan(folder, "changeset", request)
        real = observation.record_charter_write
        observation.record_charter_write = lambda *_a, **_k: (_ for _ in ()).throw(OSError("full"))
        try:
            reply = api_changeset.apply(console.Session(folder), {
                "id": request["draft_id"], "revision": request["draft_revision"],
                "plan_id": p.plan_id, "confirm": PHRASE})
        finally:
            observation.record_charter_write = real
        check(reply["applied"] and reply["follow_up"],
              "the console's change-set route passes the follow-up through with the success")
        result = do(folder, "add", {"title": "Plain", "body": "x\n"})
        check(result["applied"] and result["follow_up"] == [],
              "an action with nothing to follow up says so with an empty list")
        shutil.rmtree(folder)


def case_windows_readers() -> None:
    """Candidate, archive, baseline, change-set and Agent Context writes with a
    lock-free reader: the console never lists a transaction's own file, and a
    reader that has a target open for a moment (Windows then refuses the
    rename or removal) is waited out, leaving no journal behind."""
    print("\nlock-free readers during candidate, archive, baseline, change-set and Agent Context writes")
    import threading
    from app import console
    from tests.harness import HeldOpen
    windows = os.name == "nt"
    with isolated_private_state():
        folder = context()
        cs = ps.PrivateState.default().for_context(folder)
        do(folder, "add", {"title": "Audit", "scope": "Audit.", "body": "Audit v1.\n"})
        logical = "authority-candidates/audit.md"
        candidate_file = cs.candidate_file(logical)
        session = console.Session(folder)

        def at_first_temp(act):
            fired = []

            def fault(step):
                if step.startswith("temp:") and not fired:
                    fired.append(step)
                    act()
            return fault

        def quiet(label):
            leftovers = [os.path.join(d, n) for d, _s, names in os.walk(cs.base) for n in names
                         if n.startswith(ac.TRANSACTION_PREFIXES) or n.endswith(".tmp")]
            leftovers += [n for n in os.listdir(folder) if n.startswith(ac.TRANSACTION_PREFIXES)]
            check(not tx.interrupted(cs) and not leftovers and ac.examine(folder).valid, label)

        def refused_once(reader):
            return not windows or len(reader.refusals) == 1

        # Mid-edit, the console's refresh: no file Charter cannot use is listed.
        seen = {}

        def refresh():
            seen["temp"] = [n for n in os.listdir(os.path.dirname(candidate_file))
                            if n.startswith(ac.TRANSACTION_PREFIXES)]
            t = threading.Thread(target=lambda: seen.update(state=console.state(session),
                                                             unusable=cs.unusable_candidate_files()))
            t.start()
            t.join(60)
        p = au.plan(folder, "edit-candidate", {"candidate": logical, "scope": "Audit.", "body": "Audit v2.\n"})
        au.apply(folder, "edit-candidate", p.request, p.plan_id, True, fault=at_first_temp(refresh))
        check(len(seen["temp"]) == 1 and seen["state"]["unusable_candidate_files"] == [] and seen["unusable"] == []
              and any(d["path"] == logical for d in seen["state"]["documents"]),
              "mid-edit, GET /api/state never lists the transaction's file among files Charter cannot use")
        quiet("  and the edit leaves no journal or debris")

        with HeldOpen("after-refusal") as reader:
            p = au.plan(folder, "edit-candidate", {"candidate": logical, "scope": "Audit.", "body": "Audit v3.\n"})
            au.apply(folder, "edit-candidate", p.request, p.plan_id, True,
                     fault=at_first_temp(lambda: reader.open(candidate_file)))
        check("Audit v3." in cs.read_candidate(logical) and refused_once(reader),
              "a candidate open in a reader for a moment, as it is edited: refused once, then written")
        quiet("  no journal or debris")

        with open(candidate_file, "ab") as fh:
            fh.write(b"Edited by hand.\n")  # changed outside Charter, so Mark as seen writes
        with HeldOpen("after-refusal") as reader:
            reader.open(cs.path(*prov.record_path(logical).split("/")))
            seen_now = prov.mark_seen(folder, logical, ac.sha256_text(cs.read_candidate(logical)))
        check(seen_now["changed"] and not prov.changed(cs, logical, cs.read_candidate(logical)) and refused_once(reader),
              "a baseline open in a reader for a moment, as Mark as seen records it: refused once, then written")
        quiet("  no journal or debris")

        ctx = chs.Ctx(folder)
        draft = chs.create(ctx, "Audit plan")
        with HeldOpen("after-refusal") as reader:
            reader.open(os.path.join(chs._dir(ctx), draft["id"] + ".json"))
            draft = chs.update(ctx, draft["id"], draft["revision"], {"rationale": "Why."})
        check(draft["rationale"] == "Why." and refused_once(reader),
              "a change-set draft open in a reader for a moment, as it saves: refused once, then saved")
        quiet("  no temporary file left beside it")

        # Govern it: an agent reading the map at that moment does not stop the change.
        request = seeded(folder, {"alongside": logical})
        mid = {}

        def mid_change_set():
            from app import mcp
            t = threading.Thread(target=lambda: mid.update(unfinished=tx.unfinished(cs),
                                                           mcp_refuses=mcp.interrupted(folder)))
            t.start()
            t.join(60)
            reader.open(os.path.join(folder, ac.CONTEXT_MAP))
        with HeldOpen("after-refusal") as reader:
            plan = au.plan(folder, "changeset", request)
            au.apply(folder, "changeset", request, plan.plan_id, au.CONFIRM_PHRASE,
                     fault=at_first_temp(mid_change_set))
        check(mid == {"unfinished": True, "mcp_refuses": True},
              "while a change set is part-way through writing the Agent Context, agents are refused, as before")
        check(any(d.title == "Audit" for d in ac.examine(folder).documents) and refused_once(reader),
              "AGENT-CONTEXT.md open in an agent's reader for a moment, as a change set applies: refused once, "
              "then applied")
        quiet("  the Agent Context valid, no journal or debris")

        # Withdraw it, then retire the candidate while a reader has it open: it is removed, and archived.
        from tests.harness import govern
        govern(folder, {"document": "authoritative/audit.md", "outcome": "withdraw"})
        back = [c for c in cs.candidates() if "audit" in c][0]
        with HeldOpen("after-refusal") as reader:
            p = au.plan(folder, "retire", {"candidate": back})
            au.apply(folder, "retire", p.request, p.plan_id, True,
                     fault=at_first_temp(lambda: reader.open(cs.candidate_file(back))))
        check(back not in cs.candidates() and cs.archived() and refused_once(reader),
              "a candidate open in a reader for a moment, as it is retired: refused once, then archived")
        quiet("  no journal or debris")
        shutil.rmtree(folder)


def run() -> None:
    case_candidates()
    case_no_direct_routes()
    case_front_matter_in_text()
    case_preview_survives_midnight()
    case_revision_origin()
    case_grant_and_withdraw()
    case_replace()
    case_preconditions_and_staleness()
    case_no_git()
    case_rollback()
    case_crash_recovery()
    case_crash_at_every_step()
    case_tooling_files_in_subfolders()
    case_path_limit()
    case_candidate_records_path_limit()
    case_transaction_bounds()
    case_earlier_name_temporary_files()
    case_concurrent_edits()
    case_hostile_journal()
    case_untrusted_record_wording()
    case_journal_links()
    case_backup_cleanup()
    case_bounded_names()
    case_post_commit_follow_up()
    case_windows_readers()
    print(f"\n{OK} All authority action checks passed.")


if __name__ == "__main__":
    run()
