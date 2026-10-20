"""Parliamentary materials: debates ('Hansard', AGLC4 r 7.5.1 and r 24.4.1) and
explanatory memoranda, statements and notes (r 3.7).

Committee reports (r 7.1.2) are ordinary reports with the committee as author
('Committee, Legislature'), and parliamentary research papers (r 7.2.3) are research
papers; both live in `secondary.py`.
"""

from __future__ import annotations

from ..models import Citation, ExplanatoryMemorandumSource, ParliamentaryDebatesSource, RichText
from .base import BIB_LEGISLATION, BIB_OTHER, Formatter, missing, register


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
        if src.speaker:
            speaker = f"{src.speaker}, {src.speaker_position}" if src.speaker_position else src.speaker
            out.append(f" ({speaker})")
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
