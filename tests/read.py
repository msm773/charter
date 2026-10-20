"""`charter read`: Command-Line Access to an Agent Context. Run: python -m tests.read

Agent Context as the Project Asset §9 and acceptance criterion 18:

  * four forms, each answering exactly as its MCP tool does, after the same
    validation, as text ending with `<<<END CHARTER READ>>>` or as one JSON
    object without it;
  * `--context` is an absolute path, every time: omitted, empty or relative is
    `bad-arguments`, exit 2, with the exact governed message and no prior-
    context warning; nothing else — the current folder, an environment
    variable, a search — ever names the folder;
  * exactly the governed reason codes, `charter-outdated` for a copy older than
    the map; every unavailable named context ends with the do-not-rely
    sentence and serves nothing; `changed-during-read` allows one retry;
  * nothing on standard error; no private state, activity or Recent written;
  * MCP itself answers as it did.
"""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import manager as mg  # noqa: E402
from app import mcp  # noqa: E402
from app import private_store as ps  # noqa: E402
from app import read  # noqa: E402
from app import transaction as tx  # noqa: E402
from tests.agent_context import (context, doc_text, generate, with_map_format,  # noqa: E402
                                 write)
from tests.harness import isolated_private_state  # noqa: E402
from tests.mcp import SECTIONED, fixture  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAUNCH = os.path.join(HERE, "_launch.py")
OK = "ok"
MARKER = "<<<END CHARTER READ>>>"
DO_NOT_RELY = ("Do not rely on Charter context you retrieved earlier in this session. Report to "
               "the person that Charter context is unavailable, rather than guessing or continuing "
               "from earlier context.")
NOT_NAMED = ("No Agent Context was named, so nothing is served. Run the exact command your project "
             "instructions give, and do not search for an Agent Context.")
NOT_ABSOLUTE = ("The Agent Context must be named by its full path, so nothing is served. Run the "
                "exact command your project instructions give, and do not search for an Agent "
                "Context.")
CHANGED = ("A file changed while it was being read, so nothing was returned. Run the exact same "
           "command once more. If you have already run it once more after this result, or that run "
           "does not succeed, do not run it again. " + DO_NOT_RELY)
GOVERNED_CODES = ("context-invalid", "context-unclean", "map-outdated", "charter-outdated",
                  "changed-during-read", "not-governing", "unsafe-path", "heading-missing",
                  "heading-ambiguous", "bad-arguments")
POLICY = "authoritative/policy.md"
# Nothing an agent could use as context: no path, title, scope, excerpt or map text.
LEAKS = ("authoritative", ".md", "AGENT-CONTEXT", ".agent-context", "Policy", "Alpha", "Beta",
         "scope", "Inside the lines", "Boundaries", "Current governing", "Test project", "sha256")


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def run_read(argv: list, state: str, cwd: str = None, env: dict = None) -> tuple:
    """`charter read …` as a separate process, as an agent's shell runs it:
    (exit code, stdout bytes, stderr bytes)."""
    p = subprocess.run([sys.executable, LAUNCH, state, "read"] + argv, capture_output=True,
                       cwd=cwd or ROOT, env=env, stdin=subprocess.DEVNULL)
    return p.returncode, p.stdout, p.stderr


def in_process(argv: list) -> tuple:
    data, code = read.result(argv)
    return code, data.decode("utf-8")


def tree(root: str) -> dict:
    """Every file under `root` and its bytes: what the private state holds."""
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            p = os.path.join(dirpath, name)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = fh.read()
    return out


def leaked(text: str, folder: str) -> list:
    return [w for w in LEAKS + (folder,) if w.lower() in text.lower()]


FORMS = (([], "get_context", None),
         (["--list"], "list_governing_documents", None),
         (["--document", POLICY], "get_document", {"document": POLICY}),
         (["--document", "policy", "--heading", "Boundaries"], "get_document_section",
          {"document": "policy", "heading": "Boundaries"}))


