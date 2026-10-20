"""Fallback for unclassified sources: emitted verbatim, keeping the footnote's own italics."""

from ..models import Citation, OtherSource, RichText
from .base import BIB_OTHER, Formatter, register


def _verbatim(src: OtherSource) -> RichText:
    if src.rich is not None and src.rich.text == src.text:
        return src.rich.model_copy(deep=True)
    return RichText.plain(src.text)


@register
class OtherFormatter(Formatter):
    source_type = "other"
    bibliography_category = BIB_OTHER

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, OtherSource)
        out = _verbatim(src)
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        return out

    def short_title_italic(self, citation: Citation) -> bool:
        """Italic when the words of the short title are italic where they appear in the
        source ('*Parliamentary Debates*' in a Hansard reference)."""
        src = citation.source
        short = (citation.short_title or "").strip()
        if not isinstance(src, OtherSource) or not short:
            return False
        rich = _verbatim(src)
        start = rich.text.find(short)
        if start == -1:
            return False
        return all(run.italic for run in rich.slice(start, start + len(short)).runs if run.text.strip())
