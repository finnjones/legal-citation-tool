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
from typing import Annotated, Literal, Union, get_args

from pydantic import BaseModel, Field

from . import validate
from .llm.base import LLMError, LLMProvider
from .models import (
    Citation,
    CitationSegment,
    Footnote,
    OtherSource,
    RichText,
    Segment,
    Signal,
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


_SIGNALS = {str(v).lower().rstrip(","): v for v in get_args(Signal)} | {"eg": "Eg,", "see eg": "See, eg,", "see, eg": "See, eg,"}


def _split_leading_commentary(original: str, citation: Citation, out: list[Segment]) -> None:
    """If the model put commentary inside the citation's original text ('For a strong
    statement of this view, see Ronald Dworkin, ...') while also setting the signal, keep
    the commentary as text so it isn't lost."""
    if not citation.signal:
        return
    word = citation.signal.rstrip(",").lower()
    m = re.search(rf"(?i)(?:^|\s){re.escape(word)}\b[:,]?\s", original)
    if m and m.start() > 0:
        prefix = original[: m.start()].rstrip() + " "
        if out and isinstance(out[-1], TextSegment) and out[-1].text.text.strip():
            return  # the model already gave the commentary as its own text segment
        out.append(TextSegment(text=RichText.plain(prefix)))


def _drop_repeated_start_page(citation: Citation, original: str) -> Citation:
    """'..., 2008, p. 38' sometimes comes back as starting_page 38 *and* pinpoint 38, which
    renders '38, 38'. If the number appears only once in the source, it can't be both."""
    start = getattr(citation.source, "starting_page", None) or getattr(citation.source, "page", None)
    pins = citation.pinpoints
    if not start or len(pins) != 1 or pins[0].value.strip() != start.strip():
        return citation
    if len(re.findall(rf"(?<!\d){re.escape(start.strip())}(?!\d)", original)) <= 1:
        return citation.model_copy(update={"pinpoints": []})
    return citation


def _dedupe_signal(citation: Citation, out: list[Segment]) -> Citation:
    """If the model left the signal word at the end of the preceding text as well as in
    `citation.signal` ('... this view, see ' + signal 'See'), drop it from the text."""
    if not citation.signal or not out or not isinstance(out[-1], TextSegment):
        return citation
    prev = out[-1].text
    word = citation.signal.rstrip(",").lower()
    m = re.search(rf"(?i)\b{re.escape(word)}[:,]?\s*$", prev.text)
    if m:
        keep = RichText()
        remaining = m.start()
        for run in prev.runs:
            if remaining <= 0:
                break
            keep.append(run.text[:remaining], run.italic)
            remaining -= len(run.text)
        out[-1] = TextSegment(text=keep)
    return citation


def _author_names(source: Source) -> list[str]:
    names = list(getattr(source, "authors", None) or []) + list(getattr(source, "editors", None) or [])
    if getattr(source, "author", None):
        names.append(source.author)
    return names


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
            # Secondary sources are referred to by author surname ('Luntz (n 11)')
            for c in citations:
                if any(target in _norm(a) for a in _author_names(c.source)):
                    return c.source, c.short_title
        # The model named this footnote explicitly; if it cites only one source, that's it
        if len(citations) == 1:
            return citations[0].source, citations[0].short_title
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
        #: text between the previous cursor and the start of the last match
        self.skipped: RichText = RichText()

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
        self.skipped = RichText()
        for ch, italic in self._chars[self.cursor : idx]:
            self.skipped.append(ch, italic)
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
    def __init__(self, provider: LLMProvider, batch_size: int = 15, strict: bool = True, verify: bool = True) -> None:
        self.provider = provider
        self.batch_size = batch_size
        #: verify: run the deterministic coverage/grounding checks in aglc/validate.py
        self.verify = verify
        #: strict: a footnote whose extraction still drops content after a repair round is
        #: left exactly as written (and flagged) rather than rewritten with gaps.
        self.strict = strict
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
                if (llm_fn is None or not llm_fn.segments) and fn.original.text.strip():
                    # Models occasionally skip a footnote in a long batch; ask again for it alone.
                    llm_fn = self._retry_single(fn, resolved, system_prompt) or llm_fn
                if llm_fn is None:
                    self.warnings.append(f"footnote {fn.number}: missing from LLM response; left unchanged")
                    continue
                results[fn.number].segments = self._convert_verified(fn, llm_fn, resolved, system_prompt)
                resolved[fn.number] = results[fn.number]

        return [results[n] for n in order]

    # ---- verification (see aglc/validate.py) ------------------------------------ #

    def _convert_verified(
        self, fn: Footnote, llm_fn: LLMFootnote, resolved: dict[int, Footnote], system_prompt: str
    ) -> list[Segment]:
        """Convert, then check nothing in the footnote was dropped. If something was, ask the
        model once more naming exactly what it missed; if it still can't account for it,
        keep the footnote as written (strict) so no information is ever lost."""
        segments, missing = self._convert_and_check(fn, llm_fn, resolved)
        if not missing or not self.verify:
            return segments

        log.info("  footnote %d: extraction left out %s; asking again", fn.number, ", ".join(missing))
        repaired = self._repair(fn, missing, resolved, system_prompt)
        if repaired is not None:
            segments2, missing2 = self._convert_and_check(fn, repaired, resolved)
            if not missing2:
                return segments2
            segments, missing = segments2, missing2

        gaps = ", ".join(repr(t) for t in missing)
        if self.strict:
            self.warnings.append(
                f"footnote {fn.number}: left unchanged for manual review; the extraction kept dropping {gaps}"
            )
            return [TextSegment(text=fn.original.model_copy(deep=True))]
        self.warnings.append(f"footnote {fn.number}: may have dropped {gaps}; check it")
        return segments

    def _convert_and_check(
        self, fn: Footnote, llm_fn: LLMFootnote, resolved: dict[int, Footnote]
    ) -> tuple[list[Segment], list[str]]:
        segments = self._convert_footnote(fn, llm_fn, resolved)
        # footnote numbers in '(n 4)' / 'above n 4' are captured as refers_to_footnote
        refs = [str(s.refers_to_footnote) for s in llm_fn.segments
                if isinstance(s, LLMCitationSegment) and s.refers_to_footnote is not None]
        return segments, validate.missing_from_extraction(fn.original.text, segments, extra=refs)

    def _repair(
        self, fn: Footnote, missing: list[str], resolved: dict[int, Footnote], system_prompt: str
    ) -> LLMFootnote | None:
        user = (
            self._build_user_prompt([fn], self._build_index(resolved))
            + "\n\nYour previous extraction of this footnote left out these words/numbers from the "
            f"original: {', '.join(repr(t) for t in missing)}. Every part of the footnote must be "
            "captured: in a citation field, a pinpoint, pinpoint_judges, the signal, or a text "
            "segment for commentary. Extract the footnote again."
        )
        try:
            response = self.provider.generate_json(system=system_prompt, user=user, output_model=ExtractionBatch)
        except LLMError:
            return None
        return next((lf for lf in response.footnotes if lf.number == fn.number and lf.segments), None)

    def _retry_single(self, fn: Footnote, resolved: dict[int, Footnote], system_prompt: str) -> LLMFootnote | None:
        log.info("  footnote %d came back empty; asking for it on its own", fn.number)
        try:
            response = self.provider.generate_json(
                system=system_prompt,
                user=self._build_user_prompt([fn], self._build_index(resolved)),
                output_model=ExtractionBatch,
            )
        except LLMError:
            return None
        match = next((lf for lf in response.footnotes if lf.number == fn.number), None)
        return match if match and match.segments else None

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
                if seg.original:
                    mapper.slice(seg.original)  # advance the cursor past this span too
                    citation = self._recover_skipped(footnote.number, mapper.skipped, citation, out)
                    _split_leading_commentary(seg.original, citation, out)
                citation = _dedupe_signal(citation, out)
                citation = _drop_repeated_start_page(citation, seg.original)
                if self.verify and seg.refers_to_footnote is None:  # references carry earlier footnotes' data
                    citation, notes = validate.remove_invented_numbers(citation, footnote.original.text)
                    self.warnings += [f"footnote {footnote.number}: {n}" for n in notes]
                out.append(CitationSegment(citation=citation, original=seg.original))

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

    def _recover_skipped(self, number: int, skipped: RichText, citation: Citation, out: list[Segment]) -> Citation:
        """Text the model left out of every segment, just before a citation: a bare signal
        ('See: ') becomes the citation's signal; anything else is kept as text."""
        word = skipped.text.strip(" \t\n:;,")
        if not word:
            return citation
        signal = _SIGNALS.get(word.lower().rstrip("."))
        if signal:
            return citation if citation.signal else citation.model_copy(update={"signal": signal})
        out.append(TextSegment(text=skipped))
        self.warnings.append(f"footnote {number}: kept text the extraction skipped: {skipped.text.strip()!r}")
        return citation

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
            # the original text already contains its pinpoint, so don't emit it twice
            return citation.model_copy(
                update={"source": OtherSource(text=fallback_text), "pinpoints": [], "pinpoint_judges": None}
            )

        source, short_title = match
        return citation.model_copy(update={"source": source, "short_title": short_title})
