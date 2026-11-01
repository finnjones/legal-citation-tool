"""Pay per document, or with credits. Off unless $AGLC_PAYMENTS names a provider (`square`,
`stripe`, or `fake`).

When it is on, processing is free but returns a redacted preview (see `preview`): every
footnote's original and stamp, all warnings, how many corrections were found, and only the
first `preview_size` changed footnotes in full (a tenth of them, 1 to PREVIEW_FULL). The
full result is kept server-side; paying for the document unlocks it and the .docx
download. docs/paywall-audit.md lists every path checked for leaks.

Paying (by card or with credits) creates an entitlement: the paid document, its tier, its
fingerprint and FREE_RESCANS free re-scans for RESCAN_DAYS. The page is given a re-scan
token (POST /api/rescan-link/{session_id}; kept hashed). An upload that comes with it and
is mostly the same essay (AGLC_RESCAN_OVERLAP) is checked in full, unlocked, using one
re-scan; one that isn't gets the normal preview, with a note saying why. Documents paid for
before entitlements existed were given one by the migration and keep working.

What can be bought is in PRODUCTS (prices live there only): a document is an `essay` (up to
ESSAY_MAX_FOOTNOTES footnotes) or a `long` document (up to $AGLC_MAX_FOOTNOTES), chosen
here from its footnote count, never by the page; or a pack of credits (`pack3`, `pack10`)
with a redeem code (aglc/credits.py). An essay takes 1 credit, a long document 2. A pack
bought from a document's unlock screen unlocks that document with its first credits.

    GET  /api/config                    what the page needs to know (prices, payments on/off)
    POST /api/checkout {session_id?, product?}
                                        create a hosted checkout (a document's, or a pack's), return its URL
    POST /api/webhooks/{provider}       verified, deduplicated, applied in one transaction
    GET  /api/entitlement/{session_id}  unlocked yet? (asks the provider if the webhook is late);
                                        status unlocked | pending | refunded | expired | none
    GET  /api/results/{session_id}      the full result once unlocked, else the preview
    GET  /api/pack/latest               fallback: this browser's pack with a code waiting, else its newest paid one
    GET  /api/pack/{order_id}           a pack's status (its code only to the browser that bought it)
    POST /api/pack/{order_id}/received  the buyer's page has the code: forget it
    POST /api/redeem {session_id, code} unlock a document with credits
    POST /api/credits {code}            credits left on a code
    POST /api/rescan-link/{session_id}  a paid document's re-scan token (a new one each time)

Free processing is limited before any LLM call: per browser and per IP address per day,
a global daily cap, a footnote cap and a cap on concurrent jobs. If a paid document's
files have gone, the payment is refunded automatically.

One essay gets one free preview, whoever uploads it. Each upload is fingerprinted
(aglc/fingerprint.py) and, before any LLM call, compared with earlier free previews: a
match is a "seen" document. No model runs for it, though it counts as a free use. The
browser that made the earlier preview gets it again (the same footnotes in full); any other
browser, or once it has been deleted, a 409 built from the new upload alone, offering to
unlock: nothing of one student's essay is shown to another. A seen document can always be
paid for; payment unlocks a fresh run of the new upload (POST /api/run/{session_id}, in
aglc/api.py).

Nobody pays for footnotes the model failed to read. Failed footnotes are retried once
before the preview; if more than $AGLC_MAX_FAILED_SHARE of them (or a whole batch) still
failed, the document isn't `payable` and checkout refuses it (409) until a free re-run
(POST /api/rerun/{session_id}, MAX_RERUNS per document, paid or not) reads them.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from . import credits, fingerprint, mailer, pipeline, retention
from .docx_io import read_footnotes
from .models import Extraction, Footnote
from .payments import (
    PaymentError,
    Product,
    WebhookEvent,
    WebhookSignatureError,
    configured_payment_provider,
    get_payment_provider,
)
from .store import data_dir, get_store, now, today

log = logging.getLogger("aglc")

#: What can be bought. Prices live here only; the client never sends one.
PRODUCTS: dict[str, Product] = {
    "essay": Product(id="essay", name="AGLC4 citation check: one essay (up to 150 footnotes)", amount=500, currency="AUD"),
    "long": Product(id="long", name="AGLC4 citation check: one long document (151 to 400 footnotes)", amount=900,
                    currency="AUD"),
    "pack3": Product(id="pack3", name="AGLC4 citation check: 3 credits", amount=1200, currency="AUD"),
    "pack10": Product(id="pack10", name="AGLC4 citation check: 10 credits", amount=3500, currency="AUD"),
}
ESSAY_MAX_FOOTNOTES = 150  # an essay up to this many footnotes; a long document up to $AGLC_MAX_FOOTNOTES
TIER_CREDITS = {"essay": 1, "long": 2}  # credits a document of each tier takes
PACK_CREDITS = {"pack3": 3, "pack10": 10}

PREVIEW_FULL = 3  # at most this many changed footnotes are shown in full before paying,
PREVIEW_SHARE = 0.10  # ... a tenth of them, rounded up,
PREVIEW_MIN = 1  # ... and at least this many (see preview_size)
MAX_RERUNS = 2  # free re-runs of failed footnotes per document
ANON_COOKIE = "aglc_anon"
_REFUND_OUTCOMES = {"duplicate_payment", "files_missing"}


def enabled() -> bool:
    return configured_payment_provider() is not None


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


def sessions_dir() -> Path:
    """Where uploads and results are kept when payments are on (they must outlive /tmp)."""
    path = data_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_dir(session_id: str) -> Path:
    return sessions_dir() / session_id


def _files_present(session_id: str) -> bool:
    d = _session_dir(session_id)
    return (d / "output.docx").is_file() and (d / "result.json").is_file()


def _awaiting_run(doc: sqlite3.Row) -> bool:
    """A seen document not yet run: it is unlocked by paying, then run (POST /api/run)."""
    return doc["kind"] == "seen" and doc["status"] in ("seen", "processing")


def _can_deliver(doc: sqlite3.Row) -> bool:
    """Whether what a payment for this document buys is still on disk: the result, or for a
    seen document awaiting its run, the upload it will be run on."""
    if _awaiting_run(doc):
        return (_session_dir(doc["session_id"]) / "input.docx").is_file()
    return _files_present(doc["session_id"])


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def check_session_id(session_id: str) -> str:
    try:
        return str(uuid.UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid session ID") from None


def _require_enabled() -> None:
    if not enabled():
        raise HTTPException(status_code=404, detail="Payments are not enabled")


def max_footnotes() -> int:
    return _int_env("AGLC_MAX_FOOTNOTES", 400)


def tier_for(footnote_count: int) -> str:
    """The product a document of `footnote_count` footnotes is sold as."""
    return "essay" if footnote_count <= ESSAY_MAX_FOOTNOTES else "long"


def _price(product_id: str = "essay") -> dict:
    p = PRODUCTS[product_id]
    out = {"id": p.id, "amount": p.amount, "currency": p.currency, "display": p.display}
    if product_id in TIER_CREDITS:
        out["credits"] = TIER_CREDITS[product_id]
        out["max_footnotes"] = ESSAY_MAX_FOOTNOTES if product_id == "essay" else max_footnotes()
    else:
        out["credits"] = PACK_CREDITS[product_id]
    return out


def prices() -> dict[str, dict]:
    """Every product's price, for /api/config (the page renders prices from these)."""
    return {product_id: _price(product_id) for product_id in PRODUCTS}


# --------------------------------------------------------------------------- #
# Free-path limits (all checked before any LLM call)
# --------------------------------------------------------------------------- #


@dataclass
class Visitor:
    ip_hash: str | None
    anon_id: str
    new_cookie: bool


def _client_ip(request: Request) -> str | None:
    """$AGLC_CLIENT_IP_HEADER (eg CF-Connecting-IP) behind a reverse proxy, else the peer
    address (which uvicorn --proxy-headers takes from X-Forwarded-For). Only trustworthy when
    the proxy is the only way in: see DEPLOY.md.

    For X-Forwarded-For the *last* address is used: that is the one the nearest proxy
    added; anything before it was sent by the client and can be made up. An IPv6 address
    counts as its /64, since one connection is usually given a whole /64 to pick from."""
    header = os.environ.get("AGLC_CLIENT_IP_HEADER")
    ip = None
    if header and request.headers.get(header):
        ip = request.headers[header].split(",")[-1].strip()
    elif request.client:
        ip = request.client.host
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    mapped = getattr(addr, "ipv4_mapped", None)
    if addr.version == 6 and mapped is None:
        return str(ipaddress.ip_network(f"{addr}/64", strict=False))
    return str(mapped or addr)


