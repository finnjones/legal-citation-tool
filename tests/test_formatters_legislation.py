"""Tests for aglc/formatters/legislation.py (AGLC4 ch 3).

Examples are taken verbatim from reference/aglc4.txt where possible; each test notes
the PDF page the example comes from.
"""

from aglc.formatters.legislation import LegislationFormatter
from aglc.models import Citation, LegislationSource, Pinpoint, PinpointKind

fmt = LegislationFormatter()


def pp(kind: PinpointKind, value: str, plural: bool = False) -> Pinpoint:
    return Pinpoint(kind=kind, value=value, plural=plural)


# --------------------------------------------------------------------------- #
# Acts (r 3.1)
# --------------------------------------------------------------------------- #


def test_act_no_pinpoint():
    # r 3.1.1 example 1, PDF PAGE 92: "Evidence Act 1995 (NSW)."
    src = LegislationSource(kind="act", title="Evidence Act", year="1995", jurisdiction="NSW")
    citation = Citation(source=src)
    assert fmt.full(citation).to_markup() == "*Evidence Act 1995* (NSW)"


def test_act_with_section_pinpoint():
    # ch 3's header worked example, PDF PAGE 91: "Crimes Act 1958 (Vic) s 3."
    src = LegislationSource(kind="act", title="Crimes Act", year="1958", jurisdiction="Vic")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.section, "3")])
    assert fmt.full(citation).to_markup() == "*Crimes Act 1958* (Vic) s 3"


def test_act_title_with_embedded_number():
    # r 3.1.1 example 3, PDF PAGE 92:
    # "Financial Framework Legislation Amendment Act (No 2) 2012 (Cth)."
    src = LegislationSource(
        kind="act", title="Financial Framework Legislation Amendment Act (No 2)", year="2012", jurisdiction="Cth"
    )
    citation = Citation(source=src)
    assert (
        fmt.full(citation).to_markup()
        == "*Financial Framework Legislation Amendment Act (No 2) 2012* (Cth)"
    )


def test_act_multiple_pinpoint_kinds():
    # r 3.1.4 example 11, PDF PAGE 96: "Aboriginal and Torres Strait Islander Act
    # 2005 (Cth) pt 3A div 2."
    src = LegislationSource(kind="act", title="Aboriginal and Torres Strait Islander Act", year="2005", jurisdiction="Cth")
    citation = Citation(
        source=src, pinpoints=[pp(PinpointKind.part, "3A"), pp(PinpointKind.division, "2")]
    )
    assert fmt.full(citation).to_markup() == "*Aboriginal and Torres Strait Islander Act 2005* (Cth) pt 3A div 2"


def test_act_definition_pinpoint_verbatim():
    # r 3.1.6 example 24, PDF PAGE 97: "Property Law Act 1958 (Vic) s 3 (definition
    # of 'legal practitioner')." PinpointKind has no dedicated "definition" kind, so
    # this is expressed as a verbatim PinpointKind.other value.
    src = LegislationSource(kind="act", title="Property Law Act", year="1958", jurisdiction="Vic")
    citation = Citation(
        source=src, pinpoints=[pp(PinpointKind.other, "s 3 (definition of ‘legal practitioner’)")]
    )
    assert (
        fmt.full(citation).to_markup()
        == "*Property Law Act 1958* (Vic) s 3 (definition of ‘legal practitioner’)"
    )


def test_act_missing_year_and_jurisdiction_not_invented():
    src = LegislationSource(kind="act", title="Mystery Act")
    citation = Citation(source=src)
    markup = fmt.full(citation).to_markup()
    assert "[MISSING: year]" in markup
    assert "[MISSING: jurisdiction]" in markup


# --------------------------------------------------------------------------- #
# Delegated legislation (r 3.4)
# --------------------------------------------------------------------------- #


def test_delegated_legislation():
    # r 3.4 example 39, PDF PAGE 100: "Heritage Regulation 2006 (ACT) reg 5(1)."
    src = LegislationSource(kind="delegated", title="Heritage Regulation", year="2006", jurisdiction="ACT")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.regulation, "5(1)")])
    assert fmt.full(citation).to_markup() == "*Heritage Regulation 2006* (ACT) reg 5(1)"


def test_delegated_legislation_rules():
    # r 3.4 example 42, PDF PAGE 100: "Supreme Court (General Civil Procedure) Rules
    # 2015 (Vic) r 3.01."
    src = LegislationSource(
        kind="delegated", title="Supreme Court (General Civil Procedure) Rules", year="2015", jurisdiction="Vic"
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.rule, "3.01")])
    assert fmt.full(citation).to_markup() == "*Supreme Court (General Civil Procedure) Rules 2015* (Vic) r 3.01"


# --------------------------------------------------------------------------- #
# Bills (r 3.2) -- not italicised.
# --------------------------------------------------------------------------- #


def test_bill_with_clause_pinpoint():
    # r 3.2 example 34, PDF PAGE 99:
    # "Carbon Pollution Reduction Scheme Bill 2009 (Cth) cl 83."
    src = LegislationSource(kind="bill", title="Carbon Pollution Reduction Scheme Bill", year="2009", jurisdiction="Cth")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.clause, "83")])
    result = fmt.full(citation)
    assert result.to_markup() == "Carbon Pollution Reduction Scheme Bill 2009 (Cth) cl 83"
    assert all(not r.italic for r in result.runs)


