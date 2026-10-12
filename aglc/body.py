"""Body-text checks around footnotes: deterministic fixes to `word/document.xml`.

The footnote pass only ever rewrites footnote *content*. These are the AGLC and
presentation rules that live in the body text instead:

- r 1.1.2: a footnote reference mark goes after any punctuation (except a dash),
  so "the Act¹." becomes "the Act.¹".
- Footnote reference marks are never italic, even when they follow italic text
  ("Human Tissue Act 1983 (NSW).*¹¹*" picks up italics when typed after a title).
- Headings are kept with the paragraph that follows them, so a heading is never
  stranded at the foot of a page with its text on the next.

Every fix is written as a Word tracked change when `track_changes` is set
(w:ins/w:del for moved punctuation, w:rPrChange/w:pPrChange for formatting) and
reported back as a `BodyFix`.
"""

from __future__ import annotations

import copy
import re

from lxml import etree

from .docx_io import (
    XML_SPACE,
    _footnote_reference_order,
    _insert_ordered,
    _local,
    _run_text,
    _wrap_change,
    qn,
)
from .models import BodyFix

# r 1.1.2: the punctuation a reference mark must follow, plus any closing quote
# that belongs with it ("harm.’¹"). Dashes are the stated exception.
_TRAILING_PUNCT = re.compile(r"^[.,;:!?]+[’”'\"]*")

# Elements that can sit between a reference mark and the following text without
# being text themselves.
_TRANSPARENT = {"bookmarkStart", "bookmarkEnd", "proofErr", "commentRangeStart",
                "commentRangeEnd", "permStart", "permEnd"}

# Run content that isn't visible text (a run made only of these is skipped over).
_NON_TEXT_RUN_CHILDREN = {"rPr", "lastRenderedPageBreak"}

# Relevant subset of CT_PPrBase's child order (ECMA-376 Part 1, §17.3.1.26):
# keepNext must come straight after pStyle, and pPrChange must be last.
_PPR_HEAD = ("pStyle",)
_PPR_TAIL = ("rPr", "sectPr", "pPrChange")

_HEADING_MAX_WORDS = 15


class _Styles:
    """Just enough style resolution to answer "is this italic / keep-with-next /
    a heading" through the basedOn chain."""

    def __init__(self, styles_root) -> None:
        self._by_id: dict[str, etree._Element] = {}
        self.default_paragraph: str | None = None
        if styles_root is None:
            return
        for s in styles_root.iter(qn("w:style")):
            sid = s.get(qn("w:styleId"))
            if sid is None:
                continue
            self._by_id[sid] = s
            if s.get(qn("w:type")) == "paragraph" and s.get(qn("w:default")) in ("1", "true", "on"):
                self.default_paragraph = sid

    def _chain(self, style_id: str | None):
        seen: set[str] = set()
        while style_id and style_id not in seen and style_id in self._by_id:
            seen.add(style_id)
            style = self._by_id[style_id]
            yield style
            based = style.find(qn("w:basedOn"))
            style_id = based.get(qn("w:val")) if based is not None else None

    def flag(self, style_id: str | None, container: str, tag: str) -> bool | None:
        """The first explicit value of `container/tag` (eg "w:pPr", "w:keepNext")
        up the basedOn chain, or None if no style in the chain sets it."""
        for style in self._chain(style_id):
            props = style.find(qn(container))
            if props is not None:
                value = _on_off(props.find(qn(tag)))
                if value is not None:
                    return value
        return None

    def is_heading(self, style_id: str | None) -> bool:
        for style in self._chain(style_id):
            name = style.find(qn("w:name"))
            if name is not None and (name.get(qn("w:val")) or "").lower().startswith(("heading", "title", "subtitle")):
                return True
            ppr = style.find(qn("w:pPr"))
            if ppr is not None and _outline_level(ppr) is not None:
                return True
        return False


