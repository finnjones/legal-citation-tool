"""Stripe Checkout (hosted Checkout Sessions). Requires `pip install aglc[stripe]`.

Settings (environment):
    STRIPE_SECRET_KEY       secret (or restricted) API key; sk_test_... until you go live
    STRIPE_WEBHOOK_SECRET   the webhook endpoint's signing secret (whsec_...)

Point a webhook endpoint at https://<domain>/api/webhooks/stripe and subscribe it to
`checkout.session.completed`, `checkout.session.async_payment_succeeded`,
`checkout.session.expired` and `charge.refunded`. A payment counts once a Checkout Session
completes with payment_status "paid" (or later reports async_payment_succeeded). Orders are
matched by the Checkout Session id that create_checkout returned (stored as the order's
provider_order_id). A refund event carries a Charge, not a session, so the session is found
from the charge's PaymentIntent (one `checkout/sessions` list call); only a full refund
locks the document again. `checkout.session.expired` is subscribed for the dashboard's log
but needs no action: a session that expires took no money.

Sessions expire an hour after they are made, so billing makes a fresh one when a pending
order is older than `checkout_lifetime`. Apple Pay and Google Pay come with Checkout
(payment_method_types is left to the Dashboard's payment method settings).
"""

from __future__ import annotations

import logging
import os
import time
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

log = logging.getLogger("aglc.stripe")

SIGNATURE_HEADER = "stripe-signature"

#: How long a Checkout Session can be paid (Stripe allows 30 minutes to 24 hours).
SESSION_LIFETIME = 3600

#: Seconds before a request to Stripe gives up, and how often the SDK retries a network
#: failure (safe: every create call carries an idempotency key).
TIMEOUT = 20
MAX_NETWORK_RETRIES = 2


def _stripe():
    try:
        import stripe
    except ImportError as e:  # pragma: no cover - depends on the install
        raise PaymentError("The Stripe SDK is not installed. Run: pip install 'aglc[stripe]'") from e
    return stripe


