"""The Stripe Checkout provider (aglc/payments/providers/stripe_provider.py), offline.

Webhooks are signed here with Stripe's own scheme (`t=<time>,v1=HMAC-SHA256(secret, "<time>.<body>")`)
and verified by the real SDK; every call to Stripe goes to a mocked client."""

from __future__ import annotations

import hashlib
import hmac
import json
import shutil
import time
from pathlib import Path
from unittest import mock

import pytest

stripe = pytest.importorskip("stripe")

from fastapi.testclient import TestClient  # noqa: E402

from aglc import api, billing  # noqa: E402
from aglc.llm import get_provider  # noqa: E402
from aglc.payments import (  # noqa: E402
    PaymentError,
    Product,
    WebhookSignatureError,
    get_payment_provider,
    reset_payment_providers,
)
from aglc.payments.providers.stripe_provider import SIGNATURE_HEADER, StripeProvider  # noqa: E402
from aglc.store import get_store  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
ESSAY = FIXTURES / "sample_essay.docx"
EXTRACTION = (FIXTURES / "sample_essay_extraction.json").read_text()
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

SECRET = "whsec_test_secret"
PRODUCT = Product(id="document", name="AGLC4 citation check: one document", amount=400, currency="AUD")
REDIRECT = "https://aglc.example/?paid=1&session=abc123"


def signed(payload: dict, secret: str = SECRET, *, t: int | None = None) -> tuple[bytes, dict[str, str]]:
    """A webhook body and its Stripe-Signature header, as Stripe would send them."""
    body = json.dumps(payload).encode()
    t = int(time.time()) if t is None else t
    digest = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return body, {SIGNATURE_HEADER: f"t={t},v1={digest}"}


def event(kind: str, obj: dict, event_id: str = "evt_1") -> dict:
    return {"id": event_id, "object": "event", "type": kind, "data": {"object": obj}}


def completed_session(**overrides) -> dict:
    return {
        "id": "cs_test_1", "object": "checkout.session", "status": "complete", "payment_status": "paid",
        "payment_intent": "pi_1", "amount_total": 400, "currency": "aud", "client_reference_id": "order-1",
        **overrides,
    }


def charge(**overrides) -> dict:
    return {"id": "ch_1", "object": "charge", "payment_intent": "pi_1", "refunded": True,
            "amount": 400, "amount_refunded": 400, "currency": "aud", **overrides}


def session_object(**values):
    return stripe.checkout.Session.construct_from(values, "sk_test_x")


@pytest.fixture
def api_client():
    """A mocked StripeClient (its v1 API, as the provider uses it)."""
    client = mock.MagicMock()
    client.v1.checkout.sessions.create.return_value = session_object(
        id="cs_test_1", url="https://checkout.stripe.com/c/pay/cs_test_1")
    return client


@pytest.fixture
def provider(api_client):
    return StripeProvider(client=api_client, webhook_secret=SECRET)


def parse(provider, payload, *, headers=None, secret=SECRET):
    body, signature = signed(payload, secret)
    return provider.parse_webhook(body=body, headers=signature if headers is None else headers, url="http://x/")


# ---- webhooks ------------------------------------------------------------------- #


def test_completed_session_is_paid_with_amount_and_payment_intent(provider):
    e = parse(provider, event("checkout.session.completed", completed_session(), "evt_paid"))
    assert (e.event_id, e.type, e.status) == ("evt_paid", "checkout.session.completed", "paid")
    assert e.provider_order_id == "cs_test_1"
    assert e.payment_id == "pi_1"
    assert (e.amount, e.currency) == (400, "AUD")  # Stripe says "aud"; billing compares upper case


def test_unpaid_completion_waits_for_the_async_event(provider):
    unpaid = completed_session(payment_status="unpaid", payment_intent=None)
    assert parse(provider, event("checkout.session.completed", unpaid)).status == "ignored"
    later = parse(provider, event("checkout.session.async_payment_succeeded", completed_session(), "evt_2"))
    assert (later.status, later.provider_order_id, later.amount) == ("paid", "cs_test_1", 400)


def test_bad_signatures_are_rejected(provider):
    payload = event("checkout.session.completed", completed_session())
    with pytest.raises(WebhookSignatureError):
        parse(provider, payload, secret="whsec_somebody_else")
    body, headers = signed(payload)
    with pytest.raises(WebhookSignatureError):
        provider.parse_webhook(body=body + b" ", headers=headers, url="")  # tampered
    with pytest.raises(WebhookSignatureError):
        provider.parse_webhook(body=body, headers={}, url="")  # unsigned
    body, headers = signed(payload, t=int(time.time()) - 3600)
    with pytest.raises(WebhookSignatureError):
        provider.parse_webhook(body=body, headers=headers, url="")  # a replay outside Stripe's tolerance
    with pytest.raises(WebhookSignatureError):
        StripeProvider(client=mock.MagicMock(), webhook_secret="").parse_webhook(body=body, headers=headers, url="")


