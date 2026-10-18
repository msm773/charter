# Changelog

## 2.0.0 — development build, unreleased: Charter

Version `2.0.0.dev0` in the source tree. No 2.0.0 release archive or release
tag has been made yet.

Charter replaces Context Governance Utility's governance
workspace and published surface with one dedicated **Agent Context** folder,
and keeps everything else in private state on this computer. It never operates
Git.

- **Named Charter.** The product is **Charter**, with the command `charter`;
  *Agent Context Manager* is its descriptive category, and the tagline is "One
  trusted context for every AI agent on your project." It was developed under
  the name Agent Context Manager, with the `acm` command, which is gone: there
  is no `acm` launcher, alias or stub. Private state lives in a `Charter`
  folder (`charter` on Linux); the first operation that writes private state
  takes over the earlier `ACM` folder in one rename, refuses with a way out
  when it cannot, never starts fresh beside it, and reports it when both
  exist. A map generated under the earlier name fails closed, with that
  reason, until Rebuild Agent Context regenerates only the map and metadata.
  The MCP server is `charter`, hosts register `charter-<project>`, the console
  uses `X-Charter-Console` headers, review material uses
  `charter-context-impact-prompt/1` and `-report/1`, and the release is
  `charter-<version>.zip`. Unchanged: the Agent Context and its files, MCP
  tools and refusal codes, `acm-context-fingerprint/1`, stored `acm`
  observations, and recovery of an earlier `.acm-txn-` temporary file.
- **The Agent Context.** `AGENT-CONTEXT.md`, `.agent-context.json` and
  `authoritative/`, and nothing else but tolerated tooling files. Validity is
  checked over LF-normalized hashes of the map, metadata and governing
  documents; an invalid or unclean folder is never served.
- **Private state** under the operating system's per-user application-data
  folder (`Charter`): authority candidates, the archive, Agent Proposals,
  change-set drafts and receipts, observed state, bounded MCP
  diagnostic activity, staging and locks. No environment variable moves it.
- **One transaction for every write.** Folder and private writes are journaled
  privately, staged beside their targets and replaced in turn; an interrupted
  write is rolled back when the Agent Context is next opened, and agents are
  refused until then.
- **Candidate actions** — Create candidate, Revise, Edit, Retire, and accepting
  or rejecting an Agent Proposal — are direct: previewed as plans, applied as
  previewed with an ordinary confirmation, and they change only private
  candidates.
- **Every change to governing context is a coordinated change set, planned
  candidate first.** There is no direct grant, replace or withdraw action, in
  the console or its API. A change set is built from the candidates it
  includes, and for each the person chooses exactly one decision: **Replace**,
  with the governing document they select, or **Govern alongside**. It may also
  withdraw governing documents, in the same change set. Every governing
  document no candidate replaces and no withdrawal names is retained without a
  decision and not listed in Build Change Set, while Preview and Apply shows
  every one; a
  document that starts governing after a draft was prepared is retained once
  the draft is refreshed. **Revise…** only writes a revision candidate: it is
  never a change-set decision, and a revision candidate is applied through
  Replace. **Plan a change set…** on a candidate opens a change set that
  includes it, its decision not yet made; **Withdraw in a change set…** on a
  governing document opens one that withdraws it. Nothing is preselected: a
  candidate made with Revise lists the document it was revised from first
  among replacement targets, labelled, as context only. While no document
  governs, a candidate set to Replace says there is nothing to replace yet and
  to choose Govern alongside. Change-set records are version 2.
- **Change sets recorded in the earlier form** — version 1, with a retain,
  revise, replace or withdraw outcome for each governing document — keep their
  meaning. Applied receipts and abandoned drafts are shown exactly as recorded,
  **Revised** included. An active one is never an unreadable record: it can be
  viewed, abandoned or deleted, and is refreshed, reviewed, previewed or
  applied only after **Convert to current form…**, which lists every change
  before the person confirms it — each revise becomes a replace of the same
  document by the same candidate, each replace stays one, govern-alongside and
  withdraw are kept, and each retain or undecided entry is removed and listed,
  leaving that document retained. Conversion changes no governing context, and
  attached reports and prompt records become stale. Nothing converts
  automatically.
- **Dates are the day of writing.** A candidate's or document's `created` and
  `updated` dates are assigned when the action or change set is applied, so a
  preview left open past local midnight still applies.
- **Add Document** removes a Markdown or text file's own front matter from the
  text, offering only a valid one-line `title` and `scope` as editable
  suggestions; identity, authority, lifecycle, source, dates, supersession and
  other tools' keys are not carried over. Candidate text, and an Agent
  Proposal's body, that begins with a front-matter block is refused. Edit
  leaves an older candidate's leftover block out of the form, and the preview
  shows its removal before it is saved.
- **Create Candidate** shows only the drop area and **Choose a file** until a
  file is converted; then one form like **Edit…**, with no numbered steps,
  under **Review Converted Document**: the file's name, kind and size with
  **Choose another file**, any notes, **Title**, **Scope** and **Text**, the
  editable converted document. Choosing another file replaces the conversion,
  its notes, anything typed and any open preview. Leaving the page — by the navigation, Back,
  Cancel or opening another Agent Context — discards the chosen file, its
  conversion, anything typed and any open preview, and a conversion still under
  way is dropped; reopening it always starts fresh. Converting keeps nothing on
  this computer, so there is nothing left to clean up.
- **One compact Scope field** on Create Candidate, **Revise…** and candidate
  **Edit…**: the label **Scope** and the one helper “A short routing summary
  shown in AGENT-CONTEXT.md.”, with no information icon, hover panel or
  placeholder.
- **Rebuild Agent Context** regenerates the map and metadata after documents
  are edited outside Charter, with a preview; outside changes are reported until
  acknowledged.
- **`charter` command:** `serve`, `check` (read-only), `mcp`, `compare`
  (read-only), `propose` and `add-to-path`, from the `charter`, `charter.cmd`
  and `charter.py` launchers.
- **MCP** serves the Agent Context folder directly: four read-only tools,
  revalidation on every call, eight fixed refusal codes, and refusal while a
  write is interrupted.
