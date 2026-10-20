"""Connect agents: copy-ready text, offered only for a ready Agent Context.
Run: python -m tests.connect

  * the MCP configuration is one program and an exact list of arguments, never
    a command line for a shell: on Windows the Python running Charter with this
    copy's `charter.py`, elsewhere this copy's launcher, each by its full path,
    so PATH can never route an agent to another copy — the same for a release
    and a development checkout;
  * another copy first on PATH is named, with its remedy, and blocks nothing;
  * `claude mcp add` is quoted for PowerShell and for Command Prompt on
    Windows, and for a POSIX shell elsewhere. On Windows the commands are
    run through each real shell, with `claude` replaced by a program that
    prints the arguments it was given, and must arrive exactly;
  * the file-access instruction points at `AGENT-CONTEXT.md`;
  * an invalid or unclean folder, or one with an interrupted write, gets the
    reason and nothing to copy;
  * producing it, directly or through the console over HTTP, writes nothing
    anywhere: every file-writing call is refused while it runs, and the
    folder and private state are byte-for-byte unchanged.
"""
from __future__ import annotations

import builtins
import contextlib
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
from app import connect  # noqa: E402
from app import console  # noqa: E402
from app import manager as mg  # noqa: E402
from app import on_path  # noqa: E402
from app import server  # noqa: E402
from tests.agent_context import context, doc_text, read, snapshot, write  # noqa: E402
from tests.harness import isolated_private_state, seeded  # noqa: E402

OK = "ok"
PHRASE = "change governing context"
FORBIDDEN_WORDS = ("workspace", "surface", "publication", "publish", "binding", "cgu")


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


class Crash(BaseException):
    """A process dying mid-write: not caught as a failure, so nothing is rolled back."""
    pass


class FakeRegistry:
    def __init__(self, user: str = "", machine: str = "") -> None:
        self.user, self.machine = user, machine

    def user_path(self):
        return self.user, 2

    def machine_path(self):
        return self.machine


@contextlib.contextmanager
def found_on(*folders: str):
    """`charter` looked up in exactly `folders`, never this computer's PATH: they are
    this process's PATH, which macOS and Linux read, and the made-up registry's
    user PATH, which Windows reads. Yields that registry."""
    saved = os.environ.get("PATH", "")
    os.environ["PATH"] = os.pathsep.join(folders)
    try:
        yield FakeRegistry(user=";".join(folders))
    finally:
        os.environ["PATH"] = saved


@contextlib.contextmanager
def no_writes():
    """Refuse every way this process could write, delete or run something."""
    attempts = []
    real_open = builtins.open
    real_os_open = os.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if any(c in str(mode) for c in "wax+"):
            attempts.append(("open", str(file), mode))
            raise PermissionError(f"write refused: {file}")
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC):
            attempts.append(("os.open", str(path), flags))
            raise PermissionError(f"write refused: {path}")
        return real_os_open(path, flags, *args, **kwargs)

    def refuse(name):
        def fn(*args, **kwargs):
            attempts.append((name, str(args[:1]), ""))
            raise PermissionError(f"{name} refused")
        return fn

    patched = [(builtins, "open", guarded_open), (os, "open", guarded_os_open)]
    for mod, names in ((os, ("replace", "rename", "remove", "unlink", "rmdir", "mkdir", "makedirs",
                             "utime", "chmod", "link", "symlink", "truncate")),
                       (shutil, ("copy", "copy2", "copyfile", "move", "rmtree", "copytree")),
                       (subprocess, ("Popen", "run", "call", "check_call", "check_output"))):
        for name in names:
            if hasattr(mod, name):
                patched.append((mod, name, refuse(f"{mod.__name__}.{name}")))
    if os.name == "nt":
        import winreg
        for name in ("SetValueEx", "CreateKey", "CreateKeyEx", "DeleteValue", "DeleteKey"):
            patched.append((winreg, name, refuse(f"winreg.{name}")))
    saved = [(mod, name, getattr(mod, name)) for mod, name, _ in patched]
    for mod, name, fn in patched:
        setattr(mod, name, fn)
    try:
        yield attempts
    finally:
        for mod, name, fn in saved:
            setattr(mod, name, fn)


def strings(value):
    if isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from strings(v)
    elif isinstance(value, str):
        yield value


def shown_wording(folder: str, extra: str = "") -> str:
    """Every string Connect agents can show, for each state and each platform,
    with `charter` found on a controlled PATH, never this computer's: ready, not on
    PATH, another copy first, Windows file access only, and not ready. Only
    the exact local values a payload carries — its folder, its map, and where
    `charter` was found — are left out; everything else is wording. `extra` is
    appended to one payload's wording, to prove the scan sees it."""
    other = tempfile.mkdtemp(prefix="charter-other-copy-")
    open(os.path.join(other, "charter.cmd" if os.name == "nt" else "charter"), "w").close()
    if os.name != "nt":
        os.chmod(os.path.join(other, "charter"), 0o755)
    odd = os.path.join(tempfile.mkdtemp(prefix="charter-odd-"), "R&D")
    mg.create(odd, "Odd")
    unclean = context()
    write(unclean, "notes.txt", b"mine")
    saved = os.environ.get("PATH", "")
    payloads = []
    try:
        for path in ([on_path.LAUNCHERS], [], [other, on_path.LAUNCHERS]):
            os.environ["PATH"] = os.pathsep.join(path)
            registry = FakeRegistry(user=";".join(path))
            for windows in (True, False):
                for where in (folder, odd, unclean):
                    payloads.append(connect.connection(where, windows=windows, registry=registry))
    finally:
        os.environ["PATH"] = saved
    states = {p.get("connect") for p in payloads}
    assert states == {"ready", "not-ready"}, states
    out = []
    for p in payloads:
        local = [p["folder"], p["map"], on_path.LAUNCHERS]
        found = (p.get("launcher") or {}).get("found") or ""
        if found:
            local += [found, os.path.dirname(found)]
        local += [p.get("command") or ""] + list(p.get("args") or [])
        # `config_text` is `config` as JSON, whose strings are scanned already.
        text = " ".join(strings(dict(p, config_text="")))
        for value in sorted(set(local), key=len, reverse=True):
            text = text.replace(value, "")
        out.append(text)
    out[0] += " " + extra
    for d in (other, os.path.dirname(odd), unclean):
        shutil.rmtree(d, ignore_errors=True)
    return " ".join(out)


