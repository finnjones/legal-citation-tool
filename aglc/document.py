"""Document pass: turns per-footnote citations into AGLC-correct text using the
citation history (ibid, '(n x)', short titles, signals, punctuation) and builds
the bibliography.

This module contains no source-type-specific formatting knowledge; all of that
lives in the ``Formatter`` subclasses (``aglc/formatters/*``). This module's
job is purely the *document-level* bookkeeping described in AGLC4 ch 1:

- r 1.1.3/1.1.4: joining multiple citations within a footnote and closing
  punctuation.
- r 1.2: introductory signals and their capitalisation.
- r 1.4.1/1.4.3/1.4.4: deciding between a full citation, 'Ibid', and a
  short-title/'(n x)' subsequent reference.
- r 1.13: assembling the bibliography.

Two passes are made over the footnotes:

1. ``_build_plans`` walks the footnotes once, deciding -- for every citation
   occurrence -- whether it is the first (full) citation of its source, an
   'Ibid', or a subsequent reference. This also determines, for each source,
   whether it is ever cited again other than purely through a chain of
   'Ibid's (which drives whether a short title needs to be defined at all,
   per r 1.4.3/1.4.4).
2. ``render_document`` uses that plan to actually build the RichText for each
   footnote (signals, separators, punctuation) and the bibliography.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .formatters import BIB_ORDER, Formatter, formatter_for
from .models import (
    BibliographySection,
    Citation,
    CitationSegment,
    Footnote,
    FootnoteResult,
    ProcessResult,
    RichText,
    TextSegment,
    Warning_,
)

# AGLC4 uses curly quotes throughout (see eg r 1.4.4's "(' Short Title ')").
OPEN_QUOTE = "‘"
CLOSE_QUOTE = "’"

_SENTENCE_END = (".", "!", "?")


# --------------------------------------------------------------------------- #
# small text helpers
# --------------------------------------------------------------------------- #


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:]


def _source_key(citation: Citation) -> str:
    """`citation.source_key` should always be set by normalisation; fall back
    to per-object identity (never grouped) so a missing key can't silently
    merge unrelated sources."""
    return citation.source_key or f"__unkeyed_{id(citation)}"


def _at_sentence_start(out: RichText) -> bool:
    """True at the very start of a footnote, and after a full stop (a new
    sentence) -- as opposed to after a colon or semicolon, where 'ibid' and
    signals are lower-cased (r 1.2, r 1.4.3)."""
    text = out.text.rstrip()
    return text == "" or text.endswith(_SENTENCE_END)


def _ensure_closing_punctuation(out: RichText) -> RichText:
    """AGLC4 r 1.1.4: every footnote ends with exactly one closing stop.
    Don't double up if the content already ends in terminal punctuation
    (eg discursive text ending in '?', or an 'Ibid.' the caller pre-closed);
    do add one after anything else, including a URL's closing '>'."""
    text = out.text
    if not text or text[-1] in _SENTENCE_END:
        return out
    out.append(".")
    return out


# --------------------------------------------------------------------------- #
# pass 1: decide full / ibid / subsequent for every citation occurrence
# --------------------------------------------------------------------------- #


@dataclass
class _Plan:
    kind: Literal["full", "ibid", "subsequent"]
    ibid_suffix: str = ""  # eg "42" for "Ibid 42"; "" for a bare "Ibid"


def _citation_segments(fn: Footnote) -> list[CitationSegment]:
    return [seg for seg in fn.segments if isinstance(seg, CitationSegment)]


