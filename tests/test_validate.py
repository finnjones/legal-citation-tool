"""The deterministic no-loss / no-invention checks (aglc/validate.py) and how the
extractor uses them: repair round, then leave-unchanged fallback."""

import json

from aglc import validate as V
from aglc.extract import Extractor
from aglc.formatters import formatter_for
from aglc.formatters.base import _REGISTRY
from aglc.llm import get_provider
from aglc.models import (
    BookSource,
    CaseSource,
    Citation,
    CitationSegment,
    Footnote,
    Pinpoint,
    ReportSource,
    RichText,
    TextSegment,
)

ALRC = "Australian Law Reform Commission, For Your Information, Report No. 108 (May 2008) vol 1 at 339."
REPORT = {"type": "report", "author": "Australian Law Reform Commission", "title": "For Your Information",
          "document_type": "Report", "document_number": "108", "date": "May 2008"}


def _seg(citation: dict, original: str) -> dict:
    return {"kind": "citation", "original": original, "citation": citation}


def _batch(number: int, *segments: dict) -> str:
    return json.dumps({"footnotes": [{"number": number, "segments": list(segments)}]})


def _fn(number: int, text: str) -> Footnote:
    return Footnote(number=number, original=RichText.plain(text))


# ---- tokenising ------------------------------------------------------------------ #


def test_abbreviation_full_stops_do_not_matter():
    assert V.meaningful("(N.S.W.) C.L.R.") == V.meaningful("(NSW) CLR")


def test_shortened_spans_count_as_the_full_number():
    assert "155" in V.numbers("150–5")


# ---- 1. coverage ------------------------------------------------------------------ #


def test_dropped_volume_is_detected():
    seg = CitationSegment(citation=Citation(source=ReportSource(**{k: v for k, v in REPORT.items() if k != "type"}),
                                            pinpoints=[Pinpoint(value="339")]))
    assert V.missing_from_extraction(ALRC, [seg]) == ["1"]


def test_dropped_title_word_is_detected():
    seg = CitationSegment(citation=Citation(source=BookSource(title="The Law of Torts", editors=["C Sappideen"],
                                                              publisher="Lawbook", edition="10", year="2011")))
    assert "fleming's" in V.missing_from_extraction("C Sappideen (ed), Fleming's The Law of Torts (Lawbook, 10th ed, 2011).", [seg])


def test_complete_extraction_passes_even_when_reformatted():
    seg = CitationSegment(citation=Citation(
        source=CaseSource(name="Donoghue v Stevenson", year="1932", report="AC", starting_page="562"),
        pinpoints=[Pinpoint(value="580")], pinpoint_judges="Lord Atkin"))
    assert V.missing_from_extraction("Donoghue v. Stevenson [1932] A.C. 562 at 580 per Lord Atkin.", [seg]) == []


def test_commentary_in_text_segments_counts():
    segs = [TextSegment(text=RichText.plain("This was later confirmed: ")),
            CitationSegment(citation=Citation(source=CaseSource(name="A v B", year="2000", volume="1", report="CLR", starting_page="1")))]
    assert V.missing_from_extraction("This was later confirmed: A v B (2000) 1 CLR 1.", segs) == []


# ---- 2. grounding ------------------------------------------------------------------ #


def test_invented_edition_is_removed():
    c = Citation(source=BookSource(authors=["Ronald Dworkin"], title="Justice for Hedgehogs", publisher="Belknap Press",
                                   edition="1", year="2011"), pinpoints=[Pinpoint(value="10")])
    cleaned, notes = V.remove_invented_numbers(c, "Ronald Dworkin, Justice for Hedgehogs (Belknap Press 2011) p 10.")
    assert cleaned.source.edition is None and cleaned.source.year == "2011" and notes


