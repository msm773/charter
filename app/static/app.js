/* Charter — front end.
   No framework, no build step. The server owns every rule; this file collects
   human decisions and renders what the server plans to do. */

const $ = (id) => document.getElementById(id);
let state = { open: false };
let staged = null;      // the file currently in Create candidate
let review = null;      // { kind, request, plan, applied }
/* The primary areas of an open Agent Context, each with its own address
   (#settings, …), so a link opens it and Back returns to the one before.
   Open Agent Context is not among them: it is where you are when none is open. */
const ROUTED_VIEWS = ["governing", "candidates", "intake", "proposals", "changesets",
  "connect", "settings"];
/* The views drawn from the document lists. */
const CONTEXT_VIEWS = ["governing", "candidates"];
/* Views reached by an action rather than the navigation, and the view each
   is started from: Create candidate files an authority candidate. */
const VIEW_OWNER = { intake: "candidates" };
const VIEWS = ["open"].concat(ROUTED_VIEWS);
const hasHistory = () => typeof history !== "undefined" && !!history.pushState && typeof location !== "undefined";
function viewFromAddress() {
  const view = hasHistory() ? String(location.hash || "").replace(/^#/, "") : "";
  return ROUTED_VIEWS.indexOf(view) !== -1 ? view : "";
}
let currentView = viewFromAddress() || "governing";
let reading = null;    // { source, data, opener } — the Markdown open in the viewer
let readerMode = "rendered";

/* ---------------------------------------------------------------- helpers */

/* Filled in by the server when it serves this page: a per-launch token that,
   with the server's Host check, tells the real console page apart from any
   other origin. Sent on every API request. */
const CONSOLE_TOKEN = (document.querySelector('meta[name="charter-console-token"]') || {}).content || "";

async function call(path, body) {
  /* The console's own page says so on every request: the server answers
     nothing else, since the console shows private local state. */
  const headers = { "X-Charter-Console": "person", "X-Charter-Console-Token": CONSOLE_TOKEN };
  const opts = body === undefined
    ? { headers }
    : { method: "POST", headers: { ...headers, "Content-Type": "application/json" },
        body: JSON.stringify(body) };
  let res;
  try {
    res = await fetch(path, opts);
  } catch (netErr) {
    /* The fetch itself failed: the console process is not answering (it was
       stopped, or the computer slept). Say what to do, not "Failed to fetch". */
    const err = new Error("The Charter console is not responding — it may have "
      + "stopped. Start it again with `charter serve`, then reload this page.");
    err.offline = true;
    throw err;
  }
  const data = await res.json().catch(() => ({ error: "The server returned something unreadable." }));
  if (!res.ok) {
    const err = new Error(data.error || `Request failed (${res.status})`);
    /* A refusal is usually just words. The rare failure that leaves something
       for a person to finish carries the detail needed to offer one button. */
    err.recovery = data.recovery || null;
    err.data = data;
    throw err;
  }
  return data;
}

/* `action`, when given, is one optional follow-up — { label, onclick } — such
   as the details of a change that has just been recorded.

   An error stays until it is dismissed: it says why something did not happen,
   and nobody should have to read that against a clock. A success message goes
   by itself, but never while it is being pointed at or has focus. */
const TOAST_MS = 4500;
const TOAST_ACTION_MS = 8000;

function toast(message, isError, action) {
  document.querySelectorAll(".toast").forEach((t) => t.remove());
  const actions = [].concat(action || []);  // one action, or several
  const node = el("div", { class: "toast" + (isError ? " error" : ""), role: isError ? "alert" : "status" }, [
    el("span", { class: "toast-text" }, withCode(message)),
    ...actions.map((a) => el("button", { type: "button", class: "btn ghost small toast-action", text: a.label,
      onclick: () => { node.remove(); a.onclick(); } })),
    isError ? el("button", { type: "button", class: "btn ghost small toast-dismiss", text: "Dismiss",
      onclick: () => node.remove() }) : null,
  ]);
  document.body.appendChild(node);
  if (isError) return;
  let timer = null;
  const start = () => { clearTimeout(timer); timer = setTimeout(() => node.remove(), actions.length ? TOAST_ACTION_MS : TOAST_MS); };
  const pause = () => { clearTimeout(timer); timer = null; };
  node.addEventListener("mouseenter", pause);
  node.addEventListener("focusin", pause);
  node.addEventListener("mouseleave", start);
  node.addEventListener("focusout", start);
  start();
}

/* A time as people say it: “just now”, “5 min ago”, “yesterday”. */
function relativeTime(iso, now) {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.floor(((now === undefined ? Date.now() : now) - then) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.max(1, Math.floor(seconds / 60));
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return days === 1 ? "yesterday" : `${days} days ago`;
  return new Date(then).toISOString().slice(0, 10);
}

/* ------------------------------------------------------------- disclosure */

/* One accessible disclosure for every “About …” and “details” section: a real
   button saying whether it is expanded, controlling a region hidden until
   asked for. Every one starts closed. `open` and `onToggle` let a region that
   is redrawn (the Git-base comparison) keep the state someone chose. */
function toggleDisclosure(button, force) {
  const region = $(button.getAttribute("aria-controls"));
  const open = force === undefined ? button.getAttribute("aria-expanded") !== "true" : !!force;
  button.setAttribute("aria-expanded", String(open));
  if (region) region.hidden = !open;
  return open;
}

let disclosureSeq = 0;

function disclosure(label, content, options = {}) {
  const id = options.id || "disclosure-" + (++disclosureSeq);
  const open = !!options.open;
  const region = el("div", { id, class: "disclosure-body", hidden: open ? null : "" }, content);
  const button = el("button", { type: "button", class: "disclosure-toggle", text: label,
    id: options.buttonId || null, "aria-expanded": String(open), "aria-controls": id,
    onclick: () => {
      const now = toggleDisclosure(button);
      if (options.onToggle) options.onToggle(now);
    } });
  return el("div", { class: "disclosure" + (options.class ? " " + options.class : "") }, [button, region]);
}

/* A locked step is inert: out of the tab order and the accessibility tree. */
function setInert(node, on) {
  node.inert = !!on;
  if (on) node.setAttribute("inert", "");
  else node.removeAttribute("inert");
}

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key === "html") node.innerHTML = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== null && value !== false && value !== undefined) node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) if (child) node.appendChild(child);
  return node;
}

const chip = (text, kind) => el("span", { class: "chip" + (kind ? " " + kind : ""), text });

/* A validation issue, built as nodes: a path or message is shown as the
   characters it is, never interpreted as markup; `code` in the message is
   shown as code. */
const issueItem = (i) => el("li", { class: i.level }, [el("span", {}, i.general
  ? withCode(`${i.message}${i.fix ? " " + i.fix : ""}`)  // about the action, not one file
  : [el("code", { text: i.path || "folder" }), ...withCode(` — ${i.message}${i.fix ? " " + i.fix : ""}`)])]);

/* Every scope field — Create candidate, Revise… and Edit… — is the same
   compact control: the label Scope and this one helper, with no information
   control and no placeholder (Scope Authoring and Revision Workflow). */
const SCOPE_LABEL = "Scope";
const SCOPE_HINT = "A short routing summary shown in AGENT-CONTEXT.md.";

function renderDiff(text) {
  const box = el("pre", { class: "diff" });
  (text || "").split("\n").forEach((line) => {
    let cls = "";
    if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") ||
        line.startsWith("index ") || line.startsWith("new file") || line.startsWith("deleted file")) cls = "meta";
    else if (line.startsWith("@@")) cls = "hunk";
    else if (line.startsWith("+")) cls = "add";
    else if (line.startsWith("-")) cls = "del";
    box.appendChild(el("div", { class: cls, text: line || " " }));
  });
  return box;
}

/* -------------------------------------------------------- file-first lists */

/* Planned changes, one item per file. A move is shown as one item only because
   the plan says so — a change naming the path it `moved_from` — never because
   two paths happen to share a file name. A replacement's candidate is
   promoted onto the governing path, and the version governing today moves to
   its actual archive path; each is shown exactly as planned. */
const OPERATION_CHIP = { create: "ok", modify: "proposed", move: "authority", promote: "authority",
  archive: "stale", delete: "stale" };

function changeItems(changes) {
  const movedAway = new Set(changes.filter((c) => c.moved_from).map((c) => c.moved_from));
  const items = [];
  changes.forEach((change) => {
    // The delete of a move's source is shown with that move, not on its own.
    if (change.action === "delete" && movedAway.has(change.path)) return;
    /* `preview` is the server's word on whether the file's result can be read
       as a document; a move is read at its destination. */
    if (change.moved_from) {
      const source = changes.find((o) => o.action === "delete" && o.path === change.moved_from);
      items.push({ op: change.move_kind || "move", path: `${change.moved_from} → ${change.path}`,
        outcome: change.reason, diffs: source ? [source.diff, change.diff] : [change.diff],
        target: change.path, preview: change.preview || null });
    } else {
      items.push({ op: change.action, path: change.path, outcome: change.reason,
        diffs: [change.diff], target: change.path, preview: change.preview || null });
    }
  });
  return items;
}

/* Collapsed by default. Each file's header is a real button carrying
   aria-expanded, controlling its own region, so it works from the keyboard
   and says what state it is in. Nothing is dropped: every diff is one click
   away, and Expand all shows the whole preview at once. */
let fileListSeq = 0;

/* `read(path, button)`, when given, opens a file's result in the Markdown
   viewer. Only files the server says have a readable result get the action;
   every other file keeps its diff, and says why there is nothing to render.

   `memory`, when given, is a Set of the paths left open. A list rebuilt with
   fresh data from the same Set opens the same files, so refreshing never
   collapses what someone was reading. */
function fileList(items, read, memory) {
  const toggles = [];
  const setOpen = (button, region, open) => {
    button.setAttribute("aria-expanded", String(open));
    region.hidden = !open;
    if (memory) { if (open) memory.add(button.dataset.path); else memory.delete(button.dataset.path); }
  };
  const list = el("ul", { class: "files" });
  items.forEach((item) => {
    const id = "file-detail-" + (++fileListSeq);
    const open = !!(memory && memory.has(item.path));
    const region = el("div", { id, class: "file-detail", role: "region",
      "aria-label": `Changes to ${item.path}`, hidden: open ? null : "" });
    const readable = !!(read && item.preview && item.preview.available);
    if (read && item.preview && !item.preview.available && item.preview.why) {
      region.appendChild(el("p", { class: "hint preview-unavailable" }, withCode(item.preview.why)));
    }
    item.diffs.forEach((diff) => region.appendChild(renderDiff(diff || "(no textual change to show)")));
    const button = el("button", {
      type: "button", class: "file-toggle", "aria-expanded": String(open), "aria-controls": id,
      "data-path": item.path,
      onclick: () => setOpen(button, region, button.getAttribute("aria-expanded") !== "true"),
    }, [
      chip(item.op, OPERATION_CHIP[item.op] || null),
      el("span", { class: "file-path", text: item.path }),
      item.outcome ? el("span", { class: "why", text: item.outcome }) : null,
    ]);
    toggles.push([button, region]);
    const row = readable
      ? el("div", { class: "file-row" }, [button, el("button", {
          type: "button", class: "btn ghost small file-read", text: "Read",
          "aria-label": `Read ${item.target} as it would be`,
          onclick: (event) => read(item.target, event.currentTarget) })])
      : button;
    list.appendChild(el("li", { class: "file-item" }, [row, region]));
  });
  const controls = el("div", { class: "files-controls" }, [
    el("span", { class: "hint", text: `${items.length} file${items.length === 1 ? "" : "s"}` }),
    el("button", { type: "button", class: "btn ghost small", text: "Expand all",
      onclick: () => toggles.forEach(([b, r]) => setOpen(b, r, true)) }),
    el("button", { type: "button", class: "btn ghost small", text: "Collapse all",
      onclick: () => toggles.forEach(([b, r]) => setOpen(b, r, false)) }),
  ]);
  return el("div", { class: "file-list" }, [controls, list]);
}

/* A small inline form panel, used for every governance act that needs choices
   before a plan can be computed. Cancel discards what was typed; `onCancel`
   says where it then leads. */
function formPanel(title, intro, fields, submitLabel, onSubmit, lead, onCancel) {
  const panel = $("review");
  panel.textContent = "";
  const inputs = {};
  const inner = el("div", { class: "inner" });
  if (lead) inner.appendChild(lead);  // what the form is about, above what it asks
  if (intro) inner.appendChild(el("div", { class: intro.tone || "note", text: intro.text || intro }));

  fields.forEach((f) => {
    let input;
    if (f.type === "select") {
      input = el("select", {});
      (f.options || []).forEach((o) => input.appendChild(el("option", { value: o.value, text: o.label })));
      if (f.value) input.value = f.value;
    } else if (f.type === "checkbox") {
      input = el("input", { type: "checkbox", style: "width:auto", checked: f.value ? "" : null });
    } else if (f.type === "textarea") {
      input = el("textarea", { rows: f.rows || 10 });
      input.value = f.value || "";
    } else {
      input = el("input", { type: "text", placeholder: f.placeholder || "", spellcheck: "false" });
      input.value = f.value || "";
    }
    inputs[f.name] = input;
    if (f.type !== "checkbox") input.setAttribute("id", `formField-${f.name}`);
    const label = f.type === "checkbox"
      ? el("label", { style: "display:flex; gap:.5rem; align-items:center" }, [input, el("span", { text: f.label })])
      : el("label", { text: f.label, for: `formField-${f.name}` });
    const field = el("div", { class: "field" }, f.type === "checkbox" ? [label] : [label, input]);
    if (f.hint) {
      /* The hint says what the field means, so it is read with the field. */
      const hintId = `formHint-${f.name}`;
      input.setAttribute("aria-describedby", hintId);
      field.appendChild(el("p", { class: "hint", id: hintId, text: f.hint }));
    }
    inner.appendChild(field);
  });

  inner.appendChild(el("div", { class: "actions" }, [
    el("button", {
      class: "btn", text: submitLabel,
      onclick: () => {
        const values = {};
        for (const [key, input] of Object.entries(inputs)) {
          values[key] = input.type === "checkbox" ? input.checked : input.value;
        }
        onSubmit(values);
      },
    }),
    el("button", { class: "btn ghost", type: "button", text: "Cancel",
      onclick: () => { panel.textContent = ""; if (onCancel) onCancel(); } }),
  ]));

  showFormPanel(title, inner);
}

/* The control that opened the current form panel, to return focus to on close. */
let panelOpener = null;

/* The frame every form panel shares: a title, a Close, and the form. On open,
   focus moves to the panel heading and Escape closes it; on close, focus
   returns to the control that opened it (UI Standards: visible focus, keyboard
   operability). */
function showFormPanel(title, inner, options = {}) {
  const panel = $("review");
  panelOpener = (typeof document !== "undefined" && document.activeElement
                 && document.activeElement.focus) ? document.activeElement : null;
  panel.textContent = "";
  const heading = el("h3", { text: title, tabindex: "-1" });
  panel.appendChild(el("section", { class: "review" }, [
    el("header", {}, [heading,
      options.close === false ? null : el("button", { class: "btn ghost small close", text: "Close", onclick: closePanel })]),
    inner,
  ]));
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
  heading.focus();
}

function closePanel() {
  const opener = panelOpener;
  panelOpener = null;
  $("review").textContent = "";
  if (opener && opener.focus) opener.focus();
}

/* After an action completes, move focus to a meaningful, visible destination —
   the updated heading, status or receipt — so a finished action never leaves
   focus on <body> (UI Standards: visible, keyboard-operable focus). `target`
   is an element or a selector; a non-interactive destination (a heading) is
   made focusable without being added to the tab order. */
function focusAfter(target) {
  const node = typeof target === "string"
    ? (document.getElementById(target) || document.querySelector(target)) : target;
  if (!node || !node.focus) return false;
  const tag = (node.tagName || "").toLowerCase();
  const native = tag === "a" || tag === "button" || tag === "input" || tag === "select"
    || tag === "textarea";
  const hasTabindex = node.getAttribute && node.getAttribute("tabindex") != null;
  if (!native && !hasTabindex && node.setAttribute) node.setAttribute("tabindex", "-1");
  node.focus();
  return true;
}

/* The heading of the view the person is on now: a stable focus destination when
   an action completes without opening something more specific. */
function currentViewHeading() {
  return document.querySelector("#view-" + currentView + " h2");
}

async function planFor(kind, request, options) {
  try {
    const plan = await call("/api/plan", { kind, request });
    openReview(kind, request, plan, options || {});
  } catch (err) { toast(err.message, true); }
}

/* ------------------------------------------------------------------ state */

/* Everything, now: the first load, and after an operation. A form someone is filling
   in — Create candidate, an open preview, the viewer — is left as it is. */
async function refresh() {
  viewSeq++;  // anything a navigation was still fetching is older than this
  state = await call("/api/state");
  renderShell();
  if (!state.open) { closeDocument(); renderStart(); show("open"); return; }
  await loadCommand();
  announceRecovery();
  renderKnowledge();
  renderIntakeForm();
  renderSettings();
  await reloadReader();
  await renderAgentProposals();
  await renderChangeSets();
  await renderConnect();
  show(currentView);
}

/* Navigation's refresh: fresh state, and fresh data for the view being opened,
   so every click shows the Agent Context as it is now. */
let viewSeq = 0;

async function refreshView(view) {
  const seq = ++viewSeq;
  let next;
  try { next = await call("/api/state"); } catch (err) { toast(err.message, true); return; }
  if (seq !== viewSeq) return;  // a later navigation has taken over
  state = next;
  renderShell();
  if (!state.open) { renderStart(); show("open"); return; }
  announceRecovery();
  if (CONTEXT_VIEWS.indexOf(view) !== -1) renderKnowledge();
  else if (view === "intake") renderIntakeForm();
  else if (view === "settings") renderSettings();
  else if (view === "proposals") await renderAgentProposals();
  else if (view === "changesets") await renderChangeSets();
  else if (view === "connect") await renderConnect();
}

/* A click in the navigation adds a history entry; Back and Forward
   (`fromHistory`) move between the entries without adding more. */
function navigate(view, fromHistory) {
  if (!state.open) return;
  if (!fromHistory && hasHistory() && ROUTED_VIEWS.indexOf(view) !== -1 && viewFromAddress() !== view) {
    history.pushState({ from: currentView }, "", "#" + view);
  }
  closeDocument();
  show(view);
  return refreshView(view);
}

/* Create candidate, once filed or cancelled, is finished, and its emptied form
   must not be where Back leads: its history entry becomes Authority
   candidates. */
async function leaveIntake() {
  const from = hasHistory() && history.state ? history.state.from : "";
  if (hasHistory() && history.replaceState) history.replaceState(null, "", "#candidates");
  closeDocument();
  show("candidates");
  if (from === "candidates" && history.back) history.back();
  await refreshView("candidates");
  focusCandidatesHeading();
}

if (typeof window !== "undefined" && window.addEventListener) {
  window.addEventListener("popstate", () => {
    const view = viewFromAddress() || "governing";
    if (state.open && view !== currentView) navigate(view, true);
    if (state.open && view === "changesets") changeSetsFromHistory();
  });
}


/* Proposals waiting for a decision: from agents and imported. A stale one is
   said in words as well as colour. */
function renderTally() {
  const p = state.open ? state.proposals : null;
  const total = p ? p.pending + p.imported : 0;
  const tally = $("tallyProposals");
  tally.textContent = p ? `(${p.stale ? `${total} · ${p.stale} stale` : total})` : "";
  tally.className = "tally" + (p && p.stale ? " alert" : "");
  $("tallyProposalsLabel").textContent = p
    ? `: ${total} waiting${p.stale ? `, ${p.stale} stale` : ""}${p.unexpected ? `, ${plural(p.unexpected, "unexpected record", "unexpected records")}` : ""}` : "";
}

/* Change sets still being worked on, including a waiting, blocked or stale
   draft a refresh can bring up to date. An applied change set is a private
   receipt and an abandoned one is finished: neither counts. */
const isActiveDraft = (d) => !d.unreadable && d.state !== "applied" && d.state !== "abandoned";

function renderChangeSetTally(n) {
  const known = typeof n === "number";
  $("tallyChangeSets").textContent = known ? `(${n})` : "";
  $("tallyChangeSetsLabel").textContent = known ? `: ${countOf(n, ["active draft", "active drafts"])}` : "";
}

/* After a draft is started, abandoned or applied in its editor: the index is
   not on screen, so the count is asked for on its own. */
async function refreshChangeSetTally() {
  if (!state.open) return;
  try {
    const data = await call("/api/changesets/list", {});
    renderChangeSetTally(data.drafts.filter(isActiveDraft).length);
  } catch (err) { /* the count stays as it was; the index shows the error */ }
}

function show(view) {
  /* Work that belongs to one area never follows the person to another:
     leaving Agent Proposals closes Import Agent Proposal and any expanded
     review, and leaving Create
     candidate discards its whole upload and conversion; arriving there from
     elsewhere always starts fresh. */
  const from = currentView;
  if (from === "proposals" && view !== "proposals") { discardImport(); collapseProposalReview(); }
  if (from === "intake" && view !== "intake") discardIntake();
  if (view === "intake" && from !== "intake") resetIntake();
  currentView = view;
  VIEWS.forEach((name) => {
    $("view-" + name).hidden = name !== view;
  });
  /* The current item says so to assistive technology; a view with no item of
     its own (Create candidate) marks the one it is started from. */
  const items = Array.from(document.querySelectorAll("#nav button"));
  const owner = VIEW_OWNER[view];
  items.forEach((b) => {
    b.setAttribute("aria-current", String(b.dataset.view === view || b.dataset.view === owner));
    b.classList.toggle("ancestor", b.dataset.view === owner);
  });
  if (ROUTED_VIEWS.indexOf(view) !== -1 && hasHistory() && viewFromAddress() !== view && history.replaceState) {
    history.replaceState(null, "", "#" + view);
  }
  const heading = $("view-" + view).querySelector("h2");
  if (heading) document.title = `${heading.getAttribute("data-title") || heading.textContent} — Charter`;
}

/* Opening an Agent Context first rolls back an interrupted Charter
   write. What that did is said once. */
