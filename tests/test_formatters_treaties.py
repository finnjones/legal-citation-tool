"""Tests for aglc/formatters/treaties.py (AGLC4 ch 8).

Examples are taken verbatim from reference/aglc4.txt where possible; each test
notes the PDF page the example comes from.
"""

from aglc.formatters.treaties import TreatyFormatter
from aglc.models import Citation, Pinpoint, PinpointKind, TreatySource

fmt = TreatyFormatter()


def pp(kind: PinpointKind, value: str, plural: bool = False) -> Pinpoint:
    return Pinpoint(kind=kind, value=value, plural=plural)


def test_open_multilateral_treaty_with_pinpoint():
    # r 8, PDF PAGE 158: "Treaty on the Non-Proliferation of Nuclear Weapons,
    # opened for signature 1 July 1968, 729 UNTS 161 (entered into force 5
    # March 1970) art 3."
    src = TreatySource(
        title="Treaty on the Non-Proliferation of Nuclear Weapons",
        opened_for_signature="1 July 1968",
        treaty_series="729 UNTS 161",
        entry_into_force="5 March 1970",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.article, "3")])
    assert (
        fmt.full(citation).to_markup()
        == "*Treaty on the Non-Proliferation of Nuclear Weapons*, opened for signature 1 July 1968, 729 UNTS 161 (entered into force 5 March 1970) art 3"
    )


def test_bilateral_treaty_with_parties_and_pinpoint():
    # r 8, PDF PAGE 158: "Agreement regarding the Transfer of the
    # Administration of Justice in the Territories of Northern Slesvig,
    # Denmark-Germany, signed 12 July 1921, 8 LNTS 397 (entered into force 17
    # January 1922) art 2."
    src = TreatySource(
        title="Agreement regarding the Transfer of the Administration of Justice in the Territories of Northern Slesvig",
        parties=["Denmark", "Germany"],
        signed=True,
        opened_for_signature="12 July 1921",
        treaty_series="8 LNTS 397",
        entry_into_force="17 January 1922",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.article, "2")])
    assert (
        fmt.full(citation).to_markup()
        == "*Agreement regarding the Transfer of the Administration of Justice in the Territories of Northern Slesvig*, Denmark–Germany, signed 12 July 1921, 8 LNTS 397 (entered into force 17 January 1922) art 2"
    )


def test_no_repeated_parties_when_in_title():
    # r 8.2, PDF PAGE 160, example 3: parties already named in the title are
    # not repeated after it.
    src = TreatySource(
        title="Agreement on Cultural and Educative Integration between the Republic of Venezuela and the Republic of Peru",
        signed=True,
        opened_for_signature="12 January 1996",
        treaty_series="2408 UNTS 125",
        entry_into_force="13 March 1997",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.article, "4")])
    assert (
        fmt.full(citation).to_markup()
        == "*Agreement on Cultural and Educative Integration between the Republic of Venezuela and the Republic of Peru*, signed 12 January 1996, 2408 UNTS 125 (entered into force 13 March 1997) art 4"
    )


def test_trilateral_treaty_parties():
    # r 8.2, PDF PAGE 160, example 4: "International Agreement on the
    # Scheldt, Belgium-France-Netherlands, signed 3 December 2002, 2351 UNTS
    # 13 (entered into force 1 December 2005) art 3(1)(a)."
    src = TreatySource(
        title="International Agreement on the Scheldt",
        parties=["Belgium", "France", "Netherlands"],
        signed=True,
        opened_for_signature="3 December 2002",
        treaty_series="2351 UNTS 13",
        entry_into_force="1 December 2005",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.article, "3(1)(a)")])
    assert (
        fmt.full(citation).to_markup()
        == "*International Agreement on the Scheldt*, Belgium–France–Netherlands, signed 3 December 2002, 2351 UNTS 13 (entered into force 1 December 2005) art 3(1)(a)"
    )


def test_signed_and_entered_into_force_same_date():
    # r 8.3.2, PDF PAGE 161, example 8: "Agreement Relating to Co-operation
    # on Antitrust Matters, Australia-United States of America, 1369 UNTS 43
    # (signed and entered into force 29 June 1982)."
    src = TreatySource(
        title="Agreement Relating to Co-operation on Antitrust Matters",
        parties=["Australia", "United States of America"],
        signed=True,
        opened_for_signature="29 June 1982",
        treaty_series="1369 UNTS 43",
        entry_into_force="29 June 1982",
    )
    citation = Citation(source=src)
    assert (
        fmt.full(citation).to_markup()
        == "*Agreement Relating to Co-operation on Antitrust Matters*, Australia–United States of America, 1369 UNTS 43 (signed and entered into force 29 June 1982)"
    )