def _visitor(request: Request) -> Visitor:
    anon = request.cookies.get(ANON_COOKIE) or ""
    new = not re.fullmatch(r"[0-9a-f]{32}", anon)
    if new:
        anon = secrets.token_hex(16)
    ip = _client_ip(request)
    ip_hash = None
    if ip:
        # Salted and rotated daily: counts uses today without keeping anyone's address.
        salt = os.environ.get("AGLC_IP_SALT") or get_store().secret("ip_salt")
        ip_hash = hashlib.sha256(f"{salt}:{today()}:{ip}".encode()).hexdigest()[:32]
    return Visitor(ip_hash=ip_hash, anon_id=anon, new_cookie=new)


def visitor_of(request: Request) -> Visitor:
    """Who is uploading (hashed), without the free-use check or the cookie: for a re-scan."""
    return _visitor(request)


def _free_limits() -> tuple[int, int, int]:
    """Today's free runs: (per IP, per browser, for everyone)."""
    per_browser = _int_env("AGLC_FREE_PER_DAY", 3)
    # One address is often a whole campus or household behind NAT, so it gets more headroom.
    per_ip = _int_env("AGLC_FREE_PER_IP_PER_DAY", per_browser * 5)
    return per_ip, per_browser, _int_env("AGLC_FREE_GLOBAL_PER_DAY", 300)


def _refuse(limit: str, per_browser: int) -> None:
    if limit == "global":
        raise HTTPException(429, "The free preview has reached today's limit. Please try again tomorrow.")
    raise HTTPException(429, f"You've used today's {per_browser} free previews. Please try again tomorrow.")


def admit(request: Request, response: Response) -> Visitor:
    """Refuse (429) a free run over today's limits; set the anonymous cookie. This is the
    early check, before the upload is read; `start_document` checks again as it records the run."""
    v = _visitor(request)
    per_ip, per_browser, global_cap = _free_limits()
    by_ip, by_browser, total = get_store().free_uses_today(ip_hash=v.ip_hash, anon_id=v.anon_id)
    if total >= global_cap:
        _refuse("global", per_browser)
    if by_browser >= per_browser or by_ip >= per_ip:
        _refuse("visitor", per_browser)
    if v.new_cookie:
        response.set_cookie(
            ANON_COOKIE, v.anon_id, max_age=365 * 86400, httponly=True, samesite="lax",
            secure=request.url.scheme == "https",
        )
    return v


def check_footnote_cap(docx_path: Path) -> int:
    """Count the footnotes (no LLM involved) and refuse (413) a document over the cap."""
    return len(read_capped(docx_path))


def read_capped(docx_path: Path) -> list[Footnote]:
    """The document's footnotes (no LLM involved), refusing (413) a document over the cap."""
    footnotes = read_footnotes(docx_path)
    cap = max_footnotes()
    if len(footnotes) > cap:
        raise HTTPException(413, f"This document has {len(footnotes)} footnotes; the limit is {cap}. "
                                 "Try splitting it into parts.")
    return footnotes


# --------------------------------------------------------------------------- #
# Fingerprints: one free preview per essay
# --------------------------------------------------------------------------- #

_sample_hash: dict[str, str] = {}


def fingerprint_of(footnotes: list[Footnote]) -> fingerprint.Fingerprint:
    key = get_store().secret("fingerprint_key")
    return fingerprint.compute([fn.original.text for fn in footnotes], key)


def _is_sample(fp: fingerprint.Fingerprint) -> bool:
    """The sample essay ("Try a sample essay") may be previewed by everyone."""
    from .site import SAMPLE_ESSAY

    key = get_store().secret("fingerprint_key")
    if key not in _sample_hash:
        try:
            _sample_hash[key] = fingerprint_of(read_footnotes(SAMPLE_ESSAY)).doc_hash
        except (OSError, ValueError, KeyError):
            _sample_hash[key] = ""
    return fp.doc_hash == _sample_hash[key]


@dataclass(frozen=True)
class Seen:
    """An upload matched an earlier free preview. `own`: the same browser uploaded that
    one, so it may be shown its preview again; nobody else ever is."""
    earlier: str
    own: bool


def seen_before(fp: fingerprint.Fingerprint, visitor: Visitor) -> Seen | None:
    """The earlier free preview this upload matches (see aglc/fingerprint.py), or None.
    The visitor's own earlier upload is preferred, one whose result is still kept first.
    Only the anonymous browser id decides "own", never the IP address: a campus or a
    household shares one."""
    share = fingerprint.seen_overlap()
    if share <= 0 or len(fp.hashes) < fingerprint.MIN_MATCHES or _is_sample(fp):
        return None
    store = get_store()
    # each candidate's count is how many of this upload's counted footnotes it shares
    hits = [sid for sid, shared in store.fingerprint_candidates(fp.hashes, fingerprint.MIN_MATCHES)
            if shared / len(fp.hashes) >= share]
    if not hits:
        return None
    for sid in hits:
        doc = store.document(sid)
        if doc is not None and visitor.anon_id and doc["anon_id"] == visitor.anon_id and _load_result(sid) is not None:
            return Seen(sid, own=True)
    return Seen(hits[0], own=False)


_semaphore: tuple[int, threading.BoundedSemaphore] | None = None
_semaphore_lock = threading.Lock()


@contextmanager
def processing_slot() -> Iterator[None]:
    """At most $AGLC_MAX_CONCURRENT documents in the pipeline at once; refuse (503) the rest."""
    global _semaphore
    size = max(1, _int_env("AGLC_MAX_CONCURRENT", 2))
    with _semaphore_lock:
        if _semaphore is None or _semaphore[0] != size:
            _semaphore = (size, threading.BoundedSemaphore(size))
        sem = _semaphore[1]
    if not sem.acquire(blocking=False):
        raise HTTPException(503, "The server is busy with other documents. Please try again in a minute.",
                            headers={"Retry-After": "30"})
    try:
        yield
    finally:
        sem.release()


# --------------------------------------------------------------------------- #
# Results: saved in full, previewed until paid for
# --------------------------------------------------------------------------- #


def extraction_report(full: dict) -> dict:
    """Which footnotes the model failed to read, and whether the document can be paid for."""
    failed = pipeline.failed_footnotes(full)
    total = len(full["footnotes"])
    too_many = len(failed) > _float_env("AGLC_MAX_FAILED_SHARE", 0.2) * total
    payable = not failed or not (too_many or pipeline.whole_batch_failed(full, total))
    return {"failed_footnotes": sorted(failed), "payable": payable}


def start_document(session_id: str, filename: str, visitor: Visitor, *, footnote_count: int = 0,
                   fp: fingerprint.Fingerprint | None = None) -> None:
    """Record a free run, refusing (429) one over today's limits. The check and the record
    are one transaction, so uploads at the same moment can't all pass `admit` and then
    all be recorded. Its fingerprint is kept, and found by later uploads once its preview
    is ready (save_result)."""
    limits = _free_limits()
    refused = get_store().add_document(session_id, filename, ip_hash=visitor.ip_hash, anon_id=visitor.anon_id,
                                       limits=limits, footnote_count=footnote_count)
    if refused:
        _refuse(refused, limits[1])
    if fp is not None:
        get_store().add_fingerprint(session_id, fp.doc_hash, fp.hashes)


SEEN_MESSAGE = "We've already checked this essay — unlock it to see every correction."
SEEN_ELSEWHERE = "An essay with these footnotes has already had its free preview. Unlock to see every correction."


def start_seen(session_id: str, filename: str, visitor: Visitor, *, footnote_count: int,
               fp: fingerprint.Fingerprint, seen: Seen, options: dict) -> dict:
    """Record an upload that matched an earlier free preview, with no model run. It counts
    against the free limits like any free upload (429 over them). The browser that made
    the earlier preview gets it again (the same footnotes in full) for this new session;
    anyone else, or once it has been deleted, a 409 built from the new upload alone,
    offering to unlock. Paying for it runs the new upload."""
    limits = _free_limits()
    refused = get_store().add_document(
        session_id, filename, ip_hash=visitor.ip_hash, anon_id=visitor.anon_id, limits=limits,
        footnote_count=footnote_count, kind="seen", status="seen", seen_of=seen.earlier, seen_shown=seen.own)
    if refused:
        _refuse(refused, limits[1])
    get_store().add_fingerprint(session_id, fp.doc_hash, fp.hashes)
    (_session_dir(session_id) / "options.json").write_text(json.dumps(options))
    log.info("document %s matches an earlier free preview (%s): no model run", session_id[:8],
             "the same browser's" if seen.own else "another browser's")
    return seen_view(get_store().document(session_id))