- **Agent Proposals** through `charter propose --context .` or an imported file,
  filed privately and reviewed in the console; accepting changes only a
  candidate. The page is introduced in one line, with no information panel.
  Each compact card leads with the friendly title of the document it concerns,
  with no operation word or internal `p-…` id — the target's current title, or
  a create's supplied title or else its body's first heading, filed directly
  or imported, with no badge — or the logical path, labelled as one, only when
  there is neither; then one line, **Submitted by:** … · **Received:** …,
  noting an import, and a one-line purpose. **Review proposal…** expands the
  same card in place: the purpose in full, each changed file with **Read**, and
  **Accept as candidate**, **Reject proposal** and **Close review** together at
  the end, with no separate panel and no inline copy of the candidate.
  **Accept as candidate** applies that preview in one step, with no second
  preview or Accept, and the notice says exactly **Proposal accepted.**, with
  no button, link or document name. **Reject proposal** is also on the compact
  card: it asks once, in place, with **Reject** and **Cancel** and no reason
  field, without opening the review; **Reject** removes the proposal and says
  exactly **Proposal rejected.** In an expanded review the confirmation stands
  in for the decision row, so only one Reject action shows. **Cancel** leaves
  the card as it was.
  Closing the review, opening another, or leaving Agent Proposals collapses it
  and drops anything still on its way. Expected context impact stays private advisory
  review material, kept with the proposal and never shown on the review
  surface, and the generated map describes it that way, so a map generated
  before this change fails closed until Rebuild Agent Context. Summaries name
  documents by title, never as `file “…”`. **Import agent proposal…** is the
  fallback for an agent that could not file its own JSON: **Import Agent
  Proposal** asks for the **Agent proposal JSON**, sends people to **Create
  candidate** for their own material, and puts **Check proposal** beside
  **Import**, which only a passing check of the exact JSON entered enables —
  any edit disables it again. A passing check shows nothing more; a failing one
  shows one concise red error. **Check proposal**, **Import** and **Cancel**
  sit together, with no header Close; **Cancel** clears and closes the panel. Leaving Agent Proposals closes it
  and discards what was pasted or checked, including a check still under way.
- **Authority candidate cards** show the title and then one source tag —
  **Proposed by: <agent>** when the proposal named its agent, otherwise
  **Agent Proposal**; **Created by person**; **Revision**; or **Withdrawn
  governing document**, which a change set's withdrawal now records privately
  — never an invented identity; then **Filename:** and a one-line **Scope:**,
  both rows at the same text size.
- **Coordinated change sets** with explicit decisions, hash pins, a structural
  preview and one typed confirmation; the immutable receipt is written in the
  same transaction as the change. The receipt leads with **Change set
  applied** and a plain summary of its non-zero outcome counts and applied
  date, such as `3 documents updated · 4 retained`; lists each changed
  document by title with a badge for its outcome as recorded; keeps paths,
  archive locations, retained documents, established governing documents and
  the full copyable technical summary behind disclosures; and states whether
  an advisory report was attached apart from each **Review prompt copied** or
  **Review packet exported** record, which is not evidence. **Build Change
  Set** has a **Name**, **Candidates**, **Withdrawals** and a **Change Set
  Summary** beside one **Agent Review** panel, and scrolls as one page. Each
  candidate is a compact row: its title, a provenance label only where titles
  collide, one decision dropdown starting unselected, a target dropdown only
  after **Replace** — a revision's source listed first as a suggestion, never
  selected — and a one-line scope, with **View details** for the complete
  candidate and scope comparison and **Edit details…**, which returns to the
  draft to refresh it. A new change set's **Name** starts empty and is never
  filled from a candidate or withdrawal. “No candidates available.” appears
  only when none is listed or can be added. A required review packet shows only
  its status and size, **Save review packet…** and the disclosure beside it.
  **Add a review**, then **Add another review**, adds reviews whose reviewing
  agent and text save automatically; only a structurally valid report counts
  as attached advisory evidence, invalid text stays saved with validation
  feedback, and **Remove review** asks first only for a valid report.
  **Preview and Apply** shows, in one pass, any blocking problem or
  decision-relevant warning, **Changes to Apply**, naming each document the
  change set changes and what happens to it, with no scope comparison or
  retained-document list, every changed file with its diff and **Read**, the
  regenerated map included, and the typed confirmation with
  **Apply** and **Cancel**: no Governing Now and Governing After lists, and no
  note that only explains mechanics. **Discard draft** asks once, discards the
  private draft and returns to Change Sets. The normal Change Sets view lists active drafts and any record
  it cannot read, never applied change sets or discarded drafts: their
  receipts and records stay private and unchanged, and a receipt is shown when
  its change set is applied. The sidebar shows the Git branch and the
  count of changed context files, with no file list.
  **Advisory review** prompts and packets (`charter-context-impact-prompt/1`,
  `charter-context-impact-report/1`) with mechanical report checks. Review
  material adds no private state, local path or Git detail of Charter's own,
  and embeds the reviewed documents and candidates exactly as they read: one
  that quotes a local path, or, for `charter compare`, a word equal to the
  base such as `main`, no longer stops the material being prepared. Only
  Charter's own wording, metadata and what it sends with the material are
  checked.
- **Console cleanup.** **Open Agent Context…** and the **Charter** wordmark
  both open the Open or Create Agent Context view. There are no information
  icons or hover panels anywhere; the README explains each status, including
  **Agents are served** and **Matches the governing documents**. Governing
  Documents is now **Governing Context**, with one subtitle; its list scrolls
  with the page, and its cards drop the Governing badge and use bold
  **Filename:** and **Scope:** labels. Status labels follow the title they
  describe, a candidate's source label follows its title, and no label sits
  beside action buttons. The header always shows **Agent context ready** or
  **Agent context unavailable**, and the Context Map **Map current**, **Map out
  of date** or **Map not checked**, each in words as well as colour. A
  candidate's agent source reads **Proposed by: <agent>**, the name exactly as
  recorded. The change-set index's empty state reads “No open change sets.”
  Connect Agents is four sections, each a heading that opens and closes it:
  **Connect Agents with MCP (Recommended)**, open, then **Add Project
  Instructions (Optional)**, **Test the Connection (Optional)** and **Connect
  Agents with File Access**, closed. The Agent Proposals subtitle reads
  “Accepted proposals become authority candidates.” and the Change Sets
  subtitle “Apply one or more authority changes as a set.”
  Settings has a subtitle under its heading and two-line guidance options. The
  rail's heading reads **CURRENT CONTEXT**. Every enabled action button —
  Apply, Accept as candidate, Reject proposal, Retire, Close and toast actions
  included — shares the one treatment of **Read** and **Edit…**: white, ink
  text, a light outline, with no filled, danger or authority variant; disabled
  buttons stay visibly disabled. An error toast's **Dismiss** keeps it too, with
  ink text, never white on its white face. **Recent** lists the Agent
  Contexts opened on this computer, the most recently opened first, whenever
  the Open view is shown; its
  **Clear** empties only that list, never an Agent Context or its private
  state, and opening or creating an Agent Context lists it again. The
  Context Map no longer repeats the agent guidance, which Settings shows. Retired
  and replaced documents stay in private state; the console shows no archive.
- **Connect agents:** a guided, copy-only view, offered only while the Agent
  Context is ready. From a development checkout or worktree, every
  configuration and command names that checkout's own launcher by its full
  path, so PATH can never route an agent to another copy; an installed release
  names `charter`. MCP comes first, as the recommended route: `claude mcp add`
  commands quoted for each shell, at Claude Code's default local scope rather
  than for every project; Codex's `[mcp_servers.<name>]` TOML; JSON for other
  hosts; a startup pointer for the project's `CLAUDE.md` or `AGENTS.md`; and a
  check command. A prompt follows that confirms an agent retrieved the context.
  File access and terminal proposals are optional sections, and an **Access and
  trust** disclosure says what Charter controls and what an agent host's wider
  permissions can bypass. Status lists what was checked and what was not, so
  "ready to connect" never means the host or the agent is connected.
