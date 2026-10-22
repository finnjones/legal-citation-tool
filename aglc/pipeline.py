"""End-to-end orchestration. The only module that wires the stages together."""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from .document import render_document
from .docx_io import read_footnotes, write_document
from .extract import Extractor
from .llm.base import LLMProvider, get_provider
from .models import CitationSegment, Extraction, Footnote, ProcessResult, Warning_
from .formatters import formatter_for
from .normalise import normalise_citation, unify_source_keys
from .progress import Progress, footnote_texts, found_in, safe
from .validate import check_footnote_rendering

log = logging.getLogger("aglc")


def process_footnotes(
    footnotes: list[Footnote],
    provider: LLMProvider | str | None = None,
    *,
    bibliography: bool = True,
    previous: Extraction | None = None,
    only: set[int] | None = None,
    progress: Progress | None = None,
) -> ProcessResult:
    """Extract, normalise and render. With `previous` and `only`, extract just the footnotes
    numbered in `only` again and reuse `previous` for the rest. `progress` is told what is
    happening as it happens (see aglc/progress.py)."""
    if not isinstance(provider, LLMProvider):
        provider = get_provider(provider)
    extraction = extract_footnotes(footnotes, provider, previous=previous, only=only, progress=progress)
    result = _render(extraction, bibliography=bibliography, progress=progress)
    result.extraction = extraction
    return result


def extract_footnotes(
    footnotes: list[Footnote],
    provider: LLMProvider,
    *,
    previous: Extraction | None = None,
    only: set[int] | None = None,
    progress: Progress | None = None,
) -> Extraction:
    extractor = Extractor(provider, progress=progress)
    if previous is None or only is None:
        extracted = extractor.extract(footnotes)
        return Extraction(footnotes=extracted, warnings=extractor.warnings, provider_down=extractor.provider_down)
    kept = {fn.number: fn for fn in previous.footnotes if fn.number not in only}
    if kept:
        # read the first time round
        safe(progress)("done", {"numbers": sorted(kept), "found": {n: found_in(fn) for n, fn in kept.items()}})
    redo = extractor.extract([fn for fn in footnotes if fn.number in only], context=list(kept.values()))
    merged = {**kept, **{fn.number: fn for fn in redo}}
    warnings = [m for m in previous.warnings if not (warning_footnotes(m) & only)] + extractor.warnings
    return Extraction(
        footnotes=[merged[fn.number] for fn in footnotes if fn.number in merged],
        warnings=warnings,
        provider_down=extractor.provider_down,
    )


def _render(extraction: Extraction, *, bibliography: bool, progress: Progress | None = None) -> ProcessResult:
    report = safe(progress)
    report("stage", {"name": "formatting"})
    extracted = [fn.model_copy(deep=True) for fn in extraction.footnotes]  # normalising edits in place
    warnings: list[Warning_] = [Warning_(message=m) for m in extraction.warnings]
    for fn in extracted:
        for seg in fn.segments:
            if isinstance(seg, CitationSegment):
                seg.citation, msgs = normalise_citation(seg.citation)
                warnings += [Warning_(footnote=fn.number, message=m) for m in msgs]

    unify_source_keys(seg.citation for fn in extracted for seg in fn.segments if isinstance(seg, CitationSegment))
    _share_short_titles(extracted)

    # Deterministic check that the formatter printed every field (aglc/validate.py)
    report("stage", {"name": "checking"})
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
    session: str | None = None,
    progress: Progress | None = None,
) -> ProcessResult:
    """Process `src` into `dst`. With `previous` and `only`, re-extract just those footnotes
    (see process_footnotes); everything after extraction is redone for the whole document.
    `session` (the API's session id) labels the summary log line; `progress` is told what is
    happening (see aglc/progress.py)."""
    t0 = time.monotonic()
    report = safe(progress)
    if not isinstance(provider, LLMProvider):
        provider = get_provider(provider)
    footnotes = read_footnotes(src)
    log.info("read %d footnotes from %s", len(footnotes), Path(src).name)
    report("total", {"footnotes": len(footnotes), "texts": footnote_texts(footnotes)})
    result = process_footnotes(
        footnotes, provider, bibliography=bibliography, previous=previous, only=only, progress=progress
    )
    report("stage", {"name": "writing_doc"})
    result.body_fixes = write_document(
        src,
        dst,
        result.footnotes,
        bibliography=result.bibliography if bibliography else None,
        track_changes=track_changes,
        fix_body=fix_body,
    )
    log.info("%s", run_summary(result, provider, session, time.monotonic() - t0))
    return result


# Kinds of warning, for the summary log line. Some warnings quote the footnote, so the line
# names only these fixed phrases (or "other"), never the warning itself. First match wins.
_WARNING_KINDS = (
    "extraction failed",
    "missing from LLM response",
    "LLM returned no segments",
    "left unchanged for manual review",
    "could not resolve",
    "points to footnote",
    "may have dropped",
    "left out of the AGLC citation",
    "kept text the extraction skipped",
    "trailing text not covered",
    "not in the footnote",
    "formatter omitted",
    "has no pinpoint",
    "has missing data",
    "unknown report series",
    "unknown court identifier",
    "unknown jurisdiction",
    "missing year",
    "missing jurisdiction",
    "missing journal name",
    "missing author",
    "starting page",
    "removed",
)


def warning_kinds(result) -> Counter[str]:
    """How many warnings of each kind in _WARNING_KINDS. `result` is anything `failed_footnotes` takes."""
    counts: Counter[str] = Counter()
    for message in _messages(result):
        text = message.lower()
        counts[next((k for k in _WARNING_KINDS if k.lower() in text), "other")] += 1
    return counts


def run_summary(result: ProcessResult, provider: LLMProvider, session: str | None, seconds: float) -> str:
    """One line per document with no student text: counts, the model and the time taken."""
    kinds = ", ".join(f"{kind} {n}" for kind, n in warning_kinds(result).most_common()) or "none"
    return (
        f"formatted session {session[:8] if session else '-'} with {provider.name}:{provider.model}:"
        f" {len(result.footnotes)} footnotes, {sum(f.changed for f in result.footnotes)} changed,"
        f" {len(failed_footnotes(result))} extraction failures, {len(result.body_fixes)} body fixes;"
        f" {len(result.warnings)} warnings ({kinds}); {seconds:.1f}s"
    )


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
    """Whether every footnote in one of the batches sent to the model (1-15, 16-30, ...) went
    unread, or the whole document did. Judged from the failed footnotes, not from a single
    warning: a failed batch is split into smaller requests, each warning about only its part.
    `result` is anything `failed_footnotes` takes."""
    failed = failed_footnotes(result)
    return any(
        set(range(start + 1, min(start + batch_size, total) + 1)) <= failed
        for start in range(0, total, batch_size)
    )