def seen_view(doc: sqlite3.Row) -> dict:
    """What a locked seen document shows: the earlier preview if the same browser made it
    (decided once, at upload), else a 409 offering to unlock that carries nothing but the
    new upload's own name and price."""
    tier = tier_for(doc["footnote_count"])
    earlier = _load_result(doc["seen_of"]) if doc["seen_of"] and doc["seen_shown"] else None
    if earlier is None:
        raise HTTPException(409, {
            "message": SEEN_ELSEWHERE, "seen": True, "session_id": doc["session_id"], "filename": doc["filename"],
            "tier": tier, "credits_needed": TIER_CREDITS[tier], "price": _price(tier),
        })
    shown = preview(earlier, footnote_count=doc["footnote_count"])
    return {**shown, "id": doc["session_id"], "filename": doc["filename"], "seen": True, "message": SEEN_MESSAGE,
            "failed_footnotes": [], "payable": True, "reruns_left": 0}


def claim_run(session_id: str) -> tuple[sqlite3.Row, dict]:
    """Start the paid run of a seen document: 402 until it is unlocked, 409 if it has no run
    waiting, and "running" (raised as 202) if it has started already. Returns the document
    and the options it was uploaded with."""
    store = get_store()
    doc = store.document(session_id)
    _require_not_purged(doc)
    if doc is None:
        raise HTTPException(404, "Session not found or expired")
    if not _awaiting_run(doc):
        raise HTTPException(409, "This document has already been checked.")
    if not doc["unlocked_at"]:
        raise HTTPException(402, "Unlock this document to check it in full.")
    if not store.set_status(session_id, "processing", expect="seen"):
        raise HTTPException(202, "running")
    try:
        options = json.loads((_session_dir(session_id) / "options.json").read_text())
    except (OSError, ValueError):
        options = {}
    return doc, options


def run_failed(session_id: str) -> None:
    """A paid run failed: it can be started again (the upload is kept)."""
    get_store().set_status(session_id, "seen", expect="processing")


# --------------------------------------------------------------------------- #
# Entitlements: a paid document, and its free re-scans
# --------------------------------------------------------------------------- #

FREE_RESCANS = 3  # free re-scans of a revised version of a paid document...
RESCAN_DAYS = 14  # ... for this many days after paying (separate from MAX_RERUNS)
DEFAULT_RESCAN_OVERLAP = 0.5  # $AGLC_RESCAN_OVERLAP: how like the paid document a re-scan must be


def rescan_overlap() -> float:
    return min(1.0, max(0.0, _float_env("AGLC_RESCAN_OVERLAP", DEFAULT_RESCAN_OVERLAP)))


def _token_hash(token: str) -> str:
    return hashlib.sha256(f"aforecite-rescan:{token}".encode()).hexdigest()


def _grant_entitlement(conn: sqlite3.Connection, session_id: str, source: str) -> str:
    """Record that `session_id` was paid for (in the caller's transaction, with the unlock).
    A document paid for again after a refund gets its entitlement back, fresh."""
    doc = conn.execute("SELECT footnote_count FROM documents WHERE session_id = ?", (session_id,)).fetchone()
    paid = datetime.now(timezone.utc)
    ent_id = uuid.uuid4().hex
    conn.execute(
        "INSERT INTO entitlements (id, session_id, tier, source, rescans_remaining, paid_at, expires_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET source = excluded.source,"
        " tier = excluded.tier, rescans_remaining = excluded.rescans_remaining, paid_at = excluded.paid_at,"
        " expires_at = excluded.expires_at, token_hash = NULL, revoked_at = NULL",
        (ent_id, session_id, tier_for(doc["footnote_count"]), source, FREE_RESCANS,
         paid.isoformat(timespec="seconds"), (paid + timedelta(days=RESCAN_DAYS)).isoformat(timespec="seconds")),
    )
    ent = conn.execute("SELECT id FROM entitlements WHERE session_id = ?", (session_id,)).fetchone()
    conn.execute("UPDATE documents SET entitlement_id = ? WHERE session_id = ?", (ent["id"], session_id))
    return ent["id"]


def _revoke_entitlement(conn: sqlite3.Connection, session_id: str) -> None:
    """The document's payment was refunded (or its files have gone): no more re-scans."""
    conn.execute("UPDATE entitlements SET rescans_remaining = 0, token_hash = NULL, revoked_at = ?"
                 " WHERE session_id = ? AND revoked_at IS NULL", (now(), session_id))


def _entitlement(conn: sqlite3.Connection, ent_id: str | None) -> sqlite3.Row | None:
    if not ent_id:
        return None
    return conn.execute("SELECT * FROM entitlements WHERE id = ?", (ent_id,)).fetchone()


def _active(ent: sqlite3.Row | None) -> bool:
    return ent is not None and not ent["revoked_at"] and ent["expires_at"] > now()


def _paid_groups(session_id: str, key: str) -> tuple[list[list[str]], bool] | None:
    """The paid document's fingerprint: for each counted footnote, its hash as written and
    (when the result is kept) as corrected, so a revision with the corrections accepted is
    still recognised. With whether it came from the full result. None if nothing is left."""
    full = _load_result(session_id)
    if full:
        groups = []
        for fn in full["footnotes"]:
            forms = [_plain(fn.get("original_html", ""))] + ([_plain(fn.get("formatted_html", ""))] if fn.get("changed") else [])
            group = list(dict.fromkeys(h for h in (fingerprint.footnote_hash(t, key) for t in forms) if h))
            if group:
                groups.append(group)
        return groups, True
    d = _session_dir(session_id)
    if (d / "input.docx").is_file():  # a seen document not yet run, or paid for before fingerprints
        try:
            texts = [fn.original.text for fn in read_footnotes(d / "input.docx")]
            return [[h] for h in (fingerprint.footnote_hash(t, key) for t in texts) if h], False
        except Exception:  # noqa: BLE001 - an old upload that can't be read just isn't recognised
            log.warning("couldn't fingerprint the earlier upload of %s", session_id[:8])
    hashes = get_store().fingerprint(session_id)
    return ([[h] for h in hashes], False) if hashes else None


def _groups(stored: str | None) -> list[list[str]]:
    """An entitlement's stored fingerprint as groups (a flat list is one hash per footnote)."""
    if not stored:
        return []
    return [g if isinstance(g, list) else [g] for g in json.loads(stored)]


def _plain(html: str) -> str:
    from html import unescape

    return unescape(re.sub(r"<[^>]+>", "", html))


def refresh_entitlement(ent_id: str | None, session_id: str) -> None:
    """Record the paid document's fingerprint on its entitlement, while its files are kept:
    from its full result once there is one (a seen document's paid run adds the corrected
    forms). Only the paid document itself: a re-scan never widens what later re-scans are
    measured against, so an entitlement can't drift to cover other essays."""
    if not ent_id:
        return
    with get_store().read() as conn:
        ent = _entitlement(conn, ent_id)
    if ent is None or ent["session_id"] != session_id or ent["revoked_at"]:
        return
    found = _paid_groups(session_id, get_store().secret("fingerprint_key"))
    if not found or (ent["fingerprint"] and not found[1]):
        return  # nothing better than what is stored
    with get_store().transaction() as conn:
        conn.execute("UPDATE entitlements SET fingerprint = ? WHERE id = ?", (json.dumps(found[0]), ent_id))


def rescan_info(ent: sqlite3.Row | None) -> dict | None:
    """What the page shows about a paid document's re-scans."""
    if ent is None:
        return None
    return {"remaining": ent["rescans_remaining"] if _active(ent) else 0, "total": FREE_RESCANS,
            "expires_at": ent["expires_at"], "tier": ent["tier"], "active": _active(ent) and ent["rescans_remaining"] > 0,
            "session_id": ent["session_id"]}


