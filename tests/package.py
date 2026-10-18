"""Build and verify a release, and its separate verification bundle.

    python3 -m tests.package [build|inspect|verify] [--out <folder>] [release.zip verification.zip]

A build writes two archives to a disposable output folder — a new temporary
folder unless `--out` names one — and never to this working tree's `dist/`:

  * `charter-<version>.zip`, the end-user release: the
    launchers, `app/` and its static page, the README, CHANGELOG and
    requirements. It holds no test and no test-only helper for private state
    (`tests/harness.py`, `tests/_launch.py`): nothing shipped can move the
    private state or answer the person's confirmation;
  * `charter-<version>-verification.zip`, the verification
    bundle: the `tests/` folder alone, for running the suites against a
    release from its source tree.

Verifying checks the release archive exactly — its files, modes, launchers,
version, that no shipped module refers to the tests, and that the extracted
copy runs from any folder — then overlays the verification bundle onto a
separate copy of the extracted release and runs every suite there.

`inspect` builds both archives and checks the release exactly, as verifying
does, but runs no suite: the quick check of the archives alone.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import __version__  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = f"charter-{__version__}"
BUNDLE = f"{NAME}-verification"
TOP_FILES = ("README.md", "CHANGELOG.md", "LICENSE", "requirements.txt", "charter", "charter.cmd", "charter.py")
EXECUTABLE = ("charter", "charter.py")
CRLF = ("charter.cmd",)
TEST_ONLY = ("tests/harness.py", "tests/_launch.py")
# A release's build identity (Product Specification §6), written into the
# release when it is built and nowhere in the source tree.
BUILD_FILE = "app/build.json"
# Every suite, run against the extracted release. Each module under tests/
# that is not a helper is one of these; `inspect` checks that it is.
SUITES = ("agent_context", "private_store", "host_state", "authority", "manager", "console",
          "launchers", "mcp", "activity", "propose", "intake", "changeset", "impact",
          "connect", "git_compare", "ui", "brand")
HELPERS = ("harness", "_launch", "package")
OK = "ok"


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(f"FAILED: {label}")
    print(f"  {OK} {label}")


def _listed(folder: str, suffixes: tuple) -> list:
    base = os.path.join(ROOT, *folder.split("/"))
    return [f"{folder}/{name}" for name in sorted(os.listdir(base))
            if name.endswith(suffixes) and os.path.isfile(os.path.join(base, name))]


def members() -> list:
    """Every file the end-user release contains, as forward-slash paths."""
    out = list(TOP_FILES) + _listed("app", (".py",)) + _listed("app/static", (".js", ".css", ".html"))
    return sorted(out + [BUILD_FILE])


def build_record() -> bytes:
    """`app/build.json`: the version, when this release was built, and, when Git
    can tell, the commit it was built from and whether the tree had uncommitted
    changes. Git is asked read-only, about this source tree only."""
    from app import identity
    found = identity.commit_of(ROOT) if identity.development_checkout(ROOT) else {"commit": "", "dirty": None}
    record = {"version": __version__,
              "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "commit": found["commit"], "dirty": bool(found["dirty"])}
    return (json.dumps(record, indent=1, sort_keys=True) + "\n").encode("utf-8")


def release_file(rel: str) -> bytes:
    """One release member's bytes as the release carries them, `app/build.json`
    included, which is generated rather than read from the source tree."""
    if rel == BUILD_FILE:
        return build_record()
    with open(os.path.join(ROOT, *rel.split("/")), "rb") as fh:
        return release_bytes(rel, fh.read())


def bundle_members() -> list:
    """Every file the verification bundle contains: the tests, and nothing else."""
    return sorted(_listed("tests", (".py", ".js")))


def release_bytes(rel: str, data: bytes) -> bytes:
    """A file's bytes as the release carries them. The Windows launcher always
    has CRLF line endings, whatever the checkout it was built from holds: Git
    stores it with LF, and only a checkout's own settings decide what is on disk."""
    if rel in CRLF:
        return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    return data


