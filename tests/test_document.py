"""Tests for `aglc.document.render_document`.

These register small stub Formatter subclasses -- not the real, concurrently
developed formatters in `aglc/formatters/*` -- so behaviour here is pinned to
fixed, known output and isolated from the other workstreams building the
actual case/legislation/secondary-source formatting.
"""

from __future__ import annotations

import pytest

from aglc.document import render_document
from aglc.formatters import base as formatters_base
from aglc.formatters.base import (
    BIB_CASES,
    BIB_LEGISLATION,
    BIB_OTHER,
    BIB_SECONDARY,
    BIB_TREATIES,
    Formatter,
    missing,
)
from aglc.models import (
    BookSource,
    CaseSource,
    Citation,
    CitationSegment,
    Footnote,
    JournalArticleSource,
    LegislationSource,
    OtherSource,
    Pinpoint,
    PinpointKind,
    RichText,
    TextSegment,
    TreatySource,
)

OPEN_Q = "‘"
CLOSE_Q = "’"


# --------------------------------------------------------------------------- #
# stub formatters
# --------------------------------------------------------------------------- #


class StubCaseFormatter(Formatter):
    """Mimics AGLC4 ch 2 cases: short title defined, uses '(n x)'."""

    source_type = "case"
    bibliography_category = BIB_CASES
    italic_short_title = True
    defines_short_title = True

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, CaseSource)
        out = RichText.italic(src.name)
        if src.year:
            out.append(f" ({src.year})")
        pin_text = self.pinpoints(citation.pinpoints)
        if pin_text:
            out.append(", " + pin_text)
        if citation.pinpoint_judges:
            out.append(f" ({citation.pinpoint_judges})")
        return out

    def short_title(self, citation: Citation) -> str:
        if citation.short_title:
            return citation.short_title
        src = citation.source
        assert isinstance(src, CaseSource)
        return src.name.split(" v ")[0]


class StubLegislationFormatter(Formatter):
    """Mimics AGLC4 ch 3 legislation: only an author-supplied short title (the
    base `short_title()` default), else the full citation is simply repeated.
    `uses_n_reference` stays at the base default (True): AGLC4 r 1.4.1's own
    example is "*ADJR Act* (n 63) s 5(2)" -- legislation (and treaties) *do*
    use '(n x)', contrary to `Formatter.uses_n_reference`'s docstring."""

    source_type = "legislation"
    bibliography_category = BIB_LEGISLATION
    italic_short_title = True
    defines_short_title = True

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, LegislationSource)
        out = RichText()
        out.append(f"{src.title} {src.year}", italic=True)
        if src.jurisdiction:
            out.append(f" ({src.jurisdiction})")
        pin_text = self.pinpoints(citation.pinpoints)
        if pin_text:
            out.append(" " + pin_text)
        return out

    # short_title(): inherited base default -> `citation.short_title or ""`.


class StubSecondaryFormatter(Formatter):
    """Mimics a secondary source (eg a journal article): no short-title
    definition is ever appended; subsequent references use the author
    surname + '(n x)' instead (r 1.4.1)."""

    source_type = "journal_article"
    bibliography_category = BIB_SECONDARY
    defines_short_title = False

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, JournalArticleSource)
        author = ", ".join(src.authors) if src.authors else missing("authors")
        out = RichText.plain(f'{author}, "{src.title}"')
        if src.year:
            out.append(f" ({src.year})")
        pin_text = self.pinpoints(citation.pinpoints)
        if pin_text:
            out.append(" " + pin_text)
        return out

    def short_title(self, citation: Citation) -> str:
        src = citation.source
        assert isinstance(src, JournalArticleSource)
        return src.authors[0].split()[-1] if src.authors else ""

    def sort_key(self, citation: Citation) -> str:
        src = citation.source
        assert isinstance(src, JournalArticleSource)
        return (src.authors[0] if src.authors else src.title).lower()


