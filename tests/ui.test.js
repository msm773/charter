/* The Charter console page, driven against real server payloads.

   `tests/ui.py` captures the console API's own answers for a real Agent
   Context in each state the page must show, and hands them to this file,
   which runs the page's own JavaScript against them. Run it through that:
   `python -m tests.ui`.

   The one area the console has deliberately not wired yet — MCP activity —
   has its former assertions kept, not run, in tests/deferred/. */

"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { createDocument, parseInto, serialize } = require("./domshim");

const ROOT = path.dirname(__dirname);
const STATIC = path.join(ROOT, "app", "static");
const OK = "\u001b[32m✓\u001b[0m";

const fixture = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
let failures = 0;
function check(condition, label) {
  if (condition) { console.log(`  ${OK} ${label}`); return; }
  failures++;
  console.log(`  \u001b[31m✗\u001b[0m ${label}`);
}

/* ------------------------------------------------------- browser stand-ins */

const document = createDocument();
const html = fs.readFileSync(path.join(STATIC, "index.html"), "utf8");
parseInto(document, document.body, html);
global.document = document;

const calls = [];
const DUPLICATE_MARK = " ";  // trailing whitespace: a distinct text, answered as a duplicate by this stand-in
let currentState = fixture.state_closed;
let connectAnswer = fixture.connect_ready;
let commandAnswer = fixture.command_ready;  // the header's Charter command status
let csNext = null;  // the change-set payload the next change-set call answers with
let csListAnswer = null;  // the change-set index, when not fixture.cs_list
let stageAnswer = fixture.stage;  // what converting the next file answers
let stageDelay = null;  // { gate, answer }: the next conversion answers only once gate resolves
let importCheckDelay = null;  // a gate: the next import check answers only once it resolves
const GOVERNING_KINDS = ["grant", "replace", "withdraw", "changeset"];
const planFor = (body) => {
  if (body.kind === "edit-candidate" && body.request && body.request.candidate === fixture.legacy_path) {
    return fixture.legacy_edit_plan;
  }
  if (body.kind === "changeset") {
    return body.request && body.request.draft_id === fixture.start_request.draft_id ? fixture.start_plan : fixture.cs_plan;
  }
  if (body.kind === "rebuild") {
    if (body.request && body.request.project_name !== undefined) return fixture.plan_rebuild_confirmed;
    return currentState === fixture.state_lost_metadata ? fixture.plan_rebuild_lost : fixture.plan_rebuild;
  }
  return fixture.plans[body.kind];
};
global.fetch = async (url, options) => {
  const body = options && options.body ? JSON.parse(options.body) : undefined;
  calls.push({ url, method: (options && options.method) || "GET", body,
    headers: (options && options.headers) || {} });
  const answer = (data) => ({ ok: true, status: 200, json: async () => data });
  const refuse = (status, error) => ({ ok: false, status, json: async () => ({ error }) });
  if (url === "/api/state") return answer(currentState);
  if (url === "/api/connect") return answer(connectAnswer);
  if (url === "/api/command") return answer(commandAnswer);
  if (url === "/api/diagnostics") return answer(currentState.open ? fixture.diagnostics : fixture.diagnostics_closed);
  if (url === "/api/open") {
    if (body.path.endsWith("missing")) return refuse(400, fixture.open_missing_error);
    currentState = fixture.state_valid;
    return answer({ opened: body.path, name: fixture.state_valid.project_name });
  }
  if (url === "/api/create") {
    currentState = fixture.state_valid;
    return answer({ created: body.path, name: body.project_name || "new-context", headline: "" });
  }
  if (url === "/api/pick-folder") return answer({ path: "/work", cancelled: false });
  if (url === "/api/recent/clear") {
    currentState = Object.assign({}, currentState, { recent: [] });
    return answer({ cleared: true });
  }
  if (url === "/api/peek") {
    // A read-only look: a chosen folder already holding a context answers with
    // its name; an empty or missing folder is offered to create.
    const p = (body && body.path) || "";
    if (/authored/.test(p)) return answer(fixture.peek_incomplete);
    return answer(/missing|empty|new-context|\/other$/.test(p) ? fixture.peek_empty : fixture.peek_existing);
  }
  if (url === "/api/plan") return answer(planFor(body));
  if (url === "/api/apply") {
    // Governing context changes only through a change set's own route.
    if (GOVERNING_KINDS.includes(body.kind)) return refuse(409, "Governing context changes only through a change set.");
    return answer(fixture.apply_candidate);
  }
  if (url === "/api/draft") {
    return answer(fixture.drafts[body.path] || fixture.cs_drafts[body.path]
      || (body.path === fixture.legacy_path ? fixture.legacy_draft : undefined));
  }
  if (url === "/api/preview") {
    if (body.source === "context") return answer(fixture.previews.context);
    if (body.source === "plan") return answer(fixture.previews["planned:" + body.path]);
    return fixture.previews[body.path] ? answer(fixture.previews[body.path])
      : refuse(400, "Only documents this page lists can be read here.");
  }
  if (url === "/api/candidate/compare") {
    return answer({ left: { path: body.candidate, title: "Beta revised" },
      right: { path: body.against, title: "Beta" },
      diff: "--- Beta\n+++ Beta revised\n@@ -1 +1 @@\n-Clearer Beta.\n+Even clearer Beta.\n" });
  }
  if (url === "/api/intake/stage") {
    // A conversion that answers late: held until the test lets it go.
    const delayed = stageDelay;
    stageDelay = null;
    return delayed ? delayed.gate.then(() => answer(delayed.answer)) : answer(stageAnswer);
  }
  if (url === "/api/acknowledge") return answer({ acknowledged: true });
  if (url === "/api/proposals") return answer(fixture.proposals);
  if (url === "/api/changesets/list") return answer(csListAnswer || fixture.cs_list);
  if (url === "/api/changeset/apply") return answer({ applied: true, kind: "changeset" });
  if (url === "/api/changeset/create" && body && body.start) {
    // A change set started from one candidate or a withdrawal: the real answer to that start.
    return answer(body.start.withdraw ? fixture.cs_start_withdraw
      : body.start.candidate === fixture.candidate ? fixture.cs_start_alongside : fixture.cs_start_candidate);
  }
  if (url === "/api/changeset/get" && body.id === fixture.start_request.draft_id) return answer(fixture.cs_start_applied);
  if (url === "/api/changeset/packet/save") {
    return refuse(400, "The review packet cannot be saved there: Choose a folder outside every Agent Context and Charter's private state. Nothing was saved.");
  }
  if (url.startsWith("/api/changeset")) return answer(Object.assign({}, csNext,
    url === "/api/changeset/refresh" ? { refreshed: [{ document: "authority-candidates/delta.md", change: "candidate text changed; review it" }] } : {}));
  if (url === "/api/proposals/unexpected") {
    return answer(body.name === "a-folder" ? fixture.unexpected_folder_view : fixture.unexpected_view);
  }
  if (url === "/api/proposals/import/check") {
    const checked = answer(/base_commit/.test(body.json) ? fixture.import_check_bad : fixture.import_check_ok);
    const gate = importCheckDelay;
    importCheckDelay = null;
    return gate ? gate.then(() => checked) : checked;
  }
  if (url === "/api/proposals/import") {
    // An exact duplicate of a waiting proposal is named, not filed, until the person replaces it.
    if (body.json.endsWith(DUPLICATE_MARK) && !body.replace) {
      return answer({ result: "duplicate", problem: { code: "duplicate", message: "Identical." },
        waiting: { proposal_id: "p-waiting", title: "Waiting rule" } });
    }
    return answer({ result: "pending", proposal_id: body.replace || "p-imported" });
  }
  return refuse(404, "no route " + url);
};
global.FileReader = class {
  readAsDataURL() {
    this.result = "data:application/octet-stream;base64," + Buffer.from("# Site notes\n").toString("base64");
    Promise.resolve().then(() => this.onload && this.onload());
  }
};
// Toasts are cosmetic; their timers would only hold the process open.
global.setTimeout = () => 0;
global.clearTimeout = () => {};

/* The browser's address and history, enough for the page's #view addresses. */
const addressBook = { entries: [""], states: [null], index: 0 };
global.location = { get hash() { return addressBook.entries[addressBook.index]; } };
global.history = {
  get state() { return addressBook.states[addressBook.index] === undefined ? null : addressBook.states[addressBook.index]; },
  pushState(s, t, url) {
    addressBook.entries.splice(addressBook.index + 1); addressBook.states.splice(addressBook.index + 1);
    addressBook.entries.push(url); addressBook.states.push(s); addressBook.index++;
  },
  replaceState(s, t, url) { addressBook.entries[addressBook.index] = url; addressBook.states[addressBook.index] = s; },
  back() { goBack(); },
};
const windowListeners = {};
global.window = { addEventListener(type, fn) { (windowListeners[type] = windowListeners[type] || []).push(fn); } };
const popstate = () => (windowListeners.popstate || []).forEach((fn) => fn({}));
const goBack = () => { addressBook.index--; popstate(); };
const goForward = () => { addressBook.index++; popstate(); };

const settle = async () => { for (let i = 0; i < 40; i++) await new Promise((r) => setImmediate(r)); };
/* The stand-in's id lookup also finds elements a redraw removed: only one
   still on the page counts. */
const attached = (n) => { for (let x = n; x; x = x.parentNode) if (x === document.documentElement) return true; return false; };
const $ = (id) => { const n = document.getElementById(id); return n && attached(n) ? n : null; };
const buttonSaying = (root, label) =>
  root.querySelectorAll("button").find((b) => b.textContent.trim() === label) || null;
const labelsIn = (root) => root.querySelectorAll("label").map((l) => l.textContent);
/* The stand-in's selectors take one simple selector per step: no lists or attributes. */
const fieldsIn = (root) => root.querySelectorAll("input").concat(root.querySelectorAll("textarea"));
const labelFor = (root, id) => root.querySelectorAll("label").find((l) => l.getAttribute("for") === id);
const insideOf = (node, root) => { for (let n = node; n; n = n.parentNode) if (n === root) return true; return false; };
/* Hidden for a person: the node, or anything around it up to `root`, is hidden. */
const hiddenWithin = (node, root) => {
  for (let n = node; n && n !== root; n = n.parentNode) if (n.hidden) return true;
  return false;
};
const lastCall = (url) => calls.filter((c) => c.url === url).pop();
const lastPlan = () => lastCall("/api/plan");
const requestKeys = () => JSON.stringify(Object.keys(lastPlan().body.request).sort());
const toastNow = () => document.querySelector(".toast");
const clearToasts = () => document.querySelectorAll(".toast").forEach((t) => t.remove());
const click = async (node) => { node.click(); await settle(); };
const type = (node, value) => { node.value = value; node.dispatch("input"); };
const nav = () => document.querySelectorAll("#nav button");
const navItem = (view) => nav().find((b) => b.dataset.view === view);
const navTo = async (view) => click(navItem(view));
/* The page reads the Agent Context again, as it does after an operation. */
const reload = async () => { await vm.runInThisContext("refresh")(); await settle(); };
const show = async (stateName) => { currentState = fixture[stateName]; await reload(); };
const rowOf = (listId, title) => $(listId).querySelectorAll(".doc")
  .find((d) => d.querySelector(".title").textContent === title);
const fileToggles = (root) => root.querySelectorAll(".file-toggle");
const regionOf = (button) => document.getElementById(button.getAttribute("aria-controls"));
const expanded = (root) => fileToggles(root).filter((b) => b.getAttribute("aria-expanded") === "true");
const css = fs.readFileSync(path.join(STATIC, "styles.css"), "utf8");
/* How the header names an open Agent Context: its project name and folder name. */
const shownName = (st) => `${st.project_name} · ${st.folder_name}`;
const rule = (source, selector) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\>]/g, "\\$&").replace(/\s+/g, "\\s*");
  const m = source.match(new RegExp("(^|\\n)\\s*(?:[^{}\\n]*,\\s*\\n\\s*)?" + escaped + "\\s*\\{([^}]*)\\}"));
  return m ? m[2] : "";
};
const SCOPE_ROUTING = "A short routing summary shown in AGENT-CONTEXT.md.";
/* The one compact Scope control every scope-editing form uses: the label
   Scope, exactly one helper, and no information control or placeholder. */
const compactScope = (root, inputId, hintId) => {
  const input = document.getElementById(inputId);
  const field = input && input.parentNode;
  const label = field && field.querySelectorAll("label").find((l) => l.getAttribute("for") === inputId);
  const hints = field ? field.querySelectorAll(".hint") : [];
  return !!label && label.textContent === "Scope" && hints.length === 1 && hints[0].textContent === SCOPE_ROUTING
    && hints[0].getAttribute("id") === hintId && input.getAttribute("aria-describedby") === hintId
    && !(input.getAttribute("placeholder") || "") && !field.querySelectorAll(".info-toggle").length && !field.querySelectorAll(".info-pop").length
    && !root.querySelectorAll(".info-toggle").some((t) => /scope/i.test(t.getAttribute("aria-label") || ""));
};

for (const file of ["markdown.js", "app.js"]) {
  vm.runInThisContext(fs.readFileSync(path.join(STATIC, file), "utf8"), { filename: file });
}

