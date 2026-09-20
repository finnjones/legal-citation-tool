"""Tests for aglc/formatters/secondary.py (AGLC4 ch 4-7).

Examples are taken verbatim from reference/aglc4.txt where possible; each test
notes the PDF page the example comes from. Cases marked "(derived)" combine a
guide example's data with behaviour described by a rule but not itself shown
as a full worked example (eg default short titles built from r 1.4.1's
general description).
"""

from aglc.formatters.secondary import (
    BookChapterFormatter,
    BookFormatter,
    JournalArticleFormatter,
    NewspaperFormatter,
    ReportFormatter,
    WebsiteFormatter,
    format_names,
    invert_name,
    surname,
)
from aglc.models import (
    BookChapterSource,
    BookSource,
    Citation,
    JournalArticleSource,
    NewspaperSource,
    Pinpoint,
    PinpointKind,
    ReportSource,
    WebsiteSource,
)

journal = JournalArticleFormatter()
book = BookFormatter()
chapter = BookChapterFormatter()
report = ReportFormatter()
newspaper = NewspaperFormatter()
website = WebsiteFormatter()


def pp(kind: PinpointKind, value: str, plural: bool = False) -> Pinpoint:
    return Pinpoint(kind=kind, value=value, plural=plural)


# --------------------------------------------------------------------------- #
# Author helpers (r 4.1)
# --------------------------------------------------------------------------- #


def test_surname_simple():
    assert surname("Harold Luntz") == "Luntz"


def test_surname_multi_word_given_name():
    # r 4.1.1 style: "RJ Ellicott" (PDF PAGE 108) -> surname 'Ellicott'.
    assert surname("RJ Ellicott") == "Ellicott"
    assert surname("Ian M Ramsay") == "Ramsay"


def test_surname_sir_prefix():
    # PDF PAGE 112, example 19: "Sir Anthony Mason".
    assert surname("Sir Anthony Mason") == "Mason"


def test_surname_corporate_author_not_inverted():
    # r 4.1.4, PDF PAGE 108-9: corporate authors used as-is.
    name = "Australian Law Reform Commission"
    assert surname(name) == name
    assert invert_name(name) == name


def test_invert_name_individual():
    assert invert_name("James C Hathaway") == "Hathaway, James C"


def test_format_names_one_two_three_and_four():
    # r 4.1.2, PDF PAGE 109.
    assert format_names(["James Edelman"]) == "James Edelman"
    assert format_names(["James Edelman", "Elise Bant"]) == "James Edelman and Elise Bant"
    assert format_names(["A", "B", "C"]) == "A, B and C"
    assert format_names(["Paul Rishworth", "X", "Y", "Z"]) == "Paul Rishworth et al"


def test_format_names_invert_first_only():
    # r 1.13, PDF PAGE 61: bibliography inverts only the first-listed author.
    names = ["James C Hathaway", "Michelle Foster"]
    assert format_names(names, invert_first=True) == "Hathaway, James C and Michelle Foster"


# --------------------------------------------------------------------------- #
# Journal articles (r 5)
# --------------------------------------------------------------------------- #


def test_journal_article_full_with_volume_and_issue():
    # r 5, PDF PAGE 116: "Harold Luntz, 'A Personal Journey through the Law of
    # Torts' (2005) 27(3) Sydney Law Review 393, 400."
    src = JournalArticleSource(
        authors=["Harold Luntz"],
        title="A Personal Journey through the Law of Torts",
        year="2005",
        volume="27",
        issue="3",
        journal="Sydney Law Review",
        starting_page="393",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "400")])
    assert (
        journal.full(citation).to_markup()
        == "Harold Luntz, ‘A Personal Journey through the Law of Torts’ (2005) 27(3) *Sydney Law Review* 393, 400"
    )


def test_journal_article_year_organised_non_numeric_issue():
    # r 5, PDF PAGE 116: "Lord Woolf, 'Droit Public: English Style' [1995]
    # (Spring) Public Law 57, 60."
    src = JournalArticleSource(
        authors=["Lord Woolf"],
        title="Droit Public: English Style",
        year="1995",
        issue="Spring",
        journal="Public Law",
        starting_page="57",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "60")])
    assert (
        journal.full(citation).to_markup()
        == "Lord Woolf, ‘Droit Public: English Style’ [1995] (Spring) *Public Law* 57, 60"
    )


