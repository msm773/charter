"""Private per-machine state, keyed by Agent Context folder. Run: python -m tests.private_store

Agent Context as the Project Asset §3 and the Product Specification §4:

  * the state root is the operating system's application-data location, never
    moved by an environment variable, and private to this user;
  * state is associated with a folder by its canonical location only, and
    nothing is written into the folder; a copied or moved folder starts fresh;
  * candidates are addressed by logical `authority-candidates/<name>.md` paths;
    names are checked, and unique across governing, candidate and archived
    documents;
  * deleting private state does not affect the Agent Context.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import agent_context as ac  # noqa: E402
from app import host_state as hs  # noqa: E402
from app import private_store as ps  # noqa: E402
from tests.agent_context import context, snapshot  # noqa: E402
from tests.harness import isolated_private_state  # noqa: E402

OK = "ok"


def check(condition: bool, label: str) -> None:
    if not condition:
        print(f"  FAILED: {label}")
        raise SystemExit(1)
    print(f"  {OK} {label}")


def refused(fn, *args) -> bool:
    try:
        fn(*args)
    except ps.PrivateStateError:
        return True
    return False


def raises_value(fn, *args) -> bool:
    try:
        fn(*args)
    except ValueError:
        return True
    return False


def put(path: str, text: str) -> None:
    """Place a private file directly, as a test fixture: Charter itself writes
    private state only through a transaction."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


def case_state_root() -> None:
    print("\nthe state root")
    real = ps._default_root()
    check(os.path.basename(real) in ("Charter", "charter") and os.path.basename(os.path.dirname(real))
          != "CGU", "it is Charter's own folder in the application-data location")
    name = "LOCALAPPDATA" if os.name == "nt" else "HOME"
    saved = os.environ.get(name)
    os.environ[name] = tempfile.gettempdir()
    try:
        check(ps._default_root() == real, f"setting {name} does not move it")
    finally:
        if saved is None:
            del os.environ[name]
        else:
            os.environ[name] = saved
    check(_constructor_refused(),
          "shipped code can only obtain it with `default()`")

    with isolated_private_state() as root:
        state = ps.PrivateState.default()
        check(state.root == root and not os.path.exists(root), "nothing is created until used")
        folder = context()
        state.for_context(folder)
        check(hs.private_problem(root) == "", "once created, it is private to this user")
        shutil.rmtree(folder)


def _constructor_refused() -> bool:
    try:
        ps.PrivateState()
    except TypeError:
        return True
    return False


def case_keyed_by_folder() -> None:
    print("\nkeyed by folder location")
    with isolated_private_state():
        state = ps.PrivateState.default()
        folder = context()
        before = snapshot(folder)
        one = state.for_context(folder)
        two = state.for_context(folder + os.sep)
        check(one.base == two.base, "the same folder, spelled differently, has the same state")
        if os.name == "nt":
            check(state.for_context(folder.upper()).base == one.base,
                  "and letter case does not matter where the filesystem ignores it")
            check(state.for_context("\\\\?\\" + folder).base == one.base,
                  "and an extended-length `\\\\?\\` spelling is the same state, not a second identity")
        here = os.getcwd()
        os.chdir(os.path.dirname(folder))
        try:
            check(state.for_context(os.path.basename(folder)).base == one.base,
                  "a relative path finds the same state")
        finally:
            os.chdir(here)
        check(snapshot(folder) == before and ac.examine(folder).valid,
              "nothing is written into the Agent Context folder")
        check(state.find_context(folder).base == one.base
              and state.find_context(folder + "-elsewhere") is None,
              "existing state can be found without creating any")
        check(state.known_contexts() == [hs.canonical(folder)],
              "the state remembers which folder it belongs to, privately")
        check(hs.location_key(folder) in one.base and os.path.basename(folder) not in one.base,
              "and its folder name is a one-way key, not the folder's name")
        with one.lock("writer") as held:
            check(held and not one.holds_records(),
                  "state that only records the folder was opened, and its locks, holds no records")
        one.remember_settings("Test project", ac.Settings.make("Test project").guidance_map)
        check(one.holds_records(), "remembered settings are a record")
        os.remove(one.path(ps.LAST_SETTINGS))
        put(one.path(ps.CHANGESETS, "0123456789abcdef.json"), "{}")
        check(one.holds_records(), "so is a draft, however deep")
        os.remove(one.path(ps.CHANGESETS, "0123456789abcdef.json"))
        check(not one.holds_records(), "and empty folders are not")

        put(one.candidate_file("authority-candidates/draft.md"), "---\nid: d\n---\n")
        copy = folder + "-copy"
        shutil.copytree(folder, copy)
        check(state.for_context(copy).candidates() == [],
              "a copied folder starts with fresh private state")
        moved = folder + "-moved"
        os.rename(folder, moved)
        check(state.for_context(moved).candidates() == [], "so does a moved folder")
        os.rename(moved, folder)
        check(state.for_context(folder).candidates() == ["authority-candidates/draft.md"],
              "and reopening the original folder finds its state again")
        shutil.rmtree(copy)
        shutil.rmtree(folder)


