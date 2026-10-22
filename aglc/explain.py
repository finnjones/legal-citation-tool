"""Plain-words explanations of what changed in a footnote, and which AGLC4 rule says so.

The results page shows a word diff, but many real fixes are tiny (a year moved inside
the italics, a comma, an en dash) and read as "nothing changed". `explain` compares the
student's footnote with the formatted one and names each kind of change once, eg
"The year is part of an Act's title, so it's italic too (r 3.1.2)".

Detection is deterministic and conservative: each detector looks for one recognisable
edit. Whatever no detector accounts for is summed up in one closing line naming the
AGLC4 chapter for the footnote's sources, so an amended footnote always says something
and never claims more than is known. Rule numbers are checked against the *Guide*.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from . import validate
from .models import Change, RichText

# One token per word, number, punctuation mark or run of whitespace (as in web/index.html)
_TOKEN = re.compile(r"\s+|[^\W_]+|[^\s\w]|_")

# AGLC4 chapter for each formatter's source_type: (noun phrase, rule)
_CHAPTERS = {
    "case": ("a case", "ch 2"),
    "us_case": ("a United States case", "r 25.1"),
    "legislation": ("legislation", "ch 3"),
    "journal_article": ("a journal article", "ch 5"),
    "book": ("a book", "ch 6"),
    "book_chapter": ("a book chapter", "r 6.6.1"),
    "report": ("a report", "r 7.1"),
    "newspaper": ("a newspaper article", "r 7.11"),
    "website": ("a web page", "r 7.15"),
    "treaty": ("a treaty", "ch 8"),
    "research_paper": ("a research paper", "r 7.2"),
    "parliamentary_debates": ("parliamentary debates", "r 7.5.1"),
    "submission": ("a submission to an inquiry", "r 7.5.2"),
    "committee_evidence": ("evidence to a parliamentary committee", "r 7.5.3"),
    "convention_debates": ("the Constitutional Convention Debates", "r 7.5.4"),
    "explanatory_memorandum": ("an explanatory memorandum", "r 3.7"),
}

# Reference-manager type labels AGLC4 never prints, eg Zotero's '(Journal Article, 2010)'
_TYPE_LABELS = {
    "journal article": ("journal articles", "ch 5"),
    "book section": ("book chapters", "r 6.6.1"),
    "book chapter": ("book chapters", "r 6.6.1"),
    "newspaper article": ("newspaper articles", "r 7.11"),
    "magazine article": ("magazine articles", "r 7.11.3"),
    "case": ("cases", "ch 2"),
    "statute": ("Acts", "ch 3"),
    "legislation": ("Acts", "ch 3"),
}
# The kinds of source AGLC4 never labels (validate.UNLABELLED_TYPES), for any other label
_UNLABELLED = {
    "journal_article": ("journal articles", "ch 5"),
    "book": ("books", "ch 6"),
    "book_chapter": ("book chapters", "r 6.6.1"),
    "newspaper": ("newspaper articles", "r 7.11"),
    "case": ("cases", "ch 2"),
    "us_case": ("United States cases", "r 25.1"),
    "legislation": ("Acts", "ch 3"),
    "treaty": ("treaties", "ch 8"),
}
_TYPE_LABEL = re.compile(
    r"\(\s*(" + "|".join(re.escape(k) for k in _TYPE_LABELS) + r")\b\s*,?\s*", re.I)

_SIGNALS = re.compile(r"^(see( also| generally)?|but see|cf|compare|contra|eg|see, eg)$", re.I)
_YEAR = re.compile(r"^\d{4}$")
_JURISDICTION = re.compile(r"^\(\s*[A-Z][A-Za-z ]{0,20}\)$")
_PIN_MARKERS = {"p": "page", "pp": "page", "pg": "page", "at": "at", "para": "para", "paras": "para"}
_SECTION_WORDS = re.compile(r"\b(sections?|secs?\.?|ss?\.|s\.)\s*(?=\d)", re.I)
_DOTTED = re.compile(r"\b(?:[A-Z][a-z]?\.\s?){2,}")
# A span: page '648-649', paragraph '[12]-[15]', with a hyphen, dash or 'to'
_SPAN = re.compile(r"(\[?)(\d+)(\]?)\s*(-|–|—|‑|\bto\b)\s*(\[?)(\d+)(\]?)")


@dataclass(frozen=True)
class _Token:
    text: str
    italic: bool
    start: int  # character offsets in the footnote's plain text
    end: int

    @property
    def space(self) -> bool:
        return self.text.isspace()


def _tokens(rt: RichText) -> list[_Token]:
    out, pos = [], 0
    for run in rt.runs:
        for m in _TOKEN.finditer(run.text):
            out.append(_Token(m.group(), run.italic, pos + m.start(), pos + m.end()))
        pos += len(run.text)
    return out


def _key(t: _Token) -> str:
    return " " if t.space else t.text


def _overlaps(span: tuple[int, int], spans: list[tuple[int, int]]) -> bool:
    a, b = span
    return any(a < d and c < b for c, d in spans) if a < b else any(c <= a <= d for c, d in spans)


@dataclass
class _Edit:
    """One run of differing tokens (the text only; italics are compared separately)."""
    deleted: list[_Token]
    inserted: list[_Token]
    before_span: tuple[int, int]
    after_span: tuple[int, int]
    next_after: _Token | None  # first non-space token after the edit, in the result
    prev_after: _Token | None
    next_before: _Token | None

    @property
    def substantive(self) -> bool:
        return _visible(self.deleted) != _visible(self.inserted)


def _visible(tokens: list[_Token]) -> str:
    return "".join(t.text for t in tokens if not t.space)


def _span(tokens: list[_Token], lo: int, hi: int) -> tuple[int, int]:
    """Character span of tokens[lo:hi]; an empty slice is the point where it would be."""
    if hi > lo:
        return tokens[lo].start, tokens[hi - 1].end
    at = tokens[lo].start if lo < len(tokens) else tokens[-1].end if tokens else 0
    return at, at


@dataclass
class _Context:
    before: str
    after: str
    a: list[_Token]
    b: list[_Token]
    types: set[str]
    edits: list[_Edit] = field(default_factory=list)
    italic_groups: list[tuple[bool, int, int]] = field(default_factory=list)  # (now italic, j0, j1)
    changes: list[Change] = field(default_factory=list)
    covered_before: list[tuple[int, int]] = field(default_factory=list)
    covered_after: list[tuple[int, int]] = field(default_factory=list)
    deletions_covered: bool = False

    def add(self, kind: str, text: str, rule: str | None = None, *, before=(), after=()) -> None:
        if not any(c.kind == kind and c.text == text for c in self.changes):
            self.changes.append(Change(kind=kind, text=text, rule=rule))
        self.covered_before += list(before)
        self.covered_after += list(after)


def explain(original: RichText, formatted: RichText, source_types: Sequence[str] = ()) -> list[Change]:
    """What changed between `original` and `formatted`, one entry per kind of change.

    `source_types` are the formatters' `source_type`s for the footnote's citations; they
    choose the wording and rule number (eg a case's pinpoint comma is r 2.2.5)."""
    if original.to_markup() == formatted.to_markup():
        return []
    ctx = _Context(original.text, formatted.text, _tokens(original), _tokens(formatted), set(source_types))
    _diff(ctx)
    for detect in _DETECTORS:
        detect(ctx)
    _remainder(ctx)
    return ctx.changes


def _diff(ctx: _Context) -> None:
    a, b = ctx.a, ctx.b
    matcher = SequenceMatcher(None, [_key(t) for t in a], [_key(t) for t in b], autojunk=False)
    changed_italics: list[tuple[int, bool]] = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if op == "equal":
            changed_italics += [(j1 + k, b[j1 + k].italic) for k in range(i2 - i1)
                                if not b[j1 + k].space and a[i1 + k].italic != b[j1 + k].italic]
            continue
        nxt = next((t for t in b[j2:] if not t.space), None)
        prv = next((t for t in reversed(b[:j1]) if not t.space), None)
        nxt_a = next((t for t in a[i2:] if not t.space), None)
        ctx.edits.append(_Edit(a[i1:i2], b[j1:j2], _span(a, i1, i2), _span(b, j1, j2), nxt, prv, nxt_a))
    # Group changed tokens that are adjacent but for whitespace, by direction
    for j, italic in changed_italics:
        if ctx.italic_groups:
            now, j0, j1 = ctx.italic_groups[-1]
            if now == italic and all(t.space for t in b[j1 + 1:j]):
                ctx.italic_groups[-1] = (now, j0, j)
                continue
        ctx.italic_groups.append((italic, j, j))


# --------------------------------------------------------------------------- #
# detectors, in the order their lines are shown
# --------------------------------------------------------------------------- #


def _ibid(ctx: _Context) -> None:
    m = re.search(r"\b[Ii]bid\b", ctx.after)
    if not m:
        return
    if not re.search(r"\bibid\b", ctx.before, re.I):
        ctx.add("ibid", "Same source as the footnote before, so ‘Ibid’ replaces the citation", "r 1.4.3",
                after=[m.span()])
        ctx.deletions_covered = True
    elif m.group() == "Ibid" and re.match(r"\s*ibid\b", ctx.before) and m.start() == 0:
        ctx.add("ibid", "‘Ibid’ takes a capital at the start of a footnote", "r 1.4.3", after=[m.span()])


def _n_reference(ctx: _Context) -> None:
    new = [m for m in re.finditer(r"\(n (\d+)\)", ctx.after) if m.group() not in ctx.before]
    if not new:
        return
    old = list(re.finditer(r"\b(above|supra|op\.?\s?cit\.?|loc\.?\s?cit\.?)\b(\s*n\.?\s*\d+)?", ctx.before, re.I))
    numbers = list(dict.fromkeys(m.group(1) for m in new))
    if old:
        text = f"AGLC4 refers back with ‘(n {numbers[0]})’, not ‘{old[0].group().strip()}’"
    elif len(numbers) == 1:
        text = f"Already cited in full at footnote {numbers[0]}, so shortened with ‘(n {numbers[0]})’"
    else:
        text = f"Already cited in full at footnotes {_join(numbers)}, so shortened with ‘(n x)’"
    ctx.add("n_reference", text, "r 1.4.1", before=[m.span() for m in old], after=[m.span() for m in new])
    ctx.deletions_covered = True


def _short_title(ctx: _Context) -> None:
    for m in re.finditer(r"\(‘([^’]+)’\)", ctx.after):
        title = m.group(1)
        same = re.search(r"\(\s*[‘'\"“]\s*" + re.escape(title) + r"\s*[’'\"”]\s*\)", ctx.before)
        if same and same.group() == m.group():
            continue  # already defined as AGLC4 prints it (any italics fix is explained below)
        if same:
            ctx.add("short_title", f"Short title (‘{title}’) set in single curly quotes", "r 1.4.4",
                    before=[same.span()], after=[m.span()])
            continue
        ctx.add("short_title", f"Defines the short title ‘{title}’ for later references to this source",
                "r 1.4.4", after=[m.span()])
        # A definition the student wrote differently ("('the Act')") is replaced by this one
        ctx.covered_before += [d.span() for d in re.finditer(r"\(\s*[‘'\"“][^)]*[’'\"”]\s*\)", ctx.before)]


def _italics(ctx: _Context) -> None:
    b = ctx.b
    for now_italic, j0, j1 in ctx.italic_groups:
        text = ctx.after[b[j0].start:b[j1].end]
        span = [(b[j0].start, b[j1].end)]
        if _overlaps(span[0], ctx.covered_after):
            continue  # inside a new short title definition, say
        prev = next((t for t in reversed(b[:j0]) if not t.space), None)
        if now_italic:
            kind, line, rule = _made_italic(ctx, text, prev)
        else:
            kind, line, rule = _made_roman(ctx, text, j0)
        ctx.add(kind, line, rule, after=span)


def _made_italic(ctx: _Context, text: str, prev: _Token | None) -> tuple[str, str, str | None]:
    if _YEAR.match(text) and prev is not None and prev.italic:
        return "act_year_italic", "The year is part of an Act’s title, so it’s italic too", "r 3.1.2"
    if "legislation" in ctx.types and re.search(r"\b\d{4}$", text):
        return "title_italic", "An Act’s title and year are italic", "rr 3.1.1–3.1.2"
    if text == "v" and ctx.types & _CASES:
        return "title_italic", "The ‘v’ is part of the case name, so it’s italic", _case_rule(ctx, "r 2.1.11", "r 25.1.1")
    if ctx.types & _CASES and not re.search(r"\d", text):
        return "title_italic", "Case names are italic", _case_rule(ctx, "r 2.1.1", "r 25.1.1")
    if "legislation" in ctx.types and re.search(r"\b(Act|Regulations?|Rules|Code|Constitution)\b", text):
        return "title_italic", "An Act’s title is italic", "r 3.1.1"
    if ctx.types & {"book", "book_chapter"}:
        return "title_italic", "Book titles are italic", "r 6.2"
    if "website" in ctx.types:
        return "title_italic", "The website’s name is italic", "r 7.15"
    if "journal_article" in ctx.types:
        return "title_italic", "The journal’s name is italic", "r 5.5"
    return "title_italic", "Titles are italic", _source_rule(ctx)


def _made_roman(ctx: _Context, text: str, j0: int) -> tuple[str, str, str | None]:
    if _SIGNALS.match(text.strip(", ")):
        return "roman", "Introductory signals aren’t italic", "r 1.2"
    if "legislation" in ctx.types and _JURISDICTION.match(text):
        return "roman", "Only an Act’s title and year are italic, not the jurisdiction", "r 3.1.3"
    quoted = ctx.after.rfind("‘", 0, ctx.b[j0].start) > ctx.after.rfind("’", 0, ctx.b[j0].start)
    if quoted and ctx.types & {"journal_article", "book_chapter"}:
        return "roman", "Article and chapter titles go in single quotes, not italics", "r 5.2"
    if ctx.types & _CASES and re.search(r"[\d\[\]()]", text):
        return "roman", "Only the case name is italic, not the year or report details", _case_rule(ctx, "ch 2", "r 25.1")
    return "roman", "Set upright: only titles are italic", _source_rule(ctx)


_CASES = {"case", "us_case"}


def _case_rule(ctx: _Context, australian: str, us: str) -> str | None:
    """The rule for a case-citation change: AGLC4 ch 2's for Australian (and similar) cases,
    r 25.1's for United States cases, none when the footnote cites both."""
    kinds = ctx.types & _CASES
    return None if len(kinds) != 1 else australian if "case" in kinds else us


def _source_rule(ctx: _Context) -> str | None:
    """The rule for the footnote's kind of source, when it cites only one kind: where a
    general styling change ('only titles are italic') is set out for that source."""
    rules = {_CHAPTERS[t][1] for t in ctx.types if t in _CHAPTERS}
    return rules.pop() if len(rules) == 1 and ctx.types <= set(_CHAPTERS) else None


def _case_number(ctx: _Context) -> None:
    for m in re.finditer(r"\((Nos? \d+[^)]*)\)", ctx.before):
        new = ctx.after.find(f"[{m.group(1)}]")
        if new >= 0:
            ctx.add("case_number", f"A case’s number goes in square brackets: ‘[{m.group(1)}]’", "r 2.1.13",
                    before=[m.span()], after=[(new, new + len(m.group()))])


def _judges(ctx: _Context) -> None:
    for m in re.finditer(r"\bper\s+((?:[A-Z][\w’'-]*,?\s+(?:and\s+)?)+(?:CJ|ACJ|JJ|JA|JJA|AJ|P|J))\b", ctx.before):
        new = ctx.after.find(f"({m.group(1)})")
        if new >= 0:
            ctx.add("judges", "Judges are named in brackets after the pinpoint, without ‘per’", "r 2.4.1",
                    before=[m.span()], after=[(new, new + len(m.group(1)) + 2)])


def _type_label(ctx: _Context) -> None:
    for m in _TYPE_LABEL.finditer(ctx.before):
        label = m.group(1)
        if re.search(re.escape(label), ctx.after, re.I):
            continue
        what, rule = _TYPE_LABELS[label.lower()]
        ctx.add("type_label", f"AGLC4 doesn’t label {what}, so ‘{label}’ is removed", rule,
                before=[(m.start() + 1, m.end())])
    # Any other label on a kind of source AGLC4 never labels ('(Journal Report, 2021)')
    kinds = [_UNLABELLED[t] for t in sorted(ctx.types) if t in _UNLABELLED]
    if len(kinds) != 1:
        return
    what, rule = kinds[0]
    for m in validate.TYPE_LABEL.finditer(ctx.before):
        label = m.group(1)
        if label.lower() in _TYPE_LABELS or re.search(re.escape(label), ctx.after, re.I):
            continue
        ctx.add("type_label", f"AGLC4 doesn’t label {what}, so ‘{label}’ is removed", rule,
                before=[(m.start() + 1, m.end())])


def _pinpoint_punctuation(ctx: _Context) -> None:
    for e in ctx.edits:
        ins = "".join(t.text for t in e.inserted).strip()
        dels = "".join(t.text for t in e.deleted if t.text.lower() not in _PIN_MARKERS and t.text != ".").strip()
        pin_follows = e.next_after is not None and (e.next_after.text == "[" or e.next_after.text[0].isdigit())
        if ins == "," and not dels and pin_follows and e.prev_after is not None and e.prev_after.text[-1].isdigit():
            rule = _case_rule(ctx, "r 2.2.5", "r 25.1.4") or ("r 5.7" if "journal_article" in ctx.types else None)
            ctx.add("pinpoint_comma", "A comma and a space go before a pinpoint", rule, after=[e.after_span])
        elif dels == "," and not ins and "legislation" in ctx.types and e.next_before is not None \
                and re.match(r"(ss?|sections?|secs?|pts?|divs?|schs?|regs?|rr?|cls?)$", e.next_before.text, re.I):
            ctx.add("pinpoint_comma", "No comma between an Act and its pinpoint", "r 3.1.4",
                    before=[e.before_span])


def _pinpoint_markers(ctx: _Context) -> None:
    for e in ctx.edits:
        words = [t for t in e.deleted if not t.space and t.text.lower() in _PIN_MARKERS]
        for t in words:
            rest = ctx.before[t.end:].lstrip(". ")
            if t.text.lower() == "at":
                rest = re.sub(r"^(pp?|pg|paras?)\b\.?\s*", "", rest)
            if not rest[:1].isdigit() and not rest.startswith("["):
                continue
            # '[597]' is the result of 'para 597'; a section's 'para' (r 3.1.4) is never removed
            marker = _PIN_MARKERS[t.text.lower()]
            text = {
                "page": "Page pinpoints don’t take ‘p’ or ‘pp’",
                "at": "Pinpoints follow the citation directly, without ‘at’",
                "para": "Paragraph pinpoints go in square brackets, without ‘para’",
            }[marker]
            # with the comma before it, if any ('Ibid, at 45' -> 'Ibid 45')
            start = len(ctx.before[:t.start].rstrip().removesuffix(","))
            ctx.add("pinpoint_marker", text, "r 1.1.6", before=[(start, len(ctx.before) - len(rest))])
            if marker == "para":
                ctx.covered_after += [m.span() for m in re.finditer(r"[\[\]]", ctx.after)]


def _sections(ctx: _Context) -> None:
    if "legislation" not in ctx.types:
        return
    old = [m for m in _SECTION_WORDS.finditer(ctx.before) if m.group(1) not in ("s", "ss")]
    if old and re.search(r"\bss? \d", ctx.after):
        ctx.add("section", "Sections are cited as ‘s 5’, or ‘ss 5–7’ for more than one", "r 3.1.4",
                before=[m.span() for m in old], after=[m.span() for m in re.finditer(r"\bss?(?= \d)", ctx.after)])


def _spans(ctx: _Context) -> None:
    after_spans = {(m.group(2), m.group(5) + m.group(6)): m for m in _SPAN.finditer(ctx.after)}
    for m in _SPAN.finditer(ctx.before):
        first, sep, second = m.group(2), m.group(4), m.group(6)
        hit = next((am for (start, _), am in after_spans.items() if start == first and am.group(4) == "–"), None)
        if hit is None or hit.group() == m.group():
            continue
        shortened = hit.group(6) != second
        if shortened:
            text = f"Page range shortened to ‘{hit.group().strip()}’, with an en dash" if sep != "–" \
                else f"Page range shortened to ‘{hit.group().strip()}’"
        else:
            text = "A range takes an en dash, not a hyphen"
        ctx.add("span", text, "r 1.1.7", before=[m.span()], after=[hit.span()])


def _abbreviations(ctx: _Context) -> None:
    for m in _DOTTED.finditer(ctx.before):
        letters = re.sub(r"[.\s]", "", m.group())
        new = re.search(r"\b" + re.escape(letters) + r"\b", ctx.after)
        if new and m.group().strip() not in ctx.after:
            ctx.add("abbreviation", "No full stops in abbreviations", "r 1.6.1", before=[m.span()], after=[new.span()])


def _quotes(ctx: _Context) -> None:
    for m in re.finditer(r"‘([^’]+)’", ctx.after):
        inner = re.escape(m.group(1))
        old = re.search(r"([\"“]|'|‘)" + inner + r"([\"”]|'|’)", ctx.before)
        if old and old.group() != m.group():
            double = old.group(1) in "\"“"
            text = "Titles go in single quotation marks, not double" if double else "Quotation marks set as curly quotes"
            rule = "r 5.2" if double and ctx.types & {"journal_article", "book_chapter"} else None
            ctx.add("quotes", text, rule, before=[(old.start(), old.start() + 1), (old.end() - 1, old.end())],
                    after=[m.span()])


def _closing_full_stop(ctx: _Context) -> None:
    before, after = ctx.before.rstrip(), ctx.after.rstrip()
    if before and after.endswith(".") and not before.endswith((".", "!", "?")):
        ctx.add("full_stop", "Every footnote ends with a full stop", "r 1.1.4", before=[(len(before) - 1, len(before))],
                after=[(len(after) - 1, len(after))])


_DOUBLE_SPACE = re.compile(r"\S[ \t]{2,}\S")


def _extra_spaces(ctx: _Context) -> None:
    """The diff treats any run of spaces as one, so a removed double space needs its own line."""
    if _DOUBLE_SPACE.search(ctx.before) and not _DOUBLE_SPACE.search(ctx.after):
        ctx.add("spaces", "Extra space between words removed")


_DETECTORS = [_ibid, _n_reference, _short_title, _italics, _case_number, _judges, _type_label, _pinpoint_punctuation,
              _pinpoint_markers, _sections, _spans, _abbreviations, _quotes, _closing_full_stop,
              _extra_spaces]


def _remainder(ctx: _Context) -> None:
    """One line for any edit no detector accounted for."""
    def inside(t: _Token, spans: list[tuple[int, int]]) -> bool:
        return t.space or any(a <= t.start and t.end <= b for a, b in spans)

    def covered(e: _Edit) -> bool:
        return (ctx.deletions_covered or all(inside(t, ctx.covered_before) for t in e.deleted)) and all(
            inside(t, ctx.covered_after) for t in e.inserted)

    if not any(e.substantive and not covered(e) for e in ctx.edits):
        return
    kinds = [_CHAPTERS[t] for t in dict.fromkeys(sorted(ctx.types)) if t in _CHAPTERS]
    lead = "Other details set out" if ctx.changes else "Set out"
    if not kinds:
        ctx.add("other", f"{lead} in AGLC4 form")
        return
    nouns = list(dict.fromkeys(noun for noun, _ in kinds))
    rules = list(dict.fromkeys(rule for _, rule in kinds))
    rule = rules[0] if len(rules) == 1 else ", ".join(rules)
    ctx.add("other", f"{lead} in the AGLC4 form for {_join(nouns)}", rule)


def _join(items: Sequence[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]
