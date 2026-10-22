"""Core data model shared by every stage of the pipeline.

The pipeline is:  docx -> Footnote(raw runs) -> extraction (LLM) -> Citation/Source
-> normalisation -> document pass (ibid / n x / short titles) -> RichText -> docx.

Nothing in this module talks to an LLM or to Word; it is pure data.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema


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

    def visible(self) -> "RichText":
        """A copy reduced to what a reader can see, for deciding whether a footnote changed:
        no leading or trailing whitespace, and whitespace never italic (an italic space looks
        the same as a roman one)."""
        out = RichText()
        for run in self.runs:
            for part in re.findall(r"\s+|\S+", run.text):
                out.append(part, run.italic and not part.isspace())
        text = out.text
        lead, trail = len(text) - len(text.lstrip()), len(text) - len(text.rstrip())
        return out.slice(lead, len(text) - trail)

    def slice(self, start: int, end: int) -> "RichText":
        """Characters [start, end) of the text, keeping their italics."""
        out, pos = RichText(), 0
        for run in self.runs:
            lo, hi = max(start, pos), min(end, pos + len(run.text))
            if lo < hi:
                out.append(run.text[lo - pos : hi - pos], run.italic)
            pos += len(run.text)
        return out

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
    annex = "annex"          # annex II (treaties, r 8.7)
    volume = "volume"        # vol 1  (followed by ", " before a page: 'vol 1, 339 [7.7]')
    book = "book"            # bk 2
    footnote = "footnote"    # 42 n 7
    column = "column"        # col 778 (UK parliamentary debates, r 24.4.1)
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
    et_al: bool = Field(default=False, description="The authors are followed by 'et al' in the footnote (r 4.1.2)")
    authors_are_bodies: bool | None = Field(
        default=None,
        description="True if the authors are bodies (organisations, governments, committees), false if "
        "people; leave out if mixed or unsure. Decides whether repeat references shorten them to surnames",
    )
    title: str
    #: `title` with the italics it had in the footnote, for a case or Act name inside the
    #: quoted title. Filled in by extraction, never by the model.
    title_rich: SkipJsonSchema[RichText | None] = None
    part: str | None = Field(default=None, description="Article published in parts (r 5.8): '1' -> '(Pt 1)'")
    year: str | None = None
    year_style: Literal["round", "square"] | None = Field(
        default=None,
        description="Round when the journal has volume numbers; square when organised by year "
        "(r 5.3), eg '[1995] (Spring) Public Law 57'. Default: round if volume present, else square.",
    )
    volume: str | None = None
    issue: str | None = Field(default=None, description="Issue number or name, eg '3', '1–2', 'Spring'")
    journal: str | None = Field(default=None, description="Full journal name (AGLC does not abbreviate)")
    starting_page: str | None = Field(
        default=None, description="Starting page, or article number with page range for online journals (r 5.10), eg '416:1–19'"
    )
    forthcoming: bool = Field(default=False, description="'(forthcoming)' replaces the starting page (r 5.11)")
    advance: bool = Field(default=False, description="'(advance)' replaces the starting page (r 5.11)")


class BookSource(_SourceBase):
    """AGLC4 r 6.1-6.5."""

    type: Literal["book"] = "book"
    authors: list[str] = Field(default_factory=list)
    et_al: bool = Field(default=False, description="The authors are followed by 'et al' in the footnote (r 4.1.2)")
    authors_are_bodies: bool | None = Field(
        default=None,
        description="True if the authors are bodies (organisations, governments, committees), false if "
        "people; leave out if mixed or unsure. Decides whether repeat references shorten them to surnames",
    )
    editors: list[str] = Field(default_factory=list, description="Only when the book itself is edited (no authors)")
    title: str
    translators: list[str] = Field(default_factory=list, description="r 6.7: ', tr Joan Riviere'")
    publisher: str | None = None
    edition: str | None = Field(default=None, description="Edition number, eg '5' -> '5th ed'; '3 rev' -> '3rd rev ed'; 'rev' -> 'rev ed'")
    year: str | None = Field(default=None, description="Year, span ('1984–88', '1975–') or 'forthcoming'")
    volume: str | None = None


class BookChapterSource(_SourceBase):
    """AGLC4 r 6.6."""

    type: Literal["book_chapter"] = "book_chapter"
    authors: list[str] = Field(default_factory=list)
    et_al: bool = Field(default=False, description="The authors are followed by 'et al' in the footnote (r 4.1.2)")
    authors_are_bodies: bool | None = Field(
        default=None,
        description="True if the authors are bodies (organisations, governments, committees), false if "
        "people; leave out if mixed or unsure. Decides whether repeat references shorten them to surnames",
    )
    chapter_title: str
    #: `chapter_title` with the italics it had in the footnote, for a case or Act name inside the
    #: quoted title. Filled in by extraction, never by the model.
    chapter_title_rich: SkipJsonSchema[RichText | None] = None
    translators: list[str] = Field(default_factory=list, description="Translators of the chapter (r 6.7)")
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
    author_is_body: bool | None = Field(
        default=None,
        description="True if the author is a body (organisation, company, government, committee, code name), "
        "false if a person; decides whether repeat references shorten it to a surname",
    )
    title: str
    document_type: str | None = Field(default=None, description="eg 'Report', 'Discussion Paper'")
    document_number: str | None = None
    date: str | None = Field(default=None, description="Month Year, or Year, as given")


class ResearchPaperSource(_SourceBase):
    """AGLC4 r 7.2: research papers, working papers, parliamentary research papers, notes
    and briefs (r 7.2.3), conference papers and theses. The title is quoted, not italic."""

    type: Literal["research_paper"] = "research_paper"
    authors: list[str] = Field(default_factory=list)
    authors_are_bodies: bool | None = Field(
        default=None,
        description="True if the authors are bodies (organisations, governments, committees), false if "
        "people; leave out if mixed or unsure. Decides whether repeat references shorten them to surnames",
    )
    title: str
    document_type: str | None = Field(
        default=None, description="As it appears on the source, eg 'Research Paper', 'Working Paper', 'Research Note', 'e-brief'"
    )
    document_number: str | None = Field(default=None, description="As it appears, eg '8', '9/2017', '1/2014'")
    institution: str | None = Field(
        default=None,
        description="Most specific body then umbrella body, eg 'Parliamentary Library, Parliament of Australia', "
        "'NSW Parliamentary Research Service, Parliament of New South Wales'",
    )
    date: str | None = Field(default=None, description="Full date, or as much of it as appears, eg 'December 2017'")
    url: str | None = None


class ParliamentaryDebatesSource(_SourceBase):
    """AGLC4 r 7.5.1 (and r 24.4.1 for the UK): parliamentary debates ('Hansard'),
    including second reading speeches (r 3.7 note). Pinpoints are pages (UK: vol and col)."""

    type: Literal["parliamentary_debates"] = "parliamentary_debates"
    jurisdiction: str | None = Field(
        default=None, description="As written, eg 'Commonwealth', 'New South Wales', 'NSW', 'United Kingdom'"
    )
    chamber: str | None = Field(
        default=None, description="eg 'Senate', 'House of Representatives', 'Legislative Assembly', 'Legislative Council'"
    )
    date: str | None = Field(default=None, description="Full date of the debate, eg '30 March 2022'")
    speaker: str | None = Field(default=None, description="Name of the speaker as written, eg 'Mark Speakman'")
    speaker_position: str | None = Field(
        default=None, description="Anything after the speaker's name in the brackets, eg 'Attorney-General'"
    )


class SubmissionSource(_SourceBase):
    """AGLC4 r 7.5.2: written submissions to government and parliamentary inquiries,
    committees and agencies (including royal commissions)."""

    type: Literal["submission"] = "submission"
    author: str | None = Field(
        default=None, description="Person or body that made the submission; none if anonymous (a code name counts)"
    )
    author_is_body: bool | None = Field(
        default=None,
        description="True if the author is a body (organisation, company, government, committee, code name), "
        "false if a person; decides whether repeat references shorten it to a surname",
    )
    submission_number: str | None = Field(default=None, description="Only if the body allocated one, eg '119'")
    body: str | None = Field(
        default=None,
        description="Committee, agency or royal commission it was made to, eg 'Senate Standing Committees on Economics', "
        "'Australian Competition and Consumer Commission', 'Royal Commission into Family Violence'",
    )
    legislature: str | None = Field(
        default=None, description="For a parliamentary committee, eg 'Parliament of Australia', 'Parliament of Victoria'"
    )
    inquiry: str | None = Field(
        default=None, description="Name of the inquiry, eg 'Inquiry into Drug Law Reform'; none for a royal commission"
    )
    date: str | None = Field(default=None, description="Full date, or as much of it as appears")


class CommitteeEvidenceSource(_SourceBase):
    """AGLC4 r 7.5.3: evidence given at a parliamentary committee hearing (Committee
    Hansard). Pinpoints are pages."""

    type: Literal["committee_evidence"] = "committee_evidence"
    committee: str | None = Field(default=None, description="eg 'House Standing Committee on Tax and Revenue'")
    legislature: str | None = Field(default=None, description="eg 'Parliament of Australia'")
    location: str | None = Field(default=None, description="Where the hearing was held, eg 'Canberra'")
    date: str | None = Field(default=None, description="Full date of the hearing, eg '30 November 2016'")
    speaker: str | None = Field(default=None, description="Name of the person giving evidence as written")
    speaker_position: str | None = Field(
        default=None, description="Anything after the speaker's name in the brackets, eg 'Air Chief Marshal'"
    )


class ConventionDebatesSource(_SourceBase):
    """AGLC4 r 7.5.4: debates of the Australasian federal conventions (1890s). Pinpoints
    are pages."""

    type: Literal["convention_debates"] = "convention_debates"
    title: str = Field(description="eg 'Official Record of the Debates of the Australasian Federal Convention'")
    location: str | None = Field(default=None, description="eg 'Sydney', 'Adelaide', 'Melbourne'")
    date: str | None = Field(default=None, description="Full date of the debate, eg '2 September 1897'")
    speaker: str | None = Field(default=None, description="Name of the speaker as written, eg 'Sir John Downer'")


class ExplanatoryMemorandumSource(_SourceBase):
    """AGLC4 r 3.7: explanatory memoranda, statements and notes to a Bill."""

    type: Literal["explanatory_memorandum"] = "explanatory_memorandum"
    document_type: str = Field(
        default="Explanatory Memorandum",
        description="'Explanatory Memorandum', 'Revised Explanatory Memorandum', 'Explanatory Statement', 'Explanatory Notes'...",
    )
    title: str = Field(description="Title of the Bill without its year, eg 'Charter of Human Rights and Responsibilities Bill'")
    year: str | None = None
    jurisdiction: str | None = Field(default=None, description="AGLC abbreviation: Cth, NSW, Vic, Qld, WA, SA, Tas, ACT, NT")


class NewspaperSource(_SourceBase):
    """AGLC4 r 7.11."""

    type: Literal["newspaper"] = "newspaper"
    authors: list[str] = Field(default_factory=list)
    et_al: bool = Field(default=False, description="The authors are followed by 'et al' in the footnote (r 4.1.2)")
    authors_are_bodies: bool | None = Field(
        default=None,
        description="True if the authors are bodies (organisations, governments, committees), false if "
        "people; leave out if mixed or unsure. Decides whether repeat references shorten them to surnames",
    )
    title: str
    #: `title` with the italics it had in the footnote, for a case or Act name inside the
    #: quoted title. Filled in by extraction, never by the model.
    title_rich: SkipJsonSchema[RichText | None] = None
    newspaper: str
    section: str | None = Field(default=None, description="Section/supplement, eg 'Epicure' -> '*Epicure*, *The Age*'")
    periodical: bool = Field(
        default=False,
        description="r 7.11.3 periodicals/magazines: \"'Title' (27 March 2017) *The New Yorker* 66\"",
    )
    place: str | None = Field(default=None, description="Place of publication; omitted and replaced by 'online' when url is set and no page")
    date: str | None = Field(default=None, description="Full date, eg '14 March 2018'")
    page: str | None = None
    url: str | None = None
    archived_url: str | None = Field(default=None, description="r 4.5: ', archived at <url>'")


class WebsiteSource(_SourceBase):
    """AGLC4 r 7.15 (internet materials)."""

    type: Literal["website"] = "website"
    authors: list[str] = Field(default_factory=list, description="Person or organisation author, if any")
    et_al: bool = Field(default=False, description="The authors are followed by 'et al' in the footnote (r 4.1.2)")
    authors_are_bodies: bool | None = Field(
        default=None,
        description="True if the authors are bodies (organisations, governments, committees), false if "
        "people; leave out if mixed or unsure. Decides whether repeat references shorten them to surnames",
    )
    title: str
    #: `title` with the italics it had in the footnote, for a case or Act name inside the
    #: quoted title. Filled in by extraction, never by the model.
    title_rich: SkipJsonSchema[RichText | None] = None
    website_name: str | None = None
    document_type: str | None = Field(default="Web Page", description="r 7.15: 'Web Page', 'Blog Post', 'Forum Post', 'Podcast'...")
    date: str | None = Field(default=None, description="Full date of publication/last update, if any")
    url: str | None = None
    archived_url: str | None = Field(default=None, description="r 4.5: ', archived at <url>'")


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
    #: `text` with the italics it had in the footnote (eg *Parliamentary Debates*), so that
    #: emitting it verbatim doesn't strip them. Filled in by extraction, never by the model.
    rich: SkipJsonSchema[RichText | None] = None


Source = Annotated[
    Union[
        CaseSource,
        LegislationSource,
        JournalArticleSource,
        BookSource,
        BookChapterSource,
        ReportSource,
        ResearchPaperSource,
        ParliamentaryDebatesSource,
        SubmissionSource,
        CommitteeEvidenceSource,
        ConventionDebatesSource,
        ExplanatoryMemorandumSource,
        NewspaperSource,
        WebsiteSource,
        TreatySource,
        OtherSource,
    ],
    Field(discriminator="type"),
]

SOURCE_TYPES = [
    CaseSource, LegislationSource, JournalArticleSource, BookSource, BookChapterSource,
    ReportSource, ResearchPaperSource, ParliamentaryDebatesSource, SubmissionSource, CommitteeEvidenceSource,
    ConventionDebatesSource, ExplanatoryMemorandumSource,
    NewspaperSource, WebsiteSource, TreatySource, OtherSource,
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


#: Why a footnote was left exactly as written because extraction *failed*:
#: "provider_error": the AI model gave no usable answer, even asked on its own;
#: "not_returned": it answered, but never for this footnote.
#: A footnote the tool deliberately left alone for review (it couldn't account for every
#: word, or couldn't resolve a reference) is not a failure and has no reason set.
ExtractionFailure = Literal["provider_error", "not_returned"]


class Footnote(BaseModel):
    number: int
    original: RichText = Field(description="Footnote text as read from the document")
    segments: list[Segment] = Field(default_factory=list, description="Filled by extraction")
    extraction_failed: ExtractionFailure | None = Field(
        default=None, description="Set when extraction failed and the footnote was left unchanged"
    )


# --------------------------------------------------------------------------- #
# Output / reporting
# --------------------------------------------------------------------------- #


class Warning_(BaseModel):
    footnote: int | None = None
    message: str


class Change(BaseModel):
    """One kind of change made to a footnote, in plain words (see aglc/explain.py)."""
    kind: str = Field(description="eg 'act_year_italic', 'pinpoint_comma', 'span', 'ibid'")
    text: str = Field(description="eg 'The year is part of an Act’s title, so it’s italic too'")
    rule: str | None = Field(default=None, description="The AGLC4 rule, eg 'r 3.1.2' or 'ch 5'")


class FootnoteResult(BaseModel):
    number: int
    original: RichText
    formatted: RichText
    #: see ExtractionFailure: set when this footnote is unchanged because extraction failed
    extraction_failed: ExtractionFailure | None = None
    #: what changed and why, one entry per kind of change (empty when unchanged)
    changes: list[Change] = Field(default_factory=list)

    @property
    def changed(self) -> bool:
        """A change the student can see: a trailing space, or a space that is italic in one and
        roman in the other, doesn't count (and so isn't written to the document either)."""
        return self.original.visible().to_markup() != self.formatted.visible().to_markup()


class BodyFix(BaseModel):
    """A change made to the body text rather than a footnote (see aglc/body.py), or,
    when `applied` is False, a problem spotted there that needs the author's judgement."""

    footnote: int | None = None
    message: str
    applied: bool = True


class BibliographySection(BaseModel):
    heading: str  # eg "A Articles/Books/Reports"
    entries: list[RichText]


class Extraction(BaseModel):
    """What the LLM stage produced, before normalising: kept so that the footnotes it failed
    to read can be extracted again without paying for the rest twice."""

    footnotes: list[Footnote]
    warnings: list[str] = Field(default_factory=list)
    #: the provider failed several requests in a row (it looks down), so asking it again
    #: straight away is pointless; the student can re-run later instead
    provider_down: bool = False


class ProcessResult(BaseModel):
    footnotes: list[FootnoteResult]
    bibliography: list[BibliographySection] = Field(default_factory=list)
    warnings: list[Warning_] = Field(default_factory=list)
    body_fixes: list[BodyFix] = Field(default_factory=list)
    extraction: Extraction | None = Field(default=None, exclude=True)

    @property
    def failed_footnotes(self) -> list[int]:
        """Footnotes left unchanged because extraction failed (not deliberately)."""
        return [f.number for f in self.footnotes if f.extraction_failed]
