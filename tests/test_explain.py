"""Tests for aglc/explain.py: each amended footnote says what changed and which rule says so."""

from __future__ import annotations

import pytest

from aglc import api
from aglc.document import render_document
from aglc.explain import explain
from aglc.models import CaseSource, Citation, CitationSegment, Footnote, RichText


def _rich(markup: str) -> RichText:
    """'*Crimes Act* 1900' -> RichText with 'Crimes Act' italic."""
    out = RichText()
    for i, part in enumerate(markup.split("*")):
        out.append(part, italic=bool(i % 2))
    return out


def _explain(before: str, after: str, *types: str) -> list[tuple[str, str | None]]:
    return [(c.kind, c.rule) for c in explain(_rich(before), _rich(after), types)]


def _lines(before: str, after: str, *types: str) -> list[str]:
    return [c.text for c in explain(_rich(before), _rich(after), types)]


# ---- the changes a student said looked like "nothing changed" (Oct 2026) ---------- #


def test_year_moved_inside_the_italics():
    assert _explain("*Crimes Act* 1900 (NSW) s 5.", "*Crimes Act 1900* (NSW) s 5.", "legislation") == [
        ("act_year_italic", "r 3.1.2")]
    assert _lines("*Crimes Act* 1900 (NSW).", "*Crimes Act 1900* (NSW).", "legislation") == [
        "The year is part of an Act’s title, so it’s italic too"]


def test_comma_before_a_paragraph_pinpoint():
    before = "*Momcilovic v The Queen* (2011) 245 CLR 1 [597]."
    after = "*Momcilovic v The Queen* (2011) 245 CLR 1, [597]."
    assert _explain(before, after, "case") == [("pinpoint_comma", "r 2.2.5")]
    assert _explain("Smith, ‘Title’ (2010) 34 *MULR* 1 5.", "Smith, ‘Title’ (2010) 34 *MULR* 1, 5.",
                    "journal_article") == [("pinpoint_comma", "r 5.7")]


def test_page_range_shortened_with_an_en_dash():
    before = "*Mabo v Queensland [No 2]* (1992) 175 CLR 1, 648-649."
    after = "*Mabo v Queensland [No 2]* (1992) 175 CLR 1, 648–9."
    assert _explain(before, after, "case") == [("span", "r 1.1.7")]
    assert _lines(before, after, "case") == ["Page range shortened to ‘648–9’, with an en dash"]


def test_en_dash_only():
    assert _lines("*Agius v South Australia* [2018] FCA 358, [90]-[97].",
                  "*Agius v South Australia* [2018] FCA 358, [90]–[97].", "case") == [
        "A range takes an en dash, not a hyphen"]


def test_short_title_defined():
    before = "*Crimes Act 1900* (NSW) s 5."
    after = "*Crimes Act 1900* (NSW) s 5 (‘*Crimes Act*’)."
    assert _explain(before, after, "legislation") == [("short_title", "r 1.4.4")]
    assert _lines(before, after, "legislation") == [
        "Defines the short title ‘Crimes Act’ for later references to this source"]


def test_journal_article_label_removed():
    before = "Jane Smith, ‘Statutory Interpretation’ (Journal Article, 2010) 34 *Melbourne University Law Review* 1."
    after = "Jane Smith, ‘Statutory Interpretation’ (2010) 34 *Melbourne University Law Review* 1."
    assert _explain(before, after, "journal_article") == [("type_label", "ch 5")]
    assert _lines(before, after, "journal_article") == [
        "AGLC4 doesn’t label journal articles, so ‘Journal Article’ is removed"]


# ---- subsequent references ------------------------------------------------------ #


def test_ibid():
    before = "*Mabo v Queensland [No 2]* (1992) 175 CLR 1, 34."
    assert _explain(before, "Ibid 34.", "case") == [("ibid", "r 1.4.3")]
    assert _explain("See " + before, "See ibid 34.", "case") == [("ibid", "r 1.4.3")]
    assert _explain("Ibid 34.", "Ibid 34.", "case") == []


def test_n_reference():
    before = "Jane Smith, ‘Title’ (2010) 34 *Melbourne University Law Review* 1, 12."
    assert _explain(before, "Smith (n 3) 12.", "journal_article") == [("n_reference", "r 1.4.1")]
    assert _lines(before, "Smith (n 3) 12.", "journal_article") == [
        "Already cited in full at footnote 3, so shortened with ‘(n 3)’"]
    assert _lines("Smith, above n 3, 12.", "Smith (n 3) 12.", "journal_article") == [
        "AGLC4 refers back with ‘(n 3)’, not ‘above n 3’"]


# ---- other common fixes ----------------------------------------------------------- #