# --- quoting ------------------------------------------------------------------------

def case_quoting() -> None:
    print("\nquoting for each shell")
    ps = connect.powershell_arg
    check(ps("--") == "'--'", "PowerShell: `--` is quoted, since PowerShell drops a bare one "
                               "passed to a script such as an npm-installed claude")
    check([ps(a) for a in ("mcp", "--scope", "/c", "charter-demo", r"C:\Ctx\a.b")]
          == ["mcp", "--scope", "/c", "charter-demo", r"C:\Ctx\a.b"], "PowerShell: plain arguments stay plain")
    check(ps(r"C:\My Ctx") == r"'C:\My Ctx'" and ps(r"C:\a$b`c") == r"'C:\a$b`c'"
          and ps(r"C:\it's") == r"'C:\it''s'" and ps(r"C:\a,b") == r"'C:\a,b'"
          and ps(r"C:\(x) é") == r"'C:\(x) é'",
          "PowerShell: anything else is single-quoted, literal, with ' doubled")
    cmd = connect.cmd_arg
    check(cmd("--") == "--" and cmd(r"C:\Ctx") == r"C:\Ctx" and cmd(r"C:\My Ctx") == r'"C:\My Ctx"'
          and cmd(r"C:\a$b 'q' (x)") == r'''"C:\a$b 'q' (x)"''',
          "Command Prompt: double quotes where needed")
    for bad in ("%", "&", "|", "<", ">", "^", '"'):
        try:
            cmd(rf"C:\a{bad}b")
            ok = False
        except ValueError:
            ok = True
        check(ok, f"Command Prompt: {bad} is never offered, since quotes do not protect it")
    check(connect.posix_arg("/home/me/My Ctx/it's") == "'/home/me/My Ctx/it'\"'\"'s'"
          and connect.posix_arg("/srv/ctx") == "/srv/ctx", "POSIX: shell quoting")


PY = r"C:\Program Files\Python 3.12\python.exe"


