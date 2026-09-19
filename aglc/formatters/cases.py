"""Cases (AGLC4 ch 2).

Covers reported decisions (r 2.2), decisions with a medium neutral citation but no
report (r 2.3.1), and unreported decisions with no medium neutral citation (r 2.3.2).
Arbitral awards, transcripts, submissions, court orders and proceedings (rr 2.6-2.8)
are out of scope: `CaseSource` has no fields for them.
"""

from __future__ import annotations

import re

from ..models import CaseSource, Citation, RichText
from .base import BIB_CASES, Formatter, missing, register

# Crown-as-first-party names (r 2.1.4): short title uses the *second* party instead.
_CROWN_NAMES = {"R", "The King", "The Queen"}

# Strips a trailing case-number suffix like "[No 2]" / "[Nos 4 and 5]" (r 2.1.13) so the
# default short title is just the party name(s), per the guide's own example
# ("Mabo v Queensland [No 2]" -> short title "Mabo").
_TRAILING_NUMBER = re.compile(r"\s*\[Nos?\b[^\]]*\]\s*$")


@register
class CaseFormatter(Formatter):
    source_type = "case"
    bibliography_category = BIB_CASES
    italic_short_title = True
    defines_short_title = True
    # uses_n_reference stays at the base default (True): r 1.4.1 says cases use a
    # short title followed by "(n x)" -- see examples at r 2.1.14/2.1.15 ("*Al-Kateb*
    # (n 53) 622 [167]-[168]").

    # ------------------------------------------------------------------ full() --- #
    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, CaseSource)

        out = RichText.italic(src.name)
        unreported_no_mnc = False

        if src.report:
            # Reported decision (r 2.2). A medium neutral citation is never added
            # alongside a report (r 2.2.7: "Parallel citations should not be used").
            square = self._year_is_square(src)
            out.append(" " + self._year(src, square))
            if src.volume:
                out.append(" " + src.volume)
            out.append(" " + src.report)
            out.append(" " + (src.starting_page or missing("starting_page")))
        elif src.court_id:
            # Medium neutral citation only, no report (r 2.3.1). Year is always
            # square-bracketed for medium neutral citations.
            out.append(" " + self._year(src, square=True))
            out.append(" " + src.court_id)
            out.append(" " + (src.judgment_number or missing("judgment_number")))
        elif src.court_name:
            # Unreported, no medium neutral citation (r 2.3.2).
            unreported_no_mnc = True
            parts = [src.court_name, src.judges or missing("judges"), src.date or missing("date")]
            out.append(" (" + ", ".join(parts) + ")")
        else:
            out.append(" " + missing("case citation (report or court details)"))

        pin = self.pinpoints(citation.pinpoints)
        if pin:
            # r 2.3.2: "no punctuation between the closing parenthesis of the full
            # date and any pinpoint" for unreported cases without an MNC. Reported
            # and medium-neutral cases use a comma (rr 2.2.5, 2.3.1).
            out.append((" " if unreported_no_mnc else ", ") + pin)
        if citation.pinpoint_judges:
            out.append(f" ({citation.pinpoint_judges})")
        return out

    # ------------------------------------------------------------- short_title --- #
    def short_title(self, citation: Citation) -> str:
        if citation.short_title:
            return citation.short_title
        src = citation.source
        assert isinstance(src, CaseSource)

        # "Re Wakim; Ex parte McNally" -> take only the first (primary) action,
        # per r 2.1.14's list of default short titles (popular name / first party /
        # ship name); the "Ex parte ..." continuation is dropped.
        segment = src.name.split(";")[0].strip()
        segment = _TRAILING_NUMBER.sub("", segment).strip()

        if " v " in segment:
            first, _, second = segment.partition(" v ")
            first, second = first.strip(), second.strip()
            if first in _CROWN_NAMES:
                # r 2.1.14: "the second-named party when the first-named party is
                # the Crown", eg "R v Tang" -> "Tang".
                return second
            return first
        # No "v": Re cases, admiralty in rem cases (ship name), etc - use as-is.
        return segment

    # -------------------------------------------------------------- internals --- #
    @staticmethod
    def _year(src: CaseSource, square: bool) -> str:
        if not src.year:
            return missing("year")
        return f"[{src.year}]" if square else f"({src.year})"

    @staticmethod
    def _year_is_square(src: CaseSource) -> bool:
        """r 2.2.1: round brackets when the report series numbers volumes
        independently of year; square brackets when the year identifies the volume.
        `normalise` should set `year_style` from knowledge of the report series; this
        is only a fallback for when it hasn't (a volume number is at least a strong
        hint that the series is organised by volume, eg CLR, but is not a reliable
        signal on its own -- eg "(2002) EOC P93-198" has no volume yet uses round
        brackets)."""
        if src.year_style is not None:
            return src.year_style == "square"
        return not src.volume
