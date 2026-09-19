"""Core data model shared by every stage of the pipeline.

The pipeline is:  docx -> Footnote(raw runs) -> extraction (LLM) -> Citation/Source
-> normalisation -> document pass (ibid / n x / short titles) -> RichText -> docx.

Nothing in this module talks to an LLM or to Word; it is pure data.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Rich text: the output of every formatter. AGLC needs italics (case names,
# legislation titles, book and journal-less titles) so plain str is not enough.
# --------------------------------------------------------------------------- #


class Run(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    italic: bool = False


class RichText(BaseModel):
    runs: list[Run] = Field(default_factory=list)

    # -- construction helpers ------------------------------------------------ #
    @classmethod
    def plain(cls, text: str) -> "RichText":
        return cls(runs=[Run(text=text)] if text else [])

    @classmethod
    def italic(cls, text: str) -> "RichText":
        return cls(runs=[Run(text=text, italic=True)] if text else [])

    def append(self, text: str, italic: bool = False) -> "RichText":
        """Append text in place (merging with the previous run when styles match)."""
        if not text:
            return self
        if self.runs and self.runs[-1].italic == italic:
            last = self.runs.pop()
            self.runs.append(Run(text=last.text + text, italic=italic))
        else:
            self.runs.append(Run(text=text, italic=italic))
        return self

    def extend(self, other: "RichText") -> "RichText":
        for r in other.runs:
            self.append(r.text, r.italic)
        return self

    def __add__(self, other: "RichText") -> "RichText":
        return RichText().extend(self).extend(other)

    # -- inspection ---------------------------------------------------------- #
    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    def to_markup(self) -> str:
        """Render with *asterisks* around italic runs. Used by tests and the CLI."""
        return "".join(f"*{r.text}*" if r.italic else r.text for r in self.runs)

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.to_markup()


# --------------------------------------------------------------------------- #
# Pinpoints (AGLC4 r 1.1.6, 2.5, 3.1.4)
# --------------------------------------------------------------------------- #


class PinpointKind(str, Enum):
    page = "page"            # 42        -> "42"
    paragraph = "paragraph"  # [42]      -> "[42]"
    section = "section"      # s 5       -> "s 5"   (ss for plural)
    part = "part"            # pt 2
    division = "division"    # div 3
    schedule = "schedule"    # sch 1
    regulation = "regulation"  # reg 4
    rule = "rule"            # r 4
    clause = "clause"        # cl 3
    article = "article"      # art 5
    chapter = "chapter"      # ch 4
    footnote = "footnote"    # 42 n 7
    other = "other"          # verbatim; value is emitted exactly as given


class Pinpoint(BaseModel):
    kind: PinpointKind = PinpointKind.page
    value: str = Field(description="The number/range only, eg '42', '42-4', '5(1)(a)', '12]-[15'")
    plural: bool = Field(default=False, description="True for ranges/lists of sections etc (ss, pts)")


# --------------------------------------------------------------------------- #
# Sources. One model per AGLC4 source type, discriminated on `type`.
# All fields are optional-ish because extraction can be incomplete; the
# formatter emits `[MISSING: field]` markers rather than inventing data.
# --------------------------------------------------------------------------- #


class _SourceBase(BaseModel):
    model_config = ConfigDict(extra="ignore")


class CaseSource(_SourceBase):
    """AGLC4 ch 2. Reported, medium-neutral, or unreported cases."""

    type: Literal["case"] = "case"
    name: str = Field(description="Case name as it should appear, eg 'Mabo v Queensland [No 2]'")
    year: str | None = None
    year_style: Literal["round", "square"] | None = Field(
        default=None,
        description="Round () when report volumes are numbered independently of year; "
        "square [] when the year identifies the volume. Normaliser fills this in.",
    )
    volume: str | None = None
    report: str | None = Field(default=None, description="Report series abbreviation, eg 'CLR', 'NSWLR'")
    starting_page: str | None = None
    # Medium neutral citation (r 2.3): [2010] HCA 1
    court_id: str | None = Field(default=None, description="Unique court identifier, eg 'HCA', 'NSWCA'")
    judgment_number: str | None = None
    # Unreported without MNC (r 2.3.2): (Supreme Court of Victoria, Smith J, 1 June 1990)
    court_name: str | None = None
    judges: str | None = None
    date: str | None = Field(default=None, description="Full decision date, eg '1 June 1990'")


class LegislationSource(_SourceBase):
    """AGLC4 ch 3. Acts, delegated legislation, bills, constitutions."""

    type: Literal["legislation"] = "legislation"
    kind: Literal["act", "delegated", "bill", "constitution"] = "act"
    title: str = Field(description="Short title without year, eg 'Competition and Consumer Act'")
    year: str | None = None
    jurisdiction: str | None = Field(default=None, description="AGLC abbreviation: Cth, NSW, Vic, Qld, WA, SA, Tas, ACT, NT")


class JournalArticleSource(_SourceBase):
    """AGLC4 r 5.1-5.10."""

    type: Literal["journal_article"] = "journal_article"
    authors: list[str] = Field(default_factory=list)
    title: str
    year: str | None = None
    volume: str | None = None
    issue: str | None = None
    journal: str | None = Field(default=None, description="Full journal name (AGLC does not abbreviate)")
    starting_page: str | None = None
    forthcoming: bool = False


class BookSource(_SourceBase):
    """AGLC4 r 6.1-6.5."""

    type: Literal["book"] = "book"
    authors: list[str] = Field(default_factory=list)
    editors: list[str] = Field(default_factory=list, description="Only when the book itself is edited (no authors)")
    title: str
    publisher: str | None = None
    edition: str | None = Field(default=None, description="Edition number only, eg '5' -> '5th ed'")
    year: str | None = None
    volume: str | None = None


class BookChapterSource(_SourceBase):
    """AGLC4 r 6.6."""

    type: Literal["book_chapter"] = "book_chapter"
    authors: list[str] = Field(default_factory=list)
    chapter_title: str
    editors: list[str] = Field(default_factory=list)
    book_title: str
    publisher: str | None = None
    edition: str | None = None
    year: str | None = None
    starting_page: str | None = None


class ReportSource(_SourceBase):
    """AGLC4 r 7.1 (reports, government documents, law reform commission reports)."""

    type: Literal["report"] = "report"
    author: str | None = Field(default=None, description="Person or body, eg 'Australian Law Reform Commission'")
    title: str
    document_type: str | None = Field(default=None, description="eg 'Report', 'Discussion Paper'")
    document_number: str | None = None
    date: str | None = Field(default=None, description="Month Year, or Year, as given")


class NewspaperSource(_SourceBase):
    """AGLC4 r 7.10."""

    type: Literal["newspaper"] = "newspaper"
    authors: list[str] = Field(default_factory=list)
    title: str
    newspaper: str
    place: str | None = None
    date: str | None = Field(default=None, description="Full date, eg '14 March 2018'")
    page: str | None = None
    url: str | None = None


class WebsiteSource(_SourceBase):
    """AGLC4 r 7.15 (internet materials)."""

    type: Literal["website"] = "website"
    authors: list[str] = Field(default_factory=list, description="Person or organisation author, if any")
    title: str
    website_name: str | None = None
    date: str | None = Field(default=None, description="Full date of publication/last update, if any")
    url: str | None = None


class TreatySource(_SourceBase):
    """AGLC4 r 8.1-8.2."""

    type: Literal["treaty"] = "treaty"
    title: str
    parties: list[str] = Field(default_factory=list, description="Only for bilateral treaties")
    opened_for_signature: str | None = Field(default=None, description="Full date, or signed date for bilateral")
    signed: bool = Field(default=False, description="True -> 'signed <date>' rather than 'opened for signature <date>'")
    treaty_series: str | None = Field(default=None, description="eg '1155 UNTS 331'")
    entry_into_force: str | None = Field(default=None, description="Full date, or 'not yet in force'")


class OtherSource(_SourceBase):
    """Anything the extractor cannot classify. Emitted verbatim and flagged for review."""

    type: Literal["other"] = "other"
    text: str


Source = Annotated[
    Union[
        CaseSource,
        LegislationSource,
        JournalArticleSource,
        BookSource,
        BookChapterSource,
        ReportSource,
        NewspaperSource,
        WebsiteSource,
        TreatySource,
        OtherSource,
    ],
    Field(discriminator="type"),
]

SOURCE_TYPES = [
    CaseSource, LegislationSource, JournalArticleSource, BookSource, BookChapterSource,
    ReportSource, NewspaperSource, WebsiteSource, TreatySource, OtherSource,
]


# --------------------------------------------------------------------------- #
# A single citation occurrence inside a footnote.
# --------------------------------------------------------------------------- #

Signal = Literal["See", "See also", "See especially", "See generally", "Cf", "But see", "Contra", "See, eg,", "Eg,"]


class Citation(BaseModel):
    source: Source
    pinpoints: list[Pinpoint] = Field(default_factory=list)
    pinpoint_judges: str | None = Field(default=None, description="eg 'Mason CJ' -> rendered '(Mason CJ)' after pinpoint")
    signal: Signal | None = None
    short_title: str | None = Field(default=None, description="Author-defined short title, eg 'Mabo'")
    source_key: str | None = Field(
        default=None,
        description="Identity of the underlying source across the document; set by normalise.source_key()",
    )


class TextSegment(BaseModel):
    kind: Literal["text"] = "text"
    text: RichText


class CitationSegment(BaseModel):
    kind: Literal["citation"] = "citation"
    citation: Citation
    original: str = Field(default="", description="The text as it appeared in the input, for the change report")


Segment = Annotated[Union[TextSegment, CitationSegment], Field(discriminator="kind")]


class Footnote(BaseModel):
    number: int
    original: RichText = Field(description="Footnote text as read from the document")
    segments: list[Segment] = Field(default_factory=list, description="Filled by extraction")


# --------------------------------------------------------------------------- #
# Output / reporting
# --------------------------------------------------------------------------- #


class Warning_(BaseModel):
    footnote: int | None = None
    message: str


class FootnoteResult(BaseModel):
    number: int
    original: RichText
    formatted: RichText

    @property
    def changed(self) -> bool:
        return self.original.to_markup() != self.formatted.to_markup()


class BibliographySection(BaseModel):
    heading: str  # eg "A Articles/Books/Reports"
    entries: list[RichText]


class ProcessResult(BaseModel):
    footnotes: list[FootnoteResult]
    bibliography: list[BibliographySection] = Field(default_factory=list)
    warnings: list[Warning_] = Field(default_factory=list)
