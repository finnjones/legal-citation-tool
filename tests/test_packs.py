"""Prices by document size, credit packs and their codes (aglc/billing.py, aglc/credits.py),
with the offline fake payment provider and the fake email sender."""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from aglc import api, billing, credits, guards, mailer, retention
from aglc.store import get_store

from test_billing import _checkout, _process, _provider_order_id, _webhook, client, fake, paid  # noqa: F401


def _set_footnotes(sid, n):
    with get_store().transaction() as conn:
        conn.execute("UPDATE documents SET footnote_count = ? WHERE session_id = ?", (n, sid))


def _buy_pack(client, fake, product="pack3", session_id=None, email=None, deliver=True):
    body = {"product": product} | ({"session_id": session_id} if session_id else {})
    r = client.post("/api/checkout", json=body)
    assert r.status_code == 200, r.text
    order_id = r.json()["order_id"]
    poid = _provider_order_id(order_id)
    fake.pay(poid, email=email)
    outcome = _webhook(client, fake, poid)[0].json()["outcome"] if deliver else None
    return order_id, poid, outcome


def _code(client, order_id, received=True):
    """The pack as the buying browser's page sees it, confirming it has the code."""
    r = client.get(f"/api/pack/{order_id}")
    assert r.status_code == 200, r.text
    if received and "code" in r.json():
        assert client.post(f"/api/pack/{order_id}/received").json() == {"ok": True}
    return r.json()


@pytest.fixture
def emails(monkeypatch):
    monkeypatch.setenv("AGLC_EMAIL", "fake")
    mailer.reset()
    yield mailer.get_sender()
    mailer.reset()


# ---- tiers ---------------------------------------------------------------------- #


def test_tier_follows_the_footnote_count():
    assert billing.tier_for(1) == billing.tier_for(150) == "essay"
    assert billing.tier_for(151) == billing.tier_for(400) == "long"
    assert billing.TIER_CREDITS == {"essay": 1, "long": 2}


def test_a_long_document_is_charged_as_long_whatever_the_page_asks(paid, client):
    sid = _process(client).json()["id"]
    _set_footnotes(sid, 200)
    r = client.post("/api/checkout", json={"session_id": sid, "product": "essay"})  # asking for the cheaper tier
    order = get_store().order(r.json()["order_id"])
    assert (order["product"], order["amount"]) == ("long", 900)
    preview = client.get(f"/api/results/{sid}").json()
    assert client.get(f"/api/download/{sid}").json()["detail"] == "Unlock this document (A$9) to download it."
    assert preview["tier"] == "essay"  # the preview's own count: 10 footnotes (the row was edited above)


def test_preview_shows_its_tier_and_price(paid, client):
    data = _process(client).json()
    assert (data["tier"], data["credits_needed"], data["price"]["display"]) == ("essay", 1, "A$5")


def test_unknown_product_and_pack_without_document(paid, client):
    assert client.post("/api/checkout", json={"product": "free"}).status_code == 422
    assert client.post("/api/checkout", json={}).status_code == 422
    r = client.post("/api/checkout", json={"product": "pack10"})
    order = get_store().order(r.json()["order_id"])
    assert (order["session_id"], order["product"], order["amount"]) == (None, "pack10", 3500)


# ---- packs ---------------------------------------------------------------------- #