def _build_plans(
    footnotes: list[Footnote],
) -> tuple[dict[int, _Plan], dict[str, int], dict[str, Citation], dict[str, bool]]:
    """Single forward pass over all footnotes.

    Returns:
        plans: keyed by `id(segment)` -> what to render for that occurrence.
        first_footnote: source_key -> footnote number of its first citation.
        first_citation: source_key -> the Citation object used for that first
            (full) citation -- also the one bibliography entries are built from.
        needs_lookahead: source_key -> True if the source is cited again later
            other than purely via 'Ibid' (r 1.4.3/1.4.4: this is what makes a
            short title worth defining at all).
    """
    plans: dict[int, _Plan] = {}
    first_footnote: dict[str, int] = {}
    first_citation: dict[str, Citation] = {}
    needs_lookahead: dict[str, bool] = {}
    seen: set[str] = set()
    prev_footnote_citations: list[Citation] = []

    for fn in footnotes:
        this_footnote_citations: list[Citation] = []
        for j, seg in enumerate(_citation_segments(fn)):
            citation = seg.citation
            key = _source_key(citation)
            formatter = formatter_for(citation)

            if key not in seen:
                seen.add(key)
                first_footnote[key] = fn.number
                first_citation[key] = citation
                plans[id(seg)] = _Plan(kind="full")
            else:
                eligible = False
                suffix = ""
                # r 1.4.3: ibid only ever refers to the *immediately preceding
                # footnote*, and only when it contains exactly one source, and
                # only as the first citation of the current footnote (a later
                # citation within the same footnote can't use ibid at all).
                if (
                    j == 0
                    and len(prev_footnote_citations) == 1
                    and _source_key(prev_footnote_citations[0]) == key
                ):
                    prev_citation = prev_footnote_citations[0]
                    cur_pin = formatter.ibid_pinpoint(citation)
                    prev_pin = formatter.ibid_pinpoint(prev_citation)
                    # r 1.4.3 note: if the preceding footnote had a pinpoint
                    # but this one needs none, ibid must NOT be used -- fall
                    # back to r 1.4.1 instead.
                    if not (cur_pin == "" and prev_pin != ""):
                        eligible = True
                        suffix = "" if cur_pin == prev_pin else cur_pin

                if eligible:
                    plans[id(seg)] = _Plan(kind="ibid", ibid_suffix=suffix)
                else:
                    plans[id(seg)] = _Plan(kind="subsequent")
                    needs_lookahead[key] = True

            this_footnote_citations.append(citation)

        prev_footnote_citations = this_footnote_citations

    return plans, first_footnote, first_citation, needs_lookahead


def _short_titles(
    first_citation: dict[str, Citation],
    needs_lookahead: dict[str, bool],
) -> tuple[dict[str, str], dict[str, bool], dict[str, bool]]:
    """r 1.4.1/1.4.4: the short title text to use for subsequent references,
    whether a "('Short Title')" definition should be appended to the first
    (full) citation, and which sources need author-surname disambiguation.

    A definition is only worth adding when the formatter defines short titles
    at all (cases/legislation/treaties -- secondary sources use the author's
    surname instead, see `Formatter.defines_short_title`), and when either
    the source is cited again other than purely through a chain of 'Ibid's,
    or the author explicitly supplied one.

    r 1.4.1: "if several works by the same author/s are cited, both the
    surname ... and the title or short title ... should be provided" --
    for sources that use the author-surname style (`defines_short_title` is
    False), a subsequent reference normally repeats just the surname; if two
    different sources land on the *same* surname, both need the title added
    to disambiguate them (see `_disambiguation_title`).
    """
    short_title_text: dict[str, str] = {}
    append_definition: dict[str, bool] = {}
    for key, citation in first_citation.items():
        formatter = formatter_for(citation)
        st = formatter.short_title(citation)
        short_title_text[key] = st
        # An author-supplied short title is always defined, for any source type (r 1.4.4:
        # '(‘*Traditional Rights and Freedoms*’)' for a report, '(‘Meanings of Membership’)'
        # for an article); otherwise only types that use short titles get one, when reused.
        wants_definition = bool(citation.short_title) or (
            formatter.defines_short_title and needs_lookahead.get(key, False)
        )
        append_definition[key] = bool(wants_definition and st)

    surname_groups: dict[str, list[str]] = {}
    for key, citation in first_citation.items():
        formatter = formatter_for(citation)
        if formatter.defines_short_title:
            continue  # cases/legislation/treaties: not the "author surname" style
        st = short_title_text.get(key, "")
        if not st:
            continue
        surname_groups.setdefault(st, []).append(key)
    disambiguate = {key: True for keys in surname_groups.values() if len(keys) > 1 for key in keys}

    return short_title_text, append_definition, disambiguate


