"""Tests for aglc/formatters/cases.py (AGLC4 ch 2).

Examples are taken verbatim from reference/aglc4.txt where possible; each test notes
the PDF page the example comes from. A few short-title cases combine the *case name*
from a guide example with a short title derived from applying rule 2.1.14 (not
itself a worked example in the guide) -- these are marked "(derived)".
"""

from aglc.formatters.cases import CaseFormatter
from aglc.models import Citation, CaseSource, Pinpoint, PinpointKind

fmt = CaseFormatter()


def pp(kind: PinpointKind, value: str, plural: bool = False) -> Pinpoint:
    return Pinpoint(kind=kind, value=value, plural=plural)


# --------------------------------------------------------------------------- #
# Reported decisions (r 2.2)
# --------------------------------------------------------------------------- #


def test_reported_with_volume_round_brackets():
    # r 2.2.1 example 56, PDF PAGE 74: "R v Lester (2008) 190 A Crim R 468."
    src = CaseSource(name="R v Lester", year="2008", volume="190", report="A Crim R", starting_page="468")
    citation = Citation(source=src)
    assert fmt.full(citation).to_markup() == "*R v Lester* (2008) 190 A Crim R 468"


def test_reported_no_volume_square_brackets():
    # r 2.2.1 example 58, PDF PAGE 74: "King v King [1974] Qd R 253."
    src = CaseSource(name="King v King", year="1974", report="Qd R", starting_page="253")
    citation = Citation(source=src)
    assert fmt.full(citation).to_markup() == "*King v King* [1974] Qd R 253"


def test_reported_explicit_year_style_overrides_fallback():
    # year_style set by the normaliser should always win over the volume-presence
    # fallback heuristic.
    src = CaseSource(
        name="Borg v Commissioner, Department of Corrective Services",
        year="2002",
        report="EOC",
        starting_page="¶93-198",
        year_style="round",
    )
    citation = Citation(source=src)
    # r 2.2.4 example 67, PDF PAGE 77: no volume, but round brackets.
    assert (
        fmt.full(citation).to_markup()
        == "*Borg v Commissioner, Department of Corrective Services* (2002) EOC ¶93-198"
    )


def test_reported_pinpoint_and_judge():
    # r 2.1.5 example 15, PDF PAGE 67:
    # "Papua and New Guinea v Guba (1973) 130 CLR 353, 369 (Barwick CJ)."
    src = CaseSource(name="Papua and New Guinea v Guba", year="1973", volume="130", report="CLR", starting_page="353")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "369")], pinpoint_judges="Barwick CJ")
    assert fmt.full(citation).to_markup() == "*Papua and New Guinea v Guba* (1973) 130 CLR 353, 369 (Barwick CJ)"


def test_reported_missing_starting_page():
    src = CaseSource(name="Smith v Jones", year="2001", volume="1", report="CLR")
    citation = Citation(source=src)
    assert fmt.full(citation).to_markup() == "*Smith v Jones* (2001) 1 CLR [MISSING: starting_page]"


# --------------------------------------------------------------------------- #
# Medium neutral citation only (r 2.3.1)
# --------------------------------------------------------------------------- #


def test_medium_neutral_no_pinpoint():
    # r 2.3.1 example 81, PDF PAGE 81: "Hooper v Australian Electoral Commission
    # [2015] HCASL 247."
    src = CaseSource(name="Hooper v Australian Electoral Commission", year="2015", court_id="HCASL", judgment_number="247")
    citation = Citation(source=src)
    assert fmt.full(citation).to_markup() == "*Hooper v Australian Electoral Commission* [2015] HCASL 247"


def test_medium_neutral_pinpoint_and_judge():
    # r 2.3.1 example 82, PDF PAGE 81: "Re Culleton [No 2] [2017] HCA 4, [57]
    # (Nettle J)."
    src = CaseSource(name="Re Culleton [No 2]", year="2017", court_id="HCA", judgment_number="4")
    citation = Citation(
        source=src, pinpoints=[pp(PinpointKind.paragraph, "57")], pinpoint_judges="Nettle J"
    )
    assert fmt.full(citation).to_markup() == "*Re Culleton [No 2]* [2017] HCA 4, [57] (Nettle J)"


def test_quarmby_worked_example():
    # r 2.3.1's own worked example (PDF PAGE 79): "Quarmby v Keating [2009] TASSC 80,
    # [11]."
    src = CaseSource(name="Quarmby v Keating", year="2009", court_id="TASSC", judgment_number="80")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.paragraph, "11")])
    assert fmt.full(citation).to_markup() == "*Quarmby v Keating* [2009] TASSC 80, [11]"


# --------------------------------------------------------------------------- #
# Unreported, no medium neutral citation (r 2.3.2)
# --------------------------------------------------------------------------- #


