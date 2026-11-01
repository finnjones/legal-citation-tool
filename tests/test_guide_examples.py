"""The example citations on the AGLC4 guide pages (web/pages/guides/) that are ours rather
than the Guide's own, run through the real formatters.

The guides' guard test (test_api.py) only lets a guide show a citation that appears in the
tests, so every example of our own is pinned here to exactly what the tool produces. They
cite real sources; the pinpoints only illustrate the form.
"""

from __future__ import annotations

import pytest

from aglc.document import render_document
from aglc.formatters import formatter_for
from aglc.models import (
    CaseSource,
    Citation,
    CitationSegment,
    ExplanatoryMemorandumSource,
    Footnote,
    JournalArticleSource,
    LegislationSource,
    ParliamentaryDebatesSource,
    Pinpoint,
    PinpointKind,
    ReportSource,
    RichText,
    TextSegment,
    TreatySource,
    WebsiteSource,
)


def cite(source, *pins: tuple[PinpointKind, str], **kw) -> Citation:
    return Citation(source=source, pinpoints=[Pinpoint(kind=k, value=v) for k, v in pins], **kw)


def full(citation: Citation) -> str:
    return formatter_for(citation).full(citation).to_markup()


def subsequent(citation: Citation, first_footnote: int) -> str:
    f = formatter_for(citation)
    return f.subsequent(citation, f.short_title(citation), first_footnote=first_footnote).to_markup()


def bibliography(citation: Citation) -> str:
    return formatter_for(citation).bibliography(citation).to_markup()


# ---- /guides/journal-articles ------------------------------------------------------------ #

MASON = JournalArticleSource(
    authors=["Anthony Mason"],
    title="The Role of a Constitutional Court in a Federation: A Comparison of the Australian and the United States Experience",
    year="1986", volume="16", journal="Federal Law Review", starting_page="1",
)
GAGELER = JournalArticleSource(
    authors=["Stephen Gageler"], title="Foundations of Australian Federalism and the Role of Judicial Review",
    year="1987", volume="17", journal="Federal Law Review", starting_page="162",
)
DIXON = JournalArticleSource(
    authors=["Owen Dixon"], title="Concerning Judicial Method", year="1956", volume="29",
    journal="Australian Law Journal", starting_page="468",
)


def test_journal_article_examples():
    assert full(cite(MASON, (PinpointKind.page, "5"))) == (
        "Anthony Mason, ‘The Role of a Constitutional Court in a Federation: A Comparison of the Australian and the United States Experience’ (1986) 16 *Federal Law Review* 1, 5"
    )
    assert full(cite(GAGELER, (PinpointKind.page, "165"))) == (
        "Stephen Gageler, ‘Foundations of Australian Federalism and the Role of Judicial Review’ (1987) 17 *Federal Law Review* 162, 165"
    )
    assert full(cite(DIXON)) == "Owen Dixon, ‘Concerning Judicial Method’ (1956) 29 *Australian Law Journal* 468"


def test_journal_article_later_reference_and_bibliography():
    assert subsequent(cite(MASON, (PinpointKind.page, "7")), 4) == "Mason (n 4) 7"
    assert bibliography(cite(DIXON, (PinpointKind.page, "471"))) == (
        "Dixon, Owen, ‘Concerning Judicial Method’ (1956) 29 *Australian Law Journal* 468"
    )


# ---- /guides/reports --------------------------------------------------------------------- #

PATHWAYS = ReportSource(
    author="Australian Law Reform Commission",
    title="Pathways to Justice: Inquiry into the Incarceration Rate of Aboriginal and Torres Strait Islander Peoples",
    document_type="Report", document_number="133", date="December 2017",
)