def test_journal_article_year_organised_numeric_issue_has_space():
    # r 5.4, PDF PAGE 118: "John Kleinig, 'Paternalism and Personal Integrity'
    # [1983] (3) Bulletin of the Australian Society of Legal Philosophy 27."
    src = JournalArticleSource(
        authors=["John Kleinig"],
        title="Paternalism and Personal Integrity",
        year="1983",
        issue="3",
        journal="Bulletin of the Australian Society of Legal Philosophy",
        starting_page="27",
    )
    citation = Citation(source=src)
    assert (
        journal.full(citation).to_markup()
        == "John Kleinig, ‘Paternalism and Personal Integrity’ [1983] (3) *Bulletin of the Australian Society of Legal Philosophy* 27"
    )


def test_journal_article_numeric_issue_attaches_to_volume():
    # r 5.4, PDF PAGE 118: "... (2017) 40(3) Melbourne University Law Review
    # 738, 747-9."
    src = JournalArticleSource(
        authors=["Andrew Edgar"],
        title="Administrative Regulation-Making: Contrasting Parliamentary and Deliberative Legitimacy",
        year="2017",
        volume="40",
        issue="3",
        journal="Melbourne University Law Review",
        starting_page="738",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "747–9")])
    text = journal.full(citation).to_markup()
    assert "40(3) *Melbourne University Law Review* 738, 747–9" in text


def test_journal_article_non_numeric_issue_with_volume_has_space():
    # r 5.4, PDF PAGE 118: "... (2017) 133 (January) Law Quarterly Review 73."
    src = JournalArticleSource(
        authors=["AP Simester"],
        title="Accessory Liability and Common Unlawful Purposes",
        year="2017",
        volume="133",
        issue="January",
        journal="Law Quarterly Review",
        starting_page="73",
    )
    citation = Citation(source=src)
    assert "(2017) 133 (January) *Law Quarterly Review* 73" in journal.full(citation).to_markup()


def test_journal_article_published_in_parts():
    # r 5.8, PDF PAGE 119-120: "RN Gooderson, 'Claim of Right and Dispute of
    # Title' (Pt 1) [1966] (1) Cambridge Law Journal 90."
    src = JournalArticleSource(
        authors=["RN Gooderson"],
        title="Claim of Right and Dispute of Title",
        part="1",
        year="1966",
        issue="1",
        journal="Cambridge Law Journal",
        starting_page="90",
    )
    citation = Citation(source=src)
    assert (
        journal.full(citation).to_markup()
        == "RN Gooderson, ‘Claim of Right and Dispute of Title’ (Pt 1) [1966] (1) *Cambridge Law Journal* 90"
    )


def test_journal_article_forthcoming():
    # r 5.11, PDF PAGE 122: "... (2017) 23 Columbia Journal of European Law
    # (forthcoming)."
    src = JournalArticleSource(
        authors=["Geneviève Helleringer", "Anne-Lise Sibony"],
        title="European Consumer Protection through the Behavioral Lens",
        year="2017",
        volume="23",
        journal="Columbia Journal of European Law",
        forthcoming=True,
    )
    citation = Citation(source=src)
    assert journal.full(citation).to_markup().endswith("*Columbia Journal of European Law* (forthcoming)")


def test_journal_article_advance():
    # r 5.11, PDF PAGE 122: "... (2015) 38(3) Melbourne University Law Review
    # (advance)."
    src = JournalArticleSource(
        authors=["Michael Crommelin"],
        title="Powers of the Head of State",
        year="2015",
        volume="38",
        issue="3",
        journal="Melbourne University Law Review",
        advance=True,
    )
    citation = Citation(source=src)
    assert journal.full(citation).to_markup().endswith("*Melbourne University Law Review* (advance)")


def test_journal_article_missing_authors_flagged():
    src = JournalArticleSource(title="Untitled", year="2020", journal="Some Journal", starting_page="1")
    citation = Citation(source=src)
    assert journal.full(citation).to_markup().startswith("[MISSING: authors]")


def test_journal_article_default_short_title_two_authors():
    # (derived) r 1.4.1, PDF PAGE 34-35 pattern: 'Edelman and Bant (n 2) 260.'
    src = JournalArticleSource(
        authors=["James Edelman", "Elise Bant"],
        title="Some Article",
        year="2016",
        journal="A Journal",
        starting_page="1",
    )
    citation = Citation(source=src)
    assert journal.short_title(citation) == "Edelman and Bant"