def _on_off(el) -> bool | None:
    """An ST_OnOff element's value: absent -> None, <w:x/> -> True, w:val="0" -> False."""
    if el is None:
        return None
    val = el.get(qn("w:val"))
    return True if val is None else val.strip().lower() not in ("0", "false", "off")


def _outline_level(ppr) -> int | None:
    el = ppr.find(qn("w:outlineLvl"))
    if el is None:
        return None
    try:
        level = int(el.get(qn("w:val"), "9"))
    except ValueError:
        return None
    return level if level < 9 else None  # 9 is "body text"


def _style_val(props, tag: str) -> str | None:
    if props is None:
        return None
    el = props.find(qn(tag))
    return el.get(qn("w:val")) if el is not None else None


def _inside(el, tag: str) -> bool:
    return any(_local(a) == tag for a in el.iterancestors())


def _paragraph_of(el):
    for a in el.iterancestors():
        if _local(a) == "p":
            return a
    return None


# --------------------------------------------------------------------------- #
# Tracked formatting changes
# --------------------------------------------------------------------------- #


def _change_mark(tag: str, author: str, date: str, id_gen):
    el = etree.Element(qn(tag))
    el.set(qn("w:id"), str(id_gen()))
    el.set(qn("w:author"), author)
    el.set(qn("w:date"), date)
    return el


def _record_rpr_change(rpr, author: str, date: str, id_gen) -> None:
    """Snapshot `rpr` as it is now into a w:rPrChange (call before modifying)."""
    if rpr.find(qn("w:rPrChange")) is not None:
        return  # already carries an earlier tracked formatting change; keep its baseline
    old = copy.deepcopy(rpr)
    change = _change_mark("w:rPrChange", author, date, id_gen)
    change.append(old)
    old.tag = qn("w:rPr")
    rpr.append(change)


def _record_ppr_change(ppr, author: str, date: str, id_gen) -> None:
    """Snapshot `ppr` (minus rPr/sectPr, which pPrChange can't hold) into a w:pPrChange."""
    if ppr.find(qn("w:pPrChange")) is not None:
        return
    old = etree.Element(qn("w:pPr"))
    for child in ppr:
        if _local(child) not in _PPR_TAIL:
            old.append(copy.deepcopy(child))
    change = _change_mark("w:pPrChange", author, date, id_gen)
    change.append(old)
    ppr.append(change)


def _ensure_ppr(p):
    ppr = p.find(qn("w:pPr"))
    if ppr is None:
        ppr = etree.Element(qn("w:pPr"))
        p.insert(0, ppr)
    return ppr


# --------------------------------------------------------------------------- #
# Footnote reference marks
# --------------------------------------------------------------------------- #


def _reference_is_italic(run, styles: _Styles) -> bool:
    rpr = run.find(qn("w:rPr"))
    for tag in ("w:i", "w:iCs"):
        value = _on_off(rpr.find(qn(tag))) if rpr is not None else None
        if value is not None:
            return value
    char_style = styles.flag(_style_val(rpr, "w:rStyle"), "w:rPr", "w:i")
    if char_style is not None:
        return char_style
    p = _paragraph_of(run)
    p_style = _style_val(p.find(qn("w:pPr")), "w:pStyle") if p is not None else None
    return bool(styles.flag(p_style or styles.default_paragraph, "w:rPr", "w:i"))


def _unitalicise(run, styles: _Styles, track_changes: bool, author: str, date: str, id_gen) -> bool:
    if not _reference_is_italic(run, styles):
        return False
    rpr = run.find(qn("w:rPr"))
    if rpr is None:
        rpr = etree.Element(qn("w:rPr"))
        run.insert(0, rpr)
    if track_changes:
        _record_rpr_change(rpr, author, date, id_gen)
    for tag in ("w:i", "w:iCs"):
        el = rpr.find(qn(tag))
        if el is not None:
            rpr.remove(el)
    if _reference_is_italic(run, styles):
        # Italic comes from a style, so it has to be switched off explicitly.
        for tag in ("w:i", "w:iCs"):
            off = etree.Element(qn(tag))
            off.set(qn("w:val"), "0")
            _insert_ordered(rpr, off)
    return True