function announceRecovery() {
  const r = state.recovered;
  if (!r) return;
  if (r.problem) { toast(r.problem, true); return; }
  if ((r.unrestored || []).length) {
    toast("An interrupted Charter write was rolled back, except "
      + `${r.unrestored.join(", ")}: changed meanwhile, so left as it is.`, true);
    return;
  }
  toast("An interrupted Charter write was found and rolled back. Nothing else changed.");
}

/* `text` in `node`, breakable after each `/`, `\\`, `_` and `.` — the places a
   branch, folder or file name reads naturally split; a hyphen already is. CSS
   breaks a run with none of them only as a last resort, so a long value stays
   inside a narrow column without being cut at arbitrary letters. */
function breakable(node, text) {
  node.textContent = "";
  let run = "";
  for (const ch of String(text)) {
    run += ch;
    if ("/\\_.".includes(ch)) {
      node.appendChild(document.createTextNode(run));
      node.appendChild(el("wbr"));
      run = "";
    }
  }
  if (run) node.appendChild(document.createTextNode(run));
  return node;
}

/* The open Agent Context's folder name, as the server derives it. A page newer
   than the console serving it — Charter updated in its folder while the
   console ran — gets none, so it takes the last part of the path itself,
   never showing a blank, "undefined" or the full path. */
function contextFolderName() {
  if (state.folder_name) return state.folder_name;
  const parts = String(state.root || "").split(/[\\/]+/).filter(Boolean);
  return parts.length ? parts[parts.length - 1] : String(state.root || "");
}

function renderShell() {
  const open = state.open;
  const s = open ? state.status : null;
  $("projectName").textContent = open ? state.project_name : "no Agent Context open";
  /* Named by its folder's name, never its full path (UI Standards): the exact
     path is in Diagnostics, Open Agent Context… and copy-ready commands. */
  breakable($("metaRoot"), open ? contextFolderName() : "—");
  $("metaAgents").textContent = open ? (s.agents_served ? "Ready" : "Unavailable") : "—";
  const groups = open ? documentGroups() : null;
  $("metaContext").textContent = open ? String(groups.governing.length) : "—";
  $("metaPdf").textContent = open && !state.pdf_support
    ? "Adding PDF documents is unavailable: install pypdf to enable it." : "";
  renderGit();
  CONTEXT_LISTS.forEach(({ key, tally, noun }) => {
    const n = open ? groups[key].length : 0;
    $(tally).textContent = open ? `(${n})` : "";
    $(tally + "Label").textContent = open ? `: ${countOf(n, noun)}` : "";
  });
  renderTally();
  renderChangeSetTally(open ? state.change_sets.active : null);

  const barPath = $("barPath");
  barPath.textContent = "";
  if (open) {
    barPath.appendChild(el("span", { class: "bar-name", id: "barName", text: state.project_name }));
    barPath.appendChild(document.createTextNode(" · "));
    breakable(barPath.appendChild(el("span", { class: "path", id: "barFolder" })), contextFolderName());
  } else {
    barPath.textContent = "No Agent Context open";
  }
  const bar = $("barState");
  bar.textContent = "";
  /* One context status label, always: ready, or unavailable with the problem
     and next safe step named in the status above every view. */
  if (open) bar.appendChild(s.agents_served ? chip("Agent context ready", "ok") : chip("Agent context unavailable", "stale"));
  renderCommand();
  $("btnSwitch").hidden = !open;
  syncStartForms(!!state.folder_picker);
  renderContextStatus();
}

/* The Charter command status, after the context's and independent of it
   (UI Standards): whether the default `charter` command — what a new terminal,
   or an agent running `charter propose`, finds — runs this installation. Needs
   attention is a warning, never the context's problem, and disables nothing;
   it is a button that opens the remedy dialog. */
let commandStatus = null;
let commandOpener = null;

async function loadCommand() {
  try { commandStatus = await call("/api/command"); } catch (err) { commandStatus = null; }
  renderCommand();
}

function renderCommand() {
  const box = $("barCommand");
  box.textContent = "";
  if (!state || !state.open || !commandStatus) return;
  if (commandStatus.state === "ready") { box.appendChild(chip("Charter command ready", "ok")); return; }
  box.appendChild(el("button", { type: "button", class: "chip warn chip-button", id: "btnCommandStatus",
    "aria-haspopup": "dialog", text: "Charter command needs attention",
    onclick: (event) => openCommandDialog(event.currentTarget) }));
  // The explicit action, immediately after the status: the same dialog (UI Standards).
  box.appendChild(el("button", { type: "button", class: "btn ghost small", id: "btnCommandFix",
    "aria-haspopup": "dialog", text: "Fix…", onclick: (event) => openCommandDialog(event.currentTarget) }));
}

/* The remedy, in a focused dialog over the page: which copy the `charter`
   command finds, or that it finds none; what that means for a new terminal
   and `charter propose`; that agents connected by full path are unaffected;
   and one copy-ready command that runs this copy by its full paths. */
async function openCommandDialog(opener) {
  await loadCommand();  // what PATH holds now, not when the page loaded
  const c = commandStatus;
  if (!c || c.state === "ready") {
    if (c) toast("The charter command runs this copy of Charter now.");
    return;
  }
  commandOpener = opener && opener.id ? opener.id : null;
  const other = c.state === "other";
  const code = (text) => el("code", { text });
  const words = (text) => document.createTextNode(text);
  const where = c.changes_path ? `In ${c.shell}, put this copy on your PATH:`
    : "In a terminal, run this; it says what to add to your shell startup file:";
  const close = el("button", { class: "btn ghost small close", text: "Close", onclick: closeCommandDialog });
  const viewer = $("docViewer");
  viewer.textContent = "";
  viewer.appendChild(el("article", { class: "reader command-dialog", role: "dialog", "aria-modal": "true",
    "aria-labelledby": "commandTitle", id: "commandDialog" }, [
    el("header", {}, [el("div", { class: "reader-heading" }, [
      el("h3", { id: "commandTitle", text: "Charter Command Needs Attention" })]), close]),
    el("div", { class: "reader-body" }, [
      el("p", { id: "commandFound" }, other
        ? [words("The "), code("charter"), words(" command runs another copy of Charter, from "), code(c.other_folder), words(".")]
        : [words("The "), code("charter"), words(" command is not found on PATH.")]),
      el("p", { id: "commandImpact" }, [words("A new terminal, or an agent that runs "), code("charter propose"),
        words(other ? " in this folder, would use that copy, not the one managing this Agent Context."
          : " in this folder, cannot run Charter.")]),
      el("p", { id: "commandSafe" }, withCode("Agents set up through Connect Agents run this copy by its full path, so they are unaffected.")),
      el("p", { id: "commandStep" }, other
        ? [words("Remove "), code(c.other_folder), words(" from your PATH. Then: " + where[0].toLowerCase() + where.slice(1))]
        : [words(where)]),
      copyBlock("commandRemedy", "", c.remedy, "Copy command", ""),
      el("p", { id: "commandAfter" }, withCode("Afterwards, open a new terminal, and restart any agent host whose agents run `charter propose`.")),
    ]),
  ]));
  viewer.hidden = false;
  setBackgroundInert(true);
  close.focus();
}

function closeCommandDialog() {
  const opener = commandOpener;
  commandOpener = null;
  $("docViewer").textContent = "";
  $("docViewer").hidden = true;
  setBackgroundInert(false);
  // Opening re-renders the status, so the control that opened it is found
  // again by its id: the status, or Fix….
  const back = (opener && $(opener)) || $("btnCommandStatus");
  if (back && back.focus) back.focus();
}

const commandDialogOpen = () => !!$("commandDialog");

/* Git is the person's own and secondary: a compact, read-only summary in the
   sidebar — the branch, and the count of context files Git reports as
   changed — with no control that lists the files. A Git failure is said as
   one, never shown as no changes. */
const GIT_BRANCH_NOTE = { "not-checkout": "Not a Git checkout", unavailable: "Git unavailable" };
const UNREAD = "Could not be read";

function renderGit() {
  const git = state.open ? state.status.git : null;
  const known = !!git && git.state === "checkout";
  const counted = known || (!!git && git.state === "unreadable");
  $("metaGitLabel").hidden = $("metaBranch").hidden = !git;
  $("metaChangedLabel").hidden = $("metaChanged").hidden = !counted;
  const changed = known ? git.changed : [];
  if (!git) return;
  breakable($("metaBranch"), GIT_BRANCH_NOTE[git.state] || git.branch || UNREAD);
  $("metaChangedCount").textContent = known ? String(changed.length) : UNREAD;
}

/* Above every view, while it matters: whether agents are served, what is wrong
   and the next safe step, whether the content changed outside Charter, and
   private state Charter's earlier name left on this computer. */
function renderContextStatus() {
  const box = $("contextStatus");
  box.textContent = "";
  if (!state.open) { box.hidden = true; return; }
  const s = state.status;
  const parts = [];
  if (!s.agents_served) {
    const card = el("section", { class: "status-card refused", id: "refusedCard" }, [
      el("h3", {}, withCode(s.headline_title || s.headline)),
      s.headline_detail ? el("p", { class: "status-detail", id: "refusedDetail" }, withCode(s.headline_detail)) : null,
    ]);
    const errors = s.issues.filter((i) => i.level === "error");
    const attention = errors.filter((i) => i.kind === "integrity");
    if (attention.length) card.appendChild(attentionList(attention, s));
    const others = errors.filter((i) => i.kind !== "integrity");
    if (others.length) {
      const list = el("ul", { class: "issues" });
      // A file that does not belong: its name first, in bold, then what to do.
      others.forEach((i) => list.appendChild(i.kind === "stray" && i.path
        ? el("li", { class: "error stray-item" }, [el("strong", { text: i.path }),
          document.createTextNode(` ${i.message}${i.fix ? " " + i.fix : ""}`)])
        : issueItem(i)));
      card.appendChild(list);
    }
    if (s.strays.length) {
      card.appendChild(el("p", { class: "hint", id: "straysNote", text: "Charter never moves "
        + "or deletes files it did not create. After resolving the files listed above, choose any "
        + "navigation item to check the folder again." }));
    }
    if (s.rebuild.available) {
      card.appendChild(el("div", { class: "actions" }, [el("button", { class: "btn", id: "btnRebuildFromStatus",
        text: "Rebuild Agent Context…", onclick: startRebuild })]));
    } else if (!s.interrupted && !s.needs_review && s.rebuild.blockers.length
               && errors.some((i) => i.kind === "generated")) {
      card.appendChild(el("p", { class: "hint", id: "rebuildBlockedNote", text: "Rebuild Agent Context is offered "
        + "once these are corrected. It never changes or repairs a governing document." }));
    }
    parts.push(card);
  }
  /* "Changed outside Charter" is only the notice for a valid outside change,
     which is still served; an unavailable context lists what does not match. */
  const o = s.outside;
  if (o.changed_outside && s.agents_served) {
    const note = el("section", { class: "status-card outside", id: "outsideNotice" }, [
      el("h3", { text: "Changed Outside Charter" }),
      el("p", {}, withCode(o.message)),
    ]);
    if (o.paths.length) {
      note.appendChild(el("ul", { class: "paths" }, o.paths.map((p) => el("li", {}, [el("code", { text: p })]))));
    }
    if (s.agents_served) {
      note.appendChild(el("div", { class: "actions" }, [el("button", { class: "btn ghost small",
        id: "btnAcknowledge", text: "Mark as seen", onclick: acknowledgeOutside })]));
    }
    parts.push(note);
  }
  /* Unknown origin is provenance, not a warning: Governing documents says it,
     beside the context's status (renderContextMap), and no other view does. */
  const legacy = legacyNotice();
  if (legacy) parts.push(legacy);
  parts.forEach((p) => box.appendChild(p));
  box.hidden = !parts.length;
}

/* Context changes need review (UI Standards): each affected file by its
   logical path with one chip — Does not match approved context, Missing from
   context, Not in approved context, or Cannot verify file — and only what
   Charter observed: the recorded and current hashes, never a file time and
   never who or what made the change. A governing document that does not match
   offers Revise…, which files its current text as a revision candidate; a map
   whose own hash is the sole failure offers Regenerate map…. Nothing here
   accepts, remaps, or makes current the changed text. */
const shortHash = (h) => (h ? h.slice(0, 12) : "");
const OWN_STEP = ["missing", "unrecorded", "unverifiable"];

function attentionList(items, s) {
  const governing = new Map((state.documents || []).filter((d) => d.kind === "governing")
    .map((d) => [d.path, d]));
  const list = el("ul", { class: "issues attention", id: "attentionList", "aria-label": "Files that need review" });
  items.forEach((i) => {
    const facts = [];
    if (i.recorded_sha256) facts.push(`Recorded ${shortHash(i.recorded_sha256)}`);
    if (i.current_sha256) facts.push(`current ${shortHash(i.current_sha256)}`);
    const doc = governing.get(i.path);
    const actions = [];
    if (i.state === "changed" && doc) {
      actions.push(el("button", { class: "btn ghost small", text: "Revise…",
        onclick: () => startRevision(doc) }));
    }
    if (i.path === "AGENT-CONTEXT.md" && s.regenerate && s.regenerate.available) {
      actions.push(el("button", { class: "btn small", id: "btnRegenerateMap", text: "Regenerate map…",
        onclick: startRegenerate }));
    }
    /* The status above already gives the next step for a file that does not
       match; a row adds only what it alone needs to say: restoring a missing
       or unreadable file, or the two routes for one not in the approved
       context. */
    const own = OWN_STEP.includes(i.state) && i.fix ? " " + i.fix : "";
    list.appendChild(el("li", { class: "error attention-item", "data-state": i.state }, [
      el("div", { class: "title-row" }, [el("code", { text: i.path }), chip(i.label, "stale")]),
      el("div", {}, withCode(i.message + own)),
      facts.length ? el("div", { class: "hint attention-facts", text: facts.join(" · ") }) : null,
      actions.length ? el("div", { class: "actions" }, actions) : null,
    ]));
  });
  return list;
}

/* Private state that Agent Context Manager, Charter's earlier name, left on this
   computer: waiting to be taken over, or left beside Charter's own. */
function legacyNotice() {
  const l = state.legacy_state || {};
  if (!l.message) return null;
  return el("p", { class: "note", id: "legacyStateNotice", "data-legacy": l.status }, withCode(l.message));
}

async function acknowledgeOutside(event) {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await call("/api/acknowledge", {});
    await refreshQuiet();
    /* The notice (and its button) are gone; focus the heading of the view the
       person is on, not <body>. */
    focusAfter(currentViewHeading());
    toast("Marked as seen. The change made outside Charter is no longer flagged.");
  } catch (err) { button.disabled = false; toast(err.message, true); }
}

/* -------------------------------------------------------------- documents */

function renderKnowledge() {
  /* Errors are in the status above every view; warnings, such as a governing
     document without a scope, are listed with the documents. */
  const issues = $("knowledgeIssues");
  issues.textContent = "";
  (state.issues || []).filter((i) => i.level === "warning").forEach((i) => issues.appendChild(issueItem(i)));
  renderContextMap();
  const groups = documentGroups();
  CONTEXT_LISTS.forEach(({ key }) => {
    const docs = groups[key];
    const list = $(key + "List");
    list.textContent = "";
    docs.forEach((d) => list.appendChild(docRow(d)));
    list.hidden = !docs.length;  // an empty list holds nothing: its count says so
  });
  Object.entries({ governing: "governingUnavailable", candidates: "candidatesUnavailable" }).forEach(([key, id]) => {
    $(id).textContent = NOT_VALID;
    $(id).hidden = canChangeGoverning() || !groups[key].length;
  });
  const governing = groups.governing.length;
  $("governingGroupLabel").textContent = groupLabel("Governing Documents", governing);
  $("governingGroup").hidden = !governing;
}

/* The shared section break: a group of related records under a compact
   label with its count, named for assistive technology by that label. An
   empty group is not shown at all. */
const groupLabel = (name, n) => `${name} (${n})`;

function recordGroup(id, name, items) {
  const labelId = id + "Label";
  return el("section", { class: "record-group", id, "aria-labelledby": labelId }, [
    el("h3", { class: "record-group-label", id: labelId, text: groupLabel(name, items.length) }),
    el("div", { class: "docs" }, items),
  ]);
}

/* The two lists: the view (and list) each is shown in, its count, and the
   words a screen reader hears for that count. Archived documents — retired
   candidates and replaced versions — stay in private local state and are
   not shown in normal views. */
const CONTEXT_LISTS = [
  { key: "governing", tally: "tallyGoverning", noun: ["governing document", "governing documents"] },
  { key: "candidates", tally: "tallyCandidates", noun: ["authority candidate", "authority candidates"] },
];
const countOf = (n, [one, many]) => `${n} ${n === 1 ? one : many}`;

function documentGroups() {
  const docs = state.documents || [];
  return {
    governing: docs.filter((d) => d.kind === "governing"),
    candidates: docs.filter((d) => d.kind === "candidate"),
  };
}

/* The map's state is claimed only as far as it was checked: while a governing
   document has a problem, the map is not compared at all. */
function renderContextMap() {
  const s = state.status;
  const generated = s.issues.filter((i) => i.level === "error" && i.kind === "generated");
  const box = $("contextMapState");
  box.textContent = "";
  /* Out of date: a generated file is missing, unreadable, or not what Charter
     generates, and Rebuild Agent Context or Regenerate map may correct it.
     Not checked: a governing-document problem stops the comparison, context
     changes that need review among them. Otherwise current — a stray file
     elsewhere does not make the map stale. */
  const blocking = s.issues.filter((i) => i.level === "error" && i.kind !== "generated" && i.kind !== "stray");
  let label;
  if (s.regenerate && s.regenerate.available) label = chip("Map out of date", "stale");
  else if (s.needs_review) label = chip("Map not checked", "warn");
  else if (generated.length) label = chip("Map out of date", "stale");
  else if (blocking.length) label = chip("Map not checked", "warn");
  else label = chip("Map current", "ok");
  box.appendChild(label);
  $("contextMapDetail").textContent = "";
  /* Unknown origin, said plainly: no repair is implied. "Valid" is claimed only
     while agents are served; recovery, if needed, is the status above. */
  const origin = $("originUnknown");
  origin.textContent = "";
  origin.hidden = !!s.outside.known;
  if (!s.outside.known) {
    origin.appendChild(el("strong", { text: "Origin unknown." }));
    origin.appendChild(document.createTextNode(s.agents_served
      ? " These files are valid, but Charter has no local record of how this version was created or changed."
      : " Charter has no local record of how this version was created or changed."));
  }
  $("btnRebuildContext").hidden = !s.rebuild.available;
  $("btnViewContext").disabled = s.issues.some((i) => i.path === "AGENT-CONTEXT.md"
    && i.level === "error" && /no `AGENT-CONTEXT.md`|could not be read|not UTF-8/.test(i.message));
}

/* A governing change needs a valid, clean Agent Context to start from. */
const canChangeGoverning = () => state.status.agents_served;
const NOT_VALID = "Change-set actions are unavailable until the Agent Context is valid and clean: "
  + "see the status above.";
/* The one visible line, above each list, saying why its change-set actions are
   disabled; each disabled action is described by it. */
const UNAVAILABLE_NOTE = { governing: "governingUnavailable", candidate: "candidatesUnavailable" };

/* A candidate's one compact source tag. An identity is named only when Charter
   knows it — an Agent Proposal's self-reported agent name — and never invented. */
const SOURCE_LABEL = { proposal: "Agent Proposal", create: "Created by person", revise: "Revision",
  withdrawn: "Withdrawn governing document" };
const sourceTag = (c) => (c.source_kind === "proposal" && c.source_agent
  ? `Proposed by: ${c.source_agent}` : SOURCE_LABEL[c.source_kind] || "");

function competingNotice(co) {
  /* "with a count when more than one other candidate exists." */
  return "Another revision candidate exists for this document." + (co > 1 ? ` ${co} others in all.` : "");
}

/* The one attention state of a governing document whose file needs review. */
const attentionOf = (path) => ((state.status && state.status.issues) || [])
  .find((i) => i.kind === "integrity" && i.path === path) || null;

function docRow(doc) {
  const isCandidate = doc.kind === "candidate";
  const tag = isCandidate ? sourceTag(doc) : "";
  const labelled = (cls, label, text) => el("div", { class: cls + " labelled" }, [el("strong", { text: label + " " }),
    el("span", { text })]);
  const meta = el("div", {}, [
    /* A candidate leads with its title and, immediately after it, one compact
       source tag; its filename and scope follow, labelled. */
    isCandidate
      ? el("div", { class: "title-row" }, [el("span", { class: "title", text: doc.title }),
        tag ? el("span", { class: "source-tag", text: tag }) : null])
      : attentionOf(doc.path)
        ? el("div", { class: "title-row" }, [el("span", { class: "title", text: doc.title }),
          chip(attentionOf(doc.path).label, "stale")])
        : el("div", { class: "title", text: doc.title }),
    labelled("path", "Filename:", doc.path),
    doc.scope ? labelled("scope", "Scope:", doc.scope) : null,
    /* Human-only candidate lineage: which governing document a revision revises,
       and where the candidate came from. Private local state (never agent-facing). */
    isCandidate && doc.revises_title
      ? el("div", { class: "origin lineage", text: "Revision of: " + doc.revises_title }) : null,
    /* Made from an earlier version: applying it would undo what changed since. */
    isCandidate && doc.revises_title && doc.revises_current === false
      ? el("div", { class: "origin lineage-earlier", text: doc.revises_path
        ? "Made from an earlier version of this document, which has changed since. Applying it as "
          + "it is would undo those changes: compare it with the governing document first."
        : "The document it revises no longer governs." }) : null,
    isCandidate && doc.co_revisions > 0
      ? el("div", { class: "origin competing", text: competingNotice(doc.co_revisions) }) : null,
  ]);
  const governingAction = (text, cls, onclick) => el("button", { class: cls, text, onclick,
    disabled: canChangeGoverning() ? null : "",
    "aria-describedby": canChangeGoverning() ? null : UNAVAILABLE_NOTE[doc.kind] });
  const actions = el("div", { class: "actions" }, [
    el("button", { class: "btn ghost small", text: "Read",
      onclick: (event) => openDocument(doc.path, event.currentTarget) }),
    doc.kind === "candidate" ? el("button", { class: "btn ghost small", text: "Edit…",
      onclick: () => startCandidateEdit(doc) }) : null,
    isCandidate && doc.revises_path ? el("button", { class: "btn ghost small", text: "Compare with governing…",
      onclick: (event) => openComparison(doc.path, [doc.revises_path],
        `Compare “${doc.title}” with the Governing Document It Revises`, event.currentTarget) }) : null,
    isCandidate && doc.co_revisions > 0 ? el("button", { class: "btn ghost small", text: "Compare revisions…",
      onclick: (event) => openComparison(doc.path,
        (state.documents || []).filter((d) => d.kind === "candidate"
          && d.revises_path === doc.revises_path && d.path !== doc.path).map((d) => d.path),
        `Compare “${doc.title}” with Competing Revision Candidates`, event.currentTarget) }) : null,
    doc.kind === "governing" ? el("button", { class: "btn ghost small", text: "Revise…",
      onclick: () => startRevision(doc) }) : null,
    doc.kind === "candidate" ? el("button", { class: "btn ghost small", text: "Retire…",
      onclick: () => startRetirement(doc) }) : null,
    doc.kind === "governing" ? governingAction("Withdraw in a change set…", "btn ghost small",
      () => startWithdrawal(doc)) : null,
    doc.kind === "candidate" ? governingAction("Plan a change set…", "btn small primary-action",
      () => startCandidateChangeSet(doc)) : null,
  ]);
  return el("div", {
    class: "doc" + (doc.governing ? " is-authority" : ""),
  }, [meta, actions]);
}

