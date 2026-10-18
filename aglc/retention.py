"""Deleting uploaded documents after $AGLC_RETENTION_HOURS (default 24, at least 1).

Runs when the server starts and then every few minutes (see `run_periodically`). It
deletes a session's whole folder: the uploaded input.docx, the output.docx and the saved
results. What counts as "after the window":

- Free (payments off) documents, in the temp directory: the folder is older than the window.
- Documents in $AGLC_DATA_DIR/sessions (payments on): the window runs from the *latest* of
    * the upload,
    * the newest checkout still pending: someone who is paying isn't cut off mid-checkout,
      and a checkout abandoned for a whole window no longer holds the document,
    * the payment: a paid document can be downloaded again for one more full window.
  Before a document with a pending checkout is deleted, the provider is asked whether it
  was paid after all (a lost webhook); if so it is unlocked and kept for a window.
  A payment that arrives after its document was deleted is refunded automatically, as for
  any document whose files are gone.

A deleted document's database row is kept, without its filename, with `purged_at` set: it
still counts towards today's free-use limits, its orders stay for the accounts, and asking
for it gets 410 Gone (no refund: it was paid for, downloaded or not, within the window).
Folders that aren't named like a session id are never touched.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.concurrency import run_in_threadpool

log = logging.getLogger("aglc")

DEFAULT_HOURS = 24.0
MIN_HOURS = 1.0  # documents are never deleted while they could still be processing


def retention_hours() -> float:
    try:
        hours = float(os.environ.get("AGLC_RETENTION_HOURS") or DEFAULT_HOURS)
    except ValueError:
        hours = DEFAULT_HOURS
    return max(MIN_HOURS, hours)


def sweep_interval() -> float:
    """Seconds between sweeps: a quarter of the window, between 1 minute and 1 hour."""
    return min(3600.0, max(60.0, retention_hours() * 3600 / 4))


def _is_session_dir(path: Path) -> bool:
    try:
        return path.is_dir() and str(uuid.UUID(path.name)) == path.name
    except ValueError:
        return False


def _older_than(path: Path, cutoff: float) -> bool:
    try:
        return path.stat().st_mtime < cutoff
    except OSError:
        return False


def sweep(temp_dir: Path | None, *, at: datetime | None = None) -> int:
    """Delete everything past the retention window; returns how many sessions were deleted."""
    at = at or datetime.now(timezone.utc)
    window = timedelta(hours=retention_hours())
    cutoff = at - window
    deleted = 0

    if temp_dir is not None and temp_dir.is_dir():
        for d in temp_dir.iterdir():
            if _is_session_dir(d) and _older_than(d, cutoff.timestamp()):
                shutil.rmtree(d, ignore_errors=True)
                deleted += 1

    from .store import data_dir

    sessions = data_dir() / "sessions"
    if sessions.is_dir():
        deleted += _sweep_paid(sessions, cutoff)
    if deleted:
        log.info("retention: deleted %d documents older than %g hours", deleted, retention_hours())
    return deleted


def _sweep_paid(sessions: Path, cutoff: datetime) -> int:
    from . import billing
    from .store import get_store

    store = get_store()
    stamp = cutoff.isoformat(timespec="seconds")
    deleted = 0
    for session_id, has_pending in store.expired_documents(stamp):
        if has_pending and billing.enabled():
            billing.reconcile_quietly(session_id)  # paid after all, webhook lost? then it's kept
        if store.purge_document(session_id, stamp):
            shutil.rmtree(sessions / session_id, ignore_errors=True)
            deleted += 1
            if has_pending and billing.enabled():
                billing.cancel_checkouts_quietly(session_id)
    # Folders with no live row: a crash mid-upload, or a purge whose delete failed.
    folders = [d for d in sessions.iterdir() if _is_session_dir(d)]
    purged = store.purged_states([d.name for d in folders])  # one query, not one per folder
    for d in folders:
        if (d.name not in purged and _older_than(d, cutoff.timestamp())) or purged.get(d.name):
            shutil.rmtree(d, ignore_errors=True)
            deleted += d.name not in purged
    return deleted


def sweep_safely(temp_dir: Path | None) -> None:
    try:
        sweep(temp_dir)
    except Exception:  # never let the sweeper take the server down; try again next time
        log.exception("retention sweep failed")


async def run_periodically(temp_dir: Path | None) -> None:
    """Sweep now, then every sweep_interval() seconds, until cancelled."""
    while True:
        t0 = time.monotonic()
        await run_in_threadpool(sweep_safely, temp_dir)
        await asyncio.sleep(max(1.0, sweep_interval() - (time.monotonic() - t0)))
