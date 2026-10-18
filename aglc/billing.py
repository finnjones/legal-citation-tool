"""Pay per document. Off unless $AGLC_PAYMENTS names a provider (`square`, or `fake`).

When it is on, processing is free but returns a redacted preview: every footnote's
stamp, all warnings, and only the first PREVIEW_FULL changed footnotes in full. The full
result is kept server-side; paying for the document (v1: the processing session id is
the entitlement) unlocks it and the .docx download.

    GET  /api/config                    what the page needs to know (price, payments on/off)
    POST /api/checkout {session_id}     create a hosted checkout, return its URL
    POST /api/webhooks/{provider}       verified, deduplicated, applied in one transaction
    GET  /api/entitlement/{session_id}  unlocked yet? (asks the provider if the webhook is late)
    GET  /api/results/{session_id}      the full result once unlocked, else the preview

Free processing is limited before any LLM call: per browser and per IP address per day,
a global daily cap, a footnote cap and a cap on concurrent jobs. If a paid document's
files have gone, the payment is refunded automatically.
"""

from __future__ import annotations

import hashlib
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
from html import escape
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from .docx_io import read_footnotes
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
    "document": Product(id="document", name="AGLC4 citation check: one document", amount=400, currency="AUD"),
}

PREVIEW_FULL = 3  # changed footnotes shown in full before paying
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


