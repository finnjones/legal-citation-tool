"""Reading and writing Word footnotes.

Everything here operates at the raw OOXML level (zipfile + lxml) rather than
through python-docx, because python-docx has no footnote API at all: footnotes
live in a separate `word/footnotes.xml` part, referenced from the body only by
`w:footnoteReference` elements (there is no relationship id on the run itself,
only a package-level relationship declaring the part's existence).

Everything not touched by a write (styles, media, headers, other XML parts) is
copied through unchanged, byte-for-byte.
"""

from __future__ import annotations

import copy
import difflib
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from lxml import etree

from .models import BibliographySection, Footnote, FootnoteResult, RichText

# --------------------------------------------------------------------------- #
# OOXML plumbing
# --------------------------------------------------------------------------- #

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"

DOCUMENT_PATH = "word/document.xml"
FOOTNOTES_PATH = "word/footnotes.xml"
STYLES_PATH = "word/styles.xml"

# Relevant subset of CT_RPr's fixed child-element order (ECMA-376 Part 1, §17.3.2),
# used so runs we splice in (or elements we add to a copied rPr) stay schema-valid.
_RPR_ORDER = [
    "rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
    "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden",
    "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
    "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
    "specVanish", "oMath",
]


def qn(tag: str) -> str:
    prefix, local = tag.split(":")
    assert prefix == "w"
    return f"{{{W_NS}}}{local}"


def _local(el) -> str:
    return etree.QName(el).localname


def _parse_xml(data: bytes):
    return etree.fromstring(data)


def _serialize(root) -> bytes:
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + etree.tostring(root)


def _insert_ordered(rpr, new_el) -> None:
    """Insert `new_el` into `rpr` at the position CT_RPr's schema order requires."""
    new_tag = _local(new_el)
    new_idx = _RPR_ORDER.index(new_tag) if new_tag in _RPR_ORDER else len(_RPR_ORDER)
    for child in rpr:
        child_idx = _RPR_ORDER.index(_local(child)) if _local(child) in _RPR_ORDER else len(_RPR_ORDER)
        if child_idx > new_idx:
            child.addprevious(new_el)
            return
    rpr.append(new_el)


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def _run_italic(rpr) -> bool:
    """w:i / w:iCs (honouring w:val="0"/"false"), falling back to an "Emphasis"
    character style (the cheap way to catch italics applied via a style rather
    than direct formatting)."""
    if rpr is None:
        return False
    direct: bool | None = None
    for tag in ("w:i", "w:iCs"):
        el = rpr.find(qn(tag))
        if el is not None:
            val = el.get(qn("w:val"))
            flag = True if val is None else val.strip().lower() not in ("0", "false", "off")
            direct = flag if direct is None else (direct or flag)
    if direct is not None:
        return direct
    style_el = rpr.find(qn("w:rStyle"))
    if style_el is not None and style_el.get(qn("w:val")) == "Emphasis":
        return True
    return False


def _run_text(run) -> str:
    """Concatenate a run's visible text: w:t verbatim, w:tab -> \\t, w:br -> \\n,
    w:delText is ignored (deleted text is never included)."""
    parts: list[str] = []
    for child in run:
        tag = _local(child)
        if tag == "t":
            parts.append(child.text or "")
        elif tag == "tab":
            parts.append("\t")
        elif tag == "br":
            parts.append("\n")
        # delText, footnoteRef, rPr, etc. are all ignored
    return "".join(parts)


def _footnote_reference_order(document_root) -> list[str]:
    """w:id of every real w:footnoteReference in the body, in document order,
    first occurrence only."""
    seen: list[str] = []
    seen_set: set[str] = set()
    for ref in document_root.iter(qn("w:footnoteReference")):
        fid = ref.get(qn("w:id"))
        if fid is not None and fid not in seen_set:
            seen_set.add(fid)
            seen.append(fid)
    return seen


def _footnote_elements(footnotes_root) -> dict[str, "etree._Element"]:
    """id -> <w:footnote> element, skipping separator/continuationSeparator."""
    result = {}
    if footnotes_root is None:
        return result
    for fn in footnotes_root.findall(qn("w:footnote")):
        if fn.get(qn("w:type")) in ("separator", "continuationSeparator"):
            continue
        fid = fn.get(qn("w:id"))
        if fid is not None:
            result[fid] = fn
    return result