def test_journal_article_default_short_title_four_authors_et_al():
    # (derived) r 4.1.2, PDF PAGE 109: 'Rishworth et al (n 3).'
    src = JournalArticleSource(
        authors=["Paul Rishworth", "A", "B", "C"],
        title="Some Article",
        year="2016",
        journal="A Journal",
        starting_page="1",
    )
    citation = Citation(source=src)
    assert journal.short_title(citation) == "Rishworth et al"


def test_journal_article_explicit_short_title_is_quoted():
    # PDF PAGE 38, example 90: "Rubenstein, 'Meanings of Membership' (n 88)
    # 305-11." The short title is quoted, not italicised, and used instead of
    # the surname because multiple works by the same author are cited.
    src = JournalArticleSource(
        authors=["Kim Rubenstein"],
        title="Meanings of Membership: Mary Gaudron's Contributions to Australian Citizenship",
        year="2004",
        volume="15",
        issue="4",
        journal="Public Law Review",
        starting_page="305",
    )
    citation = Citation(source=src, short_title="Meanings of Membership", pinpoints=[pp(PinpointKind.page, "305–11")])
    out = journal.subsequent(citation, journal.short_title(citation), first_footnote=88)
    # r 1.4.1: a personal author is referred to by surname; the short title is added only
    # to tell apart several works by that author, which the document pass does (it knows
    # the whole document). See test_aglc4_subsequent.py::1.4.4-b for the full form
    # "Rubenstein, ‘Meanings of Membership’ (n 88) 305–11".
    assert out.to_markup() == "Rubenstein (n 88) 305–11"


def test_journal_article_bibliography_inverts_first_author():
    # r 1.13, PDF PAGE 61: "Hathaway, James C and Michelle Foster, The Law of
    # Refugee Status (Cambridge University Press, 2nd ed, 2014)" - analogous
    # article entry: "Foster, Michelle, '...' (2012) 13(1) Melbourne Journal
    # of International Law 395" (no pinpoint, no full stop).
    src = JournalArticleSource(
        authors=["Michelle Foster"],
        title="The Implications of the Failed “Malaysia Solution”",
        year="2012",
        volume="13",
        issue="1",
        journal="Melbourne Journal of International Law",
        starting_page="395",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "410")])
    assert journal.bibliography(citation).to_markup().startswith("Foster, Michelle, ")
    assert "410" not in journal.bibliography(citation).to_markup()


# --------------------------------------------------------------------------- #
# Books (r 6)
# --------------------------------------------------------------------------- #


def test_book_full_with_edition_and_pinpoint():
    # r 6, PDF PAGE 123: "Malcolm N Shaw, International Law (Cambridge
    # University Press, 7th ed, 2014) 578."
    src = BookSource(authors=["Malcolm N Shaw"], title="International Law", publisher="Cambridge University Press", edition="7", year="2014")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "578")])
    assert book.full(citation).to_markup() == "Malcolm N Shaw, *International Law* (Cambridge University Press, 7th ed, 2014) 578"


def test_book_chapter_pinpoint_no_comma():
    # r 6.4, PDF PAGE 126: "Cheryl Saunders, ... (Hart Publishing, 2011) ch 5"
    src = BookSource(authors=["Cheryl Saunders"], title="The Constitution of Australia: A Contextual Analysis", publisher="Hart Publishing", year="2011")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.chapter, "5")])
    assert book.full(citation).to_markup() == "Cheryl Saunders, *The Constitution of Australia: A Contextual Analysis* (Hart Publishing, 2011) ch 5"


def test_book_multi_volume_with_pinpoint():
    # r 6.5, PDF PAGE 127: "Joel Feinberg, The Moral Limits of the Criminal
    # Law (Oxford University Press, 1984-88) vol 4, 45."
    src = BookSource(authors=["Joel Feinberg"], title="The Moral Limits of the Criminal Law", publisher="Oxford University Press", year="1984–88", volume="4")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "45")])
    assert book.full(citation).to_markup() == "Joel Feinberg, *The Moral Limits of the Criminal Law* (Oxford University Press, 1984–88) vol 4, 45"


def test_book_multi_volume_no_pinpoint():
    # r 6.3.4, PDF PAGE 126: "Jeremy Bentham, Rationale of Judicial Evidence
    # (Garland Publishing, 1978) vol 1."
    src = BookSource(authors=["Jeremy Bentham"], title="Rationale of Judicial Evidence", publisher="Garland Publishing", year="1978", volume="1")
    citation = Citation(source=src)
    assert book.full(citation).to_markup() == "Jeremy Bentham, *Rationale of Judicial Evidence* (Garland Publishing, 1978) vol 1"


