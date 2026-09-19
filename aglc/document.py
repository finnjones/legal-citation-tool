"""Document pass: turns per-footnote citations into AGLC-correct text using the
citation history (ibid, '(n x)', short titles, signals, punctuation) and builds
the bibliography. CONTRACT (implemented by workstream agent)."""

from __future__ import annotations

from .models import Footnote, ProcessResult


def render_document(footnotes: list[Footnote], *, bibliography: bool = True) -> ProcessResult:
    """`footnotes` must already be extracted and normalised (every Citation has
    source_key set). Returns formatted text for every footnote, bibliography
    sections (if requested) and warnings."""
    raise NotImplementedError