def case_payload() -> None:
    print("\nthe copy-ready text")
    with isolated_private_state():
        base = tempfile.mkdtemp(prefix="charter-connect-")
        folder = os.path.join(base, "My Ctx $x 'q' (é)")
        mg.create(folder, "Demo Project")
        folder = mg.check(folder)["path"]
        script = os.path.join(on_path.LAUNCHERS, "charter.py")
        check(os.name == "nt" or os.access(os.path.join(on_path.LAUNCHERS, "charter"), os.X_OK),
              "this copy's `charter` launcher is executable, as Git and the release record it")
        with found_on(on_path.LAUNCHERS) as on:
            win = connect.connection(folder, windows=True, registry=on, python=PY)
            posix = connect.connection(folder, windows=False, registry=on)
        check(win["ready"] and win["server_name"] == "charter-demo-project",
              "a ready Agent Context gets a server named for its project")
        server = win["config"]["mcpServers"]["charter-demo-project"]
        check(server == {"command": PY, "args": [script, "mcp", "--context", folder]}
              and json.loads(win["config_text"]) == win["config"],
              "Windows: the configuration runs the Python running Charter, by its full path, with this "
              "copy's charter.py and each argument as its own exact argument")
        check("cmd" not in (server["command"], *server["args"][:1]) and "/c" not in server["args"]
              and server["command"] not in ("charter", "py", "cmd", "powershell"),
              "never a bare `charter`, a bare `py`, `cmd /c`, or another shell")
        check(win["config_note"] == "Add this using your host's MCP instructions.",
              "other hosts get one action sentence, no launcher explanation")
        check("Keep Charter in one folder" in win["install_note"]
              and "move Charter" in win["install_note"] and "Python" in win["install_note"],
              "it says registrations keep working when Charter is updated in place, and need "
              "reconnecting if Charter or its Python moves")
        shells = {s["shell"]: s for s in win["shells"]}
        register = ["claude", "mcp", "add", "charter-demo-project", "--", PY, script, "mcp", "--context", folder]
        check(shells["powershell"]["claude_code"] == connect.command_line(register, connect.powershell_arg)
              and connect.powershell_arg(PY) in shells["powershell"]["claude_code"],
              "Windows: the PowerShell claude mcp add command, every path quoted as one argument")
        check(shells["cmd"]["claude_code"] == connect.command_line(register, connect.cmd_arg)
              and f'"{PY}"' in shells["cmd"]["claude_code"],
              "Windows: the Command Prompt claude mcp add command")
        check("--scope" not in " ".join(s["claude_code"] for s in win["shells"])
              and "claude_code_note" not in win,
              "Claude Code: registered at its default, local scope; the view's one instruction replaces a note")
        check(not any(k in win for k in ("claude_vscode_note", "check_note", "writes_nothing")),
              "troubleshooting, the VS Code workaround and the no-writes footer are the README's, not this view's")
        check(win["codex_toml"] == "[mcp_servers.charter-demo-project]\ncommand = " + json.dumps(PY)
              + "\nargs = " + json.dumps([script, "mcp", "--context", folder], ensure_ascii=False)
              .replace('","', '", "') + "\n"
              and win["codex_note"] == "Add this to your Codex configuration, then restart Codex.",
              "Codex: its [mcp_servers.<name>] table, runs the same program and arguments")
        try:
            import tomllib
        except ImportError:
            tomllib = None
        if tomllib:
            for payload in (win, posix):
                parsed = tomllib.loads(payload["codex_toml"])["mcp_servers"][payload["server_name"]]
                check(parsed == payload["config"]["mcpServers"][payload["server_name"]],
                      "Codex: the TOML parses to exactly the MCP configuration, the folder included")
        check(win["pointer"].count("charter-demo-project") == 1 and "get_context" in win["pointer"]
              and folder not in win["pointer"]
              and win["pointer_note"] == connect.POINTER_NOTE
              and all(n in win["pointer_note"] for n in ("`CLAUDE.md`", "`AGENTS.md`", "Do not put it in `AGENT-CONTEXT.md`",
                                                         "anywhere inside the Agent Context folder"))
              and "AGENT-CONTEXT-MAP" not in win["pointer_note"] and "Optional" not in win["pointer_note"],
              "a startup pointer names the server, not a path, and belongs in the project, not the context")
        check("[describe a small task]" in win["verify_prompt"] and "do not guess" in win["verify_prompt"]
              and "verify_note" not in win,
              "a verification prompt, with no note")
        check(win["status_text"] == "This context is ready to connect."
              and not any(k in win for k in ("checked", "not_checked"))
              and not any(w in win["status_text"] for w in ("connected", "retrieved", "follows")),
              "ready is one sentence: never that a host is configured, or an agent retrieved or follows it")
        check(not any(k in win for k in ("proposals_note", "same_context", "not_visible",
                                          "wider_access", "not_enforced")),
              "terminal proposals and the trust boundary are the README's, not this view's")
        check(win["files_note"] == "Requires direct read access to the Agent Context folder. See the README for guidance.",
              "file access says it needs direct read access, and that the README has the rest")
        check(shells["powershell"]["check"] == connect.command_line([PY, script, "mcp", "--context", folder, "--check"],
                                                                    connect.powershell_arg)
              and shells["cmd"]["check"] == connect.command_line([PY, script, "mcp", "--context", folder, "--check"],
                                                                 connect.cmd_arg),
              "and a check command for each, running the same copy")
        launcher = os.path.join(on_path.LAUNCHERS, "charter")
        check(posix["config"]["mcpServers"]["charter-demo-project"]
              == {"command": launcher, "args": ["mcp", "--context", folder]}
              and [s["shell"] for s in posix["shells"]] == ["posix"]
              and posix["shells"][0]["claude_code"].endswith(" -- " + connect.posix_arg(launcher)
                                                              + " mcp --context " + connect.posix_arg(folder)),
              "elsewhere: this copy's launcher by its full path, quoted for a POSIX shell")
        check(win["map"] == os.path.join(folder, ac.CONTEXT_MAP)
              and win["map"] in win["instruction"] and "AGENT-CONTEXT.md" in win["instruction"]
              and "authoritative" in win["instruction"],
              "the file-access instruction points at this folder's AGENT-CONTEXT.md")
        print("\nCommand-Line Access: `charter read` by this copy's full paths, with the folder's full path")
        read_parts = [PY, script, "read", "--context", folder]
        access = {s["shell"]: s for s in win["command_access"]}
        check([s["label"] for s in win["command_access"]] == ["PowerShell", "Command Prompt", "Bash"]
              and access["powershell"]["command"] == "& " + connect.command_line(read_parts, connect.powershell_arg)
              and access["cmd"]["command"] == connect.command_line(read_parts, connect.cmd_arg)
              and access["bash"]["command"] == connect.command_line(read_parts, connect.posix_arg),
              "Windows: PowerShell, Command Prompt and Bash, each the Python running Charter, this "
              "copy's charter.py, then `read --context <folder>`, quoted for that shell")
        posix_launcher = os.path.join(on_path.LAUNCHERS, "charter")
        check([s["label"] for s in posix["command_access"]] == ["Terminal"]
              and posix["command_access"][0]["command"]
              == connect.command_line([posix_launcher, "read", "--context", folder], connect.posix_arg),
              "elsewhere: one terminal command, this copy's launcher by its full path")
        propose_parts = [PY, script, "propose", "--context", folder]
        check(access["powershell"]["propose_command"] == "& " + connect.command_line(propose_parts, connect.powershell_arg)
              and access["cmd"]["propose_command"] == connect.command_line(propose_parts, connect.cmd_arg)
              and access["bash"]["propose_command"] == connect.command_line(propose_parts, connect.posix_arg)
              and posix["command_access"][0]["propose_command"]
              == connect.command_line([posix_launcher, "propose", "--context", folder], connect.posix_arg),
              "each shell's matching `propose --context <folder>` command: the same program and the "
              "same absolute folder, quoted the same way")
        for s in win["command_access"] + posix["command_access"]:
            for key in ("command", "propose_command"):
                words_in = s[key].replace("'", " ").replace('"', " ").split()
                check(s["instruction"].count(s[key]) == 1 and os.path.isabs(folder)
                      and not {"charter", "py", "python", "python3", "cmd", "/c"} & set(words_in)
                      and "--context" in words_in and " . " not in s[key] and not s[key].endswith(" .")
                      and words_in[-1].strip() != ".",
                      f"{s['label']} {key}: in the instruction once, with no bare `charter`, `py` or "
                      "`cmd /c`, and the folder's absolute path, never `.`")
            check(all(p in s["instruction"] for p in (
                    "Before beginning work, run this command", "`--list`", "`--document <path-or-id>`",
                    "`--heading <heading>`", "Treat only the governing documents it lists as authoritative",
                    "`<<<END CHARTER READ>>>`", "If the command cannot run, or reports that Charter "
                    "context is unavailable, stop and tell the person",
                    "do not read the Agent Context's files instead",
                    "To propose a change, follow \"Making an Agent Proposal\" in the context map, "
                    "sending the proposal JSON to this command:"))
                  and s["instruction"].index(s["command"]) < s["instruction"].index(s["propose_command"])
                  and not re.search(r"\bPATH\b|add-to-path|telemetry|activity|wizard", s["instruction"]),
                  f"{s['label']}: run it before work, retrieve the relevant documents, trust only the "
                  "marked-complete output, stop and tell the person — never fall back to the files — "
                  "and propose through the map's route with the matching command")
        check(win["command_note"] == posix["command_note"] == connect.COMMAND_NOTE
              == "Add this to your project’s instruction file, such as `CLAUDE.md` or `AGENTS.md`. "
                 "Do not put it in `AGENT-CONTEXT.md` or anywhere inside the Agent Context folder.",
              "one placement note: the project's own instruction file, never the Agent Context folder")
        broken = connect.connection(folder, windows=True, registry=FakeRegistry(), python="C:\\Py\nthon\\python.exe")
        check(broken["connect"] == "files-only" and broken["command_access"] == [],
              "a path no command line can carry exactly gets no Command-Line Access command")
        words = shown_wording(folder)
        check(not re.search(r"\b(" + "|".join(FORBIDDEN_WORDS) + r")\b", words, re.I)
              and re.search(r"\b(" + "|".join(FORBIDDEN_WORDS) + r")\b", "a cgu surface", re.I)
              and "CGU" in shown_wording(folder, extra="CGU"),
              "its wording is Charter's own, in every state it can show")
        check("Agent Context Manager" not in words,
              "it names the product Charter, never its earlier name")
        check(win["connect"] == "ready" and win["status_text"] == connect.READY,
              "with this copy on PATH: ready to connect")

        print("\nPATH decides nothing about connecting, and Connect agents says nothing about it")
        with found_on() as nowhere:
            off = connect.connection(folder, windows=True, registry=nowhere, python=PY)
        other_dir = tempfile.mkdtemp(prefix="charter-other-")
        open(os.path.join(other_dir, "charter.cmd" if os.name == "nt" else "charter"), "w").close()
        if os.name != "nt":
            os.chmod(os.path.join(other_dir, "charter"), 0o755)
        with found_on(other_dir, on_path.LAUNCHERS) as first:
            other = connect.connection(folder, windows=True, registry=first, python=PY)
        check(all(p["ready"] and p["connect"] == "ready" and p["config"] == win["config"]
                  and p["shells"] == win["shells"] for p in (off, other)),
              "with `charter` nowhere on PATH, or another copy first, the same setup, ready: hosts start "
              "this copy by its full path")
        check(all(not any(k in p for k in ("path_conflict", "launcher", "fix", "restart")) for p in (win, off, other))
              and other_dir not in " ".join(strings(other))
              and all(not re.search(r"\bPATH\b|add-to-path|Remove ", " ".join(strings(p))) for p in (win, off, other)),
              "Connect agents carries no PATH warning or remedy in any state: the header's Charter command "
              "status does")
        shutil.rmtree(other_dir)
        shutil.rmtree(base)