def _is_reference_run(el) -> bool:
    return _local(el) == "r" and el.find(qn("w:footnoteReference")) is not None


def _is_empty_run(el) -> bool:
    return _local(el) == "r" and all(_local(c) in _NON_TEXT_RUN_CHILDREN for c in el)


def _adjacent_text_run(run, forward: bool):
    """The nearest sibling run carrying text, skipping bookmarks and empty runs;
    None if anything else (another reference mark, a hyperlink, a tracked change)
    comes first."""
    sib = run.getnext() if forward else run.getprevious()
    while sib is not None:
        tag = _local(sib)
        if tag in _TRANSPARENT or _is_empty_run(sib):
            sib = sib.getnext() if forward else sib.getprevious()
            continue
        if tag == "r" and not _is_reference_run(sib):
            return sib
        return None
    return None


def _leading_text_element(run):
    """The run's first content child if it is a w:t (eg not a tab or break)."""
    for child in run:
        tag = _local(child)
        if tag in _NON_TEXT_RUN_CHILDREN:
            continue
        return child if tag == "t" else None
    return None


def _text_run_like(template, text: str, deleted: bool = False):
    r = etree.Element(qn("w:r"))
    rpr = template.find(qn("w:rPr"))
    if rpr is not None:
        rpr = copy.deepcopy(rpr)
        change = rpr.find(qn("w:rPrChange"))
        if change is not None:
            rpr.remove(change)
        r.append(rpr)
    t = etree.SubElement(r, qn("w:delText" if deleted else "w:t"))
    t.set(XML_SPACE, "preserve")
    t.text = text
    return r


def _move_punctuation_before(run, track_changes: bool, author: str, date: str, id_gen) -> str | None:
    """r 1.1.2: "Act¹." -> "Act.¹". Returns the punctuation moved, or None."""
    after = _adjacent_text_run(run, forward=True)
    if after is None:
        return None
    t = _leading_text_element(after)
    if t is None or not t.text:
        return None
    m = _TRAILING_PUNCT.match(t.text)
    if not m:
        return None
    before = _adjacent_text_run(run, forward=False)
    if before is None or not _run_text(before) or _run_text(before)[-1].isspace():
        return None  # nothing (or only a space) to attach the punctuation to: leave it
    punct = m.group(0)

    if track_changes:
        run.addprevious(_wrap_change("w:ins", author, date, id_gen, [_text_run_like(after, punct)]))
        after.addprevious(_wrap_change("w:del", author, date, id_gen,
                                       [_text_run_like(after, punct, deleted=True)]))
    else:
        run.addprevious(_text_run_like(after, punct))
    t.text = t.text[len(punct):]
    if not t.text and len([c for c in after if _local(c) not in _NON_TEXT_RUN_CHILDREN]) == 1:
        after.getparent().remove(after)
    return punct


# --------------------------------------------------------------------------- #
# Headings: keep with next
# --------------------------------------------------------------------------- #


def _paragraph_text(p) -> str:
    return "".join(_run_text(r) for r in p.iter(qn("w:r")) if not _inside(r, "del"))


def _is_blank(p) -> bool:
    if _paragraph_text(p).strip():
        return False
    return not any(_local(el) in ("drawing", "pict", "object", "footnoteReference") for el in p.iter())