def case_boundaries() -> None:
    print("\nboundaries")
    with isolated_private_state() as root:
        state = ps.PrivateState.default()
        state.ensure()
        inner = os.path.join(root, "contexts", "x")
        os.makedirs(inner)
        check(refused(state.for_context, inner),
              "an Agent Context inside the private state is refused")
        if os.name == "nt":
            check(refused(state.for_context, "\\\\?\\" + inner),
                  "and the refusal is not evaded by an extended-length `\\\\?\\` spelling")
        check(refused(state.for_context, os.path.dirname(root)),
              "and so is one that contains the private state")
        folder = context()
        cs = state.for_context(folder)
        record = os.path.join(cs.base, ps.CONTEXT_RECORD)
        hs.write_json_atomic(record, {"version": 1, "folder": "elsewhere"})
        check(refused(state.for_context, folder),
              "state recorded for another folder is not used for this one")
        shutil.rmtree(folder)


def case_candidates_and_archive() -> None:
    print("\ncandidates and the archive")
    with isolated_private_state():
        state = ps.PrivateState.default()
        folder = context()
        cs = state.for_context(folder)
        logical = "authority-candidates/new-policy.md"
        put(cs.candidate_file(logical), "---\r\nid: p\r\n---\r\nBody.\r\n")
        check(cs.candidates() == [logical], "a candidate is listed by its logical path")
        check(cs.read_candidate(logical) == "---\nid: p\n---\nBody.\n",
              "and read back as LF text")
        check(not os.path.exists(os.path.join(folder, "authority-candidates")),
              "it is not in the Agent Context folder")
        check(cs.read_candidate("authority-candidates/missing.md") is None,
              "a candidate that does not exist reads as nothing")
        for bad in ("authoritative/a.md", "authority-candidates/../a.md",
                    "authority-candidates/sub/a.md", "authority-candidates/a.txt",
                    "authority-candidates/.hidden.md", "authority-candidates/CON.md",
                    "authority-candidates/" + "x" * 130 + ".md", "authority-candidates/a b.md"):
            check(refused(cs.candidate_file, bad), f"`{bad[:48]}` is not a candidate path")

        put(cs.archive_file("old.md"), "old\n")
        check(cs.archived() == ["old.md"] and cs.read_archived("old.md") == "old\n",
              "archived documents are kept privately by name")
        governing = [d.path for d in ac.examine(folder).documents]
        check(cs.name_in_use("A.md", governing), "a governing document's name is in use")
        check(cs.name_in_use("NEW-policy.md") and cs.name_in_use("old.md"),
              "so are candidate and archived names, ignoring letter case")
        check(cs.new_candidate_path("a", governing) == "authority-candidates/a-2.md",
              "a new candidate gets a name free everywhere")
        check(cs.new_candidate_path("-bad", governing) == "authority-candidates/untitled.md",
              "a name that cannot be used falls back to `untitled`")
        shutil.rmtree(folder)