class StubBookFormatter(Formatter):
    """Another author-surname-style secondary source (like the article
    formatter above), but with an italicised title -- used together with it
    to test r 1.4.1's same-author disambiguation across *different* source
    types sharing a surname."""

    source_type = "book"
    bibliography_category = BIB_SECONDARY
    italic_short_title = True
    defines_short_title = False

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, BookSource)
        author = ", ".join(src.authors) if src.authors else missing("authors")
        out = RichText.plain(f"{author}, ")
        out.append(src.title, italic=True)
        pin_text = self.pinpoints(citation.pinpoints)
        if pin_text:
            out.append(" " + pin_text)
        return out

    def short_title(self, citation: Citation) -> str:
        src = citation.source
        assert isinstance(src, BookSource)
        return src.authors[0].split()[-1] if src.authors else ""

    def sort_key(self, citation: Citation) -> str:
        src = citation.source
        assert isinstance(src, BookSource)
        return (src.authors[0] if src.authors else src.title).lower()


class StubTreatyFormatter(Formatter):
    source_type = "treaty"
    bibliography_category = BIB_TREATIES
    italic_short_title = True
    defines_short_title = True

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, TreatySource)
        out = RichText.italic(src.title)
        pin_text = self.pinpoints(citation.pinpoints)
        if pin_text:
            out.append(", " + pin_text)
        return out


class StubOtherFormatter(Formatter):
    source_type = "other"
    bibliography_category = BIB_OTHER

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, OtherSource)
        return RichText.plain(src.text)


@pytest.fixture(autouse=True)
def stub_registry(monkeypatch):
    registry = {
        "case": StubCaseFormatter(),
        "legislation": StubLegislationFormatter(),
        "journal_article": StubSecondaryFormatter(),
        "book": StubBookFormatter(),
        "treaty": StubTreatyFormatter(),
        "other": StubOtherFormatter(),
    }
    monkeypatch.setattr(formatters_base, "_REGISTRY", registry)
    yield


# --------------------------------------------------------------------------- #
# builders
# --------------------------------------------------------------------------- #


def pin(value: str, kind: PinpointKind = PinpointKind.page) -> Pinpoint:
    return Pinpoint(kind=kind, value=value)


def case(name="Mabo v Queensland", year="1992", pinpoints=None, **kw) -> Citation:
    return Citation(
        source=CaseSource(name=name, year=year),
        pinpoints=pinpoints or [],
        source_key=kw.pop("source_key", f"case:{name}"),
        **kw,
    )


def legislation(title="Native Title Act", year="1993", jurisdiction="Cth", pinpoints=None, **kw) -> Citation:
    return Citation(
        source=LegislationSource(title=title, year=year, jurisdiction=jurisdiction),
        pinpoints=pinpoints or [],
        source_key=kw.pop("source_key", f"legislation:{title}"),
        **kw,
    )


def article(authors=("Jane Smith",), title="On Trusts", year="2010", pinpoints=None, **kw) -> Citation:
    return Citation(
        source=JournalArticleSource(authors=list(authors), title=title, year=year),
        pinpoints=pinpoints or [],
        source_key=kw.pop("source_key", f"article:{title}"),
        **kw,
    )


def book(authors=("Kim Rubenstein",), title="Australian Citizenship Law in Context", pinpoints=None, **kw) -> Citation:
    return Citation(
        source=BookSource(authors=list(authors), title=title),
        pinpoints=pinpoints or [],
        source_key=kw.pop("source_key", f"book:{title}"),
        **kw,
    )


def treaty_(title="Convention on X", pinpoints=None, **kw) -> Citation:
    return Citation(
        source=TreatySource(title=title),
        pinpoints=pinpoints or [],
        source_key=kw.pop("source_key", f"treaty:{title}"),
        **kw,
    )


def other_source(text="Hansard, 1 Jan 2000", **kw) -> Citation:
    return Citation(
        source=OtherSource(text=text),
        source_key=kw.pop("source_key", f"other:{text}"),
        **kw,
    )


