"""End-to-end orchestration. The only module that wires the stages together."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable
from pathlib import Path

from .document import render_document
from .docx_io import read_footnotes, write_document
from .extract import Extractor
from .llm.base import LLMProvider, get_provider
from .models import CitationSegment, Extraction, Footnote, ProcessResult, Warning_
from .formatters import formatter_for
from .normalise import normalise_citation
from .validate import check_footnote_rendering

log = logging.getLogger("aglc")


def process_footnotes(
    footnotes: list[Footnote],
    provider: LLMProvider | str | None = None,
    *,
    bibliography: bool = True,
    previous: Extraction | None = None,
    only: set[int] | None = None,
) -> ProcessResult:
    """Extract, normalise and render. With `previous` and `only`, extract just the footnotes
    numbered in `only` again and reuse `previous` for the rest."""
    if not isinstance(provider, LLMProvider):
        provider = get_provider(provider)
    extraction = extract_footnotes(footnotes, provider, previous=previous, only=only)
    result = _render(extraction, bibliography=bibliography)
    result.extraction = extraction
    return result


def extract_footnotes(
    footnotes: list[Footnote],
    provider: LLMProvider,
    *,
    previous: Extraction | None = None,
    only: set[int] | None = None,
) -> Extraction:
    extractor = Extractor(provider)
    if previous is None or only is None:
        return Extraction(footnotes=extractor.extract(footnotes), warnings=extractor.warnings)
    kept = {fn.number: fn for fn in previous.footnotes if fn.number not in only}
    redo = extractor.extract([fn for fn in footnotes if fn.number in only], context=list(kept.values()))
    merged = {**kept, **{fn.number: fn for fn in redo}}
    warnings = [m for m in previous.warnings if not (warning_footnotes(m) & only)] + extractor.warnings
    return Extraction(footnotes=[merged[fn.number] for fn in footnotes if fn.number in merged], warnings=warnings)


def _render(extraction: Extraction, *, bibliography: bool) -> ProcessResult:
    extracted = [fn.model_copy(deep=True) for fn in extraction.footnotes]  # normalising edits in place
    warnings: list[Warning_] = [Warning_(message=m) for m in extraction.warnings]
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
    fix_body: bool = True,
    previous: Extraction | None = None,
    only: set[int] | None = None,
) -> ProcessResult:
    """Process `src` into `dst`. With `previous` and `only`, re-extract just those footnotes
    (see process_footnotes); everything after extraction is redone for the whole document."""
    t0 = time.monotonic()
    footnotes = read_footnotes(src)
    log.info("read %d footnotes from %s", len(footnotes), Path(src).name)
    result = process_footnotes(footnotes, provider, bibliography=bibliography, previous=previous, only=only)
    changed = sum(f.changed for f in result.footnotes)
    log.info("formatted: %d footnotes changed, %d warnings", changed, len(result.warnings))
    result.body_fixes = write_document(
        src,
        dst,
        result.footnotes,
        bibliography=result.bibliography if bibliography else None,
        track_changes=track_changes,
        fix_body=fix_body,
    )
    if result.body_fixes:
        log.info("body text: %d fixes", len(result.body_fixes))
    log.info("wrote %s (%.1fs total)", Path(dst).name, time.monotonic() - t0)
    return result


# --------------------------------------------------------------------------- #
# Footnotes the LLM failed to read
# --------------------------------------------------------------------------- #
# Read from each footnote's `extraction_failed` reason. The Extractor's warnings are still
# checked too, for results saved before that field existed; callers only use these functions.

_FAILED = re.compile(r"^extraction failed for footnotes \[([\d,\s]+)\]", re.I)
_MISSING = re.compile(r"^footnote (\d+): (missing from LLM response|LLM returned no segments)", re.I)


def warning_footnotes(message: str) -> set[int]:
    """The footnote numbers an extractor warning is about ('footnote 3: ...', 'footnotes [1, 2]')."""
    if m := re.match(r"^footnote (\d+):", message, re.I):
        return {int(m[1])}
    if m := re.search(r"footnotes \[([\d,\s]+)\]", message, re.I):
        return {int(n) for n in m[1].split(",") if n.strip()}
    return set()


def _messages(result) -> Iterable[str]:
    for w in result.warnings if hasattr(result, "warnings") else result:
        if isinstance(w, str):
            yield w
        elif isinstance(w, dict):
            yield w.get("message") or ""
        else:
            yield w.message


def failed_footnotes(result) -> set[int]:
    """Footnotes the model failed to read (left as written because extraction failed, not
    because the tool chose to). `result` is a ProcessResult, the API's result dict, or a
    list of warnings."""
    failed: set[int] = set()
    if isinstance(result, dict):
        failed |= {fn["number"] for fn in result.get("footnotes", []) if fn.get("extraction_failed")}
        result = result.get("warnings", [])
    elif hasattr(result, "footnotes"):
        failed |= {fn.number for fn in result.footnotes if getattr(fn, "extraction_failed", None)}
    for message in _messages(result):
        if m := _FAILED.match(message):
            failed |= {int(n) for n in m[1].split(",") if n.strip()}
        elif m := _MISSING.match(message):
            failed.add(int(m[1]))
    return failed


def whole_batch_failed(result, total: int, batch_size: int = 15) -> bool:
    """Whether one request to the model failed for a whole batch (or the whole document)."""
    return any(
        len(warning_footnotes(message)) >= min(batch_size, total)
        for message in _messages(result)
        if _FAILED.match(message)
    )