def _paragraph_mark_deleted(p) -> bool:
    """True if this paragraph's mark is a tracked deletion (w:pPr/w:rPr/w:del):
    on acceptance the paragraph merges into the next one, so no break should
    be emitted after it."""
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        return False
    rpr = ppr.find(qn("w:rPr"))
    if rpr is None:
        return False
    return rpr.find(qn("w:del")) is not None


def _richtext_from_footnote(fn_elem) -> RichText:
    rt = RichText()
    stripped_leading_space = False
    for pi, p in enumerate(fn_elem.findall(qn("w:p"))):
        # A paragraph whose own mark is a tracked deletion has been merged away
        # (see _mark_paragraph_deleted): don't emit a break for it.
        if pi > 0 and not _paragraph_mark_deleted(p):
            rt.append("\n", False)
        for run in p.iter(qn("w:r")):
            if run.find(qn("w:footnoteRef")) is not None:
                continue  # the reference mark itself, not content
            text = _run_text(run)
            if not stripped_leading_space:
                stripped_leading_space = True
                if text.startswith(" "):
                    text = text[1:]
            if text:
                rt.append(text, _run_italic(run.find(qn("w:rPr"))))
    return rt


def read_footnotes(path: str | Path) -> list[Footnote]:
    """Read all real footnotes (skip separator/continuation footnotes) in document
    order, numbered 1..n, preserving italics as RichText runs."""
    with zipfile.ZipFile(path) as z:
        doc_root = _parse_xml(z.read(DOCUMENT_PATH))
        fn_root = _parse_xml(z.read(FOOTNOTES_PATH)) if FOOTNOTES_PATH in z.namelist() else None

    order = _footnote_reference_order(doc_root)
    fn_map = _footnote_elements(fn_root)

    footnotes: list[Footnote] = []
    for i, fid in enumerate(order, start=1):
        fn_elem = fn_map.get(fid)
        original = _richtext_from_footnote(fn_elem) if fn_elem is not None else RichText()
        footnotes.append(Footnote(number=i, original=original, segments=[]))
    return footnotes


# --------------------------------------------------------------------------- #
# Writing: shared run/rPr builders
# --------------------------------------------------------------------------- #


def _make_rpr(base_rpr, italic: bool):
    """A copy of `base_rpr` with w:i/w:iCs set (or removed) to match `italic`."""
    rpr = copy.deepcopy(base_rpr) if base_rpr is not None else None
    if rpr is not None:
        for tag in ("w:i", "w:iCs"):
            el = rpr.find(qn(tag))
            if el is not None:
                rpr.remove(el)
    if italic:
        if rpr is None:
            rpr = etree.Element(qn("w:rPr"))
        _insert_ordered(rpr, etree.Element(qn("w:i")))
        _insert_ordered(rpr, etree.Element(qn("w:iCs")))
    if rpr is not None and len(rpr) == 0:
        rpr = None
    return rpr


def _run_element(text: str, italic: bool, base_rpr):
    r = etree.Element(qn("w:r"))
    rpr = _make_rpr(base_rpr, italic)
    if rpr is not None:
        r.append(rpr)
    t = etree.SubElement(r, qn("w:t"))
    t.set(XML_SPACE, "preserve")
    t.text = text
    return r


def _br_run(base_rpr):
    r = etree.Element(qn("w:r"))
    rpr = _make_rpr(base_rpr, False)
    if rpr is not None:
        r.append(rpr)
    etree.SubElement(r, qn("w:br"))
    return r


def _text_runs(text: str, italic: bool, base_rpr) -> list:
    """`text` -> one or more <w:r> elements, splitting on embedded newlines
    (from multi-paragraph joins or w:br) into real <w:br/> elements."""
    elems = []
    parts = text.split("\n")
    for i, part in enumerate(parts):
        if i > 0:
            elems.append(_br_run(base_rpr))
        if part:
            elems.append(_run_element(part, italic, base_rpr))
    return elems


def _wrap_change(tag: str, author: str, date: str, id_gen, children: list):
    wrapper = etree.Element(qn(tag))
    wrapper.set(qn("w:id"), str(id_gen()))
    wrapper.set(qn("w:author"), author)
    wrapper.set(qn("w:date"), date)
    for c in children:
        wrapper.append(c)
    return wrapper


