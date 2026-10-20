"""Live progress for a document being processed, so the page can show what is happening.

The pipeline reports events through a plain callback, `progress(kind, data)`:

    total    {"footnotes": 32}                    after the document is read
    writing  {"numbers": [16, 17]}                the model has started writing these (streamed)
    done     {"numbers": [16], "failed": False}   finished (failed: couldn't be read, kept as written)
    note     {"kind": "reask", ...}               what the tool is doing about a problem
    stage    {"name": "formatting"}               formatting | checking | writing_doc

`Jobs` keeps the latest state of each document being processed in the web app, which the
page polls (GET /api/progress/{id}). Only footnote numbers are kept, never their text.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("aglc")

Progress = Callable[[str, dict[str, Any]], None]


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
    #: when the counts last moved, so the page can say the model is slow
    changed: float = field(default_factory=time.time)
    finished: float | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None

    def update(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "total":
            self.total = int(data.get("footnotes", 0))
        elif kind == "writing":
            new = {int(n) for n in data.get("numbers", [])} - self.done - self.writing
            if new:
                self.writing |= new
                self.changed = time.time()
        elif kind == "done":
            numbers = {int(n) for n in data.get("numbers", [])}
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
