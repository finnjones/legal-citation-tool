"""Entitlements and free re-scans of a paid document (aglc/billing.py)."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from aglc import api, billing, fingerprint
from aglc.docx_io import read_footnotes
from aglc.store import MIGRATIONS, Store, get_store

from test_billing import DOCX, ESSAY, _checkout, _process, _provider_order_id, _webhook, client, fake, paid  # noqa: F401
from test_seen import NEW_TEXTS, SAMPLE_TEXTS, _docx

COUNTED = [t for t in SAMPLE_TEXTS if fingerprint.counts(fingerprint.normalise(t))]  # 8 of the 10


def _pay(client, fake):
    sid = _process(client).json()["id"]
    poid = _provider_order_id(_checkout(client, sid)["order_id"])
    fake.pay(poid)
    assert _webhook(client, fake, poid)[0].json()["outcome"] == "unlocked"
    return sid, poid


def _token(client, sid):
    r = client.post(f"/api/rescan-link/{sid}")
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _rescan(client, token, content=None, **data):
    return client.post("/api/process", data={"rescan_token": token, **data},
                       files={"file": ("revised.docx", content or ESSAY.read_bytes(), DOCX)})


def _ent(sid):
    with sqlite3.connect(get_store().path) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM entitlements WHERE session_id = ?", (sid,)).fetchone()


# ---- entitlements --------------------------------------------------------------------- #


def test_paying_creates_an_entitlement_with_the_documents_fingerprint(paid, client, fake):
    sid, poid = _pay(client, fake)
    ent = _ent(sid)
    assert (ent["tier"], ent["rescans_remaining"], ent["source"]) == ("essay", 3, get_store().orders_for(sid)[0]["id"])
    paid_at = datetime.fromisoformat(ent["paid_at"])
    assert datetime.fromisoformat(ent["expires_at"]) - paid_at == timedelta(days=billing.RESCAN_DAYS)
    hashes = set(json.loads(ent["fingerprint"]))
    assert set(get_store().fingerprint(sid)) < hashes  # as written, and as corrected
    assert get_store().document(sid)["entitlement_id"] == ent["id"] and ent["token_hash"] is None
    info = client.get(f"/api/results/{sid}").json()["rescan"]
    assert info == {"remaining": 3, "total": 3, "expires_at": ent["expires_at"], "tier": "essay", "active": True,
                    "session_id": sid}


def test_credits_create_an_entitlement_too(paid, client, fake):
    r = client.post("/api/checkout", json={"product": "pack3"})
    poid = _provider_order_id(r.json()["order_id"])
    fake.pay(poid)
    _webhook(client, fake, poid)
    code = client.get(f"/api/pack/{r.json()['order_id']}").json()["code"]
    sid = _process(client).json()["id"]
    client.post("/api/redeem", json={"session_id": sid, "code": code})
    ent = _ent(sid)
    assert ent["source"].startswith("credit:") and ent["rescans_remaining"] == 3 and ent["fingerprint"]


def test_documents_paid_for_before_entitlements_keep_working(tmp_path, monkeypatch, paid, client, fake):
    """A version-5 database with a paid document: the migration gives it an entitlement."""
    sid, _ = _pay(client, fake)
    path = get_store().path
    with sqlite3.connect(path) as conn:  # back to how a paid document looked before migration 6
        conn.execute("DROP TABLE entitlements")
        conn.execute("ALTER TABLE documents DROP COLUMN entitlement_id")
        conn.execute("ALTER TABLE documents DROP COLUMN seen_shown")
        conn.execute("DELETE FROM fingerprints")
        conn.execute("PRAGMA user_version = 5")
    store = Store(path)
    from aglc import store as store_module
    store_module._stores[path] = store
    ent = _ent(sid)
    doc = store.document(sid)
    assert doc["entitlement_id"] == ent["id"] and ent["source"] == doc["unlocked_by"]
    assert ent["expires_at"] == (datetime.fromisoformat(doc["unlocked_at"]) + timedelta(days=14)).isoformat()
    assert ent["fingerprint"] is None and ent["tier"] == "essay"
    assert client.get(f"/api/download/{sid}").status_code == 200
    data = client.get(f"/api/results/{sid}").json()
    assert data["locked"] is False and data["rescan"]["remaining"] == 3
    assert _ent(sid)["fingerprint"]  # filled in from the kept upload, so re-scans work
    assert _rescan(client, _token(client, sid)).json()["locked"] is False


def test_the_store_upgrades_from_version_1_with_entitlements(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        for statement in filter(str.strip, MIGRATIONS[0].split(";")):
            conn.execute(statement)
        conn.execute("PRAGMA user_version = 1")
        conn.execute("INSERT INTO documents (session_id, filename, day, created_at, unlocked_at, unlocked_by,"
                     " footnote_count) VALUES ('s', 'f', 'd', 'c', '2026-10-01T10:00:00+00:00', 'o1', 200)")
    store = Store(path)
    with store.read() as conn:
        ent = conn.execute("SELECT * FROM entitlements").fetchone()
    assert (ent["session_id"], ent["tier"], ent["expires_at"]) == ("s", "long", "2026-10-15T10:00:00+00:00")
    assert store.document("s")["kind"] == "free"


# ---- the re-scan token ------------------------------------------------------------------ #


def test_the_rescan_token_is_made_for_a_paid_document_and_kept_hashed(paid, client, fake):
    sid = _process(client).json()["id"]
    assert client.post(f"/api/rescan-link/{sid}").status_code == 402
    poid = _provider_order_id(_checkout(client, sid)["order_id"])
    fake.pay(poid)
    _webhook(client, fake, poid)
    first = _token(client, sid)
    assert len(first) >= 32
    wal = get_store().path.with_name("aglc.db-wal")
    raw = get_store().path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")
    assert first.encode() not in raw
    second = _token(client, sid)  # a new link replaces the old one
    assert second != first
    assert _rescan(client, first).json()["locked"] is True
    assert _rescan(client, second).json()["locked"] is False


# ---- re-scanning ---------------------------------------------------------------------------- #


def test_a_revised_essay_is_rescanned_in_full_for_free(paid, client, fake, monkeypatch):
    monkeypatch.setenv("AGLC_FREE_PER_DAY", "1")
    sid, _ = _pay(client, fake)
    token = _token(client, sid)
    assert _process(client).status_code == 200  # the day's free preview, used up
    calls = paid.call_count
    r = _rescan(client, token)
    data = r.json()
    assert r.status_code == 200 and data["locked"] is False and data["rescanned"] is True
    assert all("formatted" in f for f in data["footnotes"]) and data["bibliography"]
    assert paid.call_count == calls + 1
    assert data["rescan"]["remaining"] == 2 and data["rescan"]["session_id"] == sid
    assert client.get(f"/api/download/{data['id']}").status_code == 200
    assert get_store().orders_for(data["id"]) == []
    assert client.get(f"/api/results/{sid}").json()["rescan"]["remaining"] == 2


def test_a_revision_with_the_corrections_accepted_is_still_recognised(paid, client, fake, tmp_path):
    sid, _ = _pay(client, fake)
    full = json.loads((billing.sessions_dir() / sid / "result.json").read_text())
    corrected = [billing._plain(f["formatted_html"]) for f in full["footnotes"]]
    assert corrected != SAMPLE_TEXTS
    data = _rescan(client, _token(client, sid), _docx(tmp_path, corrected)).json()
    assert data["locked"] is False and data["rescanned"] is True


@pytest.mark.parametrize("paid_footnotes,new_footnotes,rescanned", [
    (5, 5, True),  # 50%: enough
    (5, 6, False),  # 45%
    (4, 0, False),  # 100%, but fewer than 5 footnotes in common
])
def test_rescan_overlap_threshold(paid, client, fake, tmp_path, paid_footnotes, new_footnotes, rescanned):
    sid, _ = _pay(client, fake)
    extra = NEW_TEXTS + ["Mabo v Queensland (No 1) (1988) 166 CLR 186.", "Re Wakim; Ex parte McNally (1999) 198 CLR 511."]
    content = _docx(tmp_path, COUNTED[:paid_footnotes] + extra[:new_footnotes])
    data = _rescan(client, _token(client, sid), content).json()
    assert (data["locked"] is False) is rescanned
    if not rescanned:
        assert "different essay" in data["rescan_note"] and _ent(sid)["rescans_remaining"] == 3


def test_a_different_essay_gets_the_normal_preview_and_a_note(paid, client, fake, tmp_path):
    sid, _ = _pay(client, fake)
    r = _rescan(client, _token(client, sid), _docx(tmp_path, NEW_TEXTS), progress="true")
    assert r.status_code == 202 and "different essay" in r.json()["rescan_note"]
    assert _ent(sid)["rescans_remaining"] == 3


def test_three_rescans_then_a_new_purchase(paid, client, fake):
    sid, _ = _pay(client, fake)
    token = _token(client, sid)
    for left in (2, 1, 0):
        assert _rescan(client, token).json()["rescan"]["remaining"] == left
    data = _rescan(client, token).json()
    assert data["locked"] is True and "used or have ended" in data["rescan_note"]


def test_expired_rescans_dont_work(paid, client, fake):
    sid, _ = _pay(client, fake)
    token = _token(client, sid)
    with get_store().transaction() as conn:
        conn.execute("UPDATE entitlements SET expires_at = ?", ((datetime.now(timezone.utc) - timedelta(minutes=1))
                                                                .isoformat(timespec="seconds"),))
    data = _rescan(client, token).json()
    assert data["locked"] is True and "ended" in data["rescan_note"]
    assert client.post(f"/api/rescan-link/{sid}").status_code == 410


def test_an_essay_rescan_doesnt_cover_a_long_document():
    fp = fingerprint.Fingerprint("d", tuple(f"h{i}" for i in range(10)))
    ent = {"id": "e", "session_id": "s", "revoked_at": None, "rescans_remaining": 3, "tier": "essay",
           "expires_at": "9999", "fingerprint": json.dumps(list(fp.hashes))}
    assert billing.choose_rescan([ent], fp, 150).entitlement_id == "e"
    refused = billing.choose_rescan([ent], fp, 151)
    assert refused.entitlement_id is None and "long document" in refused.note and "new document" in refused.note
    assert billing.choose_rescan([{**ent, "tier": "long"}], fp, 400).entitlement_id == "e"


def test_concurrent_rescans_never_take_more_than_are_left(paid, client, fake):
    sid, _ = _pay(client, fake)
    ent_id = _ent(sid)["id"]
    fp = billing.fingerprint_of(read_footnotes(ESSAY))
    visitor = billing.Visitor(ip_hash=None, anon_id="a" * 32, new_cookie=False)
    results, barrier = [], threading.Barrier(6)

    def go(i):
        barrier.wait()
        try:
            billing.start_rescan(f"00000000-0000-4000-8000-00000000000{i}", "r.docx", visitor, footnote_count=10,
                                 fp=fp, ent_id=ent_id)
            results.append("ok")
        except billing.HTTPException as e:
            results.append(e.status_code)

    threads = [threading.Thread(target=go, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results, key=str) == [429, 429, 429, "ok", "ok", "ok"]
    assert _ent(sid)["rescans_remaining"] == 0


def test_a_failed_rescan_gives_the_rescan_back(paid, client, fake):
    sid, _ = _pay(client, fake)
    token = _token(client, sid)
    works, paid.side_effect = paid.side_effect, RuntimeError("model down")
    assert _rescan(client, token).status_code == 500
    assert _ent(sid)["rescans_remaining"] == 3
    paid.side_effect = works


def test_a_refund_ends_the_rescans(paid, client, fake):
    sid, poid = _pay(client, fake)
    token = _token(client, sid)
    _webhook(client, fake, poid, status="refunded")
    assert _ent(sid)["revoked_at"] and _ent(sid)["rescans_remaining"] == 0
    assert _rescan(client, token).json()["locked"] is True
    assert client.post(f"/api/rescan-link/{sid}").status_code == 402


def test_rescans_and_free_rereads_are_separate(paid, client, fake):
    sid, _ = _pay(client, fake)
    token = _token(client, sid)
    data = _rescan(client, token).json()
    assert data["reruns_left"] == billing.MAX_RERUNS
    client.post(f"/api/rerun/{data['id']}")
    assert _ent(sid)["rescans_remaining"] == 2


def test_a_rescan_isnt_refused_as_a_seen_essay(paid, client, fake, monkeypatch):
    monkeypatch.delenv("AGLC_SEEN_OVERLAP")  # the seen check at its defaults
    sid, _ = _pay(client, fake)
    token = _token(client, sid)
    data = _rescan(client, token).json()
    assert data["locked"] is False and not data.get("seen")
    other = TestClient(api.app).post("/api/process", files={"file": ("e.docx", ESSAY.read_bytes(), DOCX)})
    assert other.status_code == 409 and other.json()["detail"]["seen"] is True  # without the token: seen


def test_rescan_tokens_are_never_logged(paid, client, fake, caplog):
    caplog.set_level(logging.DEBUG)
    sid, _ = _pay(client, fake)
    token = _token(client, sid)
    _rescan(client, token)
    assert token not in caplog.text


def test_pages_offer_the_rescans():
    client = TestClient(api.app)
    assert "3 free re-scans for 14 days" in client.get("/").text
    assert "re-scan" in client.get("/terms").text


def test_a_paid_documents_fingerprint_and_token_go_when_its_rescans_end(paid, client, fake):
    from aglc import retention

    sid, _ = _pay(client, fake)
    _token(client, sid)
    retention.sweep(None, at=datetime.now(timezone.utc) + timedelta(days=13))
    assert _ent(sid)["fingerprint"] and _ent(sid)["token_hash"]
    retention.sweep(None, at=datetime.now(timezone.utc) + timedelta(days=15))
    ent = _ent(sid)
    assert ent["fingerprint"] is None and ent["token_hash"] is None and ent["paid_at"]


def test_privacy_page_describes_the_rescan_record():
    text = TestClient(api.app).get("/privacy").text
    assert "one-way hash of your re-scan link" in text and "14 days after you pay" in text