def cseg(citation: Citation) -> CitationSegment:
    return CitationSegment(citation=citation)


def tseg(text: str) -> TextSegment:
    return TextSegment(text=RichText.plain(text))


def footnote(number: int, *segments) -> Footnote:
    return Footnote(number=number, original=RichText.plain(f"[fn {number} raw]"), segments=list(segments))


def texts(result) -> list[str]:
    return [f.formatted.text for f in result.footnotes]


# --------------------------------------------------------------------------- #
# full citations / basic punctuation
# --------------------------------------------------------------------------- #


def test_full_citation_gets_a_single_full_stop():
    result = render_document([footnote(1, cseg(case()))], bibliography=False)
    assert texts(result) == ["Mabo v Queensland (1992)."]
    assert result.footnotes[0].formatted.runs[0].italic is True


def test_no_segments_footnote_is_unchanged():
    original = RichText.plain("Some raw untouched footnote text")
    fn1 = Footnote(number=1, original=original, segments=[])
    result = render_document([fn1], bibliography=False)
    assert result.footnotes[0].formatted.to_markup() == original.to_markup()


# --------------------------------------------------------------------------- #
# ibid (r 1.4.3)
# --------------------------------------------------------------------------- #


def test_ibid_same_pinpoint():
    c1 = case(pinpoints=[pin("42")])
    c2 = case(pinpoints=[pin("42")])
    result = render_document([footnote(1, cseg(c1)), footnote(2, cseg(c2))], bibliography=False)
    assert texts(result) == ["Mabo v Queensland (1992), 42.", "Ibid."]


def test_ibid_different_pinpoint():
    c1 = case(pinpoints=[pin("40")])
    c2 = case(pinpoints=[pin("45")])
    result = render_document([footnote(1, cseg(c1)), footnote(2, cseg(c2))], bibliography=False)
    assert texts(result) == ["Mabo v Queensland (1992), 40.", "Ibid 45."]


def test_ibid_blocked_by_multi_source_previous_footnote():
    c1 = case(name="Mabo v Queensland", pinpoints=[pin("1")])
    interrupt = legislation()
    c2 = case(name="Mabo v Queensland", pinpoints=[pin("45")])
    result = render_document(
        [footnote(1, cseg(c1), cseg(interrupt)), footnote(2, cseg(c2))], bibliography=False
    )
    assert texts(result) == [
        f"Mabo v Queensland (1992), 1 ({OPEN_Q}Mabo{CLOSE_Q}); Native Title Act 1993 (Cth).",
        "Mabo (n 1) 45.",
    ]


def test_ibid_blocked_by_no_citation_previous_footnote():
    c1 = case(pinpoints=[pin("1")])
    c2 = case(pinpoints=[pin("2")])
    result = render_document(
        [footnote(1, cseg(c1)), footnote(2, tseg("Discursive text only.")), footnote(3, cseg(c2))],
        bibliography=False,
    )
    # footnote 2 has no citations at all, so footnote 3 cannot ibid back to footnote 1.
    assert "Ibid" not in result.footnotes[2].formatted.text
    assert result.footnotes[2].formatted.text == f"Mabo (n 1) 2."


def test_ibid_cannot_refer_within_the_same_footnote():
    c1 = case(pinpoints=[pin("1")])
    c1b = case(pinpoints=[pin("2")])
    result = render_document([footnote(1, cseg(c1), cseg(c1b))], bibliography=False)
    assert texts(result) == [
        f"Mabo v Queensland (1992), 1 ({OPEN_Q}Mabo{CLOSE_Q}); Mabo (n 1) 2.",
    ]


def test_ibid_after_a_signal_with_different_pinpoint():
    c1 = case(pinpoints=[pin("40")])
    c2 = case(pinpoints=[pin("42")], signal="See")
    result = render_document([footnote(1, cseg(c1)), footnote(2, cseg(c2))], bibliography=False)
    assert texts(result) == ["Mabo v Queensland (1992), 40.", "See ibid 42."]


