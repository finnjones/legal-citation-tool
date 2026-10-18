"""Offline payment provider for tests and local demos (AGLC_PAYMENTS=fake). No network.

Checkouts live in memory. `pay()` plays the customer paying; `signed_event()` builds the
HMAC-signed webhook the provider would send. The billing router serves a stand-in
checkout page for it at /api/fake-checkout/{id}.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
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

SIGNATURE_HEADER = "x-fake-signature"


@dataclass
class FakeCheckout:
    order_id: str
    product: Product
    redirect_url: str
    payment_id: str | None = None
    refunds: list[Refund] = field(default_factory=list)


@register_payment_provider("fake")
class FakePaymentProvider(PaymentProvider):
    def __init__(self, **options: Any) -> None:
        self.secret = options.get("secret") or os.environ.get("AGLC_FAKE_WEBHOOK_SECRET") or "fake-webhook-secret"
        self.checkouts: dict[str, FakeCheckout] = {}
        self.fail_refunds = False

    # ---- PaymentProvider ---------------------------------------------------- #

    def create_checkout(self, *, order_id: str, product: Product, redirect_url: str) -> CheckoutSession:
        provider_order_id = f"fake_order_{uuid.uuid4().hex[:16]}"
        self.checkouts[provider_order_id] = FakeCheckout(order_id, product, redirect_url)
        return CheckoutSession(
            checkout_id=f"fake_link_{provider_order_id[11:]}",
            url=f"/api/fake-checkout/{provider_order_id}",
            provider_order_id=provider_order_id,
        )

    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str], url: str) -> WebhookEvent:
        given = headers.get(SIGNATURE_HEADER) or ""
        if not given or not hmac.compare_digest(given, self.sign(body)):
            raise WebhookSignatureError("bad fake webhook signature")
        payload = json.loads(body)
        return WebhookEvent(
            event_id=payload["event_id"],
            type=payload["type"],
            status=payload["status"],
            provider_order_id=payload.get("provider_order_id"),
            payment_id=payload.get("payment_id"),
            amount=int(payload.get("amount") or 0),
            currency=payload.get("currency") or "",
        )

    def retrieve(self, provider_order_id: str) -> PaymentStatus:
        c = self.checkouts.get(provider_order_id)
        if not c or not c.payment_id:
            return PaymentStatus(paid=False)
        return PaymentStatus(paid=True, amount=c.product.amount, currency=c.product.currency, payment_id=c.payment_id)

    def refund(self, *, payment_id: str, amount: int, currency: str, reason: str, idempotency_key: str) -> Refund:
        if self.fail_refunds:
            raise PaymentError("fake refund failure")
        for c in self.checkouts.values():
            if c.payment_id == payment_id:
                for r in c.refunds:  # idempotent, like the real thing
                    if r.refund_id == f"fake_refund_{idempotency_key}":
                        return r
                refund = Refund(refund_id=f"fake_refund_{idempotency_key}", status="COMPLETED")
                c.refunds.append(refund)
                return refund
        raise PaymentError(f"unknown payment {payment_id}")

    # ---- test helpers ------------------------------------------------------- #

    def sign(self, body: bytes) -> str:
        return hmac.new(self.secret.encode(), body, hashlib.sha256).hexdigest()

    def pay(self, provider_order_id: str) -> str:
        """The customer pays; returns the payment id."""
        c = self.checkouts[provider_order_id]
        c.payment_id = c.payment_id or f"fake_payment_{uuid.uuid4().hex[:16]}"
        return c.payment_id

    def signed_event(
        self,
        provider_order_id: str,
        *,
        status: str = "paid",
        amount: int | None = None,
        currency: str | None = None,
        event_id: str | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        """The webhook body and headers the provider would send for this checkout."""
        c = self.checkouts[provider_order_id]
        body = json.dumps(
            {
                "event_id": event_id or f"fake_evt_{uuid.uuid4().hex}",
                "type": "payment.updated",
                "status": status,
                "provider_order_id": provider_order_id,
                "payment_id": c.payment_id,
                "amount": c.product.amount if amount is None else amount,
                "currency": currency or c.product.currency,
            }
        ).encode()
        return body, {SIGNATURE_HEADER: self.sign(body), "content-type": "application/json"}
