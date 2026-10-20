"""Regressions found by the first real run (DeepSeek V4 Flash via OpenRouter on
examples/test_essay.docx). Each test reproduces what the model actually returned."""

import json

from aglc import pipeline
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
    ex = Extractor(get_provider("fake:x", responses=[raw]), verify=False)
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
    out = Extractor(provider, verify=False).extract(fns)
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


# ---- run on a real student case note ------------------------------------------ #


def test_short_title_from_a_later_reference_is_used_from_the_first_citation():
    """The author defines short titles in the body text ("... ('Maynard')"), so the tool
    learns them from the footnotes that use them: "Maynard (n 1)"."""
    from aglc import pipeline

    # footnote 2 cites something else, so footnote 6 can't be an 'Ibid' (as in the real document)
    fns = [_fn(1, "Adoption of Maynard (a pseudonym) [2026] NSWSC 921."), _fn(2, "Adoption Act 2000 (NSW)."),
           _fn(6, "Maynard (n 1).")]
    batch = json.dumps({"footnotes": [
        {"number": 1, "segments": [{"kind": "citation", "original": "Adoption of Maynard (a pseudonym) [2026] NSWSC 921",
                                    "citation": {"source": {"type": "case", "name": "Adoption of Maynard (a pseudonym)",
                                                            "year": "2026", "court_id": "NSWSC", "judgment_number": "921"}}}]},
        {"number": 2, "segments": [{"kind": "citation", "original": "Adoption Act 2000 (NSW)",
                                    "citation": {"source": {"type": "legislation", "title": "Adoption Act", "year": "2000",
                                                            "jurisdiction": "NSW"}}}]},
        {"number": 6, "segments": [{"kind": "citation", "original": "Maynard (n 1)", "refers_to_footnote": 1,
                                    "citation": {"source": {"type": "other", "text": "Maynard (n 1)"}}}]},
    ]})
    result = pipeline.process_footnotes(fns, get_provider("fake:x", responses=[batch]), bibliography=False)
    out = {f.number: f.formatted.to_markup() for f in result.footnotes}
    assert out[1] == "*Adoption of Maynard (a pseudonym)* [2026] NSWSC 921 (‘*Maynard*’)."
    assert out[6] == "*Maynard* (n 1)."


def test_a_cases_full_name_is_not_treated_as_a_short_title():
    fns = [_fn(1, "Donoghue v Stevenson [1932] AC 562."), _fn(5, "Donoghue v Stevenson, supra n 1, 599.")]
    batch = json.dumps({"footnotes": [
        {"number": 1, "segments": [{"kind": "citation", "original": "Donoghue v Stevenson [1932] AC 562",
                                    "citation": {"source": {"type": "case", "name": "Donoghue v Stevenson", "year": "1932",
                                                            "report": "AC", "starting_page": "562"}}}]},
        {"number": 5, "segments": [{"kind": "citation", "original": "Donoghue v Stevenson, supra n 1, 599", "refers_to_footnote": 1,
                                    "citation": {"source": {"type": "other", "text": "x"},
                                                 "pinpoints": [{"kind": "page", "value": "599"}]}}]},
    ]})
    out = Extractor(get_provider("fake:x", responses=[batch]), verify=False).extract(fns)
    assert out[1].segments[0].citation.short_title is None


def test_webpage_and_web_page_count_as_the_same_word():
    from aglc import validate as V

    seg = CitationSegment(citation=Citation(source=WebsiteSource(
        title="Legal Formalism", website_name="Cornell", document_type="Web Page", date="2023", url="https://x")))
    assert V.missing_from_extraction("‘Legal Formalism’, Cornell (Webpage, 2023) <https://x>.", [seg]) == []


# ---- run on a real statutory interpretation assignment (Oct 2026) ------------------ #
# The student saw footnotes marked Amended with nothing visibly changed, 'et al' removed,
# and italics taken off a Hansard reference; replaying the later draft also showed a
# '(n x)' with the wrong number swapped for a different source.


def _rich(n: int, markup: str) -> Footnote:
    """'*Crimes Act *(n 1)' -> a footnote with those italic runs (the space is italic too)."""
    rt = RichText()
    for i, part in enumerate(markup.split("*")):
        rt.append(part, italic=i % 2 == 1)
    return Footnote(number=n, original=rt)


def _cite(original: str, source: dict, ref: int | None = None, **citation) -> dict:
    return {"kind": "citation", "original": original, "refers_to_footnote": ref,
            "citation": {"source": source, **citation}}


def _act(title: str, year: str) -> dict:
    return {"type": "legislation", "kind": "act", "title": title, "year": year, "jurisdiction": "NSW"}


def _sec(value: str) -> dict:
    return {"kind": "section", "value": value}


_DOT = {"kind": "text", "text": "."}


def _process(fns: list[Footnote], llm_footnotes: list[dict]):
    raw = json.dumps({"footnotes": llm_footnotes})
    return pipeline.process_footnotes(fns, get_provider("fake:x", responses=[raw]), bibliography=False)