def test_ibid_after_a_signal_with_same_pinpoint():
    c1 = case(pinpoints=[pin("40")])
    c2 = case(pinpoints=[pin("40")], signal="See")
    result = render_document([footnote(1, cseg(c1)), footnote(2, cseg(c2))], bibliography=False)
    assert texts(result) == ["Mabo v Queensland (1992), 40.", "See ibid."]


def test_ibid_lowercase_when_not_at_sentence_start():
    c1 = case(pinpoints=[pin("40")])
    c2 = case(pinpoints=[pin("40")])
    result = render_document(
        [footnote(1, cseg(c1)), footnote(2, tseg("Note: "), cseg(c2))], bibliography=False
    )
    assert result.footnotes[1].formatted.text == "Note: ibid."


def test_ibid_may_be_the_first_of_several_sources_in_a_footnote():
    # AGLC4 r 1.1.3/1.4.3: "Ibid; *R v Macleod* (2001) 52 NSWLR 389." -- ibid
    # can open a footnote that goes on to cite further, different sources.
    c1 = case(pinpoints=[pin("1")])
    c2 = case(pinpoints=[pin("1")])
    new_case = case(name="R v Macleod", year="2001")
    result = render_document(
        [footnote(1, cseg(c1)), footnote(2, cseg(c2), cseg(new_case))], bibliography=False
    )
    assert result.footnotes[1].formatted.text == "Ibid; R v Macleod (2001)."


def test_ibid_blocked_when_current_pinpoint_missing_but_previous_had_one():
    # AGLC4 r 1.4.3 note + example 80: if the preceding footnote has a
    # pinpoint but this citation needs none, fall back to r 1.4.1 (n x)
    # rather than using 'ibid'.
    c1 = case(pinpoints=[pin("185")])
    c2 = case(signal="See generally")
    result = render_document([footnote(1, cseg(c1)), footnote(2, cseg(c2))], bibliography=False)
    assert texts(result) == [
        f"Mabo v Queensland (1992), 185 ({OPEN_Q}Mabo{CLOSE_Q}).",
        "See generally Mabo (n 1).",
    ]


# --------------------------------------------------------------------------- #
# subsequent references / short titles (r 1.4.1, 1.4.4)
# --------------------------------------------------------------------------- #


def test_subsequent_n_reference_with_pinpoint_across_an_interruption():
    c1 = case(pinpoints=[pin("10")])
    interrupt = legislation()
    c3 = case(pinpoints=[pin("20")])
    result = render_document(
        [footnote(1, cseg(c1)), footnote(2, cseg(interrupt)), footnote(3, cseg(c3))], bibliography=False
    )
    assert result.footnotes[0].formatted.text == f"Mabo v Queensland (1992), 10 ({OPEN_Q}Mabo{CLOSE_Q})."
    assert result.footnotes[2].formatted.text == "Mabo (n 1) 20."


def test_legislation_style_repeat_has_no_n_reference():
    l1 = legislation(pinpoints=[pin("5", PinpointKind.section)])
    interrupt = case()
    l3 = legislation(pinpoints=[pin("6", PinpointKind.section)])
    result = render_document(
        [footnote(1, cseg(l1)), footnote(2, cseg(interrupt)), footnote(3, cseg(l3))], bibliography=False
    )
    assert result.footnotes[0].formatted.text == "Native Title Act 1993 (Cth) s 5."
    assert result.footnotes[2].formatted.text == "Native Title Act 1993 (Cth) s 6."
    assert "(n" not in result.footnotes[2].formatted.text
    assert OPEN_Q not in result.footnotes[0].formatted.text  # no author-defined short title


def test_short_title_definition_not_added_for_a_single_citation():
    result = render_document([footnote(1, cseg(case()))], bibliography=False)
    assert OPEN_Q not in result.footnotes[0].formatted.text