def case_command_status() -> None:
    print("\nthe Charter command status: this installation, another copy, or none")
    other_dir = tempfile.mkdtemp(prefix="charter-other-")
    open(os.path.join(other_dir, "charter.cmd" if os.name == "nt" else "charter"), "w").close()
    if os.name != "nt":
        os.chmod(os.path.join(other_dir, "charter"), 0o755)
    script = os.path.join(on_path.LAUNCHERS, "charter.py")
    try:
        with no_writes() as attempts:
            with found_on(on_path.LAUNCHERS, other_dir) as mine:
                ready = connect.command_status(windows=os.name == "nt", registry=mine, python=PY)
            with found_on(other_dir, on_path.LAUNCHERS) as first:
                other = connect.command_status(windows=True, registry=first, python=PY)
                other_posix = connect.command_status(windows=False, registry=first)
            with found_on() as nowhere:
                missing = connect.command_status(windows=True, registry=nowhere, python=PY)
                missing_posix = connect.command_status(windows=False, registry=nowhere)
        check(not attempts, "finding out writes nothing and runs nothing")
        check(ready["state"] == "ready" and "remedy" not in ready,
              "this installation first: Charter command ready, with no remedy")
        check(other["state"] == "other" and other["other_folder"] == other_dir and other["found"].startswith(other_dir),
              "another copy first, though this one is on PATH too: needs attention, naming that copy's folder")
        check(missing["state"] == "missing" and missing["found"] == "" and missing["other_folder"] == "",
              "`charter` nowhere on PATH: needs attention, with nothing named as found")
        expect = "& " + connect.command_line([PY, script, "add-to-path"], connect.powershell_arg)
        check(other["remedy"] == missing["remedy"] == expect and other["shell"] == "PowerShell"
              and other["changes_path"],
              f"Windows: one PowerShell command, this Python and this copy's charter.py by full path: {expect}")
        check(" " in PY and expect.startswith("& '" + PY + "' ")
              and expect.endswith(" " + connect.powershell_arg(script) + " add-to-path"),
              "an interpreter path with spaces is quoted and run with `&`, as PowerShell requires")
        for c in (other, missing, other_posix, missing_posix):
            words = c["remedy"].replace(PY, "").replace(script, "").replace(os.path.join(on_path.LAUNCHERS, "charter"), "")
            check(not re.search(r"(^|[\s&'\"])(py|charter|cmd)(\s|$)|/c\b", words) and other_dir not in c["remedy"],
                  f"{c['shell']}, {c['state']}: no bare charter, py or cmd /c, and nothing that runs the other copy")
        launcher = os.path.join(on_path.LAUNCHERS, "charter")
        check(other_posix["remedy"] == missing_posix["remedy"] == connect.posix_arg(launcher) + " add-to-path"
              and other_posix["shell"] == "Terminal" and not other_posix["changes_path"],
              "elsewhere: this copy's launcher by its full path, which says what to add to the shell startup file")
    finally:
        shutil.rmtree(other_dir)


