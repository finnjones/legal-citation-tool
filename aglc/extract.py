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
import os
import re
import time
from functools import lru_cache
from importlib import resources
from typing import Annotated, Literal, Union, get_args

from pydantic import BaseModel, Field

from . import validate
from .llm.base import LLMError, LLMProvider
from .progress import Progress, found_in, safe
from .models import (
    CaseSource,
    Citation,
    CitationSegment,
    Footnote,
    OtherSource,
    Pinpoint,
    PinpointKind,
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
    omitted: str = Field(
        default="",
        description=(
            "Text from the original that AGLC deliberately leaves out, copied verbatim, eg the "
            "publisher and place of publication of a report ('Australian Government Publishing "
            "Service, Canberra'). Use this only for text a correct AGLC citation must not "
            "contain -- never for detail that belongs in a field."
        ),
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
    if source.type == "parliamentary_debates":
        parts = (source.jurisdiction, "Parliamentary Debates", source.chamber, source.date, source.speaker)
        return ", ".join(p for p in parts if p)
    if source.type == "submission":
        parts = (source.author, "Submission", source.submission_number, source.body, source.inquiry, source.date)
        return ", ".join(p for p in parts if p)
    if source.type == "committee_evidence":
        parts = ("Evidence", source.committee, source.location, source.date, source.speaker)
        return ", ".join(p for p in parts if p)
    if source.type == "social_media":
        return source.username
    if source.type == "un_document":
        return source.resolution or source.document_number or ""
    return getattr(source, "text", "") or ""


_SIGNALS = {str(v).lower().rstrip(","): v for v in get_args(Signal)} | {"eg": "Eg,", "see eg": "See, eg,", "see, eg": "See, eg,"}


def _signal_in(text: str, citation: Citation) -> re.Match | None:
    """Where the citation's signal word appears in `text` ('see ' in '..., see Dworkin')."""
    if not citation.signal:
        return None
    word = citation.signal.rstrip(",").lower()
    return re.search(rf"(?i)(?:^|\s){re.escape(word)}\b[:,]?\s", text)


def _split_leading_commentary(span: RichText, citation: Citation, out: list[Segment]) -> None:
    """If the model put commentary inside the citation's original text ('For a strong
    statement of this view, see Ronald Dworkin, ...') while also setting the signal, keep
    the commentary as text so it isn't lost."""
    m = _signal_in(span.text, citation)
    if m and m.start() > 0:
        prefix = span.slice(0, len(span.text[: m.start()].rstrip())).append(" ")
        if out and isinstance(out[-1], TextSegment) and out[-1].text.text.strip():
            return  # the model already gave the commentary as its own text segment
        out.append(TextSegment(text=prefix))


def _keep_only_real_short_title(citation: Citation) -> Citation:
    """Drop a 'short title' read from a reference when it isn't an abbreviation at all: a
    case's full name repeated ('Donoghue v Stevenson, supra n 1, 599'), or the authors'
    surnames ('Sanson (n 27)', 'Hamer et al (n 14)'), which r 1.4.1 uses without defining
    them. Legislation short titles legitimately equal the title without its year ('Adoption Act')."""
    short = (citation.short_title or "").strip()
    if short and citation.source.type == "case" and _norm(short) == _norm(_display_name(citation.source)):
        return citation.model_copy(update={"short_title": None})
    surnames = {_norm(n.split()[-1]) for n in _author_names(citation.source) if n.split()}
    parts = [p for p in re.split(r"(?i)\s*(?:,|&|\band\b|\bet\.?\s+al\b\.?)\s*", short) if p.strip()]
    if parts and all(_norm(p) in surnames for p in parts):
        return citation.model_copy(update={"short_title": None})
    return citation


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


_IBID = re.compile(r"(?i)\s*\*?ibid\b")

_PROVISIONS = {PinpointKind.section, PinpointKind.regulation, PinpointKind.rule, PinpointKind.clause,
               PinpointKind.article}
_SUBDIVISION = re.compile(r"[0-9]{1,4}[A-Z]{0,2}|[a-z]{1,2}|[ivxlc]{1,6}|[A-Z]")


def _as_subdivisions(value: str) -> str | None:
    """'1' -> '(1)'; '(1)(b)', '1, b' and '(1), (b)' -> '(1)(b)'; None for anything that
    isn't a run of subdivisions."""
    parts = [p for p in re.split(r"[\s,()]+", value) if p]
    if not parts or re.search(r"[^\w\s,()]", value) or not all(_SUBDIVISION.fullmatch(p) for p in parts):
        return None
    return "".join(f"({p})" for p in parts)


def _bracketed_paragraphs(citation: Citation, original: str) -> Citation:
    """A pinpoint the citation's own text writes in square brackets ('[202]') is a paragraph,
    whatever kind the model gave it; one written without them is left as written."""
    text = re.sub(r"\s+", "", original)
    pins = [p.model_copy(update={"kind": PinpointKind.paragraph})
            if p.kind == PinpointKind.page and "[" + re.sub(r"\s+", "", p.value) + "]" in text else p
            for p in citation.pinpoints]
    return citation if pins == citation.pinpoints else citation.model_copy(update={"pinpoints": pins})


def _bare_numbers_as_written(citation: Citation, original: str) -> tuple[Citation, list[str]]:
    """r 2.3.1: a case cited by its medium neutral citation has no pages, so a number written
    after it without square brackets ('Kvelde (n 8) 69, [202]') can't be read as a page or
    a paragraph. Keep it exactly as written, with the comma after it, and say so."""
    src = citation.source
    if not (isinstance(src, CaseSource) and src.court_id and not src.report):
        return citation, []
    pins, notes = [], []
    for k, p in enumerate(citation.pinpoints):
        if p.kind != PinpointKind.page:
            pins.append(p)
            continue
        m = re.search(rf"(?<![\w\[]){re.escape(p.value.strip())}(?![\w\]])\s*(,?)", original)
        comma = m.group(1) if m and k + 1 < len(citation.pinpoints) else ""
        pins.append(Pinpoint(kind=PinpointKind.other, value=p.value.strip() + comma))
        notes.append(f"pinpoint {p.value.strip()} has no square brackets, but a case cited by its medium "
                     f"neutral citation has no page numbers (AGLC4 r 2.3.1): if it is a paragraph, write "
                     f"[{p.value.strip()}]")
    return citation.model_copy(update={"pinpoints": pins}), notes


def _join_subdivisions(citation: Citation, original: str) -> Citation:
    """'s 214A(1)(b)' sometimes comes back as three pinpoints (section '214A', then '1' and
    'b'), which renders 's 214A 1, b'. Where the citation's own text has the provision with
    those subdivisions bracketed after it, put them back into the provision's value."""
    pins = citation.pinpoints
    text = re.sub(r"\s+", "", original)
    out: list[Pinpoint] = []
    i = 0
    while i < len(pins):
        p = pins[i]
        i += 1
        if p.kind not in _PROVISIONS or p.plural:
            out.append(p)
            continue
        value, j = p.value.strip(), i
        while j < len(pins) and (sub := _as_subdivisions(pins[j].value)):
            longer = value + sub
            if re.sub(r"\s+", "", longer) not in text:
                break
            value, j = longer, j + 1
        out.append(p.model_copy(update={"value": value}) if j > i else p)
        i = j
    if len(out) == len(pins):
        return citation
    return citation.model_copy(update={"pinpoints": out})


def _continues_citation(text: str, out: list[Segment]) -> bool:
    """Whether text the model left out of every segment, right after a citation, is the rest
    of that citation (its pinpoint, say), already captured in its fields, rather than
    something to keep as written."""
    if not out or not isinstance(out[-1], CitationSegment) or not any(ch.isalnum() for ch in text):
        return False
    return not validate.missing_from_extraction(text, [out[-1]])


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


def _keep_italics(citation: Citation, span: RichText) -> Citation:
    """An unclassified source is emitted verbatim: keep the italics its text has in the
    footnote ('New South Wales, *Parliamentary Debates*, ...'), which `OtherSource.text`
    alone can't carry. A source resolved from an earlier footnote already has them."""
    src = citation.source
    if not isinstance(src, OtherSource) or src.rich is not None:
        return citation
    found = _TextMapper(span).find(src.text)
    if found is None:
        return citation
    return citation.model_copy(update={"source": src.model_copy(update={"text": found.text, "rich": found})})


def _keep_original_text(citation: Citation, span: RichText) -> Citation:
    """An unclassified source is emitted verbatim, so what's emitted must be the footnote's
    own text. When the model's `text` isn't part of the citation's span ('x' for 'Mabo v
    Queensland ...'), use the span itself, after any signal (which the signal already prints).
    The span carries its own pinpoint and short title, so the separate ones are dropped
    rather than printed twice."""
    src = citation.source
    if not isinstance(src, OtherSource) or src.rich is not None or _TextMapper(span).find(src.text) is not None:
        return citation
    m = _signal_in(span.text, citation)
    rest = span.text[m.end():] if m else span.text
    start = len(span.text) - len(rest.lstrip())
    rich = span.slice(start, len(span.text.rstrip()))
    if not rich.text:
        return citation
    return citation.model_copy(update={
        "source": src.model_copy(update={"text": rich.text, "rich": rich}),
        "pinpoints": [], "pinpoint_judges": None, "short_title": None,
    })


def _keep_et_al(citation: Citation, original: str) -> Citation:
    """r 4.1.2: 'David Hamer et al, ...' must keep its 'et al'. Models tend to return just
    the named author and nothing to say there were more, so read it from the text."""
    src = citation.source
    authors = getattr(src, "authors", None)
    if not authors or getattr(src, "et_al", True):
        return citation
    if re.search(rf"{re.escape(authors[-1].strip())}\s*,?\s*et\.?\s+al\b", original, re.I):
        return citation.model_copy(update={"source": src.model_copy(update={"et_al": True})})
    return citation


#: Source types whose title is quoted and roman (r 5.2, 6.6.1, 7.3, 7.4, 7.10, 7.15, 7.16), and its field
_QUOTED_TITLES = {
    "journal_article": "title", "book_chapter": "chapter_title", "newspaper": "title", "website": "title",
    "speech": "title", "media_release": "title", "social_media": "title",
}


def _keep_title_italics(citation: Citation, span: RichText) -> Citation:
    """A case or Act name inside a quoted title stays italic ('... under the *Summary
    Offences and Other Legislation Amendment Act 2019* (Qld)'). The title field is a plain
    str, so keep the italics the student gave it in the footnote; none are added. A title
    that is italic throughout is an article title mistakenly italicised, so it's left roman."""
    src = citation.source
    field = _QUOTED_TITLES.get(src.type)
    if field is None or getattr(src, f"{field}_rich") is not None:
        return citation
    title = getattr(src, field)
    found = _TextMapper(span).find(title) if title else None
    if found is None:
        return citation
    styles = {run.italic for run in found.runs if run.text.strip()}
    if styles != {True, False}:
        return citation
    return citation.model_copy(update={"source": src.model_copy(update={f"{field}_rich": found})})


def _author_names(source: Source) -> list[str]:
    names = list(getattr(source, "authors", None) or []) + list(getattr(source, "editors", None) or [])
    if getattr(source, "author", None):
        names.append(source.author)
    return names


def _distinct(matches: list[tuple[Source, str | None]]) -> list[tuple[Source, str | None]]:
    out: list[tuple[Source, str | None]] = []
    for m in matches:
        if all(m[0] != o[0] for o in out):
            out.append(m)
    return out


def _match_citations(citations: list[Citation], short_title: str | None) -> list[tuple[Source, str | None]]:
    """Which of a footnote's citations a subsequent reference can mean: one is a match,
    none is no match, and several are ambiguous ('Smith (n 1)' where n 1 cites two Smiths).

    If a short title/name was given, match it (exact short-title match first, then a loose
    substring match on the source's display name, then an author's surname, then part of an
    author's name); a name matching nothing is no match (see `_find_named`). If none was
    given, the reference is only unambiguous when the target footnote has exactly one citation.
    """
    if not citations:
        return []
    if short_title:
        target = _norm(short_title)
        if target:
            tiers = (
                lambda c: bool(c.short_title) and _norm(c.short_title) == target,
                lambda c: bool(name := _norm(_display_name(c.source))) and (target in name or name in target),
                # Secondary sources are referred to by author surname ('Luntz (n 11)')
                lambda c: any(a.split() and _norm(a.split()[-1]) == target for a in _author_names(c.source)),
                lambda c: any(target in _norm(a) for a in _author_names(c.source)),
            )
            for matches in tiers:
                found = _distinct([(c.source, c.short_title) for c in citations if matches(c)])
                if found:
                    return found
            # A name that matches nothing in the footnote is a wrong number, not a reason to
            # take whatever that footnote cites ('Kvelde (n 12)' where n 12 is the Crimes Act)
            return []
    return _distinct([(c.source, c.short_title) for c in citations])


def _find_named(short_title: str, resolved: dict[int, Footnote], before: int) -> tuple[int, tuple[Source, str | None]] | None:
    """The earliest footnote before `before` that cites a source called exactly `short_title`
    (its short title, its name or title, or an author's surname), for a reference whose
    footnote number is wrong. None when no source, or more than one, is called that."""
    target = _norm(short_title)
    if not target:
        return None
    found: list[tuple[int, tuple[Source, str | None]]] = []
    for number in sorted(n for n in resolved if n < before):
        for seg in resolved[number].segments:
            if not isinstance(seg, CitationSegment):
                continue
            c = seg.citation
            names = [c.short_title or "", _display_name(c.source)] + [a.split()[-1] for a in _author_names(c.source) if a.split()]
            if target in {_norm(n) for n in names if n} and all(c.source != f[1][0] for f in found):
                found.append((number, (c.source, c.short_title)))
    return found[0] if len(found) == 1 else None


_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})


