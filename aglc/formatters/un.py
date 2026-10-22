"""Official documents of the United Nations (AGLC4 r 9.2, 9.5).

 Author, *Title*, Resolution Number, Official Records, Committee, Session, Meeting,
 Agenda Item, Supplement, UN Doc Number (Full Date, adopted Date) Pinpoint.

Every element is included only when the document has it. Elements before the document
number are separated by commas; after it, only the date (in brackets) and the pinpoint
follow. Pinpoints to a resolution or decision use the r 3.1.4 abbreviations ('para 3',
'paras 138–9', 'pt K'), while other documents (reports, general comments, committee
decisions) cite paragraphs in square brackets, as for any secondary source (r 9.2.13).

A repeat reference uses the short title the author introduced, with the document number
(r 9.5): '*Resolution 1325*, UN Doc S/RES/1325 (n 45) para 7'. Without one the citation is
repeated in full: untitled resolutions and meeting records have nothing to shorten.
"""

from __future__ import annotations

from ..models import Citation, Pinpoint, PinpointKind, RichText, UNDocumentSource
from .base import BIB_OTHER, Formatter, missing, register
from .pinpoints import shorten_span, span
from .secondary import _ordinal


def _agenda(items: list[str]) -> str:
    """r 9.2.8: 'Agenda Item 49(b)', 'Agenda Items 46 and 120', 'Agenda Items 42, 88 and 166'."""
    if len(items) == 1:
        return f"Agenda Item {items[0]}"
    return f"Agenda Items {', '.join(items[:-1])} and {items[-1]}"


def _doc_number(number: str) -> str:
    """r 9.2.10: 'UN Doc A/RES/54/275'; 'UN Docs A/63/804 and Corr.1' for several."""
    return f"UN Docs {number}" if " and " in number else f"UN Doc {number}"


@register
class UNDocumentFormatter(Formatter):
    source_type = "un_document"
    uses_n_reference = True
    italic_short_title = True  # r 9.5: '*Resolution 1325*'
    defines_short_title = True
    bibliography_category = BIB_OTHER

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, UNDocumentSource)
        out = RichText()
        if src.author:
            out.append(f"{src.author}, ")
        if src.title:
            out.append(src.title, italic=True)
            out.append(", ")
        parts = [src.resolution, src.official_records]
        if src.committee:
            parts.append(f"{_ordinal(src.committee)} Comm")
        if src.session:
            parts.append(f"{_ordinal(src.session)} sess")
        if src.session_part:
            parts.append(f"{_ordinal(src.session_part)} pt")
        if src.meeting:
            parts.append(f"{_ordinal(src.meeting)} {'plen mtg' if src.plenary else 'mtg'}")
        if src.agenda_items:
            parts.append(_agenda(src.agenda_items))
        if src.supplement:
            parts.append(f"Supp No {src.supplement}")
        parts.append(_doc_number(src.document_number) if src.document_number else missing("document_number"))
        out.append(", ".join(p for p in parts if p))
        if src.date:
            out.append(f" ({src.date}, adopted {src.adopted})" if src.adopted else f" ({src.date})")
        pin = self._pins(citation)
        if pin:
            out.append(f" {pin}")
        return out

    def short_title(self, citation: Citation) -> str:
        # As for treaties, only a short title the author introduced (r 9.5, 1.4.4).
        return citation.short_title or ""

    def subsequent(self, citation: Citation, short_title: str, first_footnote: int) -> RichText:
        """r 9.5: *Short Title*, UN Doc Number (n Footnote) Pinpoint."""
        src = citation.source
        assert isinstance(src, UNDocumentSource)
        out = RichText.italic(short_title)
        if src.document_number:
            out.append(f", {_doc_number(src.document_number)}")
        out.append(f" (n {first_footnote})")
        pin = self._pins(citation)
        if pin:
            out.append(f" {pin}")
        return out

    def ibid_pinpoint(self, citation: Citation) -> str:
        return self._pins(citation)

    def _pins(self, citation: Citation) -> str:
        """Pinpoints, with a resolution's or decision's paragraphs as 'para 3' or
        'paras 3, 5' rather than '[3]' (r 9.2.13). Pinpoints of different kinds are
        separated by spaces only ('pt B para 2', 'annex para 3')."""
        src = citation.source
        assert isinstance(src, UNDocumentSource)
        number = (src.document_number or "").upper()
        if not (src.resolution or "/RES/" in number or "/DEC/" in number):
            return self.pinpoints(citation.pinpoints)
        out: list[str] = []
        paras: list[Pinpoint] = []

        def flush() -> None:
            if paras:
                values = [shorten_span(span(p.value.strip().strip("[]"))) for p in paras]
                plural = len(paras) > 1 or any(p.plural or "–" in v or "," in v or " and " in v for p, v in zip(paras, values))
                out.append(f"{'paras' if plural else 'para'} {', '.join(values)}")
                paras.clear()

        groups: list[Pinpoint] = []
        for p in citation.pinpoints:
            if p.kind is PinpointKind.paragraph:
                if groups:
                    out.append(self.pinpoints(groups))
                    groups = []
                paras.append(p)
            else:
                flush()
                groups.append(p)
        flush()
        if groups:
            out.append(self.pinpoints(groups))
        return " ".join(out)
