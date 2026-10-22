"""The offline check that a case cited by medium neutral citation exists (aglc/verify.py),
against a small stand-in for aglc/data/case_index.json.gz."""

import json

import pytest

from aglc import api, pipeline
from aglc import verify as V
from aglc.llm import get_provider
from aglc.models import CaseSource, Citation, Footnote, LegislationSource, RichText

INDEX = {
    "courts": {
        "HCA": {
            "scraped": "2024-09-13",
            "years": {
                "1956": {str(n): f"Case {n} v Someone" for n in range(1, 21)} | {"14": "Muir v Open Brethren"},
                # 2 of 10: the site barely has this year
                "1903": {"1": "D'Emden v Pedder", "10": "Other v Case"},
                # still being added to when the index was built
                "2024": {"1": "Recent v Case"},
            },
        },
        "FCA": {
            "scraped": "2024-09-13",
            "years": {
                "2003": {str(n): f"Party{n} v Respondent{n}" for n in range(1, 21)}
                | {"9": "Australian Competition & Consumer Commission v George Weston Foods Limited & Anor",
                   "10": ["AGV20 v Minister for Immigration", "AGV20 v Minister for Immigration (No 2)"]},
            },
        },
    },
    "unnumbered": {"HCA": {"?": ["Commissioner of Taxation (Cth) v Westfield Ltd"]}},
}


_LOADER = V._index  # the real one, which reads aglc/data/case_index.json.gz


@pytest.fixture(autouse=True)
def index(monkeypatch):
    monkeypatch.setattr(V, "_index", lambda: INDEX)


def _warning(citation: Citation) -> str | None:
    check = V.check_citation(citation)
    return check.warning if check else None


def _case(name: str, year: str | None, court: str | None, number: str | None) -> Citation:
    return Citation(source=CaseSource(name=name, year=year, court_id=court, judgment_number=number))


def test_real_case_passes():
    assert _warning(_case("Muir v Open Brethren", "1956", "HCA", "14")) is None


def test_number_the_court_never_reached_is_not_found():
    msg = _warning(_case("Smith v Jones", "1956", "HCA", "99"))
    assert msg == "Case not found: [1956] HCA 99 is past the court's last decision that year, [1956] HCA 20"


def test_number_just_past_the_last_one_indexed_is_not_flagged():
    # the Corpus may lack the year's last few decisions
    assert _warning(_case("Smith v Jones", "1956", "HCA", "23")) is None


def test_gap_in_a_covered_year_is_not_flagged(monkeypatch):
    # the Corpus lacks some real decisions, so a gap proves nothing
    gappy = json.loads(json.dumps(INDEX))
    del gappy["courts"]["HCA"]["years"]["1956"]["5"]
    monkeypatch.setattr(V, "_index", lambda: gappy)
    assert _warning(_case("Smith v Jones", "1956", "HCA", "5")) is None


def test_real_citation_for_another_case_is_a_name_mismatch():
    msg = _warning(_case("Smith v Jones", "1956", "HCA", "14"))
    assert msg == "Case name mismatch: [1956] HCA 14 is 'Muir v Open Brethren', not 'Smith v Jones'"


def test_name_is_checked_in_any_year_the_number_is_indexed():
    assert _warning(_case("Smith v Jones", "2024", "HCA", "1")).startswith("Case name mismatch")


@pytest.mark.parametrize("name", [
    "ACCC v George Weston Foods Ltd",
    "Australian Competition and Consumer Commission v George Weston Foods Ltd",
    "George Weston Foods",
])
def test_shortened_or_respelt_names_match(name):
    assert _warning(_case(name, "2003", "FCA", "9")) is None


def test_any_title_of_a_shared_number_matches():
    assert _warning(_case("AGV20 v Minister for Immigration, Citizenship and Multicultural Affairs [No 2]",
                                  "2003", "FCA", "10")) is None


def test_a_name_with_nothing_distinctive_is_not_checked():
    assert V.same_case("R v The Queen", "Muir v Open Brethren")


@pytest.mark.parametrize("year, court, number", [
    ("1903", "HCA", "5"),    # year the court's site barely has
    ("2024", "HCA", "999"),  # year the index was still being added to
    ("2026", "HCA", "1"),    # after the index was built
    ("1956", "VSC", "1"),    # court the index doesn't have
    ("1956", "HCA", "1a"),   # not a number
    (None, "HCA", "14"),
])
def test_citations_the_index_cant_answer_for_are_not_flagged(year, court, number):
    assert _warning(_case("Smith v Jones", year, court, number)) is None


def _reported(name: str, year: str, report: str = "CLR") -> Citation:
    return Citation(source=CaseSource(name=name, year=year, volume="95", report=report, starting_page="1"))


