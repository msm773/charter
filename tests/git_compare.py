"""The optional, read-only Git-base comparison.
Run: python -m tests.git_compare

Every check runs against a disposable Git repository made here. Commits in it
are the test's own; Charter makes none.

  * only the read-only commands in `git_compare.allowed()` ever run, each
    from the Agent Context folder: every Git process a comparison starts is
    recorded and checked against the allow-list, and the allow-list itself
    refuses every command that writes, fetches or reads outside the folder;
  * the repository — working tree, index, refs and objects — is byte-for-byte
    unchanged, and so is private state;
  * only the Agent Context's subtree is read: files beside it never appear;
  * the comparison is right, and its review material names no commit, branch,
    revision, local location or private state, keeps the report contract, and
    says it is advisory only;
  * a base that does not resolve, is not in the history, has no valid Agent
    Context, or a current context that is not valid and clean, gets a reason
    and no review material;
  * `charter compare` prints a summary, the prompt or JSON, saves a packet only
    where the person says and never for a comparison that changed during the
    run, and adopts or creates no private state;
  * the console offers no comparison.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import authority as au  # noqa: E402
from app import console  # noqa: E402
from app import git_compare as gc  # noqa: E402
from app import impact  # noqa: E402
from app import server  # noqa: E402
from app.__main__ import main as cli_main  # noqa: E402
from tests.agent_context import doc_text, generate, snapshot, write  # noqa: E402
from tests.harness import isolated_private_state, seeded  # noqa: E402

OK = "ok"
PHRASE = "change governing context"
SECRET = "TOP SECRET OUTSIDE THE CONTEXT"


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


class Crash(BaseException):
    pass


def git(repo: str, *args: str) -> str:
    # No optional locks: the test's own reads must not refresh the index either.
    return subprocess.run(["git", "--no-optional-locks", "-C", repo, *args], capture_output=True, text=True,
                          check=True).stdout.strip()


def repository():
    """A repository with an Agent Context in `context/`, a file and a folder
    beside it, and history: `start` (no context yet), `base` (a valid
    context), `broken` (its map deleted), then the current, changed context
    in the working tree."""
    repo = tempfile.mkdtemp(prefix="charter-git-")
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "commit.gpgsign", "false")
    write(repo, "secret-outside.txt", SECRET + "\n")
    write(repo, "other/authoritative/z.md", doc_text("z", "Outside doc", body=SECRET + "\n"))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "start")
    git(repo, "tag", "start")
    folder = os.path.join(repo, "context")
    write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Alpha rules.\n"))
    write(folder, "authoritative/b.md", doc_text("b", "Beta", body="Beta rules.\n"))
    write(folder, "authoritative/s.md", doc_text("s", "Steady", body="Steady rules.\n"))
    generate(folder, "Demo project")
    base_fp = ac.examine(folder).fingerprint
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "branch", "-q", "feature-base")
    git(repo, "tag", "base")
    os.remove(os.path.join(folder, ac.CONTEXT_MAP))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "broken")
    git(repo, "tag", "broken")
    git(repo, "checkout", "-q", "base", "--", ".")  # the working tree as at base, map back
    write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Alpha rules, changed.\n"))
    os.remove(os.path.join(folder, "authoritative", "b.md"))
    write(folder, "authoritative/c.md", doc_text("c", "Gamma", body="Gamma rules.\n"))
    generate(folder, "Demo project")
    return repo, folder, base_fp


def repo_snapshot(repo: str) -> dict:
    """Every file in the repository, `.git` included, and what Git says."""
    out = snapshot(repo)
    out["@status"] = git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    out["@refs"] = git(repo, "for-each-ref", "--format=%(refname) %(objectname)")
    out["@head"] = git(repo, "rev-parse", "--symbolic-full-name", "HEAD") + " " + git(repo, "rev-parse", "HEAD")
    return out


class GitSpy:
    """Records every process the comparison starts."""

    def __init__(self) -> None:
        self.calls = []
        self.real = subprocess.run

    def __enter__(self):
        def spy(cmd, *a, **k):
            self.calls.append(list(cmd))
            return self.real(cmd, *a, **k)
        subprocess.run = spy
        gc.subprocess.run = spy
        return self

    def __exit__(self, *exc):
        subprocess.run = self.real
        gc.subprocess.run = self.real


# --- the allow-list ---------------------------------------------------------------

def case_allow_list() -> None:
    print("\nthe read-only allow-list")
    oid = "a" * 40
    for args in (["rev-parse", "--is-inside-work-tree"],
                 ["rev-parse", "--verify", "--quiet", "main^{commit}"],
                 ["rev-parse", "--verify", "--quiet", "HEAD~2^{commit}"],
                 ["rev-parse", "--verify", "--quiet", "v1.0^{commit}"],
                 ["rev-parse", "--symbolic-full-name", "feature-base"],
                 ["symbolic-ref", "--quiet", "HEAD"],
                 ["ls-tree", "-r", "-z", oid, "--", "."],
                 ["cat-file", "blob", oid]):
        check(gc.allowed(args), f"allowed: git {' '.join(args)}")
    for args in (["fetch"], ["pull"], ["push"], ["checkout", "main"], ["switch", "main"],
                 ["merge", "main"], ["rebase", "main"], ["commit", "-m", "x"], ["add", "."],
                 ["reset", "--hard"], ["stash"], ["branch", "x"], ["tag", "x"], ["update-ref", "x", oid],
                 ["config", "x", "y"], ["status"], ["log"], ["show", "main:secret.txt"], ["diff", "main"],
                 ["for-each-ref"], ["rev-parse", "--show-toplevel"],
                 ["rev-parse", "--verify", "--quiet", "main"],
                 ["rev-parse", "--verify", "--quiet", "--all^{commit}"],
                 ["rev-parse", "--verify", "--quiet", "HEAD:secret.txt^{commit}"],
                 ["rev-parse", "--verify", "--quiet", "main..HEAD^{commit}"],
                 ["ls-tree", "-r", "-z", oid, "--", ".."],
                 ["ls-tree", "-r", "-z", oid, "--", "/"],
                 ["ls-tree", "-r", "-z", "--full-tree", oid, "--", "."],
                 ["ls-tree", "-r", "-z", "main", "--", "."],
                 ["ls-tree", "-r", oid],
                 ["cat-file", "-p", oid], ["cat-file", "--batch"], ["cat-file", "blob", "main:secret.txt"],
                 ["symbolic-ref", "HEAD", "refs/heads/x"], ["symbolic-ref", "--quiet", "HEAD", "refs/heads/x"],
                 ["symbolic-ref", "--short", "HEAD"], ["rev-parse", "--symbolic-full-name", "--all"],
                 ["rev-parse", "--symbolic-full-name", " main"],
                 ["rev-parse", "--symbolic-full-name", "HEAD:secret.txt"]):
        check(not gc.allowed(args), f"refused: git {' '.join(args)}")
    check(not gc.allowed(["cat-file", "blob", oid], oids={"b" * 40}),
          "refused: cat-file of an object the context's listing did not return")
    for bad in ("", " ", "-x", "--all", "HEAD:secret.txt", ":/message", "a b", "main..HEAD", "a\nb",
                "refs/heads/x.lock", "../x"):
        try:
            gc.valid_revision(bad)
            ok = False
        except gc.CompareError:
            ok = True
        check(ok, f"a base of {bad!r} is refused before Git is asked")
    try:
        gc._git(".", ["fetch"])
        ran = True
    except gc.CompareError:
        ran = False
    check(not ran, "the runner itself refuses anything off the allow-list")


# --- a real comparison ---------------------------------------------------------------

def case_compare() -> None:
    print("\ncomparing with a base the person names")
    with isolated_private_state() as state_root:
        repo, folder, base_fp = repository()
        session = console.Session(folder)
        folder = session.folder
        secrets = [folder, repo, state_root]
        before_repo, before_state = repo_snapshot(repo), snapshot(state_root)
        commit = git(repo, "rev-parse", "base")

        with GitSpy() as spy:
            r = gc.compare(folder, "base", secrets)
            for name in ("feature-base", commit, commit[:10], "HEAD~1"):
                check(gc.compare(folder, name, secrets)["comparison_fingerprint"] == r["comparison_fingerprint"],
                      f"the base may be named as the person likes: {name if len(name) < 12 else 'a commit'}")
        git_calls = [c for c in spy.calls if c and c[0] == "git"]
        check(spy.calls and len(git_calls) == len(spy.calls), "the comparison starts no process but Git")
        check(all("--no-optional-locks" in c and c[c.index("-C") + 1] == folder for c in git_calls),
              "every Git command runs without optional locks, from the Agent Context folder")
        check(all("core.fsmonitor=false" in c for c in git_calls),
              "and with the folder's own Git config unable to run a program (no fsmonitor, hook or helper)")
        listed = set()
        shapes_ok = True
        for c in git_calls:
            args = c[c.index("-C") + 2:]
            if args[0] == "ls-tree":
                listed |= set(re.findall(r"[0-9a-f]{40}", git(folder, *args)))
            shapes_ok &= gc.allowed(args, listed if args[0] == "cat-file" else None)
        check(shapes_ok, f"all {len(git_calls)} Git commands are on the allow-list, and cat-file reads "
                         "only objects the context's own listing returned")
        after_repo = repo_snapshot(repo)
        check(after_repo == before_repo,
              "the repository is byte-for-byte unchanged: working tree, index, refs, HEAD and objects"
              + "".join(f" [{k}]" for k in set(after_repo) | set(before_repo)
                        if after_repo.get(k) != before_repo.get(k)))
        check(snapshot(state_root) == before_state, "private state is unchanged")

        check(r["available"] and r["base"] == "base" and r["base_fingerprint"] == base_fp
              and r["current_fingerprint"] == ac.examine(folder).fingerprint,
              "it compares the base's Agent Context with the current one, by context fingerprint")
        changes = {row["path"]: row["change"] for row in r["rows"]}
        check(changes == {"authoritative/a.md": "changed", "authoritative/b.md": "removed",
                          "authoritative/c.md": "added", "authoritative/s.md": "unchanged"}
              and r["summary"] == {"added": 1, "changed": 1, "removed": 1, "unchanged": 1},
              "each governing document is added, changed, removed or unchanged")
        diff = next(row["diff"] for row in r["rows"] if row["path"] == "authoritative/a.md")
        check("-Alpha rules." in diff and "+Alpha rules, changed." in diff
              and next(row["diff"] for row in r["rows"] if row["change"] == "unchanged") == "",
              "a changed document shows its diff")
        dumped = json.dumps(r)
        check(SECRET not in dumped and "secret-outside" not in dumped and "other/" not in dumped
              and "Outside doc" not in dumped, "nothing outside the Agent Context's folder is read or shown")
        check("does not establish authority" in r["advisory"] and "approve a merge" in r["advisory"]
              and "change set current" in r["advisory"], "it says it is advisory review input only")

        p = r["review_prompt"]
        text = p["text"]
        check(p["ready"] and not p["over_limit"]
              and text.rstrip().endswith(impact.end_marker(r["comparison_fingerprint"]))
              and impact.PROMPT_SCHEMA in text and r["base_fingerprint"] in text
              and r["current_fingerprint"] in text and r["comparison_fingerprint"] in text,
              "the review prompt carries the schema, both context fingerprints and its end marker")
        check(all(f"governing document: {d}" in text for d in ("authoritative/a.md", "authoritative/c.md",
                                                                 "authoritative/s.md"))
              and "base document, no longer governing: authoritative/a.md" in text
              and "base document, no longer governing: authoritative/b.md" in text
              and "Alpha rules.\n" in text and "Beta rules." in text,
              "it includes the current documents, and the base versions of what changed or was removed")
        check("- changed `authoritative/a.md`" in text and "- removed `authoritative/b.md`" in text
              and "- added `authoritative/c.md`" in text and "authoritative/s.md`\n- " not in text,
              "it lists the changes since the base")
        check("does not approve a merge" in text and "decides nothing" in text,
              "it tells the agent the review is advisory and approves nothing")
        leaked = [s for s in (commit, commit[:7], commit[:12], "feature-base", folder, repo, state_root,
                              tempfile.gettempdir(), "charter-base-") if s in text]
        check(not leaked,
              "it names no commit, branch, local location, temporary folder or private state")
        check(SECRET not in text, "and nothing from beside the Agent Context")

        identity = {"project": r["project"], "fingerprint": r["current_fingerprint"],
                    "documents": [{"path": d.path, "sha256": ac.examine(folder).hashes[d.path],
                                   "text": ac.examine(folder).texts[d.path]}
                                  for d in sorted(ac.examine(folder).documents, key=lambda d: d.path)]}
        example = json.loads(re.search(r"```json\n(\{.*?\n\})\n```", text, re.S).group(1))
        example.update(coverage=[{"path": d["path"], "status": "affected"} for d in identity["documents"]],
                       impact={"related_documents": ["authoritative/a.md"], "overlap": "none",
                               "conflict": "none found", "recommended_relationship": "retain",
                               "unresolved_decision": "none"},
                       claims=[{"kind": "overlap", "path": "authoritative/a.md",
                                "quote": "Alpha rules, changed.", "explanation": "x"}],
                       recommendations=[{"path": "authoritative/a.md", "action": "retain"}], limitations=[])
        checked = impact.check_report(json.dumps(example), identity, {}, r["comparison_fingerprint"])
        check(checked["status"] == "well-formed",
              "a report written from it passes the existing report contract's form checks")

        same = gc.compare(folder, "base", secrets)
        check(same["comparison_fingerprint"] == r["comparison_fingerprint"],
              "comparing again gives the same comparison")
        shutil.rmtree(repo, ignore_errors=True)


def case_refused() -> None:
    print("\nno comparison: a reason, and no review material")
    with isolated_private_state():
        repo, folder, _fp = repository()
        session = console.Session(folder)
        folder = session.folder

        def refused(base, expect, label):
            r = gc.compare(folder, base)
            check(not r["available"] and expect in r["reason"] and "review_prompt" not in r
                  and "rows" not in r, label)
            return r

        refused("no-such-branch", "cannot be resolved", "a base that does not resolve")
        refused("--all", "not a revision", "an option instead of a base")
        refused("HEAD:secret-outside.txt", "not a revision", "a path at a revision instead of a base")
        refused("start", "no files in this Agent Context's folder",
                "a base from before this folder held anything")
        r = refused("broken", "does not hold a valid Agent Context", "a base whose Agent Context is not valid")
        check(any("AGENT-CONTEXT.md" in m for m in r["base_problems"]), "naming what is wrong at that base")

        blob = subprocess.run(["git", "-C", repo, "hash-object", "-w", "--stdin"], input=b"../secret-outside.txt",
                              capture_output=True, check=True).stdout.decode().strip()
        git(repo, "update-index", "--add", "--cacheinfo", f"120000,{blob},context/authoritative/link.md")
        tree = git(repo, "write-tree")
        linked = git(repo, "commit-tree", tree, "-p", "HEAD", "-m", "a link")
        git(repo, "read-tree", "HEAD")
        r = refused(linked, "not an ordinary file", "a base holding a link in the folder")
        check(SECRET not in json.dumps(r), "and the link is not followed")

        write(folder, "notes.txt", b"mine")
        refused("base", "not valid and clean", "the current context is not clean")
        os.remove(os.path.join(folder, "notes.txt"))
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited outside.\n"))
        refused("base", "not valid and clean", "the current context is not valid")
        generate(folder, "Demo project")

        cand = au.plan(folder, "add", {"title": "Delta", "body": "x\n"})
        au.apply(folder, "add", cand.request, cand.plan_id, True)
        req = seeded(folder, {"alongside": "authority-candidates/delta.md"})
        p = au.plan(folder, "changeset", req)
        try:
            au.apply(folder, "changeset", req, p.plan_id, PHRASE,
                     fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "replace:AGENT-CONTEXT.md" else None)
        except Crash:
            pass
        refused("base", "interrupted", "an interrupted Charter write")
        console.open_context(session, {"path": folder})

        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "now")
        same = gc.compare(folder, "HEAD")
        check(same["available"] and same["same"] and not same["review_prompt"]["ready"]
              and "nothing to review" in same["review_prompt"]["reason"] and "text" not in same["review_prompt"],
              "a base the same as now: nothing to review, and no material")

        shallow = tempfile.mkdtemp(prefix="charter-shallow-")
        subprocess.run(["git", "clone", "-q", "--depth", "1", "file:///" + repo.replace("\\", "/"),
                        shallow], check=True, capture_output=True)
        refused_shallow = gc.compare(os.path.join(shallow, "context"), "HEAD~1")
        check(not refused_shallow["available"] and "cannot be resolved" in refused_shallow["reason"],
              "a base outside a shallow clone's history: refused, without fetching")

        plain = tempfile.mkdtemp(prefix="charter-plain-")
        for rel in ("authoritative/a.md",):
            write(plain, rel, doc_text("a", "Alpha"))
        generate(plain, "Plain")
        if subprocess.run(["git", "-C", plain, "rev-parse", "--is-inside-work-tree"],
                          capture_output=True).returncode != 0:
            r = gc.compare(plain, "main")
            check(not r["available"] and "not in a Git checkout" in r["reason"]
                  and not gc.in_checkout(plain),
                  "an Agent Context outside Git: no comparison can be made")
        else:
            print("  (the temporary folder is itself inside a Git checkout; skipped)")
        check(gc.in_checkout(folder), "inside a checkout, a comparison can be made")
        for d in (repo, shallow, plain):
            shutil.rmtree(d, ignore_errors=True)


# --- the console, the packet and staleness ---------------------------------------------

def _http(port: int, path: str, body=None):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}",
                                 data=None if body is None else json.dumps(body).encode(),
                                 method="GET" if body is None else "POST")
    req.add_header("X-Charter-Console", "person")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def cli(*args: str):
    """`charter compare ...`, run in this process: its exit status, standard
    output and standard error."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli_main(["compare", *args])
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def case_command() -> None:
    print("\n`charter compare`: in the terminal, read-only, a packet only where the person says")
    with isolated_private_state() as state_root:
        repo, folder, _fp = repository()
        commit = git(repo, "rev-parse", "base")
        before_repo = repo_snapshot(repo)

        code, out, err = cli("--context", folder, "--base", "base")
        check(code == 0 and "Since “base”: 1 document added, 1 changed, 1 removed, 1 unchanged." in out
              and "added    authoritative/c.md — Gamma" in out and "removed  authoritative/b.md — Beta" in out
              and "changed  authoritative/a.md — Alpha" in out and "authoritative/s.md" not in out
              and gc.ADVISORY in out and gc.READ_ONLY in out and "Print it with --prompt." in out,
              "by default: a summary of what changed, advisory and read-only, and how to get the prompt")
        check(commit not in out and commit[:7] not in out and SECRET not in out,
              "the summary names the base as typed, never its commit")

        code, out, err = cli("--context", folder, "--base", "base", "--json")
        data = json.loads(out)
        check(code == 0 and data["available"]
              and sorted(r["change"] for r in data["rows"]) == ["added", "changed", "removed", "unchanged"]
              and "text" not in data["review_prompt"],
              "--json: one object, every document's change, and no prompt text unless asked for")

        code, prompt, err = cli("--context", folder, "--base", "base", "--prompt")
        check(code == 0 and prompt == gc.compare(folder, "base", ())["review_prompt"]["text"]
              and gc.DISCLOSURE in err and gc.DISCLOSURE not in prompt,
              "--prompt: only the prompt on standard output, the disclosure warning beside it")
        check(commit not in prompt and commit[:7] not in prompt and folder not in prompt
              and repo not in prompt and state_root not in prompt and SECRET not in prompt
              and "“base”" not in prompt,
              "the prompt names no commit, revision, local location or private state")
        code, out, _err = cli("--context", folder, "--base", "base", "--prompt", "--json")
        check(code == 0 and json.loads(out)["review_prompt"]["text"] == prompt,
              "--prompt --json carries the prompt's text")

        outside = tempfile.mkdtemp(prefix="charter-packets-")
        try:
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", outside)
            check(code == 1 and "fits in one message" in out and os.listdir(outside) == [],
                  "a review that fits one message is not saved as a packet")
            code, out, _err = cli("--context", folder, "--base", "no-such-branch")
            check(code == 1 and "No comparison was made." in out and "Charter does not fetch" in out,
                  "a base that does not resolve: the reason, and exit 1")
            code, _out, _err = cli("--context", folder, "--base", "base", "--accept-git-warning")
            check(code == 2, "--accept-git-warning without --packet is an unusable command line")
            code, _out, _err = cli("--context", folder, "--base", "base", "--prompt", "--packet", outside)
            check(code == 2, "--prompt and --packet cannot be asked for together")
            check(repo_snapshot(repo) == before_repo and not os.path.exists(state_root),
                  "the repository is unchanged, and no private state was adopted or created")

            big = "".join(f"Rule {i}: a long governing sentence that makes this document large.\n"
                          for i in range(1200))
            write(folder, "authoritative/c.md", doc_text("c", "Gamma", body=big))
            generate(folder, "Demo project")
            before_repo = repo_snapshot(repo)
            code, out, _err = cli("--context", folder, "--base", "base", "--prompt")
            check(code == 1 and "--packet" in out and "No prompt was printed." in out,
                  "past the practical limit, --prompt prints no prompt and points to --packet")
            code, out, _err = cli("--context", folder, "--base", "base", "--packet",
                                  os.path.join(folder, "packet.md"))
            check(code == 1 and "cannot be saved there" in out
                  and not os.path.exists(os.path.join(folder, "packet.md")),
                  "a packet is never saved inside the Agent Context")
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", outside)
            names = os.listdir(outside)
            r = gc.compare(folder, "base", ())
            text = open(os.path.join(outside, names[0]), encoding="utf-8").read() if names else ""
            check(code == 0 and names == [r["review_prompt"]["file_name"]]
                  and f"Saved the review packet “{names[0]}”" in out
                  and gc.DISCLOSURE in out and r["review_prompt"]["request"] in out
                  and text.rstrip().endswith(impact.end_marker(r["comparison_fingerprint"], True)),
                  "--packet saves one complete packet there, with the request to send and the disclosure warning")
            check(commit not in text and commit[:7] not in text and folder not in text and repo not in text
                  and state_root not in text and SECRET not in text,
                  "the packet names no commit or local location")
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", outside)
            check(code == 0 and len(os.listdir(outside)) == 2 and "nothing was replaced" in out,
                  "a second packet never overwrites the first")

            in_repo = os.path.join(repo, "packets")
            os.makedirs(in_repo)
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", in_repo)
            check(code == 1 and "inside a Git repository" in out and "--accept-git-warning" in out
                  and os.listdir(in_repo) == [],
                  "inside a Git repository, the warning is stated and nothing is saved")
            check(gc.PACKET_CONTENTS in out and "candidate" not in out,
                  "the warning says what a comparison's packet holds, not a change set's candidates")
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", in_repo,
                                  "--accept-git-warning")
            check(code == 0 and len(os.listdir(in_repo)) == 1 and "inside a Git repository" in out,
                  "with --accept-git-warning, it is saved there, the warning repeated")
            shutil.rmtree(in_repo)
            check(repo_snapshot(repo) == before_repo and not os.path.exists(state_root),
                  "apart from the packets the person named, nothing was written: Git and private state untouched")

            real = gc.compare
            calls = []

            def moving(*a, **k):
                calls.append(1)
                if len(calls) == 2:  # the context changes between the comparison and its packet
                    write(folder, "authoritative/s.md", doc_text("s", "Steady", body="Steady, edited.\n"))
                    generate(folder, "Demo project")
                return real(*a, **k)
            gc.compare = moving
            try:
                code, out, _err = cli("--context", folder, "--base", "base", "--packet", outside)
            finally:
                gc.compare = real
            check(code == 1 and "changed while they were being compared" in out
                  and len(os.listdir(outside)) == 2,
                  "if the context changes during the run, no packet is saved")
        finally:
            shutil.rmtree(outside, ignore_errors=True)
            shutil.rmtree(repo, ignore_errors=True)


