"""Tests for parliamentary materials: debates (AGLC4 r 7.5.1, r 24.4.1), explanatory
memoranda (r 3.7), research papers (r 7.2, incl r 7.2.3 parliamentary research papers)
and committee reports (r 7.1.2). Full citations of the guide's own examples are in
tests/aglc4_examples/parliamentary.json; these tests cover what those can't: repeat
references, normalisation, the bibliography and the coverage check."""

from aglc import validate
from aglc.document import render_document
from aglc.formatters import formatter_for
from aglc.formatters.base import BIB_LEGISLATION, BIB_OTHER, BIB_SECONDARY
from aglc.models import (
    Citation,
    CitationSegment,
    ExplanatoryMemorandumSource,
    Footnote,
    ParliamentaryDebatesSource,
    Pinpoint,
    ReportSource,
    ResearchPaperSource,
    RichText,
    TextSegment,
)
from aglc.normalise import normalise_citation

SPEAKMAN = ParliamentaryDebatesSource(
    jurisdiction="New South Wales", chamber="Legislative Assembly", date="30 March 2022",
    speaker="Mark Speakman", speaker_position="Attorney-General",
)
SPEAKMAN_FULL = (
    "New South Wales, *Parliamentary Debates*, Legislative Assembly, 30 March 2022, 8938 "
    "(Mark Speakman, Attorney-General)"
)
BENNETT = ResearchPaperSource(
    authors=["Scott Bennett"], title="The Rise of the Australian Greens", document_type="Research Paper",
    document_number="8", institution="Parliamentary Library, Parliament of Australia", date="22 September 2008",
)
ADOPTION_EN = ExplanatoryMemorandumSource(document_type="Explanatory Notes", title="Adoption Bill", year="2009", jurisdiction="Qld")
OTHER = ReportSource(author="Australian Law Reform Commission", title="Elder Abuse", document_type="Discussion Paper",
                     document_number="83", date="December 2016")


def _cite(source, page=None, **kw) -> Citation:
    pins = [Pinpoint(value=page)] if page else []
    return normalise_citation(Citation(source=source, pinpoints=pins, **kw))[0]


def _render(*footnotes: list[Citation]) -> list[str]:
    fns = [
        Footnote(number=i, original=RichText.plain("x"),
                 segments=[CitationSegment(citation=c) for c in cits] + [TextSegment(text=RichText.plain("."))])
        for i, cits in enumerate(footnotes, start=1)
    ]
    return [f.formatted.to_markup() for f in render_document(fns, bibliography=False).footnotes]


def _full(c: Citation) -> str:
    return formatter_for(c).full(c).to_markup()


# --------------------------------------------------------------------------- #
# Parliamentary debates (r 7.5.1)
# --------------------------------------------------------------------------- #


def test_hansard_short_title_is_defined_then_used_with_n():
    # r 1.4.1, 1.4.4: the author's short title, styled like *Parliamentary Debates*.
    out = _render([_cite(SPEAKMAN, "8938", short_title="Parliamentary Debates")], [_cite(OTHER)],
                  [_cite(SPEAKMAN, "8939")])
    assert out[0] == SPEAKMAN_FULL + " (‘*Parliamentary Debates*’)."
    assert out[2] == "*Parliamentary Debates* (n 1) 8939."


def test_hansard_ibid_changes_only_the_page():
    # r 1.4.3; r 1.4.6 example 92-93 ('Commonwealth, *Parliamentary Debates*, Senate, ... 2626' then 'Ibid 2625').
    out = _render([_cite(SPEAKMAN, "8938")], [_cite(SPEAKMAN, "8939")])
    assert out[1] == "Ibid 8939."


def test_hansard_without_a_short_title_is_repeated_in_full():
    # No author or title to shorten: repeating the citation is the only safe form.
    out = _render([_cite(SPEAKMAN, "8938")], [_cite(OTHER)], [_cite(SPEAKMAN, "8940")])
    assert out[2] == SPEAKMAN_FULL.replace("8938", "8940") + "."


def test_a_different_speaker_on_the_same_day_is_a_new_citation():
    other_speaker = SPEAKMAN.model_copy(update={"speaker": "Paul Lynch", "speaker_position": None})
    out = _render([_cite(SPEAKMAN, "8938", short_title="Parliamentary Debates")], [_cite(other_speaker, "8945")])
    assert out[1] == "New South Wales, *Parliamentary Debates*, Legislative Assembly, 30 March 2022, 8945 (Paul Lynch)."


def test_hansard_normaliser_spells_out_jurisdiction_and_chamber_and_strips_titles():
    # r 7.5.1: 'MP', 'Senator' etc are not included [Not: ... Senator the Hon George Brandis QC ...].
    messy = ParliamentaryDebatesSource(jurisdiction="Cth", chamber="Senate", date="7th February 2017",
                                       speaker="Senator the Hon George Brandis QC", speaker_position="Attorney-General")
    c, warnings = normalise_citation(Citation(source=messy, pinpoints=[Pinpoint(value="39")]))
    assert _full(c) == "Commonwealth, *Parliamentary Debates*, Senate, 7 February 2017, 39 (George Brandis, Attorney-General)"
    assert warnings == []
    nsw = _cite(ParliamentaryDebatesSource(jurisdiction="NSW", chamber="LA", date="30 March 2022",
                                           speaker="The Hon. Mark Speakman SC MP", speaker_position="Attorney-General"), "8938")
    assert _full(nsw) == SPEAKMAN_FULL
    assert nsw.source_key == _cite(SPEAKMAN, "1").source_key


