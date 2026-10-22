"""Deterministic conversion of source files to Markdown.

DOCX is parsed with the standard library only (a .docx is a zip of XML), so the
utility runs with no third-party packages at all. PDF text extraction needs
`pypdf`; if it is missing we say so plainly instead of guessing.
"""
from __future__ import annotations

import importlib.util
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any, Dict, List, Optional, Tuple

from .docs import leading_front_matter, not_text, single_line

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

SUPPORTED = {
    ".md": "Markdown",
    ".markdown": "Markdown",
    ".txt": "Plain text",
    ".text": "Plain text",
    ".docx": "Word document",
    ".pdf": "PDF",
}


class ConversionError(RuntimeError):
    pass


def extension(filename: str) -> str:
    dot = filename.rfind(".")
    return filename[dot:].lower() if dot != -1 else ""


def pdf_available() -> bool:
    """Whether the optional `pypdf` package is installed. Asked of the import
    system rather than by importing it, so asking costs nothing."""
    return importlib.util.find_spec("pypdf") is not None


# --- DOCX --------------------------------------------------------------------

# Word's boolean (ST_OnOff) values that turn a property off. A property that
# is present with no value, or with any other value, is on.
_OFF = ("0", "false", "off")

# Markdown's hard line break: a backslash ending the line.
HARD_BREAK = "\\\n"


def _on(props: Optional[ET.Element], name: str) -> bool:
    if props is None:
        return False
    el = props.find(W + name)
    if el is None:
        return False
    return (el.get(W + "val") or "").strip().lower() not in _OFF


def _styled(text: str, bold: bool, italic: bool) -> str:
    stripped = text.strip()
    if not stripped:
        return text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    if bold:
        stripped = f"**{stripped}**"
    if italic:
        stripped = f"_{stripped}_"
    return lead + stripped + trail


def _run_lines(node: ET.Element) -> List[str]:
    """The text of `node`'s runs as the lines its explicit line breaks make,
    each run's children read in document order. A page or column break is
    not a line break: it stays a plain newline, as before."""
    lines: List[List[str]] = [[]]
    for run in node.iter():
        if run.tag != W + "r":
            continue
        props = run.find(W + "rPr")
        bold, italic = _on(props, "b"), _on(props, "i")
        segments = [""]
        for child in run:
            tag = child.tag
            if tag == W + "t":
                segments[-1] += child.text or ""
            elif tag == W + "tab":
                segments[-1] += " "
            elif tag == W + "cr" or (tag == W + "br" and child.get(W + "type") in (None, "textWrapping")):
                segments.append("")
            elif tag == W + "br":
                segments[-1] += "\n"
        for index, segment in enumerate(segments):
            if index:
                lines.append([])
            if segment:
                lines[-1].append(_styled(segment, bold, italic))
    texts = ["".join(parts).strip() for parts in lines]
    # A break at either end of the paragraph separates nothing.
    while texts and not texts[0]:
        texts.pop(0)
    while texts and not texts[-1]:
        texts.pop()
    return texts


def _runs_to_markdown(node: ET.Element, line_break: str = HARD_BREAK) -> str:
    """`node`'s text, its explicit line breaks written as `line_break`: a
    Markdown hard break unless the text must stay on one line."""
    lines = _run_lines(node)
    if line_break.strip() == "":
        lines = [line for line in lines if line]
    return line_break.join(lines)


def _paragraph_markdown(para: ET.Element, numbering: Dict[str, str]) -> str:
    if not _run_lines(para):
        return ""
    props = para.find(W + "pPr")
    style = ""
    if props is not None:
        style_el = props.find(W + "pStyle")
        if style_el is not None:
            style = (style_el.get(W + "val") or "").lower()
    # A Markdown heading is one line: a line break in one is a space.
    match = re.match(r"heading(\d)", style) or re.match(r"h(\d)$", style)
    if match:
        level = min(int(match.group(1)), 6)
        return "#" * level + " " + _runs_to_markdown(para, " ")
    if style in ("title",):
        return "# " + _runs_to_markdown(para, " ")
    if style in ("subtitle",):
        return "## " + _runs_to_markdown(para, " ")
    if props is not None and props.find(W + "numPr") is not None:
        num_pr = props.find(W + "numPr")
        ilvl_el = num_pr.find(W + "ilvl")
        level = int(ilvl_el.get(W + "val")) if ilvl_el is not None else 0
        num_el = num_pr.find(W + "numId")
        num_id = num_el.get(W + "val") if num_el is not None else ""
        marker = "1." if numbering.get(num_id) == "decimal" else "-"
        indent = "  " * level
        # Lines after a break continue the item, indented to its text.
        text = _runs_to_markdown(para, HARD_BREAK + indent + " " * (len(marker) + 1))
        return indent + f"{marker} {text}"
    if style in ("quote", "intensequote"):
        return "> " + _runs_to_markdown(para, HARD_BREAK + "> ")
    return _runs_to_markdown(para)