def _disambiguation_title(citation: Citation) -> str:
    """r 1.4.1: the title to append after an author's surname when they have
    more than one cited work. Prefers an author-supplied short title (eg
    '"Meanings of Membership"'); otherwise falls back to whatever title-like
    field the source has. NOTE: this duck-types across source models rather
    than using a dedicated Formatter hook -- see the final report for a
    proposed `Formatter.disambiguation_title()` contract addition."""
    if citation.short_title:
        return citation.short_title
    src = citation.source
    for field in ("title", "chapter_title", "book_title"):
        value = getattr(src, field, None)
        if value:
            return value
    return ""


def _render_disambiguated_subsequent(
    citation: Citation,
    formatter: Formatter,
    surname: str,
    first_footnote: int,
    out: RichText,
) -> None:
    """As `Formatter.subsequent()`, but with the title appended after the
    surname to disambiguate two different works by the same author (r 1.4.1).
    Built by hand (rather than via `Formatter.subsequent()`) because the
    surname is always roman while the title needs its own italic/quoted
    styling -- something a single `short_title: str` parameter can't carry."""
    out.append(surname)
    title = _disambiguation_title(citation)
    if title:
        out.append(", ")
        if formatter.italic_short_title:
            out.append(title, italic=True)
        else:
            out.append(OPEN_QUOTE + title + CLOSE_QUOTE)
    if formatter.uses_n_reference:
        out.append(f" (n {first_footnote})")
    pin_text = formatter.pinpoints(citation.pinpoints)
    if pin_text:
        out.append(("," if not formatter.uses_n_reference else "") + " " + pin_text)
    if citation.pinpoint_judges:
        out.append(f" ({citation.pinpoint_judges})")


# --------------------------------------------------------------------------- #
# pass 2: render
# --------------------------------------------------------------------------- #


def _render_signal(signal: str | None, at_start: bool) -> str:
    """r 1.2: capitalised at the start of a footnote/sentence, lower-cased
    otherwise (eg after a colon or semicolon). Signals are never italicised."""
    if not signal:
        return ""
    text = signal if at_start else _lower_first(signal)
    return text + " "


def _render_citation(
    citation: Citation,
    plan: _Plan,
    out: RichText,
    *,
    first_footnote: dict[str, int],
    short_title_text: dict[str, str],
    append_definition: dict[str, bool],
    disambiguate: dict[str, bool],
) -> None:
    formatter = formatter_for(citation)
    key = _source_key(citation)

    at_start = _at_sentence_start(out)
    sig = _render_signal(citation.signal, at_start)
    if sig:
        out.append(sig)

    if plan.kind == "full":
        out.extend(formatter.full(citation))
        if append_definition.get(key):
            # The definition introduces the author's own short title where they gave one
            # (r 1.4.4); short_title_text may be an author surname for secondary sources.
            out.append(" (" + OPEN_QUOTE)
            out.append(citation.short_title or short_title_text[key], italic=formatter.italic_short_title)
            out.append(CLOSE_QUOTE + ")")
    elif plan.kind == "ibid":
        # r 1.4.3: 'Ibid' is capitalised at the start of a footnote; a
        # signal "refers only to the source ... not the introductory
        # signal" so once a signal has been emitted, 'ibid' is lower-case.
        capitalise = at_start and not citation.signal
        out.append("Ibid" if capitalise else "ibid")
        if plan.ibid_suffix:
            out.append(" " + plan.ibid_suffix)
    else:  # subsequent
        st = short_title_text.get(key, "")
        if st == "":
            # "Returning '' means 'no short form: repeat the full citation'"
            out.extend(formatter.full(citation))
        elif disambiguate.get(key):
            _render_disambiguated_subsequent(citation, formatter, st, first_footnote[key], out)
        else:
            out.extend(formatter.subsequent(citation, st, first_footnote[key]))


