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
- **MCP**: read-only retrieval, and Agent Proposals filed for your review with `submit_proposal`; for an agent that can run commands but can't use MCP, the same checked retrieval through `charter read`; or direct file access.
- **Command-line tools** for local operations and optional agent proposals.

Through MCP and `charter read`, Charter checks the Agent Context before serving it; direct file reads do not have that validation. Charter detects when the map no longer matches its documents. Where it has a prior local record, the console identifies the change as outside Charter’s workflow; otherwise, it reports the context’s origin as unknown. It can provide context and ask agents to use it, **but cannot guarantee an agent will follow it**.

Charter runs locally with Python 3.9+ and works alongside Git without managing your commits or branches. It requires no hosted service, remote API, embeddings, or AI provider.

> ⚠️ **Pre-release — `2.0.0.dev0`.** Charter isn't public yet; this guide assumes you received its release ZIP directly.

### The Charter workflow

Imagine you're building a product with several AI agents—one helping with product design, another writing code, and a third testing the application.

As you work, each agent brings a different perspective. Your product agent might propose a new feature, your development agent might identify an architectural constraint, or your testing agent might discover an important edge case worth preserving.

Here's how Charter fits into that process:

1. **Develop the idea.** Work with one or more agents to explore a feature, resolve questions, and reach a decision. Agents suggest changes as **Agent Proposals**: an agent that can run `charter propose` files one itself, in Charter's proposal JSON format, and an agent that can't returns that JSON for you to bring in with **Import agent proposals…**. Your own material doesn't go through Agent Proposals: add it yourself with **Create candidate**.
2. **Review and govern.** Review proposals and accept the ones worth considering. When you're ready, use a **change set** to make candidates govern—each replacing a governing document or governing alongside—or to withdraw one. You decide what becomes authoritative.
3. **Carry the knowledge forward.** Your agents can retrieve the updated governing context. New sessions and other agents can build on those decisions rather than rediscovering them.

And the process continues as your project evolves.

---

## Get started