/* --------------------------------------------------------- Markdown viewer */

/* One viewer for every Markdown the page shows as a document: a document in
   any folder, the context map, and a file as a plan would leave it — Intake,
   a governance act, or an agent proposal if accepted. It asks the server for
   what to show, never a path to open: a document by the exact path Knowledge
   lists, the context map by name, a plan's file by plan. The server answers
   with the text and a banner saying what it is, and refuses anything else.

   It lies over the page rather than replacing any of it, so closing it leaves
   the view it was opened from exactly as it was — a half-filled form, an open
   diff, a scroll position — and puts focus back on the button that opened it.
   It is read-only: nothing here writes, plans or records. */
const BANNER_TONE = { governing: "note authority", mismatch: "note warn" };

async function openPreview(source, opener) {
  try {
    const data = await call("/api/preview", source);
    reading = { source, data, opener: opener || null };
    readerMode = "rendered";
    renderReader();
  } catch (err) { toast(err.message, true); }
}

const openDocument = (path, opener) => openPreview({ source: "document", path }, opener);

/* A human-only comparison, over the page like the reader: a candidate against
   the governing document it revises, or against competing candidates. Reuses the
   diff viewer; console-only, so no agent ever sees it. */
let comparing = false;

async function openComparison(candidatePath, againsts, label, opener) {
  const list = (againsts || []).filter(Boolean);
  if (!list.length) return;
  const sections = [];
  try {
    for (const against of list) sections.push(await call("/api/candidate/compare",
      { candidate: candidatePath, against }));
  } catch (err) { toast(err.message, true); return; }
  comparing = true;
  comparisonOpener = opener || null;
  const viewer = $("docViewer");
  viewer.textContent = "";
  const close = el("button", { class: "btn ghost small close", text: "Close", onclick: closeComparison });
  const inner = el("div", { class: "reader-body" });
  sections.forEach((s) => {
    inner.appendChild(el("h4", { class: "cmp-head",
      text: `“${s.left.title}” Compared with “${s.right.title}”` }));
    inner.appendChild(renderDiff(s.diff));
  });
  viewer.appendChild(el("article", { class: "reader", role: "dialog", "aria-modal": "true",
    "aria-labelledby": "cmpTitle" }, [
    el("header", {}, [el("div", { class: "reader-heading" }, [el("h3", { id: "cmpTitle", text: label })]), close]),
    inner,
  ]));
  viewer.hidden = false;
  setBackgroundInert(true);
  close.focus();
}

let comparisonOpener = null;

function closeComparison() {
  const opener = comparisonOpener;
  comparing = false;
  comparisonOpener = null;
  $("docViewer").textContent = "";
  $("docViewer").hidden = true;
  setBackgroundInert(false);
  if (opener && opener.focus) opener.focus();
}

/* Reading is a view, not a state the utility holds on your behalf. Leaving a
   view, or coming back to it, closes whatever was open. */
function closeDocument() {
  const opener = reading ? reading.opener : null;
  reading = null;
  $("docViewer").textContent = "";
  $("docViewer").hidden = true;
  setBackgroundInert(false);  // release the focus trap
  if (opener && opener.focus) opener.focus();
}

function renderReader() {
  const viewer = $("docViewer");
  viewer.textContent = "";
  if (!reading) { viewer.hidden = true; return; }

  const { data } = reading;
  const { meta, body } = CharterMarkdown.splitFrontMatter(data.text);
  const rendered = readerMode === "rendered";
  const close = el("button", { class: "btn ghost small close", text: "Close", onclick: closeDocument });
  const article = el("article", { class: "reader", role: "dialog", "aria-modal": "true",
    "aria-labelledby": "readerTitle", "data-state": data.state }, [
    el("header", {}, [
      el("div", { class: "reader-heading" }, [
        el("h3", { id: "readerTitle", text: data.title }),
        el("div", { class: "reader-path", text: data.path }),
      ]),
      el("button", {
        class: "btn ghost small",
        text: rendered ? "View source" : "View rendered",
        onclick: () => { readerMode = rendered ? "source" : "rendered"; renderReader(); },
      }),
      close,
    ]),
    el("div", { class: "reader-banner " + (BANNER_TONE[data.state] || "note") }, [
      el("strong", { text: data.banner.title }),
      el("span", { text: data.banner.text }),
      data.after ? el("span", { class: "after", text: data.after }) : null,
    ]),
  ]);

  const inner = el("div", { class: "reader-body" });
  if (rendered) {
    if (meta) inner.appendChild(CharterMarkdown.renderMeta(meta));
    const prose = el("div", { class: "md" });
    prose.appendChild(CharterMarkdown.render(body));
    inner.appendChild(prose);
  } else {
    inner.appendChild(el("pre", { class: "code", text: data.text }));
  }
  article.appendChild(inner);
  viewer.appendChild(article);
  viewer.hidden = false;
  setBackgroundInert(true);  // trap focus in the dialog: the rail and main are inert
  close.focus();
}

/* While a modal surface (the reader) is open, the rail and main content are
   inert, so Tab and a screen reader stay within the dialog. */
function setBackgroundInert(on) {
  for (const sel of [".skip-link", ".rail", "#main"]) {
    const node = document.querySelector(sel);
    if (node) setInert(node, on);
  }
}

/* The viewer must never show text as it was before a change was applied. It
   asks again; whatever can no longer be shown honestly — a plan that moved
   on, a document that went — closes rather than showing what was. */
async function reloadReader() {
  if (!reading) return;
  const { source } = reading;
  try {
    const data = await call("/api/preview", source);
    if (reading && reading.source === source) { reading.data = data; renderReader(); }
  } catch (err) { closeDocument(); }
}

$("docViewer").addEventListener("click", (event) => {
  if (event.target !== $("docViewer")) return;  // the backdrop, not the page
  if (commandDialogOpen()) closeCommandDialog();
  else if (comparing) closeComparison(); else closeDocument();
});
if (document.addEventListener) {
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (commandDialogOpen()) closeCommandDialog();
    else if (reading) closeDocument();
    else if (comparing) closeComparison();  // a comparison overlay is open
    else if (panelOpener) closePanel();  // a form/preview panel is open
  });
}

/* ------------------------------------------------------- governance acts */

async function draftOf(path) {
  try { return await call("/api/draft", { path }); } catch (err) { toast(err.message, true); return null; }
}

/* Edit a candidate: its title, scope and text. It is not context before or
   after, so this never changes what governs. */
async function startCandidateEdit(doc, options = {}) {
  const draft = await draftOf(doc.path);
  if (!draft) return;
  review = null;
  /* An older candidate may still carry front matter at the top of its text.
     It is left out of this form, and saying so here is not saving: the
     candidate changes only if the person saves, after a preview whose diff
     shows the removal. */
  const legacy = draft.legacy_front_matter;
  const lead = legacy ? el("div", { class: "note", id: "legacyFrontMatterNote", role: "status" }, [
    el("strong", { text: "Old front matter was removed from the text for this edit." }),
    el("div", { text: `It held ${legacy.keys.join(", ")}. The candidate is unchanged unless you save; the preview `
      + "shows the removal before you confirm. Its title and scope are set in their own fields below." }),
  ]) : null;
  formPanel(
    `Edit “${draft.title}”`,
    { text: "An authority candidate — not context — before and after. Editing it changes nothing "
        + "agents read.", tone: "note" },
    [
      { name: "title", label: "Title", value: draft.title },
      { name: "scope", label: SCOPE_LABEL, value: draft.scope, hint: SCOPE_HINT },
      { name: "body", label: "Text", type: "textarea", rows: 18, value: draft.body },
    ],
    "Preview the change",
    (values) => planFor("edit-candidate",
      { candidate: doc.path, title: values.title, scope: values.scope, body: values.body },
      { applyLabel: "Save candidate", returnTo: options.returnTo || null }),
    lead,
    /* Opened from a change set's Edit details, Cancel leaves the person in
       that change set, whose controls this does not change. */
    options.returnTo ? null : backToCandidates,
  );
}

/* Leaving an unfinished candidate form: back to Authority candidates, with
   focus on its heading rather than lost with the form. */
async function backToCandidates() {
  if (currentView !== "candidates") await navigate("candidates");
  focusCandidatesHeading();
}

function focusCandidatesHeading() {
  const heading = $("view-candidates").querySelector("h2");
  heading.setAttribute("tabindex", "-1");
  if (heading.focus) heading.focus();
}

/* A governing document is never edited in place. Revise files a new authority
   candidate starting from its current title, scope and text; the document
   keeps governing, unchanged, until the person revises it with the candidate
   in a change set. */
async function startRevision(doc) {
  const draft = await draftOf(doc.path);
  if (!draft) return;
  const lead = el("div", { class: "note authority", id: "reviseNotice" }, [
    el("strong", { text: "Filing creates a new authority candidate — not context." }),
    el("div", { text: `“${draft.title}” keeps governing at ${draft.path}, unchanged, until a change set `
      + "you apply replaces it with the candidate." }),
  ]);
  review = null;
  formPanel(
    `Revise “${draft.title}”`,
    null,
    [
      { name: "title", label: "Title", value: draft.title },
      { name: "scope", label: SCOPE_LABEL, value: draft.scope, hint: SCOPE_HINT },
      { name: "body", label: "Text", type: "textarea", rows: 18, value: draft.body },
    ],
    "Preview the candidate",
    (values) => planFor("revise",
      { path: draft.path, title: values.title, scope: values.scope, body: values.body },
      { applyLabel: "File as candidate" }),
    lead,
  );
}

/* Every change to what governs is a change set. Starting from one candidate
   opens a new change set that includes it, its decision not yet made;
   starting from a governing document's Withdraw in a change set… opens one
   that withdraws it — nothing more. Every other governing document is
   retained without a decision, and related candidates and withdrawals can be
   added before its preview. Nothing starts chosen: a candidate made with
   Revise… lists the document it was revised from first among replacement
   targets, labelled, as context only — never selected for the person. */
async function startChangeSet(start) {
  let made;
  try { made = await call("/api/changeset/create", { start }); }
  catch (err) { toast(err.message, true); return null; }
  $("review").textContent = "";
  review = null;
  showChangeSet(made);
  return made;
}

const REVISED_FROM = "the document this was revised from";

/* From a candidate: a new change set that includes it, its decision not yet
   made — Replace, with the governing document the person selects, or Govern
   alongside, chosen in the change set itself. */
function startCandidateChangeSet(doc) {
  return startChangeSet({ candidate: doc.path });
}

/* Withdrawing is chosen on the governing document itself: the change set
   opens with that one withdrawal, and is previewed and confirmed there. */
function startWithdrawal(doc) {
  return startChangeSet({ withdraw: doc.path });
}

function startRetirement(doc) {
  planFor("retire", { candidate: doc.path }, { applyLabel: "Retire" });
}

/* ------------------------------------------------------------------ intake */

/* Create candidate asks only for a title and a scope: every document is filed as
   a candidate, under a name the server picks. */
function renderIntakeForm() {
  /* The drop target, the file picker and the hint offer PDF only while it can be converted. */
  $("dropText").textContent = state.pdf_support
    ? "Drop a PDF, Word document, Markdown or text file here"
    : "Drop a Word document, Markdown or text file here";
  $("file").setAttribute("accept", (state.pdf_support ? ".pdf," : "") + ".docx,.md,.markdown,.txt,.text");
  $("dropHint").textContent = state.pdf_support
    ? "PDF, DOCX, Markdown and plain text."
    : "DOCX, Markdown and plain text. PDF needs the optional pypdf package.";
}

/* Progressive disclosure: until a chosen file is converted, only choosing a
   file is shown. Then one form, laid out like Edit…, takes its place:
   Review Converted Document, with the file, its notes, Title, Scope and Text. */
function unlockIntake(done) {
  $("stepFile").hidden = done;
  $("stepConvert").hidden = !done;
}

/* Each file chosen starts a new read and conversion. Choosing another file,
   cancelling, filing, or another Agent Context opening makes any still in
   flight obsolete: when it answers late, it is dropped, never shown in the form. */
let intakeSeq = 0;
let intakeReader = null;

function abandonIntakeWork() {
  intakeSeq++;
  if (intakeReader && intakeReader.readyState === 1 && intakeReader.abort) intakeReader.abort();
  intakeReader = null;
}

async function stageFile(file) {
  abandonIntakeWork();
  clearConversion();  // another file replaces the conversion and everything derived from it
  const seq = intakeSeq;
  const root = state.root;
  const current = () => seq === intakeSeq && state.root === root;
  const reader = new FileReader();
  intakeReader = reader;
  reader.onload = async () => {
    if (!current()) return;
    const b64 = String(reader.result).split(",")[1];
    try {
      const answer = await call("/api/intake/stage", { filename: file.name, content_b64: b64 });
      if (!current()) return;
      staged = answer;
      $("stagedInfo").textContent = "";
      $("stagedInfo").textContent = `${staged.filename} — ${staged.kind}, ${(staged.bytes / 1024).toFixed(1)} kB`;
      $("convertNotes").textContent = "";
      staged.notes.forEach((n) => $("convertNotes").appendChild(el("div", { class: "note" }, withCode(n))));
      $("markdown").value = staged.markdown;
      $("title").value = staged.suggested_title;
      $("scope").value = staged.suggested_scope || "";
      showFrontMatterNote(staged.front_matter);
      unlockIntake(true);
      $("stepConvert").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) { if (current()) toast(err.message, true); }
  };
  reader.readAsDataURL(file);
}

/* A file's own front matter is removed from the text it becomes. Its title
   and scope, when it gave usable ones, are only suggestions in fields the
   person can change; nothing else it said is carried over. */
function showFrontMatterNote(front) {
  const note = $("frontMatterNote");
  note.textContent = "";
  note.hidden = !front;
  if (!front) return;
  const used = front.used || [];
  note.appendChild(el("strong", { text: "The file's front matter was removed from the text." }));
  note.appendChild(el("div", { id: "frontMatterUsed", text: used.length
    ? (used.length > 1 ? `Its ${used.join(" and ")} are filled in below as suggestions: change them as you wish.`
      : `Its ${used[0]} is filled in below as a suggestion: change it as you wish.`)
    : "It had no usable one-line title or scope, so nothing was filled in from it." }));
  if ((front.dropped || []).length) {
    note.appendChild(el("div", { id: "frontMatterDropped",
      text: `Not carried over: ${front.dropped.join(", ")}. Charter assigns a candidate's `
        + "identity, status and dates itself." }));
  }
}

function intakeRequest() {
  return {
    title: $("title").value.trim(),
    scope: $("scope").value.trim(),
    body: $("markdown").value,
    source: staged ? `${staged.filename} (sha256 ${staged.sha256.slice(0, 12)})` : "",
  };
}

/* --------------------------------------------------------- Agent Proposals */

/* Untrusted requests for a person's review. Accepting one only files,
   updates or retires an authority candidate, after a preview; either decision
   removes it, and nothing about it is kept. An agent's name, reason and
   expected impact are its claims. */
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
let proposalData = null;

async function renderAgentProposals() {
  if (!state.open) return;
  try { proposalData = await call("/api/proposals", {}); } catch (err) { toast(err.message, true); return; }
  if (!proposalData || !Array.isArray(proposalData.pending) || !Array.isArray(proposalData.imported)
      || !Array.isArray(proposalData.unexpected)) {
    /* One malformed record must never blank the whole screen. */
    toast("The Agent Proposals could not be read.", true);
    return;
  }
  collapseProposalReview();  // a fresh list: any expanded review is closed
  const pending = $("pendingProposals");
  pending.textContent = "";
  proposalData.pending.forEach((p) => pending.appendChild(proposalCard(p)));
  const imported = $("importedProposals");
  imported.textContent = "";
  proposalData.imported.forEach((p) => imported.appendChild(proposalCard(p)));
  $("proposalsImportedGroup").hidden = !proposalData.imported.length;
  const odd = $("unexpectedRecords");
  odd.textContent = "";
  proposalData.unexpected.forEach((u) => odd.appendChild(unexpectedRow(u)));
  $("proposalsUnexpectedGroup").hidden = !proposalData.unexpected.length;
}

/* A proposal leads with the friendly title of the document it concerns — that
   document's current title, or the title a create supplies, else its body's
   first heading — with no operation word, and only when there is no title,
   its logical path, labelled as one. One metadata line says who submitted it
   and when it arrived; internal p-… identifiers are never shown. In the list
   a card stays compact: that identity, the metadata line and a one-line
   purpose. Review proposal… expands the same card in place. */
const PATH_TITLE_LABEL = "Logical path — no title found";
const proposalKind = (p) => p.title_kind || (p.title ? "current" : "path");
const proposalTitle = (p) => p.title || p.target_path;

function proposalHeading(p, id, level) {
  return el(level, { class: "proposal-title", id }, [
    proposalKind(p) === "path" ? el("code", { class: "proposal-target", text: proposalTitle(p) })
      : el("span", { text: proposalTitle(p) }),
  ]);
}

function proposalMeta(p) {
  const who = (p.agent || "an unnamed agent") + (p.source === "imported" ? ", imported by you" : "");
  return el("div", { class: "proposal-meta" }, [
    el("strong", { text: "Submitted by:" }), document.createTextNode(` ${who} · `),
    el("strong", { text: "Received:" }), document.createTextNode(` ${relativeTime(p.received)}`),
  ]);
}

/* The DOM id fragment for a proposal: its record, never shown as text. */
const proposalKey = (p) => String(p.proposal_id).replace(/[^\w-]/g, "_");

function proposalCard(p) {
  const key = proposalKey(p);
  const kind = proposalKind(p);
  const card = el("article", { class: "proposal" + (p.stale ? " is-stale" : ""), "data-id": p.proposal_id,
    "aria-labelledby": `proposalTitle-${key}` });
  const open = el("button", { class: "btn small proposal-open", text: "Review proposal…",
    "aria-describedby": `proposalTitle-${key}`, "aria-expanded": "false", "aria-controls": `proposalDetail-${key}`,
    onclick: () => openProposalReview(p, card) });
  /* Rejecting needs no review: the compact card asks for one confirmation inline. */
  const reject = el("button", { class: "btn ghost small proposal-reject-open", id: `proposalReject-${key}`,
    text: "Reject proposal", "aria-describedby": `proposalTitle-${key}`, "aria-controls": `proposalDetail-${key}`,
    onclick: () => openCardRejection(p, card) });
  [
    el("header", {}, [
      proposalHeading(p, `proposalTitle-${key}`, "h4"),
      kind === "path" ? chip(PATH_TITLE_LABEL, null) : null,
      p.stale ? chip("Stale", "stale") : null,
    ]),
    proposalMeta(p),
    el("p", { class: "proposal-reason proposal-reason-preview", id: `proposalReason-${key}` }, [
      el("strong", { text: "Purpose: " }), el("span", { text: p.reason })]),
    el("div", { class: "actions proposal-open-row" }, [open, reject]),
    el("div", { class: "proposal-detail", id: `proposalDetail-${key}`, role: "region",
      "aria-labelledby": `proposalTitle-${key}`, hidden: "" }),
  ].forEach((n) => card.appendChild(n));
  return card;
}

/* The one expanded review, and a counter that makes any answer still on its
   way for an earlier review obsolete. */
let proposalReview = null;  // { card, p }: the one card being reviewed or rejected
let proposalReviewSeq = 0;

/* Close the expanded review or the card's own rejection: the card is compact
   again and everything prepared — its preview, a rejection being confirmed,
   an answer still on its way — is discarded. */
function collapseProposalReview() {
  proposalReviewSeq++;
  const open = proposalReview;
  proposalReview = null;
  if (!open) return;
  const { card } = open;
  card.classList.remove("is-expanded");
  card.classList.remove("is-rejecting");
  const detail = card.querySelector(".proposal-detail");
  if (detail) { detail.textContent = ""; detail.hidden = true; }
  const button = card.querySelector(".proposal-open");
  if (button) button.setAttribute("aria-expanded", "false");
  const row = card.querySelector(".proposal-open-row");
  if (row) row.hidden = false;
}

/* Reject proposal, straight from the compact card: no review opens. The card
   asks for one confirmation in place; Reject removes the proposal, and Cancel
   leaves the card as it was. */
function openCardRejection(p, card) {
  collapseProposalReview();
  const seq = proposalReviewSeq;
  proposalReview = { card, p };
  card.classList.add("is-rejecting");
  card.querySelector(".proposal-open-row").hidden = true;
  const detail = card.querySelector(".proposal-detail");
  detail.textContent = "";
  detail.hidden = false;
  detail.appendChild(el("div", { class: "proposal-reject-slot" }));
  const back = card.querySelector(".proposal-reject-open");
  startProposalRejection(p, detail, seq, () => { collapseProposalReview(); if (back && back.focus) back.focus(); });
}

/* Review proposal…: the same card, expanded in place, is the one complete
   review surface. Its heading, metadata line and Purpose — now shown in full —
   stay the only summary. Before either decision it adds what accepting would
   write: each changed file, with Read for the candidate as it would be. Accept
   as candidate applies exactly that preview, with no later screen or second
   Accept. The agent's expected context impact stays private advisory review
   material, never shown here. */