def _write(target: str, prefix: str, files: list, root: str = ROOT, generated: dict = None) -> None:
    tmp = target + ".partial"
    generated = generated or {}
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in files:
            if rel in generated:
                info = zipfile.ZipInfo(f"{prefix}/{rel}", time.localtime()[:6])
                info.create_system = 3
                info.external_attr = (0o100644 & 0xFFFF) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, generated[rel])
                continue
            path = os.path.join(root, *rel.split("/"))
            info = zipfile.ZipInfo(f"{prefix}/{rel}", time.localtime(os.path.getmtime(path))[:6])
            info.create_system = 3  # Unix, so the permission bits below are honoured
            info.external_attr = ((0o100755 if rel in EXECUTABLE else 0o100644) & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(path, "rb") as fh:
                archive.writestr(info, release_bytes(rel, fh.read()))
    os.replace(tmp, target)


def build(out: str = "") -> tuple:
    """Write the release and the verification bundle to `out` (a new temporary
    folder by default). Returns their paths."""
    out = os.path.abspath(out) if out else tempfile.mkdtemp(prefix="charter-dist-")
    os.makedirs(out, exist_ok=True)
    release = os.path.join(out, NAME + ".zip")
    bundle = os.path.join(out, BUNDLE + ".zip")
    _write(release, NAME, members(), generated={BUILD_FILE: build_record()})
    _write(bundle, NAME, bundle_members())
    print(f"Built {release} ({len(members())} files)")
    print(f"Built {bundle} ({len(bundle_members())} files)")
    return release, bundle


def _shipped_imports(root: str) -> list:
    """Modules shipped code imports that are tests."""
    found = []
    for folder, _dirs, files in os.walk(root):
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(folder, name)
            with open(path, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "tests":
                    found.append(path)
                elif isinstance(node, ast.Import) and any(a.name.split(".")[0] == "tests"
                                                          for a in node.names):
                    found.append(path)
    return found


def _crlf_from_lf_checkout(released: bytes) -> bool:
    """Build `charter.cmd` into an archive from an LF-only copy of it, as a macOS or
    Linux checkout holds it, and compare the ZIP entry's raw bytes."""
    with open(os.path.join(ROOT, "charter.cmd"), "rb") as fh:
        lf = fh.read().replace(b"\r\n", b"\n")
    scratch = tempfile.mkdtemp(prefix="charter-lf-checkout-")
    try:
        with open(os.path.join(scratch, "charter.cmd"), "wb") as fh:
            fh.write(lf)
        target = os.path.join(scratch, "lf.zip")
        _write(target, NAME, ["charter.cmd"], root=scratch)
        with zipfile.ZipFile(target) as archive:
            built = archive.read(f"{NAME}/charter.cmd")
        return (b"\r" not in lf and built == released and built.count(b"\r\n") == lf.count(b"\n")
                and b"\n" not in built.replace(b"\r\n", b""))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def verify(release: str, bundle: str, run_suites: bool = True) -> int:
    print(f"verifying {release}")
    with zipfile.ZipFile(release) as archive:
        names = archive.namelist()
        infos = {i.filename: i for i in archive.infolist()}
        check(archive.testzip() is None, "the archive's checksums are intact")
        check(sorted(names) == [f"{NAME}/{m}" for m in members()],
              f"it holds exactly the release's {len(names)} files, under {NAME}/")
        check(not any("/tests/" in n or n.endswith(tuple(t.split("/")[-1] for t in TEST_ONLY))
                      for n in names),
              "no test and no test-only helper for private state")
        check(not any("__pycache__" in n or n.endswith((".pyc", ".pyo")) or "/dist/" in n
                      or "/.git" in n or "/assets/" in n for n in names),
              "no bytecode, no dist/, nothing from Git, no working material")
        for rel in EXECUTABLE:
            mode = infos[f"{NAME}/{rel}"].external_attr >> 16
            check(infos[f"{NAME}/{rel}"].create_system == 3 and stat.S_IMODE(mode) == 0o755,
                  f"`{rel}` is executable (0755)")
        launcher = archive.read(f"{NAME}/charter")
        check(launcher.startswith(b"#!/usr/bin/env bash\n") and b"\r" not in launcher
              and b'"$here/charter.py"' in launcher,
              "`charter` is a bash script with Unix line endings, running charter.py")
        windows = archive.read(f"{NAME}/charter.cmd")
        check(windows.startswith(b"@echo off\r\n") and b"\n" not in windows.replace(b"\r\n", b"")
              and all(b < 0x80 for b in windows) and b'"%~dp0charter.py"' in windows,
              "`charter.cmd` is an ASCII batch script with Windows line endings, running charter.py")
        check(_crlf_from_lf_checkout(windows),
              "a `charter.cmd` checked out with LF endings, as on macOS or Linux, is still released "
              "with CRLF, byte for byte the same")
        check(not any(n.split("/")[-1] in ("cgu", "cgu.cmd", "cgu.py") for n in names),
              "there is no `cgu` launcher: no compatibility command")
        version = archive.read(f"{NAME}/app/__init__.py").decode("utf-8")
        check(f'__version__ = "{__version__}"' in version, f"it is version {__version__}")
        record = json.loads(archive.read(f"{NAME}/{BUILD_FILE}").decode("utf-8"))
        check(set(record) == {"version", "built", "commit", "dirty"} and record["version"] == __version__
              and len(record["built"]) == 20 and record["built"].endswith("Z")
              and isinstance(record["commit"], str) and isinstance(record["dirty"], bool),
              "it records its build identity: version, build time, commit and whether the tree was dirty")
        check(f"{NAME}/LICENSE" in names, "the release includes a LICENSE file")
        license_text = archive.read(f"{NAME}/LICENSE").decode("utf-8")
        check("Apache License" in license_text and "Version 2.0" in license_text
              and "Copyright 2026 Mike Meyers" in license_text,
              "and it is the Apache License 2.0 carrying the project's copyright")
        where = tempfile.mkdtemp(prefix="charter-package-")
        archive.extractall(where)
        # extractall ignores the archived permission bits, which unzip and
        # Finder apply: give the launchers the modes the archive records.
        for rel in EXECUTABLE:
            os.chmod(os.path.join(where, NAME, *rel.split("/")),
                     stat.S_IMODE(infos[f"{NAME}/{rel}"].external_attr >> 16))
    root = os.path.join(where, NAME)
    check(_shipped_imports(root) == [], "no shipped module imports anything from the tests")
    modules = sorted(n[:-3] for n in os.listdir(os.path.join(ROOT, "tests")) if n.endswith(".py"))
    check(sorted(SUITES + HELPERS) == modules,
          f"every test module is a registered suite or a helper ({len(SUITES)} suites)")
    # This working tree stays on the import path, so the probe would find it if
    # the extracted copy did not come first. Paths are compared resolved: a
    # temporary folder can be reached through a symlink (macOS's /var is
    # /private/var), and the child reports the resolved one.
    probe = subprocess.run([sys.executable, "-c", "import app, os; print(os.path.realpath(app.__file__))"],
                           cwd=root, capture_output=True, text=True,
                           env=dict(os.environ, PYTHONPATH=ROOT))
    imported = probe.stdout.strip()
    check(imported.startswith(os.path.join(os.path.realpath(root), ""))
          and not imported.startswith(os.path.join(os.path.realpath(ROOT), "")),
          "the extracted copy imports its own app, not this working tree's")
    help_text = subprocess.run([sys.executable, os.path.join(root, "charter.py"), "--help"],
                               cwd=tempfile.gettempdir(), capture_output=True, text=True)
    check(help_text.returncode == 0 and help_text.stdout.startswith("usage: charter ")
          and "{serve,check,mcp,compare,propose,add-to-path}" in help_text.stdout,
          "the extracted `python charter.py --help` runs from any folder: serve, check, mcp, compare, propose, add-to-path")
    empty = tempfile.mkdtemp(prefix="charter-not-a-context-")
    checked_out = subprocess.run([sys.executable, os.path.join(root, "charter.py"), "check", "--context",
                                  "."], cwd=empty, capture_output=True, text=True,
                                 stdin=subprocess.DEVNULL)
    check(checked_out.returncode == 1 and "Agents:        unavailable" in checked_out.stdout
          and os.listdir(empty) == [],
          "the extracted `python charter.py check --context .` reports a folder that is not a valid "
          "Agent Context, exit 1, writing nothing in it")
    shutil.rmtree(empty, ignore_errors=True)

    print(f"\nverifying {bundle}")
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        check(sorted(names) == [f"{NAME}/{m}" for m in bundle_members()]
              and all(n.startswith(f"{NAME}/tests/") for n in names),
              f"the verification bundle holds only the {len(names)} test files")
        checked = tempfile.mkdtemp(prefix="charter-verify-")
        shutil.copytree(root, os.path.join(checked, NAME))
        archive.extractall(checked)
    tree = os.path.join(checked, NAME)
    if not run_suites:
        shutil.rmtree(where, ignore_errors=True)
        shutil.rmtree(checked, ignore_errors=True)
        print(f"\nRelease inspected, no suite run: {release}")
        return 0
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    failed = []
    for suite in SUITES:
        start = time.monotonic()
        proc = subprocess.run([sys.executable, "-m", f"tests.{suite}"], cwd=tree, env=env,
                              capture_output=True)
        took = time.monotonic() - start
        if proc.returncode != 0:
            failed.append(suite)
            tail = (proc.stdout + proc.stderr).decode("utf-8", "replace")[-2500:]
            print(f"  FAILED tests.{suite} against the extracted release:\n{tail}")
        else:
            print(f"  ok tests.{suite} against the extracted release ({took:.0f}s)")
    check(not failed, "every suite passes against the extracted release"
          + (f" (failed: {', '.join(failed)})" if failed else ""))
    shutil.rmtree(where, ignore_errors=True)
    shutil.rmtree(checked, ignore_errors=True)
    print(f"\nRelease verified: {release}")
    return 0


def run(argv) -> int:
    args = list(argv)
    out = ""
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
        if not out:
            raise AssertionError("FAILED: --out needs a folder")
    command = args[0] if args else "all"
    if command == "build":
        build(out)
        return 0
    if command == "inspect":
        return verify(*build(out), run_suites=False)
    if command == "verify":
        if len(args) != 3:
            raise AssertionError("FAILED: verify needs the release and the verification bundle")
        return verify(args[1], args[2])
    return verify(*build(out))


if __name__ == "__main__":
    try:
        sys.exit(run(sys.argv[1:]))
    except AssertionError as exc:
        print(exc)
        sys.exit(1)