def case_not_ready() -> None:
    print("\nnot ready: the reason, and nothing to copy")
    with isolated_private_state():
        folder = context()
        copyable = ("config", "config_text", "shells", "instruction", "server_name", "launch_line",
                    "codex_toml", "pointer", "verify_prompt")

        def refused(label, expect):
            c = connect.connection(folder, windows=True, registry=FakeRegistry())
            check(not c["ready"] and expect in " ".join(c["reasons"])
                  and not any(k in c for k in copyable)
                  and "writes_nothing" not in c, label)
            return c

        write(folder, "notes.txt", b"mine")
        c = refused("an unclean folder: refused, naming the stray file", "notes.txt")
        check(c["reasons"][0].startswith("Charter can’t serve this Agent Context yet.")
              and "`notes.txt`: isn’t part of this Agent Context." in c["reasons"],
              "the first reason is the folder's own status, then the file that does not belong")
        os.remove(os.path.join(folder, "notes.txt"))

        approved = read(folder, "authoritative/a.md")
        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited in an editor.\n"))
        c = refused("an edited governing document: refused, context changes need review",
                    "Context changes need review")
        check(any("Does not match approved context" in r or "does not match" in r for r in c["reasons"])
              and not any("Rebuild Agent Context to" in r for r in c["reasons"]),
              "naming the document that does not match, and never offering Rebuild for it")
        write(folder, "authoritative/a.md", approved)
        check(connect.connection(folder)["ready"], "with the approved text restored, it is ready again")

        cand = au.plan(folder, "add", {"title": "Gamma", "body": "x\n"})
        au.apply(folder, "add", cand.request, cand.plan_id, True)
        req = seeded(folder, {"alongside": "authority-candidates/gamma.md"})
        p = au.plan(folder, "changeset", req)
        try:
            au.apply(folder, "changeset", req, p.plan_id, PHRASE,
                     fault=lambda n: (_ for _ in ()).throw(Crash()) if n == "replace:AGENT-CONTEXT.md" else None)
        except Crash:
            pass
        refused("an interrupted write: refused until the folder is opened and recovered", "interrupted")
        mg.open_context(folder)
        check(connect.connection(folder)["ready"], "recovered, it is ready again")

        odd = os.path.join(tempfile.mkdtemp(prefix="charter-connect-"), "R&D 100%")
        mg.create(odd, "Odd")
        c = connect.connection(odd, windows=True, registry=FakeRegistry(user=on_path.LAUNCHERS))
        check(c["ready"] and c["connect"] == "ready" and c["config"]["mcpServers"][c["server_name"]]["args"][-1] == odd,
              "Windows, a folder with % and &: MCP is offered, the folder passed as one exact argument")
        check([sh["shell"] for sh in c["shells"]] == ["powershell"],
              "Command Prompt cannot type it reliably, so only PowerShell's registration command is offered")
        check(c["instruction"] and c["map"] in c["instruction"],
              "the file-access instruction is still offered")
        shutil.rmtree(os.path.dirname(odd))
        shutil.rmtree(folder)


# --- writes nothing -----------------------------------------------------------------

def _http(port: int, method: str, path: str, body=None, header=True):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if header:
        req.add_header("X-Charter-Console", "person")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _private_root() -> str:
    from app import private_store as ps
    return ps.PrivateState.default().root


