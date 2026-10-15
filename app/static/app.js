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
    ...actions.map((a) => el("button", { type: "button", class: "linkish toast-action", text: a.label,
      onclick: () => { node.remove(); a.onclick(); } })),
    isError ? el("button", { type: "button", class: "linkish toast-dismiss", text: "Dismiss",
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

/* ---------------------------------------------------- information controls */

/* A small “i” button beside a heading; its popup holds the explanation that
   would otherwise sit on the page. Keyboard focus or hover shows it. A click
   (or Enter, or Space) keeps it open until it is clicked again, Escape is
   pressed, focus leaves it, or someone clicks elsewhere. Hover is only a
   convenience: everything works from the keyboard, the popup can be hovered
   without closing, and aria-expanded says whether it is showing. `open` and
   `onToggle` let a popup that is redrawn stay open. */
const within = (node, root) => { for (let n = node; n; n = n.parentNode) if (n === root) return true; return false; };

function wireInfoTip(wrap, options = {}) {
  const button = wrap.querySelector(".info-toggle");
  const pop = wrap.querySelector(".info-pop");  // not yet in the document when drawn by script
  let pinned = !!options.open;
  let focused = false;
  let hovered = false;
  const sync = () => {
    const open = pinned || focused || hovered;
    button.setAttribute("aria-expanded", String(open));
    pop.hidden = !open;
  };
  const pin = (on) => {
    if (pinned === on) return;
    pinned = on;
    if (options.onToggle) options.onToggle(on);
  };
  const close = () => { pin(false); focused = false; hovered = false; sync(); };
  wrap.infoClose = () => { if (button.getAttribute("aria-expanded") === "true") close(); };
  button.addEventListener("click", () => {
    if (pinned) close(); else { pin(true); sync(); }
  });
  button.addEventListener("focus", () => { focused = true; sync(); });
  wrap.addEventListener("focusout", (ev) => {
    if (wrap.isConnected === false) return;  // redrawn away, not left: the new copy keeps the state
    if (ev.relatedTarget && within(ev.relatedTarget, wrap)) return;
    close();
  });
  wrap.addEventListener("mouseenter", () => { hovered = true; sync(); });
  wrap.addEventListener("mouseleave", () => { hovered = false; sync(); });
  wrap.addEventListener("keydown", (ev) => {
    if (ev.key !== "Escape" || button.getAttribute("aria-expanded") !== "true") return;
    ev.preventDefault();
    close();
    button.focus();
  });
  sync();
  return wrap;
}

/* The same control, built for a region that is drawn by script. */
function infoTip(label, content, options = {}) {
  const id = options.id || "info-" + (++disclosureSeq);
  const wrap = el("div", { class: "info-wrap" + (options.class ? " " + options.class : "") }, [
    el("button", { type: "button", class: "info-toggle", id: options.buttonId || null, "aria-label": label,
      "aria-expanded": "false", "aria-controls": id }, [el("span", { "aria-hidden": "true", text: "i" })]),
    el("div", { class: "info-pop", id, hidden: "" }, content),
  ]);
  return wireInfoTip(wrap, options);
}

/* A click anywhere else closes whichever popup is showing. */
document.addEventListener("click", (ev) => {
  document.querySelectorAll(".info-wrap").forEach((w) => {
    if (w.infoClose && !within(ev.target, w)) w.infoClose();
  });
});

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
const issueItem = (i) => el("li", { class: i.level }, [el("span", {}, [
  el("code", { text: i.path || "folder" }),
  ...withCode(` — ${i.message}${i.fix ? " " + i.fix : ""}`),
])]);

/* Instructional, never an example value: an empty scope field must look empty,
   and submits nothing unless something is typed into it. */
const SCOPE_PLACEHOLDER = "Describe what this document governs or applies to";
/* What scope is for, said at every scope field: the short sentence stays in
   view, and the fuller explanation is behind “About scope”. */
const SCOPE_HINT = "A short routing summary shown in AGENT-CONTEXT.md; it does not replace this document's rules.";
const scopeInfoContent = () => [
  el("p", { text: "Scope is a short routing summary: the decisions, behavior or project area this "
    + "document governs." }),
  el("p", { text: "It appears in AGENT-CONTEXT.md beside the document's title, so a person or an agent "
    + "can tell which governing documents to read for a task." }),
  el("p", { text: "It does not replace, summarize or override the document's own rules. Agents still "
    + "need to read the document itself." }),
  el("p", { text: "You decide whether the wording describes the document accurately. Charter "
    + "does not write, judge or approve it." }),
];
const scopeInfo = () => infoTip("About scope", scopeInfoContent(), { class: "scope-info" });

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
    /* An information control sits beside the label it explains. */
    const head = f.info ? el("div", { class: "label-row" }, [label, f.info()]) : label;
    const field = el("div", { class: "field" }, f.type === "checkbox" ? [label] : [head, input]);
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
function showFormPanel(title, inner) {
  const panel = $("review");
  panelOpener = (typeof document !== "undefined" && document.activeElement
                 && document.activeElement.focus) ? document.activeElement : null;
  panel.textContent = "";
  const heading = el("h3", { text: title, tabindex: "-1" });
  panel.appendChild(el("section", { class: "review" }, [
    el("header", {}, [heading,
      el("button", { class: "close", text: "Close", onclick: closePanel })]),
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

function renderShell() {
  const open = state.open;
  const s = open ? state.status : null;
  $("projectName").textContent = open ? state.project_name : "no Agent Context open";
  $("metaRoot").textContent = open ? state.root : "—";
  $("metaAgents").textContent = open ? (s.agents_served ? "Served" : "Refused") : "—";
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

  $("barPath").textContent = open ? state.root : "No Agent Context open";
  const bar = $("barState");
  bar.textContent = "";
  if (open) bar.appendChild(s.agents_served ? chip("Agents are served", "ok") : chip("Agents are refused", "stale"));
  $("btnSwitch").hidden = !open;
  syncStartForms(!!state.folder_picker);
  renderContextStatus();
}

/* Git is the person's own and secondary: a compact, read-only summary in the
   rail — the branch, and the count of context files Git reports as changed —
   with the files themselves only on request. A Git failure is said as one,
   never shown as no changes. */
const GIT_BRANCH_NOTE = { "not-checkout": "Not a Git checkout", unavailable: "Git unavailable" };
const UNREAD = "Could not be read";

function renderGit() {
  const git = state.open ? state.status.git : null;
  const known = !!git && git.state === "checkout";
  const counted = known || (!!git && git.state === "unreadable");
  $("metaGitLabel").hidden = $("metaBranch").hidden = !git;
  $("metaChangedLabel").hidden = $("metaChanged").hidden = !counted;
  const changed = known ? git.changed : [];
  const toggle = $("gitDetailsToggle");
  toggle.hidden = !changed.length;
  if (!changed.length) closeGitDetails(false);
  $("gitChanged").textContent = "";
  if (!git) return;
  $("metaBranch").textContent = GIT_BRANCH_NOTE[git.state] || git.branch || UNREAD;
  $("metaChangedCount").textContent = known ? String(changed.length) : UNREAD;
  toggle.setAttribute("aria-label", changed.length === 1 ? "Show the changed context file"
    : `Show the ${changed.length} changed context files`);
  changed.forEach((p) => $("gitChanged").appendChild(el("li", {}, [el("code", { text: p })])));
}

/* The details open and close only by the person's own action: the button,
   Escape (focus returns to the button), a click elsewhere, or leaving it. */
const gitDetailsOpen = () => $("gitDetailsToggle").getAttribute("aria-expanded") === "true";

function closeGitDetails(refocus) {
  $("gitDetailsToggle").setAttribute("aria-expanded", "false");
  $("gitDetailsPanel").hidden = true;
  if (refocus) $("gitDetailsToggle").focus();
}

$("gitDetailsToggle").addEventListener("click", () => {
  if (gitDetailsOpen()) { closeGitDetails(false); return; }
  $("gitDetailsToggle").setAttribute("aria-expanded", "true");
  $("gitDetailsPanel").hidden = false;
  if ($("gitDetailsPanel").scrollIntoView) $("gitDetailsPanel").scrollIntoView({ block: "nearest" });
});
$("gitDetails").addEventListener("focusout", (ev) => {
  if (ev.relatedTarget && !within(ev.relatedTarget, $("gitDetails"))) closeGitDetails(false);
});
document.addEventListener("click", (ev) => {
  if (gitDetailsOpen() && !within(ev.target, $("gitDetails"))) closeGitDetails(false);
});

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
      el("h3", {}, withCode(s.headline)),
    ]);
    const errors = s.issues.filter((i) => i.level === "error");
    if (errors.length) {
      const list = el("ul", { class: "issues" });
      errors.forEach((i) => list.appendChild(issueItem(i)));
      card.appendChild(list);
    }
    if (s.strays.length) {
      card.appendChild(el("p", { class: "hint", id: "straysNote", text: "Charter never moves "
        + "or deletes a file it did not write. Move each file listed out of the folder, or delete it, "
        + "then choose any page in the navigation: Charter checks the folder again each time." }));
    }
    if (s.rebuild.available) {
      card.appendChild(el("div", { class: "actions" }, [el("button", { class: "btn", id: "btnRebuildFromStatus",
        text: "Rebuild Agent Context…", onclick: startRebuild })]));
    } else if (!s.interrupted && s.rebuild.blockers.length && errors.some((i) => i.kind === "generated")) {
      card.appendChild(el("p", { class: "hint", id: "rebuildBlockedNote", text: "Rebuild Agent Context is offered "
        + "once these are corrected. It never changes or repairs a governing document." }));
    }
    parts.push(card);
  }
  const o = s.outside;
  if (o.changed_outside) {
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
    // The archive is history: compact rows, not full document cards.
    docs.forEach((d) => list.appendChild(key === "archive" ? archiveRow(d) : docRow(d)));
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

/* The three lists: the view (and list) each is shown in, its count, and the
   words a screen reader hears for that count. */
const CONTEXT_LISTS = [
  { key: "governing", tally: "tallyGoverning", noun: ["governing document", "governing documents"] },
  { key: "candidates", tally: "tallyCandidates", noun: ["authority candidate", "authority candidates"] },
  { key: "archive", tally: "tallyArchive", noun: ["archived document", "archived documents"] },
];
const countOf = (n, [one, many]) => `${n} ${n === 1 ? one : many}`;

function documentGroups() {
  const docs = state.documents || [];
  return {
    governing: docs.filter((d) => d.kind === "governing"),
    candidates: docs.filter((d) => d.kind === "candidate"),
    archive: docs.filter((d) => d.kind === "archived"),
  };
}

/* The map's state is claimed only as far as it was checked: while a governing
   document has a problem, the map is not compared at all. */
function renderContextMap() {
  const s = state.status;
  const generated = s.issues.filter((i) => i.level === "error" && i.kind === "generated");
  const box = $("contextMapState");
  box.textContent = "";
  let label;
  if (s.agents_served) label = chip("Matches the governing documents", "ok");
  else if (generated.length) label = chip("Does not match the governing documents", "stale");
  else label = chip("Not checked until the problems above are corrected", null);
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
  const on = (state.agent_guidance || []).filter((g) => g.on).map((g) => g.label);
  $("agentGuidanceSummary").textContent = `Agent guidance in the map: ${on.length ? on.join(", ") : "none"}.`
    + " Change it in Settings.";
}

/* A governing change needs a valid, clean Agent Context to start from. */
const canChangeGoverning = () => state.status.agents_served;
const NOT_VALID = "Change-set actions are unavailable until the Agent Context is valid and clean: "
  + "see the status above.";
/* The one visible line, above each list, saying why its change-set actions are
   disabled; each disabled action is described by it. */
const UNAVAILABLE_NOTE = { governing: "governingUnavailable", candidate: "candidatesUnavailable" };

const SOURCE_LABEL = { revise: "Revise", proposal: "Agent Proposal", create: "Create candidate" };

function competingNotice(co) {
  /* "with a count when more than one other candidate exists." */
  return "Another revision candidate exists for this document." + (co > 1 ? ` ${co} others in all.` : "");
}

/* The archive is history, shown compactly: one line per document — its title,
   when it was archived, and Read — not a full card. It governs nothing and is
   private local state (never agent-facing). */
function archiveRow(doc) {
  return el("div", { class: "doc archive-row is-retired" }, [
    el("div", { class: "archive-line" }, [
      el("span", { class: "title", text: doc.title }),
      doc.updated ? el("span", { class: "archive-date", text: doc.updated }) : null,
    ]),
    el("div", { class: "actions" }, [
      chip("Archived — not context"),
      el("button", { class: "btn ghost small", text: "Read",
        onclick: (event) => openDocument(doc.path, event.currentTarget) }),
    ]),
  ]);
}

function docRow(doc) {
  const isCandidate = doc.kind === "candidate";
  const meta = el("div", {}, [
    el("div", { class: "title", text: doc.title }),
    el("div", { class: "path", text: doc.path }),
    doc.scope ? el("div", { class: "scope", text: "Scope: " + doc.scope }) : null,
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
    isCandidate && doc.source_kind
      ? el("div", { class: "origin source", text: "Source: " + (SOURCE_LABEL[doc.source_kind] || doc.source_kind) }) : null,
    isCandidate && doc.co_revisions > 0
      ? el("div", { class: "origin competing", text: competingNotice(doc.co_revisions) }) : null,
    /* The "Governing" chip already says a governing document is read by agents;
       only the private location is worth stating, on candidates. */
    doc.governing ? null
      : el("div", { class: "origin location", text: "Private local state on this computer — agents never see it." }),
  ]);
  const governingAction = (text, cls, onclick) => el("button", { class: cls, text, onclick,
    disabled: canChangeGoverning() ? null : "",
    "aria-describedby": canChangeGoverning() ? null : UNAVAILABLE_NOTE[doc.kind] });
  const actions = el("div", { class: "actions" }, [
    doc.kind === "governing" ? chip("Governing", "authority")
      : doc.kind === "candidate" ? chip("Authority candidate — not context", "proposed")
      : chip("Archived — not context"),
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
    doc.kind === "governing" ? governingAction("Change in a change set…", "btn ghost small",
      () => startDocumentChangeSet(doc)) : null,
    doc.kind === "governing" ? governingAction("Withdraw in a change set…", "btn ghost small",
      () => startWithdrawal(doc)) : null,
    doc.kind === "candidate" ? governingAction("Plan a change set…", "btn small primary-action",
      () => startCandidateChangeSet(doc)) : null,
  ]);
  return el("div", {
    class: "doc" + (doc.governing ? " is-authority" : "") + (doc.kind === "archived" ? " is-retired" : ""),
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
  const close = el("button", { class: "close", text: "Close", onclick: closeComparison });
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
  const close = el("button", { class: "close", text: "Close", onclick: closeDocument });
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
  for (const sel of [".rail", "#main"]) {
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
  if (comparing) closeComparison(); else closeDocument();
});
if (document.addEventListener) {
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (gitDetailsOpen()) closeGitDetails(true);  // the rail's Git details, opened last
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
      { name: "scope", label: "Scope — what does it cover?", value: draft.scope,
        placeholder: SCOPE_PLACEHOLDER, hint: SCOPE_HINT, info: scopeInfo },
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
    el("div", { text: `“${draft.title}” keeps governing at ${draft.path}, unchanged, until you revise it `
      + "with the candidate in a change set." }),
  ]);
  review = null;
  formPanel(
    `Revise “${draft.title}”`,
    null,
    [
      { name: "title", label: "Title", value: draft.title },
      { name: "scope", label: "Scope — what does it cover?", value: draft.scope,
        placeholder: SCOPE_PLACEHOLDER, hint: SCOPE_HINT, info: scopeInfo },
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
   or one governing document opens a new change set prefilled with the one
   outcome the person chose here — nothing more. Every other governing
   document is left undecided until the person decides it in the change set,
   where related outcomes can be added before its preview. Nothing here starts
   chosen: a candidate made with Revise… lists the document it was revised
   from first, labelled, as context only — never selected for the person. */
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
const choiceRadio = (name, id, value, disabled) => el("input", { type: "radio", name, id, value,
  disabled: disabled ? "" : null, style: "width:auto" });
const choiceOption = (input, label, hint) => el("label", { class: "choice", for: input.id }, [
  input, el("span", {}, [el("strong", { text: label }), el("span", { class: "hint", text: hint })])]);
const UNDECIDED_NOTE = "Every other governing document stays undecided until you decide it in the change "
  + "set. Nothing changes until you preview the change set and confirm it there.";

/* From a candidate: govern alongside, or revise or replace a governing
   document the person names. */
function startCandidateChangeSet(doc) {
  const target = `${state.authoritative_dir}/${doc.path.split("/").pop()}`;
  const governing = documentGroups().governing;
  const origin = doc.revises_path ? governing.find((d) => d.path === doc.revises_path) : null;
  const inner = el("div", { class: "inner" });
  inner.appendChild(el("div", { class: "note authority",
    text: "Choose what this candidate does. A new change set opens with that one outcome." }));
  inner.appendChild(el("dl", { class: "scope-compare" }, [
    el("dt", { text: "Its scope" }),
    el("dd", { id: "startCandidateScope", class: doc.scope ? "" : "empty",
      text: doc.scope || "No scope stated" }),
  ]));
  inner.appendChild(el("p", { class: "hint", text: "To change its title, scope or text first, use Edit on the candidate." }));

  const none = !governing.length;
  const alongside = choiceRadio("startOutcome", "startAlongside", "alongside", false);
  const revise = choiceRadio("startOutcome", "startRevise", "revise", none);
  const replace = choiceRadio("startOutcome", "startReplace", "replace", none);
  const ordered = origin ? [origin].concat(governing.filter((d) => d !== origin)) : governing;
  const chosen = el("select", { id: "startTarget" }, [
    el("option", { value: "", text: "Choose the governing document" })]
    .concat(ordered.map((d) => el("option", { value: d.path,
      text: `${d.title} (${d.path})` + (d === origin ? ` — ${REVISED_FROM}` : "") }))));
  chosen.value = "";
  const currentScope = el("dd", { id: "startCurrentScope" });
  const currentLabel = el("dt", { text: "Current scope" });
  const outcome = el("p", { class: "scope-outcome", id: "startScopeOutcome", role: "status" });
  const compare = el("div", { id: "startScopeCompare", hidden: "" }, [
    el("dl", { class: "scope-compare" }, [currentLabel, currentScope]), outcome]);
  const syncScopes = () => {
    const old = governing.find((d) => d.path === chosen.value);
    compare.hidden = !old;
    if (!old) return;
    const proposed = (doc.scope || "").trim();
    const current = (old.scope || "").trim();
    currentLabel.textContent = `Current scope of “${old.title}”`;
    currentScope.textContent = current || "No scope stated";
    currentScope.className = current ? "" : "empty";
    outcome.textContent = proposed
      ? `If the change set is applied, AGENT-CONTEXT.md shows: “${proposed}”.`
      : current
        ? `The candidate has no scope, so it would inherit “${old.title}”'s current scope: “${current}”.`
        : "Neither document states a scope, so AGENT-CONTEXT.md would say the scope is not stated.";
  };
  const targetDetail = el("div", { class: "replace-detail", id: "startTargetDetail", hidden: "" }, [
    el("div", { class: "field" }, [
      el("label", { for: "startTarget", text: "Governing document" }), chosen,
      el("p", { class: "hint", id: "startTargetHint", text: origin
        ? `Listed first because this candidate was made with Revise… from “${origin.title}”. Nothing is `
          + "chosen for you: choose the document yourself."
        : "One document. Charter does not guess it from names or version numbers." }),
    ]),
    compare,
  ]);
  const sync = () => { targetDetail.hidden = !(revise.checked || replace.checked); syncScopes(); };
  [alongside, revise, replace].forEach((r) => r.addEventListener("change", sync));
  chosen.addEventListener("change", syncScopes);
  const unavailable = "Nothing governs yet, so there is nothing to revise or replace.";
  inner.appendChild(el("fieldset", { class: "field start-mode", id: "startOutcomes" }, [
    el("legend", { text: "What should this candidate do?" }),
    choiceOption(alongside, "Govern alongside",
      `Everything that governs today keeps governing. It would be written to ${target}.`),
    choiceOption(revise, "Revise a governing document with this candidate",
      none ? unavailable : "This candidate is a new version of one governing document, and takes its path."),
    choiceOption(replace, "Replace a governing document with this candidate",
      none ? unavailable : "This candidate takes over from a different governing document, at its path."),
    targetDetail,
  ]));
  inner.appendChild(el("p", { class: "hint", id: "startUndecided", text: UNDECIDED_NOTE }));
  sync();
  inner.appendChild(el("div", { class: "actions" }, [
    el("button", { class: "btn", id: "btnOpenChangeSet", text: "Open change set", onclick: () => {
      if (alongside.checked) { startChangeSet({ alongside: doc.path }); return; }
      const picked = revise.checked ? "revise" : replace.checked ? "replace" : "";
      if (!picked) { toast("Choose what this candidate does.", true); return; }
      if (!chosen.value) { toast(`Choose the governing document to ${picked}.`, true); return; }
      startChangeSet({ document: chosen.value, outcome: picked, candidate: doc.path });
    } }),
    el("button", { class: "btn ghost", text: "Cancel", onclick: closeReview }),
  ]));
  review = null;
  showFormPanel(`Plan a Change Set with “${doc.title}”`, inner);
}

/* From a governing document: revise or replace it with a candidate the person
   names, or withdraw it. A person with no candidate for it yet is pointed to
   Revise…, which files one. */
function startDocumentChangeSet(doc) {
  const candidates = documentGroups().candidates;
  const made = candidates.filter((c) => c.revises_path === doc.path);
  const ordered = made.concat(candidates.filter((c) => made.indexOf(c) === -1));
  const none = !candidates.length;
  const inner = el("div", { class: "inner" });
  inner.appendChild(el("div", { class: "note authority",
    text: `“${doc.title}” governs at ${doc.path}. Choose what happens to it. A new change set opens with that one outcome.` }));
  const revise = choiceRadio("docOutcome", "docRevise", "revise", none);
  const replace = choiceRadio("docOutcome", "docReplace", "replace", none);
  const withdraw = choiceRadio("docOutcome", "docWithdraw", "withdraw", false);
  const labels = candidateLabels(ordered);
  const chosen = el("select", { id: "docCandidate" }, [
    el("option", { value: "", text: "Choose the authority candidate" })]
    .concat(ordered.map((c) => el("option", { value: c.path, text: labels[c.path] }))));
  chosen.value = "";
  const candidateDetail = el("div", { class: "replace-detail", id: "docCandidateDetail", hidden: "" }, [
    el("div", { class: "field" }, [
      el("label", { for: "docCandidate", text: "Authority candidate" }), chosen,
      el("p", { class: "hint", text: "Nothing is chosen for you: choose the candidate yourself." }),
    ]),
  ]);
  const sync = () => { candidateDetail.hidden = !(revise.checked || replace.checked); };
  [revise, replace, withdraw].forEach((r) => r.addEventListener("change", sync));
  const needCandidate = "There is no authority candidate yet. Use Revise… to file one from this document first.";
  inner.appendChild(el("fieldset", { class: "field start-mode", id: "docOutcomes" }, [
    el("legend", { text: `What should happen to “${doc.title}”?` }),
    choiceOption(revise, "Revise it with a candidate",
      none ? needCandidate : "A new version of it, filed as a candidate, takes its path."),
    choiceOption(replace, "Replace it with a candidate",
      none ? needCandidate : "A different candidate takes over at its path."),
    choiceOption(withdraw, "Withdraw it", "It stops governing and becomes an authority candidate again."),
    candidateDetail,
  ]));
  if (none) {
    inner.appendChild(el("div", { class: "actions" }, [
      el("button", { class: "btn ghost small", id: "docReviseFirst", text: "Revise this document…",
        onclick: () => startRevision(doc) })]));
  }
  inner.appendChild(el("p", { class: "hint", text: UNDECIDED_NOTE }));
  inner.appendChild(el("div", { class: "actions" }, [
    el("button", { class: "btn", id: "btnOpenChangeSet", text: "Open change set", onclick: () => {
      if (withdraw.checked) { startChangeSet({ document: doc.path, outcome: "withdraw" }); return; }
      const picked = revise.checked ? "revise" : replace.checked ? "replace" : "";
      if (!picked) { toast(`Choose what happens to “${doc.title}”.`, true); return; }
      if (!chosen.value) { toast(`Choose the candidate to ${picked} it with.`, true); return; }
      startChangeSet({ document: doc.path, outcome: picked, candidate: chosen.value });
    } }),
    el("button", { class: "btn ghost", text: "Cancel", onclick: closeReview }),
  ]));
  review = null;
  showFormPanel(`Change “${doc.title}” in a Change Set`, inner);
}

/* Withdrawing is chosen on the governing document itself: the change set
   opens with that one outcome, and is previewed and confirmed there. */
function startWithdrawal(doc) {
  return startChangeSet({ document: doc.path, outcome: "withdraw" });
}

function startRetirement(doc) {
  planFor("retire", { candidate: doc.path }, { applyLabel: "Retire", applyClass: "btn danger" });
}

/* ------------------------------------------------------------------ intake */

/* Create candidate asks only for a title and a scope: every document is filed as
   a candidate, under a name the server picks. */
function renderIntakeForm() {
  $("candidateNote").textContent =
    "Filed as an authority candidate in private local state on this computer — not context.";
  /* The drop target, the file picker and the hint offer PDF only while it can be converted. */
  $("dropText").textContent = state.pdf_support
    ? "Drop a PDF, Word document, Markdown or text file here"
    : "Drop a Word document, Markdown or text file here";
  $("file").setAttribute("accept", (state.pdf_support ? ".pdf," : "") + ".docx,.md,.markdown,.txt,.text");
  $("dropHint").textContent = state.pdf_support
    ? "PDF, DOCX, Markdown and plain text."
    : "DOCX, Markdown and plain text. PDF needs the optional pypdf package.";
}

/* A locked step cannot be reached at all — not by pointer, keyboard or screen
   reader — and says what it is waiting for; its heading stays readable. */
function unlockIntake(done) {
  ["stepConvert", "stepName"].forEach((id) => {
    $(id).classList.toggle("locked", !done);
    setInert($(id + "Body"), !done);
  });
  $("stepFile").dataset.done = String(done);
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
      $("stagedInfo").appendChild(el("div", { class: "note",
        text: `${staged.filename} — ${staged.kind}, ${(staged.bytes / 1024).toFixed(1)} kB, `
          + `sha256 ${staged.sha256.slice(0, 12)}…` }));
      $("convertNotes").textContent = "";
      staged.notes.forEach((n) => $("convertNotes").appendChild(el("div", { class: "note" }, withCode(n))));
      $("markdown").value = staged.markdown;
      $("title").value = staged.suggested_title;
      $("scope").value = staged.suggested_scope || "";
      showFrontMatterNote(staged.front_matter);
      unlockIntake(true);
      $("stepConvert").dataset.done = "true";
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
   updates or retires an authority candidate, after a preview; rejecting one
   records why. An agent's name, reason and expected impact are its claims. */
const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const OPERATION_WORD = { create: "Create", amend: "Amend", retire: "Retire" };
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

function impactBlock(impact) {
  if (impact === undefined || impact === null || impact === "") return null;
  const text = typeof impact === "string" ? impact : JSON.stringify(impact, null, 2);
  return disclosure("Expected context impact (the agent's assessment, advisory)",
    [el("pre", { class: "code impact", text })]);
}

function proposalCard(p) {
  const target = el("code", { class: "proposal-target", text: p.target_path });
  const card = el("article", { class: "proposal" + (p.stale ? " is-stale" : ""), "data-id": p.proposal_id }, [
    el("header", {}, [
      chip(OPERATION_WORD[p.operation] || p.operation, "proposed"), target,
      p.stale ? chip("Stale", "stale") : null,
    ]),
    el("div", { class: "proposal-meta", text: `${p.proposal_id} · from ${p.agent || "an unnamed agent"} `
      + `(self-reported) · ${p.source === "imported" ? "imported" : "received"} ${relativeTime(p.received)}` }),
    el("div", { class: "proposal-reason" }, [el("strong", { text: "Reason: " }), document.createTextNode(p.reason)]),
  ]);
  const impact = impactBlock(p.expected_context_impact);
  if (impact) card.appendChild(impact);
  if (p.stale) {
    card.appendChild(el("div", { class: "note warn", text: p.stale_reasons.join(" ")
      + " It cannot be accepted as written: reject it, or ask the agent to propose again." }));
  }
  card.appendChild(el("div", { class: "actions" }, [
    el("button", { class: "btn small", text: "Review and accept…", disabled: p.stale ? "" : null,
      onclick: () => planFor("accept-proposal", { proposal_id: p.proposal_id },
        { applyLabel: p.operation === "retire" ? "Accept: retire the candidate" : "Accept as candidate" }) }),
    el("button", { class: "btn ghost small", text: "Reject…", onclick: () => startProposalRejection(p) }),
  ]));
  return card;
}

function startProposalRejection(p) {
  formPanel(
    `Reject ${p.proposal_id}`,
    { text: "Rejecting changes nothing else. The reason is kept with the proposal, privately.", tone: "note" },
    [{ name: "reason", label: "Why", type: "textarea", rows: 3, value: "" }],
    "Preview the rejection",
    (values) => planFor("reject-proposal", { proposal_id: p.proposal_id, reason: values.reason },
      { applyLabel: "Reject proposal", applyClass: "btn danger" }),
  );
}

function unexpectedRow(u) {
  return el("div", { class: "doc unexpected-record" }, [
    el("div", {}, [
      el("div", { class: "title", text: u.name }),
      el("div", { class: "origin", text: `${u.why} Untrusted local material — not a proposal. `
        + `${(u.bytes / 1024).toFixed(1)} kB.` }),
    ]),
    el("div", { class: "actions" }, [
      chip("Unexpected — not a proposal", "stale"),
      el("button", { class: "btn ghost small", text: "View contents", onclick: () => viewUnexpected(u, false) }),
      el("button", { class: "btn ghost small", text: "Import a copy…", onclick: () => viewUnexpected(u, true) }),
    ]),
  ]);
}

async function viewUnexpected(u, asImport) {
  let got;
  try { got = await call("/api/proposals/unexpected", { name: u.name }); } catch (err) { toast(err.message, true); return; }
  if (asImport) { startImport(got.text); return; }
  review = null;
  showFormPanel(`Unexpected Local Record ${u.name}`, el("div", { class: "inner" }, [
    el("div", { class: "note warn", text: "Untrusted local material, shown as text. It is not a proposal, "
      + "and viewing it changes nothing." }),
    el("pre", { class: "code", id: "unexpectedText", text: got.text }),
  ]));
}

/* Import: a proposal an agent returned as JSON, checked exactly as `charter
   propose` checks it, then filed only when the person confirms. */
function startImport(prefill) {
  review = null;
  const box = el("textarea", { id: "importJson", rows: 12, spellcheck: "false" });
  box.value = prefill || "";
  const result = el("div", { id: "importResult" });
  const inner = el("div", { class: "inner" }, [
    el("div", { class: "note", text: "Paste the one JSON proposal an agent returned when it could not file "
      + "it. It is checked exactly as `charter propose` checks it, and filed only when you confirm." }),
    el("div", { class: "field" }, [el("label", { for: "importJson", text: "Proposal JSON" }), box]),
    el("div", { class: "actions" }, [el("button", { class: "btn", id: "btnCheckImport", text: "Check",
      onclick: () => checkImport(box.value, result) })]),
    result,
  ]);
  showFormPanel("Import Proposal", inner);
}

async function checkImport(text, result) {
  result.textContent = "";
  let checked;
  try { checked = await call("/api/proposals/import/check", { json: text }); }
  catch (err) { result.appendChild(el("div", { class: "note warn" }, withCode(err.message))); return; }
  if (!checked.ok) {
    result.appendChild(el("div", { class: "note warn", text: "It would be refused, and is not filed:" }));
    result.appendChild(el("ul", { class: "issues", id: "importProblems" }, checked.problems.map((p) =>
      el("li", { class: "error" }, [el("code", { text: p.field || "proposal" }), ...withCode(` — ${p.message}`)]))));
    return;
  }
  const s = checked.summary;
  result.appendChild(el("div", { class: "note", id: "importSummary",
    text: `${OPERATION_WORD[s.operation]} ${s.target_path}, from ${s.agent} (self-reported): ${s.reason}` }));
  result.appendChild(el("div", { class: "actions" }, [el("button", { class: "btn", id: "btnFileImport",
    text: "File as imported proposal", onclick: async (event) => {
      const btn = event.currentTarget;
      btn.disabled = true;
      let filed;
      try { filed = await call("/api/proposals/import", { json: text, confirm: true }); }
      catch (err) { btn.disabled = false; toast(err.message, true); return; }
      if (filed.result !== "pending") {
        btn.disabled = false;  // the person can correct and try again
        toast(filed.result === "refused" ? filed.problems.map((p) => p.message).join(" ") : filed.problem.message, true);
        return;
      }
      closeReview();
      await refreshQuiet();
      toast(`Filed ${filed.proposal_id} as an imported proposal, for review. It is not context.`);
    } })]));
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

/* Connect with MCP, under the view's heading: one instruction, a PATH
   prerequisite when needed, the host choice (its legend for assistive
   technology only), the chosen host's setup, and the optional instruction
   for the agent as a small action. */
function connectMcp(c) {
  const mcp = el("section", { class: "connect-method connect-mcp", id: "connectMcp",
    "aria-labelledby": "connectMcpTitle" });
  if (c.connect === "files-only") {
    mcp.appendChild(el("div", { class: "note warn", id: "connectMcpLimitation" }, withCode(c.mcp_limitation)));
    return mcp;
  }
  mcp.appendChild(el("p", { id: "connectMcpInstruction",
    text: "Configure the Charter MCP server for your agent." }));
  if (c.connect === "needs-path") {
    mcp.appendChild(el("div", { class: "connect-prerequisite", id: "connectPrerequisite" }, [
      el("div", { class: "note warn", id: "connectLauncher" }, withCode(c.launcher.note)),
      copyBlock("connectAddToPath", "Before Connecting: Add Charter to Your PATH", c.launcher.fix,
        "Copy command", c.launcher.restart),
    ]));
  }
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
  mcp.appendChild(el("fieldset", { class: "connect-hosts", id: "connectHosts" },
    [el("legend", { class: "sr-only", text: "Choose an agent host" })].concat(radios)));
  CONNECT_HOSTS.forEach(([key]) => mcp.appendChild(panels[key]));
  /* The startup pointer: where it goes, then the text to copy. */
  mcp.appendChild(el("section", { class: "connect-instruct", id: "connectPointerSection",
    "aria-labelledby": "connectPointerTitle" }, [
    el("h3", { class: "connect-label", id: "connectPointerTitle", text: "Instruct Your Agent to Use Charter" }),
    el("p", { class: "hint", id: "connectPointerNote" }, withCode(c.pointer_note)),
    copyBlock("connectPointer", "", c.pointer, "Copy startup pointer", ""),
  ]));
  return mcp;
}

/* File access: the other route, a section whose heading is its own closed
   toggle. It starts open only when it is the one route offered. */
function connectFiles(c, open) {
  const body = el("div", { class: "disclosure-body", id: "connectFilesDetails", hidden: open ? null : "" }, [
    el("p", { class: "hint", id: "connectFilesNote" }, withCode(c.files_note)),
    copyBlock("connectInstruction", "", c.instruction, "Copy agent instruction", "")]);
  const toggle = el("button", { type: "button", class: "disclosure-toggle", id: "connectFilesToggle",
    "aria-expanded": String(!!open), "aria-controls": "connectFilesDetails", text: "Connect Agents with File Access",
    onclick: () => toggleDisclosure(toggle) });
  return el("section", { class: "connect-method connect-files", id: "connectOther" }, [
    el("h2", {}, [toggle]), el("div", { class: "disclosure" }, [body])]);
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
  box.appendChild(connectMcp(c));
  box.appendChild(el("section", { class: "connect-method connect-test", id: "connectVerify",
    "aria-labelledby": "connectTestTitle" }, [
    el("h3", { class: "connect-label", id: "connectTestTitle", text: "Test the Connection" }),
    copyBlock("connectVerifyPrompt", "", c.verify_prompt, "Copy prompt", ""),
  ]));
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
  rebuild: "Rebuild Agent Context", settings: "Settings", "accept-proposal": "Accept Agent Proposal",
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
    el("fieldset", { class: "field" }, [el("legend", { text: "Agent guidance" })].concat(boxes)),
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
  if (plan.kind === "changeset" && options.changeSet) inner.appendChild(governingSetCompare(options.changeSet));
  else if (plan.governing_change && plan.after) inner.appendChild(governingBeforeAfter(plan));

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
      el("p", { class: "hint", text: "This changes the governing context agents read, so it is confirmed in words." }),
    ]));
  }

  inner.appendChild(el("div", { class: "actions" }, [
    el("button", {
      class: options.applyClass || (plan.governing_change ? "btn authority" : "btn"),
      id: "btnApply",
      text: options.applyLabel || "Apply",
      disabled: (plan.blocked || !plan.changes.length) || null,
      onclick: (event) => applyReview(confirmInput ? confirmInput.value : true, event.currentTarget),
    }),
    el("button", { class: "btn ghost", text: "Cancel", onclick: closeReview }),
    plan.blocked ? chip("Cannot apply — see above", "stale") : null,
  ]));

  panel.appendChild(el("section", { class: "review", id: "reviewPanel" }, [
    el("header", {}, [
      el("h3", { text: "Preview" }),
      chip(planLabel(plan.kind), plan.governing_change ? "authority" : "proposed"),
      el("span", { text: plan.summary }),
      el("button", { class: "close", text: "Close", onclick: closeReview }),
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
      el("button", { class: "close", text: "Close", onclick: closeReview }),
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
  const message = doneMessage(plan) + (kind === "add" || kind === "revise"
    ? " Filed as an authority candidate — not context." : kind === "accept-proposal"
    ? " Only an authority candidate changed — not context." : kind === "reject-proposal"
    ? " The proposal is rejected, with your reason." : kind === "changeset"
    ? " Every declared outcome was applied as one action; its receipt is kept privately."
    : options && options.returnTo ? " Back to the change set: refresh it to use the edited candidate." : "");
  const lands = options && options.returnTo ? "" : landsIn(kind);
  const goThere = lands && lands !== currentView
    ? [{ label: `Go to ${$("view-" + lands).querySelector("h2").textContent}`, onclick: () => navigate(lands) }]
    : [];
  /* Applied is applied: anything that failed after it is said with it, and
     stays until dismissed. One toast shows at a time, so it is one message. */
  const followUp = (applied && applied.follow_up) || [];
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
   all-or-nothing write. It has two screens. Build change set holds the plan — only the
   governing documents the person adds, each with the outcome they declare,
   and the candidates they add to govern alongside — beside its live
   context-impact review. Preview and apply shows everything the plan writes
   before one confirmation. A candidate joins the set only by being chosen for
   a row. The draft is private local state — kept on this computer only — and
   changes nothing until it is applied; then it is an immutable receipt. Every outcome is
   the person's: no control here starts chosen, and nothing a report says
   chooses one. */
let changeSet = null;  // the draft open in the editor, as the server describes it
let csScreen = "build";  // "build", or "preview" while its preview is open
let csQueue = Promise.resolve();  // changes to the draft, sent one at a time
let csRationale = null;  // rationale typed but not yet saved: { text, timer }
let csPacket = {};  // the review packet's save, for one plan: { plan, confirm, typing, error, saved }
const csOpen = {};  // which of the editor's disclosures the person opened, across redraws

const OUTCOME_OPTIONS = [
  ["", "Choose an outcome"],
  ["retain", "Retain — keeps governing, unchanged"],
  ["revise", "Revise — a revision of it replaces it"],
  ["replace", "Replace — another candidate replaces it"],
  ["withdraw", "Withdraw — stops governing, becomes a candidate again"],
];
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
  const slot = $("changeSetInfo");
  if (slot && !slot.firstChild) {
    slot.appendChild(infoTip("About change sets", [
      el("p", { text: "A coordinated change set applies several authority changes — grants, revisions, "
        + "replacements and withdrawals — as one action, with one confirmation." }),
      el("p", { text: data.private_note }),
      el("p", { text: "Once applied, the Agent Context's files are the approved context, and the draft is kept "
        + "as a private receipt. Charter never commits: Git is yours." }),
    ], { id: "aboutChangeSets" }));
  }
  if (!data.drafts.length) {
    list.appendChild(el("p", { class: "hint", id: "noChangeSets",
      text: "No change sets for this Agent Context on this computer. Start one with New change set." }));
  }
  const groupFor = ({ id, name, holds }) => {
    const rows = data.drafts.filter(holds).map(changeSetRow);
    return rows.length ? recordGroup(id, name, rows) : null;
  };
  /* Active drafts are the everyday work, shown first. Applied change sets and
     abandoned drafts are history: compact, together behind a collapsed Change
     history disclosure below the active drafts. Each keeps its own group and
     count within that history, in the same order. */
  const active = groupFor(CHANGE_SET_ACTIVE);
  if (active) list.appendChild(active);
  const history = CHANGE_HISTORY_GROUPS.map(groupFor).filter(Boolean);
  const historyCount = data.drafts.filter(isHistoryRecord).length;
  if (historyCount) {
    list.appendChild(disclosure(groupLabel("Change History", historyCount), history,
      { id: "csHistoryBody", buttonId: "csHistoryToggle", class: "change-history" }));
  }
  /* A record Charter cannot read is none of these; it stays listed last, after the
     active drafts and the change history, where it can be deleted. */
  const unreadable = groupFor(CHANGE_SET_UNREADABLE);
  if (unreadable) list.appendChild(unreadable);
  renderChangeSetEditor();
}

/* The index's groups, each shown only when it has a member. An incomplete or
   stale draft is active; applied and abandoned change sets are history. */
const CHANGE_SET_ACTIVE = { id: "csGroupActive", name: "Active Drafts", holds: isActiveDraft };
const CHANGE_HISTORY_GROUPS = [
  { id: "csGroupApplied", name: "Applied Change Sets", holds: (d) => !d.unreadable && d.state === "applied" },
  { id: "csGroupAbandoned", name: "Abandoned Drafts", holds: (d) => !d.unreadable && d.state === "abandoned" },
];
const CHANGE_SET_UNREADABLE = { id: "csGroupUnreadable", name: "Unreadable Records", holds: (d) => !!d.unreadable };
const isHistoryRecord = (d) => !d.unreadable && (d.state === "applied" || d.state === "abandoned");

function changeSetRow(d) {
  return el("div", { class: "doc changeset-row", "data-id": d.id }, [
    el("div", {}, [
      el("div", { class: "title", text: d.title || "Unreadable draft" }),
      el("div", { class: "path", text: d.unreadable || changeSetCounts(d) }),
    ]),
    el("div", { class: "actions" }, [
      chip(d.unreadable ? "unreadable" : d.state, d.state === "active" ? "proposed" : null),
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
    csScreen = "build"; csPacket = {}; dropRationale();
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

/* Abandoning is irreversible: confirm it clearly first (it is not reversible
   afterwards, and the draft is kept only as an abandoned record). */
async function abandonChangeSet() {
  const d = changeSet && changeSet.draft;
  const label = d && d.title ? `the change set “${d.title}”` : "this change set";
  if (typeof confirm === "function" && !confirm(`Abandon ${label}? It can no longer be edited or `
      + "applied, and is kept only as an abandoned record. This cannot be undone. No governing "
      + "context is affected.")) return;
  await changeSetCall("/api/changeset/abandon");
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
  return el("header", { class: "cs-head" }, [
    active && !previewing ? null : el("h3", { class: "cs-title-text", id: "csTitleText", text: d.title }),
    active ? el("ol", { class: "cs-steps", id: "csSteps", "aria-label": "Steps" }, [
      el("li", { "aria-current": previewing ? null : "step", text: "1. Build Change Set" }),
      el("li", { "aria-current": previewing ? "step" : null, text: "2. Preview and Apply" }),
    ]) : null,
    el("div", { class: "cs-status", id: "csStatus" }, [
      chip(cs.lifecycle, LIFECYCLE_TONE[cs.lifecycle] || null),
      chip(cs.review_stage, null),
      chip("Private draft — not context", "proposed"),
    ]),
  ]);
}

/* Preview and apply: the plan's own preview, beneath, is the screen. */
function changeSetPreviewing() {
  return el("div", { class: "inner cs-previewing", id: "csPreviewing" }, [
    el("p", { class: "note", text: "Below is everything this change set does: the governing set before and after, "
      + "every authority effect, and every file it writes with its diff. Nothing is written until you type "
      + "the phrase once and apply." }),
    el("div", { class: "actions" }, [el("button", { class: "btn ghost", id: "csBackToBuild",
      text: "← Back to Build Change Set", onclick: closeReview })]),
  ]);
}

async function previewChangeSet() {
  await flushRationale();
  await csQueue;  // the preview is of the draft with every edit saved
  const cs = changeSet;
  if (!cs || !cs.valid) return;
  csScreen = "preview";
  await planFor("changeset", { draft_id: cs.draft.id, draft_revision: cs.draft.revision },
    { applyLabel: "Apply change set", applyClass: "btn authority", changeSet: cs });
  renderChangeSetEditor();
  /* On the preview screen now: focus its heading, not the button that vanished. */
  focusAfter("csTitleText");
}

/* The name is the person's, prominent and editable; it heads the change
   summary. */
function changeSetTitle(d) {
  const input = el("input", { type: "text", id: "csTitle", class: "cs-title-input", maxlength: "200",
    "aria-label": "Change set name", placeholder: "Name this change set" });
  input.value = d.untitled ? "" : d.title;
  input.addEventListener("change", () => {
    const value = input.value.trim();
    if (!value) { input.value = d.untitled ? "" : d.title; return; }
    if (value !== d.title) changeSetCall("/api/changeset/update", { title: value });
  });
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter") { ev.preventDefault(); input.blur(); } });
  return el("div", { class: "cs-title" }, [input, el("p", { class: "hint", id: "csTitleHint", text: d.untitled
    ? "Name this change set. Its name heads the change summary; Charter never names it for you."
    : "Its name heads the change summary." })]);
}

/* Build change set: the plan, and beside it — below it on a narrow screen —
   its context-impact review and the agents' responses, two panels that stay
   in view while the plan is built. */
function changeSetBuild(cs, active) {
  const d = cs.draft;
  const plan = el("div", { class: "cs-col cs-plan", id: "csPlan" }, [
    active ? changeSetTitle(d) : null,
    changeSetRows(cs, active),
    changeSetAlongside(cs, active),
    changeSetOthers(cs, active),
    active ? changeSetRationale(cs) : null,
    changeSetSummary(cs),
    changeSetReasons(cs, active),
    el("div", { class: "actions cs-next" }, [
      active ? el("button", { class: "btn authority", id: "csPreview", text: "Preview and apply →",
        disabled: cs.valid ? null : "", onclick: previewChangeSet }) : null,
      active ? null : el("span", { class: "hint", text: "Abandoned: this draft no longer changes." }),
      active ? el("button", { class: "btn ghost", text: "Abandon", onclick: abandonChangeSet }) : null,
      active ? null : el("button", { class: "btn ghost", text: "Delete draft", onclick: () => deleteChangeSet(d.id, d.title) }),
    ]),
  ]);
  const reviewColumn = el("div", { class: "cs-col cs-review", id: "csReview" }, [
    changeSetPrompt(cs, active),
    changeSetReports(cs, active),
  ]);
  return el("div", { class: "inner cs-build", id: "csBuild" }, [plan, reviewColumn]);
}

/* A picker option distinguishes candidates that share a title by their source,
   revision relationship, scope and a short change summary — never by the
   filename suffix alone. */
function candidateLabel(c) {
  const parts = [c.title];
  const bits = [];
  if (c.source_kind) bits.push(SOURCE_LABEL[c.source_kind] || c.source_kind);
  if (c.revises_title) {
    bits.push(c.revises_current === false
      ? `revises an earlier version of “${c.revises_title}”` : `revises “${c.revises_title}”`);
  }
  if (bits.length) parts.push(" — " + bits.join(", "));
  if (c.scope) parts.push(` · ${c.scope.length > 60 ? c.scope.slice(0, 57) + "…" : c.scope}`);
  if (c.change_summary) parts.push(` · ${c.change_summary}`);
  return parts.join("");
}

/* Labels for the candidates one picker offers, by path. Where two would
   still read the same, the date each was created is added, and then its
   logical path: always beside what tells them apart, never alone. */
function candidateLabels(list) {
  const labels = {};
  list.forEach((c) => { labels[c.path] = candidateLabel(c); });
  const repeated = () => {
    const seen = {};
    list.forEach((c) => { seen[labels[c.path]] = (seen[labels[c.path]] || 0) + 1; });
    return list.filter((c) => seen[labels[c.path]] > 1);
  };
  repeated().forEach((c) => { if (c.created) labels[c.path] += ` · created ${c.created}`; });
  repeated().forEach((c) => { labels[c.path] += ` · ${c.path}`; });
  return labels;
}

const candidateOption = (c, chosen, labels) => el("option", { value: c.path,
  text: `${(labels && labels[c.path]) || candidateLabel(c)}${c.used && c.path !== chosen ? " (already in this plan)" : ""}` });

/* One governing document the person is changing: its outcome, and for a
   revision or replacement, the candidate they choose. */
function changeSetRows(cs, active) {
  const list = el("ul", { class: "cs-list", id: "csRows" });
  cs.rows.forEach((r, i) => list.appendChild(planRow(cs, r, i, active)));
  const pick = el("select", { id: "csAddRow", "aria-label": "Governing document to change" },
    [el("option", { value: "", text: "Choose a governing document" })]
      .concat((cs.others || []).map((g) => el("option", { value: g.path, text: `${g.title} — ${g.path}` }))));
  return csSection("Governing Documents You Are Changing", [
    cs.rows.length ? list : el("p", { class: "hint", id: "csNoRows",
      text: "Add each governing document this change set revises, replaces or withdraws." }),
    active && (cs.others || []).length ? el("div", { class: "actions cs-add" }, [pick,
      el("button", { class: "btn ghost small", id: "csAddRowButton", text: "Add to plan", onclick: () => {
        if (!pick.value) { toast("Choose a governing document.", true); return; }
        changeSetCall("/api/changeset/update", { outcomes: { [pick.value]: { outcome: "" } } });
      } })]) : null,
  ]);
}

function planRow(cs, r, i, active) {
  const outcome = el("select", { id: `csOutcome-${i}`, disabled: active && r.governs ? null : "" },
    OUTCOME_OPTIONS.map(([value, label]) => el("option", { value, text: label })));
  outcome.value = r.outcome || "";
  const needsCandidate = r.outcome === "revise" || r.outcome === "replace";
  const chosen = r.candidate ? r.candidate.path : "";
  const labels = candidateLabels(cs.available_candidates);
  const pick = el("select", { id: `csCandidate-${i}`, disabled: active ? null : "" },
    [el("option", { value: "", text: "Choose the candidate" })]
      .concat(cs.available_candidates.map((c) => candidateOption(c, chosen, labels))));
  if (chosen && !cs.available_candidates.some((c) => c.path === chosen)) {
    pick.appendChild(el("option", { value: chosen, text: r.candidate.title }));
  }
  pick.value = chosen;
  const send = (o) => changeSetCall("/api/changeset/update", { outcomes: { [r.path]: o } });
  outcome.addEventListener("change", () => send({ outcome: outcome.value, candidate: "" }));
  pick.addEventListener("change", () => send({ outcome: r.outcome, candidate: pick.value }));
  const effect = (cs.effects || []).find((e) => e.document === r.path);
  return el("li", { class: "cs-item cs-row", "data-path": r.path }, [
    el("div", { class: "cs-row-head" }, [
      el("div", {}, [el("div", { class: "title", text: r.title }), el("div", { class: "path", text: r.path })]),
      r.governs ? null : chip("No longer governs", "stale"),
      active ? el("button", { class: "btn ghost small", text: "Remove", "aria-label": `Remove ${r.title} from the plan`,
        onclick: () => send(null) }) : null,
    ]),
    el("div", { class: "cs-row-fields" }, [
      el("div", { class: "field" }, [el("label", { for: `csOutcome-${i}`, text: "Outcome" }), outcome]),
      needsCandidate ? el("div", { class: "field" }, [el("label", { for: `csCandidate-${i}`,
        text: r.outcome === "revise" ? "Revised by" : "Replaced by" }), pick]) : null,
    ]),
    needsCandidate && r.candidate ? rowScope(r, effect, i, active) : null,
    needsCandidate && r.candidate && r.candidate.revises_title && r.candidate.revises_current === false
      ? el("p", { class: "note warning cs-earlier", id: `csEarlier-${i}`,
        text: `“${r.candidate.title}” was made from an earlier version of “${r.candidate.revises_title}”. `
          + "Applying it would undo whatever changed in that document since, unless the candidate repeats "
          + "it: compare them before you apply." }) : null,
  ]);
}

const sameScope = (a, b) => String(a || "").split(/\s+/).join(" ").trim() === String(b || "").split(/\s+/).join(" ").trim();

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

function rowScope(r, effect, i, active) {
  const c = r.candidate;
  const after = effect ? effect.scope_after : (c.scope || r.scope);
  const changes = !sameScope(after, r.scope);
  const blank = r.scope ? "Blank — inherits the replaced document's scope" : "Blank — no scope stated";
  return el("div", { class: "cs-scope", id: `csScope-${i}` }, [
    c.present ? null : chip("No longer an authority candidate", "stale"),
    scopeLine(`csScopeLine-${i}`, "Candidate's scope", c.scope, blank,
      chip(changes ? "Scope changes" : "Scope unchanged", changes ? "proposed" : null)),
    el("div", { class: "cs-scope-actions" }, [
      csDisclosure(`scope-${r.path}`, "Full scope and comparison",
        [candidateScope(c, r, effect, true)], { buttonId: `csScopeToggle-${i}` }),
      editDetails(c, `csEditDetails-${i}`, active),
    ]),
  ]);
}

/* A candidate's scope, as its own metadata says — beside the scope it
   replaces, for a revision or replacement. Read-only here: scope is changed
   with Edit details on the candidate, which makes any report stale. */
function candidateScope(c, row, effect, nested) {
  const compare = el("dl", { class: "scope-compare" }, row ? [
    el("dt", { text: "Candidate's scope" }), el("dd", { text: c.scope || "None stated" }),
    el("dt", { text: "Current scope" }), el("dd", { text: row.scope || "None stated" }),
    el("dt", { text: "Scope after" }),
    el("dd", { text: effect ? (effect.scope_after || "None stated")
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

function changeSetAlongside(cs, active) {
  const list = el("ul", { class: "cs-list", id: "csAlongside" });
  cs.alongside.forEach((c, j) => list.appendChild(el("li", { class: "cs-item cs-row", "data-path": c.path }, [
    el("div", { class: "cs-row-head" }, [
      el("div", {}, [el("div", { class: "title", text: c.title }), el("div", { class: "path", text: c.path })]),
      chip("Governs alongside", "ok"),
      active ? el("button", { class: "btn ghost small", text: "Remove", "aria-label": `Remove ${c.title} from the plan`,
        onclick: () => changeSetCall("/api/changeset/update",
          { alongside: cs.alongside.filter((o) => o.path !== c.path).map((o) => o.path) }) }) : null,
    ]),
    el("div", { class: "cs-scope", id: `csAlongsideScope-${j}` }, [
      c.present ? null : chip("No longer an authority candidate", "stale"),
      scopeLine(`csAlongsideScopeLine-${j}`, "Scope", c.scope, "Blank — no scope stated"),
      el("div", { class: "cs-scope-actions" }, [
        csDisclosure(`alongside-scope-${c.path}`, "Full scope", [candidateScope(c, null, null, true)],
          { buttonId: `csAlongsideScopeToggle-${j}` }),
        editDetails(c, `csAlongsideEdit-${j}`, active),
      ]),
    ]),
  ])));
  const free = cs.available_candidates.filter((c) => !c.used);
  const freeLabels = candidateLabels(free);
  const pick = el("select", { id: "csAddAlongside", "aria-label": "Authority candidate to govern alongside" },
    [el("option", { value: "", text: "Choose an authority candidate" })]
      .concat(free.map((c) => el("option", { value: c.path, text: freeLabels[c.path] }))));
  return csSection("New Documents to Govern Alongside", [
    cs.alongside.length ? list : null,
    active && free.length ? el("div", { class: "actions cs-add" }, [pick,
      el("button", { class: "btn ghost small", id: "csAddAlongsideButton", text: "Add to govern alongside", onclick: () => {
        if (!pick.value) { toast("Choose an authority candidate.", true); return; }
        changeSetCall("/api/changeset/update", { alongside: cs.alongside.map((c) => c.path).concat([pick.value]) });
      } })]) : null,
    !cs.alongside.length && !(active && free.length)
      ? el("p", { class: "hint", text: "No other authority candidate is waiting." }) : null,
  ]);
}

/* Every governing document the plan does not name stays only by the
   person's one explicit choice, shown compactly with the list behind it. */
function changeSetOthers(cs, active) {
  const others = cs.others || [];
  if (!others.length) return null;
  const list = el("ul", { class: "set-list", id: "csOthersList" },
    others.map((g) => el("li", {}, [el("span", { text: `${g.title} — ${g.path}` })])));
  const body = cs.others_retained
    ? [chip("Retained — your decision", "ok"),
      csDisclosure("others", `Retaining ${documentsOf(others.length)}`, [list], { buttonId: "csOthersToggle" }),
      active ? el("button", { class: "btn ghost small", id: "csUnretain", text: "Undo",
        onclick: () => changeSetCall("/api/changeset/update", { retain_others: false }) }) : null]
    : [active ? el("button", { class: "btn small", id: "csRetainOthers",
        text: `Retain all other governing documents (${others.length})`,
        onclick: () => changeSetCall("/api/changeset/update", { retain_others: true }) }) : null,
      csDisclosure("others", `Show the ${documentsOf(others.length)}`, [list], { buttonId: "csOthersToggle" })];
  return csSection("Every Other Governing Document", [
    cs.others_retained ? null : el("p", { class: "hint",
      text: "Each governing document needs an outcome you choose. One not in the plan stays only if you retain it." }),
    el("div", { class: "cs-retained", id: "csOthers" }, body),
  ]);
}

/* The rationale is part of the draft, saved as the person writes it: shortly
   after they stop typing, when they leave the field, and before anything
   that leaves or previews the draft. There is no Save step. */
const RATIONALE_PAUSE_MS = 800;

function changeSetRationale(cs) {
  const rationale = el("textarea", { id: "csRationale", rows: 2, "aria-describedby": "csRationaleHint" });
  rationale.value = csRationale ? csRationale.text : (cs.draft.rationale || "");
  rationale.addEventListener("input", () => {
    if (csRationale && csRationale.timer) clearTimeout(csRationale.timer);
    csRationale = { text: rationale.value, timer: setTimeout(() => flushRationale(), RATIONALE_PAUSE_MS) };
  });
  rationale.addEventListener("change", () => {
    if (!csRationale) csRationale = { text: rationale.value, timer: null };
    flushRationale();
  });
  return csSection("Context-Impact Rationale", [
    el("p", { class: "hint", id: "csRationaleHint",
      text: "Why these outcomes make the governing set coherent. It goes into the change summary, "
        + "and is saved as you write." }),
    rationale,
  ]);
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
    reasons.length ? list : el("p", { class: "hint", text: cs.lifecycle === "structurally valid"
      ? "Structurally valid: every outcome is declared, and the result passes validation. "
        + "Whether the documents agree is still your judgement." : "" }),
    active && refreshable ? el("div", { class: "actions" }, [el("button", { class: "btn small", id: "csRefresh",
      text: "Refresh", onclick: async () => {
        const next = await changeSetCall("/api/changeset/refresh");
        if (next && next.refreshed && next.refreshed.length) {
          toast("Refreshed: " + next.refreshed.map((c) => `${c.document || "Agent Context"} ${c.change}`).join("; ") + ".");
        }
      } })]) : null,
  ]);
}

function changeSetSummary(cs) {
  const summary = cs.summary || "";
  if (!summary) return null;
  return csSection("Change Summary", [csDisclosure("summary", "Show the change summary", [
    el("pre", { class: "code", id: "csSummary", text: summary }),
    el("div", { class: "actions" }, [el("button", { class: "btn ghost small", id: "csCopySummary",
      text: "Copy summary", onclick: () => copyText(summary, "csSummary") })]),
  ], { buttonId: "csSummaryToggle" })]);
}

/* The live context-impact review, prepared from a complete plan: no mode to
   choose, nothing to generate. Within the practical single-message limit it
   is a self-contained prompt to copy; past it, the same review as one review
   packet the person saves where they choose and attaches. Preparing either
   discloses nothing; copying or attaching does, and says so beside it. */
function changeSetPrompt(cs, active) {
  const p = cs.review_prompt || { ready: false, reason: "" };
  const body = [];
  if (active && !p.ready) {
    body.push(el("p", { class: "hint", id: "csPromptWaiting" }, withCode(p.reason)));
  } else if (active && p.over_limit) {
    body.push(...changeSetPacket(cs, p));
  } else if (active) {
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
  const last = active ? (cs.copied || []).slice(-1)[0] : null;
  if (last && p.ready) {
    body.push(el("p", { class: "hint", id: "csCopied", text: last.current
      ? (last.mode === "packet" ? "You saved a review packet for this plan." : `You copied the ${MODE_NAME[last.mode] || last.mode} for this plan.`)
      : `You ${last.mode === "packet" ? "saved a review packet" : "copied a review prompt"} for an earlier version of this plan: `
        + "a report written from it will be stale." }));
  }
  return el("section", { class: "cs-section cs-panel", id: "csPromptPanel" }, [
    el("div", { class: "label-row" }, [el("h4", { text: "Context-Impact Review" }), infoTip("About context-impact review", [
      el("p", { text: "Charter prepares review material for an agent of your choice. It contacts no "
        + "agent or service and uses no AI." }),
      el("p", { text: "A review that fits in one message is a prompt to copy. A larger one is a review packet: one Markdown "
        + "file you save outside every Agent Context and Charter's private state, then attach. It is "
        + "never committed, kept or removed for you." }),
      el("p", { text: "The agent's report is advisory. Its form is checked, never its conclusions, and it never selects an outcome." }),
    ])]),
    ...body,
  ]);
}

function promptIncludes(p) {
  const inc = p.includes || {};
  return `Includes ${documentsOf(inc.documents)} in full, ${countOf(inc.candidates, ["candidate", "candidates"])} `
    + `and the complete planned change. ${p.size_chars.toLocaleString("en")} characters, `
    + `about ${p.approx_tokens.toLocaleString("en")} tokens.`;
}

const sizeOf = (bytes) => bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB`
  : `${Math.max(1, Math.round(bytes / 1024)).toLocaleString("en")} KB`;

/* Past the limit: the packet, saved where the person chooses. What it holds
   and the disclosure stay visible where it is saved; the request to send with
   it is ready to copy. The packet's text never comes to the page. */
function changeSetPacket(cs, p) {
  if (csPacket.plan !== cs.plan_fingerprint) csPacket = { plan: cs.plan_fingerprint };
  const out = [
    el("p", { class: "cs-includes", id: "csPacketIntro", text: `This review is ${p.size_chars.toLocaleString("en")} characters, `
      + `past the practical single-message limit of ${p.limit.toLocaleString("en")}. Save it as one review packet and attach `
      + "the file to the agent you choose." }),
    el("p", { class: "cs-includes", id: "csPacketIncludes", text: `The packet holds the review instructions, ${documentsOf(p.includes.documents)} `
      + `in full, ${countOf(p.includes.candidates, ["candidate", "candidates"])}, the complete planned change, every hash, `
      + `and the report format, all marked as data to review. One Markdown file, ${sizeOf(p.size_bytes)}.` }),
    el("div", { class: "cs-copy" }, [
      el("button", { class: "btn small", id: "csSavePacket", type: "button", text: "Save review packet…",
        onclick: () => savePacket(cs, {}) }),
      el("p", { class: "cs-copy-warning", id: "csPacketDisclosure", text: cs.packet_disclosure }),
    ]),
  ];
  if (csPacket.typing) {
    const path = el("input", { type: "text", id: "csPacketPath", placeholder: `For example C:\\Users\\you\\Downloads\\${p.file_name}` });
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
  /* Once saved, the request names the file as it was saved, renamed or not. */
  const requestText = (csPacket.saved && csPacket.saved.request) || p.request;
  const request = el("pre", { class: "code", id: "csPacketRequest", text: requestText });
  out.push(csSection("Request to Send with the Packet", [
    request,
    el("div", { class: "actions" }, [el("button", { class: "btn ghost small", id: "csCopyRequest", type: "button",
      text: "Copy request", onclick: () => copyText(requestText, "csPacketRequest") })]),
  ], null, "csPacketRequestPanel"));
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

function changeSetReports(cs, active) {
  const grid = el("div", { class: "report-grid", id: "csReports" });
  (cs.reports || []).forEach((r) => grid.appendChild(reportCard(r, active)));
  const label = el("input", { type: "text", id: "csReportLabel", placeholder: "Which agent, or a note" });
  const text = el("textarea", { id: "csReportText", rows: 5,
    placeholder: "Paste the agent's whole response, or only its JSON report. No code fences needed." });
  return csSection("Agent Responses", [
    active ? el("div", { class: "field" }, [el("label", { for: "csReportText", text: "The agent's response" }), text]) : null,
    active ? el("div", { class: "field" }, [el("label", { for: "csReportLabel", text: "Label" }), label]) : null,
    active ? el("div", { class: "actions" }, [el("button", { class: "btn ghost small", id: "csAttach", text: "Attach report",
      onclick: () => changeSetCall("/api/changeset/report/attach", { text: text.value, label: label.value }) })]) : null,
    (cs.reports || []).length ? grid : el("p", { class: "hint", text: "No report attached." }),
  ], infoTip("About reports", [
    el("p", { text: "A report is an agent's advisory claims, never Charter's findings, and never "
      + "governing context." }),
    el("p", { text: "Report issues are form checks only: missing, stale, malformed or unsupported. They never judge "
      + "the report's conclusions, and no report is chosen over another." }),
    el("p", { text: "A report is stale once the context or this plan changes after its prompt was copied." }),
  ]), "csResponsesPanel");
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

/* An applied change set: an immutable receipt of what it did, as it was
   applied. Nothing here edits it. */
function changeSetReceipt(cs) {
  const r = cs.receipt || {};
  const d = cs.draft;
  const changed = (r.outcomes || []).filter((e) => e.effect !== "retain");
  const retained = (r.outcomes || []).filter((e) => e.effect === "retain");
  const established = r.after || [];
  const outcomeLine = (e) => {
    const by = e.candidate ? ` — by “${e.candidate_title || e.candidate}”` : "";
    const where = e.archived_to ? `; the previous version is archived at ${e.archived_to}`
      : e.withdrawn_to ? `; it is an authority candidate again at ${e.withdrawn_to}` : "";
    return el("li", { class: "cs-item" }, [
      el("div", {}, [chip(EFFECT_WORDS[e.effect] || e.effect, e.effect === "withdraw" ? "stale" : "authority"),
        el("span", { class: "title", text: ` ${e.title}` })]),
      el("div", { class: "path", text: `${e.document}${by}${where}` }),
    ]);
  };
  const reports = r.reports || [];
  const evidence = reports.length
    ? csDisclosure("receipt-reports", `${countOf(reports.length, ["advisory report", "advisory reports"])}, as checked when applied`,
      [el("div", { class: "report-grid" }, reports.map((x) => reportCard(x, false)))], { buttonId: "csReceiptReportsToggle" })
    : el("p", { class: "hint", text: "No advisory report was attached." });
  const copied = (r.prompts || []).length
    ? el("p", { class: "hint", id: "csReceiptShared", text: "Review material shared: " + r.prompts.map((p) =>
      `${MODE_NAME[p.mode] || p.mode} ${p.mode === "packet" ? "saved" : "copied"}`).join(", ") + "." })
    : null;
  return el("section", { class: "review changeset cs-receipt", id: "changeSetPanel" }, [
    el("header", { class: "cs-head" }, [
      el("h3", { class: "cs-title-text", id: "csTitleText", text: d.title }),
      el("div", { class: "cs-status", id: "csStatus" }, [chip("Applied — receipt", "authority"),
        chip("Private record — not context", "proposed")]),
    ]),
    el("div", { class: "inner" }, [
      el("div", { class: "cs-result", id: "csResult" }, [
        el("p", { class: "note", id: "csRecorded", text: `Applied to the Agent Context folder${r.at
          ? ` on ${r.at.slice(0, 10)}` : ""}, as one action. Agents read the new context now. Git is untouched: `
          + "commit it when you choose." }),
      ]),
      csSection(`Final Outcomes (${changed.length})`, [
        el("ul", { class: "cs-list", id: "csReceiptOutcomes" }, changed.map(outcomeLine)),
      ], null, "csReceiptFinal"),
      csSection(`Established Governing Documents (${established.length})`, [
        el("p", { class: "hint", text: "What governed once this change set was applied." }),
        csDisclosure("receipt-established", `Show the ${documentsOf(established.length)}`,
          [el("ul", { class: "set-list", id: "csReceiptEstablished" }, established.map((a) => el("li", {}, [
            el("span", { text: `${a.title} — ${a.path}` }), a.effect ? chip(a.effect, EFFECT_TONE[a.effect] || null) : null])))],
          { buttonId: "csReceiptEstablishedToggle" }),
        retained.length ? csDisclosure("receipt-retained", `Retained, unchanged: ${documentsOf(retained.length)}`,
          [el("ul", { class: "set-list", id: "csReceiptRetained" },
            retained.map((e) => el("li", { text: `${e.title} — ${e.document}` })))],
          { buttonId: "csReceiptRetainedToggle" }) : null,
      ], null, "csReceiptEstablishedSection"),
      csSection("Advisory Review", [
        evidence, copied,
      ], null, "csReceiptReview"),
      r.summary ? csSection("Change Summary", [
        el("pre", { class: "code", id: "csSummary", text: r.summary }),
        el("div", { class: "actions" }, [el("button", { class: "btn ghost small", id: "csCopySummary",
          text: "Copy summary", onclick: () => copyText(r.summary, "csSummary") })]),
      ]) : null,
    ]),
  ]);
}

/* The whole governing set before and after, each document with its effect. */
function governingSetCompare(cs) {
  const before = el("ul", { class: "set-list" }, (cs.before || []).map((b) => {
    const effect = (cs.effects || []).find((e) => e.document === b.path);
    return el("li", {}, [el("span", { text: `${b.title} — ${b.path}` }),
      effect && effect.effect !== "retain" ? chip(effect.effect, effect.effect === "withdraw" ? "stale" : "authority") : null]);
  }));
  const after = el("ul", { class: "set-list" }, (cs.after || []).map((a) =>
    el("li", {}, [el("span", { text: `${a.title} — ${a.path}` }), chip(a.effect, EFFECT_TONE[a.effect] || null)])));
  return el("div", { class: "set-compare", id: "setCompare" }, [
    el("div", {}, [el("h4", { text: `Governing Now (${(cs.before || []).length})` }), before]),
    el("div", {}, [el("h4", { text: `Governing After (${(cs.after || []).length})` }), after]),
  ]);
}

/* --------------------------------------------- Rebuild Agent Context */

/* Offered only when the governing documents are valid and the folder is
   clean: it regenerates the map and metadata, after a preview and an
   ordinary deliberate confirmation, and never changes a governing document. */
function startRebuild() {
  planFor("rebuild", {}, { applyLabel: "Rebuild Agent Context" });
}

/* ----------------------------------------------------------------- settings */

function renderSettings() {
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
  box.appendChild(el("fieldset", { class: "field" }, [el("legend", { text: "Agent guidance" })].concat(boxes)));
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

/* Create candidate's empty first-use state, exactly. */
function resetIntake() {
  abandonIntakeWork();
  staged = null;
  ["markdown", "title", "scope"].forEach((id) => { $(id).value = ""; });
  showFrontMatterNote(null);
  $("stagedInfo").textContent = "";
  $("convertNotes").textContent = "";
  $("file").value = "";
  $("stepConvert").dataset.done = "false";
  unlockIntake(false);
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
    if (hint) hint.textContent = "An Agent Context is already here, so there is nothing to create. "
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
  const box = $("recentContexts");
  box.textContent = "";
  if (state.closed_because) showFieldError("contextError", state.closed_because);
  const legacy = legacyNotice();
  if (legacy) box.appendChild(legacy);
  const recent = state.recent || [];
  if (!recent.length) return;
  box.appendChild(el("h3", { text: "Opened on This Computer" }));
  box.appendChild(el("ul", { class: "recent" }, recent.map((p) => el("li", {}, [
    el("button", { type: "button", class: "linkish", text: p, onclick: () => {
      $("contextPath").value = p; showFieldError("contextError", ""); $("contextPath").focus(); peekFolder();
    } })]))));
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
$("btnSwitch").addEventListener("click", () => { closeDocument(); closeReview(); renderStart(); show("open"); });
$("btnViewContext").addEventListener("click", viewContext);
$("btnRebuildContext").addEventListener("click", startRebuild);
/* The disclosures written into the page itself; those built later wire their own. */
document.querySelectorAll(".disclosure-toggle").forEach((b) => b.addEventListener("click", () => toggleDisclosure(b)));
scopeInfoContent().forEach((p) => $("aboutIntakeScopeBody").appendChild(p));
document.querySelectorAll(".info-wrap").forEach((w) => wireInfoTip(w));

$("btnPick").addEventListener("click", () => $("file").click());
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