def test_book_edited_no_author():
    # r 4.1.3, PDF PAGE 109: "Peter Birks (ed), New Perspectives in the Roman
    # Law of Property: Essays for Barry Nicholas (Clarendon Press, 1989)."
    src = BookSource(editors=["Peter Birks"], title="New Perspectives in the Roman Law of Property: Essays for Barry Nicholas", publisher="Clarendon Press", year="1989")
    citation = Citation(source=src)
    assert book.full(citation).to_markup() == "Peter Birks (ed), *New Perspectives in the Roman Law of Property: Essays for Barry Nicholas* (Clarendon Press, 1989)"


def test_book_edited_subsequent_reference():
    # PDF PAGE 109, example 8: "Birks (ed) (n 6)."
    src = BookSource(editors=["Peter Birks"], title="New Perspectives in the Roman Law of Property: Essays for Barry Nicholas", publisher="Clarendon Press", year="1989")
    citation = Citation(source=src)
    st = book.short_title(citation)
    assert st == "Birks (ed)"
    out = book.subsequent(citation, st, first_footnote=6)
    assert out.to_markup() == "Birks (ed) (n 6)"


def test_book_authors_and_editors_multiple():
    # r 4.1.3, PDF PAGE 109: "Cedric Ryngaert et al (eds), Judicial Decisions
    # on the Law of International Organizations (Oxford University Press,
    # 2016)."
    src = BookSource(editors=["Cedric Ryngaert", "A", "B", "C"], title="Judicial Decisions on the Law of International Organizations", publisher="Oxford University Press", year="2016")
    citation = Citation(source=src)
    assert book.full(citation).to_markup().startswith("Cedric Ryngaert et al (eds), ")


def test_book_no_author_or_editor_short_title_is_title_italicised():
    # (derived) r 1.4.1: no author/editor -> the title stands in, styled as
    # it was in the full citation (italic, since books are italicised).
    src = BookSource(title="Some Anonymous Work", publisher="A Press", year="2000")
    citation = Citation(source=src)
    st = book.short_title(citation)
    assert st == "Some Anonymous Work"
    out = book.subsequent(citation, st, first_footnote=4)
    assert out.to_markup() == "*Some Anonymous Work* (n 4)"


def test_book_author_and_editor_no_publisher():
    # r 6.1, PDF PAGE 123, example 2: "St John Ambulance Australia,
    # Australian First Aid, ed Shirley Dyson (4th ed, 2006)." Demonstrates
    # r 6.6.2 (author AND editor -> ', ed Editor') and that a publisher is
    # genuinely optional (r 6.3.1), not a missing-data gap.
    src = BookSource(authors=["St John Ambulance Australia"], editors=["Shirley Dyson"], title="Australian First Aid", edition="4", year="2006")
    citation = Citation(source=src)
    assert book.full(citation).to_markup() == "St John Ambulance Australia, *Australian First Aid*, ed Shirley Dyson (4th ed, 2006)"


def test_book_author_editor_and_translators():
    # r 6.6.2 + r 6.7, PDF PAGE 129, example 35: "Ludwig Wittgenstein, *On
    # Certainty*, ed GEM Anscombe and GH von Wright, tr Denis Paul and GEM
    # Anscombe (Harper Torchbooks, 1972)." 'ed'/'tr' never pluralise.
    src = BookSource(
        authors=["Ludwig Wittgenstein"],
        editors=["GEM Anscombe", "GH von Wright"],
        translators=["Denis Paul", "GEM Anscombe"],
        title="On Certainty",
        publisher="Harper Torchbooks",
        year="1972",
    )
    citation = Citation(source=src)
    assert (
        book.full(citation).to_markup()
        == "Ludwig Wittgenstein, *On Certainty*, ed GEM Anscombe and GH von Wright, tr Denis Paul and GEM Anscombe (Harper Torchbooks, 1972)"
    )


def test_book_translator_only():
    # r 6.7, PDF PAGE 129, example 36: "Sigmund Freud, Civilization and its
    # Discontents, tr Joan Riviere (Hogarth Press, 1930)."
    src = BookSource(authors=["Sigmund Freud"], translators=["Joan Riviere"], title="Civilization and its Discontents", publisher="Hogarth Press", year="1930")
    citation = Citation(source=src)
    assert book.full(citation).to_markup() == "Sigmund Freud, *Civilization and its Discontents*, tr Joan Riviere (Hogarth Press, 1930)"