function openProposalReview(p, card) {
  collapseProposalReview();
  const seq = proposalReviewSeq;
  proposalReview = { card, p };
  card.classList.add("is-expanded");
  const button = card.querySelector(".proposal-open");
  button.setAttribute("aria-expanded", "true");
  card.querySelector(".proposal-open-row").hidden = true;
  const detail = card.querySelector(".proposal-detail");
  detail.textContent = "";
  detail.hidden = false;
  const change = el("div", { class: "proposal-change" },
    p.stale ? [] : [el("p", { class: "hint", text: "Preparing the preview…" })]);
  const accept = el("button", { class: "btn", id: "btnAcceptProposal", text: "Accept as candidate", disabled: "" });
  const decisions = el("div", { class: "actions proposal-decisions" }, [
    accept,
    el("button", { class: "btn ghost", id: "btnRejectProposal", text: "Reject proposal",
      onclick: () => startProposalRejection(p, detail, seq) }),
    el("button", { class: "btn ghost", id: "btnCloseProposalReview", text: "Close review",
      onclick: () => { collapseProposalReview(); if (button.focus) button.focus(); } }),
  ]);
  if (p.stale) {
    detail.appendChild(el("div", { class: "note warn", id: "proposalReviewStale", text: p.stale_reasons.join(" ")
      + " It cannot be accepted as written: reject it, or ask the agent to propose again." }));
  }
  detail.appendChild(change);
  detail.appendChild(el("div", { class: "proposal-reject-slot" }));
  detail.appendChild(decisions);
  if (!p.stale) proposalPreview(p, seq, change, accept);
}

/* The accept plan, computed once and shown in the expanded card: each file it
   writes, with Read for the candidate as it would be. Accept applies this
   plan. */
async function proposalPreview(p, seq, change, accept) {
  const request = { proposal_id: p.proposal_id };
  let plan;
  try { plan = await call("/api/plan", { kind: "accept-proposal", request }); }
  catch (err) {
    if (seq !== proposalReviewSeq) return;
    change.textContent = "";
    change.appendChild(el("div", { class: "note error", id: "proposalReviewUnavailable", role: "alert", text: err.message }));
    return;
  }
  if (seq !== proposalReviewSeq) return;
  change.textContent = "";
  const issues = plan.issues || [];
  if (issues.length) change.appendChild(el("ul", { class: "issues", id: "proposalReviewProblems" }, issues.map(issueItem)));
  const readPlanned = (path, opener) => openPreview({ source: "plan", kind: "accept-proposal", request,
    plan_id: plan.plan_id, path }, opener);
  /* The candidate change only: the proposal's own private record, which
     holds its expected context impact, is bookkeeping and not shown here. */
  const items = changeItems(plan.changes.filter((c) => !/^Agent Proposal /.test(c.path)));
  if (items.length) change.appendChild(fileList(items, readPlanned));
  if (plan.blocked || !plan.changes.length) return;
  accept.disabled = false;
  accept.addEventListener("click", (event) => applyPlan("accept-proposal", request, plan, event.currentTarget, true, {}));
}

/* Reject proposal: one confirmation, in the same card, with no reason field
   (UI Standards). Reject removes the proposal from the inbox; nothing about it
   is kept. In an expanded review the confirmation stands in for the decision
   row, so only one Reject action is ever shown; Cancel brings the row back. */
function startProposalRejection(p, detail, seq, onCancel) {
  if (seq !== proposalReviewSeq || detail.querySelector("#proposalRejectForm")) return;
  const decisions = detail.querySelector(".proposal-decisions");
  const confirmButton = el("button", { class: "btn", id: "btnConfirmReject", type: "button", text: "Reject",
    onclick: async (event) => {
      const request = { proposal_id: p.proposal_id };
      let plan;
      try { plan = await call("/api/plan", { kind: "reject-proposal", request }); }
      catch (err) { toast(err.message, true); return; }
      if (seq !== proposalReviewSeq) return;
      await applyPlan("reject-proposal", request, plan, event.currentTarget, true, {});
    } });
  const form = el("div", { class: "proposal-reject", id: "proposalRejectForm", role: "group",
    "aria-label": "Reject this proposal" }, [
    el("div", { class: "actions" }, [confirmButton,
      el("button", { class: "btn", id: "btnCancelReject", type: "button", text: "Cancel", onclick: () => {
        if (onCancel) { onCancel(); return; }
        form.remove();
        if (decisions) decisions.hidden = false;
        const decline = detail.querySelector("#btnRejectProposal");
        if (decline && decline.focus) decline.focus();
      } })]),
  ]);
  if (decisions) decisions.hidden = true;
  detail.querySelector(".proposal-reject-slot").appendChild(form);
  if (confirmButton.focus) confirmButton.focus();
}

function unexpectedRow(u) {
  return el("div", { class: "doc unexpected-record" }, [
    el("div", {}, [
      el("div", { class: "title-row" }, [el("span", { class: "title", text: u.name }),
        chip("Unexpected — not a proposal", "stale")]),
      el("div", { class: "origin", text: `${u.why} Untrusted local material — not a proposal. `
        + `${(u.bytes / 1024).toFixed(1)} kB.` }),
    ]),
    el("div", { class: "actions" }, [
      el("button", { class: "btn ghost small", text: "View contents", onclick: () => viewUnexpected(u, false) }),
      /* Only a file has text to import; a folder, link or special file does not. */
      u.regular === false ? null
        : el("button", { class: "btn ghost small", text: "Import a copy…", onclick: () => viewUnexpected(u, true) }),
    ]),
  ]);
}

async function viewUnexpected(u, asImport) {
  let got;
  try { got = await call("/api/proposals/unexpected", { name: u.name }); } catch (err) { toast(err.message, true); return; }
  if (asImport && got.regular !== false) { startImport(got.text); return; }
  review = null;
  showFormPanel(`Unexpected Local Record ${u.name}`, el("div", { class: "inner" }, got.regular === false
    ? [el("div", { class: "note warn", id: "unexpectedText", text: got.message })]
    : [el("div", { class: "note warn", text: "Untrusted local material, shown as text. It is not a proposal, "
        + "and viewing it changes nothing." }),
      el("pre", { class: "code", id: "unexpectedText", text: got.text })]));
}

/* Import: a proposal an agent returned as JSON, checked exactly as `charter
   propose` checks it, then filed only when the person confirms. */
/* Import Agent Proposal: the fallback for an agent that could not file its
   own proposal JSON. Proposals are agent-submitted material; a person adds
   their own through Create candidate. The panel belongs to Agent Proposals:
   leaving that area closes it and drops whatever was pasted or checked. */
let importPanel = null;  // the open Import Agent Proposal panel
let importSeq = 0;

function startImport(prefill) {
  review = null;
  const seq = ++importSeq;
  const box = el("textarea", { id: "importJson", rows: 12, spellcheck: "false" });
  box.value = prefill || "";
  const result = el("div", { id: "importResult" });
  /* Import files exactly the JSON that passed Check proposal: any edit
     disables it again, and clears what the last check said. */
  const importButton = el("button", { class: "btn", id: "btnFileImport", text: "Import", disabled: "" });
  let passed = null;  // the exact text that passed, while it is still what the field holds
  const invalidate = () => { passed = null; importButton.disabled = true; result.textContent = ""; };
  box.addEventListener("input", invalidate);
  importButton.addEventListener("click", () => {
    if (passed === null || passed !== box.value) { invalidate(); return; }
    fileImport(passed, importButton, seq);
  });
  const inner = el("div", { class: "inner" }, [
    el("p", { class: "note", id: "importInstruction" }, [
      document.createTextNode("Paste an agent proposal as JSON below. Use "),
      el("strong", { text: "Create candidate" }),
      document.createTextNode(" for material you want to add yourself. The JSON must follow Charter’s "
        + "proposal format; Charter checks it before anything is filed."),
    ]),
    el("div", { class: "field" }, [el("label", { for: "importJson", text: "Agent proposal JSON" }), box]),
    result,
    el("div", { class: "actions import-actions" }, [
      el("button", { class: "btn ghost", id: "btnCheckImport", text: "Check proposal", onclick: async () => {
        const text = box.value;
        invalidate();
        if (await checkImport(text, result, seq) && seq === importSeq && box.value === text) {
          passed = text;
          importButton.disabled = false;
        }
      } }),
      importButton,
      el("button", { class: "btn ghost", id: "btnCancelImport", type: "button", text: "Cancel", onclick: () => {
        const opener = panelOpener;
        discardImport();
        if (opener && opener.focus) opener.focus();
      } }),
    ]),
  ]);
  showFormPanel("Import Agent Proposal", inner, { close: false });
  importPanel = inner;
}

/* Leaving Agent Proposals: the import panel closes, and its pasted JSON, its
   check result and any answer still on its way are discarded. */
function discardImport() {
  importSeq++;
  const panel = importPanel;
  importPanel = null;
  let shown = false;
  for (let n = panel; n; n = n.parentNode) if (n === $("review")) shown = true;
  if (shown) {
    review = null;
    panelOpener = null;
    $("review").textContent = "";
  }
}

/* Check proposal: true when the JSON would be filed. A passing check says
   nothing — it only enables Import. A failing one is one concise error. */
async function checkImport(text, result, seq) {
  result.textContent = "";
  let checked;
  const fail = (message) => {
    if (seq !== importSeq) return false;
    result.appendChild(el("div", { class: "note error", id: "importError", role: "alert" }, withCode(message)));
    return false;
  };
  try { checked = await call("/api/proposals/import/check", { json: text }); }
  catch (err) { return fail(err.message); }
  if (seq !== importSeq) return false;
  if (!checked.ok) {
    return fail("Not a valid agent proposal: " + checked.problems.map((p) =>
      (p.field ? `\`${p.field}\` — ` : "") + p.message).join(" "));
  }
  return true;
}

async function fileImport(text, button, seq, replace) {
  button.disabled = true;
  let filed;
  try {
    filed = await call("/api/proposals/import",
      Object.assign({ json: text, confirm: true }, replace ? { replace } : {}));
  } catch (err) { button.disabled = false; toast(err.message, true); return; }
  if (seq !== importSeq) return;
  if (filed.result === "duplicate" && filed.waiting && !replace) {
    button.disabled = false;
    askToReplace(text, filed.waiting, seq);
    return;
  }
  if (filed.result !== "pending") {
    button.disabled = false;  // the person can correct and try again
    toast(filed.result === "refused" ? filed.problems.map((p) => p.message).join(" ") : filed.problem.message, true);
    return;
  }
  importPanel = null;
  closeReview();
  await refreshQuiet();
  toast(replace ? "Replaced the waiting proposal with this one, for review. It is not context."
    : "Imported the agent proposal, for review. It is not context.");
}

/* An exact duplicate of a proposal still awaiting review is never filed as a
   second one. The panel asks, in place of its own actions, whether to replace
   the waiting proposal with this submission; Cancel changes nothing. */
function askToReplace(text, waiting, seq) {
  const panel = importPanel;
  if (!panel) return;
  const actions = panel.querySelector(".import-actions");
  const prompt = el("div", { class: "note warn import-duplicate", id: "importDuplicate", role: "alert" }, [
    el("p", { id: "importDuplicateText",
      text: `An identical proposal, “${waiting.title},” is already awaiting review. Replace it?` }),
  ]);
  const close = () => { prompt.remove(); if (actions) actions.hidden = false; };
  const replaceButton = el("button", { class: "btn", id: "btnReplaceImport", type: "button", text: "Replace",
    onclick: () => fileImport(text, replaceButton, seq, waiting.proposal_id) });
  prompt.appendChild(el("div", { class: "actions" }, [replaceButton,
    el("button", { class: "btn", id: "btnCancelReplace", type: "button", text: "Cancel", onclick: () => {
      close();
      const again = panel.querySelector("#btnFileImport");
      if (again && again.focus) again.focus();
    } })]));
  if (actions) actions.hidden = true;
  panel.querySelector("#importResult").appendChild(prompt);
  if (replaceButton.focus) replaceButton.focus();
}

/* ---------------------------------------------------------- connect agents */

/* Copy-only. The server gives the text for the open Agent Context while it is
   ready, and only the reason while it is not. Showing it reads; copying it
   touches only the clipboard. There is no register, connect or setup action:
   the person pastes the text where it belongs and runs any command themselves. */
let connectInfo = null;   // the last /api/connect payload

/* Inline `code` in the server's sentences, shown as code, never as markup. */
function withCode(text) {
  return String(text || "").split("`").map((part, i) =>
    i % 2 ? el("code", { text: part }) : document.createTextNode(part));
}

async function renderConnect() {
  if (!state.open) return;
  try { connectInfo = await call("/api/connect"); } catch (err) { connectInfo = { error: err.message }; }
  drawConnect();
}

/* One block of text to copy: a heading, the exact text, and its Copy button. */
function copyBlock(id, heading, text, button, note) {
  return el("div", { class: "copy-block", id: id + "Block" }, [
    heading ? el("h4", { text: heading }) : null,
    el("pre", { class: "code", id, tabindex: "0", text }),
    el("div", { class: "actions" }, [
      el("button", { type: "button", class: "btn small", id: "btnCopy" + id[0].toUpperCase() + id.slice(1),
        text: button, onclick: () => copyText(text, id) })]),
    note ? el("p", { class: "hint" }, withCode(note)) : null,
  ]);
}

/* The agent hosts offered, Claude Code first. Only the chosen one's setup is
   shown; the choice outlives a redraw. */
const CONNECT_HOSTS = [["claude", "Claude Code"], ["codex", "Codex"], ["other", "Other MCP host"]];
let connectHost = "claude";

/* Each host's copy-ready setup. Claude Code needs nothing more than the
   instruction under the heading; Codex and other hosts say where it goes. */
function connectHostPanels(c) {
  const shells = c.shells.length > 1;
  return {
    claude: [el("div", { class: "connect-shells" }, c.shells.map((s) => copyBlock("connectClaude-" + s.shell,
      shells ? s.label : "", s.claude_code, "Copy command", "")))],
    codex: [copyBlock("connectCodex", "", c.codex_toml, "Copy Codex configuration", c.codex_note)],
    other: [copyBlock("connectConfig", "", c.config_text, "Copy MCP configuration", c.config_note)],
  };
}

/* Connect Agents is four sections with one disclosure pattern — a heading
   that is its own toggle — in this order: MCP, open; then project
   instructions, the connection test, and file access, closed. A closed
   section shows nothing of its text. What a person opens or closes stays so
   across redraws in this session. */
const connectOpen = {};
function connectSection(ids, title, body, open, cls) {
  const key = ids.section + (open ? ":open" : ":closed");   // a route offered alone starts open regardless
  if (key in connectOpen) open = connectOpen[key];
  const region = el("div", { class: "disclosure-body", id: ids.body, hidden: open ? null : "" }, body);
  const toggle = el("button", { type: "button", class: "disclosure-toggle", id: ids.toggle,
    "aria-expanded": String(!!open), "aria-controls": ids.body, text: title, onclick: () => { connectOpen[key] = toggleDisclosure(toggle); } });
  return el("section", { class: "connect-method connect-section " + cls, id: ids.section, "aria-labelledby": ids.title }, [
    el("h3", { class: "connect-section-title", id: ids.title }, [toggle]), region]);
}

/* Connect with MCP: the purpose sentence, a PATH prerequisite when needed,
   the host choice (its legend for assistive technology only), and the chosen
   host's setup with its Copy actions. */
function connectMcp(c) {
  const mcp = [];
  if (c.connect === "files-only") {
    mcp.push(el("div", { class: "note warn", id: "connectMcpLimitation" }, withCode(c.mcp_limitation)));
    return mcp;
  }
  mcp.push(el("p", { id: "connectMcpInstruction",
    text: "Configure the Charter MCP server for your agent." }));
  /* Hosts start this copy by its full path, so PATH decides nothing here: what
     the `charter` command runs is the header's Charter command status's to say. */
  const content = connectHostPanels(c);
  const panels = {};
  CONNECT_HOSTS.forEach(([key, label]) => {
    panels[key] = el("div", { class: "connect-host", id: "connectHost-" + key, role: "group",
      "aria-label": label, hidden: key === connectHost ? null : "" }, content[key]);
  });
  const radios = CONNECT_HOSTS.map(([key, label]) => {
    const input = el("input", { type: "radio", name: "connectHost", id: "connectHostChoice-" + key, value: key,
      "aria-controls": "connectHost-" + key, style: "width:auto" });
    input.checked = key === connectHost;
    input.addEventListener("change", () => {
      if (!input.checked) return;
      connectHost = key;
      CONNECT_HOSTS.forEach(([k]) => { panels[k].hidden = k !== key; });
    });
    return el("label", { for: input.id }, [input, el("span", { text: label })]);
  });
  mcp.push(el("fieldset", { class: "connect-hosts", id: "connectHosts" },
    [el("legend", { class: "sr-only", text: "Choose an agent host" })].concat(radios)));
  CONNECT_HOSTS.forEach(([key]) => mcp.push(panels[key]));
  if (c.install_note) mcp.push(el("p", { class: "hint", id: "connectInstallNote" }, withCode(c.install_note)));
  return mcp;
}

/* File access: the other route, closed unless it is the one route offered. */
function connectFiles(c, open) {
  return connectSection({ section: "connectOther", title: "connectFilesTitle", toggle: "connectFilesToggle",
    body: "connectFilesDetails" }, "Connect Agents with File Access", [
    el("p", { class: "hint", id: "connectFilesNote" }, withCode(c.files_note)),
    copyBlock("connectInstruction", "", c.instruction, "Copy agent instruction", "")], open, "connect-files");
}

function drawConnect() {
  const box = $("connectBody");
  box.textContent = "";
  const c = connectInfo;
  if (!c) return;
  if (c.error) { box.appendChild(el("div", { class: "note warn" }, withCode(c.error))); return; }

  if (!c.ready) {
    box.appendChild(el("section", { class: "connect-status not-ready", id: "connectNotReady" }, [
      el("p", { text: "Not ready to connect: nothing is offered to copy until this Agent Context is ready." }),
      el("ul", { class: "issues", id: "connectReasons" }, c.reasons.map((r) => el("li", { class: "error" }, withCode(r)))),
    ]));
    return;
  }
  /* Ready needs no words; a state that blocks MCP says so, once. */
  if (c.connect !== "ready") {
    box.appendChild(el("p", { class: "connect-status-line " + c.connect, id: "connectStatus",
      "data-connect": c.connect }, [el("span", { id: "connectStatusText" }, withCode(c.status_text))]));
  }
  box.appendChild(connectSection({ section: "connectMcp", title: "connectMcpTitle", toggle: "connectMcpToggle",
    body: "connectMcpDetails" }, "Connect Agents with MCP (Recommended)", connectMcp(c), true, "connect-mcp"));
  if (c.connect !== "files-only") {
    box.appendChild(connectSection({ section: "connectPointerSection", title: "connectPointerTitle",
      toggle: "connectPointerToggle", body: "connectPointerDetails" }, "Add Project Instructions (Recommended)", [
      el("p", { class: "hint", id: "connectPointerNote" }, withCode(c.pointer_note)),
      copyBlock("connectPointer", "", c.pointer, "Copy startup pointer", ""),
    ], false, "connect-instruct"));
  }
  box.appendChild(connectSection({ section: "connectVerify", title: "connectTestTitle", toggle: "connectTestToggle",
    body: "connectTestDetails" }, "Test the Connection (Optional)", [
    copyBlock("connectVerifyPrompt", "", c.verify_prompt, "Copy prompt", ""),
  ], false, "connect-test"));
  box.appendChild(connectFiles(c, c.connect === "files-only"));
}

/* Copying only ever touches the clipboard. If the browser refuses, the text is
   selected where it can be, and the person copies it by hand. */
async function copyText(text, fallbackId) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied. Nothing was written.");
    return true;
  } catch (err) {
    const node = $(fallbackId);
    let selected = false;
    if (node && node.select) { node.select(); selected = true; }
    else if (node && typeof window.getSelection === "function" && document.createRange) {
      const range = document.createRange();
      range.selectNodeContents(node);
      const selection = window.getSelection();
      selection.removeAllRanges();
      selection.addRange(range);
      selected = true;
    }
    toast(selected ? "Copying is not allowed here. The text is selected: copy it with your keyboard."
      : "Copying is not allowed here. Select the text and copy it with your keyboard.", true);
    return false;
  }
}

/* ------------------------------------------------------------ review panel */

/* What each kind of plan is, in the words the page uses for the action. */
const PLAN_LABEL = {
  add: "Create candidate", revise: "Revise", "edit-candidate": "Edit candidate", retire: "Retire",
  rebuild: "Rebuild Agent Context", "regenerate-map": "Regenerate map", settings: "Settings",
  "accept-proposal": "Accept Agent Proposal",
  "reject-proposal": "Reject Agent Proposal",
  changeset: "Change set",
};
const planLabel = (kind) => PLAN_LABEL[kind] || "Change";

function openReview(kind, request, plan, options = {}) {
  review = { kind, request, plan, options };
  renderReview();
  $("review").scrollIntoView({ behavior: "smooth", block: "start" });
}

function closeReview() {
  review = null;
  panelOpener = null;
  $("review").textContent = "";
  /* Closing a change set's preview returns to Build change set. */
  if (csScreen === "preview") { csScreen = "build"; renderChangeSetEditor(); }
}

/* Rebuild over lost metadata: the settings offered — last known on this
   computer, or the defaults — for the person to confirm or change. They are
   used only once the person has previewed them. */
