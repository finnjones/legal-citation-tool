"""Regressions found by the first real run (DeepSeek V4 Flash via OpenRouter on
examples/test_essay.docx). Each test reproduces what the model actually returned."""

import json

from aglc.document import render_document
from aglc.extract import Extractor
from aglc.formatters import formatter_for
from aglc.llm import get_provider
from aglc.models import (
    CaseSource,
    Citation,
    CitationSegment,
    Footnote,
    LegislationSource,
    Pinpoint,
    RichText,
    TextSegment,
    TreatySource,
    WebsiteSource,
)
from aglc.normalise import normalise_citation


def _norm(c: Citation) -> Citation:
    return normalise_citation(c)[0]


def _full(c: Citation) -> str:
    c = _norm(c)
    return formatter_for(c).full(c).to_markup()


def _extract(footnotes: list[Footnote], llm_footnotes: list[dict]) -> list[Footnote]:
    raw = json.dumps({"footnotes": llm_footnotes})
    ex = Extractor(get_provider("fake:x", responses=[raw]))
    return ex.extract(footnotes)


def _fn(n: int, text: str) -> Footnote:
    return Footnote(number=n, original=RichText.plain(text))


# ---- formatter / normaliser ------------------------------------------------- #


def test_commonwealth_constitution_has_no_year_or_jurisdiction():
    c = Citation(
        source=LegislationSource(kind="constitution", title="Commonwealth Constitution", jurisdiction="Cth"),
        pinpoints=[Pinpoint(kind="section", value="51(xxix)")],
    )
    assert _full(c) == "*Australian Constitution* s 51(xxix)"
    assert normalise_citation(c)[1] == []  # no spurious "missing year" warning


def test_treaty_series_abbreviation_loses_full_stops():
    c = Citation(
        source=TreatySource(
            title="International Covenant on Civil and Political Rights",
            opened_for_signature="16 December 1966",
            treaty_series="999 U.N.T.S. 171",
            entry_into_force="23 March 1976",
        ),
        pinpoints=[Pinpoint(kind="article", value="14")],
    )
    assert _full(c) == (
        "*International Covenant on Civil and Political Rights*, opened for signature 16 December 1966, "
        "999 UNTS 171 (entered into force 23 March 1976) art 14"
    )


def test_medium_neutral_citation_pinpoints_are_paragraphs():
    c = Citation(
        source=CaseSource(name="Kuhl v Zurich Financial Services Australia Ltd", year="2011", court_id="HCA", judgment_number="11"),
        pinpoints=[Pinpoint(kind="page", value="20")],
    )
    assert _full(c) == "*Kuhl v Zurich Financial Services Australia Ltd* [2011] HCA 11, [20]"


def test_body_author_of_website_becomes_website_name():
    c = Citation(
        source=WebsiteSource(
            authors=["High Court of Australia"],
            title="James Edelman",
            url="http://www.hcourt.gov.au/justices/current/justice-james-edelman",
        )
    )
    assert "[MISSING" not in _full(c)
    assert _full(c).startswith("‘James Edelman’, *High Court of Australia*")


# ---- document pass ------------------------------------------------------------ #


def test_bare_semicolon_before_a_new_signal_becomes_a_new_sentence():
    a = _norm(Citation(source=LegislationSource(title="Wrongs Act", year="1958", jurisdiction="Vic"),
                       pinpoints=[Pinpoint(kind="section", value="48")], signal="See also"))
    b = _norm(Citation(source=LegislationSource(title="Civil Liability Act", year="2003", jurisdiction="Qld"),
                       pinpoints=[Pinpoint(kind="section", value="9")], signal="Cf"))
    fn = Footnote(number=8, original=RichText.plain("x"), segments=[
        CitationSegment(citation=a), TextSegment(text=RichText.plain("; ")), CitationSegment(citation=b),
        TextSegment(text=RichText.plain(".")),
    ])
    out = render_document([fn], bibliography=False).footnotes[0].formatted.to_markup()
    assert out == "See also *Wrongs Act 1958* (Vic) s 48. Cf *Civil Liability Act 2003* (Qld) s 9."


# ---- extraction ----------------------------------------------------------------- #

LUNTZ = {"type": "journal_article", "authors": ["Harold Luntz"], "title": "A Personal Journey through the Law of Torts",
         "year": "2005", "volume": "27", "issue": "3", "journal": "Sydney Law Review", "starting_page": "393"}