def _norm_char(ch: str) -> str:
    return " " if ch.isspace() else ch.translate(_QUOTES)


class _TextMapper:
    """Slices substrings out of a `RichText`, preserving italics, walking forward so the
    slices are ordered, non-overlapping spans of the original: repeated substrings resolve to
    successive occurrences, and text an earlier slice already took is never matched again.

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
        #: where the last match started
        self.start: int = 0
        #: text between the previous cursor and the start of the last match
        self.skipped: RichText = RichText()

    def _find(self, text: str, start: int) -> tuple[int, int] | None:
        if "*" not in self.plain:
            # the model sometimes copies the *italic* markup it was shown into its text
            text = text.replace("*", "")
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

    def slice(self, text: str) -> RichText | None:
        """The next occurrence of `text` at or after the cursor, moving the cursor past it,
        or None (cursor unchanged) when the rest of the original doesn't contain it."""
        span = self._find(text, self.cursor) if text else None
        if span is None:
            return None
        idx, end = span
        self.start = idx
        self.skipped = RichText()
        for ch, italic in self._chars[self.cursor : idx]:
            self.skipped.append(ch, italic)
        out = RichText()
        for ch, italic in self._chars[idx:end]:
            out.append(ch, italic)
        self.cursor = end
        return out

    def find(self, text: str) -> RichText | None:
        """The first occurrence of `text`, with its italics, or None; doesn't move the cursor."""
        span = self._find(text, 0)
        if span is None:
            return None
        out = RichText()
        for ch, italic in self._chars[span[0] : span[1]]:
            out.append(ch, italic)
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


