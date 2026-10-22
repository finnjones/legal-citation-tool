"""Speeches (AGLC4 r 7.3), media releases (r 7.4), dictionaries (r 7.6), legal
encyclopedias (r 7.7), social media posts (r 7.16) and UN documents (r 9.2).

The guide's own examples for each are golden tests in tests/aglc4_examples/other_sources.json
and un.json. These cover what the examples don't: repeat references, the bibliography, the
normaliser's clean-up of what students actually write, and extraction through to the
formatted footnote."""

import json
from pathlib import Path

import pytest

from aglc import pipeline, validate
from aglc.formatters import formatter_for
from aglc.llm import get_provider
from aglc.models import (
    Citation,
    DictionarySource,
    Footnote,
    LegalEncyclopediaSource,
    MediaReleaseSource,
    Pinpoint,
    RichText,
    SocialMediaSource,
    SpeechSource,
    UNDocumentSource,
)
from aglc.normalise import normalise_citation, source_key


def _norm(c: Citation) -> Citation:
    return normalise_citation(c)[0]


def _full(c: Citation) -> str:
    c = _norm(c)
    return formatter_for(c).full(c).to_markup()


def _bib(c: Citation) -> str:
    c = _norm(c)
    return formatter_for(c).bibliography(c).to_markup()


def _subsequent(c: Citation, n: int) -> str:
    c = _norm(c)
    f = formatter_for(c)
    return f.subsequent(c, f.short_title(c), n).to_markup()


HEYDON = SpeechSource(authors=["Justice Dyson Heydon"], title="Threats to Judicial Independence: The Enemy Within",
                      forum="Inner Temple", date="23 January 2012")
DEFENCE = MediaReleaseSource(authors=["Department of Defence (Cth)"], authors_are_bodies=True,
                             title="Highest East Timorese Honour for Army Officers", document_number="MSPA 172/09",
                             date="22 May 2009")
STEPHENSON = SocialMediaSource(username="@s_m_stephenson", author_name="Scott Stephenson", platform="Twitter",
                               date="17 July 2017", time="9:37pm", time_zone="AEST",
                               url="https://twitter.com/s_m_stephenson/status/887169425551441921")
RES_1325 = UNDocumentSource(resolution="SC Res 1325", official_records="UN SCOR", meeting="4213",
                            document_number="S/RES/1325", date="31 October 2000")


# ---- repeat references and the bibliography ------------------------------- #


def test_a_speech_is_referred_to_again_by_the_speakers_surname():
    c = Citation(source=HEYDON, pinpoints=[Pinpoint(value="4")])
    assert _subsequent(c, 41) == "Heydon (n 41) 4"
    assert _bib(c) == ("Heydon, Justice Dyson, ‘Threats to Judicial Independence: The Enemy Within’ "
                       "(Speech, Inner Temple, 23 January 2012)")


def test_a_media_release_by_a_body_keeps_the_bodys_whole_name():
    c = Citation(source=DEFENCE, pinpoints=[Pinpoint(value="2")])
    assert _subsequent(c, 45) == "Department of Defence (Cth) (n 45) 2"
    assert _bib(c).startswith("Department of Defence (Cth), ‘Highest")


def test_a_media_release_with_no_author_is_referred_to_by_its_quoted_title():
    c = Citation(source=MediaReleaseSource(title="Budget Delivers for Families", body="Treasury", date="9 May 2023"))
    assert _full(c) == "‘Budget Delivers for Families’ (Media Release, Treasury, 9 May 2023)"
    assert _subsequent(c, 3) == "‘Budget Delivers for Families’ (n 3)"


def test_a_social_media_post_is_referred_to_by_its_username():
    assert _subsequent(Citation(source=STEPHENSON), 116) == "@s_m_stephenson (n 116)"
    # nothing to invert: a username is not a name
    assert _bib(Citation(source=STEPHENSON)).startswith("@s_m_stephenson (Scott Stephenson) (Twitter")


def test_a_un_document_is_referred_to_by_its_short_title_and_document_number():
    # r 9.5 example 48
    c = Citation(source=RES_1325, short_title="Resolution 1325", pinpoints=[Pinpoint(kind="paragraph", value="7")])
    assert _subsequent(c, 45) == "*Resolution 1325*, UN Doc S/RES/1325 (n 45) para 7"
    # r 9.3.1 example 40: a committee's views are not a resolution, so paragraphs keep their brackets
    views = Citation(
        source=UNDocumentSource(author="Human Rights Committee", title="Views: Communication No 1011/2001", session="81",
                                document_number="CCPR/C/81/D/1011/2001", date="26 August 2004"),
        short_title="Madafferi v Australia",
        pinpoints=[Pinpoint(value="22"), Pinpoint(kind="paragraph", value="10")],
    )
    assert _subsequent(views, 38) == "*Madafferi v Australia*, UN Doc CCPR/C/81/D/1011/2001 (n 38) 22 [10]"