- **`charter mcp --check`** also says how a newly started program finds `charter`, and
  that it ran the server with its own Python, not the host's command,
  environment or agent.
- **`charter.cmd`** runs the first Python 3.9 or later it finds, `py -3` then
  `python`, proving each first, and says so when there is none, as `charter` does.
- **`charter` and `charter.py`** are executable in Git as in the release, and
  `charter` follows symlinks, so a link such as `~/.local/bin/charter` runs this
  copy. On macOS and Linux, `charter add-to-path` changes nothing: it prints the
  `export` line and the startup file for the user's shell (`~/.bashrc`,
  `~/.zshrc`, or for bash on macOS the login file bash reads: `~/.bash_profile`,
  else an existing `~/.bash_login` or `~/.profile`, so a new file never stops
  bash reading one), and on Linux points desktop-started hosts to `~/.profile`
  and a new login. `--check` names a launcher that is not executable, with the
  `chmod +x` that fixes it, and reads PATH entries literally, as shells do. Both
  exit 0 only when the shell already runs this copy as `charter`. `charter`
  finds its folder with bash alone, so it needs no `dirname`, which macOS keeps
  only in `/usr/bin`.
- **macOS paths:** one folder is one location however it is spelled. Canonical
  paths take the letter case a case-insensitive volume stores, so `/users/me/x`
  and `/Users/me/x` share private state and containment checks, and a review
  packet cannot be saved into an Agent Context or private state by typing it in
  other letter case. Review material is refused when it quotes the Agent
  Context, its Git checkout, private state or home in any spelling of the same
  place: as given, as resolved, through a link to it, or through a top-level
  link such as macOS's `/var` for `/private/var`.
- **`charter serve`** writes its address at once, also when its output is piped
  or redirected. On Linux and macOS, a console stopped with Ctrl+C starts again
  at once on the port it used, which its closed connections still hold for
  about a minute; a port another program listens on is still refused, and on
  Windows the console still takes its port exclusively.
- **`charter compare`:** an optional, read-only comparison against a Git
  revision the person names, limited to the Agent Context's folder, with
  advisory review material that names no commit or branch. It runs in the
  terminal, not the console: a summary by default, `--prompt` for the review
  prompt, `--packet` to save a large review where the person says, and
  `--json`. It writes nothing else and creates no private state.
- **The README is a task guide.** Installing starts from the release ZIP, and
  says what to do when another copy of Charter comes first on PATH. Getting
  started and everyday work are numbered procedures: creating and opening an
  Agent Context, Recent and Clear, a status table saying what to do for each
  health and map status, every Settings guidance option with its default and
  map heading, how Create candidate chooses a title (keeping a leading
  heading in the text), optional scope, candidate tasks, change sets from
  start to receipt, and Agent Proposals with the proposal JSON fields and the
  `charter propose` exit codes. Connect Agents is one flow: the server name
  derived from the project name, the copied commands for each host, project
  instructions, the connection test and file access, with an installed release
  kept apart from a development checkout.
- **Agent Proposals are an inbox.** A proposal is temporary work awaiting a
  decision: accepting it files, updates or retires its candidate, and accepting
  or rejecting it removes it. No decided record, rejection reason or proposal
  history is kept, and the change-set review prompt no longer reads one.
  Records an earlier build kept for decided proposals are left exactly as they
  are and never read; their intake-ledger entries are dropped the next time the
  ledger is written. A proposal is a duplicate when its JSON text, exactly as
  submitted — whitespace and any byte-order mark included, never parsed or
  trimmed first — matches one still awaiting review in the same Agent Context,
  from either `charter propose` or an import. `charter propose` refuses a
  duplicate with a new result, `duplicate`, exit code 5, changing nothing and
  saying nothing about the waiting proposal beyond that it exists. Importing one
  asks “An identical proposal, “…,” is already awaiting review. Replace it?”;
  **Replace** updates that one proposal's received time, source and content in
  place, and **Cancel** changes nothing. A proposal filed before this change
  never matches.
- **One name for each agent-guidance setting.** **Context check-in**, **Assess
  proposal impact** and **Review discovered material** are the Settings labels
  and now also their headings in `AGENT-CONTEXT.md`, which also tells agents
  what `duplicate` means. A map generated before this change is recognized as
  an earlier version's and fails closed until Rebuild Agent Context regenerates
  it.
- **Create candidate keeps a leading heading.** A leading `# Heading` still
  suggests the title, and now stays in the text, as an agent's proposed body
  does.
- **Another copy first on PATH.** `add-to-path` and `add-to-path --check` say
  to remove the other copy's folder from PATH. They no longer suggest a bare
  `charter add-to-path`, which would run that copy, or that adding this copy
  again would help. Every command they give runs this copy by its full paths,
  the same command the Charter command dialog gives: on Windows, for
  PowerShell, the Python running Charter with this copy's `charter.py`; on
  macOS and Linux, this copy's launcher, or the Python running Charter with
  `charter.py` while the launcher is not executable. Never a bare `py`,
  `python3` or `charter`.
- **Charter command status.** While an Agent Context is open, the top bar
  shows **Charter command ready** when `charter` in a new terminal runs this
  installation, or **Charter command needs attention**, a warning, when it runs
  another copy, compatible or not, or isn't found. It is independent of the
  Agent Context's status and disables nothing. Choosing it opens a dialog that
  names the copy found, says what a new terminal or `charter propose` would
  do, says agents connected by full path are unaffected, and gives one
  copy-ready command running this copy by the full paths of its Python and
  `charter.py` (elsewhere, its launcher), then says to open a new terminal.
  Connect Agents no longer carries a PATH warning, and Diagnostics states which
  copy `charter` runs without repeating the remedy.
- **Files that don't belong, in plain words.** A folder holding them is headed
  **Charter can’t serve this Agent Context yet**, says the files aren't part of
  the Agent Context and are left untouched, lists each by name with what to do,
  and ends by saying Charter never moves or deletes files it did not create.
  Agents are still refused until it is resolved.
- **Every refusal in plain words.** No status begins "Agents are refused:" any
  more. Each is a heading — **Charter can’t serve this Agent Context yet**,
  **This Agent Context’s map is out of date**, or **This copy of Charter is out
  of date** — then a line saying why and what to do, with the same conditions,
  next actions and fail-closed behaviour. `charter check` reads
  `Agents: unavailable` instead of `refused`, with the same exit codes.
- **Fix…** follows **Charter command needs attention** in the top bar and
  opens the same dialog; **Charter command ready** has none. Revise's notice says a change set replaces the document
  with the revision, and saving unchanged Settings says "Nothing to save".