def test_op_cit_resolves_by_author_surname():
    fns = [_fn(11, "Harold Luntz, 'A Personal Journey through the Law of Torts' (2005) 27(3) Sydney Law Review 393, 400."),
           _fn(14, "Luntz, op cit, 402.")]
    out = _extract(fns, [
        {"number": 11, "segments": [{"kind": "citation", "original": fns[0].original.text[:-1],
                                     "citation": {"source": LUNTZ, "pinpoints": [{"kind": "page", "value": "400"}]}}]},
        {"number": 14, "segments": [{"kind": "citation", "original": "Luntz, op cit, 402", "refers_to_footnote": 11,
                                     "citation": {"source": {"type": "other", "text": "Luntz, op cit, 402"},
                                                  "short_title": "Luntz", "pinpoints": [{"kind": "page", "value": "402"}]}}]},
    ])
    cit = out[1].segments[0].citation
    assert cit.source.type == "journal_article" and cit.pinpoints[0].value == "402"


def test_unresolvable_reference_does_not_repeat_the_pinpoint():
    fns = [_fn(3, "Smith, op cit, 402.")]
    out = _extract(fns, [{"number": 3, "segments": [{"kind": "citation", "original": "Smith, op cit, 402", "refers_to_footnote": 1,
                                                     "citation": {"source": {"type": "other", "text": "x"}, "short_title": "Smith",
                                                                  "pinpoints": [{"kind": "page", "value": "402"}]}}]}])
    rendered = render_document(out, bibliography=False).footnotes[0].formatted.text
    assert rendered.count("402") == 1


def test_signal_left_outside_every_segment_is_recovered():
    fns = [_fn(4, "See: Perre v. Apand Pty. Ltd. (1999) 198 C.L.R. 180.")]
    out = _extract(fns, [{"number": 4, "segments": [{"kind": "citation", "original": "Perre v. Apand Pty. Ltd. (1999) 198 C.L.R. 180",
                                                     "citation": {"source": {"type": "case", "name": "Perre v Apand Pty Ltd", "year": "1999",
                                                                             "volume": "198", "report": "CLR", "starting_page": "180"}}}]}])
    assert out[0].segments[0].citation.signal == "See"


def test_signal_duplicated_in_preceding_text_is_removed():
    text = "For a strong statement of this view, see Ronald Dworkin, Justice for Hedgehogs (Belknap Press, 2011) 10."
    fns = [_fn(13, text)]
    out = _extract(fns, [{"number": 13, "segments": [
        {"kind": "text", "text": "For a strong statement of this view, see "},
        {"kind": "citation", "original": "Ronald Dworkin, Justice for Hedgehogs (Belknap Press, 2011) 10",
         "citation": {"source": {"type": "book", "authors": ["Ronald Dworkin"], "title": "Justice for Hedgehogs",
                                 "publisher": "Belknap Press", "year": "2011"},
                      "pinpoints": [{"kind": "page", "value": "10"}], "signal": "See"}},
    ]}])
    for fn in out:
        for seg in fn.segments:
            if isinstance(seg, CitationSegment):
                seg.citation = _norm(seg.citation)
    rendered = render_document(out, bibliography=False).footnotes[0].formatted.to_markup()
    assert rendered == "For a strong statement of this view, see Ronald Dworkin, *Justice for Hedgehogs* (Belknap Press, 2011) 10."


def test_footnote_skipped_by_model_is_retried_alone():
    fns = [_fn(1, "A v B (2000) 1 CLR 1."), _fn(2, "C v D (2001) 2 CLR 2.")]
    first = {"footnotes": [
        {"number": 1, "segments": [{"kind": "citation", "original": "A v B (2000) 1 CLR 1",
                                    "citation": {"source": {"type": "case", "name": "A v B"}}}]},
        {"number": 2, "segments": []},
    ]}
    retry = {"footnotes": [{"number": 2, "segments": [{"kind": "citation", "original": "C v D (2001) 2 CLR 2",
                                                        "citation": {"source": {"type": "case", "name": "C v D"}}}]}]}
    provider = get_provider("fake:x", responses=[json.dumps(first), json.dumps(retry)])
    out = Extractor(provider).extract(fns)
    assert out[1].segments[0].citation.source.name == "C v D"
    assert len(provider.calls) == 2


# ---- second real run ---------------------------------------------------------- #

from aglc.models import BookChapterSource, BookSource, ReportSource  # noqa: E402


def test_report_series_mistaken_for_court_identifier():
    c = Citation(
        source=CaseSource(name="Donoghue v Stevenson", year="1932", court_id="A.C.", judgment_number="562"),
        pinpoints=[Pinpoint(kind="page", value="580")],
        pinpoint_judges="Lord Atkin",
    )
    assert _full(c) == "*Donoghue v Stevenson* [1932] AC 562, 580 (Lord Atkin)"
    assert normalise_citation(c)[1] == []