def test_book_revised_edition_with_number():
    # r 6.3.3, PDF PAGE 126, example 16: "... (Kluwer Law International, 3rd
    # rev ed, 2008)."
    src = BookSource(editors=["Konstantinos D Kerameus", "Phaedon J Kozyris"], title="Introduction to Greek Law", publisher="Kluwer Law International", edition="3 rev", year="2008")
    citation = Citation(source=src)
    assert (
        book.full(citation).to_markup()
        == "Konstantinos D Kerameus and Phaedon J Kozyris (eds), *Introduction to Greek Law* (Kluwer Law International, 3rd rev ed, 2008)"
    )


def test_book_unnumbered_revised_edition():
    # r 6.3.3, PDF PAGE 126, example 17: "... (Oxford University Press, rev
    # ed, 2012) 55."
    src = BookSource(authors=["Ernest J Weinrib"], title="The Idea of Private Law", publisher="Oxford University Press", edition="rev", year="2012")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "55")])
    assert book.full(citation).to_markup() == "Ernest J Weinrib, *The Idea of Private Law* (Oxford University Press, rev ed, 2012) 55"


def test_book_forthcoming():
    # r 6.8, PDF PAGE 130, example 40: "... (Miegunyah Press, forthcoming)."
    src = BookSource(authors=["Quentin Bryce"], title="Dear Quentin: Letters of a Governor-General", publisher="Miegunyah Press", year="forthcoming")
    citation = Citation(source=src)
    assert book.full(citation).to_markup() == "Quentin Bryce, *Dear Quentin: Letters of a Governor-General* (Miegunyah Press, forthcoming)"


def test_book_no_publisher_same_as_author():
    # r 6.3.1, PDF PAGE 124, example 12: "Law Institute of Victoria, Legal
    # Directory 2006 (2005)." (publisher omitted: same name as author).
    src = BookSource(authors=["Law Institute of Victoria"], title="Legal Directory 2006", year="2005")
    citation = Citation(source=src)
    assert book.full(citation).to_markup() == "Law Institute of Victoria, *Legal Directory 2006* (2005)"


def test_book_bibliography_inverts_first_author_only():
    # r 1.13, PDF PAGE 61: "Hathaway, James C and Michelle Foster, The Law of
    # Refugee Status (Cambridge University Press, 2nd ed, 2014)"
    src = BookSource(authors=["James C Hathaway", "Michelle Foster"], title="The Law of Refugee Status", publisher="Cambridge University Press", edition="2", year="2014")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "10")])
    assert (
        book.bibliography(citation).to_markup()
        == "Hathaway, James C and Michelle Foster, *The Law of Refugee Status* (Cambridge University Press, 2nd ed, 2014)"
    )


# --------------------------------------------------------------------------- #
# Book chapters (r 6.6.1)
# --------------------------------------------------------------------------- #


def test_chapter_full():
    # r 6.6.1, PDF PAGE 128: "Jeremy Waldron, 'Do Judges Reason Morally?' in
    # Grant Huscroft (ed), Expounding the Constitution: Essays in
    # Constitutional Theory (Cambridge University Press, 2008) 38."
    src = BookChapterSource(
        authors=["Jeremy Waldron"],
        chapter_title="Do Judges Reason Morally?",
        editors=["Grant Huscroft"],
        book_title="Expounding the Constitution: Essays in Constitutional Theory",
        publisher="Cambridge University Press",
        year="2008",
        starting_page="38",
    )
    citation = Citation(source=src)
    assert (
        chapter.full(citation).to_markup()
        == "Jeremy Waldron, ‘Do Judges Reason Morally?’ in Grant Huscroft (ed), *Expounding the Constitution: Essays in Constitutional Theory* (Cambridge University Press, 2008) 38"
    )


