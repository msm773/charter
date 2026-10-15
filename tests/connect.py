"""Connect agents: copy-ready text, offered only for a ready Agent Context.
Run: python -m tests.connect

  * the MCP configuration runs `charter mcp --context <folder>`; on Windows through
    `cmd /c`, which is how agent hosts start a `.cmd` launcher;
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
from tests.agent_context import context, doc_text, snapshot, write  # noqa: E402
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
    assert states == {"ready", "needs-path", "files-only", "not-ready"}, states
    out = []
    for p in payloads:
        local = [p["folder"], p["map"], on_path.LAUNCHERS]
        found = (p.get("launcher") or {}).get("found") or ""
        if found:
            local += [found, os.path.dirname(found)]
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


def case_payload() -> None:
    print("\nthe copy-ready text")
    with isolated_private_state():
        base = tempfile.mkdtemp(prefix="charter-connect-")
        folder = os.path.join(base, "My Ctx $x 'q' (é)")
        mg.create(folder, "Demo Project")
        folder = mg.check(folder)["path"]
        on = FakeRegistry(user=on_path.LAUNCHERS)
        win = connect.connection(folder, windows=True, registry=on)
        check(win["ready"] and win["server_name"] == "charter-demo-project",
              "a ready Agent Context gets a server named for its project")
        server = win["config"]["mcpServers"]["charter-demo-project"]
        check(server == {"command": "cmd", "args": ["/c", "charter", "mcp", "--context", folder]}
              and json.loads(win["config_text"]) == win["config"],
              "Windows: the configuration runs `cmd /c charter mcp --context <folder>`, the folder as one argument")
        check(win["config_note"] == "Add this using your host's MCP instructions.",
              "other hosts get one action sentence, no launcher explanation")
        shells = {s["shell"]: s for s in win["shells"]}
        check(shells["powershell"]["claude_code"]
              == "claude mcp add charter-demo-project '--' cmd /c charter mcp --context "
              + connect.powershell_arg(folder), "Windows: the PowerShell claude mcp add command")
        check(shells["cmd"]["claude_code"]
              == f'claude mcp add charter-demo-project -- cmd /c charter mcp --context "{folder}"',
              "Windows: the Command Prompt claude mcp add command")
        check("--scope" not in " ".join(s["claude_code"] for s in win["shells"])
              and "claude_code_note" not in win,
              "Claude Code: registered at its default, local scope; the view's one instruction replaces a note")
        check(not any(k in win for k in ("claude_vscode_note", "check_note", "writes_nothing")),
              "troubleshooting, the VS Code workaround and the no-writes footer are the README's, not this view's")
        check(win["codex_toml"] == "[mcp_servers.charter-demo-project]\ncommand = \"cmd\"\nargs = "
              + json.dumps(["/c", "charter", "mcp", "--context", folder], ensure_ascii=False)
              .replace('","', '", "') + "\n"
              and win["codex_note"] == "Add this to your Codex configuration, then restart Codex.",
              "Codex: its [mcp_servers.<name>] table, runs the same command, with one action sentence")
        try:
            import tomllib
        except ImportError:
            tomllib = None
        if tomllib:
            for payload in (win, connect.connection(folder, windows=False, registry=on)):
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
        check(shells["powershell"]["check"] == "charter mcp --context " + connect.powershell_arg(folder)
              + " --check" and shells["cmd"]["check"] == f'charter mcp --context "{folder}" --check',
              "and a check command for each")
        posix = connect.connection(folder, windows=False, registry=on)
        check(posix["config"]["mcpServers"]["charter-demo-project"]
              == {"command": "charter", "args": ["mcp", "--context", folder]}
              and [s["shell"] for s in posix["shells"]] == ["posix"]
              and posix["shells"][0]["claude_code"].endswith(" -- charter mcp --context "
                                                              + connect.posix_arg(folder)),
              "elsewhere: `charter mcp --context <folder>` directly, quoted for a POSIX shell")
        check(win["map"] == os.path.join(folder, ac.CONTEXT_MAP)
              and win["map"] in win["instruction"] and "AGENT-CONTEXT.md" in win["instruction"]
              and "authoritative" in win["instruction"],
              "the file-access instruction points at this folder's AGENT-CONTEXT.md")
        words = shown_wording(folder)
        check(not re.search(r"\b(" + "|".join(FORBIDDEN_WORDS) + r")\b", words, re.I)
              and re.search(r"\b(" + "|".join(FORBIDDEN_WORDS) + r")\b", "a cgu surface", re.I)
              and "CGU" in shown_wording(folder, extra="CGU"),
              "its wording is Charter's own, in every state it can show")
        check("Agent Context Manager" not in words,
              "it names the product Charter, never its earlier name")
        check(win["launcher"]["on_path"] and win["connect"] == "ready"
              and win["status_text"] == connect.READY,
              "with `charter` on PATH for new programs: ready to connect")

        print("\nMCP needs `charter` on PATH")
        off = connect.connection(folder, windows=True, registry=FakeRegistry())
        check(off["ready"] and off["connect"] == "needs-path" and not off["launcher"]["on_path"]
              and off["status_text"] == "Agent Context ready. Add Charter to your PATH before a new agent "
                                        "host can connect."
              and "Ready to connect" not in off["status_text"],
              "without it: the Agent Context is ready, but it is not called ready to connect")
        check(off["config"] == win["config"] and off["shells"] == win["shells"]
              and off["instruction"] == win["instruction"] and off["codex_toml"] == win["codex_toml"],
              "the MCP configuration, commands and file instruction are still all there")
        check("checked" not in off and off["status_text"] != connect.READY,
              "and it does not claim `charter` was found")
        check(off["launcher"]["fix"] == "charter add-to-path" and "charter add-to-path" in off["launcher"]["note"]
              and "python charter.py add-to-path" in off["launcher"]["note"]
              and "quit and reopen the agent host" in off["launcher"]["restart"],
              "with `charter add-to-path` to copy, and the host to be restarted afterwards")
        other_dir = tempfile.mkdtemp(prefix="charter-other-")
        open(os.path.join(other_dir, "charter.cmd" if os.name == "nt" else "charter"), "w").close()
        if os.name != "nt":
            os.chmod(os.path.join(other_dir, "charter"), 0o755)
        saved_path = os.environ.get("PATH", "")
        os.environ["PATH"] = other_dir + os.pathsep + on_path.LAUNCHERS
        try:
            other = connect.connection(folder, windows=os.name == "nt",
                                       registry=FakeRegistry(user=other_dir + ";" + on_path.LAUNCHERS))
        finally:
            os.environ["PATH"] = saved_path
        check(other["connect"] == "needs-path" and "Another copy of Charter" in other["status_text"]
              and other_dir in other["launcher"]["note"],
              "another copy first on PATH: also not ready to connect, naming where it is")
        shutil.rmtree(other_dir)
        shutil.rmtree(base)


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
        check("Agents are refused" in c["reasons"][0], "the first reason is the folder's own status")
        os.remove(os.path.join(folder, "notes.txt"))

        write(folder, "authoritative/a.md", doc_text("a", "Alpha", body="Edited in an editor.\n"))
        refused("an invalid folder: refused, saying the map no longer matches", "Rebuild")
        p = mg.rebuild_plan(folder)
        mg.rebuild_apply(folder, p.plan_id, True)
        check(connect.connection(folder)["ready"], "rebuilt, it is ready again")

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
        mcp_text = ("config", "config_text", "shells", "server_name", "launch_line", "launcher",
                    "codex_toml", "pointer")
        check(c["ready"] and c["connect"] == "files-only"
              and c["status_text"].startswith("Agent Context ready for file access.")
              and "Ready to connect" not in c["status_text"],
              "Windows, a path cmd /c cannot carry: ready for file access, not called ready to connect")
        check("cmd /c" in c["mcp_limitation"] and "% &" in c["mcp_limitation"]
              and "No MCP configuration is offered" in c["mcp_limitation"]
              and not any(k in c for k in mcp_text),
              "the concrete MCP limitation, and no MCP configuration or command at all")
        check(c["instruction"] and c["map"] in c["instruction"],
              "the file-access instruction is still offered")
        check(connect.connection(odd, windows=False)["connect"] in ("ready", "needs-path")
              and "config" in connect.connection(odd, windows=False),
              "elsewhere the same path gets MCP text")
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
        c = connect.connection(folder, windows=True, registry=FakeRegistry())
        expected = ["mcp", "add", "charter-shell-test", "--", "cmd", "/c", "charter", "mcp", "--context", folder]
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
        shutil.rmtree(base)


def run() -> int:
    case_quoting()
    case_payload()
    case_not_ready()
    case_writes_nothing()
    case_real_shells()
    print(f"\n{OK} All Connect agents checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
