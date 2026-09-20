"""Secondary sources: journal articles, books, book chapters, reports,
newspapers and internet materials (AGLC4 ch 4-7).

Shared author-formatting rules (r 4.1) and the r 1.13 bibliography rules
(name inversion of the first author only, no pinpoints, no full stop) are
implemented once here and reused by every formatter in this module.

Two title styles recur throughout ch 4-7:
  - "quoted" titles (article/chapter/document titles, r 5.2/6.6.1/7.15): single
    curly quotes, not italicised.
  - "italic" titles (book/report/website titles, r 6.2/7.1/7.15): the *Guide*'s
    normal italic-title convention.
When no author is available, r 1.4.1 says the (short) title stands in for the
author surname in subsequent references, styled the same way it was styled in
the full citation - that's why several `subsequent()` overrides below check
`citation.source.authors`/`.author` rather than relying solely on the
`italic_short_title` class flag (which cannot vary a single class between a
plain surname and a styled title).
"""

from __future__ import annotations

import re

from ..models import (
    BookChapterSource,
    BookSource,
    Citation,
    JournalArticleSource,
    NewspaperSource,
    ReportSource,
    RichText,
    WebsiteSource,
)
from .base import BIB_SECONDARY, Formatter, missing, register

# AGLC uses curly single quotes for quoted titles (r 5.2 etc), eg
# '...Title'.
_LQ, _RQ = "‘", "’"


# --------------------------------------------------------------------------- #
# Author formatting (r 4.1)
# --------------------------------------------------------------------------- #

# Heuristic used to tell a personal name (invert/take-last-word-as-surname)
# from a corporate/institutional author (r 4.1.4) - "Australian Law Reform
# Commission" should never be inverted or have its last word treated as a
# surname.
_ORG_WORDS = {
    "commission", "committee", "department", "authority", "institute",
    "bureau", "council", "government", "court", "corporation", "board",
    "office", "university", "society", "association", "commonwealth",
    "parliament", "tribunal", "organisation", "organization", "agency",
    "ministry", "division", "directorate", "ombudsman", "bank", "union",
    "federation", "foundation", "academy", "college", "service", "services",
    "centre", "center", "group", "trust", "party", "reform", "law",
    "coalition", "network", "alliance", "taskforce", "force", "panel",
}


def is_corporate_author(name: str) -> bool:
    """r 4.1.4: publications authored by a body use the body's name as-is."""
    words = {w.strip(",.") .lower() for w in name.split()}
    return bool(words & _ORG_WORDS)


def surname(name: str) -> str:
    """The default short title for an individual author (r 1.4.1): their
    surname. Copes with multi-word given names ('Ian M Ramsay' -> 'Ramsay'),
    'Sir'/'Dame'/peerage prefixes ('Sir Anthony Mason' -> 'Mason'), and
    corporate authors (returned unchanged, per r 4.1.4)."""
    name = name.strip()
    if not name or is_corporate_author(name):
        return name
    parts = name.split()
    return parts[-1] if parts else name


def invert_name(name: str) -> str:
    """r 1.13: 'an author's first name and surname should be inverted and
    separated by a comma'. Corporate authors are never inverted."""
    name = name.strip()
    if not name or is_corporate_author(name):
        return name
    parts = name.split()
    if len(parts) < 2:
        return name
    return f"{parts[-1]}, {' '.join(parts[:-1])}"


def format_names(names: list[str], *, invert_first: bool = False) -> str:
    """r 4.1.2: one -> 'A'; two/three -> 'A, B and C'; more than three -> the
    first-listed name followed by 'et al' (also applied in subsequent
    references, r 1.4.1). `invert_first` applies r 1.13's bibliography rule
    (only the first-listed author's name is inverted)."""
    if not names:
        return ""
    names = list(names)
    if invert_first:
        names[0] = invert_name(names[0])
    if len(names) > 3:
        return f"{names[0]} et al"
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])} and {names[-1]}"


def surname_list(names: list[str]) -> str:
    """The r 1.4.1 default short title for multiple authors: their surnames,
    joined the same way as r 4.1.2 (eg 'Edelman and Bant', 'Rishworth et al')."""
    return format_names([surname(n) for n in names])

def _names(source) -> list[str]:
    if getattr(source, "authors", None):
        return list(source.authors)
    if getattr(source, "author", None):
        return [source.author]
    return list(getattr(source, "editors", None) or [])