BIG = "".join(f"Rule {i}: a long governing sentence that makes this document large.\n" for i in range(1200))


def _big(folder: str) -> None:
    """Make the review past the practical single-message limit."""
    write(folder, "authoritative/c.md", doc_text("c", "Gamma", body=BIG))
    generate(folder, "Demo project")


def case_packet_naming() -> None:
    print("\nthe request and every field name the packet as it was actually saved")
    with isolated_private_state():
        repo, folder, _fp = repository()
        _big(folder)
        outside = tempfile.mkdtemp(prefix="charter-packets-")
        try:
            suggested = gc.compare(folder, "base", ())["review_prompt"]["file_name"]
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", outside)
            check(code == 0 and f"in the attached file “{suggested}”" in out,
                  "the first packet keeps the suggested name, and the request names it")
            numbered = suggested[:-3] + " (2).md"
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", outside)
            check(code == 0 and os.path.exists(os.path.join(outside, numbered))
                  and f"Saved the review packet “{numbered}”" in out
                  and f"in the attached file “{numbered}”" in out
                  and f"in the attached file “{suggested}”" not in out,
                  "a taken name: the request names the file as saved, “… (2).md”, not the suggested one")
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", outside, "--json")
            data = json.loads(out)
            third = suggested[:-3] + " (3).md"
            check(code == 0 and data["packet"]["name"] == third
                  and f"“{third}”" in data["packet"]["request"]
                  and data["review_prompt"]["file_name"] == third
                  and f"“{third}”" in data["review_prompt"]["request"]
                  and suggested not in json.dumps(data, ensure_ascii=False).replace(suggested[:-3] + " (", ""),
                  "--json: packet.request, review_prompt.request and file_name all name the saved file")
            custom = os.path.join(outside, "custom name.md")
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", custom)
            check(code == 0 and os.path.exists(custom) and "in the attached file “custom name.md”" in out
                  and suggested not in out,
                  "a name the person gives: the request names it")
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", custom, "--json")
            data = json.loads(out)
            check(code == 0 and data["packet"]["name"] == "custom name (2).md"
                  and "“custom name (2).md”" in data["packet"]["request"]
                  and "“custom name (2).md”" in data["review_prompt"]["request"],
                  "a name the person gives, already taken: every field names “custom name (2).md”")
        finally:
            shutil.rmtree(outside, ignore_errors=True)
            shutil.rmtree(repo, ignore_errors=True)