def test_bill_no_pinpoint():
    # r 3.2 example 33, PDF PAGE 99:
    # "Corporations Amendment (Crowd-Sourced Funding) Bill 2015 (Cth)."
    src = LegislationSource(
        kind="bill", title="Corporations Amendment (Crowd-Sourced Funding) Bill", year="2015", jurisdiction="Cth"
    )
    citation = Citation(source=src)
    assert fmt.full(citation).to_markup() == "Corporations Amendment (Crowd-Sourced Funding) Bill 2015 (Cth)"


# --------------------------------------------------------------------------- #
# Constitutions (r 3.6)
# --------------------------------------------------------------------------- #


def test_commonwealth_constitution_no_jurisdiction():
    # r 3.6 example 49, PDF PAGE 102: "Australian Constitution s 51(ii)."
    src = LegislationSource(kind="constitution", title="Australian Constitution")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.section, "51(ii)")])
    assert fmt.full(citation).to_markup() == "*Australian Constitution* s 51(ii)"


def test_state_constitution_cited_as_normal_act():
    # r 3.6 example 52, PDF PAGE 102: "Constitution Act 1902 (NSW) s 5." -- state
    # constitutions "should be cited as normal statutes" per r 3.6, so kind="act".
    src = LegislationSource(kind="act", title="Constitution Act", year="1902", jurisdiction="NSW")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.section, "5")])
    assert fmt.full(citation).to_markup() == "*Constitution Act 1902* (NSW) s 5"


# --------------------------------------------------------------------------- #
# Short titles and subsequent references (r 3.5, r 1.4.1)
# --------------------------------------------------------------------------- #


def test_short_title_default_is_empty_without_author_supplied_one():
    src = LegislationSource(kind="act", title="Property Law Act", year="1958", jurisdiction="Vic")
    citation = Citation(source=src)
    assert fmt.short_title(citation) == ""


def test_short_title_author_supplied():
    # r 3.5 example 45, PDF PAGE 101:
    # "Property Law Act 1958 (Vic) s 6 ('Property Act')."
    src = LegislationSource(kind="act", title="Property Law Act", year="1958", jurisdiction="Vic")
    citation = Citation(source=src, short_title="Property Act", pinpoints=[pp(PinpointKind.section, "6")])
    assert fmt.short_title(citation) == "Property Act"
    # full() excludes the short title definition -- the document pass adds
    # "('Property Act')" after this.
    assert fmt.full(citation).to_markup() == "*Property Law Act 1958* (Vic) s 6"


def test_subsequent_reference_uses_n_reference():
    # r 3.5 example 48, PDF PAGE 101: "ADJR Act (n 46) s 7."
    #
    # NOTE: Formatter.uses_n_reference documents that "legislation ... do[es] not"
    # use "(n x)" for subsequent references, and the task brief for this module said
    # to override subsequent() to produce "CCA s 5" with no "(n x)". That contradicts
    # the Guide: r 1.4.1 states "[f]or cases *and legislation*, a short title ... may
    # be used followed by a cross-reference in parentheses", and every worked
    # example agrees (eg this one, and r 3.1.7 examples 31-32: "Criminal Code (n 66)
    # s 80.2(5)", "Australian Consumer Law (n 67) s 3"). LegislationFormatter
    # therefore leaves `uses_n_reference` at the Formatter base default (True) and
    # does not override `subsequent()`; see the final report.
    src = LegislationSource(kind="act", title="Administrative Decisions (Judicial Review) Act", year="1977", jurisdiction="Cth")
    citation = Citation(source=src, short_title="ADJR Act", pinpoints=[pp(PinpointKind.section, "7")])
    out = fmt.subsequent(citation, "ADJR Act", first_footnote=46)
    assert out.to_markup() == "*ADJR Act* (n 46) s 7"


def test_ibid_pinpoint():
    # r 1.4.3 example, PDF PAGE 37: "72 Defamation Act 2005 (Vic) s 37. 73 Ibid s 38."
    src = LegislationSource(kind="act", title="Defamation Act", year="2005", jurisdiction="Vic")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.section, "38")])
    assert fmt.ibid_pinpoint(citation) == "s 38"


# --------------------------------------------------------------------------- #
# Bibliography (r 1.13)
# --------------------------------------------------------------------------- #


def test_bibliography_strips_pinpoints():
    # r 1.13 example, PDF PAGE 62: "Access to Medicinal Cannabis Act 2016 (Vic)"
    src = LegislationSource(kind="act", title="Access to Medicinal Cannabis Act", year="2016", jurisdiction="Vic")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.section, "10")])
    assert fmt.bibliography(citation).to_markup() == "*Access to Medicinal Cannabis Act 2016* (Vic)"


def test_bibliography_constitution():
    # r 1.13 example, PDF PAGE 62: "Australian Constitution"
    src = LegislationSource(kind="constitution", title="Australian Constitution")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.section, "51(xxix)")])
    assert fmt.bibliography(citation).to_markup() == "*Australian Constitution*"