def test_a_resolutions_paragraphs_are_paras_in_an_ibid_too():
    c = _norm(Citation(source=RES_1325, pinpoints=[Pinpoint(kind="paragraph", value="3")]))
    assert formatter_for(c).ibid_pinpoint(c) == "para 3"
    two = _norm(Citation(source=RES_1325, pinpoints=[Pinpoint(kind="paragraph", value="3"),
                                                      Pinpoint(kind="paragraph", value="5")]))
    assert formatter_for(two).ibid_pinpoint(two) == "paras 3, 5"


def test_a_dictionary_or_encyclopedia_without_a_short_title_is_repeated_in_full():
    for source in (DictionarySource(title="Macquarie Dictionary", edition="5", year="2009", entry="demise"),
                   LegalEncyclopediaSource(publisher="LexisNexis", title="Halsbury’s Laws of Australia", online=True,
                                           retrieved="1 May 2024", title_name="Insurance")):
        c = _norm(Citation(source=source))
        assert formatter_for(c).short_title(c) == ""


def test_an_encyclopedia_paragraph_keeps_its_hyphen_but_a_span_takes_an_en_dash():
    src = LegalEncyclopediaSource(publisher="Westlaw AU", title="The Laws of Australia", online=True,
                                  retrieved="15 February 2018", title_number="2", title_name="Administrative Law")
    assert _full(Citation(source=src, pinpoints=[Pinpoint(kind="paragraph", value="235-270")])).endswith(" [235-270]")
    assert _full(Citation(source=src, pinpoints=[Pinpoint(kind="paragraph", value="2.3.10–2.3.15")])).endswith(
        " [2.3.10]–[2.3.15]")


def test_missing_parts_are_flagged_not_invented():
    assert "[MISSING: retrieved]" in _full(Citation(source=DictionarySource(title="Macquarie Dictionary", online=True,
                                                                            entry="punctilious")))
    assert "[MISSING: document_number]" in _full(Citation(source=UNDocumentSource(resolution="SC Res 1441")))
    assert "[MISSING: platform]" in _full(Citation(source=SocialMediaSource(username="someone", date="1 May 2024")))


# ---- normalisation ---------------------------------------------------------- #

_EXAMPLES = [e for name in ("other_sources.json", "un.json")
             for e in json.loads((Path(__file__).parent / "aglc4_examples" / name).read_text(encoding="utf-8"))]


@pytest.mark.parametrize("entry", _EXAMPLES, ids=lambda e: e["id"])
def test_the_guides_examples_come_through_the_normaliser_unchanged(entry):
    c, warnings = normalise_citation(Citation.model_validate(entry["citation"]))
    rendered = formatter_for(c).full(c)
    assert rendered.to_markup() == entry["expected_full"]
    assert warnings == []
    assert validate.missing_from_rendering(c, rendered.text) == []



def test_a_lecture_name_loses_the_and_its_number_in_the_series():
    src = _norm(Citation(source=SpeechSource(authors=["Lord Sumption"], title="'The Limits of Law'",
                                             lecture="the 27th Sultan Azlan Shah Lecture", forum="Kuala Lumpur",
                                             date="20th November 2013"))).source
    assert (src.title, src.lecture, src.date) == ("The Limits of Law", "Sultan Azlan Shah Lecture", "20 November 2013")


def test_an_ordinary_address_is_a_speech_and_honorifics_go():
    c = Citation(source=SpeechSource(authors=["The Hon Robert French AC"], title="Rights and Freedoms",
                                     lecture="Keynote Address", forum="University of Sydney", date="1 May 2015"))
    assert _full(c) == "Robert French, ‘Rights and Freedoms’ (Speech, University of Sydney, 1 May 2015)"


def test_a_media_releases_body_is_dropped_when_it_is_the_author():
    src = DEFENCE.model_copy(update={"body": "Department of Defence (Cth)", "document_number": "No MSPA 172/09"})
    assert _full(Citation(source=src)) == (
        "Department of Defence (Cth), ‘Highest East Timorese Honour for Army Officers’ (Media Release MSPA 172/09, 22 May 2009)")


