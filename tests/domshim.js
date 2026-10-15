/* A DOM small enough to read, real enough to run the utility's front end.

   The front end has no build step and no framework, so the only thing standing
   between it and a test is a document object. This is that object: elements,
   text nodes, attributes, events, and a serialiser that escapes text exactly
   where a browser would. Nothing here interprets markup on a node's behalf, so
   a test that sees `&lt;script&gt;` is seeing what a browser would render. */

"use strict";

const VOID = new Set(["area", "base", "br", "col", "embed", "hr", "img", "input",
  "link", "meta", "param", "source", "track", "wbr"]);

const escapeText = (value) => String(value)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escapeAttr = (value) => escapeText(value).replace(/"/g, "&quot;");

const camel = (name) => name.replace(/-([a-z])/g, (_, c) => c.toUpperCase());

class TextNode {
  constructor(data) {
    this.nodeType = 3;
    this.nodeName = "#text";
    this.data = String(data);
    this.parentNode = null;
  }
  get textContent() { return this.data; }
  set textContent(value) { this.data = String(value); }
}

class Element {
  constructor(tag, ownerDocument) {
    this.nodeType = 1;
    this.localName = String(tag).toLowerCase();
    this.tagName = this.localName.toUpperCase();
    this.nodeName = this.tagName;
    this.ownerDocument = ownerDocument || null;
    this.attributes = {};
    this.childNodes = [];
    this.parentNode = null;
    this.dataset = {};
    this.listeners = {};
    this.hidden = false;
    this.checked = false;
    this.selected = false;
    this.disabled = false;
    this._value = "";
    this._rawHTML = null;
  }

  /* -- tree -- */
  get firstChild() { return this.childNodes[0] || null; }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  appendChild(node) {
    if (node && node.nodeType === 11) {
      for (const child of node.childNodes.slice()) this.appendChild(child);
      node.childNodes.length = 0;
      return node;
    }
    if (node.parentNode) node.parentNode.removeChild(node);
    node.parentNode = this;
    this.childNodes.push(node);
    this._rawHTML = null;
    return node;
  }
  removeChild(node) {
    const at = this.childNodes.indexOf(node);
    if (at !== -1) this.childNodes.splice(at, 1);
    node.parentNode = null;
    return node;
  }
  remove() { if (this.parentNode) this.parentNode.removeChild(this); }

  /* -- attributes -- */
  setAttribute(name, value) {
    const key = String(name);
    this.attributes[key] = String(value);
    if (key.startsWith("data-")) this.dataset[camel(key.slice(5))] = String(value);
    if (key === "hidden") this.hidden = true;
    if (key === "checked") this.checked = true;
    if (key === "selected") this.selected = true;
    if (key === "disabled") this.disabled = true;
    if (key === "value") this._value = String(value);
  }
  removeAttribute(name) {
    const key = String(name);
    delete this.attributes[key];
    if (key.startsWith("data-")) delete this.dataset[camel(key.slice(5))];
    if (key === "hidden") this.hidden = false;
    if (key === "checked") this.checked = false;
    if (key === "disabled") this.disabled = false;
  }
  getAttribute(name) {
    return Object.prototype.hasOwnProperty.call(this.attributes, name)
      ? this.attributes[name] : null;
  }
  get className() { return this.attributes["class"] || ""; }
  set className(value) { this.attributes["class"] = String(value); }
  get id() { return this.attributes.id || ""; }
  get classList() {
    const owner = this;
    const read = () => owner.className.split(/\s+/).filter(Boolean);
    const write = (list) => { owner.className = list.join(" "); };
    return {
      contains: (name) => read().indexOf(name) !== -1,
      add: (name) => { const l = read(); if (l.indexOf(name) === -1) l.push(name); write(l); },
      remove: (name) => write(read().filter((n) => n !== name)),
      toggle: (name, force) => {
        const on = force === undefined ? read().indexOf(name) === -1 : !!force;
        if (on) { const l = read(); if (l.indexOf(name) === -1) l.push(name); write(l); }
        else write(read().filter((n) => n !== name));
      },
    };
  }
  get type() {
    if (this.attributes.type) return this.attributes.type;
    if (this.tagName === "SELECT") return "select-one";
    if (this.tagName === "TEXTAREA") return "textarea";
    if (this.tagName === "INPUT") return "text";
    return undefined;
  }

  /* -- form controls -- */
  get options() { return this.children.filter((n) => n.tagName === "OPTION"); }
  get selectedOptions() { return this.options.filter((o) => o.selected); }
  get value() {
    if (this.tagName === "SELECT") {
      const chosen = this.options.find((o) => o.selected) || this.options[0];
      return chosen ? chosen.value : "";
    }
    if (this.tagName === "OPTION") {
      return Object.prototype.hasOwnProperty.call(this.attributes, "value")
        ? this.attributes.value : this.textContent;
    }
    return this._value;
  }
  set value(next) {
    if (this.tagName === "SELECT") {
      let matched = false;
      for (const option of this.options) {
        option.selected = !matched && option.value === String(next);
        if (option.selected) matched = true;
      }
      return;
    }
    this._value = String(next);
  }

  /* -- content -- */
  get textContent() { return this.childNodes.map((n) => n.textContent).join(""); }
  set textContent(value) {
    this.childNodes.forEach((n) => { n.parentNode = null; });
    this.childNodes = [];
    this._rawHTML = null;
    if (value !== "" && value !== null && value !== undefined) {
      this.appendChild(new TextNode(value));
    }
  }
  get innerHTML() {
    if (this._rawHTML !== null) return this._rawHTML;
    return this.childNodes.map(serialize).join("");
  }
  set innerHTML(value) {
    this.childNodes.forEach((n) => { n.parentNode = null; });
    this.childNodes = [];
    this._rawHTML = String(value);
  }
  get outerHTML() { return serialize(this); }

  /* -- events and no-ops the front end calls -- */
  addEventListener(type, handler) {
    (this.listeners[type] = this.listeners[type] || []).push(handler);
  }
  dispatch(type, event) {
    const payload = Object.assign({ type, target: this, currentTarget: this,
      preventDefault() {}, dataTransfer: null }, event || {});
    for (const handler of (this.listeners[type] || []).slice()) handler(payload);
  }
  click() { this.dispatch("click"); }
  scrollIntoView() {}
  focus() { if (this.ownerDocument) this.ownerDocument.activeElement = this; }
  querySelectorAll(selector) { return queryAll(this, selector); }
  querySelector(selector) { return queryAll(this, selector)[0] || null; }
}

class Fragment {
  constructor() {
    this.nodeType = 11;
    this.nodeName = "#document-fragment";
    this.childNodes = [];
  }
  get firstChild() { return this.childNodes[0] || null; }
  get children() { return this.childNodes.filter((n) => n.nodeType === 1); }
  appendChild(node) {
    if (node && node.nodeType === 11) {
      for (const child of node.childNodes.slice()) this.appendChild(child);
      node.childNodes.length = 0;
      return node;
    }
    node.parentNode = this;
    this.childNodes.push(node);
    return node;
  }
  removeChild(node) {
    const at = this.childNodes.indexOf(node);
    if (at !== -1) this.childNodes.splice(at, 1);
    node.parentNode = null;
    return node;
  }
  get textContent() { return this.childNodes.map((n) => n.textContent).join(""); }
}

function serialize(node) {
  if (!node) return "";
  if (node.nodeType === 3) return escapeText(node.data);
  if (node.nodeType === 11) return node.childNodes.map(serialize).join("");
  const attrs = Object.keys(node.attributes).sort()
    .map((k) => ` ${k}="${escapeAttr(node.attributes[k])}"`).join("");
  if (VOID.has(node.localName)) return `<${node.localName}${attrs}>`;
  const inner = node._rawHTML !== null ? node._rawHTML : node.childNodes.map(serialize).join("");
  return `<${node.localName}${attrs}>${inner}</${node.localName}>`;
}

/* Descendant chains of `tag`, `#id` and `.class` — all the front end uses. */
function matches(node, token) {
  if (node.nodeType !== 1) return false;
  const parts = token.match(/^([a-zA-Z][\w-]*)?((?:[.#][\w-]+)*)$/);
  if (!parts) return false;
  if (parts[1] && node.localName !== parts[1].toLowerCase()) return false;
  for (const bit of (parts[2] || "").match(/[.#][\w-]+/g) || []) {
    if (bit[0] === "#" && node.id !== bit.slice(1)) return false;
    if (bit[0] === "." && !node.classList.contains(bit.slice(1))) return false;
  }
  return true;
}

function descendants(node, out) {
  for (const child of node.childNodes) {
    if (child.nodeType !== 1) continue;
    out.push(child);
    descendants(child, out);
  }
  return out;
}

function queryAll(root, selector) {
  const tokens = String(selector).trim().split(/\s+/);
  let scope = [root];
  for (const token of tokens) {
    const next = [];
    for (const node of scope) {
      for (const candidate of descendants(node, [])) {
        if (matches(candidate, token) && next.indexOf(candidate) === -1) next.push(candidate);
      }
    }
    scope = next;
  }
  return scope;
}

function createDocument() {
  const byId = new Map();
  const doc = {
    nodeType: 9,
    createElement(tag) {
      const node = new Element(tag, doc);
      const setAttribute = node.setAttribute.bind(node);
      node.setAttribute = (name, value) => {
        setAttribute(name, value);
        if (name === "id") byId.set(String(value), node);
      };
      return node;
    },
    createTextNode: (data) => new TextNode(data),
    createDocumentFragment: () => new Fragment(),
    getElementById: (id) => byId.get(String(id)) || null,
    querySelectorAll: (selector) => queryAll(doc.documentElement, selector),
    querySelector: (selector) => queryAll(doc.documentElement, selector)[0] || null,
    /* Document-level events (a key press) and focus, which a test reads back. */
    activeElement: null,
    listeners: {},
    addEventListener(type, handler) { (doc.listeners[type] = doc.listeners[type] || []).push(handler); },
    dispatch(type, event) {
      const payload = Object.assign({ type, target: doc.activeElement || doc.body, preventDefault() {} },
        event || {});
      for (const handler of (doc.listeners[type] || []).slice()) handler(payload);
    },
  };
  doc.documentElement = doc.createElement("html");
  doc.body = doc.createElement("body");
  doc.documentElement.appendChild(doc.body);
  return doc;
}

/* Enough of an HTML parser for the utility's own index.html: no scripts, no
   doctype, no exotica. Reading the real file keeps the shim honest — a test
   cannot pass against an element the page does not have. */
function parseInto(doc, parent, html) {
  const source = String(html)
    .replace(/<!doctype[^>]*>/gi, "")
    .replace(/<script[\s\S]*?<\/script>/gi, "");
  const token = /<!--[\s\S]*?-->|<(\/?)([a-zA-Z][\w-]*)((?:\s+[^\s"'>/=]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'>`]+))?)*)\s*(\/?)>|([^<]+)/g;
  const stack = [parent];
  let match;
  while ((match = token.exec(source)) !== null) {
    if (match[0].startsWith("<!--")) continue;
    if (match[5] !== undefined) {
      if (match[5].trim()) stack[stack.length - 1].appendChild(doc.createTextNode(match[5]));
      continue;
    }
    const tag = match[2].toLowerCase();
    if (match[1] === "/") {
      for (let i = stack.length - 1; i > 0; i--) {
        if (stack[i].localName === tag) { stack.length = i; break; }
      }
      continue;
    }
    const node = doc.createElement(tag);
    const attr = /([^\s"'>/=]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>`]+)))?/g;
    let found;
    while ((found = attr.exec(match[3] || "")) !== null) {
      const value = found[2] !== undefined ? found[2]
        : found[3] !== undefined ? found[3]
        : found[4] !== undefined ? found[4] : "";
      node.setAttribute(found[1], value);
    }
    stack[stack.length - 1].appendChild(node);
    if (!VOID.has(tag) && !match[4]) stack.push(node);
  }
  return parent;
}

module.exports = { createDocument, parseInto, serialize, Element, TextNode, Fragment };