- **Which copy of Charter is running.** `charter --version` reports the
  version, the build (a release's build time and commit, recorded in the new
  `app/build.json` when it is built; a development checkout's commit and
  whether it is dirty, asked of Git read-only, without locks), the full paths of
  the launcher, `charter.py` and Python, and the map format it generates.
  `charter check` and `charter mcp --check` report the same, with the map
  format the Agent Context records. The console shows it, and what `charter`
  runs for a new terminal, only in a collapsed **Diagnostics** disclosure at
  the end of Settings and of the Open view.
- **Agents start this copy, by its full path.** Every generated registration
  is one program and an exact argument list: on Windows the Python running
  Charter with this copy's `charter.py`, elsewhere this copy's launcher — for a
  release and a development checkout alike. No registration uses a bare
  `charter`, `py`, `cmd /c` or another shell, so PATH cannot route an agent to
  another copy, and paths with spaces or `% & | < > ^` work. PATH no longer
  decides whether Connect Agents is ready; another copy first on it is named,
  with its remedy, and nothing offered would run it. The README recommends one
  stable Charter folder, updated in place, and says to reconnect after moving
  Charter or changing its Python.
- **Map-format version 2, and stale-host diagnosis.** The generated map and
  metadata are now map-format version 2 (the Settings-name headings, the
  `duplicate` result, and MCP-connected agents told to return proposal JSON
  rather than run `charter propose`). A context in version 1 is out of date:
  the console offers Rebuild, MCP refuses with `map-outdated`, and
  `charter propose` returns `unavailable` with `map_outdated`. A context in a
  newer version than this Charter understands is not damage: this copy says it
  is out of date, offers no Rebuild or other write, MCP refuses with
  `server-outdated` ("restart the agent host"), and `charter propose` returns
  `unavailable` with `charter_outdated`. A genuinely invalid context is still
  `context-invalid`. A Rebuild no longer raises a false "Changed Outside
  Charter" notice for Charter's own map and metadata.
- **Removed:** governance workspaces, published surfaces, bindings,
  publication and repair, registration and identity, configuration migration,
  capability records, every Git write (commits, recovery commits, branch
  checks), the in-repository proposal queue, agent-instruction file writing,
  the kickoff prompt, the activity rail, and the `cgu` launchers.

Versions before 2.0.0, below, were released as Context Governance Utility.

## v1.0.0 — 2026-09-26 — optional local MCP context access

The last V1 feature. CGU stays file-first and works fully without MCP. MCP adds
an optional, local, read-only route: a compatible agent retrieves governing
context *through CGU*, and the person governing the repository sees what was
retrieved.

```text
CGU governance action → regenerates AGENT-CONTEXT.md
Local agent → calls CGU through MCP → receives only valid governing context
CGU → records one small activity event → Knowledge shows it
```

### The server

- **`cgu mcp --repo <path> [--client-name "<optional activity label>"]`** — a local stdio MCP
  server shipped with CGU (`app/mcp.py`). The agent host launches it; it speaks
  newline-delimited JSON-RPC 2.0 on stdin/stdout. No port, web server,
  credential or background process; offline; one process per host. Standard
  library only — still no dependencies, still Python 3.9+. Protocol versions
  2024-11-05 through 2025-11-25 are negotiated; `structuredContent` and
  `outputSchema` from 2025-06-18.
- **Nothing but a valid current CGU repository is served** — but an invalid
  one does not make the server exit, which hosts report only as
  "disconnected". The handshake completes, the reason goes into the server's
  instructions and onto stderr, and every tool refuses with it until the
  repository is fixed; the next call after a fix succeeds.
- **Checked against the real client.** Claude Code 2.1.259 on native Windows
  was captured, byte for byte, sending `initialize` at protocol `2025-11-25`,
  `notifications/initialized`, `tools/list`, and tool calls carrying a `task`
  argument and `_meta` — no `server/discover` or other negotiation step. That
  exact transcript is a regression test against a real server process, and an
  opt-in test (`CGU_TEST_CLAUDE_CODE=1`) has the installed `claude` connect to
  it. A leading UTF-8 byte-order mark, which PowerShell adds when piping, is
  ignored rather than answered with a parse error.
- **`cgu mcp … --check`** says in words whether the command can serve an
  agent: repository, governing context, activity, then the exact server command
  run through a handshake. Writes nothing.
- **Four read-only tools, no write tools:** `get_context` (the current
  `AGENT-CONTEXT.md`), `list_governing_documents` (id, title, scope, path),
  `get_document` (one governing document in full) and `get_document_section`
  (one heading's section). Each accepts an optional `task` label.
- **Only governing context.** CGU's own predicate decides — no second
  definition. A document is named by the exact path or id that predicate
  produced; the caller's string is compared, never used as a path. Candidates,
  the archive, proposals, fixed and generated files, anything under
  `.context-governance/`, loose Markdown, traversal, absolute paths and
  look-alikes cannot be named. A file is re-checked as it is read, and one that
  resolves outside `authoritative/` is refused.
- **Fail closed.** Every call re-reads the repository. Any validation error, or
  a missing or out-of-date `AGENT-CONTEXT.md`, refuses all four tools with the
  reason. Nothing is cached: a repair is seen by the next call.
- **Sections by heading, deterministically:** ATX headings outside code fences,
  case and spacing ignored, leading `#`s pin the level; a missing heading lists
  the document's headings, an ambiguous one lists every match.

### Activity

- **`.context-governance/activity/mcp-activity.jsonl`** — one line per
  connection and per tool call, served or refused (`app/activity.py`). Only
  safe fields: schema version, time, per-process session id, the optional
  activity label, the host's self-reported name and version, optional task label, tool, status, a fixed reason
  code, and — only for a governing document actually resolved — its path, title
  and the matched heading. Never document text, prompts, responses or raw
  arguments.
- **Kept out of Git by the committed ignore file.** New repositories get
  `activity/` in `.context-governance/.gitignore` at setup. Repositories set up
  earlier get it through **Enable MCP activity** under Agent integrations: a
  previewed, one-line change to that file, recorded as one scoped commit and
  refused if the file has uncommitted edits or Git cannot commit. Nothing is
  written to the activity folder until Git confirms it is ignored — before that
  the server still serves context, and records nothing.
- **Agents are named by their host.** Activity shows the name the MCP host
  reports about itself during initialization, made friendly — `Claude Code ·
  Read current context`, `Codex · Read current context` — or **Unnamed agent**
  when the host reports nothing usable. An optional activity label
  (`--client-name`), when configured, is shown instead; it exists only to tell
  apart several instances of the same host. The friendly name is computed when
  the page reads the log: what is stored is unchanged, and events recorded with
  a label keep it.
- **Safe with several processes:** each line is written whole under a
  cross-process lock (`msvcrt` on Windows, `flock` elsewhere); a line broken by
  a killed writer is never glued to the next one; an event that cannot get the
  lock within a few seconds is dropped rather than delaying context. Rotates at
  1 MB, keeping one previous file.

### The page

- **Opening and creating are separate.** With no repository open, the page has
  two independent sections instead of one shared path/name/button form.
  **Open existing context repository** takes a folder and opens only a valid
  current CGU context repository; it writes nothing and never touches Git, and
  a plain Git repository is refused with a pointer to creating one. **Create a
  new context repository** takes a human-readable **Project name**, a
  **Location** and a **Repository folder name** (suggested from the project
  name, checked while typing) and, with **Create and open context
  repository** (`POST /api/create`), creates the folder, runs `git init`
  itself, sets up the context structure, records it in one commit and opens it
  on a clean tree. It never sets up over an existing folder or file. No Git, no
  Git identity, or a location inside another repository is explained before
  the folder exists; a later failure removes the folder. It never creates
  `AGENTS.md` or `CLAUDE.md`. An optional **Browse…** opens a native folder
  dialog where the computer has one (`CGU_FOLDER_PICKER=0` turns it off).
  “Run `git init` there first” and the fixed example project name are gone.
  **Open another repository** still returns to this screen. `cgu init` still
  sets up an existing folder from a terminal.

- **Agent integrations → MCP context access:** no name to invent. **Copy MCP
  configuration** — labelled a *generic local MCP configuration (stdio)*, with
  a note that hosts differ, and no `--client-name` by default. The server name
  is generated from the context repository's project name (`cgu-studio-context`,
  `cgu-utility-context`), and the page says so. An **Optional activity label**
  stays collapsed at the end of the section, for distinguishing multiple
  instances of the same agent host; when set, it is added as `--client-name`.
  Existing configurations that pass `--client-name` keep working. Then **Copy agent instruction**, which says to call
  `get_context` first, use MCP when available and read `AGENT-CONTEXT.md`
  directly only as a fallback. Both are offered only once MCP activity is
  enabled; producing and copying them writes nothing. Also **Copy Claude Code
  command** — `claude mcp add --scope user …`, because Claude Code's default
  folder scope is keyed by the exact path string, and on Windows VS Code's
  `c:\…` and a terminal's `C:\…` are different folders to it, so a server added
  in one can be missing in the other — and **Copy check command** for when a
  host shows the server as disconnected.