def test_buying_a_pack_shows_its_code_once_and_keeps_only_a_hash(paid, client, fake):
    order_id, poid, outcome = _buy_pack(client, fake)
    assert outcome == "pack_granted"
    first = _code(client, order_id)
    assert first["status"] == "paid" and first["credits"] == 3 and first["credits_remaining"] == 3
    code = first["code"]
    assert re.fullmatch(r"AFC-[23456789ABCDEFGHJKMNPQRSTWXYZ]{4}(-[23456789ABCDEFGHJKMNPQRSTWXYZ]{4}){2}", code)
    assert "code" not in _code(client, order_id)  # forgotten once the page said it had it
    raw = get_store().path.read_bytes() + get_store().path.with_name("aglc.db-wal").read_bytes()
    assert code.encode() not in raw and code.replace("-", "").encode() not in raw
    with sqlite3.connect(get_store().path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM code_pickup").fetchone()[0] == 0
        ledger = conn.execute("SELECT delta, reason, payment_id, order_id FROM credit_ledger").fetchall()
    assert ledger == [(3, "grant", fake.checkouts[poid].payment_id, order_id)]
    assert client.post("/api/credits", json={"code": code.lower().replace("-", " ")}).json()["credits_remaining"] == 3


def test_replayed_pack_webhook_grants_once(paid, client, fake):
    order_id, poid, _ = _buy_pack(client, fake)
    r, body, headers = _webhook(client, fake, poid)
    assert r.json()["outcome"] == "already_paid"  # a new event for the same payment
    assert client.post("/api/webhooks/fake", content=body, headers=headers).json()["outcome"] == "duplicate"
    with sqlite3.connect(get_store().path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM credit_codes").fetchone()[0] == 1
        assert conn.execute("SELECT SUM(delta) FROM credit_ledger").fetchone()[0] == 3


def test_late_pack_webhook_is_reconciled_by_the_success_page(paid, client, fake):
    order_id, poid, _ = _buy_pack(client, fake, deliver=False)
    data = _code(client, order_id)
    assert data["status"] == "paid" and data["code"]
    assert _webhook(client, fake, poid)[0].json()["outcome"] == "already_paid"


def test_unknown_pack_order_is_404(paid, client):
    assert client.get("/api/pack/nope").status_code == 404
    assert client.get(f"/api/pack/{'0' * 32}").status_code == 404
    sid = _process(client).json()["id"]
    assert client.get(f"/api/pack/{_checkout(client, sid)['order_id']}").status_code == 404  # a document's order


def test_redeeming_unlocks_and_spends_by_tier(paid, client, fake):
    order_id, _, _ = _buy_pack(client, fake)
    code = _code(client, order_id)["code"]
    sid = _process(client).json()["id"]
    assert client.get(f"/api/download/{sid}").status_code == 402
    r = client.post("/api/redeem", json={"session_id": sid, "code": code})
    assert r.json() == {"unlocked": True, "credits_spent": 1, "credits_remaining": 2}
    assert client.get(f"/api/results/{sid}").json()["locked"] is False
    assert client.get(f"/api/download/{sid}").status_code == 200
    again = client.post("/api/redeem", json={"session_id": sid, "code": code}).json()
    assert again == {"unlocked": True, "credits_spent": 0, "credits_remaining": 2}  # already unlocked: free

    long_sid = _process(client).json()["id"]
    _set_footnotes(long_sid, 300)
    assert client.post("/api/redeem", json={"session_id": long_sid, "code": code}).json()["credits_spent"] == 2
    third = _process(client).json()["id"]
    r = client.post("/api/redeem", json={"session_id": third, "code": code})
    assert r.status_code == 402 and "1 credit" in r.json()["detail"]
    assert get_store().document(third)["unlocked_at"] is None
    with sqlite3.connect(get_store().path) as conn:
        spends = conn.execute("SELECT delta, session_id FROM credit_ledger WHERE reason = 'spend' ORDER BY id").fetchall()
    assert spends == [(-1, sid), (-2, long_sid)]


def test_bad_codes_are_refused(paid, client):
    sid = _process(client).json()["id"]
    assert client.post("/api/redeem", json={"session_id": sid, "code": "hello"}).status_code == 400
    r = client.post("/api/redeem", json={"session_id": sid, "code": credits.new_code()})
    assert r.status_code == 404 and get_store().document(sid)["unlocked_at"] is None
    assert client.post("/api/credits", json={"code": credits.new_code()}).status_code == 404


def test_code_normalising():
    code = credits.new_code()
    body = code.removeprefix("AFC-")
    assert credits.normalise(code.lower()) == credits.normalise(body.replace("-", "")) == code.replace("-", "")
    assert credits.code_hash(f" {code.lower()} ") == credits.code_hash(code)
    assert credits.normalise("AFC-0000-1111-IIII") is None and credits.normalise("") is None


def test_concurrent_spends_never_overspend(paid, client, fake, monkeypatch):
    monkeypatch.setenv("AGLC_FREE_PER_DAY", "50")
    order_id, _, _ = _buy_pack(client, fake)  # 3 credits
    code = _code(client, order_id)["code"]
    sids = [_process(client).json()["id"] for _ in range(6)]
    results, barrier = [], threading.Barrier(len(sids) + 2)

    def spend(sid):
        barrier.wait()
        try:
            results.append(billing.redeem(billing.RedeemRequest(session_id=sid, code=code))["credits_spent"])
        except billing.HTTPException as e:
            results.append(e.status_code)

    # six documents, and the first one twice more at the same moment
    threads = [threading.Thread(target=spend, args=(sid,)) for sid in sids + sids[:2]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(1 for r in results if r == 1) == 3
    assert all(r in (0, 1, 402) for r in results)
    with sqlite3.connect(get_store().path) as conn:
        assert conn.execute("SELECT credits_remaining FROM credit_codes").fetchone()[0] == 0
        assert conn.execute("SELECT SUM(delta) FROM credit_ledger").fetchone()[0] == 0
        unlocked = conn.execute("SELECT COUNT(*) FROM documents WHERE unlocked_at IS NOT NULL").fetchone()[0]
    assert unlocked == 3


def test_a_pack_bought_from_the_unlock_screen_unlocks_that_document(paid, client, fake):
    sid = _process(client).json()["id"]
    r = client.post("/api/checkout", json={"session_id": sid, "product": "pack3"})
    poid = _provider_order_id(r.json()["order_id"])
    assert get_payment_redirect(fake, poid).endswith(f"/?paid=1&session={sid}&pack={r.json()['order_id']}")
    fake.pay(poid)
    assert _webhook(client, fake, poid)[0].json()["outcome"] == "pack_unlocked"
    data = _code(client, r.json()["order_id"])
    assert data["unlocked"] is True and data["credits_remaining"] == 2 and data["session_id"] == sid
    assert client.get(f"/api/download/{sid}").status_code == 200


def get_payment_redirect(fake, poid):
    return fake.checkouts[poid].redirect_url


def test_a_pack_for_a_deleted_document_keeps_all_its_credits(paid, client, fake):
    sid = _process(client).json()["id"]
    r = client.post("/api/checkout", json={"session_id": sid, "product": "pack3"})
    poid = _provider_order_id(r.json()["order_id"])
    shutil.rmtree(billing.sessions_dir() / sid)
    fake.pay(poid)
    assert _webhook(client, fake, poid)[0].json()["outcome"] == "pack_granted"
    assert _code(client, r.json()["order_id"])["credits_remaining"] == 3
    assert fake.checkouts[poid].refunds == []  # nothing to refund: the credits are kept


def test_credits_come_back_when_an_unlocked_documents_files_are_gone(paid, client, fake):
    order_id, _, _ = _buy_pack(client, fake)
    code = _code(client, order_id)["code"]
    sid = _process(client).json()["id"]
    client.post("/api/redeem", json={"session_id": sid, "code": code})
    (billing.sessions_dir() / sid / "output.docx").unlink()
    assert client.get(f"/api/download/{sid}").status_code == 410
    assert client.post("/api/credits", json={"code": code}).json()["credits_remaining"] == 3
    assert client.get(f"/api/download/{sid}").status_code == 402


# ---- refunds -------------------------------------------------------------------- #


def test_refunding_a_pack_removes_its_unspent_credits(paid, client, fake):
    order_id, poid, _ = _buy_pack(client, fake)
    code = _code(client, order_id)["code"]
    sid = _process(client).json()["id"]
    client.post("/api/redeem", json={"session_id": sid, "code": code})
    assert _webhook(client, fake, poid, status="refunded")[0].json()["outcome"] == "pack_refunded"
    assert client.post("/api/credits", json={"code": code}).json() == {"credits_remaining": 0, "refunded": True}
    assert client.get(f"/api/download/{sid}").status_code == 200  # already unlocked: stays unlocked
    other = _process(client).json()["id"]
    r = client.post("/api/redeem", json={"session_id": other, "code": code})
    assert r.status_code == 402 and "refunded" in r.json()["detail"]
    with sqlite3.connect(get_store().path) as conn:
        rows = conn.execute("SELECT delta, reason FROM credit_ledger ORDER BY id").fetchall()
    assert rows == [(3, "grant"), (-1, "spend"), (-2, "refund")]
    assert get_store().order(order_id)["status"] == "refunded"
    assert _webhook(client, fake, poid, status="refunded")[0].json()["outcome"] == "already_refunded"


def test_a_partial_refund_removes_a_packs_credits_but_not_a_documents_unlock(paid, client, fake):
    order_id, poid, _ = _buy_pack(client, fake)
    assert _webhook(client, fake, poid, status="refunded", full=False)[0].json()["outcome"] == "pack_refunded"
    assert _code(client, order_id)["credits_remaining"] == 0

    sid = _process(client).json()["id"]
    doc_order = _checkout(client, sid)["order_id"]
    doc_poid = _provider_order_id(doc_order)
    fake.pay(doc_poid)
    _webhook(client, fake, doc_poid)
    assert _webhook(client, fake, doc_poid, status="refunded", full=False)[0].json()["outcome"] == "partial_refund"
    assert client.get(f"/api/download/{sid}").status_code == 200


def test_a_refund_before_the_code_is_collected_forgets_it(paid, client, fake):
    order_id, poid, _ = _buy_pack(client, fake)
    _webhook(client, fake, poid, status="refunded")
    data = _code(client, order_id)
    assert data["status"] == "refunded" and "code" not in data and data["credits_remaining"] == 0


# ---- email ---------------------------------------------------------------------- #


def test_the_code_is_emailed_once_when_email_is_on(paid, client, fake, emails):
    assert client.get("/api/config").json()["email_codes"] is True
    order_id, poid, _ = _buy_pack(client, fake, email="student@example.edu")
    assert len(emails.sent) == 1 and emails.sent[0].to == "student@example.edu"
    data = _code(client, order_id)
    assert data["code"] in emails.sent[0].text and data["emailed"] is True
    _webhook(client, fake, poid)  # a later event for the same payment
    assert len(emails.sent) == 1


def test_no_email_without_an_address_or_a_sender(paid, client, fake, emails, monkeypatch):
    order_id, _, _ = _buy_pack(client, fake)  # the checkout collected no address
    assert emails.sent == [] and _code(client, order_id)["emailed"] is False
    monkeypatch.delenv("AGLC_EMAIL")
    assert client.get("/api/config").json()["email_codes"] is False
    order_id, _, _ = _buy_pack(client, fake, email="student@example.edu")
    data = _code(client, order_id)
    assert data["emailed"] is False and data["email_enabled"] is False and emails.sent == []


def test_a_failing_email_never_fails_the_payment(paid, client, fake, emails):
    emails.fail = True
    order_id, _, outcome = _buy_pack(client, fake, email="student@example.edu")
    assert outcome == "pack_granted" and _code(client, order_id)["code"]


def test_codes_are_never_logged(paid, client, fake, emails, caplog):
    caplog.set_level(logging.DEBUG)
    order_id, _, _ = _buy_pack(client, fake, email="student@example.edu")
    code = _code(client, order_id)["code"]
    sid = _process(client).json()["id"]
    client.post("/api/redeem", json={"session_id": sid, "code": code})
    assert code not in caplog.text and "student@example.edu" not in caplog.text


def test_resend_sender_is_off_unless_configured(monkeypatch):
    mailer.reset()
    assert mailer.get_sender() is None
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    assert mailer.get_sender() is None  # needs a From address too
    monkeypatch.setenv("AGLC_EMAIL_FROM", "Aforecite <codes@example.com>")
    assert isinstance(mailer.get_sender(), mailer.ResendSender)


# ---- retention, logs and pages --------------------------------------------------- #


def test_uncollected_codes_are_forgotten_after_the_retention_window(paid, client, fake):
    order_id, _, _ = _buy_pack(client, fake)
    retention.sweep(None, at=datetime.now(timezone.utc) + timedelta(hours=25))
    data = _code(client, order_id)
    assert "code" not in data and data["credits_remaining"] == 3  # the credits are kept, the code isn't shown


def test_order_ids_are_redacted_in_the_access_log():
    oid = "0123456789abcdef0123456789abcdef"
    assert guards.redact_ids(f"GET /?paid=1&pack={oid} HTTP/1.1") == "GET /?paid=1&pack=01234567… HTTP/1.1"


def test_pages_show_every_price_from_the_server(monkeypatch):
    client = TestClient(api.app)
    home = client.get("/").text
    for product in billing.PRODUCTS.values():
        assert product.display in home
    terms = client.get("/terms").text
    assert "A$12 for 3" in terms and "A$35 for 10" in terms and "nothing renews" in terms
    refunds = client.get("/refunds").text
    assert "no refunds" not in refunds.lower() and "Australian Consumer Law" in refunds
    assert "unused credits" in refunds
    privacy = client.get("/privacy").text
    assert "one-way hash of the pack's code" in privacy and "We don't email codes" in privacy
    monkeypatch.setenv("AGLC_EMAIL", "fake")
    assert "through our email provider" in client.get("/privacy").text


# ---- the code goes only to the buyer's browser (review findings) -------------------- #


def test_only_the_buying_browser_can_collect_the_code(paid, client, fake):
    """Regression: GET /api/pack/{order_id} gave the code to whoever asked first, and the
    order id was in the app log and the return URL."""
    order_id, _, _ = _buy_pack(client, fake)
    stranger = TestClient(api.app)
    other = stranger.get(f"/api/pack/{order_id}").json()
    assert "code" not in other and other["code_elsewhere"] is True and other["status"] == "paid"
    assert stranger.post(f"/api/pack/{order_id}/received").status_code == 403
    assert "code" in client.get(f"/api/pack/{order_id}").json()  # still there for the buyer


def test_order_ids_are_not_in_the_app_log(paid, client, fake, caplog):
    caplog.set_level(logging.DEBUG)
    order_id, poid, _ = _buy_pack(client, fake)
    _webhook(client, fake, poid, status="refunded")
    assert order_id not in caplog.text and order_id[:8] in caplog.text


def test_the_redaction_filter_guards_the_app_log_too(caplog):
    guards.install_log_redaction()
    caplog.set_level(logging.INFO)
    logging.getLogger("aglc").info("order %s", "0123456789abcdef0123456789abcdef")
    assert "0123456789abcdef0123456789abcdef" not in caplog.text


def test_the_page_finds_its_pack_by_cookie(paid, client, fake):
    order_id, _, _ = _buy_pack(client, fake)
    latest = client.get("/api/pack/latest").json()
    assert latest["order_id"] == order_id and latest["code"]
    assert TestClient(api.app).get("/api/pack/latest").status_code == 404


def test_the_code_is_kept_until_the_page_confirms_it(paid, client, fake):
    """Regression: the code was deleted on the first GET, received or not."""
    order_id, _, _ = _buy_pack(client, fake)
    first = client.get(f"/api/pack/{order_id}").json()["code"]
    assert client.get(f"/api/pack/{order_id}").json()["code"] == first  # the first answer was lost: ask again
    client.post(f"/api/pack/{order_id}/received")
    assert "code" not in client.get(f"/api/pack/{order_id}").json()


def test_an_operator_can_reissue_a_lost_code(paid, client, fake):
    from typer.testing import CliRunner
    from aglc.cli import app as cli

    order_id, _, _ = _buy_pack(client, fake)
    old = _code(client, order_id)["code"]
    sid = _process(client).json()["id"]
    client.post("/api/redeem", json={"session_id": sid, "code": old})
    result = CliRunner().invoke(cli, ["reissue-code", order_id])
    assert result.exit_code == 0, result.output
    new = result.output.split()[0]
    assert new != old and credits.normalise(new)
    assert client.post("/api/credits", json={"code": old}).status_code == 404
    assert client.post("/api/credits", json={"code": new}).json()["credits_remaining"] == 2
    assert CliRunner().invoke(cli, ["reissue-code", "0" * 32]).exit_code == 1


def test_giving_credits_back_to_a_refunded_pack_writes_no_ledger_row(paid, client, fake):
    order_id, poid, _ = _buy_pack(client, fake)
    code = _code(client, order_id)["code"]
    sid = _process(client).json()["id"]
    client.post("/api/redeem", json={"session_id": sid, "code": code})
    _webhook(client, fake, poid, status="refunded")
    with get_store().transaction() as conn:
        code_id = conn.execute("SELECT id FROM credit_codes").fetchone()["id"]
        assert credits.give_back(conn, code_id, sid) == 0
    with sqlite3.connect(get_store().path) as conn:
        assert [r[0] for r in conn.execute("SELECT reason FROM credit_ledger ORDER BY id")] == ["grant", "spend", "refund"]



def test_the_return_page_asks_about_the_pack_that_was_paid_not_an_abandoned_one(paid, client, fake):
    """Regression: /api/pack/latest picked the newest order, so paying a 3-pack after opening
    (and abandoning) a 10-pack showed "payment not confirmed" and left the code uncollected."""
    three = client.post("/api/checkout", json={"product": "pack3"}).json()
    client.post("/api/checkout", json={"product": "pack10"})  # opened, then abandoned
    poid = _provider_order_id(three["order_id"])
    assert fake.checkouts[poid].redirect_url.endswith(f"/?paid=1&pack={three['order_id']}")
    fake.pay(poid)
    _webhook(client, fake, poid)
    assert client.get(f"/api/pack/{three['order_id']}").json()["code"]
    latest = client.get("/api/pack/latest").json()  # the fallback prefers a waiting code, then a paid pack
    assert latest["order_id"] == three["order_id"] and latest["code"]
    client.post(f"/api/pack/{three['order_id']}/received")
    assert client.get("/api/pack/latest").json()["order_id"] == three["order_id"]  # paid beats pending


def test_the_page_takes_the_order_id_out_of_the_address_before_analytics(monkeypatch):
    monkeypatch.setenv("AGLC_PLAUSIBLE_DOMAIN", "cite.example.com")
    html = TestClient(api.app).get("/").text
    strip = html.index("const PACK_ORDER")
    assert "history.replaceState" in html[strip:strip + 800]
    assert '<script defer data-domain="cite.example.com"' in html  # deferred: runs after the inline script
    assert html.index("const PACK_ORDER") < html.index("document.addEventListener(\"DOMContentLoaded\"")
