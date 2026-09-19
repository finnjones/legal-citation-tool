"""Tests for aglc.normalise: case-name clean-up, report/court/jurisdiction
canonicalisation, pinpoint tidy-up, and source_key identity."""

from __future__ import annotations

import pytest

from aglc.models import (
    BookSource,
    CaseSource,
    Citation,
    JournalArticleSource,
    LegislationSource,
    OtherSource,
    Pinpoint,
    PinpointKind,
    TreatySource,
)
from aglc.normalise import normalise_citation, source_key


def make_citation(source) -> Citation:
    return Citation(source=source)


# --------------------------------------------------------------------------- #
# Case name clean-up (AGLC4 r 2.1)
# --------------------------------------------------------------------------- #


def test_case_name_pty_ltd_full_stops_removed():
    c, _ = normalise_citation(make_citation(CaseSource(name="Smith v Jones Pty. Ltd.", report="CLR")))
    assert c.source.name == "Smith v Jones Pty Ltd"


def test_case_name_vs_normalised():
    c, _ = normalise_citation(make_citation(CaseSource(name="Smith vs. Jones", report="CLR")))
    assert c.source.name == "Smith v Jones"


def test_case_name_capital_v_normalised():
    c, _ = normalise_citation(make_citation(CaseSource(name="Smith V Jones", report="CLR")))
    assert c.source.name == "Smith v Jones"


def test_case_name_v_dot_normalised():
    c, _ = normalise_citation(make_citation(CaseSource(name="Smith v. Jones", report="CLR")))
    assert c.source.name == "Smith v Jones"


def test_case_name_crown_first_party_abbreviated():
    # AGLC4 r 2.1.4: Crown as first-named party -> 'R'
    c, _ = normalise_citation(make_citation(CaseSource(name="Regina v Smith", report="CLR")))
    assert c.source.name == "R v Smith"


def test_case_name_crown_rex_first_party():
    c, _ = normalise_citation(make_citation(CaseSource(name="Rex v Smith", report="CLR")))
    assert c.source.name == "R v Smith"


def test_case_name_crown_as_respondent_written_in_full():
    # AGLC4 r 2.1.4: Crown as respondent -> 'The Queen'/'The King' written in full
    c, _ = normalise_citation(make_citation(CaseSource(name="Honeysett v Regina", report="CLR")))
    assert c.source.name == "Honeysett v The Queen"


def test_case_name_crown_king_respondent():
    c, _ = normalise_citation(make_citation(CaseSource(name="Honeysett v Rex", report="CLR")))
    assert c.source.name == "Honeysett v The King"


def test_case_name_the_queen_untouched_as_respondent():
    c, _ = normalise_citation(make_citation(CaseSource(name="Honeysett v The Queen", report="CLR")))
    assert c.source.name == "Honeysett v The Queen"


def test_case_name_no_2_parens_to_brackets():
    c, _ = normalise_citation(make_citation(CaseSource(name="Mabo v Queensland (No. 2)", report="CLR")))
    assert c.source.name == "Mabo v Queensland [No 2]"


def test_case_name_no_2_already_bracketed_untouched():
    c, _ = normalise_citation(make_citation(CaseSource(name="Mabo v Queensland [No 2]", report="CLR")))
    assert c.source.name == "Mabo v Queensland [No 2]"


def test_case_name_no_2_bare_bracketed():
    c, _ = normalise_citation(make_citation(CaseSource(name="Bahr v Nicolay No 2", report="CLR")))
    assert c.source.name == "Bahr v Nicolay [No 2]"


def test_case_name_strips_quotes_and_collapses_whitespace():
    c, _ = normalise_citation(make_citation(CaseSource(name="  'Smith  v   Jones'  ", report="CLR")))
    assert c.source.name == "Smith v Jones"


# --------------------------------------------------------------------------- #
# Report series canonicalisation and year_style (AGLC4 r 2.2.1, 2.2.3)
# --------------------------------------------------------------------------- #


def test_report_clr_round_authorised_punctuated_variant():
    c, w = normalise_citation(
        make_citation(CaseSource(name="A v B", report="C.L.R.", volume="164", starting_page="1", year="1987"))
    )
    assert c.source.report == "CLR"
    assert c.source.year_style == "round"
    assert not w


def test_report_nswlr_round():
    # Confirmed against reference/aglc4.txt r 2.2.1: eg '(1992) 29 NSWLR 188'
    c, _ = normalise_citation(make_citation(CaseSource(name="A v B", report="NSWLR")))
    assert c.source.report == "NSWLR"
    assert c.source.year_style == "round"