- **Agent context activity** (“Live access through MCP”): a right-hand rail on
  every view, full height and fixed in place like the navigation, stacked
  below the page on narrow windows; newest first, in plain words
  ("Claude Code · 2 min ago — Read Architecture — “Boundaries”"), refusals
  included, polled every five seconds while a repository is open. Before any
  activity it is one quiet line; configured but unused, it says no retrieval
  has been recorded — not that none happened. The list scrolls inside a fixed
  height, so it never lengthens the page, and a poll does not scroll someone
  reading older entries back to the top. Connections are secondary: the latest
  is one small status line, and each is listed only after **Show connection
  events**. This is display only; the log and its rotation are unchanged.

### What it does not claim

An activity line shows a retrieval through CGU happened. It does not show that
an agent read nothing else, understood what it read or followed it; a client or
host name is a label, not an identity; CGU cannot see or prevent direct file
reads. File-based integration is unchanged and remains the fallback. Nothing
here is described, or should be read, as enforcement. V1 is local only: the
agent host needs filesystem access to the repository.

### Also

- **`cgu.py`**: a Python launcher that works from any folder, on any platform —
  what the MCP configuration runs. `./cgu` now calls it and no longer changes
  directory first, so relative repository paths are read from where you run it.
- The UI's document reader refuses absolute, drive-letter and traversal paths,
  and anything resolving outside the repository.
- **A Markdown link that leads outside the repository never governs.** Found
  under `authoritative/`, `authority-candidates/`, `archive/` or anywhere else,
  a file whose real path is outside the repository (or cannot be resolved) is
  not read: it is a validation error, not a document. Before, one under
  `authoritative/` was scanned as governing by its lexical path and routed to
  from `AGENT-CONTEXT.md`, while MCP refused to read it. Now the governing
  predicate, the context map, the page, MCP and every action agree, and every
  action is blocked until the link is removed.
- **The page's static server checks containment by resolved path components,**
  not a string prefix, which had admitted a sibling folder such as
  `app/static-private/`. Traversal, absolute and drive paths, links leading out
  and unresolvable paths are refused.
- **Release ZIPs are not committed.** `dist/` is ignored; a verified ZIP is a
  release attachment. Source control holds the code, tests, documentation and
  the build-and-verify script.
- **`python -m tests.package`** builds the release ZIP from an explicit file
  list, with `cgu` executable (the 0.2.2–0.3.0 archives had lost
  the bit), then extracts it elsewhere and runs every suite from the copy.
- New suites: `tests.mcp`, `tests.activity`, `tests.boundaries`, `tests.package`; MCP cases added to
  `tests.integrations` and `tests.ui`.

## v0.3.0 — 2026-09-26 — one context model

CGU now governs exactly one repository shape, with one way in, three states and
one confirmation phrase. The classification-based layout of v0.2.x is gone, not
kept alongside: there were no real repositories using it, and two models meant
two sets of rules for humans and agents to keep apart.

### What was wrong

A document classified as a Specification was filed under `authoritative/`
without anyone granting it authority. The index was right — it read the
metadata — but the folder told humans, and agents listing files, that the
document governed. Two sources gave two answers.

### The model

```text
authoritative/           governs — the project's context
authority-candidates/    awaiting possible promotion — not context
archive/                 superseded and retired — not context
.context-governance/     config, proposal inbox, kept originals
AGENT-CONTEXT.md  (README.md)
```

`cgu init <repo>` creates exactly this. A document's folder and its front matter
always agree.

- **Intake is the only way in.** Every document is filed as a non-authoritative
  candidate in `authority-candidates/`, under a name the utility picks. No
  classification, no destination path, no supersession at intake. Keeping the
  original file and its provenance work as before.
- **Grant authority** moves the document to `authoritative/`, marks it,
  regenerates the index, validates, and commits once, scoped to its own paths.
  **Withdraw authority** is the exact reverse: back to `authority-candidates/`.
- **Replace with…** is one commit: the replacement moves into `authoritative/`
  and takes the authority; the prior document is marked `superseded`, records
  `superseded_by` (the replacement records `supersedes`), and moves to
  `archive/`.
- **Retire** marks a candidate `retired` and moves it to `archive/`. It is the
  only way to retire anything, and it applies only to candidates: a governing
  document is replaced, or withdrawn and then retired, so removing current
  context is always its own confirmed act. An agent may propose retiring a
  candidate; a proposal to retire a governing document is refused.
- **Edit details** changes a document's scope, and nothing else.
- **Lifecycle** is `active`, `superseded` or `retired`. Any other status is a
  validation error.
- **Relationships** are `supersedes` and `superseded_by`, always written together.
- **One confirmation phrase**, `change governing context`, confirms every action
  that changes current governing context: granting, withdrawing or transferring
  authority, amending a governing document's text, or editing its scope. Filing,
  retiring or editing a candidate needs no phrase.
- **Governing is gated.** A document governs only if its metadata says
  `authority: authoritative`, it is in `authoritative/`, and it passes
  validation. A document that has not been checked never governs. A hand edit
  that makes a candidate or an archived document claim authority does not make
  it govern: it is not routed by `AGENT-CONTEXT.md`, not shown as governing, and
  reported as an error.