def test_a_trailing_space_or_an_italic_space_is_not_an_amendment():
    fns = [_rich(1, "*Crimes Act 1900* (NSW) s 214A (‘*Crimes Act*’)."),
           _rich(2, "*Interpretation Act 1987* (NSW) s 33 (‘*Interpretation Act*’)."),
           _rich(3, "*Crimes Act *(n 1) s 214A. "),
           _rich(4, "Ibid s 214A(1)(b). ")]
    result = _process(fns, [
        {"number": 1, "segments": [_cite("Crimes Act 1900 (NSW) s 214A (‘Crimes Act’)", _act("Crimes Act", "1900"),
                                         pinpoints=[_sec("214A")], short_title="Crimes Act"), _DOT]},
        {"number": 2, "segments": [_cite("Interpretation Act 1987 (NSW) s 33 (‘Interpretation Act’)", _act("Interpretation Act", "1987"),
                                         pinpoints=[_sec("33")], short_title="Interpretation Act"), _DOT]},
        {"number": 3, "segments": [_cite("Crimes Act (n 1) s 214A", {"type": "other", "text": "Crimes Act (n 1) s 214A"}, 1,
                                         pinpoints=[_sec("214A")], short_title="Crimes Act"), _DOT]},
        {"number": 4, "segments": [_cite("Ibid s 214A(1)(b)", {"type": "other", "text": "Ibid s 214A(1)(b)"}, 3,
                                         pinpoints=[_sec("214A(1)(b)")]), _DOT]},
    ])
    assert [f.changed for f in result.footnotes] == [False, False, False, False]
    # the space after the final full stop is kept, not closed over ('(b). .')
    assert result.footnotes[3].formatted.text == "Ibid s 214A(1)(b). "


_HAMER = "David Hamer et al, *Laying Down the Law* (LexisNexis Butterworths, 12th ed, 2023) 648-649."


def _hamer_book(**extra) -> dict:
    return {"type": "book", "authors": ["David Hamer"], "title": "Laying Down the Law",
            "publisher": "LexisNexis Butterworths", "edition": "12", "year": "2023", **extra}


def test_et_al_is_kept_when_the_model_returns_only_the_named_author():
    result = _process([_rich(14, _HAMER), _rich(15, "Commentary."), _rich(20, "Hamer (n 14) 650.")], [
        {"number": 14, "segments": [_cite(_HAMER.replace("*", "")[:-1], _hamer_book(),
                                          pinpoints=[{"kind": "page", "value": "648-649", "plural": True}]), _DOT]},
        {"number": 15, "segments": [{"kind": "text", "text": "Commentary."}]},
        {"number": 20, "segments": [_cite("Hamer (n 14) 650", {"type": "other", "text": "Hamer (n 14) 650"}, 14,
                                          pinpoints=[{"kind": "page", "value": "650"}], short_title="Hamer"), _DOT]},
    ])
    out = [f.formatted.to_markup() for f in result.footnotes]
    assert out[0] == "David Hamer et al, *Laying Down the Law* (LexisNexis Butterworths, 12th ed, 2023) 648–9."
    assert out[2] == "Hamer et al (n 14) 650."


def test_et_al_is_kept_when_the_model_sets_it_or_leaves_it_on_the_name():
    for book in (_hamer_book(et_al=True), _hamer_book(authors=["David Hamer et al"])):
        result = _process([_rich(14, _HAMER)], [
            {"number": 14, "segments": [_cite(_HAMER.replace("*", "")[:-1], book,
                                              pinpoints=[{"kind": "page", "value": "648-649", "plural": True}]), _DOT]},
        ])
        assert result.footnotes[0].formatted.to_markup().startswith("David Hamer et al, *Laying Down the Law*")


def test_an_unclassified_hansard_reference_keeps_its_italics():
    hansard = ("New South Wales, *Parliamentary Debates*, Legislative Assembly, 30 March 2022, 8938 "
               "(Mark Speakman, Attorney-General) (‘*Parliamentary Debates*’). ")
    text = hansard.replace("*", "").split(" (‘")[0]
    result = _process([_rich(5, hansard), _rich(6, "Commentary."), _rich(28, "*Parliamentary Debates* (n 5) 8939.")], [
        {"number": 5, "segments": [_cite(text + " (‘Parliamentary Debates’)", {"type": "other", "text": text},
                                         short_title="Parliamentary Debates"), _DOT]},
        {"number": 6, "segments": [{"kind": "text", "text": "Commentary."}]},
        {"number": 28, "segments": [_cite("Parliamentary Debates (n 5) 8939", {"type": "other", "text": "Parliamentary Debates (n 5) 8939"}, 5,
                                          pinpoints=[{"kind": "page", "value": "8939"}], short_title="Parliamentary Debates"), _DOT]},
    ])
    assert result.footnotes[0].formatted.visible().to_markup() == _rich(5, hansard).original.visible().to_markup()
    assert result.footnotes[2].formatted.to_markup() == "*Parliamentary Debates* (n 5) 8939."
    assert not any(f.changed for f in result.footnotes)