_BARE_SEPARATORS = {"", ";", ".", ","}


def _render_footnote(
    fn: Footnote,
    plans: dict[int, _Plan],
    first_footnote: dict[str, int],
    short_title_text: dict[str, str],
    append_definition: dict[str, bool],
    disambiguate: dict[str, bool],
) -> RichText:
    if not fn.segments:
        return fn.original

    out = RichText()
    prev_was_citation = False
    prev_citation: Citation | None = None

    for seg in fn.segments:
        if isinstance(seg, TextSegment):
            if prev_was_citation and seg.text.text.strip() in _BARE_SEPARATORS:
                # A bare ';' / '.' between citations from extraction: the separator is
                # decided below from the signals (r 1.1.3), and closing punctuation by
                # _ensure_closing_punctuation, so drop the extracted one.
                continue
            out.extend(seg.text)
            prev_was_citation = False
            prev_citation = None
            continue

        # r 1.1.3: adjacent citations with nothing between them (no
        # TextSegment separator from extraction) are joined by a semicolon,
        # unless the introductory signal changes, in which case a new
        # sentence (full stop) is required instead.
        if prev_was_citation and prev_citation is not None:
            same_signal = prev_citation.signal == seg.citation.signal
            out.append("; " if same_signal else ". ")

        plan = plans[id(seg)]
        _render_citation(
            seg.citation,
            plan,
            out,
            first_footnote=first_footnote,
            short_title_text=short_title_text,
            append_definition=append_definition,
            disambiguate=disambiguate,
        )
        prev_was_citation = True
        prev_citation = seg.citation

    return _ensure_closing_punctuation(out)


# --------------------------------------------------------------------------- #
# bibliography (r 1.13)
# --------------------------------------------------------------------------- #


def _build_bibliography(first_citation: dict[str, Citation]) -> list[BibliographySection]:
    by_category: dict[str, list[tuple[str, RichText]]] = {cat: [] for cat in BIB_ORDER}
    for citation in first_citation.values():
        formatter = formatter_for(citation)
        entry = formatter.bibliography(citation)
        sort_key = formatter.sort_key(citation)
        by_category.setdefault(formatter.bibliography_category, []).append((sort_key, entry))

    sections: list[BibliographySection] = []
    for category in BIB_ORDER:
        items = by_category.get(category, [])
        if not items:
            continue
        items.sort(key=lambda pair: pair[0])
        sections.append(BibliographySection(heading=category, entries=[entry for _, entry in items]))
    return sections


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def render_document(footnotes: list[Footnote], *, bibliography: bool = True) -> ProcessResult:
    """`footnotes` must already be extracted and normalised (every Citation has
    source_key set). Returns formatted text for every footnote, bibliography
    sections (if requested) and warnings."""
    plans, first_footnote, first_citation, needs_lookahead = _build_plans(footnotes)
    short_title_text, append_definition, disambiguate = _short_titles(first_citation, needs_lookahead)

    results: list[FootnoteResult] = []
    warnings: list[Warning_] = []
    for fn in footnotes:
        formatted = _render_footnote(
            fn, plans, first_footnote, short_title_text, append_definition, disambiguate
        )
        results.append(FootnoteResult(number=fn.number, original=fn.original, formatted=formatted))
        if "[MISSING:" in formatted.text:
            warnings.append(Warning_(footnote=fn.number, message=f"Footnote {fn.number} has missing data"))

    bib_sections = _build_bibliography(first_citation) if bibliography else []

    return ProcessResult(footnotes=results, bibliography=bib_sections, warnings=warnings)
