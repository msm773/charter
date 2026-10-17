# Charter

*Agent Context Manager*

**One trusted context for every AI agent on your project.**

AI agents can do remarkable work, but a new session doesn't automatically inherit the decisions, constraints, and lessons from earlier work. Across long-running projects, sessions change, conversations are compacted, and different agents can end up working from different assumptions. Even excellent work can drift away from what the project actually needs.

**Charter helps you keep the project's decisions in the project—not in any one agent session.** It provides a shared source of governing knowledge that you choose, review, and maintain as work evolves.

## Contents

- [Understand Charter](#understand-charter)
- [Get started](#get-started)
- [Work with Charter](#work-with-charter)
- [Help and reference](#help-and-reference)

---

## Understand Charter

### The idea: knowledge that survives sessions

As projects evolve, important knowledge accumulates: requirements, design decisions, architectural constraints, and lessons learned.

Some of that knowledge comes from working directly with AI agents. Some comes from your team—product specifications, development standards, or requirements you've been asked to implement.

Wherever it comes from, the challenge is the same: making sure your agents know which information matters and which decisions are current.

Charter supports a simple approach:

- **Capture what matters.** Add documents yourself or let agents submit proposals as you work.
- **Decide what governs.** Review potential changes and choose which documents become part of your project's governing context.
- **Carry it forward.** Make that context available to agents across sessions, tasks, and tools.

As the project changes, you can revise, replace, or withdraw governing documents without losing the distinction between approved knowledge and work in progress.

The result is a shared foundation for your agents, maintained by the people responsible for the project.

### What Charter provides

- **A local console** to review candidates and governing changes.
- **An Agent Context folder** containing governing Markdown documents and their generated map.
- **Read-only MCP retrieval**, or direct file access for agents that can't use MCP.
- **Command-line tools** for local operations and optional agent proposals.

Through MCP, Charter checks the Agent Context before serving it; direct file reads do not have that validation. Charter detects when the map no longer matches its documents. Where it has a prior local record, the console identifies the change as outside Charter’s workflow; otherwise, it reports the context’s origin as unknown. It can provide context and ask agents to use it, **but cannot guarantee an agent will follow it**.

Charter runs locally with Python 3.9+ and works alongside Git without managing your commits or branches. It requires no hosted service, remote API, embeddings, or AI provider.

> ⚠️ **Pre-release — `2.0.0.dev0`.** Charter isn't public yet; this guide assumes you received its folder directly. Windows has been exercised from source. macOS and Linux are supported in code but aren't yet release-verified on a clean machine.

### The Charter workflow

Imagine you're building a product with several AI agents—one helping with product design, another writing code, and a third testing the application.

As you work, each agent brings a different perspective. Your product agent might propose a new feature, your development agent might identify an architectural constraint, or your testing agent might discover an important edge case worth preserving.

Here's how Charter fits into that process:

1. **Develop the idea.** Work with one or more agents to explore a feature, resolve questions, and reach a decision. Agents suggest changes as **Agent Proposals**: an agent that can run `charter propose` files one itself, in Charter's proposal JSON format, and an agent that can't returns that JSON for you to bring in with **Import agent proposal…**. Your own material doesn't go through Agent Proposals: add it yourself with **Create candidate**.
2. **Review and govern.** Review proposals and accept the ones worth considering. When you're ready, use a **change set** to make candidates govern—each replacing a governing document or governing alongside—or to withdraw one. You decide what becomes authoritative.
3. **Carry the knowledge forward.** Your agents can retrieve the updated governing context. New sessions and other agents can build on those decisions rather than rediscovering them.

And the process continues as your project evolves.

---

## Get started

### Install Charter

You need the Charter folder and **Python 3.9 or later**.

1. **Check Python.**

   Windows:

   ```powershell
   py -3 --version
   ```

   macOS/Linux:

   ```bash
   python3 --version
   ```

   ✅ **Expected result:** `Python 3.9` or later (for example, `Python 3.12.4`). On Windows, prefer `py` to `python`, which may be a Microsoft Store placeholder. If `py` is missing, install Python from [python.org](https://www.python.org/) and use a new terminal.

2. **Open the Charter folder in a terminal.** Keep it somewhere permanent; PATH and host settings will refer to it. On Windows, open the folder containing `charter.py` in File Explorer, then choose **Open in Terminal**. On Windows 10, enter `cmd` in File Explorer's address bar instead.

3. **Make `charter` available on PATH.** From that folder:

   Windows:

   ```powershell
   py charter.py add-to-path
   ```

   macOS/Linux:

   ```bash
   python3 charter.py add-to-path
   ```

   On Windows, expect `Added to your user PATH:` (or `Already on your user PATH:`). On macOS/Linux, Charter changes neither PATH nor any file: it prints an `export PATH=…` line and the file to add it to, `~/.bashrc` for bash or `~/.zshrc` for zsh. For bash on macOS, it names the login file bash reads: `~/.bash_profile`, or your existing `~/.bash_login` or `~/.profile` if you have one and no `~/.bash_profile`. Add the line with a text editor. Agent hosts started from the desktop rather than a terminal may not read that file; on many Linux desktops they get PATH from `~/.profile`, which takes effect only after you log out and back in.

4. **Restart and verify.** Reopen your terminal and any agent hosts (including VS Code, Claude Code, or Codex), then run from any folder:

   ```text
   charter add-to-path --check
   ```

   ✅ **Expected result (Windows):** `New programs run:` followed by your launcher path, such as `C:\Tools\Charter\charter.cmd`. If `nothing:` appears after `New programs run:`, see [Troubleshooting](#troubleshooting).

   ✅ **Expected result (macOS/Linux):** `This shell runs:` followed by your launcher path, such as `/home/you/tools/charter/charter`. Otherwise, the output says what to do next, such as a `chmod +x` command if the launcher isn't executable.

**Optional PDF import:** From the Charter folder on Windows, run:

```powershell
py -m pip install -r requirements.txt
```

On macOS/Linux, use `python3 -m pip install -r requirements.txt`.

Some Linux distributions install Python without pip (`No module named pip`), or refuse installs outside a virtual environment (`externally-managed-environment`, under PEP 668). Then, from the Charter folder, create a virtual environment outside it and start the console with that environment's Python whenever you want PDF import:

```bash
python3 -m venv ~/.venvs/charter
~/.venvs/charter/bin/python -m pip install -r requirements.txt
~/.venvs/charter/bin/python charter.py serve
```

On Debian and Ubuntu, `python3 -m venv` itself needs the `python3-venv` package. Installing it changes the system and needs administrator rights, for example `sudo apt install python3-venv`; other distributions package it differently.

### Create your first Agent Context

You'll create a context, make your first documents govern, then connect an agent.

#### 1. Choose where your context will live

Before choosing the folder, decide how the agent will access it:

- **MCP (recommended):** Your agent retrieves the context through Charter's local read-only server.
- **File access:** Your agent reads the Agent Context folder directly.

**Using MCP (recommended)**

Keep your Agent Context **beside** the project, rather than inside a folder agents can write. For example:

```text
C:\work\my-project\           your project, where agents work
C:\work\my-project-context\   the Agent Context
```

The Agent Context folder doesn't need to exist yet. Its parent folder (`C:\work` in this example) **does**.

With MCP, the agent retrieves governing documents through Charter and doesn't need ordinary filesystem access to the context folder.

**Using file access**

Your agent must be able to **read** the Agent Context folder. You can still keep it beside the project if your host lets you grant access to that folder separately—ideally **read-only**. If the host can only read within the project workspace, you'll need to put the context inside that accessible area.

🔒 **Recommended setup:** MCP **without direct folder access** offers the strongest separation. The agent can retrieve Charter-checked documents but can't accidentally modify the Agent Context with ordinary filesystem tools. If you're using file access instead, make it read-only whenever possible; otherwise, an agent with write permission could edit the context directly.

#### 2. Start the console

Open a terminal and run:

```text
charter serve
```

✅ **Expected result:**

```text
Charter
  Agent Context: (none open)
  open:          http://127.0.0.1:8765
  stop:          Ctrl-C
```

Open the address in your browser. Leave the terminal open while you use the console; press **Ctrl+C** when you're finished.

💡 Agents connected through MCP don't need the console running. Their host starts Charter's read-only server separately.

#### 3. Create the Agent Context

In the console:

1. Enter the path in **Agent Context folder** (or use **Browse…** if offered).
2. Enter a **Project name (required)**.
3. Choose **Create Agent Context**.

That project name becomes the title of the context map your agents read.

#### 4. Add your documents

This is how you add your own material: Agent Proposals are only for what agents submit. In **Authority Candidates**, select **Create candidate**. You can bring in:

- Markdown or plain-text files.
- Word (`.docx`) documents.
- PDFs, if you installed the optional dependency.

At first the page asks only for a file. Once it's converted, one form like **Edit…** takes its place, under **Review Converted Document**: the file's name, kind and size, with **Choose another file**; any notes about the conversion; **Title**; **Scope**, a short routing summary shown in `AGENT-CONTEXT.md`; and **Text**, the converted document for you to check and edit. **Choose another file** replaces the conversion and everything you typed. Leaving the page before filing discards the file and everything typed; nothing is kept.

🔒 **Nothing governs yet.** A candidate is private until you explicitly include it in a confirmed change set.

#### 5. Make your documents govern

On a candidate:

1. Choose **Plan a change set…**. A change set opens with that candidate included and its decision not yet made.
2. For your first document, choose **Govern alongside** from its decision dropdown. Once documents govern, a candidate can instead **Replace** one you then select.
3. Add other candidates to the change set if you want them to govern together.
4. Choose **Preview and apply →** and inspect the changes.
5. To apply them, type **`change governing context`**.

✅ **Success:** Your selected documents appear in the governing set. A valid, clean context can already be served before you add documents.

### Connect your agents

Choose how your agent will read its context:

| Route | Best for | What happens |
| --- | --- | --- |
| **MCP (recommended)** | Claude Code, Codex, and other MCP hosts | The host starts Charter; agents retrieve validated governing documents through four read-only tools |
| **File access** | Hosts that can read the Agent Context folder | Agents read files directly, without Charter observing or validating the read |

The console's **Connect Agents** page has four sections, each opened or closed from its heading: **Connect Agents with MCP (Recommended)**, open, with the host choice, its setup commands, and their Copy buttons; then, closed, **Add Project Instructions (Optional)**, **Test the Connection (Optional)**, and **Connect Agents with File Access**. Sections you open stay open while you move around the console.

**Running Charter from a development checkout or worktree?** Connect Agents then names that checkout's own launcher by its full path—`charter.cmd` on Windows, `charter` elsewhere—in every configuration and command it shows, so PATH can never route an agent to another copy of Charter. An installed release uses the `charter` command that `charter add-to-path` puts on your PATH. On Windows, a checkout path containing spaces or any of `% & | < > ^ "` can't be carried through `cmd /c`, so Connect Agents offers file access only from it.

Use the instructions below, substituting your **own Agent Context path** and chosen server name for the examples. Charter does not change an agent host's configuration for you. MCP is recommended because agents don't need direct filesystem access to the context. Keep direct access read-only when you use the file route.

Optional terminal-based proposals are separate from context retrieval; see [Let agents suggest changes](#let-agents-suggest-changes).

#### Claude Code

Run the setup command **once from your project's folder**. Use the command for your shell below, substituting your actual folder and server name.

**Windows — PowerShell:** (`--` must be quoted)

```powershell
claude mcp add charter-my-project '--' cmd /c charter mcp --context C:\work\my-project-context
```

**Windows — Command Prompt:**

```cmd
claude mcp add charter-my-project -- cmd /c charter mcp --context C:\work\my-project-context
```

**macOS/Linux:**

```bash
claude mcp add charter-my-project -- charter mcp --context /home/you/work/my-project-context
```

On Windows, the host uses `cmd /c` to launch `charter`, which is a Command Prompt launcher.

By default, Claude Code uses **local scope**: this server is available to you **in this project**.

- Use `--scope project` to share the registration through the project's `.mcp.json` (which records this computer's folder path).
- Use `--scope user` to make it available in all your projects.

Then start a **new Claude Code session**.

#### Codex

Codex reads MCP servers from `config.toml` inside the `.codex` folder in your home directory. On Windows, that's:

```text
%USERPROFILE%\.codex\config.toml
```

Create the folder and file if needed. ⚠️ When Windows hides file extensions, File Explorer may save `config.toml.txt` instead; check that the name truly ends in `.toml`.

Add the appropriate table below, substituting your actual folder and server name. Then **quit and reopen Codex**.

**Codex running natively on Windows:**

```toml
[mcp_servers.charter-my-project]
command = "cmd"
args = ["/c", "charter", "mcp", "--context", "C:\\work\\my-project-context"]
```

**macOS/Linux:**

```toml
[mcp_servers.charter-my-project]
command = "charter"
args = ["mcp", "--context", "/home/you/work/my-project-context"]
```

This is Codex's **user configuration**, so the server will be available in every project you open in Codex.

⚠️ Codex running **inside WSL** hasn't been tested with Charter. The Windows configuration above is for **native Windows Codex** only.

#### Other MCP hosts

Many hosts accept an `"mcpServers"` JSON configuration. Use the version for the platform where the host runs.

**Windows:**

```json
{
  "mcpServers": {
    "charter-my-project": {
      "command": "cmd",
      "args": ["/c", "charter", "mcp", "--context", "C:\\work\\my-project-context"]
    }
  }
}
```

**macOS/Linux:**

```json
{
  "mcpServers": {
    "charter-my-project": {
      "command": "charter",
      "args": ["mcp", "--context", "/home/you/work/my-project-context"]
    }
  }
}
```

Adapt the shape to your host's documented configuration; not every host uses this format.

#### Give agents a startup pointer

Some MCP hosts expose Charter's server instructions, which ask the agent to call `get_context` before work. Claude Code does, but not all hosts do. To state the expectation explicitly, put a startup instruction in your **project's** instruction file:

- `CLAUDE.md` for Claude Code.
- `AGENTS.md` for Codex.
- The equivalent project instruction file for other hosts.

Use this startup pointer, replacing the server name if yours differs:

```text
This project's governing context is served by the `charter-my-project` MCP server (Charter).
Before beginning work, call its `get_context` tool, then retrieve the governing documents relevant to your task. Treat only the governing documents it lists as authoritative.
```

⚠️ Keep instruction files in the **project**, never inside the Agent Context folder: extra files in the Agent Context cause MCP refusal. Charter cannot compel an agent to obey instructions.

#### File-based agents (without MCP)

When MCP is unavailable, give the agent **read access** to the Agent Context folder (preferably read-only), including when the folder sits outside the main workspace. Add this instruction to your host's project instructions, adjusting the paths:

```text
This project's governing context is an Agent Context, in this folder:
  C:\work\my-project-context

Before beginning work, read its context map:
  C:\work\my-project-context\AGENT-CONTEXT.md

It lists the governing documents and how to use them. Treat only the governing documents it lists as authoritative. If the Charter MCP tools are available, `get_context` returns the same map.
```

🔒 **Important:** Direct file reads bypass Charter's validation. The agent sees whatever is in the folder. If it can also write there, it can bypass the review workflow.

### Verify your agent retrieved the context

Start a **new agent session** in your project and send:

> Before doing anything else, retrieve this project's Agent Context. Tell me
> the project name it gives, and which of its governing documents apply to
> this task: [describe a small task]. If you cannot retrieve it, say so; do
> not guess.

✅ **Success:** The agent names your project and the relevant documents from its map. By default, the map also asks agents to use `Context check: AGENT-CONTEXT read.` as the first line of a short update after reading the map and relevant documents.

Your host might ask you to allow the tool first. If the agent can't name the project, it **hasn't demonstrated retrieval yet**. Connection by itself isn't proof.

**What counts as success?** Configuration means you've registered the server; connection means the host can start it (`claude mcp list` can confirm that for Claude Code). **Retrieval** is the real check: the agent names your project and documents from the map. That still doesn't guarantee it follows them.

---

## Work with Charter

### Read the console

The console carries no information icons or hover panels; this section explains what it shows.

**Opening.** **Open Agent Context…**, at the top right, and the **Charter** name at the top left both lead to the Open or Create Agent Context view, which lists the Agent Contexts opened on this computer under **Recent**. An **Agent Context** is a dedicated folder agents read: `AGENT-CONTEXT.md`, `.agent-context.json`, and the governing documents in `authoritative/`. It may sit inside a project or its own Git repository; nothing else belongs in it. **Open Agent Context** checks the folder and shows whether agents can be served; it writes nothing in the folder, except that an interrupted Charter write is rolled back first. **Create Agent Context** makes a new, empty one in an empty folder. To start from governing documents you already have, put them in `authoritative/` and open the folder: **Rebuild Agent Context…** generates the rest. Neither action runs Git or creates agent instruction files such as `AGENTS.md` or `CLAUDE.md`.

**What each status means.** A status label follows the title of the thing it describes. Green, amber, and red only reinforce the words; every label says what it means.

| Status | Where | Meaning | What to do |
| --- | --- | --- | --- |
| **Agent context ready** | Top bar (and **Agents: Ready** in **CURRENT CONTEXT**) | The folder is valid and clean, so MCP and file-reading agents receive its governing documents. | Nothing. |
| **Agent context unavailable** | Top bar (and **Agents: Unavailable**) | The folder is invalid, incomplete, or holds stray files, so MCP refuses it. | Follow the status above every view: it names the problem and the next safe step, such as correcting a document, removing a stray file, or **Rebuild Agent Context…**. |
| **No Agent Context open** | Top bar | Nothing is open in the console. | Choose **Open Agent Context…**. |
| **Map current** | Context Map, in **Governing Context** | `AGENT-CONTEXT.md` and `.agent-context.json` are exactly what Charter generates from the governing documents and settings. | Nothing. |
| **Map out of date** | Context Map | The map or metadata is missing, unreadable, or not what Charter generates—for example, after a document was edited outside Charter. | Check the governing documents are what you intend, then use **Rebuild Agent Context…**. |
| **Map not checked** | Context Map | A governing document has a problem, so the map can't be compared yet. | Correct the document named in the status above every view; the map is then checked again. |
| **Origin unknown** | Context Map | The files are valid, but this computer has no record of how this version was created or changed—for example, a copied or cloned folder. Nothing needs repair. |
| **Changed outside Charter** | Status above every view | The folder differs from what Charter last saw here. A valid change remains usable context; mark it as seen when you've checked it. |
| **Stale** | Agent Proposal card | Its target changed after the agent read it, so it can't be accepted as written; reject it, or ask the agent to propose again. |
| **active** / **unreadable** | Change Sets | An active draft is work in progress. An unreadable record is a private file Charter can't read; it is listed so you can delete it. |
| **structurally valid** / **waiting for required candidates or decisions** / **blocked** | Change-set editor | Whether the plan can be previewed, still needs a decision, or has a problem to correct first. |

**Governing Context** lists the documents currently governing the selected Agent Context, after its **Context Map**: Charter generates `AGENT-CONTEXT.md`, the agents' entry point, and `.agent-context.json`, its integrity record, from the governing documents and settings. The map is a routing aid, not a governing document, and is never edited by hand. **Rebuild Agent Context…** regenerates both after documents were changed with other tools—an edit, a merge, a recovery. It is offered only when the governing documents are valid and nothing else is in the folder, and it never changes a governing document.

**Governing document, candidate, archive.** A governing document is in `authoritative/`, listed by the map; agents read it as current context, within its scope. An authority candidate is kept in private local state on this computer; agents never see it, and each card's source label—**Proposed by:** and the agent's name (or **Agent Proposal** when none was given), **Created by person**, **Revision**, or **Withdrawn governing document**—follows its title. Replaced and retired documents are archived in private local state for history; the console doesn't list them.

**Settings.** The project name and agent guidance are recorded in `.agent-context.json` and written into `AGENT-CONTEXT.md`. Agent guidance is advisory: a governing document's stricter rule always applies. Changing a setting is previewed first and changes no governing document; the map's other wording is generated and can't be edited.

### Manage governing documents

A document governs only when **all three** conditions hold:

1. It lives in `authoritative/`.
2. Its metadata marks it **authoritative** and **active**.
3. The map and metadata record it.

Documents brought into Charter for possible approval are **authority candidates**, kept privately until you include them in a confirmed change set. Archived documents, stray files, and invalid governing documents are not candidates just because they are outside the governing set. Archived documents stay in private state; the console doesn't show an archive.

Here's the basic lifecycle:

```text
Create candidate / Revise / Edit / accepted create or amend proposal
    → private authority candidate (new or updated)

Accepted retire proposal / Retire candidate → archived

Change set → each candidate governs alongside the others,
             or replaces a governing document you select
             (the previous document is archived privately);
             a governing document can be withdrawn to candidate status;
             every other governing document is retained
```

A few details are worth understanding:

- **Candidate actions stay private.** **Create candidate**, **Revise…**, **Edit…**, **Retire…**, and accepted proposals can create, update, or retire private candidates after preview and confirmation. Rejecting a proposal records the rejection and its reason; it does not change a candidate.
- **Governing changes always use change sets.** There's no separate grant, replace, or withdraw action. **Plan a change set…** on a candidate starts a change set that includes it, with its decision not yet made; **Withdraw in a change set…** on a governing document starts one that withdraws it. Charter doesn't decide for you. Add related candidates and withdrawals before previewing.
- **Revision doesn't edit a governing document in place.** **Revise…** creates a candidate prefilled with that document's title, scope, and text. Revise is how you write a revision, not a change-set decision: in the change set, the revision candidate **Replaces** a document like any other candidate. Its original document is listed first among the documents it could replace, labelled, **but isn't automatically selected**.
- **Changes are previewed before they are applied.** You can inspect the files, private records, and diffs affected by candidate or governing changes before confirming them. Planning can save change-set drafts and rationale before the apply preview. Private candidate changes use ordinary confirmation; governing change sets require **`change governing context`**. Dates in generated documents reflect the application day, even if a preview stays open past midnight.
- **Imported content is normalized.** **Create Candidate** accepts Markdown, text, Word (`.docx`), and optionally PDF. For Markdown and text, existing front matter is removed; valid one-line `title` and `scope` values become editable suggestions. Identity, authority, status, dates, source, and supersession **aren't carried over**. Charter refuses candidate text that starts with its own front-matter block.
- **Writes are transactional.** Charter writes private state and Agent Context changes as one transaction. If it or the computer stops mid-write, reopening the context rolls the incomplete write back.
- **Scope helps agents choose documents.** A document's short scope appears alongside its title in `AGENT-CONTEXT.md`. When a candidate replaces a document, the change set displays the candidate's scope beside the previous document's. A blank candidate scope inherits the previous scope.

**What if you edit a governing file directly?** That's allowed, but it leaves the map and metadata out of date, so MCP refuses to serve the folder. First correct any problems in the documents themselves. Then use **Rebuild Agent Context…** to preview and regenerate the map and metadata. If metadata was lost, Rebuild offers settings last known on this computer, or defaults if none are known. Where Charter has a prior local record of this context, the console marks changes made outside its workflow until you acknowledge them; for a new or moved copy without that history, the origin is unknown.

#### Change sets and advisory review

A **change set** is how Charter handles any governing change, whether one document or several.

A change set is built from the candidates you include. For each candidate, you choose exactly one decision:

- **Replace**: it replaces one governing document you select, at that document's path.
- **Govern alongside**: it governs alongside the others, at its own new path.

A change set can also **withdraw** governing documents; a withdrawal uses no candidate. Every governing document that no candidate replaces and no withdrawal names is **retained**, unchanged, without a separate decision; Build Change Set doesn't list them, and Preview and Apply shows every one. Each candidate is a compact row: its title, one decision dropdown that starts unselected, a target dropdown that appears only after **Replace**, and a one-line scope, with **View details** for the full candidate and its scope comparison. **Discard draft** asks once, then discards the private draft and returns you to Change Sets; its record stays private and the Change Sets view doesn't list it. Charter never guesses at a decision or target.

Before applying, **Preview and Apply** shows, in order: anything that blocks applying or bears on your decision; **Authority Effects**, each changed governing document by title with its effect, and for a replacement its current, candidate and resulting scope; **Retained Governing Documents (N)**, collapsed; and every changed file with its diff and **Read**, including the regenerated map. It checks the resulting structure and validity. One typed confirmation applies the changes together; failures roll back. The result is an **immutable private receipt**, shown when the change set is applied; Charter keeps it privately, but the Change Sets view lists only active drafts (and any record it cannot read). The receipt leads with **Change set applied** and a summary such as `3 documents updated · 4 retained`, lists each changed document by title with its outcome, keeps paths, archive locations, the retained documents, and the full technical summary behind disclosures, and says separately whether an advisory report was attached and whether a review prompt was copied or a packet exported.

**Change sets recorded by an earlier Charter build** declared an outcome for every governing document, including **retain** and **revise**. Applied and abandoned ones are kept exactly as recorded. An active one can be viewed, abandoned, or deleted, but must be converted before it can be refreshed, reviewed, previewed, or applied: **Convert to current form…** lists every change first—each revise becomes a replace of the same document by the same candidate, each replace stays as it is, and each retain is removed, leaving that document retained—and converts only when you confirm. Converting changes no governing context; attached reports become stale.

Change-set drafts pin the exact candidates and documents they refer to, so a draft becomes **stale** if any of those inputs change. **Edit details…** on a planned candidate edits it and returns you to the draft to refresh it.

**Want an agent's opinion before applying?** Charter can prepare **vendor-neutral advisory review material** for an agent you choose:

- A prompt you can copy, or—when too large for a practical single message—a review packet you save **outside every Agent Context**.
- The material includes the documents and candidates under review, their hashes, and a report format.
- Charter **adds** no private state, local paths, or Git commit information of its own, and contacts **no service**. The documents and candidates under review are included exactly as they read.
- In **Agent Review**, choose **Add a review** (then **Add another review**) for each agent's response: its **Reviewing agent** and text save automatically. Only a structurally valid report counts as an attached advisory report; other text stays saved, with feedback on what's wrong. Charter checks a report's **form, fingerprints, coverage, paths, and quotations**, but **not its conclusions**. A report never chooses an outcome for you.

### Let agents suggest changes

When an agent can run Charter, it submits a proposal using:

```text
charter propose --context .
```

Run from the Agent Context folder, this command takes **one JSON object on standard input** and returns **one JSON result**.

- The proposal is **private**, not governing context.
- It can **create a candidate**, **amend an existing candidate**, **propose a revision to a governing document**, or **retire a candidate**. Amending a governing document creates a private revision candidate; the governing original stays unchanged.
- Proposed bodies must be **Markdown text**. Charter refuses a body that begins with front matter so the agent can correct it.
- In **Agent Proposals**, each compact card leads with the title of the document it concerns—for a new document, the title the agent gave or else its first heading—then one line such as **Submitted by:** Claude · **Received:** 1 min ago, and a one-line **Purpose**. **Review proposal…** expands that card in place: the full purpose, and each file accepting would write, with **Read** to see the candidate as it would be. **Accept as candidate** then accepts it in one step, and the console says only **Proposal accepted.** To turn a proposal down without reviewing it, choose **Reject proposal** on its card: a **Reason (optional)** field appears in place, and you can reject with or without one. A reason you give is kept privately with the rejection. **Reject proposal** in an expanded review works the same way. **Close review**, or leaving Agent Proposals, folds it away again. An agent's expected context impact is kept privately with its proposal as advisory review material; it isn't shown on the review screen.
- Accepting a create or amend proposal creates or updates a private candidate. Accepting a retire proposal archives the targeted candidate instead. **A separate change set** is required to change governing context.
- If the agent couldn't run Charter, use **Import agent proposal…** as the fallback: paste the proposal JSON it returned into **Import Agent Proposal** and choose **Check proposal**. If it passes, **Import** beside it becomes available; if not, a short error says why. Any edit to the JSON needs a fresh check before **Import**. **Cancel** clears and closes the panel. This is only for an agent's proposal; to add your own material, use **Create candidate**.

For agents that can run terminal commands, `charter` must be on their PATH and they must have permission to write Charter's private state. An agent that cannot run Charter may instead return the proposal JSON; paste it into **Agent Proposals → Import agent proposal…**.

### Work alongside Git

**You own the Git workflow.** Charter never initializes repositories or stages, commits, branches, switches, merges, rebases, fetches, pulls, or pushes.

When the Agent Context sits inside a Git checkout, Charter can **read Git information limited to that context folder**:

- When the Agent Context is in a Git checkout, the sidebar shows its current branch and the number of context files Git reports as changed. It doesn't list the files.
- **`charter compare`**, in a terminal, compares your current Agent Context with that folder at a branch, tag, or commit you name. It prepares **advisory review material** about differences since that point. The console doesn't offer this comparison.

```text
charter compare --context . --base main
```

By default it prints a summary: each governing document added, changed, or removed, whether the project name or agent guidance changed, and what review material is available. Add `--prompt` to print only the review prompt, ready to copy, when it fits one message. Past that limit, add `--packet <file or folder>` to save one review packet outside every Agent Context. If that folder is inside a Git repository, Charter warns you and saves nothing unless you also add `--accept-git-warning`. `--json` prints the result as one JSON object.

The review material identifies the base only by its context fingerprint. Charter adds no base name, commit, branch, local path, or private state of its own, and refuses to prepare material whose own wording or metadata would; the documents are included exactly as they read, so a document that mentions `main` is no obstacle to `--base main`.

The comparison uses **read-only Git commands** limited to the Agent Context and **never fetches**. It writes nothing except a packet you ask for, and creates no private state. The result is review input—not authority, merge approval, or a new current change set.

---

## Help and reference

### Troubleshooting

- **`charter` not found:** Open a new terminal and restart your agent host after PATH changes. From the Charter folder, run `py charter.py add-to-path --check` on Windows or `python3 charter.py add-to-path --check` on macOS/Linux. You can run local commands there without PATH as `py charter.py serve` or `python3 charter.py serve`, but hosts launching `charter` still need PATH configured.
- **`Permission denied` running `charter` (macOS/Linux):** The launcher has lost its executable mode, for example after unpacking the release with a tool that drops file permissions. From the Charter folder, `python3 charter.py add-to-path --check` prints the `chmod +x` command that fixes it.
- **Port 8765 occupied:** Run `charter serve --port 8766` and open `http://127.0.0.1:8766`.
- **MCP refuses the context:** Run `charter check --context <folder>`. After intentional direct edits, review and use **Rebuild Agent Context…**. If an unexpected file or folder (such as `CLAUDE.md`, notes, or an empty subfolder under `authoritative/`) is inside the Agent Context, move it out; Charter won't move or delete it.
- **Agent can't connect:** Run `charter mcp --context <folder> --check`. This diagnoses the folder and launcher, **not** the host configuration. Restart the host after PATH changes and start a new session after MCP configuration changes.

**Windows Claude Code / VS Code edge case:** If `claude mcp list` shows a connection but VS Code has no Charter tools, local-scope registration may depend on the exact project path spelling (including `C:` versus `c:`). In Command Prompt, `cd /d c:\path\to\project` using the spelling shown by VS Code, rerun the [Claude Code Command Prompt registration](#claude-code), and start a new conversation. Keep local scope for this workaround.

### Access and trust

Charter controls the context it serves and changes performed through its own workflow. **It cannot override the permissions your agent host gives an agent.** Keep these boundaries in mind:

- 🔒 **MCP reads are checked.** An agent receives only the map and governing documents. Before every retrieval, Charter checks the folder and refuses it when invalid, unclean, or mid-change. MCP exposes **no write tools**.
- **Direct file reads bypass Charter's checks.** An agent with file access reads what's present; Charter neither observes nor validates that read.
- **Private work stays out of agent-facing Charter interfaces.** Candidates, archived documents, Agent Proposals, change-set drafts and receipts, review material, and MCP activity live in Charter's private local state—not the Agent Context.
- ⚠️ **Host permissions still matter.** If a host allows an agent to read or write files, run commands, or reach the local console under your account, that agent may reach private state or edit the context directly. Charter can't stop those actions. Use the host's permissions or sandbox, and keep the context outside writable agent folders.
- **Valid doesn't mean approved.** Integrity checks establish that the folder's files agree with each other; they don't prove who wrote them. Charter changes receive your preview and confirmation. A valid direct edit also governs for that checkout. If Charter has a prior local record, the console identifies an outside change until you acknowledge it; otherwise, the content's origin is unknown.
- **Instructions aren't enforcement.** Charter asks agents to retrieve and follow the map, but can't compel them. Check what each agent says it read.

### Technical reference

#### The Agent Context folder

A typical folder looks like this:

```text
my-project-context/
├─ AGENT-CONTEXT.md       the generated map; the agents' entry point
├─ .agent-context.json    project name, agent guidance, and integrity hashes
└─ authoritative/        governing documents, one Markdown file each
```

**Nothing else belongs here.** These tooling files are tolerated:

- `.git` at the root.
- `.gitignore`, `.gitattributes`, `.DS_Store`, `Thumbs.db`, and `desktop.ini` anywhere.

Subfolders under `authoritative/` are allowed when they contain valid governing documents or only tolerated tooling files. Unexpected files or folders are strays, including empty subfolders under `authoritative/`. **MCP refuses to serve the Agent Context while a stray is present.**

A folder is **valid** when its map, metadata, and governing documents match exactly. That's a consistency check, **not proof of approval or authorship**. Integrity hashes use LF-normalized text, so differences in checkout line endings don't create a different context.

You can keep the folder in a Git repository, synced folder, or neither. If it's in Git, each checkout's valid Agent Context is the context for **that checkout**. An agent pointed at a feature-branch folder retrieves that branch's context.

#### Private state

Anything that **isn't governing context** remains outside the Agent Context in local, account-restricted private state:

| Platform | Location |
| --- | --- |
| Windows | `%LOCALAPPDATA%\Charter` |
| macOS | `~/Library/Application Support/Charter` |
| Linux | `~/.local/state/charter` |

The operating system determines this location; there isn't an environment variable or setting that moves it.

For each Agent Context, its `contexts/<key>/` private state contains:

- Authority candidates and archived documents. A candidate created from a file records the file's name and a short SHA-256 fingerprint, not a copy of the file.
- Agent Proposals.
- Change-set drafts and receipts.
- Private MCP diagnostic activity.
- Staging and locks.

🔒 This material isn't exposed through Charter's agent-facing interfaces. **But account-level access matters:** programs running as you—including agents granted such access—can still reach it. See [Access and trust](#access-and-trust).

Private state is tied to the Agent Context folder's **location on this computer**. A copied, moved, or cloned folder starts without that private history. Losing private state means losing local receipts and unapproved work, **not the governing context**.

#### The MCP server

Your agent host starts Charter as a local **stdio MCP server**:

```text
charter mcp --context <agent-context-folder>
```

It exposes **four read-only tools**:

- `get_context`
- `list_governing_documents`
- `get_document`
- `get_document_section`

MCP exposes no write tools and returns no private state. Charter validates the
folder **before every retrieval**; if it is invalid, unclean, or has an
interrupted write, the request is refused with one of **eight fixed reason
codes**.

Charter retains a bounded record of MCP diagnostic activity **privately**. It isn't available through MCP, and the console has no activity feed. A recorded retrieval means the server answered a request—it doesn't identify which agent requested it or establish that the agent followed the material.

#### Commands

Here's the command-line reference:

```text
charter serve [<agent-context-folder>] [--port 8765]
charter check --context <folder>
charter mcp --context <folder> [--check]
charter compare --context <folder> --base <revision> [--prompt | --packet <destination> [--accept-git-warning]] [--json]
charter propose --context .
charter add-to-path [--check]
```

- **`charter serve`** — Runs the local console.
- **`charter check`** — Reports whether a context folder is valid and served. Makes no changes or private state; exits **0** if agents are served, **1** otherwise.
- **`charter mcp`** — Runs the read-only stdio MCP server; `--check` provides diagnostics.
- **`charter compare`** — Compares the Agent Context with its folder at a Git base you name and prepares advisory review material. Reads Git only; exits **0** when a comparison was made, **1** when it couldn't be made or the requested material couldn't be produced, **2** for an unusable command line.
- **`charter propose`** — Submits one Agent Proposal as JSON on standard input.
- **`charter add-to-path`** — On Windows, adds `charter` to your user PATH; `--check` reports what a new program would run. On macOS/Linux, changes nothing: it prints the `export` line to add and the shell startup file to add it to; `--check` reports `This shell runs:` using the current shell's PATH, and says what to do if that isn't this copy. On macOS/Linux, both exit **0** only when this shell already runs this copy as `charter`, and **1** otherwise.

You can also run these commands **from the Charter folder without PATH** using `py charter.py …` on Windows or `python3 charter.py …` on macOS/Linux.

### Verifying a build

These developer tests live in `tests/`, **outside the release**, and run from the Charter source folder.

- **Individual suites:** For example, `py -m tests.authority` on Windows or
  `python3 -m tests.authority` on macOS/Linux.
- **UI suite:** `py -m tests.ui` on Windows (or `python3 -m tests.ui` on
  macOS/Linux) requires Node to run the page's own JavaScript.
- **Package inspection:** `py -m tests.package inspect` on Windows (or
  `python3 -m tests.package inspect` on macOS/Linux) builds the release and
  verification bundle in a temporary folder, then checks the release archive
  **without running the suites**.
- **Full packaged verification:** `py -m tests.package` on Windows (or
  `python3 -m tests.package` on macOS/Linux) also runs all suites against the
  **extracted release**.

### License

Charter is released under the **Apache License, Version 2.0**. Copyright 2026 Mike Meyers. The full license text is in `LICENSE`, included in every release.