function rebuildSettings(plan, request) {
  const offer = plan.settings_proposal;
  const chosen = request.project_name !== undefined && request.project_name !== null ? request : null;
  const name = el("input", { type: "text", id: "rebuildProjectName", spellcheck: "false" });
  name.value = chosen ? chosen.project_name : offer.project_name;
  const inputs = [];
  const boxes = (state.agent_guidance || []).map((g) => {
    const value = chosen ? !!chosen.agent_guidance[g.id] : !!offer.agent_guidance[g.id];
    const box = el("input", { type: "checkbox", id: `rebuildGuidance-${g.id}`, style: "width:auto",
      checked: value ? "" : null });
    box.dataset.setting = g.id;
    inputs.push(box);
    return el("label", { class: "choice", for: box.id }, [box, el("span", {}, [
      el("strong", { text: g.label }), el("span", { class: "hint", text: g.summary })])]);
  });
  return el("section", { class: "note settings-offer", id: "rebuildSettingsOffer" }, [
    el("strong", { id: "rebuildSettingsLabel",
      text: offer.source === "last-known" ? offer.label : "Settings are being initialized" }),
    el("p", {}, withCode(offer.source === "last-known"
      ? "`.agent-context.json` is missing or unreadable. These are the settings last seen for this "
        + "Agent Context on this computer. Confirm or change them: they are not used until you do."
      : offer.label)),
    el("div", { class: "field" }, [el("label", { for: "rebuildProjectName", text: "Project name" }), name]),
    /* The same rows as Settings: each option's name, then its description on its own line. */
    el("fieldset", { class: "field settings-guidance", id: "rebuildGuidance" },
      [el("legend", { text: "Agent guidance" })].concat(boxes)),
    el("div", { class: "actions" }, [el("button", { class: "btn small", id: "btnRebuildWithSettings",
      text: "Preview with these settings", onclick: () => {
        const guidance = {};
        inputs.forEach((b) => { guidance[b.dataset.setting] = !!b.checked; });
        planFor("rebuild", { project_name: name.value.trim(), agent_guidance: guidance },
          review ? review.options : {});
      } })]),
  ]);
}

function renderReview() {
  const panel = $("review");
  panel.textContent = "";
  if (!review) return;
  if (review.applied) { renderRecorded(); return; }
  const { plan, options } = review;
  const inner = el("div", { class: "inner" });
  if (plan.kind === "changeset" && options.changeSet) {
    renderChangeSetPreview(panel, plan, options);
    return;
  }
  (plan.notes || []).forEach((n) => {
    inner.appendChild(el("div", { class: plan.governing_change ? "note authority" : "note" }, withCode(n)));
  });
  if (plan.kind === "rebuild" && plan.settings_proposal) inner.appendChild(rebuildSettings(plan, review.request));

  const issues = plan.issues || [];
  if (issues.length) {
    const list = el("ul", { class: "issues", id: "planProblems" });
    issues.forEach((i) => list.appendChild(issueItem(i)));
    inner.appendChild(list);
  }
  if (!plan.changes.length && !issues.length) {
    inner.appendChild(el("div", { class: "note", text: "Nothing would change." }));
  }
  if (plan.governing_change && plan.after && plan.kind !== "changeset") inner.appendChild(governingBeforeAfter(plan));

  /* Each Markdown result can be read as a document: the server recomputes this
     plan, pinned to what is shown here, and renders that file of it. */
  const readPlanned = (path, opener) => openPreview({ source: "plan", kind: review.kind,
    request: review.request, plan_id: plan.plan_id, path }, opener);
  if (plan.changes.length) inner.appendChild(fileList(changeItems(plan.changes), readPlanned));

  let confirmInput = null;
  if (plan.confirm_phrase) {
    confirmInput = el("input", { type: "text", id: "confirmPhrase", placeholder: plan.confirm_phrase, spellcheck: "false" });
    inner.appendChild(el("div", { class: "field" }, [
      el("label", { for: "confirmPhrase", text: plan.kind === "changeset"
        ? `Type “${plan.confirm_phrase}” once to apply the whole change set`
        : `Type “${plan.confirm_phrase}” to confirm` }),
      confirmInput,
    ]));
  }

  inner.appendChild(el("div", { class: "actions" }, [
    el("button", {
      class: "btn",
      id: "btnApply",
      text: options.applyLabel || "Apply",
      disabled: (plan.blocked || !plan.changes.length) || null,
      onclick: (event) => applyReview(confirmInput ? confirmInput.value : true, event.currentTarget),
    }),
    el("button", { class: "btn ghost", text: "Cancel", onclick: closeReview }),
  ]));

  panel.appendChild(el("section", { class: "review", id: "reviewPanel" }, [
    el("header", {}, [
      el("h3", { text: "Preview" }),
      chip(planLabel(plan.kind), plan.governing_change ? "authority" : "proposed"),
      plan.blocked ? chip("Cannot apply — see below", "stale") : null,
      el("span", { text: plan.summary }),
      el("button", { class: "btn ghost small close", text: "Close", onclick: closeReview }),
    ]),
    inner,
  ]));
}

/* Preview and Apply for a change set: what a person needs to decide, once
   each, in this order — anything that blocks applying or bears on the
   decision; Changes to Apply, each document the change set changes and what
   happens to it in plain words; every changed file, with its diff and Read;
   and the typed confirmation. No scope comparison, retained-document list or
   before-and-after lists, and no note that repeats these or only explains
   mechanics (UI Standards). */
function changeToApply(e) {
  const replaces = e.effect === "replace" || e.effect === "revise";
  const title = replaces || e.effect === "govern-alongside" ? e.candidate_title || e.title : e.title;
  const action = replaces ? `Replaces “${e.title}”`
    : e.effect === "govern-alongside" ? "Governs alongside" : e.effect === "withdraw" ? "Withdrawn" : e.effect;
  return el("li", { class: "cs-change", "data-path": e.document, "data-effect": e.effect }, [
    el("span", { class: "title", text: title }), document.createTextNode(" — "),
    el("span", { class: "cs-change-action", text: action })]);
}

function renderChangeSetPreview(panel, plan, options) {
  const cs = options.changeSet;
  const changes = (cs.effects || []).filter((e) => e.effect !== "retain");
  const inner = el("div", { class: "inner cs-preview", id: "csPreviewBody" });
  const issues = plan.issues || [];
  if (issues.length) inner.appendChild(el("ul", { class: "issues", id: "planProblems" }, issues.map(issueItem)));
  (plan.notes || []).forEach((n) => inner.appendChild(el("div", { class: "note warn cs-preview-warning" }, withCode(n))));

  inner.appendChild(el("section", { class: "cs-section", id: "csChangesToApply", "aria-labelledby": "csChangesToApplyTitle" }, [
    el("h4", { id: "csChangesToApplyTitle", text: "Changes to Apply" }),
    el("ul", { class: "cs-changes" }, changes.map(changeToApply)),
  ]));

  const readPlanned = (path, opener) => openPreview({ source: "plan", kind: review.kind,
    request: review.request, plan_id: plan.plan_id, path }, opener);
  if (plan.changes.length) inner.appendChild(fileList(changeItems(plan.changes), readPlanned));

  const confirmInput = el("input", { type: "text", id: "confirmPhrase", spellcheck: "false" });
  inner.appendChild(el("div", { class: "field" }, [
    el("label", { for: "confirmPhrase", text: `Type “${plan.confirm_phrase}” once to apply the whole change set` }),
    confirmInput,
  ]));
  inner.appendChild(el("div", { class: "actions" }, [
    el("button", { class: "btn", id: "btnApply", text: "Apply",
      disabled: (plan.blocked || !plan.changes.length) || null,
      onclick: (event) => applyReview(confirmInput.value, event.currentTarget) }),
    el("button", { class: "btn ghost", text: "Cancel", onclick: closeReview }),
  ]));
  panel.appendChild(el("section", { class: "review", id: "reviewPanel" }, [
    el("header", {}, [
      el("h3", { text: "Preview" }),
      plan.blocked ? chip("Cannot apply — see below", "stale") : null,
      el("button", { class: "btn ghost small close", text: "Close", onclick: closeReview }),
    ]),
    inner,
  ]));
}

/* The governing set before and after: what agents read now, and would read. */
function governingBeforeAfter(plan) {
  const names = (docs) => el("ul", {}, docs.length
    ? docs.map((d) => el("li", {}, [el("span", { text: d.title }), el("code", { text: " " + d.path })]))
    : [el("li", { class: "hint", text: "None" })]);
  return el("div", { class: "before-after", id: "governingBeforeAfter" }, [
    el("div", {}, [el("h4", { text: "Governing Now" }), names(plan.before || [])]),
    el("div", {}, [el("h4", { text: "Governing After" }), names(plan.after || [])]),
  ]);
}

/* What a finished action wrote — opened only when asked for. */
function renderRecorded() {
  const { plan, applied } = review;
  const inner = el("div", { class: "inner" });
  inner.appendChild(el("div", { class: "note", text: doneMessage(plan) }));
  inner.appendChild(fileList(changeItems(plan.changes)));
  inner.appendChild(el("div", { class: "actions" }, [
    el("button", { class: "btn", text: "Close", onclick: closeReview })]));
  $("review").appendChild(el("section", { class: "review", id: "recordedPanel" }, [
    el("header", {}, [
      el("h3", { text: "Done" }),
      chip(planLabel(plan.kind), plan.governing_change ? "authority" : "proposed"),
      el("span", { text: plan.summary || "" }),
      el("button", { class: "btn ghost small close", text: "Close", onclick: closeReview }),
    ]),
    inner,
  ]));
  return applied;
}

/* Written to the folder, or kept privately: said plainly, with Git left to the person. */
const doneMessage = (plan) => (plan.changes.some((c) => c.location === "Agent Context")
  ? "Done. Written to the Agent Context folder; agents read the new context now. Git is untouched: "
    + "commit it when you choose."
  : "Done. Saved in private local state on this computer. Nothing agents read changed.");

/* One preview, one submission: a disabled button means the person never sees
   a refusal caused by their own double click. */
let applying = false;
let lastApplied = null;   // the last finished action, for “View details”

async function applyReview(confirm, button) {
  const { kind, request, plan, options } = review;
  await applyPlan(kind, request, plan, button, confirm, options);
}

async function applyPlan(kind, request, plan, button, confirm, options = {}) {
  if (applying) return;
  const label = button ? button.textContent : "";
  applying = true;
  if (button) { button.disabled = true; button.textContent = "Writing…"; }
  let applied;
  try {
    /* A change set is applied by its own route, which also keeps its receipt. */
    applied = kind === "changeset"
      ? await call("/api/changeset/apply", { id: request.draft_id, revision: request.draft_revision,
          plan_id: plan.plan_id, confirm })
      : await call("/api/apply", { kind, plan_id: plan.plan_id, request, confirm });
  } catch (err) {
    if (button) { button.disabled = false; button.textContent = label; }
    applying = false;
    await applyFailed(err);
    return;
  }
  applying = false;
  if (kind === "add") resetIntake();
  lastApplied = { kind, request, plan, options: {}, applied };
  review = null;
  $("review").textContent = "";
  await refreshQuiet();
  if (kind === "add" && currentView === "intake") await leaveIntake();
  if (kind === "changeset") {
    /* The change set's own screen becomes its receipt. */
    csScreen = "build";
    await openChangeSet(request.draft_id, { quiet: true });
  } else if (options && options.returnTo) {
    /* Edited from a change set: back to it, which now says the candidate
       changed and offers Refresh. */
    csScreen = "build";
    await openChangeSet(options.returnTo, { quiet: true });
  }
  /* Focus the result: a change set's receipt heading, or the editor it returned
     to; otherwise the heading of the view the person is on. */
  if (kind === "changeset" || (options && options.returnTo)) {
    focusAfter("csTitleText") || focusAfter("changeSetEditor");
  } else {
    focusAfter(currentViewHeading());
  }
  const followUp = (applied && applied.follow_up) || [];
  /* Deciding a proposal says exactly “Proposal accepted.” or “Proposal
     rejected.”: no action, link, document name or other detail. Anything that
     failed after the decision was recorded is its own error, never added to
     that notice. */
  if (kind === "accept-proposal" || kind === "reject-proposal") {
    toast(followUp.length ? followUp.join(" ")
      : kind === "accept-proposal" ? "Proposal accepted." : "Proposal rejected.", followUp.length > 0);
    return;
  }
  const message = doneMessage(plan) + (kind === "add" || kind === "revise"
    ? " Filed as an authority candidate — not context." : kind === "changeset"
    ? " Every declared outcome was applied as one action; its receipt is kept privately."
    : options && options.returnTo ? " Back to the change set: refresh it to use the edited candidate." : "");
  const lands = options && options.returnTo ? "" : landsIn(kind);
  const goThere = lands && lands !== currentView
    ? [{ label: `Go to ${$("view-" + lands).querySelector("h2").textContent}`, onclick: () => navigate(lands) }]
    : [];
  /* Applied is applied: anything that failed after it is said with it, and
     stays until dismissed. One toast shows at a time, so it is one message. */
  toast(followUp.length ? `${message} ${followUp.join(" ")}` : message, followUp.length > 0,
    [{ label: "View details", onclick: showApplied }].concat(goThere));
}

/* The list a finished act leaves its document in, when it has one. */
function landsIn(kind) {
  if (["add", "revise", "retire", "edit-candidate", "accept-proposal"].indexOf(kind) !== -1) return "candidates";
  return "";
}

function showApplied() {
  if (!lastApplied) return;
  review = lastApplied;
  renderReview();
  $("review").scrollIntoView({ behavior: "smooth", block: "start" });
}

/* A refusal: nothing was written, or what was written was rolled back, and
   the message says which. The page catches up with the folder either way. */
async function applyFailed(err) {
  toast(err.message, true);
  try { await refreshQuiet(); } catch (e) { /* the message above stands */ }
}

/* ------------------------------------------------------------ change sets */

/* A coordinated change set is the person's plan of several authority
   changes, applied together: one preview, one typed confirmation, one
   all-or-nothing write. It has two screens. Build change set holds the plan —
   the candidates the person includes, each with the one decision they make,
   Replace with a governing document they select or Govern alongside; the
   governing documents they withdraw; and, collapsed, every other governing
   document, retained without a decision — beside its live context-impact
   review. Preview and apply shows everything the plan writes before one
   confirmation. The draft is private local state — kept on this computer
   only — and changes nothing until it is applied; then it is an immutable
   receipt. Every decision is the person's: no control here starts chosen, and
   nothing a report says chooses one. */
let changeSet = null;  // the draft open in the editor, as the server describes it
let csScreen = "build";  // "build", or "preview" while its preview is open
let csQueue = Promise.resolve();  // changes to the draft, sent one at a time
let csRationale = null;  // rationale typed but not yet saved: { text, timer }
let csPacket = {};  // the review packet's save, for one plan: { plan, confirm, typing, error, saved }
const csOpen = {};  // which of the editor's disclosures the person opened, across redraws

const LIFECYCLE_TONE = { "structurally valid": "ok", blocked: "stale",
  "waiting for required candidates or decisions": "proposed", applied: "authority" };
const REPORT_STATUS = {
  "well-formed": ["Form checks passed — not verified as correct", "ok"],
  issues: ["Report issues found", "proposed"],
  stale: ["Stale — not current review evidence", "stale"],
  malformed: ["Malformed — could not be read", "stale"],
  "not recorded": ["Form checks at apply time not recorded", null],
};
const EFFECT_TONE = { added: "ok", revised: "authority", replaced: "authority", retained: null };
const EFFECT_WORDS = { revise: "Revised", replace: "Replaced", withdraw: "Withdrawn",
  "govern-alongside": "Governs alongside", retain: "Retained" };
const MODE_NAME = { "self-contained": "self-contained prompt", packet: "review packet" };
const documentsOf = (n) => countOf(n, ["governing document", "governing documents"]);

async function renderChangeSets() {
  const list = $("changeSetList");
  if (!list || !state.open) return;
  let data;
  try { data = await call("/api/changesets/list", {}); } catch (err) { toast(err.message, true); return; }
  list.textContent = "";
  renderChangeSetTally(data.drafts.filter(isActiveDraft).length);
  const groupFor = ({ id, name, holds }) => {
    const rows = data.drafts.filter(holds).map(changeSetRow);
    return rows.length ? recordGroup(id, name, rows) : null;
  };
  /* Active drafts are the everyday work. Applied change sets and abandoned
     drafts are history: the normal view does not list them — their receipts
     and records stay, unchanged, in private local state. A record Charter
     cannot read is never hidden: it is listed after the active drafts, where
     it can be deleted. */
  const active = groupFor(CHANGE_SET_ACTIVE);
  const unreadable = groupFor(CHANGE_SET_UNREADABLE);
  if (!active && !unreadable) {
    list.appendChild(el("p", { class: "hint", id: "noChangeSets",
      text: "No open change sets." }));
  }
  if (active) list.appendChild(active);
  if (unreadable) list.appendChild(unreadable);
  renderChangeSetEditor();
}

/* The index's groups, each shown only when it has a member. An incomplete or
   stale draft is active; applied and abandoned change sets are not listed. */
const CHANGE_SET_ACTIVE = { id: "csGroupActive", name: "Active Drafts", holds: isActiveDraft };
const CHANGE_SET_UNREADABLE = { id: "csGroupUnreadable", name: "Unreadable Records", holds: (d) => !!d.unreadable };

/* A row: its title, then its status label; its action on its own. */
function changeSetRow(d) {
  return el("div", { class: "doc changeset-row", "data-id": d.id }, [
    el("div", {}, [
      el("div", { class: "title-row" }, [
        el("span", { class: "title", text: d.title || "Unreadable draft" }),
        chip(d.unreadable ? "unreadable" : d.state, d.state === "active" ? "proposed" : null),
      ]),
      el("div", { class: "path", text: d.unreadable || changeSetCounts(d) }),
    ]),
    el("div", { class: "actions" }, [
      d.unreadable
        ? el("button", { class: "btn ghost small", text: "Delete", onclick: () => deleteChangeSet(d.id, d.id) })
        : el("button", { class: "btn small", text: "Open", onclick: () => openChangeSet(d.id) }),
    ]),
  ]);
}

/* An index card's counts. An applied change set says what it did — its final
   outcomes and the governing documents it established, from its receipt —
   never what was planned. */
function changeSetCounts(d) {
  const reports = countOf(d.reports, ["report", "reports"]);
  if (d.state === "applied" && d.final_outcomes !== undefined) {
    return `${countOf(d.final_outcomes, ["final outcome", "final outcomes"])} · `
      + `${countOf(d.established, ["established governing document", "established governing documents"])} · ${reports}`;
  }
  if (d.state === "applied") return reports;
  return `${countOf(d.changes, ["planned change", "planned changes"])} · ${reports}`;
}

/* Change Sets is an index; a draft or receipt opens in its own editor in
   place of it. Opening one adds a history entry on the same address, so
   Back returns to the index and Forward reopens it. */
function showChangeSet(next) {
  if (!changeSet || changeSet.draft.id !== next.draft.id) {
    csScreen = "build"; csPacket = {}; csConverting = false; dropRationale(); dropReviews();
    refreshChangeSetTally();  // a newly started draft counts at once
  }
  const entering = !changeSet;
  changeSet = next;
  if (currentView !== "changesets") navigate("changesets");
  if (hasHistory()) {
    const entry = { from: "changesets", changeSet: next.draft.id };
    if (entering && !(history.state && history.state.changeSet)) history.pushState(entry, "", "#changesets");
    else if (history.replaceState) history.replaceState(entry, "", "#changesets");
  }
  renderChangeSetEditor();
  const view = $("view-changesets");
  if (entering && view && view.scrollIntoView) view.scrollIntoView({ block: "start" });
}

async function openChangeSet(id, options = {}) {
  let next;
  try { next = await call("/api/changeset/get", { id }); }
  catch (err) { if (!options.quiet) toast(err.message, true); return; }
  showChangeSet(next);
}

/* Back to the index: the browser's Back when the editor has its own history
   entry, so history stays as the person made it. */
async function leaveChangeSet() {
  if (hasHistory() && history.state && history.state.changeSet && history.back) { history.back(); return; }
  await closeChangeSet();
}

async function closeChangeSet() {
  await flushRationale();
  await flushReviews();
  if (csScreen === "preview" && review && review.kind === "changeset") { review = null; $("review").textContent = ""; }
  changeSet = null;
  csScreen = "build";
  csPacket = {};
  await renderChangeSets();
  /* Back at the index: focus its heading, not <body>. */
  focusAfter(document.querySelector("#view-changesets h2"));
}

/* One change to the draft, then the draft as the server now describes it.
   Changes go one at a time, each against the revision the last one left, so
   an autosave never races another edit. A draft changed elsewhere is
   reloaded, never overwritten. */
function changeSetCall(route, body) {
  const run = async () => {
    if (!changeSet) return null;
    const d = changeSet.draft;
    try {
      const next = await call(route, Object.assign({ id: d.id, revision: d.revision }, body || {}));
      if (!changeSet || changeSet.draft.id !== d.id) return next;
      changeSet = next;
      renderChangeSetEditor();
      if (next.draft && next.draft.state !== d.state) refreshChangeSetTally();  // abandoned
      return next;
    } catch (err) {
      toast(err.message, true);
      if (err.data && /changed since you last loaded/.test(err.message)) await openChangeSet(d.id, { quiet: true });
      return null;
    }
  };
  const result = csQueue.then(run);
  csQueue = result.catch(() => null);
  return result;
}

/* A new change set started here is an empty plan, and untitled until the
   person names it. One started from a candidate or document is prefilled
   with the one outcome chosen there (see startChangeSet). */
async function newChangeSet() {
  let made;
  try { made = await call("/api/changeset/create", {}); }
  catch (err) { toast(err.message, true); return null; }
  showChangeSet(made);
  const title = $("csTitle");
  if (title) title.focus();
  return made;
}

/* Discard draft: one clear confirmation, then the private draft is
   discarded — its record kept, unchanged and unlisted, in private local state — and the person is back
   at Change Sets. Nothing else changes: no candidate, no governing context. */
async function discardChangeSet() {
  const d = changeSet && changeSet.draft;
  const label = d && d.title ? `the private draft “${d.title}”` : "this private draft";
  if (typeof confirm === "function" && !confirm(`Discard ${label}? It will be discarded. Its record stays private on this computer; `
      + "no candidate or governing context changes.")) return;
  await flushRationale();
  await flushReviews();
  const next = await changeSetCall("/api/changeset/abandon");
  if (!next) return;
  toast(`Discarded ${label}.`);
  await leaveChangeSet();
}

async function deleteChangeSet(id, label) {
  if (typeof confirm === "function" && !confirm(`Delete the change-set draft “${label}” from this computer? `
      + "No governing context is affected.")) return;
  try { await call("/api/changeset/delete", { id, confirm: true }); }
  catch (err) { toast(err.message, true); return; }
  if (changeSet && changeSet.draft.id === id) { await leaveChangeSet(); return; }
  await renderChangeSets();
}

/* Browser Back and Forward within Change Sets: an entry with a change set
   opens it; the index entry closes the editor. */
