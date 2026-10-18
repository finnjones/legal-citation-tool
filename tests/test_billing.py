"""Pay per document (aglc/billing.py) with the offline fake payment provider.

The pipeline runs for real on the sample essay, with canned LLM output from the fake
LLM provider, so the preview is redacted from a genuine result."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from aglc import api, billing, pipeline
from aglc.llm import get_provider
from aglc.payments import WebhookSignatureError, get_payment_provider, reset_payment_providers
from aglc.payments.providers.square_provider import SIGNATURE_HEADER, SquareProvider, square_signature
from aglc.store import MIGRATIONS, get_store

FIXTURES = Path(__file__).parent / "fixtures"
ESSAY = FIXTURES / "sample_essay.docx"
EXTRACTION = (FIXTURES / "sample_essay_extraction.json").read_text()
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_real_process_docx = pipeline.process_docx


@pytest.fixture
def paid(monkeypatch, tmp_path):
    """Payments on with the fake provider, a fresh data dir, and the fake LLM."""
    monkeypatch.setenv("AGLC_PAYMENTS", "fake")
    monkeypatch.setenv("AGLC_DATA_DIR", str(tmp_path / "data"))
    reset_payment_providers()
    billing._last_checked.clear()
    billing._semaphore = None

    def process(src, dst, model, **kwargs):
        return _real_process_docx(src, dst, get_provider("fake:e2e", responses=[EXTRACTION]), **kwargs)

    with mock.patch("aglc.pipeline.process_docx", side_effect=process) as m:
        yield m
    reset_payment_providers()


@pytest.fixture
def client():
    return TestClient(api.app)  # one per test, so the anonymous cookie doesn't leak between tests


@pytest.fixture
def fake():
    return get_payment_provider("fake")


def _process(client, name="essay.docx"):
    return client.post("/api/process", files={"file": (name, ESSAY.read_bytes(), DOCX)})


def _checkout(client, session_id):
    r = client.post("/api/checkout", json={"session_id": session_id})
    assert r.status_code == 200, r.text
    return r.json()


def _provider_order_id(order_id):
    return get_store().order(order_id)["provider_order_id"]


def _webhook(client, fake, provider_order_id, **kwargs):
    body, headers = fake.signed_event(provider_order_id, **kwargs)
    return client.post("/api/webhooks/fake", content=body, headers=headers), body, headers


def _paid_session(client, fake):
    sid = _process(client).json()["id"]
    order = _checkout(client, sid)
    poid = _provider_order_id(order["order_id"])
    fake.pay(poid)
    return sid, order["order_id"], poid


# ---- off by default --------------------------------------------------------- #


def test_payments_off_by_default(client):
    assert client.get("/api/config").json() == {"payments": False}
    assert client.post("/api/checkout", json={"session_id": "x"}).status_code == 404
    assert client.post("/api/webhooks/fake", content=b"{}").status_code == 404


def test_config_reports_server_price(paid, client):
    cfg = client.get("/api/config").json()
    assert cfg["payments"] is True and cfg["provider"] == "fake"
    assert cfg["price"] == {"amount": 400, "currency": "AUD", "display": "A$4"}


# ---- the preview ------------------------------------------------------------ #


def test_process_returns_locked_preview(paid, client):
    r = _process(client)
    assert r.status_code == 200
    data = r.json()
    assert data["locked"] is True
    assert r.cookies.get(billing.ANON_COOKIE)

    full = json.loads((billing.sessions_dir() / data["id"] / "result.json").read_text())
    changed = [f for f in full["footnotes"] if f["changed"]]
    assert len(changed) > billing.PREVIEW_FULL  # the fixture is a meaningful test

    # Every footnote is listed (for its stamp); only the first 3 changed ones in full.
    assert [f["number"] for f in data["footnotes"]] == [f["number"] for f in full["footnotes"]]
    shown = [f for f in data["footnotes"] if f["changed"] and not f.get("locked")]
    assert [f["number"] for f in shown] == [f["number"] for f in changed[:3]]
    for f in data["footnotes"]:
        if f.get("locked"):
            assert set(f) == {"number", "changed", "locked"}
    assert data["locked_count"] == len(changed) - 3
    # All warnings; the bibliography is withheld but counted.
    assert data["warnings"] == full["warnings"]
    assert data["bibliography"] == [] and data["bibliography_entries"] > 0
    assert "Mabo" not in json.dumps(data["footnotes"][-1])


def test_download_is_402_until_paid(paid, client):
    sid = _process(client).json()["id"]
    r = client.get(f"/api/download/{sid}")
    assert r.status_code == 402
    assert client.get(f"/api/results/{sid}").json()["locked"] is True
    assert client.get(f"/api/entitlement/{sid}").json() == {"session_id": sid, "unlocked": False, "status": "none"}


# ---- checkout -> webhook -> download ---------------------------------------- #


def test_checkout_webhook_download_happy_path(paid, client, fake):
    sid = _process(client).json()["id"]
    order = _checkout(client, sid)
    assert order["checkout_url"].startswith("/api/fake-checkout/")
    poid = _provider_order_id(order["order_id"])
    assert get_store().order(order["order_id"])["status"] == "pending"
    assert client.get(f"/api/entitlement/{sid}").json()["status"] == "pending"

    fake.pay(poid)
    r, _, _ = _webhook(client, fake, poid)
    assert r.json() == {"ok": True, "outcome": "unlocked"}

    assert client.get(f"/api/entitlement/{sid}").json()["unlocked"] is True
    results = client.get(f"/api/results/{sid}").json()
    assert results["locked"] is False and results["bibliography"]
    assert all("formatted_html" in f for f in results["footnotes"])
    d = client.get(f"/api/download/{sid}")
    assert d.status_code == 200 and d.content[:2] == b"PK"
    assert "essay.aglc.docx" in d.headers["content-disposition"]
    assert get_store().order(order["order_id"])["status"] == "paid"


def test_fake_checkout_page_pays_and_redirects(paid, client, fake):
    sid = _process(client).json()["id"]
    url = _checkout(client, sid)["checkout_url"]
    assert "Test checkout" in client.get(url).text
    r = client.post(f"{url}/pay", data={"deliver": "1"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith(f"/?paid=1&session={sid}")
    assert client.get(f"/api/entitlement/{sid}").json()["unlocked"] is True


def test_checkout_price_comes_from_server(paid, client):
    sid = _process(client).json()["id"]
    r = client.post("/api/checkout", json={"session_id": sid, "amount": 1, "currency": "USD"})
    order = get_store().order(r.json()["order_id"])
    assert (order["amount"], order["currency"]) == (400, "AUD")


def test_checkout_reuses_pending_link(paid, client):
    sid = _process(client).json()["id"]
    assert _checkout(client, sid) == _checkout(client, sid)
    assert len(get_store().orders_for(sid)) == 1


def test_checkout_unknown_session(paid, client):
    assert client.post("/api/checkout", json={"session_id": "not-a-uuid"}).status_code == 422
    assert client.post("/api/checkout", json={"session_id": "00000000-0000-4000-8000-000000000000"}).status_code == 404


# ---- webhook safety ----------------------------------------------------------- #


def test_replayed_webhook_is_a_no_op(paid, client, fake):
    sid, order_id, poid = _paid_session(client, fake)
    r, body, headers = _webhook(client, fake, poid)
    assert r.json()["outcome"] == "unlocked"
    again = client.post("/api/webhooks/fake", content=body, headers=headers)
    assert again.status_code == 200 and again.json()["outcome"] == "duplicate"
    with sqlite3.connect(get_store().path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM webhook_events").fetchone()[0] == 1
    assert get_store().order(order_id)["status"] == "paid"
    assert fake.checkouts[poid].refunds == []


def test_bad_signature_is_rejected(paid, client, fake):
    sid, _, poid = _paid_session(client, fake)
    body, headers = fake.signed_event(poid)
    r = client.post("/api/webhooks/fake", content=body, headers={**headers, "x-fake-signature": "0" * 64})
    assert r.status_code == 400
    tampered = body.replace(b'"amount": 400', b'"amount": 401')
    assert client.post("/api/webhooks/fake", content=tampered, headers=headers).status_code == 400
    assert client.post("/api/webhooks/fake", content=body).status_code == 400  # unsigned
    assert get_store().document(sid)["unlocked_at"] is None


def test_webhook_for_another_provider_is_404(paid, client):
    assert client.post("/api/webhooks/square", content=b"{}").status_code == 404


def test_amount_mismatch_is_ignored(paid, client, fake):
    sid = _process(client).json()["id"]
    order_id = _checkout(client, sid)["order_id"]
    poid = _provider_order_id(order_id)
    r, _, _ = _webhook(client, fake, poid, amount=100)
    assert r.status_code == 200 and r.json()["outcome"] == "amount_mismatch"
    r, _, _ = _webhook(client, fake, poid, currency="USD")
    assert r.json()["outcome"] == "amount_mismatch"
    assert get_store().order(order_id)["status"] == "pending"
    assert client.get(f"/api/download/{sid}").status_code == 402


def test_unknown_order_is_acknowledged(paid, client, fake):
    sid = _process(client).json()["id"]
    poid = _provider_order_id(_checkout(client, sid)["order_id"])
    body, headers = fake.signed_event(poid)
    body = body.replace(poid.encode(), b"fake_order_nobody")
    r = client.post("/api/webhooks/fake", content=body, headers={**headers, "x-fake-signature": fake.sign(body)})
    assert r.status_code == 200 and r.json()["outcome"] == "unknown_order"


# ---- late webhook ------------------------------------------------------------- #


def test_late_webhook_is_reconciled(paid, client, fake):
    sid, order_id, poid = _paid_session(client, fake)  # paid, but no webhook yet
    assert client.get(f"/api/download/{sid}").status_code == 402
    assert client.get(f"/api/entitlement/{sid}").json()["unlocked"] is True
    assert client.get(f"/api/download/{sid}").status_code == 200
    assert get_store().order(order_id)["payment_id"] == fake.checkouts[poid].payment_id

    r, _, _ = _webhook(client, fake, poid)  # the webhook turns up after all
    assert r.json()["outcome"] == "already_paid"
    assert fake.checkouts[poid].refunds == []


# ---- automatic refunds -------------------------------------------------------- #


def test_refund_when_files_missing_at_payment(paid, client, fake):
    sid, order_id, poid = _paid_session(client, fake)
    shutil.rmtree(billing.sessions_dir() / sid)
    r, _, _ = _webhook(client, fake, poid)
    assert r.json()["outcome"] == "files_missing"
    order = get_store().order(order_id)
    assert order["status"] == "refunded" and order["refund_id"]
    assert len(fake.checkouts[poid].refunds) == 1
    assert client.get(f"/api/entitlement/{sid}").json() == {"session_id": sid, "unlocked": False, "status": "refunded"}
    assert client.get(f"/api/download/{sid}").status_code == 402


def test_refund_when_files_vanish_after_unlock(paid, client, fake):
    sid, order_id, poid = _paid_session(client, fake)
    _webhook(client, fake, poid)
    (billing.sessions_dir() / sid / "output.docx").unlink()
    assert client.get(f"/api/download/{sid}").status_code == 410
    assert get_store().order(order_id)["status"] == "refunded"
    assert len(fake.checkouts[poid].refunds) == 1
    assert client.get(f"/api/download/{sid}").status_code == 402  # locked again; refunded once only
    assert len(fake.checkouts[poid].refunds) == 1


def test_second_payment_for_same_document_is_refunded(paid, client, fake):
    sid, first, poid = _paid_session(client, fake)
    # A second checkout made before the first was confirmed, then paid as well.
    get_store().update_order(first, status="failed")
    second = _checkout(client, sid)["order_id"]
    get_store().update_order(first, status="pending")
    poid2 = _provider_order_id(second)
    fake.pay(poid2)
    assert _webhook(client, fake, poid)[0].json()["outcome"] == "unlocked"
    assert _webhook(client, fake, poid2)[0].json()["outcome"] == "duplicate_payment"
    assert get_store().order(second)["status"] == "refunded"
    assert client.get(f"/api/download/{sid}").status_code == 200


def test_failed_refund_is_recorded(paid, client, fake):
    sid, order_id, poid = _paid_session(client, fake)
    shutil.rmtree(billing.sessions_dir() / sid)
    fake.fail_refunds = True
    assert _webhook(client, fake, poid)[0].json()["outcome"] == "files_missing"
    assert get_store().order(order_id)["status"] == "refund_failed"


# ---- free-path limits --------------------------------------------------------- #


def test_free_quota_per_browser_returns_429(paid, client, monkeypatch):
    monkeypatch.setenv("AGLC_FREE_PER_DAY", "2")
    assert _process(client).status_code == 200
    assert _process(client).status_code == 200
    r = _process(client)
    assert r.status_code == 429 and "free previews" in r.json()["detail"]
    assert paid.call_count == 2  # refused before any LLM call


def test_free_quota_per_ip_survives_clearing_cookies(paid, monkeypatch):
    monkeypatch.setenv("AGLC_FREE_PER_DAY", "5")
    monkeypatch.setenv("AGLC_FREE_PER_IP_PER_DAY", "1")
    assert _process(TestClient(api.app)).status_code == 200
    assert _process(TestClient(api.app)).status_code == 429  # new browser, same address


def test_paid_documents_dont_use_up_the_free_quota(paid, client, fake, monkeypatch):
    monkeypatch.setenv("AGLC_FREE_PER_DAY", "1")
    sid, _, poid = _paid_session(client, fake)
    _webhook(client, fake, poid)
    assert _process(client).status_code == 200


def test_global_daily_cap_returns_429(paid, monkeypatch):
    monkeypatch.setenv("AGLC_FREE_GLOBAL_PER_DAY", "1")
    monkeypatch.setenv("AGLC_CLIENT_IP_HEADER", "X-Forwarded-For")
    assert TestClient(api.app).post(
        "/api/process", files={"file": ("a.docx", ESSAY.read_bytes(), DOCX)}, headers={"X-Forwarded-For": "1.1.1.1"}
    ).status_code == 200
    r = TestClient(api.app).post(
        "/api/process", files={"file": ("a.docx", ESSAY.read_bytes(), DOCX)}, headers={"X-Forwarded-For": "2.2.2.2"}
    )
    assert r.status_code == 429


def test_failed_runs_dont_count_against_the_person(paid, client, monkeypatch):
    monkeypatch.setenv("AGLC_FREE_PER_DAY", "1")
    works, paid.side_effect = paid.side_effect, RuntimeError("model down")
    assert _process(client).status_code == 500
    paid.side_effect = works
    assert _process(client).status_code == 200


def test_footnote_cap_returns_413_before_llm(paid, client, monkeypatch):
    monkeypatch.setenv("AGLC_MAX_FOOTNOTES", "5")
    r = _process(client)
    assert r.status_code == 413 and "10 footnotes" in r.json()["detail"]
    assert paid.call_count == 0


def test_concurrency_cap_returns_503(paid, client, monkeypatch):
    monkeypatch.setenv("AGLC_MAX_CONCURRENT", "1")
    with billing.processing_slot():
        r = _process(client)
    assert r.status_code == 503 and r.headers["retry-after"]
    assert paid.call_count == 0
    assert _process(client).status_code == 200


# ---- Square webhook verification ---------------------------------------------- #


def _square_event(status="COMPLETED"):
    return json.dumps({
        "merchant_id": "M1", "type": "payment.updated", "event_id": "evt-1",
        "data": {"type": "payment", "id": "pay-1", "object": {"payment": {
            "id": "pay-1", "order_id": "sq-order-1", "status": status,
            "amount_money": {"amount": 400, "currency": "AUD"},
        }}},
    }).encode()


def test_square_signature_check():
    url = "https://aglc.example/api/webhooks/square"
    sq = SquareProvider(signature_key="sig-key", webhook_url=url)
    body = _square_event()
    event = sq.parse_webhook(body=body, headers={SIGNATURE_HEADER: square_signature("sig-key", url, body)}, url="http://internal/")
    assert (event.event_id, event.status, event.provider_order_id, event.payment_id, event.amount, event.currency) == (
        "evt-1", "paid", "sq-order-1", "pay-1", 400, "AUD")
    with pytest.raises(WebhookSignatureError):  # signed for a different URL
        sq.parse_webhook(body=body, headers={SIGNATURE_HEADER: square_signature("sig-key", "http://x/", body)}, url=url)
    with pytest.raises(WebhookSignatureError):
        sq.parse_webhook(body=body + b" ", headers={SIGNATURE_HEADER: square_signature("sig-key", url, body)}, url=url)
    with pytest.raises(WebhookSignatureError):
        SquareProvider(signature_key="", webhook_url=url).parse_webhook(body=body, headers={}, url=url)
    pending = _square_event("APPROVED")
    assert sq.parse_webhook(body=pending, headers={SIGNATURE_HEADER: square_signature("sig-key", url, pending)},
                            url=url).status == "ignored"


def test_square_signature_matches_sdk_helper():
    helper = pytest.importorskip("square.utils.webhooks_helper")
    url, body = "https://aglc.example/api/webhooks/square", _square_event()
    assert helper.verify_signature(request_body=body.decode(), signature_header=square_signature("k", url, body),
                                   signature_key="k", notification_url=url)


def test_square_checkout_uses_order_reference():
    client = mock.MagicMock()
    client.checkout.payment_links.create.return_value.payment_link.configure_mock(
        id="link-1", url="https://square.link/u/abc", order_id="sq-order-1")
    sq = SquareProvider(client=client, location_id="LOC")
    session = sq.create_checkout(order_id="our-order", product=billing.PRODUCTS["document"], redirect_url="https://x/?paid=1")
    assert (session.url, session.provider_order_id) == ("https://square.link/u/abc", "sq-order-1")
    kwargs = client.checkout.payment_links.create.call_args.kwargs
    assert kwargs["idempotency_key"] == "our-order"
    assert kwargs["order"]["reference_id"] == "our-order" and kwargs["order"]["location_id"] == "LOC"
    assert kwargs["order"]["line_items"][0]["base_price_money"] == {"amount": 400, "currency": "AUD"}
    assert kwargs["checkout_options"]["redirect_url"] == "https://x/?paid=1"


# ---- store -------------------------------------------------------------------- #


def test_store_is_migrated_and_in_wal_mode(paid):
    store = get_store()
    with sqlite3.connect(store.path) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"orders", "documents", "webhook_events"} <= tables
    store._migrate(store._connect())  # idempotent
