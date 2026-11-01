"""Pay per document, or with credits. Off unless $AGLC_PAYMENTS names a provider (`square`,
`stripe`, or `fake`).

When it is on, processing is free but returns a redacted preview: every footnote's
stamp, all warnings, and only the first PREVIEW_FULL changed footnotes in full. The full
result is kept server-side; paying for the document (v1: the processing session id is
the entitlement) unlocks it and the .docx download.

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
    GET  /api/pack/{order_id}           a pack's status, and its code the first time it is asked for
    POST /api/redeem {session_id, code} unlock a document with credits
    POST /api/credits {code}            credits left on a code

Free processing is limited before any LLM call: per browser and per IP address per day,
a global daily cap, a footnote cap and a cap on concurrent jobs. If a paid document's
files have gone, the payment is refunded automatically.

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
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from . import credits, mailer, pipeline, retention
from .docx_io import read_footnotes
from .models import Extraction
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

PREVIEW_FULL = 3  # changed footnotes shown in full before paying
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
    count = len(read_footnotes(docx_path))
    cap = max_footnotes()
    if count > cap:
        raise HTTPException(413, f"This document has {count} footnotes; the limit is {cap}. Try splitting it into parts.")
    return count


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


def start_document(session_id: str, filename: str, visitor: Visitor) -> None:
    """Record a free run, refusing (429) one over today's limits. The check and the record
    are one transaction, so uploads at the same moment can't all pass `admit` and then
    all be recorded."""
    limits = _free_limits()
    refused = get_store().add_document(session_id, filename, ip_hash=visitor.ip_hash, anon_id=visitor.anon_id,
                                       limits=limits)
    if refused:
        _refuse(refused, limits[1])


def fail_document(session_id: str) -> None:
    get_store().finish_document(session_id, status="failed")


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
    get_store().finish_document(session_id, status="ready", footnote_count=len(full["footnotes"]))
    return view(session_id, full)


def view(session_id: str, full: dict) -> dict:
    """The full result once unlocked, else the preview; with the extraction report."""
    doc = get_store().document(session_id)
    shown = {**full, "locked": False} if doc["unlocked_at"] else preview(full)
    return {**shown, "id": session_id, **extraction_report(full),
            "reruns_left": max(0, MAX_RERUNS - doc["reruns"])}


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


def preview(full: dict) -> dict:
    """Every footnote's status and all warnings; only the first PREVIEW_FULL changed
    footnotes in full. Unchanged footnotes, and the original of a locked one, are the
    student's own text, so they are shown; a locked footnote's result is not."""
    tier = tier_for(len(full["footnotes"]))
    footnotes, shown, locked = [], 0, 0
    for fn in full["footnotes"]:
        if not fn["changed"] or shown < PREVIEW_FULL:
            shown += fn["changed"]
            footnotes.append(fn)
        else:
            locked += 1
            footnotes.append({"number": fn["number"], "changed": True, "locked": True,
                              "original": fn["original"], "original_html": fn["original_html"]})
    return {
        **full,
        "footnotes": footnotes,
        "bibliography": [],
        "bibliography_entries": sum(len(s["entries"]) for s in full["bibliography"]),
        "locked": True,
        "locked_count": locked,
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
    doc = conn.execute("SELECT unlocked_at, purged_at FROM documents WHERE session_id = ?", (session_id,)).fetchone()
    return doc is not None and not doc["unlocked_at"] and not doc["purged_at"] and _files_present(session_id)


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
    return True


def _settle(conn: sqlite3.Connection, order: sqlite3.Row, *, payment_id: str | None, amount: int, currency: str) -> str:
    """Mark `order` paid and unlock its document (or, for a pack, make its code and unlock
    the document it was bought from), inside the caller's transaction."""
    if amount != order["amount"] or currency.upper() != order["currency"]:
        log.error("order %s: paid %s %s, expected %s %s; not unlocking",
                  order["id"], amount, currency, order["amount"], order["currency"])
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
    doc = conn.execute("SELECT unlocked_at FROM documents WHERE session_id = ?", (order["session_id"],)).fetchone()
    if doc["unlocked_at"]:
        store.update_order(order["id"], conn, status="refunding", note="document was already paid for")
        return "duplicate_payment"
    if not _files_present(order["session_id"]):
        store.update_order(order["id"], conn, status="refunding", note="document files missing")
        return "files_missing"
    conn.execute(
        "UPDATE documents SET unlocked_at = ?, unlocked_by = ? WHERE session_id = ?",
        (now(), order["id"], order["session_id"]),
    )
    return "unlocked"


def _mark_refunded(conn: sqlite3.Connection, order: sqlite3.Row, event: WebhookEvent | None = None) -> str:
    """A refund made at the provider (eg from its dashboard). A document is locked again by a
    full refund only; any refund of a pack removes its unspent credits (documents it has
    already unlocked stay unlocked)."""
    if order["status"] == "refunded":
        return "already_refunded"
    is_pack = order["product"] in PACK_CREDITS
    if event is not None and not event.full and not is_pack:
        return "partial_refund"
    get_store().update_order(order["id"], conn, status="refunded", refunded_at=now())
    if is_pack:
        removed = credits.revoke(conn, order["id"], payment_id=order["payment_id"])
        log.info("pack order %s refunded: %s unspent credits removed", order["id"], removed or 0)
        return "pack_refunded"
    conn.execute(
        "UPDATE documents SET unlocked_at = NULL, unlocked_by = NULL WHERE session_id = ? AND unlocked_by = ?",
        (order["session_id"], order["id"]),
    )
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
    log.info("webhook %s %s: %s (order %s)", provider, event.type, outcome, order_id)
    return outcome, order_id


