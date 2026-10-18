"""Square Checkout API (payment links). Requires `pip install aglc[square]`.

Settings (environment):
    SQUARE_ACCESS_TOKEN            access token for the application
    SQUARE_LOCATION_ID             the location payments are taken at
    SQUARE_ENVIRONMENT             sandbox (default) | production
    SQUARE_WEBHOOK_SIGNATURE_KEY   the webhook subscription's signature key
    SQUARE_WEBHOOK_URL             the notification URL exactly as registered with Square
                                   (default: the URL the request arrived on, which is wrong
                                   behind a reverse proxy that rewrites it)

Subscribe the webhook to `payment.created`, `payment.updated` and `refund.updated`. A payment
counts once `payment.updated` reports status COMPLETED; it is matched to our order by the
Square order id that CreatePaymentLink returned (stored at checkout). `order.updated` isn't
used: orders from payment links can stay OPEN after payment. Payment links made through the
API are single-use, so billing keeps one pending link per document and reuses it.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from collections.abc import Mapping
from typing import Any

from ..base import (
    CheckoutSession,
    PaymentError,
    PaymentProvider,
    PaymentStatus,
    Product,
    Refund,
    WebhookEvent,
    WebhookSignatureError,
    register_payment_provider,
)

SIGNATURE_HEADER = "x-square-hmacsha256-signature"


def square_signature(signature_key: str, notification_url: str, body: bytes) -> str:
    """base64(HMAC-SHA256(key, notification URL + raw body)), as Square signs webhooks."""
    digest = hmac.new(signature_key.encode(), notification_url.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


@register_payment_provider("square")
class SquareProvider(PaymentProvider):
    def __init__(self, **options: Any) -> None:
        self.access_token = options.get("access_token") or os.environ.get("SQUARE_ACCESS_TOKEN", "")
        self.location_id = options.get("location_id") or os.environ.get("SQUARE_LOCATION_ID", "")
        self.environment = (options.get("environment") or os.environ.get("SQUARE_ENVIRONMENT") or "sandbox").lower()
        self.signature_key = options.get("signature_key") or os.environ.get("SQUARE_WEBHOOK_SIGNATURE_KEY", "")
        self.webhook_url = options.get("webhook_url") or os.environ.get("SQUARE_WEBHOOK_URL", "")
        self._client = options.get("client")

    @property
    def client(self):
        if self._client is None:
            try:
                from square import Square
                from square.environment import SquareEnvironment
            except ImportError as e:  # pragma: no cover - depends on the install
                raise PaymentError("The Square SDK is not installed. Run: pip install 'aglc[square]'") from e
            if not self.access_token or not self.location_id:
                raise PaymentError("Set SQUARE_ACCESS_TOKEN and SQUARE_LOCATION_ID")
            env = SquareEnvironment.PRODUCTION if self.environment == "production" else SquareEnvironment.SANDBOX
            self._client = Square(token=self.access_token, environment=env, timeout=20)
        return self._client

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PaymentError:
            raise
        except Exception as e:  # square.core.api_error.ApiError, httpx errors
            raise PaymentError(f"Square request failed: {e}") from e

    # ---- PaymentProvider ---------------------------------------------------- #

    def create_checkout(self, *, order_id: str, product: Product, redirect_url: str) -> CheckoutSession:
        resp = self._call(
            self.client.checkout.payment_links.create,
            idempotency_key=order_id,
            order={
                "location_id": self.location_id,
                "reference_id": order_id,
                "line_items": [
                    {
                        "name": product.name,
                        "quantity": "1",
                        "base_price_money": {"amount": product.amount, "currency": product.currency},
                    }
                ],
            },
            checkout_options={
                "redirect_url": redirect_url,  # carries our own session id; only production appends orderId
                "allow_tipping": False,
                "ask_for_shipping_address": False,
                # No documented default, so ask for wallets explicitly. The seller must also turn them
                # on in Dashboard > Payment links > Settings.
                "accepted_payment_methods": {"apple_pay": True, "google_pay": True},
            },
            payment_note=f"Order {order_id}",
        )
        link = resp.payment_link
        if not link or not link.url or not link.order_id:
            raise PaymentError(f"Square returned no payment link: {getattr(resp, 'errors', None)}")
        return CheckoutSession(checkout_id=link.id or "", url=link.url, provider_order_id=link.order_id)

    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str], url: str) -> WebhookEvent:
        if not self.signature_key:
            raise WebhookSignatureError("SQUARE_WEBHOOK_SIGNATURE_KEY is not set")
        given = _header(headers, SIGNATURE_HEADER)
        expected = square_signature(self.signature_key, self.webhook_url or url, body)
        if not given or not hmac.compare_digest(given.encode(), expected.encode()):
            raise WebhookSignatureError("bad Square webhook signature")
        try:
            payload = json.loads(body)
        except ValueError as e:
            raise WebhookSignatureError("webhook body is not JSON") from e

        event_id, kind = str(payload.get("event_id") or ""), str(payload.get("type") or "")
        obj = (payload.get("data") or {}).get("object") or {}
        if kind.startswith("payment.") and "payment" in obj:
            p = obj["payment"]
            money = p.get("amount_money") or {}
            return WebhookEvent(
                event_id=event_id,
                type=kind,
                status="paid" if p.get("status") == "COMPLETED" else "ignored",
                provider_order_id=p.get("order_id"),
                payment_id=p.get("id"),
                amount=int(money.get("amount") or 0),
                currency=str(money.get("currency") or ""),
            )
        if kind.startswith("refund.") and "refund" in obj:
            r = obj["refund"]
            money = r.get("amount_money") or {}
            return WebhookEvent(
                event_id=event_id,
                type=kind,
                status="refunded" if r.get("status") == "COMPLETED" else "ignored",
                provider_order_id=r.get("order_id"),
                payment_id=r.get("payment_id"),
                amount=int(money.get("amount") or 0),
                currency=str(money.get("currency") or ""),
            )
        return WebhookEvent(event_id=event_id, type=kind, status="ignored")

    def retrieve(self, provider_order_id: str) -> PaymentStatus:
        order = self._call(self.client.orders.get, provider_order_id).order
        if order is None:
            return PaymentStatus(paid=False)
        total = order.total_money
        due, currency = (total.amount or 0, total.currency or "") if total else (0, "")
        paid_amount, payment_id = 0, None
        for tender in order.tenders or []:
            if not tender.payment_id:
                continue
            payment = self._call(self.client.payments.get, tender.payment_id).payment
            if payment and payment.status == "COMPLETED" and payment.amount_money:
                paid_amount += payment.amount_money.amount or 0
                payment_id = payment_id or payment.id
        return PaymentStatus(
            paid=due > 0 and paid_amount >= due, amount=paid_amount, currency=currency, payment_id=payment_id
        )

    def refund(self, *, payment_id: str, amount: int, currency: str, reason: str, idempotency_key: str) -> Refund:
        resp = self._call(
            self.client.refunds.refund_payment,
            idempotency_key=idempotency_key[:45],
            payment_id=payment_id,
            amount_money={"amount": amount, "currency": currency},
            reason=reason[:192],
        )
        if not resp.refund:
            raise PaymentError(f"Square refused the refund: {getattr(resp, 'errors', None)}")
        return Refund(refund_id=resp.refund.id or "", status=resp.refund.status or "PENDING")


def _header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name)
    if value is None:  # plain dicts aren't case-insensitive like Starlette's Headers
        value = next((v for k, v in headers.items() if k.lower() == name), None)
    return value or ""
