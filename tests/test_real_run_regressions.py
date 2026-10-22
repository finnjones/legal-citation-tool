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
    Run,
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


def test_a_pinpoint_written_in_square_brackets_stays_a_paragraph():
    # the model labelled the author's '[20]' a page, which would print it without brackets
    kuhl = "Kuhl v Zurich Financial Services Australia Ltd [2011] HCA 11, [20]"
    result = _process([_rich(1, "*Kuhl v Zurich Financial Services Australia Ltd* [2011] HCA 11, [20].")], [
        {"number": 1, "segments": [_cite(kuhl, {"type": "case", "name": "Kuhl v Zurich Financial Services Australia Ltd",
                                                "year": "2011", "court_id": "HCA", "judgment_number": "11"},
                                         pinpoints=[{"kind": "page", "value": "20"}]), _DOT]},
    ])
    assert result.footnotes[0].formatted.text == kuhl + "."


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


# An Act named in an article title lost its italics: AGLC4 keeps legislation and case
# names italic inside a quoted title, and the student had them right.

_marked = _rich


_HEMMINGS_TITLE = ("A Danger to Protest: The Freedom of Peaceful Assembly and Disruptive Protest under the "
                   "Summary Offences and Other Legislation Amendment Act 2019 (Qld)")


def _hemmings(markup_title: str) -> str:
    """Extract and render the student's footnote, with its title written as `markup_title`."""
    original = (f"Toby Hemmings and Azadeh Dastyari, ‘{markup_title}’ (Journal Article, 2021) 27(2) "
                "*Australian Journal of Human Rights* 1")
    fns = [_marked(5, original + ".")]
    source = {"type": "journal_article", "authors": ["Toby Hemmings", "Azadeh Dastyari"], "title": _HEMMINGS_TITLE,
              "year": "2021", "volume": "27", "issue": "2", "journal": "Australian Journal of Human Rights",
              "starting_page": "1"}
    out = _extract(fns, [{"number": 5, "segments": [
        {"kind": "citation", "original": fns[0].original.text[:-1], "citation": {"source": source}}]}])
    for seg in out[0].segments:
        if isinstance(seg, CitationSegment):
            seg.citation = _norm(seg.citation)
    return render_document(out, bibliography=False).footnotes[0].formatted.to_markup()


def test_act_name_inside_an_article_title_stays_italic():
    title = _HEMMINGS_TITLE.replace("Summary", "*Summary").replace(" 2019", " 2019*")
    assert _hemmings(title) == (
        "Toby Hemmings and Azadeh Dastyari, ‘A Danger to Protest: The Freedom of Peaceful Assembly and Disruptive "
        "Protest under the *Summary Offences and Other Legislation Amendment Act 2019* (Qld)’ (2021) 27(2) "
        "*Australian Journal of Human Rights* 1."
    )


def test_article_title_gets_no_italics_the_student_did_not_use():
    plain = f"Toby Hemmings and Azadeh Dastyari, ‘{_HEMMINGS_TITLE}’ (2021) 27(2) *Australian Journal of Human Rights* 1."
    assert _hemmings(_HEMMINGS_TITLE) == plain
    # an article title italicised throughout is a mistake, not a case or Act name
    assert _hemmings(f"*{_HEMMINGS_TITLE}*") == plain


def test_case_name_inside_a_chapter_title_stays_italic():
    title = "Revisiting *Mabo v Queensland [No 2]* (1992)"
    src = BookChapterSource(authors=["Jane Doe"], chapter_title="Revisiting Mabo v Queensland [No 2] (1992)",
                            chapter_title_rich=_marked(1, title).original, editors=["John Roe"],
                            book_title="Native Title", publisher="Federation Press", year="2010", starting_page="1")
    assert _full(Citation(source=src)).startswith("Jane Doe, ‘Revisiting *Mabo v Queensland [No 2]* (1992)’ in ")


# Hansard and parliamentary papers now have source types of their own.