def test_a_ministers_titles_go_but_their_portfolio_stays():
    c = Citation(source=MediaReleaseSource(authors=["The Hon Mark Dreyfus KC MP"], authors_are_bodies=False,
                                           title="Privacy Reforms", release_type="Press Release", body="Attorney-General",
                                           date="28 September 2023"))
    assert _full(c) == "Mark Dreyfus, ‘Privacy Reforms’ (Press Release, Attorney-General, 28 September 2023)"


def test_dictionary_edition_definition_and_retrieval_date_are_tidied():
    c = _norm(Citation(source=DictionarySource(title="Macquarie Dictionary", edition="5th edn", year="2009", entry="‘demise’"),
                       pinpoints=[Pinpoint(kind="other", value="def 4")]))
    assert formatter_for(c).full(c).to_markup() == "*Macquarie Dictionary* (5th ed, 2009) ‘demise’ (def 4)"
    online = DictionarySource(title="Macquarie Dictionary", retrieved="accessed 20th February 2018", entry="punctilious")
    assert _full(Citation(source=online)) == "*Macquarie Dictionary* (online at 20 February 2018) ‘punctilious’"


def test_an_encyclopedias_volume_and_page_pinpoints_are_moved_where_they_belong():
    c = _norm(Citation(source=LegalEncyclopediaSource(publisher="LexisNexis Pty Ltd", title="Halsbury's Laws of Australia",
                                                      date="at 25 May 2009", title_number="235", title_name="Insurance",
                                                      chapter="'2 General Principles'"),
                       pinpoints=[Pinpoint(kind="volume", value="15"), Pinpoint(kind="page", value="[235-270]")]))
    assert formatter_for(c).full(c).to_markup() == (
        "LexisNexis, *Halsbury's Laws of Australia*, vol 15 (at 25 May 2009) 235 Insurance, ‘2 General Principles’ [235-270]")


def test_a_twitter_handle_gets_its_at_sign_and_the_platform_its_capitals():
    src = _norm(Citation(source=SocialMediaSource(username="s_m_stephenson", platform="twitter", date="17 July 2017"))).source
    assert (src.username, src.platform) == ("@s_m_stephenson", "Twitter")
    # a display name with a space is not a handle
    named = _norm(Citation(source=SocialMediaSource(username="Scott Stephenson", platform="Twitter"))).source
    assert named.username == "Scott Stephenson"


def test_un_document_elements_lose_their_labels_and_take_the_guides_abbreviations():
    src = _norm(Citation(source=UNDocumentSource(
        title="2005 World Summit Outcome", resolution="General Assembly Resolution 60/1",
        official_records="General Assembly Official Records", session="60th session", meeting="8th plenary meeting",
        agenda_items=["Agenda Items 46 and 120"], supplement="Supp. No. 49", document_number="U.N. Doc. A/RES/60/1",
        date="24th October 2005", adopted="adopted 16 September 2005"))).source
    assert _full(Citation(source=src)) == (
        "*2005 World Summit Outcome*, GA Res 60/1, UN GAOR, 60th sess, 8th plen mtg, Agenda Items 46 and 120, "
        "Supp No 49, UN Doc A/RES/60/1 (24 October 2005, adopted 16 September 2005)")


def test_resolution_and_committee_variants():
    def res(value: str) -> str:
        return _norm(Citation(source=UNDocumentSource(resolution=value, document_number="x"))).source.resolution

    assert res("G.A. Res. 217A (III)") == "GA Res 217A (III)"
    assert res("UNSC Resolution 1441") == "SC Res 1441"
    assert res("Security Council Resolution No 1441") == "SC Res 1441"
    assert res("ECOSOC Decision 2001/203") == "ESC Dec 2001/203"
    third = _norm(Citation(source=UNDocumentSource(committee="Third Committee", official_records="GAOR",
                                                   document_number="A/C.3/47/SR.35"))).source
    assert (third.committee, third.official_records) == ("3", "UN GAOR")


def test_a_un_document_is_identified_by_its_document_number():
    a = UNDocumentSource(title="United Nations Declaration on the Rights of Indigenous Peoples", resolution="GA Res 61/295",
                         document_number="A/RES/61/295")
    b = UNDocumentSource(resolution="General Assembly Resolution 61/295", document_number="UN Doc A/RES/61/295")
    assert source_key(a) == source_key(b)
    assert source_key(a) != source_key(b.model_copy(update={"document_number": "A/RES/61/296"}))


