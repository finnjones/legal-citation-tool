"""Normalisation: deterministic clean-up of extracted citations using lookup
tables in aglc/data/. CONTRACT (implemented by workstream agent)."""

from __future__ import annotations

from .models import Citation, Source


def normalise_citation(citation: Citation) -> tuple[Citation, list[str]]:
    """Return a cleaned copy of `citation` plus human-readable warnings.

    Must: canonicalise report abbreviations and decide CaseSource.year_style,
    clean case names per AGLC4 r 2.1, canonicalise jurisdictions, tidy author
    names, and set `citation.source_key` via `source_key()`.
    """
    raise NotImplementedError


def source_key(source: Source) -> str:
    """Stable identity for a source so repeated citations of the same work are
    recognised (drives ibid and '(n x)'). Must ignore pinpoints and be robust to
    trivial differences (case, whitespace, punctuation)."""
    raise NotImplementedError