function changeSetsFromHistory() {
  const id = hasHistory() && history.state ? history.state.changeSet : null;
  if (id && (!changeSet || changeSet.draft.id !== id)) return openChangeSet(id, { quiet: true });
  if (!id && changeSet) return closeChangeSet();
  return null;
}

const csSection = (title, children, info, id) => el("section", { class: "cs-section", id: id || null }, [
  el("div", { class: "label-row" }, [el("h4", { text: title }), info || null]), ...children]);

const csDisclosure = (key, label, content, options = {}) => disclosure(label, content, {
  id: `csd-${key.replace(/[^A-Za-z0-9_-]/g, "-")}`, buttonId: options.buttonId, open: !!csOpen[key],
  class: "cs-disclosure", onToggle: (open) => { csOpen[key] = open; } });

/* The index or one change set's editor, never both: an open draft or receipt
   takes the whole view, with the way back to the index above it. */
function renderChangeSetEditor() {
  const box = $("changeSetEditor");
  if (!box) return;
  const focus = csFocus();
  box.textContent = "";
  const index = $("changeSetIndex");
  if (index) index.hidden = !!changeSet;
  box.hidden = !changeSet;
  if (!changeSet) return;
  const cs = changeSet;
  box.appendChild(el("nav", { class: "cs-back", "aria-label": "Change Sets" }, [
    el("button", { class: "btn ghost small", id: "csBackToIndex", type: "button", text: "← Change Sets",
      onclick: () => leaveChangeSet() })]));
  if (cs.lifecycle === "applied") { box.appendChild(changeSetReceipt(cs)); return; }
  const active = cs.draft.state === "active";
  if (csScreen === "preview" && !(review && review.kind === "changeset")) csScreen = "build";
  const previewing = active && csScreen === "preview";
  box.appendChild(el("section", { class: "review changeset", id: "changeSetPanel" }, [
    changeSetHeader(cs, active, previewing),
    previewing ? changeSetPreviewing() : changeSetBuild(cs, active),
  ]));
  restoreFocus(focus);
}

/* A redraw keeps the field the person is typing in, and where in it. */
function csFocus() {
  const node = typeof document !== "undefined" ? document.activeElement : null;
  const id = node && node.getAttribute ? node.getAttribute("id") : "";
  if (!id || !/^cs/.test(id)) return null;
  return { id, start: node.selectionStart, end: node.selectionEnd };
}

function restoreFocus(saved) {
  if (!saved) return;
  const node = $(saved.id);
  if (!node || !node.focus) return;
  node.focus();
  if (typeof saved.start === "number" && node.setSelectionRange) {
    try { node.setSelectionRange(saved.start, saved.end); } catch (err) { /* not a text field */ }
  }
}

/* The two screens are said in words. While the plan is being built, its name
   is the plan's first field; otherwise it heads the panel. */
function changeSetHeader(cs, active, previewing) {
  const d = cs.draft;
  const editing = active && !previewing && cs.form !== "earlier";
  return el("header", { class: "cs-head" }, [
    editing ? null : el("h3", { class: "cs-title-text", id: "csTitleText", text: d.title }),
    active ? el("ol", { class: "cs-steps", id: "csSteps", "aria-label": "Steps" }, [
      el("li", { "aria-current": previewing ? null : "step", text: "1. Build Change Set" }),
      el("li", { "aria-current": previewing ? "step" : null, text: "2. Preview and Apply" }),
    ]) : null,
    el("div", { class: "cs-status", id: "csStatus" }, [
      chip(cs.lifecycle, LIFECYCLE_TONE[cs.lifecycle] || null),
      cs.form === "earlier" ? chip("Earlier form", "proposed") : null,
      chip(cs.review_stage, null),
      chip("Private draft — not context", "proposed"),
    ]),
  ]);
}

/* Preview and apply: the plan's own preview, beneath, is the screen. */
function changeSetPreviewing() {
  return el("div", { class: "inner cs-previewing", id: "csPreviewing" }, [
    el("div", { class: "actions" }, [el("button", { class: "btn ghost", id: "csBackToBuild",
      text: "← Back to Build Change Set", onclick: closeReview })]),
  ]);
}

async function previewChangeSet() {
  await flushRationale();
  await flushReviews();
  await csQueue;  // the preview is of the draft with every edit saved
  const cs = changeSet;
  if (!cs || !cs.valid) return;
  csScreen = "preview";
  await planFor("changeset", { draft_id: cs.draft.id, draft_revision: cs.draft.revision },
    { applyLabel: "Apply", changeSet: cs });
  renderChangeSetEditor();
  /* On the preview screen now: focus its heading, not the button that vanished. */
  focusAfter("csTitleText");
}

/* The name is the person's, prominent and editable; it heads the change
   summary. */
function changeSetTitle(d) {
  const input = el("input", { type: "text", id: "csTitle", class: "cs-title-input", maxlength: "200" });
  input.value = d.untitled ? "" : d.title;
  input.addEventListener("change", () => {
    const value = input.value.trim();
    if (!value) { input.value = d.untitled ? "" : d.title; return; }
    if (value !== d.title) changeSetCall("/api/changeset/update", { title: value });
  });
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); input.blur(); } });
  return el("div", { class: "field cs-title" }, [el("label", { for: "csTitle", text: "Name" }), input]);
}

/* Build change set: the plan, and beside it — below it on a narrow screen —
   one Agent Review panel. The page scrolls as a whole. */
function changeSetBuild(cs, active) {
  const d = cs.draft;
  /* A draft in the earlier form is shown as recorded and changes only by
     being converted or discarded. */
  const earlier = cs.form === "earlier";
  const editable = active && !earlier;
  const plan = el("div", { class: "cs-col cs-plan", id: "csPlan" }, [
    editable ? changeSetTitle(d) : null,
    earlier ? changeSetEarlier(cs, active) : changeSetCandidates(cs, editable),
    earlier ? null : changeSetWithdrawals(cs, editable),
    editable ? changeSetRationale(cs) : null,
    changeSetReasons(cs, editable),
    el("div", { class: "actions cs-next" }, [
      editable ? el("button", { class: "btn", id: "csPreview", text: "Preview and apply →",
        disabled: cs.valid ? null : "", onclick: previewChangeSet }) : null,
      active ? null : el("span", { class: "hint", text: "Discarded: this draft no longer changes." }),
      active ? el("button", { class: "btn ghost", id: "csDiscard", text: "Discard draft", onclick: discardChangeSet }) : null,
    ]),
  ]);
  return el("div", { class: "inner cs-build", id: "csBuild" }, [plan, changeSetAgentReview(cs, editable)]);
}

/* A picker option is short enough to scan in a native dropdown: the
   candidate's title, and "revision" for one that revises a governing
   document. Only candidates that share a title also carry their source,
   what they revise and a short change summary, which tell them apart —
   never the filename suffix alone. The full provenance and scope stay on the
   candidate's card and behind View details. */
function candidateLabel(c, shared) {
  const earlier = c.revises_current === false;
  const key = (t) => (t || "").trim().toLowerCase();
  /* What a revision revises: just "revision" when that is the document of the
     candidate's own title, which the label already names. */
  const revises = !c.revises_title ? ""
    : key(c.revises_title) === key(c.title) ? (earlier ? "revision of an earlier version" : "revision")
      : (earlier ? `revises an earlier version of “${c.revises_title}”` : `revises “${c.revises_title}”`);
  if (!shared) {
    return c.revises_title ? `${c.title} — ${earlier ? "revision of an earlier version" : "revision"}` : c.title;
  }
  const bits = [];
  if (revises) bits.push(revises);
  const tag = sourceTag(c);
  if (tag && !(tag === "Revision" && revises)) bits.push(tag);  // a Revise candidate's source is said already
  if (c.change_summary) bits.push(shortChange(c.change_summary));
  return bits.length ? `${c.title} — ${bits.join(" · ")}` : c.title;
}

/* A change summary for a picker option: its quoted line cut shorter still. */
function shortChange(summary) {
  return summary.replace(/“([^”]*)”/, (whole, quoted) =>
    quoted.length > 28 ? `“${quoted.replace(/…$/, "").slice(0, 27).trimEnd()}…”` : whole);
}

/* Labels for the candidates one picker offers, by path. A title is shared
   when another candidate in `all` (by default the list itself) has it. Where
   two would still read the same, the date each was created is added, and
   then its logical path: always beside what tells them apart, never alone. */
function candidateLabels(list, all) {
  const titleKey = (c) => (c.title || "").trim().toLowerCase();
  const counts = {};
  (all || list).forEach((c) => { counts[titleKey(c)] = (counts[titleKey(c)] || 0) + 1; });
  const labels = {};
  list.forEach((c) => { labels[c.path] = candidateLabel(c, counts[titleKey(c)] > 1); });
  const repeated = () => {
    const seen = {};
    list.forEach((c) => { seen[labels[c.path]] = (seen[labels[c.path]] || 0) + 1; });
    return list.filter((c) => seen[labels[c.path]] > 1);
  };
  repeated().forEach((c) => { if (c.created) labels[c.path] += ` · created ${c.created}`; });
  repeated().forEach((c) => { labels[c.path] += ` · ${c.path}`; });
  return labels;
}

/* A candidate's provenance, shown only where it tells candidates that share
   a title apart: its source, and the document a revision revises. */
function provenanceOf(cs, c) {
  const all = cs.available_candidates || [];
  const same = all.filter((o) => (o.title || "").trim().toLowerCase() === (c.title || "").trim().toLowerCase());
  if (same.length < 2) return "";
  const bits = [];
  if (sourceTag(c)) bits.push(sourceTag(c));
  if (c.revises_title) bits.push(`revises “${c.revises_title}”`);
  if (c.change_summary) bits.push(c.change_summary);
  return bits.join(" · ");
}

/* A closed native dropdown shows only as much of its choice as fits, so a long
   label — or the end of one that tells candidates sharing a title apart —
   can be cut off. The choice is also said in full, in words, just beneath it:
   state, not an information control, shown only once something is chosen. */
function selectedLine(id, text) {
  const line = el("p", { class: "cs-selected", id });
  showSelected(line, text);
  return line;
}

function showSelected(line, text) {
  line.textContent = text ? `Selected: ${text}` : "";
  line.hidden = !text;
}

/* The candidates the plan includes, each a compact row with exactly one
   decision the person makes, from one dropdown: Replace, with the governing
   document they then select, or Govern alongside. A candidate already in the
   plan is not offered again. */
function changeSetCandidates(cs, active) {
  const items = cs.plan_candidates || [];
  const list = el("ul", { class: "cs-list", id: "csCandidates" });
  items.forEach((c, i) => list.appendChild(planCandidate(cs, c, i, active)));
  const free = cs.available_candidates.filter((c) => !c.used);
  const freeLabels = candidateLabels(free, cs.available_candidates);
  const pick = el("select", { id: "csAddCandidate", "aria-label": "Authority candidate to include",
    "aria-describedby": "csAddCandidateSelected" },
    [el("option", { value: "", text: "Choose an authority candidate" })]
      .concat(free.map((c) => el("option", { value: c.path, text: freeLabels[c.path] }))));
  const chosen = selectedLine("csAddCandidateSelected", "");
  pick.addEventListener("change", () => showSelected(chosen, pick.value ? freeLabels[pick.value] : ""));
  return csSection("Candidates", [
    items.length ? list : null,
    active && free.length ? el("div", { class: "actions cs-add" }, [pick,
      el("button", { class: "btn ghost small", id: "csAddCandidateButton", text: "Add", onclick: () => {
        if (!pick.value) { toast("Choose an authority candidate.", true); return; }
        changeSetCall("/api/changeset/update", { candidates: items.map((c) => c.path).concat([pick.value]) });
      } })]) : null,
    active && free.length ? chosen : null,
    /* Only when the section lists no candidate and none can be added: with
       every candidate already planned, it simply offers no Add. */
    items.length || free.length ? null
      : el("p", { class: "hint", id: "csNoCandidates", text: "No candidates available." }),
  ]);
}

/* The governing documents a candidate may replace: not one another candidate
   already replaces or the plan withdraws. One made with Revise… lists the
   document it was drafted from first, labelled as a suggestion — never
   selected. */
function replacementTargets(cs, c) {
  const taken = new Set((cs.plan_candidates || []).filter((o) => o.path !== c.path && o.decision === "replace"
    && o.target).map((o) => o.target).concat((cs.withdrawals || []).map((w) => w.path)));
  const open = (cs.governing || []).filter((g) => !taken.has(g.path) || g.path === c.target);
  const origin = c.revises_path ? open.find((g) => g.path === c.revises_path) : null;
  return origin ? [origin].concat(open.filter((g) => g !== origin)) : open;
}

const DECISION_OPTIONS = [["", "Choose a decision"], ["replace", "Replace"], ["govern-alongside", "Govern alongside"]];

function planCandidate(cs, c, i, active) {
  const send = (d) => changeSetCall("/api/changeset/update", { decisions: { [c.path]: d } });
  const decision = el("select", { id: `csDecision-${i}`, class: "cs-decision", disabled: active ? null : "",
    "aria-label": `Decision for “${c.title}”` },
    DECISION_OPTIONS.map(([value, label]) => el("option", { value, text: label })));
  decision.value = c.decision || "";
  decision.addEventListener("change", () => send({ decision: decision.value,
    target: decision.value === "replace" ? (c.target || "") : "" }));
  let target = null;
  let origin = null;
  if (c.decision === "replace") {
    const targets = replacementTargets(cs, c);
    origin = c.revises_path && targets[0] && targets[0].path === c.revises_path ? targets[0] : null;
    target = el("select", { id: `csTarget-${i}`, class: "cs-target", disabled: active ? null : "",
      "aria-label": `Governing document “${c.title}” replaces`, "aria-describedby": `csTargetSelected-${i}` },
      [el("option", { value: "", text: "Choose the document it replaces" })]
        .concat(targets.map((g) => el("option", { value: g.path,
          text: g === origin ? `${g.title} — suggested: ${REVISED_FROM}` : g.title }))));
    if (c.target && !targets.some((g) => g.path === c.target)) {
      target.appendChild(el("option", { value: c.target, text: c.target_title || c.target }));
    }
    target.value = c.target || "";
    target.addEventListener("change", () => send({ decision: "replace", target: target.value }));
  }
  const replaced = (cs.governing || []).find((g) => g.path === c.target);
  const blank = c.decision === "replace" && replaced && replaced.scope
    ? "Blank — inherits the replaced document's scope" : "Blank — no scope stated";
  const provenance = provenanceOf(cs, c);
  return el("li", { class: "cs-item cs-row cs-candidate", "data-path": c.path }, [
    el("div", { class: "cs-row-head" }, [
      el("div", { class: "cs-row-name" }, [
        el("div", { class: "title-row" }, [el("span", { class: "title", text: c.title }),
          c.present ? null : chip("No longer an authority candidate", "stale")]),
        provenance ? el("div", { class: "path cs-provenance", text: provenance }) : null,
      ]),
    ]),
    el("div", { class: "cs-row-controls" }, [decision, target]),
    target ? selectedLine(`csTargetSelected-${i}`, target.value && replaced ? `Replaces “${replaced.title}”` : "") : null,
    scopeLine(`csScopeLine-${i}`, "Scope", c.scope, blank),
    c.decision === "replace" && c.revises_title && c.revises_current === false
      ? el("p", { class: "note warning cs-earlier", id: `csEarlier-${i}`,
        text: `“${c.title}” was made from an earlier version of “${c.revises_title}”. `
          + "Applying it would undo whatever changed in that document since, unless the candidate repeats "
          + "it: compare them before you apply." }) : null,
    el("div", { class: "actions cs-row-actions" }, [
      el("button", { class: "btn ghost small", id: `csViewDetails-${i}`, type: "button", text: "View details",
        "aria-label": `View details of “${c.title}”`, onclick: (event) => viewCandidateDetails(cs, c, event.currentTarget) }),
      editDetails(c, `csEditDetails-${i}`, active),
      active ? el("button", { class: "btn ghost small", type: "button", text: "Remove", "aria-label": `Remove ${c.title} from the plan`,
        onclick: () => changeSetCall("/api/changeset/update",
          { candidates: (cs.plan_candidates || []).filter((o) => o.path !== c.path).map((o) => o.path) }) }) : null,
    ]),
  ]);
}

/* View details: the complete candidate's details and, for a replacement, its
   scope beside the scope it replaces — on request, never in the row. */
function viewCandidateDetails(cs, c, opener) {
  const replaced = c.decision === "replace" ? (cs.governing || []).find((g) => g.path === c.target) : null;
  const effect = (cs.effects || []).find((e) => e.candidate === c.path);
  const facts = [["Title", c.title], ["Logical path", c.path],
    ["Source", sourceTag(c) || "—"],
    c.revises_title ? ["Revises", c.revises_current === false ? `an earlier version of “${c.revises_title}”`
      : `“${c.revises_title}”`] : null,
    c.change_summary ? ["Change", c.change_summary] : null,
    ["Decision", c.decision === "replace" ? (replaced ? `Replace “${replaced.title}”` : "Replace — document not chosen")
      : c.decision === "govern-alongside" ? "Govern alongside" : "Not yet chosen"]].filter(Boolean);
  review = null;
  showFormPanel(`Details: ${c.title}`, el("div", { class: "inner cs-details", id: "csDetails" }, [
    el("dl", { class: "scope-compare cs-details-facts" },
      facts.reduce((out, [k, v]) => out.concat([el("dt", { text: k }), el("dd", { text: v })]), [])),
    el("h5", { text: replaced ? "Scope Comparison" : "Scope" }),
    candidateScope(c, replaced ? { path: replaced.path, scope: replaced.scope } : null, effect, false),
    el("div", { class: "actions" }, [
      c.present ? el("button", { class: "btn ghost small", id: "csDetailsRead", type: "button", text: "Read the candidate",
        onclick: (event) => openDocument(c.path, event.currentTarget) }) : null,
      c.present && (c.revises_path || replaced) ? el("button", { class: "btn ghost small", id: "csDetailsCompare",
        type: "button", text: "Compare with governing…", onclick: (event) => openComparison(c.path,
          [replaced ? replaced.path : c.revises_path], `Compare “${c.title}” with “${replaced ? replaced.title
            : c.revises_title}”`, event.currentTarget) }) : null,
    ]),
  ]));
  if (opener) panelOpener = opener;
}

/* Governing documents the plan withdraws: each stops governing and becomes an
   authority candidate again. A withdrawal uses no candidate. */
function changeSetWithdrawals(cs, active) {
  const withdrawals = cs.withdrawals || [];
  const list = el("ul", { class: "cs-list", id: "csWithdrawals" }, withdrawals.map((w) =>
    el("li", { class: "cs-item cs-row", "data-path": w.path }, [
      el("div", { class: "cs-row-head" }, [
        el("div", { class: "title-row" }, [el("span", { class: "title", text: w.title }),
          w.governs ? null : chip("No longer governs", "stale")]),
        active ? el("button", { class: "btn ghost small", type: "button", text: "Remove",
          "aria-label": `Remove the withdrawal of ${w.title}`,
          onclick: () => changeSetCall("/api/changeset/update",
            { withdrawals: withdrawals.filter((o) => o.path !== w.path).map((o) => o.path) }) }) : null,
      ]),
    ])));
  const replaced = new Set((cs.plan_candidates || []).filter((c) => c.decision === "replace").map((c) => c.target));
  const open = (cs.governing || []).filter((g) => !replaced.has(g.path)
    && !withdrawals.some((w) => w.path === g.path));
  const pick = el("select", { id: "csAddWithdrawal", "aria-label": "Governing document to withdraw" },
    [el("option", { value: "", text: "Choose a governing document" })]
      .concat(open.map((g) => el("option", { value: g.path, text: g.title }))));
  return csSection("Withdrawals", [
    el("p", { class: "hint", id: "csWithdrawalsHint", text: "Withdrawn documents become authority candidates." }),
    withdrawals.length ? list : null,
    active && open.length ? el("div", { class: "actions cs-add" }, [pick,
      el("button", { class: "btn ghost small", id: "csAddWithdrawalButton", text: "Add", onclick: () => {
        if (!pick.value) { toast("Choose a governing document.", true); return; }
        changeSetCall("/api/changeset/update", { withdrawals: withdrawals.map((w) => w.path).concat([pick.value]) });
      } })]) : null,
  ]);
}

/* A draft recorded in the earlier form, shown exactly as recorded: an outcome
   for each governing document. It is refreshed, reviewed, previewed or
   applied only once the person converts it, after seeing every change. */
const EARLIER_OUTCOME = { retain: "Retain", revise: "Revise", replace: "Replace", withdraw: "Withdraw", "": "Not yet decided" };
let csConverting = false;  // the conversion's confirmation is open

function changeSetEarlier(cs, active) {
  const earlier = cs.earlier || { rows: [], alongside: [], others: [] };
  const rows = el("ul", { class: "cs-list", id: "csEarlierRows" }, earlier.rows.map((r) =>
    el("li", { class: "cs-item cs-row", "data-path": r.path }, [
      el("div", { class: "cs-row-head" }, [
        el("div", {}, [el("div", { class: "title", text: r.title }), el("div", { class: "path", text: r.path })]),
        chip(EARLIER_OUTCOME[r.outcome] || r.outcome, null),
      ]),
      r.candidate ? el("p", { class: "hint", text: `With “${r.candidate.title}” — ${r.candidate.path}` }) : null,
    ])));
  const alongside = earlier.alongside.length ? el("ul", { class: "cs-list", id: "csEarlierAlongside" },
    earlier.alongside.map((c) => el("li", { class: "cs-item cs-row" }, [el("div", { class: "cs-row-head" }, [
      el("div", {}, [el("div", { class: "title", text: c.title }), el("div", { class: "path", text: c.path })]),
      chip("Govern alongside", null)])]))) : null;
  const others = earlier.others.length ? el("p", { class: "hint", id: "csEarlierOthers",
    text: `Every other governing document (${earlier.others.length}): `
      + (earlier.others_retained ? "Retain all other governing documents was chosen." : "not yet decided.") }) : null;
  return csSection("Recorded in the Earlier Form", [
    el("p", { class: "note warning", id: "csEarlierNote", text: "This change set was recorded in the earlier "
      + "form, which declared an outcome for every governing document. It is shown exactly as recorded. "
      + "To refresh, review, preview or apply it, convert it to the current form first." }),
    earlier.rows.length ? rows : null,
    alongside,
    others,
    active ? (csConverting ? conversionPanel(cs) : el("div", { class: "actions" }, [
      el("button", { class: "btn", id: "csConvert", type: "button", text: "Convert to current form…",
        onclick: () => { csConverting = true; renderChangeSetEditor(); focusAfter("csConversionHeading"); } })])) : null,
  ], null, "csEarlier");
}