def test_each_dictionary_definition_is_its_own_source():
    one = DictionarySource(title="Macquarie Dictionary", edition="5", year="2009", entry="demise", definition="4")
    assert source_key(one) != source_key(one.model_copy(update={"definition": "5"}))
    assert source_key(one) != source_key(one.model_copy(update={"entry": "demised"}))


# ---- extraction through to the formatted footnote --------------------------- #


def _fn(n: int, markup: str) -> Footnote:
    rt = RichText()
    for i, part in enumerate(markup.split("*")):
        rt.append(part, italic=i % 2 == 1)
    return Footnote(number=n, original=rt)


def _cite(original: str, source: dict, ref: int | None = None, **citation) -> dict:
    return {"kind": "citation", "original": original, "refers_to_footnote": ref, "citation": {"source": source, **citation}}


_DOT = {"kind": "text", "text": "."}
_NTA = "*Native Title Act 1993* (Cth)."  # another source in between, so a repeat isn't 'Ibid'
_NTA_SEGMENTS = [_cite("Native Title Act 1993 (Cth)", {"type": "legislation", "kind": "act", "title": "Native Title Act",
                                                       "year": "1993", "jurisdiction": "Cth"}), _DOT]


def _run(footnotes: list[Footnote], segments: dict[int, list[dict]]) -> list[str]:
    raw = json.dumps({"footnotes": [{"number": n, "segments": s} for n, s in segments.items()]})
    result = pipeline.process_footnotes(footnotes, get_provider("fake:x", responses=[raw]), bibliography=False)
    assert result.warnings == []
    return [f.formatted.to_markup() for f in result.footnotes]


def test_a_speech_is_extracted_and_formatted():
    text = 'Lord Sumption, "The Limits of Law" (The 27th Sultan Azlan Shah Lecture, Kuala Lumpur, 20th November 2013) at 4'
    out = _run([_fn(1, text + "."), _fn(2, _NTA), _fn(3, "Sumption, above n 1, 6.")], {
        1: [_cite(text, {"type": "speech", "authors": ["Lord Sumption"], "authors_are_bodies": False,
                         "title": "The Limits of Law", "lecture": "The 27th Sultan Azlan Shah Lecture",
                         "forum": "Kuala Lumpur", "date": "20th November 2013"},
                  pinpoints=[{"kind": "page", "value": "4"}]), _DOT],
        2: _NTA_SEGMENTS,
        3: [_cite("Sumption, above n 1, 6", {"type": "other", "text": "Sumption, above n 1, 6"}, ref=1,
                  short_title="Sumption", pinpoints=[{"kind": "page", "value": "6"}]), _DOT],
    })
    assert out == ["Lord Sumption, ‘The Limits of Law’ (Sultan Azlan Shah Lecture, Kuala Lumpur, 20 November 2013) 4.",
                   "*Native Title Act 1993* (Cth).",
                   "Sumption (n 1) 6."]


def test_a_media_release_is_extracted_and_formatted():
    text = ('Department of Defence (Cth), "Highest East Timorese Honour for Army Officers", Media Release No MSPA 172/09, '
            'Department of Defence (Cth), 22 May 2009')
    out = _run([_fn(1, text + ".")], {
        1: [_cite(text, {"type": "media_release", "authors": ["Department of Defence (Cth)"], "authors_are_bodies": True,
                         "title": "Highest East Timorese Honour for Army Officers", "release_type": "Media Release",
                         "document_number": "No MSPA 172/09", "body": "Department of Defence (Cth)",
                         "date": "22 May 2009"}), _DOT],
    })
    assert out == ["Department of Defence (Cth), ‘Highest East Timorese Honour for Army Officers’ "
                   "(Media Release MSPA 172/09, 22 May 2009)."]


def test_a_dictionary_entry_is_extracted_and_formatted():
    print_text = "Macquarie Dictionary, 5th edn, 2009, 'demise', def 4"
    online_text = "Macquarie Dictionary (online, accessed 20th February 2018), 'punctilious'"
    out = _run([_fn(1, print_text + "."), _fn(2, online_text + ".")], {
        1: [_cite(print_text, {"type": "dictionary", "title": "Macquarie Dictionary", "edition": "5th edn", "year": "2009",
                               "entry": "demise"}, pinpoints=[{"kind": "other", "value": "def 4"}]), _DOT],
        2: [_cite(online_text, {"type": "dictionary", "title": "Macquarie Dictionary", "online": True,
                                "retrieved": "20th February 2018", "entry": "punctilious"}), _DOT],
    })
    assert out == ["*Macquarie Dictionary* (5th ed, 2009) ‘demise’ (def 4).",
                   "*Macquarie Dictionary* (online at 20 February 2018) ‘punctilious’."]