def _from_markup(n: int, markup: str) -> Footnote:
    """A footnote whose *asterisked* runs are italic, as read from Word."""
    runs = [Run(text=part, italic=bool(i % 2)) for i, part in enumerate(markup.split("*")) if part]
    return Footnote(number=n, original=RichText(runs=runs))


SPEAKMAN = {"type": "parliamentary_debates", "jurisdiction": "New South Wales", "chamber": "Legislative Assembly",
            "date": "30 March 2022", "speaker": "Mark Speakman", "speaker_position": "Attorney-General"}
SPEAKMAN_FULL = ("New South Wales, *Parliamentary Debates*, Legislative Assembly, 30 March 2022, 8938 "
                 "(Mark Speakman, Attorney-General)")


def test_hansard_already_in_aglc_form_is_left_unchanged():
    """Hansard used to fall through to the 'other' type and be copied verbatim, so a wrong
    one could never be fixed. As its own type it is formatted, and a correct one is kept."""
    from aglc import pipeline

    fns = [
        _from_markup(5, SPEAKMAN_FULL + " (‘*Parliamentary Debates*’)."),
        _from_markup(6, "Australian Law Reform Commission, *Elder Abuse* (Discussion Paper No 83, December 2016)."),
        _from_markup(7, "*Parliamentary Debates* (n 5) 8939."),
    ]
    batch = json.dumps({"footnotes": [
        {"number": 5, "segments": [{"kind": "citation", "original": fns[0].original.text[:-1],
                                    "citation": {"source": SPEAKMAN, "pinpoints": [{"kind": "page", "value": "8938"}],
                                                 "short_title": "Parliamentary Debates"}}]},
        {"number": 6, "segments": [{"kind": "citation", "original": fns[1].original.text[:-1],
                                    "citation": {"source": {"type": "report", "author": "Australian Law Reform Commission",
                                                            "title": "Elder Abuse", "document_type": "Discussion Paper",
                                                            "document_number": "83", "date": "December 2016"}}}]},
        {"number": 7, "segments": [{"kind": "citation", "original": "Parliamentary Debates (n 5) 8939", "refers_to_footnote": 5,
                                    "citation": {"source": {"type": "other", "text": "Parliamentary Debates (n 5) 8939"},
                                                 "short_title": "Parliamentary Debates",
                                                 "pinpoints": [{"kind": "page", "value": "8939"}]}}]},
    ]})
    result = pipeline.process_footnotes(fns, get_provider("fake:x", responses=[batch]), bibliography=False)
    assert [f.formatted.to_markup() for f in result.footnotes] == [f.original.to_markup() for f in fns]
    assert not any(f.changed for f in result.footnotes)
    assert result.warnings == []


def test_badly_formatted_hansard_is_corrected():
    """'Parliamentary Debates' in roman with the chamber italicised and no comma after it;
    then the same speech with the speaker's titles and abbreviations left in."""
    from aglc import pipeline

    messy = [
        _from_markup(5, "New South Wales, Parliamentary Debates, *Legislative Assembly* 30 March 2022, 8938 "
                        "(Mark Speakman, Attorney-General)."),
        _from_markup(9, "NSW, *Parliamentary Debates*, LA, 30th March 2022, p 8938 (The Hon. Mark Speakman SC MP, Attorney-General)."),
    ]
    extracted = [
        dict(SPEAKMAN),
        dict(SPEAKMAN, jurisdiction="NSW", chamber="LA", date="30th March 2022", speaker="The Hon. Mark Speakman SC MP"),
    ]
    batch = json.dumps({"footnotes": [
        {"number": fn.number, "segments": [{"kind": "citation", "original": fn.original.text[:-1],
                                            "citation": {"source": src, "pinpoints": [{"kind": "page", "value": "8938"}]}}]}
        for fn, src in zip(messy, extracted)
    ]})
    for fn in messy:
        # each footnote on its own, so the second isn't an 'Ibid' to the first
        one = json.dumps({"footnotes": [f for f in json.loads(batch)["footnotes"] if f["number"] == fn.number]})
        result = pipeline.process_footnotes([fn], get_provider("fake:x", responses=[one]), bibliography=False)
        assert result.footnotes[0].formatted.to_markup() == SPEAKMAN_FULL + "."
        assert result.warnings == []