def _del_run(text: str, italic: bool, base_rpr):
    r = etree.Element(qn("w:r"))
    rpr = _make_rpr(base_rpr, italic)
    if rpr is not None:
        r.append(rpr)
    dt = etree.SubElement(r, qn("w:delText"))
    dt.set(XML_SPACE, "preserve")
    dt.text = text
    return r


def _make_id_gen(*roots):
    max_id = 0
    for root in roots:
        if root is None:
            continue
        for tag in ("w:ins", "w:del"):
            for el in root.iter(qn(tag)):
                v = el.get(qn("w:id"))
                if v is not None:
                    try:
                        max_id = max(max_id, int(v))
                    except ValueError:
                        pass
    counter = [max_id]

    def gen() -> int:
        counter[0] += 1
        return counter[0]

    return gen


# --------------------------------------------------------------------------- #
# Writing: word-level diff for tracked changes
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(r"\S+|\s+")


def _tokenize(rt: RichText) -> list[tuple[str, bool]]:
    tokens: list[tuple[str, bool]] = []
    for run in rt.runs:
        for m in _TOKEN_RE.findall(run.text):
            tokens.append((m, run.italic))
    return tokens


def _diff_tokens(old: list[tuple[str, bool]], new: list[tuple[str, bool]]) -> list[tuple[str, str, bool]]:
    """Word-level diff. Returns ops (kind, text, italic) with kind in
    "equal" | "del" | "ins", in emission order. A token whose text is unchanged
    but whose italic flag changed is emitted as a del of the old run plus an
    ins of the new one (a formatting-only change)."""
    a_text = [t for t, _ in old]
    b_text = [t for t, _ in new]
    sm = difflib.SequenceMatcher(None, a_text, b_text, autojunk=False)
    ops: list[tuple[str, str, bool]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                otext, oital = old[i1 + k]
                _, nital = new[j1 + k]
                if oital == nital:
                    ops.append(("equal", otext, oital))
                else:
                    ops.append(("del", otext, oital))
                    ops.append(("ins", otext, nital))
        else:
            for k in range(i1, i2):
                ops.append(("del", old[k][0], old[k][1]))
            for k in range(j1, j2):
                ops.append(("ins", new[k][0], new[k][1]))
    return ops


def _merge_ops(ops: list[tuple[str, str, bool]]) -> list[tuple[str, str, bool]]:
    merged: list[tuple[str, str, bool]] = []
    for kind, text, italic in ops:
        if merged and merged[-1][0] == kind and merged[-1][2] == italic:
            k, t, i = merged[-1]
            merged[-1] = (k, t + text, i)
        else:
            merged.append((kind, text, italic))
    return merged


def _ops_to_elements(ops: list[tuple[str, str, bool]], base_rpr, author: str, date: str, id_gen) -> list:
    elems = []
    for kind, text, italic in ops:
        if kind == "equal":
            elems.extend(_text_runs(text, italic, base_rpr))
        elif kind == "del":
            elems.append(_wrap_change("w:del", author, date, id_gen, [_del_run(text, italic, base_rpr)]))
        elif kind == "ins":
            elems.append(_wrap_change("w:ins", author, date, id_gen, _text_runs(text, italic, base_rpr)))
    return elems


# --------------------------------------------------------------------------- #
# Writing: rewriting a single footnote
# --------------------------------------------------------------------------- #


def _split_first_paragraph(first_p):
    """Return (marker_run_or_None, space_run_or_None, index-in-children where the
    replaceable old content starts)."""
    children = list(first_p)
    idx = 0
    if children and _local(children[0]) == "pPr":
        idx = 1
    marker = None
    for i in range(idx, len(children)):
        c = children[i]
        if _local(c) == "r" and c.find(qn("w:footnoteRef")) is not None:
            marker = c
            idx = i + 1
            break
    space_run = None
    if idx < len(children):
        c = children[idx]
        if _local(c) == "r" and c.find(qn("w:rPr")) is None and _run_text(c) == " ":
            space_run = c
            idx += 1
    return marker, space_run, idx


def _find_base_rpr(children):
    for c in children:
        for r in c.iter(qn("w:r")):
            if r.find(qn("w:t")) is not None or r.find(qn("w:delText")) is not None:
                rpr = r.find(qn("w:rPr"))
                return copy.deepcopy(rpr) if rpr is not None else None
    return None


def _mark_paragraph_deleted(p, author: str, date: str, id_gen) -> None:
    """Mark an entire paragraph (its runs, and the paragraph mark itself) as a
    tracked deletion, per r 17.13.5.15 (w:pPr/w:rPr/w:del marks the mark)."""
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        ppr = etree.Element(qn("w:pPr"))
        p.insert(0, ppr)
    rpr = ppr.find(qn("w:rPr"))
    if rpr is None:
        rpr = etree.SubElement(ppr, qn("w:rPr"))
    del_mark = etree.Element(qn("w:del"))
    del_mark.set(qn("w:id"), str(id_gen()))
    del_mark.set(qn("w:author"), author)
    del_mark.set(qn("w:date"), date)
    rpr.append(del_mark)

    for r in [c for c in list(p) if _local(c) == "r"]:
        idx = list(p).index(r)
        p.remove(r)
        for t in r.findall(qn("w:t")):
            t.tag = qn("w:delText")
        p.insert(idx, _wrap_change("w:del", author, date, id_gen, [r]))


def _rewrite_footnote(fn_elem, result: FootnoteResult, track_changes: bool, author: str, date: str, id_gen) -> None:
    paragraphs = fn_elem.findall(qn("w:p"))
    if not paragraphs:
        return
    first_p = paragraphs[0]
    children = list(first_p)
    marker, space_run, idx = _split_first_paragraph(first_p)
    old_content_children = children[idx:]
    base_rpr = _find_base_rpr(old_content_children)

    keep = set()
    if children and _local(children[0]) == "pPr":
        keep.add(id(children[0]))
    if marker is not None:
        keep.add(id(marker))
    if space_run is not None:
        keep.add(id(space_run))
    for c in list(first_p):
        if id(c) not in keep:
            first_p.remove(c)

    if track_changes:
        old_tokens = _tokenize(result.original)
        new_tokens = _tokenize(result.formatted)
        ops = _merge_ops(_diff_tokens(old_tokens, new_tokens))
        new_elems = _ops_to_elements(ops, base_rpr, author, date, id_gen)
    else:
        new_elems = []
        for run in result.formatted.runs:
            new_elems.extend(_text_runs(run.text, run.italic, base_rpr))
    for el in new_elems:
        first_p.append(el)

    for p in paragraphs[1:]:
        if track_changes:
            _mark_paragraph_deleted(p, author, date, id_gen)
        else:
            fn_elem.remove(p)


# --------------------------------------------------------------------------- #
# Writing: bibliography
# --------------------------------------------------------------------------- #


def _style_exists(styles_root, style_id: str) -> bool:
    if styles_root is None:
        return False
    for s in styles_root.iter(qn("w:style")):
        if s.get(qn("w:styleId")) == style_id:
            return True
    return False


def _ins_paragraph_mark(ppr, author: str, date: str, id_gen) -> None:
    rpr = etree.SubElement(ppr, qn("w:rPr"))
    ins_mark = etree.Element(qn("w:ins"))
    ins_mark.set(qn("w:id"), str(id_gen()))
    ins_mark.set(qn("w:author"), author)
    ins_mark.set(qn("w:date"), date)
    rpr.append(ins_mark)


def _append_run_elements(p, run_elems: list, track_changes: bool, author: str, date: str, id_gen) -> None:
    if track_changes:
        p.append(_wrap_change("w:ins", author, date, id_gen, run_elems))
    else:
        for r in run_elems:
            p.append(r)


def _heading_paragraph(text: str, style_id: str, use_style: bool, track_changes: bool,
                        author: str, date: str, id_gen):
    p = etree.Element(qn("w:p"))
    ppr = etree.SubElement(p, qn("w:pPr"))
    if use_style:
        se = etree.SubElement(ppr, qn("w:pStyle"))
        se.set(qn("w:val"), style_id)
    if track_changes:
        _ins_paragraph_mark(ppr, author, date, id_gen)

    run_elems = _text_runs(text, False, None)
    if not use_style:
        for r in run_elems:
            rpr = r.find(qn("w:rPr"))
            if rpr is None:
                rpr = etree.Element(qn("w:rPr"))
                r.insert(0, rpr)
            _insert_ordered(rpr, etree.Element(qn("w:b")))
    _append_run_elements(p, run_elems, track_changes, author, date, id_gen)
    return p


def _entry_paragraph(rt: RichText, track_changes: bool, author: str, date: str, id_gen):
    p = etree.Element(qn("w:p"))
    ppr = etree.SubElement(p, qn("w:pPr"))
    if track_changes:
        _ins_paragraph_mark(ppr, author, date, id_gen)
    run_elems = []
    for run in rt.runs:
        run_elems.extend(_text_runs(run.text, run.italic, None))
    _append_run_elements(p, run_elems, track_changes, author, date, id_gen)
    return p


def _page_break_paragraph(track_changes: bool, author: str, date: str, id_gen):
    p = etree.Element(qn("w:p"))
    ppr = etree.SubElement(p, qn("w:pPr"))
    if track_changes:
        _ins_paragraph_mark(ppr, author, date, id_gen)
    else:
        p.remove(ppr)
        ppr = None
    r = etree.Element(qn("w:r"))
    br = etree.SubElement(r, qn("w:br"))
    br.set(qn("w:type"), "page")
    _append_run_elements(p, [r], track_changes, author, date, id_gen)
    return p


def _append_bibliography(doc_root, bibliography: list[BibliographySection], styles_root,
                          track_changes: bool, author: str, date: str, id_gen) -> None:
    body = doc_root.find(qn("w:body"))
    if body is None:
        return
    sect_pr = body.find(qn("w:sectPr"))
    heading1 = _style_exists(styles_root, "Heading1")
    heading2 = _style_exists(styles_root, "Heading2")

    new_paragraphs = [_page_break_paragraph(track_changes, author, date, id_gen),
                       _heading_paragraph("Bibliography", "Heading1", heading1, track_changes, author, date, id_gen)]
    for section in bibliography:
        new_paragraphs.append(
            _heading_paragraph(section.heading, "Heading2", heading2, track_changes, author, date, id_gen)
        )
        for entry in section.entries:
            new_paragraphs.append(_entry_paragraph(entry, track_changes, author, date, id_gen))

    if sect_pr is not None:
        for p in new_paragraphs:
            sect_pr.addprevious(p)
    else:
        for p in new_paragraphs:
            body.append(p)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def write_document(
    src: str | Path,
    dst: str | Path,
    results: list[FootnoteResult],
    *,
    bibliography: list[BibliographySection] | None = None,
    track_changes: bool = True,
    author: str = "AGLC Citation Tool",
) -> None:
    """Copy `src` to `dst`, replacing the text of each changed footnote with
    `result.formatted` (as tracked insertions/deletions when `track_changes`),
    and append a Bibliography at the end of the body if given."""
    src = Path(src)
    dst = Path(dst)
    date = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with zipfile.ZipFile(src) as zin:
        names = zin.namelist()
        infos = {n: zin.getinfo(n) for n in names}
        data = {n: zin.read(n) for n in names}

    doc_root = _parse_xml(data[DOCUMENT_PATH])
    fn_root = _parse_xml(data[FOOTNOTES_PATH]) if FOOTNOTES_PATH in data else None
    styles_root = _parse_xml(data[STYLES_PATH]) if STYLES_PATH in data else None

    id_gen = _make_id_gen(doc_root, fn_root)

    if fn_root is not None:
        order = _footnote_reference_order(doc_root)
        fn_map = _footnote_elements(fn_root)
        for result in results:
            if not result.changed:
                continue
            if not (1 <= result.number <= len(order)):
                continue
            fn_elem = fn_map.get(order[result.number - 1])
            if fn_elem is not None:
                _rewrite_footnote(fn_elem, result, track_changes, author, date, id_gen)
        data[FOOTNOTES_PATH] = _serialize(fn_root)

    if bibliography:
        _append_bibliography(doc_root, bibliography, styles_root, track_changes, author, date, id_gen)
        data[DOCUMENT_PATH] = _serialize(doc_root)

    dst.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(infos[name], data[name])
