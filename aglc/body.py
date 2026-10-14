"""Body-text checks around footnotes: deterministic fixes to `word/document.xml`.

The footnote pass only ever rewrites footnote *content*. These are the AGLC and
presentation rules that live in the body text instead:

- r 1.1.2: a footnote reference mark goes after any punctuation (except a dash),
  so "the Act¹." becomes "the Act.¹".
- Footnote reference marks are never italic, even when they follow italic text
  ("Human Tissue Act 1983 (NSW).*¹¹*" picks up italics when typed after a title).
- No space before a footnote reference mark ("Adoption Act ⁹" -> "Adoption Act⁹").
- Citations in the body text are italicised like citations in footnotes: the
  case name (including its 'v') and the Act title and year only, never the
  jurisdiction, year, report series or medium neutral citation (AGLC4 chs 2-3).
- More than one section is 'ss', with an en dash for a range ("s 57-64" ->
  "ss 57–64", r 3.1.4).
- Headings are kept with the paragraph that follows them, so a heading is never
  stranded at the foot of a page with its text on the next.

Every fix is written as a Word tracked change when `track_changes` is set
(w:ins/w:del for text, w:rPrChange/w:pPrChange for formatting) and reported back
as a `BodyFix`.

Some problems can only be spotted, not safely fixed, so they are reported as
checks (`BodyFix(applied=False)`) and the text is left alone: a footnote number
followed by a new sentence with no full stop before it, and an italicised
possessive ("*Maynard’s* affidavit"), which usually means the person rather
than the case.
"""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path

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
# pPrChange must be last, after rPr and sectPr.
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


def _is_italic(run, styles: _Styles) -> bool:
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


def _set_italic(run, styles: _Styles, italic: bool, track_changes: bool, author: str, date: str,
                id_gen) -> bool:
    """Make `run` italic or upright; False if it already was."""
    if _is_italic(run, styles) == italic:
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
    if _is_italic(run, styles) != italic:
        # The inherited formatting is wrong too, so set it explicitly.
        for tag in ("w:i", "w:iCs"):
            el = etree.Element(qn(tag))
            if not italic:
                el.set(qn("w:val"), "0")
            _insert_ordered(rpr, el)
    return True


def _is_reference_run(el) -> bool:
    return _local(el) == "r" and el.find(qn("w:footnoteReference")) is not None


def _is_empty_run(el) -> bool:
    return _local(el) == "r" and all(_local(c) in _NON_TEXT_RUN_CHILDREN for c in el)


def _adjacent_text_run(run, forward: bool):
    """The nearest sibling run carrying text, skipping bookmarks, empty runs and
    deleted text; None if anything else (another reference mark, a hyperlink)
    comes first."""
    sib = run.getnext() if forward else run.getprevious()
    while sib is not None:
        tag = _local(sib)
        if tag in _TRANSPARENT or tag == "del" or _is_empty_run(sib):
            sib = sib.getnext() if forward else sib.getprevious()
            continue
        if tag == "r" and not _is_reference_run(sib):
            return sib
        if tag == "ins" and not forward:
            # Text inserted by a fix made just before (eg a removed space): it is
            # only read, never edited, so looking inside is safe.
            inserted = sib.findall(qn("w:r"))
            return inserted[-1] if inserted else None
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
# Citations and punctuation in the running text
# --------------------------------------------------------------------------- #

# A paragraph is read as one string so patterns can span runs. Content that can't be
# edited as plain text stands in as a single placeholder character, so no pattern
# matches across it: _FN for a footnote reference mark, _OPAQUE for anything else
# (tabs, fields, hyperlinks, earlier tracked insertions).
_FN = ""
_OPAQUE = "￼"

_JURISDICTIONS = "|".join(
    re.escape(code) for code in json.loads((Path(__file__).parent / "data" / "jurisdictions.json").read_text())
)
# 'Adoption Act 2000 (NSW)': only the title and year are italic (r 3.1.2).
_ACT_JURISDICTION = re.compile(rf"(?<=\d{{4}} )\((?:{_JURISDICTIONS})\)")
# '[2020] NSWCA 83', '[1991] 1 WLR 844', '(1992) 175 CLR 1': never italic (rr 2.2, 2.3).
_CASE_DETAILS = re.compile(r"[\[(]\d{4}[\])] (?:\d+ )?[A-Z][A-Za-z]*(?: [A-Z][A-Za-z]*)* \d+\b")
# 'Hackett v Secretary': the 'v' is part of the italicised case name (r 2.1.1).
_CASE_V = re.compile(r"(?<=\S) v (?=\S)")
# 's 57-64' -> 'ss 57–64' (r 3.1.4); 'ss 57-64' -> 'ss 57–64'. A hyphen followed by
# '(' is part of a single provision number instead (eg ITAA 1997 's 20-110(1)').
_SECTION_RANGE = re.compile(r"\b(ss?) (\d+[A-Z]*) ?[-–] ?(\d+[A-Z]*)\b(?![-(])")
_SPACE_BEFORE_FN = re.compile(rf"(?<=[^\s{_FN}{_OPAQUE}]) +(?={_FN})")
_NEW_SENTENCE = re.compile(rf"{_FN}(?= ([A-Z][a-z]*))")
_POSSESSIVE = re.compile(r"\b([A-Z][A-Za-z-]+)[’']s\b")