def test_italic_markup_copied_into_the_citation_text_is_ignored():
    # The real model returned original="... ‘Protest Law in New South Wales’, *Parliament of NSW* (Report,
    # 2024) <https://www...>" with the asterisks it was shown. Unmatched, the footnote's closing '.'
    # was then found in 'www.' and the rest of the URL appended: '(Report, 2024)parliament.nsw.gov.au/...>.'
    url = "https://www.parliament.nsw.gov.au/research-papers/protest-law-nsw"
    markup = f"Parliament of NSW, ‘Protest Law in New South Wales’, *Parliament of NSW* (Report, 2024) <{url}>"
    out = _extract([_rich(31, markup + ".")], [{"number": 31, "segments": [
        {"kind": "citation", "original": markup,
         "citation": {"source": {"type": "report", "author": "Parliament of NSW", "title": "Protest Law in New South Wales",
                                 "document_type": "Report", "date": "2024"}}},
        {"kind": "text", "text": "."}]}])
    texts = [s.text.text for s in out[0].segments if isinstance(s, TextSegment)]
    assert texts == ["."]  # no URL fragment left over


def test_a_subsection_split_into_separate_pinpoints_is_put_back_together():
    # The model returned 's 214A(1)(b)' as section '214A' then '1' and 'b', which rendered
    # 'Crimes Act (n 1) s 214A 1, b'
    fns = [_rich(1, "*Crimes Act 1900* (NSW) s 214A (‘*Crimes Act*’)."),
           _rich(2, "*Interpretation Act 1987* (NSW) s 33."),
           _rich(3, "*Crimes Act* (n 1) s 214A(1)(b)."),
           _rich(4, "*Crimes Act* (n 1) s 214A(7).")]
    result = _process(fns, [
        {"number": 1, "segments": [_cite("Crimes Act 1900 (NSW) s 214A (‘Crimes Act’)", _act("Crimes Act", "1900"),
                                         pinpoints=[_sec("214A")], short_title="Crimes Act"), _DOT]},
        {"number": 2, "segments": [_cite("Interpretation Act 1987 (NSW) s 33", _act("Interpretation Act", "1987"),
                                         pinpoints=[_sec("33")]), _DOT]},
        {"number": 3, "segments": [_cite("Crimes Act (n 1) s 214A(1)(b)", {"type": "other", "text": "x"}, 1,
                                         pinpoints=[_sec("214A"), {"kind": "other", "value": "1"},
                                                    {"kind": "other", "value": "b"}], short_title="Crimes Act"), _DOT]},
        {"number": 4, "segments": [_cite("Crimes Act (n 1) s 214A(7)", {"type": "other", "text": "x"}, 1,
                                         pinpoints=[_sec("214A"), {"kind": "page", "value": "(7)"}],
                                         short_title="Crimes Act"), _DOT]},
    ])
    assert result.footnotes[2].formatted.text == "Crimes Act (n 1) s 214A(1)(b)."
    assert result.footnotes[3].formatted.text == "Ibid s 214A(7)."


def test_separate_provisions_are_not_joined_into_subsections():
    fns = [_rich(1, "*Crimes Act 1900* (NSW) s 5, sch 1.")]
    result = _process(fns, [
        {"number": 1, "segments": [_cite("Crimes Act 1900 (NSW) s 5, sch 1", _act("Crimes Act", "1900"),
                                         pinpoints=[_sec("5"), {"kind": "schedule", "value": "1"}]), _DOT]},
    ])
    assert result.footnotes[0].formatted.text == "Crimes Act 1900 (NSW) s 5 sch 1."


def _book_seg(original: str, pinpoints: list | None = None, **book) -> dict:
    return _cite(original, {"type": "book", "authors": ["Jane Smith"], "title": "Torts", **book}, pinpoints=pinpoints or [])