def case_forms() -> None:
    print("\nthe four forms answer exactly as their MCP tools do, as text or as one JSON object")
    with isolated_private_state():
        folder = fixture()
        state = tempfile.mkdtemp(prefix="charter-read-")
        server = mcp.Server(folder, record=False)
        server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
        for extra, tool, arguments in FORMS:
            reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": tool, "arguments": arguments}})["result"]
            mcp_text, mcp_payload = reply["content"][0]["text"], reply["structuredContent"]
            label = "charter read" + ("" if not extra else " " + " ".join(extra))
            code, out, err = run_read(["--context", folder] + extra, state)
            text = out.decode("utf-8")
            body = mcp_text if mcp_text.endswith("\n") else mcp_text + "\n"
            check(code == 0 and err == b"" and text == body + MARKER + "\n",
                  f"{label}: exit 0, {tool}'s exact text, then the marker as the last line, "
                  "nothing on standard error")
            check(text.count(MARKER) == 1 and text.splitlines()[-1] == MARKER,
                  "  the marker appears once, on its own final line")
            code, out, err = run_read(["--context", folder, "--json"] + extra, state)
            obj = json.loads(out.decode("ascii"))
            check(code == 0 and err == b"" and out.endswith(b"}\n") and out.count(b"\n") == 1
                  and MARKER.encode() not in out
                  and obj == dict({"result": "served"}, **mcp_payload),
                  f"  --json: exactly one JSON object, `result: served` with {tool}'s structured "
                  "fields, and no marker")
        check(os.listdir(state) == [] or not tree(state),
              "serving them created no private state at all")
        # Options in any order, and `--option=value`, are the same request.
        code, out, _ = run_read(["--heading=Boundaries", "--json", "--document=" + POLICY,
                                 "--context=" + folder], state)
        check(code == 0 and json.loads(out)["heading"] == "Boundaries",
              "options may come in any order, and as `--option=value`")
        shutil.rmtree(folder)
        shutil.rmtree(state)


def case_naming_the_context() -> None:
    print("\n`--context` must be an absolute path: nothing else ever names the folder")
    with isolated_private_state():
        folder = fixture()
        state = tempfile.mkdtemp(prefix="charter-read-")
        parent, name = os.path.split(folder)
        relative = [".", name, os.path.join(".", name), os.path.join("..", name), "~", "relative"]
        if os.name == "nt":
            drive, rest = os.path.splitdrive(folder)
            relative += [rest, drive + name]  # `\…` (current drive) and `C:name` (current folder)
        cases = [([], NOT_NAMED, "omitted"), (["--context"], NOT_NAMED, "with no value"),
                 (["--context", ""], NOT_NAMED, "empty"), (["--context="], NOT_NAMED, "empty, as --context="),
                 (["--list"], NOT_NAMED, "omitted, with another option")]
        cases += [(["--context", r], NOT_ABSOLUTE, f"relative: {r!r}") for r in relative]
        env = dict(os.environ, CHARTER_CONTEXT=folder, CHARTER_AGENT_CONTEXT=folder)
        for argv, message, label in cases:
            for as_json in (False, True):
                code, out, err = run_read(argv + (["--json"] if as_json else []), state,
                                          cwd=parent if "." in "".join(argv) or name in "".join(argv)
                                          else folder, env=env)
                text = out.decode("utf-8")
                if as_json:
                    obj = json.loads(text)
                    ok = obj == {"result": "refused", "reason": "bad-arguments", "message": message}
                else:
                    ok = text == f"bad-arguments: {message}\n"
                check(code == 2 and err == b"" and ok and MARKER not in text
                      and "Do not rely" not in text,
                      f"{label}{' (--json)' if as_json else ''}: `bad-arguments`, exit 2, the exact "
                      "message, no prior-context warning, nothing served")
        # Run inside the valid Agent Context, with variables naming it: still nothing.
        code, out, _ = run_read([], state, cwd=folder, env=env)
        check(code == 2 and out.decode() == f"bad-arguments: {NOT_NAMED}\n",
              "run in the Agent Context folder itself, with environment variables naming it, a "
              "command that names no folder is still refused: no current-folder or environment "
              "fallback")
        # A folder above or below a valid context is not that context.
        code, out, _ = run_read(["--context", parent], state)
        check(code == 1 and out.decode().startswith("context-") and "Policy" not in out.decode(),
              "the folder above an Agent Context is refused, never searched below")
        code, out, _ = run_read(["--context", os.path.join(folder, "authoritative")], state)
        check(code == 1 and out.decode().startswith("context-"),
              "a folder inside it is refused, never searched above")
        check(not tree(state), "no refusal created private state")
        shutil.rmtree(folder)
        shutil.rmtree(state)