def _title_based(citation: Citation) -> bool:
    """r 1.4.1: subsequent references to secondary sources use the author's surname.
    The (short) title is used instead only when there is no author, or when the author
    is a body and a short title was introduced ('*Traditional Rights and Freedoms* (n 52)').
    A personal author's work keeps the surname even with a short title; the title is then
    only added to tell apart several works by that author (the document pass does that)."""
    names = _names(citation.source)
    return not names or (bool(citation.short_title) and all(is_corporate_author(n) for n in names))



def format_editors(editors: list[str], *, invert_first: bool = False) -> str:
    """r 4.1.3: editor names, followed by '(ed)'/'(eds)'."""
    names = format_names(editors, invert_first=invert_first)
    label = " (ed)" if len(editors) == 1 else " (eds)"
    return names + label


# --------------------------------------------------------------------------- #
# Small shared helpers
# --------------------------------------------------------------------------- #


def _ordinal(n: str) -> str:
    """r 6.3.2: '5' -> '5th'. Non-numeric strings pass through unchanged."""
    try:
        i = int(n)
    except ValueError:
        return n
    if 10 <= i % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(i % 10, "th")
    return f"{i}{suffix}"


def _edition_text(edition: str) -> str:
    """r 6.3.2-6.3.3: '5' -> '5th ed'; '3 rev' -> '3rd rev ed'; 'rev' (no
    number, ie an unnumbered revision of the first edition) -> 'rev ed'."""
    edition = edition.strip()
    if edition.lower() == "rev":
        return "rev ed"
    parts = edition.split(None, 1)
    if len(parts) == 2 and parts[1].strip().lower() == "rev":
        return f"{_ordinal(parts[0])} rev ed"
    return f"{_ordinal(edition)} ed"


_NUMERIC_ISSUE = re.compile(r"^[\d–\-]+$")


def _is_numeric_issue(issue: str) -> bool:
    return bool(_NUMERIC_ISSUE.match(issue.strip()))


def _year_volume_issue(src: JournalArticleSource) -> str:
    """r 5.3-5.4. Style defaults to round-bracket/volume-organised when a
    volume is present, square-bracket/year-organised otherwise; `year_style`
    overrides this. A numeric issue attaches directly to a volume number
    ('27(3)'); a non-numeric issue (season/month) - or any issue on a
    year-organised journal - is preceded by a space ('31 (Winter)',
    '[1983] (3)')."""
    year = src.year or missing("year")
    style = src.year_style or ("round" if src.volume else "square")
    if style == "round":
        vi = src.volume or missing("volume")
        if src.issue:
            vi += f"({src.issue})" if _is_numeric_issue(src.issue) else f" ({src.issue})"
        return f"({year}) {vi}"
    out = f"[{year}]"
    if src.issue:
        out += f" ({src.issue})"
    return out


# --------------------------------------------------------------------------- #
# Journal articles (AGLC4 ch 5)
# --------------------------------------------------------------------------- #


