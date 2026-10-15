/* Read view: Markdown is rendered, and rendering it cannot introduce markup.

   Run: node tests/markdown.test.js   (or via `python -m tests.ui`) */

"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const { createDocument, serialize } = require("./domshim");

const ROOT = path.dirname(__dirname);
const OK = "[32m✓[0m";

global.document = createDocument();
vm.runInThisContext(
  fs.readFileSync(path.join(ROOT, "app", "static", "markdown.js"), "utf8"),
  { filename: "markdown.js" });

const md = global.CharterMarkdown;
let failures = 0;

function check(condition, label) {
  if (condition) { console.log(`  ${OK} ${label}`); return; }
  failures++;
  console.log(`  [31m✗[0m ${label}`);
}

const html = (source) => serialize(md.render(source));

/* ------------------------------------------------------------------ blocks */

console.log("headings, paragraphs and emphasis");
check(html("# Title\n\n## Sub") === "<h1>Title</h1><h2>Sub</h2>", "ATX headings become h1..h6");
check(html("###### Deep") === "<h6>Deep</h6>", "six levels supported");
check(html("Title\n=====") === "<h1>Title</h1>", "an `=` underline reads as a heading");
check(html("One line\nwrapped here.") === "<p>One line wrapped here.</p>",
  "a wrapped source line is still one paragraph");
check(html("a\n\nb") === "<p>a</p><p>b</p>", "a blank line starts a new paragraph");
check(html("**bold** and *italic*")
  === "<p><strong>bold</strong> and <em>italic</em></p>", "bold and italic");
check(html("__bold__ and _italic_")
  === "<p><strong>bold</strong> and <em>italic</em></p>", "underscore forms too");
check(html("a snake_case_name here") === "<p>a snake_case_name here</p>",
  "underscores inside a word are not emphasis");
check(html("***both***") === "<p><strong><em>both</em></strong></p>", "bold italic nests");
check(html("line one  \nline two") === "<p>line one<br>line two</p>",
  "two trailing spaces is a hard break");
check(html("---") === "<hr>", "a rule is a rule");
check(html("> quoted\n> lines") === "<blockquote><p>quoted lines</p></blockquote>", "block quotes");

console.log("\nlists");
check(html("- a\n- b") === "<ul class=\"md-list\"><li>a</li><li>b</li></ul>", "tight bullet list");
check(html("1. a\n2. b") === "<ol class=\"md-list\"><li>a</li><li>b</li></ol>", "ordered list");
check(html("3. a\n4. b").indexOf("start=\"3\"") !== -1, "an ordered list keeps its first number");
check(html("- a\n\n- b").indexOf("<li><p>a</p></li>") !== -1,
  "a loose list keeps its paragraphs");
check(html("- a\n  - b\n- c")
  === "<ul class=\"md-list\"><li>a<ul class=\"md-list\"><li>b</li></ul></li><li>c</li></ul>",
  "nested lists nest");
check(html("- **a** and `b`")
  === "<ul class=\"md-list\"><li><strong>a</strong> and <code class=\"md-code-inline\">b</code></li></ul>",
  "inline markup works inside list items");

console.log("\ntables");
const table = html("| Document | Governs |\n| --- | :---: |\n| A \\| B | yes |");
check(table.indexOf("<table class=\"md-table\">") !== -1, "a pipe table becomes a table");
check(table.indexOf("<th>Document</th>") !== -1, "header cells");
check(table.indexOf("<td>A | B</td>") !== -1, "an escaped pipe is content, not a cell boundary");
check(table.indexOf("text-align:center") !== -1, "alignment row honoured");
check(html("| a |\n| --- |\n| b |\n\nafter").indexOf("<p>after</p>") !== -1,
  "a blank line ends the table");
check(html("just | a pipe") === "<p>just | a pipe</p>",
  "a pipe without a delimiter row is not a table");

console.log("\ncode");
check(html("```\nplain\n```") === "<pre class=\"md-code\"><code>plain\n</code></pre>",
  "fenced code block");
check(html("```python\nx = 1\n```").indexOf("class=\"language-python\"") !== -1,
  "the info string is recorded as a language class");
