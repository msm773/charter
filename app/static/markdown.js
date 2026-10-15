/* Markdown rendering for the Read view.
   No dependency, no build step, no innerHTML: every piece of document text
   becomes a text node, so nothing a document contains can become markup. Raw
   HTML in a document is therefore shown as the characters it is, which is also
   the honest thing to show for a governed record.

   This is a reader, not an editor and not a CommonMark implementation. It
   covers what governed documents actually contain: headings, paragraphs,
   emphasis, lists, tables, code, block quotes, rules and links. */

(function (global) {
  "use strict";

  /* Only these become clickable. Anything else — javascript:, data:, a
     repo-relative path the utility does not serve — renders as inert text
     carrying its target in a tooltip. */
  const SAFE_SCHEME = /^(?:https?|mailto):/i;
  const ESCAPABLE = "\\`*_{}[]()#+-.!|~>\"'";
  const LIFECYCLE_KEYS = ["id", "title", "status", "authority", "scope",
    "source", "source_sha256", "created", "updated"];

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const key in (attrs || {})) {
      if (attrs[key] === null || attrs[key] === undefined || attrs[key] === "") continue;
      if (key === "class") node.className = attrs[key];
      else node.setAttribute(key, attrs[key]);
    }
    for (const child of (children || [])) if (child) node.appendChild(child);
    return node;
  }

  const text = (value) => document.createTextNode(value);

  /* ------------------------------------------------------------ front matter */

  function unquote(raw) {
    const value = String(raw).trim();
    if (value.length >= 2 && value[0] === '"' && value[value.length - 1] === '"') {
      const body = value.slice(1, -1);
      let out = "";
      for (let i = 0; i < body.length; i++) {
        if (body[i] === "\\" && i + 1 < body.length) {
          const next = body[i + 1];
          out += next === "n" ? "\n" : next;
          i++;
        } else {
          out += body[i];
        }
      }
      return out;
    }
    return value;
  }

  /* Mirrors the codec in app/docs.py: the same restricted subset, read back the
     same way, so the reader shows exactly the fields the utility maintains. */
  function splitFrontMatter(source) {
    const normalised = String(source === null || source === undefined ? "" : source)
      .replace(/\r\n/g, "\n");
    if (!normalised.startsWith("---\n")) return { meta: null, body: normalised };
    const end = normalised.indexOf("\n---", 4);
    if (end === -1) return { meta: null, body: normalised };
    const block = normalised.slice(4, end + 1);
    let rest = normalised.slice(end + 4);
    if (rest.startsWith("\n")) rest = rest.slice(1);

    const meta = [];
    const index = {};
    let currentList = null;
    const put = (key, value) => {
      if (Object.prototype.hasOwnProperty.call(index, key)) {
        meta[index[key]][1] = value;
      } else {
        index[key] = meta.length;
        meta.push([key, value]);
      }
      return index[key];
    };
    for (const line of block.split("\n")) {
      if (!line.trim()) continue;
      const item = /^\s*-\s(.*)$/.exec(line);
      if (item && currentList !== null) {
        meta[currentList][1].push(unquote(item[1]));
        continue;
      }
      const colon = line.indexOf(":");
      if (colon === -1) continue;
      const key = line.slice(0, colon).trim();
      const raw = line.slice(colon + 1).trim();
      if (raw === "") {
        currentList = put(key, []);
      } else if (raw === "[]") {
        put(key, []);
        currentList = null;
      } else if (raw.startsWith("[") && raw.endsWith("]")) {
        const inner = raw.slice(1, -1).trim();
        put(key, inner ? inner.split(",").map((p) => unquote(p.trim())) : []);
        currentList = null;
      } else {
        put(key, unquote(raw));
        currentList = null;
      }
    }
    return { meta, body: rest };
  }

  /* Front matter as a readable metadata block rather than as source. */
  function renderMeta(meta) {
    const known = meta.filter(([k]) => LIFECYCLE_KEYS.indexOf(k) !== -1);
    const rest = meta.filter(([k]) => LIFECYCLE_KEYS.indexOf(k) === -1);
    const ordered = LIFECYCLE_KEYS
      .map((k) => known.find(([key]) => key === k))
      .filter(Boolean)
      .concat(rest);

    const list = el("dl", { class: "md-meta-list" }, []);
    for (const [key, value] of ordered) {
      const shown = Array.isArray(value) ? value.join(", ") : String(value);
      if (!shown) continue;
      list.appendChild(el("dt", {}, [text(key.replace(/_/g, " "))]));
      list.appendChild(el("dd", {}, [text(shown)]));
    }
    return el("section", { class: "md-meta" }, [
      el("h4", {}, [text("Document metadata")]),
      list,
    ]);
  }

  /* ------------------------------------------------------------------ inline */

  function matchLink(src, start) {
    if (src[start] !== "[") return null;
    let depth = 1;
    let i = start + 1;
    while (i < src.length && depth > 0) {
      const ch = src[i];
      if (ch === "\\") { i += 2; continue; }
      if (ch === "[") depth++;
      else if (ch === "]") depth--;
      i++;
    }
    if (depth !== 0 || src[i] !== "(") return null;
    const label = src.slice(start + 1, i - 1);
    let j = i + 1;
    let parens = 1;
    while (j < src.length && parens > 0) {
      const ch = src[j];
      if (ch === "\\") { j += 2; continue; }
      if (ch === "(") parens++;
      else if (ch === ")") parens--;
      j++;
    }
    if (parens !== 0) return null;

    let dest = src.slice(i + 1, j - 1).trim();
    let title = "";
    const titled = /^([\s\S]*?)\s+(?:"([^"]*)"|'([^']*)')$/.exec(dest);
    if (titled) {
      dest = titled[1].trim();
      title = titled[2] !== undefined ? titled[2] : titled[3];
    }
    if (dest.startsWith("<") && dest.endsWith(">")) dest = dest.slice(1, -1);
    return { label: label, dest: dest, title: title, end: j };
  }

  function linkNode(link) {
    const label = link.label.trim();
    if (SAFE_SCHEME.test(link.dest)) {
      const anchor = el("a", {
        href: link.dest, target: "_blank", rel: "noopener noreferrer nofollow",
        title: link.title,
      }, []);
      inline(label || link.dest, anchor);
      return anchor;
    }
    /* Not refused, not made clickable: the target is shown so the reader can
       follow it deliberately. */
    const span = el("span", {
      class: "md-link-inert",
      title: link.dest + (link.title ? " — " + link.title : ""),
    }, []);
    inline(label || link.dest, span);
    return span;
  }

  function imageNode(link) {
    const alt = link.label.trim() || link.dest;
    return el("span", { class: "md-image", title: link.dest }, [text("[image: " + alt + "]")]);
  }

  function matchCodeSpan(src, start) {
    return /^(`+)([\s\S]*?)\1(?!`)/.exec(src.slice(start));
  }

  function matchEmphasis(src, start) {
    const marker = src[start];
    let run = 0;
    while (src[start + run] === marker) run++;
    if (marker === "~") {
      if (run < 2) return null;
      run = 2;
    } else if (run > 3) {
      run = 3;
    }
    const after = src[start + run] || "";
    if (!after || /\s/.test(after)) return null;
    // snake_case and file_names are words, not emphasis.
    if (marker === "_" && /[A-Za-z0-9]/.test(src[start - 1] || "")) return null;

    const rest = src.slice(start + run);
    let i = 0;
    while (i < rest.length) {
      if (rest[i] === "\\") { i += 2; continue; }
      if (rest[i] === "`") {
        const code = matchCodeSpan(rest, i);
        if (code) { i += code[0].length; continue; }
      }
      if (rest[i] === marker) {
        let close = 0;
        while (rest[i + close] === marker) close++;
        if (close >= run && i > 0 && !/\s/.test(rest[i - 1])
            && !(marker === "_" && /[A-Za-z0-9]/.test(rest[i + close] || ""))) {
          const inner = rest.slice(0, i);
          const end = start + run + i + run;
          if (marker === "~") return { tag: "del", inner: inner, end: end };
          if (run === 3) return { tag: "strong", inner: marker + inner + marker, end: end };
          return { tag: run === 2 ? "strong" : "em", inner: inner, end: end };
        }
        i += close;
        continue;
      }
      i++;
    }
    return null;
  }

  function inline(source, parent) {
    const src = String(source || "");
    let buffer = "";
    const flush = () => {
      if (buffer) { parent.appendChild(text(buffer)); buffer = ""; }
    };

    let i = 0;
    while (i < src.length) {
      const ch = src[i];

      if (ch === "\\") {
        const next = src[i + 1];
        if (next === "\n") { flush(); parent.appendChild(el("br", {}, [])); i += 2; continue; }
        if (next && ESCAPABLE.indexOf(next) !== -1) { buffer += next; i += 2; continue; }
      }

      if (ch === "\n") {
        // Two trailing spaces is Markdown's hard line break; otherwise a
        // wrapped source line is still one paragraph line.
        if (/ {2,}$/.test(buffer)) {
          buffer = buffer.replace(/ +$/, "");
          flush();
          parent.appendChild(el("br", {}, []));
        } else {
          buffer += " ";
        }
        i++;
        continue;
      }

      if (ch === "`") {
        const code = matchCodeSpan(src, i);
        if (code) {
          flush();
          parent.appendChild(el("code", { class: "md-code-inline" },
            [text(code[2].replace(/^ ([\s\S]*) $/, "$1"))]));
          i += code[0].length;
          continue;
        }
      }

      if (ch === "!" && src[i + 1] === "[") {
        const link = matchLink(src, i + 1);
        if (link) { flush(); parent.appendChild(imageNode(link)); i = link.end; continue; }
      }

      if (ch === "[") {
        const link = matchLink(src, i);
        if (link) { flush(); parent.appendChild(linkNode(link)); i = link.end; continue; }
      }

      if (ch === "<") {
        const auto = /^<((?:https?|mailto):[^\s<>]+)>/.exec(src.slice(i));
        if (auto) {
          flush();
          parent.appendChild(el("a", {
            href: auto[1], target: "_blank", rel: "noopener noreferrer nofollow",
          }, [text(auto[1])]));
          i += auto[0].length;
          continue;
        }
      }

      if (ch === "*" || ch === "_" || ch === "~") {
        const emphasis = matchEmphasis(src, i);
        if (emphasis) {
          flush();
          const node = el(emphasis.tag, {}, []);
          inline(emphasis.inner, node);
          parent.appendChild(node);
          i = emphasis.end;
          continue;
        }
      }

      buffer += ch;
      i++;
    }
    flush();
    return parent;
  }

  /* ------------------------------------------------------------------ tables */

  function splitRow(row) {
    let s = row.trim();
    if (s.startsWith("|")) s = s.slice(1);
    if (s.endsWith("|") && !s.endsWith("\\|")) s = s.slice(0, -1);
    const cells = [];
    let cell = "";
    for (let i = 0; i < s.length; i++) {
      if (s[i] === "\\" && s[i + 1] === "|") { cell += "|"; i++; continue; }
      if (s[i] === "|") { cells.push(cell); cell = ""; continue; }
      cell += s[i];
    }
    cells.push(cell);
    return cells;
  }

  function alignmentsOf(row) {
    if (!row || row.indexOf("|") === -1) return null;
    const cells = splitRow(row).map((c) => c.trim());
    if (!cells.length || !cells.every((c) => /^:?-+:?$/.test(c))) return null;
    return cells.map((c) => {
      const left = c.startsWith(":");
      const right = c.endsWith(":");
      if (left && right) return "center";
      if (right) return "right";
      if (left) return "left";
      return "";
    });
  }

  function renderTable(header, aligns, rows) {
    const cellsOf = (row, tag) => {
      const values = splitRow(row);
      const out = [];
      for (let i = 0; i < aligns.length; i++) {
        const cell = el(tag, { style: aligns[i] ? "text-align:" + aligns[i] : null }, []);
        inline((values[i] === undefined ? "" : values[i]).trim(), cell);
        out.push(cell);
      }
      return out;
    };
    const table = el("table", { class: "md-table" }, [
      el("thead", {}, [el("tr", {}, cellsOf(header, "th"))]),
    ]);
    const body = el("tbody", {}, []);
    for (const row of rows) body.appendChild(el("tr", {}, cellsOf(row, "td")));
    table.appendChild(body);
    // Wide tables scroll inside themselves rather than widening the page.
    return el("div", { class: "md-table-wrap" }, [table]);
  }

  /* ------------------------------------------------------------------ blocks */

  const RE_FENCE = /^ {0,3}(`{3,}|~{3,})\s*(.*)$/;
  const RE_RULE = /^ {0,3}([-*_])[ \t]*(?:\1[ \t]*){2,}$/;
  const RE_HEADING = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
  const RE_QUOTE = /^ {0,3}>\s?(.*)$/;
  const RE_ITEM = /^( *)([-*+]|\d{1,9}[.)])(\s+)(.*)$/;

  function isBlank(line) { return !line || !line.trim(); }
  const RE_COMMENT = /^ {0,3}<!--.*-->\s*$/;

  function startsBlock(line) {
    return RE_FENCE.test(line) || RE_RULE.test(line) || RE_HEADING.test(line)
      || RE_QUOTE.test(line) || RE_ITEM.test(line);
  }

  function readList(lines, start, parent) {
    const first = RE_ITEM.exec(lines[start]);
    const indent = first[1].length;
    const ordered = /\d/.test(first[2]);
    const items = [];
    let i = start;
    let loose = false;
    let pendingBlank = false;

    while (i < lines.length) {
      const line = lines[i];
      if (isBlank(line)) {
        // A blank line only ends the list if what follows is not part of it.
        const next = lines[i + 1];
        if (next === undefined) { i++; break; }
        const nextItem = RE_ITEM.exec(next);
        const continues = (nextItem && nextItem[1].length === indent
                           && /\d/.test(nextItem[2]) === ordered)
          || (!isBlank(next) && next.search(/\S/) > indent);
        if (!continues) break;
        pendingBlank = true;
        i++;
        continue;
      }

      const match = RE_ITEM.exec(line);
      const sameLevel = match && match[1].length === indent && /\d/.test(match[2]) === ordered;
      if (sameLevel) {
        if (pendingBlank) { loose = true; pendingBlank = false; }
        const contentIndent = indent + match[2].length + match[3].length;
        items.push({ lines: [match[4]], contentIndent: contentIndent });
        i++;
        continue;
      }
      if (!items.length) break;
      const current = items[items.length - 1];
      if (line.search(/\S/) < current.contentIndent && !isBlank(line)) {
        // Dedented below this item's content: the list is over unless it is a
        // lazy continuation of the item's paragraph.
        if (startsBlock(line) || pendingBlank) break;
      }
      if (pendingBlank) { current.lines.push(""); loose = true; pendingBlank = false; }
      current.lines.push(line.slice(Math.min(current.contentIndent, line.search(/\S/))));
      i++;
    }

    const list = el(ordered ? "ol" : "ul", { class: "md-list" }, []);
    if (ordered) {
      const startAt = parseInt(first[2], 10);
      if (startAt !== 1 && !isNaN(startAt)) list.setAttribute("start", String(startAt));
    }
    for (const item of items) {
      const holder = el("div", {}, []);
      blocks(item.lines, holder);
      const node = el("li", {}, []);
      let first = true;
      while (holder.firstChild) {
        const child = holder.firstChild;
        holder.removeChild(child);
        // A tight item reads as text, not as a paragraph inside a bullet —
        // even when a nested list follows it.
        if (first && !loose && child.nodeName === "P") {
          while (child.firstChild) {
            const inner = child.firstChild;
            child.removeChild(inner);
            node.appendChild(inner);
          }
        } else {
          node.appendChild(child);
        }
        first = false;
      }
      list.appendChild(node);
    }
    parent.appendChild(list);
    return i;
  }

  function blocks(lines, parent) {
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (isBlank(line)) { i++; continue; }
      // A line that is wholly an HTML comment is a note for the file, not
      // content — AGENT-CONTEXT.md marks its generated region this way — so, as in
      // any Markdown renderer, it is not shown. Other raw HTML is still text.
      if (RE_COMMENT.test(line)) { i++; continue; }

      const fence = RE_FENCE.exec(line);
      if (fence) {
        const marker = fence[1][0];
        const closing = new RegExp("^ {0,3}\\" + marker + "{" + fence[1].length + ",}\\s*$");
        const buffer = [];
        i++;
        while (i < lines.length && !closing.test(lines[i])) { buffer.push(lines[i]); i++; }
        if (i < lines.length) i++;  // the closing fence itself
        const info = (fence[2] || "").trim().split(/\s+/)[0];
        const code = el("code", { class: info ? "language-" + info.replace(/[^\w.+-]/g, "") : null },
          [text(buffer.join("\n") + (buffer.length ? "\n" : ""))]);
        parent.appendChild(el("pre", { class: "md-code" }, [code]));
        continue;
      }

      if (RE_RULE.test(line)) { parent.appendChild(el("hr", {}, [])); i++; continue; }

      const heading = RE_HEADING.exec(line);
      if (heading) {
        const node = el("h" + heading[1].length, {}, []);
        inline(heading[2], node);
        parent.appendChild(node);
        i++;
        continue;
      }

      if (RE_QUOTE.test(line)) {
        const inner = [];
        while (i < lines.length && RE_QUOTE.test(lines[i])) {
          inner.push(RE_QUOTE.exec(lines[i])[1]);
          i++;
        }
        const quote = el("blockquote", {}, []);
        blocks(inner, quote);
        parent.appendChild(quote);
        continue;
      }

      if (RE_ITEM.test(line)) { i = readList(lines, i, parent); continue; }

      const aligns = line.indexOf("|") !== -1 ? alignmentsOf(lines[i + 1]) : null;
      if (aligns) {
        const rows = [];
        let j = i + 2;
        while (j < lines.length && !isBlank(lines[j]) && lines[j].indexOf("|") !== -1
               && !startsBlock(lines[j])) {
          rows.push(lines[j]);
          j++;
        }
        parent.appendChild(renderTable(line, aligns, rows));
        i = j;
        continue;
      }

      // Paragraph, with `=` underlining read as a level-one heading because
      // converted Word documents produce it.
      const paragraph = [];
      while (i < lines.length && !isBlank(lines[i]) && !startsBlock(lines[i])) {
        if (paragraph.length && /^ {0,3}=+\s*$/.test(lines[i])) break;
        if (lines[i].indexOf("|") !== -1 && alignmentsOf(lines[i + 1])) break;
        paragraph.push(lines[i]);
        i++;
      }
      if (!paragraph.length) { i++; continue; }
      if (i < lines.length && /^ {0,3}=+\s*$/.test(lines[i]) && paragraph.length === 1) {
        const node = el("h1", {}, []);
        inline(paragraph[0].trim(), node);
        parent.appendChild(node);
        i++;
        continue;
      }
      const node = el("p", {}, []);
      inline(paragraph.join("\n").trim(), node);
      parent.appendChild(node);
    }
    return parent;
  }

  function render(markdown) {
    const fragment = document.createDocumentFragment();
    const lines = String(markdown === null || markdown === undefined ? "" : markdown)
      .replace(/\r\n/g, "\n")
      .replace(/\t/g, "    ")
      .split("\n");
    blocks(lines, fragment);
    return fragment;
  }

  global.CharterMarkdown = {
    render: render,
    renderMeta: renderMeta,
    splitFrontMatter: splitFrontMatter,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