function conversionPanel(cs) {
  const changes = (cs.conversion && cs.conversion.changes) || [];
  const word = { converted: "Converted", kept: "Kept", removed: "Removed" };
  return el("div", { class: "cs-conversion", id: "csConversion", role: "region", "aria-labelledby": "csConversionHeading" }, [
    el("h5", { id: "csConversionHeading", tabindex: "-1", text: "Converting to the Current Form Changes This" }),
    el("ul", { class: "issues", id: "csConversionChanges" }, changes.map((c) => el("li", {
      class: c.change === "removed" ? "warning" : "" }, [
      el("span", {}, [chip(word[c.change] || c.change, c.change === "removed" ? "proposed" : null),
        el("span", { text: ` ${c.text}` })]),
    ]))),
    el("p", { class: "hint", id: "csConversionNote", text: "Converting changes no governing context. The plan "
      + "changes, so attached reports and prompt records become stale; they are kept as history. Nothing is "
      + "converted until you confirm." }),
    el("div", { class: "actions" }, [
      el("button", { class: "btn", id: "csConvertConfirm", type: "button", text: "Convert", onclick: async () => {
        const next = await changeSetCall("/api/changeset/convert", { confirm: true });
        csConverting = false;
        if (next) { renderChangeSetEditor(); toast("Converted to the current form. Review the plan; refresh it if it says so."); }
      } }),
      el("button", { class: "btn ghost", id: "csConvertCancel", type: "button", text: "Cancel", onclick: () => {
        csConverting = false; renderChangeSetEditor(); focusAfter("csConvert");
      } }),
    ]),
  ]);
}


/* A planned candidate's scope, on one line however long it is: the whole
   text is there for a screen reader, and clipped on screen. Its complete
   scope, and for a revision or replacement the comparison with the scope it
   replaces, are one disclosure away; Preview and apply shows them in full. */
function scopeLine(id, label, text, blank, lead) {
  return el("p", { class: "cs-scope-line cs-scope-oneline", id }, [
    lead || null,
    el("span", { class: "cs-scope-label", text: `${label}: ` }),
    el("span", { class: text ? "cs-scope-text" : "cs-scope-text empty", text: text || blank }),
  ]);
}

/* Scope is the candidate's own metadata, changed with Edit details… — never
   here. Editing it makes the draft and its review evidence stale until the
   person refreshes it; this returns them to the draft to do so. */
function editDetails(c, id, active) {
  if (!active || !c.present || !changeSet) return null;
  const draftId = changeSet.draft.id;
  return el("button", { class: "btn ghost small", id, type: "button", text: "Edit details…",
    "aria-label": `Edit details of “${c.title}”`,
    onclick: () => startCandidateEdit({ path: c.path }, { returnTo: draftId }) });
}

/* A candidate's scope, as its own metadata says — beside the scope it
   replaces, for a revision or replacement. Read-only here: scope is changed
   with Edit details on the candidate, which makes any report stale. */
function candidateScope(c, row, effect, nested) {
  const compare = el("dl", { class: "scope-compare" }, row ? [
    el("dt", { text: "Candidate's scope" }), el("dd", { text: c.scope || "None stated" }),
    el("dt", { text: "Current scope" }), el("dd", { text: row.scope || "None stated" }),
    el("dt", { text: "Scope after" }),
    el("dd", { text: effect
      ? (effect.scope_after || "None stated") + (!c.scope && row.scope && effect.scope_after ? " (inherited)" : "")
      : (c.scope || (row.scope ? `${row.scope} (inherited)` : "None stated")) }),
  ] : [el("dt", { text: "Candidate's scope" }), el("dd", { text: c.scope || "None stated" })]);
  compare.classList.add(row ? "scope-compare-row" : "scope-compare-one");
  return el("div", { class: nested ? "cs-scope-detail" : "cs-scope" }, [
    c.present || nested ? null : chip("No longer an authority candidate", "stale"),
    compare,
    el("p", { class: "hint cs-scope-note", text: "Scope is the candidate's own metadata: change it with "
      + "Edit details on the candidate." }),
  ]);
}

/* The rationale is part of the draft, saved as the person writes it: shortly
   after they stop typing, when they leave the field, and before anything
   that leaves or previews the draft. There is no Save step. */
const RATIONALE_PAUSE_MS = 800;

function changeSetRationale(cs) {
  const rationale = el("textarea", { id: "csRationale", rows: 3, "aria-labelledby": "csRationaleHeading" });
  rationale.value = csRationale ? csRationale.text : (cs.draft.rationale || "");
  rationale.addEventListener("input", () => {
    if (csRationale && csRationale.timer) clearTimeout(csRationale.timer);
    csRationale = { text: rationale.value, timer: setTimeout(() => flushRationale(), RATIONALE_PAUSE_MS) };
  });
  rationale.addEventListener("change", () => {
    if (!csRationale) csRationale = { text: rationale.value, timer: null };
    flushRationale();
  });
  return el("section", { class: "cs-section", id: "csRationaleSection" }, [
    el("h4", { id: "csRationaleHeading", text: "Change Set Summary" }), rationale]);
}

/* Save the rationale typed so far, once. Text typed while it saves stays
   pending, and is saved next. */
async function flushRationale() {
  if (!csRationale || !changeSet) { csRationale = null; return; }
  if (csRationale.timer) clearTimeout(csRationale.timer);
  const text = csRationale.text;
  csRationale.timer = null;
  if (text === (changeSet.draft.rationale || "")) { csRationale = null; return; }
  const saved = await changeSetCall("/api/changeset/update", { rationale: text });
  // Kept when the save failed, so nothing typed is lost.
  if (saved && csRationale && csRationale.text === text && !csRationale.timer) csRationale = null;
}

function dropRationale() {
  if (csRationale && csRationale.timer) clearTimeout(csRationale.timer);
  csRationale = null;
}

function changeSetReasons(cs, active) {
  const reasons = cs.reasons || [];
  const refreshable = reasons.some((r) => r.refreshable);
  const list = el("ul", { class: "issues cs-reasons", id: "csReasons" });
  reasons.forEach((r) => list.appendChild(el("li", { class: r.refreshable ? "warning" : "error" }, [
    el("span", {}, [el("code", { text: r.document || "change set" }),
      ...withCode(` — ${r.message}${r.refreshable ? " Refresh resolves this." : ""}`)]),
  ])));
  return csSection(cs.stale ? "Stale — Refresh Before Applying" : "Readiness", [
    reasons.length ? list : el("p", { class: "hint", id: "csReady",
      text: cs.lifecycle === "structurally valid" ? "Ready to preview." : "" }),
    active && refreshable ? el("div", { class: "actions" }, [el("button", { class: "btn small", id: "csRefresh",
      text: "Refresh", onclick: async () => {
        const next = await changeSetCall("/api/changeset/refresh");
        if (next && next.refreshed && next.refreshed.length) {
          toast("Refreshed: " + next.refreshed.map((c) => `${c.document || "Agent Context"} ${c.change}`).join("; ") + ".");
        }
      } })]) : null,
  ]);
}

/* What a review prompt holds, in one line. Within the practical
   single-message limit the review is a prompt to copy; past it, one packet
   to save. Preparing either discloses nothing; copying or saving does, and
   says so beside it. */
function promptIncludes(p) {
  const inc = p.includes || {};
  return `Includes ${documentsOf(inc.documents)} in full, ${countOf(inc.candidates, ["candidate", "candidates"])} `
    + `and the complete planned change. ${p.size_chars.toLocaleString("en")} characters, `
    + `about ${p.approx_tokens.toLocaleString("en")} tokens.`;
}