def test_a_book_and_an_article_sharing_author_and_title_are_both_cited_in_full():
    book = "Jane Smith, *Torts* (Federation Press, 2020)"
    article = "Jane Smith, ‘Torts’ (2021) 45 *Melbourne University Law Review* 1"
    raw = json.dumps({"footnotes": [
        {"number": 1, "segments": [_book_seg(book.replace("*", ""), publisher="Federation Press", year="2020"), _DOT]},
        {"number": 2, "segments": [_cite(article.replace("*", ""), {
            "type": "journal_article", "authors": ["Jane Smith"], "title": "Torts", "year": "2021", "volume": "45",
            "journal": "Melbourne University Law Review", "starting_page": "1"}), _DOT]},
    ]})
    result = pipeline.process_footnotes([_rich(1, book + "."), _rich(2, article + ".")],
                                        get_provider("fake:x", responses=[raw]))
    assert not result.footnotes[1].formatted.text.startswith("Ibid")
    assert sum(len(s.entries) for s in result.bibliography) == 2


def test_the_bibliography_takes_a_detail_the_first_citation_lacked_from_a_later_one():
    first = "Jane Smith, *Torts* (2020)"
    later = "Jane Smith, *Torts* (Federation Press, 2020) 12"
    raw = json.dumps({"footnotes": [
        {"number": 1, "segments": [_book_seg(first.replace("*", ""), year="2020"), _DOT]},
        {"number": 2, "segments": [{"kind": "text", "text": "See generally the discussion."}]},
        {"number": 3, "segments": [_book_seg(later.replace("*", ""), publisher="Federation Press", year="2020",
                                             pinpoints=[{"value": "12"}]), _DOT]},
    ]})
    result = pipeline.process_footnotes(
        [_rich(1, first + "."), _rich(2, "See generally the discussion."), _rich(3, later + ".")],
        get_provider("fake:x", responses=[raw]))
    assert result.footnotes[2].formatted.text.startswith("Smith (n 1) 12")
    entries = [e.text for s in result.bibliography for e in s.entries]
    assert entries == ["Smith, Jane, Torts (Federation Press, 2020)"]


_MABO = "Mabo v Queensland [No 2] (1992) 175 CLR 1"


def _mabo(**citation) -> dict:
    return _cite(_MABO, {"type": "case", "name": "Mabo v Queensland [No 2]", "year": "1992", "volume": "175",
                         "report": "CLR", "starting_page": "1"}, **citation)


def test_the_full_stop_before_commentary_is_kept():
    text = _MABO + ". This was later doubted."
    result = _process([_rich(1, "*Mabo v Queensland [No 2]* (1992) 175 CLR 1. This was later doubted.")],
                      [{"number": 1, "segments": [_mabo(), _DOT, {"kind": "text", "text": " This was later doubted."}]}])
    assert result.footnotes[0].formatted.text == text


def test_ibid_keeps_the_judge_when_there_is_no_pinpoint():
    result = _process([_rich(1, "*Mabo v Queensland [No 2]* (1992) 175 CLR 1."), _rich(2, "Ibid (Brennan J).")], [
        {"number": 1, "segments": [_mabo(), _DOT]},
        {"number": 2, "segments": [_cite("Ibid (Brennan J)", {"type": "other", "text": "Ibid"}, 1,
                                         pinpoint_judges="Brennan J"), _DOT]},
    ])
    assert result.footnotes[1].formatted.text == "Ibid (Brennan J)."


def test_a_bare_number_after_a_medium_neutral_citation_is_not_bracketed():
    # 'Kvelde (n 8) 69, [202]': the author wrote 69 without brackets, so it isn't made '[69]'
    kvelde = "Kvelde v The State of New South Wales [2023] NSWSC 1560"
    result = _process([_rich(1, f"*{kvelde[:39]}*{kvelde[39:]} [202] (‘*Kvelde*’)."), _rich(2, "Discussed below."),
                       _rich(3, "*Kvelde* (n 1) 69, [202].")], [
        {"number": 1, "segments": [_cite(kvelde + " [202] (‘Kvelde’)", {
            "type": "case", "name": "Kvelde v The State of New South Wales", "year": "2023", "court_id": "NSWSC",
            "judgment_number": "1560"}, pinpoints=[{"kind": "paragraph", "value": "202"}], short_title="Kvelde"), _DOT]},
        {"number": 2, "segments": [{"kind": "text", "text": "Discussed below."}]},
        {"number": 3, "segments": [_cite("Kvelde (n 1) 69, [202]", {"type": "other", "text": "Kvelde"}, 1,
                                         pinpoints=[{"kind": "page", "value": "69"}, {"kind": "paragraph", "value": "202"}],
                                         short_title="Kvelde"), _DOT]},
    ])
    assert result.footnotes[2].formatted.text == "Kvelde (n 1) 69, [202]."
    assert any("if it is a paragraph, write [69]" in w.message for w in result.warnings)