def _commit_context(repo: str, folder: str, files: dict, message: str) -> str:
    """A commit, made with plumbing so the working tree, index and HEAD stay
    as they are, whose `context/` holds a valid Agent Context of `files`."""
    tmp = tempfile.mkdtemp(prefix="charter-ctx-")
    index = os.path.join(tmp, "index")
    env = dict(os.environ, GIT_INDEX_FILE=index)
    try:
        for rel, text in files.items():
            write(tmp, "c/" + rel, text)
        generate(os.path.join(tmp, "c"), "Demo project")
        subprocess.run(["git", "-C", repo, "read-tree", "--empty"], env=env, check=True)
        root = os.path.join(tmp, "c")
        for dirpath, _dirs, names in os.walk(root):
            for name in names:
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root).replace("\\", "/")
                blob = git(repo, "hash-object", "-w", full)
                subprocess.run(["git", "-C", repo, "update-index", "--add", "--cacheinfo",
                                f"100644,{blob},context/{rel}"], env=env, check=True)
        tree = subprocess.run(["git", "-C", repo, "write-tree"], env=env, check=True,
                              capture_output=True, text=True).stdout.strip()
        return git(repo, "commit-tree", tree, "-p", "base", "-m", message)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def case_disclosure() -> None:
    print("\nreview material is refused when a document quotes a commit, branch, revision or location")
    from app import compare as cmp
    with isolated_private_state() as state_root:
        repo, folder, _fp = repository()
        branch = git(repo, "symbolic-ref", "--short", "HEAD")
        base_commit, head = git(repo, "rev-parse", "base"), git(repo, "rev-parse", "HEAD")
        home = os.path.expanduser("~")
        original = open(os.path.join(folder, "authoritative", "a.md"), encoding="utf-8").read()
        before_repo = repo_snapshot(repo)

        def drive_forms(path: str) -> list:
            fwd = path.replace("\\", "/")
            out = [path, fwd, path.upper(), path.lower(), "file:///" + fwd.lstrip("/"),
                   "file://" + fwd if fwd.startswith("/") else "file:///" + fwd]
            if re.match(r"[A-Za-z]:/", fwd):
                out += ["/" + fwd[0].lower() + fwd[2:], "/mnt/" + fwd[0].lower() + fwd[2:],
                        fwd.replace(" ", "%20"), path.replace("\\", "\\\\")]
            return out

        quoted = [("the base's commit", base_commit, "base", gc.COMMIT),
                  ("the base's commit, abbreviated to 7", base_commit[:7], "base", gc.COMMIT),
                  ("the base's commit, abbreviated to 12, in capitals", base_commit[:12].upper(), "base",
                   gc.COMMIT),
                  ("the base's commit in `git describe` form", f"v1.0-3-g{base_commit[:9]}", "base", gc.COMMIT),
                  ("the checked-out commit", head, "base", gc.COMMIT),
                  ("the checked-out commit, abbreviated", head[:8], "base", gc.COMMIT),
                  ("the current branch", f"Merge from {branch}.", "base", gc.REVISION),
                  ("the current branch as a full ref", f"refs/heads/{branch}", "base", gc.REVISION),
                  ("the ref the base resolved to", "see refs/tags/base", "base", gc.REVISION),
                  ("the base as typed", "Compared with feature-base.", "feature-base", gc.REVISION),
                  ("the base as typed, with ~", "relative to HEAD~1 here", "HEAD~1", gc.REVISION),
                  ("a remote-style branch name", f"origin/{branch} is upstream", "base", gc.REVISION)]
        for where, label in ((repo, "the Git checkout's folder"), (folder, "the Agent Context folder"),
                             (state_root, "Charter's private state"), (home, "the home folder")):
            for i, form in enumerate(drive_forms(where)):
                quoted.append((f"{label}, form {i + 1}", f"Stored at {form} today.", "base", gc.LOCATION))
        if home and folder.casefold().startswith(home.casefold() + os.sep):
            quoted.append(("the Agent Context folder relative to home",
                           "~" + folder[len(home):].replace("\\", "/"), "base", gc.LOCATION))

        outside = tempfile.mkdtemp(prefix="charter-packets-")
        try:
            all_ok = True
            for label, text, base, category in quoted:
                write(folder, "authoritative/a.md", doc_text("a", "Alpha", body=f"Alpha rules. {text}\n"))
                generate(folder, "Demo project")
                r = gc.compare(folder, base, cmp.secrets(folder))
                material = r.get("review_prompt") or {}
                ok = (r["available"] and not material.get("ready") and "text" not in material
                      and category in material.get("reason", "") and "`authoritative/a.md`" in material["reason"]
                      and text not in material["reason"])
                code, out, err = cli("--context", folder, "--base", base, "--prompt")
                ok &= code == 1 and "UNTRUSTED DATA" not in out + err and category in out
                code, out, err = cli("--context", folder, "--base", base, "--prompt", "--json")
                data = json.loads(out)
                ok &= (code == 1 and "text" not in data["review_prompt"] and category in data["refused"]
                       and "UNTRUSTED DATA" not in out)
                if not ok:
                    print(f"    not refused: {label}")
                all_ok &= ok
            check(all_ok, f"each of {len(quoted)} quoted forms — commits full, abbreviated and described; "
                          "branch, ref and typed base; folder, checkout, private state and home in native, "
                          "slash, case, MSYS, WSL, file: and escaped forms — is refused, naming the kind, "
                          "never the value, exit 1, nothing printed")

            write(folder, "authoritative/a.md", doc_text("a", "Alpha", body=f"Alpha rules. {head}\n" + BIG))
            generate(folder, "Demo project")
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", outside)
            check(code == 1 and gc.COMMIT in out and os.listdir(outside) == [] and head not in out,
                  "past the limit, a packet quoting a commit is not written")
            code, out, _err = cli("--context", folder, "--base", "base", "--packet", outside, "--json")
            check(code == 1 and gc.COMMIT in json.loads(out)["refused"] and os.listdir(outside) == [],
                  "and with --json, the same refusal and no file")

            # The base's documents are checked too: a base whose removed document
            # quotes the current branch, or this checkout's location in MSYS form.
            write(folder, "authoritative/a.md", original)
            generate(folder, "Demo project")
            base_files = {"authoritative/a.md": doc_text("a", "Alpha", body="Alpha rules.\n"),
                          "authoritative/s.md": doc_text("s", "Steady", body="Steady rules.\n")}
            msys = "/" + repo[0].lower() + repo[2:].replace("\\", "/") if re.match(r"[A-Za-z]:", repo) else repo
            for tag, quote, category in (("quoted-branch", f"Work on {branch}.\n", gc.REVISION),
                                         ("quoted-place", f"Kept in {msys}/notes.\n", gc.LOCATION),
                                         ("quoted-self", "Compare with quoted-self.\n", gc.REVISION)):
                files = dict(base_files, **{"authoritative/b.md": doc_text("b", "Beta", body=quote)})
                git(repo, "tag", tag, _commit_context(repo, folder, files, tag))
                r = gc.compare(folder, tag, cmp.secrets(folder))
                check(r["available"] and not r["review_prompt"]["ready"]
                      and category in r["review_prompt"]["reason"]
                      and "the base version of `authoritative/b.md`" in r["review_prompt"]["reason"],
                      f"a base document quoting {category.split(',')[0]} ({tag}) is refused too")
                git(repo, "tag", "-d", tag)

            # Whole tokens only: a base named `main` is not refused for `maintain`.
            if branch == "main":
                git(repo, "branch", "-m", "main", "trunk")
            git(repo, "branch", "main", "base")
            write(folder, "authoritative/a.md", doc_text(
                "a", "Alpha", body="We maintain the domain, mainly; see main.md and remain-main-ish.\n"))
            generate(folder, "Demo project")
            r = gc.compare(folder, "main", cmp.secrets(folder))
            check(r["available"] and r["review_prompt"]["ready"],
                  "a document whose words merely contain the base name (`maintain`, `domain`, `main.md`) is "
                  "not refused")
            write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Merged into main.\n"))
            generate(folder, "Demo project")
            r = gc.compare(folder, "main", cmp.secrets(folder))
            check(not r["review_prompt"]["ready"] and gc.REVISION in r["review_prompt"]["reason"],
                  "but the name itself, as a word, is")
            write(folder, "authoritative/a.md", doc_text("a", "Alpha", body=f"A hash-like word {base_commit[:6]}.\n"))
            generate(folder, "Demo project")
            check(gc.compare(folder, "main", cmp.secrets(folder))["review_prompt"]["ready"],
                  "fewer than 7 hex digits is not taken for a commit")
            git(repo, "branch", "-D", "main")
            if branch == "main":
                git(repo, "branch", "-m", "trunk", "main")
            check("candidate" not in gc.DISCLOSURE and "base versions" in gc.DISCLOSURE,
                  "the disclosure statement describes what comparison material holds: current and base "
                  "documents, no candidates")
            write(folder, "authoritative/a.md", original)
            generate(folder, "Demo project")
            after = repo_snapshot(repo)
            # The test's own plumbing commits left objects; Charter changed nothing Git shows.
            check(all(after[k] == before_repo[k] for k in ("@status", "@refs", "@head"))
                  and not os.path.exists(state_root),
                  "the repository's refs, HEAD and working tree, and private state, are unchanged throughout")
        finally:
            shutil.rmtree(outside, ignore_errors=True)
            shutil.rmtree(repo, ignore_errors=True)