@pytest.mark.parametrize("before, after, types, expected", [
    ("Crimes Act 1900 (NSW) s 5.", "*Crimes Act 1900* (NSW) s 5.", ["legislation"], [("title_italic", "rr 3.1.1–3.1.2")]),
    ("*Crimes Act 1900 (NSW)* s 5.", "*Crimes Act 1900* (NSW) s 5.", ["legislation"], [("roman", "r 3.1.3")]),
    ("Mabo v Queensland (1992) 175 CLR 1.", "*Mabo v Queensland* (1992) 175 CLR 1.", ["case"], [("title_italic", "r 2.1.1")]),
    ("*Mabo v Queensland (1992) 175 CLR 1*.", "*Mabo v Queensland* (1992) 175 CLR 1.", ["case"], [("roman", "ch 2")]),
    ("Dworkin, Justice for Hedgehogs (Belknap Press, 2011) 10.", "Dworkin, *Justice for Hedgehogs* (Belknap Press, 2011) 10.",
     ["book"], [("title_italic", "r 6.2")]),
    ("*Mabo v Queensland (No 2)* (1992) 175 CLR 1.", "*Mabo v Queensland [No 2]* (1992) 175 CLR 1.", ["case"],
     [("case_number", "r 2.1.13")]),
    ("*Wik Peoples v Queensland* (1996) 187 CLR 1, 129 per Toohey J.", "*Wik Peoples v Queensland* (1996) 187 CLR 1, 129 (Toohey J).",
     ["case"], [("judges", "r 2.4.1")]),
    ("*Mabo v Queensland* (1992) 175 CLR 1 at 34.", "*Mabo v Queensland* (1992) 175 CLR 1, 34.", ["case"],
     [("pinpoint_comma", "r 2.2.5"), ("pinpoint_marker", "r 1.1.6")]),
    ("Ibid, at 45.", "Ibid 45.", ["case"], [("pinpoint_marker", "r 1.1.6")]),
    ("*Smith v Jones* (2005) 220 A.L.R. 1.", "*Smith v Jones* (2005) 220 ALR 1.", ["case"], [("abbreviation", "r 1.6.1")]),
    ("*Crimes Act 1900* (NSW), section 5.", "*Crimes Act 1900* (NSW) s 5.", ["legislation"],
     [("pinpoint_comma", "r 3.1.4"), ("section", "r 3.1.4")]),
    ("*R v Gomez* [1993] AC 442", "*R v Gomez* [1993] AC 442.", ["case"], [("full_stop", "r 1.1.4")]),
    ("J Smith, \"Native Title\" (1995) 19 *Melbourne University Law Review* 195.",
     "J Smith, ‘Native Title’ (1995) 19 *Melbourne University Law Review* 195.", ["journal_article"], [("quotes", "r 5.2")]),
])
def test_other_fixes(before, after, types, expected):
    assert _explain(before, after, *types) == expected


def test_unexplained_changes_get_one_closing_line():
    # A publisher's name shortened: no detector for it, so the chapter is named instead
    assert _explain("P Butt, *Land Law* (Lawbook Co, 6th ed, 2010) 45.", "P Butt, *Land Law* (Lawbook, 6th ed, 2010) 45.",
                    "book") == [("other", "ch 6")]
    lines = _lines("*Mabo v Queensland (No 2)* (1992) 175 CLR 1 and others.", "*Mabo v Queensland [No 2]* (1992) 175 CLR 1.",
                   "case")
    assert lines == ["A case’s number goes in square brackets: ‘[No 2]’",
                     "Other details set out in the AGLC4 form for a case"]


def test_unchanged_and_whitespace_only():
    assert _explain("*Crimes Act 1900* (NSW) s 5.", "*Crimes Act 1900* (NSW) s 5.", "legislation") == []
    assert _explain("*Crimes Act 1900*  (NSW) s 5.", "*Crimes Act 1900* (NSW) s 5.", "legislation") == []


# ---- wired through the document pass and the API ------------------------------------ #


def _case_footnote(number: int, original: str, pin: str) -> Footnote:
    citation = Citation.model_validate({
        "source": CaseSource(name="Mabo v Queensland [No 2]", year="1992", year_style="round", volume="175",
                             report="CLR", starting_page="1").model_dump(),
        "pinpoints": [{"kind": "page", "value": pin}], "source_key": "mabo"})
    return Footnote(number=number, original=_rich(original), segments=[CitationSegment(citation=citation)])


def test_render_document_explains_each_footnote():
    footnotes = [
        _case_footnote(1, "*Mabo v Queensland [No 2]* (1992) 175 CLR 1, 648-649.", "648-649"),
        _case_footnote(2, "*Mabo v Queensland [No 2]* (1992) 175 CLR 1, 650.", "650"),
    ]
    result = render_document(footnotes, bibliography=False)
    assert [c.kind for c in result.footnotes[0].changes] == ["span"]
    assert [c.kind for c in result.footnotes[1].changes] == ["ibid"]

    data = api._result_json("sid", result)
    assert data["footnotes"][0]["changes"] == [
        {"kind": "span", "text": "Page range shortened to ‘648–9’, with an en dash", "rule": "r 1.1.7"}]
    assert data["footnotes"][1]["changes"][0]["rule"] == "r 1.4.3"