def case_observed_and_locks() -> None:
    print("\nthe last observed context, and locks")
    with isolated_private_state():
        state = ps.PrivateState.default()
        folder = context()
        cs = state.for_context(folder)
        check(cs.observed() is None, "a new state has observed nothing")
        exam = ac.examine(folder)
        cs.record_observed(exam.fingerprint, exam.hashes, "rebuild", ["authoritative/a.md"])
        seen = cs.observed()
        check(seen["fingerprint"] == exam.fingerprint and seen["source"] == "rebuild"
              and seen["sha256"] == exam.hashes and seen["outside"] == ["authoritative/a.md"],
              "the fingerprint, hashes, source and unacknowledged outside changes are remembered")
        check(raises_value(cs.record_observed, exam.fingerprint, exam.hashes, "guess"),
              "only the known sources are recorded")
        with open(cs.path(ps.OBSERVED), "w") as fh:
            fh.write("{not json")
        check(cs.observed() is None, "an unreadable record counts as nothing observed")

        with cs.lock("writer") as held:
            check(held, "the writer lock is taken")
            with cs.lock("writer", timeout=0.2) as again:
                check(not again, "a second holder waits, then gives up")
            with cs.lock("intake", timeout=0.2) as other:
                check(other, "other kinds of lock are independent")
        check(os.path.dirname(cs.staging_dir("journal")).startswith(cs.base),
              "staging is inside this context's private state")
        shutil.rmtree(folder)


def case_disposable() -> None:
    print("\nprivate state is disposable")
    with isolated_private_state() as root:
        state = ps.PrivateState.default()
        folder = context()
        before = snapshot(folder)
        cs = state.for_context(folder)
        put(cs.candidate_file("authority-candidates/draft.md"), "draft\n")
        shutil.rmtree(root)
        check(ac.examine(folder).valid and snapshot(folder) == before,
              "deleting it leaves the Agent Context valid and unchanged")
        check(state.for_context(folder).candidates() == [],
              "opening the folder again recreates empty private state")
        shutil.rmtree(folder)


def _tree(root: str) -> dict:
    """Every file under `root`, by relative path, with its bytes."""
    out = {}
    for d, _subs, names in os.walk(root):
        for n in names:
            p = os.path.join(d, n)
            with open(p, "rb") as fh:
                out[os.path.relpath(p, root)] = fh.read()
    return out


def _earlier_state(folder: str) -> tuple:
    """State as Agent Context Manager left it: built in Charter's root, with a
    candidate and an observation recorded under the earlier name, then moved
    to the earlier name's folder. Returns (state, its files)."""
    state = ps.PrivateState.default()
    cs = state.for_context(folder)
    put(cs.candidate_file("authority-candidates/kept.md"), "---\nid: kept\n---\n\nKept.\n")
    exam = ac.examine(folder)
    cs.record_observed(exam.fingerprint, exam.hashes, "acm", [])
    files = _tree(state.root)
    os.rename(state.root, state.legacy_root)
    return state, files