def test_report_vr_round_not_square():
    # Confirmed against reference/aglc4.txt r 2.2.1 example 57: '(2002) 6 VR 317'
    c, _ = normalise_citation(make_citation(CaseSource(name="A v B", report="V.R.")))
    assert c.source.report == "VR"
    assert c.source.year_style == "round"


def test_report_qd_r_square():
    # Confirmed against reference/aglc4.txt r 2.2.1 example 58: '[1974] Qd R 253'
    c, _ = normalise_citation(make_citation(CaseSource(name="A v B", report="Qd.R.")))
    assert c.source.report == "Qd R"
    assert c.source.year_style == "square"


def test_report_nzlr_square():
    c, _ = normalise_citation(make_citation(CaseSource(name="A v B", report="N.Z.L.R.")))
    assert c.source.report == "NZLR"
    assert c.source.year_style == "square"


def test_report_full_name_matches_abbrev():
    c, _ = normalise_citation(make_citation(CaseSource(name="A v B", report="Commonwealth Law Reports")))
    assert c.source.report == "CLR"


def test_report_unknown_warns_and_leaves_year_style_untouched():
    c, w = normalise_citation(make_citation(CaseSource(name="A v B", report="Made Up Reports")))
    assert c.source.report == "Made Up Reports"
    assert c.source.year_style is None
    assert any("Unknown report series" in msg for msg in w)


def test_mnc_only_sets_square_year_style():
    c, _ = normalise_citation(
        make_citation(CaseSource(name="A v B", court_id="HCA", judgment_number="1", year="2010"))
    )
    assert c.source.year_style == "square"


# --------------------------------------------------------------------------- #
# Court canonicalisation (AGLC4 r 2.3)
# --------------------------------------------------------------------------- #


def test_court_id_punctuated_variant_canonicalised():
    c, w = normalise_citation(
        make_citation(CaseSource(name="A v B", court_id="N.S.W.C.A.", judgment_number="1", year="2010"))
    )
    assert c.source.court_id == "NSWCA"
    assert not w


def test_court_id_full_name_variant():
    c, _ = normalise_citation(
        make_citation(CaseSource(name="A v B", court_id="High Court", judgment_number="1", year="2010"))
    )
    assert c.source.court_id == "HCA"


def test_court_id_unknown_warns():
    c, w = normalise_citation(
        make_citation(CaseSource(name="A v B", court_id="XYZQQ", judgment_number="1", year="2010"))
    )
    assert c.source.court_id == "XYZQQ"
    assert any("Unknown court identifier" in msg for msg in w)


# --------------------------------------------------------------------------- #
# Legislation (AGLC4 r 3.1)
# --------------------------------------------------------------------------- #


def test_legislation_jurisdiction_variant_canonicalised():
    c, w = normalise_citation(
        make_citation(LegislationSource(title="Crimes Act", year="1900", jurisdiction="N.S.W."))
    )
    assert c.source.jurisdiction == "NSW"
    assert not w


def test_legislation_year_split_from_title():
    c, _ = normalise_citation(make_citation(LegislationSource(title="Crimes Act 1900", jurisdiction="NSW")))
    assert c.source.title == "Crimes Act"
    assert c.source.year == "1900"


def test_legislation_constitution_special_case():
    c, _ = normalise_citation(make_citation(LegislationSource(title="Constitution", jurisdiction="Cth")))
    assert c.source.kind == "constitution"
    assert c.source.title == "Australian Constitution"
    assert c.source.jurisdiction == "Cth"


def test_legislation_commonwealth_constitution_variant():
    c, _ = normalise_citation(make_citation(LegislationSource(title="Commonwealth Constitution")))
    assert c.source.kind == "constitution"
    assert c.source.title == "Australian Constitution"
    assert c.source.jurisdiction == "Cth"


def test_legislation_state_constitution_act_not_rewritten():
    # 'Constitution Act 1902 (NSW)' is a normal Act, not the special Constitution case.
    c, _ = normalise_citation(
        make_citation(LegislationSource(title="Constitution Act 1902", jurisdiction="NSW"))
    )
    assert c.source.kind == "act"
    assert c.source.title == "Constitution Act"


def test_legislation_missing_jurisdiction_warns():
    _, w = normalise_citation(make_citation(LegislationSource(title="Crimes Act", year="1900")))
    assert any("jurisdiction" in msg.lower() for msg in w)


# --------------------------------------------------------------------------- #
# Authors / secondary sources
# --------------------------------------------------------------------------- #


def test_authors_trimmed_and_trailing_punctuation_removed():
    c, _ = normalise_citation(
        make_citation(
            JournalArticleSource(authors=["  John Smith, ", "Jane Doe."], title="An Article", journal="A Journal")
        )
    )
    assert c.source.authors == ["John Smith", "Jane Doe"]