def new_rescan_token(session_id: str) -> dict:
    """Make the paid document's re-scan token (replacing any earlier one, which stops
    working): only its hash is kept, so it is shown this once. Whoever has the document's
    results link has the document itself, so may have its re-scans too."""
    _require_enabled()
    session_id = check_session_id(session_id)
    store = get_store()
    doc = store.document(session_id)
    _require_not_purged(doc)
    if doc is None or not doc["unlocked_at"]:
        raise HTTPException(402, "Unlock this document first.")
    token = secrets.token_urlsafe(24)
    with store.transaction() as conn:
        ent = conn.execute("SELECT * FROM entitlements WHERE session_id = ?", (session_id,)).fetchone()
        if not _active(ent):
            raise HTTPException(410, "This document's free re-scans have ended.")
        conn.execute("UPDATE entitlements SET token_hash = ? WHERE id = ?", (_token_hash(token), ent["id"]))
        ent = _entitlement(conn, ent["id"])
    refresh_entitlement(ent["id"], session_id)
    return {"token": token, "rescan": rescan_info(ent)}


@dataclass
class Rescan:
    """The outcome of trying to use re-scan tokens on an upload."""
    entitlement_id: str | None = None  # a re-scan to use
    note: str | None = None  # why it isn't one, for the page


def rescan_candidates(tokens: list[str] | None) -> list[sqlite3.Row]:
    """The usable entitlements among the tokens an upload came with (checked before the
    upload is read, so that a re-scan isn't held to the free limits)."""
    found = []
    with get_store().read() as conn:
        for token in (tokens or [])[:10]:
            if not token or len(token) > 100:
                continue
            ent = conn.execute("SELECT * FROM entitlements WHERE token_hash = ?", (_token_hash(token),)).fetchone()
            if ent is not None and ent["id"] not in {e["id"] for e in found}:
                found.append(ent)
    return found


def choose_rescan(candidates: list[sqlite3.Row], fp: fingerprint.Fingerprint, footnote_count: int) -> Rescan:
    """The entitlement whose paid document this upload is a revision of, if any
    (fingerprint.is_revision, with AGLC_RESCAN_OVERLAP): at least that share of the upload's
    counted footnotes (and 5) are the paid document's as written or corrected, at least that
    share of the paid document's are in the upload, and it adds no more new footnotes than
    half the paid document's. An essay-tier entitlement doesn't cover a version that has
    grown into a long document: that is a new purchase."""
    note = None
    for ent in candidates:
        if not _active(ent) or ent["rescans_remaining"] <= 0:
            note = note or (f"Your {FREE_RESCANS} free re-scans for that document have been used or have ended, so "
                            "this is checked as a new document.")
            continue
        if not ent["fingerprint"]:
            refresh_entitlement(ent["id"], ent["session_id"])
            with get_store().read() as conn:
                ent = _entitlement(conn, ent["id"])
        if not fingerprint.is_revision(fp.hashes, _groups(ent["fingerprint"]), rescan_overlap()):
            note = note or ("This looks like a different essay from the one you paid for, so it isn't a free "
                            "re-scan. Here is its free preview.")
            continue
        if ent["tier"] == "essay" and tier_for(footnote_count) == "long":
            note = (f"This version has more than {ESSAY_MAX_FOOTNOTES} footnotes, so it's a long document, which your "
                    "free re-scans (bought for an essay) don't cover. Unlock it as a new document to see every correction.")
            continue
        return Rescan(entitlement_id=ent["id"])
    return Rescan(note=note)


def start_rescan(session_id: str, filename: str, visitor: Visitor, *, footnote_count: int,
                 fp: fingerprint.Fingerprint, ent_id: str) -> None:
    """Record a re-scan, unlocked, using one of the entitlement's re-scans: the decrement and
    the record are one transaction, so re-scans at the same moment can't take more than
    are left. 429 if none are left after all."""
    with get_store().transaction() as conn:
        taken = conn.execute(
            "UPDATE entitlements SET rescans_remaining = rescans_remaining - 1"
            " WHERE id = ? AND rescans_remaining > 0 AND revoked_at IS NULL AND expires_at > ?",
            (ent_id, now()),
        ).rowcount == 1
        if not taken:
            raise HTTPException(429, f"The {FREE_RESCANS} free re-scans for that document have been used.")
        conn.execute(
            "INSERT INTO documents (session_id, filename, ip_hash, anon_id, day, created_at, footnote_count, kind,"
            " unlocked_at, unlocked_by, entitlement_id) VALUES (?, ?, ?, ?, ?, ?, ?, 'rescan', ?, ?, ?)",
            (session_id, filename, visitor.ip_hash, visitor.anon_id, today(), now(), footnote_count, now(),
             f"rescan:{ent_id}", ent_id),
        )
    get_store().add_fingerprint(session_id, fp.doc_hash, fp.hashes)
    log.info("document %s is a free re-scan", session_id[:8])


def _give_back_rescan(conn: sqlite3.Connection, ent_id: str) -> None:
    conn.execute("UPDATE entitlements SET rescans_remaining = MIN(?, rescans_remaining + 1) WHERE id = ?",
                 (FREE_RESCANS, ent_id))


def fail_document(session_id: str) -> None:
    """A run failed: it isn't a free use, and a re-scan's re-scan is given back."""
    store = get_store()
    store.finish_document(session_id, status="failed")
    doc = store.document(session_id)
    if doc is not None and doc["kind"] == "rescan" and doc["entitlement_id"]:
        with store.transaction() as conn:
            _give_back_rescan(conn, doc["entitlement_id"])
            conn.execute("UPDATE documents SET unlocked_at = NULL, unlocked_by = NULL WHERE session_id = ?",
                         (session_id,))


def write_result(session_dir: Path, filename: str, full: dict, *,
                 extraction: Extraction | None = None, options: dict | None = None) -> dict:
    """Write result.json, and extraction.json (the model's own answer) and options.json when
    given, next to the documents; the retention sweep deletes them with the folder. Free mode
    keeps them too, so a run can be looked into afterwards. Returns the result as saved."""
    full = {**full, "filename": filename}
    if extraction is not None:
        (session_dir / "extraction.json").write_text(extraction.model_dump_json())
    if options is not None:
        (session_dir / "options.json").write_text(json.dumps(options))
    (session_dir / "result.json").write_text(json.dumps(full))
    return full


def save_result(session_id: str, filename: str, full: dict, *,
                extraction: Extraction | None = None, options: dict | None = None) -> dict:
    """Keep the full result server-side (with what a re-run needs) and return what the page
    may see now."""
    full = write_result(_session_dir(session_id), filename, full, extraction=extraction, options=options)
    store = get_store()
    store.finish_document(session_id, status="ready", footnote_count=len(full["footnotes"]))
    doc = store.document(session_id)
    if doc["kind"] == "free" and not doc["unlocked_at"] and extraction_report(full)["payable"]:
        # A preview worth having: later uploads of the same essay get it again, not a new one.
        # (One the model mostly failed to read isn't, so the essay can be tried again.)
        store.index_fingerprint(session_id)
    if doc["unlocked_at"]:  # a paid run, re-run or re-scan: its corrections join the fingerprint
        refresh_entitlement(doc["entitlement_id"], session_id)
    return view(session_id, full)


def view(session_id: str, full: dict) -> dict:
    """The full result once unlocked, else the preview; with the extraction report."""
    store = get_store()
    doc = store.document(session_id)
    shown = {**full, "locked": False} if doc["unlocked_at"] else preview(full)
    out = {**shown, "id": session_id, **extraction_report(full), "reruns_left": max(0, MAX_RERUNS - doc["reruns"])}
    if doc["unlocked_at"]:
        with store.read() as conn:
            ent = _entitlement(conn, doc["entitlement_id"])
        if ent is not None and not ent["fingerprint"] and ent["session_id"] == session_id:
            refresh_entitlement(ent["id"], session_id)  # paid for before entitlements had one
        out["rescan"] = rescan_info(ent)
        out["rescanned"] = doc["kind"] == "rescan"
    return out


def _expired_message() -> str:
    return (f"This document was deleted {retention.retention_hours():g} hours after it was processed"
            " (or paid for), as our privacy policy says. Please process it again.")


def _require_not_purged(doc: sqlite3.Row | None) -> None:
    """410 for a document the retention sweep deleted (no refund: that's the policy)."""
    if doc is not None and doc["purged_at"]:
        raise HTTPException(410, _expired_message())


def rerun_inputs(session_id: str) -> tuple[dict, Extraction | None, dict]:
    """The saved result, extraction and processing options of a document (404 if gone)."""
    doc = get_store().document(session_id)
    _require_not_purged(doc)
    full = _load_result(session_id) if doc else None
    if full is None:
        raise HTTPException(404, "Session not found or expired")
    d = _session_dir(session_id)
    try:
        extraction = Extraction.model_validate_json((d / "extraction.json").read_text())
        options = json.loads((d / "options.json").read_text())
    except (OSError, ValueError):
        extraction, options = None, {}
    return full, extraction, options