def test_report_examples():
    assert full(cite(PATHWAYS, (PinpointKind.page, "85"))) == (
        "Australian Law Reform Commission, *Pathways to Justice: Inquiry into the Incarceration Rate of Aboriginal and Torres Strait Islander Peoples* (Report No 133, December 2017) 85"
    )
    access = ReportSource(author="Productivity Commission", title="Access to Justice Arrangements",
                          document_type="Inquiry Report", document_number="72", date="September 2014")
    assert full(cite(access, (PinpointKind.volume, "1"), (PinpointKind.page, "4"))) == (
        "Productivity Commission, *Access to Justice Arrangements* (Inquiry Report No 72, September 2014) vol 1, 4"
    )
    royal = ReportSource(author="Royal Commission into Institutional Responses to Child Sexual Abuse",
                         title="Final Report", document_type="Report", date="December 2017")
    assert full(cite(royal, (PinpointKind.volume, "1"))) == (
        "Royal Commission into Institutional Responses to Child Sexual Abuse, *Final Report* (Report, December 2017) vol 1"
    )


def test_report_later_reference_uses_the_short_title():
    later = cite(PATHWAYS, (PinpointKind.page, "90"), short_title="Pathways to Justice")
    assert subsequent(later, 3) == "*Pathways to Justice* (n 3) 90"


# ---- /guides/websites -------------------------------------------------------------------- #


def test_website_examples():
    aglc = WebsiteSource(title="Australian Guide to Legal Citation", website_name="Melbourne Law School",
                         url="https://law.unimelb.edu.au/mulr/aglc")
    assert full(cite(aglc)) == (
        "‘Australian Guide to Legal Citation’, *Melbourne Law School* (Web Page) <https://law.unimelb.edu.au/mulr/aglc>"
    )
    blog = WebsiteSource(title="About the Blog", website_name="AUSPUBLAW", url="https://auspublaw.org/about-the-blog")
    assert full(cite(blog)) == "‘About the Blog’, *AUSPUBLAW* (Web Page) <https://auspublaw.org/about-the-blog>"


def test_website_later_references_as_the_guide_describes_them():
    blog = WebsiteSource(title="About the Blog", website_name="AUSPUBLAW")
    assert subsequent(cite(blog), 5) == "*AUSPUBLAW* (n 5)"  # no author: the website's name, italic
    # an author left out of the full citation because it matches the website's name is
    # still used, in roman type, in later references
    page = WebsiteSource(authors=["Australian Human Rights Commission"], authors_are_bodies=True,
                         title="Native Title Report 2017", website_name="Australian Human Rights Commission")
    assert not full(cite(page)).startswith("Australian Human Rights Commission,")
    assert subsequent(cite(page), 9) == "Australian Human Rights Commission (n 9)"


# ---- /guides/treaties -------------------------------------------------------------------- #

ICCPR = TreatySource(
    title="International Covenant on Civil and Political Rights", opened_for_signature="16 December 1966",
    treaty_series="999 UNTS 171", entry_into_force="23 March 1976",
)


def test_treaty_examples():
    crc = TreatySource(title="Convention on the Rights of the Child", opened_for_signature="20 November 1989",
                       treaty_series="1577 UNTS 3", entry_into_force="2 September 1990")
    assert full(cite(crc, (PinpointKind.article, "3"))) == (
        "*Convention on the Rights of the Child*, opened for signature 20 November 1989, 1577 UNTS 3 (entered into force 2 September 1990) art 3"
    )
    assert full(cite(ICCPR, (PinpointKind.article, "14(1)"))) == (
        "*International Covenant on Civil and Political Rights*, opened for signature 16 December 1966, 999 UNTS 171 (entered into force 23 March 1976) art 14(1)"
    )
    vclt = TreatySource(title="Vienna Convention on the Law of Treaties", opened_for_signature="23 May 1969",
                        treaty_series="1155 UNTS 331", entry_into_force="27 January 1980")
    assert full(cite(vclt, (PinpointKind.article, "31"))) == (
        "*Vienna Convention on the Law of Treaties*, opened for signature 23 May 1969, 1155 UNTS 331 (entered into force 27 January 1980) art 31"
    )


def test_treaty_later_reference_and_bibliography():
    assert subsequent(cite(ICCPR, (PinpointKind.article, "14(3)"), short_title="ICCPR"), 2) == "*ICCPR* (n 2) art 14(3)"
    assert bibliography(cite(ICCPR, (PinpointKind.article, "14(3)"))) == (
        "*International Covenant on Civil and Political Rights*, opened for signature 16 December 1966, 999 UNTS 171 (entered into force 23 March 1976)"
    )