def case_writes_nothing() -> None:
    print("\nproducing it writes nothing anywhere")
    with isolated_private_state():
        folder = context()
        session = console.Session(folder)
        root = _private_root()
        home = tempfile.mkdtemp(prefix="charter-home-")
        before = (snapshot(folder), snapshot(root), snapshot(home))
        saved_home = {k: os.environ.get(k) for k in ("HOME", "USERPROFILE", "APPDATA")}
        os.environ.update({"HOME": home, "USERPROFILE": home, "APPDATA": home})
        try:
            with no_writes() as attempts:
                try:
                    open(os.path.join(home, "probe.txt"), "w").close()
                except PermissionError:
                    pass
            check(attempts and not os.path.exists(os.path.join(home, "probe.txt")),
                  "the guard itself refuses a write")
            with no_writes() as attempts:
                ready = console.connect_agents(session)
                connect.connection(folder, windows=True)
                connect.connection(folder, windows=False)
            check(ready["ready"] and not attempts,
                  "with every file write, deletion, process and registry change refused, it still answers")
        finally:
            for k, v in saved_home.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
        check((snapshot(folder), snapshot(root), snapshot(home)) == before,
              "the Agent Context, private state and home folder are byte-for-byte unchanged")
        check(not any(os.path.exists(os.path.join(p, n)) for p in (folder, home, os.path.dirname(folder))
                      for n in ("AGENTS.md", "CLAUDE.md", ".mcp.json", ".claude.json")),
              "no AGENTS.md, CLAUDE.md or MCP configuration exists anywhere it could have gone")

        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(session))
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            before = (snapshot(folder), snapshot(root))
            status, body = _http(port, "GET", "/api/connect")
            check(status == 200 and json.loads(body)["ready"]
                  and json.loads(body)["folder"] == session.folder,
                  "over HTTP, the console's page gets the same answer")
            check((snapshot(folder), snapshot(root)) == before, "and nothing changed")
            check(_http(port, "GET", "/api/connect", header=False)[0] == 403,
                  "it answers only the console's own page")
            for route in ("/api/connect", "/api/connect/register", "/api/connect/apply",
                          "/api/integrations/apply"):
                check(_http(port, "POST", route, {})[0] == 404,
                      f"there is no POST `{route}`: nothing registers or sets anything up")
            check((snapshot(folder), snapshot(root)) == before, "still nothing changed")
        finally:
            httpd.shutdown()
            httpd.server_close()
        shutil.rmtree(home)
        shutil.rmtree(folder)


# --- the real shells (Windows) ---------------------------------------------------------

def _argv_printer(where: str) -> str:
    """A stand-in for `claude`: prints the arguments it was given, as JSON."""
    script = os.path.join(where, "argv.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write("import sys, json\nsys.stdout.write(json.dumps(sys.argv[1:]))\n")
    return script


def case_real_shells() -> None:
    print("\nthe commands, typed into the real shells")
    if os.name != "nt":
        print("  (not Windows: PowerShell and Command Prompt are checked on Windows)")
        return
    with isolated_private_state():
        base = tempfile.mkdtemp(prefix="charter-shells-")
        folder = os.path.join(base, "Ctx $x 'q' (a) é,b;c")
        mg.create(folder, "Shell Test")
        folder = mg.check(folder)["path"]
        fake_py = os.path.join(base, "Py Thon 3", "python.exe")
        copy = os.path.join(base, "Charter Copy (x)")
        c = connect.connection(folder, windows=True, registry=FakeRegistry(), launchers=copy, python=fake_py)
        expected = ["mcp", "add", "charter-shell-test", "--", fake_py, os.path.join(copy, "charter.py"),
                    "mcp", "--context", folder]
        printer = _argv_printer(base)
        py = sys.executable
        shells = {s["shell"]: s for s in c["shells"]}
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")

        # PowerShell, as npm installs claude: a .ps1 script forwarding $args.
        shim = os.path.join(base, "claude.ps1")
        with open(shim, "w", encoding="utf-8-sig") as fh:
            fh.write(f"& '{py}' '{printer}' $args\n")
        line = shells["powershell"]["claude_code"].replace("claude ", f"& '{shim}' ", 1)
        ps = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + line],
                            capture_output=True, env=env)
        got = json.loads(ps.stdout.decode("utf-8") or "null")
        check(got == expected, "PowerShell, through an npm-style claude.ps1: every argument arrives exactly")
        line = shells["powershell"]["claude_code"].replace("claude ", f"& '{py}' '{printer}' ", 1)
        ps = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + line],
                            capture_output=True, env=env)
        check(json.loads(ps.stdout.decode("utf-8") or "null") == expected,
              "PowerShell, to a native claude.exe: every argument arrives exactly")

        # Command Prompt: the line as typed at its prompt.
        native = os.path.join(base, "claude.cmd")
        with open(native, "w", encoding="utf-8") as fh:
            fh.write(f'@"{py}" "{printer}" %*\r\n')
        line = shells["cmd"]["claude_code"].replace("claude ", f'"{native}" ', 1)
        cp = subprocess.run(f'cmd /d /s /c "chcp 65001>nul & {line}"', capture_output=True, env=env)
        check(json.loads(cp.stdout.decode("utf-8") or "null") == expected,
              "Command Prompt: every argument arrives exactly")

        # The Charter command dialog's remedy, as pasted into PowerShell: a
        # quoted interpreter with spaces in its path, run through `&`, with this
        # copy's charter.py. Stand-ins print what they are given, so nothing
        # changes PATH.
        spaced = os.path.join(base, "Py Thon 3", "python.cmd")
        os.makedirs(os.path.dirname(spaced), exist_ok=True)
        with open(spaced, "w", encoding="utf-8") as fh:
            fh.write(f'@"{py}" %*\r\n')
        os.makedirs(copy, exist_ok=True)
        shutil.copy(printer, os.path.join(copy, "charter.py"))
        with found_on() as nowhere:
            remedy = connect.command_status(windows=True, registry=nowhere, python=spaced, launchers=copy)["remedy"]
        ps = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + remedy],
                            capture_output=True, env=env)
        check(json.loads(ps.stdout.decode("utf-8") or "null") == ["add-to-path"],
              f"the Charter command remedy runs in PowerShell as shown, spaces and all: {remedy}")
        shutil.rmtree(base)


