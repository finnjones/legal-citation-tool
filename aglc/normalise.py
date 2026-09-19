"""Normalisation: deterministic clean-up of extracted citations using lookup
tables in aglc/data/.

Implements AGLC4 (4th ed) rules:
  - r 2.1: case name clean-up (full stops, 'v', the Crown, '[No 2]')
  - r 2.2.1, 2.2.3: report series abbreviations and round/square year brackets
  - r 2.3: medium-neutral court identifiers
  - r 3.1.3: jurisdiction abbreviations, r 15.3/17-20.2.3 style Constitution handling

Data tables live in aglc/data/*.json and are cached with functools.lru_cache.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from .models import (
    BookChapterSource,
    BookSource,
    CaseSource,
    Citation,
    JournalArticleSource,
    LegislationSource,
    NewspaperSource,
    OtherSource,
    Pinpoint,
    PinpointKind,
    ReportSource,
    Source,
    TreatySource,
    WebsiteSource,
)

# --------------------------------------------------------------------------- #
# Data loading
# --------------------------------------------------------------------------- #

_DATA_DIR = Path(__file__).resolve().parent / "data"


@lru_cache(maxsize=None)
def _load_json(name: str) -> dict:
    with open(_DATA_DIR / name, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=None)
def _report_series_index() -> dict[str, dict]:
    """normalised variant -> series entry (abbrev/full_name/year_style/authorised)."""
    raw = _load_json("report_series.json")
    index: dict[str, dict] = {}
    for entry in raw["series"]:
        keys = {entry["abbrev"], entry.get("full_name", "")} | set(entry.get("variants", []))
        for key in keys:
            if key:
                index[_norm_key(key)] = entry
    return index


@lru_cache(maxsize=None)
def _courts_index() -> dict[str, dict]:
    """normalised variant -> {"id": ..., "name": ...}."""
    raw = _load_json("courts.json")
    index: dict[str, dict] = {}
    for entry in raw["courts"]:
        keys = {entry["id"], entry.get("name", "")} | set(entry.get("variants", []))
        for key in keys:
            if key:
                index[_norm_key(key)] = entry
    for variant, court_id in raw.get("variants", {}).items():
        index[_norm_key(variant)] = {"id": court_id}
    return index


@lru_cache(maxsize=None)
def _jurisdictions_index() -> dict[str, str]:
    """normalised variant -> canonical AGLC jurisdiction abbreviation."""
    raw = _load_json("jurisdictions.json")
    index: dict[str, str] = {}
    for abbrev, info in raw.items():
        keys = {abbrev, info.get("name", "")} | set(info.get("variants", []))
        for key in keys:
            if key:
                index[_norm_key(key)] = abbrev
    return index


# --------------------------------------------------------------------------- #
# Generic string helpers
# --------------------------------------------------------------------------- #


def _norm_key(s: str | None) -> str:
    """Lossy key used only for table lookups / identity comparison: lower-case,
    strip full stops/apostrophes/commas, and collapse away all whitespace."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"[.’'‘,]", "", s)
    s = re.sub(r"\s+", "", s)
    return s


def _strip_trailing_punct(s: str) -> str:
    return re.sub(r"[\s.,;:]+$", "", s.strip())


def _clean_field(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value.strip())
    value = _strip_trailing_punct(value)
    return value or None


def _clean_authors(authors: list[str]) -> list[str]:
    out = []
    for a in authors:
        a = re.sub(r"\s+", " ", a.strip())
        a = a.rstrip(",.").strip()
        if a:
            out.append(a)
    return out


def _surname(author: str) -> str:
    author = author.strip()
    if "," in author:
        return author.split(",", 1)[0].strip()
    parts = author.split()
    return parts[-1] if parts else author


# --------------------------------------------------------------------------- #
# Case name clean-up (AGLC4 r 2.1)
# --------------------------------------------------------------------------- #

_WRAP_CHARS = "\"'‘’“”*_"
_ABBREV_STOPS = re.compile(
    r"\b(Pty|Ltd|Co|Inc|Corp|Bros|Assn|Mr|Mrs|Ms|Dr|Jr|Sr|No)\.", re.IGNORECASE
)
_V_PATTERN = re.compile(r"\s+(?:vs\.?|V\.?)\s+", re.IGNORECASE)
_NO_PATTERN = re.compile(r"[\(\[]?\s*No\.?\s*(\d+(?:\s*(?:,|and)\s*\d+)*)\s*[\)\]]?\s*$", re.IGNORECASE)
_CROWN_QUEEN = {"the queen", "regina", "queen"}
_CROWN_KING = {"the king", "rex", "king"}


def _clean_case_name(name: str) -> str:
    """AGLC4 r 2.1: strip quotes, drop full stops from abbreviations, normalise
    'v', abbreviate/expand the Crown per r 2.1.4, and bracket '[No x]' per r 2.1.13."""
    if not name:
        return name
    n = name.strip()

    # strip wrapping quote/italic markers
    changed = True
    while changed and len(n) >= 2:
        changed = False
        if n[0] in _WRAP_CHARS and n[-1] in _WRAP_CHARS:
            n = n[1:-1].strip()
            changed = True

    n = re.sub(r"\s+", " ", n).strip()

    # remove full stops from common name abbreviations (r 2.1: 'Pty Ltd' not 'Pty. Ltd.')
    n = _ABBREV_STOPS.sub(r"\1", n)

    # normalise 'vs'/'vs.'/'V'/'V.' -> ' v '
    n = _V_PATTERN.sub(" v ", n)

    # r 2.1.4: 'Rex'/'Regina'/'The King'/'The Queen' -> 'R' only as first-named
    # party; as respondent, write 'The King'/'The Queen' in full.
    if re.search(r"\bv\b", n):
        parts = re.split(r"\s+v\s+", n)
        new_parts = []
        for i, part in enumerate(parts):
            core = part.strip()
            lowered = core.lower()
            if i == 0 and lowered in (_CROWN_QUEEN | _CROWN_KING):
                new_parts.append("R")
            elif lowered in _CROWN_QUEEN:
                new_parts.append("The Queen")
            elif lowered in _CROWN_KING:
                new_parts.append("The King")
            else:
                new_parts.append(core)
        n = " v ".join(new_parts)

    # r 2.1.13: '(No. 2)' / '(No 2)' / 'No 2' -> '[No 2]'
    m = _NO_PATTERN.search(n)
    if m:
        n = _NO_PATTERN.sub(lambda mm: f" [No {mm.group(1)}]", n)

    n = re.sub(r"\s+", " ", n).strip()
    return n


def _case_name_key(name: str) -> str:
    return _norm_key(_clean_case_name(name))


# --------------------------------------------------------------------------- #
# Pinpoints (r 1.1.6-1.1.7)
# --------------------------------------------------------------------------- #

_PINPOINT_PREFIXES = ("at ", "pp ", "p ", "paras ", "para ")


def _clean_pinpoint(p: Pinpoint) -> Pinpoint:
    value = p.value.strip()
    kind = p.kind

    lowered = value.lower()
    for prefix in _PINPOINT_PREFIXES:
        if lowered.startswith(prefix):
            value = value[len(prefix) :].strip()
            break

    if kind == PinpointKind.page and value.startswith("[") and value.endswith("]") and len(value) > 2:
        kind = PinpointKind.paragraph
        value = value[1:-1].strip()
    elif kind == PinpointKind.paragraph:
        value = value.strip("[]").strip()

    value = _strip_trailing_punct(value)
    return Pinpoint(kind=kind, value=value, plural=p.plural)


# --------------------------------------------------------------------------- #
# Lookups: report series / courts / jurisdictions
# --------------------------------------------------------------------------- #


def _canon_report(report: str) -> tuple[str | None, str | None, bool]:
    """Returns (canonical abbrev, year_style, matched)."""
    entry = _report_series_index().get(_norm_key(report))
    if entry:
        return entry["abbrev"], entry.get("year_style"), True
    return None, None, False


def _canon_court(court: str) -> tuple[str | None, bool]:
    entry = _courts_index().get(_norm_key(court))
    if entry:
        return entry["id"], True
    return None, False


def _canon_jurisdiction(jurisdiction: str) -> tuple[str | None, bool]:
    abbrev = _jurisdictions_index().get(_norm_key(jurisdiction))
    if abbrev:
        return abbrev, True
    return None, False


# --------------------------------------------------------------------------- #
# Per-source-type normalisation
# --------------------------------------------------------------------------- #


def _normalise_case(source: CaseSource) -> tuple[CaseSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()

    data["name"] = _clean_case_name(source.name)

    for field in ("year", "volume", "starting_page", "judgment_number", "court_name", "judges", "date"):
        if data.get(field):
            data[field] = _clean_field(data[field])

    if source.report:
        abbrev, year_style, matched = _canon_report(source.report)
        if matched:
            data["report"] = abbrev
            data["year_style"] = year_style
        else:
            data["report"] = _clean_field(source.report)
            warnings.append(f"Unknown report series: '{source.report.strip()}'")
    elif source.court_id and (source.judgment_number or source.year):
        # Medium-neutral citation (AGLC4 r 2.3.1): year is the volume identifier -> square.
        data["year_style"] = "square"

    if source.court_id:
        abbrev, matched = _canon_court(source.court_id)
        if matched:
            data["court_id"] = abbrev
        else:
            data["court_id"] = _clean_field(source.court_id)
            warnings.append(f"Unknown court identifier: '{source.court_id.strip()}'")

    if not source.year:
        warnings.append("Case citation missing year")

    return CaseSource(**data), warnings


def _normalise_legislation(source: LegislationSource) -> tuple[LegislationSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()

    title = (source.title or "").strip()
    year = source.year.strip() if source.year else None

    if not year and title:
        m = re.match(r"^(.*\S)\s+(\d{4})$", title)
        if m:
            title = m.group(1).strip()
            year = m.group(2)

    if _norm_key(title) in {"constitution", "commonwealthconstitution", "australianconstitution"}:
        data["kind"] = "constitution"
        title = "Australian Constitution"
        data["jurisdiction"] = "Cth"

    data["title"] = title
    data["year"] = year

    if data.get("jurisdiction"):
        abbrev, matched = _canon_jurisdiction(data["jurisdiction"])
        if matched:
            data["jurisdiction"] = abbrev
        else:
            warnings.append(f"Unknown jurisdiction: '{data['jurisdiction']}'")
    else:
        warnings.append("Legislation missing jurisdiction")

    if not year:
        warnings.append("Legislation missing year")

    return LegislationSource(**data), warnings


def _normalise_journal_article(source: JournalArticleSource) -> tuple[JournalArticleSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["authors"] = _clean_authors(source.authors)
    data["title"] = (source.title or "").strip()
    if source.journal:
        data["journal"] = source.journal.strip()
    else:
        warnings.append("Journal article missing journal name")
    for field in ("year", "volume", "issue", "starting_page"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    if not data["authors"]:
        warnings.append("Journal article missing author(s)")
    return JournalArticleSource(**data), warnings


def _normalise_book(source: BookSource) -> tuple[BookSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["authors"] = _clean_authors(source.authors)
    data["editors"] = _clean_authors(source.editors)
    data["title"] = (source.title or "").strip()
    for field in ("publisher", "edition", "year", "volume"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    if not data["authors"] and not data["editors"]:
        warnings.append("Book missing author(s)/editor(s)")
    return BookSource(**data), warnings


def _normalise_book_chapter(source: BookChapterSource) -> tuple[BookChapterSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["authors"] = _clean_authors(source.authors)
    data["editors"] = _clean_authors(source.editors)
    data["chapter_title"] = (source.chapter_title or "").strip()
    data["book_title"] = (source.book_title or "").strip()
    for field in ("publisher", "edition", "year", "starting_page"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    if not data["authors"]:
        warnings.append("Book chapter missing author(s)")
    return BookChapterSource(**data), warnings


def _normalise_report(source: ReportSource) -> tuple[ReportSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["title"] = (source.title or "").strip()
    for field in ("author", "document_type", "document_number", "date"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    if not data.get("author"):
        warnings.append("Report missing author/body")
    return ReportSource(**data), warnings


def _normalise_newspaper(source: NewspaperSource) -> tuple[NewspaperSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["authors"] = _clean_authors(source.authors)
    data["title"] = (source.title or "").strip()
    data["newspaper"] = (source.newspaper or "").strip()
    for field in ("place", "date", "page"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    if source.url:
        data["url"] = source.url.strip()
    return NewspaperSource(**data), warnings


def _normalise_website(source: WebsiteSource) -> tuple[WebsiteSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["authors"] = _clean_authors(source.authors)
    data["title"] = (source.title or "").strip()
    if data.get("website_name"):
        data["website_name"] = _clean_field(data["website_name"])
    if data.get("date"):
        data["date"] = _clean_field(data["date"])
    if source.url:
        data["url"] = source.url.strip()
    return WebsiteSource(**data), warnings


def _normalise_treaty(source: TreatySource) -> tuple[TreatySource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["title"] = (source.title or "").strip()
    data["parties"] = _clean_authors(source.parties)
    for field in ("opened_for_signature", "treaty_series", "entry_into_force"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    return TreatySource(**data), warnings


def _normalise_other(source: OtherSource) -> tuple[OtherSource, list[str]]:
    data = source.model_dump()
    data["text"] = (source.text or "").strip()
    return OtherSource(**data), []


_DISPATCH = {
    "case": _normalise_case,
    "legislation": _normalise_legislation,
    "journal_article": _normalise_journal_article,
    "book": _normalise_book,
    "book_chapter": _normalise_book_chapter,
    "report": _normalise_report,
    "newspaper": _normalise_newspaper,
    "website": _normalise_website,
    "treaty": _normalise_treaty,
    "other": _normalise_other,
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


def normalise_citation(citation: Citation) -> tuple[Citation, list[str]]:
    """Return a cleaned copy of `citation` plus human-readable warnings.

    Canonicalises report abbreviations and decides CaseSource.year_style, cleans
    case names per AGLC4 r 2.1, canonicalises jurisdictions, tidies author names,
    and sets `citation.source_key` via `source_key()`.
    """
    citation = citation.model_copy(deep=True)
    warnings: list[str] = []

    handler = _DISPATCH[citation.source.type]
    new_source, source_warnings = handler(citation.source)
    citation.source = new_source
    warnings.extend(source_warnings)

    citation.pinpoints = [_clean_pinpoint(p) for p in citation.pinpoints]
    if citation.pinpoint_judges:
        citation.pinpoint_judges = _strip_trailing_punct(citation.pinpoint_judges.strip()) or None
    if citation.short_title:
        citation.short_title = citation.short_title.strip() or None

    citation.source_key = source_key(citation.source)
    return citation, warnings


def source_key(source: Source) -> str:
    """Stable identity for a source so repeated citations of the same work are
    recognised (drives ibid and '(n x)'). Ignores pinpoints and is robust to
    trivial differences (case, whitespace, punctuation, quoting)."""

    if isinstance(source, CaseSource):
        if source.report:
            abbrev, _, matched = _canon_report(source.report)
            report_key = _norm_key(abbrev) if matched else _norm_key(source.report)
            if report_key and source.starting_page:
                vol_or_year = _norm_key(source.volume or source.year or "")
                return f"case:{report_key}:{vol_or_year}:{_norm_key(source.starting_page)}"
        if source.court_id and source.judgment_number:
            abbrev, matched = _canon_court(source.court_id)
            court_key = _norm_key(abbrev) if matched else _norm_key(source.court_id)
            return f"case:mnc:{_norm_key(source.year)}:{court_key}:{_norm_key(source.judgment_number)}"
        return f"case:name:{_case_name_key(source.name)}"

    if isinstance(source, LegislationSource):
        title = (source.title or "").strip()
        year = source.year.strip() if source.year else None
        if not year and title:
            m = re.match(r"^(.*\S)\s+(\d{4})$", title)
            if m:
                title = m.group(1).strip()
                year = m.group(2)
        title_key = _norm_key(title)
        year_key = _norm_key(year or "")
        if source.jurisdiction:
            abbrev, matched = _canon_jurisdiction(source.jurisdiction)
            juris_key = _norm_key(abbrev) if matched else _norm_key(source.jurisdiction)
        else:
            juris_key = ""
        return f"legislation:{title_key}:{year_key}:{juris_key}"

    if isinstance(source, TreatySource):
        return f"treaty:{_norm_key(source.title)}"

    if isinstance(source, OtherSource):
        return f"other:{_norm_key(source.text)}"

    if isinstance(source, BookChapterSource):
        authors = source.authors
        surname = _norm_key(_surname(authors[0])) if authors else ""
        return f"secondary:{surname}:{_norm_key(source.chapter_title)}"

    if isinstance(source, ReportSource):
        surname = _norm_key(_surname(source.author)) if source.author else ""
        return f"secondary:{surname}:{_norm_key(source.title)}"

    # JournalArticleSource, BookSource, NewspaperSource, WebsiteSource: `authors` + `title`
    authors = getattr(source, "authors", None) or []
    surname = _norm_key(_surname(authors[0])) if authors else ""
    title = getattr(source, "title", "") or ""
    return f"secondary:{surname}:{_norm_key(title)}"