def claim_rerun(session_id: str) -> None:
    if not get_store().claim_rerun(session_id, MAX_RERUNS):
        raise HTTPException(429, f"This document has had its {MAX_RERUNS} free re-reads. Please check it again later.")


def preview_size(changed: int) -> int:
    """How many changed footnotes a preview shows in full: a tenth of them rounded up, at
    least PREVIEW_MIN and at most PREVIEW_FULL, so a short essay can't be fixed whole for free."""
    return min(PREVIEW_FULL, max(PREVIEW_MIN, math.ceil(round(PREVIEW_SHARE * changed, 9))))


def preview(full: dict, *, footnote_count: int | None = None) -> dict:
    """What an unpaid page may see. Every footnote's original text and status, all warnings
    (they describe problems, never the corrected citation), how many corrections there are,
    and the corrected text of only the first `preview_size` changed footnotes: always the
    same ones for the same document. Withheld until paid for: every other correction (with
    its explanation), the bibliography's entries (counted), the body-text fixes that were
    made (counted; the checks left for the student are shown, like warnings), and the cases
    found or not checked on the footnotes that are locked (counted). No .docx. The price is
    for `footnote_count` footnotes (default: the result's own)."""
    tier = tier_for(len(full["footnotes"]) if footnote_count is None else footnote_count)
    changed = [fn["number"] for fn in full["footnotes"] if fn["changed"]]
    shown = set(changed[:preview_size(len(changed))])
    footnotes = []
    for fn in full["footnotes"]:
        if fn["changed"] and fn["number"] not in shown:
            footnotes.append({"number": fn["number"], "changed": True, "locked": True,
                              "original": fn["original"], "original_html": fn["original_html"]})
        else:
            footnotes.append(fn)
    visible = {fn["number"] for fn in footnotes if not fn.get("locked")}
    check = dict(full.get("case_check") or {})
    for key in ("found", "unchecked"):
        entries = check.get(key) or []
        check[key] = [e for e in entries if e["footnote"] in visible]
        check[f"{key}_locked"] = len(entries) - len(check[key])
    body_fixes = full.get("body_fixes") or []
    return {
        **full,
        "footnotes": footnotes,
        "bibliography": [],
        "bibliography_entries": sum(len(s["entries"]) for s in full["bibliography"]),
        "body_fixes": [b for b in body_fixes if b.get("applied") is False],
        "body_fixes_locked": sum(1 for b in body_fixes if b.get("applied") is not False),
        "case_check": check,
        "locked": True,
        "changed_count": len(changed),
        "preview_count": len(shown),
        "locked_count": len(changed) - len(shown),
        "tier": tier,
        "credits_needed": TIER_CREDITS[tier],
        "price": _price(tier),
    }


def _load_result(session_id: str) -> dict | None:
    path = _session_dir(session_id) / "result.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def require_unlocked(session_id: str) -> None:
    """Gate for the download: 402 until paid; refund (and 410) if a paid document's files are gone."""
    doc = get_store().document(session_id)
    if doc is None:
        raise HTTPException(404, "Session not found or output not ready")
    _require_not_purged(doc)
    if not doc["unlocked_at"]:
        price = PRODUCTS[tier_for(doc["footnote_count"])].display
        raise HTTPException(402, f"Unlock this document ({price}) to download it.")
    if _awaiting_run(doc):
        raise HTTPException(409, "This document is still being checked. Please wait for it to finish.")
    if not _files_present(session_id):
        _refund_missing(session_id)
        raise HTTPException(410, "This document's files are no longer available. Your payment has been refunded.")


# --------------------------------------------------------------------------- #
# Applying payments (shared by the webhook and the late-webhook reconcile)
# --------------------------------------------------------------------------- #

#: outcomes of a pack's payment being applied (its code was made: email it, show it once)
_PACK_OUTCOMES = {"pack_granted", "pack_unlocked"}


class _NotEnoughCredits(Exception):
    def __init__(self, cost: int) -> None:
        super().__init__(cost)
        self.cost = cost


def _unlockable(conn: sqlite3.Connection, session_id: str | None) -> bool:
    """Whether a pack bought from this document's unlock screen should unlock it now."""
    if not session_id:
        return False
    doc = conn.execute("SELECT * FROM documents WHERE session_id = ?", (session_id,)).fetchone()
    return doc is not None and not doc["unlocked_at"] and not doc["purged_at"] and _can_deliver(doc)


def _unlock_with_credits(conn: sqlite3.Connection, code_id: str, session_id: str) -> bool:
    """Spend the document's credits from `code_id` and unlock it, in the caller's transaction.
    False if the document is already unlocked (nothing is spent); _NotEnoughCredits if the
    code hasn't enough left (the caller's transaction must then be rolled back)."""
    doc = conn.execute("SELECT footnote_count FROM documents WHERE session_id = ?", (session_id,)).fetchone()
    cost = TIER_CREDITS[tier_for(doc["footnote_count"])]
    unlocked = conn.execute(
        "UPDATE documents SET unlocked_at = ?, unlocked_by = ? WHERE session_id = ? AND unlocked_at IS NULL",
        (now(), f"credit:{code_id}", session_id),
    ).rowcount == 1
    if not unlocked:
        return False
    if not credits.spend(conn, code_id, cost, session_id=session_id):
        raise _NotEnoughCredits(cost)
    _grant_entitlement(conn, session_id, f"credit:{code_id}")
    return True


def _settle(conn: sqlite3.Connection, order: sqlite3.Row, *, payment_id: str | None, amount: int, currency: str) -> str:
    """Mark `order` paid and unlock its document (or, for a pack, make its code and unlock
    the document it was bought from), inside the caller's transaction."""
    if amount != order["amount"] or currency.upper() != order["currency"]:
        log.error("order %s: paid %s %s, expected %s %s; not unlocking",
                  order["id"][:8], amount, currency, order["amount"], order["currency"])
        return "amount_mismatch"
    if order["status"] != "pending":
        return f"already_{order['status']}"
    store = get_store()
    store.update_order(order["id"], conn, status="paid", payment_id=payment_id, paid_at=now())
    if order["product"] in PACK_CREDITS:
        code_id, code = credits.grant(conn, order_id=order["id"], credits=PACK_CREDITS[order["product"]],
                                      payment_id=payment_id)
        conn.execute("INSERT INTO code_pickup (order_id, code, created_at) VALUES (?, ?, ?)", (order["id"], code, now()))
        # A pack is always worth at least one long document, so the new code has enough.
        if _unlockable(conn, order["session_id"]) and _unlock_with_credits(conn, code_id, order["session_id"]):
            return "pack_unlocked"
        return "pack_granted"  # bought on its own, or the document has gone: the credits are kept
    doc = conn.execute("SELECT * FROM documents WHERE session_id = ?", (order["session_id"],)).fetchone()
    if doc["unlocked_at"]:
        store.update_order(order["id"], conn, status="refunding", note="document was already paid for")
        return "duplicate_payment"
    if not _can_deliver(doc):
        store.update_order(order["id"], conn, status="refunding", note="document files missing")
        return "files_missing"
    conn.execute(
        "UPDATE documents SET unlocked_at = ?, unlocked_by = ? WHERE session_id = ?",
        (now(), order["id"], order["session_id"]),
    )
    _grant_entitlement(conn, order["session_id"], order["id"])
    return "unlocked"


def _mark_refunded(conn: sqlite3.Connection, order: sqlite3.Row, event: WebhookEvent | None = None) -> str:
    """A refund made at the provider (eg from its dashboard). A document is locked again by a
    full refund only; any refund of a pack removes its unspent credits (documents it has
    already unlocked stay unlocked)."""
    if order["status"] == "refunded":
        return "already_refunded"
    is_pack = order["product"] in PACK_CREDITS
    # A refund is full only if the provider says so and it covers the order: Square reports each
    # refund's own amount, with no flag, so a partial one is told apart here.
    full = event is None or (event.full and (event.amount <= 0 or event.amount >= order["amount"]))
    if not full and not is_pack:
        return "partial_refund"
    get_store().update_order(order["id"], conn, status="refunded", refunded_at=now())
    if is_pack:
        removed = credits.revoke(conn, order["id"], payment_id=order["payment_id"])
        log.info("pack order %s refunded: %s unspent credits removed", order["id"][:8], removed or 0)
        return "pack_refunded"
    locked = conn.execute(
        "UPDATE documents SET unlocked_at = NULL, unlocked_by = NULL, entitlement_id = NULL"
        " WHERE session_id = ? AND unlocked_by = ?",
        (order["session_id"], order["id"]),
    ).rowcount
    if locked:
        _revoke_entitlement(conn, order["session_id"])
    return "refunded"