def test_header_name_is_case_insensitive_for_plain_dicts(provider):
    body, headers = signed(event("checkout.session.completed", completed_session()))
    value = headers[SIGNATURE_HEADER]
    assert provider.parse_webhook(body=body, headers={"Stripe-Signature": value}, url="").status == "paid"


def test_unknown_events_are_ignored(provider):
    for kind, obj in [("customer.created", {"id": "cus_1"}), ("checkout.session.expired", completed_session(
            status="expired", payment_status="unpaid")), ("payment_intent.created", {"id": "pi_1"})]:
        e = parse(provider, event(kind, obj, f"evt_{kind}"))
        assert (e.status, e.event_id, e.type) == ("ignored", f"evt_{kind}", kind)


def test_full_refund_is_matched_to_the_order_through_its_checkout_session(provider, api_client):
    api_client.v1.checkout.sessions.list.return_value = {"data": [{"id": "cs_test_1"}]}
    e = parse(provider, event("charge.refunded", charge(), "evt_refund"))
    assert (e.status, e.provider_order_id, e.payment_id, e.amount, e.currency) == ("refunded", "cs_test_1", "pi_1", 400, "AUD")
    api_client.v1.checkout.sessions.list.assert_called_once_with(params={"payment_intent": "pi_1", "limit": 1})


def test_partial_and_unmatched_refunds(provider, api_client):
    partial = parse(provider, event("charge.refunded", charge(refunded=False, amount_refunded=100)))
    assert partial.status == "ignored"
    api_client.v1.checkout.sessions.list.assert_not_called()
    api_client.v1.checkout.sessions.list.return_value = {"data": []}  # not one of our checkouts
    e = parse(provider, event("charge.refunded", charge()))
    assert (e.status, e.provider_order_id) == ("refunded", None)  # billing records it as unknown_order
    api_client.v1.checkout.sessions.list.side_effect = stripe.APIConnectionError("down")
    with pytest.raises(PaymentError):  # the webhook fails, so Stripe sends it again
        parse(provider, event("charge.refunded", charge()))


# ---- calls to Stripe ---------------------------------------------------------------- #


def test_create_checkout_sends_the_right_parameters(provider, api_client):
    before = time.time()
    session = provider.create_checkout(order_id="order-1", product=PRODUCT, redirect_url=REDIRECT)
    assert (session.checkout_id, session.provider_order_id) == ("cs_test_1", "cs_test_1")
    assert session.url == "https://checkout.stripe.com/c/pay/cs_test_1"

    kwargs = api_client.v1.checkout.sessions.create.call_args.kwargs
    assert kwargs["options"] == {"idempotency_key": "order-1"}
    params = kwargs["params"]
    assert params["mode"] == "payment"
    assert params["client_reference_id"] == "order-1" and params["metadata"] == {"order_id": "order-1"}
    assert params["line_items"] == [{
        "quantity": 1,
        "price_data": {"currency": "aud", "unit_amount": 400,
                       "product_data": {"name": "AGLC4 citation check: one document"}},
    }]
    assert params["success_url"] == REDIRECT  # carries our own session id, no {CHECKOUT_SESSION_ID}
    assert params["cancel_url"] == "https://aglc.example/?session=abc123"  # not "confirming payment"
    assert before + 3500 < params["expires_at"] < time.time() + 3700
    assert "payment_method_types" not in params  # wallets come with Checkout
    assert params["payment_intent_data"]["metadata"] == {"order_id": "order-1"}


def test_create_checkout_failures_are_payment_errors(provider, api_client):
    api_client.v1.checkout.sessions.create.side_effect = stripe.APIConnectionError("no route")
    with pytest.raises(PaymentError, match="Stripe request failed"):
        provider.create_checkout(order_id="order-1", product=PRODUCT, redirect_url=REDIRECT)
    api_client.v1.checkout.sessions.create.side_effect = None
    api_client.v1.checkout.sessions.create.return_value = session_object(id="cs_test_1", url=None)
    with pytest.raises(PaymentError):
        provider.create_checkout(order_id="order-2", product=PRODUCT, redirect_url=REDIRECT)


def test_missing_settings_fail_clearly(monkeypatch):
    with pytest.raises(PaymentError, match="STRIPE_SECRET_KEY"):
        StripeProvider().create_checkout(order_id="o", product=PRODUCT, redirect_url=REDIRECT)
    with pytest.raises(WebhookSignatureError, match="STRIPE_WEBHOOK_SECRET"):
        StripeProvider().parse_webhook(body=b"{}", headers={}, url="")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_x")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    p = StripeProvider()
    assert (p.api_key, p.webhook_secret) == ("sk_test_x", SECRET)
    assert p.client.checkout.sessions  # the real SDK client


