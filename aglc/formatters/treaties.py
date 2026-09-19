"""Treaties (AGLC4 ch 8).

 *Treaty Title* [, Parties,] opened for signature Date, Treaty Series
 (entered into force Date) Pinpoint.

Bilateral/trilateral treaties use 'signed' instead of 'opened for signature'
(r 8.3.2); when the date of conclusion and entry into force are the same,
they collapse into a single '(signed and entered into force Date)' clause
placed after the treaty series, with no separate date-of-conclusion clause
(r 8.3.2). Treaties not yet in force use '(not yet in force)' in place of the
entry-into-force clause (r 8.3.3).

Subsequent references (r 8.8) follow the general r 1.4.1/1.4.4 rule and DO
use '(n x)' (eg '*Timor Gap Treaty* (n 20) art 6(1)'), with no comma before
the pinpoint - exactly what the base Formatter.subsequent() default produces
given uses_n_reference=True and italic_short_title=True, so it isn't
overridden here. A short title may also be given to just a portion of a
treaty (eg an annex): that's simply whatever `citation.short_title` holds
(eg 'Annex on Chemicals') placed after the portion's pinpoint by the document
pass - nothing formatter-specific is needed for it beyond passing the value
through unchanged.
"""

from __future__ import annotations

from ..models import Citation, RichText, TreatySource
from .base import BIB_TREATIES, Formatter, missing, register

_EN_DASH = "–"


@register
class TreatyFormatter(Formatter):
    source_type = "treaty"
    # r 1.4.1/8.8: treaty subsequent references use '(n x)' like everything else.
    uses_n_reference = True
    # Treaty short titles are always a (portion of the) treaty title, so
    # always italicised (r 1.4.4, r 8.1).
    italic_short_title = True
    defines_short_title = True
    bibliography_category = BIB_TREATIES

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, TreatySource)
        out = RichText()
        out.append(src.title, italic=True)
        if src.parties:
            out.append(", " + _EN_DASH.join(src.parties))

        combined = bool(
            src.signed
            and src.opened_for_signature
            and src.entry_into_force
            and src.opened_for_signature == src.entry_into_force
        )
        not_yet_in_force = bool(src.entry_into_force and src.entry_into_force.strip().lower() == "not yet in force")

        if combined:
            # r 8.3.2: "..., Treaty Series (signed and entered into force Date)."
            out.append(", ")
            out.append(src.treaty_series or missing("treaty_series"))
            out.append(f" (signed and entered into force {src.opened_for_signature})")
        else:
            verb = "signed" if src.signed else "opened for signature"
            date = src.opened_for_signature or missing("opened_for_signature")
            out.append(f", {verb} {date}, ")
            out.append(src.treaty_series or missing("treaty_series"))
            if not_yet_in_force:
                out.append(" (not yet in force)")
            else:
                out.append(f" (entered into force {src.entry_into_force or missing('entry_into_force')})")

        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        return out

    def short_title(self, citation: Citation) -> str:
        # r 8.1/8.8: unlike cases/legislation, treaty titles have no obvious
        # automatic short form (they're not shortened to a "first party"), so
        # only an author-supplied short title is ever used.
        return citation.short_title or ""
