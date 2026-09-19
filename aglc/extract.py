"""LLM-driven extraction: raw footnote text -> structured segments.

The Extractor sends footnotes to the LLM in batches (via `provider.generate_json`), gets back a
small LLM-facing schema (`ExtractionBatch`), and converts it into `Footnote.segments`
(`TextSegment` / `CitationSegment`) as defined in `aglc.models`.

Two things happen here that the LLM is deliberately *not* asked to do, to keep the schema small
and avoid asking a model to be its own database:

1. Mapping each extracted text segment back onto the original `RichText` so italics (case names,
   titles) survive, by walking the original footnote text and matching substrings in order.
2. Resolving subsequent references (`Ibid`, `(n x)`, `above n x`, a reused short title) to the
   actual `Source` extracted for the target footnote, by looking it up in Python rather than
   asking the model to remember or re-derive bibliographic details it already produced elsewhere.
"""

from __future__ import annotations

import logging
import re
import time
from functools import lru_cache
from importlib import resources
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from .llm.base import LLMError, LLMProvider
from .models import (
    Citation,
    CitationSegment,
    Footnote,
    OtherSource,
    RichText,
    Segment,
    Source,
    TextSegment,
)


log = logging.getLogger("aglc")

# --------------------------------------------------------------------------- #
# LLM-facing schema. Kept small and flat: one discriminated union of two
# segment kinds, reusing `Citation`/`Source` from aglc.models directly so the
# model doesn't have to learn a second vocabulary for source fields.
# --------------------------------------------------------------------------- #


class LLMTextSegment(BaseModel):
    kind: Literal["text"] = "text"
    text: str = Field(description="Exact text copied verbatim from the footnote.")


class LLMCitationSegment(BaseModel):
    kind: Literal["citation"] = "citation"
    original: str = Field(default="", description="Exact text of just this citation, verbatim.")
    citation: Citation
    refers_to_footnote: int | None = Field(
        default=None,
        description="Footnote number this is a subsequent reference to (Ibid / (n x) / above n x), else null.",
    )


LLMSegment = Annotated[Union[LLMTextSegment, LLMCitationSegment], Field(discriminator="kind")]


class LLMFootnote(BaseModel):
    number: int
    segments: list[LLMSegment] = Field(default_factory=list)


