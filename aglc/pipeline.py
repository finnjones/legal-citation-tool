"""End-to-end orchestration. The only module that wires the stages together."""

from __future__ import annotations

from pathlib import Path

from .document import render_document
from .docx_io import read_footnotes, write_document
from .extract import Extractor
from .llm.base import LLMProvider, get_provider
from .models import CitationSegment, Footnote, ProcessResult, Warning_
from .normalise import normalise_citation


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

    result = render_document(extracted, bibliography=bibliography)
    result.warnings = warnings + result.warnings
    return result


def process_docx(
    src: str | Path,
    dst: str | Path,
    provider: LLMProvider | str | None = None,
    *,
    bibliography: bool = True,
    track_changes: bool = True,
) -> ProcessResult:
    result = process_footnotes(read_footnotes(src), provider, bibliography=bibliography)
    write_document(
        src,
        dst,
        result.footnotes,
        bibliography=result.bibliography if bibliography else None,
        track_changes=track_changes,
    )
    return result
