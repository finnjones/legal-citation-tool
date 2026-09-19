"""Deterministic checks that no information is lost or invented between the original
footnote and the formatted citation. No LLM is involved: everything is token accounting.

1. coverage   original footnote -> extraction   every meaningful word/number was captured
2. grounding  extraction -> original footnote   no number was invented by the model
3. rendering  source fields -> formatted text   the formatter printed every field

Tokens are compared case-insensitively after removing full stops from abbreviations
('N.S.W.' == 'NSW'), so the model and the normaliser may reformat but not drop.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from pydantic import BaseModel

from .models import Citation, CitationSegment, Footnote, RichText, TextSegment

# Words that carry no information of their own: citation furniture that AGLC rewrites
# or removes (signals, 'at', 'supra', 'ibid', pinpoint labels, 'ed', 'et al'...), and
# common short function words.
NOISE = frozenset(
    """
    a an and the of in on for to at by with from as or per via
    p pp para paras paragraph paragraphs s ss sec section sections art arts article articles
    reg regs regulation regulations r rr rule rules cl cls clause clauses pt pts part parts
    div divs division divisions sch schs schedule schedules ch chs chapter chapters
    vol vols volume volumes bk bks book books annex annexes n nn fn fns footnote note notes
    see also cf eg generally contra but especially compare
    ibid id idem supra infra above below op cit loc hereafter hereinafter referred
    ed eds edn edns edition editor editors rev tr trans translated translator
    et al v vs no nos th st nd rd
    opened signature signed entered into force yet
    http https www
    """.split()
)

_ABBREV_DOTS = re.compile(r"(?<=\b[A-Za-z])\.")          # N.S.W. -> NSW, U.N.T.S. -> UNTS
_TOKEN = re.compile(r"\d+|[^\W\d_]+(?:['’][^\W\d_]+)?")   # numbers, words (incl. accents, O'Donovan)
_SPAN = re.compile(r"(\d+)\s*[–—-]\s*(\d+)")


def tokens(text: str) -> list[str]:
    """Lower-cased word and number tokens, with abbreviation full stops removed."""
    text = _ABBREV_DOTS.sub("", text).replace("’", "'")
    return [t.lower() for t in _TOKEN.findall(text)]


def meaningful(text: str) -> set[str]:
    return {t for t in tokens(text) if t not in NOISE and (t.isdigit() or len(t) > 1)}


def numbers(text: str) -> set[str]:
    """Numeric tokens, with shortened spans expanded ('150–5' also yields '155')."""
    out = {t for t in tokens(text) if t.isdigit()}
    for a, b in _SPAN.findall(text):
        if len(b) < len(a):
            out.add(a[: len(a) - len(b)] + b)
    return {n.lstrip("0") or "0" for n in out}


def _strings(value: Any) -> Iterable[str]:
    """Every string inside a pydantic model / list / scalar (enum-like fields excluded)."""
    if isinstance(value, BaseModel):
        for name, field_value in value:
            if name in {"type", "kind", "year_style", "source_key", "plural"}:
                continue
            yield from _strings(field_value)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, str):
        yield value
    elif isinstance(value, RichText):  # pragma: no cover - RichText is a BaseModel
        yield value.text


# --------------------------------------------------------------------------- #
# 1. coverage: nothing the author wrote is dropped
# --------------------------------------------------------------------------- #


def extracted_text(segments: list, extra: Iterable[str] = ()) -> str:
    """Everything an extraction captured, as one string: text segments verbatim plus every
    field of every citation (resolved sources included)."""
    parts: list[str] = list(extra)
    for seg in segments:
        if isinstance(seg, TextSegment):
            parts.append(seg.text.text)
        elif isinstance(seg, CitationSegment):
            parts.extend(_strings(seg.citation))
            parts.append(seg.original if seg.citation.source.type == "other" else "")
    return " ".join(parts)


def missing_from_extraction(original: str, segments: list, extra: Iterable[str] = ()) -> list[str]:
    """Meaningful tokens of `original` that appear nowhere in the extraction, in the
    order they occur in the footnote. Empty means nothing was dropped."""
    captured = meaningful(extracted_text(segments, extra)) | numbers(extracted_text(segments, extra))
    seen: set[str] = set()
    missing: list[str] = []
    for tok in tokens(original):
        if tok in NOISE or (not tok.isdigit() and len(tok) <= 1) or tok in seen:
            continue
        seen.add(tok)
        key = (tok.lstrip("0") or "0") if tok.isdigit() else tok
        if key not in captured and tok not in captured:
            missing.append(tok)
    return missing


# --------------------------------------------------------------------------- #
# 2. grounding: the model invented no numbers
# --------------------------------------------------------------------------- #

# Fields holding numbers that must be copied from the source, never supplied from memory.
_NUMERIC_FIELDS = (
    "year", "volume", "issue", "starting_page", "judgment_number", "edition", "page",
    "document_number", "treaty_series", "date", "opened_for_signature", "entry_into_force",
)


def remove_invented_numbers(citation: Citation, original: str) -> tuple[Citation, list[str]]:
    """Blank any numeric source field (and drop any pinpoint) containing a number that
    doesn't appear in the original footnote. Returns the cleaned citation and a note per
    removal. Only for sources extracted from this footnote, not resolved references."""
    source_numbers = numbers(original)
    notes: list[str] = []
    updates: dict[str, Any] = {}
    for field in _NUMERIC_FIELDS:
        value = getattr(citation.source, field, None)
        if isinstance(value, str) and value and not numbers(value) <= source_numbers:
            updates[field] = None
            notes.append(f"removed {field} {value!r}, which isn't in the original")
    pins = [p for p in citation.pinpoints if numbers(p.value) <= source_numbers]
    if len(pins) != len(citation.pinpoints):
        dropped = [p.value for p in citation.pinpoints if p not in pins]
        notes.append(f"removed pinpoint {', '.join(dropped)}, which isn't in the original")
    if not updates and len(pins) == len(citation.pinpoints):
        return citation, []
    source = citation.source.model_copy(update=updates)
    return citation.model_copy(update={"source": source, "pinpoints": pins}), notes


# --------------------------------------------------------------------------- #
# 3. rendering: the formatter printed every field
# --------------------------------------------------------------------------- #


def missing_from_rendering(citation: Citation, rendered: str) -> list[str]:
    """Meaningful tokens of the citation's fields that the formatted full citation
    doesn't contain (a formatter bug, since normalised fields should all be printed)."""
    source = citation.source
    if getattr(source, "kind", None) == "constitution" and not getattr(source, "year", None):
        source = source.model_copy(update={"jurisdiction": None})  # *Australian Constitution*, no (Cth)
    fields = " ".join(_strings(source)) + " " + " ".join(p.value for p in citation.pinpoints)
    if citation.pinpoint_judges:
        fields += " " + citation.pinpoint_judges
    have = meaningful(rendered) | numbers(rendered)
    return sorted(t for t in meaningful(fields) | numbers(fields) if t not in have)


def check_footnote_rendering(footnote: Footnote, formatter_for) -> list[str]:
    """Rendering check for every citation in a footnote; returns human-readable problems."""
    problems = []
    for seg in footnote.segments:
        if isinstance(seg, CitationSegment) and seg.citation.source.type != "other":
            f = formatter_for(seg.citation)
            gaps = missing_from_rendering(seg.citation, f.full(seg.citation).text)
            if gaps:
                problems.append(f"formatter omitted {', '.join(gaps)} from {seg.citation.source.type} citation")
    return problems