def test_chapter_with_pinpoint_and_multiple_editors():
    # r 6.6.1, PDF PAGE 128: "Janet Ransley, ... in Nicholas Aroney, Scott
    # Prasser and JR Nethercote (eds), Restraining Elective Dictatorship: The
    # Upper House Solution? (University of Western Australia Press, 2008)
    # 248, 252-3."
    src = BookChapterSource(
        authors=["Janet Ransley"],
        chapter_title="Illusions of Reform: Queensland's Legislative Assembly since Fitzgerald",
        editors=["Nicholas Aroney", "Scott Prasser", "JR Nethercote"],
        book_title="Restraining Elective Dictatorship: The Upper House Solution?",
        publisher="University of Western Australia Press",
        year="2008",
        starting_page="248",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "252–3")])
    assert (
        chapter.full(citation).to_markup()
        == "Janet Ransley, ‘Illusions of Reform: Queensland's Legislative Assembly since Fitzgerald’ in Nicholas Aroney, Scott Prasser and JR Nethercote (eds), *Restraining Elective Dictatorship: The Upper House Solution?* (University of Western Australia Press, 2008) 248, 252–3"
    )


def test_chapter_with_translator():
    # r 6.7, PDF PAGE 129, example 38 (translator portion only - the guide's
    # full example also gives the *book itself* an author ('in Franz Kafka,
    # *The Complete Stories*, ed Nahum N Glatzer'), which BookChapterSource
    # can't represent since it has no separate book-author field; see final
    # report): "'The Metamorphosis', tr Willa Muir and Edwin Muir in ...".
    src = BookChapterSource(
        authors=["Franz Kafka"],
        chapter_title="The Metamorphosis",
        translators=["Willa Muir", "Edwin Muir"],
        editors=["Nahum N Glatzer"],
        book_title="The Complete Stories",
        publisher="Schocken Books",
        year="1971",
        starting_page="89",
    )
    citation = Citation(source=src)
    text = chapter.full(citation).to_markup()
    assert "‘The Metamorphosis’, tr Willa Muir and Edwin Muir in Nahum N Glatzer (ed), *The Complete Stories*" in text


def test_chapter_subsequent_uses_chapter_author_not_editor():
    # r 6.6.1 note, PDF PAGE 128: "Ransley (n 31) 255. [Not: Ransley (n
    # 29) 255.]" -- ie the chapter's own author, cross-referenced to its own
    # first footnote.
    src = BookChapterSource(
        authors=["Janet Ransley"],
        chapter_title="Illusions of Reform",
        editors=["Nicholas Aroney"],
        book_title="Restraining Elective Dictatorship",
        publisher="UWA Press",
        year="2008",
        starting_page="248",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "255")])
    st = chapter.short_title(citation)
    assert st == "Ransley"
    out = chapter.subsequent(citation, st, first_footnote=31)
    assert out.to_markup() == "Ransley (n 31) 255"


# --------------------------------------------------------------------------- #
# Reports (r 7.1)
# --------------------------------------------------------------------------- #


def test_report_no_author():
    # r 7.1.1, PDF PAGE 132: "Review of the Law of Negligence (Final Report,
    # September 2002) 37-57."
    src = ReportSource(title="Review of the Law of Negligence", document_type="Final Report", date="September 2002")
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "37–57")])
    assert report.full(citation).to_markup() == "*Review of the Law of Negligence* (Final Report, September 2002) 37–57"


def test_report_with_author_and_number():
    # r 1.4.4, PDF PAGE 37: "Australian Law Reform Commission, Traditional
    # Rights and Freedoms: Encroachments by Commonwealth Laws (Report No 129,
    # December 2015) 209 [7.111]."
    src = ReportSource(
        author="Australian Law Reform Commission",
        title="Traditional Rights and Freedoms: Encroachments by Commonwealth Laws",
        document_type="Report",
        document_number="129",
        date="December 2015",
    )
    citation = Citation(source=src, pinpoints=[pp(PinpointKind.page, "209"), pp(PinpointKind.paragraph, "7.111")])
    assert (
        report.full(citation).to_markup()
        == "Australian Law Reform Commission, *Traditional Rights and Freedoms: Encroachments by Commonwealth Laws* (Report No 129, December 2015) 209 [7.111]"
    )


def test_report_corporate_author_short_title_not_inverted():
    src = ReportSource(author="Australian Law Reform Commission", title="Traditional Rights and Freedoms", document_type="Report", document_number="129", date="December 2015")
    citation = Citation(source=src)
    # r 4.1.4: the guide itself recommends a short title here instead (see
    # explicit-short-title test below); this is the fallback when none is
    # supplied.
    assert report.short_title(citation) == "Australian Law Reform Commission"