@dataclass
class _Piece:
    run: object | None  # a run holding exactly one w:t, or None for a placeholder
    text: str
    footnote: int | None = None


def _pieces(p, numbers: dict[str, int]) -> list[_Piece]:
    pieces: list[_Piece] = []
    for child in p:
        tag = _local(child)
        if tag in _TRANSPARENT or tag in ("pPr", "del") or _is_empty_run(child):
            continue
        if _is_reference_run(child):
            fid = child.find(qn("w:footnoteReference")).get(qn("w:id"))
            pieces.append(_Piece(None, _FN, numbers.get(fid)))
            continue
        if tag == "r":
            content = [c for c in child if _local(c) not in _NON_TEXT_RUN_CHILDREN]
            if len(content) == 1 and _local(content[0]) == "t":
                pieces.append(_Piece(child, content[0].text or ""))
                continue
        pieces.append(_Piece(None, _OPAQUE))
    return pieces


@dataclass
class _Edit:
    start: int
    end: int
    message: str
    replacement: str | None = None  # new text, or None for a formatting change
    italic: bool = False  # the formatting to apply when replacement is None
    footnote: int | None = None


class _Editor:
    """Applies `_Edit`s to a paragraph's runs, as tracked changes if asked."""

    def __init__(self, styles: _Styles, track_changes: bool, author: str, date: str, id_gen) -> None:
        self.styles, self.track = styles, track_changes
        self.author, self.date, self.id_gen = author, date, id_gen

    def apply(self, pieces: list[_Piece], edits: list[_Edit]) -> list[_Edit]:
        """Apply non-overlapping edits right to left (so splitting a run never moves
        the text an earlier edit points at). Returns the edits that changed anything."""
        done: list[_Edit] = []
        limit = None
        for e in sorted(edits, key=lambda e: e.start, reverse=True):
            if limit is not None and e.end > limit:
                continue
            runs = self._isolate(pieces, e.start, e.end)
            if runs is None:
                continue
            if e.replacement is not None:
                self._replace(runs, e.replacement)
                changed = True
            else:
                changed = False
                for r in runs:
                    changed |= _set_italic(r, self.styles, e.italic, self.track, self.author,
                                           self.date, self.id_gen)
            if changed:
                done.append(e)
                limit = e.start
        return done[::-1]

    def _isolate(self, pieces: list[_Piece], start: int, end: int):
        """The runs covering exactly [start, end), splitting runs at the edges; None if
        the span crosses a placeholder."""
        spans = []
        pos = 0
        for piece in pieces:
            a, b = pos, pos + len(piece.text)
            pos = b
            if b <= start or a >= end:
                continue
            if piece.run is None:
                return None
            spans.append((piece.run, max(start, a) - a, min(end, b) - a))
        runs = []
        for run, lo, hi in spans:
            if hi < len(_run_text(run)):
                self._split(run, hi)
            runs.append(self._split(run, lo) if lo > 0 else run)
        return runs

    def _split(self, run, k: int):
        """Split a one-w:t run at offset k: `run` keeps the text before k, and the
        returned new run (inserted just after it) holds the rest."""
        new = copy.deepcopy(run)
        for change in new.iter(qn("w:rPrChange")):
            change.set(qn("w:id"), str(self.id_gen()))
        t, new_t = run.find(qn("w:t")), new.find(qn("w:t"))
        t.text, new_t.text = t.text[:k], t.text[k:]
        t.set(XML_SPACE, "preserve")
        new_t.set(XML_SPACE, "preserve")
        run.addnext(new)
        return new

    def _replace(self, runs: list, text: str) -> None:
        first = runs[0]
        if text:
            new = _text_run_like(first, text)
            first.addprevious(_wrap_change("w:ins", self.author, self.date, self.id_gen, [new])
                              if self.track else new)
        for r in runs:
            if self.track:
                r.find(qn("w:t")).tag = qn("w:delText")
                wrapper = _wrap_change("w:del", self.author, self.date, self.id_gen, [])
                r.addprevious(wrapper)
                wrapper.append(r)
            else:
                r.getparent().remove(r)


def _italic_flags(pieces: list[_Piece], styles: _Styles) -> list[bool]:
    flags: list[bool] = []
    for piece in pieces:
        italic = piece.run is not None and _is_italic(piece.run, styles)
        flags.extend([italic] * len(piece.text))
    return flags


def _footnote_at(pieces: list[_Piece], index: int) -> int | None:
    pos = 0
    for piece in pieces:
        if pos == index:
            return piece.footnote
        pos += len(piece.text)
    return None