- **Validation** requires folder and metadata to agree, in every direction, and
  reports every Markdown file without governance metadata — in a context folder
  or anywhere else — as an error. While an error stands, other actions are
  refused, and the refusal names the document and the action that repairs it.
- **A root `README.md` is the repository's own.** Like `AGENT-CONTEXT.md` (and a
  root `AGENTS.md` or `CLAUDE.md` an agent keeps there), it is a fixed root file: never a document, never indexed,
  never a candidate or eligible for authority, never reported by validation, and
  never writable by an agent proposal. The exemption is exactly `README.md` at
  the root; a README anywhere else is ordinary Markdown.
- **AGENT-CONTEXT.md**, the context map, routes only to governing documents. Candidates and the archive are
  counted and flagged as not context, never linked.
- **AGENT-CONTEXT.md and PROPOSALS.md** describe the three folders: candidates and
  the archive are not context, a claim of authority outside `authoritative/`
  does not govern, Markdown anywhere else is not context at all, agents never
  move files between the folders, and `create` proposals must target
  `authority-candidates/` with a file name unused in any of the three.
- **The UI** shows Knowledge as *Governing — current context*, *Authority
  candidates — not context* and *Archive — not context*. Candidates offer Grant
  and Retire; governing documents offer Withdraw and Replace. A folder/metadata
  disagreement is flagged on the document with its repairs. Setup asks for a path
  and a project name, nothing else.

- **AGENT-CONTEXT.md, not INDEX.md.** The generated file is `AGENT-CONTEXT.md`, the project's
  context map: which documents govern now, their scopes, and what is not
  context. `AGENT-CONTEXT.md` is a protected fixed file: no
  proposal or document action can write, promote, retire or edit it. `cgu
  reindex` is now `cgu rebuild-context`; the proposal field
  `expected_index_impact` is now `expected_context_impact`. A root `INDEX.md` is
  ordinary loose Markdown, reported like any other.

- **Context check-in.** A new `AGENT-CONTEXT.md` opens with a check-in block,
  above the generated region: agents read `AGENT-CONTEXT.md` and the applicable
  governing documents, then send one progress update whose first line is exactly
  `Context check: AGENT-CONTEXT read.`, stating what they relied on or could not
  read, without creating any artifact. Rebuilds keep it; each repository may
  adjust it.

### Agent integrations are optional; CGU owns no agent's instructions

**What was wrong.** Setup created `AGENTS.md` and `CLAUDE.md`, and a persistent
**Update bootstrap rules** button rewrote them. CGU was assuming that those files
exist, that they sit in the context repository, and that they are its to write —
when an agent's instructions usually live in the project it works on, and belong
to that project.

**Now.**

- CGU core owns `authoritative/`, `authority-candidates/`, `archive/`,
  `AGENT-CONTEXT.md` and `.context-governance/`, and nothing else. `cgu init`
  creates no agent instruction file. **Update bootstrap rules**, the `bootstrap`
  plan and its templates are gone.
- The rules agents need now live in files CGU does own: `AGENT-CONTEXT.md` says
  what is not context, that agents do not grant authority or move documents,
  and that governing context changes through an agent proposal as
  `PROPOSALS.md` describes. It no longer refers to `AGENTS.md` or `CLAUDE.md`.
  Existing context maps show as out of date until the next action or rebuild.
- **Agent integrations**, a new optional page under Agent Proposals, connects an
  agent to the repository. For `AGENTS.md` and `CLAUDE.md` you select the file;
  nothing is assumed and selecting writes nothing. Add, update and remove are
  previewed and touch only a block between
  `<!-- context-governance:agent-context:begin/end -->`: every other byte is
  kept, the block is never duplicated, and malformed markers stop every write.
  A file inside the context repository is recorded as one scoped commit; a file
  outside it is written but not recorded anywhere, and the preview says so first.
- A **startup instruction** — the universal fallback for agents without a
  supported instruction file — is generated from the same wording, names
  `AGENT-CONTEXT.md` by its full path, and can be copied. It writes nothing.
- Existing repositories keep their `AGENTS.md` and `CLAUDE.md` untouched; a root
  one is still not reported as loose Markdown, and still cannot be written by a
  proposal. An old `context-governance:bootstrap` block is recognised only on the
  Agent integrations page, to view, update or remove. An untracked `AGENTS.md` or
  `CLAUDE.md` is no longer counted as CGU's by “Commit CGU changes”.

### Setup records itself, and what could not be recorded is recoverable

**What went wrong.** A fresh test repository showed 12 uncommitted files after
setup, filing a candidate and granting authority. Setup had run in a directory
that was not yet a Git repository; `git init` followed 30 seconds later. Setup's
recording was best-effort, so it wrote all 13 scaffolding files, warned, and
committed nothing — and nothing ever came back for them. The two actions that
followed correctly committed only their own paths; filing picked up
`INDEX.md`, leaving the other 12.

**Now.**

- Setup checks, before writing anything, that it can record itself. A directory
  that is not a Git repository gets one; Git without an identity is refused with
  the fix. Setup then commits its scaffolding like any action.
- A context root inside another Git repository is refused by setup and on open.
  Git reports status relative to the top of the repository, CGU relative to the
  context root, so nested, conflict detection would have seen nothing and an
  incomplete commit would have looked complete.
- A recording that cannot finish — a commit that fails and cannot be fully
  undone, a commit that leaves paths behind, a setup commit that fails — notes
  exactly the paths involved.
- **Commit CGU changes**, in the top bar beside the branch status, previews and,
  after explicit confirmation, commits exactly those paths plus any setup
  scaffolding never committed, and nothing else: unrelated work stays exactly as
  it was, staged or not. It says plainly when there is nothing to commit; if Git
  fails again, nothing is committed and the same changes stay listed. It
  replaces the generic `/api/commit` endpoint, and **Retry recording this
  change** now opens it. It is recovery only; every action still records itself.
- Actions refuse, before writing, in a directory that is not a Git repository,
  instead of writing unrecorded changes with a warning.

### Console

- **File-first previews.** Every preview lists one row per file — create, modify,
  move or delete, the path, and what it does — collapsed until opened, with
  **Expand all** and **Collapse all**. Rows are keyboard-operable buttons with
  `aria-expanded`. The recorded result, proposal reviews and Commit CGU changes
  use the same list; the full Git diff stays one click away.
- **View context** opens the current `AGENT-CONTEXT.md` in the reader, read-only.
  **Rebuild index** is now **Rebuild context**.
- **Scope fields** show an instruction, not an example value, and submit nothing
  unless something is typed.
- The reader no longer shows a line that is wholly an HTML comment, as no
  Markdown renderer does; `AGENT-CONTEXT.md` marks its generated region that way.

### Agent Proposals