check(html("`inline`") === "<p><code class=\"md-code-inline\">inline</code></p>", "inline code");
check(html("```\n# not a heading\n- not a list\n```")
  === "<pre class=\"md-code\"><code># not a heading\n- not a list\n</code></pre>",
  "code content is never parsed as Markdown");
check(html("`*literal*`").indexOf("<em>") === -1, "no emphasis inside inline code");

console.log("\nlinks and safety");
const link = html("[docs](https://example.com/x 'why')");
check(link.indexOf("<a href=\"https://example.com/x\"") !== -1, "https links are clickable");
check(link.indexOf("rel=\"noopener noreferrer nofollow\"") !== -1, "and are opened safely");
check(html("[mail](mailto:a@b.c)").indexOf("href=\"mailto:a@b.c\"") !== -1, "mailto is allowed");
check(html("<https://example.com>").indexOf("<a href=\"https://example.com\"") !== -1, "autolinks");
const unsafe = html("[click](javascript:alert(1))");
check(unsafe.indexOf("<a ") === -1 && unsafe.indexOf("javascript:alert(1)") !== -1,
  "a javascript: URL is never an anchor, and its target is shown instead");
check(html("[data](data:text/html,<script>)").indexOf("<a ") === -1, "data: URLs are not anchors");
check(html("[a note](authority-candidates/note.md)").indexOf("md-link-inert") !== -1,
  "a repo-relative link renders inert, carrying its target");
check(html("![shot](x.png)").indexOf("[image: shot]") !== -1, "images are described, not fetched");
check(html("<!-- context-governance:begin -->\n\n# Map\n\n<!-- context-governance:end -->")
        .indexOf("context-governance") === -1 && html("<!-- note -->\n\n# Map").indexOf("<h1>Map</h1>") !== -1,
  "a line that is wholly an HTML comment is not shown, as in any Markdown renderer");
check(html("before <!-- inline --> after").indexOf("&lt;!-- inline --&gt;") !== -1,
  "but a comment inside text is still shown as the characters it is");

const injected = html("<script>alert('x')</script>\n\n<img src=x onerror=\"alert(1)\">");
check(injected.indexOf("<script") === -1 && injected.indexOf("&lt;script&gt;") !== -1,
  "raw HTML in a document is shown as text, never as markup");
check(injected.indexOf("onerror") !== -1 && injected.indexOf("<img") === -1,
  "an inert img tag stays inert");
check(html("[x](https://e.com\" onmouseover=\"alert(1))").indexOf("onmouseover=\"alert") === -1,
  "a quote inside a URL cannot break out of the attribute");

/* ------------------------------------------------------------- front matter */

console.log("\nfront matter");
const document = [
  "---",
  "id: booking-data-model",
  "title: Booking data model",
  "status: active",
  "authority: authoritative",
  'scope: "Booking persistence, v2"',
  "superseded_by: []",
  "supersedes:",
  "  - booking-data-model-v1",
  "  - booking-holds",
  "---",
  "",
  "# Booking data model",
  "",
  "One row per booking.",
].join("\n");

const split = md.splitFrontMatter(document);
const meta = new Map(split.meta);
check(meta.get("id") === "booking-data-model", "front matter is parsed, not shown as source");
check(meta.get("scope") === "Booking persistence, v2", "quoted scalars are unquoted");
check(Array.isArray(meta.get("supersedes")) && meta.get("supersedes").length === 2,
  "list fields are parsed as lists");
check(split.body.trimStart().startsWith("# Booking data model")
      && split.body.indexOf("authority:") === -1,
  "the body starts after the closing fence, exactly as app/docs.py splits it");
check(serialize(md.render(split.body)).startsWith("<h1>Booking data model</h1>"),
  "and renders as a document, not as a code block");

const metaHtml = serialize(md.renderMeta(split.meta));
check(metaHtml.indexOf("<dt>status</dt><dd>active</dd>") !== -1,
  "metadata renders as a readable list");
check(metaHtml.indexOf("<dd>booking-data-model-v1, booking-holds</dd>") !== -1, "list fields read as text");
check(md.splitFrontMatter("# No front matter\n").meta === null,
  "a document without front matter still renders");

console.log("");
if (failures) {
  console.log(`${failures} markdown check(s) failed.`);
  process.exit(1);
}
console.log("All markdown checks passed.");