def _looks_like_heading(p, styles: _Styles) -> bool:
    ppr = p.find(qn("w:pPr"))
    if ppr is not None and _outline_level(ppr) is not None:
        return True
    if styles.is_heading(_style_val(ppr, "w:pStyle")):
        return True
    # A heading made with direct formatting: a short line, every run bold or
    # italic, no closing punctuation and no footnotes.
    text = _paragraph_text(p).strip()
    if not text or len(text.split()) > _HEADING_MAX_WORDS or text[-1] in ".,;:":
        return False
    if any(True for _ in p.iter(qn("w:footnoteReference"))):
        return False
    runs = [r for r in p.iter(qn("w:r")) if _run_text(r).strip() and not _inside(r, "del")]
    for r in runs:
        rpr = r.find(qn("w:rPr"))
        bold = _on_off(rpr.find(qn("w:b"))) if rpr is not None else None
        italic = _on_off(rpr.find(qn("w:i"))) if rpr is not None else None
        if not (bold or italic):
            return False
    return bool(runs)


def _keeps_with_next(p, styles: _Styles) -> bool:
    ppr = p.find(qn("w:pPr"))
    direct = _on_off(ppr.find(qn("w:keepNext"))) if ppr is not None else None
    if direct is not None:
        return direct
    return bool(styles.flag(_style_val(ppr, "w:pStyle") or styles.default_paragraph, "w:pPr", "w:keepNext"))


def _set_keep_next(p, track_changes: bool, author: str, date: str, id_gen) -> None:
    ppr = _ensure_ppr(p)
    if track_changes:
        _record_ppr_change(ppr, author, date, id_gen)
    existing = ppr.find(qn("w:keepNext"))
    if existing is not None:
        ppr.remove(existing)
    keep = etree.Element(qn("w:keepNext"))
    style = ppr.find(qn("w:pStyle"))
    if style is not None:
        style.addnext(keep)
    else:
        ppr.insert(0, keep)


def _keep_headings_with_text(doc_root, styles: _Styles, track_changes: bool, author: str, date: str,
                             id_gen) -> list[BodyFix]:
    body = doc_root.find(qn("w:body"))
    if body is None:
        return []
    paragraphs = [p for p in body.iter(qn("w:p")) if not _inside(p, "tbl")]
    fixes: list[BodyFix] = []
    for i, p in enumerate(paragraphs):
        if _is_blank(p) or not _looks_like_heading(p, styles):
            continue
        # The heading, plus any blank spacing paragraphs between it and its text:
        # keep-with-next on the heading alone only binds it to the blank line.
        chain = [p]
        j = i + 1
        while j < len(paragraphs) and _is_blank(paragraphs[j]):
            chain.append(paragraphs[j])
            j += 1
        if j >= len(paragraphs):
            continue  # nothing after it to keep it with
        loose = [q for q in chain if not _keeps_with_next(q, styles)]
        if not loose:
            continue
        for q in loose:
            _set_keep_next(q, track_changes, author, date, id_gen)
        fixes.append(BodyFix(message=f"Heading ‘{_paragraph_text(p).strip()}’ set to keep with the "
                                     "following text, so it can't be left alone at the foot of a page"))
    return fixes


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


def fix_body(doc_root, styles_root, *, track_changes: bool, author: str, date: str, id_gen) -> list[BodyFix]:
    """Apply the body-text fixes in place and describe each one."""
    styles = _Styles(styles_root)
    numbers = {fid: n for n, fid in enumerate(_footnote_reference_order(doc_root), start=1)}
    fixes: list[BodyFix] = []

    for ref in list(doc_root.iter(qn("w:footnoteReference"))):
        run = ref.getparent()
        if _local(run) != "r" or _inside(run, "del"):
            continue
        number = numbers.get(ref.get(qn("w:id")))
        if _unitalicise(run, styles, track_changes, author, date, id_gen):
            fixes.append(BodyFix(footnote=number,
                                 message="footnote number in the text was italic; set upright"))
        moved = _move_punctuation_before(run, track_changes, author, date, id_gen)
        if moved:
            fixes.append(BodyFix(footnote=number,
                                 message=f"footnote number moved after the ‘{moved}’ "
                                         "(AGLC4 r 1.1.2: footnote numbers go after punctuation)"))

    fixes += _keep_headings_with_text(doc_root, styles, track_changes, author, date, id_gen)
    return fixes
