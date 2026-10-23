"""Problem reports: a student sends one footnote the tool got wrong, so it can be looked
into and added to the tests (POST /api/report/{id}, the "Report a problem" link on each
footnote; read them with `aglc reports`).

A report is built from the result saved on the server, not from what the page sends, so it
holds exactly what the tool produced: the footnote as written, the result, its notes and
changes, and what the AI model read in it. The student adds an optional comment. Reports
are kept apart from the documents, as one JSON file each in $AGLC_DATA_DIR/reports, and
deleted after $AGLC_REPORT_DAYS (default 90): long enough to fix the problem, and the
privacy page says so. Only the footnote reported is kept, never the rest of the essay.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .store import data_dir

log = logging.getLogger("aglc")

DEFAULT_DAYS = 90
MAX_PER_DOCUMENT = 20  # a document's reports, so one page can't fill the disk
MAX_COMMENT = 1000


class TooManyReports(Exception):
    pass


def report_days() -> float:
    try:
        return max(1.0, float(os.environ.get("AGLC_REPORT_DAYS") or DEFAULT_DAYS))
    except ValueError:
        return DEFAULT_DAYS


def reports_dir() -> Path:
    return data_dir() / "reports"


def save(session_dir: Path, session_id: str, footnote: int, comment: str | None = None, *,
         at: datetime | None = None) -> Path:
    """Report `footnote` of the document in `session_dir`. FileNotFoundError if the document
    has been deleted, LookupError if it has no such footnote, TooManyReports past the limit."""
    full = json.loads((session_dir / "result.json").read_text())
    fn = next((f for f in full["footnotes"] if f["number"] == footnote), None)
    if fn is None:
        raise LookupError(footnote)
    folder = reports_dir()
    folder.mkdir(parents=True, exist_ok=True)
    tag = session_id[:8]
    if len(list(folder.glob(f"*-{tag}-*.json"))) >= MAX_PER_DOCUMENT:
        raise TooManyReports(session_id)

    at = at or datetime.now(timezone.utc)
    report = {
        "created_at": at.isoformat(timespec="seconds"),
        "document": tag,  # enough to tell one document's reports apart, not to find the essay
        "footnote": footnote,
        "comment": (comment or "").strip()[:MAX_COMMENT] or None,
        "original": fn.get("original"),
        "formatted": fn.get("formatted"),
        "changed": fn.get("changed"),
        "changes": fn.get("changes") or [],
        "extraction_failed": fn.get("extraction_failed"),
        "warnings": [w["message"] for w in full.get("warnings", []) if w.get("footnote") == footnote],
        "cases": {kind: [c for c in (full.get("case_check") or {}).get(kind, []) if c.get("footnote") == footnote]
                  for kind in ("found", "unchecked")},
        "extraction": _extraction(session_dir, footnote),
        "model": _model(session_dir),
    }
    path = folder / f"{at:%Y%m%dT%H%M%S}-{tag}-{footnote}-{uuid.uuid4().hex[:6]}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    log.info("problem report %s saved", path.name)
    return path


def _extraction(session_dir: Path, footnote: int) -> list | None:
    """What the AI model read in the footnote: its segments, from extraction.json."""
    try:
        extraction = json.loads((session_dir / "extraction.json").read_text())
    except (OSError, ValueError):
        return None
    fn = next((f for f in extraction.get("footnotes", []) if f.get("number") == footnote), None)
    return fn.get("segments") if fn else None


def _model(session_dir: Path) -> str | None:
    try:
        return json.loads((session_dir / "options.json").read_text()).get("model")
    except (OSError, ValueError, AttributeError):
        return None


def load(limit: int | None = None) -> list[dict]:
    """The reports kept, newest first."""
    folder = reports_dir()
    paths = sorted(folder.glob("*.json"), reverse=True) if folder.is_dir() else []
    reports = []
    for path in paths[:limit]:
        try:
            reports.append({"file": path.name, **json.loads(path.read_text())})
        except (OSError, ValueError):
            continue
    return reports


def purge(at: datetime | None = None) -> int:
    """Delete reports older than report_days(); returns how many. Run by the retention sweep."""
    folder = reports_dir()
    if not folder.is_dir():
        return 0
    cutoff = ((at or datetime.now(timezone.utc)) - timedelta(days=report_days())).timestamp()
    deleted = 0
    for path in folder.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                deleted += 1
        except OSError:
            continue
    return deleted