def test_page_spans_are_shortened_but_paragraph_spans_are_not():
    book = BookSource(authors=["P Butt"], title="Land Law", publisher="Lawbook", year="2010")
    assert _full(Citation(source=book, pinpoints=[Pinpoint(kind="page", value="150-155")])).endswith(" 150–5")
    assert _full(Citation(source=book, pinpoints=[Pinpoint(kind="page", value="215-219")])).endswith(" 215–19")
    case = CaseSource(name="Sullivan v Moody", year="2001", volume="207", report="CLR", starting_page="562")
    assert _full(Citation(source=case, pinpoints=[Pinpoint(kind="paragraph", value="55-60")])).endswith("[55]–[60]")


def test_publisher_company_terms_are_dropped():
    book = BookSource(editors=["C Sappideen", "P Vines"], title="Fleming's The Law of Torts",
                      publisher="Lawbook Co.", edition="10", year="2011")
    assert "(Lawbook, 10th ed, 2011)" in _full(Citation(source=book))


def test_final_report_moves_from_title_into_the_brackets():
    rep = ReportSource(title="Review of the Law of Negligence: Final Report", document_type="Report", date="September 2002")
    c = Citation(source=rep, pinpoints=[Pinpoint(kind="page", value="25-27")])
    assert _full(c) == "*Review of the Law of Negligence* (Final Report, September 2002) 25–7"
    assert normalise_citation(c)[1] == []


def test_lone_page_number_on_a_chapter_is_its_starting_page():
    ch = BookChapterSource(authors=["Jeremy Waldron"], chapter_title="Do Judges Reason Morally?", editors=["G Huscroft"],
                           book_title="Expounding the Constitution: Essays in Constitutional Theory",
                           publisher="Cambridge University Press", year="2008")
    c = Citation(source=ch, pinpoints=[Pinpoint(kind="page", value="38")])
    assert _full(c).endswith("(Cambridge University Press, 2008) 38")
    assert "[MISSING" not in _full(c)


def test_commentary_inside_citation_original_is_kept():
    text = "For a strong statement of this view, see Ronald Dworkin, Justice for Hedgehogs (Belknap Press, 2011) 10."
    out = _extract([_fn(13, text)], [{"number": 13, "segments": [
        {"kind": "citation", "original": text[:-1],
         "citation": {"source": {"type": "book", "authors": ["Ronald Dworkin"], "title": "Justice for Hedgehogs",
                                 "publisher": "Belknap Press", "year": "2011"},
                      "pinpoints": [{"kind": "page", "value": "10"}], "signal": "See"}},
    ]}])
    for fn in out:
        for seg in fn.segments:
            if isinstance(seg, CitationSegment):
                seg.citation = _norm(seg.citation)
    rendered = render_document(out, bibliography=False).footnotes[0].formatted.to_markup()
    assert rendered == "For a strong statement of this view, see Ronald Dworkin, *Justice for Hedgehogs* (Belknap Press, 2011) 10."


def test_single_page_number_is_not_both_start_page_and_pinpoint():
    text = "Stephanie Peatling, 'Female Chief Justice Rewrites the Script', The Age (Melbourne), 31 January 2017, p. 6."
    out = _extract([_fn(19, text)], [{"number": 19, "segments": [
        {"kind": "citation", "original": text[:-1],
         "citation": {"source": {"type": "newspaper", "authors": ["Stephanie Peatling"], "title": "Female Chief Justice Rewrites the Script",
                                 "newspaper": "The Age", "place": "Melbourne", "date": "31 January 2017", "page": "6"},
                      "pinpoints": [{"kind": "page", "value": "6"}]}},
    ]}])
    assert out[0].segments[0].citation.pinpoints == []


def test_pinpoint_equal_to_start_page_is_kept_when_written_twice():
    # r 5.7: '(2000) 8(2) Restitution Law Review 189, 189' pinpoints the first page deliberately
    text = "Gordon Goldberg, 'Certain Confusions' (2000) 8(2) Restitution Law Review 189, 189."
    out = _extract([_fn(1, text)], [{"number": 1, "segments": [
        {"kind": "citation", "original": text[:-1],
         "citation": {"source": {"type": "journal_article", "authors": ["Gordon Goldberg"], "title": "Certain Confusions",
                                 "year": "2000", "volume": "8", "issue": "2", "journal": "Restitution Law Review", "starting_page": "189"},
                      "pinpoints": [{"kind": "page", "value": "189"}]}},
    ]}])
    assert len(out[0].segments[0].citation.pinpoints) == 1