def apply_event(provider: str, event: WebhookEvent) -> tuple[str, str | None]:
    """Record and apply a verified webhook in one transaction. Returns (outcome, order id);
    a replayed event id is a no-op."""
    with get_store().transaction() as conn:
        inserted = conn.execute(
            "INSERT OR IGNORE INTO webhook_events (event_id, provider, type, outcome, received_at)"
            " VALUES (?, ?, ?, 'received', ?)",
            (event.event_id, provider, event.type, now()),
        ).rowcount
        if not inserted:
            return "duplicate", None
        order = None
        if event.provider_order_id:
            order = conn.execute(
                "SELECT * FROM orders WHERE provider = ? AND provider_order_id = ?",
                (provider, event.provider_order_id),
            ).fetchone()
        if event.status == "ignored":
            outcome = "ignored"
        elif order is None:
            outcome = "unknown_order"
        elif event.status == "paid":
            outcome = _settle(conn, order, payment_id=event.payment_id, amount=event.amount, currency=event.currency)
        else:
            outcome = _mark_refunded(conn, order, event)
        order_id = order["id"] if order else None
        conn.execute("UPDATE webhook_events SET outcome = ?, order_id = ? WHERE event_id = ?",
                     (outcome, order_id, event.event_id))
    log.info("webhook %s %s: %s (order %s)", provider, event.type, outcome, order_id and order_id[:8])
    return outcome, order_id


def after_payment(outcome: str, order_id: str | None, email: str | None) -> None:
    """What follows a payment being applied, outside its transaction: a refund it called for,
    or a new pack's code emailed (once) to the address the checkout collected."""
    if not order_id:
        return
    if outcome in _REFUND_OUTCOMES:
        _refund(order_id)
        return
    if outcome in ("unlocked", "pack_unlocked"):  # the paid document's fingerprint, for re-scans
        order = get_store().order(order_id)
        doc = get_store().document(order["session_id"])
        refresh_entitlement(doc["entitlement_id"], order["session_id"])
    if outcome in _PACK_OUTCOMES and email:
        _email_code(order_id, email)


def _email_code(order_id: str, email: str) -> None:
    store = get_store()
    with store.read() as conn:
        row = conn.execute(
            "SELECT p.code, c.credits_total FROM code_pickup p JOIN credit_codes c ON c.order_id = p.order_id"
            " WHERE p.order_id = ?", (order_id,),
        ).fetchone()
    if row is None:
        return  # already collected by the buyer's page (and forgotten), or refunded
    n = row["credits_total"]
    sent = mailer.send_quietly(mailer.Message(
        to=email,
        subject="Your Aforecite credits code",
        text=(f"Thanks for buying {n} credits.\n\nYour code: {row['code']}\n\n"
              "Keep this email: the code is how you use your credits, and we can't show it to you again. "
              f"An essay (up to {ESSAY_MAX_FOOTNOTES} footnotes) uses 1 credit and a longer document 2. "
              "Credits don't expire.\n\n"
              "To use one, check a document, then choose \"Use a credit\" and enter the code.\n"),
    ))
    if sent:
        with store.transaction() as conn:
            conn.execute("UPDATE code_pickup SET emailed = 1 WHERE order_id = ?", (order_id,))


def _refund(order_id: str) -> None:
    """Refund an order that _settle marked `refunding`. Claiming that status in the
    transaction makes sure only one caller refunds it."""
    store = get_store()
    order = store.order(order_id)
    if order is None or order["status"] != "refunding" or not order["payment_id"]:
        return
    try:
        refund = get_payment_provider(order["provider"]).refund(
            payment_id=order["payment_id"], amount=order["amount"], currency=order["currency"],
            reason=f"Automatic refund: {order['note'] or 'document unavailable'}",
            idempotency_key=f"refund-{order_id}",
        )
    except PaymentError as e:
        log.error("automatic refund of order %s failed: %s", order_id[:8], e)
        store.update_order(order_id, status="refund_failed", note=f"{order['note']}; refund failed: {e}")
        return
    log.warning("refunded order %s: %s", order_id[:8], order["note"])
    store.update_order(order_id, status="refunded", refund_id=refund.refund_id, refunded_at=now())


def _refund_missing(session_id: str) -> None:
    """The document was paid for but its files are gone: lock it, and refund the payment
    (or give back the credits spent on it)."""
    store = get_store()
    order_id = None
    with store.transaction() as conn:
        doc = conn.execute("SELECT unlocked_by FROM documents WHERE session_id = ?", (session_id,)).fetchone()
        unlocked_by = doc["unlocked_by"] if doc else None
        if unlocked_by:
            conn.execute("UPDATE documents SET unlocked_at = NULL, unlocked_by = NULL, entitlement_id = NULL"
                         " WHERE session_id = ?", (session_id,))
        if unlocked_by and unlocked_by.startswith("rescan:"):
            _give_back_rescan(conn, unlocked_by.removeprefix("rescan:"))
            unlocked_by = None
        elif unlocked_by:
            _revoke_entitlement(conn, session_id)
        if unlocked_by and unlocked_by.startswith("credit:"):
            credits.give_back(conn, unlocked_by.removeprefix("credit:"), session_id)
        elif unlocked_by:
            order_id = unlocked_by
            conn.execute(
                "UPDATE orders SET status = 'refunding', note = 'document files missing', updated_at = ?"
                " WHERE id = ? AND status = 'paid'",
                (now(), order_id),
            )
    if order_id:
        _refund(order_id)


_last_checked: dict[str, float] = {}
RECONCILE_INTERVAL = 2.0  # seconds between asking the provider about one order


def _reconcile_order(order: sqlite3.Row) -> str | None:
    """The webhook is late: ask the provider directly about this pending order. Returns the
    outcome of applying it, or None if it isn't paid (or was asked about a moment ago)."""
    if order["status"] != "pending" or not order["provider_order_id"]:
        return None
    if time.monotonic() - _last_checked.get(order["id"], -1e9) < RECONCILE_INTERVAL:
        return None
    _last_checked[order["id"]] = time.monotonic()
    try:
        status = get_payment_provider(order["provider"]).retrieve(order["provider_order_id"])
    except PaymentError as e:
        log.warning("could not check order %s: %s", order["id"][:8], e)
        return None
    if not status.paid:
        return None
    with get_store().transaction() as conn:
        fresh = conn.execute("SELECT * FROM orders WHERE id = ?", (order["id"],)).fetchone()
        outcome = _settle(conn, fresh, payment_id=status.payment_id, amount=status.amount, currency=status.currency)
    log.info("reconciled order %s: %s", order["id"][:8], outcome)
    after_payment(outcome, order["id"], status.email)
    return outcome


def _reconcile(session_id: str) -> None:
    """The webhook is late: ask the provider directly about this document's pending orders."""
    for order in get_store().orders_for(session_id):
        _reconcile_order(order)


def cancel_checkouts_quietly(session_id: str) -> None:
    """For the retention sweep, after deleting a document: stop its unpaid checkouts taking
    payment. Orders are left as they are, so a payment that still arrives is refunded."""
    for order in get_store().orders_for(session_id):
        if order["status"] == "pending" and order["checkout_id"]:
            try:
                get_payment_provider(order["provider"]).cancel_checkout(order["checkout_id"])
            except Exception:
                log.warning("could not cancel the checkout of a deleted document's order %s", order["id"][:8])


def reconcile_quietly(session_id: str) -> None:
    """_reconcile for the retention sweep, which must carry on whatever the provider says."""
    try:
        _reconcile(session_id)
    except Exception:
        log.exception("could not check the pending orders of a document before deleting it")


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

router = APIRouter()


@router.get("/api/config")
async def get_config() -> dict:
    # retention_hours: how long uploads and results are kept (quoted by the privacy page)
    if not enabled():
        return {"payments": False, "retention_hours": retention.retention_hours()}
    return {
        "payments": True,
        "retention_hours": retention.retention_hours(),
        "provider": configured_payment_provider(),
        "price": _price("essay"),
        "prices": prices(),  # every product: the page renders prices from these, never its own
        "essay_max_footnotes": ESSAY_MAX_FOOTNOTES,
        "max_footnotes": max_footnotes(),
        "preview_footnotes": PREVIEW_FULL,  # the most a preview shows in full (preview_size)
        "preview_share": PREVIEW_SHARE,
        "email_codes": mailer.enabled(),  # whether a pack's code is also emailed
        "free_rescans": FREE_RESCANS,
        "rescan_days": RESCAN_DAYS,
    }