def test_short_title_definition_added_when_cited_again_non_ibid():
    c1 = case()
    interrupt = legislation()
    c2 = case(pinpoints=[pin("5")])
    result = render_document(
        [footnote(1, cseg(c1)), footnote(2, cseg(interrupt)), footnote(3, cseg(c2))], bibliography=False
    )
    assert f"({OPEN_Q}Mabo{CLOSE_Q})" in result.footnotes[0].formatted.text


def test_short_title_definition_not_added_when_only_cited_via_ibid():
    c1 = case(pinpoints=[pin("100")])
    c2 = case(pinpoints=[pin("101")])
    result = render_document([footnote(1, cseg(c1)), footnote(2, cseg(c2))], bibliography=False)
    assert OPEN_Q not in result.footnotes[0].formatted.text
    assert result.footnotes[1].formatted.text == "Ibid 101."


def test_author_supplied_short_title_used_even_for_a_single_citation():
    c1 = case(short_title="Mabo No 2")
    result = render_document([footnote(1, cseg(c1))], bibliography=False)
    assert f"({OPEN_Q}Mabo No 2{CLOSE_Q})" in result.footnotes[0].formatted.text


def test_author_supplied_short_title_for_legislation_uses_n_reference():
    # AGLC4 r 1.4.1's own example: "*ADJR Act* (n 63) s 5(2)" -- legislation
    # short titles *do* get a '(n x)' cross-reference (see StubLegislationFormatter).
    l1 = legislation(title="ADJR Act", year="1977", short_title="ADJR Act")
    interrupt = case()
    l2 = legislation(title="ADJR Act", year="1977", pinpoints=[pin("5", PinpointKind.section)])
    result = render_document(
        [footnote(1, cseg(l1)), footnote(2, cseg(interrupt)), footnote(3, cseg(l2))], bibliography=False
    )
    assert result.footnotes[0].formatted.text == f"ADJR Act 1977 (Cth) ({OPEN_Q}ADJR Act{CLOSE_Q})."
    assert result.footnotes[2].formatted.text == "ADJR Act (n 1) s 5."


def test_treaty_subsequent_reference_uses_n_reference():
    # AGLC4 r 1.4.1 example flavour: "*Timor Gap Treaty* (n 20) art 6(1)".
    t1 = treaty_(title="Timor Gap Treaty", short_title="Timor Gap Treaty")
    interrupt = case()
    t2 = treaty_(title="Timor Gap Treaty", pinpoints=[pin("6", PinpointKind.article)])
    result = render_document(
        [footnote(1, cseg(t1)), footnote(2, cseg(interrupt)), footnote(3, cseg(t2))], bibliography=False
    )
    assert result.footnotes[2].formatted.text == "Timor Gap Treaty (n 1) art 6."


def test_uses_n_reference_false_is_respected_when_a_formatter_sets_it(monkeypatch):
    # document.py must never hardcode which source types use '(n x)' -- it
    # relies entirely on `Formatter.uses_n_reference`. This isolated test
    # (not "legislation" or "treaty", which both use '(n x)' for real) checks
    # that a formatter opting out of it is still honoured.
    class NoNReferenceTreatyFormatter(StubTreatyFormatter):
        uses_n_reference = False

    monkeypatch.setitem(formatters_base._REGISTRY, "treaty", NoNReferenceTreatyFormatter())

    t1 = treaty_(title="Convention on X", short_title="Convention on X")
    interrupt = case()
    t2 = treaty_(title="Convention on X", pinpoints=[pin("6", PinpointKind.article)])
    result = render_document(
        [footnote(1, cseg(t1)), footnote(2, cseg(interrupt)), footnote(3, cseg(t2))], bibliography=False
    )
    assert result.footnotes[2].formatted.text == "Convention on X, art 6."
    assert "(n" not in result.footnotes[2].formatted.text