def test_report_explicit_short_title_subsequent():
    # PDF PAGE 37-38, examples 85 & 87: "... (Report No 129, December 2015)
    # 209 [7.111] ('Traditional Rights and Freedoms')." then "Traditional
    # Rights and Freedoms (n 85) 209 [7.111]."
    src = ReportSource(author="Australian Law Reform Commission", title="Traditional Rights and Freedoms: Encroachments by Commonwealth Laws", document_type="Report", document_number="129", date="December 2015")
    citation = Citation(
        source=src,
        short_title="Traditional Rights and Freedoms",
        pinpoints=[pp(PinpointKind.page, "209"), pp(PinpointKind.paragraph, "7.111")],
    )
    out = report.subsequent(citation, report.short_title(citation), first_footnote=85)
    assert out.to_markup() == "*Traditional Rights and Freedoms* (n 85) 209 [7.111]"


def test_report_volume_pinpoint():
    # r 7.1.1 note (multi-volume reports, PDF PAGE 131-2) + PinpointKind.volume:
    # "(Report No 108, May 2008) vol 1, 339 [7.7]".
    src = ReportSource(title="Some Inquiry", document_type="Report", document_number="108", date="May 2008")
    citation = Citation(
        source=src,
        pinpoints=[pp(PinpointKind.volume, "1"), pp(PinpointKind.page, "339"), pp(PinpointKind.paragraph, "7.7")],
    )
    assert report.full(citation).to_markup() == "*Some Inquiry* (Report No 108, May 2008) vol 1, 339 [7.7]"


def test_report_missing_document_type_and_date():
    src = ReportSource(title="A Report")
    citation = Citation(source=src)
    text = report.full(citation).to_markup()
    assert "[MISSING: document_type]" in text
    assert "[MISSING: date]" in text


# --------------------------------------------------------------------------- #
# Newspaper articles (r 7.11)
# --------------------------------------------------------------------------- #


def test_newspaper_printed():
    # r 7.11.1, PDF PAGE 148: "Stephanie Peatling, 'Female Chief Justice
    # Rewrites the Script', The Age (Melbourne, 31 January 2017) 6."
    src = NewspaperSource(authors=["Stephanie Peatling"], title="Female Chief Justice Rewrites the Script", newspaper="The Age", place="Melbourne", date="31 January 2017", page="6")
    citation = Citation(source=src)
    assert (
        newspaper.full(citation).to_markup()
        == "Stephanie Peatling, ‘Female Chief Justice Rewrites the Script’, *The Age* (Melbourne, 31 January 2017) 6"
    )


def test_newspaper_electronic_with_url():
    # r 7.11.2, PDF PAGE 149: "Farrah Tomazin, 'Kinder Wages Breakthrough',
    # The Age (online, 19 May 2009) <http://...>."
    src = NewspaperSource(
        authors=["Farrah Tomazin"],
        title="Kinder Wages Breakthrough",
        newspaper="The Age",
        date="19 May 2009",
        url="http://www.theage.com.au/national/education/kinder-wages-breakthrough-20090519-bcwh.html",
    )
    citation = Citation(source=src)
    assert (
        newspaper.full(citation).to_markup()
        == "Farrah Tomazin, ‘Kinder Wages Breakthrough’, *The Age* (online, 19 May 2009) <http://www.theage.com.au/national/education/kinder-wages-breakthrough-20090519-bcwh.html>"
    )


def test_newspaper_unsigned_no_author():
    # r 7.11.4, PDF PAGE 150: "'Fury at WA Council Plan', The Australian
    # Financial Review (Sydney, 1 May 2006) 5."
    src = NewspaperSource(title="Fury at WA Council Plan", newspaper="The Australian Financial Review", place="Sydney", date="1 May 2006", page="5")
    citation = Citation(source=src)
    assert (
        newspaper.full(citation).to_markup()
        == "‘Fury at WA Council Plan’, *The Australian Financial Review* (Sydney, 1 May 2006) 5"
    )


def test_newspaper_with_named_section():
    # r 7.11.1, PDF PAGE 149, example 85: "Carolyn Holbrook, 'Brownie
    # Points', Epicure, The Age (Melbourne, 9 August 2005) 4."
    src = NewspaperSource(authors=["Carolyn Holbrook"], title="Brownie Points", newspaper="The Age", section="Epicure", place="Melbourne", date="9 August 2005", page="4")
    citation = Citation(source=src)
    assert (
        newspaper.full(citation).to_markup()
        == "Carolyn Holbrook, ‘Brownie Points’, *Epicure*, *The Age* (Melbourne, 9 August 2005) 4"
    )