class CheckoutRequest(BaseModel):
    session_id: str | None = None
    #: a pack (`pack3`, `pack10`); omitted, or a document's tier, means "this document", whose
    #: tier is chosen here from its footnote count whatever the page asks for
    product: str | None = None


def _public_base(request: Request) -> str:
    return (os.environ.get("AGLC_PUBLIC_URL") or str(request.base_url)).rstrip("/")


CHECKOUT_LAPSE_MARGIN = 300  # seconds: a checkout this close to lapsing isn't offered again


def _checkout_lapsed(order: sqlite3.Row) -> bool:
    """Has this pending order's checkout (nearly) lapsed, so that it shouldn't be offered again?
    The order stays pending, so a payment made at the last minute is still applied."""
    try:
        lifetime = get_payment_provider(order["provider"]).checkout_lifetime
    except (PaymentError, ValueError):
        return False
    if not lifetime:
        return False
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(order["created_at"])).total_seconds()
    return age > lifetime - CHECKOUT_LAPSE_MARGIN


def _payable_document(session_id: str) -> sqlite3.Row:
    """The document a checkout or a credit is for: 404/410/409 unless it can be unlocked now."""
    doc = get_store().document(session_id)
    _require_not_purged(doc)
    if doc is None or (doc["status"] != "ready" and not _awaiting_run(doc)):
        raise HTTPException(404, "Session not found or output not ready")
    if not doc["unlocked_at"] and not _can_deliver(doc):
        raise HTTPException(410, "This document has expired. Please process it again.")
    if not doc["unlocked_at"] and not _awaiting_run(doc) and not extraction_report(_load_result(session_id))["payable"]:
        raise HTTPException(409, "Some footnotes couldn't be read. Re-run them (free) before unlocking.")
    return doc


@router.post("/api/checkout")
def create_checkout(body: CheckoutRequest, request: Request, response: Response) -> dict:
    _require_enabled()
    store = get_store()
    is_pack = body.product in PACK_CREDITS
    if body.product is not None and body.product not in PRODUCTS:
        raise HTTPException(422, "Unknown product")
    session_id = check_session_id(body.session_id) if body.session_id else None
    if session_id is None and not is_pack:
        raise HTTPException(422, "Which document?")
    doc = _payable_document(session_id) if session_id else None
    if doc is not None and doc["unlocked_at"] and not is_pack:
        return {"unlocked": True}
    if doc is not None and doc["unlocked_at"]:
        session_id = None  # a pack bought from an unlocked document's page: just the credits

    product = PRODUCTS[body.product] if is_pack else PRODUCTS[tier_for(doc["footnote_count"])]
    if session_id:  # don't make a second link for the same document and product
        for order in store.orders_for(session_id):
            if (order["status"] == "pending" and order["product"] == product.id and order["checkout_url"]
                    and not _checkout_lapsed(order)):
                store.update_order(order["id"])  # touched: the retention window runs from the latest checkout
                return {"checkout_url": order["checkout_url"], "order_id": order["id"]}

    provider = get_payment_provider()
    order_id = uuid.uuid4().hex
    buyer = _buyer(request, response) if is_pack else None
    store.add_order(order_id, session_id, product=product.id, amount=product.amount,
                    currency=product.currency, provider=provider.name, buyer_anon=buyer)
    back = f"{_public_base(request)}/?paid=1"
    # A pack's order id is in the return URL so the page asks about the pack that was paid
    # for. That is safe: only the buying browser's cookie collects the code, the logs keep 8
    # characters of it, and the page removes it from the URL before analytics loads.
    redirect = (f"{back}&session={session_id}" if session_id else back) + (f"&pack={order_id}" if is_pack else "")
    try:
        session = provider.create_checkout(order_id=order_id, product=product, redirect_url=redirect)
    except PaymentError as e:
        log.error("checkout for order %s failed: %s", order_id[:8], e)
        store.update_order(order_id, status="failed", note=str(e))
        raise HTTPException(502, "The payment provider is unavailable. Please try again shortly.") from e
    store.update_order(order_id, checkout_id=session.checkout_id, checkout_url=session.url,
                       provider_order_id=session.provider_order_id)
    return {"checkout_url": session.url, "order_id": order_id}


@router.post("/api/webhooks/{provider}")
async def receive_webhook(provider: str, request: Request) -> dict:
    _require_enabled()
    if provider != configured_payment_provider():
        raise HTTPException(404, "Unknown payment provider")
    body = await request.body()  # raw bytes: the signature covers them exactly
    try:
        event = get_payment_provider().parse_webhook(body=body, headers=request.headers, url=str(request.url))
    except WebhookSignatureError as e:
        log.warning("rejected %s webhook: %s", provider, e)
        raise HTTPException(400, "Invalid webhook signature") from e
    if not event.event_id:
        raise HTTPException(400, "Webhook has no event id")
    outcome, order_id = await run_in_threadpool(apply_event, provider, event)
    await run_in_threadpool(after_payment, outcome, order_id, event.email)
    return {"ok": True, "outcome": outcome}


@router.get("/api/entitlement/{session_id}")
def get_entitlement(session_id: str) -> dict:
    _require_enabled()
    session_id = check_session_id(session_id)
    store = get_store()
    doc = store.document(session_id)
    if doc is None:
        raise HTTPException(404, "Session not found")
    if not doc["unlocked_at"]:
        _reconcile(session_id)
        doc = store.document(session_id)
    statuses = {o["status"] for o in store.orders_for(session_id)}
    refunded = bool(statuses & {"refunding", "refunded", "refund_failed"})
    if doc["purged_at"]:  # deleted by the retention sweep: nothing left to unlock or download
        status = "refunded" if refunded else "expired"
        return {"session_id": session_id, "unlocked": False, "status": status}
    if doc["unlocked_at"]:
        status = "unlocked"
    elif "pending" in statuses:
        status = "pending"
    elif refunded:
        status = "refunded"
    else:
        status = "none"
    return {"session_id": session_id, "unlocked": bool(doc["unlocked_at"]), "status": status}


@router.get("/api/results/{session_id}")
def get_results(session_id: str) -> dict:
    _require_enabled()
    session_id = check_session_id(session_id)
    doc = get_store().document(session_id)
    _require_not_purged(doc)
    if doc is not None and _awaiting_run(doc):
        if not doc["unlocked_at"]:
            return seen_view(doc)
        if not _can_deliver(doc):
            _refund_missing(session_id)
            raise HTTPException(410, "This document's files are no longer available. Your payment has been refunded.")
        # paid for, not yet run: the page starts the run (POST /api/run/{id})
        return {"id": session_id, "filename": doc["filename"], "locked": False, "needs_run": True,
                "running": doc["status"] == "processing", "footnotes": []}
    full = _load_result(session_id) if doc else None
    if doc is None or (full is None and not doc["unlocked_at"]):
        raise HTTPException(404, "Session not found or expired")
    if doc["unlocked_at"] and not _files_present(session_id):
        _refund_missing(session_id)
        raise HTTPException(410, "This document's files are no longer available. Your payment has been refunded.")
    return view(session_id, full)


# ---- Credit packs ------------------------------------------------------------- #


def _buyer(request: Request, response: Response) -> str:
    """The browser's anonymous id (set now if it has none): a pack's code goes only to it."""
    v = _visitor(request)
    if v.new_cookie:
        response.set_cookie(ANON_COOKIE, v.anon_id, max_age=365 * 86400, httponly=True, samesite="lax",
                            secure=request.url.scheme == "https")
    return v.anon_id


def _is_buyer(request: Request, order: sqlite3.Row) -> bool:
    anon = request.cookies.get(ANON_COOKIE) or ""
    return bool(order["buyer_anon"]) and secrets.compare_digest(anon, order["buyer_anon"])


def _code_balance(conn: sqlite3.Connection, code_row: sqlite3.Row | None) -> int:
    return code_row["credits_remaining"] if code_row is not None and not code_row["revoked_at"] else 0


def _pack_order(order_id: str) -> sqlite3.Row:
    if not re.fullmatch(r"[0-9a-f]{32}", order_id):
        raise HTTPException(404, "Unknown order")
    order = get_store().order(order_id)
    if order is None or order["product"] not in PACK_CREDITS:
        raise HTTPException(404, "Unknown order")
    return order