def test_a_legal_encyclopedia_is_extracted_and_formatted():
    text = "Halsbury's Laws of Australia (LexisNexis, vol 15, at 25 May 2009) 235 Insurance, '2 General Principles' at [235-270]"
    out = _run([_fn(1, text + "."), _fn(2, "Ibid [235-275].")], {
        1: [_cite(text, {"type": "legal_encyclopedia", "publisher": "LexisNexis", "title": "Halsbury's Laws of Australia",
                         "volume": "15", "date": "25 May 2009", "title_number": "235", "title_name": "Insurance",
                         "chapter": "2 General Principles"},
                  pinpoints=[{"kind": "paragraph", "value": "235-270"}]), _DOT],
        2: [_cite("Ibid [235-275]", {"type": "other", "text": "Ibid [235-275]"}, ref=1,
                  pinpoints=[{"kind": "paragraph", "value": "235-275"}]), _DOT],
    })
    assert out == ["LexisNexis, *Halsbury's Laws of Australia*, vol 15 (at 25 May 2009) 235 Insurance, "
                   "‘2 General Principles’ [235-270].",
                   "Ibid [235-275]."]


def test_a_social_media_post_is_extracted_and_formatted():
    url = "https://twitter.com/s_m_stephenson/status/887169425551441921"
    text = f"s_m_stephenson (Scott Stephenson), twitter, 17 July 2017, 9:37pm AEST, {url}"
    out = _run([_fn(1, text + ".")], {
        1: [_cite(text, {"type": "social_media", "username": "s_m_stephenson", "author_name": "Scott Stephenson",
                         "platform": "twitter", "date": "17 July 2017", "time": "9:37pm", "time_zone": "AEST",
                         "url": url}), _DOT],
    })
    assert out == [f"@s_m_stephenson (Scott Stephenson) (Twitter, 17 July 2017, 9:37pm AEST) <{url}>."]


def test_a_un_resolution_is_extracted_and_formatted():
    undrip = ("General Assembly Resolution 61/295, United Nations Declaration on the Rights of Indigenous Peoples, "
              "U.N. Doc. A/RES/61/295 (13 September 2007), para. 3")
    sc = "SC Res 1325, UN SCOR, 4213th mtg, UN Doc S/RES/1325 (31 October 2000) ('Resolution 1325')"
    out = _run([_fn(1, undrip + "."), _fn(2, "Ibid, para. 5."), _fn(3, sc + "."), _fn(4, _NTA), _fn(5, "Resolution 1325 (n 3) para 7.")], {
        1: [_cite(undrip, {"type": "un_document", "title": "United Nations Declaration on the Rights of Indigenous Peoples",
                           "resolution": "General Assembly Resolution 61/295", "document_number": "U.N. Doc. A/RES/61/295",
                           "date": "13 September 2007"},
                  pinpoints=[{"kind": "paragraph", "value": "3"}]), _DOT],
        2: [_cite("Ibid, para. 5", {"type": "other", "text": "Ibid, para. 5"}, ref=1,
                  pinpoints=[{"kind": "paragraph", "value": "5"}]), _DOT],
        3: [_cite(sc, {"type": "un_document", "resolution": "SC Res 1325", "official_records": "UN SCOR",
                       "meeting": "4213th mtg", "document_number": "S/RES/1325", "date": "31 October 2000"},
                  short_title="Resolution 1325"), _DOT],
        4: _NTA_SEGMENTS,
        5: [_cite("Resolution 1325 (n 3) para 7", {"type": "other", "text": "Resolution 1325 (n 3) para 7"}, ref=3,
                  short_title="Resolution 1325", pinpoints=[{"kind": "paragraph", "value": "7"}]), _DOT],
    })
    assert out == [
        "*United Nations Declaration on the Rights of Indigenous Peoples*, GA Res 61/295, UN Doc A/RES/61/295 "
        "(13 September 2007) para 3.",
        "Ibid para 5.",
        "SC Res 1325, UN SCOR, 4213th mtg, UN Doc S/RES/1325 (31 October 2000) (‘*Resolution 1325*’).",
        "*Native Title Act 1993* (Cth).",
        "*Resolution 1325*, UN Doc S/RES/1325 (n 3) para 7.",
    ]