def test_secondary_source_never_gets_a_short_title_definition():
    a1 = article(pinpoints=[pin("10")])
    interrupt = case()
    a2 = article(pinpoints=[pin("20")])
    result = render_document(
        [footnote(1, cseg(a1)), footnote(2, cseg(interrupt)), footnote(3, cseg(a2))], bibliography=False
    )
    assert OPEN_Q not in result.footnotes[0].formatted.text
    assert result.footnotes[2].formatted.text == "Smith (n 1) 20."


def test_same_author_multiple_works_are_disambiguated_with_the_title():
    # AGLC4 r 1.4.1: "if several works by the same author/s are cited, both
    # the surname ... and the title or short title ... should be provided" --
    # eg "Rubenstein, *Australian Citizenship Law in Context* (n 59) 48" and
    # "Rubenstein, 'Meanings of Membership' (n 58) 307-11". The two works are
    # of different source types (book vs article) but share a surname.
    b1 = book(authors=["Kim Rubenstein"], title="Australian Citizenship Law in Context", pinpoints=[pin("48")])
    a1 = article(authors=["Kim Rubenstein"], title="Meanings of Membership", pinpoints=[pin("305")])
    interrupt = case()
    b2 = book(authors=["Kim Rubenstein"], title="Australian Citizenship Law in Context", pinpoints=[pin("65")])
    a2 = article(authors=["Kim Rubenstein"], title="Meanings of Membership", pinpoints=[pin("307")])

    result = render_document(
        [
            footnote(1, cseg(b1)),
            footnote(2, cseg(a1)),
            footnote(3, cseg(interrupt)),
            footnote(4, cseg(b2)),
            footnote(5, cseg(a2)),
        ],
        bibliography=False,
    )

    assert result.footnotes[3].formatted.text == "Rubenstein, Australian Citizenship Law in Context (n 1) 65."
    assert result.footnotes[4].formatted.text == f"Rubenstein, {OPEN_Q}Meanings of Membership{CLOSE_Q} (n 2) 307."
    # the book title is italicised, the article title is not (r 1.4.4: "italicised
    # for a book title, in inverted commas for a journal article").
    assert any(run.italic for run in result.footnotes[3].formatted.runs)
    assert not any(run.italic for run in result.footnotes[4].formatted.runs)


def test_single_author_work_is_not_disambiguated():
    a1 = article(authors=["Jane Smith"], title="On Trusts", pinpoints=[pin("10")])
    interrupt = case()
    a2 = article(authors=["Jane Smith"], title="On Trusts", pinpoints=[pin("20")])
    result = render_document(
        [footnote(1, cseg(a1)), footnote(2, cseg(interrupt)), footnote(3, cseg(a2))], bibliography=False
    )
    assert result.footnotes[2].formatted.text == "Smith (n 1) 20."


# --------------------------------------------------------------------------- #
# signals (r 1.2)
# --------------------------------------------------------------------------- #


def test_signal_capitalised_at_footnote_start():
    result = render_document([footnote(1, cseg(case(signal="See")))], bibliography=False)
    assert result.footnotes[0].formatted.text.startswith("See ")


def test_signal_lowercased_mid_sentence():
    c1 = case(signal="See generally", pinpoints=[pin("198")])
    result = render_document(
        [footnote(1, tseg("There are differing views: "), cseg(c1))], bibliography=False
    )
    text = result.footnotes[0].formatted.text
    assert "see generally" in text
    assert "See generally" not in text


def test_cf_signal_capitalised_after_new_sentence():
    c1 = case(name="A v B", year="2000")
    c2 = case(name="C v D", year="2001", signal="Cf")
    result = render_document([footnote(1, cseg(c1), cseg(c2))], bibliography=False)
    assert texts(result) == ["A v B (2000). Cf C v D (2001)."]


# --------------------------------------------------------------------------- #
# multiple sources in one footnote (r 1.1.3) / closing punctuation (r 1.1.4)
# --------------------------------------------------------------------------- #