def test_not_yet_in_force():
    # r 8.3.3, PDF PAGE 161, example 9: "Multilateral Convention to Implement
    # Tax Treaty Related Measures to Prevent Base Erosion and Profit
    # Shifting, opened for signature 31 December 2016, [2017] ATNIF 23 (not
    # yet in force)."
    src = TreatySource(
        title="Multilateral Convention to Implement Tax Treaty Related Measures to Prevent Base Erosion and Profit Shifting",
        opened_for_signature="31 December 2016",
        treaty_series="[2017] ATNIF 23",
        entry_into_force="not yet in force",
    )
    citation = Citation(source=src)
    assert (
        fmt.full(citation).to_markup()
        == "*Multilateral Convention to Implement Tax Treaty Related Measures to Prevent Base Erosion and Profit Shifting*, opened for signature 31 December 2016, [2017] ATNIF 23 (not yet in force)"
    )


def test_annex_pinpoint():
    # r 8.7, PDF PAGE 165, example 19: "... (entered into force 15 July
    # 2001) annex II."
    src = TreatySource(
        title="Agreement Establishing the Advisory Centre on WTO Law",
        opened_for_signature="30 November 1999",
        treaty_series="2299 UNTS 249",
        entry_into_force="15 July 2001",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.annex, "II")])
    assert fmt.full(citation).to_markup().endswith("(entered into force 15 July 2001) annex II")


def test_missing_treaty_series_flagged():
    src = TreatySource(title="Some Treaty", opened_for_signature="1 January 2000", entry_into_force="1 January 2001")
    citation = Citation(source=src)
    assert "[MISSING: treaty_series]" in fmt.full(citation).to_markup()


# --------------------------------------------------------------------------- #
# Short titles and subsequent references (r 1.4.1, r 1.4.4, r 8.8)
# --------------------------------------------------------------------------- #


def test_no_default_short_title_without_author_definition():
    # r 8.1/8.8: unlike cases, a treaty has no automatic short form; the
    # formatter returns "" (meaning: repeat the full citation) unless one was
    # explicitly introduced.
    src = TreatySource(title="Convention on the Rights of the Child", opened_for_signature="20 November 1989", treaty_series="1577 UNTS 3", entry_into_force="2 September 1990")
    citation = Citation(source=src)
    assert fmt.short_title(citation) == ""


def test_subsequent_reference_uses_n_and_no_comma_before_pinpoint():
    # r 8.8, PDF PAGE 166, examples 20 & 22: "... art 4(2)(a) ('Timor Gap
    # Treaty')." then "Timor Gap Treaty (n 20) art 6(1)." - note: '(n 20)' IS
    # used (unlike legislation/cases-style short titles that skip it) and
    # there is no comma before the pinpoint.
    src = TreatySource(
        title="Treaty on the Zone of Cooperation in an Area between the Indonesian Province of East Timor and Northern Australia",
        signed=True,
        opened_for_signature="11 December 1989",
        treaty_series="1654 UNTS 105",
        entry_into_force="9 February 1991",
    )
    citation = Citation(source=src, short_title="Timor Gap Treaty", pinpoints=[pp(PinpointKind.article, "6(1)")])
    st = fmt.short_title(citation)
    assert st == "Timor Gap Treaty"
    out = fmt.subsequent(citation, st, first_footnote=20)
    assert out.to_markup() == "*Timor Gap Treaty* (n 20) art 6(1)"


def test_short_title_of_a_treaty_portion():
    # r 8.8: a short title may name just a portion of a treaty (eg an
    # annex); the formatter doesn't need to know this - it's just whatever
    # short title text the document pass supplies, still italicised and
    # cross-referenced the normal way.
    src = TreatySource(
        title="Convention on the Prohibition of the Development, Production, Stockpiling and Use of Chemical Weapons and on Their Destruction",
        opened_for_signature="13 January 1993",
        treaty_series="1974 UNTS 45",
        entry_into_force="29 April 1997",
    )
    citation = Citation(source=src, short_title="Annex on Chemicals", pinpoints=[pp(PinpointKind.article, "6")])
    out = fmt.subsequent(citation, fmt.short_title(citation), first_footnote=23)
    assert out.to_markup() == "*Annex on Chemicals* (n 23) art 6"


# --------------------------------------------------------------------------- #
# Bibliography (r 1.13)
# --------------------------------------------------------------------------- #


def test_bibliography_no_pinpoint_no_full_stop():
    # r 1.13, PDF PAGE 62, D Treaties example: "Convention against Torture
    # and Other Cruel, Inhuman or Degrading Treatment or Punishment, opened
    # for signature 10 December 1984, 1465 UNTS 85 (entered into force 26
    # June 1987)"
    src = TreatySource(
        title="Convention against Torture and Other Cruel, Inhuman or Degrading Treatment or Punishment",
        opened_for_signature="10 December 1984",
        treaty_series="1465 UNTS 85",
        entry_into_force="26 June 1987",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.article, "1")])
    assert (
        fmt.bibliography(citation).to_markup()
        == "*Convention against Torture and Other Cruel, Inhuman or Degrading Treatment or Punishment*, opened for signature 10 December 1984, 1465 UNTS 85 (entered into force 26 June 1987)"
    )


def test_class_attrs():
    assert fmt.uses_n_reference is True
    assert fmt.italic_short_title is True
    assert fmt.defines_short_title is True
    from aglc.formatters.base import BIB_TREATIES

    assert fmt.bibliography_category == BIB_TREATIES