def _git_bash() -> str:
    """Git for Windows' bash, the shell Claude Code runs commands in on Windows,
    never WSL's `bash.exe`, which is a different computer's shell."""
    for candidate in (shutil.which("bash") or "",
                      os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Git", "bin", "bash.exe")):
        if candidate and os.path.isfile(candidate) and "system32" not in candidate.lower():
            return candidate
    return ""


PROPOSAL_BODY = "# Probe — dash\n\nCafé, naïve, “curly quotes”.\n"


def _command_access_end_to_end(base: str, folder: str, env: dict, bash: str) -> None:
    """The generated Command-Line Access instruction's own commands, run in each
    real shell against this Charter with throwaway private state: `read` serves
    the map with its marker, and `propose`, given ASCII JSON as the map says,
    files the proposal with its em dash, accents and curly quotes exact."""
    from app import agent_proposals as apx
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    state = os.path.join(base, "state")
    copy = os.path.join(base, "Stub Copy")
    os.makedirs(copy)
    with open(os.path.join(copy, "charter.py"), "w", encoding="utf-8") as fh:
        fh.write("import sys\nsys.path.insert(0, %r)\nfrom app import private_store\n"
                 "private_store._default_root = lambda: %r\nfrom app.__main__ import main\n"
                 "raise SystemExit(main(sys.argv[1:]))\n" % (root, state))
    c = connect.connection(folder, windows=True, registry=FakeRegistry(), launchers=copy,
                           python=sys.executable)
    access = {s["shell"]: s for s in c["command_access"]}
    check(all(" read --context " in s["command"] and " propose --context " in s["propose_command"]
              for s in access.values()), "the stand-in copy's instruction holds both commands")
    pending = lambda: os.path.join(state, "contexts")

    def filed(out: bytes) -> str:
        result = json.loads(out.decode("ascii").strip().splitlines()[-1])
        if result.get("result") != "pending":
            return "not filed: " + json.dumps(result)
        for dirpath, _dirs, files in os.walk(pending()):
            if result["proposal_id"] + ".json" in files:
                with open(os.path.join(dirpath, result["proposal_id"] + ".json"), encoding="utf-8") as fh:
                    return json.load(fh)["proposal"]["proposed_body"]
        return "no record"

    def proposal(name: str) -> str:
        return json.dumps({"agent": "shell-test", "operation": "create",
                           "target_path": f"authority-candidates/{name}.md", "reason": "Shell test.",
                           "proposed_body": PROPOSAL_BODY}, ensure_ascii=True)

    payload = os.path.join(base, "proposal.json")
    runs = {"powershell": lambda cmd, data: subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; '" + data.replace("'", "''") + "' | " + cmd],
                capture_output=True, env=env, stdin=subprocess.DEVNULL),
            "cmd": lambda cmd, data: subprocess.run(
                f'cmd /d /s /c "chcp 65001>nul & {cmd} < "{payload}""', capture_output=True, env=env),
            "bash": lambda cmd, data: subprocess.run(
                [bash, "-c", f"{cmd} < '{payload}'"], capture_output=True, env=env)}
    for shell, label in (("powershell", "PowerShell"), ("cmd", "Command Prompt"), ("bash", "Git Bash")):
        if shell == "bash" and not bash:
            continue
        s = access[shell]
        read_out = (runs[shell](s["command"], "") if shell == "powershell"
                    else subprocess.run(f'cmd /d /s /c "chcp 65001>nul & {s["command"]}"', capture_output=True,
                                        env=env, stdin=subprocess.DEVNULL) if shell == "cmd"
                    else subprocess.run([bash, "-c", s["command"]], capture_output=True, env=env,
                                        stdin=subprocess.DEVNULL))
        text = read_out.stdout.decode("utf-8")
        check(read_out.returncode == 0 and text.rstrip("\r\n").endswith("<<<END CHARTER READ>>>")
              and "If you received this file through `charter read`" in text,
              f"{label}: the instruction's `charter read` serves the format-4 map, marker last")
        data = proposal(f"shell-{shell}")
        with open(payload, "w", encoding="ascii") as fh:
            fh.write(data)
        out = runs[shell](s["propose_command"], data)
        body = filed(out.stdout)
        check(out.returncode == 0 and data.isascii() and body == PROPOSAL_BODY,
              f"{label}: the instruction's `charter propose`, given ASCII JSON, files the em dash, "
              f"accents and curly quotes exactly (exit {out.returncode})")
    # The defect the rule exists for, recorded, not asserted: Windows PowerShell 5.1
    # pipes text to a program in its `$OutputEncoding`, US-ASCII by default.
    raw = json.dumps(json.loads(proposal("shell-raw-utf8")), ensure_ascii=False)
    out = runs["powershell"](access["powershell"]["propose_command"], raw)
    body = filed(out.stdout)
    print(f"  (evidence: raw UTF-8 JSON through PowerShell was filed "
          f"{'exactly' if body == PROPOSAL_BODY else 'altered, as ' + repr(body)})")
    del apx