def test_newspaper_periodical():
    # r 7.11.3, PDF PAGE 149, example 89: "Jill Lepore, 'The History Test'
    # (27 March 2017) The New Yorker 66."
    src = NewspaperSource(authors=["Jill Lepore"], title="The History Test", newspaper="The New Yorker", periodical=True, date="27 March 2017", page="66")
    citation = Citation(source=src)
    assert newspaper.full(citation).to_markup() == "Jill Lepore, ‘The History Test’ (27 March 2017) *The New Yorker* 66"


def test_newspaper_electronic_with_archived_url():
    # r 7.11.2 + r 4.5, PDF PAGE 149, example 87: "Owen Bowcott, 'Trolling
    # Legislation Needs To Be Simplified, Says Law Commission', The Guardian
    # (online, 13 July 2016) <https://...>, archived at <https://perma.cc/
    # SQ5P-BDRW>."
    src = NewspaperSource(
        authors=["Owen Bowcott"],
        title="Trolling Legislation Needs To Be Simplified, Says Law Commission",
        newspaper="The Guardian",
        date="13 July 2016",
        url="https://www.theguardian.com/technology/2016/jul/13/trolling-legislation-needs-to-be-simplified-says-law-commission",
        archived_url="https://perma.cc/SQ5P-BDRW",
    )
    citation = Citation(source=src)
    assert newspaper.full(citation).to_markup() == (
        "Owen Bowcott, ‘Trolling Legislation Needs To Be Simplified, Says Law Commission’, "
        "*The Guardian* (online, 13 July 2016) "
        "<https://www.theguardian.com/technology/2016/jul/13/trolling-legislation-needs-to-be-simplified-says-law-commission>, "
        "archived at <https://perma.cc/SQ5P-BDRW>"
    )


# --------------------------------------------------------------------------- #
# Internet materials (r 7.15)
# --------------------------------------------------------------------------- #


def test_website_with_author():
    # r 7.15 + r 4.5, PDF PAGE 155, example 113: "Martin Clark, 'Koani v The
    # Queen', Opinions on High (Blog Post, 18 October 2017) <http://...>,
    # archived at <https://perma.cc/FD2P-M22L>."
    src = WebsiteSource(
        authors=["Martin Clark"],
        title="Koani v The Queen",
        website_name="Opinions on High",
        document_type="Blog Post",
        date="18 October 2017",
        url="http://blogs.unimelb.edu.au/opinionsonhigh/2017/10/18/koani-case-page/",
        archived_url="https://perma.cc/FD2P-M22L",
    )
    citation = Citation(source=src)
    assert website.full(citation).to_markup() == (
        "Martin Clark, ‘Koani v The Queen’, *Opinions on High* (Blog Post, 18 October 2017) "
        "<http://blogs.unimelb.edu.au/opinionsonhigh/2017/10/18/koani-case-page/>, "
        "archived at <https://perma.cc/FD2P-M22L>"
    )


def test_website_no_author_no_date():
    # r 7.15, PDF PAGE 155, example 112: "'James Edelman', High Court of
    # Australia (Web Page) <http://...>."
    src = WebsiteSource(title="James Edelman", website_name="High Court of Australia", url="http://www.hcourt.gov.au/justices/current/justice-james-edelman")
    citation = Citation(source=src)
    assert (
        website.full(citation).to_markup()
        == "‘James Edelman’, *High Court of Australia* (Web Page) <http://www.hcourt.gov.au/justices/current/justice-james-edelman>"
    )


def test_website_no_author_short_title_falls_back_to_site_name_italic():
    # (derived) r 1.4.1 + r 7.15: no author -> the web page title (italic)
    # stands in for the author in subsequent references.
    src = WebsiteSource(title="James Edelman", website_name="High Court of Australia")
    citation = Citation(source=src)
    st = website.short_title(citation)
    assert st == "High Court of Australia"
    out = website.subsequent(citation, st, first_footnote=112)
    assert out.to_markup() == "*High Court of Australia* (n 112)"


def test_website_author_equal_to_site_name_omitted():
    # r 7.15: "Where the author and web page title are identical, the author
    # should not be included."
    src = WebsiteSource(authors=["High Court of Australia"], title="Some Page", website_name="High Court of Australia")
    citation = Citation(source=src)
    assert not website.full(citation).to_markup().startswith("High Court of Australia,")