_KVELDE = "Kvelde v The State of New South Wales [2023] NSWSC 1560 [202] (‘Kvelde’)"


def _kvelde_run(name: str) -> tuple:
    fns = [_rich(1, "*Crimes Act 1900* (NSW) s 214A (‘*Crimes Act*’)."),
           _rich(11, "*Kvelde v The State of New South Wales* [2023] NSWSC 1560 [202] (‘*Kvelde*’)."),
           _rich(12, "*Crimes Act* (n 1) s 214A(1)(c)."),
           _rich(17, f"*{name}* (n 12) [228]."),
           _rich(18, "Ibid [415]."),
           _rich(19, "*Crimes Act* (n 1) s 214A(2).")]
    result = _process(fns, [
        {"number": 1, "segments": [_cite("Crimes Act 1900 (NSW) s 214A (‘Crimes Act’)", _act("Crimes Act", "1900"),
                                         pinpoints=[_sec("214A")], short_title="Crimes Act"), _DOT]},
        {"number": 11, "segments": [_cite(_KVELDE, {"type": "case", "name": "Kvelde v The State of New South Wales", "year": "2023",
                                                    "court_id": "NSWSC", "judgment_number": "1560"},
                                          pinpoints=[{"kind": "paragraph", "value": "202"}], short_title="Kvelde"), _DOT]},
        {"number": 12, "segments": [_cite("Crimes Act (n 1) s 214A(1)(c)", {"type": "other", "text": "Crimes Act (n 1) s 214A(1)(c)"}, 1,
                                          pinpoints=[_sec("214A(1)(c)")], short_title="Crimes Act"), _DOT]},
        {"number": 17, "segments": [_cite(f"{name} (n 12) [228]", {"type": "other", "text": f"{name} (n 12) [228]"}, 12,
                                          pinpoints=[{"kind": "paragraph", "value": "228"}], short_title=name), _DOT]},
        {"number": 18, "segments": [_cite("Ibid [415]", {"type": "other", "text": "Ibid [415]"}, 17,
                                          pinpoints=[{"kind": "paragraph", "value": "415"}]), _DOT]},
        {"number": 19, "segments": [_cite("Crimes Act (n 1) s 214A(2)", {"type": "other", "text": "Crimes Act (n 1) s 214A(2)"}, 1,
                                          pinpoints=[_sec("214A(2)")], short_title="Crimes Act"), _DOT]},
    ])
    return {f.number: f.formatted.to_markup() for f in result.footnotes}, [w.message for w in result.warnings]


def test_a_reference_with_the_wrong_footnote_number_points_to_the_named_source():
    out, warnings = _kvelde_run("Kvelde")
    assert out[17] == "*Kvelde* (n 11) [228]."  # not '*Crimes Act* (n 1) [228].'
    assert out[18] == "Ibid [415]."  # still Kvelde
    assert out[19] == "*Crimes Act* (n 1) s 214A(2)."  # not turned into 'Ibid'
    assert any("footnote 17: '(n 12)' points to footnote 12, which doesn't cite 'Kvelde'; changed to footnote 11" in w
               for w in warnings)


def test_a_reference_naming_no_earlier_source_is_kept_as_written():
    out, warnings = _kvelde_run("Smith")
    assert out[17] == "*Smith* (n 12) [228]."
    assert any(w.startswith("footnote 17: could not resolve reference to footnote 12") for w in warnings)


def test_a_reference_by_author_surname_defines_no_short_title():
    # r 1.4.1: 'Sanson (n 27)' uses the surname; the full citation gets no "(‘Sanson’)"
    book = {"type": "book", "authors": ["Michelle Sanson"], "title": "Statutory Interpretation",
            "publisher": "Oxford University Press", "edition": "2", "year": "2016"}
    full = "Michelle Sanson, Statutory Interpretation (Oxford University Press, 2nd ed, 2016) 215"
    result = _process([_rich(27, f"{full}."), _rich(28, "Commentary."), _rich(30, "Sanson (n 27) 216.")], [
        {"number": 27, "segments": [_cite(full, book, pinpoints=[{"kind": "page", "value": "215"}]), _DOT]},
        {"number": 28, "segments": [{"kind": "text", "text": "Commentary."}]},
        {"number": 30, "segments": [_cite("Sanson (n 27) 216", {"type": "other", "text": "Sanson (n 27) 216"}, 27,
                                          pinpoints=[{"kind": "page", "value": "216"}], short_title="Sanson"), _DOT]},
    ])
    out = [f.formatted.to_markup() for f in result.footnotes]
    assert out[0] == "Michelle Sanson, *Statutory Interpretation* (Oxford University Press, 2nd ed, 2016) 215."
    assert out[2] == "Sanson (n 27) 216."