const sizeOf = (bytes) => bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB`
  : `${Math.max(1, Math.round(bytes / 1024)).toLocaleString("en")} KB`;

/* Past the limit: the packet, saved where the person chooses. Compact and
   factual: its status and size, the save action, and the disclosure beside
   it. The packet itself holds its review instructions; its text never comes
   to the page. */
function changeSetPacket(cs, p) {
  if (csPacket.plan !== cs.plan_fingerprint) csPacket = { plan: cs.plan_fingerprint };
  const out = [
    el("p", { class: "cs-includes", id: "csPacketStatus", text: `Review packet required: `
      + `${p.size_chars.toLocaleString("en")} characters, past the ${p.limit.toLocaleString("en")}-character `
      + `single-message limit · ${sizeOf(p.size_bytes)}.` }),
    el("div", { class: "cs-copy" }, [
      el("button", { class: "btn small", id: "csSavePacket", type: "button", text: "Save review packet…",
        onclick: () => savePacket(cs, {}) }),
      el("p", { class: "cs-copy-warning", id: "csPacketDisclosure", text: cs.packet_disclosure }),
    ]),
  ];
  if (csPacket.typing) {
    const path = el("input", { type: "text", id: "csPacketPath" });
    path.value = csPacket.typed || "";
    out.push(el("div", { class: "note", id: "csPacketTyped" }, [
      el("label", { for: "csPacketPath", text: "No Save dialog is available here. Type the full path of the file, or of a folder:" }),
      path,
      el("div", { class: "actions" }, [el("button", { class: "btn small", id: "csSavePacketTyped", type: "button",
        text: "Save review packet", onclick: () => { csPacket.typed = path.value; savePacket(cs, { path: path.value }); } })]),
    ]));
  }
  if (csPacket.error) out.push(el("div", { class: "note warn", id: "csPacketRefused", role: "alert" }, withCode(csPacket.error)));
  if (csPacket.confirm) {
    out.push(el("div", { class: "note warn", id: "csPacketWarning", role: "alert" }, [
      el("p", { text: csPacket.confirm.warning }),
      el("p", { class: "path", text: csPacket.confirm.path }),
      el("div", { class: "actions" }, [
        el("button", { class: "btn small", id: "csSavePacketAnyway", type: "button", text: "Save there anyway",
          onclick: () => savePacket(cs, { path: csPacket.confirm.path, accept_warning: true }) }),
        el("button", { class: "btn ghost small", id: "csSavePacketElsewhere", type: "button", text: "Choose another location…",
          onclick: () => savePacket(cs, {}) }),
      ]),
    ]));
  }
  if (csPacket.saved) {
    const s = csPacket.saved;
    out.push(el("div", { class: "note", id: "csPacketSaved", role: "status" }, [
      el("p", { text: `Saved “${s.name}”${s.renamed ? " — a file with the chosen name was already there, so nothing was replaced" : ""}.` }),
      el("p", { class: "path", text: s.folder }),
      s.warning ? el("p", { text: s.warning }) : null,
    ]));
  }
  return out;
}

/* Save the packet: the Save dialog chooses where, unless the person typed a
   path. A refusal or a Git-repository warning stays on screen; nothing is
   saved until the destination is allowed. */
async function savePacket(cs, extra) {
  csPacket = { plan: cs.plan_fingerprint, typing: csPacket.typing, typed: csPacket.typed };
  let got;
  try {
    got = await call("/api/changeset/packet/save", Object.assign({ id: cs.draft.id,
      plan_fingerprint: cs.plan_fingerprint }, extra));
  } catch (err) {
    if (err.data && err.data.type_path) csPacket.typing = true;
    else csPacket.error = err.message;
    if (err.data && /changed after you last loaded/.test(err.message)) { await openChangeSet(cs.draft.id, { quiet: true }); return; }
    renderChangeSetEditor();
    if (csPacket.typing && $("csPacketPath")) $("csPacketPath").focus();
    return;
  }
  if (got.cancelled) { renderChangeSetEditor(); return; }
  if (got.needs_confirmation) {
    csPacket.confirm = { path: got.path, warning: got.warning };
    renderChangeSetEditor();
    return;
  }
  const saved = got.saved;
  changeSet = Object.assign({}, got);
  delete changeSet.saved;
  csPacket = { plan: got.plan_fingerprint, saved };
  renderChangeSetEditor();
  toast(`Saved the review packet “${saved.name}”. Attach it to the agent you choose; nothing was sent.`);
}

async function copyReviewPrompt(p) {
  try {
    await navigator.clipboard.writeText(p.text);
  } catch (err) {
    csOpen.prompt = true;
    if ($("csShowPrompt")) toggleDisclosure($("csShowPrompt"), true);
    if ($("csPromptText")) $("csPromptText").select();
    toast("Copying is not allowed here. The prompt is selected: copy it with your keyboard.", true);
    return;
  }
  toast("Copied the review prompt. Give it to the agent you choose; nothing was sent.");
  await recordCopy(p);
}

/* Remembered with the draft, on this computer: which prompt was copied, for
   which plan. Not the prompt itself. */
const recordCopy = (p) => changeSetCall("/api/changeset/prompt/copied",
  { mode: p.mode, plan_fingerprint: p.plan_fingerprint });

/* Agent Review: one panel with the review material to give an agent — a
   prompt to copy, or past the practical limit a packet to save, its
   disclosure beside it — and any number of reviews, each with its reviewing
   agent and response, saved as they are written. Only a structurally valid
   report counts as an attached advisory report; any other text stays saved,
   with what is wrong with it. */
function changeSetAgentReview(cs, active) {
  const reviews = cs.reports || [];
  const list = el("div", { class: "cs-reviews", id: "csReviews" }, reviews.map((r, i) => reviewEntry(r, i, active)));
  return el("section", { class: "cs-col cs-review cs-section", id: "csAgentReview" }, [
    el("h4", { text: "Agent Review" }),
    ...(active ? reviewMaterial(cs) : []),
    reviews.length ? list : null,
    active ? el("div", { class: "actions" }, [el("button", { class: "btn ghost small", id: "csAddReview", type: "button",
      text: reviews.length ? "Add another review" : "Add a review", onclick: addReview })]) : null,
  ]);
}

function reviewMaterial(cs) {
  const p = cs.review_prompt || { ready: false, reason: "" };
  const body = [];
  if (!p.ready) {
    body.push(el("p", { class: "hint", id: "csPromptWaiting" }, withCode(p.reason)));
  } else if (p.over_limit) {
    body.push(...changeSetPacket(cs, p));
  } else {
    body.push(el("p", { class: "cs-includes", id: "csPromptIncludes", text: promptIncludes(p) }));
    const text = el("textarea", { id: "csPromptText", rows: 10, readonly: "", "aria-label": "Review prompt" });
    text.value = p.text;
    text.addEventListener("copy", () => recordCopy(p));
    body.push(el("div", { class: "cs-copy" }, [
      el("button", { class: "btn small", id: "csCopyPrompt", text: "Copy review prompt",
        onclick: () => copyReviewPrompt(p) }),
      el("p", { class: "cs-copy-warning", id: "csDisclosure", text: cs.disclosure_warning }),
    ]));
    body.push(csDisclosure("prompt", "Show the prompt text", [text], { buttonId: "csShowPrompt" }));
  }
  const last = (cs.copied || []).slice(-1)[0];
  if (last && p.ready) {
    body.push(el("p", { class: "hint", id: "csCopied", text: last.current
      ? (last.mode === "packet" ? "You saved a review packet for this plan." : `You copied the ${MODE_NAME[last.mode] || last.mode} for this plan.`)
      : `You ${last.mode === "packet" ? "saved a review packet" : "copied a review prompt"} for an earlier version of this plan: `
        + "a report written from it will be stale." }));
  }
  return body;
}

/* Reviews being written: what the person typed, kept until it is saved, so
   a redraw never loses it. Each review saves on its own, shortly after the
   person stops typing, when they leave the field, and before anything that
   leaves or previews the draft. */
const csReviewDrafts = {};

function reviewEntry(r, i, active) {
  const pending = csReviewDrafts[r.id] || {};
  const label = el("input", { type: "text", id: `csReviewAgent-${i}`, maxlength: "200", disabled: active ? null : "" });
  label.value = pending.label !== undefined ? pending.label : (r.label || "");
  const text = el("textarea", { id: `csReviewText-${i}`, rows: 6, disabled: active ? null : "",
    "aria-describedby": `csReviewState-${i}` });
  text.value = pending.text !== undefined ? pending.text : (r.text || "");
  const edited = (field, input) => () => {
    const d = csReviewDrafts[r.id] = csReviewDrafts[r.id] || {};
    d[field] = input.value;
    if (d.timer) clearTimeout(d.timer);
    d.timer = setTimeout(() => flushReview(r.id), RATIONALE_PAUSE_MS);
  };
  label.addEventListener("input", edited("label", label));
  text.addEventListener("input", edited("text", text));
  label.addEventListener("change", () => { edited("label", label)(); flushReview(r.id); });
  text.addEventListener("change", () => { edited("text", text)(); flushReview(r.id); });
  return el("article", { class: "cs-review-entry" + (r.valid ? " is-valid" : ""), id: `csReview-${i}`, "data-report": r.id }, [
    el("div", { class: "field" }, [el("label", { for: `csReviewAgent-${i}`, text: "Reviewing agent" }), label]),
    el("div", { class: "field" }, [el("label", { for: `csReviewText-${i}`, text: "Response" }), text]),
    reviewState(r, i),
    active ? el("div", { class: "actions" }, [el("button", { class: "btn ghost small", id: `csRemoveReview-${i}`,
      type: "button", text: "Remove review", onclick: () => removeReview(r) })]) : null,
  ]);
}

/* What the saved text is: a report — its claims and its form checks, side by
   side with the others — or, when it is not one yet, why. */
function reviewState(r, i) {
  const id = `csReviewState-${i}`;
  if (r.status === "empty") return el("p", { class: "hint", id, text: "Not yet written." });
  if (!r.valid) {
    return el("div", { class: "note warn", id, role: "status" }, [
      el("p", { text: "Not a structurally valid report yet, so it is not attached as advisory evidence. "
        + "It stays saved as written." }),
      el("ul", { class: "issues report-issues" }, (r.issues || []).map((x) => el("li", { class: "error" }, [
        el("span", {}, [el("code", { text: x.category }), ...withCode(` ${x.path ? x.path + ": " : ""}${x.message}`)])]))),
    ]);
  }
  return el("div", { id }, [reportCard(Object.assign({}, r, { label: r.label || "Unnamed reviewing agent" }), false)]);
}

async function flushReview(id) {
  const d = csReviewDrafts[id];
  if (!d || !changeSet) { delete csReviewDrafts[id]; return; }
  if (d.timer) clearTimeout(d.timer);
  d.timer = null;
  const body = { report_id: id };
  if (d.label !== undefined) body.label = d.label;
  if (d.text !== undefined) body.text = d.text;
  const sent = { label: d.label, text: d.text };
  const saved = await changeSetCall("/api/changeset/review/save", body);
  // Kept when the save failed, or when the person typed more meanwhile.
  const now = csReviewDrafts[id];
  if (saved && now && !now.timer && now.label === sent.label && now.text === sent.text) delete csReviewDrafts[id];
}

async function flushReviews() {
  for (const id of Object.keys(csReviewDrafts)) await flushReview(id);
}

function dropReviews() {
  Object.keys(csReviewDrafts).forEach((id) => {
    if (csReviewDrafts[id].timer) clearTimeout(csReviewDrafts[id].timer);
    delete csReviewDrafts[id];
  });
}

async function addReview() {
  await flushReviews();
  const next = await changeSetCall("/api/changeset/review/add");
  const n = next && (next.reports || []).length;
  if (n) focusAfter(`csReviewAgent-${n - 1}`);
}

/* Removing a review removes only that private draft review. A structurally
   valid report counts as attached evidence, so removing one is confirmed
   first. The plan and governing context never change. */
async function removeReview(r) {
  if (r.valid && typeof confirm === "function" && !confirm(`Remove the review from `
      + `${r.label ? `“${r.label}”` : "an unnamed reviewing agent"}? It is a structurally valid report, so it counts `
      + "as attached advisory evidence. Removing it changes nothing in the plan or governing context.")) return;
  if (csReviewDrafts[r.id] && csReviewDrafts[r.id].timer) clearTimeout(csReviewDrafts[r.id].timer);
  delete csReviewDrafts[r.id];
  await changeSetCall("/api/changeset/report/remove", { report_id: r.id });
}

function reportCard(r, active) {
  const [label, tone] = REPORT_STATUS[r.status] || [r.status, null];
  const claims = r.claims && typeof r.claims === "object" ? r.claims : null;
  const body = [];
  if (claims) {
    const impact = claims.impact && typeof claims.impact === "object" ? claims.impact : {};
    const text = (v) => Array.isArray(v) ? v.join(", ") : String(v === undefined ? "—" : v);
    body.push(el("dl", { class: "report-impact" }, [
      ["Related governing documents", impact.related_documents], ["Overlap", impact.overlap],
      ["Conflict", impact.conflict], ["Recommended relationship", impact.recommended_relationship],
      ["Unresolved decision", impact.unresolved_decision],
    ].flatMap(([k, v]) => [el("dt", { text: k }), el("dd", { text: text(v) })])));
    const coverage = Array.isArray(claims.coverage) ? claims.coverage : [];
    if (coverage.length) body.push(el("ul", { class: "report-coverage" }, coverage.map((c) =>
      el("li", { text: `${c && c.path} — ${c && c.status}` }))));
    const quoted = Array.isArray(claims.claims) ? claims.claims : [];
    quoted.forEach((c) => body.push(el("blockquote", { class: "report-claim" }, [
      el("p", { text: `${c && c.kind} · ${c && c.path}` }), el("p", { text: `“${c && c.quote}”` }),
      c && c.explanation ? el("p", { text: c.explanation }) : null])));
    /* Shown as the agent's suggestion. Nothing here sets a control. */
    const recs = Array.isArray(claims.recommendations) ? claims.recommendations : [];
    if (recs.length) body.push(el("ul", { class: "report-recs" }, recs.map((x) =>
      el("li", { text: `Agent suggests: ${x && x.action} ${x && x.path}${x && x.candidate ? " with " + x.candidate : ""}` }))));
    const limits = Array.isArray(claims.limitations) ? claims.limitations : [];
    if (limits.length) body.push(el("p", { class: "hint", text: "Limitations the agent states: " + limits.join("; ") }));
  }
  const issues = el("ul", { class: "issues report-issues" }, (r.issues || []).map((i) =>
    el("li", { class: i.category === "stale" || i.category === "malformed" ? "error" : "warning" }, [
      el("span", {}, [el("code", { text: i.category }),
        ...withCode(` ${i.path ? i.path + ": " : ""}${i.message}`)])])));
  return el("article", { class: "report-card", "data-report": r.id }, [
    el("header", {}, [el("strong", { text: r.label }), chip(label, tone)]),
    el("h5", { text: "Agent's Advisory Claims — Not Verified, Not Findings" }),
    ...body,
    el("h5", { text: "Report Issues (Form Checks Only)" }),
    (r.issues || []).length ? issues : el("p", { class: "hint", text: "None found." }),
    active ? el("button", { class: "btn ghost small", text: "Remove report",
      onclick: () => changeSetCall("/api/changeset/report/remove", { report_id: r.id }) }) : null,
  ]);
}

/* A receipt's outcome summary: plain labels, only the categories with a
   count, in this order. An earlier-form receipt counts its revisions as
   recorded. */
const RECEIPT_COUNTS = [
  ["replace", "updated"], ["revise", "revised"], ["govern-alongside", "newly governing"],
  ["withdraw", "withdrawn"], ["retain", "retained"],
];

function receiptSummary(outcomes) {
  const parts = [];
  RECEIPT_COUNTS.forEach(([effect, word]) => {
    const n = outcomes.filter((e) => e.effect === effect).length;
    if (!n) return;
    parts.push(parts.length ? `${n} ${word}` : `${n} ${n === 1 ? "document" : "documents"} ${word}`);
  });
  return parts.join(" · ");
}

/* An applied change set: an immutable receipt of what it did, as it was
   applied. It leads with its completion and what it did, in plain words;
   paths, archive locations and the full technical summary are a disclosure
   away. Nothing here edits it. */
function changeSetReceipt(cs) {
  const r = cs.receipt || {};
  const d = cs.draft;
  const outcomes = r.outcomes || [];
  const changed = outcomes.filter((e) => e.effect !== "retain");
  const retained = outcomes.filter((e) => e.effect === "retain");
  const established = r.after || [];
  const appliedOn = r.at ? r.at.slice(0, 10) : "";
  const summaryLine = [receiptSummary(outcomes), appliedOn ? `applied ${appliedOn}` : ""].filter(Boolean).join(" · ");
  const outcomeLine = (e, i) => {
    const by = e.candidate && e.effect !== "govern-alongside" ? `by “${e.candidate_title || e.candidate}”` : "";
    const details = [
      ["Governing path", e.document],
      e.candidate ? ["Candidate", e.candidate] : null,
      e.archived_to ? ["Previous version archived privately at", e.archived_to] : null,
      e.withdrawn_to ? ["Now an authority candidate at", e.withdrawn_to] : null,
      e.scope_before !== undefined && e.effect !== "govern-alongside" ? ["Scope before", e.scope_before || "None stated"] : null,
      e.scope_after !== undefined ? ["Scope after", e.scope_after || "None stated"] : null,
    ].filter(Boolean);
    return el("li", { class: "cs-item cs-receipt-item", "data-path": e.document }, [
      el("div", { class: "cs-receipt-line" }, [
        el("span", { class: "title", text: e.title }),
        chip(EFFECT_WORDS[e.effect] || e.effect, e.effect === "withdraw" ? "stale"
          : e.effect === "govern-alongside" ? "ok" : "authority"),
      ]),
      by ? el("div", { class: "hint", text: by }) : null,
      csDisclosure(`receipt-detail-${e.document}`, "Technical details", [
        el("dl", { class: "scope-compare cs-receipt-detail" },
          details.reduce((out, [k, v]) => out.concat([el("dt", { text: k }), el("dd", { text: v })]), [])),
      ], { buttonId: `csReceiptDetailToggle-${i}` }),
    ]);
  };
  const reports = r.reports || [];
  const evidence = reports.length
    ? csDisclosure("receipt-reports", `${countOf(reports.length, ["advisory report", "advisory reports"])} attached, as checked when applied`,
      [el("div", { class: "report-grid" }, reports.map((x) => reportCard(x, false)))], { buttonId: "csReceiptReportsToggle" })
    : el("p", { class: "hint", id: "csReceiptNoReport", text: "No advisory report attached." });
  const shared = (r.prompts || []).map((p) => el("li", {}, [
    el("strong", { text: p.mode === "packet" ? "Review packet exported" : "Review prompt copied" }),
    el("span", { class: "hint", text: (p.exported || p.copied) ? ` · ${(p.exported || p.copied).slice(0, 10)}` : "" }),
  ]));
  return el("section", { class: "review changeset cs-receipt", id: "changeSetPanel" }, [
    el("header", { class: "cs-head cs-receipt-head" }, [
      el("p", { class: "cs-applied", id: "csAppliedStatus", role: "status" }, [
        el("strong", { text: "Change set applied" })]),
      el("p", { class: "cs-outcome-summary", id: "csOutcomeSummary", text: summaryLine }),
      el("h3", { class: "cs-title-text", id: "csTitleText", text: d.title }),
      el("div", { class: "cs-status", id: "csStatus" }, [chip("Private record — not context", "proposed")]),
    ]),
    el("div", { class: "inner" }, [
      el("p", { class: "note", id: "csRecorded", text: "Agents read the new context now. Git is untouched: "
        + "Charter did not operate it, so commit it when you choose." }),
      csSection(`Changed Documents (${changed.length})`, [
        el("ul", { class: "cs-list", id: "csReceiptOutcomes" }, changed.map(outcomeLine)),
      ], null, "csReceiptFinal"),
      retained.length ? el("section", { class: "cs-section", id: "csReceiptRetainedSection" }, [
        csDisclosure("receipt-retained", groupLabel("Retained Governing Documents", retained.length),
          [el("ul", { class: "set-list", id: "csReceiptRetained" },
            retained.map((e) => el("li", { text: `${e.title} — ${e.document}` })))],
          { buttonId: "csReceiptRetainedToggle" })]) : null,
      el("section", { class: "cs-section", id: "csReceiptEstablishedSection" }, [
        csDisclosure("receipt-established", groupLabel("Established Governing Documents", established.length),
          [el("p", { class: "hint", text: "What governed once this change set was applied." }),
            el("ul", { class: "set-list", id: "csReceiptEstablished" }, established.map((a) => el("li", {}, [
              el("span", { text: `${a.title} — ${a.path}` }), a.effect ? chip(a.effect, EFFECT_TONE[a.effect] || null) : null])))],
          { buttonId: "csReceiptEstablishedToggle" })]),
      csSection("Advisory Review", [evidence], null, "csReceiptReview"),
      shared.length ? csSection("Review Material Shared", [
        el("p", { class: "hint", text: "A record of what was copied or exported for review. It is not advisory evidence." }),
        el("ul", { class: "set-list", id: "csReceiptShared" }, shared),
      ], null, "csReceiptSharedSection") : null,
      r.summary ? el("section", { class: "cs-section", id: "csReceiptSummarySection" }, [
        el("div", { class: "actions" }, [el("button", { class: "btn ghost small", id: "csCopySummary",
          text: "Copy summary", onclick: () => copyText(r.summary, "csSummary") })]),
        csDisclosure("receipt-summary", "Technical change summary",
          [el("pre", { class: "code", id: "csSummary", text: r.summary })], { buttonId: "csSummaryToggle" }),
      ]) : null,
    ]),
  ]);
}

/* The whole governing set before and after, each document with its effect. */
/* --------------------------------------------- Rebuild Agent Context */

/* Offered only when the governing documents are valid and the folder is
   clean: it regenerates the map and metadata, after a preview and an
   ordinary deliberate confirmation, and never changes a governing document. */
function startRebuild() {
  planFor("rebuild", {}, { applyLabel: "Rebuild Agent Context" });
}

/* Offered only when the map's own hash is the sole failure: it rewrites only
   the map from the governing documents, which all match, after a preview. */
function startRegenerate() {
  planFor("regenerate-map", {}, { applyLabel: "Regenerate map" });
}

/* ----------------------------------------------------------------- settings */

/* Diagnostics: which copy of Charter this is — version, build, launcher,
   Python, map formats, and what `charter` by name runs, as a fact — collapsed
   at the end of Settings and of the Open view. Never in a header, footer or
   status, and never the PATH remedy, which is the Charter command dialog's
   alone (UI Standards). */
async function renderDiagnostics(id) {
  const box = $(id);
  if (!box) return;
  let d;
  try { d = await call("/api/diagnostics"); } catch (err) { box.textContent = ""; return; }
  const i = d.identity;
  const rows = [["Version", i.version], ["Build", i.build_text], ["Launcher", i.launcher],
    ["charter.py", i.script], ["Python", i.python], ["Map format", `${i.map_format} (generated by this Charter)`]];
  if ("context_map_format" in i) {
    rows.push(["This Agent Context's map format", i.context_map_format === null ? "not recorded"
      : `${i.context_map_format}${d.relation ? ` (${d.relation})` : ""}`]);
  }
  if (d.folder) rows.push(["Agent Context folder", d.folder]);
  rows.push(["`charter` on PATH", d.on_path.text]);
  const list = el("dl", { class: "diagnostics-list" },
    rows.reduce((out, [k, v]) => out.concat([el("dt", {}, withCode(k)), el("dd", { text: v })]), []));
  const content = [list];
  box.textContent = "";
  box.appendChild(el("section", { class: "record-group", "aria-labelledby": id + "Toggle" }, [
    disclosure("Diagnostics", content, { id: id + "Body", buttonId: id + "Toggle" })]));
}

function renderSettings() {
  renderDiagnostics("settingsDiagnostics");
  const box = $("settingsForm");
  box.textContent = "";
  if (!state.open) return;
  const current = state.status.settings;
  if (!current || !state.status.agents_served) {
    box.appendChild(el("div", { class: "note", id: "settingsUnavailable",
      text: "Settings can be changed while the Agent Context is valid and clean. See the status above." }));
    return;
  }
  const name = el("input", { type: "text", id: "settingsProjectName", spellcheck: "false" });
  name.value = current.project_name;
  const boxes = (state.agent_guidance || []).map((g) => {
    const input = el("input", { type: "checkbox", id: `settingsGuidance-${g.id}`, style: "width:auto",
      checked: g.on ? "" : null });
    input.dataset.setting = g.id;
    return el("label", { class: "choice", for: input.id }, [input, el("span", {}, [
      el("strong", { text: g.label }), el("span", { class: "hint", text: g.summary })])]);
  });
  box.appendChild(el("div", { class: "field" }, [
    el("label", { for: "settingsProjectName", text: "Project name" }), name,
    el("p", { class: "hint",
      text: "Used in the generated context map (AGENT-CONTEXT.md) that agents read. "
        + "It does not rename the folder." })]));
  box.appendChild(el("fieldset", { class: "field settings-guidance", id: "settingsGuidance" },
    [el("legend", { text: "Agent guidance" })].concat(boxes)));
  box.appendChild(el("div", { class: "actions" }, [el("button", { class: "btn", id: "btnPreviewSettings",
    text: "Preview changes", onclick: () => {
      const guidance = {};
      boxes.forEach((label) => { const i = label.querySelector("input"); guidance[i.dataset.setting] = !!i.checked; });
      planFor("settings", { project_name: name.value.trim(), agent_guidance: guidance },
        { applyLabel: "Save settings" });
    } })]));
}

/* View agent context: the current AGENT-CONTEXT.md, in the Markdown viewer.
   Reading it changes nothing. */
function viewContext() {
  openPreview({ source: "context" }, $("btnViewContext"));
}

/* After an action: the state, the lists and the counts it may have changed. */
async function refreshQuiet() {
  viewSeq++;
  state = await call("/api/state");
  renderShell();
  if (!state.open) return;
  renderKnowledge();
  renderSettings();
  if (!staged) renderIntakeForm();
  await reloadReader();
  await renderAgentProposals();
}

/* Leaving Create candidate: the chosen file, its conversion, anything still
   being read or converted, and any open preview of filing it are discarded.
   The server keeps nothing of an upload: converting writes nothing. */
function discardIntake() {
  if (review && review.kind === "add") { review = null; panelOpener = null; $("review").textContent = ""; }
  resetIntake();
}

/* The conversion and everything derived from it — the file line, its notes,
   the title, scope and text, and any open preview of filing it — gone, and
   only choosing a file shown. */
function clearConversion() {
  if (review && review.kind === "add") { review = null; panelOpener = null; $("review").textContent = ""; }
  staged = null;
  ["markdown", "title", "scope"].forEach((id) => { $(id).value = ""; });
  showFrontMatterNote(null);
  $("stagedInfo").textContent = "";
  $("convertNotes").textContent = "";
  unlockIntake(false);
}

/* Create candidate's empty first-use state, exactly. */
function resetIntake() {
  abandonIntakeWork();
  clearConversion();
  $("file").value = "";
}

/* ------------------------------------------------------------------ wiring */

document.querySelectorAll("#nav button").forEach((b) => {
  b.addEventListener("click", async () => {
    /* Change Sets in the navigation is always its index. */
    if (b.dataset.view === "changesets" && changeSet) {
      if (currentView === "changesets") { await leaveChangeSet(); return; }
      await closeChangeSet();
    }
    navigate(b.dataset.view);
  });
});
$("btnNewChangeSet").addEventListener("click", () => newChangeSet());
$("btnAddDocument").addEventListener("click", () => navigate("intake"));
/* Cancel files nothing and changes no context: the chosen file, its
   conversion and any open preview of filing it are discarded. */
$("btnCancelIntake").addEventListener("click", async () => {
  if (review && review.kind === "add") { review = null; $("review").textContent = ""; }
  resetIntake();
  await leaveIntake();
});
$("btnImportProposal").addEventListener("click", () => startImport(""));

/* ---------------------------------------------------- no Agent Context open */

/* One folder, two intentions: Open checks an existing Agent Context and
   writes nothing in it; Create makes a new, empty one in an empty folder. */
const fieldValue = (id) => String($(id).value || "").trim();
let startBusy = false;   // one request at a time from this form

function showFieldError(id, message) {
  $(id).textContent = "";
  withCode(message).forEach((n) => $(id).appendChild(n));
  $(id).hidden = !message;
}

/* What a read-only peek found about the folder in the path field, or null until
   the person commits a folder (Enter/blur, Browse, or a recent choice). */
let startPeek = null;

function syncStartForms(picker) {
  if (picker !== undefined) $("btnBrowse").hidden = !picker;
  const path = fieldValue("contextPath");
  const existing = !!(startPeek && startPeek.has_context);
  const knownNotContext = !!(startPeek && !startPeek.has_context);
  /* Open an existing Agent Context; create a new one in an empty folder. Before
     a folder is committed (no peek yet), both are offered. */
  $("btnOpen").disabled = startBusy || !path || knownNotContext;
  $("btnCreate").disabled = startBusy || !path || existing || !fieldValue("newProjectName");
  /* A button disabled by what the folder holds is described by the line saying so. */
  ["btnOpen", "btnCreate"].forEach((id) => {
    if ((id === "btnOpen" ? knownNotContext : existing) && $(id).disabled) {
      $(id).setAttribute("aria-describedby", "newProjectNameHint");
    } else $(id).removeAttribute("aria-describedby");
  });
  $("contextPath").setAttribute("aria-invalid", $("contextError").hidden ? "false" : "true");
}

/* The name field follows the folder: for an existing Agent Context it shows the
   name it already has, read-only and secondary; for a new folder it is the
   required, editable project name. */
function applyStartMode() {
  const nameField = $("newProjectName");
  const hint = $("newProjectNameHint");
  const label = $("newProjectNameLabel");
  if (startPeek && startPeek.has_context) {
    nameField.readOnly = true;
    nameField.value = startPeek.name || "";
    nameField.setAttribute("aria-required", "false");
    nameField.classList.add("secondary");
    if (label) label.textContent = "Name";
    if (hint) hint.textContent = startPeek.incomplete
      ? "This folder holds authoritative/ but no context map yet, so there is nothing to create. "
        + "Open it to see what it needs; opening writes nothing in it."
      : "An Agent Context is already here, so there is nothing to create. "
        + (startPeek.name ? "Opening keeps its name; change it later in Settings."
          : "Opening will show its state.");
  } else {
    // Leaving an existing context drops the name it filled in, so a new folder
    // starts from an empty, editable field rather than the old context's name.
    if (nameField.readOnly) nameField.value = "";
    nameField.readOnly = false;
    nameField.classList.remove("secondary");
    nameField.setAttribute("aria-required", "true");
    if (label) label.textContent = "Project name (required)";
    if (hint) hint.textContent = startPeek
      ? "No Agent Context here yet, so there is nothing to open. Name the project to create one; it titles the map agents read."
      : "Names a new Agent Context; it titles the map agents read.";
  }
  syncStartForms();
}

async function peekFolder() {
  const path = fieldValue("contextPath");
  if (!path) { startPeek = null; applyStartMode(); return; }
  try { startPeek = await call("/api/peek", { path }); }
  catch (err) { startPeek = null; }
  applyStartMode();
}

/* Agent Contexts this computer has opened before, one click to fill the folder. */
function renderStart() {
  renderDiagnostics("openDiagnostics");
  const box = $("recentContexts");
  box.textContent = "";
  if (state.closed_because) showFieldError("contextError", state.closed_because);
  const legacy = legacyNotice();
  if (legacy) box.appendChild(legacy);
  const recent = state.recent || [];
  if (!recent.length) return;
  box.appendChild(el("div", { class: "recent-head" }, [
    el("h3", { id: "recentTitle", text: "Recent" }),
    el("button", { type: "button", class: "btn small", id: "btnClearRecent", text: "Clear",
      "aria-label": "Clear the Recent list", onclick: clearRecent })]));
  box.appendChild(el("ul", { class: "recent", "aria-labelledby": "recentTitle" }, recent.map((p) => el("li", {}, [
    el("button", { type: "button", class: "linkish", text: p, onclick: () => {
      $("contextPath").value = p; showFieldError("contextError", ""); $("contextPath").focus(); peekFolder();
    } })]))));
}

/* Clear forgets only the list: every Agent Context, open or not, and its
   private state stay as they are. Opening one again lists it again. */
async function clearRecent() {
  try {
    await call("/api/recent/clear", {});
    state.recent = (await call("/api/state")).recent || [];
  } catch (err) { toast(err.message, true); return; }
  renderStart();
  $("contextPath").focus();
  toast("Recent list cleared. No Agent Context was changed.");
}

async function browseFolder() {
  let chosen;
  try { chosen = await call("/api/pick-folder", { initial: fieldValue("contextPath") }); }
  catch (err) { toast(err.message, true); return; }
  if (chosen.path) {
    $("contextPath").value = chosen.path;
    showFieldError("contextError", "");
    await peekFolder();  // a chosen existing context fills in its name, read-only
  }
}

async function startAction(button, working, route, body, done) {
  if (!body.path) { showFieldError("contextError", "Choose the Agent Context folder first."); syncStartForms(); return; }
  const label = button.textContent;
  showFieldError("contextError", "");
  startBusy = true;
  button.textContent = working;
  syncStartForms();
  try {
    const data = await call(route, body);
    $("contextPath").value = "";
    $("newProjectName").value = "";
    startPeek = null; applyStartMode();
    closeDocument(); resetIntake(); closeReview();
    currentView = "governing";
    await refresh();
    if (done) done(data);
  } catch (err) {
    showFieldError("contextError", err.message);
  } finally {
    startBusy = false;
    button.textContent = label;
    syncStartForms();
  }
}

/* Typing a path resets to the undecided state; committing it (blur/Enter,
   Browse, or a recent choice) peeks to tell open from create and fill a name. */
$("contextPath").addEventListener("input", () => {
  showFieldError("contextError", ""); startPeek = null; applyStartMode();
});
$("contextPath").addEventListener("change", () => { showFieldError("contextError", ""); peekFolder(); });
$("newProjectName").addEventListener("input", () => { showFieldError("contextError", ""); syncStartForms(); });
/* Enter opens: the action that changes nothing. Creating is always its own click. */
$("contextPath").addEventListener("keydown", (e) => { if (e.key === "Enter" && !$("btnOpen").disabled) $("btnOpen").click(); });
$("btnBrowse").addEventListener("click", browseFolder);
$("btnOpen").addEventListener("click", (event) => startAction(event.currentTarget, "Opening…", "/api/open",
  { path: fieldValue("contextPath") }));
$("btnCreate").addEventListener("click", (event) => startAction(event.currentTarget, "Creating…", "/api/create",
  { path: fieldValue("contextPath"), project_name: fieldValue("newProjectName") },
  (data) => toast(`Created the Agent Context “${data.name}” at ${data.created}. Git is untouched.`
    + ((data.follow_up || []).length ? " " + data.follow_up.join(" ") : ""), (data.follow_up || []).length > 0)));
/* Open Agent Context… and the Charter wordmark lead to the same place: the
   Open or Create Agent Context view. */
const openContextView = () => { closeDocument(); closeReview(); renderStart(); show("open"); };
$("btnSwitch").addEventListener("click", openContextView);
$("wordmark").addEventListener("click", openContextView);
$("btnViewContext").addEventListener("click", viewContext);
$("btnRebuildContext").addEventListener("click", startRebuild);
/* The disclosures written into the page itself; those built later wire their own. */
document.querySelectorAll(".disclosure-toggle").forEach((b) => b.addEventListener("click", () => toggleDisclosure(b)));

$("btnPick").addEventListener("click", () => $("file").click());
/* Choose another file: the picker again; the file chosen replaces the conversion. */
$("btnChooseAnother").addEventListener("click", () => { $("file").value = ""; $("file").click(); });
$("file").addEventListener("change", (e) => { if (e.target.files[0]) stageFile(e.target.files[0]); });
const drop = $("drop");
["dragenter", "dragover"].forEach((evt) => drop.addEventListener(evt, (e) => {
  e.preventDefault(); drop.classList.add("over");
}));
["dragleave", "drop"].forEach((evt) => drop.addEventListener(evt, (e) => {
  e.preventDefault(); drop.classList.remove("over");
}));
drop.addEventListener("drop", (e) => { if (e.dataTransfer.files[0]) stageFile(e.dataTransfer.files[0]); });

$("btnPreviewIntake").addEventListener("click", () => {
  const request = intakeRequest();
  if (!request.title) { toast("Give the document a title.", true); return; }
  planFor("add", request, { applyLabel: "File as candidate" });
});

refresh().catch((err) => toast(err.message, true));
