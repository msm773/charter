"""`charter propose --context .`: filing one Agent Proposal. Run: python -m tests.propose

Product Specification §3.3 and the Phase 8 decisions:

  * `.` is resolved only as an Agent Context root; records go only to that
    context's private state, never into its folder;
  * `agent`, `operation`, `target_path` and `reason` are required; create,
    amend and retire take exactly their documented fields; any other field,
    `proposed_meta` keys included, is refused field by field; Charter
    assigns the `proposal_id`;
  * staleness is by content hash alone; a stale proposal is refused;
  * one result object, always: `pending` only when a record was filed,
    `refused` when nothing was, `unavailable` only when intake could not run,
    retryable only when it says so; nothing on standard error.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import agent_proposals as apx  # noqa: E402
from app import authority as au  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import propose  # noqa: E402
from tests.agent_context import context, doc_text, generate, read, snapshot, write  # noqa: E402
from tests.harness import isolated_private_state  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OK = "ok"


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def sha(folder: str, rel: str) -> str:
    return ac.sha256_text(read(folder, rel).decode("utf-8"))


def submit(folder: str, proposal) -> dict:
    data = proposal if isinstance(proposal, bytes) else json.dumps(proposal).encode("utf-8")
    return propose.submit(["--context", folder], data)


def codes(result: dict) -> set:
    return {(p["code"], p.get("field", "")) for p in result.get("problems", [])}


def pending_files(folder: str) -> list:
    cs = ps.PrivateState.default().find_context(folder)
    path = cs.path(ps.PROPOSALS, apx.PENDING) if cs else ""
    return sorted(n for n in os.listdir(path) if n.endswith(".json")) if path and os.path.isdir(path) else []


def setup() -> tuple:
    folder = context()
    a = au.plan(folder, "add", {"title": "Draft", "body": "Draft body.\n"})
    au.apply(folder, "add", a.request, a.plan_id, True)
    return folder, "authority-candidates/draft.md"


def case_create() -> None:
    print("\ncreate")
    with isolated_private_state():
        folder, _candidate = setup()
        before = snapshot(folder)
        good = {"agent": "codex", "operation": "create", "target_path": "authority-candidates/new-rule.md",
                "reason": "Needed.", "proposed_body": "# New rule\n\nText.\n",
                "proposed_meta": {"title": "New rule", "scope": "Rules."},
                "expected_context_impact": {"related": ["authoritative/a.md"], "conflict": "none"}}
        result = submit(folder, good)
        check(result["result"] == "pending" and result["proposal_id"].startswith("p-")
              and set(result) == {"result", "proposal_id"},
              "a valid create is filed: `pending`, with the id Charter assigned")
        check(snapshot(folder) == before and pending_files(folder) == [result["proposal_id"] + ".json"],
              "the record is in private state only; the Agent Context folder is unchanged")
        record = json.loads(open(os.path.join(ps.PrivateState.default().find_context(folder).path(
            ps.PROPOSALS, apx.PENDING), result["proposal_id"] + ".json"), encoding="utf-8").read())
        check(record["proposal"] == good and record["source"] == "agent",
              "it records the proposal exactly, as an agent's")
        for label, change, expected in (
                ("a missing agent", {"agent": None}, ("missing", "agent")),
                ("a missing reason", {"reason": None}, ("missing", "reason")),
                ("an empty reason", {"reason": "  "}, ("not_text", "reason")),
                ("a multi-line agent", {"agent": "a\nb"}, ("not_one_line", "agent")),
                ("a body missing", {"proposed_body": None}, ("missing", "proposed_body")),
                ("a target outside the candidates", {"target_path": "authoritative/x.md"},
                 ("target_invalid", "target_path")),
                # A name already in use is deliberately NOT refused: candidate and
                # archived names are private, so a collision is resolved at
                # acceptance instead (see case_candidate_name_privacy).
                ("base_sha256 on a create", {"base_sha256": "0" * 64}, ("not_used", "base_sha256")),
                ("replacements on a create", {"replacements": []}, ("not_used", "replacements")),
                ("an unknown field", {"proposal_id": "mine"}, ("unknown_field", "proposal_id")),
                ("legacy base_commit", {"base_commit": "abc"}, ("unknown_field", "base_commit")),
                ("legacy created", {"created": "2026-01-01"}, ("unknown_field", "created")),
                ("legacy related_finding", {"related_finding": "x"}, ("unknown_field", "related_finding")),
                ("an unknown proposed_meta key", {"proposed_meta": {"title": "T", "authority": "authoritative"}},
                 ("unknown_field", "proposed_meta.authority")),
                ("an unknown operation", {"operation": "supersede"}, ("operation_unknown", "operation"))):
            raw = dict(good)
            for k, v in change.items():
                if v is None:
                    raw.pop(k, None)
                else:
                    raw[k] = v
            result = submit(folder, raw)
            check(result["result"] == "refused" and expected in codes(result),
                  f"{label} is refused, naming `{expected[1]}`")
        check(len(pending_files(folder)) == 1, "and nothing refused was filed")
        result = submit(folder, {"agent": "a", "operation": "create", "target_path": "x", "reason": "r",
                                 "colour": "blue", "base_commit": "abc"})
        check({f for _c, f in codes(result)} >= {"colour", "base_commit", "target_path", "proposed_body"},
              "every problem is listed, each with its field")
        shutil.rmtree(folder)


def case_amend_and_retire() -> None:
    print("\namend and retire")
    with isolated_private_state():
        folder, candidate = setup()
        cs = ps.PrivateState.default().for_context(folder)
        gov_sha = sha(folder, "authoritative/a.md")
        cand_sha = ac.sha256_text(cs.read_candidate(candidate))
        amend = {"agent": "claude", "operation": "amend", "target_path": "authoritative/a.md",
                 "reason": "Clarify.", "base_sha256": gov_sha,
                 "replacements": [{"find": "Body.", "replace": "Clearer body."}]}
        check(submit(folder, amend)["result"] == "pending", "an amend of a governing document, by replacements")
        whole = dict(amend, replacements=None)
        whole.pop("replacements")
        whole["proposed_body"] = "Rewritten.\n"
        whole["proposed_meta"] = {"title": "Alpha v2"}
        check(submit(folder, whole)["result"] == "pending", "and by a complete body, with a new title")
        check(submit(folder, dict(whole, target_path=candidate, base_sha256=cand_sha))["result"] == "pending",
              "an amend of a candidate the agent was given")
        retire = {"agent": "claude", "operation": "retire", "target_path": candidate,
                  "reason": "Superseded.", "base_sha256": cand_sha}
        check(submit(folder, retire)["result"] == "pending", "a retire of a candidate")
        for label, raw, expected in (
                ("an amend without base_sha256", {k: v for k, v in amend.items() if k != "base_sha256"},
                 ("missing", "base_sha256")),
                ("a malformed hash", dict(amend, base_sha256="ABC"), ("base_invalid", "base_sha256")),
                ("a stale hash", dict(amend, base_sha256="0" * 64), ("stale", "base_sha256")),
                ("both body and replacements", dict(amend, proposed_body="x\n"),
                 ("body_or_replacements", "proposed_body")),
                ("neither body nor replacements", {k: v for k, v in amend.items() if k != "replacements"},
                 ("body_or_replacements", "proposed_body")),
                ("a replacement that does not match", dict(amend, replacements=[{"find": "Nope", "replace": "x"}]),
                 ("replacement_no_match", "replacements")),
                ("a replacement with extra keys", dict(amend, replacements=[{"find": "Body.", "replace": "x", "count": 2}]),
                 ("replacement_malformed", "replacements")),
                # A target that is not a governing document gets one private
                # result, revealing neither existence nor staleness.
                ("a target no one listed", dict(amend, target_path="authoritative/zzz.md"),
                 ("target_unavailable", "target_path")),
                ("the map itself", dict(amend, target_path="AGENT-CONTEXT.md"),
                 ("target_unavailable", "target_path")),
                ("an archived name", dict(amend, target_path="archive/old.md"),
                 ("target_unavailable", "target_path")),
                ("retiring a governing document", dict(retire, target_path="authoritative/a.md", base_sha256=gov_sha),
                 ("target_governing", "target_path")),
                ("a retire with a body", dict(retire, proposed_body="x\n"), ("not_used", "proposed_body")),
                ("a retire with proposed_meta", dict(retire, proposed_meta={"title": "x"}),
                 ("not_used", "proposed_meta"))):
            result = submit(folder, raw)
            check(result["result"] == "refused" and expected in codes(result), f"{label} is refused")
        ambiguous = context(docs=())
        write(ambiguous, "authoritative/d.md", doc_text("d", "Dup", body="same\nsame\n"))
        generate(ambiguous)
        result = submit(ambiguous, {"agent": "a", "operation": "amend", "target_path": "authoritative/d.md",
                                    "reason": "r", "base_sha256": sha(ambiguous, "authoritative/d.md"),
                                    "replacements": [{"find": "same", "replace": "other"}]})
        check(("replacement_ambiguous", "replacements") in codes(result), "a replacement matching twice is refused")
        for raw, op in (({k: v for k, v in amend.items() if k != "base_sha256"}, "amend"),
                        (dict(retire, base_sha256="ABC"), "retire")):
            messages = [p["message"] for p in submit(folder, raw)["problems"] if p["field"] == "base_sha256"]
            check(messages and messages[0].startswith(f"An `{op}` proposal needs `base_sha256`"),
                  f"a missing or malformed hash on `{op}` is explained grammatically")
        shutil.rmtree(ambiguous)
        shutil.rmtree(folder)


def case_results() -> None:
    print("\none result: pending, refused or unavailable")
    with isolated_private_state():
        folder, _candidate = setup()
        good = {"agent": "a", "operation": "create", "target_path": "authority-candidates/n.md",
                "reason": "r", "proposed_body": "x\n"}
        for data, code in ((b"not json", "not_json"), (b"[1]", "not_an_object"),
                           (b"\xff\xfe", "not_utf8"), (b"{" + b" " * (apx.MAX_INPUT + 10) + b"}", "too_large")):
            r = propose.submit(["--context", folder], data)
            check(r["result"] == "refused" and code in {p["code"] for p in r["problems"]},
                  f"{data[:12]!r}: refused, `{code}`")
        # A non-finite JSON value round-trips through Python but no browser's
        # JSON.parse accepts it, so one filed proposal would make the whole
        # Agent Proposals screen unreadable. It must be refused at intake.
        before_nonfinite = pending_files(folder)
        tmpl = (b'{"agent":"a","operation":"create","target_path":"authority-candidates/n.md",'
                b'"reason":"r","proposed_body":"x","expected_context_impact":[__V__]}')
        for token in (b"Infinity", b"-Infinity", b"NaN", b"1e999"):
            r = propose.submit(["--context", folder], tmpl.replace(b"__V__", token))
            check(r["result"] == "refused" and "not_json" in {p["code"] for p in r["problems"]},
                  f"a non-finite JSON value ({token.decode()}) is refused as not valid JSON")
        check(pending_files(folder) == before_nonfinite, "and nothing is filed for a non-finite value")
        check(propose.submit(["--context", folder], b"\xef\xbb\xbf" + json.dumps(good).encode())["result"]
              == "pending", "a byte-order mark before the JSON is ignored")
        for argv in ([], ["--context"], ["--context", folder, "--extra"], ["--repo", folder]):
            r = propose.submit(argv, json.dumps(good).encode())
            check(r["result"] == "refused" and r["problems"][0]["code"] == "bad_command",
                  f"command line {argv[:2]}: refused, not filed")

        plain = tempfile.mkdtemp(prefix="charter-plain-")
        r = submit(plain, good)
        check(r == {"result": "unavailable", "retryable": False, "problem": r["problem"]}
              and r["problem"]["code"] == "context_not_found", "a folder that is not an Agent Context: unavailable, not retryable")
        inner = os.path.join(folder, "authoritative")
        check(submit(inner, good)["problem"]["code"] == "context_not_found",
              "`.` is never resolved upward to an enclosing Agent Context")
        shutil.rmtree(plain)
        write(folder, "notes.txt", b"x")
        r = submit(folder, good)
        check(r["result"] == "unavailable" and r["problem"]["code"] == "context_invalid" and not r["retryable"],
              "an Agent Context that is not valid and clean: unavailable, for a person to correct")
        os.remove(os.path.join(folder, "notes.txt"))

        cs = ps.PrivateState.default().for_context(folder)
        before = pending_files(folder)
        with cs.lock("intake"):
            apx.INTAKE_TIMEOUT, saved = 0.2, apx.INTAKE_TIMEOUT
            try:
                r = submit(folder, good)
            finally:
                apx.INTAKE_TIMEOUT = saved
        check(r["result"] == "unavailable" and r["retryable"] is True and r["problem"]["code"] == "intake_busy"
              and pending_files(folder) == before, "intake busy: unavailable, retryable, nothing filed")
        check(json.dumps(r).find(cs.base) == -1 and json.dumps(r).find("contexts") == -1,
              "no result names private state")
        shutil.rmtree(folder)


def case_front_matter() -> None:
    print("\na proposed body never brings front matter of its own")
    block = "---\nid: from-agent\ntitle: From agent\nauthority: authoritative\n---\n\n"
    with isolated_private_state():
        folder, candidate = setup()
        cs = ps.PrivateState.default().for_context(folder)
        create = {"agent": "a", "operation": "create", "target_path": "authority-candidates/fm.md", "reason": "r"}
        amend_gov = {"agent": "a", "operation": "amend", "target_path": "authoritative/a.md", "reason": "r",
                     "base_sha256": sha(folder, "authoritative/a.md")}
        amend_cand = {"agent": "a", "operation": "amend", "target_path": candidate, "reason": "r",
                      "base_sha256": ac.sha256_text(cs.read_candidate(candidate))}
        bodies = (("a front-matter block", block + "Text.\n"),
                  ("one after a byte-order mark", "﻿" + block + "Text.\n"),
                  ("one after blank lines", "\n\n  \n" + block + "Text.\n"),
                  ("one with CRLF line endings", block.replace("\n", "\r\n") + "Text.\r\n"))
        before = snapshot(folder)
        for label, base in (("create", create), ("amend of a governing document", amend_gov),
                            ("amend of a candidate", amend_cand)):
            for what, body in bodies:
                result = submit(folder, dict(base, proposed_body=body))
                check(result["result"] == "refused" and ("front_matter_in_body", "proposed_body") in codes(result)
                      and "sets a candidate's metadata itself" in result["problems"][0]["message"]
                      and "proposed_meta" in result["problems"][0]["message"],
                      f"{label} whose body begins with {what}: refused, saying why and what to do instead")
        result = submit(folder, dict(amend_gov, replacements=[{"find": "Body.", "replace": block + "Body."}]))
        check(result["result"] == "refused" and ("front_matter_in_body", "replacements") in codes(result),
              "replacements that would leave front matter at the top are refused too")
        check(pending_files(folder) == [] and snapshot(folder) == before,
              "nothing was filed, and the Agent Context is unchanged")
        for what, body in (("that opens with a thematic break", "---\nProse after a thematic break.\n---\n\nMore.\n"),
                           ("that opens with an unclosed pseudo block", "---\ntitle: never closed\n\nText.\n"),
                           ("with a fenced block only later in its text", "Intro.\n\n---\nid: x\n---\n")):
            result = submit(folder, dict(create, target_path=f"authority-candidates/ok-{len(pending_files(folder))}.md",
                                         proposed_body=body))
            check(result["result"] == "pending", f"a body {what} is ordinary Markdown, and filed")
        filed = [json.loads(open(cs.path(ps.PROPOSALS, apx.PENDING, n), encoding="utf-8").read())
                 for n in pending_files(folder)]
        check(sorted(r["proposal"]["proposed_body"] for r in filed) == sorted(
            ["---\nProse after a thematic break.\n---\n\nMore.\n", "---\ntitle: never closed\n\nText.\n",
             "Intro.\n\n---\nid: x\n---\n"]), "and filed exactly as proposed, never rewritten")
        shutil.rmtree(folder)


def case_process() -> None:
    print("\nthe real command")
    with tempfile.TemporaryDirectory(prefix="charter-propose-") as tmp:
        with isolated_private_state(tmp):
            folder, _candidate = setup()
        good = {"agent": "cli-test", "operation": "create", "target_path": "authority-candidates/from-cli.md",
                "reason": "From the command line.", "proposed_body": "# From the CLI\n\nText.\n"}

        def run(data: bytes, cwd: str, *args: str) -> subprocess.CompletedProcess:
            return subprocess.run([sys.executable, os.path.join(HERE, "_launch.py"), tmp, "propose", *args],
                                  input=data, cwd=cwd, capture_output=True, timeout=120)
        out = run(json.dumps(good).encode(), folder, "--context", ".")
        result = json.loads(out.stdout)
        check(out.returncode == 0 and out.stderr == b"" and out.stdout.count(b"\n") == 1
              and result["result"] == "pending",
              "`charter propose --context .` in the Agent Context: `pending`, exit 0, one line, nothing on stderr")
        out = run(b'{"agent": "x"}', folder, "--context", ".")
        check(out.returncode == 3 and json.loads(out.stdout)["result"] == "refused" and out.stderr == b"",
              "refused: exit 3")
        fronted = dict(good, target_path="authority-candidates/fronted.md",
                       proposed_body="﻿\n---\ntitle: Fronted\nstatus: active\n---\n\nText.\n")
        out = run(json.dumps(fronted).encode(), folder, "--context", ".")
        refused = json.loads(out.stdout)
        check(out.returncode == 3 and refused["result"] == "refused"
              and [p["code"] for p in refused["problems"]] == ["front_matter_in_body"] and out.stderr == b"",
              "a body beginning with front matter, after a byte-order mark: refused by the real command, exit 3")
        out = run(json.dumps(good).encode(), tmp, "--context", ".")
        check(out.returncode == 4 and json.loads(out.stdout)["result"] == "unavailable", "unavailable: exit 4")
        out = run(b"", tmp, "--nonsense")
        check(out.returncode == 3 and out.stderr == b"" and json.loads(out.stdout)["problems"][0]["code"] == "bad_command",
              "even a bad command line gets one JSON result")
        out = subprocess.run([sys.executable, os.path.join(ROOT, "charter.py"), "propose", "--help"],
                             capture_output=True, timeout=60, stdin=subprocess.DEVNULL)
        check(out.returncode == 0 and b"charter propose --context" in out.stdout and out.stderr == b""
              and b"`duplicate`" in out.stdout and b"exit 5" in out.stdout,
              "`charter propose --help` explains it, `duplicate` and exit 5 included")
        with isolated_private_state(tmp):
            check(len(pending_files(folder)) == 1, "exactly one record was filed")

        print("\nthe real command: an exact duplicate of a waiting proposal")

        def private_bytes() -> dict:
            out = {}
            for d, _dirs, names in os.walk(os.path.join(tmp, "state")):
                for n in names:
                    with open(os.path.join(d, n), "rb") as fh:
                        out[os.path.relpath(os.path.join(d, n), tmp)] = fh.read()
            return out
        before = private_bytes()
        out = run(json.dumps(good).encode(), folder, "--context", ".")
        dup = json.loads(out.stdout)
        check(out.returncode == 5 and out.stderr == b"" and out.stdout.count(b"\n") == 1
              and dup == {"result": "duplicate", "problem": {"code": "duplicate", "message": dup["problem"]["message"]}}
              and "change the proposal," in dup["problem"]["message"]
              and "replace the waiting proposal" in dup["problem"]["message"],
              "the same bytes again: `duplicate`, exit 5, telling the agent to change the proposal "
              "or ask a person")
        check("proposal_id" not in out.stdout.decode() and "From the CLI" not in out.stdout.decode()
              and "p-" not in dup["problem"]["message"],
              "it reveals nothing about the waiting proposal beyond its existence")
        check(private_bytes() == before, "and changes nothing: every private file is byte for byte as it was")
        reordered = dict(reversed(list(good.items())))
        for label, data in (("a trailing newline", json.dumps(good).encode() + b"\n"),
                            ("a byte-order mark", b"\xef\xbb\xbf" + json.dumps(good).encode()),
                            ("two byte-order marks", b"\xef\xbb\xbf" * 2 + json.dumps(good).encode()),
                            ("other spacing", json.dumps(good, indent=2).encode()),
                            ("its keys in another order", json.dumps(reordered).encode()),
                            ("a key written with a JSON escape",
                             json.dumps(good).replace('"agent"', '"\\u0061gent"').encode())):
            out = run(data, folder, "--context", ".")
            check(out.returncode == 5 and json.loads(out.stdout)["result"] == "duplicate",
                  f"{label}: the same content, so a `duplicate`, exit 5 (Product Specification §3.2)")
        check(private_bytes() == before, "none of them changed anything")
        for field, value in (("agent", "another-agent"), ("reason", "Another reason."),
                             ("expected_context_impact", "Related: none.")):
            out = run(json.dumps(dict(good, **{field: value})).encode(), folder, "--context", ".")
            check(out.returncode == 0 and json.loads(out.stdout)["result"] == "pending",
                  f"a different `{field}` makes a distinct proposal: filed, exit 0")
        with isolated_private_state(tmp):
            check(len(pending_files(folder)) == 4, "four distinct records wait, and no duplicate was filed")


def case_candidate_name_privacy() -> None:
    print("\ncandidate and archived names are private to agents (Product Specification)")
    with isolated_private_state():
        folder, candidate = setup()  # a private candidate authority-candidates/draft.md exists
        gov = ac.examine(folder).documents[0].path  # a governing document the map lists
        amend = lambda tp, h: {"agent": "a", "operation": "amend", "target_path": tp,
                               "reason": "r", "base_sha256": h,
                               "replacements": [{"find": "x", "replace": "y"}]}

        # 1. A create whose name collides with a private candidate is filed, and
        #    never told the name is taken.
        r = submit(folder, {"agent": "a", "operation": "create",
                            "target_path": "authority-candidates/draft.md",
                            "reason": "r", "proposed_body": "# X\n\nBody.\n"})
        check(r["result"] == "pending"
              and "target_in_use" not in {p["code"] for p in r.get("problems", [])},
              "a create colliding with a private candidate is filed, not told the name is taken")

        # 2. An unknown candidate and a stale candidate are refused identically.
        unknown = submit(folder, amend("authority-candidates/no-such.md", "0" * 64))
        stale = submit(folder, amend(candidate, "0" * 64))  # the real candidate, wrong hash
        check(unknown["result"] == "refused" and stale["result"] == "refused"
              and codes(unknown) == codes(stale),
              "an unknown candidate and a stale candidate are refused identically")
        check(not ({"stale", "target_unknown"} & {p["code"] for p in stale["problems"]}),
              "neither the `stale` nor the `target_unknown` code is used for a private candidate")

        # 3. A governing document is public (the map lists it): a wrong hash is still `stale`.
        g = submit(folder, {"agent": "a", "operation": "amend", "target_path": gov, "reason": "r",
                            "base_sha256": "0" * 64, "proposed_body": "# G\n\nNew.\n"})
        check("stale" in {p["code"] for p in g["problems"]},
              "a governing document still reports a wrong hash as stale")

        # 4. Accepting the colliding create assigns a free name, keeping the candidate.
        before = ps.PrivateState.default().for_context(folder).candidates()
        p = au.plan(folder, "accept-proposal", {"proposal_id": r["proposal_id"]})
        au.apply(folder, "accept-proposal", p.request, p.plan_id, True)
        after = ps.PrivateState.default().for_context(folder).candidates()
        check(candidate in after and len(after) == len(before) + 1,
              "accepting the colliding create keeps the existing candidate and adds one under a free name")

        # 5. An archived name is private too: a create colliding with it is still filed.
        rp = au.plan(folder, "retire", {"candidate": candidate})
        au.apply(folder, "retire", rp.request, rp.plan_id, True)  # draft.md now archived
        again = submit(folder, {"agent": "a", "operation": "create",
                                "target_path": "authority-candidates/draft.md",
                                "reason": "r", "proposed_body": "# Y\n\nBody.\n"})
        check(again["result"] == "pending"
              and "target_in_use" not in {p["code"] for p in again.get("problems", [])},
              "a create colliding with an archived name is filed, not told the name is taken")
        shutil.rmtree(folder)


def case_piped_non_ascii() -> None:
    print("\npiped output with non-ASCII is reliable (Windows code page)")
    with tempfile.TemporaryDirectory(prefix="charter-piped-") as tmp:
        with isolated_private_state(tmp):
            folder = context()
            generate(folder, "日本語プロジェクト")  # CJK name

        # Force a non-UTF-8 console code page in the child, as a redirected
        # Windows pipe gives by default: cp1252 cannot encode the arrow or the
        # CJK name, so the old behaviour crashes. The fix must hold regardless.
        env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0",
               "PYTHONLEGACYWINDOWSSTDIO": "1"}

        def launch(data, *args):
            return subprocess.run([sys.executable, os.path.join(HERE, "_launch.py"), tmp, *args],
                                  input=data, cwd=folder, capture_output=True, timeout=120, env=env)

        # propose: a refusal echoing a non-ASCII field name must still be exactly
        # one JSON line with nothing on stderr, whatever the console code page.
        bad = json.dumps({"agent": "a", "operation": "create",
                          "target_path": "authority-candidates/n.md", "reason": "r",
                          "proposed_body": "x\n", "note→": 1}).encode("utf-8")
        out = launch(bad, "propose", "--context", folder)
        check(out.returncode == 3 and out.stderr == b"" and out.stdout.count(b"\n") == 1,
              "propose returns one JSON line and nothing on stderr, even echoing a non-ASCII field name")
        check(json.loads(out.stdout)["result"] == "refused", "and it is a clean refusal")
        # check: its report names the project, which here holds non-ASCII.
        out = subprocess.run([sys.executable, os.path.join(HERE, "_launch.py"), tmp, "check",
                              "--context", folder], capture_output=True, timeout=120,
                             stdin=subprocess.DEVNULL, env=env)
        check(out.returncode == 0,
              "check on a valid context exits 0 even with a non-ASCII name on a pipe")
        check("日本語".encode("utf-8") in out.stdout,
              "and its piped output is UTF-8, carrying the name intact")
        with isolated_private_state(tmp):
            shutil.rmtree(folder, ignore_errors=True)


def case_retryable() -> None:
    """Product Specification §3.3: only `unavailable` may be retried unchanged,
    and only when it says `retryable` is true, so it says so only when a retry
    can succeed without anything changing."""
    print("\nretryable only when a retry can succeed unchanged")
    import errno
    from app import host_state as hs
    good = {"agent": "a", "operation": "create", "target_path": "authority-candidates/r.md",
            "reason": "r", "proposed_body": "x\n"}

    def windows_error(code: int, message: str, winerror: int) -> OSError:
        """The error Windows raises, with its `winerror`. Only Windows' OSError takes
        one as an argument; elsewhere it is set, so every platform checks the
        Windows classification."""
        if os.name == "nt":
            return OSError(code, message, None, winerror)
        error = OSError(code, message)
        error.winerror = winerror  # type: ignore[attr-defined]
        return error

    failures = (
        ("a path too long for this computer", windows_error(errno.ENOENT, "path", 206), False),
        ("a name too long", OSError(errno.ENAMETOOLONG, "name too long"), False),
        ("a permission denied", PermissionError(errno.EACCES, "denied"), False),
        ("an EACCES with no Windows error code, as macOS and Linux raise it",
         OSError(errno.EACCES, "denied"), False),
        ("a missing folder", FileNotFoundError(errno.ENOENT, "missing"), False),
        ("another program holding the file (Windows sharing violation, 32)",
         windows_error(errno.EACCES, "in use", 32), True),
        ("a lock violation (Windows, 33)", windows_error(errno.EACCES, "locked", 33), True),
        ("a busy file", OSError(errno.EBUSY, "busy"), True),
    )
    with isolated_private_state():
        folder, _candidate = setup()
        original = hs.write_json_atomic
        for label, error, retryable in failures:
            def failing(*_args, _error=error, **_kwargs):
                raise _error
            hs.write_json_atomic = failing
            try:
                result = submit(folder, good)
            finally:
                hs.write_json_atomic = original
            check(result["result"] == "unavailable" and result["retryable"] is retryable,
                  f"{label}: unavailable, retryable {str(retryable).lower()}")
        check(submit(folder, good)["result"] == "pending", "and once it is corrected, filing works")
        shutil.rmtree(folder)


def case_map_format_mismatch() -> None:
    print("\na map-format mismatch: nothing filed, nothing written, and why")
    from tests.agent_context import with_map_format
    with isolated_private_state() as root:
        folder, _candidate = setup()
        good = {"agent": "cli-test", "operation": "create", "target_path": "authority-candidates/mm.md",
                "reason": "r", "proposed_body": "x\n"}

        def private_bytes() -> dict:
            out = {}
            for d, _dirs, names in os.walk(root):
                for n in names:
                    with open(os.path.join(d, n), "rb") as fh:
                        out[os.path.relpath(os.path.join(d, n), root)] = fh.read()
            return out
        for version, code, words in ((1, "map_outdated", "rebuild it"),
                                     (2, "map_outdated", "rebuild it"),
                                     (ac.MAP_FORMAT_VERSION + 1, "charter_outdated", "out of date")):
            with_map_format(folder, version)
            before = private_bytes()
            result = submit(folder, good)
            check(result["result"] == "unavailable" and result["retryable"] is False
                  and result["problem"]["code"] == code and words in result["problem"]["message"]
                  and "nothing was filed" in result["problem"]["message"],
                  f"map-format version {version}: `unavailable`, not retryable, `{code}`, saying why")
            check(private_bytes() == before and pending_files(folder) == [],
                  "and nothing was written: no record, ledger entry or private state")
        shutil.rmtree(folder)


def case_command_line_access_route() -> None:
    """Product Specification §3.3: `--context` names the Agent Context root as
    `.` from the folder, or as the absolute path a Command-Line Access agent's
    project instructions give; no result sends an agent to find the folder."""
    print("\nCommand-Line Access: `propose --context <absolute path>` from anywhere; `.` still works")
    launch = os.path.join(HERE, "_launch.py")
    with isolated_private_state() as state_root:
        folder = context()
        outside = tempfile.mkdtemp(prefix="charter-elsewhere-")
        state = os.path.dirname(state_root)  # `_launch` puts private state at <state>/state

        def run_propose(argv, data: bytes, cwd: str) -> tuple:
            p = subprocess.run([sys.executable, launch, state, "propose"] + argv, input=data,
                               capture_output=True, cwd=cwd)
            return p.returncode, json.loads(p.stdout), p.stderr

        body = "# Probe — dash\n\nCafé, naïve, “curly quotes”.\n"
        good = {"agent": "cla", "operation": "create", "target_path": "authority-candidates/cla.md",
                "reason": "Command-Line Access route.", "proposed_body": body}
        data = json.dumps(good, ensure_ascii=True).encode("ascii")
        before = snapshot(folder)
        code, out, err = run_propose(["--context", folder], data, outside)
        check(code == 0 and out["result"] == "pending" and err == b"" and data.isascii(),
              "from an unrelated folder, with the absolute path: `pending`, exit 0, nothing on stderr")
        cs = ps.PrivateState.default().find_context(folder)
        record = json.load(open(cs.path(ps.PROPOSALS, apx.PENDING, out["proposal_id"] + ".json"),
                                encoding="utf-8"))
        check(record["proposal"]["proposed_body"] == body,
              "ASCII JSON with Unicode escapes files the em dash, accents and curly quotes exactly")
        check(snapshot(folder) == before, "the Agent Context folder is unchanged: no authority change")
        for argv, cwd, label in ((["--context", "."], folder, "`--context .` in the folder"),
                                 (["--context", folder + os.sep], outside, "the absolute path with a trailing separator")):
            code, out, _ = run_propose(argv, data, cwd)
            check(code == 5 and out["result"] == "duplicate",
                  f"{label}: the same proposal is a `duplicate`, exit 5 — one Agent Context, one queue")
        amend = {"agent": "cla", "operation": "amend", "target_path": "authoritative/a.md",
                 "reason": "Stale.", "base_sha256": "0" * 64,
                 "replacements": [{"find": "Body.", "replace": "Body, amended."}]}
        code, out, _ = run_propose(["--context", folder], json.dumps(amend).encode(), outside)
        check(code == 3 and any(p["code"] == "stale" for p in out["problems"]),
              "a stale amend through the absolute path: `refused`, exit 3")
        for target, label in ((folder + "-missing", "a missing folder"),
                              (os.path.join(folder, "authoritative"), "a folder inside the Agent Context"),
                              (os.path.dirname(folder), "the folder above it")):
            code, out, err = run_propose(["--context", target], data, outside)
            message = out["problem"]["message"]
            check(code == 4 and out["result"] == "unavailable" and out["retryable"] is False
                  and out["problem"]["code"] == "context_not_found" and err == b""
                  and "Do not search for one" in message and "return the complete proposal JSON" in message
                  and not re.search(r"run the command in|in the folder that holds|move into|find|locate",
                                    message, re.I),
                  f"{label}: `unavailable`, exit 4, never searched, and the message sends the agent to "
                  "import, never to look for the folder")
        code, out, _ = run_propose([], data, outside)
        message = out["problems"][0]["message"]
        check(code == 3 and out["problems"][0]["code"] == "bad_command"
              and "Do not search for an Agent Context" in message
              and not re.search(r"run .* in the folder|in the folder that holds|move into|locate", message, re.I),
              "no `--context`: `refused` `bad_command`, naming no place to run it and no search")
        shutil.rmtree(outside)
        shutil.rmtree(folder)


def run() -> None:
    case_create()
    case_amend_and_retire()
    case_results()
    case_retryable()
    case_front_matter()
    case_candidate_name_privacy()
    case_piped_non_ascii()
    case_process()
    case_map_format_mismatch()
    case_command_line_access_route()
    print(f"\n{OK} All propose checks passed.")


if __name__ == "__main__":
    run()