def case_current_problems() -> None:
    print("\na current context that is not valid and clean: its problems, listed")
    with isolated_private_state():
        repo, folder, _fp = repository()
        try:
            write(folder, "notes.txt", b"mine")
            code, out, _err = cli("--context", folder, "--base", "base")
            check(code == 1 and "listed below" in out and "Problems:" in out and "  - notes.txt: " in out,
                  "unclean: the summary lists each problem, path and message, as `charter check` does")
            code, out, _err = cli("--context", folder, "--base", "base", "--json")
            data = json.loads(out)
            check(code == 1 and not data["available"] and "listed below" in data["reason"]
                  and any(p["path"] == "notes.txt" and p["message"] for p in data["current_problems"]),
                  "--json: the same problems, as `current_problems` with path and message")
            os.remove(os.path.join(folder, "notes.txt"))
            write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited outside.\n"))
            code, out, _err = cli("--context", folder, "--base", "base")
            data = json.loads(cli("--context", folder, "--base", "base", "--json")[1])
            check(code == 1 and "Problems:" in out and "authoritative/a.md" in out
                  and data["current_problems"] and all(p["message"] for p in data["current_problems"]),
                  "invalid: the problems are listed in text and JSON")
            r = gc._not_comparable({"issues": [], "interrupted": False})
            check("listed below" not in r["reason"] and r["current_problems"] == [],
                  "with nothing to list, it never says “listed below”")
        finally:
            shutil.rmtree(repo, ignore_errors=True)