def _fix_paragraph_text(p, numbers: dict[str, int], styles: _Styles, edit: _Editor) -> list[BodyFix]:
    pieces = _pieces(p, numbers)
    text = "".join(piece.text for piece in pieces)
    if not text.strip(_FN + _OPAQUE + " "):
        return []
    italic = _italic_flags(pieces, styles)
    edits: list[_Edit] = []

    for m in _SPACE_BEFORE_FN.finditer(text):
        edits.append(_Edit(m.start(), m.end(), "space before the footnote number removed",
                           replacement="", footnote=_footnote_at(pieces, m.end())))
    for m in _ACT_JURISDICTION.finditer(text):
        if any(italic[m.start():m.end()]):
            edits.append(_Edit(m.start(), m.end(),
                               f"‘{m.group(0)}’ after an Act’s title set upright (AGLC4 r 3.1.2: "
                               "the jurisdiction is not italicised)"))
    for m in _CASE_DETAILS.finditer(text):
        if any(italic[m.start():m.end()]):
            edits.append(_Edit(m.start(), m.end(),
                               f"‘{m.group(0)}’ set upright (AGLC4 ch 2: only the case name is "
                               "italicised, not the year, report or medium neutral citation)"))
    for m in _CASE_V.finditer(text):
        if italic[m.start() - 1] and italic[m.end()] and not italic[m.start() + 1]:
            left = text[:m.start()].rsplit(" ", 1)[-1]
            right = text[m.end():].split(" ", 1)[0]
            edits.append(_Edit(m.start(), m.end(),
                               f"‘v’ in ‘{left} v {right}’ italicised (AGLC4 r 2.1.1: it is part of "
                               "the case name)", italic=True))
    for m in _SECTION_RANGE.finditer(text):
        label, a, b = m.groups()
        if a.isdigit() and b.isdigit() and int(b) <= int(a):
            continue  # not an ascending range, so probably one provision's number
        fixed = f"ss {a}–{b}"
        if fixed != m.group(0):
            edits.append(_Edit(m.start(), m.end(),
                               f"‘{m.group(0)}’ changed to ‘{fixed}’ (AGLC4 r 3.1.4: ‘ss’ for more "
                               "than one section, and an en dash for a range)", replacement=fixed))

    fixes = [BodyFix(footnote=e.footnote, message=e.message) for e in edit.apply(pieces, edits)]

    for m in _NEW_SENTENCE.finditer(text):
        before = text[:m.start()].rstrip("’”'\")]")
        if before and before[-1] not in ".!?" + _FN + _OPAQUE:
            fixes.append(BodyFix(
                footnote=_footnote_at(pieces, m.start()), applied=False,
                message=f"a new sentence (‘{m.group(1)} …’) starts after this footnote number, "
                        "but the sentence before it has no full stop"))
    return fixes


def _possessive_checks(paragraphs: list, styles: _Styles) -> list[BodyFix]:
    """'*Maynard’s* sworn affidavit': an italic name with a possessive almost always
    means the person, not the case. Only the reader can tell, so this is a check."""
    counts: dict[str, int] = {}
    for p in paragraphs:
        pieces = _pieces(p, {})
        text = "".join(piece.text for piece in pieces)
        italic = _italic_flags(pieces, styles)
        for m in _POSSESSIVE.finditer(text):
            if all(italic[m.start(1):m.end(1)]) and not m.group(1).endswith("Act"):
                counts[m.group(1)] = counts.get(m.group(1), 0) + 1
    return [
        BodyFix(applied=False, message=(
            f"‘{name}’s’ is italicised{f' ({n} times)' if n > 1 else ''}. Italicise a case name only "
            f"when you mean the case; when you mean the person (‘{name}’s affidavit’), use roman type"))
        for name, n in counts.items()
    ]


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
    """Apply the body-text fixes in place and describe each one (plus the checks
    that were only reported)."""
    styles = _Styles(styles_root)
    numbers = {fid: n for n, fid in enumerate(_footnote_reference_order(doc_root), start=1)}
    edit = _Editor(styles, track_changes, author, date, id_gen)
    fixes: list[BodyFix] = []

    body = doc_root.find(qn("w:body"))
    paragraphs = list(body.iter(qn("w:p"))) if body is not None else []
    for p in paragraphs:
        fixes += _fix_paragraph_text(p, numbers, styles, edit)
    fixes += _possessive_checks(paragraphs, styles)

    for ref in list(doc_root.iter(qn("w:footnoteReference"))):
        run = ref.getparent()
        if _local(run) != "r" or _inside(run, "del"):
            continue
        number = numbers.get(ref.get(qn("w:id")))
        if _set_italic(run, styles, False, track_changes, author, date, id_gen):
            fixes.append(BodyFix(footnote=number,
                                 message="footnote number in the text was italic; set upright"))
        moved = _move_punctuation_before(run, track_changes, author, date, id_gen)
        if moved:
            fixes.append(BodyFix(footnote=number,
                                 message=f"footnote number moved after the ‘{moved}’ "
                                         "(AGLC4 r 1.1.2: footnote numbers go after punctuation)"))

    fixes += _keep_headings_with_text(doc_root, styles, track_changes, author, date, id_gen)
    return fixes
