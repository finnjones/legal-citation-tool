"""Tests for parliamentary materials: debates (AGLC4 r 7.5.1, r 24.4.1), submissions
(r 7.5.2), committee evidence (r 7.5.3), convention debates (r 7.5.4), explanatory
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
    CommitteeEvidenceSource,
    ConventionDebatesSource,
    ExplanatoryMemorandumSource,
    Footnote,
    ParliamentaryDebatesSource,
    Pinpoint,
    ReportSource,
    ResearchPaperSource,
    RichText,
    SubmissionSource,
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
MOBIL = SubmissionSource(
    author="Mobil Oil Australia", submission_number="25", body="Australian Competition and Consumer Commission",
    inquiry="Inquiry into the Price of Unleaded Petrol", date="27 July 2007",
)
MOBIL_FULL = (
    "Mobil Oil Australia, Submission No 25 to Australian Competition and Consumer Commission, "
    "*Inquiry into the Price of Unleaded Petrol* (27 July 2007)"
)
ANON = SubmissionSource(submission_number="12", body="Law Reform Committee", legislature="Parliament of Victoria",
                        inquiry="Inquiry into Drug Law Reform", date="2017")
HOUSTON = CommitteeEvidenceSource(
    committee="Senate Standing Committee on Foreign Affairs, Defence and Trade", legislature="Parliament of Australia",
    location="Canberra", date="26 February 2007", speaker="Angus Houston", speaker_position="Air Chief Marshal",
)
HOUSTON_FULL = (
    "Evidence to Senate Standing Committee on Foreign Affairs, Defence and Trade, Parliament of Australia, "
    "Canberra, 26 February 2007, 12 (Angus Houston, Air Chief Marshal)"
)
BARTON = ConventionDebatesSource(title="Official Record of the Debates of the Australasian Federal Convention",
                                 location="Sydney", date="2 September 1897", speaker="Edmund Barton")
BARTON_FULL = "*Official Record of the Debates of the Australasian Federal Convention*, Sydney, 2 September 1897, 19 (Edmund Barton)"
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


# --------------------------------------------------------------------------- #
# Submissions (r 7.5.2)
# --------------------------------------------------------------------------- #


def test_submission_subsequent_reference_uses_the_author():
    # r 1.4.1: a body that is the author is repeated in full.
    out = _render([_cite(MOBIL, "6–7")], [_cite(OTHER)], [_cite(MOBIL, "8")], [_cite(MOBIL, "9")])
    assert out[0] == MOBIL_FULL + " 6–7."
    assert out[2] == "Mobil Oil Australia (n 1) 8."
    assert out[3] == "Ibid 9."
    out = _render([_cite(MOBIL, "6", short_title="Mobil Submission")], [_cite(OTHER)], [_cite(MOBIL, "8")])
    assert out[0] == MOBIL_FULL + " 6 (‘Mobil Submission’)."
    assert out[2] == "Mobil Submission (n 1) 8."


def test_two_submissions_by_one_author_add_the_inquiry():
    # r 1.4.1: several works by the same author are told apart by their (italic) title.
    second = MOBIL.model_copy(update={"submission_number": "4", "inquiry": "Petrol Prices and Australian Consumers",
                                      "date": "2007"})
    out = _render([_cite(MOBIL, "6")], [_cite(second, "2")], [_cite(MOBIL, "7")])
    assert out[2] == "Mobil Oil Australia, *Inquiry into the Price of Unleaded Petrol* (n 1) 7."


def test_anonymous_submission_is_repeated_in_full_or_by_its_short_title():
    out = _render([_cite(ANON, "3")], [_cite(OTHER)], [_cite(ANON, "4")])
    assert out[0] == ("Submission No 12 to Law Reform Committee, Parliament of Victoria, "
                      "*Inquiry into Drug Law Reform* (2017) 3.")
    assert out[2] == out[0].replace(") 3.", ") 4.")
    out = _render([_cite(ANON, "3", short_title="Submission 12")], [_cite(OTHER)], [_cite(ANON, "4")])
    assert out[0].endswith("(2017) 3 (‘Submission 12’).")
    assert out[2] == "Submission 12 (n 1) 4."


def test_submission_normaliser_drops_anonymous_and_the_royal_commissions_inquiry():
    # r 7.5.2: no author if anonymous; no inquiry name for a royal commission.
    c, warnings = normalise_citation(Citation(source=SubmissionSource(
        author="Anonymous", submission_number="No. 489", body="to the Royal Commission into Family Violence",
        inquiry="Royal Commission into Family Violence", date="29th May 2015")))
    assert _full(c) == "Submission No 489 to the Royal Commission into Family Violence (29 May 2015)"
    assert warnings == []
    moved = _cite(SubmissionSource(author="Anonymous 489", inquiry="Royal Commission into Family Violence", date="29 May 2015"))
    assert _full(moved) == "Anonymous 489, Submission to Royal Commission into Family Violence (29 May 2015)"


def test_submission_missing_its_body_is_flagged():
    c, warnings = normalise_citation(Citation(source=SubmissionSource(author="Mobil Oil Australia", date="2007")))
    assert _full(c) == "Mobil Oil Australia, Submission to [MISSING: body] (2007)"
    assert warnings == ["Submission missing the body it was made to"]


WILLIAMS = SubmissionSource(
    author="George Williams", author_is_body=False, submission_number="7", body="Senate Legal and Constitutional "
    "Affairs Committee", legislature="Parliament of Australia", inquiry="Inquiry into a Bill of Rights", date="2009",
)
WILLIAMS_FULL = ("George Williams, Submission No 7 to Senate Legal and Constitutional Affairs Committee, "
                 "Parliament of Australia, *Inquiry into a Bill of Rights* (2009)")


def test_submission_by_a_person_uses_the_surname():
    # r 1.4.1: 'Williams (n 1)', even where a short title was introduced.
    out = _render([_cite(WILLIAMS, "3")], [_cite(OTHER)], [_cite(WILLIAMS, "4")])
    assert out[0] == WILLIAMS_FULL + " 3."
    assert out[2] == "Williams (n 1) 4."
    out = _render([_cite(WILLIAMS, "3", short_title="Williams Submission")], [_cite(OTHER)], [_cite(WILLIAMS, "4")])
    assert out[2] == "Williams (n 1) 4."


def test_submission_by_a_person_is_inverted_in_the_bibliography():
    # r 1.13: the author's name is inverted.
    c = _cite(WILLIAMS, "3")
    assert formatter_for(c).bibliography(c).to_markup() == WILLIAMS_FULL.replace("George Williams,", "Williams, George,")


def test_two_submissions_by_one_person_add_the_inquiry():
    second = WILLIAMS.model_copy(update={"submission_number": "2", "inquiry": "Inquiry into Human Rights"})
    out = _render([_cite(WILLIAMS, "3")], [_cite(second, "2")], [_cite(WILLIAMS, "5")])
    assert out[2] == "Williams, *Inquiry into a Bill of Rights* (n 1) 5."


def test_submission_by_a_body_keeps_its_whole_name():
    # 'Mobil Oil Australia (n 50) 7', not 'Australia'; nor is it inverted.
    body = MOBIL.model_copy(update={"author_is_body": True})
    out = _render([_cite(body, "6")], [_cite(OTHER)], [_cite(body, "7")])
    assert out[2] == "Mobil Oil Australia (n 1) 7."
    c = _cite(body, "6")
    assert formatter_for(c).bibliography(c).to_markup() == MOBIL_FULL
    code = ANON.model_copy(update={"author": "Anonymous 489", "author_is_body": True})
    out = _render([_cite(code, "3")], [_cite(OTHER)], [_cite(code, "4")])
    assert out[2] == "Anonymous 489 (n 1) 4."


def test_unmarked_submission_author_is_never_cut_to_a_surname():
    # Without the extraction's flag the name is treated as a body's: most submissions are
    # by bodies the corporate-author word list doesn't know.
    out = _render([_cite(ANON.model_copy(update={"author": "Anonymous 489"}), "3")], [_cite(OTHER)],
                  [_cite(ANON.model_copy(update={"author": "Anonymous 489"}), "4")])
    assert out[2] == "Anonymous 489 (n 1) 4."
    c = _cite(MOBIL, "6")
    assert formatter_for(c).bibliography_category == BIB_OTHER
    assert formatter_for(c).bibliography(c).to_markup() == MOBIL_FULL


def test_submission_words_count_as_captured():
    seg = CitationSegment(citation=Citation(source=ANON, pinpoints=[Pinpoint(value="3")]))
    original = "Anonymous, Sub No 12 to Law Reform Committee, Parliament of Victoria, Inquiry into Drug Law Reform (2017) 3."
    assert validate.missing_from_extraction(original, [seg]) == []


# --------------------------------------------------------------------------- #
# Evidence to parliamentary committees (r 7.5.3)
# --------------------------------------------------------------------------- #


def test_committee_evidence_is_repeated_in_full_without_a_short_title():
    out = _render([_cite(HOUSTON, "12")], [_cite(OTHER)], [_cite(HOUSTON, "14")], [_cite(HOUSTON, "15")])
    assert out[0] == HOUSTON_FULL + "."
    assert out[2] == HOUSTON_FULL.replace(", 12 (", ", 14 (") + "."
    assert out[3] == "Ibid 15."


def test_committee_evidence_short_title_is_defined_then_used():
    out = _render([_cite(HOUSTON, "12", short_title="Houston Evidence")], [_cite(OTHER)], [_cite(HOUSTON, "14")])
    assert out[0] == HOUSTON_FULL + " (‘Houston Evidence’)."
    assert out[2] == "Houston Evidence (n 1) 14."


def test_a_different_witness_at_the_same_hearing_is_a_new_citation():
    other = HOUSTON.model_copy(update={"speaker": "Brendan Nelson", "speaker_position": None})
    out = _render([_cite(HOUSTON, "12", short_title="Houston Evidence")], [_cite(other, "20")])
    assert out[1] == HOUSTON_FULL.replace("12 (Angus Houston, Air Chief Marshal)", "20 (Brendan Nelson)") + "."


def test_committee_evidence_normaliser_strips_titles_and_the_committee_page_prefix():
    # r 7.5.3 note: 'SL&C' etc before Committee Hansard page numbers are omitted.
    bare = HOUSTON.model_copy(update={"committee": "Evidence to " + HOUSTON.committee, "speaker": None,
                                      "speaker_position": None, "date": "26th February 2007"})
    c, warnings = normalise_citation(Citation(source=bare, pinpoints=[Pinpoint(value="FAD&T 12")],
                                              pinpoint_judges="Air Chief Marshal Angus Houston, Air Chief Marshal"))
    assert c.pinpoint_judges is None and warnings == []
    assert c.source.speaker == "Air Chief Marshal Angus Houston"  # ranks aren't titles we can safely strip
    c = _cite(HOUSTON.model_copy(update={"speaker": "Mr Peter Strong"}), "SL&C 2")
    assert _full(c).endswith(", 2 (Peter Strong, Air Chief Marshal)")
    assert c.source_key == _cite(HOUSTON.model_copy(update={"speaker": "Peter Strong"})).source_key


def test_committee_evidence_missing_fields_are_flagged_not_invented():
    c = _cite(CommitteeEvidenceSource(committee="Senate Economics References Committee", date="1 May 2020"), "3")
    assert _full(c) == ("Evidence to Senate Economics References Committee, [MISSING: legislature], "
                        "[MISSING: location], 1 May 2020, 3")


def test_committee_evidence_and_witness_titles_count_as_captured():
    seg = CitationSegment(citation=Citation(source=HOUSTON.model_copy(update={"speaker": "Peter Strong", "speaker_position": None}),
                                            pinpoints=[Pinpoint(value="12")]))
    original = ("Proof Committee Hansard, Senate Standing Committee on Foreign Affairs, Defence and Trade, Parliament of "
                "Australia, Canberra, 26 February 2007, 12 (Mr Peter Strong).")
    assert validate.missing_from_extraction(original, [seg]) == []


# --------------------------------------------------------------------------- #
# Australasian federal convention debates (r 7.5.4)
# --------------------------------------------------------------------------- #


def test_convention_debates_are_repeated_in_full_without_a_short_title():
    # Every day of a convention has the same title, so the title can't be the short form.
    out = _render([_cite(BARTON, "19")], [_cite(OTHER)], [_cite(BARTON, "20")], [_cite(BARTON, "21")])
    assert out[0] == BARTON_FULL + "."
    assert out[2] == BARTON_FULL.replace(", 19 (", ", 20 (") + "."
    assert out[3] == "Ibid 21."


def test_convention_debates_short_title_is_italic():
    out = _render([_cite(BARTON, "19", short_title="Convention Debates")], [_cite(OTHER)], [_cite(BARTON, "20")])
    assert out[0] == BARTON_FULL + " (‘*Convention Debates*’)."
    assert out[2] == "*Convention Debates* (n 1) 20."


def test_convention_speaker_drops_titles_but_keeps_sir():
    # r 7.5.4: titles such as 'the Hon', 'Mr' and 'Dr' are omitted, but not 'Sir'.
    c = _cite(BARTON.model_copy(update={"speaker": "Mr Edmund Barton QC"}), "19")
    assert _full(c) == BARTON_FULL
    downer = _cite(BARTON.model_copy(update={"speaker": "the Hon Sir John Downer"}))
    assert downer.source.speaker == "Sir John Downer"
    moved = _cite(BARTON.model_copy(update={"speaker": None}), "19", pinpoint_judges="Mr Edmund Barton")
    assert moved.pinpoint_judges is None and _full(moved) == BARTON_FULL


def test_convention_debates_go_under_other_in_the_bibliography():
    c = _cite(BARTON, "19")
    assert formatter_for(c).bibliography_category == BIB_OTHER
    assert formatter_for(c).bibliography(c).to_markup() == BARTON_FULL.replace(", 19", "")
