"""Live progress for a document being processed, so the page can show what is happening.

The pipeline reports events through a plain callback, `progress(kind, data)`:

    total    {"footnotes": 32, "texts": {1: "..."}}  after the document is read
    writing  {"numbers": [16, 17]}                  the model has started writing these (streamed)
    done     {"numbers": [16], "failed": False,     finished (failed: couldn't be read, kept as
              "found": {16: [...]}}                 written); found: see `found_in`
    note     {"kind": "reask", ...}                 what the tool is doing about a problem
    stage    {"name": "formatting"}                 formatting | checking | writing_doc

`Jobs` keeps the latest state of each document being processed in the web app, which the
page polls (GET /api/progress/{id}), so it can show each footnote as it is read. A footnote's
text is kept only in memory, with the job (see KEEP_FINISHED), and a snapshot carries only
the few footnotes the page is about to show.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("aglc")

Progress = Callable[[str, dict[str, Any]], None]

#: what the page calls each kind of source
SOURCE_LABELS = {
    "case": "Case", "legislation": "Legislation", "journal_article": "Article", "book": "Book",
    "book_chapter": "Book chapter", "report": "Report", "research_paper": "Research paper",
    "parliamentary_debates": "Hansard", "submission": "Submission", "committee_evidence": "Committee evidence",
    "convention_debates": "Convention debates", "explanatory_memorandum": "Explanatory memorandum",
    "newspaper": "Newspaper", "website": "Website", "treaty": "Treaty",
    "speech": "Speech", "media_release": "Media release", "dictionary": "Dictionary",
    "legal_encyclopedia": "Legal encyclopedia", "social_media": "Social media", "un_document": "UN document",
}
#: a footnote's text is cut to this many characters for the page
MAX_TEXT = 400


def footnote_texts(footnotes: Any) -> dict[int, dict[str, Any]]:
    """{number: {"text", "italic": [[start, end], ...]}} of `footnotes` (aglc.models.Footnote),
    cut to MAX_TEXT, for the total event. Italics carry meaning in a citation, so they go too."""
    out = {}
    for fn in footnotes:
        raw = fn.original.text
        lead = len(raw) - len(raw.lstrip())
        text = raw.strip()[:MAX_TEXT]
        italic, at = [], -lead
        for run in fn.original.runs:
            start, end = max(at, 0), min(at + len(run.text), len(text))
            if run.italic and start < end:
                italic.append([start, end])
            at += len(run.text)
        out[fn.number] = {"text": text, "italic": italic}
    return out


def found_in(footnote: Any) -> list[dict[str, str]]:
    """The citations read in `footnote` (aglc.models.Footnote): [{"kind": "Case", "text": the
    citation as written}], so the page can mark each one in the footnote's text. A source the
    model couldn't classify isn't listed."""
    found = []
    for seg in footnote.segments:
        if getattr(seg, "kind", None) != "citation":
            continue
        label = SOURCE_LABELS.get(seg.citation.source.type)
        if label:
            found.append({"kind": label, "text": seg.original.strip()[:MAX_TEXT]})
    return found


def safe(progress: Progress | None) -> Progress:
    """`progress`, or a no-op, wrapped so that a failing callback never breaks a run."""

    def call(kind: str, data: dict[str, Any]) -> None:
        if progress is None:
            return
        try:
            progress(kind, data)
        except Exception:  # noqa: BLE001 - progress is never worth failing a document over
            log.debug("progress callback failed", exc_info=True)

    return call


#: how long a finished document's state is kept for the page to collect, in seconds
KEEP_FINISHED = 600
#: notes kept for the page (the latest is shown)
MAX_NOTES = 5
#: footnotes read most recently, sent with every snapshot (a batch is 15)
RECENT = 20
#: footnotes not yet read, sent with every snapshot, so the page has one to show next
AHEAD = 3


@dataclass
class Job:
    started: float = field(default_factory=time.time)
    status: str = "processing"  # processing | done | failed
    total: int = 0
    done: set[int] = field(default_factory=set)
    failed: set[int] = field(default_factory=set)
    writing: set[int] = field(default_factory=set)
    stage: str = "reading"
    notes: list[dict[str, Any]] = field(default_factory=list)
    #: each footnote's text (see footnote_texts), and the citations read in it (see found_in)
    texts: dict[int, dict[str, Any]] = field(default_factory=dict)
    found: dict[int, list[dict[str, str]]] = field(default_factory=dict)
    #: footnotes in the order they were read
    order: list[int] = field(default_factory=list)
    #: when the counts last moved, so the page can say the model is slow
    changed: float = field(default_factory=time.time)
    finished: float | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def update(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "total":
            self.total = int(data.get("footnotes", 0))
            self.texts = {int(n): t for n, t in (data.get("texts") or {}).items()}
        elif kind == "writing":
            new = {int(n) for n in data.get("numbers", [])} - self.done - self.writing
            if new:
                self.writing |= new
                self.changed = time.time()
        elif kind == "done":
            numbers = {int(n) for n in data.get("numbers", [])}
            self.order += sorted(numbers - self.done)
            self.found.update({int(n): f for n, f in (data.get("found") or {}).items()})
            self.done |= numbers
            self.writing -= numbers
            if data.get("failed"):
                self.failed |= numbers
            else:
                self.failed -= numbers  # read on a later attempt
            self.changed = time.time()
        elif kind == "note":
            self.notes = (self.notes + [{**data, "at": time.time()}])[-MAX_NOTES:]
        elif kind == "stage":
            self.stage = str(data.get("name", self.stage))
            self.changed = time.time()

    def _showing(self) -> dict[int, dict[str, Any]]:
        """The footnotes the page may show next: those being written, the next few not yet
        read, and the most recently read (with the citations read in them)."""
        if not self.texts:
            return {}
        ahead = [n for n in sorted(self.texts) if n not in self.done][:AHEAD]
        numbers = set(self.writing - self.done) | set(ahead) | set(self.order[-RECENT:])
        out: dict[int, dict[str, Any]] = {}
        for n in sorted(numbers):
            entry: dict[str, Any] = dict(self.texts.get(n) or {"text": "", "italic": []})
            if n in self.done:
                entry["found"] = self.found.get(n, [])
            out[n] = entry
        return out

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        out: dict[str, Any] = {
            "status": self.status,
            "stage": self.stage,
            "total": self.total,
            "done": sorted(self.done),
            "failed": sorted(self.failed),
            "writing": sorted(self.writing - self.done),
            "notes": [{k: v for k, v in n.items() if k != "at"} | {"ago": round(now - n["at"], 1)}
                      for n in self.notes],
            "showing": self._showing(),
            "read": self.order[-RECENT:],
            # how many of each kind of source have been read, eg {"Case": 14}
            "kinds": dict(Counter(f["kind"] for found in self.found.values() for f in found)),
            "elapsed": round(now - self.started, 1),
            "idle": round(now - self.changed, 1),
        }
        if self.result is not None:
            out["result"] = self.result
        if self.error is not None:
            out["error"] = self.error
        return out


class Jobs:
    """Thread-safe store of the documents being processed (one web server process)."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, job_id: str) -> Progress:
        """Register a document and return the progress callback that updates it."""
        with self._lock:
            self._expire()
            self._jobs[job_id] = Job()

        def progress(kind: str, data: dict[str, Any]) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if job is not None:
                    job.update(kind, data)

        return progress

    def finish(self, job_id: str, *, result: dict[str, Any] | None = None, error: dict[str, Any] | None = None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "failed" if error is not None else "done"
            job.result, job.error = result, error
            job.finished = time.time()

    def snapshot(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._expire()
            job = self._jobs.get(job_id)
            return job.snapshot() if job is not None else None

    def _expire(self) -> None:
        cutoff = time.time() - KEEP_FINISHED
        for job_id in [j for j, job in self._jobs.items() if job.finished is not None and job.finished < cutoff]:
            del self._jobs[job_id]


jobs = Jobs()