def _table_markdown(table: ET.Element) -> List[str]:
    rows: List[List[str]] = []
    for tr in table.findall(W + "tr"):
        cells = []
        for tc in tr.findall(W + "tc"):
            # A table row is one line: a line break in a cell is a space.
            cell = " ".join(
                filter(None, (_runs_to_markdown(p, " ") for p in tc.findall(W + "p")))
            )
            cells.append(cell.replace("|", "\\|").strip())
        if cells:
            rows.append(cells)
    if not rows:
        return []
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |",
           "|" + "|".join([" --- "] * width) + "|"]
    for row in rows[1:]:
        out.append("| " + " | ".join(row) + " |")
    return out


def _numbering_formats(zf: zipfile.ZipFile) -> Dict[str, str]:
    formats: Dict[str, str] = {}
    try:
        root = ET.fromstring(zf.read("word/numbering.xml"))
    except Exception:
        return formats
    abstract: Dict[str, str] = {}
    for node in root.findall(W + "abstractNum"):
        aid = node.get(W + "abstractNumId") or ""
        lvl = node.find(W + "lvl")
        fmt_el = lvl.find(W + "numFmt") if lvl is not None else None
        abstract[aid] = (fmt_el.get(W + "val") if fmt_el is not None else "bullet") or "bullet"
    for node in root.findall(W + "num"):
        nid = node.get(W + "numId") or ""
        ref = node.find(W + "abstractNumId")
        aid = ref.get(W + "val") if ref is not None else ""
        formats[nid] = abstract.get(aid, "bullet")
    return formats


def docx_to_markdown(data: bytes) -> str:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        xml = zf.read("word/document.xml")
    except Exception as exc:  # noqa: BLE001
        raise ConversionError(f"This does not look like a readable .docx file ({exc}).")
    numbering = _numbering_formats(zf)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise ConversionError(f"This .docx file's content could not be read ({exc}).")
    body = root.find(W + "body")
    if body is None:
        raise ConversionError("The .docx file has no document body.")
    blocks: List[str] = []
    try:
        for child in body:
            if child.tag == W + "p":
                md = _paragraph_markdown(child, numbering)
                if md:
                    blocks.append(md)
            elif child.tag == W + "tbl":
                rows = _table_markdown(child)
                if rows:
                    blocks.append("\n".join(rows))
    except ConversionError:
        raise
    except Exception as exc:  # noqa: BLE001 — malformed structure inside the document
        raise ConversionError(f"This .docx file's content could not be read ({exc}).")
    return _join_blocks(blocks)


def _join_blocks(blocks: List[str]) -> str:
    out: List[str] = []
    for block in blocks:
        is_list = block.lstrip().startswith(("- ", "1. "))
        if out and is_list and out[-1].lstrip().startswith(("- ", "1. ")):
            out.append(block)
        else:
            if out:
                out.append("")
            out.append(block)
    text = "\n".join(out).strip()
    return re.sub(r"\n{3,}", "\n\n", text) + "\n"


# --- PDF ---------------------------------------------------------------------