def after_payment(outcome: str, order_id: str | None, email: str | None) -> None:
    """What follows a payment being applied, outside its transaction: a refund it called for,
    or a new pack's code emailed (once) to the address the checkout collected."""
    if not order_id:
        return
    if outcome in _REFUND_OUTCOMES:
        _refund(order_id)
    elif outcome in _PACK_OUTCOMES and email:
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
        log.error("automatic refund of order %s failed: %s", order_id, e)
        store.update_order(order_id, status="refund_failed", note=f"{order['note']}; refund failed: {e}")
        return
    log.warning("refunded order %s: %s", order_id, order["note"])
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
            conn.execute("UPDATE documents SET unlocked_at = NULL, unlocked_by = NULL WHERE session_id = ?", (session_id,))
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
        log.warning("could not check order %s: %s", order["id"], e)
        return None
    if not status.paid:
        return None
    with get_store().transaction() as conn:
        fresh = conn.execute("SELECT * FROM orders WHERE id = ?", (order["id"],)).fetchone()
        outcome = _settle(conn, fresh, payment_id=status.payment_id, amount=status.amount, currency=status.currency)
    log.info("reconciled order %s: %s", order["id"], outcome)
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
        "preview_footnotes": PREVIEW_FULL,
        "email_codes": mailer.enabled(),  # whether a pack's code is also emailed
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
    if doc is None or doc["status"] != "ready":
        raise HTTPException(404, "Session not found or output not ready")
    if not doc["unlocked_at"] and not _files_present(session_id):
        raise HTTPException(410, "This document has expired. Please process it again.")
    if not doc["unlocked_at"] and not extraction_report(_load_result(session_id))["payable"]:
        raise HTTPException(409, "Some footnotes couldn't be read. Re-run them (free) before unlocking.")
    return doc


@router.post("/api/checkout")
def create_checkout(body: CheckoutRequest, request: Request) -> dict:
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
    store.add_order(order_id, session_id, product=product.id, amount=product.amount,
                    currency=product.currency, provider=provider.name)
    back = f"{_public_base(request)}/?paid=1"
    redirect = (f"{back}&session={session_id}" if session_id else back) + (f"&pack={order_id}" if is_pack else "")
    try:
        session = provider.create_checkout(order_id=order_id, product=product, redirect_url=redirect)
    except PaymentError as e:
        log.error("checkout for order %s failed: %s", order_id, e)
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
    full = _load_result(session_id) if doc else None
    if doc is None or (full is None and not doc["unlocked_at"]):
        raise HTTPException(404, "Session not found or expired")
    if doc["unlocked_at"] and not _files_present(session_id):
        _refund_missing(session_id)
        raise HTTPException(410, "This document's files are no longer available. Your payment has been refunded.")
    return view(session_id, full)


# ---- Credit packs ------------------------------------------------------------- #


def _code_balance(conn: sqlite3.Connection, code_row: sqlite3.Row | None) -> int:
    return code_row["credits_remaining"] if code_row is not None and not code_row["revoked_at"] else 0


@router.get("/api/pack/{order_id}")
def get_pack(order_id: str) -> dict:
    """A pack's order: `pending` (asks the provider if the webhook is late), `paid` or
    `refunded`. The first time it is asked for once paid, it carries the code, which is then
    forgotten: the page shows it once and keeps it in the browser. `emailed` says whether it
    was also emailed to the address given at checkout."""
    _require_enabled()
    if not re.fullmatch(r"[0-9a-f]{32}", order_id):
        raise HTTPException(404, "Unknown order")
    store = get_store()
    order = store.order(order_id)
    if order is None or order["product"] not in PACK_CREDITS:
        raise HTTPException(404, "Unknown order")
    if order["status"] == "pending":
        _reconcile_order(order)
        order = store.order(order_id)
    out: dict = {"order_id": order_id, "status": order["status"], "credits": PACK_CREDITS[order["product"]],
                 "session_id": order["session_id"], "email_enabled": mailer.enabled()}
    if order["status"] not in ("paid", "refunded"):
        return out
    with store.transaction() as conn:
        pickup = conn.execute("SELECT code, emailed FROM code_pickup WHERE order_id = ?", (order_id,)).fetchone()
        conn.execute("DELETE FROM code_pickup WHERE order_id = ?", (order_id,))
        row = conn.execute("SELECT * FROM credit_codes WHERE order_id = ?", (order_id,)).fetchone()
        out["credits_remaining"] = _code_balance(conn, row)
    if pickup is not None:
        store.scrub_wal()  # the code is now only in the response
        out["code"], out["emailed"] = pickup["code"], bool(pickup["emailed"])
    if order["session_id"]:
        doc = store.document(order["session_id"])
        out["unlocked"] = bool(doc and doc["unlocked_at"] and doc["unlocked_by"] == f"credit:{row['id'] if row else ''}")
    return out


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
    return {"unlocked": True, "credits_spent": cost if spent else 0, "credits_remaining": left}


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