def test_journal_name_trimmed_not_abbreviated():
    c, _ = normalise_citation(
        make_citation(JournalArticleSource(authors=["A Author"], title="T", journal="  The Law Journal  "))
    )
    assert c.source.journal == "The Law Journal"


def test_book_missing_authors_and_editors_warns():
    _, w = normalise_citation(make_citation(BookSource(title="A Book")))
    assert any("author" in msg.lower() for msg in w)


# --------------------------------------------------------------------------- #
# Pinpoints
# --------------------------------------------------------------------------- #


def test_pinpoint_at_prefix_stripped():
    c = make_citation(CaseSource(name="A v B", report="CLR"))
    c.pinpoints = [Pinpoint(kind=PinpointKind.page, value="at 42")]
    c, _ = normalise_citation(c)
    assert c.pinpoints[0].value == "42"
    assert c.pinpoints[0].kind == PinpointKind.page


def test_pinpoint_pp_prefix_stripped():
    c = make_citation(CaseSource(name="A v B", report="CLR"))
    c.pinpoints = [Pinpoint(kind=PinpointKind.page, value="pp 42-45")]
    c, _ = normalise_citation(c)
    assert c.pinpoints[0].value == "42-45"


def test_pinpoint_bracketed_page_becomes_paragraph():
    c = make_citation(CaseSource(name="A v B", report="CLR"))
    c.pinpoints = [Pinpoint(kind=PinpointKind.page, value="[12]")]
    c, _ = normalise_citation(c)
    assert c.pinpoints[0].kind == PinpointKind.paragraph
    assert c.pinpoints[0].value == "12"


def test_pinpoint_para_prefix_with_paragraph_kind():
    c = make_citation(CaseSource(name="A v B", report="CLR"))
    c.pinpoints = [Pinpoint(kind=PinpointKind.paragraph, value="para 12")]
    c, _ = normalise_citation(c)
    assert c.pinpoints[0].value == "12"


# --------------------------------------------------------------------------- #
# source_key identity
# --------------------------------------------------------------------------- #


def test_source_key_same_case_different_writing_report_based():
    a = CaseSource(name="Mabo v. Queensland (No. 2)", report="C.L.R.", volume="175", starting_page="1", year="1992")
    b = CaseSource(name="Mabo v Queensland [No 2]", report="CLR", volume="175", starting_page="1", year="1992")
    assert source_key(a) == source_key(b)


def test_source_key_same_mnc_case_different_writing():
    a = CaseSource(name="Re Culleton (No. 2)", court_id="H.C.A.", judgment_number="4", year="2017")
    b = CaseSource(name="Re Culleton [No 2]", court_id="HCA", judgment_number="4", year="2017")
    assert source_key(a) == source_key(b)


def test_source_key_different_cases_differ():
    a = CaseSource(name="A v B", report="CLR", volume="1", starting_page="1", year="2000")
    b = CaseSource(name="C v D", report="CLR", volume="2", starting_page="5", year="2001")
    assert source_key(a) != source_key(b)


def test_source_key_legislation_identity():
    a = LegislationSource(title="Crimes Act 1900", jurisdiction="N.S.W.")
    b = LegislationSource(title="Crimes Act", year="1900", jurisdiction="NSW")
    assert source_key(a) == source_key(b)


def test_source_key_journal_article_uses_first_author_surname_and_title():
    a = JournalArticleSource(authors=["Jane Smith"], title="A Great Article", journal="J")
    b = JournalArticleSource(authors=["Jane   Smith "], title="  a great article ", journal="J")
    assert source_key(a) == source_key(b)


def test_source_key_other_source_normalised_text():
    a = OtherSource(text="Some Raw Citation Text.")
    b = OtherSource(text="  some raw citation text  ")
    assert source_key(a) == source_key(b)


def test_source_key_treaty_normalised_title():
    a = TreatySource(title="Vienna Convention on the Law of Treaties")
    b = TreatySource(title="  vienna convention on the law of treaties  ")
    assert source_key(a) == source_key(b)


def test_citation_source_key_set_by_normalise():
    c, _ = normalise_citation(make_citation(CaseSource(name="A v B", report="CLR", volume="1", starting_page="1")))
    assert c.source_key
    assert c.source_key == source_key(c.source)


def test_pinpoint_judges_trimmed():
    c = Citation(
        source=CaseSource(name="A v B", report="CLR"),
        pinpoint_judges="  Mason CJ. ",
    )
    c, _ = normalise_citation(c)
    assert c.pinpoint_judges == "Mason CJ"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
