"""Fallback for unclassified sources: emitted verbatim."""

from ..models import Citation, OtherSource, RichText
from .base import BIB_OTHER, Formatter, register


@register
class OtherFormatter(Formatter):
    source_type = "other"
    bibliography_category = BIB_OTHER

    def full(self, citation: Citation) -> RichText:
        src = citation.source
        assert isinstance(src, OtherSource)
        out = RichText.plain(src.text)
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(" " + pin)
        return out