def test_hansard_speaker_read_as_pinpoint_judges_moves_to_the_source():
    bare = SPEAKMAN.model_copy(update={"speaker": None, "speaker_position": None})
    c = _cite(bare, "8938", pinpoint_judges="Mark Speakman, Attorney-General")
    assert c.pinpoint_judges is None
    assert _full(c) == SPEAKMAN_FULL
    assert c.source_key == _cite(SPEAKMAN).source_key


def test_hansard_missing_chamber_is_flagged_not_invented():
    c, warnings = normalise_citation(Citation(source=ParliamentaryDebatesSource(jurisdiction="Victoria", date="14 December 2017")))
    assert _full(c) == "Victoria, *Parliamentary Debates*, [MISSING: chamber], 14 December 2017"
    assert warnings == ["Parliamentary debates missing chamber"]


def test_england_stays_england():
    # r 24.4.1: 'United Kingdom' is replaced with the polity shown in the volume.
    c = _cite(ParliamentaryDebatesSource(jurisdiction="England", chamber="House of Commons", date="1 May 1800"))
    assert c.source.jurisdiction == "England"


def test_hansard_goes_under_other_in_the_bibliography():
    c = _cite(SPEAKMAN, "8938")
    assert formatter_for(c).bibliography_category == BIB_OTHER
    assert formatter_for(c).bibliography(c).to_markup() == SPEAKMAN_FULL.replace(", 8938", "")


def test_hansard_and_its_speaker_titles_count_as_captured():
    source = SPEAKMAN.model_copy(update={"jurisdiction": "NSW"})
    seg = CitationSegment(citation=Citation(source=source, pinpoints=[Pinpoint(value="8938")]))
    original = "NSW Hansard, Legislative Assembly, 30 March 2022, 8938 (the Hon Mark Speakman MP, Attorney-General)."
    assert validate.missing_from_extraction(original, [seg]) == []


# --------------------------------------------------------------------------- #
# Explanatory memoranda (r 3.7)
# --------------------------------------------------------------------------- #


def test_explanatory_memorandum_title_year_and_jurisdiction_are_normalised():
    c = _cite(ExplanatoryMemorandumSource(title="Charter of Human Rights and Responsibilities Bill 2006", jurisdiction="Victoria"), "12")
    assert _full(c) == "Explanatory Memorandum, Charter of Human Rights and Responsibilities Bill 2006 (Vic) 12"


def test_explanatory_memorandum_short_title_is_roman():
    out = _render([_cite(ADOPTION_EN, "5", short_title="Explanatory Notes")], [_cite(OTHER)], [_cite(ADOPTION_EN, "29")])
    assert out[0] == "Explanatory Notes, Adoption Bill 2009 (Qld) 5 (‘Explanatory Notes’)."
    assert out[2] == "Explanatory Notes (n 1) 29."


def test_explanatory_memorandum_is_listed_with_legislation():
    assert formatter_for(_cite(ADOPTION_EN)).bibliography_category == BIB_LEGISLATION


# --------------------------------------------------------------------------- #
# Research papers (r 7.2, 7.2.3)
# --------------------------------------------------------------------------- #


def test_research_paper_subsequent_reference_uses_the_surname():
    # r 1.4.1
    out = _render([_cite(BENNETT, "15")], [_cite(OTHER)], [_cite(BENNETT, "16")])
    assert out[2] == "Bennett (n 1) 16."


def test_research_paper_by_a_body_does_not_repeat_it_as_institution():
    body = "Parliamentary Research Service, Parliament of New South Wales"
    c = _cite(ResearchPaperSource(authors=[body], title="Statutory Interpretation", document_type="Briefing Paper",
                                  document_number="3/2019", institution=body, date="May 2019"))
    assert _full(c) == f"{body}, ‘Statutory Interpretation’ (Briefing Paper No 3/2019, May 2019)"


def test_research_paper_without_author_starts_with_the_quoted_title():
    out = _render([_cite(BENNETT.model_copy(update={"authors": []}), "15")], [_cite(OTHER)],
                  [_cite(BENNETT.model_copy(update={"authors": []}), "16")])
    assert out[0].startswith("‘The Rise of the Australian Greens’ (Research Paper No 8,")
    assert out[2] == "‘The Rise of the Australian Greens’ (n 1) 16."


def test_research_paper_bibliography_inverts_the_first_author():
    c = _cite(BENNETT, "15")
    assert formatter_for(c).bibliography_category == BIB_SECONDARY
    assert formatter_for(c).bibliography(c).text.startswith("Bennett, Scott, ‘The Rise")