def test_invented_pinpoint_is_removed():
    c = Citation(source=CaseSource(name="A v B", year="2000", volume="1", report="CLR", starting_page="1"),
                 pinpoints=[Pinpoint(value="99")])
    cleaned, _ = V.remove_invented_numbers(c, "A v B (2000) 1 CLR 1.")
    assert cleaned.pinpoints == []


# ---- 3. rendering ------------------------------------------------------------------ #


def test_rendering_check_catches_a_formatter_that_drops_a_field(monkeypatch):
    c = Citation(source=CaseSource(name="A v B", year="2000", volume="175", report="CLR", starting_page="1"))
    fn = Footnote(number=1, original=RichText.plain("x"), segments=[CitationSegment(citation=c)])
    assert V.check_footnote_rendering(fn, formatter_for) == []

    real = _REGISTRY["case"]

    class DropsVolume(type(real)):
        def full(self, citation):
            return RichText.plain("A v B (2000) CLR 1")

    monkeypatch.setitem(_REGISTRY, "case", DropsVolume())
    assert "175" in V.check_footnote_rendering(fn, formatter_for)[0]


# ---- extractor integration ------------------------------------------------------------ #


def test_repair_round_recovers_a_dropped_pinpoint():
    dropped = _batch(1, _seg({"source": REPORT, "pinpoints": [{"value": "339"}]}, ALRC[:-1]))
    fixed = _batch(1, _seg({"source": REPORT, "pinpoints": [{"kind": "volume", "value": "1"}, {"value": "339"}]}, ALRC[:-1]))
    provider = get_provider("fake:x", responses=[dropped, fixed])
    ex = Extractor(provider)
    out = ex.extract([_fn(1, ALRC)])
    assert [p.value for p in out[0].segments[0].citation.pinpoints] == ["1", "339"]
    assert len(provider.calls) == 2
    assert "'1'" in provider.calls[1]["user"]  # the repair prompt names what was missed
    assert ex.warnings == []


def test_footnote_left_unchanged_when_repair_fails():
    dropped = _batch(1, _seg({"source": REPORT, "pinpoints": [{"value": "339"}]}, ALRC[:-1]))
    ex = Extractor(get_provider("fake:x", responses=[dropped]))  # the repair repeats the same mistake
    out = ex.extract([_fn(1, ALRC)])
    assert len(out[0].segments) == 1 and isinstance(out[0].segments[0], TextSegment)
    assert out[0].segments[0].text.text == ALRC  # exactly as written
    assert any("left unchanged" in w for w in ex.warnings)


def test_non_strict_mode_keeps_the_extraction_but_warns():
    dropped = _batch(1, _seg({"source": REPORT, "pinpoints": [{"value": "339"}]}, ALRC[:-1]))
    ex = Extractor(get_provider("fake:x", responses=[dropped]), strict=False)
    out = ex.extract([_fn(1, ALRC)])
    assert isinstance(out[0].segments[0], CitationSegment)
    assert any("may have dropped" in w for w in ex.warnings)


def test_reference_footnote_numbers_are_not_reported_missing():
    first = {"number": 1, "segments": [_seg({"source": {"type": "case", "name": "Perre v Apand Pty Ltd", "year": "1999",
                                                       "volume": "198", "report": "CLR", "starting_page": "180"}},
                                             "Perre v Apand Pty Ltd (1999) 198 CLR 180")]}
    second = {"number": 4, "segments": [{"kind": "citation", "original": "Perre, above n 1, 225", "refers_to_footnote": 1,
                                         "citation": {"source": {"type": "other", "text": "x"}, "short_title": "Perre",
                                                      "pinpoints": [{"value": "225"}]}}]}
    provider = get_provider("fake:x", responses=[json.dumps({"footnotes": [first, second]})])
    ex = Extractor(provider)
    out = ex.extract([_fn(1, "Perre v Apand Pty Ltd (1999) 198 CLR 180."), _fn(4, "Perre, above n 1, 225.")])
    assert out[1].segments[0].citation.source.type == "case"
    assert ex.warnings == [] and len(provider.calls) == 1