Proposals are now named for what they are: an explicit handoff from an agent to
a person. The sidebar item is **Agent Proposals** and the page **Agent
proposals**: "Review changes proposed by agents. Nothing here is context or
takes effect until you review and approve it." A summary names who is asking
("Review 3 changes proposed by Claude." / "… by 2 agents."), cards are grouped
by agent when more than one has proposals waiting, and every card says who
proposed it. The empty state reads "No agent proposals waiting for review." The
generated `AGENTS.md`, `CLAUDE.md` and `PROPOSALS.md` describe the same handoff.

Nothing about the workflow is weaker: CGU computes the actual change, stale
proposals are blocked, changes to governing context need `change governing
context`, protected files cannot be proposed, and every decision is recorded as
a scoped commit with its audit record.

### Configuration

`.context-governance/config.json` is `{"version": 5, "project_name": …}`. Folder
names, the index path, the bootstrap files and the proposal inbox are fixed
rather than configurable. Any other config — an earlier version, or extra keys —
is refused on open and on setup with a message saying the repository is not a
supported context repository — versions 3 and 4 included, the earlier drafts
that generated `INDEX.md` and `CONTEXT.md`. Nothing is migrated.

The one ignore rule the utility needs lives in `.context-governance/.gitignore`,
so the repository root holds nothing but context and bootstrap files.

### Removed

- The classification taxonomy: `research/`, `investigation`, `working/`,
  `decisions/`, `implementation/`, `specification`, `authority_candidate`, and
  the `classification` front-matter field.
- The `deprecated` and `archived` statuses, and changing lifecycle status by
  editing details.
- Describing (adopting) existing Markdown, the "Not described by the index"
  inventory and index section, and moving loose files into the model.
- The `governs`, `depends_on`, `related_to` and `tags` fields, their editing
  controls, and the index's relationship map.
- Operation-specific confirmation phrases (`grant authority`,
  `change governing content`).
- Granting authority in place, the optional "also move" on grant, reclassifying
  on grant, archiving on withdrawal, choosing an intake destination path, and
  superseding at intake.
- Configurable folders, index path, bootstrap files, proposals and originals
  directories, and excluded directories.

### Also

- Setup no longer says "Commit them when you are ready". Setup has recorded
  itself since v0.2.3.
- Generated Python bytecode is no longer tracked. A `.gitignore` excludes
  `__pycache__/` and `*.pyc`, so running the tests leaves no churn.
- PDF support is detected without importing `pypdf`, and the code is free of
  pyflakes warnings.
- The package's `cgu` launcher keeps its executable bit.

### Tests

```bash
python3 -m tests.lifecycle   # new: the model end to end
python3 -m tests.smoke       # rewritten for the model
python3 -m tests.governance  # rewritten: editing details, and retiring
python3 -m tests.durability  # unchanged contract, candidates and moves
python3 -m tests.atomicity   # unchanged contract
python3 -m tests.encoding    # unchanged contract
python3 -m tests.ui          # one suite for the one page
```

## v0.2.3 — 2026-09-08

One boundary, drawn properly: **you govern the documents, the utility governs
Git.** No change to the governance model, the confirmations, the preview step,
or the atomicity guarantees.

### A governance action now finishes by itself

**What went wrong.** An authority promotion wrote its document, regenerated
`INDEX.md`, and stopped. Three files it owned were left uncommitted. Later
actions committed only their own paths, so the promotion's changes stayed
stranded behind them — and the person who had approved that promotion was left
holding a Git problem nobody had told them they were being given.

**Why.** Applying and recording were two steps, and only the first belonged to
the utility. The UI marked the action "Written", then offered a **Commit these
files** button as a separate task. Miss it, and the repository was left in a
state only Git knowledge could get out of.

**Now.** One action is one whole thing. Every governance action — intake,
accepting or rejecting a proposal, granting or withdrawing authority, editing
governance metadata, supersession, adoption, bootstrap, reindex, and attaching
the utility itself — validates, previews, writes atomically, regenerates the
index, re-checks the repository, and commits, before it reports success. The
manual commit step is gone from the normal flow.

### The commit is scoped, and never sweeps up your work

A commit contains the paths that action wrote, and nothing else. Unrelated
changes in the working tree — a half-finished edit, an untracked scratch file —
are neither committed nor disturbed.

Where that isolation is impossible, the action refuses **before writing
anything**: if a path it needs already carries uncommitted changes, committing
it would either record work nobody reviewed or destroy it. The refusal names the
path and says what to do. Untracked files are not a conflict; describing a file
Git has never seen is the ordinary case.

Three conditions are therefore checked before the first byte: that no path the
action needs is already dirty, that Git has an identity to commit with, and that
no path the action writes is one the ignore rules would keep out of Git. All are
knowable in advance, and finding them out afterwards would mean undoing a change
that was otherwise perfectly good.

### An action that cannot be recorded did not happen

If the commit fails after the writes have landed, the writes are rolled back
from the apply journal and the failure is reported as a failure. The repository
is byte-for-byte as it was, including the index. Nothing is reported as
complete that is not complete.

The one case that cannot be undone — the commit ran but Git still reports the
action's own paths as uncommitted — is handed over as exactly one recoverable
state, with the paths and the commit message, and one **Retry recording this
change** button. `/api/commit` still exists for precisely that retry; nothing in
the ordinary path through the UI calls it.

### Documentation

"Previewed, applied, shown as a Git diff, and only then committed, by you" is
gone. The utility uses Git for local durability, history, diffing and rollback;
you interact with governance actions, not Git mechanics. Git status, diffs and
history remain visible as diagnostics for anyone who wants them. Pushing to a
remote is deliberately still not something this utility does.

### Regression cover

```bash
python3 -m tests.durability
```

A clean repository where every action finishes clean with its own commit; a
repository dirty only in unrelated files, where the action commits its own paths
and leaves the dirt exactly as it was; a conflicting edit to a path the action
needs, refused before any write; a Git with no identity, and a destination the
ignore rules exclude, both refused before any write; an injected commit failure, rolled back and never reported as success;
a half-succeeded recording, handed over as one recoverable state; and the
original defect, that an authority promotion cannot leave CGU-owned changes
behind.

## v0.2.2 — 2026-09-08

Dogfood usability, not new machinery. The governance model, the confirmations,
the preview-then-apply step and the atomicity guarantees are all unchanged.

### Intake finishes when the document is filed

**What went wrong.** After filing a document, going back to Intake still showed
the previous upload, its converted Markdown and its title, as though the
operation were still in flight.

**Why.** The intake workspace was only cleared after the *commit* step. Applying
a plan — the act that puts the document on disk — left the form exactly as it
was, so a finished piece of work looked unfinished.

**Now.** A successful intake apply clears the workspace: the staged upload is
released, the form empties, the conversion notes go, the file chooser resets,
and the steps lock back to step one. The written work stays in the review panel,
so committing it is still the next thing in front of you.

### Knowledge clears the document you were reading

**What went wrong.** Opening a document with **Read** left it expanded below the
list indefinitely, including after navigating away and back.

**Now.** Clicking any navigation item closes the reader, so Knowledge always
opens on the document list. The reader also has its own Close button, and a
document that is open while a change is applied is re-read rather than left
showing text that is no longer on disk.