@contextlib.contextmanager
def patched(obj, name, value):
    real = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield real
    finally:
        setattr(obj, name, real)


def _raiser(exc):
    def fail(*_a, **_k):
        raise exc
    return fail


def case_json_failures() -> None:
    print("\n--json: one result object, never a traceback, when reading or writing fails")
    from app import compare as cmp
    from app import host_state as hs
    from app import private_store as ps
    from app import review_packet
    with isolated_private_state() as state_root:
        repo, folder, _fp = repository()
        outside = tempfile.mkdtemp(prefix="charter-packets-")
        denied = PermissionError(13, "Permission denied")

        def one_object(label, *extra, expect="", files=None):
            code, out, err = cli("--context", folder, "--base", "base", "--json", *extra)
            try:
                data = json.loads(out)
            except ValueError:
                data = None
            text = (data or {}).get("refused") or (data or {}).get("reason") or ""
            check(code == 1 and isinstance(data, dict) and "Traceback" not in out + err
                  and expect in text and (files is None or os.listdir(outside) == files),
                  label)
            return data

        try:
            with patched(gc.mg, "check", _raiser(denied)):
                d = one_object("an unreadable Agent Context or private state", expect="Permission denied")
                check(d["available"] is False, "is a comparison that could not be made")
            with patched(cmp.ps.PrivateState, "default",
                         classmethod(_raiser(hs.HostStateError("Windows did not report this user's identity.")))):
                one_object("private state that cannot be located", expect="private state")
            with patched(gc.tempfile, "mkdtemp", _raiser(denied)):
                one_object("the base cannot be rebuilt to check it", expect="could not rebuild")
            real_git = gc._git
            with patched(gc, "_git", lambda f, a, o=None: None if a[:1] == ["cat-file"] else real_git(f, a, o)):
                one_object("Git failing part-way, reading the base's files", expect="not available")
            with patched(gc, "_git", lambda f, a, o=None: b"garbage\0" if a[:1] == ["ls-tree"] else real_git(f, a, o)):
                one_object("Git listing the base in an unexpected form", expect="does not recognise")
            with patched(gc.subprocess, "run", _raiser(OSError(2, "No such file"))):
                one_object("Git not runnable at all", expect="not in a Git checkout")
            with patched(gc, "_examine_base", _raiser(UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"))):
                one_object("a base blob that cannot be decoded", expect="could not rebuild")

            with patched(gc, "recheck", _raiser(OSError(5, "Input/output error"))):
                one_object("a read failing while the prompt is made again", "--prompt",
                           expect="Input/output error")
            _big(folder)
            with patched(review_packet, "_place", _raiser(denied)):
                one_object("the packet's write failing", "--packet", outside, expect="could not be saved",
                           files=[])
            with patched(review_packet, "_forbidden", _raiser(ps.PrivateStateError("Private state is unreadable."))):
                one_object("private state unreadable while checking the destination", "--packet", outside,
                           expect="could not be produced", files=[])
            with patched(gc, "recheck", _raiser(OSError(5, "Input/output error"))):
                one_object("a read failing while the material is made again", "--packet", outside,
                           expect="Input/output error", files=[])
            with patched(gc, "recheck", _raiser(denied)):
                code, out, err = cli("--context", folder, "--base", "base", "--packet", outside)
                check(code == 1 and "could not be produced (Permission denied)" in out and "Traceback" not in err,
                      "and in text, a refusal in words, exit 1")
            check(not os.path.exists(state_root), "no private state was created by any of it")
        finally:
            shutil.rmtree(outside, ignore_errors=True)
            shutil.rmtree(repo, ignore_errors=True)


def _link_folder(link: str, target: str) -> bool:
    """Make `link` a junction (Windows) or symbolic link to `target`."""
    if os.name == "nt":
        return subprocess.run(["cmd", "/c", "mklink", "/J", link, target], capture_output=True).returncode == 0
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


def case_destination_revalidated() -> None:
    print("\nthe packet's destination is checked again immediately before the write")
    with isolated_private_state():
        repo, folder, _fp = repository()
        _big(folder)
        try:
            def run_with(change, *extra):
                """Run `--packet` with `change()` made after the destination
                was checked, while the comparison is made again."""
                real = gc.recheck

                def moving(*a, **k):
                    result = real(*a, **k)
                    change()
                    return result
                with patched(gc, "recheck", moving):
                    return cli("--context", folder, "--base", "base", *extra)

            outside = tempfile.mkdtemp(prefix="charter-packets-")
            code, out, _err = run_with(lambda: (write(outside, "authoritative/x.md", doc_text("x", "X")),
                                                generate(outside, "Elsewhere")), "--packet", outside)
            check(code == 1 and "changed before the packet was written" in out and "Agent Context" in out
                  and not [n for n in os.listdir(outside) if n.endswith(".md") and n != ac.CONTEXT_MAP],
                  "the folder became an Agent Context: nothing written")
            shutil.rmtree(outside)

            outside = tempfile.mkdtemp(prefix="charter-packets-")
            code, out, _err = run_with(lambda: git(outside, "init", "-q"), "--packet", outside, "--json")
            data = json.loads(out)
            check(code == 1 and "now inside a Git repository" in data["refused"]
                  and [n for n in os.listdir(outside) if n != ".git"] == [],
                  "the folder became a Git repository the person was not warned about: nothing written")
            shutil.rmtree(outside, ignore_errors=True)

            parent = tempfile.mkdtemp(prefix="charter-packets-")
            dest = os.path.join(parent, "dest")
            os.mkdir(dest)
            before = snapshot(folder)
            linked = []

            def swap():
                os.rename(dest, dest + "-moved")
                linked.append(_link_folder(dest, folder))
            code, out, _err = run_with(swap, "--packet", dest)
            if linked and linked[0]:
                check(code == 1 and "changed before the packet was written" in out and snapshot(folder) == before
                      and os.listdir(dest + "-moved") == [],
                      "the folder was replaced by a link into the Agent Context: nothing written anywhere")
            else:
                print("  (links cannot be made here; skipped)")
            if os.name == "nt" and os.path.isdir(dest):
                os.rmdir(dest)  # removes the junction only
            elif os.path.islink(dest):
                os.remove(dest)
            shutil.rmtree(parent, ignore_errors=True)

            outside = tempfile.mkdtemp(prefix="charter-packets-")
            target = os.path.join(outside, "mine.md")
            code, out, _err = run_with(lambda: write(outside, "mine.md", b"the person's own file"),
                                       "--packet", target)
            check(code == 0 and open(target, "rb").read() == b"the person's own file"
                  and os.path.exists(os.path.join(outside, "mine (2).md"))
                  and "“mine (2).md”" in out,
                  "a file that appeared at the chosen name meanwhile is never overwritten")
            shutil.rmtree(outside, ignore_errors=True)

            outside = tempfile.mkdtemp(prefix="charter-packets-")
            gone = os.path.join(outside, "gone")
            os.mkdir(gone)
            code, out, _err = run_with(lambda: os.rmdir(gone), "--packet", gone)
            check(code == 1 and "does not exist any more" in out and not os.path.exists(gone),
                  "the folder was removed meanwhile: nothing written, and it is not recreated")
            shutil.rmtree(outside, ignore_errors=True)
        finally:
            shutil.rmtree(repo, ignore_errors=True)


def case_not_in_console() -> None:
    print("\nthe console offers no Git-base comparison")
    with isolated_private_state():
        repo, folder, _fp = repository()
        session = console.Session(folder)
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(session))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            check(_http(port, "/api/state")[1]["status"]["git"]["state"] == "checkout",
                  "the folder is in a Git checkout")
            for route in ("/api/compare", "/api/compare/packet/save"):
                check(_http(port, route, {"base": "base"})[0] == 404, f"there is no `{route}`")
        finally:
            httpd.shutdown()
            httpd.server_close()
            shutil.rmtree(repo, ignore_errors=True)


def _listing(entries) -> bytes:
    """A `git ls-tree -r -z` listing of (path) names, as crafted objects could
    carry it: every entry an ordinary blob, the path exactly as given."""
    return b"".join(b"100644 blob " + b"a" * 40 + b"\t" + p.encode("utf-8") + b"\0" for p in entries)


def case_crafted_paths() -> None:
    print("\na crafted base tree cannot write outside the private comparison folder")
    # Git refuses such trees on checkout, but `ls-tree`/`cat-file` read objects
    # verbatim, and a fetch does not fsck by default. `_base_files` must reject
    # any path that leaves the Agent Context folder, before anything is read or
    # written. Here `_git` is replaced to return exactly what a crafted tree
    # would list, so no real crafted objects are needed.
    real_git = gc._git
    escapes = ["authoritative/../../../escaped.md", "../escaped.md", "a/../../escaped.md",
               "/etc/escaped.md", "C:/Windows/escaped.md", r"authoritative\..\..\escaped.md",
               "authoritative/./../escaped.md", "sub/x:stream.md"]
    try:
        for rel in escapes:
            gc._git = lambda folder, args, oids=None: (_listing([rel])
                                                       if args[:1] == ["ls-tree"] else b"body\n")
            try:
                gc._base_files("ignored", "0" * 40)
                refused = False
            except gc.CompareError:
                refused = True
            check(refused, f"a base listing {rel!r} is refused, so nothing is read or written")
        gc._git = lambda folder, args, oids=None: (_listing(["authoritative/ok.md"])
                                                    if args[:1] == ["ls-tree"] else
                                                    doc_text("ok", "Okay", body="Fine.\n").encode("utf-8"))
        files = gc._base_files("ignored", "0" * 40)
        check(list(files) == ["authoritative/ok.md"], "an ordinary nested path is still read")
    finally:
        gc._git = real_git

    # Belt-and-suspenders: even if a bad path reached it, `_examine_base` must
    # not write outside its own temporary folder.
    probe = tempfile.mkdtemp(prefix="charter-escape-probe-")
    marker = os.path.join(probe, "escaped.md")
    try:
        try:
            gc._examine_base({"authoritative/../../../../../../../../.." + marker: b"x\n"})
        except (gc.CompareError, OSError, ValueError):
            pass
        check(not os.path.exists(marker),
              "_examine_base writes nothing outside its temporary folder, even for a `..` path")
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def run() -> int:
    if shutil.which("git") is None:
        print("SKIPPED: Git is not installed.")
        return 0
    case_allow_list()
    case_crafted_paths()
    case_compare()
    case_refused()
    case_command()
    case_packet_naming()
    case_disclosure()
    case_current_problems()
    case_json_failures()
    case_destination_revalidated()
    case_not_in_console()
    print(f"\n{OK} All Git-base comparison checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