def test_adjacent_citations_joined_by_semicolons():
    c1 = case(name="A v B", year="2000")
    c2 = case(name="C v D", year="2001")
    c3 = case(name="E v F", year="2002")
    result = render_document([footnote(1, cseg(c1), cseg(c2), cseg(c3))], bibliography=False)
    assert texts(result) == ["A v B (2000); C v D (2001); E v F (2002)."]


def test_existing_separator_between_citations_is_not_duplicated():
    c1 = case(name="A v B", year="2000")
    c2 = case(name="C v D", year="2001")
    result = render_document([footnote(1, cseg(c1), tseg("; "), cseg(c2))], bibliography=False)
    assert texts(result) == ["A v B (2000); C v D (2001)."]


def test_closing_punctuation_not_doubled_after_existing_sentence_end():
    result = render_document(
        [footnote(1, cseg(case()), tseg(". What of this?"))], bibliography=False
    )
    assert texts(result) == ["Mabo v Queensland (1992). What of this?"]


def test_closing_punctuation_not_doubled_for_discursive_text():
    result = render_document([footnote(1, tseg("Note that s 22 applies."))], bibliography=False)
    assert texts(result) == ["Note that s 22 applies."]


def test_closing_punctuation_added_after_a_url():
    citation = other_source(text="Smith, 'Title' <https://example.com>")
    result = render_document([footnote(1, cseg(citation))], bibliography=False)
    assert texts(result) == ["Smith, 'Title' <https://example.com>."]


# --------------------------------------------------------------------------- #
# warnings
# --------------------------------------------------------------------------- #


def test_missing_marker_produces_a_warning():
    citation = other_source(text="Some source [MISSING: date]")
    result = render_document([footnote(1, cseg(citation))], bibliography=False)
    assert len(result.warnings) == 1
    assert result.warnings[0].footnote == 1


def test_no_warning_when_nothing_missing():
    result = render_document([footnote(1, cseg(case()))], bibliography=False)
    assert result.warnings == []


# --------------------------------------------------------------------------- #
# bibliography (r 1.13)
# --------------------------------------------------------------------------- #


def test_bibliography_grouping_sorting_and_dedup():
    f1 = footnote(1, cseg(case(name="Zeta v Alpha", year="2000")))
    f2 = footnote(2, cseg(case(name="Alpha v Beta", year="2001")))
    f3 = footnote(3, cseg(legislation(title="Some Act")))
    f4 = footnote(4, cseg(article(authors=["Jane Smith"], title="An Article")))
    f5 = footnote(5, cseg(case(name="Zeta v Alpha", year="2000")))  # repeat -> dedup

    result = render_document([f1, f2, f3, f4, f5], bibliography=True)

    headings = [section.heading for section in result.bibliography]
    assert headings == [BIB_SECONDARY, BIB_CASES, BIB_LEGISLATION]  # BIB_ORDER, empty sections omitted

    cases_section = next(s for s in result.bibliography if s.heading == BIB_CASES)
    assert len(cases_section.entries) == 2
    assert cases_section.entries[0].text.startswith("Alpha v Beta")
    assert cases_section.entries[1].text.startswith("Zeta v Alpha")


def test_bibliography_entries_have_no_trailing_full_stop():
    result = render_document([footnote(1, cseg(case(pinpoints=[pin("42")])))], bibliography=True)
    for section in result.bibliography:
        for entry in section.entries:
            assert not entry.text.endswith(".")


def test_bibliography_omitted_when_not_requested():
    result = render_document([footnote(1, cseg(case()))], bibliography=False)
    assert result.bibliography == []


def test_bibliography_includes_treaties_and_other_categories():
    f1 = footnote(1, cseg(treaty_(title="Convention on X")))
    f2 = footnote(2, cseg(other_source(text="Hansard, 1 Jan 2000")))
    result = render_document([f1, f2], bibliography=True)
    headings = [section.heading for section in result.bibliography]
    assert headings == [BIB_TREATIES, BIB_OTHER]
