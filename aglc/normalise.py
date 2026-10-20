"""Normalisation: deterministic clean-up of extracted citations using lookup
tables in aglc/data/.

Implements AGLC4 (4th ed) rules:
  - r 2.1: case name clean-up (full stops, 'v', the Crown, '[No 2]')
  - r 2.2.1, 2.2.3: report series abbreviations and round/square year brackets
  - r 2.3: medium-neutral court identifiers
  - r 3.1.3: jurisdiction abbreviations, r 15.3/17-20.2.3 style Constitution handling
  - r 3.7, 7.5.1-7.5.4: explanatory memoranda, parliamentary debates (Hansard), submissions
    to inquiries, evidence to committees and the federal convention debates

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
    CommitteeEvidenceSource,
    ConventionDebatesSource,
    ExplanatoryMemorandumSource,
    JournalArticleSource,
    LegislationSource,
    NewspaperSource,
    OtherSource,
    ParliamentaryDebatesSource,
    Pinpoint,
    PinpointKind,
    ReportSource,
    ResearchPaperSource,
    Source,
    SubmissionSource,
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


_ET_AL = re.compile(r"(?i)[\s,]*\bet\.?\s+al\b\.?$")


def _authors_and_et_al(source) -> tuple[list[str], bool]:
    """r 4.1.2: the cleaned authors, and whether the footnote said 'et al'. The model may
    set `et_al`, or leave 'et al' on the last name ('David Hamer et al') or as a name of
    its own; either way it is kept, never dropped."""
    et_al = source.et_al
    authors = []
    for a in source.authors:
        trimmed = _ET_AL.sub("", a)
        et_al = et_al or trimmed != a
        authors.append(trimmed)
    return _clean_authors(authors), et_al


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

    if source.court_id and not source.report and not _canon_court(source.court_id)[1]:
        abbrev, _, is_report = _canon_report(source.court_id)
        if is_report:
            # '[1932] A.C. 562' read as a medium neutral citation: 'A.C.' is a report
            # series and '562' its starting page (r 2.2), not a court and judgment number.
            data["report"], data["court_id"] = source.court_id, None
            data["starting_page"], data["judgment_number"] = source.judgment_number, None
            source = source.model_copy(update={"report": source.court_id, "court_id": None})

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

    if not year and data["kind"] != "constitution":
        warnings.append("Legislation missing year")

    return LegislationSource(**data), warnings


def _normalise_journal_article(source: JournalArticleSource) -> tuple[JournalArticleSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["authors"], data["et_al"] = _authors_and_et_al(source)
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


_COMPANY_TERMS = re.compile(r"(?:,?\s+(?:Pty\.?|Ltd\.?|Limited|Co\.?|Company|Inc\.?|Incorporated|LLC|plc))+$", re.I)


def _clean_publisher(name: str) -> str:
    """r 6.3.1: 'Terms designating the publisher as a company (eg Pty, Ltd, Co, Inc)
    should be omitted' ('Lawbook' [Not: 'Lawbook Co' nor 'Lawbook Company'])."""
    return _COMPANY_TERMS.sub("", name).strip() or name


