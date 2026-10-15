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
let currentState = fixture.state_closed;
let connectAnswer = fixture.connect_ready;
let csNext = null;  // the change-set payload the next change-set call answers with
let csListAnswer = null;  // the change-set index, when not fixture.cs_list
let stageAnswer = fixture.stage;  // what converting the next file answers
let stageDelay = null;  // { gate, answer }: the next conversion answers only once gate resolves
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
  if (url === "/api/peek") {
    // A read-only look: a chosen folder already holding a context answers with
    // its name; an empty or missing folder is offered to create.
    const p = (body && body.path) || "";
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
    // A change set started from one candidate or document: the real answer to that start.
    return answer(body.start.alongside ? fixture.cs_start_alongside
      : body.start.outcome === "withdraw" ? fixture.cs_start_withdraw : fixture.cs_start_revise);
  }
  if (url === "/api/changeset/get" && body.id === fixture.start_request.draft_id) return answer(fixture.cs_start_applied);
  if (url === "/api/changeset/packet/save") {
    return refuse(400, "The review packet cannot be saved there: Choose a folder outside every Agent Context and Charter's private state. Nothing was saved.");
  }
  if (url.startsWith("/api/changeset")) return answer(Object.assign({}, csNext,
    url === "/api/changeset/refresh" ? { refreshed: [{ document: "authority-candidates/delta.md", change: "candidate text changed; review it" }] } : {}));
  if (url === "/api/proposals/unexpected") return answer(fixture.unexpected_view);
  if (url === "/api/proposals/import/check") {
    return answer(/base_commit/.test(body.json) ? fixture.import_check_bad : fixture.import_check_ok);
  }
  if (url === "/api/proposals/import") return answer({ result: "pending", proposal_id: "p-imported" });
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
const labelFor = (root, id) => root.querySelectorAll("label").find((l) => l.getAttribute("for") === id);
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
const rule = (source, selector) => {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\>]/g, "\\$&").replace(/\s+/g, "\\s*");
  const m = source.match(new RegExp("(^|\\n)\\s*(?:[^{}\\n]*,\\s*\\n\\s*)?" + escaped + "\\s*\\{([^}]*)\\}"));
  return m ? m[2] : "";
};
const SCOPE_PLACEHOLDER = "Describe what this document governs or applies to";
const SCOPE_ROUTING = "A short routing summary shown in AGENT-CONTEXT.md; it does not replace this document's rules.";
const aboutScope = (root) => root.querySelectorAll(".info-toggle").filter((b) => b.getAttribute("aria-label") === "About scope");

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

  console.log("\nWhat each action does is behind the information control beside the heading");
  const openInfo = $("aboutOpeningToggle");
  const openInfoBody = $("aboutOpeningBody");
  check(openInfo.parentNode.parentNode === startView.querySelector(".view-head")
    && openInfo.getAttribute("aria-expanded") === "false" && openInfoBody.hidden,
    "a named button beside the heading, closed to start");
  openInfo.focus();
  openInfo.dispatch("focus");
  check(!openInfoBody.hidden && /dedicated folder/.test(openInfoBody.textContent)
    && /writes nothing in the folder/.test(openInfoBody.textContent)
    && /empty folder/.test(openInfoBody.textContent)
    && /Neither action runs Git/.test(openInfoBody.textContent)
    && /AGENTS\.md/.test(openInfoBody.textContent),
    "it explains the folder, both actions, and that Git and agent instruction files are left alone");
  $("aboutOpening").dispatch("keydown", { key: "Escape" });
  check(openInfoBody.hidden && document.activeElement === openInfo, "Escape dismisses it");
  $("aboutOpening").dispatch("focusout", { relatedTarget: null });

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
  const recent = $("recentContexts").querySelectorAll("button");
  check(/Opened on This Computer/.test($("recentContexts").textContent)
    && recent.some((b) => b.textContent === fixture.folder), "Agent Contexts opened here before are listed");
  await click(recent.find((b) => b.textContent === fixture.folder));
  check($("contextPath").value === fixture.folder, "and one click fills in the folder");
  currentState = fixture.state_valid;
  await click($("btnOpen"));
  check(!$("view-governing").hidden && $("barPath").textContent === fixture.state_valid.root,
    "Open shows the Agent Context");

  /* ----------------------------------------------------- shell and navigation */

  console.log("\nNavigation is the six Agent Context areas");
  check(nav().map((b) => b.dataset.view).join(" ") === "governing candidates proposals changesets connect settings",
    "Governing Documents, Authority Candidates, Agent Proposals, Change Sets, Connect Agents, Settings");
  check(nav().map((b) => b.childNodes[0].textContent.trim()).join(" | ")
      === "Governing Documents | Authority Candidates | Agent Proposals | Change Sets | Connect Agents | Settings"
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
  check($("barPath").textContent === fixture.state_valid.root && $("barState").textContent === "Agents are served"
    && $("metaRoot").textContent === fixture.state_valid.root && $("metaAgents").textContent === "Served",
    "its folder, and that agents are served");
  const govCount = fixture.state_valid.documents.filter((d) => d.kind === "governing").length;
  const candCount = fixture.state_valid.documents.filter((d) => d.kind === "candidate").length;
  const archCount = fixture.state_valid.documents.filter((d) => d.kind === "archived").length;
  check($("metaContext").textContent === String(govCount), "the rail counts governing documents only");
  check($("contextMetaTitle").textContent === "This Agent Context" && !$("gitInfo") && !$("gitInfoToggle")
    && !$("gitDetailsToggleText") && fixture.state_valid.status.git.state === "not-checkout"
    && !$("metaGitLabel").hidden && $("metaGitLabel").textContent === "Git branch"
    && $("metaBranch").textContent === "Not a Git checkout"
    && $("metaChangedLabel").hidden && $("metaChanged").hidden && $("gitDetailsToggle").hidden,
    "outside a Git checkout the rail says Git branch: Not a Git checkout, with no count and no control");
  check($("contextStatus").hidden && !$("contextStatus").querySelector("#originUnknown")
    && within($("originUnknown"), $("contextMapSection")) && !$("originUnknown").hidden
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
  check($("tallyArchive").textContent === `(${archCount})` && $("tallyArchiveLabel").textContent === `: ${archCount} archived document`,
    "and the private archive, in its disclosure");

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
    === "Authority Candidates — Charter | Settings — Charter | Governing Documents — Charter",
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
  check(governingView.querySelector(".view-head h2").textContent === "Governing Documents"
    && governingView.querySelector(".view-head .info-toggle") === $("aboutStatesToggle"),
    "the heading has an information control beside it");
  const govRows = $("governingList").querySelectorAll(".doc");
  check(govRows.length === govCount && govRows.every((r) => r.classList.contains("is-authority")
    && /Governing/.test(r.querySelector(".actions").textContent)
    && !/In the Agent Context folder/.test(r.textContent)
    && !/Private local state/.test(r.textContent)),
    "governing documents carry the Governing chip, without repeating where agents read them");
  const alpha = rowOf("governingList", "Alpha");
  check(buttonSaying(alpha, "Read") && buttonSaying(alpha, "Revise…") && buttonSaying(alpha, "Change in a change set…")
    && buttonSaying(alpha, "Withdraw in a change set…")
    && !buttonSaying(alpha, "Edit…") && !buttonSaying(alpha, "Retire…") && !buttonSaying(alpha, "Plan a change set…"),
    "a governing document is read, revised, or changed or withdrawn in a change set — never edited in place or retired");
  check(!document.querySelectorAll("button").some((b) => /Grant authority|Withdraw authority/.test(b.textContent)),
    "no button offers a direct grant or withdrawal");
  check(!$("governingList").textContent.includes("AGENT-CONTEXT.md"), "the map is never listed as a governing document");
  await navTo("candidates");
  check($("view-candidates").querySelector(".lede").textContent
    === "Candidates stay private until you make them governing.",
    "Authority candidates says, in one sentence, that they stay private until made governing");
  const gamma = rowOf("candidatesList", "Gamma rules");
  check(gamma && /Authority candidate — not context/.test(gamma.textContent)
    && /Private local state on this computer — agents never see it\./.test(gamma.textContent),
    "each candidate is marked not context, and private");
  check(buttonSaying(gamma, "Edit…") && buttonSaying(gamma, "Retire…") && buttonSaying(gamma, "Plan a change set…")
    && !buttonSaying(gamma, "Withdraw in a change set…") && !buttonSaying(gamma, "Change in a change set…"),
    "a candidate is edited, retired, or planned into a change set");

  /* Governed candidate lineage, source, comparison, and picker labels (human-only). */
  const betaRev = rowOf("candidatesList", "Beta revised");
  check(betaRev && /Revision of: Beta/.test(betaRev.textContent) && /Source: Revise/.test(betaRev.textContent),
    "a revision candidate's card shows the governing document it revises and its source");
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
  check(/Revision of: Alpha/.test(synthCard) && /Source: Agent Proposal/.test(synthCard)
    && /Another revision candidate exists for this document\. 2 others/.test(synthCard)
    && synthCard.indexOf("Compare revisions") !== -1,
    "a card shows source, revision lineage, a competing-revision count, and Compare revisions");
  const pickLabel = vm.runInThisContext("candidateLabel")(
    { title: "X", source_kind: "proposal", revises_title: "Alpha", scope: "short scope" });
  check(/Agent Proposal/.test(pickLabel) && /revises .Alpha./.test(pickLabel) && /short scope/.test(pickLabel),
    "a change-set picker label disambiguates by source, revision relationship and a short summary");
  check($("archiveBody").hidden && $("archiveToggle").getAttribute("aria-expanded") === "false",
    "the private archive is behind a closed disclosure");
  check($("archiveToggle").textContent.replace(/\s+/g, " ").startsWith(`Archived (${archCount})`)
    && !/History|Replaced and Retired/.test($("archiveToggle").textContent),
    "the disclosure is labelled Archived, with its count");
  check(!$("archiveBody").querySelector(".hint") && !/kept privately for history/.test($("archiveBody").textContent),
    "the archive has no explanatory sentence: its label and each row's chip say what it is");
  await click($("archiveToggle"));
  const archived = $("archiveList").querySelector(".doc");
  const archivedDoc = fixture.state_valid.documents.find((d) => d.kind === "archived");
  check(!$("archiveBody").hidden && $("archiveToggle").getAttribute("aria-expanded") === "true"
    && /Archived — not context/.test(archived.textContent)
    && archived.querySelectorAll("button").map((b) => b.textContent).join() === "Read",
    "opened, an archived document can only be read");
  const archivedTitle = archived.querySelector(".archive-line .title");
  const archivedDate = archived.querySelector(".archive-line .archive-date");
  check(archivedDoc.updated && archivedTitle && archivedTitle.textContent === archivedDoc.title
    && archivedDate && archivedDate.textContent === archivedDoc.updated,
    "an archived row's title and date are separate fields");
  const archiveLineRule = rule(css, ".archive-line");
  const archiveDateRule = rule(css, ".archive-line .archive-date");
  check(/display:\s*flex/.test(archiveLineRule) && /flex-wrap:\s*wrap/.test(archiveLineRule)
    && /gap:/.test(archiveLineRule) && /color:\s*var\(--ink-faint\)/.test(archiveDateRule),
    "the date is spaced from the title, muted, and wraps to its own line when narrow");
  await click(buttonSaying(archived, "Read"));
  check(!$("docViewer").hidden && $("docViewer").textContent.indexOf(archivedDoc.title) !== -1,
    "Read opens the archived document");
  await click(buttonSaying($("docViewer"), "Close"));
  await click($("archiveToggle"));
  check($("archiveBody").hidden && $("archiveToggle").getAttribute("aria-expanded") === "false",
    "and the disclosure closes again");

  console.log("\nAn empty list shows a 0, and no empty-state text");
  const kept = vm.runInThisContext("state.documents");
  global.__kept = kept;
  vm.runInThisContext("state.documents = state.documents.filter((d) => d.kind === 'governing')");
  vm.runInThisContext("renderShell(); renderKnowledge();");
  check(navItem("candidates").querySelector(".tally").textContent === "(0)" && $("candidatesList").hidden
    && !/No candidates|nothing here/i.test($("view-candidates").textContent),
    "with no candidates, the count is 0 and the list is simply absent");
  check($("tallyArchive").textContent === "(0)" && $("archiveList").hidden
    && $("archiveToggle").textContent.replace(/\s+/g, " ").startsWith("Archived (0)"),
    "with nothing archived, the disclosure reads Archived (0) and its list is absent");
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
  check($("changeSetList").querySelectorAll(".changeset-row").length === 3
    && csTally.textContent === "(1)" && $("tallyChangeSetsLabel").textContent === ": 1 active draft",
    "the index lists all three; the navigation counts 1");

  console.log("\nChange Sets index: active drafts primary, applied and abandoned behind a collapsed Change history");
  const topGroups = () => $("changeSetList").children.filter((n) => n.classList.contains("record-group"));
  const summaryOf = (groups) => groups.map((g) => {
    const label = g.querySelector(".record-group-label");
    return `${label.textContent}:${g.querySelectorAll(".changeset-row").map((r) => r.querySelector(".actions .chip").textContent).join("+")}`;
  }).join(" | ");
  const historyGroups = () => $("csHistoryBody").children.filter((n) => n.classList.contains("record-group"));
  const groupNamed = (groups, name) => groups.find((g) => new RegExp(name).test(g.querySelector(".record-group-label").textContent));
  check(summaryOf(topGroups()) === "Active Drafts (1):active",
    "Active drafts is the one primary, immediately visible group");
  const hist = $("csHistoryToggle");
  check(hist && hist.textContent === "Change History (2)" && hist.getAttribute("aria-expanded") === "false"
    && $("csHistoryBody").hidden,
    "applied and abandoned sit together behind a compact, collapsed Change history (2) disclosure");
  check(summaryOf(historyGroups()) === "Applied Change Sets (1):applied | Abandoned Drafts (1):abandoned",
    "within history, in order — Applied change sets, then Abandoned drafts — each with its own count");
  hist.click();
  check(!$("csHistoryBody").hidden && hist.getAttribute("aria-expanded") === "true"
    && historyGroups().every((g) => g.tagName === "SECTION" && g.querySelector(".record-group-label").tagName === "H3"
      && g.getAttribute("aria-labelledby") === g.querySelector(".record-group-label").getAttribute("id")),
    "a person can expand history to the two groups, each a section named by its own heading");
  check(!!buttonSaying(groupNamed(historyGroups(), "Applied Change Sets"), "Open"),
    "an applied change set opens as its immutable receipt from history");
  check(!!buttonSaying(groupNamed(historyGroups(), "Abandoned Drafts"), "Open"),
    "and an abandoned draft can still be deliberately opened");
  check(!$("noChangeSets"), "with records there is no empty-state message");
  csListAnswer = Object.assign({}, fixture.cs_mixed_list,
    { drafts: fixture.cs_mixed_list.drafts.filter((d) => d.state !== "active") });
  await navTo("candidates");
  await navTo("changesets");
  check(!topGroups().length && $("csHistoryToggle") && $("csHistoryToggle").textContent === "Change History (2)"
    && $("csHistoryBody").hidden && !$("noChangeSets") && csTally.textContent === "(0)",
    "with no active draft, Change history is first: no empty Active group, no empty-state message, a count of 0");
  csListAnswer = fixture.cs_unreadable_list;
  await navTo("candidates");
  await navTo("changesets");
  check(summaryOf(topGroups()) === "Active Drafts (1):active | Unreadable Records (1):unreadable"
    && $("csHistoryToggle") && $("csHistoryToggle").textContent === "Change History (2)"
    && !!buttonSaying(groupNamed(topGroups(), "Unreadable Records"), "Delete") && csTally.textContent === "(1)",
    "an unreadable record is listed last, after the active drafts and the change history, still deletable and not counted");
  csListAnswer = Object.assign({}, fixture.cs_mixed_list, { drafts: [] });
  await navTo("candidates");
  await navTo("changesets");
  check(!topGroups().length && !$("csHistoryToggle") && !!$("noChangeSets")
    && /^No change sets for this Agent Context on this computer\./.test($("noChangeSets").textContent)
    && csTally.textContent === "(0)",
    "with no change set at all, the existing empty-state message remains, with no groups or history");
  csListAnswer = null;
  currentState = fixture.state_valid;
  await navTo("candidates");
  check(csTally.textContent === "(0)", "the count follows the state on every view");

  console.log("\nThe lifecycle is explained once, behind the information control");
  await navTo("governing");
  const aboutStates = $("aboutStatesToggle");
  const aboutBody = $("aboutStatesBody");
  check(aboutStates.getAttribute("aria-label") === "About governing documents and candidates"
    && aboutStates.getAttribute("aria-expanded") === "false" && aboutBody.hidden,
    "a named button, closed to start");
  aboutStates.click();
  check(!aboutBody.hidden && /Authority candidate — not context/.test(aboutBody.textContent)
    && /only way Charter changes what governs/.test(aboutBody.textContent)
    && /govern alongside, revise or replace[\s\S]*withdrawn/.test(aboutBody.textContent)
    && /change governing context/.test(aboutBody.textContent)
    && /changed outside Charter/.test(aboutBody.textContent),
    "a click opens it: the states, change sets and their outcomes, the typed phrase, and changes made outside");
  aboutStates.click();
  check(aboutBody.hidden, "a second click closes it");
  $("aboutStates").dispatch("mouseenter");
  check(!aboutBody.hidden, "hovering shows it");
  $("aboutStates").dispatch("mouseleave");
  check(aboutBody.hidden, "and leaving hides it");
  aboutStates.click();
  document.dispatch("click", { target: $("main") });
  check(aboutBody.hidden, "a click elsewhere closes it");
  check(/position:\s*absolute/.test(rule(css, ".info-pop")) && /outline:/.test(rule(css, ".info-toggle:focus-visible")),
    "it floats over the page, and the control shows keyboard focus");

  console.log("\nThe shared section break: a gap, a thin divider and a compact label with a count");
  const groupRule = rule(css, ".record-group");
  check(/margin-top:\s*1(\.\d+)?rem/.test(groupRule) && /border-top:\s*1px solid/.test(groupRule)
    && /padding-top/.test(groupRule) && /font-size:\s*\.8rem/.test(rule(css, ".record-group-label")),
    "one pattern: a modest gap, a thin divider, and a small label");
  check(/display:\s*none/.test(rule(css, ".record-group[hidden]")), "an empty group is not shown at all");
  const historyRule = rule(css, ".change-history");
  check(/margin-top:\s*1(\.\d+)?rem/.test(historyRule) && /border-top:\s*1px solid/.test(historyRule)
    && /font-size:\s*\.8rem/.test(rule(css, ".change-history > .disclosure-toggle")),
    "Change history uses the same section break and a compact label as its disclosure");

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
  check(/Matches the governing documents/.test($("contextMapState").textContent) && $("btnRebuildContext").hidden,
    "valid: it is said to match, and Rebuild is not offered");
  check(/Agent guidance in the map: Context check-in\. Change it in Settings\./.test($("agentGuidanceSummary").textContent),
    "the enabled guidance is named, with where to change it");
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
  check(!/follow/i.test($("docViewer").querySelector(".reader-banner").textContent)
    && !/follow/i.test($("aboutStatesBody").textContent),
    "neither the banner nor the explanation claims agents follow it: Charter cannot make them");
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

  console.log("\nPlan a change set from a candidate: the person chooses what it does");
  const createsBefore = () => calls.filter((c) => c.url === "/api/changeset/create").length;
  const noGoverningApply = () => !calls.some((c) => c.url === "/api/apply" && GOVERNING_KINDS.includes(c.body.kind));
  await click(buttonSaying(rowOf("candidatesList", "Gamma rules"), "Plan a change set…"));
  check(/Gamma decisions\./.test($("startCandidateScope").textContent)
    && !$("review").querySelectorAll("input").some((i) => i.type === "text"),
    "the candidate's own scope is shown; it is changed with Edit, not here");
  check(!!labelFor($("review"), "startAlongside") && /Govern alongside/.test(labelFor($("review"), "startAlongside").textContent)
    && /Revise a governing document with this candidate/.test(labelFor($("review"), "startRevise").textContent)
    && /Replace a governing document with this candidate/.test(labelFor($("review"), "startReplace").textContent),
    "it offers govern alongside, revise a governing document, and replace one");
  check(!$("startAlongside").checked && !$("startRevise").checked && !$("startReplace").checked
    && $("startTargetDetail").hidden && $("startTarget").value === "",
    "nothing is chosen for the person");
  check($("startTarget").options[0].value === ""
    && $("startTarget").options.slice(1).map((o) => o.value).join()
      === fixture.state_valid.documents.filter((d) => d.governing).map((d) => d.path).join(),
    "only governing documents can be revised or replaced");
  check(/stays undecided until you decide it in the change set/.test($("startUndecided").textContent),
    "it says every other governing document stays undecided");
  let made = createsBefore();
  await click($("btnOpenChangeSet"));
  check(createsBefore() === made && /Choose what this candidate does/.test(toastNow().textContent),
    "with nothing chosen, nothing is opened");
  clearToasts();
  $("startReplace").checked = true;
  $("startReplace").dispatch("change");
  check(!$("startTargetDetail").hidden && $("startScopeCompare").hidden, "choosing replace asks which document");
  await click($("btnOpenChangeSet"));
  check(createsBefore() === made && /Choose the governing document to replace/.test(toastNow().textContent),
    "replacing without a document opens nothing");
  clearToasts();
  $("startTarget").value = fixture.governing;
  $("startTarget").dispatch("change");
  check(!$("startScopeCompare").hidden && $("startCurrentScope").textContent === "A scope."
    && $("startScopeOutcome").textContent === "If the change set is applied, AGENT-CONTEXT.md shows: “Gamma decisions.”.",
    "choosing one shows its current scope beside the result");
  vm.runInThisContext("closeReview")();

  await click(buttonSaying(rowOf("candidatesList", "Unscoped idea"), "Plan a change set…"));
  $("startRevise").checked = true;
  $("startRevise").dispatch("change");
  $("startTarget").value = fixture.governing;
  $("startTarget").dispatch("change");
  check($("startCandidateScope").textContent === "No scope stated"
    && $("startScopeOutcome").textContent === "The candidate has no scope, so it would inherit “Alpha”'s current scope: “A scope.”.",
    "a blank candidate scope is shown, explicitly, as inheriting the replaced document's");
  vm.runInThisContext("closeReview")();

  console.log("\nA candidate made with Revise… lists its origin first, as context only");
  const revised = fixture.state_valid.documents.find((d) => d.title === "Beta revised");
  const plain = fixture.state_valid.documents.find((d) => d.path === fixture.candidate);
  check(revised && revised.revises_path === "authoritative/b.md" && plain.revises_path === ""
    && fixture.state_valid.documents.filter((d) => d.kind === "candidate" && d.revises_path).length === 1,
    "the server says which candidate came from Revise…, and from which governing document");
  made = createsBefore();
  const plansBeforeRevised = calls.filter((c) => c.url === "/api/plan").length;
  await click(buttonSaying(rowOf("candidatesList", "Beta revised"), "Plan a change set…"));
  const originOption = $("startTarget").options[1];
  check(originOption.value === "authoritative/b.md" && /— the document this was revised from$/.test(originOption.textContent)
    && $("startTarget").options.slice(2).every((o) => !/revised from/.test(o.textContent)),
    "its origin is listed first, labelled “the document this was revised from”");
  check(!$("startAlongside").checked && !$("startRevise").checked && !$("startReplace").checked
    && $("startTarget").value === "" && $("startTargetDetail").hidden,
    "and nothing is selected: not the outcome, not the document");
  check(/Nothing is chosen for you/.test($("startTargetHint").textContent),
    "it says the choice is the person's");
  check(createsBefore() === made && calls.filter((c) => c.url === "/api/plan").length === plansBeforeRevised,
    "opening it creates, plans and applies nothing");
  $("startRevise").checked = true;
  $("startRevise").dispatch("change");
  $("startTarget").value = "authoritative/b.md";
  $("startTarget").dispatch("change");
  check($("startCurrentScope").textContent === "A scope."
    && $("startScopeOutcome").textContent === "The candidate has no scope, so it would inherit “Beta”'s current scope: “A scope.”.",
    "choosing its origin shows scope continuity");
  await click($("btnOpenChangeSet"));
  check(JSON.stringify(lastCall("/api/changeset/create").body)
      === JSON.stringify({ start: { document: "authoritative/b.md", outcome: "revise", candidate: revised.path } }),
    "Open change set starts exactly the outcome the person chose");
  check(!$("changeSetEditor").hidden && $("changeSetIndex").hidden && $("review").childNodes.length === 0
    && $("csRows").querySelectorAll(".cs-row").length === 1 && $("csOutcome-0").value === "revise",
    "its editor opens with that one row, in place of the index");
  check(!!$("csRetainOthers") && !$("csUnretain") && $("csPreview").disabled,
    "every other governing document is left undecided, so it is not ready to preview yet");
  check(!$("confirmPhrase") && calls.filter((c) => c.url === "/api/plan").length === plansBeforeRevised && noGoverningApply(),
    "no phrase is asked for and nothing is previewed or applied until the change set is");
  await vm.runInThisContext("closeChangeSet")();
  await navTo("candidates");

  console.log("\nA change set started from a candidate is previewed, confirmed and applied as a change set");
  await click(buttonSaying(rowOf("candidatesList", "Gamma rules"), "Plan a change set…"));
  $("startAlongside").checked = true;
  $("startAlongside").dispatch("change");
  check($("startTargetDetail").hidden, "governing alongside needs no document");
  await click($("btnOpenChangeSet"));
  check(JSON.stringify(lastCall("/api/changeset/create").body) === JSON.stringify({ start: { alongside: fixture.candidate } })
    && !$("changeSetEditor").hidden && fixture.cs_start_alongside.alongside.length === 1
    && fixture.cs_start_alongside.draft.title === "Govern alongside: “Gamma rules”",
    "govern alongside opens a change set with the candidate alone, named for what it does");
  // U4: Abandon is irreversible, so it asks for a clear confirmation first;
  // declining it changes nothing and makes no server call.
  const priorConfirm = global.confirm;
  let abandonMsg = null;
  global.confirm = (m) => { abandonMsg = m; return false; };
  const abandonsBefore = calls.filter((c) => c.url === "/api/changeset/abandon").length;
  await click(buttonSaying($("changeSetEditor"), "Abandon"));
  check(/cannot be undone/.test(abandonMsg || "")
    && calls.filter((c) => c.url === "/api/changeset/abandon").length === abandonsBefore,
    "Abandon asks for a clear confirmation and, when declined, abandons nothing");
  global.confirm = priorConfirm;
  await vm.runInThisContext("closeChangeSet")();
  await vm.runInThisContext("planFor")("changeset", fixture.start_request,
    { applyLabel: "Apply change set", applyClass: "btn authority" });

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
  check($("governingBeforeAfter") && /Governing Now/.test($("governingBeforeAfter").textContent)
    && /Governing After[\s\S]*Gamma rules/.test($("governingBeforeAfter").textContent),
    "the governing set is shown before and after");
  check($("review").textContent.indexOf("Document dates are assigned when this change set is applied.") !== -1,
    "it says document dates are assigned when the change set is applied");

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
  check(!$("changeSetEditor").hidden && /Applied — receipt/.test($("changeSetEditor").textContent),
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

  console.log("\nA governing document: withdrawn or changed in a change set; Retire is an ordinary confirmation");
  await navTo("governing");
  made = createsBefore();
  const plansBeforeWithdraw = calls.filter((c) => c.url === "/api/plan").length;
  await click(buttonSaying(rowOf("governingList", "Beta"), "Withdraw in a change set…"));
  check(createsBefore() === made + 1
    && JSON.stringify(lastCall("/api/changeset/create").body) === JSON.stringify({ start: { document: "authoritative/b.md", outcome: "withdraw" } }),
    "Withdraw in a change set… starts a change set withdrawing that document alone");
  check(!$("changeSetEditor").hidden && $("csOutcome-0").value === "withdraw" && !!$("csRetainOthers") && !$("csUnretain")
    && !$("confirmPhrase") && calls.filter((c) => c.url === "/api/plan").length === plansBeforeWithdraw && noGoverningApply(),
    "its editor opens with the others undecided; the phrase comes only at its preview");
  await vm.runInThisContext("closeChangeSet")();
  await navTo("governing");
  await click(buttonSaying(rowOf("governingList", "Beta"), "Change in a change set…"));
  check(!$("docRevise").checked && !$("docReplace").checked && !$("docWithdraw").checked
    && $("docCandidateDetail").hidden && $("docCandidate").value === "",
    "changing a governing document starts with nothing chosen");
  const betaCandidates = $("docCandidate").options.slice(1);
  check(betaCandidates[0].value === revised.path && /revises “Beta”/.test(betaCandidates[0].textContent)
    && betaCandidates.length === fixture.state_valid.documents.filter((d) => d.kind === "candidate").length,
    "any candidate can be chosen; one revised from it is listed first, labelled, not selected");
  made = createsBefore();
  $("docRevise").checked = true;
  $("docRevise").dispatch("change");
  await click($("btnOpenChangeSet"));
  check(createsBefore() === made && /Choose the candidate to revise it with/.test(toastNow().textContent),
    "revising without a candidate opens nothing");
  clearToasts();
  $("docCandidate").value = revised.path;
  await click($("btnOpenChangeSet"));
  check(JSON.stringify(lastCall("/api/changeset/create").body)
      === JSON.stringify({ start: { document: "authoritative/b.md", outcome: "revise", candidate: revised.path } })
    && !$("changeSetEditor").hidden && noGoverningApply(),
    "it opens a change set with exactly that outcome");
  await vm.runInThisContext("closeChangeSet")();
  const keptDocs = vm.runInThisContext("state.documents");
  global.__keptDocs = keptDocs;
  vm.runInThisContext("state.documents = state.documents.filter((d) => d.kind !== 'candidate')");
  await navTo("governing");
  await click(buttonSaying(rowOf("governingList", "Alpha"), "Change in a change set…"));
  check($("docRevise").disabled && $("docReplace").disabled && !$("docWithdraw").disabled
    && /Use Revise… to file one from this document first/.test(labelFor($("review"), "docRevise").textContent)
    && !!$("docReviseFirst"),
    "with no candidate, revise and replace point to Revise… first; withdrawing is still possible");
  await click($("docReviseFirst"));
  check(lastCall("/api/draft").body.path === fixture.governing && /Revise “Alpha”/.test($("review").textContent)
    && /until you revise it with the candidate in a change set/.test($("reviseNotice").textContent),
    "Revise… files a candidate first, and says the document keeps governing until a change set");
  vm.runInThisContext("closeReview")();
  vm.runInThisContext("state.documents = __keptDocs; renderShell(); renderKnowledge();");
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
  check(aboutScope($("review")).length === 1 && $("review").textContent.indexOf(SCOPE_ROUTING) !== -1
    && $("formField-scope").getAttribute("aria-describedby") === "formHint-scope",
    "its scope field says what scope is for, with About scope beside it");
  const scopeTip = aboutScope($("review"))[0];
  scopeTip.click();
  check(/does not replace, summarize or override/.test(document.getElementById(scopeTip.getAttribute("aria-controls")).textContent)
    && /Charter does not write, judge or approve it/.test(document.getElementById(scopeTip.getAttribute("aria-controls")).textContent),
    "About scope explains routing, and that the wording is the person's");
  scopeTip.click();
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
  check(/kept in private local state — not context/.test($("intakeLede").textContent)
    && /governs nothing until a change set you apply makes it govern/.test($("intakeLede").textContent)
    && /not context/.test($("candidateNote").textContent),
    "it says the document becomes a private candidate, not context");
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

  console.log("\nLocked steps cannot be reached until a file is chosen");
  const lockedBodies = ["stepConvertBody", "stepNameBody"].map($);
  check(lockedBodies.every((b) => b.getAttribute("inert") !== null)
    && ["markdown", "title", "scope", "btnPreviewIntake"].every((id) => lockedBodies.some((b) => b.querySelector("#" + id) === $(id))),
    "steps 2 and 3, and every field in them, are inert");
  check(["stepConvert", "stepName"].every((id) => $(id).querySelector(".step-locked-note").textContent === "Choose a file in step 1 first."),
    "each says what it needs first");
  await vm.runInThisContext("stageFile")({ name: "site-notes.md" });
  await settle();
  check($("title").value === fixture.stage.suggested_title && $("markdown").value === fixture.stage.markdown,
    "the converted text and title are offered");
  check($("scope").value === "" && $("scope").getAttribute("placeholder") === SCOPE_PLACEHOLDER
    && $("scopeHint").textContent === SCOPE_ROUTING, "the scope field is empty, with an instruction");
  check(lockedBodies.every((b) => b.getAttribute("inert") === null), "the later steps unlock");
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
    && $("stepConvert").classList.contains("locked"), "Create candidate is empty and locked again");
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
    "Cancel is a native button beside the heading, never in a locked step");
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
    && $("stepConvert").classList.contains("locked"), "Create candidate is empty and locked again");
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
  check($("convertNotes").textContent.indexOf(fm.notes[1]) !== -1, "the conversion notes say so too");
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

  console.log("\nA conversion that answers late never fills a form it no longer belongs to");
  const late = Object.assign({}, fixture.stage, { filename: "late.md", markdown: "LATE TEXT\n", suggested_title: "Late" });
  const hold = () => { let release; const gate = new Promise((r) => { release = r; }); stageDelay = { gate, answer: late }; return release; };
  const staged = () => vm.runInThisContext("staged");
  const intakeEmpty = () => staged() === null && $("markdown").value === "" && $("title").value === ""
    && $("stepConvertBody").getAttribute("inert") !== null;
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

  console.log("\nNavigating shows fresh data, and keeps unfinished work");
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
  check($("title").value === "Half-typed title", "going back to Create candidate finds the half-typed title");
  $("title").value = "";
  currentState = fixture.state_valid;

  console.log("\nNo Check again: the console reads the folder on opening and after each operation");
  check(!$("btnRefresh") && !$("refreshStatus")
    && !document.querySelectorAll("button").some((b) => /Check again|Checking/.test(b.textContent))
    && !$("btnSwitch").hidden,
    "the top bar has no Check again button and no “Checked” status; Open another Agent Context remains");
  $("title").value = "Still typing";
  await reload();
  check($("title").value === "Still typing", "reading the folder again keeps what was being typed");
  $("title").value = "";
  await navTo("governing");

  /* --------------------------------------------- status, outside changes, rebuild */

  console.log("\nAn ordinary edit: agents refused, the reason, and Rebuild");
  await show("state_invalid");
  check($("barState").textContent === "Agents are refused" && $("metaAgents").textContent === "Refused",
    "the header and rail say agents are refused");
  check($("refusedCard") && /Rebuild Agent Context/.test($("refusedCard").querySelector("h3").textContent)
    && $("refusedCard").querySelectorAll(".issues li").length > 0, "the status says why, and what to do next");
  check($("btnRebuildFromStatus") && !$("btnRebuildContext").hidden, "Rebuild Agent Context is offered");
  check($("outsideNotice") && /authoritative\/a\.md/.test($("outsideNotice").textContent) && !$("btnAcknowledge"),
    "the document changed outside Charter is named; it cannot be marked seen while refused");
  check(/Does not match the governing documents/.test($("contextMapState").textContent), "the map is said not to match");
  const withdraw = buttonSaying(rowOf("governingList", "Beta"), "Withdraw in a change set…");
  const changeIt = buttonSaying(rowOf("governingList", "Beta"), "Change in a change set…");
  check(withdraw.disabled && changeIt.disabled && !withdraw.getAttribute("title")
    && !$("governingUnavailable").hidden && /valid and clean/.test($("governingUnavailable").textContent)
    && withdraw.getAttribute("aria-describedby") === "governingUnavailable"
    && changeIt.getAttribute("aria-describedby") === "governingUnavailable",
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
  check($("barState").textContent === "Agents are served" && /Rebuild Agent Context regenerated/.test($("outsideNotice").textContent)
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
  check(/notes\.txt/.test($("refusedCard").textContent) && /never moves or deletes a file it did not write/.test($("straysNote").textContent)
    && !$("btnRebuildFromStatus"), "the stray is named, the person told it is left alone, and Rebuild is not offered");

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
  $("rebuildGuidance-review_newly_discovered_material").checked = true;
  await click($("btnRebuildWithSettings"));
  const sent = lastPlan().body.request;
  check(sent.project_name === offered.project_name && sent.agent_guidance.review_newly_discovered_material === true
    && JSON.stringify(Object.keys(sent.agent_guidance).sort())
      === JSON.stringify(["context_check_in", "proposal_context_impact_check", "review_newly_discovered_material"]),
    "confirming or changing them sends the name and every guidance setting explicitly");
  check(!$("btnApply").disabled, "then Rebuild can apply");
  vm.runInThisContext("closeReview")();

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

  console.log("\nGit: a compact read-only summary, the files on request");
  await show("state_git");
  const gitToggle = $("gitDetailsToggle");
  check(!$("metaBranch").hidden && $("metaGitLabel").textContent === "Git branch" && $("metaBranch").textContent === "feature/scope"
    && !$("metaChanged").hidden && $("metaChangedLabel").textContent === "Context files changed"
    && $("metaChangedCount").textContent === "1" && $("gitDetailsPanel").hidden
    && $("contextMeta").querySelectorAll("li").every((li) => li.parentNode === $("gitChanged")),
    "in a Git checkout the rail shows the branch and the count; the file list stays closed");
  check(!gitToggle.hidden && gitToggle.getAttribute("type") === "button"
    && gitToggle.getAttribute("aria-expanded") === "false" && gitToggle.getAttribute("aria-controls") === "gitDetailsPanel"
    && gitToggle.getAttribute("aria-label") === "Show the changed context file"
    && $("gitDetailsPanel").getAttribute("aria-labelledby") === "metaChangedLabel"
    && !$("contextMeta").querySelectorAll("button").some((b) => b !== gitToggle),
    "beside the count, one labelled control for the files — and no other Git control");
  gitToggle.focus();
  await click(gitToggle);
  check(!$("gitDetailsPanel").hidden && gitToggle.getAttribute("aria-expanded") === "true"
    && $("gitChanged").querySelectorAll("li").length === 1 && /context\/authoritative\/a\.md/.test($("gitChanged").textContent)
    && $("gitChanged").getAttribute("tabindex") === "0"
    && !/does not stage|commit when|diff/i.test($("gitDetailsPanel").textContent)
    && !$("gitDetailsPanel").querySelectorAll("button").length,
    "activating it lists the changed context files — read-only: no diffs, no Git controls, no tutorial");
  document.dispatch("keydown", { key: "Escape" });
  check($("gitDetailsPanel").hidden && gitToggle.getAttribute("aria-expanded") === "false"
    && document.activeElement === gitToggle, "Escape closes it, and focus returns to the control");
  await click(gitToggle);
  document.dispatch("click", { target: $("main") });
  check($("gitDetailsPanel").hidden, "a click elsewhere closes it");
  await click(gitToggle);
  $("gitDetails").dispatch("focusout", { relatedTarget: $("btnSwitch") });
  check($("gitDetailsPanel").hidden, "moving focus out of it closes it");
  await click(gitToggle);
  $("gitDetails").dispatch("focusout", { relatedTarget: $("gitChanged") });
  check(!$("gitDetailsPanel").hidden, "moving focus within it, to the file list, keeps it open");
  await click(gitToggle);
  check($("gitDetailsPanel").hidden, "and the control itself closes it again");

  const many = JSON.parse(JSON.stringify(fixture.state_git));
  many.status.git.changed = ["context/a.md", "context/b.md", "context/c.md"];
  currentState = many;
  await reload();
  check($("metaChangedCount").textContent === "3" && gitToggle.getAttribute("aria-label") === "Show the 3 changed context files"
    && $("gitChanged").querySelectorAll("li").length === 3, "the control names how many files it shows");

  await show("state_git_clean");
  check($("metaBranch").textContent === "main" && $("metaChangedCount").textContent === "0"
    && gitToggle.hidden && $("gitDetailsPanel").hidden && !$("gitChanged").querySelectorAll("li").length,
    "a checkout with no changed context files: 0, and no control");
  await show("state_git_unreadable");
  check($("metaChangedCount").textContent === "Could not be read" && $("metaBranch").textContent === "main"
    && gitToggle.hidden && !/\b0\b/.test($("metaChanged").textContent),
    "when Git status could not be read, it says so — never 0, and no control");
  await show("state_git_unavailable");
  check($("metaBranch").textContent === "Git unavailable" && $("metaChanged").hidden && $("metaChangedLabel").hidden
    && gitToggle.hidden, "when Git cannot be run: Git unavailable, and no count");

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
  check(/never changes governing context/.test($("aboutProposalsBody").textContent)
    && /charter propose --context \./.test($("aboutProposalsBody").textContent),
    "its information control says how agents file, and that accepting never changes what governs");
  check($("view-proposals").querySelector(".lede").textContent
    === "Review proposals from agents. Once you accept one, it becomes an authority candidate."
    && !!$("btnImportProposal"),
    "its introduction says accepting one makes an authority candidate, beside Import proposal");
  const keptPending = fixture.proposals.pending;
  fixture.proposals.pending = [];
  await vm.runInThisContext("renderAgentProposals")();
  check($("pendingProposals").children.length === 0 && !$("noPendingProposals")
    && !/No proposal from an agent is waiting/.test($("view-proposals").textContent),
    "with no proposal waiting, there is no empty-state sentence");
  fixture.proposals.pending = keptPending;
  await vm.runInThisContext("renderAgentProposals")();
  const cards = $("pendingProposals").querySelectorAll(".proposal");
  const fresh = cards.find((c) => c.getAttribute("data-id") === fixture.proposal_pending);
  const staleCard = cards.find((c) => c.getAttribute("data-id") === fixture.proposal_stale);
  check(cards.length === fixture.proposals.pending.length && fresh && staleCard, "each pending proposal has a card");
  check(/Create/.test(fresh.querySelector("header").textContent)
    && fresh.querySelector(".proposal-target").textContent === "authority-candidates/release-rule.md"
    && /from codex \(self-reported\)/.test(fresh.querySelector(".proposal-meta").textContent)
    && /Releases need a written rule\./.test(fresh.querySelector(".proposal-reason").textContent),
    "a card says what it proposes, for which target, from whom by its own account, and why");
  const impactToggle = fresh.querySelector(".disclosure-toggle");
  check(impactToggle && /the agent's assessment, advisory/.test(impactToggle.textContent)
    && impactToggle.getAttribute("aria-expanded") === "false",
    "the expected context impact is the agent's advisory claim, closed until asked for");
  check(staleCard.classList.contains("is-stale") && /Stale/.test(staleCard.querySelector("header").textContent)
    && /cannot be accepted as written/.test(staleCard.textContent)
    && buttonSaying(staleCard, "Review and accept…").disabled && !buttonSaying(staleCard, "Reject…").disabled,
    "a stale proposal says why, cannot be accepted, and can still be rejected");
  check(!$("proposalsImportedGroup").hidden
    && $("importedProposals").querySelectorAll(".proposal").length === fixture.proposals.imported.length
    && /imported/.test($("importedProposals").querySelector(".proposal-meta").textContent),
    "imported proposals are listed apart");
  const odd = $("unexpectedRecords").querySelector(".unexpected-record");
  check(!$("proposalsUnexpectedGroup").hidden && odd && /dropped-in\.json/.test(odd.textContent)
    && /Unexpected — not a proposal/.test(odd.textContent) && !buttonSaying(odd, "Review and accept…"),
    "an unexpected local record is shown apart, never as a proposal, and cannot be accepted");
  await click(buttonSaying(odd, "View contents"));
  check(lastCall("/api/proposals/unexpected").body.name === "dropped-in.json"
    && $("unexpectedText").textContent === fixture.unexpected_view.text
    && /viewing it changes nothing/.test($("review").textContent),
    "its contents can be viewed, as text, changing nothing");
  vm.runInThisContext("closeReview")();

  console.log("\nAccepting: previewed, ordinary confirmation, a candidate only");
  await click(buttonSaying(fresh, "Review and accept…"));
  check(JSON.stringify(lastPlan().body) === JSON.stringify({ kind: "accept-proposal",
    request: { proposal_id: fixture.proposal_pending } }), "it previews accepting exactly this proposal");
  check(/never changes governing context/.test($("review").textContent) && !$("confirmPhrase")
    && $("review").querySelectorAll(".file-toggle .why").every((n) => n.textContent === "Private local state — not agent-visible"),
    "the preview says it changes no governing context, every write is private, and no phrase is asked");
  const acceptedRow = $("review").querySelectorAll(".file-item")
    .find((li) => li.querySelector(".file-path").textContent === fixture.accepted_path);
  await click(buttonSaying(acceptedRow, "Read"));
  check(/As this preview would leave it/.test($("docViewer").querySelector(".reader-banner").textContent)
    && /Tag every release\./.test($("docViewer").textContent), "the candidate it would file can be read first");
  await click(buttonSaying($("docViewer"), "Close"));
  await click(buttonSaying($("review"), "Accept as candidate"));
  check(lastCall("/api/apply").body.kind === "accept-proposal" && lastCall("/api/apply").body.confirm === true,
    "accepting applies with an ordinary confirmation");
  check(/Only an authority candidate changed — not context\./.test(toastNow().textContent)
    && !!buttonSaying(toastNow(), "Go to Authority Candidates"),
    "the message says only a candidate changed, with the way to it");
  clearToasts();

  console.log("\nRejecting records why");
  await click(buttonSaying($("pendingProposals").querySelectorAll(".proposal")[0], "Reject…"));
  $("formField-reason").value = "Not now.";
  await click(buttonSaying($("review"), "Preview the rejection"));
  check(lastPlan().body.kind === "reject-proposal" && lastPlan().body.request.reason === "Not now."
    && buttonSaying($("review"), "Reject proposal").className.indexOf("danger") !== -1 && !$("confirmPhrase"),
    "rejecting previews the decision with its reason, confirmed ordinarily");
  vm.runInThisContext("closeReview")();

  console.log("\nImporting a proposal an agent returned");
  await click($("btnImportProposal"));
  check($("importJson") && /checked exactly as `charter propose` checks it/.test($("review").textContent),
    "Import proposal asks for the JSON, and says it is checked as the command checks it");
  $("importJson").value = JSON.stringify(Object.assign(JSON.parse(fixture.import_returned), { base_commit: "abc123" }));
  await click($("btnCheckImport"));
  check($("importProblems") && /base_commit/.test($("importProblems").textContent) && !$("btnFileImport"),
    "a field that is not allowed is named, and nothing can be filed");
  $("importJson").value = fixture.import_returned;
  await click($("btnCheckImport"));
  check(/chat-agent \(self-reported\)/.test($("importSummary").textContent) && $("btnFileImport"),
    "a proposal that passes is summarized, ready to file");
  check(!calls.some((c) => c.url === "/api/proposals/import"), "checking files nothing");
  await click($("btnFileImport"));
  check(lastCall("/api/proposals/import").body.confirm === true
    && /as an imported proposal, for review\. It is not context\./.test(toastNow().textContent),
    "filing it is the person's confirmed action, and it is not context");
  clearToasts();

  /* --------------------------------------------------------- Change Sets */

  console.log("\nChange Sets: an index, and one draft's dedicated editor in its place");
  await show("state_valid");
  await navTo("changesets");
  check(lastCall("/api/changesets/list") && !$("changeSetIndex").hidden && $("changeSetEditor").hidden
    && $("changeSetList").querySelectorAll(".changeset-row").length === fixture.cs_list.drafts.length,
    "Change Sets opens on its index of private drafts");
  check($("changeSetIndex").querySelector(".lede").textContent
    === "Plan several authority changes and apply them together with one confirmation.",
    "its introduction is one sentence");
  const aboutCs = $("changeSetInfo").querySelector(".info-pop");
  check(/never commits: Git is yours/.test(aboutCs.textContent) && /private local state/.test(aboutCs.textContent),
    "its information control says drafts are private, and Git is the person's");
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
    && !/commit/i.test($("csTitleHint").textContent), "a private, untitled draft, its name never invented");
  check($("csNoRows") && $("csPreview").disabled, "an empty plan cannot be previewed");

  console.log("\nBuild change set: the person's own rows and decisions");
  const addRow = $("csAddRow");
  check(addRow.options.map((o) => o.value).slice(1).join() === fixture.cs_created.others.map((g) => g.path).join(),
    "any governing document can be added to the plan");
  addRow.value = "authoritative/a.md";
  csNext = fixture.cs_row;
  await click($("csAddRowButton"));
  check(JSON.stringify(lastCall("/api/changeset/update").body.outcomes) === JSON.stringify({ "authoritative/a.md": { outcome: "" } }),
    "adding a row declares nothing");
  check($("csOutcome-0").value === "" && !$("csCandidate-0"), "its outcome starts unchosen, with no candidate");
  check($("csOutcome-0").options.map((o) => o.value).join() === ",retain,revise,replace,withdraw",
    "the outcomes are retain, revise, replace and withdraw");
  check(!!$("csRetainOthers") && /Retain all other governing documents/.test($("csRetainOthers").textContent),
    "every other governing document waits for one explicit Retain decision");

  console.log("\nA complete plan, beside its review");
  csNext = fixture.cs_valid;
  await vm.runInThisContext("openChangeSet")(fixture.cs_valid.draft.id);
  await settle();
  check(!$("csPreview").disabled && /Retained — your decision/.test($("csOthers").textContent)
    && $("csRows").querySelectorAll(".cs-row").length === 2 && $("csAlongside").querySelectorAll(".cs-row").length === 1,
    "revise, withdraw and govern alongside, the others retained by decision: ready to preview");
  check($("csBuild").children.map((c) => c.id).join() === "csPlan,csReview"
    && $("csReview").children.map((c) => c.id).join() === "csPromptPanel,csResponsesPanel",
    "the plan sits beside a column of the context-impact review above the agent responses");
  check(/grid-template-columns:\s*minmax\(0,\s*1\.15fr\)\s*minmax\(0,\s*1fr\)/.test(rule(css, ".review .inner.cs-build"))
    && /@(?:media|container)[^{]*\{\s*\.review \.inner\.cs-build\s*\{\s*grid-template-columns:\s*minmax\(0,\s*1fr\)/.test(css),
    "two columns on desktop, stacked on narrow widths");
  check($("csCopyPrompt") && $("csDisclosure").textContent === fixture.cs_valid.disclosure_warning
    && $("csDisclosure").parentNode === $("csCopyPrompt").parentNode,
    "the review is one prompt to copy, the disclosure warning beside the button");
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
  csNext = packetView;
  await vm.runInThisContext("openChangeSet")(packetView.draft.id);
  await settle();
  check($("csSavePacket") && !$("csPromptText") && $("csPacketDisclosure").textContent === fixture.cs_valid.packet_disclosure,
    "a review packet to save instead, its disclosure beside it, and no text on the page");
  await click($("csSavePacket"));
  check(lastCall("/api/changeset/packet/save").body.plan_fingerprint === fixture.cs_valid.plan_fingerprint,
    "saving asks the server, for this plan");
  check(/Choose a folder outside every Agent Context/.test($("csPacketRefused") ? $("csPacketRefused").textContent : "")
    || !!$("csPacketSaved"), "a refused destination is said, or the saved file is named");

  console.log("\nAgent responses: advisory, side by side, never choosing");
  csNext = fixture.cs_reports;
  await vm.runInThisContext("openChangeSet")(fixture.cs_reports.draft.id);
  await settle();
  const reportCards = $("csReports").querySelectorAll(".report-card");
  check(reportCards.length === 2 && reportCards.every((c) => /Not Verified, Not Findings/.test(c.textContent)),
    "two reports, each shown as the agent's unverified claims");
  check(/Agent suggests: revise/.test(reportCards[0].textContent) && /Agent suggests: retain/.test(reportCards[1].textContent)
    && $("csOutcome-0").value === "revise", "they disagree side by side, and neither changes an outcome");
  check(/display:\s*grid/.test(rule(css, ".report-grid")) && /max-height/.test(rule(css, ".cs-reasons")),
    "reports sit in a grid; long lists stay bounded");

  console.log("\nStale review evidence, and Refresh");
  csNext = fixture.cs_stale;
  await vm.runInThisContext("openChangeSet")(fixture.cs_stale.draft.id);
  await settle();
  check(/Stale — Refresh Before Applying/.test($("csPlan").textContent) && $("csPreview").disabled
    && $("csReports").querySelectorAll(".report-card").every((c) => /Stale — not current review evidence/.test(c.textContent)),
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
  check(steps2[1].getAttribute("aria-current") === "step" && $("csPreviewing") && $("setCompare"),
    "the second screen: the governing set before and after");
  check(labelFor($("review"), "confirmPhrase").textContent === "Type “change governing context” once to apply the whole change set"
    && /written as one action/.test($("review").textContent) && /does not stage, commit/.test($("review").textContent),
    "one typed phrase for the whole set, written as one action, with no Git");
  type($("confirmPhrase"), "change governing context");
  csNext = fixture.cs_applied;
  await click($("btnApply"));
  const csApplied = lastCall("/api/changeset/apply").body;
  check(csApplied.confirm === "change governing context" && csApplied.id === fixture.cs_refreshed.draft.id
    && csApplied.plan_id === fixture.cs_plan.plan_id,
    "applying sends the phrase for this draft");
  check(/Applied — receipt/.test($("csStatus").textContent) && /Private record — not context/.test($("csStatus").textContent)
    && /Git is untouched/.test($("csRecorded").textContent) && !/Recorded in Git/.test($("changeSetEditor").textContent),
    "it becomes an immutable private receipt, saying Git is left to the person");
  check($("csReceiptOutcomes").querySelectorAll("li").length === 3 && !$("csTitle") && !$("csOutcome-0")
    && /Change set: Restructure/.test($("csSummary").textContent) && !!$("csCopySummary"),
    "with its final outcomes, a copyable summary, and nothing editable");
  await click($("csBackToIndex"));
  check(!$("changeSetIndex").hidden && $("changeSetEditor").hidden, "← Change Sets returns to the index");
  clearToasts();

  console.log("\nLong scopes: one line in the plan, the whole scope one disclosure away");
  csNext = fixture.cs_valid;
  await vm.runInThisContext("openChangeSet")(fixture.cs_valid.draft.id);
  await settle();
  const longScope = fixture.cs_long_scope;
  check(longScope.length > 400 && fixture.cs_valid.rows.some((r) => r.candidate && r.candidate.scope === longScope),
    "the plan's revision has a scope of hundreds of characters");
  const revRow = fixture.cs_valid.rows.findIndex((r) => r.candidate && r.candidate.scope === longScope);
  const line = $(`csScopeLine-${revRow}`);
  check(line && line.classList.contains("cs-scope-oneline") && line.textContent.indexOf(longScope) !== -1
    && /^Scope (changes|unchanged)Candidate's scope: /.test(line.textContent),
    "a revision row shows the candidate's scope as one line — the whole text, for a screen reader");
  const toggle = $(`csScopeToggle-${revRow}`);
  const region = regionOf(toggle);
  check(toggle.tagName === "BUTTON" && toggle.getAttribute("type") === "button" && toggle.getAttribute("tabindex") === null
    && toggle.getAttribute("aria-expanded") === "false" && region && region.hidden
    && region.querySelectorAll("dl").length === 1,
    "its complete scope and comparison are behind a closed disclosure, a keyboard-operable button");
  await click(toggle);
  check(toggle.getAttribute("aria-expanded") === "true" && !region.hidden
    && /Candidate's scope[\s\S]*Current scope[\s\S]*Scope after/.test(region.textContent)
    && region.textContent.indexOf(longScope) !== -1,
    "opened, it says so, and shows the whole scope beside the current and resulting scope");
  await click(toggle);
  check(toggle.getAttribute("aria-expanded") === "false" && region.hidden, "and closes again");
  check(!!$(`csEditDetails-${revRow}`) && $(`csEditDetails-${revRow}`).textContent === "Edit details…",
    "the planned candidate has Edit details…");

  const alongsideLine = $("csAlongsideScopeLine-0");
  const alongsideToggle = $("csAlongsideScopeToggle-0");
  check(alongsideLine && alongsideLine.classList.contains("cs-scope-oneline")
    && alongsideLine.textContent.indexOf("Delta: " + longScope) !== -1
    && $("csAlongside").querySelectorAll("dl").length === regionOf(alongsideToggle).querySelectorAll("dl").length,
    "a candidate governing alongside shows one line too, with no comparison in the open");
  check(alongsideToggle.getAttribute("aria-expanded") === "false" && regionOf(alongsideToggle).hidden
    && !!$("csAlongsideEdit-0"),
    "its complete scope is behind a closed disclosure, beside Edit details…");
  await click(alongsideToggle);
  check(!regionOf(alongsideToggle).hidden && regionOf(alongsideToggle).textContent.indexOf("Delta: " + longScope) !== -1,
    "opened, it shows the whole scope");
  await click(alongsideToggle);

  const oneline = rule(css, ".cs-scope-oneline");
  check(/white-space:\s*nowrap/.test(oneline) && /text-overflow:\s*ellipsis/.test(oneline) && /overflow:\s*hidden/.test(oneline),
    "on screen the line is clipped with an ellipsis, so a long scope cannot make the card tall");
  check(/min-width:\s*0/.test(rule(css, ".cs-item")) && /minmax\(0, 1fr\)/.test(rule(css, ".cs-item"))
    && /min-width:\s*0/.test(rule(css, ".cs-scope")),
    "and the card can shrink to its column, so nothing scrolls sideways");
  check(/max-height/.test(rule(css, ".cs-scope-detail")) && /overflow-y:\s*auto/.test(rule(css, ".cs-scope-detail")),
    "an opened full scope is bounded, and scrolls on its own");

  console.log("\nA blank candidate scope says it inherits the replaced document's");
  csNext = fixture.cs_blank;
  await vm.runInThisContext("openChangeSet")(fixture.cs_blank.draft.id);
  await settle();
  check(/Candidate's scope: Blank — inherits the replaced document's scope/.test($("csScopeLine-0").textContent),
    "the one line says the blank scope inherits");
  await click($("csScopeToggle-0"));
  check(/\(inherited\)/.test(regionOf($("csScopeToggle-0")).textContent),
    "and the comparison shows the inherited scope after");
  await click($("csScopeToggle-0"));

  console.log("\nEdit details…: the candidate's own metadata, then back to the draft to refresh it");
  csNext = fixture.cs_valid;
  await vm.runInThisContext("openChangeSet")(fixture.cs_valid.draft.id);
  await settle();
  const editPath = fixture.cs_valid.rows[revRow].candidate.path;
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

  console.log("\nApplied change sets: final outcomes and established governing documents");
  const applied = fixture.cs_applied_list.drafts.find((d) => d.state === "applied");
  check(applied && applied.final_outcomes === 3 && applied.established === fixture.cs_applied.receipt.after.length,
    "the server counts an applied change set from its receipt");
  const savedList = fixture.cs_list;
  fixture.cs_list = fixture.cs_applied_list;
  await vm.runInThisContext("renderChangeSets")();
  await settle();
  const card = $("changeSetList").querySelectorAll(".changeset-row").find((r) => r.getAttribute("data-id") === applied.id);
  check(card && /3 final outcomes · \d+ established governing documents/.test(card.textContent)
    && !/planned/.test(card.textContent),
    "its index card says final outcomes and established governing documents, never planned changes");
  fixture.cs_list = savedList;
  csNext = fixture.cs_applied;
  await vm.runInThisContext("openChangeSet")(fixture.cs_applied.draft.id);
  await settle();
  const editorText = $("changeSetEditor").textContent;
  check(/Final Outcomes \(3\)/.test(editorText)
    && new RegExp(`Established Governing Documents \\(${fixture.cs_applied.receipt.after.length}\\)`).test(editorText)
    && !/planned/i.test(editorText.replace($("csSummary").textContent, "")),
    "the receipt says final outcomes and established governing documents, never planned");
  check($("csReceiptEstablishedToggle").getAttribute("aria-expanded") === "false"
    && $("csReceiptEstablished").querySelectorAll("li").length === fixture.cs_applied.receipt.after.length,
    "the established governing documents are listed behind a disclosure");
  check(!!$("csReceiptRetainedToggle") && $("csReceiptRetained").querySelectorAll("li").length
      === fixture.cs_applied.receipt.outcomes.filter((o) => o.effect === "retain").length
    && $("csReceiptOutcomes").querySelectorAll("li").length === 3,
    "the documents retained unchanged are listed apart from the final outcomes");
  check(/\nFinal outcomes:\n/.test($("csSummary").textContent), "its summary names the final outcomes");
  await vm.runInThisContext("closeChangeSet")();

  console.log("\nAn older receipt keeps its stored summary, under the new wording");
  const older = JSON.parse(JSON.stringify(fixture.cs_applied));
  older.receipt.summary = older.receipt.summary.replace("Final outcomes:", "Declared outcomes:");
  csNext = older;
  await vm.runInThisContext("openChangeSet")(older.draft.id);
  await settle();
  check($("csSummary").textContent === older.receipt.summary && /Declared outcomes:/.test($("csSummary").textContent)
    && /Final Outcomes \(3\)/.test($("changeSetEditor").textContent)
    && /Established Governing Documents/.test($("changeSetEditor").textContent),
    "its summary is shown exactly as kept; only the labels around it are new");
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
    check(!v.hidden && firstH2.textContent === "Connect Agents with MCP (Recommended)"
      && firstH2.id === "connectMcpTitle" && $("connectMcp").getAttribute("aria-labelledby") === "connectMcpTitle"
      && document.title === "Connect Agents — Charter"
      && !v.querySelector(".lede") && !$("connectStatus") && !/ready to connect/i.test(v.textContent)
      && $("connectMcp").firstChild === $("connectMcpInstruction")
      && $("connectMcpInstruction").textContent === "Configure the Charter MCP server for your agent."
      && !$("connectFolder") && !$("connectChecksDetails") && !$("connectLaunch") && !$("connectWritesNothing")
      && !$("connectPrerequisite"),
      `${name}: the MCP heading leads, with one instruction beneath — no page title, lede or readiness line`);
    const server = JSON.parse($("connectConfig").textContent).mcpServers[payload.server_name];
    const launched = [server.command].concat(server.args).join(" ");
    check($("connectConfig").textContent === payload.config_text
      && launched === (name === "Windows" ? "cmd /c " : "") + "charter mcp --context " + payload.folder,
      `${name}: the MCP configuration runs charter mcp --context <folder>`);
    payload.shells.forEach((s) => check($("connectClaude-" + s.shell).textContent === s.claude_code
      && /^claude mcp add charter-/.test(s.claude_code) && s.claude_code.indexOf("--scope") === -1,
      `${name}: the claude mcp add command for ${s.label} is shown exactly, at Claude Code's default local scope`));
    check($("connectCodex").textContent === payload.codex_toml && /^\[mcp_servers\./.test(payload.codex_toml)
      && $("connectPointer").textContent === payload.pointer
      && $("connectVerifyPrompt").textContent === payload.verify_prompt,
      `${name}: Codex's TOML, the startup pointer and the verification prompt are shown exactly`);
    check(v.querySelectorAll("h2").map((h) => h.textContent).join(" | ")
        === "Connect Agents with MCP (Recommended) | Connect Agents with File Access"
      && v.querySelectorAll("h3").map((h) => h.textContent).join(" | ")
        === "Instruct Your Agent to Use Charter | Test the Connection"
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
    const pointerSection = $("connectPointerSection");
    check(v.querySelectorAll(".disclosure-toggle").length === 1 && v.querySelector(".disclosure-toggle") === $("connectFilesToggle")
      && !$("connectPointerToggle") && !$("connectPointerDetails") && !/Optional/.test(v.textContent)
      && within(pointerSection, $("connectMcp")) && pointerSection.getAttribute("aria-labelledby") === "connectPointerTitle"
      && $("connectPointerTitle").tagName === "H3" && $("connectPointerTitle").textContent === "Instruct Your Agent to Use Charter",
      `${name}: file access is the only disclosure; the agent instruction is a shown, labelled section, not optional`);
    const pointerParts = pointerSection.children;
    check(pointerParts[0] === $("connectPointerTitle") && pointerParts[1] === $("connectPointerNote")
      && pointerParts[2] === $("connectPointerBlock")
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
      && $("connectFilesToggle").parentNode.tagName === "H2"
      && $("connectFilesToggle").textContent === "Connect Agents with File Access",
      `${name}: file access is a closed section heading: one warning first, then the instruction`);
    await click($("connectFilesToggle"));
    check(!$("connectFilesDetails").hidden && $("connectFilesToggle").getAttribute("aria-expanded") === "true",
      `${name}: and opens from its heading`);
    await click($("connectFilesToggle"));
    check(!$("connectVerifyPromptBlock").querySelector(".hint") && $("connectTestTitle").textContent === "Test the Connection"
      && $("connectTestTitle").classList.contains("connect-label") && $("connectVerify").getAttribute("aria-labelledby") === "connectTestTitle"
      && !!$("btnCopyConnectVerifyPrompt"),
      `${name}: Test the connection is a small label over the prompt and its Copy button, with no other words`);
  }
  check(fixture.connect_windows.shells.map((s) => s.label).join() === "PowerShell,Command Prompt"
    && fixture.connect_posix.shells.map((s) => s.label).join() === "Terminal",
    "Windows offers PowerShell and Command Prompt commands; elsewhere one terminal command");
  check(fixture.connect_ready.ready && fixture.connect_ready.folder === fixture.state_valid.root,
    "the console's own answer for the open, valid Agent Context is ready");

  console.log("\nMCP needs charter on PATH: the Agent Context is ready, the agent setup is not");
  for (const [name, payload] of [["Windows", fixture.connect_windows_needs_path],
    ["macOS and Linux", fixture.connect_posix_needs_path]]) {
    connectAnswer = payload;
    await navTo("governing");
    await navTo("connect");
    check(payload.connect === "needs-path" && $("connectStatus").dataset.connect === "needs-path"
      && $("connectStatusText").textContent === "Agent Context ready. Add Charter to your PATH before a new agent host can connect."
      && !/ready to connect/i.test($("connectStatus").textContent),
      `${name}: “Agent Context ready. Add Charter to your PATH…”, never “ready to connect”`);
    check(!!$("connectPrerequisite") && $("connectAddToPath").textContent === "charter add-to-path"
      && /quit and reopen the agent host/.test($("connectAddToPathBlock").textContent)
      && /cannot run/.test($("connectLauncher").textContent),
      `${name}: charter add-to-path is offered to copy, saying the host must be restarted afterwards`);
    check($("connectConfig").textContent === payload.config_text
      && payload.shells.every((s) => $("connectClaude-" + s.shell).textContent === s.claude_code)
      && $("connectInstruction").textContent === payload.instruction,
      `${name}: the copy-ready configuration, commands and file instruction stay visible`);
    check(connectView().textContent.indexOf("charter add-to-path") < connectView().textContent.indexOf(payload.config_text.slice(0, 20)),
      `${name}: the prerequisite comes before the configuration`);
  }
  Object.defineProperty(global, "navigator", { configurable: true,
    value: { clipboard: { writeText: async (t) => { global.__copied = t; } } } });
  clearToasts();
  await click($("btnCopyConnectAddToPath"));
  check(global.__copied === "charter add-to-path" && /Nothing was written/.test(toastNow().textContent),
    "Copy copies charter add-to-path, and runs nothing");
  clearToasts();

  console.log("\nWindows, a path cmd /c cannot carry: file access, and the MCP limitation");
  connectAnswer = fixture.connect_files_only;
  await navTo("governing");
  await navTo("connect");
  check($("connectStatus").dataset.connect === "files-only"
    && /^Agent Context ready for file access\./.test($("connectStatusText").textContent)
    && !/ready to connect/i.test($("connectStatus").textContent),
    "it says the Agent Context is ready for file access, not ready to connect");
  check(!!$("connectMcpLimitation") && /cmd \/c/.test($("connectMcpLimitation").textContent)
    && /No MCP configuration is offered/.test($("connectMcpLimitation").textContent),
    "it gives the concrete MCP limitation");
  check(!$("connectConfig") && !$("connectClaude-powershell") && !$("connectClaude-cmd")
    && !$("connectCodex") && !$("connectPointer") && !$("connectCheckToggle") && !$("connectAddToPath")
    && connectView().querySelectorAll("pre").length === 2 && !!$("connectVerifyPrompt"),
    "and offers no MCP configuration or command that would not work: only the verification prompt and file instruction");
  check($("connectInstruction").textContent === fixture.connect_files_only.instruction
    && !!$("btnCopyConnectInstruction") && !$("connectFilesDetails").hidden
    && $("connectFilesToggle").getAttribute("aria-expanded") === "true" && !$("connectHosts"),
    "the file-access instruction, the only route here, starts open to copy; no host choice is offered");
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
  check(/font-weight:\s*400/.test(rule(css, ".connect-method .connect-label"))
    && !/max-width/.test(rule(css, "#connectMcpTitle"))
    && /minmax\(0, 1fr\)/.test(rule(css, "#connectBody")) && /auto-fit/.test(rule(css, ".connect-shells")),
    "the lede uses the full width; the body and the shell commands still reflow on a narrow screen");

  console.log("\nUnknown origin is said on Governing documents only");
  const beforeOrigin = currentState;
  currentState = fixture.state_valid;
  for (const view of ["connect", "settings", "candidates", "proposals", "changesets"]) {
    await navTo(view);
    check(!within($("originUnknown"), $("view-" + view)) && !within($("originUnknown"), $("contextStatus"))
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
    && /Revise, revises “Coding Standards” · How code is written\. · changes 1 line · created 2026-10-14/.test(twinLabels[twins[0].path]),
    "two otherwise identical candidates differ, with their path added beside the source, scope, change and date that still read alike");
  const differing = labelsFor([twins[0], Object.assign({}, twins[1], { change_summary: "changes 3 lines" })]);
  check(Object.values(differing).every((l) => !/authority-candidates\//.test(l))
    && differing[twins[0].path] !== differing[twins[1].path],
    "candidates the change summary already tells apart carry no path at all: never the suffix alone");
  const earlier = labelsFor([Object.assign({}, twins[0], { revises_current: false })])[twins[0].path];
  check(/revises an earlier version of “Coding Standards”/.test(earlier),
    "a revision made from an earlier version says so in the picker");

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