@router.get("/api/pack/latest")
def get_latest_pack(request: Request) -> dict:
    """A fallback for a page that has lost its pack's order id: this browser's newest pack
    with a code still waiting, else its newest paid one, else its newest."""
    _require_enabled()
    order = get_store().latest_pack_order(request.cookies.get(ANON_COOKIE) or "") if request.cookies.get(
        ANON_COOKIE) else None
    if order is None:
        raise HTTPException(404, "No pack bought in this browser")
    return get_pack(order["id"], request)


@router.get("/api/pack/{order_id}")
def get_pack(order_id: str, request: Request) -> dict:
    """A pack's order: `pending` (asks the provider if the webhook is late), `paid` or
    `refunded`. To the browser that bought it, once paid, it carries the code until that
    page confirms it has it (POST .../received), which is then forgotten; anyone else gets
    the status only. `emailed` says whether it was also emailed to the checkout's address."""
    _require_enabled()
    store = get_store()
    order = _pack_order(order_id)
    if order["status"] == "pending":
        _reconcile_order(order)
        order = store.order(order_id)
    buyer = _is_buyer(request, order)
    out: dict = {"order_id": order_id, "status": order["status"], "credits": PACK_CREDITS[order["product"]],
                 "email_enabled": mailer.enabled()}
    if buyer:  # the document a pack unlocked is the buyer's to know: its id opens the full result
        out["session_id"] = order["session_id"]
    if order["status"] not in ("paid", "refunded"):
        return out
    with store.read() as conn:
        pickup = conn.execute("SELECT code, emailed FROM code_pickup WHERE order_id = ?", (order_id,)).fetchone()
        row = conn.execute("SELECT * FROM credit_codes WHERE order_id = ?", (order_id,)).fetchone()
        out["credits_remaining"] = _code_balance(conn, row)
    if pickup is not None:
        out["emailed"] = bool(pickup["emailed"])
        if buyer:
            out["code"] = pickup["code"]
        else:
            out["code_elsewhere"] = True  # held for the browser that bought it
    if buyer and order["session_id"]:
        doc = store.document(order["session_id"])
        out["unlocked"] = bool(doc and doc["unlocked_at"] and doc["unlocked_by"] == f"credit:{row['id'] if row else ''}")
    return out


@router.post("/api/pack/{order_id}/received")
def pack_received(order_id: str, request: Request) -> dict:
    """The buyer's page has shown and kept the code: forget it (only the hash stays)."""
    _require_enabled()
    order = _pack_order(order_id)
    if not _is_buyer(request, order):
        raise HTTPException(403, "Only the browser that bought this pack can do that.")
    with get_store().transaction() as conn:
        deleted = conn.execute("DELETE FROM code_pickup WHERE order_id = ?", (order_id,)).rowcount
    if deleted:
        get_store().scrub_wal()
    return {"ok": True}


def reissue_code(order_id: str) -> tuple[str, int]:
    """For an operator (`aglc reissue-code`): give a paid pack a new code, with the credits
    its old one had left; the old code stops working. Returns (the new code, credits)."""
    with get_store().transaction() as conn:
        row = conn.execute("SELECT * FROM credit_codes WHERE order_id = ?", (order_id,)).fetchone()
        if row is None:
            raise LookupError("That order has no code (not a paid pack?)")
        if row["revoked_at"]:
            raise LookupError("That pack was refunded")
        code = credits.reissue(conn, row["id"])
        conn.execute("DELETE FROM code_pickup WHERE order_id = ?", (order_id,))
    get_store().scrub_wal()
    log.info("pack order %s: code reissued", order_id[:8])
    return code, row["credits_remaining"]


class CodeRequest(BaseModel):
    code: str


class RedeemRequest(BaseModel):
    session_id: str
    code: str


_BAD_CODE = "That code isn't one of ours. Check it and try again."


@router.post("/api/credits")
def get_credits(body: CodeRequest) -> dict:
    """Credits left on a code (POSTed, so the code stays out of URLs and logs)."""
    _require_enabled()
    with get_store().read() as conn:
        row = credits.find(conn, body.code)
        if row is None:
            raise HTTPException(404, _BAD_CODE)
        return {"credits_remaining": _code_balance(conn, row), "refunded": bool(row["revoked_at"])}


@router.post("/api/redeem")
def redeem(body: RedeemRequest) -> dict:
    """Unlock a document with credits: 1 for an essay, 2 for a long document. The spend and
    the unlock are one transaction, so a code can't be spent twice at once or go below zero,
    and a document already unlocked costs nothing."""
    _require_enabled()
    session_id = check_session_id(body.session_id)
    if credits.normalise(body.code) is None:
        raise HTTPException(400, "That doesn't look like a code. Codes look like AFC-XXXX-XXXX-XXXX.")
    doc = _payable_document(session_id)
    cost = TIER_CREDITS[tier_for(doc["footnote_count"])]
    try:
        with get_store().transaction() as conn:
            row = credits.find(conn, body.code)
            if row is None:
                raise HTTPException(404, _BAD_CODE)
            if row["revoked_at"]:
                raise HTTPException(402, "That code's pack was refunded, so it has no credits left.")
            spent = _unlock_with_credits(conn, row["id"], session_id)
            left = conn.execute("SELECT credits_remaining FROM credit_codes WHERE id = ?", (row["id"],)).fetchone()[0]
    except _NotEnoughCredits as e:
        raise HTTPException(402, f"This document needs {e.cost} credit{'s' if e.cost > 1 else ''}, and that code "
                                 "hasn't enough left.") from None
    if spent:
        log.info("document %s unlocked with %d credits", session_id[:8], cost)
        refresh_entitlement(get_store().document(session_id)["entitlement_id"], session_id)
    return {"unlocked": True, "credits_spent": cost if spent else 0, "credits_remaining": left}


@router.post("/api/rescan-link/{session_id}")
def rescan_link(session_id: str) -> dict:
    """A new re-scan token for a paid document (the old one stops working)."""
    return new_rescan_token(session_id)


# ---- Stand-in checkout page for AGLC_PAYMENTS=fake (local demos and tests) -- #


def _fake_checkout(provider_order_id: str):
    if configured_payment_provider() != "fake":
        raise HTTPException(404, "Not found")
    provider = get_payment_provider()
    checkout = provider.checkouts.get(provider_order_id)
    if checkout is None:
        raise HTTPException(404, "Unknown checkout")
    return provider, checkout


@router.get("/api/fake-checkout/{provider_order_id}", response_class=HTMLResponse)
def fake_checkout_page(provider_order_id: str) -> str:
    _, c = _fake_checkout(provider_order_id)
    cancel = c.redirect_url.replace("paid=1&", "")
    action = f"/api/fake-checkout/{escape(provider_order_id)}/pay"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Test checkout</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;max-width:28rem;margin:10vh auto;padding:0 16px;color:#222;background:#f4f4f2}}
.card{{background:#fff;border-radius:6px;padding:24px;box-shadow:0 2px 10px #0002}}button{{font:inherit;padding:10px 16px;border-radius:4px;border:1px solid #222;cursor:pointer}}
.pay{{background:#222;color:#fff}}form{{display:inline}}p.small{{font-size:14px;color:#666}}</style></head>
<body><div class="card"><h1 style="font-size:20px">Test checkout</h1>
<p>{escape(c.product.name)}: <strong>{escape(c.product.display)}</strong></p>
<p class="small">AGLC_PAYMENTS=fake: no card is charged and no money moves.</p>
<form method="post" action="{action}"><p><label>Email (optional) <input type="email" name="email"></label></p>
<input type="hidden" name="deliver" value="1"><button class="pay">Pay {escape(c.product.display)}</button></form>
<form method="post" action="{action}"><input type="hidden" name="deliver" value="0"><button>Pay, webhook late</button></form>
<p><a href="{escape(cancel)}">Cancel and go back</a></p></div></body></html>"""


@router.post("/api/fake-checkout/{provider_order_id}/pay")
async def fake_checkout_pay(provider_order_id: str, deliver: str = Form("1"), email: str = Form("")) -> RedirectResponse:
    provider, c = _fake_checkout(provider_order_id)
    provider.pay(provider_order_id, email=email.strip() or None)
    if deliver == "1":  # deliver the signed webhook through the real verification path
        body, headers = provider.signed_event(provider_order_id)
        event = provider.parse_webhook(body=body, headers=headers, url="")
        outcome, order_id = await run_in_threadpool(apply_event, provider.name, event)
        await run_in_threadpool(after_payment, outcome, order_id, event.email)
    return RedirectResponse(c.redirect_url, status_code=303)