# ---- /guides/hansard --------------------------------------------------------------------- #


def test_hansard_and_explanatory_memorandum_examples():
    apology = ParliamentaryDebatesSource(jurisdiction="Commonwealth", chamber="House of Representatives",
                                         date="13 February 2008", speaker="Kevin Rudd", speaker_position="Prime Minister")
    assert full(cite(apology, (PinpointKind.page, "167"))) == (
        "Commonwealth, *Parliamentary Debates*, House of Representatives, 13 February 2008, 167 (Kevin Rudd, Prime Minister)"
    )
    em = ExplanatoryMemorandumSource(title="Native Title Bill", year="1993", jurisdiction="Cth")
    assert full(cite(em)) == "Explanatory Memorandum, Native Title Bill 1993 (Cth)"


# ---- /guides/signals: whole footnotes, through the document pass --------------------------- #


def case(name: str, year: str, volume: str, page: str, *pins: tuple[PinpointKind, str], signal=None) -> Citation:
    src = CaseSource(name=name, year=year, year_style="round", volume=volume, report="CLR", starting_page=page)
    return cite(src, *pins, signal=signal, source_key=name)


def rendered(*segments) -> str:
    footnote = Footnote(number=1, original=RichText.plain(""), segments=[
        CitationSegment(citation=s) if isinstance(s, Citation) else TextSegment(text=RichText.plain(s))
        for s in segments
    ])
    return render_document([footnote], bibliography=False).footnotes[0].formatted.to_markup()


MABO = ("Mabo v Queensland [No 2]", "1992", "175", "1")
WIK = ("Wik Peoples v Queensland", "1996", "187", "1")
WARD = ("Western Australia v Ward", "2002", "213", "1")
YORTA = ("Members of the Yorta Yorta Aboriginal Community v Victoria", "2002", "214", "422")


@pytest.mark.parametrize("segments, expected", [
    ([case(*WIK, signal="See")], "See *Wik Peoples v Queensland* (1996) 187 CLR 1."),
    # sources under the same signal are joined by semicolons (r 1.1.3)
    ([case(*MABO, signal="See"), case(*WIK, signal="See")],
     "See *Mabo v Queensland [No 2]* (1992) 175 CLR 1; see *Wik Peoples v Queensland* (1996) 187 CLR 1."),
    # a new signal starts a new sentence, so it is capitalised
    ([case(*WARD), case(*YORTA, signal="Cf")],
     "*Western Australia v Ward* (2002) 213 CLR 1. Cf *Members of the Yorta Yorta Aboriginal Community v Victoria* (2002) 214 CLR 422."),
    ([case(*MABO, (PinpointKind.page, "42")), case(*WIK, signal="See also")],
     "*Mabo v Queensland [No 2]* (1992) 175 CLR 1, 42. See also *Wik Peoples v Queensland* (1996) 187 CLR 1."),
    # inside a sentence, the signal is lower case (r 1.2)
    (["On the content of native title, ", case(*WARD, signal="See generally")],
     "On the content of native title, see generally *Western Australia v Ward* (2002) 213 CLR 1."),
    ([case(*YORTA, signal="But see")],
     "But see *Members of the Yorta Yorta Aboriginal Community v Victoria* (2002) 214 CLR 422."),
])
def test_signal_examples(segments, expected):
    assert rendered(*segments) == expected


def test_signals_are_never_italic():
    out = rendered(case(*WIK, signal="Cf"))
    assert out.startswith("Cf *Wik") and "*Cf" not in out


# ---- /guides/common-mistakes ------------------------------------------------------------ #


def test_common_mistakes_examples():
    act = cite(LegislationSource(title="Native Title Act", year="1993", jurisdiction="Cth"), (PinpointKind.section, "223"))
    assert full(act) == "*Native Title Act 1993* (Cth) s 223"
    assert full(case(*MABO, (PinpointKind.page, "42"))) == "*Mabo v Queensland [No 2]* (1992) 175 CLR 1, 42"