@register
class JournalArticleFormatter(Formatter):
    source_type = "journal_article"
    uses_n_reference = True
    italic_short_title = False
    defines_short_title = False
    bibliography_category = BIB_SECONDARY

    def full(self, citation: Citation) -> RichText:
        return self._render(citation, invert_author=False)

    def bibliography(self, citation: Citation) -> RichText:
        stripped = citation.model_copy(update={"pinpoints": [], "pinpoint_judges": None})
        return self._render(stripped, invert_author=True)

    def _render(self, citation: Citation, invert_author: bool) -> RichText:
        src = citation.source
        assert isinstance(src, JournalArticleSource)
        out = RichText()
        authors = format_names(src.authors, invert_first=invert_author) if src.authors else missing("authors")
        out.append(f"{authors}, ")
        out.append(f"{_LQ}{src.title}{_RQ}")
        if src.part:
            out.append(f" (Pt {src.part})")
        out.append(f" {_year_volume_issue(src)} ")
        out.append(src.journal or missing("journal"), italic=True)
        if src.forthcoming:
            out.append(" (forthcoming)")
        elif src.advance:
            out.append(" (advance)")
        else:
            out.append(" " + (src.starting_page or missing("starting_page")))
            pin = self.pinpoints(citation.pinpoints)
            if pin:
                out.append(", " + pin)
        return out

    def short_title(self, citation: Citation) -> str:
        if citation.short_title and _title_based(citation):
            return citation.short_title
        src = citation.source
        assert isinstance(src, JournalArticleSource)
        return surname_list(src.authors) if src.authors else src.title

    def subsequent(self, citation: Citation, short_title: str, first_footnote: int) -> RichText:
        src = citation.source
        assert isinstance(src, JournalArticleSource)
        out = RichText()
        title_based = _title_based(citation)
        out.append(f"{_LQ}{short_title}{_RQ}" if title_based else short_title)
        out.append(f" (n {first_footnote})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        if citation.pinpoint_judges:
            out.append(f" ({citation.pinpoint_judges})")
        return out


# --------------------------------------------------------------------------- #
# Books (AGLC4 ch 6)
# --------------------------------------------------------------------------- #


@register
class BookFormatter(Formatter):
    source_type = "book"
    uses_n_reference = True
    italic_short_title = True  # styled like the italic title (r 1.4.1)
    defines_short_title = False
    bibliography_category = BIB_SECONDARY

    def full(self, citation: Citation) -> RichText:
        return self._render(citation, invert_author=False)

    def bibliography(self, citation: Citation) -> RichText:
        stripped = citation.model_copy(update={"pinpoints": [], "pinpoint_judges": None})
        return self._render(stripped, invert_author=True)

    def _render(self, citation: Citation, invert_author: bool) -> RichText:
        src = citation.source
        assert isinstance(src, BookSource)
        out = RichText()
        # r 6.6.1: an edited book with no separate author leads with
        # "Editor (ed), *Title* ...". r 6.6.2: a book with BOTH an author and
        # an editor instead leads with the author and puts ", ed Editor"
        # after the title (handled below).
        if src.authors:
            out.append(format_names(src.authors, invert_first=invert_author) + ", ")
        elif src.editors:
            out.append(format_editors(src.editors, invert_first=invert_author) + ", ")
        else:
            out.append(missing("authors") + ", ")
        out.append(src.title, italic=True)
        if src.authors and src.editors:
            # r 6.6.2: 'ed' is invariant, never pluralised to 'eds'.
            out.append(f", ed {format_names(src.editors)}")
        if src.translators:
            # r 6.7: 'tr' is likewise invariant.
            out.append(f", tr {format_names(src.translators)}")
        # r 6.3.1: publisher is genuinely optional (self-published works,
        # or where publisher and author share a name) - omitted, not flagged.
        pub = [src.publisher] if src.publisher else []
        if src.edition:
            pub.append(_edition_text(src.edition))
        pub.append(src.year or missing("year"))
        out.append(f" ({', '.join(pub)})")
        pin = self.pinpoints(citation.pinpoints)
        if src.volume:
            out.append(f" vol {src.volume}")
            if pin:
                out.append(f", {pin}")
        elif pin:
            out.append(f" {pin}")
        return out

    def short_title(self, citation: Citation) -> str:
        if citation.short_title and _title_based(citation):
            return citation.short_title
        src = citation.source
        assert isinstance(src, BookSource)
        if src.authors:
            return surname_list(src.authors)
        if src.editors:
            return format_editors([surname(e) for e in src.editors])
        return src.title

    def subsequent(self, citation: Citation, short_title: str, first_footnote: int) -> RichText:
        src = citation.source
        assert isinstance(src, BookSource)
        out = RichText()
        title_based = _title_based(citation)
        out.append(short_title, italic=title_based)
        out.append(f" (n {first_footnote})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        if citation.pinpoint_judges:
            out.append(f" ({citation.pinpoint_judges})")
        return out


# --------------------------------------------------------------------------- #
# Book chapters (AGLC4 r 6.6.1)
# --------------------------------------------------------------------------- #


@register
class BookChapterFormatter(Formatter):
    source_type = "book_chapter"
    uses_n_reference = True
    italic_short_title = False
    defines_short_title = False
    bibliography_category = BIB_SECONDARY

    def full(self, citation: Citation) -> RichText:
        return self._render(citation, invert_author=False)

    def bibliography(self, citation: Citation) -> RichText:
        stripped = citation.model_copy(update={"pinpoints": [], "pinpoint_judges": None})
        return self._render(stripped, invert_author=True)

    def _render(self, citation: Citation, invert_author: bool) -> RichText:
        src = citation.source
        assert isinstance(src, BookChapterSource)
        out = RichText()
        authors = format_names(src.authors, invert_first=invert_author) if src.authors else missing("authors")
        out.append(f"{authors}, ")
        out.append(f"{_LQ}{src.chapter_title}{_RQ}")
        if src.translators:
            # r 6.7: translator(s) of the chapter, before 'in ...'.
            out.append(f", tr {format_names(src.translators)}")
        out.append(" in ")
        # The editor is the editor of the whole book, not "the author" of this
        # citation, so r 1.13's first-author inversion never touches it.
        if src.editors:
            out.append(format_editors(src.editors) + ", ")
        else:
            out.append(missing("editors") + ", ")
        out.append(src.book_title, italic=True)
        pub = [src.publisher] if src.publisher else []
        if src.edition:
            pub.append(_edition_text(src.edition))
        pub.append(src.year or missing("year"))
        out.append(f" ({', '.join(pub)}) ")
        out.append(src.starting_page or missing("starting_page"))
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f", {pin}")
        return out

    def short_title(self, citation: Citation) -> str:
        if citation.short_title and _title_based(citation):
            return citation.short_title
        src = citation.source
        assert isinstance(src, BookChapterSource)
        # r 6.6.1 note: subsequent references use the chapter's own author(s),
        # not the book's editor(s).
        return surname_list(src.authors) if src.authors else src.chapter_title

    def subsequent(self, citation: Citation, short_title: str, first_footnote: int) -> RichText:
        src = citation.source
        assert isinstance(src, BookChapterSource)
        out = RichText()
        title_based = _title_based(citation)
        out.append(f"{_LQ}{short_title}{_RQ}" if title_based else short_title)
        out.append(f" (n {first_footnote})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        if citation.pinpoint_judges:
            out.append(f" ({citation.pinpoint_judges})")
        return out


# --------------------------------------------------------------------------- #
# Reports (AGLC4 r 7.1)
# --------------------------------------------------------------------------- #


@register
class ReportFormatter(Formatter):
    source_type = "report"
    uses_n_reference = True
    italic_short_title = True  # styled like the italic title (r 1.4.1)
    defines_short_title = False
    bibliography_category = BIB_SECONDARY

    def full(self, citation: Citation) -> RichText:
        return self._render(citation, invert_author=False)

    def bibliography(self, citation: Citation) -> RichText:
        stripped = citation.model_copy(update={"pinpoints": [], "pinpoint_judges": None})
        return self._render(stripped, invert_author=True)

    def _render(self, citation: Citation, invert_author: bool) -> RichText:
        src = citation.source
        assert isinstance(src, ReportSource)
        out = RichText()
        # r 7.1.1: many reports (Royal Commissions, ad hoc reports) have no
        # prominently indicated author; the citation then starts with the
        # italic title.
        if src.author:
            author = invert_name(src.author) if invert_author else src.author
            out.append(f"{author}, ")
        out.append(src.title, italic=True)
        doc_type = src.document_type or missing("document_type")
        doc = f"{doc_type} No {src.document_number}" if src.document_number else doc_type
        out.append(f" ({doc}, {src.date or missing('date')})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f" {pin}")
        return out

    def short_title(self, citation: Citation) -> str:
        if citation.short_title and _title_based(citation):
            return citation.short_title
        src = citation.source
        assert isinstance(src, ReportSource)
        return surname(src.author) if src.author else src.title

    def subsequent(self, citation: Citation, short_title: str, first_footnote: int) -> RichText:
        src = citation.source
        assert isinstance(src, ReportSource)
        out = RichText()
        title_based = _title_based(citation)
        out.append(short_title, italic=title_based)
        out.append(f" (n {first_footnote})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        if citation.pinpoint_judges:
            out.append(f" ({citation.pinpoint_judges})")
        return out


# --------------------------------------------------------------------------- #
# Newspaper articles (AGLC4 r 7.11)
# --------------------------------------------------------------------------- #


@register
class NewspaperFormatter(Formatter):
    source_type = "newspaper"
    uses_n_reference = True
    italic_short_title = False
    defines_short_title = False
    bibliography_category = BIB_SECONDARY

    def full(self, citation: Citation) -> RichText:
        return self._render(citation, invert_author=False)

    def bibliography(self, citation: Citation) -> RichText:
        stripped = citation.model_copy(update={"pinpoints": [], "pinpoint_judges": None})
        return self._render(stripped, invert_author=True)

    def _render(self, citation: Citation, invert_author: bool) -> RichText:
        src = citation.source
        assert isinstance(src, NewspaperSource)
        out = RichText()
        if src.authors:
            out.append(format_names(src.authors, invert_first=invert_author) + ", ")
        out.append(f"{_LQ}{src.title}{_RQ}")
        date = src.date or missing("date")
        if src.periodical:
            # r 7.11.3: periodicals/newsletters indexed by date rather than
            # volume/issue: "'Title' (Date) *Periodical* Pinpoint".
            out.append(f" ({date}) ")
            out.append(src.newspaper, italic=True)
        else:
            out.append(", ")
            if src.section:
                # r 7.11.1: named, non-consecutively-paginated section.
                out.append(src.section, italic=True)
                out.append(", ")
            out.append(src.newspaper, italic=True)
            if src.url and not src.page:
                # r 7.11.2: electronic newspapers use "(online, date)".
                out.append(f" (online, {date})")
            else:
                out.append(f" ({src.place or missing('place')}, {date})")
        if src.page:
            out.append(f" {src.page}")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append((", " if src.page else " ") + pin)
        if src.url:
            out.append(f" <{src.url}>")
        if src.archived_url:
            # r 4.5
            out.append(f", archived at <{src.archived_url}>")
        return out

    def short_title(self, citation: Citation) -> str:
        if citation.short_title and _title_based(citation):
            return citation.short_title
        src = citation.source
        assert isinstance(src, NewspaperSource)
        return surname_list(src.authors) if src.authors else src.title

    def subsequent(self, citation: Citation, short_title: str, first_footnote: int) -> RichText:
        src = citation.source
        assert isinstance(src, NewspaperSource)
        out = RichText()
        title_based = _title_based(citation)
        out.append(f"{_LQ}{short_title}{_RQ}" if title_based else short_title)
        out.append(f" (n {first_footnote})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        if citation.pinpoint_judges:
            out.append(f" ({citation.pinpoint_judges})")
        return out


# --------------------------------------------------------------------------- #
# Internet materials (AGLC4 r 7.15)
# --------------------------------------------------------------------------- #


@register
class WebsiteFormatter(Formatter):
    source_type = "website"
    uses_n_reference = True
    italic_short_title = False
    defines_short_title = False
    bibliography_category = BIB_SECONDARY

    def full(self, citation: Citation) -> RichText:
        return self._render(citation, invert_author=False)

    def bibliography(self, citation: Citation) -> RichText:
        stripped = citation.model_copy(update={"pinpoints": [], "pinpoint_judges": None})
        return self._render(stripped, invert_author=True)

    def _render(self, citation: Citation, invert_author: bool) -> RichText:
        src = citation.source
        assert isinstance(src, WebsiteSource)
        out = RichText()
        # r 7.15: author omitted if identical to the web page title.
        authors = [a for a in src.authors if a != src.website_name]
        if authors:
            out.append(format_names(authors, invert_first=invert_author) + ", ")
        out.append(f"{_LQ}{src.title}{_RQ}, ")
        out.append(src.website_name or missing("website_name"), italic=True)
        # r 7.15: 'Web Page' is the guide's default when the document type is
        # unclear (the model defaults document_type to it too).
        doc_type = src.document_type or "Web Page"
        out.append(f" ({doc_type}, {src.date})" if src.date else f" ({doc_type})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        if src.url:
            out.append(f" <{src.url}>")
        if src.archived_url:
            # r 4.5
            out.append(f", archived at <{src.archived_url}>")
        return out

    def short_title(self, citation: Citation) -> str:
        if citation.short_title and _title_based(citation):
            return citation.short_title
        src = citation.source
        assert isinstance(src, WebsiteSource)
        if src.authors:
            return surname_list(src.authors)
        return src.website_name or src.title

    def subsequent(self, citation: Citation, short_title: str, first_footnote: int) -> RichText:
        src = citation.source
        assert isinstance(src, WebsiteSource)
        out = RichText()
        if citation.short_title and _title_based(citation):
            # An author-defined short title abbreviates the (quoted) document
            # title, styled the same way (r 1.4.4).
            out.append(f"{_LQ}{short_title}{_RQ}")
        elif not src.authors:
            # No author: fall back to the (italicised) web page title, r 1.4.1.
            out.append(short_title, italic=True)
        else:
            out.append(short_title)
        out.append(f" (n {first_footnote})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        if citation.pinpoint_judges:
            out.append(f" ({citation.pinpoint_judges})")
        return out