(async () => {
  await settle();
  const startView = $("view-open");

  /* ------------------------------------------------------------ the start */

  console.log("With nothing open: one folder, Open Agent Context or Create Agent Context");
  check(!startView.hidden && startView.querySelector(".view-head h2").textContent === "Open or Create an Agent Context"
    && document.title === "Open or Create an Agent Context — Charter",
    "the entry view is Open or Create an Agent Context");
  check(JSON.stringify(labelsIn($("startSection"))) === JSON.stringify(
    ["Agent Context folder", "Project name (required)"])
    && $("newProjectName").getAttribute("aria-required") === "true"
    && $("newProjectName").getAttribute("aria-describedby") === "newProjectNameHint",
    "it asks for the folder, and the project name, labelled required");
  const actionsRow = $("startSection").querySelector(".actions");
  check(actionsRow.children[0] === $("btnOpen") && actionsRow.children[1] === $("btnCreate")
    && $("btnOpen").textContent === "Open Agent Context" && $("btnCreate").textContent === "Create Agent Context",
    "two adjacent buttons: Open Agent Context, then Create Agent Context");
  check($("btnOpen").disabled && $("btnCreate").disabled && $("contextError").hidden, "both wait for a folder");
  check($("btnBrowse").hidden, "without a folder dialog on this computer, the folder is typed");
  check(!$("projectName") || $("projectName").textContent === "no Agent Context open", "the rail says nothing is open");

  console.log("\nNo information controls: the README explains what each action does");
  check(!$("aboutOpening") && !startView.querySelectorAll(".info-toggle").length
    && !document.querySelectorAll(".info-toggle").length && !document.querySelectorAll(".info-pop").length
    && !/\.info-(toggle|pop|wrap)/.test(css),
    "the page carries no information icon, hover panel or their styles anywhere");

  console.log("\nOpen Agent Context sends the folder only; a refusal is said beside it");
  type($("contextPath"), "/work/missing");
  check(!$("btnOpen").disabled && $("btnCreate").disabled,
    "a folder enables Open; Create still waits for the project name");
  const beforeOpen = calls.length;
  $("contextPath").dispatch("keydown", { key: "Enter" });
  await settle();
  const opened = calls.slice(beforeOpen).filter((c) => c.url === "/api/open").pop();
  check(opened && JSON.stringify(opened.body) === JSON.stringify({ path: "/work/missing" })
    && !calls.slice(beforeOpen).some((c) => c.url === "/api/create"),
    "Enter is Open — the action that changes nothing — and sends the folder alone");
  check(!$("contextError").hidden && $("contextError").textContent === fixture.open_missing_error
    && $("contextError").getAttribute("role") === "alert"
    && $("contextPath").getAttribute("aria-invalid") === "true"
    && $("contextPath").getAttribute("aria-describedby") === "contextError" && !startView.hidden,
    "a refusal is said beside the folder, as an alert, and the field is marked invalid");
  type($("contextPath"), "/work/other");
  check($("contextError").hidden && $("contextPath").getAttribute("aria-invalid") === "false",
    "editing the folder clears it");
  check(calls.every((c) => c.headers["X-Charter-Console"] === "person"),
    "every request says it comes from the console's own page");

  console.log("\nCreate Agent Context sends the folder and the optional name");
  type($("contextPath"), "/work/new-context");
  type($("newProjectName"), "Booking service");
  check(!$("btnCreate").disabled, "with a folder and a project name, Create is enabled");
  await click($("btnCreate"));
  check(JSON.stringify(lastCall("/api/create").body) === JSON.stringify({ path: "/work/new-context", project_name: "Booking service" }),
    "Create sends the folder and the project name, nothing else");
  check(startView.hidden && !$("view-governing").hidden, "the new Agent Context opens on Governing documents");
  check(toastNow() && /Created the Agent Context “Booking service”/.test(toastNow().textContent)
    && /Git is untouched/.test(toastNow().textContent), "and says so, and that Git is untouched");
  check($("contextPath").value === "" && $("newProjectName").value === "", "the start form is empty again");

  console.log("\nThe folder dialog and recent Agent Contexts");
  currentState = fixture.state_closed_picker;
  await click($("btnSwitch"));
  await vm.runInThisContext("refresh")();
  await settle();
  check(!startView.hidden && !$("btnBrowse").hidden && $("btnBrowse").parentNode === $("contextPath").parentNode,
    "with a folder dialog, the folder has Browse… beside it");
  await click($("btnBrowse"));
  check(lastCall("/api/pick-folder") && $("contextPath").value === "/work" && !$("btnOpen").disabled,
    "Browse… asks this computer for a folder and fills it in");
  check(lastCall("/api/peek") && $("newProjectName").readOnly
    && $("newProjectName").value === fixture.peek_existing.name
    && $("newProjectName").classList.contains("secondary")
    && $("newProjectName").getAttribute("aria-required") === "false"
    && $("btnCreate").disabled,
    "choosing an existing Agent Context reads its name in, read-only, and Open is the action");
  check(/already here, so there is nothing to create/.test($("newProjectNameHint").textContent)
    && $("btnCreate").getAttribute("aria-describedby") === "newProjectNameHint"
    && !$("btnOpen").getAttribute("aria-describedby"),
    "disabled Create says why, visibly, and is described by that line");
  type($("contextPath"), "/work/new-context");
  $("contextPath").dispatch("change");
  await settle();
  check(!$("newProjectName").readOnly && $("newProjectName").value === ""
    && $("newProjectName").getAttribute("aria-required") === "true" && $("btnOpen").disabled,
    "choosing an empty folder leaves the name required and editable, and only Create applies");
  check(/nothing to open/.test($("newProjectNameHint").textContent)
    && $("btnOpen").getAttribute("aria-describedby") === "newProjectNameHint"
    && !$("btnCreate").getAttribute("aria-describedby"),
    "disabled Open says why, visibly, and is described by that line");
  console.log("\nA folder of authored documents in authoritative/, with no map yet: opened, never created");
  type($("contextPath"), "/work/authored-docs");
  $("contextPath").dispatch("change");
  await settle();
  type($("newProjectName"), "Typed name");
  check(fixture.peek_incomplete.has_context && fixture.peek_incomplete.incomplete
    && !$("btnOpen").disabled && $("btnCreate").disabled && $("newProjectName").readOnly,
    "Open applies and Create does not, even with a name typed");
  check(/holds authoritative\/ but no context map yet, so there is nothing to create/.test($("newProjectNameHint").textContent)
    && /opening writes nothing in it/.test($("newProjectNameHint").textContent)
    && $("btnCreate").getAttribute("aria-describedby") === "newProjectNameHint",
    "the line under the name says so, and describes the disabled Create");
  type($("contextPath"), "/work/new-context");
  $("contextPath").dispatch("change");
  await settle();
  const recent = $("recentContexts").querySelectorAll("button");
  check($("recentContexts").querySelector("h3").textContent === "Recent" && !/Opened on This Computer/.test($("recentContexts").textContent)
    && recent.some((b) => b.textContent === fixture.folder), "Agent Contexts opened here before are listed under Recent");
  await click(recent.find((b) => b.textContent === fixture.folder));
  check($("contextPath").value === fixture.folder, "and one click fills in the folder");
  currentState = fixture.state_valid;
  await click($("btnOpen"));
  check(!$("view-governing").hidden && $("barPath").textContent === shownName(fixture.state_valid),
    "Open shows the Agent Context");

  console.log("\nRecent stays available after an Agent Context is open, without a restart");
  check(Array.isArray(fixture.state_valid.recent) && fixture.state_valid.recent.includes(fixture.folder),
    "the console's state for an open Agent Context still carries Recent");
  await click($("btnSwitch"));
  check(!$("view-open").hidden && $("recentContexts").querySelector("h3").textContent === "Recent"
    && $("recentContexts").querySelectorAll("button").some((b) => b.textContent === fixture.folder),
    "Open Agent Context… shows Recent, though an Agent Context is open");
  await navTo("governing");
  await navTo("candidates");
  await click($("wordmark"));
  check($("recentContexts").querySelectorAll("button").some((b) => b.textContent === fixture.folder),
    "and still after navigating away and back");

  console.log("\nClear empties only the Recent list, and it stays empty");
  const clear = $("btnClearRecent");
  check(clear && clear.textContent === "Clear" && clear.className === "btn small"
    && clear.parentNode.querySelector("h3").textContent === "Recent",
    "a non-empty Recent list offers Clear beside its heading, with the shared button treatment");
  const beforeClear = calls.length;
  await click(clear);
  await settle();
  const clearCalls = calls.slice(beforeClear).map((c) => c.url);
  check(clearCalls.includes("/api/recent/clear")
    && !clearCalls.some((u) => /\/api\/(open|create|apply|changeset)/.test(u)),
    "Clear asks only to clear the list: nothing is opened, created or applied");
  check(!$("recentContexts").querySelector("h3") && !$("btnClearRecent") && !$("view-open").hidden
    && $("barPath").textContent === shownName(fixture.state_valid),
    "the list and its Clear are gone, and the open Agent Context stays open");
  await navTo("governing");
  await click($("wordmark"));
  check(!$("recentContexts").querySelector("h3") && !$("btnClearRecent"),
    "Recent stays cleared after navigating away and back, and offers no Clear while empty");
  currentState = fixture.state_valid;
  await navTo("governing");

  console.log("\nThe Charter wordmark and Open Agent Context… open the same view");
  check($("btnSwitch").textContent === "Open Agent Context…" && $("wordmark").tagName === "BUTTON"
    && $("wordmark").textContent === "Charter" && $("wordmark").parentNode === document.querySelector("nav.rail h1"),
    "the top-right action is Open Agent Context…, and the wordmark is a button named Charter");
  await click($("wordmark"));
  check(!$("view-open").hidden && $("view-governing").hidden && vm.runInThisContext("currentView") === "open",
    "the wordmark opens the Open or Create Agent Context view");
  await navTo("governing");
  await click($("btnSwitch"));
  check(!$("view-open").hidden && $("view-governing").hidden, "and so does Open Agent Context…");
  await navTo("governing");
  check(!$("view-governing").hidden, "the navigation returns to the open Agent Context");

  /* ----------------------------------------------------- shell and navigation */

  console.log("\nNavigation is the six Agent Context areas");
  check(nav().map((b) => b.dataset.view).join(" ") === "governing candidates proposals changesets connect settings",
    "Governing Context, Authority Candidates, Agent Proposals, Change Sets, Connect Agents, Settings");
  check(nav().map((b) => b.childNodes[0].textContent.trim()).join(" | ")
      === "Governing Context | Authority Candidates | Agent Proposals | Change Sets | Connect Agents | Settings"
    && $("btnAddDocument").textContent === "Create candidate" && $("view-intake").querySelector("h2").textContent === "Create Candidate"
    && $("btnOpen").textContent === "Open Agent Context" && $("contextMapTitle").textContent === "Context Map",
    "capitalization: navigation and headings in Title Case; buttons stay in sentence case");
  check(document.querySelector("nav.rail h1").childNodes[0].textContent === "Charter"
    && $("projectName").textContent === fixture.state_valid.project_name,
    "the application is titled Charter, and names the open project");
  check(!nav().some((b) => b.dataset.view === "intake"), "Create candidate is an action, not a navigation item");
  const pageText = html.replace(/<!--[\s\S]*?-->/g, "");
  for (const word of [/surface/i, /publication/i, /\bbind/i, /registration/i, /\bworkspace\b/i]) {
    check(!word.test(pageText), `the page never says “${word.source.replace(/\\b/g, "")}”`);
  }
  check(!/(?<!Git )\brepository\b/i.test(pageText), "“repository” is said only of a Git repository");
  check(!document.querySelectorAll("button").some((b) => /commit|push|pull|merge|rebase|\bstage\b|checkout|publish/i.test(b.textContent)),
    "no button operates Git or publishes");

  console.log("\nThe header and rail say which Agent Context, and whether agents are served");
  check($("barPath").textContent === shownName(fixture.state_valid) && $("barState").textContent === "Agent context ready"
    && $("barName").textContent === fixture.state_valid.project_name
    && $("barFolder").textContent === fixture.state_valid.folder_name
    && $("barState").querySelector(".chip").classList.contains("ok")
    && $("metaRoot").textContent === fixture.state_valid.folder_name && $("metaAgents").textContent === "Ready",
    "its project name and folder name, and its status label: Agent context ready, in the positive treatment");
  check(fixture.state_valid.root.endsWith(fixture.state_valid.folder_name)
    && fixture.state_valid.root !== fixture.state_valid.folder_name
    && document.querySelector(".topbar").textContent.indexOf(fixture.state_valid.root) === -1
    && document.querySelector("nav.rail").textContent.indexOf(fixture.state_valid.root) === -1,
    "neither the header nor the rail shows the full path");
  await show("state_windows");
  check(fixture.state_windows.folder_name === "team-alpha-context"
    && $("barFolder").textContent === "team-alpha-context" && $("metaRoot").textContent === "team-alpha-context"
    && document.querySelector(".topbar").textContent.indexOf("C:\\") === -1,
    "a Windows folder is named by its final folder name, never its drive or full path");
  await show("state_older_server");
  check(!("folder_name" in fixture.state_older_server)
    && $("barFolder").textContent === fixture.state_valid.folder_name
    && $("metaRoot").textContent === fixture.state_valid.folder_name
    && !/undefined/.test(document.querySelector(".topbar").textContent + $("metaRoot").textContent),
    "a console started before an update, which sends no folder name, still shows the folder name, never undefined");
  await show("state_valid");
  const govCount = fixture.state_valid.documents.filter((d) => d.kind === "governing").length;
  const candCount = fixture.state_valid.documents.filter((d) => d.kind === "candidate").length;
  const archivedDocs = fixture.state_valid.documents.filter((d) => d.kind === "archived");
  check($("metaContext").textContent === String(govCount), "the rail counts governing documents only");
  check($("contextMetaTitle").textContent === "Current Context"
    && /text-transform:\s*uppercase/.test(rule(css, ".rail-meta-title")) && !$("gitInfo") && !$("gitInfoToggle")
    && !$("gitDetailsToggleText") && fixture.state_valid.status.git.state === "not-checkout"
    && !$("metaGitLabel").hidden && $("metaGitLabel").textContent === "Git branch"
    && $("metaBranch").textContent === "Not a Git checkout"
    && $("metaChangedLabel").hidden && $("metaChanged").hidden && !$("gitDetailsToggle"),
    "the rail's heading reads CURRENT CONTEXT; outside a Git checkout it says Git branch: Not a Git checkout, with no count and no control");
  check($("contextStatus").hidden && !$("contextStatus").querySelector("#originUnknown")
    && insideOf($("originUnknown"), $("contextMapSection")) && !$("originUnknown").hidden
    && $("originUnknown").querySelector("strong").textContent === "Origin unknown."
    && $("originUnknown").textContent === "Origin unknown. These files are valid, but Charter has no local record of how this version was created or changed."
    && !$("originUnknown").getAttribute("role") && !$("originUnknown").querySelector("button"),
    "unknown origin is said plainly beside the context map — not as a banner above every view, and with nothing to repair");
  check(/display:\s*none/.test(rule(css, ".context-status[hidden]")) && /display:\s*grid/.test(rule(css, ".context-status")),
    "with nothing to say, the status band above every view takes no space: its grid display does not override hidden");

  console.log("\nEach list's count is shown once, and heard in words");
  check(navItem("governing").querySelector(".tally").textContent === `(${govCount})`
    && navItem("governing").querySelector(".tally").getAttribute("aria-hidden") === "true"
    && navItem("governing").querySelector(".sr-only").textContent === `: ${govCount} governing documents`,
    "Governing documents");
  check(navItem("candidates").querySelector(".tally").textContent === `(${candCount})`
    && navItem("candidates").querySelector(".sr-only").textContent === `: ${candCount} authority candidates`,
    "Authority candidates");
  check(!$("tallyArchive") && !$("tallyArchiveLabel"), "the private archive has no count: it is not shown");

  console.log("\nEach area has an address, and Back and Forward follow it");
  const before = addressBook.entries.length;
  const seen = [];
  for (const v of ["candidates", "settings", "governing"]) {
    await navTo(v);
    seen.push({ v, hash: location.hash, only: vm.runInThisContext("VIEWS").every((x) => $("view-" + x).hidden === (x !== v)),
      current: nav().filter((b) => b.getAttribute("aria-current") === "true").map((b) => b.dataset.view).join(),
      title: document.title });
  }
  check(seen.every((s) => s.hash === "#" + s.v && s.only && s.current === s.v)
    && addressBook.entries.length === before + 3,
    "each opens alone, at its own address, marked current, one history entry each");
  check(seen.map((s) => s.title).join(" | ")
    === "Authority Candidates — Charter | Settings — Charter | Governing Context — Charter",
    "the tab title names the area");
  goBack();
  await settle();
  check(location.hash === "#settings" && !$("view-settings").hidden
    && navItem("settings").getAttribute("aria-current") === "true", "Back returns to the area before");
  goForward();
  await settle();
  check(!$("view-governing").hidden, "and Forward returns");
  const viewFromAddress = vm.runInThisContext("viewFromAddress");
  const saved = addressBook.entries[addressBook.index];
  const names = ["#governing", "#candidates", "#settings", "#connect", "#nonsense", "#knowledge"].map((h) => {
    addressBook.entries[addressBook.index] = h;
    return viewFromAddress();
  });
  addressBook.entries[addressBook.index] = saved;
  check(names.join() === "governing,candidates,settings,connect,,", "a link names an area; anything else, none");

  /* ------------------------------------------------------- documents */

  console.log("\nGoverning documents and candidates cannot be confused");
  const governingView = $("view-governing");
  check(governingView.querySelector(".view-head h2").textContent === "Governing Context"
    && !governingView.querySelectorAll(".info-toggle").length
    && $("governingIntro").textContent === "Documents currently governing this Agent Context."
    && governingView.querySelectorAll(".lede").length === 1,
    "the area is Governing Context, with its one subtitle and no information control");
  const govRows = $("governingList").querySelectorAll(".doc");
  check(govRows.length === govCount && govRows.every((r) => r.classList.contains("is-authority")
    && !r.querySelectorAll(".chip").length && !/\bGoverning\b/.test(r.querySelector(".actions").textContent)
    && !/In the Agent Context folder/.test(r.textContent)
    && !/Private local state/.test(r.textContent)),
    "governing-document cards carry no redundant Governing badge, and do not repeat where agents read them");
  check(govRows.every((r) => r.querySelector(".path strong").textContent === "Filename: "
      && (!r.querySelector(".scope") || r.querySelector(".scope strong").textContent === "Scope: ")),
    "each governing card shows its path and scope after bold Filename: and Scope: labels");
  check(!/overflow|max-height/.test(rule(css, ".docs")) && !/overflow|max-height/.test(rule(css, ".record-group"))
    && !/overflow|max-height/.test(rule(css, "main")),
    "the governing list scrolls with the page: no nested scroll region");
  const alpha = rowOf("governingList", "Alpha");
  check(buttonSaying(alpha, "Read") && buttonSaying(alpha, "Revise…") && buttonSaying(alpha, "Withdraw in a change set…")
    && !buttonSaying(alpha, "Change in a change set…")
    && !buttonSaying(alpha, "Edit…") && !buttonSaying(alpha, "Retire…") && !buttonSaying(alpha, "Plan a change set…"),
    "a governing document is read, revised into a candidate, or withdrawn in a change set — never edited in place or retired");
  check(!document.querySelectorAll("button").some((b) => /Grant authority|Withdraw authority/.test(b.textContent)),
    "no button offers a direct grant or withdrawal");
  check(!$("governingList").textContent.includes("AGENT-CONTEXT.md"), "the map is never listed as a governing document");
  await navTo("candidates");
  check($("view-candidates").querySelector(".lede").textContent
    === "Candidates stay private until you make them governing.",
    "Authority candidates says, in one sentence, that they stay private until made governing");
  const gamma = rowOf("candidatesList", "Gamma rules");
  check(gamma && !/Authority candidate — not context/.test(gamma.textContent)
    && !/Private local state/.test(gamma.textContent) && !/Source:/.test(gamma.textContent)
    && !gamma.querySelector(".chip"),
    "a candidate card has no generic not-context badge, Source line, or private-local-state line");
  const gammaTitle = gamma.querySelector(".title-row");
  check(gammaTitle && gammaTitle.querySelector(".title").textContent === "Gamma rules"
    && gammaTitle.querySelector(".source-tag").textContent === "Created by person"
    && gammaTitle.children.length === 2,
    "it shows its friendly title followed immediately by one compact source tag");
  check(gamma.querySelector(".path strong").textContent === "Filename: "
    && /authority-candidates\//.test(gamma.querySelector(".path").textContent)
    && gamma.querySelector(".scope strong").textContent === "Scope: "
    && /white-space:\s*nowrap/.test(rule(css, "#candidatesList .doc .scope")),
    "its logical path follows a bold Filename: label, and its one-line scope a bold Scope: label");
  check(gamma.querySelector(".path").classList.contains("labelled") && gamma.querySelector(".scope").classList.contains("labelled")
    && /font-size:\s*\.85rem/.test(rule(css, ".doc .labelled"))
    && /font-family:\s*inherit/.test(rule(css, ".doc .path.labelled"))
    && /font-size:\s*inherit/.test(rule(css, ".doc .path.labelled span")),
    "the Filename: and Scope: rows share one text size, so their bold labels carry the same weight");
  check(buttonSaying(gamma, "Edit…") && buttonSaying(gamma, "Retire…") && buttonSaying(gamma, "Plan a change set…")
    && !buttonSaying(gamma, "Withdraw in a change set…") && !buttonSaying(gamma, "Change in a change set…"),
    "a candidate is edited, retired, or planned into a change set");

  /* Governed candidate lineage, source, comparison, and picker labels (human-only). */
  const betaRev = rowOf("candidatesList", "Beta revised");
  check(betaRev && /Revision of: Beta/.test(betaRev.textContent)
    && betaRev.querySelector(".source-tag").textContent === "Revision",
    "a revision candidate's card shows the governing document it revises, tagged Revision");
  const cmpBtn = buttonSaying(betaRev, "Compare with governing…");
  check(!!cmpBtn, "a revision candidate offers Compare with governing");
  await click(cmpBtn);
  check(!$("docViewer").hidden && /Compared with/.test($("docViewer").textContent)
    && serialize($("docViewer")).indexOf("Even clearer Beta") !== -1
    && document.querySelector(".rail").inert === true,
    "comparing a candidate opens the diff viewer with the focus trap");
  document.dispatch("keydown", { key: "Escape" });
  check($("docViewer").hidden && !document.querySelector(".rail").inert,
    "Escape closes the comparison and releases the focus trap");
  const synth = { kind: "candidate", path: "authority-candidates/x.md", title: "X", scope: "s",
    revises_path: "authoritative/a.md", revises_title: "Alpha", source_kind: "proposal", co_revisions: 2 };
  const synthCard = serialize(vm.runInThisContext("docRow")(synth));
  check(/Revision of: Alpha/.test(synthCard) && />Agent Proposal</.test(synthCard)
    && /Another revision candidate exists for this document\. 2 others/.test(synthCard)
    && synthCard.indexOf("Compare revisions") !== -1,
    "a card shows source, revision lineage, a competing-revision count, and Compare revisions");
  const tagOf = (c) => serialize(vm.runInThisContext("docRow")(Object.assign({ kind: "candidate",
    path: "authority-candidates/t.md", title: "T" }, c))).match(/class="source-tag">([^<]*)</);
  check(tagOf({ source_kind: "proposal", source_agent: "Claude" })[1] === "Proposed by: Claude"
    && tagOf({ source_kind: "proposal", source_agent: "chat-agent (import test)" })[1] === "Proposed by: chat-agent (import test)"
    && tagOf({ source_kind: "proposal", source_agent: "" })[1] === "Agent Proposal"
    && tagOf({ source_kind: "create" })[1] === "Created by person"
    && tagOf({ source_kind: "revise" })[1] === "Revision"
    && tagOf({ source_kind: "withdrawn" })[1] === "Withdrawn governing document"
    && !/Source unknown|Human Proposal/.test(serialize(vm.runInThisContext("docRow")({ kind: "candidate",
      path: "authority-candidates/u.md", title: "U", source_kind: "create" }))),
    "the source tag names an agent only when one is known, and never invents an identity");
  const pickLabel = vm.runInThisContext("candidateLabel")(
    { title: "X", source_kind: "proposal", revises_title: "Alpha", scope: "short scope",
      change_summary: "changes 1 line" }, true);
  check(/Agent Proposal/.test(pickLabel) && /revises .Alpha./.test(pickLabel) && /changes 1 line/.test(pickLabel)
    && !/short scope/.test(pickLabel),
    "a change-set picker label disambiguates a shared title by source, revision relationship and a short change summary");
  console.log("\nNo archive in normal views: retired and replaced documents stay private");
  check(archivedDocs.length > 0 && !$("archiveToggle") && !$("archiveList") && !$("archiveBody")
    && !document.querySelectorAll(".is-retired").length
    && !document.querySelectorAll(".doc").some((r) => archivedDocs.some((d) => (r.querySelector(".path") || { textContent: "" })
      .textContent.indexOf(d.path) !== -1))
    && !/Archived — not context/.test($("view-candidates").textContent),
    "archived documents exist in private state, but no normal view lists or counts them");

  console.log("\nAn empty list shows a 0, and no empty-state text");
  const kept = vm.runInThisContext("state.documents");
  global.__kept = kept;
  vm.runInThisContext("state.documents = state.documents.filter((d) => d.kind === 'governing')");
  vm.runInThisContext("renderShell(); renderKnowledge();");
  check(navItem("candidates").querySelector(".tally").textContent === "(0)" && $("candidatesList").hidden
    && !/No candidates|nothing here/i.test($("view-candidates").textContent),
    "with no candidates, the count is 0 and the list is simply absent");
  vm.runInThisContext("state.documents = state.documents.filter((d) => d.kind !== 'governing'); renderKnowledge();");
  check($("governingGroup").hidden && $("governingGroupLabel").textContent === "Governing Documents (0)",
    "with no governing document, its group is not shown");
  vm.runInThisContext("state.documents = __kept; renderShell(); renderKnowledge();");

  console.log("\nA long candidate scope is one line on its card, complete in Read and Edit");
  global.__long = Object.assign({}, kept.find((d) => d.path === fixture.candidate), { scope: fixture.cs_long_scope });
  vm.runInThisContext("state.documents = __kept.map((d) => d.path === __long.path ? __long : d); renderKnowledge();");
  const longRow = rowOf("candidatesList", __long.title);
  check(fixture.cs_long_scope.length > 400 && longRow.querySelector(".scope").textContent === "Scope: " + fixture.cs_long_scope,
    "the card holds the whole scope of hundreds of characters, for a screen reader");
  const candidateScopeRule = rule(css, "#candidatesList .doc .scope");
  check(/white-space:\s*nowrap/.test(candidateScopeRule) && /overflow:\s*hidden/.test(candidateScopeRule)
    && /text-overflow:\s*ellipsis/.test(candidateScopeRule) && /minmax\(0, 1fr\)/.test(rule(css, ".doc")),
    "on screen it is one line clipped with an ellipsis, so a long scope cannot make the card tall");
  check(!/nowrap/.test(rule(css, ".doc .scope")), "a governing document's scope is not clipped");
  check(!!buttonSaying(longRow, "Read") && !!buttonSaying(longRow, "Edit…"), "Read and Edit… stay on the card");
  vm.runInThisContext("state.documents = __kept; renderKnowledge();");
  const fullScope = fixture.drafts[fixture.candidate].scope;
  await click(buttonSaying(rowOf("candidatesList", "Gamma rules"), "Read"));
  check($("docViewer").textContent.indexOf(fullScope) !== -1, "Read shows the complete scope");
  await click(buttonSaying($("docViewer"), "Close"));
  await click(buttonSaying(rowOf("candidatesList", "Gamma rules"), "Edit…"));
  check($("formField-scope").value === fullScope, "and so does Edit");

  console.log("\nCandidate Edit: Cancel discards the edits and returns to Authority candidates");
  const plansBeforeCancel = calls.filter((c) => c.url === "/api/plan" || c.url === "/api/apply").length;
  const cancelEdit = buttonSaying($("review"), "Cancel");
  check(cancelEdit && cancelEdit.tagName === "BUTTON" && cancelEdit.getAttribute("type") === "button",
    "the form offers Cancel, a native button");
  $("formField-title").value = "Typed and abandoned";
  $("formField-scope").value = "Typed scope";
  await click(cancelEdit);
  check(!$("review").firstChild && calls.filter((c) => c.url === "/api/plan" || c.url === "/api/apply").length === plansBeforeCancel,
    "Cancel closes the form, previews nothing and writes nothing");
  check(!$("view-candidates").hidden && location.hash === "#candidates"
    && document.activeElement === $("view-candidates").querySelector("h2"),
    "it stays on Authority candidates, focus on its heading");
  await click(buttonSaying(rowOf("candidatesList", "Gamma rules"), "Edit…"));
  check($("formField-title").value === fixture.drafts[fixture.candidate].title && $("formField-scope").value === fullScope,
    "editing again starts from the saved candidate: the unsaved edits are gone");
  await navTo("governing");
  await vm.runInThisContext("startCandidateEdit")({ path: fixture.candidate });
  await settle();
  await click(buttonSaying($("review"), "Cancel"));
  check(!$("view-candidates").hidden && location.hash === "#candidates", "Cancel returns to Authority candidates from elsewhere too");
  await navTo("governing");
  await vm.runInThisContext("startCandidateEdit")({ path: fixture.candidate }, { returnTo: "0123456789abcdef" });
  await settle();
  await click(buttonSaying($("review"), "Cancel"));
  check(!$("view-governing").hidden && !$("review").firstChild,
    "opened from a change set's Edit details, Cancel only closes the form: the change set's controls are unchanged");
  await navTo("candidates");

  console.log("\nChange Sets in the navigation counts active drafts only");
  const csTally = navItem("changesets").querySelector(".tally");
  check(fixture.state_valid.change_sets.active === 0 && csTally.textContent === "(0)" && csTally.getAttribute("aria-hidden") === "true"
    && $("tallyChangeSetsLabel").textContent === ": 0 active drafts",
    "with no draft, it shows 0, said once in words for assistive technology");
  const mixedStates = fixture.cs_mixed_list.drafts.map((d) => d.state).sort().join();
  check(mixedStates === "abandoned,active,applied" && fixture.cs_mixed_state.change_sets.active === 1,
    "the server counts one of an active draft, an applied receipt and an abandoned draft");
  check(fixture.cs_mixed_list.drafts.filter(vm.runInThisContext("isActiveDraft")).length === 1
    && fixture.cs_mixed_list.drafts.find(vm.runInThisContext("isActiveDraft")).state === "active",
    "the page's own rule agrees: only the active draft");
  currentState = Object.assign({}, fixture.state_valid, { change_sets: fixture.cs_mixed_state.change_sets });
  csListAnswer = fixture.cs_mixed_list;
  await navTo("changesets");
  check($("changeSetList").querySelectorAll(".changeset-row").length === 1
    && csTally.textContent === "(1)" && $("tallyChangeSetsLabel").textContent === ": 1 active draft",
    "the index lists only the active draft; the navigation counts 1");

  console.log("\nChange Sets index: active drafts, and no history in the normal view");
  const topGroups = () => $("changeSetList").children.filter((n) => n.classList.contains("record-group"));
  const summaryOf = (groups) => groups.map((g) => {
    const label = g.querySelector(".record-group-label");
    return `${label.textContent}:${g.querySelectorAll(".changeset-row").map((r) => r.querySelector(".title-row .chip").textContent).join("+")}`;
  }).join(" | ");
  const groupNamed = (groups, name) => groups.find((g) => new RegExp(name).test(g.querySelector(".record-group-label").textContent));
  check(summaryOf(topGroups()) === "Active Drafts (1):active",
    "Active Drafts is the one group: each row's status label follows its title");
  check(!$("csHistoryToggle") && !$("csHistoryBody") && !/Change History|Applied Change Sets|Discarded Drafts/.test($("changeSetList").textContent)
    && !$("changeSetList").querySelectorAll(".changeset-row").some((r) => /applied|abandoned|discarded/.test(r.textContent)),
    "no Change History, applied change-set list or Discarded Drafts group: their records stay private");
  check($("changeSetList").querySelectorAll(".changeset-row").every((r) => !r.querySelector(".actions .chip")
      && r.querySelector(".title-row").children[0].classList.contains("title")),
    "no status label sits beside a row's action button");
  csListAnswer = Object.assign({}, fixture.cs_mixed_list,
    { drafts: fixture.cs_mixed_list.drafts.filter((d) => d.state !== "active") });
  await navTo("candidates");
  await navTo("changesets");
  check(!topGroups().length && !!$("noChangeSets") && csTally.textContent === "(0)",
    "with only applied and abandoned records, the normal view shows the empty-state message");
  csListAnswer = fixture.cs_unreadable_list;
  await navTo("candidates");
  await navTo("changesets");
  check(summaryOf(topGroups()) === "Active Drafts (1):active | Unreadable Records (1):unreadable"
    && !$("csHistoryToggle") && !$("noChangeSets")
    && !!buttonSaying(groupNamed(topGroups(), "Unreadable Records"), "Delete") && csTally.textContent === "(1)",
    "an unreadable record is never hidden: listed after the active drafts, still deletable and not counted");
  const unreadableOnly = Object.assign({}, fixture.cs_unreadable_list,
    { drafts: fixture.cs_unreadable_list.drafts.filter((d) => d.unreadable) });
  csListAnswer = unreadableOnly;
  await navTo("candidates");
  await navTo("changesets");
  check(summaryOf(topGroups()) === "Unreadable Records (1):unreadable" && !$("noChangeSets"),
    "with only an unreadable record, its group is shown instead of the empty-state message");
  csListAnswer = Object.assign({}, fixture.cs_mixed_list, { drafts: [] });
  await navTo("candidates");
  await navTo("changesets");
  check(!topGroups().length && !!$("noChangeSets")
    && $("noChangeSets").textContent === "No open change sets." && csTally.textContent === "(0)",
    "with no change set at all, the empty state reads exactly “No open change sets.”");
  csListAnswer = null;
  currentState = fixture.state_valid;
  await navTo("candidates");
  check(csTally.textContent === "(0)", "the count follows the state on every view");

  console.log("\nThe shared section break: a gap, a thin divider and a compact label with a count");
  const groupRule = rule(css, ".record-group");
  check(/margin-top:\s*1(\.\d+)?rem/.test(groupRule) && /border-top:\s*1px solid/.test(groupRule)
    && /padding-top/.test(groupRule) && /font-size:\s*\.8rem/.test(rule(css, ".record-group-label")),
    "one pattern: a modest gap, a thin divider, and a small label");
  check(/display:\s*none/.test(rule(css, ".record-group[hidden]")), "an empty group is not shown at all");

  console.log("\nGoverning documents: the map is a reference block, then the labelled list");
  const mapSiblings = $("contextMapSection").parentNode.children;
  const govGroup = $("governingGroup");
  const govLabel = $("governingGroupLabel");
  check(mapSiblings[mapSiblings.indexOf($("contextMapSection")) + 1] === govGroup
    && govGroup.classList.contains("record-group") && $("governingList").parentNode === govGroup
    && !govGroup.querySelector("#contextMapSection"),
    "the map is a separate block; the list follows it in its own group");
  check(govLabel.tagName === "H3" && govLabel.textContent === `Governing Documents (${govCount})`
    && govGroup.getAttribute("aria-labelledby") === "governingGroupLabel",
    "the group is labelled with its count, and named by that label for assistive technology");
  check(!/margin:\s*1rem 0 1/.test(rule(css, ".context-map")), "the gap comes from the section break, not the map");

  console.log("\nThe context map is generated, and said to match only when checked");
  const mapBox = $("contextMapSection");
  check(mapBox.parentNode === governingView && $("contextMapKind").textContent === "Generated — not a governing document",
    "it sits with the governing documents, and is not one of them");
  check($("contextMapState").textContent === "Map current" && $("contextMapState").querySelector(".chip").classList.contains("ok")
    && $("btnRebuildContext").hidden,
    "valid: its status reads Map current, in the positive treatment, and Rebuild is not offered");
  const mapLabelFor = (issues) => {
    vm.runInThisContext("(i) => { state = Object.assign({}, state, { status: Object.assign({}, state.status, { agents_served: false, issues: i }) }); renderContextMap(); }")(issues);
    return [$("contextMapState").textContent, $("contextMapState").querySelector(".chip").className];
  };
  const keptStatus = vm.runInThisContext("state");
  const notChecked = mapLabelFor([{ level: "error", kind: "document", path: "authoritative/a.md", message: "No title." }]);
  const strayOnly = mapLabelFor([{ level: "error", kind: "stray", path: "notes.txt", message: "Not part of it." }]);
  const outOfDate = mapLabelFor([{ level: "error", kind: "generated", path: "AGENT-CONTEXT.md", message: "Stale." }]);
  vm.runInThisContext("(s) => { state = s; renderContextMap(); }")(keptStatus);
  check(notChecked[0] === "Map not checked" && /\bwarn\b/.test(notChecked[1])
    && strayOnly[0] === "Map current" && outOfDate[0] === "Map out of date" && /\bstale\b/.test(outOfDate[1])
    && /background:/.test(rule(css, ".chip.warn")),
    "a governing-document problem reads Map not checked (warning); a stray alone leaves the map current; a stale map reads Map out of date");
  check(!/Agents are served|Agents are refused|Matches the governing documents|Does not match the governing documents/.test(serialize(document.body)),
    "the old status wording appears nowhere");
  const mapRow = mapBox.querySelector(".context-map-row");
  check(mapRow.children[0] === $("contextMapTitle") && mapRow.children[1] === $("contextMapState")
    && !mapRow.querySelectorAll("button").length && $("btnViewContext").parentNode.classList.contains("context-map-actions")
    && $("btnViewContext").parentNode !== mapRow,
    "its status label immediately follows its title, and its actions sit apart, never beside a label");
  check(!$("agentGuidanceSummary") && !/Agent guidance in the map/.test($("contextMapSection").textContent),
    "the Context Map carries no editorial line about agent guidance: Settings shows it");
  const beforeView = calls.length;
  await click($("btnViewContext"));
  check(calls.slice(beforeView).length === 1 && JSON.stringify(lastCall("/api/preview").body) === JSON.stringify({ source: "context" }),
    "View agent context asks for the map by name, and nothing else");
  check(/Generated routing map — not a governing document/.test($("docViewer").querySelector(".reader-banner").textContent)
    && $("docViewer").querySelector(".reader-path").textContent === "AGENT-CONTEXT.md",
    "it opens under a banner saying it is generated");
  check(document.querySelector(".rail").inert === true && $("main").inert === true,
    "while the reader is open the rail and main are inert, so focus is trapped in the dialog");
  await click(buttonSaying($("docViewer"), "Close"));
  check($("docViewer").hidden && document.activeElement === $("btnViewContext"), "Close returns focus to View agent context");
  check(!document.querySelector(".rail").inert && !$("main").inert,
    "closing the reader releases the focus trap");

  /* ------------------------------------------------------------- the viewer */

  console.log("\nRead renders Markdown, read-only");
  const richRow = rowOf("governingList", "Suppliers");
  const readRich = buttonSaying(richRow, "Read");
  const beforeRead = calls.length;
  await click(readRich);
  check(calls.slice(beforeRead).length === 1
    && JSON.stringify(calls[beforeRead].body) === JSON.stringify({ source: "document", path: fixture.rich }),
    "Read asks for that document by the path the page lists — nothing else");
  const viewer = serialize($("docViewer"));
  check(!$("docViewer").hidden && viewer.indexOf("<h2>Criteria</h2>") !== -1 && viewer.indexOf("<table") !== -1
    && viewer.indexOf("md-code") !== -1 && viewer.indexOf("<strong>") !== -1 && viewer.indexOf("<li>") !== -1,
    "headings, tables, code, emphasis and lists are rendered");
  check(viewer.indexOf("md-meta") !== -1 && $("docViewer").textContent.indexOf("---") === -1,
    "front matter is shown as metadata, not as its fence");
  check(viewer.indexOf("&lt;script&gt;") !== -1 && viewer.indexOf("<script") === -1,
    "HTML inside a document is shown as text, never run");
  check(/Governing document — current context/.test($("docViewer").querySelector(".reader-banner").textContent),
    "a governing document's banner says it is current context");
  check(!/follow/i.test($("docViewer").querySelector(".reader-banner").textContent),
    "the banner does not claim agents follow it: Charter cannot make them");
  check($("docViewer").querySelector("article").getAttribute("role") === "dialog"
    && document.activeElement === buttonSaying($("docViewer"), "Close"),
    "it is a dialog, with focus on Close");
  await click(buttonSaying($("docViewer"), "View source"));
  check($("docViewer").querySelector("pre.code").textContent === fixture.previews[fixture.rich].text,
    "View source shows the text exactly");
  document.dispatch("keydown", { key: "Escape" });
  await settle();
  check($("docViewer").hidden && document.activeElement === readRich, "Escape closes it, focus back on Read");
  await click(readRich);
  $("docViewer").dispatch("click", { target: $("docViewer") });
  check($("docViewer").hidden, "a click outside the document closes it too");
  await click(readRich);
  await navTo("candidates");
  check($("docViewer").hidden && $("docViewer").childNodes.length === 0, "navigating closes it");
  await click(buttonSaying(rowOf("candidatesList", "Gamma rules"), "Read"));
  check(/Authority candidate — not context/.test($("docViewer").querySelector(".reader-banner").textContent)
    && /Agents never see it/.test($("docViewer").querySelector(".reader-banner").textContent),
    "a candidate's banner says it is not context, and private");
  await click(buttonSaying($("docViewer"), "Close"));

  /* ----------------------------------------------------- authority actions */

  console.log("\nPlan a change set from a candidate: it opens a change set that includes it, undecided");
  const createsBefore = () => calls.filter((c) => c.url === "/api/changeset/create").length;
  const noGoverningApply = () => !calls.some((c) => c.url === "/api/apply" && GOVERNING_KINDS.includes(c.body.kind));
  const revised = fixture.state_valid.documents.find((d) => d.title === "Beta revised");
  const plain = fixture.state_valid.documents.find((d) => d.path === fixture.candidate);
  check(revised && revised.revises_path === "authoritative/b.md" && plain.revises_path === ""
    && fixture.state_valid.documents.filter((d) => d.kind === "candidate" && d.revises_path).length === 1,
    "the server says which candidate came from Revise…, and from which governing document");
  let made = createsBefore();
  const plansBeforeRevised = calls.filter((c) => c.url === "/api/plan").length;
  await click(buttonSaying(rowOf("candidatesList", "Beta revised"), "Plan a change set…"));
  check(createsBefore() === made + 1
    && JSON.stringify(lastCall("/api/changeset/create").body) === JSON.stringify({ start: { candidate: revised.path } }),
    "it starts a change set that includes that candidate, and nothing more");
  check(!$("changeSetEditor").hidden && $("changeSetIndex").hidden && $("review").childNodes.length === 0
    && $("csCandidates").querySelectorAll(".cs-row").length === 1
    && $("csCandidates").querySelector(".cs-row .title").textContent === "Beta revised",
    "its editor opens with that one candidate, a compact row led by its title, in place of the index");
  const decision0 = $("csDecision-0");
  check(decision0.tagName === "SELECT" && decision0.value === ""
    && decision0.options.map((o) => `${o.value}=${o.textContent}`).join("|")
      === "=Choose a decision|replace=Replace|govern-alongside=Govern alongside"
    && decision0.getAttribute("aria-label") === "Decision for “Beta revised”"
    && !$("csTarget-0") && $("csPreview").disabled,
    "its decision is one dropdown, starting unselected, offering Replace and Govern alongside; nothing to preview yet");
  check(!$("csPlan").querySelectorAll("input").some((i) => i.type === "radio")
    && !$("csPlan").querySelectorAll("option").some((o) => /^(revise|retain)$/.test(o.value))
    && !/It takes over from one governing document|Everything that governs today keeps governing/.test($("csPlan").textContent)
    && !/Retain all other governing documents/.test($("changeSetEditor").textContent),
    "no radio buttons, no permanently visible decision explanations, no Revise or Retain decision");
  check(labelFor($("csPlan"), "csTitle").textContent === "Name" && !$("csTitleHint")
    && $("csPlan").querySelectorAll("h4").map((h) => h.textContent).join("|") === "Candidates|Withdrawals|Change Set Summary|Readiness",
    "the plan reads Name, Candidates, Withdrawals, Change Set Summary and Readiness");
  check(!$("csRetained") && !/Retained Governing Documents/.test($("changeSetEditor").textContent),
    "Build Change Set lists no retained documents: they are retained without a decision");
  check($("csWithdrawalsHint").textContent === "Withdrawn documents become authority candidates."
    && $("csWithdrawals") === null && !!$("csAddWithdrawal"),
    "Withdrawals has one line of explanation, and a governing document can be added for withdrawal");
  const wRow = vm.runInThisContext("changeSetWithdrawals")({ withdrawals: [{ path: "authoritative/a.md", title: "Alpha",
    governs: false }], governing: [], plan_candidates: [] }, true).querySelector(".cs-row");
  check(wRow.querySelector(".title-row").children[0].textContent === "Alpha"
    && wRow.querySelector(".title-row .chip").textContent === "No longer governs"
    && !wRow.querySelector(".title-row").querySelectorAll("button").length && !!buttonSaying(wRow, "Remove"),
    "a withdrawal's status label immediately follows its title, apart from its Remove button");
  check(!$("changeSetEditor").querySelectorAll(".info-toggle").length
    && !fieldsIn($("changeSetEditor")).some((i) => i.getAttribute("placeholder")),
    "no information icons in the build screen, and no placeholder text in any field");
  check(!/position:\s*sticky|overflow|max-height/.test(rule(css, ".cs-review"))
    && !/overflow|max-height/.test(rule(css, ".cs-item")) && !/max-height|overflow/.test(rule(css, ".report-grid")),
    "the page scrolls as a whole: no candidate row or review panel scrolls on its own");
  check(!$("confirmPhrase") && calls.filter((c) => c.url === "/api/plan").length === plansBeforeRevised && noGoverningApply(),
    "no phrase is asked for and nothing is previewed or applied until the change set is");
  csNext = fixture.cs_start_replace_pending;
  decision0.value = "replace";
  decision0.dispatch("change");
  await settle();
  check(JSON.stringify(lastCall("/api/changeset/update").body.decisions)
      === JSON.stringify({ [revised.path]: { decision: "replace", target: "" } }),
    "choosing Replace declares only that, with no document chosen");
  const target0 = $("csTarget-0");
  const originOption = target0.options[1];
  check($("csDecision-0").value === "replace" && target0 && target0.value === ""
    && target0.options[0].textContent === "Choose the document it replaces"
    && originOption.value === "authoritative/b.md" && originOption.textContent === "Beta — suggested: the document this was revised from"
    && target0.options.slice(2).every((o) => !/suggested/.test(o.textContent))
    && target0.options.slice(1).map((o) => o.value).sort().join()
      === fixture.state_valid.documents.filter((d) => d.governing).map((d) => d.path).sort().join()
    && $("csPreview").disabled,
    "only once Replace is chosen does the target appear, unselected, its origin first as a labelled suggestion");
  csNext = fixture.cs_start_replaced;
  $("csTarget-0").value = "authoritative/b.md";
  $("csTarget-0").dispatch("change");
  await settle();
  check(JSON.stringify(lastCall("/api/changeset/update").body.decisions)
      === JSON.stringify({ [revised.path]: { decision: "replace", target: "authoritative/b.md" } })
    && $("csTarget-0").value === "authoritative/b.md" && !$("csPreview").disabled,
    "choosing the document completes the plan, ready to preview");
  check($("csTargetSelected-0") && !$("csTargetSelected-0").hidden
    && $("csTargetSelected-0").textContent === "Selected: Replaces “Beta”"
    && $("csTarget-0").getAttribute("aria-describedby") === "csTargetSelected-0"
    && /flex-basis:\s*100%/.test(rule(css, ".cs-row-controls select.cs-target")),
    "the document it replaces has a line of its own, and is said in full beneath it");
  check($("csScopeLine-0").classList.contains("cs-scope-oneline")
    && /^Scope: Blank — inherits the replaced document's scope$/.test($("csScopeLine-0").textContent)
    && !$("csScopeToggle-0") && !$("csCandidates").querySelectorAll("dl").length
    && !/Full scope and comparison/.test($("csCandidates").textContent),
    "the row shows one line of scope, with no comparison disclosure or table inside it");
  const viewDetails = $("csViewDetails-0");
  check(viewDetails.tagName === "BUTTON" && viewDetails.textContent === "View details", "an explicit View details action");
  await click(viewDetails);
  check(/^Details: Beta revised$/.test($("review").querySelector("h3").textContent)
    && /Candidate's scope[\s\S]*Current scope[\s\S]*Scope after/.test($("csDetails").textContent)
    && /\(inherited\)/.test($("csDetails").textContent) && /Revise/.test($("csDetails").textContent)
    && !!$("csDetailsRead") && !!$("csDetailsCompare"),
    "View details opens the complete candidate and its scope comparison, on request");
  vm.runInThisContext("closeReview")();
  await vm.runInThisContext("closeChangeSet")();
  await navTo("candidates");

  console.log("\nA change set started from a candidate is previewed, confirmed and applied as a change set");
  await click(buttonSaying(rowOf("candidatesList", "Gamma rules"), "Plan a change set…"));
  check(JSON.stringify(lastCall("/api/changeset/create").body) === JSON.stringify({ start: { candidate: fixture.candidate } })
    && !$("changeSetEditor").hidden && fixture.cs_start_alongside.plan_candidates.length === 1
    && fixture.cs_start_alongside.draft.untitled && $("csTitle").value === "",
    "the change set includes the candidate alone, and its Name stays empty — never named for it");
  csNext = fixture.cs_start_ready;
  $("csDecision-0").value = "govern-alongside";
  $("csDecision-0").dispatch("change");
  await settle();
  check(JSON.stringify(lastCall("/api/changeset/update").body.decisions)
      === JSON.stringify({ [fixture.candidate]: { decision: "govern-alongside", target: "" } })
    && !$("csTarget-0") && /^Scope: /.test($("csScopeLine-0").textContent) && !$("csPreview").disabled,
    "Govern alongside needs no document, and the plan is ready to preview");
  const priorConfirm = global.confirm;
  let discardMsg = null;
  global.confirm = (m) => { discardMsg = m; return false; };
  const discardsBefore = calls.filter((c) => c.url === "/api/changeset/abandon").length;
  check(!!$("csDiscard") && $("csDiscard").textContent === "Discard draft"
    && !buttonSaying($("changeSetEditor"), "Abandon") && !buttonSaying($("changeSetEditor"), "Delete draft"),
    "the active draft offers Discard draft, with no Abandon or Delete draft beside it");
  await click($("csDiscard"));
  check(/^Discard the private draft “.+”\? It will be discarded\./.test(discardMsg || "")
    && /no candidate or governing context changes\./.test(discardMsg) && !/Change History|Discarded Drafts/.test(discardMsg)
    && calls.filter((c) => c.url === "/api/changeset/abandon").length === discardsBefore
    && !$("changeSetEditor").hidden,
    "Discard draft asks once, saying the private draft will be discarded; declined, nothing happens");
  let prompts = 0;
  global.confirm = () => { prompts += 1; return true; };
  const discarded = JSON.parse(JSON.stringify(fixture.cs_start_ready));
  discarded.draft.state = "abandoned";
  csNext = discarded;
  await click($("csDiscard"));
  await settle();
  check(prompts === 1 && calls.filter((c) => c.url === "/api/changeset/abandon").length === discardsBefore + 1
    && lastCall("/api/changeset/abandon").body.id === fixture.cs_start_ready.draft.id
    && !$("changeSetIndex").hidden && $("changeSetEditor").hidden
    && !calls.some((c) => c.url === "/api/changeset/delete") && /^Discarded the private draft/.test(toastNow().textContent),
    "confirmed once, it discards the draft at once and returns to Change Sets, with no second confirmation or delete");
  global.confirm = priorConfirm;
  clearToasts();
  await vm.runInThisContext("planFor")("changeset", fixture.start_request, { applyLabel: "Apply" });

  console.log("\nPreviews list files first, each collapsed until opened");
  check(JSON.stringify(lastPlan().body) === JSON.stringify({ kind: "changeset", request: fixture.start_request }),
    "the preview is of the change set, exactly");
  const toggles = fileToggles($("review"));
  const reasons = $("review").querySelectorAll(".file-toggle .why").map((n) => n.textContent);
  check(toggles.length === fixture.start_plan.changes.length
    && reasons.includes("Agent Context — what agents read") && reasons.includes("Private local state — not agent-visible"),
    "one item per file, each saying whether agents will read it");
  check(expanded($("review")).length === 0 && toggles.every((b) => regionOf(b).hidden
    && regionOf(b).getAttribute("role") === "region"), "every file is collapsed, its diff a labelled region");
  await click(toggles[0]);
  check(expanded($("review")).length === 1 && !regionOf(toggles[0]).hidden, "one click opens one file");
  await click(buttonSaying($("review"), "Expand all"));
  check(expanded($("review")).length === toggles.length, "Expand all opens every file");
  await click(buttonSaying($("review"), "Collapse all"));
  check(expanded($("review")).length === 0, "Collapse all closes them");
  check(!$("governingBeforeAfter") && !$("setCompare") && !/Governing Now|Governing After/.test($("review").textContent),
    "a change set's preview never shows the governing set before and after");
  check(!/Document dates are assigned|written as one action|does not stage, commit|receipt is kept privately|confirmed in words/
      .test($("review").textContent),
    "and no note that only explains mechanics");

  console.log("\nA change set is confirmed in words, once, and applied by its own route");
  check(labelFor($("review"), "confirmPhrase").textContent === "Type “change governing context” once to apply the whole change set",
    "the typed phrase is asked for here, at the change set's preview");
  type($("confirmPhrase"), "change governing context");
  await click($("btnApply"));
  const startApplied = lastCall("/api/changeset/apply");
  check(startApplied && startApplied.body.id === fixture.start_request.draft_id
    && startApplied.body.revision === fixture.start_request.draft_revision
    && startApplied.body.confirm === "change governing context" && startApplied.body.plan_id === fixture.start_plan.plan_id,
    "applying sends the typed phrase to the change set's own route, pinned to the preview shown");
  check(noGoverningApply(), "and never to the general apply route");
  check($("review").childNodes.length === 0 && toastNow() && /Git is untouched: commit it when you choose/.test(toastNow().textContent)
    && /applied as one action/.test(toastNow().textContent) && !!buttonSaying(toastNow(), "View details"),
    "the preview closes; the message says Git is left to the person, with details");
  check(!$("changeSetEditor").hidden && $("csAppliedStatus").textContent === "Change set applied",
    "the change set is shown as its receipt");
  check(document.activeElement === $("csTitleText"),
    "applying a change set moves focus to its receipt heading, not <body>");
  await click(buttonSaying(toastNow(), "View details"));
  check($("recordedPanel") && /Written to the Agent Context folder/.test($("recordedPanel").textContent),
    "View details shows what was written");
  vm.runInThisContext("closeReview")();
  clearToasts();
  await vm.runInThisContext("closeChangeSet")();
  check(document.activeElement === $("view-changesets").querySelector("h2"),
    "leaving the change-set editor returns focus to the Change Sets heading, not <body>");

  console.log("\nA governing document: withdrawn in an ordinary change set; Retire is an ordinary confirmation");
  await navTo("governing");
  made = createsBefore();
  const plansBeforeWithdraw = calls.filter((c) => c.url === "/api/plan").length;
  await click(buttonSaying(rowOf("governingList", "Beta"), "Withdraw in a change set…"));
  check(createsBefore() === made + 1
    && JSON.stringify(lastCall("/api/changeset/create").body) === JSON.stringify({ start: { withdraw: "authoritative/b.md" } }),
    "Withdraw in a change set… starts a change set withdrawing that document alone");
  check(!$("changeSetEditor").hidden && $("csWithdrawals").querySelectorAll(".cs-row").length === 1
    && /Beta/.test($("csWithdrawals").textContent) && !!$("csAddCandidate") && !$("csCandidates")
    && !$("csPreview").disabled && !$("csRetained"),
    "its editor lists the withdrawal in the ordinary sections, others retained without being listed, ready to preview");
  check(!$("confirmPhrase") && calls.filter((c) => c.url === "/api/plan").length === plansBeforeWithdraw && noGoverningApply(),
    "the phrase comes only at its preview");
  await vm.runInThisContext("closeChangeSet")();
  await navTo("governing");
  check(!buttonSaying(rowOf("governingList", "Beta"), "Change in a change set…"),
    "a governing document offers no other change-set start: a change begins from a candidate, made with Revise…");
  await navTo("candidates");
  await click(buttonSaying(rowOf("candidatesList", "Gamma rules"), "Retire…"));
  check(lastPlan().body.kind === "retire" && requestKeys() === JSON.stringify(["candidate"]) && !$("confirmPhrase"),
    "retiring a candidate asks for no phrase");
  await click($("btnApply"));
  check(lastCall("/api/apply").body.confirm === true, "and applies with an ordinary confirmation");
  clearToasts();

  console.log("\nEdit a candidate: its title, scope and text, nothing else");
  await click(buttonSaying(rowOf("candidatesList", "Gamma rules"), "Edit…"));
  check(lastCall("/api/draft").body.path === fixture.candidate
    && JSON.stringify(labelsIn($("review")).map((l) => l.split(" —")[0])) === JSON.stringify(["Title", "Scope", "Text"]),
    "it starts from the candidate's own title, scope and text");
  check(/changes nothing agents read/.test($("review").textContent), "and says it changes nothing agents read");
  check(compactScope($("review"), "formField-scope", "formHint-scope"),
    "Edit…'s scope field is the compact Scope control: its label, one helper, no information icon or placeholder");
  await click(buttonSaying($("review"), "Preview the change"));
  check(lastPlan().body.kind === "edit-candidate" && requestKeys() === JSON.stringify(["body", "candidate", "scope", "title"]),
    "it previews a change to the candidate only");
  vm.runInThisContext("closeReview")();

  console.log("\nRevise: a candidate from a governing document, which keeps governing");
  await navTo("governing");
  const plansBeforeRevise = calls.filter((c) => c.url === "/api/plan").length;
  await click(buttonSaying(rowOf("governingList", "Alpha"), "Revise…"));
  const draft = fixture.drafts[fixture.governing];
  check(JSON.stringify(lastCall("/api/draft").body) === JSON.stringify({ path: fixture.governing })
    && $("formField-title").value === draft.title && $("formField-scope").value === draft.scope
    && $("formField-body").value === draft.body && draft.body.indexOf("authority:") === -1,
    "it starts from the document's current title, scope and text, without front matter");
  check(/Filing creates a new authority candidate — not context\./.test($("reviseNotice").textContent)
    && $("reviseNotice").textContent.indexOf(`keeps governing at ${fixture.governing}, unchanged`) !== -1
    && calls.filter((c) => c.url === "/api/plan").length === plansBeforeRevise,
    "it says the document keeps governing, and plans nothing by itself");
  check(/keeps governing at .+, unchanged, until a change set you apply replaces it with the candidate\.$/
      .test($("reviseNotice").textContent)
    && !/revise it with the candidate in a change set/.test($("reviseNotice").textContent),
    "it says a change set replaces the document with the revision, never that a change set revises it");
  const issueItem = vm.runInThisContext("issueItem");
  const general = issueItem({ level: "error", path: "", general: true, fix: "",
    message: "Nothing to save: these are already this Agent Context's settings." });
  const located = issueItem({ level: "error", path: "", message: "A stray file.", fix: "" });
  check(general.textContent === "Nothing to save: these are already this Agent Context's settings."
    && !general.querySelector("code") && /^folder — /.test(located.textContent),
    "a plan's own problem, such as saving unchanged settings, reads as a plain sentence, never “folder — …”");
  check(compactScope($("review"), "formField-scope", "formHint-scope"),
    "Revise…'s scope field is the compact Scope control: its label, one helper, no information icon or placeholder");
  $("formField-scope").value = "Bookings and holds";
  await click(buttonSaying($("review"), "Preview the candidate"));
  check(lastPlan().body.kind === "revise" && requestKeys() === JSON.stringify(["body", "path", "scope", "title"])
    && lastPlan().body.request.scope === "Bookings and holds",
    "it previews a candidate from the title, scope and text as edited");
  check(!!buttonSaying($("review"), "File as candidate") && !$("confirmPhrase"), "filed as a candidate, with no phrase");
  vm.runInThisContext("closeReview")();

  /* ------------------------------------------------------------ Create candidate */

  console.log("\nCreate candidate is an action on Authority candidates");
  await navTo("candidates");
  const head = $("view-candidates").querySelector(".view-head");
  check(head.children.indexOf($("btnAddDocument")) === head.children.indexOf(head.querySelector("h2")) + 1
    && !["governing", "settings"].some((v) => $("view-" + v).querySelector("#btnAddDocument")),
    "Create candidate sits beside the Authority candidates heading, and nowhere else");
  const beforeAdd = addressBook.index;
  await click($("btnAddDocument"));
  check(!$("view-intake").hidden && location.hash === "#intake" && addressBook.index === beforeAdd + 1
    && document.title === "Create Candidate — Charter"
    && nav().filter((b) => b.getAttribute("aria-current") === "true").map((b) => b.dataset.view).join() === "candidates"
    && navItem("candidates").classList.contains("ancestor"),
    "it opens at #intake, with Authority candidates marked as the way to it, and current to assistive technology");
  goBack();
  await settle();
  check(!$("view-candidates").hidden && !navItem("candidates").classList.contains("ancestor"), "Back returns to Authority candidates");
  goForward();
  await settle();
  check(!$("view-intake").hidden && navItem("candidates").getAttribute("aria-current") === "true",
    "and Forward to Create candidate again, Authority candidates still current");
  check(!$("intakeLede") && !$("view-intake").querySelector(".lede") && !$("candidateNote")
    && !/private local state/i.test($("view-intake").textContent),
    "it has no long introduction and no repeated private-local-state wording");
  const renderIntake = vm.runInThisContext("renderIntakeForm");
  const realState = vm.runInThisContext("state");
  vm.runInThisContext("(s) => { state = s; }")(Object.assign({}, realState, { pdf_support: false }));
  renderIntake();
  check(!/PDF/.test($("dropText").textContent) && !/\.pdf/.test($("file").getAttribute("accept"))
    && /\.docx/.test($("file").getAttribute("accept")) && /PDF needs the optional pypdf package/.test($("dropHint").textContent),
    "without PDF support, the drop target and the file picker do not offer PDF, and the hint says why");
  vm.runInThisContext("(s) => { state = s; }")(Object.assign({}, realState, { pdf_support: true }));
  renderIntake();
  check(/PDF/.test($("dropText").textContent) && /\.pdf/.test($("file").getAttribute("accept")),
    "with it, they do");
  vm.runInThisContext("(s) => { state = s; }")(realState);
  renderIntake();

  console.log("\nCreate Candidate: choosing a file, then one calm form like Edit…");
  check(!$("stepFile").hidden && $("stepConvert").hidden && !$("stepName")
    && $("stepFile").querySelectorAll("button").map((b) => b.textContent).join() === "Choose a file"
    && !!$("drop") && !$("stepFile").querySelector("h3")
    && !$("view-intake").querySelectorAll(".step").length && !/data-step|Choose a file in step 1 first/.test(serialize($("view-intake")))
    && /display:\s*none/.test(rule(css, ".intake-pick[hidden], .intake-form[hidden]")),
    "before a file is chosen, only the drop area and Choose a file: no editor, other section, step number or waiting note");
  check(!fieldsIn($("view-intake")).some((n) => n.getAttribute("placeholder")),
    "and no placeholder text anywhere in the form");
  await vm.runInThisContext("stageFile")({ name: "site-notes.md" });
  await settle();
  const intakeForm = $("stepConvert");
  check(!intakeForm.hidden && $("stepFile").hidden && intakeForm.querySelectorAll("h3").length === 1
    && intakeForm.querySelector("h3").textContent === "Review Converted Document" && !intakeForm.querySelectorAll(".step").length,
    "once the file is converted, one form under Review Converted Document takes the drop area's place, with no numbered steps");
  check(JSON.stringify(intakeForm.children.map((n) => n.tagName === "H3" ? "heading"
      : n.classList.contains("intake-file") ? "file" : n.getAttribute("id") === "convertNotes" ? "notes"
      : n.getAttribute("id") === "frontMatterNote" ? "front-matter"
      : n.classList.contains("actions") ? n.querySelector("button").textContent
      : n.querySelector("label").textContent))
      === JSON.stringify(["heading", "file", "notes", "front-matter", "Title", "Scope", "Text", "Preview changes"]),
    "in order: the file, its notes, Title, Scope, Text, and Preview changes — laid out like Edit…");
  check($("stagedInfo").textContent === `${fixture.stage.filename} — ${fixture.stage.kind}, ${(fixture.stage.bytes / 1024).toFixed(1)} kB`
    && $("stagedInfo").parentNode.querySelector("button").textContent === "Choose another file",
    "the chosen file's name, kind and size on one line, with Choose another file");
  check($("markdown").value === fixture.stage.markdown && !$("markdown").disabled && labelFor(intakeForm, "markdown").textContent === "Text"
    && $("title").value === fixture.stage.suggested_title && $("btnCancelIntake").parentNode === $("view-intake").querySelector(".view-head"),
    "Text holds the editable converted document; Cancel stays in the page header");
  check($("scope").value === "" && compactScope($("view-intake"), "scope", "scopeHint"),
    "Create Candidate's scope field is the compact Scope control: its label, one helper, no information icon or placeholder");
  await click($("btnPreviewIntake"));
  check(lastPlan().body.kind === "add" && requestKeys() === JSON.stringify(["body", "scope", "source", "title"])
    && lastPlan().body.request.scope === "" && /site-notes\.md \(sha256 /.test(lastPlan().body.request.source),
    "it previews the text, its name and its source — nothing about where it goes");

  console.log("\nThe candidate can be read as it would be filed");
  const filedRow = $("review").querySelectorAll(".file-item")
    .find((li) => li.querySelector(".file-path").textContent === fixture.add_filed);
  const readPlanned = buttonSaying(filedRow, "Read");
  await click(readPlanned);
  const asked = lastCall("/api/preview").body;
  check(asked.source === "plan" && asked.kind === "add" && asked.path === fixture.add_filed
    && asked.plan_id === fixture.plans.add.plan_id, "it asks for that file of this very plan, pinned to the preview");
  check(/As this preview would leave it — nothing is written yet/.test($("docViewer").querySelector(".reader-banner").textContent)
    && /Ground conditions on the north boundary\./.test($("docViewer").querySelector(".md").textContent),
    "and renders it, labelled as not written yet");
  await click(buttonSaying($("docViewer"), "Close"));
  check(document.activeElement === readPlanned && !!buttonSaying($("review"), "File as candidate"),
    "closing returns to the same preview, focus on its Read");
  await click(buttonSaying($("review"), "File as candidate"));
  check(lastCall("/api/apply").body.kind === "add" && lastCall("/api/apply").body.confirm === true,
    "filing applies it with an ordinary confirmation");
  check(vm.runInThisContext("staged") === null && $("title").value === "" && $("markdown").value === ""
    && $("stepConvert").hidden && !$("stepFile").hidden, "Create candidate is empty again, its later stages hidden");
  check(!$("view-candidates").hidden && location.hash === "#candidates"
    && document.activeElement === $("view-candidates").querySelector("h2"),
    "it returns to Authority candidates, focus on its heading");
  check(/Saved in private local state on this computer\. Nothing agents read changed\./.test(toastNow().textContent)
    && /Filed as an authority candidate — not context\./.test(toastNow().textContent)
    && !buttonSaying(toastNow(), "Go to Authority Candidates"),
    "the message says it is private and not context, with no link to the page already shown");
  goBack();
  await settle();
  check($("view-intake").hidden && location.hash !== "#intake", "Back after filing never returns to the emptied form");
  goForward();
  await settle();
  clearToasts();

  console.log("\nCreate candidate: Cancel files nothing and returns to Authority candidates");
  await click($("btnAddDocument"));
  const cancelIntake = $("btnCancelIntake");
  const intakeHead = $("view-intake").querySelector(".view-head");
  check(cancelIntake && cancelIntake.tagName === "BUTTON" && cancelIntake.getAttribute("type") === "button"
    && cancelIntake.textContent === "Cancel" && cancelIntake.parentNode === intakeHead
    && intakeHead.children.indexOf(cancelIntake) === intakeHead.children.indexOf(intakeHead.querySelector("h2")) + 1,
    "Cancel is a native button beside the heading, never inside a stage");
  await vm.runInThisContext("stageFile")({ name: "site-notes.md" });
  await settle();
  $("title").value = "Never filed";
  await click($("btnPreviewIntake"));
  const writesBeforeCancel = calls.filter((c) => c.url === "/api/apply").length;
  check(!!buttonSaying($("review"), "File as candidate"), "with a file chosen and its filing previewed");
  const intakeEntry = addressBook.index;
  await click(cancelIntake);
  check(calls.filter((c) => c.url === "/api/apply").length === writesBeforeCancel && !$("review").firstChild,
    "Cancel files nothing, and the preview of filing it is gone");
  check(vm.runInThisContext("staged") === null && $("title").value === "" && $("markdown").value === ""
    && $("stepConvert").hidden && !$("stepFile").hidden, "Create candidate is empty again, its later stages hidden");
  check(!$("view-candidates").hidden && location.hash === "#candidates" && addressBook.index < intakeEntry
    && document.activeElement === $("view-candidates").querySelector("h2"),
    "it returns to Authority candidates, focus on its heading");
  goForward();
  await settle();
  check($("view-intake").hidden, "Forward never returns to the emptied form");
  clearToasts();

  console.log("\nA file's own front matter: removed from the text, its title and scope only suggested");
  check($("frontMatterNote").hidden, "a file without front matter shows no such note");
  await click($("btnAddDocument"));
  stageAnswer = fixture.stage_front_matter;
  await vm.runInThisContext("stageFile")({ name: "supplier-policy.md" });
  await settle();
  const fm = fixture.stage_front_matter;
  check($("title").value === "Supplier policy" && $("scope").value === "Supplier choice and onboarding."
    && !$("title").disabled && !$("scope").disabled && $("title").getAttribute("readonly") === null
    && $("scope").getAttribute("readonly") === null,
    "its title and scope are filled in, in fields the person can change");
  check($("markdown").value === fm.markdown && !/^\s*---/.test($("markdown").value)
    && !/authority: authoritative|supersedes/.test($("markdown").value),
    "its front matter is not in the text");
  check(!$("frontMatterNote").hidden && /front matter was removed/.test($("frontMatterNote").textContent)
    && /title and scope are filled in below as suggestions: change them as you wish/.test($("frontMatterUsed").textContent)
    && /Not carried over: id, status, authority, source, created, updated, supersedes, superseded_by\./
      .test($("frontMatterDropped").textContent),
    "a note says it was removed, which values were used, and what was not carried over");
  check(!/was removed|not carried over|suggestion/i.test($("convertNotes").textContent),
    "the front-matter notice appears once: the conversion notes do not repeat it");
  type($("scope"), "Supplier choice.");
  await click($("btnPreviewIntake"));
  check(lastPlan().body.kind === "add" && lastPlan().body.request.scope === "Supplier choice."
    && lastPlan().body.request.title === "Supplier policy" && lastPlan().body.request.body === fm.markdown,
    "the preview files the person's title, scope and text — the suggestion changed as they chose");
  vm.runInThisContext("closeReview")();
  vm.runInThisContext("resetIntake")();
  check($("frontMatterNote").hidden && $("scope").value === "", "starting again clears the note and the fields");
  stageAnswer = fixture.stage;
  await navTo("candidates");

  console.log("\nLeaving Create Candidate after a file is chosen discards the whole session");
  await click($("btnAddDocument"));
  await vm.runInThisContext("stageFile")({ name: "site-notes.md" });
  await settle();
  $("title").value = "Half done";
  $("scope").value = "Half a scope";
  $("markdown").value = "Edited text\n";
  await click($("btnPreviewIntake"));
  check(!!buttonSaying($("review"), "File as candidate") && !$("stepConvert").hidden,
    "with a file converted, edited, and its filing previewed");
  const appliesBeforeLeaving = calls.filter((c) => c.url === "/api/apply").length;
  await navTo("governing");
  check(vm.runInThisContext("staged") === null && !$("review").firstChild
    && calls.filter((c) => c.url === "/api/apply").length === appliesBeforeLeaving,
    "leaving discards the upload, its conversion and the preview, and files nothing");
  await click(buttonSaying($("view-governing"), "Create candidate") || $("btnAddDocument"));
  check(!$("view-intake").hidden && vm.runInThisContext("staged") === null && $("stepConvert").hidden
    && !$("stepFile").hidden && $("markdown").value === "" && $("title").value === "" && $("scope").value === ""
    && $("stagedInfo").textContent === "" && $("convertNotes").textContent === "" && $("file").value === ""
    && $("frontMatterNote").hidden,
    "opening Create Candidate again starts completely fresh");
  stageAnswer = fixture.stage_front_matter;
  await vm.runInThisContext("stageFile")({ name: "supplier-policy.md" });
  await settle();
  check(!$("frontMatterNote").hidden, "with a front-matter note showing");
  goBack();
  await settle();
  check(!$("view-intake").hidden ? false : vm.runInThisContext("staged") === null && $("frontMatterNote").hidden
    && $("stepConvert").hidden, "leaving by Back discards it too");
  stageAnswer = fixture.stage;
  await navTo("candidates");
  let releaseLeft;
  stageDelay = { gate: new Promise((r) => { releaseLeft = r; }), answer: fixture.stage };
  await click($("btnAddDocument"));
  await vm.runInThisContext("stageFile")({ name: "slow.md" });
  await settle();
  await navTo("governing");
  releaseLeft();
  await settle();
  await click($("btnAddDocument"));
  check(vm.runInThisContext("staged") === null && $("markdown").value === "" && $("stepConvert").hidden,
    "a conversion still on its way when the person leaves never fills the next, fresh form");
  await navTo("candidates");

  console.log("\nChoose another file replaces the conversion and everything derived from it");
  await click($("btnAddDocument"));
  stageAnswer = fixture.stage_front_matter;
  await vm.runInThisContext("stageFile")({ name: "supplier-policy.md" });
  await settle();
  $("title").value = "Edited title";
  $("markdown").value = "Edited text\n";
  await click($("btnPreviewIntake"));
  check(!$("frontMatterNote").hidden && !!buttonSaying($("review"), "File as candidate") && $("convertNotes").textContent.length > 0,
    "with a converted file, its notes, edits and a preview of filing it");
  let pickerOpened = false;
  $("file").addEventListener("click", () => { pickerOpened = true; });
  await click($("btnChooseAnother"));
  check(pickerOpened && !$("stepConvert").hidden, "Choose another file opens the file picker, changing nothing yet");
  let releaseAnother;
  stageDelay = { gate: new Promise((r) => { releaseAnother = r; }), answer: fixture.stage };
  await vm.runInThisContext("stageFile")({ name: "site-notes.md" });
  await settle();
  check(vm.runInThisContext("staged") === null && $("title").value === "" && $("markdown").value === ""
    && $("frontMatterNote").hidden && $("convertNotes").textContent === "" && $("stagedInfo").textContent === ""
    && !$("review").firstChild && $("stepConvert").hidden && !$("stepFile").hidden,
    "once another file is chosen, the earlier conversion, its notes, the edits and the preview are gone at once");
  releaseAnother();
  await settle();
  check(vm.runInThisContext("staged").filename === fixture.stage.filename && $("title").value === fixture.stage.suggested_title
    && $("markdown").value === fixture.stage.markdown && $("frontMatterNote").hidden
    && $("stagedInfo").textContent.indexOf(fixture.stage.filename) === 0 && !$("stepConvert").hidden,
    "and the new file's conversion fills the form, with nothing left from the first");
  stageAnswer = fixture.stage;
  await navTo("candidates");

  console.log("\nA conversion that answers late never fills a form it no longer belongs to");
  const late = Object.assign({}, fixture.stage, { filename: "late.md", markdown: "LATE TEXT\n", suggested_title: "Late" });
  const hold = () => { let release; const gate = new Promise((r) => { release = r; }); stageDelay = { gate, answer: late }; return release; };
  const staged = () => vm.runInThisContext("staged");
  const intakeEmpty = () => staged() === null && $("markdown").value === "" && $("title").value === ""
    && $("stepConvert").hidden && !$("stepFile").hidden;
  clearToasts();
  await click($("btnAddDocument"));
  let release = hold();
  await vm.runInThisContext("stageFile")({ name: "late.md" });
  await settle();
  await click($("btnCancelIntake"));
  release();
  await settle();
  check(intakeEmpty() && !document.querySelectorAll(".toast").length && $("view-intake").hidden,
    "cancelled while converting: the late answer is dropped, and the form stays empty");
  await click($("btnAddDocument"));
  release = hold();
  await vm.runInThisContext("stageFile")({ name: "late.md" });
  await vm.runInThisContext("stageFile")({ name: "site-notes.md" });
  await settle();
  release();
  await settle();
  check($("markdown").value === fixture.stage.markdown && $("title").value === fixture.stage.suggested_title
    && staged().filename !== "late.md",
    "another file chosen: the earlier file's late answer never replaces it");
  vm.runInThisContext("resetIntake")();
  release = hold();
  await vm.runInThisContext("stageFile")({ name: "late.md" });
  await settle();
  const pageState = vm.runInThisContext("state");
  const openRoot = pageState.root;
  pageState.root = "C:\\elsewhere\\other-context";
  release();
  await settle();
  check(intakeEmpty(), "another Agent Context opened meanwhile: the late answer is dropped");
  pageState.root = openRoot;
  vm.runInThisContext("resetIntake")();
  await navTo("candidates");

  console.log("\nEditing an older candidate: its old front matter is left out, and saving shows the removal");
  const writesBefore = () => calls.filter((c) => c.url === "/api/apply" || c.url === "/api/plan").length;
  let writes = writesBefore();
  await vm.runInThisContext("startCandidateEdit")({ path: fixture.legacy_path });
  await settle();
  check(lastCall("/api/draft").body.path === fixture.legacy_path && $("formField-body").value === "Old rule text.\n"
    && !/^\s*---/.test($("formField-body").value),
    "the text to edit starts without the old block");
  check($("legacyFrontMatterNote") && /Old front matter was removed from the text for this edit/
      .test($("legacyFrontMatterNote").textContent)
    && /id, status, authority, created/.test($("legacyFrontMatterNote").textContent)
    && /unchanged unless you save/.test($("legacyFrontMatterNote").textContent),
    "a note says so, what it held, and that nothing changes unless the person saves");
  check(writesBefore() === writes, "opening it previews and writes nothing");
  vm.runInThisContext("closeReview")();
  check(writesBefore() === writes, "nor does cancelling");
  await vm.runInThisContext("startCandidateEdit")({ path: fixture.legacy_path });
  await settle();
  await click(buttonSaying($("review"), "Preview the change"));
  check(lastPlan().body.kind === "edit-candidate" && lastPlan().body.request.body === "Old rule text.\n" && !$("confirmPhrase"),
    "saving is previewed first, as an ordinary candidate edit");
  check(/-id: old-rule[\s\S]*-authority: authoritative/.test($("review").textContent),
    "and the preview's diff shows the old block being removed");
  vm.runInThisContext("closeReview")();

  console.log("\nNavigating shows fresh data; Create candidate never keeps a half-done session");
  await click($("btnAddDocument"));
  $("title").value = "Half-typed title";
  currentState = Object.assign({}, fixture.state_valid, { documents: fixture.state_valid.documents.concat([
    Object.assign({}, fixture.state_valid.documents.find((d) => d.kind === "candidate"),
      { path: "authority-candidates/arrived-elsewhere.md", title: "Arrived elsewhere" })]) });
  const beforeNav = calls.length;
  await navTo("candidates");
  check(calls.slice(beforeNav).some((c) => c.url === "/api/state") && !calls.slice(beforeNav).some((c) => c.url === "/api/apply")
    && /Arrived elsewhere/.test($("candidatesList").textContent)
    && navItem("candidates").querySelector(".tally").textContent === `(${candCount + 1})`,
    "a navigation reads the state now, and lists what changed — writing nothing");
  await click($("btnAddDocument"));
  check($("title").value === "" && $("stepConvert").hidden,
    "going back to Create candidate starts fresh: the half-typed title is gone");
  $("title").value = "";
  currentState = fixture.state_valid;

  console.log("\nAn opened folder of authored documents with no map: unavailable, what is missing, and Rebuild only when ready");
  currentState = fixture.state_incomplete_blocked;
  await reload();
  const blockedCard = $("refusedCard");
  check(blockedCard && /This Agent Context has no map yet/.test(blockedCard.querySelector("h3").textContent)
    && /Agent context unavailable/.test(document.body.textContent),
    "it is shown unavailable, as an Agent Context with no map yet");
  check(/AGENT-CONTEXT\.md/.test(blockedCard.textContent) && /\.agent-context\.json/.test(blockedCard.textContent)
    && /authoritative\/notes\.md/.test(blockedCard.textContent) && /governance front matter/.test(blockedCard.textContent),
    "it names what is missing and the document that cannot govern");
  check(!$("btnRebuildFromStatus") && $("btnRebuildContext").hidden,
    "with a document that cannot govern, Rebuild is not offered");
  check(!/`/.test($("refusedDetail").textContent) && $("refusedDetail").querySelectorAll("code").length >= 3,
    "file names in the explanation are code, never raw backticks");
  currentState = fixture.state_incomplete_ready;
  await reload();
  check($("refusedCard") && /This Agent Context has no map yet/.test($("refusedCard").textContent)
    && !!$("btnRebuildFromStatus") && !$("btnRebuildContext").hidden,
    "once every document there is valid and nothing else is in the folder, Rebuild is offered");
  currentState = fixture.state_valid;
  await reload();

  console.log("\nNo Check again: the console reads the folder on opening and after each operation");
  check(!$("btnRefresh") && !$("refreshStatus")
    && !document.querySelectorAll("button").some((b) => /Check again|Checking/.test(b.textContent))
    && !$("btnSwitch").hidden,
    "the top bar has no Check again button and no “Checked” status; Open Agent Context… remains");
  $("title").value = "Still typing";
  await reload();
  check($("title").value === "Still typing", "reading the folder again keeps what was being typed");
  $("title").value = "";
  await navTo("governing");

  /* --------------------------------------------- status, outside changes, rebuild */

  console.log("\nAn ordinary edit: agents refused, the reason, and Rebuild");
  await show("state_invalid");
  check($("barState").textContent === "Agent context unavailable" && $("barState").querySelector(".chip").classList.contains("stale")
    && $("metaAgents").textContent === "Unavailable",
    "the header and rail say Agent context unavailable, in the error treatment");
  check($("refusedCard") && $("refusedCard").querySelector("h3").textContent === "Charter can’t serve this Agent Context yet"
    && /Rebuild Agent Context/.test($("refusedDetail").textContent)
    && $("refusedCard").querySelectorAll(".issues li").length > 0, "the status says why, and what to do next");
  check($("btnRebuildFromStatus") && !$("btnRebuildContext").hidden, "Rebuild Agent Context is offered");
  check($("outsideNotice") && /authoritative\/a\.md/.test($("outsideNotice").textContent) && !$("btnAcknowledge"),
    "the document changed outside Charter is named; it cannot be marked seen while refused");
  check($("contextMapState").textContent === "Map out of date" && $("contextMapState").querySelector(".chip").classList.contains("stale"),
    "the map's status reads Map out of date, in the error treatment");
  const withdraw = buttonSaying(rowOf("governingList", "Beta"), "Withdraw in a change set…");
  check(withdraw.disabled && !withdraw.getAttribute("title")
    && !$("governingUnavailable").hidden && /valid and clean/.test($("governingUnavailable").textContent)
    && withdraw.getAttribute("aria-describedby") === "governingUnavailable",
    "governing changes are unavailable, and say why in one visible line that describes each, not a tooltip");
  const firstCandidate = $("candidatesList").querySelectorAll(".doc")[0];
  const planIt = firstCandidate && buttonSaying(firstCandidate, "Plan a change set…");
  check(planIt && planIt.disabled && !$("candidatesUnavailable").hidden
    && planIt.getAttribute("aria-describedby") === "candidatesUnavailable",
    "so does Plan a change set… on a candidate");
  await click($("btnRebuildFromStatus"));
  check(lastPlan().body.kind === "rebuild" && !$("confirmPhrase")
    && $("review").querySelectorAll(".file-path").every((n) => ["AGENT-CONTEXT.md", ".agent-context.json"].includes(n.textContent)),
    "Rebuild is previewed, writes only the generated files, and needs no phrase");
  check($("review").textContent.indexOf("Rebuild changes no governing document and approves nothing") !== -1,
    "the preview says it changes and approves no governing document");
  await click($("btnApply"));
  check(lastCall("/api/apply").body.kind === "rebuild" && lastCall("/api/apply").body.confirm === true,
    "applying it sends an ordinary confirmation");
  check(document.activeElement && document.activeElement.tagName === "H2",
    "a completed apply moves focus to the view heading, not <body>");
  clearToasts();

  console.log("\nAfter Rebuild: served, and still shown as changed outside");
  await show("state_rebuilt");
  check($("barState").textContent === "Agent context ready" && /Rebuild Agent Context regenerated/.test($("outsideNotice").textContent)
    && /authoritative\/a\.md/.test($("outsideNotice").textContent), "served, and the outside change is still named");
  check($("governingUnavailable").hidden && $("candidatesUnavailable").hidden
    && !buttonSaying(rowOf("governingList", "Beta"), "Withdraw in a change set…").getAttribute("aria-describedby"),
    "once served, no unavailable line is shown and nothing is described by it");
  await click($("btnAcknowledge"));
  check(lastCall("/api/acknowledge") && /no longer flagged/.test(toastNow().textContent), "the person can mark it as seen");
  check(document.activeElement && document.activeElement.tagName === "H2",
    "acknowledging moves focus to the view heading, not <body>");
  clearToasts();

  console.log("\nA stray: named, left alone, and no Rebuild");
  await show("state_unclean");
  check(/notes\.txt/.test($("refusedCard").textContent) && !$("btnRebuildFromStatus"),
    "the stray is named, and Rebuild is not offered");
  check($("refusedCard").querySelector("h3").textContent === "Charter can’t serve this Agent Context yet"
    && $("refusedDetail").textContent === "This folder contains files that are not part of the Agent Context. Charter leaves them untouched.",
    "its heading says Charter can’t serve the context yet; the next line says why, and that the files are left untouched");
  const strayRow = $("refusedCard").querySelector(".stray-item");
  check(strayRow && strayRow.querySelector("strong").textContent === "notes.txt"
    && strayRow.textContent === "notes.txt isn’t part of this Agent Context. Move it out of the context folder or delete it, then try again.",
    "each file: its name in bold, that it isn’t part of this Agent Context, and what to do");
  check($("straysNote").textContent === "Charter never moves or deletes files it did not create. After resolving the files listed above, choose any navigation item to check the folder again."
    && !/Agents are refused|Agents are not served/.test($("refusedCard").textContent)
    && $("barState").textContent === "Agent context unavailable",
    "the closing guidance, with no “Agents are refused”; the header still reads Agent context unavailable");

  console.log("\nA map in an older format: out of date, with Rebuild");
  await show("state_map_outdated");
  check($("barState").textContent === "Agent context unavailable"
    && $("refusedCard").querySelector("h3").textContent === "This Agent Context’s map is out of date"
    && /^An earlier version of Charter generated it, so Charter can’t serve the context until it’s rebuilt\./.test($("refusedDetail").textContent)
    && !!$("btnRebuildFromStatus") && $("contextMapState").textContent === "Map out of date"
    && !/\b\d\b/.test($("refusedCard").querySelector("h3").textContent),
    "the status says the map is out of date and offers Rebuild, naming no version number");

  console.log("\nA map in a newer format: this copy of Charter is out of date, and nothing is offered to write");
  await show("state_charter_outdated");
  const newer = $("refusedCard").textContent;
  check($("barState").textContent === "Agent context unavailable"
    && /newer version of Charter/.test(newer) && $("refusedCard").querySelector("h3").textContent === "This copy of Charter is out of date"
    && /so this copy can’t check or serve it/.test($("refusedDetail").textContent) && !/Agents are refused/.test(newer)
    && /not at fault/.test(newer) && !/damaged|corrupt/i.test(newer),
    "the status says this copy of Charter is out of date, and that the context is not at fault");
  check(!$("btnRebuildFromStatus") && $("btnRebuildContext").hidden && !$("rebuildBlockedNote")
    && $("contextMapState").textContent === "Map not checked",
    "it offers no Rebuild, or anything else that would write, and the map is not checked by this copy");
  check(!/\b\d+\.\d+/.test(newer) && !/version 3|version 2/.test(newer),
    "and names no version number: those are in Diagnostics");

  console.log("\nDiagnostics: which copy of Charter, collapsed at the end of Settings and of Open");
  await show("state_valid");
  await navTo("settings");
  await settle();
  const sd = $("settingsDiagnostics");
  const view = $("view-settings");
  check(!!sd && view.children.indexOf(sd) === view.children.length - 1
    && $("settingsDiagnosticsToggle").textContent === "Diagnostics"
    && $("settingsDiagnosticsToggle").getAttribute("aria-expanded") === "false" && $("settingsDiagnosticsBody").hidden,
    "Settings ends with a Diagnostics disclosure, collapsed by default");
  const terms = sd.querySelectorAll("dt").map((d) => d.textContent);
  check(["Version", "Build", "Launcher", "charter.py", "Python", "Map format", "This Agent Context's map format",
    "charter on PATH"].every((t) => terms.includes(t))
    && sd.textContent.indexOf(fixture.diagnostics.identity.version) !== -1
    && sd.textContent.indexOf(fixture.diagnostics.identity.python) !== -1,
    "it shows the version, build, launcher, charter.py, Python, both map formats and what PATH finds");
  const diagFolderRow = sd.querySelectorAll("dt").map((d) => d.textContent).indexOf("Agent Context folder");
  check(fixture.diagnostics.folder === fixture.state_valid.root && diagFolderRow !== -1
    && sd.querySelectorAll("dd")[diagFolderRow].textContent === fixture.state_valid.root
    && fixture.diagnostics_closed.folder === "",
    "and the open Agent Context's exact full folder path, as its own row, only while one is open");
  await click($("settingsDiagnosticsToggle"));
  check(!$("settingsDiagnosticsBody").hidden, "and opens on request");
  check(document.querySelector(".topbar").textContent.indexOf(fixture.diagnostics.identity.version) === -1
    && document.querySelector("nav.rail").textContent.indexOf(fixture.diagnostics.identity.version) === -1
    && $("contextStatus").textContent.indexOf(fixture.diagnostics.identity.version) === -1,
    "no header, rail or status line shows the version");
  await click($("btnSwitch"));
  await settle();
  const od = $("openDiagnostics");
  check(!!od && $("view-open").children.indexOf(od) === $("view-open").children.length - 1
    && $("openDiagnosticsToggle").getAttribute("aria-expanded") === "false"
    && od.querySelectorAll("dt").map((d) => d.textContent).includes("Version"),
    "the Open view ends with the same Diagnostics, collapsed");
  await navTo("governing");

  console.log("\nLost metadata: the settings last known on this computer, to confirm or change");
  await show("state_lost_metadata");
  await click($("btnRebuildFromStatus"));
  const offered = fixture.plan_rebuild_lost.settings_proposal;
  check($("rebuildSettingsLabel").textContent === "Last known on this computer."
    && $("rebuildProjectName").value === offered.project_name && $("btnApply").disabled,
    "they are labelled Last known on this computer, prefilled, and Rebuild waits for them");
  const offerCode = $("rebuildSettingsOffer").querySelectorAll("p code").map((c) => c.textContent);
  check(offerCode.includes(".agent-context.json") && $("review").textContent.indexOf("`") === -1
    && $("planProblems").querySelectorAll("code").some((c) => c.textContent === ".agent-context.json"),
    "inline code in the offer and in what blocks Rebuild is shown as code, never as literal backticks");
  const rebuildRows = $("rebuildGuidance").querySelectorAll("label.choice");
  check($("rebuildGuidance").classList.contains("settings-guidance") && rebuildRows.length === 3
    && rebuildRows.every((l) => l.children[0].tagName === "INPUT" && l.children[1].children[0].tagName === "STRONG"
      && l.children[1].children[1].classList.contains("hint")),
    "Rebuild's guidance options use Settings' rows: each label, then its description on its own line");
  check(!/settings are lost/.test($("review").textContent), "and never says settings were lost");
  $("rebuildGuidance-review_newly_discovered_material").checked = true;
  await click($("btnRebuildWithSettings"));
  const sent = lastPlan().body.request;
  check(sent.project_name === offered.project_name && sent.agent_guidance.review_newly_discovered_material === true
    && JSON.stringify(Object.keys(sent.agent_guidance).sort())
      === JSON.stringify(["context_check_in", "proposal_context_impact_check", "review_newly_discovered_material"]),
    "confirming or changing them sends the name and every guidance setting explicitly");
  check(!$("btnApply").disabled, "then Rebuild can apply");
  vm.runInThisContext("closeReview")();

  console.log("\nSettings: a subtitle under the heading, and two-line guidance options");
  await show("state_valid");
  await navTo("settings");
  const settingsView = $("view-settings");
  check($("settingsIntro").textContent === "Settings are reflected in AGENT-CONTEXT.md, which agents read."
    && settingsView.children[settingsView.children.indexOf(settingsView.querySelector(".view-head")) + 1] === $("settingsIntro")
    && settingsView.children.indexOf($("settingsIntro")) < settingsView.children.indexOf($("settingsForm")),
    "the subtitle sits directly under Settings, before the Project name field");
  const guidance = $("settingsGuidance").querySelectorAll("label.choice");
  check(guidance.map((l) => l.querySelector("strong").textContent).join(" | ")
      === "Context check-in | Assess proposal impact | Review discovered material"
    && guidance.map((l) => l.querySelector(".hint").textContent).join(" | ") === [
      "After reading the context map and relevant governing documents, the agent sends a brief check-in naming the documents it read.",
      "Before proposing a change, the agent checks for duplication, overlap, conflicts, and unresolved decisions.",
      "The agent compares relevant non-governing material with the governing documents and raises material concerns for human review."].join(" | "),
    "each option has its short label and its sentence");
  check(guidance.every((l) => l.children[0].tagName === "INPUT" && l.children[1].children[0].tagName === "STRONG"
      && l.children[1].children[1].classList.contains("hint"))
    && /display:\s*grid/.test(rule(css, ".settings-guidance .choice")) && /display:\s*grid/.test(rule(css, ".settings-guidance .choice > span")),
    "two lines each: the checkbox and label, then a quieter sentence beneath the label");

  console.log("\nSettings: previewed, never the typed phrase");
  await show("state_valid");
  await navTo("settings");
  check($("settingsProjectName").value === fixture.state_valid.project_name
    && fixture.state_valid.agent_guidance.every((g) => $("settingsGuidance-" + g.id).checked === g.on),
    "the project name and each guidance setting are shown as they are");
  $("settingsGuidance-proposal_context_impact_check").checked = true;
  await click($("btnPreviewSettings"));
  check(lastPlan().body.kind === "settings" && lastPlan().body.request.agent_guidance.proposal_context_impact_check === true
    && !$("confirmPhrase") && !!buttonSaying($("review"), "Save settings"),
    "a change is previewed, saved with an ordinary confirmation");
  vm.runInThisContext("closeReview")();
  await show("state_invalid");
  check($("settingsUnavailable") && !$("btnPreviewSettings"), "while the context is not valid, settings say why they wait");

  console.log("\nGit: a compact read-only summary, the branch and a count, and no file list");
  await show("state_git");
  check(!$("metaBranch").hidden && $("metaGitLabel").textContent === "Git branch" && $("metaBranch").textContent === "feature/scope"
    && !$("metaChanged").hidden && $("metaChangedLabel").textContent === "Context files changed"
    && $("metaChangedCount").textContent === "1" && $("metaChanged").textContent === "1",
    "in a Git checkout the sidebar shows the branch and the number of changed context files");
  await show("state_git_long");
  const longBranch = fixture.state_git_long.status.git.branch;
  check($("metaBranch").textContent === longBranch
    && $("metaBranch").querySelectorAll("wbr").length === (longBranch.match(/[\/_.]/g) || []).length,
    "a long branch name is shown whole, breakable after each /, _ and .");
  check(/overflow-wrap:\s*anywhere/.test(rule(css, ".rail-meta dd")) && !/break-all/.test(rule(css, ".rail-meta dd")),
    "rail values break inside a word only as a last resort, never at arbitrary letters");
  await show("state_git");
  check(!$("gitDetailsToggle") && !$("gitDetailsPanel") && !$("gitChanged")
    && !$("contextMeta").querySelectorAll("button").length && !$("contextMeta").querySelectorAll("li").length
    && !/authoritative\/a\.md/.test($("contextMeta").textContent),
    "it offers no control that expands a list of those files, and names none of them");
  const many = JSON.parse(JSON.stringify(fixture.state_git));
  many.status.git.changed = ["context/a.md", "context/b.md", "context/c.md"];
  currentState = many;
  await reload();
  check($("metaChangedCount").textContent === "3" && !$("contextMeta").querySelectorAll("button").length,
    "three changed files: the count, still with no file list");
  await show("state_git_clean");
  check($("metaBranch").textContent === "main" && $("metaChangedCount").textContent === "0",
    "a checkout with no changed context files: 0");
  await show("state_git_unreadable");
  check($("metaChangedCount").textContent === "Could not be read" && $("metaBranch").textContent === "main"
    && !/\b0\b/.test($("metaChanged").textContent),
    "when Git status could not be read, it says so — never 0");
  await show("state_git_unavailable");
  check($("metaBranch").textContent === "Git unavailable" && $("metaChanged").hidden && $("metaChangedLabel").hidden,
    "when Git cannot be run: Git unavailable, and no count");

  console.log("\nAn interrupted write rolled back on opening is said once");
  await show("state_recovered");
  check(/interrupted Charter write was found and rolled back/.test(toastNow().textContent),
    "the message says so");
  clearToasts();
  await show("state_valid");

  console.log("\nAn error stays until dismissed; a success message waits while it is read");
  const scheduled = [];
  const cleared = [];
  global.setTimeout = (fn, ms) => { scheduled.push({ fn, ms }); return scheduled.length; };
  global.clearTimeout = (id) => { if (id) cleared.push(id); };
  vm.runInThisContext("toast")("Nothing was written: the file changed.", true);
  check(scheduled.length === 0 && toastNow().getAttribute("role") === "alert" && !!buttonSaying(toastNow(), "Dismiss"),
    "an error sets no timer, is an alert, and offers Dismiss");
  await click(buttonSaying(toastNow(), "Dismiss"));
  check(!toastNow(), "Dismiss removes it");
  vm.runInThisContext("toast")("Done.", false, { label: "View details", onclick: () => {} });
  check(scheduled.length === 1 && scheduled[0].ms === 8000 && toastNow().getAttribute("role") === "status",
    "a success with a follow-up goes by itself, politely announced");
  toastNow().dispatch("mouseenter");
  check(cleared.includes(1), "pointing at it pauses the timer");
  global.setTimeout = () => 0;
  global.clearTimeout = () => {};
  clearToasts();

  /* ------------------------------------------------------- Agent Proposals */

  console.log("\nAgent Proposals: counted, and kept apart from what governs");
  await show("state_valid");
  const counts = fixture.state_valid.proposals;
  check(navItem("proposals").querySelector(".tally").textContent === `(${counts.pending + counts.imported} · ${counts.stale} stale)`
    && navItem("proposals").querySelector(".tally").classList.contains("alert")
    && navItem("proposals").querySelector(".sr-only").textContent
      === `: ${counts.pending + counts.imported} waiting, ${counts.stale} stale, 1 unexpected record`,
    "the navigation counts waiting proposals, stale ones in words too");
  await navTo("proposals");
  check(lastCall("/api/proposals") && !$("view-proposals").hidden, "opening the area reads the proposals now");
  check(!$("aboutProposals") && !$("aboutProposalsToggle") && !$("view-proposals").querySelector(".info-toggle"),
    "its header carries no information icon or explanatory panel");
  check($("view-proposals").querySelector(".lede").textContent
    === "Accepted proposals become authority candidates."
    && $("view-proposals").querySelectorAll(".lede").length === 1 && !!$("btnImportProposal"),
    "its subtitle reads exactly “Accepted proposals become authority candidates.”, beside Import agent proposal…");
  const keptPending = fixture.proposals.pending;
  fixture.proposals.pending = [];
  await vm.runInThisContext("renderAgentProposals")();
  check($("pendingProposals").children.length === 0 && !$("noPendingProposals")
    && !/No proposal from an agent is waiting/.test($("view-proposals").textContent),
    "with no proposal waiting, there is no empty-state sentence");
  fixture.proposals.pending = keptPending;
  await vm.runInThisContext("renderAgentProposals")();
  const cards = $("pendingProposals").querySelectorAll(".proposal");
  const cardOf = (id) => document.querySelectorAll(".proposal").find((c) => c.getAttribute("data-id") === id);
  const fresh = cardOf(fixture.proposal_pending);
  const staleCard = cardOf(fixture.proposal_stale);
  const titled = cardOf(fixture.proposal_titled);
  const untitled = cardOf(fixture.proposal_untitled);
  const imported = cardOf(fixture.proposal_imported);
  const importedCreate = cardOf(fixture.proposal_imported_create);
  const titleOf = (c) => c.querySelector("h4.proposal-title").textContent;
  check(cards.length === fixture.proposals.pending.length && fresh && staleCard && untitled && importedCreate,
    "each pending and imported proposal has a card");
  check(titleOf(titled) === "Release checklist" && titled.getAttribute("aria-labelledby") === titled.querySelector("h4").getAttribute("id")
    && !/Proposed title/.test(titled.textContent),
    "a create leads with the title it supplies, with no operation word or Proposed title badge");
  check(titleOf(fresh) === "Release rule" && !fresh.querySelector("h4 code") && !/Logical path/.test(fresh.textContent),
    "a directly filed create with no supplied title is titled by its body's first heading");
  check(titleOf(importedCreate) === "Imported rule" && !/Logical path/.test(importedCreate.textContent),
    "so is an imported create");
  check(titleOf(untitled) === "authority-candidates/untitled-rule.md" && !!untitled.querySelector("h4 code.proposal-target")
    && /Logical path — no title found/.test(untitled.querySelector("header").textContent),
    "only with no title and no heading does a card lead with the logical path, labelled as a path");
  check(titleOf(imported) === "Beta" && titleOf(staleCard) === "Unscoped idea",
    "an amendment leads with the current title of the governing document or candidate it targets");
  const allCards = document.querySelectorAll(".proposal");
  check(allCards.every((c) => !/^(Create|Amend|Retire)\b/.test(titleOf(c)) && !c.querySelector(".proposal-op")),
    "no card leads with an operation word");
  check(allCards.every((c) => !/\bp-\d{8}-[0-9a-f]+/.test(c.textContent)),
    "no card shows an internal p-… identifier");
  check(fresh.querySelector(".proposal-meta").textContent.replace(/\s+/g, " ").trim()
      === `Submitted by: codex · Received: ${vm.runInThisContext("relativeTime")(fixture.proposals.pending.find((p) => p.proposal_id === fixture.proposal_pending).received)}`
    && fresh.querySelector(".proposal-meta").querySelectorAll("strong").map((s) => s.textContent).join("|") === "Submitted by:|Received:"
    && fresh.querySelector("header").textContent.indexOf("codex") === -1,
    "one metadata line: Submitted by and Received, below the title, never in it");
  check(/^Submitted by: chat-agent, imported by you · Received: /.test(imported.querySelector(".proposal-meta").textContent.replace(/\s+/g, " ").trim()),
    "an imported proposal says it was imported by you");
  check(!/self-reported|Target:/.test(allCards.map((c) => c.textContent).join(" ")),
    "the metadata line is clean: no self-reported note, no target line");
  const preview = $(`proposalReason-${fixture.proposal_titled}`);
  check(preview.classList.contains("proposal-reason-preview") && preview.textContent === "Purpose: " + fixture.proposal_titled_reason
    && /white-space:\s*nowrap/.test(rule(css, ".proposal-reason-preview"))
    && /text-overflow:\s*ellipsis/.test(rule(css, ".proposal-reason-preview"))
    && /overflow:\s*hidden/.test(rule(css, ".proposal-reason-preview")),
    "the purpose is a one-line preview on screen, at any width, its whole text there for a screen reader");
  check(!/padding/.test(rule(css, ".proposal > header")) && /margin:\s*0;/.test(rule(css, ".proposal-reason-preview"))
    && /gap:\s*\.3rem/.test(rule(css, ".proposal")),
    "a card is compact: no leading space before its title, and tight spacing between its lines");
  check(allCards.every((c) => !c.querySelectorAll(".disclosure-toggle").length && !c.querySelector("pre")
      && c.querySelector(".proposal-open-row").querySelectorAll("button").map((b) => b.textContent).join() === "Review proposal…,Reject proposal"
      && c.querySelector(".proposal-detail").hidden),
    "a list card stays compact: its review collapsed, and two actions, Review proposal… and Reject proposal");
  check(staleCard.classList.contains("is-stale") && /Stale/.test(staleCard.querySelector("header").textContent),
    "a stale proposal is marked stale in the list");
  check(!$("proposalsImportedGroup").hidden
    && $("importedProposals").querySelectorAll(".proposal").length === fixture.proposals.imported.length,
    "imported proposals are listed apart");
  const odd = $("unexpectedRecords").querySelector(".unexpected-record");
  check(!$("proposalsUnexpectedGroup").hidden && odd && /dropped-in\.json/.test(odd.textContent)
    && /Unexpected — not a proposal/.test(odd.textContent) && !buttonSaying(odd, "Review proposal…")
    && odd.querySelector(".title-row .chip").textContent === "Unexpected — not a proposal"
    && !odd.querySelector(".actions .chip"),
    "an unexpected local record is shown apart, never as a proposal, and cannot be reviewed as one");
  await click(buttonSaying(odd, "View contents"));
  check(lastCall("/api/proposals/unexpected").body.name === "dropped-in.json"
    && $("unexpectedText").textContent === fixture.unexpected_view.text
    && /viewing it changes nothing/.test($("review").textContent),
    "its contents can be viewed, as text, changing nothing");
  vm.runInThisContext("closeReview")();
  check(buttonSaying(odd, "Import a copy…") && fixture.proposals.unexpected[0].regular === true,
    "a file among the records offers Import a copy…");
  const folderRow = vm.runInThisContext("unexpectedRow")(fixture.unexpected_folder_row);
  check(fixture.unexpected_folder_row.regular === false && buttonSaying(folderRow, "View contents")
    && !buttonSaying(folderRow, "Import a copy…"),
    "a record that is not a file can be viewed but offers no Import a copy…, having no text to import");
  await click(buttonSaying(folderRow, "View contents"));
  check(lastCall("/api/proposals/unexpected").body.name === "a-folder"
    && $("unexpectedText").textContent === fixture.unexpected_folder_view.message
    && /is a folder, not a regular file/.test($("unexpectedText").textContent)
    && !$("review").querySelector("pre") && !/no such unexpected record/i.test($("review").textContent),
    "viewing it says what it is, never that it does not exist, and shows no contents");
  vm.runInThisContext("closeReview")();

  check(/font-weight:\s*700/.test(rule(css, ".proposal-meta strong")) && /color:\s*var\(--ink\)/.test(rule(css, ".proposal-meta strong"))
    && /display:\s*flex/.test(rule(css, ".proposal .proposal-open-row")) && /flex-direction:\s*row/.test(rule(css, ".proposal .proposal-open-row"))
    && /flex-wrap:\s*wrap/.test(rule(css, ".proposal .proposal-open-row")),
    "Submitted by: and Received: are visibly bold, and a card's actions share one row, wrapping only when too narrow");
  check(document.querySelectorAll(".proposal").every((c) => {
      const row = c.querySelector(".proposal-open-row");
      const buttons = row.querySelectorAll("button");
      return buttons.length === 2 && buttons.every((btn) => btn.parentNode === row)
        && !buttons[1].classList.contains("proposal-reject") && buttons[1].classList.contains("proposal-reject-open");
    }) && /display:\s*grid/.test(rule(css, ".proposal-reject")),
    "Review proposal… and Reject proposal sit side by side in the one row; the button no longer takes the rejection form's block layout");
  check(/display:\s*none/.test(rule(css, ".proposal .actions[hidden]"))
    && /gap:\s*\.5rem/.test(rule(css, ".proposal .actions")) && /display:\s*flex/.test(rule(css, ".proposal .actions")),
    "a hidden compact row really is hidden, so an expanded card shows one Reject proposal, and its decisions are spaced apart");
  check(!$("proposalsImportedGroup").querySelector(".hint") && $("proposalsImportedTitle").textContent === "Imported by You",
    "Imported by You is its heading alone, with no explanatory sentence");
  check(/background:\s*#fff/.test(rule(css, ".btn")) && /border:\s*1px solid var\(--rule-strong\)/.test(rule(css, ".btn"))
    && !/background:\s*var\(--ink\)/.test(rule(css, ".btn"))
    && !/\.btn\.(danger|authority|primary)\b/.test(css) && !/\.btn\.ghost/.test(css)
    && /opacity:\s*\.45/.test(rule(css, ".btn:disabled")),
    "one shared button treatment: white, ink text, a light outline — no filled, danger, authority or alternate ghost variant; disabled stays distinct");
  const appSource = fs.readFileSync(path.join(STATIC, "app.js"), "utf8");
  check(!/"btn (danger|authority)"|btn primary|class: "close"|"linkish toast/.test(appSource) && !/applyClass/.test(appSource),
    "no action button is given a separately coloured class: Apply, Accept, Reject, Retire, Close and toast actions included");
  check(document.querySelectorAll(".proposal button").every((x) => x.classList.contains("btn")
      && !x.classList.contains("danger") && !x.classList.contains("authority")),
    "Review proposal… and Reject proposal use the shared treatment");

  console.log("\nReview proposal…: the same card, expanded in place");
  const titledDetail = titled.querySelector(".proposal-detail");
  await click(buttonSaying(titled, "Review proposal…"));
  check(!titledDetail.hidden && titled.classList.contains("is-expanded") && !$("review").firstChild
    && !$("proposalReview") && !$("reviewPanel"),
    "Review proposal… expands the card itself; no separate review panel opens");
  check(/white-space:\s*pre-wrap/.test(rule(css, ".proposal.is-expanded .proposal-reason-preview"))
    && preview.textContent === "Purpose: " + fixture.proposal_titled_reason,
    "expanded, the card's own Purpose shows the complete purpose, word for word");
  /* What the expanded detail shows on screen: each file's diff stays collapsed
     inside its own row until the person opens it. */
  const shownText = (root) => root.querySelectorAll(".file-detail").reduce(
    (text, region) => text.replace(region.textContent, ""), root.textContent);
  check(titledDetail.querySelectorAll(".file-detail").every((r) => r.hidden),
    "each changed file's diff starts collapsed in its own row");
  check(titled.querySelectorAll("h4").length === 1 && !titled.querySelectorAll("h5").length && titled.querySelectorAll(".proposal-meta").length === 1
    && shownText(titledDetail).indexOf(fixture.proposal_titled_reason) === -1
    && shownText(titledDetail).indexOf("Release checklist") === -1 && !/Submitted by|Purpose/.test(shownText(titledDetail)),
    "the card's heading, metadata line and Purpose are the only summary: none is repeated below");
  check(JSON.stringify(lastPlan().body) === JSON.stringify({ kind: "accept-proposal", request: { proposal_id: fixture.proposal_titled } })
    && !!titledDetail.querySelector(".file-list") && !titledDetail.querySelector(".proposal-candidate") && !titledDetail.querySelector(".md")
    && !/Tag every release\./.test(shownText(titledDetail)),
    "it shows each changed file's row, without rendering the candidate's title and body again");
  check(!/Expected Context Impact|advisory, not verified|does not govern|Target:|recommended_relationship/.test(titledDetail.textContent)
    && !titledDetail.querySelectorAll(".file-path").some((n) => /^Agent Proposal /.test(n.textContent)),
    "no impact, explainer banner, or the proposal's own private record");
  const decisions = titledDetail.querySelector(".proposal-decisions");
  check(decisions && decisions === titledDetail.children[titledDetail.children.length - 1]
    && decisions.querySelectorAll("button").map((b) => b.textContent).join("|") === "Accept as candidate|Reject proposal|Close review"
    && !$("btnAcceptProposal").disabled,
    "Accept as candidate and Reject proposal sit together at the end of the expanded card");
  const acceptedRow = titledDetail.querySelectorAll(".file-item")
    .find((li) => li.querySelector(".file-path").textContent === fixture.accepted_path);
  await click(buttonSaying(acceptedRow, "Read"));
  check(/As this preview would leave it/.test($("docViewer").querySelector(".reader-banner").textContent)
    && /Tag every release\./.test($("docViewer").textContent), "the file's Read opens the candidate as it would be");
  await click(buttonSaying($("docViewer"), "Close"));
  await click(buttonSaying(titled, "Close review"));
  check(titledDetail.hidden && !titledDetail.firstChild && !titled.classList.contains("is-expanded")
    && !!buttonSaying(titled, "Review proposal…") && !$("btnAcceptProposal"),
    "Close review collapses the card and clears what the review prepared");
  await click(buttonSaying(titled, "Review proposal…"));
  await click(buttonSaying(fresh, "Review proposal…"));
  check(titledDetail.hidden && !fresh.querySelector(".proposal-detail").hidden
    && document.querySelectorAll(".proposal.is-expanded").length === 1,
    "reviewing another proposal collapses the first: one review at a time");

  console.log("\nLeaving Agent Proposals collapses the review and clears its state");
  let releasePlan;
  const planGate = new Promise((r) => { releasePlan = r; });
  const realFetch = global.fetch;
  global.fetch = async (url, options) => (url === "/api/plan" ? planGate.then(() => realFetch(url, options)) : realFetch(url, options));
  await click(buttonSaying(staleCard, "Close review") || buttonSaying(fresh, "Close review"));
  await click(buttonSaying(titled, "Review proposal…"));
  await navTo("governing");
  releasePlan();
  await settle();
  global.fetch = realFetch;
  check(!document.querySelectorAll(".proposal.is-expanded").length && titledDetail.hidden && !titledDetail.firstChild
    && !$("btnAcceptProposal"),
    "leaving collapses it, and a preview still on its way is dropped");
  await navTo("proposals");
  check(!document.querySelectorAll(".proposal.is-expanded").length
    && document.querySelectorAll(".proposal").every((c) => c.querySelector(".proposal-detail").hidden),
    "back in Agent Proposals, every card is compact");

  console.log("\nAccepting: one final action, a candidate only");
  const freshNow = cardOf(fixture.proposal_pending);
  await click(buttonSaying(freshNow, "Review proposal…"));
  const plansBeforeAccept = calls.filter((c) => c.url === "/api/plan").length;
  await click($("btnAcceptProposal"));
  check(calls.filter((c) => c.url === "/api/plan").length === plansBeforeAccept
    && lastCall("/api/apply").body.kind === "accept-proposal" && lastCall("/api/apply").body.confirm === true
    && lastCall("/api/apply").body.plan_id === fixture.plans["accept-proposal"].plan_id
    && JSON.stringify(lastCall("/api/apply").body.request) === JSON.stringify({ proposal_id: fixture.proposal_pending }),
    "Accept as candidate applies the plan already shown: no second preview, apply screen, or Accept click");
  check(!document.querySelectorAll(".proposal.is-expanded").length && !$("btnAcceptProposal"),
    "the expanded review closes once the proposal is accepted");
  check(/^Accept as candidate: “[^”]+” becomes a private authority candidate\.$/.test(fixture.plans["accept-proposal"].summary)
    && !/file “/i.test(fixture.plans["accept-proposal"].summary) && !/does not govern/.test(fixture.plans["accept-proposal"].summary),
    "the acceptance summary names the candidate by friendly title, never “file <name>”");
  check(toastNow().textContent === "Proposal accepted." && !toastNow().querySelectorAll("button").length
    && !toastNow().querySelectorAll("a").length && toastNow().getAttribute("role") === "status",
    "the notice says exactly “Proposal accepted.”: no button, link, document name or other detail");
  clearToasts();

  console.log("\nRejecting: one confirmation in the same card, with no reason field");
  const staleNow = cardOf(fixture.proposal_stale);
  await click(buttonSaying(staleNow, "Review proposal…"));
  check($("btnAcceptProposal").disabled && !$("btnRejectProposal").disabled
    && /cannot be accepted as written/.test($("proposalReviewStale").textContent)
    && $(`proposalReason-${fixture.proposal_stale}`).textContent === "Purpose: Refine the idea.",
    "a stale proposal says why, cannot be accepted, and can still be rejected — its purpose shown in full first");
  const visibleRejects = (card) => card.querySelectorAll("button").filter((b) => /^Reject/.test(b.textContent)
    && !hiddenWithin(b, card));
  check(visibleRejects(staleNow).map((b) => b.textContent).join("|") === "Reject proposal",
    "expanded, the review shows exactly one Reject action");
  await click($("btnRejectProposal"));
  check(!!$("proposalRejectForm") && insideOf($("proposalRejectForm"), staleNow) && !$("review").firstChild
    && !$("proposalRejectReason") && !staleNow.querySelector("textarea")
    && !/Reason/.test(staleNow.querySelector(".proposal-detail").textContent),
    "Reject proposal asks for one confirmation inside the same card, with no reason field");
  check(staleNow.querySelector(".proposal-decisions").hidden
    && visibleRejects(staleNow).map((b) => b.textContent).join("|") === "Reject"
    && $("btnConfirmReject").textContent === "Reject" && $("btnCancelReject").textContent === "Cancel",
    "while it asks, the confirmation stands in for the decision row: one Reject action, and Cancel");
  await click($("btnCancelReject"));
  check(!$("proposalRejectForm") && !staleNow.querySelector(".proposal-decisions").hidden
    && visibleRejects(staleNow).map((b) => b.textContent).join("|") === "Reject proposal"
    && !calls.some((c) => c.url === "/api/plan" && c.body.kind === "reject-proposal"),
    "Cancel brings the decision row back, having rejected nothing");
  await click($("btnRejectProposal"));
  await click($("btnConfirmReject"));
  check(lastPlan().body.kind === "reject-proposal"
    && JSON.stringify(lastPlan().body.request) === JSON.stringify({ proposal_id: fixture.proposal_stale })
    && lastCall("/api/apply").body.kind === "reject-proposal" && lastCall("/api/apply").body.confirm === true
    && !$("confirmPhrase"),
    "Reject rejects it, sending no reason, confirmed ordinarily");
  check(toastNow().textContent === "Proposal rejected." && !toastNow().querySelectorAll("button").length
    && !toastNow().querySelectorAll("a").length && toastNow().getAttribute("role") === "status",
    "the notice says exactly “Proposal rejected.”: no button, link, document name or other detail");
  clearToasts();

  console.log("\nReject proposal, straight from the compact card");
  await navTo("governing");
  await navTo("proposals");
  const directCard = cardOf(fixture.proposal_titled);
  const directDetail = directCard.querySelector(".proposal-detail");
  const plansBeforeDirect = calls.filter((c) => c.url === "/api/plan").length;
  await click(buttonSaying(directCard, "Reject proposal"));
  check(!directDetail.hidden && !!$("proposalRejectForm") && insideOf($("proposalRejectForm"), directCard)
    && !directCard.querySelector("textarea")
    && !directCard.classList.contains("is-expanded") && directCard.classList.contains("is-rejecting")
    && !directDetail.querySelector(".file-list") && !$("btnAcceptProposal") && !$("review").firstChild
    && calls.filter((c) => c.url === "/api/plan").length === plansBeforeDirect,
    "it asks for one confirmation inside the card, without opening the review or previewing acceptance");
  check(directCard.querySelector(".proposal-open-row").hidden
    && directDetail.querySelectorAll("button").map((b) => b.textContent).join("|") === "Reject|Cancel",
    "while it asks, the card offers only Reject and Cancel");
  await click($("btnCancelReject"));
  check(directDetail.hidden && !directDetail.firstChild && !directCard.classList.contains("is-rejecting")
    && !directCard.querySelector(".proposal-open-row").hidden && !calls.some((c) => c.url === "/api/plan"
      && c.body.kind === "reject-proposal" && c.body.request.proposal_id === fixture.proposal_titled),
    "Cancel leaves the card compact again, having rejected nothing");
  await click(buttonSaying(directCard, "Reject proposal"));
  await navTo("governing");
  await navTo("proposals");
  const directAgain = cardOf(fixture.proposal_titled);
  check(directAgain.querySelector(".proposal-detail").hidden && !$("proposalRejectForm")
    && !document.querySelectorAll(".proposal.is-rejecting").length,
    "leaving Agent Proposals discards a rejection being confirmed");
  await click(buttonSaying(directAgain, "Reject proposal"));
  await click(buttonSaying(cardOf(fixture.proposal_untitled), "Review proposal…"));
  check(!directAgain.classList.contains("is-rejecting") && document.querySelectorAll(".proposal.is-expanded").length === 1,
    "opening another card's review closes the rejection: one card at a time");
  await click(buttonSaying(cardOf(fixture.proposal_untitled), "Close review"));
  await click(buttonSaying(directAgain, "Reject proposal"));
  await click($("btnConfirmReject"));
  check(lastPlan().body.kind === "reject-proposal" && lastPlan().body.request.proposal_id === fixture.proposal_titled
    && !("reason" in lastPlan().body.request) && lastCall("/api/apply").body.kind === "reject-proposal"
    && !document.querySelectorAll(".toast.error").length && toastNow().textContent === "Proposal rejected.",
    "from the compact card too: rejected with no reason, saying exactly “Proposal rejected.”");
  clearToasts();

  console.log("\nImport Agent Proposal: the fallback for an agent that could not file its own JSON");
  check($("btnImportProposal").textContent === "Import agent proposal…", "the action is Import agent proposal…");
  await click($("btnImportProposal"));
  check($("review").querySelector("h3").textContent === "Import Agent Proposal"
    && labelFor($("review"), "importJson").textContent === "Agent proposal JSON"
    && $("btnCheckImport").textContent === "Check proposal",
    "its panel is Import Agent Proposal, with the field Agent proposal JSON and the action Check proposal");
  check($("importInstruction").textContent === "Paste an agent proposal as JSON below. Use Create candidate for "
      + "material you want to add yourself. The JSON must follow Charter’s proposal format; Charter checks it "
      + "before anything is filed."
    && $("importInstruction").querySelector("strong").textContent === "Create candidate"
    && $("review").querySelectorAll(".note").length === 1,
    "its one instruction says proposals are agents' material, and sends people to Create candidate for their own");
  check($("btnFileImport").textContent === "Import" && $("btnFileImport").disabled
    && $("btnCheckImport").parentNode === $("btnFileImport").parentNode
    && $("btnFileImport").parentNode.children.indexOf($("btnFileImport"))
      === $("btnCheckImport").parentNode.children.indexOf($("btnCheckImport")) + 1,
    "Check proposal and a disabled Import sit side by side");
  check(!buttonSaying($("review").querySelector("header"), "Close")
    && $("btnCheckImport").parentNode.querySelectorAll("button").map((b) => b.textContent).join("|") === "Check proposal|Import|Cancel",
    "no header Close: Check proposal, Import and Cancel sit together");
  type($("importJson"), JSON.stringify(Object.assign(JSON.parse(fixture.import_returned), { base_commit: "abc123" })));
  await click($("btnCheckImport"));
  check($("importError") && $("importError").classList.contains("error") && $("importError").getAttribute("role") === "alert"
    && /base_commit/.test($("importError").textContent) && $("importResult").children.length === 1
    && $("btnFileImport").disabled && /color:\s*var\(--brick\)/.test(rule(css, ".note.error")),
    "a failed check shows only one concise red error saying why, and Import stays disabled");
  type($("importJson"), fixture.import_returned);
  check(!$("importError") && $("btnFileImport").disabled, "editing the JSON clears the error");
  await click($("btnCheckImport"));
  check(!$("btnFileImport").disabled && !$("importResult").firstChild && !$("importSummary")
    && !/chat-agent|Another clarification|passed|valid/i.test($("importResult").textContent),
    "a passing check shows nothing at all: it only enables Import");
  check(!calls.some((c) => c.url === "/api/proposals/import"), "checking files nothing");
  type($("importJson"), fixture.import_returned + " ");
  check($("btnFileImport").disabled, "any edit to the JSON disables Import again");
  $("btnFileImport").click();
  await settle();
  check(!calls.some((c) => c.url === "/api/proposals/import"), "and a disabled Import files nothing");
  type($("importJson"), fixture.import_returned);
  check($("btnFileImport").disabled, "even restoring the same text needs a fresh check");
  await click($("btnCheckImport"));
  await click($("btnFileImport"));
  check(lastCall("/api/proposals/import").body.json === fixture.import_returned
    && lastCall("/api/proposals/import").body.confirm === true
    && /Imported the agent proposal, for review\. It is not context\./.test(toastNow().textContent)
    && !/\bp-[\w-]+/.test(toastNow().textContent),
    "Import files exactly the checked JSON, as the person's own action, and says so without an internal id");
  clearToasts();

  console.log("\nImporting an exact duplicate of a waiting proposal: Replace or Cancel");
  const duplicateText = fixture.import_returned + "\n" + DUPLICATE_MARK;
  await click($("btnImportProposal"));
  type($("importJson"), duplicateText);
  await click($("btnCheckImport"));
  const importsBefore = calls.filter((c) => c.url === "/api/proposals/import").length;
  await click($("btnFileImport"));
  check($("importDuplicateText") && $("importDuplicateText").textContent
      === "An identical proposal, “Waiting rule,” is already awaiting review. Replace it?"
    && $("btnReplaceImport").textContent === "Replace" && $("btnCancelReplace").textContent === "Cancel",
    "an identical waiting proposal is named by its title, with Replace and Cancel");
  check($("btnFileImport").parentNode.hidden
    && $("importDuplicate").querySelectorAll("button").map((b) => b.textContent).join("|") === "Replace|Cancel"
    && !/Imported/.test((toastNow() || { textContent: "" }).textContent),
    "it stands in for the panel's own actions, and nothing was filed");
  await click($("btnCancelReplace"));
  check(!$("importDuplicate") && !$("btnFileImport").parentNode.hidden && $("importJson").value === duplicateText
    && calls.filter((c) => c.url === "/api/proposals/import").length === importsBefore + 1
    && !calls.some((c) => c.url === "/api/proposals/import" && c.body.replace),
    "Cancel changes nothing: the panel and its JSON are as they were, and nothing was replaced");
  await click($("btnFileImport"));
  await click($("btnReplaceImport"));
  check(lastCall("/api/proposals/import").body.replace === "p-waiting"
    && lastCall("/api/proposals/import").body.json === duplicateText && !$("importJson")
    && /Replaced the waiting proposal/.test(toastNow().textContent),
    "Replace replaces that waiting proposal with this submission, and the panel closes");
  clearToasts();

  console.log("\nCancel clears and closes Import Agent Proposal");
  await click($("btnImportProposal"));
  type($("importJson"), JSON.stringify(Object.assign(JSON.parse(fixture.import_returned), { base_commit: "abc123" })));
  await click($("btnCheckImport"));
  await click($("btnCancelImport"));
  check(!$("importJson") && !$("importError") && !$("review").firstChild && !$("view-proposals").hidden,
    "Cancel closes the panel and drops what was pasted and checked, staying in Agent Proposals");
  await click($("btnImportProposal"));
  check($("importJson").value === "" && !$("importError") && $("btnFileImport").disabled, "reopened, it starts empty");
  await click($("btnCancelImport"));

  console.log("\nLeaving Agent Proposals closes Import Agent Proposal, and clears it");
  await click($("btnImportProposal"));
  type($("importJson"), JSON.stringify(Object.assign(JSON.parse(fixture.import_returned), { base_commit: "abc123" })));
  await click($("btnCheckImport"));
  check(!!$("importError"), "with JSON pasted and checked");
  await navTo("candidates");
  check(!$("importJson") && !$("importResult") && !$("review").firstChild && !$("view-candidates").hidden,
    "on another area, the panel, its pasted JSON and its check result are gone");
  for (const view of ["governing", "changesets", "connect", "settings"]) {
    await navTo(view);
    check(!$("importJson") && !$("review").firstChild, `and it never appears in ${view}`);
  }
  await navTo("proposals");
  check(!$("importJson") && !$("review").firstChild, "back in Agent Proposals, it is not open");
  await click($("btnImportProposal"));
  check($("importJson").value === "" && !$("importError") && $("btnFileImport").disabled, "opened again, it starts empty");
  type($("importJson"), fixture.import_returned);
  let releaseCheck;
  importCheckDelay = new Promise((r) => { releaseCheck = r; });
  await click($("btnCheckImport"));
  await navTo("governing");
  releaseCheck();
  await settle();
  check(!$("btnFileImport") && !$("importError") && !$("review").firstChild,
    "a check still on its way when the person leaves is dropped, never shown anywhere");
  await navTo("proposals");

  /* --------------------------------------------------------- Change Sets */

  console.log("\nChange Sets: an index, and one draft's dedicated editor in its place");
  await show("state_valid");
  await navTo("changesets");
  check(lastCall("/api/changesets/list") && !$("changeSetIndex").hidden && $("changeSetEditor").hidden
    && $("changeSetList").querySelectorAll(".changeset-row").length === fixture.cs_list.drafts.length,
    "Change Sets opens on its index of private drafts");
  check($("changeSetIndex").querySelector(".lede").textContent === "Apply one or more authority changes as a set.",
    "its subtitle reads exactly “Apply one or more authority changes as a set.”");
  check(!$("changeSetInfo") && !$("changeSetIndex").querySelectorAll(".info-toggle").length,
    "Change Sets has no information control: the README explains change sets");
  csNext = fixture.cs_created;
  await click($("btnNewChangeSet"));
  check(lastCall("/api/changeset/create") && $("changeSetIndex").hidden && !$("changeSetEditor").hidden,
    "a new change set opens in the editor, in place of the index — never beneath it");
  check(calls.map((c) => c.url).lastIndexOf("/api/changesets/list") > calls.map((c) => c.url).lastIndexOf("/api/changeset/create"),
    "and the navigation's count is asked for again, so the new draft counts at once");
  const csSteps = $("csSteps").querySelectorAll("li");
  check(csSteps.map((li) => li.textContent).join(" | ") === "1. Build Change Set | 2. Preview and Apply"
    && csSteps[0].getAttribute("aria-current") === "step" && !csSteps[1].getAttribute("aria-current"),
    "two screens, Build change set then Preview and apply, and the first is current");
  check(/Private draft — not context/.test($("csStatus").textContent) && $("csTitle").value === ""
    && !$("csTitle").getAttribute("placeholder") && labelFor($("csPlan"), "csTitle").textContent === "Name",
    "a private, untitled draft, its Name field empty and never invented");
  check(!$("csCandidates") && !$("csWithdrawals") && $("csPreview").disabled, "an empty plan cannot be previewed");

  console.log("\nBuild change set: candidates first, each with its own decision");
  const addCandidate = $("csAddCandidate");
  check(addCandidate.options.map((o) => o.value).slice(1).sort().join()
      === fixture.cs_created.available_candidates.map((c) => c.path).sort().join() && !$("csNoCandidates"),
    "any authority candidate can be included");
  check($("csAddWithdrawal").options.map((o) => o.value).slice(1).sort().join()
      === fixture.cs_created.governing.map((g) => g.path).sort().join(),
    "any governing document can be withdrawn, in the same change set");
  check(!$("csRetained") && !$("csRetainedList"), "and nothing asks about the governing documents it retains");
  check($("csAddCandidateSelected").hidden && addCandidate.getAttribute("aria-describedby") === "csAddCandidateSelected",
    "before a candidate is chosen, no selection line is shown");
  addCandidate.value = fixture.cs_row.plan_candidates[0].path;
  addCandidate.focus();
  addCandidate.dispatch("change");
  const chosenOption = addCandidate.options.find((o) => o.value === addCandidate.value);
  check(!$("csAddCandidateSelected").hidden
    && $("csAddCandidateSelected").textContent === `Selected: ${chosenOption.textContent}`
    && document.activeElement === addCandidate,
    "the chosen candidate is said in full beneath the closed dropdown, which keeps focus");
  csNext = fixture.cs_row;
  await click($("csAddCandidateButton"));
  check(JSON.stringify(lastCall("/api/changeset/update").body) === JSON.stringify({ id: fixture.cs_created.draft.id,
    revision: fixture.cs_created.draft.revision, candidates: [fixture.cs_row.plan_candidates[0].path] }),
    "including a candidate decides nothing for it");
  check($("csDecision-0").value === "" && !$("csTarget-0")
    && !$("csAddCandidate").options.some((o) => o.value === fixture.cs_row.plan_candidates[0].path),
    "its decision starts unchosen, and a candidate already in the plan is not offered again");
  const noneLeft = JSON.parse(JSON.stringify(fixture.cs_row));
  noneLeft.available_candidates.forEach((c) => { c.used = true; });
  csNext = noneLeft;
  await vm.runInThisContext("openChangeSet")(noneLeft.draft.id);
  await settle();
  check(!$("csNoCandidates") && !$("csAddCandidate") && noneLeft.plan_candidates.length > 0,
    "with every candidate already included and listed, it offers no Add and never says “No candidates available.”");
  const noneAtAll = JSON.parse(JSON.stringify(fixture.cs_created));
  noneAtAll.available_candidates = [];
  noneAtAll.plan_candidates = [];
  csNext = noneAtAll;
  await vm.runInThisContext("openChangeSet")(noneAtAll.draft.id);
  await settle();
  check($("csNoCandidates") && $("csNoCandidates").textContent === "No candidates available." && !$("csAddCandidate"),
    "with no candidate listed and none to add, it says exactly “No candidates available.”");

  console.log("\nA complete plan, beside its one Agent Review panel");
  csNext = fixture.cs_valid;
  await vm.runInThisContext("openChangeSet")(fixture.cs_valid.draft.id);
  await settle();
  check(!$("csPreview").disabled && $("csDecision-0").value === "replace" && $("csDecision-1").value === "govern-alongside"
    && $("csTarget-0").value === "authoritative/a.md" && !$("csTarget-1")
    && $("csCandidates").querySelectorAll(".cs-row").length === 2 && $("csWithdrawals").querySelectorAll(".cs-row").length === 1
    && /^Ready to preview\.$/.test($("csReady").textContent),
    "a replacement, a candidate governing alongside and a withdrawal: ready to preview");
  check(!$("csAddWithdrawal").options.some((o) => o.value === "authoritative/a.md" || o.value === "authoritative/b.md")
    && !$("csTarget-0").options.some((o) => o.value === "authoritative/b.md"),
    "a governing document already replaced or withdrawn is offered for neither again");
  check($("csBuild").children.map((c) => c.id).join() === "csPlan,csAgentReview"
    && $("csAgentReview").querySelector("h4").textContent === "Agent Review"
    && !$("csPromptPanel") && !$("csResponsesPanel") && !/Context-Impact Review/.test($("changeSetEditor").textContent),
    "the plan sits beside one Agent Review panel; there is no separate Context-Impact Review panel");
  check(/grid-template-columns:\s*minmax\(0,\s*1\.15fr\)\s*minmax\(0,\s*1fr\)/.test(rule(css, ".review .inner.cs-build"))
    && /@(?:media|container)[^{]*\{\s*\.review \.inner\.cs-build\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\)/.test(css),
    "two columns on desktop, stacked on narrow widths");
  check(!labelFor($("csPlan"), "csRationale") && $("csRationale").getAttribute("aria-labelledby") === "csRationaleHeading"
    && $("csRationaleHeading").textContent === "Change Set Summary" && !$("csRationaleHint"),
    "the rationale is the Change Set Summary, with no explanatory text");
  check($("csCopyPrompt") && $("csDisclosure").textContent === fixture.cs_valid.disclosure_warning
    && $("csDisclosure").parentNode === $("csCopyPrompt").parentNode && insideOf($("csCopyPrompt"), $("csAgentReview")),
    "Agent Review offers the prompt to copy, the disclosure warning beside the button");
  check(/Charter sends nothing/.test($("csDisclosure").textContent), "and it says nothing is sent");
  Object.defineProperty(global, "navigator", { configurable: true,
    value: { clipboard: { writeText: async (t) => { global.__copied = t; } } } });
  await click($("csCopyPrompt"));
  check(global.__copied === fixture.cs_valid.review_prompt.text
    && lastCall("/api/changeset/prompt/copied").body.plan_fingerprint === fixture.cs_valid.plan_fingerprint
    && /charter-context-impact-prompt\/1/.test(global.__copied) && /<<<END OF Charter REVIEW PROMPT/.test(global.__copied),
    "copying takes the whole Charter prompt, and remembers which plan it was for");

  console.log("\nPast the practical limit: one packet, saved where the person chooses");
  const packetView = JSON.parse(JSON.stringify(fixture.cs_valid));
  Object.assign(packetView.review_prompt, { over_limit: true, size_chars: 120000, limit: 50000, size_bytes: 120000,
    file_name: "charter-review-packet-x.md", request: "Please carry out the review in the attached file." });
  delete packetView.review_prompt.text;
  packetView.reports = [];
  csNext = packetView;
  await vm.runInThisContext("openChangeSet")(packetView.draft.id);
  await settle();
  check($("csSavePacket") && !$("csPromptText") && $("csPacketDisclosure").textContent === fixture.cs_valid.packet_disclosure,
    "a review packet to save instead, its disclosure beside it, and no text on the page");
  const packetPanel = $("csAgentReview");
  check($("csPacketStatus").textContent
      === "Review packet required: 120,000 characters, past the 50,000-character single-message limit · 117 KB."
    && $("csPacketDisclosure").parentNode === $("csSavePacket").parentNode
    && !$("csPacketIntro") && !$("csPacketIncludes") && !$("csPacketRequest") && !$("csPacketRequestPanel")
    && !buttonSaying(packetPanel, "Copy request")
    && !/Request to Send with the Packet|Please carry out the review|holds the review instructions/.test(packetPanel.textContent),
    "the packet is compact and factual: its status and size, the save action, and the disclosure beside it — no narrative or request block");
  check($("csAddReview").textContent === "Add a review" && !$("csReviews"),
    "with no review yet, the control reads Add a review");
  await click($("csSavePacket"));
  check(lastCall("/api/changeset/packet/save").body.plan_fingerprint === fixture.cs_valid.plan_fingerprint,
    "saving asks the server, for this plan");
  check(/Choose a folder outside every Agent Context/.test($("csPacketRefused") ? $("csPacketRefused").textContent : "")
    || !!$("csPacketSaved"), "a refused destination is said, or the saved file is named");

  console.log("\nAgent Review: reviews saved as written, valid reports side by side, never choosing");
  csNext = fixture.cs_reports;
  await vm.runInThisContext("openChangeSet")(fixture.cs_reports.draft.id);
  await settle();
  const entries = $("csReviews").querySelectorAll(".cs-review-entry");
  check(entries.length === 2 && entries.every((e) => e.classList.contains("is-valid"))
    && entries.every((e, i) => {
      const labels = e.querySelectorAll("label");
      return labels[0].textContent === "Reviewing agent" && labels[0].getAttribute("for") === `csReviewAgent-${i}`
        && labels[1].getAttribute("for") === `csReviewText-${i}`
        && e.children.indexOf(labels[0].parentNode) < e.children.indexOf(labels[1].parentNode);
    })
    && $("csReviewAgent-0").value === "Agent one" && $("csReviewText-0").value.length > 0,
    "each review has its own Reviewing agent label above its input, and its own response field");
  const reportCards = $("csReviews").querySelectorAll(".report-card");
  check(reportCards.length === 2 && reportCards.every((c) => /Not Verified, Not Findings/.test(c.textContent))
    && /Agent suggests: revise/.test(reportCards[0].textContent) && /Agent suggests: retain/.test(reportCards[1].textContent)
    && $("csDecision-0").value === "replace" && /display:\s*grid/.test(rule(css, ".cs-reviews")),
    "two valid reports that disagree are shown side by side, and neither changes a decision");
  check(!buttonSaying($("changeSetEditor"), "Attach report") && !/No report attached/.test($("changeSetEditor").textContent)
    && !fieldsIn($("csAgentReview")).some((i) => i.getAttribute("placeholder")),
    "there is no Attach report action, no “No report attached” status, and no placeholder text");
  csNext = fixture.cs_review_added;
  await click($("csAddReview"));
  await settle();
  check(lastCall("/api/changeset/review/add") && $("csReviews").querySelectorAll(".cs-review-entry").length === 3
    && $("csReviewAgent-2").value === "" && /Not yet written\./.test($("csReviewState-2").textContent),
    "Add another review adds an empty review of its own");
  check($("csAddReview").textContent === "Add another review",
    "once a review exists, the control reads Add another review");
  const savesBefore = calls.filter((c) => c.url === "/api/changeset/review/save").length;
  $("csReviewText-2").value = "not a report";
  $("csReviewText-2").dispatch("input");
  csNext = fixture.cs_review_invalid;
  $("csReviewText-2").dispatch("change");
  await settle();
  const reviewSaves = calls.filter((c) => c.url === "/api/changeset/review/save");
  check(reviewSaves.length === savesBefore + 1 && reviewSaves[reviewSaves.length - 1].body.text === "not a report"
    && reviewSaves[reviewSaves.length - 1].body.report_id === fixture.cs_review_added.reports[2].id,
    "a review saves on its own as it is written, with no attach step");
  check($("csReviewText-2").value === "not a report" && !$("csReview-2").classList.contains("is-valid")
    && /Not a structurally valid report yet, so it is not attached as advisory evidence/.test($("csReviewState-2").textContent)
    && $("csReviewState-2").querySelectorAll("li").length > 0 && $("csReviewAgent-2").value === "Third agent",
    "invalid text stays saved as written, with clear validation feedback, and is not attached evidence");
  const priorConfirmReview = global.confirm;
  let removalPrompts = 0;
  global.confirm = () => { removalPrompts += 1; return false; };
  const removesBefore = calls.filter((c) => c.url === "/api/changeset/report/remove").length;
  await click($("csRemoveReview-0"));
  check(removalPrompts === 1 && calls.filter((c) => c.url === "/api/changeset/report/remove").length === removesBefore,
    "removing a structurally valid report asks first; declined, nothing is removed");
  await click($("csRemoveReview-2"));
  check(removalPrompts === 1 && calls.filter((c) => c.url === "/api/changeset/report/remove").length === removesBefore + 1
    && lastCall("/api/changeset/report/remove").body.report_id === fixture.cs_review_added.reports[2].id,
    "removing a review that is not a valid report needs no confirmation, and removes only that review");
  global.confirm = priorConfirmReview;

  console.log("\nStale review evidence, and Refresh");
  csNext = fixture.cs_stale;
  await vm.runInThisContext("openChangeSet")(fixture.cs_stale.draft.id);
  await settle();
  check(/Stale — Refresh Before Applying/.test($("csPlan").textContent) && $("csPreview").disabled
    && $("csReviews").querySelectorAll(".report-card").every((c) => /Stale — not current review evidence/.test(c.textContent)),
    "a changed candidate makes the plan and its reports stale, and blocks applying");
  csNext = fixture.cs_refreshed;
  await click($("csRefresh"));
  check(lastCall("/api/changeset/refresh") && /Refreshed: .*candidate text changed/.test(toastNow().textContent)
    && !$("csPreview").disabled, "Refresh repins it and says what changed; the old reports stay stale");
  clearToasts();

  console.log("\nPreview and apply: one typed confirmation, then a receipt");
  await click($("csPreview"));
  check(lastPlan().body.kind === "changeset"
    && JSON.stringify(lastPlan().body.request) === JSON.stringify({ draft_id: fixture.cs_refreshed.draft.id,
      draft_revision: fixture.cs_refreshed.draft.revision }), "it previews exactly this draft's plan");
  const steps2 = $("csSteps").querySelectorAll("li");
  check(steps2[1].getAttribute("aria-current") === "step" && $("csPreviewing") && !$("setCompare")
    && !/Governing Now|Governing After/.test($("review").textContent),
    "the second screen, with no before-and-after lists");
  const previewBody = $("csPreviewBody");
  const order = previewBody.children.map((n) => n.getAttribute("id") === "planProblems" ? "problems"
    : n.classList.contains("cs-preview-warning") ? "warning" : n.getAttribute("id") === "csChangesToApply" ? "changes"
    : n.classList.contains("file-list") ? "files"
    : n.querySelector("#confirmPhrase") ? "confirm" : n.classList.contains("actions") ? "actions" : n.tagName);
  const firstOf = (k) => order.indexOf(k);
  check(firstOf("changes") >= 0 && firstOf("files") === firstOf("changes") + 1 && firstOf("confirm") > firstOf("files")
    && firstOf("actions") === order.length - 1
    && ["problems", "warning"].every((k) => firstOf(k) === -1 || firstOf(k) < firstOf("changes")),
    "one pass, in order: problems and warnings, Changes to Apply, files, then the typed confirmation");
  const csEffects = fixture.cs_refreshed.effects;
  const changeLines = $("csChangesToApply").querySelectorAll("li");
  const lineFor = (effect) => changeLines.find((li) => li.getAttribute("data-effect") === effect);
  const ofEffect = (effect) => csEffects.find((e) => e.effect === effect);
  check($("csChangesToApply").querySelector("h4").textContent === "Changes to Apply"
    && changeLines.length === csEffects.filter((e) => e.effect !== "retain").length
    && ["replace", "govern-alongside", "withdraw"].every((k) => !!lineFor(k)),
    "Changes to Apply has one line for each document the change set changes, and none for a retained one");
  check(lineFor("replace").textContent === `${ofEffect("replace").candidate_title} — Replaces “${ofEffect("replace").title}”`
    && lineFor("govern-alongside").textContent === `${ofEffect("govern-alongside").candidate_title} — Governs alongside`
    && lineFor("withdraw").textContent === `${ofEffect("withdraw").title} — Withdrawn`,
    "each line names the document by title and says what happens to it: replaces a named document, governs alongside, or withdrawn");
  const retainedTitle = ofEffect("retain").title;
  check(!/scope|Retained|Authority Effects|Current|Resulting/i.test($("csChangesToApply").textContent)
    && !$("csPreviewRetainedToggle") && !previewBody.querySelector(".scope-compare")
    && !$("csChangesToApply").textContent.includes(retainedTitle)
    && !/Retained Governing Documents|Authority Effects|Candidate's scope|Resulting scope/.test($("review").textContent),
    "no scope comparison, no retained-document list, and no Authority Effects section");
  check(previewBody.querySelectorAll(".file-item").length === fixture.cs_plan.changes.length - fixture.cs_plan.changes.filter((c) => c.action === "delete" && fixture.cs_plan.changes.some((o) => o.moved_from === c.path)).length
    && previewBody.querySelectorAll(".file-path").some((n) => n.textContent === "AGENT-CONTEXT.md"),
    "every changed file is a row with its diff, the regenerated map included");
  check(labelFor($("review"), "confirmPhrase").textContent === "Type “change governing context” once to apply the whole change set"
    && $("btnApply").textContent === "Apply" && !!buttonSaying(previewBody, "Cancel")
    && !/written as one action|does not stage, commit|receipt is kept privately|Document dates are assigned|confirmed in words/.test($("review").textContent),
    "one typed phrase, Apply and Cancel, and no note that only explains mechanics");
  type($("confirmPhrase"), "change governing context");
  csNext = fixture.cs_applied;
  await click($("btnApply"));
  const csApplied = lastCall("/api/changeset/apply").body;
  check(csApplied.confirm === "change governing context" && csApplied.id === fixture.cs_refreshed.draft.id
    && csApplied.plan_id === fixture.cs_plan.plan_id,
    "applying sends the phrase for this draft");
  check($("csAppliedStatus").textContent === "Change set applied" && /Private record — not context/.test($("csStatus").textContent)
    && /Agents read the new context now/.test($("csRecorded").textContent) && /Git is untouched/.test($("csRecorded").textContent)
    && /did not operate it/.test($("csRecorded").textContent) && !/Recorded in Git/.test($("changeSetEditor").textContent),
    "it becomes an immutable private receipt, led by its completion, saying agents read it and Git is left to the person");
  check($("csReceiptOutcomes").querySelectorAll("li").length === 3 && !$("csTitle") && !$("csDecision-0")
    && /Change set: Restructure/.test($("csSummary").textContent) && !!$("csCopySummary"),
    "with its changed documents, a copyable summary, and nothing editable");
  await click($("csBackToIndex"));
  check(!$("changeSetIndex").hidden && $("changeSetEditor").hidden, "← Change Sets returns to the index");
  clearToasts();

  console.log("\nLong scopes: one line in the row, the complete scope behind View details");
  csNext = fixture.cs_valid;
  await vm.runInThisContext("openChangeSet")(fixture.cs_valid.draft.id);
  await settle();
  const longScope = fixture.cs_long_scope;
  check(longScope.length > 400 && fixture.cs_valid.plan_candidates.some((c) => c.scope === longScope),
    "the plan's replacement has a scope of hundreds of characters");
  const revRow = fixture.cs_valid.plan_candidates.findIndex((c) => c.scope === longScope);
  const alongRow = fixture.cs_valid.plan_candidates.findIndex((c) => c.decision === "govern-alongside");
  const line = $(`csScopeLine-${revRow}`);
  check(line && line.classList.contains("cs-scope-oneline") && line.textContent === `Scope: ${longScope}`,
    "a replacement shows the candidate's scope as one line — the whole text, for a screen reader");
  check(!$(`csScopeToggle-${revRow}`) && !$("csCandidates").querySelectorAll(".disclosure-toggle").length
    && !$("csCandidates").querySelectorAll("dl").length && !/Full scope|Scope changes|Scope unchanged/.test($("csCandidates").textContent),
    "no row holds a scope disclosure, comparison table or other expanded comparison");
  check(!!$(`csEditDetails-${revRow}`) && $(`csEditDetails-${revRow}`).textContent === "Edit details…"
    && $(`csViewDetails-${revRow}`).textContent === "View details",
    "the planned candidate has View details and Edit details…");
  await click($(`csViewDetails-${revRow}`));
  check(/Candidate's scope[\s\S]*Current scope[\s\S]*Scope after/.test($("csDetails").textContent)
    && $("csDetails").textContent.indexOf(longScope) !== -1,
    "View details shows the whole scope beside the current and resulting scope");
  vm.runInThisContext("closeReview")();
  check($(`csScopeLine-${alongRow}`).textContent === `Scope: Delta: ${longScope}` && !!$(`csEditDetails-${alongRow}`)
    && !!$(`csViewDetails-${alongRow}`),
    "a candidate governing alongside shows one line too, beside View details and Edit details…");
  await click($(`csViewDetails-${alongRow}`));
  check($("csDetails").textContent.indexOf("Delta: " + longScope) !== -1 && !/Current scope/.test($("csDetails").textContent),
    "and its details show its whole scope, with nothing to compare");
  vm.runInThisContext("closeReview")();

  const oneline = rule(css, ".cs-scope-oneline");
  check(/white-space:\s*nowrap/.test(oneline) && /text-overflow:\s*ellipsis/.test(oneline) && /overflow:\s*hidden/.test(oneline),
    "on screen the line is clipped with an ellipsis, so a long scope cannot make the row tall");
  check(/min-width:\s*0/.test(rule(css, ".cs-item")) && /minmax\(0, 1fr\)/.test(rule(css, ".cs-item")),
    "and the row can shrink to its column, so nothing scrolls sideways");

  console.log("\nA blank candidate scope says it inherits the replaced document's");
  csNext = fixture.cs_blank;
  await vm.runInThisContext("openChangeSet")(fixture.cs_blank.draft.id);
  await settle();
  check(/^Scope: Blank — inherits the replaced document's scope$/.test($("csScopeLine-0").textContent),
    "the one line says the blank scope inherits");
  await click($("csViewDetails-0"));
  check(/\(inherited\)/.test($("csDetails").textContent), "and View details shows the inherited scope after");
  vm.runInThisContext("closeReview")();

  console.log("\nEdit details…: the candidate's own metadata, then back to the draft to refresh it");
  csNext = fixture.cs_valid;
  await vm.runInThisContext("openChangeSet")(fixture.cs_valid.draft.id);
  await settle();
  const editPath = fixture.cs_valid.plan_candidates[revRow].path;
  await click($(`csEditDetails-${revRow}`));
  check(lastCall("/api/draft").body.path === editPath && /^Edit “/.test($("review").querySelector("h3").textContent)
    && !$("changeSetEditor").hidden,
    "it opens that candidate's own Edit form, with the draft still open");
  await click(buttonSaying($("review"), "Preview the change"));
  check(lastPlan().body.kind === "edit-candidate" && !$("confirmPhrase"),
    "the edit is previewed as a candidate edit, with no phrase");
  csNext = fixture.cs_stale;
  const getsBefore = calls.filter((c) => c.url === "/api/changeset/get").length;
  await click($("btnApply"));
  check(lastCall("/api/apply").body.kind === "edit-candidate"
    && calls.filter((c) => c.url === "/api/changeset/get").length === getsBefore + 1
    && lastCall("/api/changeset/get").body.id === fixture.cs_stale.draft.id,
    "after saving, the page goes back to the draft");
  check(!$("changeSetEditor").hidden && $("csReasons") && !!$("csRefresh")
    && /refresh it to use the edited candidate/.test(toastNow().textContent),
    "which says the candidate changed, and offers Refresh");
  clearToasts();
  await vm.runInThisContext("closeChangeSet")();

  console.log("\nA draft in the earlier form: shown as recorded, converted only once the person confirms");
  csNext = fixture.cs_earlier;
  await vm.runInThisContext("openChangeSet")(fixture.cs_earlier.draft.id);
  await settle();
  check(/Earlier form/.test($("csStatus").textContent) && /Recorded in the Earlier Form/.test($("csEarlier").textContent)
    && $("csEarlierRows").querySelectorAll(".cs-row").length === 2
    && /Retain/.test($("csEarlierRows").textContent) && /Revise/.test($("csEarlierRows").textContent),
    "an earlier-form draft is shown as recorded: its retain and revise outcomes, as they were declared");
  check(!$("csPreview") && !$("csTitle") && !$("csAddCandidate") && !$("csCopyPrompt") && !$("csDecision-0")
    && !!buttonSaying($("changeSetEditor"), "Discard draft") && !buttonSaying($("changeSetEditor"), "Delete draft"),
    "it cannot be edited, reviewed or previewed; it can be discarded");
  check(!!$("csConvert") && $("csConvert").textContent === "Convert to current form…" && !$("csConversion"),
    "it offers Convert to current form…, which converts nothing yet");
  const convertsBefore = calls.filter((c) => c.url === "/api/changeset/convert").length;
  await click($("csConvert"));
  const conversionItems = $("csConversionChanges").querySelectorAll("li");
  check(conversionItems.length === fixture.cs_earlier.conversion.changes.length
    && conversionItems.every((li, i) => li.textContent.indexOf(fixture.cs_earlier.conversion.changes[i].text) !== -1)
    && /becomes Replace/.test($("csConversionChanges").textContent) && /retained without a decision/.test($("csConversionChanges").textContent)
    && calls.filter((c) => c.url === "/api/changeset/convert").length === convertsBefore,
    "Convert to current form… first shows every change it would make, and converts nothing");
  check(document.activeElement === $("csConversionHeading") && $("csConversion").getAttribute("role") === "region"
    && /changes no governing context/.test($("csConversionNote").textContent)
    && /become stale/.test($("csConversionNote").textContent),
    "focus moves to the list of changes, which says no governing context changes and reports go stale");
  await click($("csConvertCancel"));
  check(!$("csConversion") && document.activeElement === $("csConvert")
    && calls.filter((c) => c.url === "/api/changeset/convert").length === convertsBefore,
    "Cancel closes it and converts nothing");
  await click($("csConvert"));
  csNext = fixture.cs_converted;
  await click($("csConvertConfirm"));
  check(JSON.stringify(lastCall("/api/changeset/convert").body) === JSON.stringify({ id: fixture.cs_earlier.draft.id,
    revision: fixture.cs_earlier.draft.revision, confirm: true }),
    "Convert sends the person's confirmation, for the draft as it was shown");
  check(!/Earlier form/.test($("csStatus").textContent) && $("csDecision-0").value === "replace"
    && $("csTarget-0").value === "authoritative/c.md" && !!$("csPreview")
    && /Converted to the current form/.test(toastNow().textContent),
    "converted, it is an ordinary current-form plan: the revise is a Replace of the same document");
  clearToasts();
  await vm.runInThisContext("closeChangeSet")();

  console.log("\nApplied change sets: a receipt led by its completion and what it did");
  const applied = fixture.cs_applied_list.drafts.find((d) => d.state === "applied");
  check(applied && applied.final_outcomes === 3 && applied.established === fixture.cs_applied.receipt.after.length,
    "the server counts an applied change set from its receipt");
  const savedList = fixture.cs_list;
  fixture.cs_list = fixture.cs_applied_list;
  await vm.runInThisContext("renderChangeSets")();
  await settle();
  const card = $("changeSetList").querySelectorAll(".changeset-row").find((r) => r.getAttribute("data-id") === applied.id);
  check(!card && !/applied/.test($("changeSetList").textContent),
    "the normal index does not list an applied change set: its receipt stays private");
  check(/3 final outcomes · \d+ established governing documents/.test(vm.runInThisContext("changeSetCounts")(applied))
    && !/planned/.test(vm.runInThisContext("changeSetCounts")(applied)),
    "its recorded counts are final outcomes and established governing documents, never planned changes");
  fixture.cs_list = savedList;
  csNext = fixture.cs_applied;
  await vm.runInThisContext("openChangeSet")(fixture.cs_applied.draft.id);
  await settle();
  const receiptHead = $("changeSetPanel").querySelector("header");
  const appliedDay = fixture.cs_applied.receipt.at.slice(0, 10);
  check(receiptHead.children[0] === $("csAppliedStatus") && $("csAppliedStatus").getAttribute("role") === "status"
    && $("csAppliedStatus").textContent === "Change set applied" && receiptHead.children[1] === $("csOutcomeSummary"),
    "the receipt leads with Change set applied, then its outcome summary");
  check($("csOutcomeSummary").textContent
      === `1 document updated · 1 newly governing · 1 withdrawn · 1 retained · applied ${appliedDay}`,
    "the summary counts each outcome in plain words, with the date it was applied");
  check(!/updated by replacement/i.test($("changeSetEditor").textContent) && !/ 0 /.test($("csOutcomeSummary").textContent),
    "no technical phrasing, and no category with nothing in it");
  const receiptItems = $("csReceiptOutcomes").querySelectorAll("li");
  console.log("    lines: " + receiptItems.map((li) => li.querySelector(".cs-receipt-line").textContent).join(" | "));
  check(receiptItems.map((li) => li.querySelector(".cs-receipt-line").textContent).join(" | ")
      === "AlphaReplaced | BetaWithdrawn | DeltaGoverns alongside" && /by “Alpha two”/.test(receiptItems[0].textContent),
    "each changed document is listed by its title first, with a badge naming its outcome as recorded");
  const detailToggle = $("csReceiptDetailToggle-0");
  check(detailToggle.textContent === "Technical details" && detailToggle.getAttribute("aria-expanded") === "false"
    && regionOf(detailToggle).hidden && !/archive\//.test(receiptItems[0].querySelector(".cs-receipt-line").textContent)
    && /archive\/a-superseded\.md/.test(regionOf(detailToggle).textContent)
    && /authoritative\/a\.md/.test(regionOf(detailToggle).textContent),
    "its path and archive location sit behind a collapsed, keyboard-operable Technical details disclosure");
  await click(detailToggle);
  check(detailToggle.getAttribute("aria-expanded") === "true" && !regionOf(detailToggle).hidden, "opened, it shows them");
  await click(detailToggle);
  check($("csReceiptRetainedToggle").textContent === "Retained Governing Documents (1)"
    && $("csReceiptRetainedToggle").getAttribute("aria-expanded") === "false" && regionOf($("csReceiptRetainedToggle")).hidden
    && $("csReceiptRetained").querySelectorAll("li").length
      === fixture.cs_applied.receipt.outcomes.filter((o) => o.effect === "retain").length,
    "the retained documents are listed apart, collapsed");
  check($("csReceiptEstablishedToggle").getAttribute("aria-expanded") === "false"
    && $("csReceiptEstablishedToggle").textContent
      === `Established Governing Documents (${fixture.cs_applied.receipt.after.length})`
    && $("csReceiptEstablished").querySelectorAll("li").length === fixture.cs_applied.receipt.after.length,
    "the established governing documents are behind a disclosure too");
  check(/2 advisory reports attached/.test($("csReceiptReview").textContent) && !$("csReceiptNoReport")
    && $("csReceiptShared").querySelectorAll("li").length === 1
    && /^Review prompt copied/.test($("csReceiptShared").textContent)
    && /not advisory evidence/.test($("csReceiptSharedSection").textContent)
    && !insideOf($("csReceiptShared"), $("csReceiptReview")),
    "the advisory reports are apart from the record of the review prompt copied, which is not evidence");
  const summaryToggle = $("csSummaryToggle");
  check(summaryToggle.textContent === "Technical change summary" && summaryToggle.getAttribute("aria-expanded") === "false"
    && regionOf(summaryToggle).hidden && /\nFinal outcomes:\n/.test($("csSummary").textContent)
    && !insideOf($("csCopySummary"), regionOf(summaryToggle)),
    "the full technical change summary is collapsed, and Copy summary works without opening it");
  check(!/planned/i.test($("changeSetEditor").textContent.replace($("csSummary").textContent, "")),
    "nothing on the receipt says planned");
  await vm.runInThisContext("closeChangeSet")();

  console.log("\nA receipt with no review: said plainly, with no shared-material record");
  const unreviewed = JSON.parse(JSON.stringify(fixture.cs_applied));
  unreviewed.receipt.reports = [];
  unreviewed.receipt.prompts = [{ mode: "packet", exported: "2026-10-14T09:00:00+00:00" }];
  csNext = unreviewed;
  await vm.runInThisContext("openChangeSet")(unreviewed.draft.id);
  await settle();
  check($("csReceiptNoReport").textContent === "No advisory report attached."
    && $("csReceiptShared").textContent === "Review packet exported · 2026-10-14",
    "no advisory report attached, and separately, the review packet exported");
  unreviewed.receipt.prompts = [];
  await vm.runInThisContext("openChangeSet")(unreviewed.draft.id);
  await settle();
  check(!!$("csReceiptNoReport") && !$("csReceiptSharedSection"), "with nothing shared, there is no shared-material record");
  await vm.runInThisContext("closeChangeSet")();

  console.log("\nAn earlier-form receipt keeps its stored summary and outcomes as recorded");
  const older = JSON.parse(JSON.stringify(fixture.cs_applied));
  older.receipt.summary = older.receipt.summary.replace("Final outcomes:", "Declared outcomes:");
  older.receipt.outcomes.forEach((o) => { if (o.effect === "replace") o.effect = "revise"; });
  csNext = older;
  await vm.runInThisContext("openChangeSet")(older.draft.id);
  await settle();
  check($("csSummary").textContent === older.receipt.summary && /Declared outcomes:/.test($("csSummary").textContent)
    && /^1 document revised · 1 newly governing · 1 withdrawn · 1 retained/.test($("csOutcomeSummary").textContent)
    && /AlphaRevised/.test($("csReceiptOutcomes").textContent),
    "its summary is shown exactly as kept, and its revision counted and badged as Revised");
  await vm.runInThisContext("closeChangeSet")();
  clearToasts();

  /* ------------------------------------------------- Git-base comparison */

  console.log("\nGit-base comparison is the `charter compare` command, not part of the console");
  await show("state_git");
  await navTo("changesets");
  check(fixture.state_git.status.git.state === "checkout" && !$("gitCompare") && !$("compareToggle")
    && !$("compareBase") && !$("btnCompare") && !/Compare with a Git Base/i.test(document.body.textContent),
    "even in a readable Git checkout, Change Sets offers no comparison control");
  check(!calls.some((c) => /^\/api\/compare/.test(c.url)) && !/\/api\/compare/.test(fs.readFileSync(path.join(STATIC, "app.js"), "utf8")),
    "the page never asks for a comparison");
  await show("state_valid");

  /* ---------------------------------------------------------- connect agents */

  console.log("\nConnect agents: copy-ready text for a ready Agent Context");
  const connectView = () => $("view-connect");
  const sentBefore = calls.filter((c) => c.method !== "GET").length;
  for (const [name, payload] of [["Windows", fixture.connect_windows], ["macOS and Linux", fixture.connect_posix]]) {
    connectAnswer = payload;
    await navTo("connect");
    const v = connectView();
    const firstH2 = v.querySelector("h2");
    check(!v.hidden && firstH2.textContent === "Connect Agents" && v.querySelectorAll("h2").length === 1
      && document.title === "Connect Agents — Charter"
      && !v.querySelector(".lede") && !$("connectStatus") && !/ready to connect/i.test(v.textContent)
      && $("connectMcp").getAttribute("aria-labelledby") === "connectMcpTitle"
      && $("connectMcpDetails").firstChild === $("connectMcpInstruction")
      && $("connectMcpInstruction").textContent === "Configure the Charter MCP server for your agent."
      && !$("connectFolder") && !$("connectChecksDetails") && !$("connectLaunch") && !$("connectWritesNothing")
      && !$("connectPrerequisite"),
      `${name}: the page is titled Connect Agents; the MCP section opens with its one purpose sentence`);
    const sections = [["connectMcp", "connectMcpTitle", "connectMcpToggle", "connectMcpDetails", "Connect Agents with MCP (Recommended)"],
      ["connectPointerSection", "connectPointerTitle", "connectPointerToggle", "connectPointerDetails", "Add Project Instructions (Optional)"],
      ["connectVerify", "connectTestTitle", "connectTestToggle", "connectTestDetails", "Test the Connection (Optional)"],
      ["connectOther", "connectFilesTitle", "connectFilesToggle", "connectFilesDetails", "Connect Agents with File Access"]];
    check(sections.every(([s], i) => $("connectBody").children.indexOf($(s)) === i) && $("connectBody").children.length === 4,
      `${name}: four sections, in order: MCP, project instructions, the connection test, file access`);
    check(sections.every(([s, t, tg, d, label]) => $(s).getAttribute("aria-labelledby") === t && $(t).tagName === "H3"
        && $(t).children.length === 1 && $(t).firstChild === $(tg) && $(tg).classList.contains("disclosure-toggle")
        && $(tg).textContent === label && $(tg).getAttribute("aria-controls") === d && $(s).children[1] === $(d)),
      `${name}: each section's heading is its own toggle, all alike`);
    check(sections.map(([, , tg, d]) => [$(tg).getAttribute("aria-expanded"), $(d).hidden].join()).join(" | ")
        === "true,false | false,true | false,true | false,true",
      `${name}: only the MCP section is open at first`);
    check(!v.querySelectorAll(".connect-reveal").length && !/Show text|Hide text/.test(v.textContent)
      && !rule(css, ".connect-reveal-body") && v.querySelectorAll(".disclosure-toggle").length === 4,
      `${name}: no Show text or Hide text controls remain`);
    const server = JSON.parse($("connectConfig").textContent).mcpServers[payload.server_name];
    const launched = [server.command].concat(server.args).join(" ");
    check($("connectConfig").textContent === payload.config_text
      && launched.endsWith(" mcp --context " + payload.folder) && server.command === payload.command
      && server.command !== "charter" && server.command !== "cmd",
      `${name}: the MCP configuration runs this copy by its full path: mcp --context <folder>`);
    payload.shells.forEach((s) => check($("connectClaude-" + s.shell).textContent === s.claude_code
      && /^claude mcp add charter-/.test(s.claude_code) && s.claude_code.indexOf("--scope") === -1,
      `${name}: the claude mcp add command for ${s.label} is shown exactly, at Claude Code's default local scope`));
    check($("connectCodex").textContent === payload.codex_toml && /^\[mcp_servers\./.test(payload.codex_toml)
      && $("connectPointer").textContent === payload.pointer
      && $("connectVerifyPrompt").textContent === payload.verify_prompt,
      `${name}: Codex's TOML, the startup pointer and the verification prompt are shown exactly`);
    check(v.querySelectorAll("h3").map((h) => h.textContent).join(" | ")
        === "Connect Agents with MCP (Recommended) | Add Project Instructions (Optional) | Test the Connection (Optional) | Connect Agents with File Access"
      && !/1\. Connect an agent|2\. Confirm it works|Optional file access|Send this in a new agent session/.test(v.textContent)
      && !$("connectProposals") && !$("connectVisible") && !$("connectTrustDetails") && !$("connectReadme")
      && !$("connectCheckToggle") && !$("connectCheckDetails") && !$("connectVscodeDetails") && !$("connectVscodeItem")
      && !/Troubleshoot|VS Code|--scope|scope project|under your account|charter propose|every project|Access and trust|--check|handshake|follows|retrieval is|proof/
        .test(v.textContent),
      `${name}: connect, confirm, optional file access — no troubleshooting, VS Code workaround, scopes, trust or proof text`);
    const hostLabels = $("connectHosts").querySelectorAll("label").map((l) => l.textContent);
    const legend = $("connectHosts").querySelector("legend");
    check($("connectHosts").tagName === "FIELDSET" && legend.textContent === "Choose an agent host"
      && legend.classList.contains("sr-only") && !/Agent host\b/.test(v.textContent.replace("Choose an agent host", ""))
      && $("connectHosts").querySelectorAll("input").every((i) => i.getAttribute("name") === "connectHost"
        && !!labelFor($("connectHosts"), i.id))
      && hostLabels.join() === "Claude Code,Codex,Other MCP host"
      && $("connectHostChoice-claude").checked && !$("connectHostChoice-codex").checked && !$("connectHostChoice-other").checked
      && $("connectHostChoice-claude").getAttribute("type") === "radio",
      `${name}: three labelled radios in a fieldset whose legend is read, not drawn; Claude Code chosen`);
    check(!$("connectHost-claude").hidden && $("connectHost-codex").hidden && $("connectHost-other").hidden
      && $("connectHost-claude").getAttribute("aria-label") === "Claude Code"
      && !$("connectClaudeNote") && !$("connectHost-claude").querySelectorAll(".hint").length
      && $("connectCodexBlock").querySelector(".hint").textContent === "Add this to your Codex configuration, then restart Codex."
      && $("connectConfigBlock").querySelector(".hint").textContent === "Add this using your host's MCP instructions.",
      `${name}: only Claude Code's setup shows, with no note of its own; Codex and other hosts keep one sentence`);
    check(payload.shells.every((s) => $("connectHost-claude").querySelector("#connectClaude-" + s.shell))
      && (name === "Windows"
        ? $("connectClaude-powershellBlock").querySelector("h4").textContent === "PowerShell"
          && $("connectClaude-cmdBlock").querySelector("h4").textContent === "Command Prompt"
        : !$("connectClaude-posixBlock").querySelector("h4")),
      `${name}: ${name === "Windows" ? "PowerShell and Command Prompt are each labelled" : "one terminal command"}`);
    check(insideOf($("connectHosts"), $("connectMcpDetails")) && insideOf($("connectClaude-" + payload.shells[0].shell), $("connectMcpDetails"))
      && insideOf($("btnCopyConnectConfig"), $("connectMcpDetails"))
      && insideOf($("connectPointer"), $("connectPointerDetails")) && insideOf($("btnCopyConnectPointer"), $("connectPointerDetails"))
      && insideOf($("connectVerifyPrompt"), $("connectTestDetails")) && insideOf($("btnCopyConnectVerifyPrompt"), $("connectTestDetails"))
      && insideOf($("connectInstruction"), $("connectFilesDetails")) && !insideOf($("connectPointerSection"), $("connectMcp")),
      `${name}: host choice, setup commands and their Copy actions are in the MCP section; each optional text and its Copy only in its own closed section`);
    await click($("connectPointerToggle"));
    check(!$("connectPointerDetails").hidden && $("connectPointerToggle").getAttribute("aria-expanded") === "true"
      && $("connectTestDetails").hidden && $("connectFilesDetails").hidden && !$("connectMcpDetails").hidden,
      `${name}: its heading opens the project instructions, and only those`);
    const pointerParts = $("connectPointerDetails").children;
    check(pointerParts[0] === $("connectPointerNote")
      && pointerParts[1] === $("connectPointerBlock")
      && $("connectPointerNote").textContent === "Copy this into the project instructions or system context your agent receives—for example, CLAUDE.md, AGENTS.md, or your agent host’s equivalent. Do not put it in AGENT-CONTEXT.md or anywhere inside the Agent Context folder."
      && $("connectPointerNote").querySelectorAll("code").map((c) => c.textContent).join()
        === "CLAUDE.md,AGENTS.md,AGENT-CONTEXT.md"
      && !$("connectPointerBlock").querySelector(".hint") && !/AGENT-CONTEXT-MAP|instruction file\u2014not/.test(v.textContent)
      && $("connectPointer").textContent === payload.pointer && !!$("btnCopyConnectPointer"),
      `${name}: where it goes comes first, file names as code, then the unchanged pointer and its Copy button`);
    $("connectHostChoice-codex").checked = true;
    $("connectHostChoice-codex").dispatch("change");
    check($("connectHost-claude").hidden && !$("connectHost-codex").hidden && $("connectHost-other").hidden,
      `${name}: choosing Codex shows its setup instead`);
    $("connectHostChoice-other").checked = true;
    $("connectHostChoice-other").dispatch("change");
    check(!$("connectHost-other").hidden && $("connectHost-codex").hidden
      && /mcpServers/.test($("connectHost-other").textContent),
      `${name}: and Other MCP host its JSON`);
    await navTo("governing");
    await navTo("connect");
    check(!$("connectHost-other").hidden && $("connectHostChoice-other").checked,
      `${name}: the choice outlives a redraw`);
    $("connectHostChoice-claude").checked = true;
    $("connectHostChoice-claude").dispatch("change");
    check($("connectFilesDetails").hidden && $("connectFilesToggle").getAttribute("aria-expanded") === "false"
      && $("connectInstruction").textContent === payload.instruction
      && payload.instruction.indexOf(payload.map) !== -1 && /AGENT-CONTEXT\.md$/.test(payload.map)
      && $("connectFilesDetails").firstChild === $("connectFilesNote")
      && $("connectFilesNote").textContent === "Requires direct read access to the Agent Context folder. See the README for guidance."
      && !$("connectInstructionBlock").querySelector(".hint")
      && $("connectFilesDetails").querySelectorAll("p").length === 1
      && $("connectFilesToggle").parentNode.tagName === "H3"
      && $("connectFilesToggle").textContent === "Connect Agents with File Access",
      `${name}: file access is a closed section heading: one warning first, then the instruction`);
    await click($("connectFilesToggle"));
    check(!$("connectFilesDetails").hidden && $("connectFilesToggle").getAttribute("aria-expanded") === "true",
      `${name}: and opens from its heading`);
    await click($("connectFilesToggle"));
    await click($("connectTestToggle"));
    check(!$("connectVerifyPromptBlock").querySelector(".hint") && $("connectTestTitle").textContent === "Test the Connection (Optional)"
      && $("connectVerify").getAttribute("aria-labelledby") === "connectTestTitle"
      && !$("connectTestDetails").hidden && !!$("btnCopyConnectVerifyPrompt"),
      `${name}: Test the connection opens to its prompt and Copy button, with no other words`);
    await navTo("governing");
    await navTo("connect");
    check(!$("connectTestDetails").hidden && !$("connectPointerDetails").hidden && $("connectFilesDetails").hidden,
      `${name}: what was opened stays open across a redraw`);
    await click($("connectTestToggle"));
    await click($("connectPointerToggle"));
    await click($("connectMcpToggle"));
    check($("connectMcpDetails").hidden && $("connectMcpToggle").getAttribute("aria-expanded") === "false",
      `${name}: the MCP section closes from its heading like the others`);
    await click($("connectMcpToggle"));
  }
  check(fixture.connect_windows.shells.map((s) => s.label).join() === "PowerShell,Command Prompt"
    && fixture.connect_posix.shells.map((s) => s.label).join() === "Terminal",
    "Windows offers PowerShell and Command Prompt commands; elsewhere one terminal command");
  check(fixture.connect_ready.ready && fixture.connect_ready.folder === fixture.state_valid.root,
    "the console's own answer for the open, valid Agent Context is ready");

  console.log("\nHosts start this copy by its full path: PATH never blocks connecting");
  for (const [name, payload] of [["Windows", fixture.connect_windows], ["macOS and Linux", fixture.connect_posix]]) {
    const server = payload.config.mcpServers[payload.server_name];
    check(payload.connect === "ready" && !["charter", "py", "cmd"].includes(server.command)
      && !server.args.includes("/c") && /[\\/]/.test(server.command),
      `${name}: the registration is a program by its full path with exact arguments, never a bare charter, py or cmd /c`);
  }
  check(/python/i.test(fixture.connect_windows.command) && /charter\.py$/.test(fixture.connect_windows.args[0]),
    "Windows: the program is the Python running Charter, its first argument this copy's charter.py");
  connectAnswer = fixture.connect_windows;
  await navTo("governing");
  await navTo("connect");
  check(!$("connectStatus") && !$("connectPathConflict") && !$("connectPrerequisite") && !$("connectAddToPath")
    && /Keep Charter in one folder/.test($("connectInstallNote").textContent)
    && /move Charter, or change the Python/.test($("connectInstallNote").textContent),
    "ready, with no PATH prerequisite, and a short note: update Charter in place; reconnect if it or its Python moves");

  console.log("\nAnother copy first on PATH: Connect Agents says nothing about it");
  connectAnswer = fixture.connect_windows_conflict;
  await navTo("governing");
  await navTo("connect");
  check(fixture.connect_windows_conflict.connect === "ready" && !$("connectPathConflict") && !!$("connectConfig")
    && $("view-connect").textContent.indexOf(fixture.connect_other_copy) === -1
    && !/Remove .+ from your PATH|add-to-path|Charter command/.test($("view-connect").textContent),
    "the full-path setup is offered as always, with no PATH warning or remedy: the header's Charter command status has it");
  clearToasts();

  console.log("\nA folder Command Prompt cannot type: PowerShell's command only");
  connectAnswer = fixture.connect_powershell_only;
  await navTo("governing");
  await navTo("connect");
  check(fixture.connect_powershell_only.connect === "ready" && !!$("connectClaude-powershell") && !$("connectClaude-cmd")
    && !!$("connectConfig"),
    "a path with % or &: MCP is offered, with the PowerShell registration command and the exact configuration");
  connectAnswer = fixture.connect_windows;

  console.log("\nA path no host can carry exactly: file access, and the MCP limitation");
  connectAnswer = fixture.connect_files_only;
  await navTo("governing");
  await navTo("connect");
  check($("connectStatus").dataset.connect === "files-only"
    && /^Agent Context ready for file access\./.test($("connectStatusText").textContent)
    && !/ready to connect/i.test($("connectStatus").textContent),
    "it says the Agent Context is ready for file access, not ready to connect");
  check(!!$("connectMcpLimitation") && /No MCP configuration is offered/.test($("connectMcpLimitation").textContent),
    "it gives the concrete MCP limitation");
  check(!$("connectConfig") && !$("connectClaude-powershell") && !$("connectClaude-cmd")
    && !$("connectCodex") && !$("connectPointer") && !$("connectCheckToggle") && !$("connectAddToPath")
    && connectView().querySelectorAll("pre").length === 2 && !!$("connectVerifyPrompt"),
    "and offers no MCP configuration or command that would not work: only the verification prompt and file instruction");
  check($("connectInstruction").textContent === fixture.connect_files_only.instruction
    && !!$("btnCopyConnectInstruction") && !$("connectFilesDetails").hidden
    && $("connectFilesToggle").getAttribute("aria-expanded") === "true" && !$("connectHosts"),
    "the file-access instruction, the only route here, starts open to copy; no host choice is offered");
  check(!$("connectPointerSection") && $("connectBody").children.map((s) => s.id).join() === "connectStatus,connectMcp,connectVerify,connectOther"
    && !$("connectMcpDetails").hidden && $("connectTestDetails").hidden,
    "with no MCP route there are no project instructions; the MCP section stays open to show why");
  connectAnswer = fixture.connect_windows;
  await navTo("governing");

  console.log("\nCopying touches only the clipboard");
  Object.defineProperty(global, "navigator", { configurable: true,
    value: { clipboard: { writeText: async (t) => { global.__copied = t; } } } });
  connectAnswer = fixture.connect_windows;
  await navTo("connect");
  for (const [button, text] of [["btnCopyConnectConfig", fixture.connect_windows.config_text],
    ["btnCopyConnectClaude-powershell", fixture.connect_windows.shells[0].claude_code],
    ["btnCopyConnectClaude-cmd", fixture.connect_windows.shells[1].claude_code],
    ["btnCopyConnectCodex", fixture.connect_windows.codex_toml],
    ["btnCopyConnectPointer", fixture.connect_windows.pointer],
    ["btnCopyConnectVerifyPrompt", fixture.connect_windows.verify_prompt],
    ["btnCopyConnectInstruction", fixture.connect_windows.instruction]]) {
    clearToasts();
    await click($(button));
    check(global.__copied === text && /Nothing was written/.test(toastNow().textContent),
      `${button} copies exactly the text shown`);
  }
  check(calls.filter((c) => c.method !== "GET").length === sentBefore
    && calls.filter((c) => c.url === "/api/connect").every((c) => c.method === "GET"),
    "showing and copying sent nothing but reads to the server");
  /* Actions only: a toggle that opens or closes part of the page is not one. */
  const connectButtons = connectView().querySelectorAll("button").filter((b) => !b.getAttribute("aria-expanded"))
    .map((b) => b.textContent.trim());
  check(!connectButtons.some((t) => /^(Register|Connect|Apply|Set up|Setup|Install|Write|Add)/i.test(t))
    && connectButtons.filter((t) => /^Copy (command|MCP|Codex|startup|prompt|agent)/.test(t)).length === 7,
    "there is no register, connect, apply or setup action: only Copy");
  check(!/\b(workspace|surface|publication|publish|binding|cgu)\b/i.test(connectView().textContent),
    "the wording is Charter's own");
  for (const sel of ["#connectBody", ".connect-method p"]) {
    check(!/max-width/.test(rule(css, sel)), `${sel} is not held to a narrow column`);
  }
  check(/font:\s*inherit/.test(rule(css, ".connect-section-title .disclosure-toggle"))
    && /max-width:\s*none/.test(rule(css, ".connect-method .disclosure-body"))
    && /minmax\(0, 1fr\)/.test(rule(css, "#connectBody")) && /auto-fit/.test(rule(css, ".connect-shells")),
    "the lede uses the full width; the body and the shell commands still reflow on a narrow screen");

  console.log("\nThe Charter command status: in the header, independent of the context's");
  const commandChip = () => $("barCommand").firstChild;
  for (const [answer, label, tone] of [[fixture.command_ready, "Charter command ready", "ok"],
    [fixture.command_other, "Charter command needs attention", "warn"],
    [fixture.command_missing, "Charter command needs attention", "warn"]]) {
    commandAnswer = answer;
    await vm.runInThisContext("refresh")();
    await settle();
    check(commandChip() && commandChip().textContent === label && commandChip().classList.contains(tone)
      && $("barState").textContent === "Agent context ready"
      && $("barCommand").textContent.indexOf("Agent context") === -1 && !$("refusedCard"),
      `\`charter\` ${answer.state}: “${label}”, in the ${tone === "ok" ? "positive" : "warning"} treatment, beside an unchanged “Agent context ready”`);
  }
  check(commandChip().tagName === "BUTTON" && commandChip().getAttribute("type") === "button"
    && commandChip().getAttribute("aria-haspopup") === "dialog" && commandChip().getAttribute("tabindex") !== "-1",
    "needs attention is a real button, so the keyboard reaches and activates it, and it says it opens a dialog");
  const fix = $("btnCommandFix");
  check(fix && fix.tagName === "BUTTON" && fix.textContent === "Fix…" && fix.getAttribute("type") === "button"
    && fix.classList.contains("btn") && fix.classList.contains("small") && !fix.classList.contains("chip")
    && fix.getAttribute("aria-haspopup") === "dialog" && $("barCommand").children.length === 2
    && $("barCommand").children[0] === commandChip() && $("barCommand").children[1] === fix,
    "Fix… follows immediately after the amber status: a compact button in the shared treatment, saying it opens a dialog");
  check(/cursor:\s*pointer/.test(rule(css, ".chip-button")) && /border-color/.test(rule(css, ".chip-button:hover"))
    && /background/.test(rule(css, ".btn:hover")) && /outline:\s*2px solid/.test(rule(css, ":focus-visible")),
    "both have hover and visible keyboard focus: the chip its own hover, Fix… the shared button's, both the shared focus ring");
  await click(fix);
  await settle();
  check($("commandDialog") && $("commandTitle").textContent === "Charter Command Needs Attention"
    && document.activeElement && document.activeElement.textContent === "Close",
    "Fix… opens the same remedy dialog");
  document.dispatch("keydown", { key: "Escape" });
  check(!$("commandDialog") && document.activeElement && document.activeElement.id === "btnCommandFix",
    "closing it returns focus to Fix…, the control that opened it");
  commandAnswer = fixture.command_ready;
  await vm.runInThisContext("refresh")();
  await settle();
  check(commandChip().tagName === "SPAN" && !$("btnCommandStatus") && !$("btnCommandFix")
    && $("barCommand").children.length === 1,
    "ready is a plain green status, with nothing to open and no Fix…");

  commandAnswer = fixture.command_other;
  await vm.runInThisContext("refresh")();
  await settle();
  check(!$("btnNewChangeSet").disabled && !$("btnAddDocument").disabled && !$("btnImportProposal").disabled,
    "needs attention disables nothing: change sets, candidates and proposals stay available");
  await click($("btnCommandStatus"));
  await settle();
  const dialog = $("commandDialog");
  check(lastCall("/api/command") && dialog && dialog.getAttribute("role") === "dialog"
    && dialog.getAttribute("aria-modal") === "true" && $("commandTitle").textContent === "Charter Command Needs Attention"
    && document.querySelector(".rail").inert === true && document.querySelector(".skip-link").inert === true
    && document.activeElement && document.activeElement.textContent === "Close",
    "it opens a focused dialog, asking PATH afresh: modal, the page behind inert (skip link included), focus on Close");
  check($("commandFound").textContent === `The charter command runs another copy of Charter, from ${fixture.command_other.other_folder}.`
    && /would use that copy, not the one managing this Agent Context/.test($("commandImpact").textContent)
    && /charter propose/.test($("commandImpact").textContent)
    && /Connect Agents run this copy by its full path, so they are unaffected/.test($("commandSafe").textContent),
    "it names the other copy's folder, what a new terminal or `charter propose` would do, and that full-path agents are unaffected");
  check($("commandStep").textContent === `Remove ${fixture.command_other.other_folder} from your PATH. Then: in PowerShell, put this copy on your PATH:`
    && $("commandRemedy").textContent === fixture.command_other.remedy
    && /^& '[^']*python\.exe' '?[^']*charter\.py'? add-to-path$/.test($("commandRemedy").textContent)
    && !/(^|\s)(py|charter|cmd)(\s|$)/.test($("commandRemedy").textContent)
    && $("commandRemedy").textContent.indexOf(fixture.command_other.other_folder) === -1
    && !!$("btnCopyCommandRemedy"),
    "the remedy: remove that folder, then one copy-ready PowerShell command by full paths, nothing bare, nothing that runs the other copy");
  check(/^Afterwards, open a new terminal/.test($("commandAfter").textContent), "and to open a new terminal afterwards");
  Object.defineProperty(global, "navigator", { configurable: true,
    value: { clipboard: { writeText: async (t) => { global.__copied = t; } } } });
  await click($("btnCopyCommandRemedy"));
  check(global.__copied === fixture.command_other.remedy, "Copy command copies exactly that command");
  clearToasts();
  document.dispatch("keydown", { key: "Escape" });
  check(!$("commandDialog") && $("docViewer").hidden && !document.querySelector(".rail").inert
    && document.activeElement && document.activeElement.id === "btnCommandStatus",
    "Escape closes it, releasing the page, and focus returns to the status");
  await click($("btnCommandStatus"));
  await settle();
  await click(buttonSaying($("commandDialog"), "Close"));
  check(!$("commandDialog") && document.activeElement && document.activeElement.id === "btnCommandStatus",
    "Close closes it too, focus back on the status");

  commandAnswer = fixture.command_missing;
  await vm.runInThisContext("refresh")();
  await settle();
  await click($("btnCommandStatus"));
  await settle();
  check($("commandFound").textContent === "The charter command is not found on PATH."
    && /cannot run Charter/.test($("commandImpact").textContent)
    && $("commandStep").textContent === "In PowerShell, put this copy on your PATH:"
    && $("commandRemedy").textContent === fixture.command_missing.remedy && /Afterwards, open a new terminal/.test($("commandAfter").textContent),
    "`charter` not found: said so, with the same full-path remedy and new-terminal step");
  await click(buttonSaying($("commandDialog"), "Close"));

  commandAnswer = fixture.command_other_posix;
  await vm.runInThisContext("refresh")();
  await settle();
  if ($("btnCommandStatus")) {
    await click($("btnCommandStatus"));
    await settle();
    check($("commandRemedy").textContent === fixture.command_other_posix.remedy
      && /it says what to add to your shell startup file/.test($("commandStep").textContent),
      "macOS and Linux: this copy's launcher by full path, which says what to add to the shell startup file");
    await click(buttonSaying($("commandDialog"), "Close"));
  }
  commandAnswer = fixture.command_other;
  currentState = fixture.state_unclean || currentState;
  await vm.runInThisContext("refresh")();
  await settle();
  check(!fixture.state_unclean || ($("barState").textContent === "Agent context unavailable"
    && commandChip().textContent === "Charter command needs attention"),
    "an unavailable context and a command needing attention are two separate statuses, each its own");
  currentState = fixture.state_valid;
  commandAnswer = fixture.command_ready;
  await vm.runInThisContext("refresh")();
  await settle();
  clearToasts();

  console.log("\nUnknown origin is said on Governing documents only");
  const beforeOrigin = currentState;
  currentState = fixture.state_valid;
  for (const view of ["connect", "settings", "candidates", "proposals", "changesets"]) {
    await navTo(view);
    check(!insideOf($("originUnknown"), $("view-" + view)) && !insideOf($("originUnknown"), $("contextStatus"))
      && $("view-governing").hidden && $("contextStatus").textContent.indexOf("Origin unknown") === -1,
      `${view}: the origin-unknown notice is not shown`);
  }
  await navTo("governing");
  check(!$("view-governing").hidden && !$("originUnknown").hidden
    && $("originUnknown").textContent === "Origin unknown. These files are valid, but Charter has no local record of how this version was created or changed.",
    "Governing documents still says the origin is unknown");

  console.log("\nUnknown origin, changed outside Charter, and invalid stay distinct");
  check(!$("outsideNotice") && !$("refusedCard") && $("btnRebuildContext").hidden && !$("originUnknown").hidden,
    "a valid context of unknown origin: the plain notice only — no outside-change card, no refusal, no Rebuild");
  await show("state_rebuilt");
  check(!!$("outsideNotice") && /changed outside Charter/i.test($("outsideNotice").textContent)
    && $("originUnknown").hidden && !$("refusedCard"),
    "changed outside Charter: its own notice, and no origin-unknown notice");
  await show("state_invalid");
  check(!!$("refusedCard") && !!$("btnRebuildFromStatus") && $("originUnknown").hidden,
    "invalid: the refusal and its Rebuild, and no origin-unknown notice");
  const invalidUnknown = JSON.parse(JSON.stringify(fixture.state_invalid));
  invalidUnknown.status.outside = Object.assign({}, fixture.state_valid.status.outside);
  currentState = invalidUnknown;
  await reload();
  check(!!$("refusedCard") && !!$("btnRebuildFromStatus") && !$("originUnknown").hidden
    && $("originUnknown").textContent === "Origin unknown. Charter has no local record of how this version was created or changed."
    && !/valid/.test($("originUnknown").textContent),
    "invalid and of unknown origin: the refusal leads, and the notice no longer calls the files valid");
  currentState = beforeOrigin;
  await reload();
  clearToasts();

  console.log("\nNot ready: the reason, and nothing to copy");
  for (const [name, payload] of [["unclean", fixture.connect_unclean], ["invalid", fixture.connect_invalid]]) {
    connectAnswer = payload;
    await navTo("governing");
    await navTo("connect");
    check(!payload.ready && !!$("connectNotReady") && !$("connectStatus")
      && /^Not ready to connect/.test($("connectNotReady").textContent)
      && $("connectReasons").querySelectorAll("li").length === payload.reasons.length
      && $("connectReasons").textContent.indexOf(payload.reasons[0]) !== -1,
      `${name}: it says why it is not ready`);
    check(!$("connectConfig") && !$("connectInstruction") && !connectView().querySelector("pre")
      && !connectView().querySelectorAll("button").some((b) => /^Copy/.test(b.textContent.trim())),
      `${name}: no configuration, command or instruction is offered`);
    check(!$("connectVisible") && !$("connectWritesNothing"),
      `${name}: no trust section or footer`);
  }
  connectAnswer = fixture.connect_ready;

  console.log("\nSame-titled candidates read differently wherever a change set chooses one");
  const labelsFor = vm.runInThisContext("candidateLabels");
  const twin = { title: "Coding Standards", source_kind: "revise", revises_title: "Coding Standards",
    revises_current: true, scope: "How code is written.", change_summary: "changes 1 line", created: "2026-10-14" };
  const twins = [Object.assign({ path: "authority-candidates/coding-standards-3.md" }, twin),
    Object.assign({ path: "authority-candidates/coding-standards-4.md" }, twin)];
  const twinLabels = labelsFor(twins);
  const strip = (s) => s.replace(/ · authority-candidates\/coding-standards-\d\.md$/, "");
  check(twinLabels[twins[0].path] !== twinLabels[twins[1].path]
    && strip(twinLabels[twins[0].path]) === strip(twinLabels[twins[1].path])
    && /^Coding Standards — revision · changes 1 line · created 2026-10-14/.test(twinLabels[twins[0].path]),
    "two otherwise identical candidates differ, with their path added beside the source, change and date that still read alike");
  const differing = labelsFor([twins[0], Object.assign({}, twins[1], { change_summary: "changes 3 lines" })]);
  check(Object.values(differing).every((l) => !/authority-candidates\//.test(l))
    && differing[twins[0].path] !== differing[twins[1].path],
    "candidates the change summary already tells apart carry no path at all: never the suffix alone");
  check(Object.values(twinLabels).concat(Object.values(differing)).every((l) => !/How code is written/.test(l)),
    "a picker option never carries the scope: the card and View details show it");
  const alone = labelsFor([twins[0]])[twins[0].path];
  const earlier = labelsFor([Object.assign({}, twins[0], { revises_current: false })])[twins[0].path];
  check(alone === "Coding Standards — revision" && earlier === "Coding Standards — revision of an earlier version",
    "a candidate whose title no other shares is its title and, for a revision, a one-word marker");
  const ownTitle = { path: "authority-candidates/onboarding.md", title: "Onboarding", source_kind: "proposal",
    source_agent: "Claude", scope: "New hires.", change_summary: "2 lines of text" };
  check(labelsFor([ownTitle])[ownTitle.path] === "Onboarding",
    "a new candidate with a title of its own is its title alone");
  const offeredTwin = labelsFor([twins[1]], twins);
  check(/^Coding Standards — revision · changes 1 line$/.test(offeredTwin[twins[1].path]),
    "a title shared with a candidate already planned still tells the offered one apart");
  const proposed = labelsFor([
    { path: "authority-candidates/p.md", title: "Charter — Product Specification", source_kind: "proposal",
      source_agent: "Codex", revises_title: "Charter — Product Specification", revises_current: true,
      change_summary: "changes 1 line: “- **Git always belongs to the user.** Charter w…”" },
    { path: "authority-candidates/p-2.md", title: "Charter — Product Specification", source_kind: "proposal",
      source_agent: "Claude", revises_title: "Charter — Product Specification", revises_current: true,
      change_summary: "changes 1 line: “A person opens an existing Agent Context or cre…”" }]);
  check(proposed["authority-candidates/p.md"] === "Charter — Product Specification — revision · Proposed by: Codex · changes 1 line: “- **Git always belongs to t…”"
    && proposed["authority-candidates/p-2.md"] === "Charter — Product Specification — revision · Proposed by: Claude · changes 1 line: “A person opens an existing…”",
    "same-titled revisions read as revisions, by who proposed them and a short change, without repeating the title");
  const elsewhere = labelsFor([Object.assign({}, twins[0], { title: "Code style" }),
    Object.assign({}, twins[1], { title: "Code style" })]);
  check(Object.values(elsewhere).every((l) => /^Code style — revises “Coding Standards” · /.test(l)),
    "a revision titled differently from what it revises names that document");
  check(Object.values(differing).concat(Object.values(proposed), [alone, earlier]).every((l) => l.length <= 120),
    "options stay short enough for a native dropdown: none past 120 characters");

  console.log("\nA server's `code` is shown as code, never as raw backticks");
  clearToasts();
  vm.runInThisContext("toast")("An Agent Context is created in an empty folder, and this one holds `authoritative`.", true);
  const shown = document.querySelectorAll(".toast")[0];
  check(shown && !/`/.test(shown.textContent) && shown.querySelectorAll("code").length === 1
    && shown.querySelectorAll("code")[0].textContent === "authoritative",
    "a toast shows the folder name as code, with no backticks");
  vm.runInThisContext("showFieldError")("contextError", "This one holds `readme.txt`, `sub`.");
  check(!/`/.test($("contextError").textContent) && $("contextError").querySelectorAll("code").length === 2,
    "a field error does too");
  vm.runInThisContext("showFieldError")("contextError", "");
  clearToasts();

  console.log("\nNo page action ever applies a governing change through the general route");
  check(!calls.some((c) => c.url === "/api/apply" && GOVERNING_KINDS.includes(c.body.kind))
    && !calls.some((c) => c.url === "/api/plan" && ["grant", "replace", "withdraw"].includes(c.body.kind)),
    "no grant, replace, withdraw or change set was ever planned or applied outside a change set's own route");

  console.log("");
  if (failures) { console.log(`${failures} front-end check(s) failed.`); process.exit(1); }
  console.log("All front-end checks passed.");
})().catch((err) => { console.error(err); process.exit(1); });