def case_bad_options() -> None:
    print("\nany other combination of options is `bad-arguments`, exit 2")
    with isolated_private_state():
        folder = fixture()
        c = ["--context", folder]
        for argv, label in ((c + ["--unknown"], "an unknown option"),
                            (c + ["--help"], "--help, which is not one of the four forms"),
                            (c + ["--list", "--list"], "a repeated option"),
                            (c + ["--context", folder], "a repeated --context"),
                            (c + ["--json", "--json"], "a repeated --json"),
                            (c + ["--heading", "Boundaries"], "--heading without --document"),
                            (c + ["--list", "--document", POLICY], "--list with --document"),
                            (c + ["--document"], "--document with no value"),
                            (c + ["--document", ""], "an empty --document"),
                            (c + ["--document", POLICY, "--heading", ""], "an empty --heading"),
                            (c + ["--list=yes"], "a flag given a value"),
                            (c + [POLICY], "a bare word"),
                            (c + ["--document", "x" * (mcp.MAX_REF + 1)], "a document name too long"),
                            (c + ["--document", POLICY, "--heading", "x" * (mcp.MAX_HEADING + 1)],
                             "a heading too long")):
            code, text = in_process(argv)
            expected = (json.dumps({"result": "refused", "reason": "bad-arguments",
                                    "message": read.BAD_OPTIONS}) + "\n" if "--json" in argv
                        else f"bad-arguments: {read.BAD_OPTIONS}\n")
            check(code == 2 and text == expected and "Do not rely" not in text and MARKER not in text,
                  f"{label}: `bad-arguments`, exit 2, served nothing")
        shutil.rmtree(folder)


def case_refusals() -> None:
    print("\nevery unavailable named context serves nothing, and says not to rely on earlier context")
    with isolated_private_state():
        folder = fixture()
        state = tempfile.mkdtemp(prefix="charter-read-")
        approved = {rel: open(os.path.join(folder, *rel.split("/")), "rb").read()
                    for rel in (ac.CONTEXT_MAP, ac.METADATA, POLICY, "authoritative/a.md")}

        def restore() -> None:
            for extra in ("notes.txt",):
                p = os.path.join(folder, extra)
                if os.path.exists(p):
                    os.remove(p)
            for rel, data in approved.items():
                write(folder, rel, data)

        a_file = os.path.join(state, "not-a-folder.txt")
        with open(a_file, "w") as fh:
            fh.write("x")
        situations = (
            ("a missing folder", lambda: None, folder + "-missing", "context-invalid",
             "No Agent Context could be read at the folder this command names"),
            ("a file, not a folder", lambda: None, a_file, "context-invalid",
             "No Agent Context could be read at the folder this command names"),
            ("a stray file (not clean)", lambda: write(folder, "notes.txt", b"mine"), folder,
             "context-unclean", "holds files that are not part of it"),
            ("a governing document changed", lambda: write(folder, "authoritative/a.md",
                                                           doc_text("a", "Alpha", body="Edited.\n")),
             folder, "context-invalid", "1 file does not match the approved context"),
            ("no usable map", lambda: os.remove(os.path.join(folder, ac.METADATA)), folder,
             "context-invalid", "documents are not in an approved context"),
            ("an older map format", lambda: with_map_format(folder, 2), folder, "map-outdated",
             "Rebuild Agent Context"),
            ("a newer map format than this copy", lambda: with_map_format(folder, ac.MAP_FORMAT_VERSION + 1),
             folder, "charter-outdated", "A person must update this copy of Charter."),
        )
        for label, damage, target, code_expected, said in situations:
            damage()
            for extra, _tool, _args in FORMS:
                code, out, err = run_read(["--context", target] + extra, state)
                text = out.decode("utf-8")
                check(code == 1 and err == b"" and text.startswith(code_expected + ": ")
                      and said in text and text.rstrip("\n").endswith(DO_NOT_RELY)
                      and MARKER not in text and not leaked(text, folder)
                      and not any(ch.isdigit() for ch in text.replace("1 file", "")
                                  .replace("3 documents", "")),
                      f"{label} ({' '.join(extra) or 'the map'}): `{code_expected}`, exit 1, ending "
                      "with the do-not-rely sentence, with no path, version or context material")
            code, out, _ = run_read(["--context", target, "--json"], state)
            obj = json.loads(out)
            check(code == 1 and set(obj) == {"result", "reason", "message"}
                  and obj["result"] == "refused" and obj["reason"] == code_expected
                  and obj["message"].endswith(DO_NOT_RELY),
                  f"  --json: one object, `result: refused`, `{code_expected}`, the same message")
            restore()
            check(run_read(["--context", folder], state)[0] == 0, "  restored, it is served again")
        outdated = read.MESSAGES["charter-outdated"]
        check("not at fault" in outdated and "restart" not in outdated and "reconnect" not in outdated
              and "agent host" not in outdated and "server-outdated" not in outdated,
              "`charter-outdated` says the context is not at fault and never to restart or "
              "reconnect a host")
        check(all("read the" not in m and "files directly" not in m and "another folder" not in m
                  for m in read.MESSAGES.values())
              and "search" not in "".join(read.MESSAGES.values()).replace("do not search", ""),
              "no message tells the agent to read the files, search, or try another folder")
        # Requests a valid context cannot answer: not unavailable, so no do-not-rely.
        for extra, code_expected in ((["--document", "nope.md"], "not-governing"),
                                     (["--document", "../outside.md"], "unsafe-path"),
                                     (["--document", POLICY, "--heading", "Nowhere"], "heading-missing"),
                                     (["--document", POLICY, "--heading", "Exceptions"],
                                      "heading-ambiguous")):
            code, out, err = run_read(["--context", folder] + extra, state)
            text = out.decode("utf-8")
            check(code == 1 and err == b"" and text == f"{code_expected}: {read.MESSAGES[code_expected]}\n"
                  and "Do not rely" not in text and MARKER not in text
                  and "list_governing_documents" not in text,
                  f"`{code_expected}`: exit 1, naming `charter read --list` rather than an MCP tool")
        check(read.CODES == GOVERNED_CODES and "server-outdated" not in read.MESSAGES,
              "the reason codes are exactly the governed ten; `server-outdated` is never used")
        shutil.rmtree(folder)
        shutil.rmtree(state)