@pytest.mark.parametrize("name, year", [
    ("Muir v Open Brethren", "1956"),
    ("Muir v Open Brethren", "1957"),  # decided the year before it was reported
    ("Federal Commissioner of Taxation v Westfield Ltd", "1991"),  # a title without a number
])
def test_reported_case_found_by_name_is_checked(name, year):
    assert V.check_citation(_reported(name, year)) == V.CaseCheck(True)


@pytest.mark.parametrize("citation", [
    _reported("Smith v Jones", "1956"),           # no such decision: the index may just lack it
    _reported("Muir v Open Brethren", "1958"),    # not that year or the year before
    _reported("Muir v Open Brethren", "1956", "VR"),  # a report the index can't search
    _reported("R v R", "1956"),                   # nothing to search for
])
def test_reported_case_not_found_is_unchecked_not_flagged(citation):
    assert V.check_citation(citation) == V.CaseCheck(False)


def test_other_sources_are_not_cases():
    act = Citation(source=LegislationSource(title="Evidence Act", year="1995", jurisdiction="Cth"))
    assert V.check_citation(act) is None  # so not counted either


@pytest.mark.parametrize("cited, title, plausible", [
    ("Kvelde v The State of New South Wales", "Kvelde v State of New South Wales", True),
    ("ACCC v CG Berbatis Holdings Pty Ltd", "Australian Competition and Consumer Commission v CG Berbatis Holdings Pty Ltd", True),
    ("Kable v DPP (NSW)", "Kable v Director of Public Prosecutions (NSW)", True),
    ("Aust Broadcasting Corp v Lenah Game Meats", "Australian Broadcasting Corporation v Lenah Game Meats Pty Ltd", True),
    ("Re Colina; Ex parte Torney", "Re Colina; Ex parte Torney", True),
    ("Commissioner of Taxation v Johnson", "John Holland Group Pty Ltd v Commissioner of Taxation", False),
    ("Smith v Jones", "Smith v Commonwealth", False),  # every party must match
])
def test_plausible_name(cited, title, plausible):
    assert V.plausible_name(cited, title) is plausible


@pytest.mark.parametrize("year, number, checked", [
    ("1956", "14", True),   # in the index
    ("1956", "99", True),   # past the court's last decision
    ("1956", "23", False),  # just past the last one indexed
    ("1903", "5", False),   # a gap in a year the index barely has
    ("2026", "1", False),   # after the index was built
])
def test_check_says_whether_the_index_could_answer(year, number, checked):
    assert V.check_citation(_case("Muir v Open Brethren", year, "HCA", number)).checked is checked


def test_no_index_checks_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "_index", _LOADER)
    monkeypatch.setattr(V, "_INDEX", tmp_path / "missing.json.gz")
    _LOADER.cache_clear()
    try:
        assert _warning(_case("Smith v Jones", "1956", "HCA", "99")) is None
    finally:
        _LOADER.cache_clear()


def test_pipeline_reports_a_missing_case_as_a_footnote_warning():
    raw = json.dumps({"footnotes": [{"number": 1, "segments": [{
        "kind": "citation", "original": "Smith v Jones [1956] HCA 99 [3].",
        "citation": {"source": {"type": "case", "name": "Smith v Jones", "year": "1956",
                                "court_id": "HCA", "judgment_number": "99"},
                     "pinpoints": [{"kind": "paragraph", "value": "3"}]},
    }]}]})
    footnote = Footnote(number=1, original=RichText.plain("Smith v Jones [1956] HCA 99 [3]."))
    result = pipeline.process_footnotes([footnote], get_provider("fake:x", responses=[raw]), bibliography=False)
    assert any(w.footnote == 1 and w.message.startswith("Case not found: [1956] HCA 99") for w in result.warnings)
    assert pipeline.warning_kinds(result)["case not found"] == 1


def test_each_case_is_counted_and_flagged_once():
    fake = {"type": "case", "name": "Smith v Jones", "year": "1956", "court_id": "HCA", "judgment_number": "99"}
    reported = {"type": "case", "name": "Tame v New South Wales", "year": "2002", "volume": "211",
                "report": "CLR", "starting_page": "317"}
    texts = {1: "Smith v Jones [1956] HCA 99.", 2: "Smith v Jones [1956] HCA 99.",
             3: "Tame v New South Wales (2002) 211 CLR 317."}
    sources = {1: fake, 2: fake, 3: reported}
    raw = json.dumps({"footnotes": [
        {"number": n, "segments": [{"kind": "citation", "original": texts[n], "citation": {"source": sources[n]}}]}
        for n in texts
    ]})
    footnotes = [Footnote(number=n, original=RichText.plain(t)) for n, t in texts.items()]
    result = pipeline.process_footnotes(footnotes, get_provider("fake:x", responses=[raw]), bibliography=False)
    assert [w.footnote for w in result.warnings if w.message.startswith("Case not found")] == [1]
    assert result.case_check.model_dump() == {"total": 2, "checked": 1, "flagged": 1}
    assert api._result_json("s", result)["case_check"] == {"total": 2, "checked": 1, "flagged": 1}
