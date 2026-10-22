"""Other secondary sources: speeches (AGLC4 r 7.3), press and media releases (r 7.4),
dictionaries (r 7.6), legal encyclopedias (r 7.7) and social media posts (r 7.16).

Speeches and media releases have an author and a quoted title, so they follow the
research paper pattern in `secondary.py`: repeat references use the author's surname
(r 1.4.1) and the bibliography inverts it (r 1.13). A dictionary entry or encyclopedia
chapter has no author, and its work's title is shared by every other entry, so like a
treaty it is only shortened to a short title the author introduced, and is otherwise
repeated in full. A social media post is referred to by its username.
"""

from __future__ import annotations

from ..models import (
    Citation,
    DictionarySource,
    LegalEncyclopediaSource,
    MediaReleaseSource,
    Pinpoint,
    PinpointKind,
    RichText,
    SocialMediaSource,
    SpeechSource,
)
from .base import BIB_OTHER, BIB_SECONDARY, Formatter, missing, register
from .pinpoints import span
from .secondary import _LQ, _RQ, _edition_text, _quoted, _title_based, format_names, surname_list


class _AuthorTitleFormatter(Formatter):
    """Author, 'Title' (...): repeat references use the author's surname, or the quoted
    title when there is no author (r 1.4.1)."""

    uses_n_reference = True
    italic_short_title = False
    defines_short_title = False

    def full(self, citation: Citation) -> RichText:
        return self._render(citation, invert_author=False)

    def bibliography(self, citation: Citation) -> RichText:
        stripped = citation.model_copy(update={"pinpoints": [], "pinpoint_judges": None})
        return self._render(stripped, invert_author=True)

    def _render(self, citation: Citation, invert_author: bool) -> RichText:
        raise NotImplementedError

    def short_title(self, citation: Citation) -> str:
        if citation.short_title and _title_based(citation):
            return citation.short_title
        src = citation.source
        return surname_list(src.authors, is_body=src.authors_are_bodies) if src.authors else src.title

    def subsequent(self, citation: Citation, short_title: str, first_footnote: int) -> RichText:
        out = RichText()
        out.append(f"{_LQ}{short_title}{_RQ}" if _title_based(citation) else short_title)
        out.append(f" (n {first_footnote})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        return out


@register
class SpeechFormatter(_AuthorTitleFormatter):
    """r 7.3: Author, 'Title' (Speech, Institution/Forum, Full Date) Pinpoint. A named
    lecture replaces 'Speech' (without a leading 'The' or its ordinal number in a series),
    and the forum is the city or town only when no forum is given."""

    source_type = "speech"
    bibliography_category = BIB_OTHER

    def _render(self, citation: Citation, invert_author: bool) -> RichText:
        src = citation.source
        assert isinstance(src, SpeechSource)
        out = RichText()
        authors = format_names(src.authors, invert_first=invert_author, is_body=src.authors_are_bodies) if src.authors else missing("authors")
        out.append(f"{authors}, ")
        out.extend(_quoted(src.title, src.title_rich))
        parts = [src.lecture or "Speech", src.forum or missing("forum"), src.date or missing("date")]
        out.append(f" ({', '.join(parts)})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f" {pin}")
        if src.url:
            out.append(f" <{src.url}>")  # r 4.4
        return out


@register
class MediaReleaseFormatter(_AuthorTitleFormatter):
    """r 7.4: Author, 'Title' (Release Type Document Number, Body, Full Date) Pinpoint. The
    body is left out when it is the author, and the release type is 'Media Release' when
    the source doesn't give one."""

    source_type = "media_release"
    bibliography_category = BIB_OTHER

    def _render(self, citation: Citation, invert_author: bool) -> RichText:
        src = citation.source
        assert isinstance(src, MediaReleaseSource)
        out = RichText()
        if src.authors:
            out.append(format_names(src.authors, invert_first=invert_author, is_body=src.authors_are_bodies) + ", ")
        out.extend(_quoted(src.title, src.title_rich))
        release = src.release_type or "Media Release"
        parts = [f"{release} {src.document_number}" if src.document_number else release]
        if src.body and src.body not in src.authors:
            parts.append(src.body)
        parts.append(src.date or missing("date"))
        out.append(f" ({', '.join(parts)})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f" {pin}")
        if src.url:
            out.append(f" <{src.url}>")  # r 4.4
        return out


@register
class DictionaryFormatter(Formatter):
    """r 7.6: *Dictionary Title* (Edition ed, Year) 'Entry Title' (def Number), or for an
    online dictionary *Dictionary Title* (online at Date of Retrieval) 'Entry Title' (def
    Number). Which of several entries for the word ('n1', 'v2') goes before the definition."""

    source_type = "dictionary"
    italic_short_title = True
    defines_short_title = True
    bibliography_category = BIB_SECONDARY

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, DictionarySource)
        out = RichText.italic(src.title or missing("title"))
        if src.online or src.retrieved:
            out.append(f" (online at {src.retrieved or missing('retrieved')})")
        else:
            pub = [_edition_text(src.edition)] if src.edition else []
            pub.append(src.year or missing("year"))
            out.append(f" ({', '.join(pub)})")
        out.append(f" {_LQ}{src.entry or missing('entry')}{_RQ}")
        which = [src.entry_designation] if src.entry_designation else []
        if src.definition:
            which.append(f"def {src.definition}")
        if which:
            out.append(f" ({', '.join(which)})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f" {pin}")
        return out


@register
class LegalEncyclopediaFormatter(Formatter):
    """r 7.7: Publisher, *Title of Encyclopedia*, vol Volume (at Full Date) Title Number Name
    of Title, 'Chapter Number Name of Chapter' [Paragraph]; online, '(online at Date of
    Retrieval)' replaces the volume and date. Paragraph numbers are often hyphenated
    ('[235-270]' in *Halsbury's*), so a hyphen stays part of the number; only an en dash
    or 'to' makes a span."""

    source_type = "legal_encyclopedia"
    italic_short_title = True
    defines_short_title = True
    bibliography_category = BIB_SECONDARY

    @staticmethod
    def pinpoint(p: Pinpoint) -> str:
        if p.kind is not PinpointKind.paragraph:
            return Formatter.pinpoint(p)
        v = p.value.strip().strip("[]").replace(" to ", "–")
        return f"[{v}]".replace("–", "]–[") if "–" in v and "]" not in v else f"[{v}]"

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, LegalEncyclopediaSource)
        out = RichText.plain(f"{src.publisher or missing('publisher')}, ")
        out.append(src.title or missing("title"), italic=True)
        if src.online or src.retrieved:
            out.append(f" (online at {src.retrieved or missing('retrieved')})")
        else:
            if src.volume:
                out.append(f", vol {src.volume}")
            if src.date:
                out.append(f" (at {src.date})")
        subject = " ".join(p for p in (src.title_number, src.title_name) if p)
        if subject:
            out.append(f" {subject}")
        if src.chapter:
            out.append(f"{',' if subject else ''} {_LQ}{src.chapter}{_RQ}")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f" {pin}")
        return out


@register
class SocialMediaFormatter(Formatter):
    """r 7.16: Username, 'Title' (Social Media Platform, Full Date, Time) <URL>. The poster's
    name may follow the username in brackets; a post without a title has none (and no
    comma); the time zone follows the time, or the date when there is no time. Pinpoints to
    a video are times ('00:00:00–00:01:00'). Repeat references use the username."""

    source_type = "social_media"
    italic_short_title = False
    defines_short_title = False
    bibliography_category = BIB_OTHER

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, SocialMediaSource)
        out = RichText.plain(src.username or missing("username"))
        if src.author_name:
            out.append(f" ({src.author_name})")
        if src.title:
            out.append(", ")
            out.extend(_quoted(src.title, src.title_rich))
        when = src.date or missing("date")
        if src.time:
            when += f", {src.time}"
        if src.time_zone:
            when += f" {src.time_zone}"
        out.append(f" ({src.platform or missing('platform')}, {when})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(f" {pin}")
        if src.url:
            out.append(f" <{src.url}>")
        if src.archived_url:
            out.append(f", archived at <{src.archived_url}>")  # r 4.5
        return out

    @staticmethod
    def pinpoint(p: Pinpoint) -> str:
        # a point or span of time in a video (r 1.11.3-1.11.4), never shortened as pages are
        return span(p.value.strip()) if ":" in p.value else Formatter.pinpoint(p)

    def short_title(self, citation: Citation) -> str:
        src = citation.source
        assert isinstance(src, SocialMediaSource)
        return citation.short_title or src.username