@register_payment_provider("stripe")
class StripeProvider(PaymentProvider):
    checkout_lifetime = SESSION_LIFETIME

    def __init__(self, **options: Any) -> None:
        self.api_key = options.get("api_key") or os.environ.get("STRIPE_SECRET_KEY", "")
        self.webhook_secret = options.get("webhook_secret") or os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        self._client = options.get("client")

    @property
    def client(self):
        """The SDK's `StripeClient`, narrowed to its v1 API (SDKs before v14 have no `.v1`)."""
        if self._client is None:
            stripe = _stripe()
            if not self.api_key:
                raise PaymentError("Set STRIPE_SECRET_KEY")
            self._client = stripe.StripeClient(
                self.api_key,
                http_client=stripe.RequestsClient(timeout=TIMEOUT),
                max_network_retries=MAX_NETWORK_RETRIES,
            )
        return getattr(self._client, "v1", self._client)

    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PaymentError:
            raise
        except Exception as e:  # stripe.StripeError, requests errors
            raise PaymentError(f"Stripe request failed: {e}") from e

    # ---- PaymentProvider ---------------------------------------------------- #

    def create_checkout(self, *, order_id: str, product: Product, redirect_url: str) -> CheckoutSession:
        session = self._call(
            self.client.checkout.sessions.create,
            params={
                "mode": "payment",
                "client_reference_id": order_id,
                "metadata": {"order_id": order_id},
                "line_items": [
                    {
                        "quantity": 1,
                        "price_data": {
                            "currency": product.currency.lower(),
                            "unit_amount": product.amount,
                            "product_data": {"name": product.name},
                        },
                    }
                ],
                # Billing's redirect URL carries our own session id, so {CHECKOUT_SESSION_ID} isn't used.
                "success_url": redirect_url,
                "cancel_url": redirect_url.replace("paid=1&", ""),  # back to the page without "confirming payment"
                "expires_at": int(time.time()) + SESSION_LIFETIME,
                "payment_intent_data": {"metadata": {"order_id": order_id}, "description": f"Order {order_id}"},
            },
            options={"idempotency_key": order_id},
        )
        if not session or not _get(session, "id") or not _get(session, "url"):
            raise PaymentError("Stripe returned no Checkout Session URL")
        return CheckoutSession(checkout_id=session["id"], url=session["url"], provider_order_id=session["id"])

    def cancel_checkout(self, checkout_id: str) -> None:
        # An expired session can't be paid, so a late payment (refunded, with Stripe keeping its
        # fee) can't happen.
        stripe = _stripe()
        try:
            self._call(self.client.checkout.sessions.expire, checkout_id)
        except PaymentError as e:
            if isinstance(e.__cause__, stripe.InvalidRequestError):  # already expired or completed
                log.info("checkout %s was already closed: %s", checkout_id, e.__cause__)
                return
            raise

    def parse_webhook(self, *, body: bytes, headers: Mapping[str, str], url: str) -> WebhookEvent:
        if not self.webhook_secret:
            raise WebhookSignatureError("STRIPE_WEBHOOK_SECRET is not set")
        stripe = _stripe()
        given = _header(headers, SIGNATURE_HEADER)
        if not given:
            raise WebhookSignatureError("missing Stripe-Signature header")
        try:
            event = stripe.Webhook.construct_event(body, given, self.webhook_secret)
        except stripe.SignatureVerificationError as e:
            raise WebhookSignatureError("bad Stripe webhook signature") from e
        except ValueError as e:  # not JSON
            raise WebhookSignatureError("webhook body is not JSON") from e

        event_id, kind = str(event["id"] or ""), str(event["type"] or "")
        obj = event["data"]["object"]
        if kind in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            # "completed" with an unpaid session is a delayed payment method: async_payment_succeeded follows.
            paid = _get(obj, "payment_status") == "paid"
            return WebhookEvent(
                event_id=event_id,
                type=kind,
                status="paid" if paid else "ignored",
                provider_order_id=_get(obj, "id"),
                payment_id=_id(_get(obj, "payment_intent")),
                amount=int(_get(obj, "amount_total") or 0),
                currency=str(_get(obj, "currency") or "").upper(),
            )
        if kind == "charge.refunded":
            payment_intent = _id(_get(obj, "payment_intent"))
            # A partial refund leaves the document unlocked; only a full one locks it.
            if not payment_intent or not _get(obj, "refunded"):
                return WebhookEvent(event_id=event_id, type=kind, status="ignored", payment_id=payment_intent)
            return WebhookEvent(
                event_id=event_id,
                type=kind,
                status="refunded",
                provider_order_id=self._session_for_payment_intent(payment_intent),
                payment_id=payment_intent,
                amount=int(_get(obj, "amount_refunded") or 0),
                currency=str(_get(obj, "currency") or "").upper(),
            )
        return WebhookEvent(event_id=event_id, type=kind, status="ignored")

    def _session_for_payment_intent(self, payment_intent: str) -> str | None:
        """The Checkout Session that created this PaymentIntent. Raises PaymentError if Stripe
        can't be asked, so the webhook fails and Stripe retries it."""
        found = self._call(self.client.checkout.sessions.list, params={"payment_intent": payment_intent, "limit": 1})
        sessions = _get(found, "data") or []
        return sessions[0]["id"] if sessions else None

    def retrieve(self, provider_order_id: str) -> PaymentStatus:
        session = self._call(self.client.checkout.sessions.retrieve, provider_order_id)
        if not session or _get(session, "payment_status") != "paid":  # unpaid: still open, expired, or paying slowly
            return PaymentStatus(paid=False)
        return PaymentStatus(
            paid=True,
            amount=int(_get(session, "amount_total") or 0),
            currency=str(_get(session, "currency") or "").upper(),
            payment_id=_id(_get(session, "payment_intent")),
        )

    def refund(self, *, payment_id: str, amount: int, currency: str, reason: str, idempotency_key: str) -> Refund:
        # `reason` is free text, but Stripe's own field is an enum, so it goes in the metadata.
        refund = self._call(
            self.client.refunds.create,
            params={"payment_intent": payment_id, "amount": amount, "metadata": {"reason": reason[:500]}},
            options={"idempotency_key": idempotency_key},
        )
        if not refund or not _get(refund, "id"):
            raise PaymentError("Stripe refused the refund")
        return Refund(refund_id=refund["id"], status=str(_get(refund, "status") or "pending"))


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """`obj[key]` for Stripe's response objects, which are dicts in older SDKs and not in newer
    ones; a missing or null field gives `default`."""
    try:
        value = obj[key]
    except (KeyError, TypeError, AttributeError):
        return default
    return default if value is None else value


def _id(value: Any) -> str | None:
    """An id from a field that is an id string, or the expanded object."""
    if value and not isinstance(value, str):
        value = _get(value, "id")
    return str(value) if value else None


def _header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name)
    if value is None:  # plain dicts aren't case-insensitive like Starlette's Headers
        value = next((v for k, v in headers.items() if k.lower() == name), None)
    return value or ""
