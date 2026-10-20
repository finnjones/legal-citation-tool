"""Parliamentary materials: debates ('Hansard', AGLC4 r 7.5.1 and r 24.4.1), written
submissions to inquiries (r 7.5.2), evidence to parliamentary committees (r 7.5.3),
the Australasian federal convention debates (r 7.5.4) and explanatory memoranda,
statements and notes (r 3.7).

Committee reports (r 7.1.2) are ordinary reports with the committee as author
('Committee, Legislature'), and parliamentary research papers (r 7.2.3) are research
papers; both live in `secondary.py`.
"""

from __future__ import annotations

from ..models import (
    Citation,
    CommitteeEvidenceSource,
    ConventionDebatesSource,
    ExplanatoryMemorandumSource,
    ParliamentaryDebatesSource,
    RichText,
    SubmissionSource,
)
from .base import BIB_LEGISLATION, BIB_OTHER, Formatter, missing, register


def _speaker(name: str | None, position: str | None = None) -> str:
    """' (Name of Speaker, Position)', or nothing without a speaker."""
    if not name:
        return ""
    return f" ({name}, {position})" if position else f" ({name})"


@register
class ParliamentaryDebatesFormatter(Formatter):
    """r 7.5.1: Jurisdiction, *Parliamentary Debates*, Chamber, Full Date of Debate,
    Pinpoint (Name of Speaker, Position). Second reading speeches are cited the same way
    (r 3.7 note).

    There is no author or title to shorten, so a repeat reference uses the author's own
    short title ('*Parliamentary Debates* (n 5) 8939'), and without one the citation is
    repeated in full. The speaker is part of the source's identity (see
    `normalise.source_key`), so a short reference never hides a change of speaker."""

    source_type = "parliamentary_debates"
    italic_short_title = True  # the short title usually abbreviates *Parliamentary Debates*
    defines_short_title = True
    bibliography_category = BIB_OTHER

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, ParliamentaryDebatesSource)
        out = RichText()
        out.append(f"{src.jurisdiction or missing('jurisdiction')}, ")
        out.append("Parliamentary Debates", italic=True)
        out.append(f", {src.chamber or missing('chamber')}, {src.date or missing('date')}")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f", {pin}")
        out.append(_speaker(src.speaker, src.speaker_position))
        return out


@register
class SubmissionFormatter(Formatter):
    """r 7.5.2: Author, Submission No Number to Body, *Name of Inquiry* (Full Date)
    Pinpoint, where a parliamentary body is 'Committee, Legislature'. No author when the
    submission is anonymous, no number when none was allocated, no inquiry for a royal
    commission (or when the submission doesn't name one), and no date when the source
    has none (r 7.5.2 example 53).

    Repeat references use the author's name (r 1.4.1): 'Mobil Oil Australia (n 50) 7'.
    The name is kept whole, here and in the bibliography: most submissions are made by
    bodies, which no word list reliably tells apart from people ('Ambulance Victoria'
    would become 'Victoria', 'Anonymous 489' would become '489'), and a full name is only
    longer where a wrong surname hides who wrote it. An anonymous submission has nothing
    to shorten, so it uses the author's own short title, else is repeated in full."""

    source_type = "submission"
    italic_short_title = False
    defines_short_title = False
    bibliography_category = BIB_OTHER

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, SubmissionSource)
        out = RichText()
        if src.author:
            out.append(f"{src.author}, ")
        number = f" No {src.submission_number}" if src.submission_number else ""
        out.append(f"Submission{number} to {src.body or missing('body')}")
        if src.legislature:
            out.append(f", {src.legislature}")
        if src.inquiry:
            out.append(", ")
            out.append(src.inquiry, italic=True)
        if src.date:
            out.append(f" ({src.date})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f" {pin}")
        return out

    def short_title(self, citation: Citation) -> str:
        src = citation.source
        assert isinstance(src, SubmissionSource)
        # A short title the author introduced is used, as for any body (r 1.4.1, 1.4.4).
        return citation.short_title or src.author or ""

    def disambiguation_title(self, citation: Citation) -> RichText:
        """Two submissions by one author: 'Law Council of Australia, *Inquiry into X* (n 4)'."""
        src = citation.source
        assert isinstance(src, SubmissionSource)
        if src.inquiry:
            return RichText.italic(src.inquiry)
        return RichText.plain(src.body or "")


@register
class CommitteeEvidenceFormatter(Formatter):
    """r 7.5.3: Evidence to Committee, Legislature, Location, Full Date, Pinpoint (Name
    of Speaker, Position). Like Hansard, there is no author or title to shorten: a repeat
    reference uses the author's own short title, else the citation is repeated in full,
    and a different witness at the same hearing is a new citation (`normalise.source_key`)."""

    source_type = "committee_evidence"
    italic_short_title = False
    defines_short_title = True
    bibliography_category = BIB_OTHER

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, CommitteeEvidenceSource)
        out = RichText.plain(
            f"Evidence to {src.committee or missing('committee')}, {src.legislature or missing('legislature')}, "
            f"{src.location or missing('location')}, {src.date or missing('date')}"
        )
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f", {pin}")
        out.append(_speaker(src.speaker, src.speaker_position))
        return out


@register
class ConventionDebatesFormatter(Formatter):
    """r 7.5.4: *Title*, Location, Full Date, Pinpoint (Name of Speaker). Every day of a
    convention has the same title, so it can't serve as a short title: a repeat reference
    uses the author's own short title, else the citation is repeated in full."""

    source_type = "convention_debates"
    italic_short_title = True
    defines_short_title = True
    bibliography_category = BIB_OTHER

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, ConventionDebatesSource)
        out = RichText()
        out.append(src.title or missing("title"), italic=True)
        out.append(f", {src.location or missing('location')}, {src.date or missing('date')}")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f", {pin}")
        out.append(_speaker(src.speaker))
        return out


@register
class ExplanatoryMemorandumFormatter(Formatter):
    """r 3.7: Explanatory Memorandum, Bill Citation Pinpoint. The Bill is cited as in
    r 3.2 (roman, not italic); 'Explanatory Statement' or 'Explanatory Note(s)' replace
    'Explanatory Memorandum' where appropriate. Pinpoints are to pages or paragraphs."""

    source_type = "explanatory_memorandum"
    italic_short_title = False
    defines_short_title = True
    bibliography_category = BIB_LEGISLATION

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, ExplanatoryMemorandumSource)
        out = RichText.plain(f"{src.document_type or 'Explanatory Memorandum'}, ")
        out.append(f"{src.title or missing('title')} {src.year or missing('year')}")
        out.append(f" ({src.jurisdiction})" if src.jurisdiction else " " + missing("jurisdiction"))
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f" {pin}")
        return out
