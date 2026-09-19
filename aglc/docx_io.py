"""Reading and writing Word footnotes. CONTRACT (implemented by workstream agent)."""

from __future__ import annotations

from pathlib import Path

from .models import BibliographySection, Footnote, FootnoteResult


def read_footnotes(path: str | Path) -> list[Footnote]:
    """Read all real footnotes (skip separator/continuation footnotes) in document
    order, numbered 1..n, preserving italics as RichText runs."""
    raise NotImplementedError


def write_document(
    src: str | Path,
    dst: str | Path,
    results: list[FootnoteResult],
    *,
    bibliography: list[BibliographySection] | None = None,
    track_changes: bool = True,
    author: str = "AGLC Citation Tool",
) -> None:
    """Copy `src` to `dst`, replacing the text of each changed footnote with
    `result.formatted` (as tracked insertions/deletions when `track_changes`),
    and append a Bibliography at the end of the body if given."""
    raise NotImplementedError