class ExtractionBatch(BaseModel):
    footnotes: list[LLMFootnote] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# System prompt, loaded once from the packaged markdown file.
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=1)
def _load_system_prompt() -> str:
    return resources.files("aglc.prompts").joinpath("extraction.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def _norm(s: str) -> str:
    """Loose normalisation for matching short titles / names: lowercase, strip
    everything but letters and digits."""
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def _display_name(source: Source) -> str:
    """The human-readable name/title of a source, whatever field it lives in."""
    for attr in ("name", "title", "chapter_title"):
        value = getattr(source, attr, None)
        if value:
            return value
    return getattr(source, "text", "") or ""


def _match_citation(citations: list[Citation], short_title: str | None) -> tuple[Source, str | None] | None:
    """Find which of a footnote's citations a subsequent reference means.

    If a short title/name was given, match it (exact short-title match first, then a loose
    substring match on the source's display name). If none was given, the reference is only
    unambiguous when the target footnote has exactly one citation.
    """
    if not citations:
        return None
    if short_title:
        target = _norm(short_title)
        if target:
            for c in citations:
                if c.short_title and _norm(c.short_title) == target:
                    return c.source, c.short_title
            for c in citations:
                name = _norm(_display_name(c.source))
                if name and (target in name or name in target):
                    return c.source, c.short_title
        return None
    if len(citations) == 1:
        return citations[0].source, citations[0].short_title
    return None


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def _norm_char(ch: str) -> str:
    return " " if ch.isspace() else ch.translate(_QUOTES)


class _TextMapper:
    """Slices substrings out of a `RichText`, preserving italics, walking forward so repeated
    substrings resolve to successive occurrences rather than always the first.

    Matching ignores differences in whitespace (Word footnotes contain tabs and line breaks
    the LLM normalises away) and between curly and straight quotes."""

    def __init__(self, original: RichText) -> None:
        self._chars: list[tuple[str, bool]] = [(ch, run.italic) for run in original.runs for ch in run.text]
        self.plain: str = "".join(ch for ch, _ in self._chars)
        # Normalised view: runs of whitespace collapse to one space; _index maps each
        # normalised position back to its position in `plain`.
        norm: list[str] = []
        self._index: list[int] = []
        for i, ch in enumerate(self.plain):
            c = _norm_char(ch)
            if c == " " and norm and norm[-1] == " ":
                continue
            norm.append(c)
            self._index.append(i)
        self._norm = "".join(norm)
        self.cursor: int = 0

    def _find(self, text: str, start: int) -> tuple[int, int] | None:
        norm = "".join(_norm_char(c) for c in text)
        needle = " ".join(norm.split())
        if not needle:
            return None
        # keep one boundary space so separators like "; " keep their trailing space
        needle = (" " if norm[:1] == " " else "") + needle + (" " if norm[-1:] == " " else "")
        nstart = next((k for k, i in enumerate(self._index) if i >= start), len(self._index))
        k = self._norm.find(needle, nstart)
        if k == -1:
            return None
        begin = self._index[k]
        end = self._index[k + len(needle) - 1] + 1
        return begin, end

    def slice(self, text: str) -> RichText:
        if not text:
            return RichText()
        span = self._find(text, self.cursor) or self._find(text, 0)
        if span is None:
            return RichText.plain(text)  # not found at all: fall back to plain, don't move cursor
        idx, end = span
        out = RichText()
        for ch, italic in self._chars[idx:end]:
            out.append(ch, italic)
        self.cursor = max(self.cursor, end)
        return out

    def remainder(self) -> RichText:
        out = RichText()
        for ch, italic in self._chars[self.cursor :]:
            out.append(ch, italic)
        self.cursor = len(self._chars)
        return out


# --------------------------------------------------------------------------- #
# Extractor
# --------------------------------------------------------------------------- #


class Extractor:
    def __init__(self, provider: LLMProvider, batch_size: int = 15) -> None:
        self.provider = provider
        self.batch_size = batch_size
        #: human-readable warnings accumulated by the most recent `extract()` call
        self.warnings: list[str] = []

    def extract(self, footnotes: list[Footnote]) -> list[Footnote]:
        """Return copies of `footnotes` with `.segments` filled in."""
        self.warnings = []
        order = [fn.number for fn in footnotes]
        results: dict[int, Footnote] = {fn.number: fn.model_copy(deep=True) for fn in footnotes}
        # Footnotes fully resolved so far (across all batches, in call order), used both to build
        # the prior-source index and to resolve subsequent references, including references from
        # later footnotes in the *same* batch back to earlier ones in that batch.
        resolved: dict[int, Footnote] = {}
        system_prompt = _load_system_prompt()

        for start in range(0, len(footnotes), self.batch_size):
            batch = footnotes[start : start + self.batch_size]
            user_prompt = self._build_user_prompt(batch, self._build_index(resolved))
            n_batches = (len(footnotes) + self.batch_size - 1) // self.batch_size
            log.info(
                "asking %s for footnotes %d-%d (batch %d/%d)...",
                self.provider, batch[0].number, batch[-1].number, start // self.batch_size + 1, n_batches,
            )
            t0 = time.monotonic()
            try:
                response = self.provider.generate_json(
                    system=system_prompt, user=user_prompt, output_model=ExtractionBatch
                )
            except LLMError as e:
                numbers = ", ".join(str(fn.number) for fn in batch)
                log.warning("extraction failed for footnotes [%s] after %.1fs: %s", numbers, time.monotonic() - t0, e)
                self.warnings.append(f"extraction failed for footnotes [{numbers}]: {e}; left unchanged")
                continue
            log.info("  got %d footnotes back in %.1fs", len(response.footnotes), time.monotonic() - t0)

            by_number = {lf.number: lf for lf in response.footnotes}
            for fn in batch:
                llm_fn = by_number.get(fn.number)
                if llm_fn is None:
                    self.warnings.append(f"footnote {fn.number}: missing from LLM response; left unchanged")
                    continue
                results[fn.number].segments = self._convert_footnote(fn, llm_fn, resolved)
                resolved[fn.number] = results[fn.number]

        return [results[n] for n in order]

    # ---- prompt construction ------------------------------------------------ #

    def _build_index(self, resolved: dict[int, Footnote]) -> str:
        lines: list[str] = []
        for number in sorted(resolved):
            for seg in resolved[number].segments:
                if isinstance(seg, CitationSegment):
                    name = _display_name(seg.citation.source)
                    short = f" ('{seg.citation.short_title}')" if seg.citation.short_title else ""
                    lines.append(f"n{number}: {seg.citation.source.type} — {name}{short}")
        return "\n".join(lines) if lines else "(none yet — this is the first batch)"

    def _build_user_prompt(self, batch: list[Footnote], index_text: str) -> str:
        parts = [
            "Sources already extracted from earlier footnotes (use this to resolve '(n x)', "
            "'above n x' and reused short titles that point back to them):",
            index_text,
            "",
            "Extract the following footnotes. *Asterisks* mark italic runs in the original "
            "document and are for your reference only; do not include them in your output.",
            "",
        ]
        parts += [f"Footnote {fn.number}: {fn.original.to_markup()}" for fn in batch]
        return "\n".join(parts)

    # ---- conversion ---------------------------------------------------------- #

    def _convert_footnote(self, footnote: Footnote, llm_fn: LLMFootnote, resolved: dict[int, Footnote]) -> list[Segment]:
        if not llm_fn.segments:
            text = footnote.original.text
            if text.strip():
                self.warnings.append(f"footnote {footnote.number}: LLM returned no segments; kept original text as-is")
                return [TextSegment(text=footnote.original.model_copy(deep=True))]
            return []

        mapper = _TextMapper(footnote.original)
        out: list[Segment] = []
        for seg in llm_fn.segments:
            if isinstance(seg, LLMTextSegment):
                out.append(TextSegment(text=mapper.slice(seg.text)))
            else:
                citation = self._resolve_citation(footnote.number, seg, resolved)
                out.append(CitationSegment(citation=citation, original=seg.original))
                if seg.original:
                    mapper.slice(seg.original)  # advance the cursor past this span too

        if mapper.cursor < len(mapper.plain):
            leftover = mapper.remainder()
            # Closing punctuation is re-applied by the document pass, so a leftover that is
            # only punctuation/whitespace (the footnote's final full stop) is not content.
            if leftover.text.strip(" \t\n.;,"):
                self.warnings.append(
                    f"footnote {footnote.number}: trailing text not covered by extraction; appended verbatim"
                )
                out.append(TextSegment(text=leftover))
        return out

    def _resolve_citation(self, footnote_number: int, seg: LLMCitationSegment, resolved: dict[int, Footnote]) -> Citation:
        citation = seg.citation
        if seg.refers_to_footnote is None:
            return citation

        ref_fn = resolved.get(seg.refers_to_footnote)
        ref_citations = [s.citation for s in ref_fn.segments if isinstance(s, CitationSegment)] if ref_fn else []
        match = _match_citation(ref_citations, citation.short_title)
        if match is None:
            self.warnings.append(
                f"footnote {footnote_number}: could not resolve reference to footnote "
                f"{seg.refers_to_footnote} ({seg.original!r}); recorded as an unclassified source"
            )
            fallback_text = seg.original or citation.short_title or f"(n {seg.refers_to_footnote})"
            return citation.model_copy(update={"source": OtherSource(text=fallback_text)})

        source, short_title = match
        return citation.model_copy(update={"source": source, "short_title": short_title})