def case_unreadable_and_interrupted() -> None:
    print("\nan unreadable folder or an interrupted Charter write is `context-invalid`")
    with isolated_private_state():
        folder = fixture()
        real = os.scandir

        def denied(path="."):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(folder):
                raise PermissionError(path)
            return real(path)
        os.scandir = denied
        try:
            code, text = in_process(["--context", folder])
        finally:
            os.scandir = real
        check(code == 1 and text.startswith("context-invalid: No Agent Context could be read")
              and text.rstrip("\n").endswith(DO_NOT_RELY) and not leaked(text, folder),
              "a folder that cannot be listed: `context-invalid`, serving nothing")
        cs = ps.PrivateState.default().for_context(folder)
        write(cs.staging_dir(tx.JOURNAL_KIND), tx.JOURNAL_FILE, b"{}")
        before = tree(ps.PrivateState.default().root)
        code, text = in_process(["--context", folder, "--list"])
        check(code == 1 and text.startswith("context-invalid: ") and text.rstrip("\n").endswith(DO_NOT_RELY)
              and not leaked(text, folder),
              "a Charter write left interrupted: `context-invalid`, as MCP refuses it")
        check(tree(ps.PrivateState.default().root) == before,
              "  and nothing was recovered, rolled back or written")
        shutil.rmtree(folder)


def case_changed_during_read() -> None:
    print("\na file changed during the read: nothing returned, and one retry")
    with isolated_private_state():
        folder = fixture()
        real = mcp.answer
        changes = []

        def answer(name, args, exam):
            out = real(name, args, exam)
            if not changes:
                changes.append(1)
                write(folder, "authoritative/b.md", doc_text("b", "Beta", body="Changed meanwhile.\n"))
                generate(folder)
            return out
        mcp.answer = answer
        try:
            code, text = in_process(["--context", folder, "--document", POLICY])
            check(code == 1 and text == f"changed-during-read: {CHANGED}\n"
                  and "Inside the lines" not in text and MARKER not in text,
                  "the first read: `changed-during-read`, exit 1, the exact one-retry message, no "
                  "document text")
            check(CHANGED.count("once more") == 2 and "do not run it again" in CHANGED
                  and CHANGED.endswith(DO_NOT_RELY),
                  "  it allows exactly one retry, then says to stop, not rely, and report")
            code, text = in_process(["--context", folder, "--document", POLICY])
            check(code == 0 and "Inside the lines" in text and text.endswith(MARKER + "\n"),
                  "the one retry, after the change settled, is served")
        finally:
            mcp.answer = real
        code, out = in_process(["--context", folder, "--json", "--document", POLICY])
        check(code == 0, "nothing about the earlier refusal is remembered: retries are not counted")
        shutil.rmtree(folder)