def test_retrieve_maps_statuses(provider, api_client):
    get = api_client.v1.checkout.sessions.retrieve
    get.return_value = session_object(**completed_session())
    status = provider.retrieve("cs_test_1")
    assert (status.paid, status.amount, status.currency, status.payment_id) == (True, 400, "AUD", "pi_1")
    get.assert_called_with("cs_test_1")
    get.return_value = session_object(**completed_session(status="open", payment_status="unpaid", payment_intent=None))
    assert provider.retrieve("cs_test_1").paid is False  # pending
    get.return_value = session_object(**completed_session(status="expired", payment_status="unpaid", payment_intent=None))
    assert provider.retrieve("cs_test_1").paid is False  # expired
    get.return_value = session_object(**completed_session(payment_intent={"id": "pi_9"}))  # expanded
    assert provider.retrieve("cs_test_1").payment_id == "pi_9"
    get.side_effect = stripe.APIConnectionError("down")
    with pytest.raises(PaymentError):
        provider.retrieve("cs_test_1")


def test_refund_is_idempotent_by_key(provider, api_client):
    api_client.v1.refunds.create.return_value = stripe.Refund.construct_from({"id": "re_1", "status": "succeeded"}, "k")
    refund = provider.refund(payment_id="pi_1", amount=400, currency="AUD", reason="Automatic refund: gone",
                             idempotency_key="refund-order-1")
    assert (refund.refund_id, refund.status) == ("re_1", "succeeded")
    kwargs = api_client.v1.refunds.create.call_args.kwargs
    assert kwargs["params"]["payment_intent"] == "pi_1" and kwargs["params"]["amount"] == 400
    assert kwargs["options"] == {"idempotency_key": "refund-order-1"}
    api_client.v1.refunds.create.side_effect = stripe.InvalidRequestError("already refunded", "payment_intent")
    with pytest.raises(PaymentError):
        provider.refund(payment_id="pi_1", amount=400, currency="AUD", reason="", idempotency_key="k")


def test_cancel_checkout_expires_the_session_and_swallows_already_closed(provider, api_client):
    expire = api_client.v1.checkout.sessions.expire
    provider.cancel_checkout("cs_test_1")
    expire.assert_called_once_with("cs_test_1")
    expire.side_effect = stripe.InvalidRequestError(
        "Only Checkout Sessions with a status in open can be expired. This one is expired.", "id")
    provider.cancel_checkout("cs_test_1")  # already expired or completed: nothing to do
    expire.side_effect = stripe.APIConnectionError("down")
    with pytest.raises(PaymentError):  # anything else is still reported (billing logs it)
        provider.cancel_checkout("cs_test_1")


def test_sdk_client_is_built_with_a_timeout_and_retries():
    p = StripeProvider(api_key="sk_test_x")
    assert p.client is not None  # builds the SDK client
    assert p._client._requestor._options.max_network_retries == 2


# ---- end to end through the API ----------------------------------------------------- #