def case_command_access_shells() -> None:
    print("\nCommand-Line Access commands, typed into the real shells")
    if os.name != "nt":
        print("  (not Windows: the terminal command is quoted by shlex, checked in the payload case)")
        return
    with isolated_private_state():
        base = tempfile.mkdtemp(prefix="charter-cla-shells-")
        folder = os.path.join(base, "Ctx $x 'q' (a) é,b;c")
        mg.create(folder, "Shell Test")
        folder = mg.check(folder)["path"]
        # A stand-in copy whose charter.py prints the arguments it is given: the
        # commands run nothing of Charter's and read no private state.
        copy = os.path.join(base, "Charter Copy (x)")
        os.makedirs(copy)
        shutil.copy(_argv_printer(base), os.path.join(copy, "charter.py"))
        c = connect.connection(folder, windows=True, registry=FakeRegistry(), launchers=copy,
                               python=sys.executable)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        bash = _git_bash()
        for key, verb in (("command", "read"), ("propose_command", "propose")):
            access = {s["shell"]: s[key] for s in c["command_access"]}
            expected = [verb, "--context", folder]
            ps = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                 "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + access["powershell"]],
                                capture_output=True, env=env, stdin=subprocess.DEVNULL)
            check(json.loads(ps.stdout.decode("utf-8") or "null") == expected,
                  f"PowerShell: `{verb} --context <folder>` arrives exactly, spaces, quotes and $ included")
            cp = subprocess.run(f'cmd /d /s /c "chcp 65001>nul & {access["cmd"]}"', capture_output=True,
                                env=env, stdin=subprocess.DEVNULL)
            check(json.loads(cp.stdout.decode("utf-8") or "null") == expected,
                  f"Command Prompt: `{verb}` arrives exactly")
            if bash:
                gb = subprocess.run([bash, "-c", access["bash"]], capture_output=True, env=env,
                                    stdin=subprocess.DEVNULL)
                check(json.loads(gb.stdout.decode("utf-8") or "null") == expected,
                      f"Git Bash: `{verb}` arrives exactly, Windows paths and all")
        if not bash:
            print("  (Git Bash not found: its command is quoted by shlex, checked in the payload case)")
        _command_access_end_to_end(base, folder, env, bash)
        odd = os.path.join(base, "R&D 100%")
        mg.create(odd, "Odd")
        c = connect.connection(mg.check(odd)["path"], windows=True, registry=FakeRegistry(),
                               launchers=copy, python=sys.executable)
        check([s["shell"] for s in c["command_access"]] == ["powershell", "bash"],
              "a folder Command Prompt cannot type exactly (& or %): no Command Prompt form")
        shutil.rmtree(base)


def case_release_and_checkout() -> None:
    print("\na release and a development checkout: the same full-path setup, spaces and all")
    base = tempfile.mkdtemp(prefix="charter-copies-")
    try:
        dev = os.path.join(base, "dev worktree")
        release = os.path.join(base, "Program Files", "Charter 2")
        os.makedirs(dev)
        os.makedirs(release)
        with open(os.path.join(dev, ".git"), "w", encoding="utf-8") as fh:
            fh.write("gitdir: elsewhere\n")  # a worktree's `.git` is a file
        with isolated_private_state():
            folder = context()
            other = FakeRegistry(user=os.path.join(base, "elsewhere"))
            for label, launchers in (("a development checkout", dev), ("an installed release", release)):
                win = connect.connection(folder, windows=True, registry=other, launchers=launchers, python=PY)
                posix = connect.connection(folder, windows=False, registry=other, launchers=launchers)
                check(win["connect"] == "ready" and win["command"] == PY
                      and win["args"] == [os.path.join(launchers, "charter.py"), "mcp", "--context", folder]
                      and posix["command"] == os.path.join(launchers, "charter")
                      and posix["args"] == ["mcp", "--context", folder],
                      f"{label}: this copy, by its full path, with spaces in it, as exact arguments")
                check(not any(re.search(r"(^|\s)(charter|py|cmd)(\s|$)", re.split(r" '?--'? ", s["claude_code"], maxsplit=1)[1])
                              for s in win["shells"] + posix["shells"]),
                      f"{label}: no registration runs a bare `charter`, `py` or `cmd`")
            shutil.rmtree(folder)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def case_host_runs_it() -> None:
    print("\nan agent host runs the registered program and arguments, with no shell")
    with isolated_private_state() as state:
        base = tempfile.mkdtemp(prefix="charter host ")
        folder = os.path.join(base, "Agent Context (spaced) & co")
        mg.create(folder, "Host Run")
        folder = mg.check(folder)["path"]
        c = connect.connection(folder, windows=os.name == "nt")
        server = c["config"]["mcpServers"][c["server_name"]]
        # As a host does: the stored program and arguments, exactly, no shell.
        # The test launcher stands in for charter.py only to isolate private state.
        argv = [server["command"]] + server["args"] + ["--check"]
        if os.name == "nt":
            argv = [server["command"], os.path.join(os.path.dirname(os.path.abspath(__file__)), "_launch.py"),
                    os.path.dirname(state)] + server["args"][1:] + ["--check"]
        done = subprocess.run(argv, capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
        out = done.stdout.decode("utf-8", "replace")
        check(done.returncode == 0 and "the Agent Context is valid and clean" in out and folder in out,
              "the server command starts from the exact arguments and checks this folder, spaces and & included")
        shutil.rmtree(base)


def run() -> int:
    case_quoting()
    case_payload()
    case_command_status()
    case_not_ready()
    case_writes_nothing()
    case_real_shells()
    case_command_access_shells()
    case_release_and_checkout()
    case_host_runs_it()
    print(f"\n{OK} All Connect agents checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