def case_nothing_written() -> None:
    print("\nno private state, activity or Recent: reads only")
    from app import console
    from app import host_state as hs
    with isolated_private_state() as launch_state:
        folder = fixture()
        # The separate processes below use this same private state (`_launch`
        # puts it at `<state>/state`), where opening the folder in the console
        # left its private state and its Recent entry.
        state = os.path.dirname(launch_state)
        session = console.Session()
        console.open_context(session, {"path": folder})
        recent = console.state(console.Session()).get("recent", [])
        check(hs.canonical(folder) in recent and tree(launch_state),
              "the folder's private state exists, and it is in Recent, as the console leaves it")
        other = context()
        before = tree(launch_state)
        # A folder never opened in the console: reading it adds nothing for it.
        run_read(["--context", other], state)
        run_read(["--context", other, "--list"], state)
        for extra, _tool, _args in FORMS:
            for more in ([], ["--json"]):
                run_read(["--context", folder] + extra + more, state)
        run_read(["--context", folder, "--document", "nope.md"], state)
        run_read(["--context", "relative"], state)
        write(folder, "notes.txt", b"stray")
        run_read(["--context", folder], state)
        after = tree(launch_state)
        check(after == before,
              "after every form, served and refused: the private state is byte-for-byte unchanged "
              "— no activity, no Recent entry, no record")
        check(console.state(console.Session()).get("recent", []) == recent
              and hs.canonical(other) not in recent,
              "  Recent is exactly as it was: a folder only read is never added")
        shutil.rmtree(folder)
        shutil.rmtree(other)


def case_mcp_unchanged() -> None:
    print("\nMCP answers as before: its codes, messages and answers are its own")
    check(set(mcp.MESSAGES) == {"context-invalid", "context-unclean", "map-outdated", "server-outdated",
                                "changed-during-read", "not-governing", "unsafe-path",
                                "heading-missing", "heading-ambiguous", "bad-arguments"}
          and "charter-outdated" not in mcp.MESSAGES
          and "Call the tool again." in mcp.MESSAGES["changed-during-read"]
          and "restart the agent host" in mcp.MESSAGES["server-outdated"],
          "MCP keeps its own ten codes and messages, `server-outdated` and its host remedy included")
    with isolated_private_state():
        folder = fixture()
        server = mcp.Server(folder, record=False)
        exam = mcp.examine(folder)
        for _extra, tool, arguments in FORMS:
            args = arguments or {}
            check(server._answer(tool, args, exam) == mcp.answer(tool, args, exam),
                  f"the server's {tool} answer is the shared one")
        shutil.rmtree(folder)


def case_command_line() -> None:
    print("\nthe command line: `charter read` is its own command, listed in --help")
    p = subprocess.run([sys.executable, os.path.join(ROOT, "charter.py"), "--help"],
                       capture_output=True, text=True)
    check(p.returncode == 0 and "read" in p.stdout and "--context" in p.stdout,
          "`charter --help` lists `read`")
    state = tempfile.mkdtemp(prefix="charter-read-")
    code, out, err = run_read(["--context"], state)
    check(code == 2 and err == b"" and out.decode() == f"bad-arguments: {NOT_NAMED}\n",
          "a bad command line still gets the one governed answer on standard output, never "
          "argparse's on standard error")
    check(not hasattr(read, "propose") and "propose" not in open(read.__file__, encoding="utf-8")
          .read().replace("There is no proposal route", ""),
          "Command-Line Access has no proposal route")
    shutil.rmtree(state)