def _check_session_id(session_id: str) -> str:
    try:
        return str(uuid.UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid session ID") from None


def _require_enabled() -> None:
    if not enabled():
        raise HTTPException(status_code=404, detail="Payments are not enabled")


def _price() -> dict:
    p = PRODUCTS["document"]
    return {"amount": p.amount, "currency": p.currency, "display": p.display}


# --------------------------------------------------------------------------- #
# Free-path limits (all checked before any LLM call)
# --------------------------------------------------------------------------- #


@dataclass
class Visitor:
    ip_hash: str | None
    anon_id: str
    new_cookie: bool


def _client_ip(request: Request) -> str | None:
    """$AGLC_CLIENT_IP_HEADER (eg CF-Connecting-IP, X-Forwarded-For) behind a reverse proxy."""
    header = os.environ.get("AGLC_CLIENT_IP_HEADER")
    if header and request.headers.get(header):
        return request.headers[header].split(",")[0].strip()
    return request.client.host if request.client else None


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


def admit(request: Request, response: Response) -> Visitor:
    """Refuse (429) a free run over today's limits; set the anonymous cookie."""
    v = _visitor(request)
    per_browser = _int_env("AGLC_FREE_PER_DAY", 3)
    # One address is often a whole campus or household behind NAT, so it gets more headroom.
    per_ip = _int_env("AGLC_FREE_PER_IP_PER_DAY", per_browser * 5)
    global_cap = _int_env("AGLC_FREE_GLOBAL_PER_DAY", 300)
    by_ip, by_browser, total = get_store().free_uses_today(ip_hash=v.ip_hash, anon_id=v.anon_id)
    if total >= global_cap:
        raise HTTPException(429, "The free preview has reached today's limit. Please try again tomorrow.")
    if by_browser >= per_browser or by_ip >= per_ip:
        raise HTTPException(429, f"You've used today's {per_browser} free previews. Please try again tomorrow.")
    if v.new_cookie:
        response.set_cookie(
            ANON_COOKIE, v.anon_id, max_age=365 * 86400, httponly=True, samesite="lax",
            secure=request.url.scheme == "https",
        )
    return v


def check_footnote_cap(docx_path: Path) -> int:
    """Count the footnotes (no LLM involved) and refuse (413) a document over the cap."""
    count = len(read_footnotes(docx_path))
    cap = _int_env("AGLC_MAX_FOOTNOTES", 400)
    if count > cap:
        raise HTTPException(413, f"This document has {count} footnotes; the limit is {cap}.")
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


def start_document(session_id: str, filename: str, visitor: Visitor) -> None:
    get_store().add_document(session_id, filename, ip_hash=visitor.ip_hash, anon_id=visitor.anon_id)


def fail_document(session_id: str) -> None:
    get_store().finish_document(session_id, status="failed")


def save_result(session_id: str, filename: str, full: dict) -> dict:
    """Keep the full result server-side and return what the page may see now."""
    full = {**full, "filename": filename}
    (_session_dir(session_id) / "result.json").write_text(json.dumps(full))
    get_store().finish_document(session_id, status="ready", footnote_count=len(full["footnotes"]))
    return preview(full)


def preview(full: dict) -> dict:
    """Every footnote's stamp and all warnings; only the first PREVIEW_FULL changed
    footnotes in full. Unchanged footnotes are the student's own text, so they are shown."""
    footnotes, shown, locked = [], 0, 0
    for fn in full["footnotes"]:
        if not fn["changed"] or shown < PREVIEW_FULL:
            shown += fn["changed"]
            footnotes.append(fn)
        else:
            locked += 1
            footnotes.append({"number": fn["number"], "changed": True, "locked": True})
    return {
        **full,
        "footnotes": footnotes,
        "bibliography": [],
        "bibliography_entries": sum(len(s["entries"]) for s in full["bibliography"]),
        "locked": True,
        "locked_count": locked,
        "price": _price(),
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
    if not doc["unlocked_at"]:
        raise HTTPException(402, f"Unlock this document ({PRODUCTS['document'].display}) to download it.")
    if not _files_present(session_id):
        _refund_missing(session_id)
        raise HTTPException(410, "This document's files are no longer available. Your payment has been refunded.")


# --------------------------------------------------------------------------- #
# Applying payments (shared by the webhook and the late-webhook reconcile)
# --------------------------------------------------------------------------- #


def _settle(conn: sqlite3.Connection, order: sqlite3.Row, *, payment_id: str | None, amount: int, currency: str) -> str:
    """Mark `order` paid and unlock its document, inside the caller's transaction."""
    if amount != order["amount"] or currency.upper() != order["currency"]:
        log.error("order %s: paid %s %s, expected %s %s; not unlocking",
                  order["id"], amount, currency, order["amount"], order["currency"])
        return "amount_mismatch"
    if order["status"] != "pending":
        return f"already_{order['status']}"
    store = get_store()
    store.update_order(order["id"], conn, status="paid", payment_id=payment_id, paid_at=now())
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


def _mark_refunded(conn: sqlite3.Connection, order: sqlite3.Row) -> str:
    """A refund made at the provider (eg from its dashboard): lock the document again."""
    if order["status"] == "refunded":
        return "already_refunded"
    get_store().update_order(order["id"], conn, status="refunded", refunded_at=now())
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
            outcome = _mark_refunded(conn, order)
        order_id = order["id"] if order else None
        conn.execute("UPDATE webhook_events SET outcome = ?, order_id = ? WHERE event_id = ?",
                     (outcome, order_id, event.event_id))
    log.info("webhook %s %s: %s (order %s)", provider, event.type, outcome, order_id)
    return outcome, order_id


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
    log.warning("refunded order %s (%s): %s", order_id, refund.refund_id, order["note"])
    store.update_order(order_id, status="refunded", refund_id=refund.refund_id, refunded_at=now())


def _refund_missing(session_id: str) -> None:
    """The document was paid for but its files are gone: refund and lock it."""
    store = get_store()
    with store.transaction() as conn:
        doc = conn.execute("SELECT unlocked_by FROM documents WHERE session_id = ?", (session_id,)).fetchone()
        order_id = doc["unlocked_by"] if doc else None
        if order_id:
            conn.execute("UPDATE documents SET unlocked_at = NULL, unlocked_by = NULL WHERE session_id = ?", (session_id,))
            conn.execute(
                "UPDATE orders SET status = 'refunding', note = 'document files missing', updated_at = ?"
                " WHERE id = ? AND status = 'paid'",
                (now(), order_id),
            )
    if order_id:
        _refund(order_id)


_last_checked: dict[str, float] = {}
RECONCILE_INTERVAL = 2.0  # seconds between asking the provider about one order


def _reconcile(session_id: str) -> None:
    """The webhook is late: ask the provider directly about this document's pending orders."""
    store = get_store()
    for order in store.orders_for(session_id):
        if order["status"] != "pending" or not order["provider_order_id"]:
            continue
        if time.monotonic() - _last_checked.get(order["id"], -1e9) < RECONCILE_INTERVAL:
            continue
        _last_checked[order["id"]] = time.monotonic()
        try:
            status = get_payment_provider(order["provider"]).retrieve(order["provider_order_id"])
        except PaymentError as e:
            log.warning("could not check order %s: %s", order["id"], e)
            continue
        if not status.paid:
            continue
        with store.transaction() as conn:
            fresh = conn.execute("SELECT * FROM orders WHERE id = ?", (order["id"],)).fetchone()
            outcome = _settle(conn, fresh, payment_id=status.payment_id, amount=status.amount, currency=status.currency)
        log.info("reconciled order %s: %s", order["id"], outcome)
        if outcome in _REFUND_OUTCOMES:
            _refund(order["id"])


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

router = APIRouter()


@router.get("/api/config")
async def get_config() -> dict:
    if not enabled():
        return {"payments": False}
    return {
        "payments": True,
        "provider": configured_payment_provider(),
        "price": _price(),
        "preview_footnotes": PREVIEW_FULL,
    }


class CheckoutRequest(BaseModel):
    session_id: str


def _public_base(request: Request) -> str:
    return (os.environ.get("AGLC_PUBLIC_URL") or str(request.base_url)).rstrip("/")


@router.post("/api/checkout")
def create_checkout(body: CheckoutRequest, request: Request) -> dict:
    _require_enabled()
    session_id = _check_session_id(body.session_id)
    store = get_store()
    doc = store.document(session_id)
    if doc is None or doc["status"] != "ready":
        raise HTTPException(404, "Session not found or output not ready")
    if doc["unlocked_at"]:
        return {"unlocked": True}
    if not _files_present(session_id):
        raise HTTPException(410, "This document has expired. Please process it again.")

    for order in store.orders_for(session_id):  # don't make a second link for the same document
        if order["status"] == "pending" and order["checkout_url"]:
            return {"checkout_url": order["checkout_url"], "order_id": order["id"]}

    product = PRODUCTS["document"]
    provider = get_payment_provider()
    order_id = uuid.uuid4().hex
    store.add_order(order_id, session_id, product=product.id, amount=product.amount,
                    currency=product.currency, provider=provider.name)
    try:
        session = provider.create_checkout(
            order_id=order_id, product=product, redirect_url=f"{_public_base(request)}/?paid=1&session={session_id}"
        )
    except PaymentError as e:
        log.error("checkout for %s failed: %s", session_id, e)
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
    if outcome in _REFUND_OUTCOMES and order_id:
        await run_in_threadpool(_refund, order_id)
    return {"ok": True, "outcome": outcome}


@router.get("/api/entitlement/{session_id}")
def get_entitlement(session_id: str) -> dict:
    _require_enabled()
    session_id = _check_session_id(session_id)
    store = get_store()
    doc = store.document(session_id)
    if doc is None:
        raise HTTPException(404, "Session not found")
    if not doc["unlocked_at"]:
        _reconcile(session_id)
        doc = store.document(session_id)
    statuses = {o["status"] for o in store.orders_for(session_id)}
    if doc["unlocked_at"]:
        status = "unlocked"
    elif "pending" in statuses:
        status = "pending"
    elif statuses & {"refunding", "refunded", "refund_failed"}:
        status = "refunded"
    else:
        status = "none"
    return {"session_id": session_id, "unlocked": bool(doc["unlocked_at"]), "status": status}


@router.get("/api/results/{session_id}")
def get_results(session_id: str) -> dict:
    _require_enabled()
    session_id = _check_session_id(session_id)
    doc = get_store().document(session_id)
    full = _load_result(session_id) if doc else None
    if doc is None or (full is None and not doc["unlocked_at"]):
        raise HTTPException(404, "Session not found or expired")
    if doc["unlocked_at"] and not _files_present(session_id):
        _refund_missing(session_id)
        raise HTTPException(410, "This document's files are no longer available. Your payment has been refunded.")
    return {**full, "id": session_id, "locked": False} if doc["unlocked_at"] else {**preview(full), "id": session_id}


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
<form method="post" action="{action}"><input type="hidden" name="deliver" value="1"><button class="pay">Pay {escape(c.product.display)}</button></form>
<form method="post" action="{action}"><input type="hidden" name="deliver" value="0"><button>Pay, webhook late</button></form>
<p><a href="{escape(cancel)}">Cancel and go back</a></p></div></body></html>"""


@router.post("/api/fake-checkout/{provider_order_id}/pay")
async def fake_checkout_pay(provider_order_id: str, deliver: str = Form("1")) -> RedirectResponse:
    provider, c = _fake_checkout(provider_order_id)
    provider.pay(provider_order_id)
    if deliver == "1":  # deliver the signed webhook through the real verification path
        body, headers = provider.signed_event(provider_order_id)
        event = provider.parse_webhook(body=body, headers=headers, url="")
        outcome, order_id = await run_in_threadpool(apply_event, provider.name, event)
        if outcome in _REFUND_OUTCOMES and order_id:
            await run_in_threadpool(_refund, order_id)
    return RedirectResponse(c.redirect_url, status_code=303)