class _WritingWatcher:
    """Reads a streamed reply as it arrives and reports each of the batch's footnotes the model
    has started writing (its `"number": 17` key), so the page can show them under way."""

    _NUMBER = re.compile(r'"number"\s*:\s*(\d+)')

    def __init__(self, numbers: list[int], report: Progress) -> None:
        self._wanted = set(numbers)
        self._seen: set[int] = set()
        self._tail = ""
        self._report = report

    def __call__(self, text: str) -> None:
        window = self._tail + text
        self._tail = window[-40:]  # a key split across two pieces is still found
        new = {int(m) for m in self._NUMBER.findall(window)} & self._wanted - self._seen
        if new:
            self._seen |= new
            self._report("writing", {"numbers": sorted(new)})


class Extractor:
    #: a failed batch is asked again in pieces this size, then one footnote at a time
    split_size = 5
    #: after this many failed requests in a row the provider is taken to be down, and a
    #: failed batch is no longer split (each top-level batch is still tried once)
    max_failures_in_a_row = 4

    def __init__(
        self,
        provider: LLMProvider,
        batch_size: int = 15,
        strict: bool = True,
        verify: bool = True,
        progress: Progress | None = None,
        deadline: float | None = None,
    ) -> None:
        self.provider = provider
        self.batch_size = batch_size
        #: told what is happening as it happens (see aglc/progress.py)
        self._report = safe(progress)
        #: seconds the whole document may spend asking the model, from $AGLC_DOCUMENT_DEADLINE
        #: (default 300); footnotes not read by then are left as written, for the free re-run
        self.deadline = deadline if deadline is not None else float(os.environ.get("AGLC_DOCUMENT_DEADLINE") or 300)
        self._deadline_at = float("inf")
        #: verify: run the deterministic coverage/grounding checks in aglc/validate.py
        self.verify = verify
        #: strict: a footnote whose extraction still drops content after a repair round is
        #: left exactly as written (and flagged) rather than rewritten with gaps.
        self.strict = strict
        #: human-readable warnings accumulated by the most recent `extract()` call
        self.warnings: list[str] = []
        self._failures_in_a_row = 0

    def extract(self, footnotes: list[Footnote], context: list[Footnote] | None = None) -> list[Footnote]:
        """Return copies of `footnotes` with `.segments` filled in. `context` is footnotes already
        extracted (eg when re-running only the ones that failed), for resolving '(n x)'."""
        self.warnings = []
        self._failures_in_a_row = 0
        self._deadline_at = time.monotonic() + self.deadline
        order = [fn.number for fn in footnotes]
        results: dict[int, Footnote] = {fn.number: fn.model_copy(deep=True) for fn in footnotes}
        # Footnotes fully resolved so far (across all batches, in call order), used both to build
        # the prior-source index and to resolve subsequent references, including references from
        # later footnotes in the *same* batch back to earlier ones in that batch.
        resolved: dict[int, Footnote] = {fn.number: fn for fn in context or [] if fn.segments and fn.number not in results}
        system_prompt = _load_system_prompt()

        n_batches = (len(footnotes) + self.batch_size - 1) // self.batch_size
        for start in range(0, len(footnotes), self.batch_size):
            batch = footnotes[start : start + self.batch_size]
            log.info(
                "asking %s for footnotes %d-%d (batch %d/%d)...",
                self.provider, batch[0].number, batch[-1].number, start // self.batch_size + 1, n_batches,
            )
            self._extract_batch(batch, results, resolved, system_prompt)

        return [results[n] for n in order]

    def _request(self, user_prompt: str, system_prompt: str, numbers: list[int] | None = None) -> ExtractionBatch | LLMError:
        """Ask the model, reporting which of `numbers` it starts writing as its reply streams in."""
        self.provider.on_text = _WritingWatcher(numbers or [], self._report) if numbers else None
        self.provider.on_event = self._provider_event
        try:
            response = self.provider.generate_json(system=system_prompt, user=user_prompt, output_model=ExtractionBatch)
        except LLMError as e:
            self._failures_in_a_row += 1
            return e
        finally:
            self.provider.on_text = self.provider.on_event = None
        self._failures_in_a_row = 0
        return response

    def _provider_event(self, kind: str, data: dict) -> None:
        if kind == "retry":
            self._report("note", {"kind": "slow" if data.get("timed_out") else "retry"})
        elif kind == "fallback":
            self._report("note", {"kind": "fallback"})

    def _out_of_time(self) -> bool:
        return time.monotonic() > self._deadline_at

    def _provider_down(self) -> bool:
        return self._failures_in_a_row >= self.max_failures_in_a_row

    @property
    def provider_down(self) -> bool:
        """Whether the most recent `extract()` ended with the provider apparently down."""
        return self._provider_down()

    def _give_up(self, batch: list[Footnote], results: dict[int, Footnote], error: LLMError) -> None:
        numbers = ", ".join(str(fn.number) for fn in batch)
        self.warnings.append(f"extraction failed for footnotes [{numbers}]: {error}; left unchanged")
        for fn in batch:
            results[fn.number].extraction_failed = "provider_error"
        self._report("done", {"numbers": [fn.number for fn in batch], "failed": True})

    def _extract_batch(
        self, batch: list[Footnote], results: dict[int, Footnote], resolved: dict[int, Footnote], system_prompt: str
    ) -> None:
        if self._out_of_time():
            # Asking any more would keep the student waiting too long: the rest can be re-run free.
            log.warning("out of time for footnotes %s", ", ".join(str(fn.number) for fn in batch))
            self._report("note", {"kind": "deadline", "count": len(batch)})
            self._give_up(batch, results, LLMError(f"the model took longer than {self.deadline:g}s for this document"))
            return
        numbers_in_batch = [fn.number for fn in batch]
        user_prompt = self._build_user_prompt(batch, self._build_index(resolved))
        t0 = time.monotonic()
        response = self._request(user_prompt, system_prompt, numbers_in_batch)
        if isinstance(response, LLMError):
            numbers = ", ".join(str(fn.number) for fn in batch)
            log.warning("extraction failed for footnotes [%s] after %.1fs: %s", numbers, time.monotonic() - t0, response)
            if len(batch) > 1 and not self._provider_down():
                # A failure on a big request is often the request, not the footnotes: ask again
                # in smaller pieces (15 -> 5s -> one at a time) before giving up on any of them.
                size = self.split_size if len(batch) > self.split_size else 1
                log.info("  asking again in batches of %d", size)
                self._report("note", {"kind": "split", "size": size, "count": len(batch)})
                for i in range(0, len(batch), size):
                    if self._provider_down():
                        self._give_up(batch[i:], results, response)
                        break
                    self._extract_batch(batch[i : i + size], results, resolved, system_prompt)
                return
            self._give_up(batch, results, response)
            return
        log.info("  got %d footnotes back in %.1fs", len(response.footnotes), time.monotonic() - t0)

        by_number = {lf.number: lf for lf in response.footnotes}
        answered = sum(1 for fn in batch if by_number.get(fn.number) and by_number[fn.number].segments)
        if answered * 2 < len(batch) and len(batch) > 1:
            # The model answered for only a few of the batch; re-asking the whole batch is
            # far cheaper than one call per missing footnote.
            log.info("  only %d/%d footnotes answered; re-asking the batch", answered, len(batch))
            self.provider.avoid_last_host()  # a host that half-answers tends to do it every time
            self._report("note", {"kind": "reask", "answered": answered, "count": len(batch)})
            retry = self._request(user_prompt, system_prompt, numbers_in_batch)
            if not isinstance(retry, LLMError):
                better = {lf.number: lf for lf in retry.footnotes}
                if sum(1 for fn in batch if better.get(fn.number) and better[fn.number].segments) > answered:
                    by_number = better
        for fn in batch:
            llm_fn = by_number.get(fn.number)
            if (llm_fn is None or not llm_fn.segments) and fn.original.text.strip():
                # Models occasionally skip a footnote in a long batch; ask again for it alone.
                llm_fn = self._retry_single(fn, resolved, system_prompt) or llm_fn
            if llm_fn is None:
                self.warnings.append(f"footnote {fn.number}: missing from LLM response; left unchanged")
                results[fn.number].extraction_failed = "not_returned"
                self._report("done", {"numbers": [fn.number], "failed": True})
                continue
            if not llm_fn.segments and fn.original.text.strip():
                results[fn.number].extraction_failed = "not_returned"  # kept as written, below
            results[fn.number].segments = self._convert_verified(fn, llm_fn, resolved, system_prompt)
            resolved[fn.number] = results[fn.number]
            self._report("done", {"numbers": [fn.number], "failed": results[fn.number].extraction_failed is not None,
                                  "found": {fn.number: found_in(results[fn.number])}})

    # ---- verification (see aglc/validate.py) ------------------------------------ #

    def _convert_verified(
        self, fn: Footnote, llm_fn: LLMFootnote, resolved: dict[int, Footnote], system_prompt: str
    ) -> list[Segment]:
        """Convert, then check nothing in the footnote was dropped and every citation is in it.
        If not, ask the model once more naming exactly what went wrong; if it still can't get
        it right, keep the footnote as written (strict) so nothing is lost or invented."""
        segments, missing, unlocated = self._convert_and_check(fn, llm_fn, resolved)
        if not (missing or unlocated) or not self.verify:
            return segments

        log.info("  footnote %d: extraction left out %d pieces of text and %d citations aren't in it; asking again",
                 fn.number, len(missing), len(unlocated))
        self._report("note", {"kind": "repair", "number": fn.number})
        repaired = self._repair(fn, missing, unlocated, resolved, system_prompt)
        if repaired is not None:
            segments2, missing2, unlocated2 = self._convert_and_check(fn, repaired, resolved)
            if not (missing2 or unlocated2):
                return segments2
            segments, missing, unlocated = segments2, missing2, unlocated2

        problems = []
        if missing:
            problems.append("dropping " + ", ".join(repr(t) for t in missing))
        if unlocated:
            problems.append("giving citation text not in the footnote: " + ", ".join(repr(t) for t in unlocated))
        if self.strict:
            self.warnings.append(
                f"footnote {fn.number}: left unchanged for manual review; the extraction kept {' and '.join(problems)}"
            )
            return [TextSegment(text=fn.original.model_copy(deep=True))]
        if missing:
            self.warnings.append(f"footnote {fn.number}: may have dropped {', '.join(repr(t) for t in missing)}; check it")
        if unlocated:
            self.warnings.append(
                f"footnote {fn.number}: citation text not in the footnote: {', '.join(repr(t) for t in unlocated)}; check it"
            )
        return segments

    def _convert_and_check(
        self, fn: Footnote, llm_fn: LLMFootnote, resolved: dict[int, Footnote]
    ) -> tuple[list[Segment], list[str], list[str]]:
        """The segments, the words of the footnote they leave out, and the citations whose
        `original` isn't in the footnote."""
        segments, unlocated = self._convert_footnote(fn, llm_fn, resolved)
        # footnote numbers in '(n 4)' / 'above n 4' are captured as refers_to_footnote
        accounted = [str(s.refers_to_footnote) for s in llm_fn.segments
                     if isinstance(s, LLMCitationSegment) and s.refers_to_footnote is not None]
        accounted += [s.omitted for s in llm_fn.segments if isinstance(s, LLMCitationSegment) and s.omitted]
        for text in (s.omitted for s in llm_fn.segments if isinstance(s, LLMCitationSegment) and s.omitted):
            note = f"footnote {fn.number}: left out of the AGLC citation: {text.strip()!r}"
            if note not in self.warnings:
                self.warnings.append(note)
        return segments, validate.missing_from_extraction(fn.original.text, segments, extra=accounted), unlocated

    def _repair(
        self, fn: Footnote, missing: list[str], unlocated: list[str], resolved: dict[int, Footnote], system_prompt: str
    ) -> LLMFootnote | None:
        user = self._build_user_prompt([fn], self._build_index(resolved))
        if missing:
            user += (
                "\n\nYour previous extraction of this footnote left out these words/numbers from the "
                f"original: {', '.join(repr(t) for t in missing)}. Every part of the footnote must be "
                "captured: in a citation field, a pinpoint, pinpoint_judges, the signal, or a text "
                "segment for commentary."
            )
        if unlocated:
            user += (
                "\n\nIn your previous extraction of this footnote, the `original` of these citations "
                f"is not text of the footnote: {', '.join(repr(t) for t in unlocated)}. Each "
                "segment must copy its text exactly, in the order it appears, without repeating text "
                "another segment already covers."
            )
        user += " Extract the footnote again."
        response = self._request(user, system_prompt, [fn.number])
        if isinstance(response, LLMError):
            return None
        return next((lf for lf in response.footnotes if lf.number == fn.number and lf.segments), None)

    def _retry_single(self, fn: Footnote, resolved: dict[int, Footnote], system_prompt: str) -> LLMFootnote | None:
        log.info("  footnote %d came back empty; asking for it on its own", fn.number)
        self._report("note", {"kind": "single", "number": fn.number})
        response = self._request(self._build_user_prompt([fn], self._build_index(resolved)), system_prompt, [fn.number])
        if isinstance(response, LLMError):
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

    def _convert_footnote(
        self, footnote: Footnote, llm_fn: LLMFootnote, resolved: dict[int, Footnote]
    ) -> tuple[list[Segment], list[str]]:
        """The footnote's segments, and the `original` of each citation that couldn't be found
        in the footnote (in order, after the segments before it)."""
        if not llm_fn.segments:
            text = footnote.original.text
            if text.strip():
                self.warnings.append(f"footnote {footnote.number}: LLM returned no segments; kept original text as-is")
                return [TextSegment(text=footnote.original.model_copy(deep=True))], []
            return [], []

        # Every segment's text is a span of the original, in order and never reused: text the
        # model wrote that isn't next in the footnote is never emitted, and the original text
        # it should have covered is kept as skipped or trailing text instead.
        mapper = _TextMapper(footnote.original)
        out: list[Segment] = []
        unlocated: list[str] = []
        starts: list[int] = []  # where each segment the model gave starts in the original
        citations: list[tuple[int, int | None, bool]] = []  # (index in out, start, check its numbers)
        for seg in llm_fn.segments:
            if isinstance(seg, LLMTextSegment):
                span = mapper.slice(seg.text)
                if span is None:
                    if seg.text.strip():
                        self.warnings.append(
                            f"footnote {footnote.number}: ignored extracted text not in the footnote: {seg.text.strip()!r}"
                        )
                    continue
                starts.append(mapper.start)
                if not _continues_citation(mapper.skipped.text, out):
                    self._keep_skipped(footnote.number, mapper.skipped, out)
                out.append(TextSegment(text=span))
            else:
                earlier = [s.citation for s in out if isinstance(s, CitationSegment)]
                citation = self._resolve_citation(footnote.number, seg, resolved, earlier)
                span = mapper.slice(seg.original)  # also advances the cursor past this span
                start = mapper.start if span is not None else None
                if span is not None:
                    starts.append(start)
                    if not _continues_citation(mapper.skipped.text, out):
                        citation = self._recover_skipped(footnote.number, mapper.skipped, citation, out)
                    _split_leading_commentary(span, citation, out)
                    if seg.refers_to_footnote is None:
                        citation = _keep_original_text(citation, span)
                else:
                    # Nowhere to anchor it: the citation may not be in the footnote at all
                    unlocated.append(seg.original)
                    span = RichText.plain(seg.original) if seg.original else footnote.original
                citation = _keep_italics(citation, span)
                if seg.refers_to_footnote is None:
                    citation = _keep_et_al(citation, span.text)
                citation = _keep_title_italics(citation, span)
                citation = _dedupe_signal(citation, out)
                citation = _drop_repeated_start_page(citation, span.text if seg.original else "")
                # references carry earlier footnotes' data, so only new sources' numbers are checked
                citations.append((len(out), start, self.verify and seg.refers_to_footnote is None))
                out.append(CitationSegment(citation=citation, original=span.text if seg.original else ""))

        # A citation's own text runs from where it starts to where the next segment does, so
        # a pinpoint the model left out of `original` ('Ibid' for 'Ibid s 214A(1)(b)') is still
        # its own, and no other citation's is
        for i, start, ground in citations:
            if start is None:  # nowhere to anchor it (reported as not in the footnote)
                own = out[i].original or mapper.plain
            else:
                own = mapper.plain[start: min((s for s in starts if s > start), default=len(mapper.plain))]
            citation = _bracketed_paragraphs(_join_subdivisions(out[i].citation, own), own)
            citation, notes = _bare_numbers_as_written(citation, own)
            self.warnings += [f"footnote {footnote.number}: {n}" for n in notes]
            if ground:
                citation, notes = validate.remove_invented_numbers(citation, own)
                self.warnings += [f"footnote {footnote.number}: {n}" for n in notes]
            out[i] = out[i].model_copy(update={"citation": citation})

        if mapper.cursor < len(mapper.plain):
            leftover = mapper.remainder()
            # Closing punctuation is re-applied by the document pass, so a leftover that is
            # only punctuation/whitespace (the footnote's final full stop) is not content;
            # nor is the rest of the last citation ('s 214A(1)(b)' after an 'Ibid' original)
            if leftover.text.strip(" \t\n.;,") and not _continues_citation(leftover.text, out):
                self.warnings.append(
                    f"footnote {footnote.number}: trailing text not covered by extraction; appended verbatim"
                )
                out.append(TextSegment(text=leftover))
        return out, unlocated

    def _ibid_target(
        self, footnote_number: int, seg: LLMCitationSegment, resolved: dict[int, Footnote], earlier: list[Citation]
    ) -> tuple[Citation | None, int]:
        """r 1.4.3: 'Ibid' means the citation immediately before it: the one before it in its
        own footnote, or the sole citation of the footnote before, whatever footnote the model
        named. Otherwise no match, and the footnote for the ordinary lookup to search (with a
        warning, as the reading can't be checked)."""
        if earlier:
            return earlier[-1], footnote_number
        previous = footnote_number - 1
        prev_fn = resolved.get(previous)
        cites = [s.citation for s in prev_fn.segments if isinstance(s, CitationSegment)] if prev_fn else []
        if len(cites) == 1:
            if seg.refers_to_footnote != previous:
                self.warnings.append(
                    f"footnote {footnote_number}: 'Ibid' points to footnote {previous}, the one before it, "
                    f"not footnote {seg.refers_to_footnote} as the extraction read it"
                )
            return cites[0], previous
        if cites:
            self.warnings.append(
                f"footnote {footnote_number}: 'Ibid' follows a footnote citing {len(cites)} sources, so "
                "which one it means is unclear (AGLC4 r 1.4.3); check it"
            )
            return None, previous
        self.warnings.append(
            f"footnote {footnote_number}: 'Ibid' follows a footnote that cites nothing; "
            f"read as referring to footnote {seg.refers_to_footnote}; check it"
        )
        return None, seg.refers_to_footnote

    def _keep_skipped(self, number: int, skipped: RichText, out: list[Segment]) -> None:
        """Text the model left out of every segment, just before a text segment: kept as text
        (a separator or full stop quietly, words with a warning)."""
        if not skipped.text.strip():
            return
        out.append(TextSegment(text=skipped))
        if any(ch.isalnum() for ch in skipped.text):
            self.warnings.append(f"footnote {number}: kept text the extraction skipped: {skipped.text.strip()!r}")

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

    def _resolve_citation(
        self, footnote_number: int, seg: LLMCitationSegment, resolved: dict[int, Footnote], earlier: list[Citation]
    ) -> Citation:
        """The source a subsequent reference means, looked up in the footnote it refers to.
        `earlier` is the citations before it in its own footnote."""
        citation = seg.citation
        if seg.refers_to_footnote is None:
            return citation
        ref = seg.refers_to_footnote
        if _IBID.match(seg.original):
            target, ref = self._ibid_target(footnote_number, seg, resolved, earlier)
            if target is not None:
                update = {"source": target.source, "short_title": citation.short_title or target.short_title}
                if not citation.pinpoints:
                    # r 1.4.3: a bare 'Ibid' means the same pinpoint as the citation before it
                    # (the model is told to leave its pinpoints empty), not the whole source
                    update["pinpoints"] = target.pinpoints
                    if not citation.pinpoint_judges:
                        update["pinpoint_judges"] = target.pinpoint_judges
                return _keep_only_real_short_title(citation.model_copy(update=update))
        if not citation.short_title:
            # The author's own short title is right there in the text of the subsequent
            # reference ("Adoption Act (n 2) s 24", "Maynard, above n 1"); read it rather
            # than relying on the model to have reported it.
            m = re.match(r"\s*\*?\s*(?P<title>[^*(]{1,80}?)\s*\*?\s*[,(]?\s*(?:\(\s*n\s*\d|above\s+n|supra)", seg.original)
            if m and m.group("title").strip().lower() not in {"ibid", "id"}:
                citation = citation.model_copy(update={"short_title": m.group("title").strip(" ,*")})

        ref_fn = resolved.get(ref)
        ref_citations = [s.citation for s in ref_fn.segments if isinstance(s, CitationSegment)] if ref_fn else []
        matches = _match_citations(ref_citations, citation.short_title)
        match = matches[0] if len(matches) == 1 else None
        if len(matches) > 1 and citation.short_title:
            self.warnings.append(
                f"footnote {footnote_number}: {citation.short_title!r} could mean any of "
                f"{len(matches)} sources cited in footnote {ref}; check it"
            )
        elif match is None and citation.short_title:
            found = _find_named(citation.short_title, resolved, before=footnote_number)
            if found is not None:
                number, match = found
                self.warnings.append(
                    f"footnote {footnote_number}: '(n {ref})' points to footnote "
                    f"{ref}, which doesn't cite {citation.short_title!r}; "
                    f"changed to footnote {number}, where it is cited"
                )
        if match is None:
            self.warnings.append(
                f"footnote {footnote_number}: could not resolve reference to footnote "
                f"{ref} ({seg.original!r}); recorded as an unclassified source"
            )
            fallback_text = seg.original or citation.short_title or f"(n {ref})"
            # the original text already contains its pinpoint (and any name), so don't emit
            # either twice: kept as written, it defines no short title
            return citation.model_copy(
                update={"source": OtherSource(text=fallback_text), "pinpoints": [], "pinpoint_judges": None,
                        "short_title": None}
            )

        source, short_title = match
        # the short title read from this reference's own text wins over the referenced one
        resolved_citation = citation.model_copy(
            update={"source": source, "short_title": citation.short_title or short_title}
        )
        return _keep_only_real_short_title(resolved_citation)