def pdf_to_markdown(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except Exception:
        raise ConversionError(
            "PDF conversion needs the optional `pypdf` package. Install it with "
            "`pip install pypdf`, or convert the file to Markdown yourself first."
        )
    try:
        reader = PdfReader(io.BytesIO(data))
        pages: List[str] = []
        for number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").replace("\r\n", "\n").strip()
            text = re.sub(r"[ \t]+\n", "\n", text)
            text = re.sub(r"\n{3,}", "\n\n", text)
            pages.append(f"## Page {number}\n\n{text}" if text
                         else f"## Page {number}\n\n_No extractable text._")
    except ConversionError:
        raise
    except Exception as exc:  # noqa: BLE001 — pypdf raises several error types
        raise ConversionError(f"This does not look like a readable PDF file ({exc}).")
    if not pages:
        raise ConversionError("The PDF has no pages.")
    return "\n\n".join(pages).strip() + "\n"


# --- text / markdown ---------------------------------------------------------

# Byte-order marks, longest first: a UTF-32 LE mark begins with the UTF-16 LE one.
_BOMS = ((b"\xff\xfe\x00\x00", "utf-32-le", "UTF-32"), (b"\x00\x00\xfe\xff", "utf-32-be", "UTF-32"),
         (b"\xef\xbb\xbf", "utf-8", ""), (b"\xff\xfe", "utf-16-le", "UTF-16"),
         (b"\xfe\xff", "utf-16-be", "UTF-16"))

NOT_TEXT = ("This file is not UTF-8 or UTF-16 text, so Charter cannot read it without guessing. "
            "Save it as UTF-8 and choose it again. Nothing was filed.")


def _utf16_without_bom(data: bytes) -> str:
    """The encoding of UTF-16 text saved without a byte-order mark, when its
    zero bytes say so unmistakably, or "". Most characters of a Markdown or
    text file are ASCII, whose UTF-16 form has a zero byte on one side."""
    if len(data) < 4 or len(data) % 2:
        return ""
    even, odd = data[0::2], data[1::2]
    if odd.count(0) >= len(odd) * 0.6 and not even.count(0):
        return "utf-16-le"
    if even.count(0) >= len(even) * 0.6 and not odd.count(0):
        return "utf-16-be"
    return ""


def decode_text(data: bytes) -> Tuple[str, str]:
    """(text, encoding name to tell the person, or "" for UTF-8). Decoded
    strictly: bytes that are not text in the encoding the file declares, or
    in UTF-8 or unmistakable UTF-16, are refused rather than replaced."""
    for bom, codec, label in _BOMS:
        if data.startswith(bom):
            try:
                return data[len(bom):].decode(codec), label
            except UnicodeDecodeError:
                raise ConversionError(NOT_TEXT)
    try:
        return data.decode("utf-8"), ""
    except UnicodeDecodeError:
        pass
    codec = _utf16_without_bom(data)
    if codec:
        try:
            return data.decode(codec), "UTF-16"
        except UnicodeDecodeError:
            pass
    raise ConversionError(NOT_TEXT)


def text_to_markdown(data: bytes) -> Tuple[str, str]:
    """(markdown, the encoding to tell the person, or "" for UTF-8)."""
    text, label = decode_text(data)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.strip() + "\n", label


# A converted document's own title and scope may be offered to the person as
# editable suggestions. Nothing else in its front matter is carried over:
# identity, authority, lifecycle, source, dates, supersession and integrity
# are Charter's to assign, and other tools' keys mean nothing here.
SUGGESTED = ("title", "scope")


def remove_front_matter(markdown: str) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Markdown without a recognizable front-matter block at its top, and
    what that block offered: a valid one-line `title` and `scope` as
    suggestions (`used`), and every other key it had, not carried over
    (`dropped`). (markdown, None) when there is no such block."""
    found = leading_front_matter(markdown)
    if found is None:
        return markdown, None
    meta, body, keys = found
    offered = {k: single_line(meta.get(k)) for k in SUGGESTED}
    used = [k for k in SUGGESTED if offered[k]]
    dropped = [k for k in dict.fromkeys(keys) if k not in used]
    body = body.strip()
    return (body + "\n" if body else ""), dict(offered, used=used, dropped=dropped)


# --- entry point -------------------------------------------------------------

def to_markdown(filename: str, data: bytes) -> Tuple[str, List[str]]:
    """Return (markdown, notes). Raises ConversionError on unsupported input."""
    ext = extension(filename)
    notes: List[str] = []
    if ext in (".md", ".markdown", ".txt", ".text"):
        markdown, label = text_to_markdown(data)
        notes.append("Markdown kept as-is, apart from any front matter at its top."
                     if ext in (".md", ".markdown") else
                     "Plain text kept as-is. Structure was not inferred.")
        if label:
            notes.append(f"Read as {label} text; the candidate is saved as UTF-8.")
    elif ext == ".docx":
        markdown = docx_to_markdown(data)
        notes.append("Headings, lists and tables converted. Images and comments are dropped.")
    elif ext == ".pdf":
        markdown = pdf_to_markdown(data)
        notes.append("Text extracted per page. Layout, images and tables are not preserved.")
    else:
        raise ConversionError(
            f"Unsupported file type `{ext or filename}`. Supported: "
            + ", ".join(sorted(SUPPORTED)) + "."
        )
    problem = not_text(markdown)
    if problem:
        raise ConversionError(f"This file cannot be used as it is: {problem}. Check that it is "
                              "a text document, saved as UTF-8. Nothing was filed.")
    if not markdown.strip():
        notes.append("No text could be extracted. Check the original file.")
    return markdown, notes


def strip_leading_title(markdown: str) -> Tuple[str, str]:
    """A leading H1 and the body after it. The heading suggests the document's
    title; Create candidate keeps it in the text."""
    lines = markdown.split("\n")
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            rest = "\n".join(lines[index + 1:]).lstrip("\n")
            return title, rest
        break
    return "", markdown