@pytest.fixture
def stripe_api(monkeypatch, tmp_path, api_client):
    """AGLC_PAYMENTS=stripe with a mocked Stripe client and the fake LLM."""
    monkeypatch.setenv("AGLC_PAYMENTS", "stripe")
    monkeypatch.setenv("AGLC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("AGLC_PUBLIC_URL", "https://aglc.example")
    reset_payment_providers()
    billing._last_checked.clear()
    billing._semaphore = None
    get_payment_provider("stripe", client=api_client, webhook_secret=SECRET)
    api_client.v1.refunds.create.return_value = stripe.Refund.construct_from({"id": "re_1", "status": "succeeded"}, "k")
    with mock.patch("aglc.pipeline.get_provider",
                    side_effect=lambda *a, **k: get_provider("fake:e2e", responses=[EXTRACTION])):
        yield TestClient(api.app)
    reset_payment_providers()


def _process(client):
    return client.post("/api/process", files={"file": ("essay.docx", ESSAY.read_bytes(), DOCX)})


def _checkout(client, sid):
    r = client.post("/api/checkout", json={"session_id": sid})
    assert r.status_code == 200, r.text
    return r.json()


def _webhook(client, payload):
    body, headers = signed(payload)
    return client.post("/api/webhooks/stripe", content=body, headers=headers)


def test_checkout_webhook_download_end_to_end(stripe_api, api_client):
    client = stripe_api
    assert client.get("/api/config").json()["provider"] == "stripe"
    sid = _process(client).json()["id"]
    assert client.get(f"/api/download/{sid}").status_code == 402

    first = _checkout(client, sid)
    assert first["checkout_url"] == "https://checkout.stripe.com/c/pay/cs_test_1"
    params = api_client.v1.checkout.sessions.create.call_args.kwargs["params"]
    assert params["success_url"] == f"https://aglc.example/?paid=1&session={sid}"
    assert params["client_reference_id"] == first["order_id"]
    assert api_client.v1.checkout.sessions.create.call_args.kwargs["options"] == {"idempotency_key": first["order_id"]}
    assert get_store().order(first["order_id"])["provider_order_id"] == "cs_test_1"
    assert _checkout(client, sid) == first  # still payable: reused, not recreated
    assert api_client.v1.checkout.sessions.create.call_count == 1

    # A forged webhook does nothing; a paid session for another order is unknown; the real one unlocks.
    assert client.post("/api/webhooks/stripe", content=b"{}", headers={SIGNATURE_HEADER: "t=1,v1=0"}).status_code == 400
    assert _webhook(client, event("checkout.session.completed", completed_session(id="cs_other"), "evt_x")).json()[
        "outcome"] == "unknown_order"
    assert client.get(f"/api/download/{sid}").status_code == 402
    r = _webhook(client, event("checkout.session.completed", completed_session(), "evt_paid"))
    assert r.json()["outcome"] == "unlocked"
    assert _webhook(client, event("checkout.session.completed", completed_session(), "evt_paid")).json()[
        "outcome"] == "duplicate"
    assert get_store().order(first["order_id"])["payment_id"] == "pi_1"
    assert client.get(f"/api/entitlement/{sid}").json()["status"] == "unlocked"
    assert client.get(f"/api/download/{sid}").status_code == 200

    # A refund from the Stripe dashboard locks the document again.
    api_client.v1.checkout.sessions.list.return_value = {"data": [{"id": "cs_test_1"}]}
    assert _webhook(client, event("charge.refunded", charge(), "evt_refund")).json()["outcome"] == "refunded"
    assert get_store().order(first["order_id"])["status"] == "refunded"
    assert client.get(f"/api/download/{sid}").status_code == 402


def test_expired_stripe_session_is_replaced_not_reused(stripe_api, api_client):
    client = stripe_api
    sid = _process(client).json()["id"]
    first = _checkout(client, sid)
    api_client.v1.checkout.sessions.create.return_value = session_object(
        id="cs_test_2", url="https://checkout.stripe.com/c/pay/cs_test_2")
    old = "2020-01-01T00:00:00+00:00"
    with get_store().transaction() as conn:
        conn.execute("UPDATE orders SET created_at = ? WHERE id = ?", (old, first["order_id"]))
    second = _checkout(client, sid)
    assert second["order_id"] != first["order_id"]
    assert second["checkout_url"].endswith("cs_test_2")
    # The old session can no longer be paid, but if it somehow was, it would still be applied.
    assert get_store().order(first["order_id"])["status"] == "pending"


def test_late_webhook_is_reconciled_from_the_session(stripe_api, api_client):
    client = stripe_api
    sid = _process(client).json()["id"]
    _checkout(client, sid)
    assert client.get(f"/api/entitlement/{sid}").json()["status"] == "pending"
    billing._last_checked.clear()
    api_client.v1.checkout.sessions.retrieve.return_value = session_object(**completed_session())
    assert client.get(f"/api/entitlement/{sid}").json()["unlocked"] is True
    api_client.v1.checkout.sessions.retrieve.assert_called_with("cs_test_1")


def test_missing_files_refund_the_payment_intent(stripe_api, api_client):
    client = stripe_api
    sid = _process(client).json()["id"]
    order_id = _checkout(client, sid)["order_id"]
    shutil.rmtree(billing.sessions_dir() / sid)
    r = _webhook(client, event("checkout.session.completed", completed_session(), "evt_paid"))
    assert r.json()["outcome"] == "files_missing"
    kwargs = api_client.v1.refunds.create.call_args.kwargs
    assert kwargs["params"]["payment_intent"] == "pi_1" and kwargs["params"]["amount"] == 400
    assert kwargs["options"] == {"idempotency_key": f"refund-{order_id}"}
    assert get_store().order(order_id)["status"] == "refunded"


def test_legal_pages_name_the_configured_provider(monkeypatch):
    client = TestClient(api.app)
    for path in ("/privacy", "/terms", "/refunds"):
        assert "Square" in client.get(path).text and "Stripe" not in client.get(path).text, path
    monkeypatch.setenv("AGLC_PAYMENTS", "stripe")
    for path in ("/privacy", "/terms", "/refunds"):
        html = client.get(path).text
        assert "Stripe" in html and "Square" not in html and "{{payment_provider}}" not in html, path
    monkeypatch.setenv("AGLC_PAYMENTS", "fake")
    assert "Square" in client.get("/terms").text
