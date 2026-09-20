"""End-to-end orchestration. The only module that wires the stages together."""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .document import render_document
from .docx_io import read_footnotes, write_document
from .extract import Extractor
from .llm.base import LLMProvider, get_provider
from .models import CitationSegment, Footnote, ProcessResult, Warning_
from .formatters import formatter_for
from .normalise import normalise_citation
from .validate import check_footnote_rendering

log = logging.getLogger("aglc")


def process_footnotes(
    footnotes: list[Footnote],
    provider: LLMProvider | str | None = None,
    *,
    bibliography: bool = True,
) -> ProcessResult:
    if not isinstance(provider, LLMProvider):
        provider = get_provider(provider)
    extractor = Extractor(provider)
    extracted = extractor.extract(footnotes)

    warnings: list[Warning_] = [Warning_(message=m) for m in extractor.warnings]
    for fn in extracted:
        for seg in fn.segments:
            if isinstance(seg, CitationSegment):
                seg.citation, msgs = normalise_citation(seg.citation)
                warnings += [Warning_(footnote=fn.number, message=m) for m in msgs]

    _share_short_titles(extracted)

    # Deterministic check that the formatter printed every field (aglc/validate.py)
    for fn in extracted:
        warnings += [Warning_(footnote=fn.number, message=m) for m in check_footnote_rendering(fn, formatter_for)]

    result = render_document(extracted, bibliography=bibliography)
    result.warnings = warnings + result.warnings
    return result


def _share_short_titles(footnotes: list[Footnote]) -> None:
    """A short title is often introduced in the body text ("the Adoption Act 2000 (NSW)
    ('Adoption Act')") and then used in later footnotes ("Adoption Act (n 2) s 24"). Give
    every citation of a source the short title any of them uses, so the document pass
    defines it at the first citation and abbreviates the rest."""
    chosen: dict[str, str] = {}
    for fn in footnotes:
        for seg in fn.segments:
            if isinstance(seg, CitationSegment):
                key, short = seg.citation.source_key, seg.citation.short_title
                if key and short and key not in chosen:
                    chosen[key] = short
    for fn in footnotes:
        for seg in fn.segments:
            if isinstance(seg, CitationSegment) and not seg.citation.short_title:
                short = chosen.get(seg.citation.source_key or "")
                if short:
                    seg.citation.short_title = short


def process_docx(
    src: str | Path,
    dst: str | Path,
    provider: LLMProvider | str | None = None,
    *,
    bibliography: bool = True,
    track_changes: bool = True,
) -> ProcessResult:
    t0 = time.monotonic()
    footnotes = read_footnotes(src)
    log.info("read %d footnotes from %s", len(footnotes), Path(src).name)
    result = process_footnotes(footnotes, provider, bibliography=bibliography)
    changed = sum(f.changed for f in result.footnotes)
    log.info("formatted: %d footnotes changed, %d warnings", changed, len(result.warnings))
    write_document(
        src,
        dst,
        result.footnotes,
        bibliography=result.bibliography if bibliography else None,
        track_changes=track_changes,
    )
    log.info("wrote %s (%.1fs total)", Path(dst).name, time.monotonic() - t0)
    return result