def case_format_4_transition() -> None:
    print("\nmap format 4: format 3 is out of date, Rebuild brings it current, older copies refuse it")
    with isolated_private_state():
        folder = fixture()
        code, text = in_process(["--context", folder])
        check(code == 0 and "If you received this file through `charter read`, submit each proposal to" in text
              and "Write each proposal as ASCII JSON" in text,
              "a format-4 map, read through `charter read`, gives its proposal route and the ASCII JSON rule")
        session_text = mcp.Server(folder, record=False)
        session_text.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                             "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
        reply = session_text.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                     "params": {"name": "get_context", "arguments": {}}})["result"]
        served = reply["content"][0]["text"]
        tools = session_text.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        check(not reply["isError"]
              and "If you received this file through MCP or any tool other than `charter read`,\ndo not "
                  "run `charter propose`" in served
              and mcp.INSTRUCTIONS == ("This server gives read-only access to this Agent Context. Call "
                                       "`get_context` before work, then use the listed document tools as "
                                       "needed. Authority candidates, archives, and Agent Proposals are "
                                       "not governing context.")
              and [t["name"] for t in tools["result"]["tools"]] == ["get_context", "list_governing_documents",
                                                                     "get_document", "get_document_section"],
              "MCP is unchanged: the same instructions and four read-only tools, and the map sends an MCP "
              "agent to return its proposal JSON for import")

        with_map_format(folder, 3)
        code, text = in_process(["--context", folder])
        check(code == 1 and text.startswith("map-outdated: ") and text.rstrip("\n").endswith(DO_NOT_RELY)
              and MARKER not in text,
              "a format-3 context, under this format-4 Charter: `charter read` refuses `map-outdated`")
        session = mcp.Server(folder, record=False)
        session.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
        result = session.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": "get_context", "arguments": {}}})["result"]
        check(result["isError"] and result["content"][0]["text"].startswith("map-outdated:"),
              "  and MCP refuses it `map-outdated` too")
        before = {rel: open(os.path.join(folder, *rel.split("/")), "rb").read()
                  for rel in (POLICY, "authoritative/a.md", "authoritative/b.md")}
        plan = mg.rebuild_plan(folder)
        status = mg.rebuild_apply(folder, plan.plan_id, True)
        check(status["agents_served"] and status["map_format"]["recorded"] == 4
              and all(open(os.path.join(folder, *rel.split("/")), "rb").read() == data
                      for rel, data in before.items()),
              "Rebuild brings it to format 4 and leaves every governing document byte-for-byte as it was")
        code, text = in_process(["--context", folder])
        check(code == 0 and "If you received this file through `charter read`" in text,
              "  after Rebuild, `charter read` serves the map with the new proposal route")

        # A copy of Charter that generates only format 3 — an agent host started
        # before the update, or an old copy a project's instructions name.
        saved = ac.MAP_FORMAT_VERSION, ac.OLDER_MAP_FORMATS
        ac.MAP_FORMAT_VERSION, ac.OLDER_MAP_FORMATS = 3, (1, 2)
        try:
            code, text = in_process(["--context", folder])
            old_session = mcp.Server(folder, record=False)
            old_session.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize",
                                "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
            old = old_session.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": "get_context", "arguments": {}}})["result"]
        finally:
            ac.MAP_FORMAT_VERSION, ac.OLDER_MAP_FORMATS = saved
        check(code == 1 and text.startswith("charter-outdated: ") and "update this copy of Charter" in text,
              "a format-3 copy run by `charter read` refuses the rebuilt context: `charter-outdated`")
        check(old["isError"] and old["content"][0]["text"].startswith("server-outdated:")
              and "restart the agent host" in old["content"][0]["text"],
              "  and a format-3 MCP server refuses it `server-outdated`, telling the person to restart the host")
        shutil.rmtree(folder)


def case_readme() -> None:
    print("\nthe README describes map format 4, the three proposal routes and ASCII JSON")
    with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as fh:
        readme = fh.read()
    check("This release generates map format 4" in readme and "map format 3" not in readme,
          "updating: this release generates map format 4, and every Agent Context needs one Rebuild")
    check("It has no proposal route" not in readme
          and "files proposals with the `charter propose` command in its instruction" in readme
          and "propose --context C:\\work\\my-project-context" in readme,
          "command-line access files proposals with the full-path command its instruction gives")
    check("**ASCII JSON.**" in readme and "turns them into `?`" in readme
          and "can't repair it" in readme
          and "an agent returning proposal JSON for you to import doesn't need it" in readme,
          "ASCII JSON for `charter propose`: why, that Charter can't repair a corrupted `?`, and that "
          "the import route is unaffected")
    check("| through MCP, or any other tool | nothing: it returns the proposal JSON" in readme,
          "MCP agents still return proposal JSON for import")


def run() -> None:
    case_forms()
    case_naming_the_context()
    case_bad_options()
    case_refusals()
    case_unreadable_and_interrupted()
    case_changed_during_read()
    case_nothing_written()
    case_mcp_unchanged()
    case_command_line()
    case_format_4_transition()
    case_readme()
    print(f"\n{OK} All charter read checks passed.")


if __name__ == "__main__":
    run()
