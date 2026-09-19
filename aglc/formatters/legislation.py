"""Legislation (AGLC4 ch 3): Acts, delegated legislation, Bills and constitutions.

Gazettes, explanatory memoranda, legislative-history annotations and non-government
delegated legislation (rr 3.7-3.9) are out of scope: `LegislationSource` has no
fields for them.
"""

from __future__ import annotations

from ..models import Citation, LegislationSource, RichText
from .base import BIB_LEGISLATION, Formatter, missing, register


@register
class LegislationFormatter(Formatter):
    source_type = "legislation"
    italic_short_title = True
    defines_short_title = True
    bibliography_category = BIB_LEGISLATION
    # uses_n_reference stays at the base default (True). Despite the "legislation ...
    # do[es] not [use '(n x)']" note on Formatter.uses_n_reference, r 1.4.1 is explicit
    # that "[f]or cases *and legislation*, a short title ... may be used followed by a
    # cross-reference in parentheses", and every worked example agrees, eg r 1.4.1's
    # own example 65 "*ADJR Act* (n 63) s 5(2)" and r 3.1.7's examples 31-32
    # ("*Criminal Code* (n 66) s 80.2(5)", "*Australian Consumer Law* (n 67) s 3").
    # See the final report for this discrepancy.

    # ------------------------------------------------------------------ full() --- #
    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, LegislationSource)
        title = src.title or missing("title")

        out = RichText()
        if src.kind == "bill":
            # r 3.2: Bills are cited like Acts, but title and year are not italicised.
            out.append(title)
            out.append(" " + (src.year or missing("year")))
        elif src.kind == "constitution" and not src.year:
            # r 3.6: "the *Australian Constitution*" (or "*Commonwealth Constitution*",
            # "*Constitution*") cited by name alone, with no year or jurisdiction.
            # A state constitution "should be cited as normal statutes" (kind="act"),
            # so this branch is only for the no-year/no-jurisdiction form.
            out.append(title, italic=True)
        else:
            # r 3.1.1-3.1.3 (Acts), r 3.4 (delegated legislation): title and year in
            # italics, jurisdiction in roman following in parentheses.
            out.append(f"{title} {src.year or missing('year')}", italic=True)

        if src.kind == "constitution" and not src.year:
            pass  # *Australian Constitution* s 51: no jurisdiction (the normaliser may set Cth)
        elif src.jurisdiction:
            out.append(f" ({src.jurisdiction})")
        else:
            out.append(" " + missing("jurisdiction"))

        pin = self.pinpoints(citation.pinpoints)
        if pin:
            # r 3.1.4: pinpoint follows the jurisdiction after a space, no comma.
            out.append(" " + pin)
        return out

    # ------------------------------------------------------------- short_title --- #
    # Uses the base implementation: only an author-supplied short title (r 3.5), else
    # "" -- an unabbreviated piece of legislation is simply cited in full every time
    # (the document pass repeats `full()` rather than calling `subsequent()`).
