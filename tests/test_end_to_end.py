"""Whole pipeline on a real .docx: read footnotes -> extract (canned LLM output via the
fake provider) -> normalise -> document pass -> write tracked changes -> read back."""

import zipfile
from pathlib import Path

import docx
import pytest

from aglc import pipeline
from aglc.docx_io import read_footnotes
from aglc.extract import Extractor
from aglc.llm import get_provider
from aglc.models import CitationSegment, Footnote, RichText, Run, TextSegment

FIXTURES = Path(__file__).parent / "fixtures"
ESSAY = FIXTURES / "sample_essay.docx"
EXTRACTION = (FIXTURES / "sample_essay_extraction.json").read_text()

EXPECTED = {
    1: "*Mabo v Queensland [No 2]* (1992) 175 CLR 1, 42 (Brennan J) (‘*Mabo*’).",
    2: "See *Competition and Consumer Act 2010* (Cth) s 18.",
    3: "Ibid 45.",
    4: "*Mabo* (n 1) 60.",
    5: "*Smith v Jones* (2005) 220 ALR 1; *Attorney-General (NSW) v X* (2001) 53 NSWLR 1.",
    6: "J Smith, ‘Native Title and the Common Law’ (1995) 19 *Melbourne University Law Review* 195.",
    7: "P Butt, *Land Law* (Lawbook, 6th ed, 2010) 45.",  # r 6.3.1 drops "Co"
    8: "This principle was later confirmed by the Court: *Wik Peoples v Queensland* (1996) 187 CLR 1, 129 (Toohey J).",
    9: "‘Native Title Report 2017’, *Australian Human Rights Commission* (Web Page, 2017) "
    "<https://humanrights.gov.au/native-title-report-2017>.",
    10: "Australian Law Reform Commission, *Connection to Country: Review of the Native Title Act 1993 (Cth)* "
    "(Report No 126, 2015) 34.",
}


@pytest.fixture
def provider():
    return get_provider("fake:e2e", responses=[EXTRACTION])


@pytest.mark.parametrize("track_changes", [True, False])
def test_process_docx_end_to_end(tmp_path, provider, track_changes):
    out = tmp_path / "out.docx"
    result = pipeline.process_docx(ESSAY, out, provider, track_changes=track_changes)

    assert {f.number: f.formatted.to_markup() for f in result.footnotes} == EXPECTED
    assert result.warnings == []

    # What Word shows (with tracked changes accepted) is the formatted text.
    reread = {f.number: f.original.to_markup() for f in read_footnotes(out)}
    assert reread == EXPECTED

    # Bibliography: grouped per r 1.13, and the output is a valid Word package.
    headings = [s.heading for s in result.bibliography]
    assert headings == ["A Articles/Books/Reports", "B Cases", "C Legislation"]
    docx.Document(str(out))  # opens as a valid package
    with zipfile.ZipFile(out) as z:
        body = z.read("word/document.xml").decode()
    assert "Bibliography" in body and "Mabo v Queensland [No 2]" in body
    # tracked mode inserts the bibliography as a tracked change; clean mode doesn't
    assert ("<w:ins " in body) is track_changes


def test_single_llm_call_for_small_document(tmp_path, provider):
    pipeline.process_docx(ESSAY, tmp_path / "out.docx", provider)
    assert len(provider.calls) == 1


# ---- regressions found by the end-to-end run -------------------------------- #


def _fn(runs: list[Run]) -> Footnote:
    return Footnote(number=1, original=RichText(runs=runs))


def _extract(footnote: Footnote, segments: list[dict]) -> list:
    import json

    raw = json.dumps({"footnotes": [{"number": 1, "segments": segments}]})
    return Extractor(get_provider("fake:x", responses=[raw]), verify=False).extract([footnote])[0].segments


def test_citation_matching_tolerates_tabs_newlines_and_quotes():
    fn = _fn([Run(text="J Smith,\t'Native Title'\n(1995) 19 "), Run(text="MULR", italic=True), Run(text=" 195.")])
    segs = _extract(
        fn,
        [{"kind": "citation", "original": "J Smith, ‘Native Title’ (1995) 19 MULR 195",
          "citation": {"source": {"type": "other", "text": "x"}}}],
    )
    # the whole footnote was matched, so nothing is re-appended as leftover text
    assert len(segs) == 1 and isinstance(segs[0], CitationSegment)


def test_separator_text_keeps_its_trailing_space():
    fn = _fn([Run(text="A v B (2000) 1 CLR 1; C v D (2001) 2 CLR 2.")])
    segs = _extract(
        fn,
        [
            {"kind": "citation", "original": "A v B (2000) 1 CLR 1", "citation": {"source": {"type": "other", "text": "a"}}},
            {"kind": "text", "text": "; "},
            {"kind": "citation", "original": "C v D (2001) 2 CLR 2", "citation": {"source": {"type": "other", "text": "c"}}},
        ],
    )
    assert isinstance(segs[1], TextSegment) and segs[1].text.text == "; "
    assert len(segs) == 3