def case_legacy_state() -> None:
    print("\nprivate state Agent Context Manager, Charter's earlier name, left behind")
    from app import manager as mg
    from app.__main__ import _report
    with isolated_private_state() as root:
        base = os.path.dirname(root)
        state = ps.PrivateState.default()
        check(os.path.basename(ps._legacy_root(ps._default_root())) in ("ACM", "acm")
              and os.path.basename(state.legacy_root) in ("ACM", "acm")
              and os.path.dirname(state.legacy_root) == base
              and os.path.normcase(base).startswith(os.path.normcase(tempfile.gettempdir())),
              "the earlier root is the ACM folder beside Charter's: here, inside this test's own "
              "temporary folder, never this computer's")
        folder = context()

        # Only the earlier state: read-only operations read it, adopt nothing, create nothing.
        state, files = _earlier_state(folder)
        legacy = state.legacy_root
        cs = state.find_context(folder)
        check(cs is not None and cs.base.startswith(legacy)
              and cs.read_candidate("authority-candidates/kept.md") is not None
              and cs.observed()["source"] == "acm",
              "read-only, the earlier state is found where it is, its `acm` observation still read")
        status = mg.check(folder, git=False)
        check(not os.path.exists(state.root) and _tree(legacy) == files
              and status["legacy_state"]["status"] == "pending"
              and status["outside"]["known"] and not status["outside"]["changed_outside"],
              "`check` adopts nothing and creates nothing, and says the earlier state is waiting")
        check(any("Charter takes it over" in line for line in _report(status)),
              "`charter check` tells the person, in words")

        # The first write adopts it: one rename, every record, byte for byte.
        cs = state.for_context(folder)
        check(not os.path.exists(legacy) and _tree(state.root) == files
              and cs.read_candidate("authority-candidates/kept.md") is not None,
              "the first write adopts it whole: every record moved, none copied, none changed")
        check(state.legacy()["status"] == "" and not hs.private_problem(state.root),
              "afterwards there is nothing earlier left, and the state is still private to this user")

        # Adoption that cannot complete refuses the write, and moves and creates nothing.
        os.rename(state.root, legacy)
        real_rename = os.rename

        def busy(src, dst):
            if os.path.normcase(src) == os.path.normcase(legacy):
                raise PermissionError(32, "The process cannot access the file")
            return real_rename(src, dst)
        os.rename = busy
        try:
            try:
                state.for_context(folder)
                message = ""
            except ps.PrivateStateError as exc:
                message = str(exc)
            opened = refused(mg.open_context, folder)
        finally:
            os.rename = real_rename
        check("could not take over" in message and legacy in message and "Nothing was moved" in message
              and not os.path.exists(state.root) and _tree(legacy) == files,
              "a rename that fails refuses the write: no fresh root, nothing partly copied, a way out")
        check(opened and not os.path.exists(state.root) and _tree(legacy) == files,
              "opening the Agent Context is refused the same way; it never starts fresh beside it")

        # Another Charter process adopting it first is not a failure.
        def raced(src, dst):
            real_rename(src, dst)
            raise FileExistsError(183, "Cannot create a file when that file already exists")
        os.rename = raced
        try:
            cs = state.for_context(folder)
        finally:
            os.rename = real_rename
        check(cs.read_candidate("authority-candidates/kept.md") is not None and not os.path.exists(legacy),
              "if another Charter process took it over a moment before, that state is used")

        # Both exist: Charter's own is used, the earlier one is left untouched and reported.
        os.makedirs(os.path.join(legacy, "contexts"))
        put(os.path.join(legacy, "contexts", "x", "context.json"), '{"version": 1, "folder": "elsewhere"}')
        earlier = _tree(legacy)
        cs = state.for_context(folder)
        status = mg.check(folder, git=False)
        check(_tree(legacy) == earlier and cs.base.startswith(state.root)
              and status["legacy_state"]["status"] == "left" and legacy in status["legacy_state"]["message"]
              and "has not read or changed" in status["legacy_state"]["message"],
              "with both, Charter uses its own, leaves the earlier folder unchanged, and reports it")
        check(any("still at" in line for line in _report(status)), "and `charter check` says so")
        shutil.rmtree(legacy)

        # A link where the earlier state was is never followed or moved.
        if os.name != "nt":
            shutil.rmtree(state.root)
            target = tempfile.mkdtemp(prefix="charter-elsewhere-")
            os.symlink(target, legacy)
            check(refused(state.for_context, folder) and not os.path.exists(state.root)
                  and os.path.islink(legacy), "a link in the earlier state's place is refused, not followed")
            os.remove(legacy)
            shutil.rmtree(target)
        shutil.rmtree(folder)

    with isolated_private_state() as root:
        folder = context()
        state = ps.PrivateState.default()
        state.for_context(folder)
        check(os.path.isdir(root) and not os.path.exists(state.legacy_root)
              and state.legacy()["status"] == "",
              "with no earlier state, Charter simply starts its own")
        shutil.rmtree(folder)