def test_ibid_subsections_given_as_one_value_are_put_back_together():
    # 'Ibid s 214A(1)(b)' came back as section '214A' then '1, b', which rendered 'Ibid s 214A 1, b'
    for original in ("Ibid s 214A(1)(b)", "Ibid"):  # with and without the pinpoint in `original`
        result = _process([_rich(1, "*Crimes Act 1900* (NSW) s 214A (‘*Crimes Act*’)."), _rich(2, "Ibid s 214A(1)(b).")], [
            {"number": 1, "segments": [_cite("Crimes Act 1900 (NSW) s 214A (‘Crimes Act’)", _act("Crimes Act", "1900"),
                                             pinpoints=[_sec("214A")], short_title="Crimes Act"), _DOT]},
            {"number": 2, "segments": [_cite(original, {"type": "other", "text": "Ibid"}, 1,
                                             pinpoints=[_sec("214A"), {"kind": "other", "value": "1, b"}]), _DOT]},
        ])
        assert result.footnotes[1].formatted.text == "Ibid s 214A(1)(b).", original


def test_a_reference_managers_document_label_is_removed_not_a_reason_to_give_up():
    # Footnote 37 of a real essay was left as written: dropping '(Journal Report, ...)' is the
    # fix, but the check counted 'report' as a word the extraction had lost
    title = ("A Danger to Protest: The Freedom of Peaceful Assembly and Disruptive Protest under the "
             "Summary Offences and Other Legislation Amendment Act 2019 (Qld)")
    written = (f"Toby Hemmings and Azadeh Dastyari, ‘{title}’ (Journal Report, 2021) 27(2) "
               "*Australian Journal of Human Rights* 1.")
    result = _process([_rich(37, written)], [
        {"number": 37, "segments": [_cite(written.replace("*", "")[:-1], {
            "type": "journal_article", "authors": ["Toby Hemmings", "Azadeh Dastyari"], "title": title,
            "year": "2021", "volume": "27", "issue": "2", "journal": "Australian Journal of Human Rights",
            "starting_page": "1"}), _DOT]},
    ])
    fn = result.footnotes[0]
    assert fn.extraction_failed is None and not any("left unchanged" in w.message for w in result.warnings)
    assert fn.formatted.text == (f"Toby Hemmings and Azadeh Dastyari, ‘{title}’ (2021) 27(2) "
                                 "Australian Journal of Human Rights 1.")
    assert ("type_label", "ch 5") in [(c.kind, c.rule) for c in fn.changes]


def test_a_us_case_is_set_out_under_r_25_1():
    written = "*Bowers v. Hardwick*, 760 F.2d 1202, 1211 (11th Cir. 1985)."
    result = _process([_rich(1, written)], [
        {"number": 1, "segments": [_cite(written.replace("*", "")[:-1], {
            "type": "case", "name": "Bowers v Hardwick", "volume": "760", "report": "F.2d", "starting_page": "1202",
            "court_name": "11th Cir.", "year": "1985"}, pinpoints=[{"value": "1211"}]), _DOT]},
    ])
    fn = result.footnotes[0]
    assert fn.formatted.to_markup() == "*Bowers v Hardwick*, 760 F 2d 1202, 1211 (11th Cir, 1985)."
    assert {c.rule for c in fn.changes} <= {"r 25.1", "r 25.1.1", "r 25.1.4", "r 1.6.1"}