### Read renders Markdown

**What went wrong.** Read showed raw Markdown source — front-matter fences,
pipe tables, backticks and all.

**Now.** Read renders the document: headings, paragraphs, bold and italic,
lists (nested and ordered), tables with alignment, fenced and inline code, block
quotes, rules, and links. Front matter is lifted out and shown as a metadata
block above the body rather than as source. **View source** is still one click
away.

The renderer is about 400 lines of plain JavaScript in `app/static/markdown.js`.
**No dependency was added** — no framework, no build step, still one HTML file,
one stylesheet and two scripts served from the standard library.

It builds DOM nodes and never assigns `innerHTML`, so no document content can
become markup: raw HTML inside a document is displayed as the characters it is.
Links are clickable only for `http:`, `https:` and `mailto:`; anything else,
`javascript:` included, renders as inert text carrying its target in a tooltip.
Repo-relative links do the same, because the utility does not serve repository
files to the browser.

### Editing governance metadata without granting authority

**What went wrong.** Reclassifying a document, or correcting its scope, could
only be done as a side effect of **Grant authority** — which taught exactly the
wrong lesson, given that classification, status and authority are independent by
design.

**Now.** Every document has an **Edit governance** action covering the
deterministic governance metadata and nothing else:

- classification;
- scope;
- lifecycle status;
- the declared relationships already modelled (`governs`, `depends_on`,
  `supersedes`, `superseded_by`, `related_to`).

`authority` is not an input to it. It is not on the form, it is not read from
the request, and it is written back exactly as it was found. A research note
reclassified as a specification still governs nothing; a document that governs
still governs, and stays listed under **Currently governing** in `INDEX.md`
whatever kind it is and whichever folder it sits in.

The file is never moved. Reclassifying changes what the index calls a document,
not where it lives — the same principle that lets authority be granted in place.

Two refusals keep the boundary honest:

- retiring a document that governs is refused here, and points you at
  withdrawing its authority or recording a supersession;
- an edit that would change nothing is refused rather than written, so the
  `updated` date does not drift.

Editing the metadata of a document that governs today requires typing
`change governing content`, the same phrase as amending governing text.

**Grant authority is unchanged**: authority may be granted in place, moving to
`authoritative/` is still an optional tick box, and `INDEX.md` still lists any
active authoritative document under **Currently governing** regardless of folder
or classification.

### Tests

```bash
python3 -m tests.smoke        # governance rules, end to end
python3 -m tests.atomicity    # all-or-nothing apply
python3 -m tests.encoding     # Unicode across the Git boundary
python3 -m tests.governance   # editing metadata vs. granting authority
python3 -m tests.ui           # the page's own JavaScript (needs Node)
```

`tests/governance.py` and `tests/ui.py` are new.

All three complaints fixed here are browser behaviour, which Python cannot
check. So `tests/ui.py` builds a real repository, captures the exact payloads the
API returns for it, and runs the page's own `app.js` and `markdown.js` against a
small DOM in `tests/domshim.js` — clicking the real buttons, reading the real
elements. Nothing about the front end is re-implemented in the test. Node is
required for it; without Node it says so and skips rather than passing quietly.


## v0.2.1 — 2026-09-08

Two correctness fixes found in first dogfood use. No workflow changes, no new
features: the same preview, the same confirmations, the same commit step.

### Applying a plan is all-or-nothing

**What went wrong.** Filing a document produced *"The repository changed since
this preview was made. Nothing was written"*, yet the Markdown document was on
disk. Re-previewing then saw that orphan and offered to file the document under
a `-2` identity.

**Why.** `apply_plan` wrote a plan's files one at a time with no journal and no
rollback, and the staleness check ran outside any lock. So a failure part-way
through an apply left the repository half-changed, and the *next* attempt
correctly reported a changed repository — a refusal caused by the previous
attempt's debris. Two submissions of one preview could interleave the same way:
one wrote while the other recomputed and refused.

**Now.**

- Every precondition is checked before the first byte is written: each change is
  matched against what is on disk, and a staged original must still exist.
- Each file is written to a temporary file beside its target and moved into
  place, after being copied aside into an apply journal.
- Any failure part-way through is rolled back from that journal **byte for
  byte** — modified files restored, deleted files put back, created files and
  the directories that appeared for them removed.
- One writer at a time per repository. Recomputing the plan, checking it against
  the preview and writing it are one indivisible step, so a second submission of
  a preview cannot slip between the check and the writes. Previews and commits
  take the same lock, so neither ever reads a half-applied tree.
- The UI disables the apply button while a write is in flight.
- Debris from a process killed mid-write is swept when the repository opens.

**What you are told.** A refusal now says *"Nothing was written"* only when that
is literally true. If a rollback itself cannot complete, the message says so
instead, names the paths that could not be restored, and keeps the journal —
which holds the only remaining copy of their previous content.

### Windows: Git output is decoded as UTF-8

**What went wrong.** On Windows, filing a Word document containing ordinary
typography — a curly quote, an em dash — returned HTTP 500 with
`UnicodeDecodeError: 'charmap' codec can't decode byte 0x9d`, followed by
`AttributeError: 'NoneType' object has no attribute 'strip'`. The document had
already been filed correctly; only the Git diff shown afterwards failed.

**Why.** Git output was captured with `text=True`, which decodes using the
platform default — `cp1252` on a Western Windows install. A diff carries file
content, and `"` is `E2 80 9D` in UTF-8; byte `0x9D` does not exist in cp1252.
On Windows that decoding happens on a subprocess reader thread whose exception
is swallowed, so the stream came back as `None` and the real cause surfaced
later as an `AttributeError`.

**Now.** Every Git command is captured as bytes and decoded here, explicitly, as
UTF-8, replacing anything undecodable rather than raising. Neither stream can be
`None`. Commands run with `core.quotepath=false`, and Git's C-style path quoting
is undone as bytes, so non-ASCII filenames read as their names. Unicode
document content, filenames and commit messages round-trip through diff, status,
log and commit.

### A failed description is not a failed write

Everything after a plan is applied — re-validation, the Git diff — only
*describes* what was written. A failure there is now reported as a gap in the
description: the response still succeeds, still lists every file written, and
carries a warning saying the changes were written and that nothing needs
re-applying. The commit step stays available. The UI shows those warnings in the
"Written — review and commit" panel, so a missing diff can never be mistaken for
a reason to apply the plan again.

### Tests

```bash
python3 -m tests.smoke       # governance rules, end to end
python3 -m tests.atomicity   # all-or-nothing apply, in a repo with no commits
python3 -m tests.encoding    # Unicode across the Git boundary, over real HTTP
```

`tests/atomicity.py` and `tests/encoding.py` are new. Every atomicity case runs
in a fresh repository with no initial commit and nothing tracked, which is how
the first defect was found. The encoding cases drive the real HTTP server:
preview, apply, Git diff, commit.

## v0.2 — MVP

First release: intake, agent proposals, authority as a property of a document,
generated `INDEX.md`, preview-then-apply for every change.