- [Install Charter](#install-charter)
- [Create your first Agent Context](#create-your-first-agent-context)
- [Connect your agents](#connect-your-agents)
- [Verify your agent retrieved the context](#verify-your-agent-retrieved-the-context)

### Install Charter

**You need:** the Charter release ZIP (`charter-<version>.zip`) and **Python 3.9 or later**.

1. **Unpack the release into one stable folder** that you keep, such as `C:\Tools\Charter`. Agent hosts start Charter by its full path, so keep this folder where it is: you'll [update Charter](#update-charter) inside it.

   Windows (PowerShell):

   ```powershell
   Expand-Archive charter-2.0.0.dev0.zip -DestinationPath C:\Tools
   Rename-Item C:\Tools\charter-2.0.0.dev0 Charter
   ```

   In File Explorer you can instead right-click the ZIP, choose **Extract All…**, set the destination folder yourself, and rename the folder it creates.

   macOS/Linux:

   ```bash
   unzip charter-2.0.0.dev0.zip -d ~/tools
   mv ~/tools/charter-2.0.0.dev0 ~/tools/charter
   ```

   In the macOS Finder you can instead double-click the ZIP: Archive Utility unpacks it beside the ZIP, as a folder named `charter-<version>`. Move that folder to where you'll keep it, such as a `tools` folder in your home folder, and rename it `charter`. Archive Utility keeps the launchers' executable mode, and a ZIP your browser marked as downloaded still runs from Terminal.

   The ZIP holds one folder, `charter-<version>`; renaming it keeps the folder's path the same across updates. That folder, which contains `charter.py`, is **the Charter folder** in the rest of this guide. If your unpacking tool added an extra folder level, use the inner folder that contains `charter.py`.

2. **Check Python.**

   Windows:

   ```powershell
   py -3 --version
   ```

   macOS/Linux:

   ```bash
   python3 --version
   ```

   ✅ **Expected result:** `Python 3.9` or later (for example, `Python 3.12.4`). On Windows, prefer `py` to `python`, which may be a Microsoft Store placeholder. If `py` is missing, install Python from [python.org](https://www.python.org/) and use a new terminal.

3. **Open the Charter folder in a terminal.** On Windows, open the folder containing `charter.py` in File Explorer, then choose **Open in Terminal**. On Windows 10, enter `cmd` in File Explorer's address bar instead.

4. **Make `charter` available on PATH**, so you can run it in a terminal (agent hosts don't need this). From that folder:

   Windows:

   ```powershell
   py charter.py add-to-path
   ```

   macOS/Linux:

   ```bash
   python3 charter.py add-to-path
   ```

   On Windows, expect `Added to your user PATH:` (or `Already on your user PATH:`). On macOS/Linux, Charter changes neither PATH nor any file: it prints an `export PATH=…` line and the file to add it to, `~/.bashrc` for bash or `~/.zshrc` for zsh. For bash on macOS, it names the login file bash reads: `~/.bash_profile`, or your existing `~/.bash_login` or `~/.profile` if you have one and no `~/.bash_profile`. Add the line with a text editor. Agent hosts started from the desktop rather than a terminal may not read that file; on many Linux desktops they get PATH from `~/.profile`, which takes effect only after you log out and back in.

5. **Restart and verify.** Reopen your terminal and any agent hosts (including VS Code, Claude Code, or Codex), then check **this copy** of Charter by its full path, from any folder. Don't use a bare `charter add-to-path --check`: if another copy of Charter comes first on your PATH, that copy answers instead and reports itself as the one that runs.

   Windows (PowerShell), with the Python that runs Charter and this copy's `charter.py`:

   ```powershell
   & C:\Python312\python.exe C:\Tools\Charter\charter.py add-to-path --check
   ```

   macOS/Linux, with this copy's launcher:

   ```bash
   ~/tools/charter/charter add-to-path --check
   ```

   ✅ **Expected result (Windows):** `New programs run:` followed by **this** Charter folder's launcher, such as `C:\Tools\Charter\charter.cmd`, and exit code 0.

   ✅ **Expected result (macOS/Linux):** `This shell runs:` followed by **this** copy's launcher, such as `/home/you/tools/charter/charter`, and exit code 0. Otherwise, the output says what to do next, such as a `chmod +x` command if the launcher isn't executable.

   ⚠️ **If it names another copy of Charter**, an older or different copy comes first on your PATH: a terminal, and an agent that runs `charter propose`, would run that copy.

   - **This copy is on PATH, but another comes first:** the output says "Another `charter` comes first on PATH" and names that copy's folder. Remove that folder from your PATH (Windows: **Settings → System → About → Advanced system settings → Environment Variables**, then edit **Path**). Running `add-to-path` again doesn't change that.
   - **This copy isn't on PATH yet:** on macOS/Linux, `This shell runs:` names the other copy, and the output gives this copy's `add-to-path` command by its full path, such as `/home/you/tools/charter/charter add-to-path`. Run it and add the line it prints: that line puts this copy ahead of the other one. On Windows, the output says to remove the other copy's folder from your PATH, then gives this copy's command by its full paths, for PowerShell, such as `& C:\Python312\python.exe C:\Tools\Charter\charter.py add-to-path`.

   Then reopen the terminal and check again with this copy's full-path check command, as above. If it reports `nothing:`, see [Troubleshooting](#troubleshooting).

**Read an Agent Context from your terminal.** Once `charter` is on your PATH, name an Agent Context by its full path to read and check it:

```powershell
charter C:\work\my-project-context
charter "C:\work\my project context" --list
```

It's exactly `charter read --context <full path>`, with the same options (`--list`, `--document <path-or-id>`, `--heading <heading>`, `--json`), the same checks, output and exit codes. Quote a path that contains spaces or characters your shell treats specially. It needs the full path: `charter .` or a folder name on its own only prints a hint, because Charter never guesses which folder you mean. This shortcut is for you; the instructions **Connect Agents** gives your agents keep their full-path form on purpose, so PATH can't send them to another copy of Charter.

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

#### Which Charter is running?

`charter --version` (or `py charter.py --version` in the Charter folder) says which copy of Charter runs: its version, its build—a release's build time and commit, or a development checkout's commit and whether it has uncommitted changes—the full paths of its launcher, `charter.py` and Python, and the map format it generates. `charter check` and `charter mcp --check` report the same. In the console, open **Diagnostics** at the end of **Settings** or of **Open Agent Context…**: it adds the map format the open Agent Context records, the open Agent Context's full folder path, and which copy `charter` runs for a new terminal.

#### Update Charter

1. Quit the console (**Ctrl+C**) and your agent hosts.
2. Unpack the new release somewhere temporary, then replace the contents of your Charter folder with it: delete the files inside the Charter folder, keep the folder, and copy in the new release's files. For example, in PowerShell:

   ```powershell
   Expand-Archive charter-<new-version>.zip -DestinationPath $env:TEMP\charter-new
   Remove-Item C:\Tools\Charter\* -Recurse -Force
   Copy-Item $env:TEMP\charter-new\charter-<new-version>\* C:\Tools\Charter -Recurse
   ```

   On macOS/Linux, with the Charter folder at `~/tools/charter`:

   ```bash
   rm -rf /tmp/charter-new
   unzip charter-<new-version>.zip -d /tmp/charter-new
   rm -rf ~/tools/charter/*
   cp -Rp /tmp/charter-new/charter-<new-version>/. ~/tools/charter/
   ```

   `cp -Rp` keeps the launchers' executable mode. If `charter` then says `Permission denied`, see [Troubleshooting](#troubleshooting).

3. Check it: `charter --version` shows the new version, from the same folder.
4. Start the console and open each Agent Context. If an update changed what Charter generates, its map shows **Map out of date**: choose **Rebuild Agent Context…** for each one. (This release generates map format 5, which sends an agent connected through MCP to the `submit_proposal` tool to file its proposals, so every existing Agent Context needs one Rebuild. Until then, MCP and `charter read` refuse it as `map-outdated`, and neither `charter propose` nor `submit_proposal` files a proposal for it. Rebuild changes only `AGENT-CONTEXT.md` and `.agent-context.json`; your governing documents, and any proposals awaiting review, stay as they are.)
5. Reopen your agent hosts. A host keeps running the Charter it started until it restarts, so an agent host left open answers with the old copy: it doesn't list `submit_proposal`, and it refuses a rebuilt Agent Context as `server-outdated`—see [Troubleshooting](#troubleshooting).
6. If you gave agents [command-line access](#agents-that-run-commands-without-mcp), copy their instruction again from **Connect Agents with Command-Line Access**: it now includes the command they file proposals with. An agent still using the old instruction has no proposal command, so the map tells it to return its proposal JSON for you to import.

Registrations keep working because the folder didn't move. If you move the Charter folder, or change the Python it runs with, [connect your agents again](#moving-updating-or-a-development-checkout), replacing each existing registration.

### Create your first Agent Context

You'll create a context, make your first documents govern, then connect an agent.

#### 1. Choose where your context will live

Before choosing the folder, decide how the agent will access it:

- **MCP (recommended):** Your agent retrieves the context through Charter's local read-only server.
- **Command-line access:** Your agent can run commands but can't use MCP. It runs `charter read`, which checks the context as MCP does.
- **File access:** Your agent reads the Agent Context folder directly.

**Using MCP (recommended)**

Keep your Agent Context **beside** the project, rather than inside a folder agents can write. For example:

```text
C:\work\my-project\           your project, where agents work
C:\work\my-project-context\   the Agent Context
```

The Agent Context folder doesn't need to exist yet. Its parent folder (`C:\work` in this example) **does**. On Windows, MCP can't be set up for a folder whose path contains any of `% & | < > ^ "`.

An Agent Context folder cannot be inside another Agent Context folder. Charter recognizes an Agent Context folder by the presence of `AGENT-CONTEXT.md`.

With MCP, the agent retrieves governing documents through Charter and doesn't need ordinary filesystem access to the context folder.

**Using command-line access**

The agent runs Charter on this computer, so keep the Agent Context beside the project, as for MCP. The command reads the folder with the agent's own permissions, so an agent that can run commands can usually also read the folder directly: command-line access gives it a checked route, not a barrier.

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

Open the address in your browser. Leave the terminal open while you use the console; press **Ctrl+C** when you're finished. If port 8765 is already in use, Charter says so; run `charter serve --port 8766` and open `http://127.0.0.1:8766` instead.

💡 Agents connected through MCP don't need the console running. Their host starts Charter's read-only server separately.

#### 3. Create the Agent Context

With no Agent Context open, the console shows **Open or Create an Agent Context**.

1. Enter the path in **Agent Context folder** (or use **Browse…** if offered), then press Tab. The hint below the name says whether there's nothing to open yet.
2. Enter a **Project name (required)**. It titles the context map your agents read, and Connect Agents [derives the MCP server name](#the-mcp-server-name) from it.
3. Choose **Create Agent Context**.

✅ **Expected result:** The **Governing Context** page, with **Agent context ready** in the top bar and **Map current** beside **Context Map**. A new context has no governing documents yet, and agents can already be served.

To come back to it later, see [Open an Agent Context](#open-an-agent-context).

#### 4. Add your documents

Agent Proposals are only for what agents submit. To add your own material:

1. In **Authority Candidates**, choose **Create candidate**.
2. Drop a file on the page, or choose **Choose a file**: Markdown, plain text, Word (`.docx`), or PDF if you installed the optional dependency.
3. Under **Review Converted Document**, check the **Title** (see [how the title is chosen](#how-a-title-is-chosen)), enter a **Scope** if you want one, and review the converted **Text**.
4. Choose **Preview changes**, then **File as candidate**.

**Choose another file** replaces the conversion and everything you typed. **Cancel**, or leaving the page before filing, discards the file and everything typed; nothing is kept.

🔒 **Nothing governs yet.** A candidate is private until you explicitly include it in a confirmed change set.

#### 5. Make your documents govern

1. On a candidate, choose **Plan a change set…**. A change set opens with that candidate included and its decision not yet made.
2. For your first document, choose **Govern alongside** from its decision dropdown. (**Replace** needs a governing document to replace.)
3. To make other candidates govern at the same time, choose each one under **Candidates** and select **Add**, then give it a decision too.
4. Optionally, enter a **Name** and a **Change Set Summary**. Both save automatically.
5. Choose **Preview and apply →** and inspect the changes. To go back without applying, choose **← Back to Build Change Set**, **Cancel**, or **Close**.
6. Type **`change governing context`** in the confirmation box and choose **Apply**.

✅ **Success:** The **Change set applied** receipt, then **Governing Context** lists your documents with **Map current** and **Agent context ready**. For every other kind of change, see [Change governing context](#change-governing-context).

### Connect your agents

Choose how your agent will read its context:

| Route | Best for | What happens |
| --- | --- | --- |
| **MCP (recommended)** | Claude Code, Codex, and other MCP hosts | The host starts Charter; agents retrieve validated governing documents through four read-only tools, and file proposals for your review with `submit_proposal` |
| **Command-line access** | Agents that can run commands on this computer but can't use MCP | Agents run `charter read`, which validates the context exactly as MCP does and answers the same four requests |
| **File access** | Hosts that can read the Agent Context folder | Agents read files directly, without Charter observing or validating the read |

Prefer them in that order: MCP whenever the host supports it, command-line access when it doesn't, and file access only when neither is possible.

You install Charter once. For MCP, register one server for each Agent Context an agent host should read: each registration serves exactly the one folder it names.

Charter never changes an agent host's configuration for you: it shows the commands and settings, and you apply them.

**Before you connect:**

- The context shows **Agent context ready**. Connect Agents offers nothing to copy until it does.
- Charter is in the folder you'll keep: registrations start **this copy** by its full path—on Windows, the Python running Charter with this copy's `charter.py`—never a `charter` found on PATH. Moving Charter, or changing that Python, means connecting again.
- **Charter command needs attention** in the top bar doesn't affect hosts set up here: they start this copy by its full path. It means a terminal, or an agent running `charter propose`, would reach another copy of Charter or none; choose it for the fix.

**To connect an agent:**

1. Open **Connect Agents**. It has five sections, each opened or closed from its heading: **Connect Agents with MCP (Recommended)** starts open; **Add Project Instructions (Recommended)**, **Test the Connection (Optional)**, **Connect Agents with Command-Line Access**, and **Connect Agents with File Access** start closed. Sections you open stay open while you move around the console.
2. Under **Choose an agent host**, select **Claude Code**, **Codex**, or **Other MCP host**.
3. Copy the command or configuration it shows for this context, and apply it as described for your host below.
4. Restart the host as described, and start a new session.
5. [Add the startup pointer](#give-agents-a-startup-pointer) to your project's instruction file (recommended).
6. [Check the connection and retrieval](#verify-your-agent-retrieved-the-context).

Registering the server is necessary but not enough on its own: it makes Charter available to the agent, but doesn't make the agent call it. The startup pointer asks the agent to.

#### The MCP server name

Connect Agents names the server `charter-` followed by the project name in lower case, with accents simplified and each run of other characters replaced by `-`. For example, the project name **Audit Project** gives `charter-audit-project`. The name only labels the server in your host; you can choose another when you register it. Changing the project name in Settings changes the suggested name, but a server you already registered keeps working under its old name.

The examples below use `charter-my-project`, a Charter folder at `C:\Tools\Charter`, Python at `C:\Python312\python.exe`, and a context at `C:\work\my-project-context`; the commands Connect Agents shows already contain your own server name and paths, quoted for each shell.

#### Claude Code

Run the setup command **once from your project's folder**. Connect Agents shows it for both Windows shells.

**Windows — PowerShell:** (`--` must be quoted)

```powershell
claude mcp add charter-my-project '--' C:\Python312\python.exe C:\Tools\Charter\charter.py mcp --context C:\work\my-project-context
```

**Windows — Command Prompt:**

```cmd
claude mcp add charter-my-project -- C:\Python312\python.exe C:\Tools\Charter\charter.py mcp --context C:\work\my-project-context
```

**macOS/Linux:**

```bash
claude mcp add charter-my-project -- /home/you/tools/charter/charter mcp --context /home/you/work/my-project-context
```

Claude Code stores the program and each argument exactly; no shell runs them later. When a path contains `% & | < > ^`, Connect Agents offers only the PowerShell form, which carries them exactly.

By default, Claude Code uses **local scope**: this server is available to you **in this project**.

- Use `--scope project` to share the registration through the project's `.mcp.json` (which records this computer's folder path).
- Use `--scope user` to make it available in all your projects.

Then start a **new Claude Code session**. `claude mcp list` shows whether Claude Code can start the server.

#### Codex

Codex reads MCP servers from `config.toml` inside the `.codex` folder in your home directory. On Windows, that's:

```text
%USERPROFILE%\.codex\config.toml
```

Create the folder and file if needed. ⚠️ When Windows hides file extensions, File Explorer may save `config.toml.txt` instead; check that the name truly ends in `.toml`.

Add the table that **Copy Codex configuration** gives you; its shape is below. Then **quit and reopen Codex**.

**Codex running natively on Windows:**

```toml
[mcp_servers.charter-my-project]
command = "C:\\Python312\\python.exe"
args = ["C:\\Tools\\Charter\\charter.py", "mcp", "--context", "C:\\work\\my-project-context"]
```

**macOS/Linux:**

```toml
[mcp_servers.charter-my-project]
command = "/home/you/tools/charter/charter"
args = ["mcp", "--context", "/home/you/work/my-project-context"]
```

This is Codex's **user configuration**, so the server will be available in every project you open in Codex.

⚠️ Codex running **inside WSL** hasn't been tested with Charter. The Windows configuration above is for **native Windows Codex** only.

#### Other MCP hosts

Many hosts accept an `"mcpServers"` JSON configuration; **Copy MCP configuration** gives it for this context. Its shape:

**Windows:**

```json
{
  "mcpServers": {
    "charter-my-project": {
      "command": "C:\\Python312\\python.exe",
      "args": ["C:\\Tools\\Charter\\charter.py", "mcp", "--context", "C:\\work\\my-project-context"]
    }
  }
}
```

**macOS/Linux:**

```json
{
  "mcpServers": {
    "charter-my-project": {
      "command": "/home/you/tools/charter/charter",
      "args": ["mcp", "--context", "/home/you/work/my-project-context"]
    }
  }
}
```

Adapt the shape to your host's documented configuration; not every host uses this format.

#### Give agents a startup pointer

Charter's server sends brief instructions asking the agent to call `get_context` before work. Claude Code and Codex both read them, but not every host does, and they don't say which project the server is for. The startup pointer says so in your project's own instructions, which the host normally loads at the start of a new project session. It's recommended setup: open **Add Project Instructions (Recommended)**, choose **Copy startup pointer**, and paste it into your **project's** instruction file:

- **Claude Code:** `CLAUDE.md` at the project root.
- **Codex:** `AGENTS.md` at the project root.
- **Other hosts:** their equivalent project instruction file.

**A project with both files:** Claude Code reads `AGENTS.md` only when the project has no `CLAUDE.md` (or `CLAUDE.local.md`), so don't rely on a pointer in `AGENTS.md` alone. Either put the pointer in `CLAUDE.md` too, or keep it in `AGENTS.md` and add a line reading `@AGENTS.md` to `CLAUDE.md`, which imports it. A sentence in `CLAUDE.md` asking Claude to read `AGENTS.md` isn't enough.

Use the project's file, not your personal one for every project (such as `~/.claude/CLAUDE.md` or `~/.codex/AGENTS.md`): the pointer names this project's server.

The pointer reads, with your server name:

```text
This project's governing context is served by the `charter-my-project` MCP server (Charter).
Before beginning work, call its `get_context` tool, then retrieve the governing documents relevant to your task. Treat only the governing documents it lists as authoritative.
```

To check that the host loaded it, start a new session: in Claude Code, run `/memory` or `/context`; in Codex, ask the agent to summarize its instructions.

⚠️ Keep instruction files in the **project**, never inside the Agent Context folder: extra files in the Agent Context cause MCP refusal.

The pointer is guidance, not enforcement: hosts give it to the agent as instructions to follow, and the agent may still not call Charter. Some Claude Code subagents, such as its built-in Explore and Plan agents, start without your project instructions, so they may not see the pointer.

#### Agents that run commands (without MCP)

When the agent's host can't use MCP but the agent can run commands on this computer, give it **command-line access**: it runs `charter read`, which checks the Agent Context exactly as the MCP server does before answering. Open **Connect Agents with Command-Line Access**, choose **Copy instruction** for the shell your agent runs commands in—on Windows **PowerShell**, **Command Prompt**, or **Bash** (Git Bash, which Claude Code uses on Windows); elsewhere the terminal—and add it to your project's instruction file, such as `CLAUDE.md` or `AGENTS.md`. Never put it inside the Agent Context folder. It reads, with your paths (PowerShell shown):

```text
This project's governing context is an Agent Context, served by Charter. Before beginning work, run this command, which prints its context map:

  & C:\Python312\python.exe C:\Tools\Charter\charter.py read --context C:\work\my-project-context

Then retrieve the governing documents relevant to your task by running the same command with `--list`, or with `--document <path-or-id>`, adding `--heading <heading>` for one section. Treat only the governing documents it lists as authoritative.

Rely on its output only when its last line is `<<<END CHARTER READ>>>`. If it refuses, do what it says. If the command cannot run, or reports that Charter context is unavailable, stop and tell the person: do not read the Agent Context's files instead.

To propose a change, follow "Making an Agent Proposal" in the context map, sending the proposal JSON to this command:

  & C:\Python312\python.exe C:\Tools\Charter\charter.py propose --context C:\work\my-project-context
```

Both commands run **this copy** of Charter by its full paths and name the Agent Context by its full path, so PATH plays no part. If you move the Agent Context or Charter, or change the Python Charter runs with, copy the instruction again.

**What the agent runs.** Four forms, each the same request as one MCP tool, and each with `--json` for one JSON object instead of text:

| Command | Returns | MCP equivalent |
| --- | --- | --- |
| `charter read --context <folder>` | `AGENT-CONTEXT.md`, unchanged | `get_context` |
| `charter read --context <folder> --list` | each governing document's id, title, scope, and path | `list_governing_documents` |
| `charter read --context <folder> --document <path-or-id>` | one governing document, in full | `get_document` |
| `charter read --context <folder> --document <path-or-id> --heading <heading>` | one heading's section of that document | `get_document_section` |

`--context` is required every time and must be the Agent Context's **full path**. Charter never uses the current folder, a relative path, an environment variable, Recent, or a folder it remembers, and never searches for an Agent Context.

**Output.** Text output is exactly what the MCP tool returns, followed by a last line that is exactly `<<<END CHARTER READ>>>`. Output that doesn't end with that line was cut off, for example by the agent host's output limit, and the agent mustn't rely on it; asking for one `--document` or `--heading` at a time keeps output short. With `--json`, the command prints exactly one JSON object and no marker: `"result": "served"` with the same fields the MCP tool returns, or `"result": "refused"` with `"reason"` and `"message"`. Nothing is ever written to standard error.

**When it refuses.** A text refusal is one line, `<reason>: <message>`, and serves no context material:

| Exit code | `reason` | Meaning |
| --- | --- | --- |
| 2 | `bad-arguments` | No Agent Context was named, it wasn't named by its full path, or the options aren't one of the four forms. The agent is told to run the exact command its instructions give and not to search for an Agent Context. |
| 1 | `context-invalid` | The folder is missing or can't be read, its files no longer match the approved map, it has no usable map, or a Charter write to it was interrupted. |
| 1 | `context-unclean` | The folder holds a file or folder that isn't part of the Agent Context. |
| 1 | `map-outdated` | The map was generated by an earlier Charter: choose **Rebuild Agent Context…** in the console. |
| 1 | `charter-outdated` | The copy of Charter the command runs is older than the one that generated the map. The context is fine: update that copy of Charter. |
| 1 | `changed-during-read` | A file changed while it was being read. The agent runs the exact same command **once** more; if that doesn't succeed, it stops and tells you. |
| 1 | `not-governing`, `unsafe-path`, `heading-missing`, `heading-ambiguous` | The document or heading asked for isn't one Charter lists. |

Whenever the Agent Context itself is unavailable—every `context-invalid`, `context-unclean`, `map-outdated`, `charter-outdated`, and `changed-during-read` refusal—the message ends by telling the agent not to rely on Charter context it retrieved earlier in the session and to tell you. No message tells it to read the folder's files instead. `bad-arguments` doesn't say this, since no Agent Context was named.

**Compared with file access.** With command-line access, every call checks the whole folder, reads each file it returns once, verifies it against the hash the map records, and answers only if nothing changed meanwhile; the agent computes nothing. With file access, the agent reads whatever is in the folder and must check the hashes itself. Neither is a security boundary: an agent that can run commands can usually read the folder directly too.

`charter read` writes nothing anywhere: no private state, no activity record, no Recent entry.

**Proposals.** An agent that read the context through `charter read` files proposals with the `charter propose` command in its instruction—the same program and the same full path—as [Filing a proposal from an agent](#filing-a-proposal-from-an-agent) describes. That command does write: it files the proposal in Charter's private state for your review, and changes no governing context. If its instruction has no proposal command, for example one copied before this release, or the command can't run, the agent returns its proposal JSON for you to [import](#importing-a-proposal) instead.

#### File-based agents (without MCP)

When neither MCP nor command-line access is available, give the agent **read access** to the Agent Context folder (preferably read-only), including when the folder sits outside the main workspace. Open **Connect Agents with File Access**, choose **Copy agent instruction**, and add it to your host's project instructions. It reads, with your paths:

```text
This project's governing context is an Agent Context, in this folder:
  C:\work\my-project-context

Before beginning work, read its context map:
  C:\work\my-project-context\AGENT-CONTEXT.md

It lists the governing documents and how to use them. Treat only the governing documents it lists as authoritative. If the Charter MCP tools are available, `get_context` returns the same map.

If a document it lists is missing or does not match its recorded hash, read the map again once. If it still does not match, stop: do not rely on what you read from it earlier, and tell the person that the Agent Context no longer matches its map.
```

🔒 **Important:** Direct file reads bypass Charter's validation. The agent sees whatever is in the folder. Charter can't refuse a file read the way it refuses MCP; the map and this instruction tell the agent to stop and tell you when the files no longer match. If it can also write there, it can bypass the review workflow. With file access, you're responsible for giving the agent the right folder and instructions, keeping them current, and routing changes back through Charter.

#### Moving, updating, or a development checkout

Every registration starts the copy of Charter you set it up from, by its full path, whether that copy is an installed release or a development checkout (a Git working tree of Charter's source), so PATH can never route an agent to another copy. [Updating Charter](#update-charter) in the same folder keeps registrations working. If you move Charter, or change the Python it runs with, connect your agents again: the old registration points at the old path, and the host reports that it can't start the server.

To connect again, start the console from Charter's new location, open **Connect Agents**, and replace each host's existing registration with what it gives you now:

- **Claude Code** refuses to add a server name it already has (`MCP server charter-my-project already exists`). From the same project folder, remove the old registration first, then run the command Connect Agents shows:

  ```text
  claude mcp remove charter-my-project
  ```

  If you registered it with `--scope project` or `--scope user`, add the same option to `claude mcp remove`. `claude mcp list` then shows the new path and whether Claude Code can start it.
- **Codex:** in `config.toml`, replace the existing `[mcp_servers.charter-my-project]` table, its `command` and `args` lines included, with the one **Copy Codex configuration** gives you. Don't add a second table with the same name: TOML doesn't allow one, so the file would no longer be valid. Then quit and reopen Codex.
- **Other MCP hosts:** replace the server's existing entry rather than adding another.
- **Command-line access:** replace the instruction in your project's instruction file with the one **Connect Agents with Command-Line Access** gives you now.

Optional terminal-based proposals are separate from context retrieval; see [Agent Proposals](#agent-proposals).

### Verify your agent retrieved the context

Three checks answer three different questions. Each one shows something the one before can't.

**1. Is the server connected?** After restarting the host, `claude mcp list` (or `/mcp` in a session) shows whether Claude Code can start the server; for Codex, `codex mcp list`, or `/mcp` in a session. This shows the host can reach Charter, not that an agent will use it. To check Charter's side without a host, run `charter mcp --context <folder> --check` (see [Troubleshooting](#troubleshooting)).

**2. Does retrieval work when asked?** Start a **new agent session** in your project and send the prompt that **Test the Connection (Optional)** copies with **Copy prompt**:

> Before doing anything else, retrieve this project's Agent Context. Tell me
> the project name it gives, and which of its governing documents apply to
> this task: [describe a small task]. If you cannot retrieve it, say so; do
> not guess.

✅ **Success:** The agent names your project and the relevant documents from its map. Your host might ask you to allow the tool first. If the agent can't name the project, it **hasn't demonstrated retrieval yet**. Run this again after you restart or reconnect a host, or change the startup pointer.

**3. Does the agent retrieve it unprompted? (optional)** In another new session, give the agent an ordinary small task without mentioning Charter. With [**Context check-in**](#settings) on, as it is by default, the map asks the agent to begin a short update with `Context check: AGENT-CONTEXT read.` and name the documents it says it read. Seeing that line is a sign the agent followed the startup pointer in that session. It isn't proof of which documents it retrieved, or that it understood or will follow them. If **Context check-in** is off, the map doesn't ask for this line, so this signal isn't available.

These checks are guidance and validation, not enforcement. Each shows what happened in one session; Charter can't prove that an agent keeps following its context.

---

## Work with Charter

- [Open an Agent Context](#open-an-agent-context)
- [Check context health](#check-context-health)
- [Settings](#settings)
- [Manage authority candidates](#manage-authority-candidates)
- [Change governing context](#change-governing-context)
- [Agent Proposals](#agent-proposals)
- [Work alongside Git](#work-alongside-git)

The console carries no information icons or hover panels; this part of the guide explains what it shows.

### Open an Agent Context

**Open Agent Context…**, at the top right, and the **Charter** name at the top left both lead to **Open or Create an Agent Context**.

1. Enter the folder in **Agent Context folder**, use **Browse…**, or select it under **Recent**.
2. When the folder already holds an Agent Context, its name appears read-only under **Name**; change it later in [Settings](#settings).
3. Choose **Open Agent Context**.

**Open Agent Context** checks the folder and shows whether agents can be served; it writes nothing in the folder, except that an interrupted Charter write is rolled back first. **Create Agent Context** makes a new, empty one in an empty folder. Neither action runs Git or creates agent instruction files such as `AGENTS.md` or `CLAUDE.md`.

#### Bring in documents you already have

Only a valid map decides what governs. Governance front matter shows that a document is shaped like a governing document; it never shows that anyone approved it into this context. So documents you already have become governing context the same way every new document does: as [authority candidates](#4-add-your-documents) governed through a reviewed [change set](#change-governing-context). Charter never generates a map that makes documents already sitting in a folder govern.

The simplest route is to [create an empty Agent Context](#3-create-the-agent-context) and add each document with **Create candidate**.

If you already have a folder that holds `authoritative/` but no `AGENT-CONTEXT.md` or `.agent-context.json`, it is an existing Agent Context with no approved context, not an empty folder: open it with **Open Agent Context**. **Create Agent Context** doesn't accept it. Opening writes nothing in the folder.

- If it holds documents, the status reads **Context changes need review** and lists each one as **Not in approved context**, whatever its front matter says. No Rebuild is offered. What you do next depends on where the documents came from:
  - **An approved map and metadata exist elsewhere** (for example, the folder is a checkout and the map is in Git): restore `AGENT-CONTEXT.md` and `.agent-context.json` with your usual recovery, and the context is checked against them again.
  - **The documents are newly authored, or were never mapped**: there is no map to restore. Move the documents out of the folder and continue below.
- Once no document remains in `authoritative/`, the status reads **This Agent Context has no map yet**. Choose **Rebuild Agent Context…**, enter the **Project name**, confirm the agent guidance, review the preview, and choose **Rebuild Agent Context**. This establishes an empty Agent Context, which governs nothing.
- Then add each document you moved out with **Create candidate**, and govern it through a change set.

A governing document starts with front matter like this, followed by its Markdown text. Charter writes it for you when a change set makes a candidate govern:

```text
---
id: deployment-rules
title: Deployment Rules
status: active
authority: authoritative
scope: How and where we deploy
created: 2026-10-18
updated: 2026-10-18
supersedes: []
superseded_by: []
---
```

Rebuild never changes a governing document, and never makes one govern; it only writes the map and metadata.

An **Agent Context** is a dedicated folder agents read: `AGENT-CONTEXT.md`, `.agent-context.json`, and the governing documents in `authoritative/`. It may sit inside a project or its own Git repository; nothing else belongs in it.

**Recent and Clear.** **Recent** lists the Agent Contexts opened or created in the console on this computer, the most recently opened first; opening one moves it to the top. A folder Charter only reads or keeps private state for in another way—an MCP retrieval, `charter check`, `charter propose`, or another command—is never added. Entries listed by an earlier Charter, which also listed folders that only those commands had used, stay until you remove them yourself, for example with **Clear**: Charter can't tell how they were first used, so it never silently drops or rewrites them. **Clear** takes every listed Agent Context off this computer's Recent list and changes nothing else: it never opens, closes, or changes an Agent Context, its files, or its candidates, proposals, and change sets. It hides the folders rather than erasing them: Charter's private state still records each folder's path, with the work it keeps for that folder, so clearing Recent doesn't remove a folder's name from this computer. Opening or creating a context afterwards lists it again.

### Check context health

The top bar names the open Agent Context by its project name and its folder's name, such as **Audit Project · audit-context**, and **CURRENT CONTEXT** in the sidebar shows the same folder name. The full path is where you need it exactly: under **Recent** in **Open Agent Context…**, in **Diagnostics**, and in the commands Connect Agents gives you. The top bar always shows one status, and **Governing Context** shows the map's status after **Context Map**. Each label says what it means in words; the colours only reinforce them. When something is wrong, the status above every view names the problem and the next safe step.

| Status | Where | Meaning | What to do |
| --- | --- | --- | --- |
| **Agent context ready** | Top bar (and **Agents: Ready** in **CURRENT CONTEXT**) | The folder is valid and clean, so MCP and file-reading agents receive its governing documents. | Nothing. |
| **Agent context unavailable** | Top bar (and **Agents: Unavailable**) | The folder is invalid, incomplete, holds stray files, or no longer matches its approved map, so MCP refuses it. | Follow the status above every view, as in the rows below. |
| **Context changes need review** | Status above every view | The checked-out files no longer match the approved context map, or the folder holds documents but no usable map. Each affected file is listed below it with one chip. Agents get an unavailable answer, and are told not to rely on Charter context they read earlier. | See [When context changes need review](#when-context-changes-need-review). |
| **Does not match approved context** | A file listed under Context changes need review, and its document card | The file's text no longer matches the hash `.agent-context.json` records for it; for `.agent-context.json` itself, the map and metadata list different documents. | Restore the approved file with Git or your own recovery. To keep a governing document's current text, choose **Revise…** first. |
| **Missing from context** | A file listed under Context changes need review | The map lists this document, but it isn't in the folder. | Restore it. If you meant to remove it, withdraw it in a change set once the context is valid again. |
| **Not in approved context** | A file listed under Context changes need review | A document in `authoritative/` that the map doesn't list, or any document when there is no usable map. It may be perfectly well formed; it just isn't approved here. | With no usable map: if an approved map and metadata exist elsewhere, restore them. Otherwise—and always when a map exists but doesn't list it—move it out of the Agent Context; to make it govern, add it with **Create candidate** and govern it through a change set. |
| **Cannot verify file** | A file listed under Context changes need review | The map records this file, but Charter can't read it, so it can't check it. | Check that it's there and readable, or restore it. |
| **Regenerate map…** | The `AGENT-CONTEXT.md` row under Context changes need review | Only the map's own text no longer matches its recorded hash; it still lists exactly the recorded documents, every one of them matches, and Charter can regenerate a map with exactly the hash `.agent-context.json` records. | Choose it, review the preview, and confirm: it restores only `AGENT-CONTEXT.md`, exactly as the approved context records it. `.agent-context.json` is never changed. |
| **No Agent Context open** | Top bar | Nothing is open in the console. | Choose **Open Agent Context…**. |
| **Charter command ready** | Top bar, after the context's status | `charter` in a new terminal runs this copy of Charter. | Nothing. |
| **Charter command needs attention** | Top bar, after the context's status | `charter` in a new terminal runs another copy of Charter, or isn't found, so a terminal, or an agent running `charter propose`, wouldn't reach this copy. It's a warning about your PATH, not about the Agent Context: nothing is disabled, and agents set up with Connect Agents start this copy by its full path. | Choose it, or **Fix…** beside it. The dialog names the copy found, gives one command to copy that puts this copy on your PATH (after removing any other copy it names), and says to open a new terminal afterwards. The console checks the PATH it was started with, so after the fix, quit the console and start it again from a new terminal for this to read **Charter command ready**. |
| **This Agent Context has no map yet** | Status above every view (with **Map out of date** or **Map not checked**) | The folder holds `authoritative/` but no `AGENT-CONTEXT.md` or `.agent-context.json`, and no document, so agents get an unavailable answer. | Correct or move out each item listed, then choose **Rebuild Agent Context…** to establish an empty context; see [Bring in documents you already have](#bring-in-documents-you-already-have). |
| **Map current** | Context Map | `AGENT-CONTEXT.md` and `.agent-context.json` are exactly what Charter generates from the governing documents and settings. | Nothing. |
| **Map out of date** | Context Map | The map or metadata is missing, unreadable, or not what Charter generates, and Charter can correct it without changing which documents govern or their text—for example, after you update Charter, when the status above every view reads "This Agent Context’s map is out of date". | Choose **Rebuild Agent Context…** (or **Regenerate map…**, when that is what's offered), review the preview, and confirm. |
| "This copy of Charter is out of date" | Status above every view (with **Map not checked**) | A newer version of Charter generated this Agent Context. The context is not at fault; this console is an older copy. Charter offers no Rebuild here, so it never rewrites the newer map. | Use the current Charter installation: quit this console and start the current one. **Diagnostics** shows which copy is running. |
| **Map not checked** | Context Map | A governing document has a problem, or context changes need review, so the map can't be compared yet. | Follow the status above every view. Charter checks again whenever you choose a page in the navigation. |
| "Charter can’t serve this Agent Context yet", with files listed | Status above every view | The folder holds a file or folder that isn't part of an Agent Context, such as notes or `CLAUDE.md`. Until it's resolved, agents get an unavailable answer instead of governing material. Charter never moves or deletes it. | Move each listed file out of the context folder, or delete it, then choose any navigation item to check again. |
| "Charter can’t serve this Agent Context yet", for another reason | Status above every view | The line under it says why: a Charter write to the folder was interrupted; Charter’s local records for the folder can’t be used, so it can’t tell whether a write was interrupted; the map was generated by Agent Context Manager, Charter’s earlier name; the map and metadata aren't in the form Charter generates for these documents and settings; or something else isn’t valid, listed below. Agents get an unavailable answer until it's resolved. | Do what that line says: open the Agent Context in Charter to recover an interrupted write or see what to do about its records; choose **Rebuild Agent Context…** for the map; or fix each listed problem. |
| **Changed Outside Charter** | Status above every view | The context is valid and served, but its governing documents differ from what Charter last saw here—for example after a Git checkout or pull that brought a context another computer's Charter generated. Charter can't tell who made the change. A **Rebuild** of Charter's own map and metadata is not flagged. Shown only while agents are served. | Check the listed documents, then choose **Mark as seen**. |
| **Origin unknown** | Context Map | The files are valid, but this computer has no record of how this version was created—for example, a copied or cloned folder. | Nothing needs repair. |
| **Stale** | Agent Proposal card | Its target changed after the agent read it, so it can't be accepted as written. | Reject it, or ask the agent to propose again. |
| **structurally valid** / **waiting for required candidates or decisions** / **blocked** | Change-set editor | Whether the plan can be previewed, still needs a decision, or has a problem to correct first. | Follow **Readiness** in the editor. |

**Governing Context** lists the documents currently governing the selected Agent Context, after its **Context Map**. **View agent context** shows `AGENT-CONTEXT.md`, the agents' entry point; `.agent-context.json` is its integrity record. The map is a routing aid, not a governing document, and is never edited by hand. **Rebuild Agent Context…** is offered only when every governing document matches the approved map and nothing else is in the folder, or when no document remains; it never changes a governing document or makes one govern.

From a terminal, `charter check --context <folder>` reports the same health—its `Agents:` line reads `served` or `unavailable`—and exits **0** only when agents are served.

#### When context changes need review

`AGENT-CONTEXT.md` and `.agent-context.json` are the only record of which documents govern and what their approved text is. Charter checks the folder exactly as it's checked out. A context that is internally consistent is served normally, whether you pulled it with Git, copied it from another computer, or made it here: Charter doesn't treat a file as suspect because this copy didn't write it.

When the files no longer agree with that record, Charter refuses to serve the context and lists what it observed—each file that doesn't match, is missing, isn't in the approved context, or can't be verified, with its recorded and current hashes. It never says who or what made a change (you, an agent, Git, an editor, a formatter, or anything else), and it never uses file times as evidence. No Rebuild, Refresh, or other action accepts the changed text. You resolve it in one of these ways:

- **Restore the approved files** with `git restore`, `git checkout`, or your own backup. The context is served again as soon as the files match.
- **Keep a document's current text as a proposal for review.** Choose **Revise…** on the document while the context is unavailable: it saves the current checked-out text as a revision candidate and changes nothing else. Then restore the approved document, and replace it with the revision through an ordinary [change set](#change-governing-context). The preview compares the revision with the approved text and warns that it was made from another version, so you can check that difference before you apply it.
- **A document that's missing** must be restored first. If you meant to remove it, withdraw it in a change set once the context is valid again.
- **A document that isn't in the approved context**: move it out of the Agent Context, and add it with **Create candidate** if you want it to govern.
- **Only the map doesn't match**, while every governing document does: **Regenerate map…** regenerates the map from the approved documents and, after a preview, replaces `AGENT-CONTEXT.md` only if the result has exactly the hash `.agent-context.json` already records. It never changes the metadata or records a new hash. If Charter can't reproduce the recorded map—for example, because the recorded settings no longer produce it—Regenerate map isn't offered, and you restore the map with your own recovery instead.

Agents connected through MCP get an unavailable answer to every tool call until it's resolved. It says what kind of mismatch Charter found, but names no files, and tells the agent not to rely on Charter context it read earlier in the session and to tell you. A file-reading agent is told by the map to reread it once and, if it still doesn't match, to stop and tell you. Charter can't erase what an agent already read; it refuses everything after.

### Settings

**Settings** holds the project name and agent guidance. Both are recorded in `.agent-context.json` and written into `AGENT-CONTEXT.md`.

1. Change **Project name** or any **Agent guidance** checkbox.
2. Choose **Preview changes** to see the regenerated map and metadata.
3. Choose **Save settings**, or **Cancel**.

Saving changes no governing document; the map's other wording is generated and can't be edited.

Agent guidance adds advisory instructions to the map's **Agent guidance** section. It isn't governing context: a governing document's stricter rule always applies.

In `AGENT-CONTEXT.md`, each option that's on is one bullet in the **Agent guidance** section, beginning with the option's name in bold, such as **Context check-in.** With every option off, the map has no Agent guidance section.

| Option | Default | Asks agents to |
| --- | --- | --- |
| **Context check-in** | On | After reading the map and relevant documents, send a brief update starting `Context check: AGENT-CONTEXT read.` that names the documents read. |
| **Assess proposal impact** | Off | Before proposing a change, check it for duplication, overlap, and conflict with governing documents, and report that in the proposal's `expected_context_impact`. |
| **Review discovered material** | Off | Compare relevant non-governing material they encounter with the governing documents, and raise conflicts with a person instead of settling them. |

### Manage authority candidates

An **authority candidate** is a document under consideration. It's kept in private local state on this computer, agents never see it, and it governs nothing until a confirmed change set makes it govern. Each card's source label follows its title:

- **Created by person**: from **Create candidate**.
- **Proposed by:** and the agent's name: from an accepted [Agent Proposal](#agent-proposals).
- **Revision**: from **Revise…**, with **Revision of:** naming the governing document.
- **Withdrawn governing document**: returned by a change-set withdrawal.

| Task | How | Result |
| --- | --- | --- |
| Add your own document | **Authority Candidates → Create candidate** ([steps](#4-add-your-documents)) | A new candidate. |
| Change a candidate | **Edit…** on its card, **Preview the change**, **Save candidate** | The candidate is updated; nothing agents read changes. |
| Revise a governing document | **Revise…** on the document in **Governing Context**, edit, **Preview the candidate**, **File as candidate** | A **Revision** candidate. The governing document doesn't change until a change set [replaces](#change-governing-context) it with the revision. |
| Compare a revision | **Compare with governing…** (or **Compare revisions…** when several candidates revise one document) | A side-by-side diff. |
| Drop a candidate | **Retire…**, review the preview, **Retire** | The candidate moves to the private archive. The console doesn't list archived documents. |

Every candidate action previews its files first; **Cancel** or **Close** leaves everything unchanged.

#### How a title is chosen

When **Create candidate** converts a file, it suggests a **Title**, which you can change:

1. A `title` in the file's front matter (Markdown and text files), if any.
2. Otherwise, a leading level-1 heading (`# Heading` in Markdown, or a Heading 1 paragraph in Word).
3. Otherwise, the file name without its extension—for example, `release-notes` for `release-notes.txt` or a PDF. PDF text is split under `## Page N` headings.

A leading level-1 heading that suggests the title **stays in the Text**, so the document keeps it as a section, as an agent's proposed body does.

Front matter in Markdown and text files is removed; its one-line `title` and `scope` become suggestions, and identity, authority, status, dates, source, and supersession **aren't carried over**. Charter refuses **Text** that starts with a front-matter block. A candidate created from a file records the file's name and a short SHA-256 fingerprint, not a copy of the file.

#### Scope

**Scope** is a short routing summary shown beside the title in `AGENT-CONTEXT.md`; it helps agents choose which documents to read. It's optional:

- A candidate that **governs alongside** with a blank scope appears in the map as *scope not stated*.
- A candidate that **replaces** a document with a blank scope inherits the replaced document's scope; the preview shows the current, candidate, and resulting scope.

### Change governing context

A document governs only when it lives in `authoritative/`, its metadata marks it **authoritative** and **active**, and the map and metadata record it. Governing context changes **only** through a change set: there's no separate grant, replace, or withdraw action.

**Start a change set** in one of three ways:

- **Plan a change set…** on a candidate: the candidate is included, its decision not yet made.
- **Withdraw in a change set…** on a governing document: the document is planned for withdrawal.
- **Change Sets → New change set**: an empty draft.

**Build it.** In the editor:

1. Under **Candidates**, add each candidate and choose one decision from its dropdown:
   - **Govern alongside**: it governs at its own new path, alongside the others.
   - **Replace**: it replaces the governing document you then choose in the target dropdown, at that document's path. The previous document is archived privately. A revision's original is listed first as a suggestion, but isn't selected for you. The replacement keeps the replaced document's path but takes the candidate's own `id`: a candidate made with **Revise…** has the original's `id` followed by `-revision` (and a number if that's taken). Its front matter records `supersedes:` with the replaced document's `id`, and the private archived copy records the new `id` in `superseded_by:`. Refer to a governing document by its path, which a replacement keeps, rather than by its `id`.
2. Under **Withdrawals**, add any governing document to withdraw. A withdrawn document becomes an authority candidate again.
3. Every governing document that isn't replaced or withdrawn is **retained** unchanged; the editor doesn't list them.
4. Optionally, enter a **Name** and **Change Set Summary**. Everything saves automatically as a private draft.

One change set can combine any number of these, and they apply together. **View details** shows a planned candidate in full; **Edit details…** edits it and returns you to the draft, which then asks you to **Refresh** it. **Remove** takes a candidate or withdrawal out of the plan. **Readiness** says what's still needed. Charter never guesses at a decision or target.

**Preview and apply.**

1. Choose **Preview and apply →**. **Preview and Apply** shows, in order: anything that blocks applying or bears on your decision; **Changes to Apply**, one line for each document the change set changes, by title, saying what happens to it: it replaces a named governing document, governs alongside, or is withdrawn; and every changed file with its diff and **Read**, including the regenerated map. Documents the change set leaves alone aren't listed. To see a resulting document, scope included, choose **Read** on its file.
2. To change the plan, choose **← Back to Build Change Set**, **Cancel**, or **Close**; nothing is written.
3. To apply, type **`change governing context`** and choose **Apply**. A wrong phrase is refused and nothing changes. All changes apply together; a failure rolls them back.

**After applying,** the **Change set applied** receipt leads with a summary such as `1 document updated · 1 newly governing · 1 withdrawn · 1 retained`, lists each changed document with its outcome, and keeps paths, the retained documents, and the full technical summary behind disclosures. Agents read the new context immediately, and Charter doesn't touch Git. **← Change Sets** returns to the index, which lists only active drafts; receipts stay in private state.

**Leave or discard a draft.** **← Change Sets** keeps the draft for later. **Discard draft** asks once, then discards it and returns you to Change Sets; candidates and governing context are unaffected.

A draft becomes **stale** if a candidate or document it refers to changes; choose **Refresh** to use the current versions.

**Change sets recorded by an earlier Charter build** declared an outcome for every governing document, including **retain** and **revise**. Applied and abandoned ones are kept exactly as recorded. An active one can be viewed, abandoned, or deleted, but must be converted before it can be refreshed, reviewed, previewed, or applied: **Convert to current form…** lists every change first—each revise becomes a replace of the same document by the same candidate, each replace stays as it is, and each retain is removed, leaving that document retained—and converts only when you confirm. Converting changes no governing context; attached reports become stale.

#### Advisory review

**Want an agent's opinion before applying?** The editor's **Agent Review** panel prepares **vendor-neutral advisory review material** once the plan is complete:

- **Copy review prompt** copies a prompt for the agent you choose. When the material is too large for a practical single message, the panel offers a review packet to save **outside every Agent Context** instead. **Save review packet…** opens your computer's Save dialog, started by the terminal running the console and beginning in your Downloads folder; if you don't see it, look behind your browser window. **Cancel** saves nothing. Where no Save dialog can be shown, the panel asks you to type the full path of a file or folder instead. Either way, Charter refuses a destination inside an Agent Context or its own private state, and asks before saving inside a Git repository, whose next commit could include the packet. The disclosure warning beside each applies: the documents under review may be shared with the service you choose. Charter itself contacts **no service** and adds no private state, local paths, or Git information.
- Choose **Add a review** (then **Add another review**) for each agent's response: its **Reviewing agent** and text save automatically. Only a structurally valid report counts as an attached advisory report; other text stays saved, with feedback on what's wrong. **Remove review** removes one.
- Charter checks a report's **form, fingerprints, coverage, paths, and quotations**, but **not its conclusions**. A report never chooses an outcome for you.

### Agent Proposals

Agents suggest changes as **Agent Proposals**: private JSON requests that a person reviews. A proposal can create a candidate, amend a candidate, propose a revision to a governing document, or retire a candidate. **Accepting one never changes governing context**; a separate change set does that.

Agent Proposals is an inbox of work awaiting your decision. Accepting a proposal files, updates, or retires the candidate it concerns; accepting or rejecting it removes the proposal. Charter keeps no history of decided proposals.

#### Filing a proposal from an agent

An agent submits one proposal at a time. How it submits depends on how it got the context; `AGENT-CONTEXT.md` tells it which:

| The agent got the context… | It submits with… |
| --- | --- |
| through MCP | the `submit_proposal` tool of the same MCP server, with the proposal's fields as the tool's arguments |
| by reading the Agent Context folder | `charter propose --context .`, run in that folder, with one JSON object on standard input |
| through `charter read` ([command-line access](#agents-that-run-commands-without-mcp)) | the `charter propose --context <full path>` command its instruction gives, exactly as given |
| through any other tool | nothing: it returns the proposal JSON for you to [import](#importing-a-proposal) |

**Through MCP.** `submit_proposal` files the proposal through the same checks as `charter propose` and import, as an ordinary agent proposal awaiting your review. It never accepts a proposal, changes governing context, or grants authority, and Charter records no activity for it. Your host may ask you to allow it, since it writes Charter's private state. It returns the same four results as `charter propose`, below, without exit codes. When it returns `unavailable` with `retryable` `true`—another proposal was being filed, or something unexpected went wrong—the agent submits exactly the same proposal once more: if the first attempt was filed after all, the retry returns `duplicate`. If the tool isn't listed or is denied, returns `unavailable` that isn't retryable, or the retry returns neither `pending` nor `duplicate`, the agent returns the proposal JSON for you to import instead, and after a retry tells you it may already be awaiting review. A result never names a folder, a path on your computer, or an authority candidate.

**ASCII JSON.** An agent sending proposal JSON to `charter propose` writes it as ASCII JSON, encoding every non-ASCII character as a JSON Unicode escape such as `—` for `—`. Some shells change other characters on the way: Windows PowerShell 5.1, by default, turns them into `?` when it pipes text to a program, and the proposal would be filed with `?` where the agent wrote `—` or `é`. Charter can't tell such a `?` from one the agent meant, so it can't repair it; ASCII JSON passes through every shell unchanged. This rule is only for JSON sent to `charter propose`: an agent returning proposal JSON for you to import doesn't need it.

`charter propose` prints one JSON object. Its `result`, and the command's exit code:

| `result` | Exit code | Meaning |
| --- | --- | --- |
| `pending` | 0 | Filed for review, with a `proposal_id`. |
| `refused` | 3 | Not filed; each listed problem says what to correct. |
| `unavailable` | 4 | Not filed; submit again unchanged only if `retryable` is `true`. |
| `duplicate` | 5 | Not filed: the same proposal is already awaiting review. Change the proposal, or ask a person to replace the waiting one in the console. |

A proposal is a duplicate when its content is the same as one still awaiting review in the same Agent Context, whether that one was filed by an agent, through `charter propose` or `submit_proposal`, or imported, from pasted JSON or a file. Charter compares the proposal's fields, not how the JSON was written: different spacing, key order, JSON escapes, or a leading byte-order mark don't make a new proposal, but a different `agent`, `reason`, `expected_context_impact`, or any other field does. A proposal already accepted or rejected never counts.

From the Agent Context folder, the agent needs `charter` on its PATH; through command-line access, its instruction names this copy by its full paths, so PATH plays no part. Either way it needs permission to write Charter's private state. An agent that read the context through MCP uses `submit_proposal` rather than `charter propose`; an agent that can't submit returns the JSON instead, for you to [import](#importing-a-proposal): `AGENT-CONTEXT.md` tells it so. `--context` names the Agent Context itself, as `.` or its full path; Charter never searches for one, and if the folder named isn't an Agent Context, the agent is told to return the JSON rather than look for it. If the Agent Context's map format doesn't match the Charter that runs the command—the map is out of date, or that Charter is—it files nothing and returns `unavailable`, not retryable, saying which.

**Proposal JSON.** `AGENT-CONTEXT.md` gives agents the complete format; in brief:

| Field | Required | Value |
| --- | --- | --- |
| `agent` | Always | The agent's self-reported name, shown to the reviewer. Can't be empty. |
| `operation` | Always | `create`, `amend`, or `retire`. |
| `target_path` | Always | A governing document's path from the map, or `authority-candidates/<name>.md` for a candidate. A `create` uses a new `authority-candidates/<name>.md` name. `retire` applies only to a candidate. |
| `reason` | Always | Why the change is needed. |
| `proposed_body` | `create`; `amend` unless `replacements` is given | The full Markdown body, **without front matter**. |
| `replacements` | `amend`, instead of `proposed_body` | `[{"find": "...", "replace": "..."}]`; each `find` occurs exactly once. |
| `base_sha256` | `amend`, `retire` | SHA-256 of the target's whole current text, as UTF-8 with LF line endings. If the target changed since, the proposal is refused or becomes **Stale**. |
| `proposed_meta` | Optional | `{"title": "...", "scope": "..."}` for the candidate. |
| `expected_context_impact` | Optional | The agent's assessment; kept privately as advisory review material. |

Any other field is refused. Amending a governing document creates a revision candidate; the governing original stays unchanged. A proposal's body is kept as written, including any leading heading.

#### Importing a proposal

1. In **Agent Proposals**, choose **Import agent proposals…**.
2. Add the proposals: paste an agent's JSON into **Agent proposal JSON**, choose **Choose files…** to pick one or more `.json` files, or drop files onto the drop area (it's also a button: press it to pick files). Each pasted text and each file becomes one row. A file's name appears only in that row: Charter never receives or keeps it.
3. Choose **Check proposals**. Charter checks each row exactly as `charter propose` would, reading a file's bytes exactly as that command reads its input, and writes nothing. Each row shows one status:

   | Status | Meaning |
   | --- | --- |
   | **Ready** | It would be filed. |
   | **Already awaiting review** | The same proposal is waiting already. **Replace…** offers to update that one instead. |
   | **Same as another selected item** | Another row in the list has the same proposal. |
   | **Stale** | The governing document it changes was changed after the agent read it. |
   | **Refused** | It can't be filed as written; the row says why. |
   | **Malformed** | It's too large, isn't UTF-8 text, isn't JSON, or isn't one JSON object. |

   If the Agent Context can't accept proposals right now, the panel says **Unavailable** once instead, and nothing can be imported.
4. Only **Ready** rows can be selected, and each starts selected. Rows with any other status don't get in the way. Choose **Import N proposals**: Charter checks the selected rows again and files all of them or none. If one is no longer ready—say its target changed meanwhile—nothing is filed and the rows show what they are now. Imported proposals appear under **Imported by You**; nothing is accepted, and no candidate or change set is made.

Adding, removing, or changing a row needs a fresh check. **Replace…** works one row at a time, apart from any import: it asks, for example, *An identical proposal, "Incident Response," is already awaiting review. Replace it?* **Replace** updates that one waiting proposal with this row—its received time and source—without adding another; **Cancel** changes nothing.

You can import up to 20 proposals at a time. **Cancel**, or leaving Agent Proposals, clears the list and closes the panel without importing. Import is only for an agent's proposals; to add your own material, use **Create candidate**.

#### Reviewing a proposal

Each card leads with the title of the document it concerns—for a new document, the title the agent gave or else its first heading—then one line such as **Submitted by:** Claude · **Received:** 1 min ago, and a one-line **Purpose**.

- **Review proposal…** expands the card in place: the full purpose, and each file accepting would write, with **Read** to see the candidate as it would be.
- **Accept as candidate** files or updates the candidate in one step; the console says **Proposal accepted.** Accepting a retire proposal archives the targeted candidate instead.
- **Reject proposal** works from the compact card or the expanded review: it asks once, in place, with **Reject** and **Cancel**. **Reject** removes the proposal, and the console says **Proposal rejected.**
- **Close review**, or leaving Agent Proposals, folds the card away again.

An agent's expected context impact is kept privately with its proposal; it isn't shown on the review screen.

#### Unexpected local records

Charter files each proposal itself, in its private state, and records what it filed. A file it finds among those records that it didn't file—or that changed after it was filed, can't be read as a proposal, or isn't a regular file—appears under **Unexpected Local Records**, marked **Unexpected — not a proposal**, with the reason. This can happen when another program, such as an agent with access to your files, writes there directly.

An unexpected record is never a proposal: it can't be accepted or rejected, and Charter leaves it unchanged.

- **View contents** shows its text. For a record that isn't a regular file—a folder, a link, or another special file—it says what the record is instead; Charter never opens or follows one.
- **Import a copy…** opens **Import agent proposals…** with its text filled in. Check it and import it like any agent's JSON. The file itself stays where it is. A record that isn't a regular file has no text, so it offers no **Import a copy…**.

To remove an unexpected record from the list, delete the file it names yourself. It's in `contexts/<key>/proposals/pending/` in [private state](#private-state), in the `<key>` folder whose `context.json` names this Agent Context's folder. Charter never moves or deletes it.

### Work alongside Git

**You own the Git workflow.** Charter never initializes repositories or stages, commits, branches, switches, merges, rebases, fetches, pulls, or pushes.

When the Agent Context sits inside a Git checkout, Charter can **read Git information limited to that context folder**:

- The sidebar shows its current branch and the number of context files Git reports as changed. It doesn't list the files.
- **`charter compare`**, in a terminal, compares your current Agent Context with that folder at a branch, tag, or commit you name. It prepares **advisory review material** about differences since that point. The console doesn't offer this comparison.

```text
charter compare --context . --base main
```

By default it prints a summary: each governing document added, changed, or removed, whether the project name or agent guidance changed, and what review material is available. Add `--prompt` to print only the review prompt, ready to copy, when it fits one message. Past that limit, add `--packet <file or folder>` to save one review packet outside every Agent Context. If that folder is inside a Git repository, Charter warns you and saves nothing unless you also add `--accept-git-warning`. `--json` prints the result as one JSON object. Outside a Git checkout, it says so and makes no comparison.

The review material identifies the base only by its context fingerprint. Charter adds no base name, commit, branch, local path, or private state of its own, and refuses to prepare material whose own wording or metadata would; the documents are included exactly as they read, so a document that mentions `main` is no obstacle to `--base main`.

The comparison uses **read-only Git commands** limited to the Agent Context and **never fetches**. It writes nothing except a packet you ask for, and creates no private state. The result is review input—not authority, merge approval, or a new current change set.

A pull, merge, or checkout that leaves the context internally consistent is served as it is. One that leaves a governing document, or the map, not matching what the map and metadata record needs review: see [When context changes need review](#when-context-changes-need-review). Charter never asks Git what happened, and never treats a commit or branch as approval.

---

## Help and reference

### Troubleshooting

- **`charter` not found:** Open a new terminal after PATH changes, then check with this copy's own command, by its full paths: in PowerShell, the Python that runs Charter and this copy's `charter.py`, such as `& C:\Python312\python.exe C:\Tools\Charter\charter.py add-to-path --check`; on macOS/Linux, this copy's launcher, such as `/home/you/tools/charter/charter add-to-path --check`. **Diagnostics** shows both paths for your copy. You can run local commands there without PATH as `py charter.py serve` or `python3 charter.py serve`. Agent hosts set up with Connect Agents don't need PATH.
- **`Permission denied` running `charter` (macOS/Linux):** The launcher has lost its executable mode, for example after unpacking the release with a tool that drops file permissions. Check with the Python that runs Charter and this copy's `charter.py`, each by its full path, such as `/usr/bin/python3 /home/you/tools/charter/charter.py add-to-path --check`: it prints the `chmod +x` command that fixes it.
- **Another `charter` comes first on PATH:** the top bar shows **Charter command needs attention**, and `add-to-path --check`, `charter mcp --check` and **Diagnostics** say which copy runs. A terminal, and an agent running `charter propose`, would reach that other copy; agent hosts set up with Connect Agents start this copy by its full path. Choose **Charter command needs attention** for the fix: remove the folder it names from your PATH, run the command it gives, and open a new terminal. To check again, use this copy's own command, by its full paths, as `add-to-path --check` gives it: for example `& C:\Python312\python.exe C:\Tools\Charter\charter.py add-to-path --check` in PowerShell, or `/home/you/tools/charter/charter add-to-path --check` on macOS/Linux; see [Install Charter](#install-charter), step 5. The console checks the PATH it started with: quit it and start it again from the new terminal before its top bar can show **Charter command ready**.
- **After updating Charter, an agent says the context can't be served:** the agent's message names the cause. `map-outdated`: the map was generated by an earlier version of Charter—open the Agent Context in the console and choose **Rebuild Agent Context…**. `server-outdated`: the agent host is still running an older Charter than the one that generated the map—the context is fine; quit and reopen the agent host, or connect it again if Charter moved. `charter-outdated`, from `charter read`: the copy its instruction runs is older than the map—update that copy, or copy the instruction again from the current one. An older Charter that predates these messages says only `context-invalid`; if `charter check --context <folder>` says agents are served, restart the agent host. From `submit_proposal`, the same causes come back as an `unavailable` result with `map_outdated` or `server_outdated`, and the same remedies.
- **An MCP agent has no `submit_proposal` tool:** the agent host is still running a Charter from before this release. Quit and reopen the agent host; until then the agent returns its proposal JSON for you to [import](#importing-a-proposal).
- **`charter read` refuses, or the agent can't run it:** its answer names the reason (the first word of a text answer, `reason` in JSON); see [Agents that run commands](#agents-that-run-commands-without-mcp) for each. `bad-arguments` usually means the instruction was edited or copied incompletely: copy it again from **Connect Agents with Command-Line Access**. If the shell can't find the program, Charter or its Python has moved: copy the instruction again from the console of the copy you now use. `charter check --context <folder>` says whether the folder can be served.
- **Port 8765 occupied:** Run `charter serve --port 8766` and open `http://127.0.0.1:8766`.
- **"Charter's private state folder is no longer private to this user" (macOS/Linux):** Charter keeps its [private state](#private-state) in a folder only your account may use, and stops if other accounts can reach it, for example `(mode 755)` after a backup restore or a copy. Check that the folder is yours, then make it private again; this changes only its permissions:

  ```bash
  ls -ld ~/Library/Application\ Support/Charter
  chmod 700 ~/Library/Application\ Support/Charter
  ```

  On Linux the folder is `~/.local/state/charter`. If `ls -ld` names another account as the owner, don't change it: ask whoever manages the computer. If the message instead says the folder belongs to another account, or isn't a plain folder, Charter can't use it until that is resolved.
- **MCP refuses the context:** Run `charter check --context <folder>`, or open the folder in the console and follow [Check context health](#check-context-health). After a direct edit to a governing document, Rebuild won't accept it: restore the approved text, or keep the edit with **Revise…** and govern it through a change set; see [When context changes need review](#when-context-changes-need-review). If an unexpected file or folder (such as `CLAUDE.md`, notes, or an empty subfolder under `authoritative/`) is inside the Agent Context, move it out; Charter won't move or delete it.
- **`charter propose` is refused, unavailable, or a duplicate:** Exit code 3 (`refused`) lists each problem to correct; exit code 4 (`unavailable`) means Charter couldn't file proposals on this computer; exit code 5 (`duplicate`) means the same proposal is already waiting—change the proposal, or replace the waiting one by [importing it](#importing-a-proposal) and choosing **Replace**. If the agent can't fix a refusal, have it return the JSON and import it.
- **Agent can't connect:** Run `charter mcp --context <folder> --check`. This diagnoses the folder and this copy of Charter, **not** the host configuration. Start a new session after MCP configuration changes, and connect again if you moved Charter or changed its Python.

**Windows Claude Code / VS Code edge case:** If `claude mcp list` shows a connection but VS Code has no Charter tools, local-scope registration may depend on the exact project path spelling (including `C:` versus `c:`). In Command Prompt, `cd /d c:\path\to\project` using the spelling shown by VS Code, rerun the [Claude Code Command Prompt registration](#claude-code), and start a new conversation. Keep local scope for this workaround.

### Access and trust

Charter controls the context it serves and changes performed through its own workflow. **It cannot override the permissions your agent host gives an agent.** Keep these boundaries in mind:

- 🔒 **MCP reads are checked.** An agent receives only the map and governing documents. Before every retrieval, Charter checks the folder and refuses it when invalid, unclean, or mid-change. MCP's one write tool, `submit_proposal`, only files a proposal for your review: it **never changes governing context**.
- 🔒 **`charter read` is checked the same way.** It answers only from a valid, clean folder, verified on every call, and returns no private state. It writes nothing.
- **Direct file reads bypass Charter's checks.** An agent with file access reads what's present; Charter neither observes nor validates that read.
- **Private work stays out of agent-facing Charter interfaces.** Candidates, archived documents, Agent Proposals, change-set drafts and receipts, review material, and MCP activity live in Charter's private local state—not the Agent Context.
- ⚠️ **Host permissions still matter.** If a host allows an agent to read or write files, run commands, or reach the local console under your account, that agent may reach private state or edit the context directly. Charter can't stop those actions. Use the host's permissions or sandbox, and keep the context outside writable agent folders.
- **Valid doesn't mean approved.** Integrity checks establish that the folder's files agree with each other; they don't prove who wrote them. Charter changes receive your preview and confirmation. A checkout whose files all agree governs for that checkout, however it was produced; one whose documents no longer match its map is refused until you restore it or govern the change through a change set. If Charter has a prior local record, the console identifies an outside change until you acknowledge it; otherwise, the content's origin is unknown.
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

It holds this computer's **Recent** list of opened Agent Contexts. For each Agent Context, its `contexts/<key>/` private state contains:

- Authority candidates and archived documents. A candidate created from a file records the file's name and a short SHA-256 fingerprint, not a copy of the file.
- Agent Proposals awaiting a decision; decided ones aren't kept.
- Change-set drafts and receipts.
- Private MCP diagnostic activity.
- Staging and locks.

🔒 This material isn't exposed through Charter's agent-facing interfaces. **But account-level access matters:** programs running as you—including agents granted such access—can still reach it. See [Access and trust](#access-and-trust).

Private state is tied to the Agent Context folder's **location on this computer**. A copied, moved, or cloned folder starts without that private history. Losing private state means losing local receipts and unapproved work, **not the governing context**.

#### The MCP server

Your agent host starts Charter as a local **stdio MCP server**, running `mcp --context <agent-context-folder>` with this copy's launcher, by its full path. It keeps running the copy and version it started until the host restarts it.

It exposes **four read-only tools** and **one proposal tool**:

- `get_context`
- `list_governing_documents`
- `get_document`
- `get_document_section`
- `submit_proposal`, which files one Agent Proposal for your review (see [Filing a proposal from an agent](#filing-a-proposal-from-an-agent))

`submit_proposal` is the only tool that writes: it files a proposal in Charter's private state and nothing else. MCP returns no private state, and no result names the Agent Context's folder or any other location on your computer. Charter validates the
folder **before every retrieval**; if it is invalid, unclean, or has an
interrupted write, the request is refused with one of **ten fixed reason
codes**. Two say what to do after an update: `map-outdated` (rebuild the Agent
Context in Charter) and `server-outdated` (restart the agent host, or connect it
to the current Charter; the context is not at fault). When the files no longer
match the approved map, or there is no usable map, every tool answers
`context-invalid` with no context material at all: the message says what kind of
mismatch was found, by count and never by file name, and tells the agent not to
rely on Charter context it retrieved earlier in the session and to tell you.

Charter retains a bounded record of MCP retrieval activity **privately**; submitting a proposal records none. It isn't available through MCP, and the console has no activity feed. A recorded retrieval means the server answered a request—it doesn't identify which agent requested it or establish that the agent followed the material.

#### Commands

Here's the command-line reference:

```text
charter serve [<agent-context-folder>] [--port 8765]
charter check --context <folder>
charter mcp --context <folder> [--check]
charter compare --context <folder> --base <revision> [--prompt | --packet <destination> [--accept-git-warning]] [--json]
charter read --context <absolute-folder> [--list | --document <path-or-id> [--heading <heading>]] [--json]
charter <absolute-folder> [--list | --document <path-or-id> [--heading <heading>]] [--json]
charter propose --context <. | full path>
charter add-to-path [--check]
charter --version
```

- **`charter serve`** — Runs the local console.
- **`charter check`** — Reports whether a context folder is valid and served, and which copy of Charter checked it. Makes no changes or private state; exits **0** if agents are served, **1** otherwise.
- **`charter mcp`** — Runs the stdio MCP server: read-only retrieval, and proposals filed for your review; `--check` provides diagnostics.
- **`charter compare`** — Compares the Agent Context with its folder at a Git base you name and prepares advisory review material. Reads Git only; exits **0** when a comparison was made, **1** when it couldn't be made or the requested material couldn't be produced, **2** for an unusable command line.
- **`charter read`** — Command-line access for an agent without MCP: prints the map, the governing-document list, one document, or one section, validated as MCP validates it. `--context` must be a full path. Text ends with the line `<<<END CHARTER READ>>>`; `--json` prints one JSON object. Writes nothing; exits **0** when served, **1** when refused, **2** for `bad-arguments`. See [Agents that run commands](#agents-that-run-commands-without-mcp).
- **`charter <absolute-folder>`** — Your shortcut for `charter read --context <absolute-folder>`, with the same options, output and exit codes. The first word must be a full path; anything that is neither a command nor a full path prints a hint and exits **2**. Agent instructions keep the full-path `charter read` form.
- **`charter propose`** — Submits one Agent Proposal as JSON on standard input, sent as ASCII JSON. `--context` is `.` in the Agent Context folder, or its full path as a command-line access instruction gives it. Exits **0** `pending`, **3** `refused`, **4** `unavailable`, **5** `duplicate`. See [Filing a proposal from an agent](#filing-a-proposal-from-an-agent).
- **`charter --version`** — Says which copy of Charter this is: version, build, launcher, `charter.py` and Python paths, and map format.
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