def _normalise_book(source: BookSource) -> tuple[BookSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["authors"], data["et_al"] = _authors_and_et_al(source)
    data["editors"] = _clean_authors(source.editors)
    data["title"] = (source.title or "").strip()
    for field in ("publisher", "edition", "year", "volume"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    if data.get("publisher"):
        data["publisher"] = _clean_publisher(data["publisher"])
    if not data["authors"] and not data["editors"]:
        warnings.append("Book missing author(s)/editor(s)")
    return BookSource(**data), warnings


def _normalise_book_chapter(source: BookChapterSource) -> tuple[BookChapterSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["authors"], data["et_al"] = _authors_and_et_al(source)
    data["editors"] = _clean_authors(source.editors)
    data["chapter_title"] = (source.chapter_title or "").strip()
    data["book_title"] = (source.book_title or "").strip()
    for field in ("publisher", "edition", "year", "starting_page"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    if data.get("publisher"):
        data["publisher"] = _clean_publisher(data["publisher"])
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
    m = re.match(r"^(.*\S)\s*[:—–-]\s*((?:Final|Interim|Annual|Draft)?\s*Report)$", data["title"], re.I)
    if m and (data.get("document_type") or "Report").lower() == "report" and not data.get("document_number"):
        # r 7.1.1: '*Review of the Law of Negligence* (Final Report, September 2002)'
        data["title"], data["document_type"] = m.group(1), m.group(2).strip()
    # A report need not have an author (r 7.1.1 example 1), so no warning for that.
    return ReportSource(**data), warnings


def _normalise_research_paper(source: ResearchPaperSource) -> tuple[ResearchPaperSource, list[str]]:
    data = source.model_dump()
    data["authors"] = _clean_authors(source.authors)
    data["title"] = (source.title or "").strip()
    for field in ("document_type", "document_number", "institution", "date"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    if source.url:
        data["url"] = source.url.strip()
    # A research paper may be authored by the body that publishes it (r 7.2.1), so no
    # warning for a missing author.
    return ResearchPaperSource(**data), []


def _split_title_year(title: str, year: str | None) -> tuple[str, str | None]:
    """'Native Title Act 1993' with no separate year -> ('Native Title Act', '1993')."""
    if not year and title:
        m = re.match(r"^(.*\S)\s+(\d{4})$", title)
        if m:
            return m.group(1).strip(), m.group(2)
    return title, year


def _normalise_explanatory_memorandum(
    source: ExplanatoryMemorandumSource,
) -> tuple[ExplanatoryMemorandumSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    title, year = _split_title_year(_clean_field(source.title) or "", _clean_field(source.year))
    data["title"], data["year"] = title, year
    data["document_type"] = _clean_field(source.document_type) or "Explanatory Memorandum"
    if data.get("jurisdiction"):
        abbrev, matched = _canon_jurisdiction(data["jurisdiction"])
        if matched:
            data["jurisdiction"] = abbrev
        else:
            warnings.append(f"Unknown jurisdiction: '{data['jurisdiction']}'")
    else:
        warnings.append("Explanatory memorandum missing the Bill's jurisdiction")
    return ExplanatoryMemorandumSource(**data), warnings


# r 7.5.1: Hansard names the jurisdiction in full ('Commonwealth', 'New South Wales').
_CHAMBERS = {
    _norm_key(variant): name
    for name, variants in {
        "Senate": [],
        "House of Representatives": ["HR", "HoR", "H of R", "Reps"],
        "Legislative Assembly": ["LA"],
        "Legislative Council": ["LC"],
        "House of Assembly": ["HA"],
        "House of Commons": ["HC"],
        "House of Lords": ["HL"],
    }.items()
    for variant in [name, *variants]
}
# r 7.5.1: 'MP', 'MLC', 'MLA', 'Senator' and other designations of membership of
# Parliament are left out of the speaker's name; r 7.5.4 (after r 4.1): so are titles
# such as 'the Hon', 'Mr' and 'Dr', but not 'Sir', 'Dame' or peerage titles.
_SPEAKER_PREFIX = re.compile(
    r"^(?:(?:the\s+)?(?:Hon(?:ourable)?|Senator|Mr|Mrs|Ms|Miss|Dr|Prof(?:essor)?)\.?\s+)+", re.I
)
_SPEAKER_SUFFIX = re.compile(r"(?:,?\s+(?:MP|MLA|MLC|MHR|MHA|QC|SC|KC))+$")


def _clean_speaker(name: str | None) -> str | None:
    """'Senator the Hon George Brandis QC' -> 'George Brandis' (r 7.5.1, 7.5.4)."""
    if not name:
        return name
    return _SPEAKER_SUFFIX.sub("", _SPEAKER_PREFIX.sub("", name)).strip() or name


def _clean_date(date: str | None) -> str | None:
    """'30th March 2022' -> '30 March 2022'."""
    return re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b", r"\1", date) if date else date


def _hansard_jurisdiction(name: str) -> str:
    abbrev, matched = _canon_jurisdiction(name)
    if not matched or (abbrev == "UK" and len(name.replace(".", "")) > 2):
        return name  # 'England', 'Scotland' etc stay as written (r 24.4.1)
    return _load_json("jurisdictions.json")[abbrev]["name"]


def _normalise_parliamentary_debates(
    source: ParliamentaryDebatesSource,
) -> tuple[ParliamentaryDebatesSource, list[str]]:
    warnings: list[str] = []
    data = {k: _clean_field(v) for k, v in source.model_dump().items() if k != "type"}
    if data["jurisdiction"]:
        data["jurisdiction"] = _hansard_jurisdiction(data["jurisdiction"])
    else:
        warnings.append("Parliamentary debates missing jurisdiction")
    if data["chamber"]:
        data["chamber"] = _CHAMBERS.get(_norm_key(data["chamber"]), data["chamber"])
    else:
        warnings.append("Parliamentary debates missing chamber")
    data["date"] = _clean_date(data["date"])
    data["speaker"] = _clean_speaker(data["speaker"])
    return ParliamentaryDebatesSource(**data), warnings


# r 7.5.2: an anonymous submission has no author, unless it's identified some other way
# ('Anonymous 489').
_ANONYMOUS = re.compile(r"(?:anonymous|name withheld|withheld|confidential)", re.I)
_ROYAL_COMMISSION = re.compile(r"^(?:the\s+)?royal commission\b", re.I)


def _normalise_submission(source: SubmissionSource) -> tuple[SubmissionSource, list[str]]:
    warnings: list[str] = []
    data = {k: _clean_field(v) for k, v in source.model_dump().items() if k != "type"}
    if data["author"] and _ANONYMOUS.fullmatch(data["author"]):
        data["author"] = None
    if data["submission_number"]:
        # 'Submission No. 119' / 'No 119' -> '119'
        data["submission_number"] = re.sub(r"^(?:submission\s*)?(?:no\b\.?\s*)?", "", data["submission_number"], flags=re.I) or None
    if data["body"]:
        data["body"] = re.sub(r"^to\s+", "", data["body"], flags=re.I)
    if data["inquiry"] and not data["body"] and _ROYAL_COMMISSION.match(data["inquiry"]):
        data["body"], data["inquiry"] = data["inquiry"], None
    if data["body"] and _ROYAL_COMMISSION.match(data["body"]):
        data["inquiry"] = None  # r 7.5.2: the royal commission is named once, as the body
    if not data["body"]:
        warnings.append("Submission missing the body it was made to")
    data["date"] = _clean_date(data["date"])
    return SubmissionSource(**data), warnings


def _normalise_committee_evidence(
    source: CommitteeEvidenceSource,
) -> tuple[CommitteeEvidenceSource, list[str]]:
    warnings: list[str] = []
    data = {k: _clean_field(v) for k, v in source.model_dump().items() if k != "type"}
    if data["committee"]:
        data["committee"] = re.sub(r"^evidence\s+to\s+", "", data["committee"], flags=re.I)
    else:
        warnings.append("Committee evidence missing the committee")
    data["date"] = _clean_date(data["date"])
    data["speaker"] = _clean_speaker(data["speaker"])
    return CommitteeEvidenceSource(**data), warnings


def _normalise_convention_debates(
    source: ConventionDebatesSource,
) -> tuple[ConventionDebatesSource, list[str]]:
    data = {k: _clean_field(v) for k, v in source.model_dump().items() if k != "type"}
    data["title"] = data["title"] or source.title
    data["date"] = _clean_date(data["date"])
    data["speaker"] = _clean_speaker(data["speaker"])
    return ConventionDebatesSource(**data), []


def _normalise_newspaper(source: NewspaperSource) -> tuple[NewspaperSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["authors"], data["et_al"] = _authors_and_et_al(source)
    data["title"] = (source.title or "").strip()
    data["newspaper"] = (source.newspaper or "").strip()
    for field in ("place", "date", "page"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    if source.url:
        data["url"] = source.url.strip()
    return NewspaperSource(**data), warnings


_BODY_WORDS = re.compile(
    r"\b(Court|Commission|Council|Department|Institute|Association|Society|Committee|Office|"
    r"Ministry|Agency|Authority|Tribunal|Parliament|Government|University|Bureau|Centre|Center|"
    r"Foundation|Organisation|Organization|Board|Service|Services|Library|Network|Nations)\b"
)


def _looks_like_body(name: str) -> bool:
    return bool(_BODY_WORDS.search(name))


def _normalise_website(source: WebsiteSource) -> tuple[WebsiteSource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["authors"], data["et_al"] = _authors_and_et_al(source)
    data["title"] = (source.title or "").strip()
    if data.get("website_name"):
        data["website_name"] = _clean_field(data["website_name"])
    if data.get("date"):
        data["date"] = _clean_field(data["date"])
    if source.url:
        data["url"] = source.url.strip()
    if not data.get("website_name") and len(data["authors"]) == 1 and _looks_like_body(data["authors"][0]):
        # A body that publishes its own site is cited as the website name, not the author
        # (r 7.15: "'James Edelman', *High Court of Australia* (Web Page) <...>").
        data["website_name"] = data["authors"][0]
        data["authors"] = []
    return WebsiteSource(**data), warnings


def _normalise_treaty(source: TreatySource) -> tuple[TreatySource, list[str]]:
    warnings: list[str] = []
    data = source.model_dump()
    data["title"] = (source.title or "").strip()
    data["parties"] = _clean_authors(source.parties)
    for field in ("opened_for_signature", "treaty_series", "entry_into_force"):
        if data.get(field):
            data[field] = _clean_field(data[field])
    if data.get("treaty_series"):
        # r 8.4: series abbreviations take no full stops ('999 U.N.T.S. 171' -> '999 UNTS 171')
        data["treaty_series"] = re.sub(
            r"\b(?:[A-Z]\.){2,}", lambda m: m.group(0).replace(".", ""), data["treaty_series"]
        )
    return TreatySource(**data), warnings


def _normalise_other(source: OtherSource) -> tuple[OtherSource, list[str]]:
    data = source.model_dump()
    text = source.text or ""
    data["text"] = text.strip()
    if source.rich is not None:
        lead = len(text) - len(text.lstrip())
        rich = source.rich.slice(lead, lead + len(data["text"]))
        data["rich"] = rich if rich.text == data["text"] else None
    return OtherSource(**data), []


_DISPATCH = {
    "case": _normalise_case,
    "legislation": _normalise_legislation,
    "journal_article": _normalise_journal_article,
    "book": _normalise_book,
    "book_chapter": _normalise_book_chapter,
    "report": _normalise_report,
    "research_paper": _normalise_research_paper,
    "parliamentary_debates": _normalise_parliamentary_debates,
    "submission": _normalise_submission,
    "committee_evidence": _normalise_committee_evidence,
    "convention_debates": _normalise_convention_debates,
    "explanatory_memorandum": _normalise_explanatory_memorandum,
    "newspaper": _normalise_newspaper,
    "website": _normalise_website,
    "treaty": _normalise_treaty,
    "other": _normalise_other,
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #


_SPOKEN = (ParliamentaryDebatesSource, CommitteeEvidenceSource, ConventionDebatesSource)
_COMMITTEE_PAGE_PREFIX = re.compile(r"^(?:[A-Z][A-Z&]+\s*|[A-Z]\s+)(?=\d)")


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
    src = citation.source
    if (
        isinstance(src, BookChapterSource)
        and not src.starting_page
        and len(citation.pinpoints) == 1
        and citation.pinpoints[0].kind == PinpointKind.page
        and "–" not in citation.pinpoints[0].value and "-" not in citation.pinpoints[0].value
    ):
        # A chapter must give its starting page (r 6.6.1); a lone page number in the
        # source ('..., 2008, p. 38') is almost always that, not a pinpoint.
        citation.source = src = src.model_copy(update={"starting_page": citation.pinpoints[0].value})
        citation.pinpoints = []
        warnings.append(f"Assumed page {src.starting_page} is the chapter's starting page")
    if isinstance(src, CaseSource) and src.court_id and not src.report:
        # r 2.3.1: a medium neutral citation has no pages, so pinpoints are paragraphs
        citation.pinpoints = [
            p.model_copy(update={"kind": PinpointKind.paragraph}) if p.kind == PinpointKind.page else p
            for p in citation.pinpoints
        ]
    if citation.pinpoint_judges:
        citation.pinpoint_judges = _strip_trailing_punct(citation.pinpoint_judges.strip()) or None
    if isinstance(src, _SPOKEN) and citation.pinpoint_judges and not src.speaker:
        # The speaker in brackets after a Hansard (or committee or convention) pinpoint read
        # as if it were a judge.
        if isinstance(src, ConventionDebatesSource):
            update = {"speaker": citation.pinpoint_judges}
        else:
            speaker, _, position = citation.pinpoint_judges.partition(",")
            update = {"speaker": speaker, "speaker_position": position or None}
        citation.source = src = _DISPATCH[src.type](src.model_copy(update=update))[0]
        citation.pinpoint_judges = None
    if isinstance(src, CommitteeEvidenceSource):
        # r 7.5.3 note: Committee Hansard page numbers carry the committee's abbreviation
        # ('SL&C 12'), which is left out of the pinpoint.
        citation.pinpoints = [
            p.model_copy(update={"value": _COMMITTEE_PAGE_PREFIX.sub("", p.value)}) if p.kind == PinpointKind.page else p
            for p in citation.pinpoints
        ]
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

    if isinstance(source, ParliamentaryDebatesSource):
        # One day's debates in one chamber; a different speaker is cited afresh so that a
        # short reference never drops who said it.
        juris = _hansard_jurisdiction(_clean_field(source.jurisdiction) or "")
        chamber = _CHAMBERS.get(_norm_key(source.chamber), source.chamber or "")
        speaker = _normalise_parliamentary_debates(source)[0].speaker
        return f"hansard:{_norm_key(juris)}:{_norm_key(chamber)}:{_norm_key(source.date)}:{_norm_key(speaker)}"

    if isinstance(source, SubmissionSource):
        sub = _normalise_submission(source)[0]
        parts = (sub.author, sub.submission_number, sub.body, sub.legislature, sub.inquiry, sub.date)
        return "submission:" + ":".join(_norm_key(p) for p in parts)

    if isinstance(source, CommitteeEvidenceSource):
        # One witness at one hearing, as for Hansard.
        ev = _normalise_committee_evidence(source)[0]
        parts = (ev.committee, ev.legislature, ev.date, ev.speaker)
        return "evidence:" + ":".join(_norm_key(p) for p in parts)

    if isinstance(source, ConventionDebatesSource):
        cd = _normalise_convention_debates(source)[0]
        parts = (cd.title, cd.location, cd.date, cd.speaker)
        return "convention:" + ":".join(_norm_key(p) for p in parts)

    if isinstance(source, ExplanatoryMemorandumSource):
        title, year = _split_title_year((source.title or "").strip(), source.year)
        juris = _canon_jurisdiction(source.jurisdiction or "")[0] or source.jurisdiction
        return f"em:{_norm_key(source.document_type)}:{_norm_key(title)}:{_norm_key(year)}:{_norm_key(juris)}"

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