def test_unreported_no_mnc_with_pinpoint():
    # r 2.3.2 example 84, PDF PAGE 81: "Ross v Chambers (Supreme Court of the
    # Northern Territory, Kriewaldt J, 5 April 1956) 77-8."
    src = CaseSource(
        name="Ross v Chambers",
        court_name="Supreme Court of the Northern Territory",
        judges="Kriewaldt J",
        date="5 April 1956",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "77-8")])
    assert (
        fmt.full(citation).to_markup()
        == "*Ross v Chambers* (Supreme Court of the Northern Territory, Kriewaldt J, 5 April 1956) 77–8"
    )


def test_unreported_no_mnc_no_pinpoint():
    # r 2.3.2's own worked example (PDF PAGE 79):
    # "Barton v Chibber (Supreme Court of Victoria, Hampel J, 29 June 1989)"
    src = CaseSource(
        name="Barton v Chibber",
        court_name="Supreme Court of Victoria",
        judges="Hampel J",
        date="29 June 1989",
    )
    citation = Citation(source=src)
    assert fmt.full(citation).to_markup() == "*Barton v Chibber* (Supreme Court of Victoria, Hampel J, 29 June 1989)"


def test_unreported_no_mnc_missing_fields_not_invented():
    src = CaseSource(name="Doe v Roe", court_name="Supreme Court of Victoria")
    citation = Citation(source=src)
    markup = fmt.full(citation).to_markup()
    assert "[MISSING: judges]" in markup
    assert "[MISSING: date]" in markup


def test_no_report_or_court_details_at_all():
    src = CaseSource(name="Doe v Roe")
    citation = Citation(source=src)
    assert "[MISSING: case citation" in fmt.full(citation).to_markup()


# --------------------------------------------------------------------------- #
# Short titles (r 2.1.14, r 1.4.4)
# --------------------------------------------------------------------------- #


def test_short_title_first_named_party():
    # (derived) task example: "Mabo v Queensland [No 2]" -> "Mabo".
    src = CaseSource(name="Mabo v Queensland [No 2]", year="1992", volume="175", report="CLR", starting_page="1")
    citation = Citation(source=src)
    assert fmt.short_title(citation) == "Mabo"


def test_short_title_crown_first_party_uses_second_party():
    # (derived from r 2.1.4 + r 2.1.14) using the case name from r 2.1.4 example 11,
    # PDF PAGE 66: "R v Reid [2007] 1 Qd R 64."
    src = CaseSource(name="R v Reid", year="2007", volume="1", report="Qd R", starting_page="64")
    citation = Citation(source=src)
    assert fmt.short_title(citation) == "Reid"


def test_short_title_re_case_with_ex_parte():
    # (derived) task example: "Re Wakim; Ex parte McNally" -> "Re Wakim".
    src = CaseSource(name="Re Wakim; Ex parte McNally", year="1999", volume="198", report="CLR", starting_page="511")
    citation = Citation(source=src)
    assert fmt.short_title(citation) == "Re Wakim"


def test_short_title_author_supplied_wins():
    # r 2.1.14 example 44, PDF PAGE 72:
    # "(1983) 158 CLR 1 ('Tasmanian Dam Case')."
    src = CaseSource(name="Commonwealth v Tasmania", year="1983", volume="158", report="CLR", starting_page="1")
    citation = Citation(source=src, short_title="Tasmanian Dam Case")
    assert fmt.short_title(citation) == "Tasmanian Dam Case"


# --------------------------------------------------------------------------- #
# Subsequent references and ibid (r 1.4.1, r 1.4.3) -- exercised through the base
# Formatter implementation, since CaseFormatter does not override them.
# --------------------------------------------------------------------------- #


def test_subsequent_reference_with_n_reference_and_judge():
    # r 2.1.14 example 46, PDF PAGE 72: "Tasmanian Dam Case (n 44) 109 (Gibbs CJ)."
    src = CaseSource(name="Commonwealth v Tasmania", year="1983", volume="158", report="CLR", starting_page="1")
    citation = Citation(
        source=src, pinpoints=[pp(PinpointKind.page, "109")], pinpoint_judges="Gibbs CJ"
    )
    out = fmt.subsequent(citation, "Tasmanian Dam Case", first_footnote=44)
    assert out.to_markup() == "*Tasmanian Dam Case* (n 44) 109 (Gibbs CJ)"


def test_ibid_pinpoint_with_judge():
    # (derived from r 1.4.3 + r 2.4.1) task example:
    # "(1992) 175 CLR 1, 42 (Mason CJ)" pinpointed via ibid.
    src = CaseSource(name="Mabo v Queensland [No 2]", year="1992", volume="175", report="CLR", starting_page="1")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "42")], pinpoint_judges="Mason CJ")
    assert fmt.ibid_pinpoint(citation) == "42 (Mason CJ)"


# --------------------------------------------------------------------------- #
# Bibliography (r 1.13)
# --------------------------------------------------------------------------- #


def test_bibliography_strips_pinpoints():
    # r 1.13 example, PDF PAGE 62: "Lane v Morrison (2009) 239 CLR 230"
    src = CaseSource(name="Lane v Morrison", year="2009", volume="239", report="CLR", starting_page="230")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "235")], pinpoint_judges="French CJ")
    assert fmt.bibliography(citation).to_markup() == "*Lane v Morrison* (2009) 239 CLR 230"
