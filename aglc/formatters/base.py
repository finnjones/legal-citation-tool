"""Formatter contract. One Formatter subclass per source type, registered by `type`.

Formatters are pure and deterministic: same input -> same RichText. They never
guess missing data; they call `missing(field)` which renders `[MISSING: field]`
and records a warning.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..models import Citation, Pinpoint, RichText

# AGLC4 r 1.13 bibliography categories
BIB_SECONDARY = "A Articles/Books/Reports"
BIB_CASES = "B Cases"
BIB_LEGISLATION = "C Legislation"
BIB_TREATIES = "D Treaties"
BIB_OTHER = "E Other"
BIB_ORDER = [BIB_SECONDARY, BIB_CASES, BIB_LEGISLATION, BIB_TREATIES, BIB_OTHER]


def missing(field: str) -> str:
    return f"[MISSING: {field}]"


class Formatter(ABC):
    #: the Source.type this formatter handles
    source_type: ClassVar[str]
    #: AGLC4 r 1.4.1: cases/secondary sources use "(n x)"; legislation and treaties do not
    uses_n_reference: ClassVar[bool] = True
    #: Whether the short title is italicised in subsequent references
    italic_short_title: ClassVar[bool] = False
    bibliography_category: ClassVar[str] = BIB_OTHER

    @abstractmethod
    def full(self, citation: Citation) -> RichText:
        """First citation, including pinpoint(s) and pinpoint judges, but NOT the
        signal, the short title definition, or closing punctuation (the document
        pass adds those)."""

    def short_title(self, citation: Citation) -> str:
        """Default short title used when the author hasn't supplied one
        (eg the first party name for cases, the author surname for articles)."""
        return citation.short_title or ""

    def subsequent(self, citation: Citation, short_title: str, first_footnote: int) -> RichText:
        """Subsequent reference (AGLC4 r 1.4). Default: 'Short Title (n 3) 42'."""
        out = RichText()
        out.append(short_title, italic=self.italic_short_title)
        if self.uses_n_reference:
            out.append(f" (n {first_footnote})")
        pin = self.pinpoints(citation.pinpoints)
        if pin:
            out.append(("," if not self.uses_n_reference else "") + " " + pin)
        if citation.pinpoint_judges:
            out.append(f" ({citation.pinpoint_judges})")
        return out

    def ibid_pinpoint(self, citation: Citation) -> str:
        """Text after 'Ibid' when only the pinpoint changes (r 1.4.3): 'Ibid 42'."""
        pin = self.pinpoints(citation.pinpoints)
        if pin and citation.pinpoint_judges:
            pin += f" ({citation.pinpoint_judges})"
        return pin

    def bibliography(self, citation: Citation) -> RichText:
        """Bibliography entry (r 1.13): full citation without pinpoints; subclasses
        override for author-name inversion etc."""
        stripped = citation.model_copy(update={"pinpoints": [], "pinpoint_judges": None})
        return self.full(stripped)

    def sort_key(self, citation: Citation) -> str:
        return self.bibliography(citation).text.lstrip("'‘").lower()

    # ---- helpers shared by subclasses ------------------------------------- #
    @staticmethod
    def pinpoint(p: Pinpoint) -> str:
        from .pinpoints import render_pinpoint

        return render_pinpoint(p)

    @classmethod
    def pinpoints(cls, ps: list[Pinpoint]) -> str:
        return ", ".join(cls.pinpoint(p) for p in ps)


_REGISTRY: dict[str, Formatter] = {}


def register(cls: type[Formatter]) -> type[Formatter]:
    _REGISTRY[cls.source_type] = cls()
    return cls


def formatter_for(citation: Citation) -> Formatter:
    from . import _load_all  # noqa: F401  (populates registry)

    try:
        return _REGISTRY[citation.source.type]
    except KeyError:
        return _REGISTRY["other"]