def case_bounded_names() -> None:
    print("\nnew private names are always valid, bounded, and found in a bounded search")
    for text, stem in (("_Ünï code notes", "Uni-code-notes"), ("con", "con-document"),
                       ("", "document"), ("...", "document"), ("a b/c\\d:e", "a-b-c-d-e"),
                       ("x" * 300, "x" * (ps.MAX_NAME - 8))):
        made = ps.safe_stem(text)
        check(made == stem and not ps.name_problem(f"{made}-999.md"),
              f"a stem made from {text[:20]!a} is {stem[:20]!a} (first 20 characters shown)")
    check(ps.free_name("a", []) == "a.md" and ps.free_name("a", ["A.MD"]) == "a-2.md"
          and ps.free_name("a", ["a.md"], first="b.md") == "b.md"
          and ps.free_name("a", [], first="_bad.md") == "a.md",
          "the first free name is taken, ignoring case; an unusable first choice is skipped")
    long = "y" * 119
    names = [ps.free_name(long, [f"{long[:117]}.md"])]
    check(len(names[0]) <= ps.MAX_NAME and not ps.name_problem(names[0])
          and names[0].endswith("-2.md"),
          "a stem too long for its suffix is shortened to fit, never searched for forever")
    real = ps.MAX_NAME_TRIES
    ps.MAX_NAME_TRIES = 4
    try:
        try:
            ps.free_name("busy", ["busy.md", "busy-2.md", "busy-3.md", "busy-4.md"])
            said = ""
        except ps.PrivateStateError as exc:
            said = str(exc)
    finally:
        ps.MAX_NAME_TRIES = real
    check("free private name" in said and "busy" in said,
          "every name taken: a refusal worded for the person")
    with isolated_private_state():
        folder = context()
        state = ps.PrivateState.default()
        cs = state.for_context(folder)
        check(cs.new_candidate_path("_odd", ["authoritative/untitled.md"])
              == "authority-candidates/untitled-2.md",
              "a slug that cannot name a candidate becomes `untitled`, numbered past what is taken")
        shutil.rmtree(folder)


def case_untrusted_state() -> None:
    print("\nstate that is there but cannot be trusted is not mistaken for absent state")
    with isolated_private_state() as root:
        folder = context()
        state = ps.PrivateState.default()
        check(state.find_context(folder, strict=True) is None and not os.path.exists(root),
              "absent state: None, strictly too, and nothing is created")
        cs = state.for_context(folder)
        check(state.find_context(folder, strict=True).base == cs.base, "present state is found")
        record = cs.path(ps.CONTEXT_RECORD)
        put(record, "{broken")
        check(state.find_context(folder) is None and refused(state.find_context, folder, True)
              and refused(state.for_context, folder),
              "an unreadable folder record: absent to a lenient look, refused strictly and on use")
        put(record, '{"version": 1, "folder": "elsewhere"}')
        check(refused(state.find_context, folder, True) and refused(state.for_context, folder),
              "a record naming another folder: refused strictly and on use")
        os.remove(record)
        check(state.find_context(folder, strict=True) is None,
              "a lost record with nothing journaled: treated as absent")
        put(os.path.join(cs.path(ps.STAGING, "journal"), "journal.json"), "{}")
        check(refused(state.find_context, folder, True),
              "a lost record beside an interrupted-write record: refused strictly")
        with open(record, "w", encoding="utf-8") as fh:
            fh.write('{"version": 1, "folder": %s}' % __import__("json").dumps(cs.folder))
        try:
            from tests.authority import make_link, remove_link
        except ImportError:
            make_link = None
        real = cs.base + "-real"
        os.rename(cs.base, real)
        if make_link is None or not make_link(cs.base, real):
            os.rename(real, cs.base)
            print("  - links not checked: this system refused to create a junction or link")
        else:
            check(refused(state.find_context, folder, True) and refused(state.for_context, folder),
                  "state reached through a link or junction: refused strictly and on use")
            remove_link(cs.base)
            os.rename(real, cs.base)
        shutil.rmtree(folder)


def run() -> None:
    case_state_root()
    case_legacy_state()
    case_keyed_by_folder()
    case_boundaries()
    case_candidates_and_archive()
    case_bounded_names()
    case_untrusted_state()
    case_observed_and_locks()
    case_disposable()
    print(f"\n{OK} All private state checks passed.")


if __name__ == "__main__":
    run()
