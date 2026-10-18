"""Pre-launch hardening: the server picks the model, upload limits, retention, and the
smaller protections around them (aglc/guards.py, aglc/retention.py)."""

from __future__ import annotations

import io
import logging
import os
import time
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from aglc import api, billing, docx_io, guards, retention
from aglc.docx_io import UnsafeDocxError, read_footnotes
from aglc.store import get_store

from test_billing import DOCX, ESSAY, _checkout, _process, _provider_order_id, _webhook, client, fake, paid  # noqa: F401


def _upload(client, data: bytes, name="essay.docx", **form):
    return client.post("/api/process", files={"file": (name, data, DOCX)}, data=form)


def _docx_with(path: Path, replace: dict[str, bytes] | None = None, add: dict[str, bytes] | None = None) -> bytes:
    """The sample essay with some parts replaced or added."""
    out = io.BytesIO()
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            zout.writestr(info, (replace or {}).get(info.filename, zin.read(info.filename)))
        for name, data in (add or {}).items():
            zout.writestr(name, data)
    return out.getvalue()


# ---- 1. the model is the server's choice in paid mode ------------------------ #


def test_paid_mode_ignores_the_client_model(paid, client):
    r = _upload(client, ESSAY.read_bytes(), model="openrouter:some/very-expensive-model")
    assert r.status_code == 200, r.text
    assert paid.call_args_list and all(c.args[0] is None for c in paid.call_args_list)
    opts = (billing.sessions_dir() / r.json()["id"] / "options.json").read_text()
    assert "very-expensive" not in opts


def test_paid_rerun_uses_the_server_model_even_if_options_say_otherwise(paid, client):
    sid = _process(client).json()["id"]
    d = billing.sessions_dir() / sid
    (d / "options.json").write_text('{"model": "openrouter:some/very-expensive-model"}')
    # Make one footnote look unread so a re-run happens.
    import json
    full = json.loads((d / "result.json").read_text())
    full["warnings"].append({"footnote": 1, "message": "footnote 1: missing from LLM response; left unchanged"})
    (d / "result.json").write_text(json.dumps(full))
    with mock.patch("aglc.pipeline.process_docx", wraps=api.pipeline.process_docx) as run:
        assert client.post(f"/api/rerun/{sid}").status_code == 200
    assert run.call_args.args[2] is None


def test_providers_endpoint_is_hidden_in_paid_mode(paid, client):
    assert client.get("/api/providers").status_code == 404


def test_providers_endpoint_still_works_locally(client):
    assert client.get("/api/providers").status_code == 200


def test_local_mode_still_honours_the_model_field(client, monkeypatch):
    with mock.patch("aglc.pipeline.process_docx") as run:
        run.side_effect = RuntimeError("stop")
        _upload(client, ESSAY.read_bytes(), model="fake:x")
    assert run.call_args.args[2] == "fake:x"


# ---- 2. upload limits ----------------------------------------------------------- #


def test_declared_body_over_the_limit_is_refused_unread(client, monkeypatch):
    monkeypatch.setenv("AGLC_MAX_UPLOAD_MB", "1")
    with mock.patch("aglc.pipeline.process_docx") as run:
        r = _upload(client, b"PK" + b"\0" * (2 * 1024 * 1024))
    assert r.status_code == 413 and "1 MB" in r.json()["detail"]
    run.assert_not_called()


def test_streamed_body_over_the_limit_is_cut_off(client, monkeypatch):
    monkeypatch.setenv("AGLC_MAX_UPLOAD_MB", "1")

    def chunks():  # no Content-Length: counted as it arrives
        for _ in range(3):
            yield b"\0" * (1024 * 1024)

    r = client.post("/api/process", content=chunks(), headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 413


def test_file_just_over_the_limit_is_413_from_the_endpoint(paid, client, monkeypatch):
    monkeypatch.setenv("AGLC_MAX_UPLOAD_MB", "1")
    r = _upload(client, b"PK" + b"\0" * (1024 * 1024 + 1000))  # under the multipart slack
    assert r.status_code == 413
    assert not any(billing.sessions_dir().iterdir())  # nothing kept
    assert get_store().free_uses_today(ip_hash=None, anon_id=None)[2] == 0  # and nothing counted


def test_small_bodies_and_webhooks_pass(paid, client):
    assert _process(client).status_code == 200


def test_zip_bomb_by_total_size_is_refused(paid, client, monkeypatch):
    monkeypatch.setattr(docx_io, "MAX_UNCOMPRESSED", 2 * 1024 * 1024)
    bomb = _docx_with(ESSAY, add={"word/media/zeros.bin": b"\0" * (3 * 1024 * 1024)})
    assert len(bomb) < 100_000  # it really is small on the wire
    r = _upload(client, bomb)
    assert r.status_code == 400 and r.json()["detail"] == "That file isn't a valid Word (.docx) document."
    paid.assert_not_called()  # refused before any AI model call


def test_zip_bomb_by_entry_count_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(docx_io, "MAX_ENTRIES", 50)
    path = tmp_path / "many.docx"
    path.write_bytes(_docx_with(ESSAY, add={f"junk/{i}.xml": b"<a/>" for i in range(60)}))
    with pytest.raises(UnsafeDocxError):
        read_footnotes(path)


def test_real_limits_accept_the_sample_essay():
    assert read_footnotes(ESSAY)


XXE = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<!DOCTYPE w:footnotes [<!ENTITY xxe SYSTEM "file://%s">]>
<w:footnotes xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:footnote w:id="1"><w:p><w:r><w:t>&xxe;</w:t></w:r></w:p></w:footnote></w:footnotes>"""


def test_xml_with_external_entities_is_refused(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-VALUE")
    path = tmp_path / "xxe.docx"
    path.write_bytes(_docx_with(ESSAY, replace={"word/footnotes.xml": XXE % str(secret).encode()}))
    with pytest.raises(UnsafeDocxError):
        read_footnotes(path)


def test_parser_never_resolves_entities_even_before_the_dtd_check(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-VALUE")
    root = docx_io.etree.fromstring(XXE % str(secret).encode(), docx_io._XML_PARSER)
    assert "TOP-SECRET-VALUE" not in docx_io.etree.tostring(root).decode()


def test_billion_laughs_is_refused():
    lol = (b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
           + b"".join(b'<!ENTITY %s "%s">' % (bytes([98 + i]), (b"&%s;" % bytes([97 + i])) * 10) for i in range(8))
           + b']><l>&i;</l>')
    with pytest.raises((UnsafeDocxError, docx_io.etree.XMLSyntaxError)):  # both are a 400
        docx_io._parse_xml(lol)


# ---- 3. retention ---------------------------------------------------------------- #


def _age(session_id: str, hours: float, *, unlocked: float | None = None, orders: float | None = None) -> None:
    """Pretend a document (and optionally its unlock / its orders) happened `hours` ago."""
    def ago(h):
        return (datetime.now(timezone.utc) - timedelta(hours=h)).isoformat(timespec="seconds")
    with get_store().transaction() as conn:
        conn.execute("UPDATE documents SET created_at = ? WHERE session_id = ?", (ago(hours), session_id))
        if unlocked is not None:
            conn.execute("UPDATE documents SET unlocked_at = ? WHERE session_id = ? AND unlocked_at IS NOT NULL",
                         (ago(unlocked), session_id))
        if orders is not None:
            conn.execute("UPDATE orders SET created_at = ?, updated_at = ? WHERE session_id = ?",
                         (ago(orders), ago(orders), session_id))


def _sweep():
    return retention.sweep(None)


def test_config_reports_retention_for_the_privacy_page(client, monkeypatch):
    assert client.get("/api/config").json()["retention_hours"] == 24
    monkeypatch.setenv("AGLC_RETENTION_HOURS", "6")
    assert client.get("/api/config").json()["retention_hours"] == 6
    monkeypatch.setenv("AGLC_RETENTION_HOURS", "0")  # never below the minimum
    assert client.get("/api/config").json()["retention_hours"] == retention.MIN_HOURS


def test_unpaid_document_is_deleted_after_the_window(paid, client):
    sid = _process(client).json()["id"]
    assert _sweep() == 0
    _age(sid, 25)
    assert _sweep() == 1
    assert not (billing.sessions_dir() / sid).exists()
    doc = get_store().document(sid)
    assert doc["purged_at"] and doc["filename"] == ""
    assert client.get(f"/api/results/{sid}").status_code == 410
    assert client.post("/api/checkout", json={"session_id": sid}).status_code == 410
    assert client.post(f"/api/rerun/{sid}").status_code == 410


def test_purged_documents_still_count_towards_todays_quota(paid, client, monkeypatch):
    monkeypatch.setenv("AGLC_FREE_PER_DAY", "1")
    sid = _process(client).json()["id"]
    _age(sid, 25)
    with get_store().transaction() as conn:  # still today, for the quota
        conn.execute("UPDATE documents SET day = date('now') WHERE session_id = ?", (sid,))
    _sweep()
    assert _process(client).status_code == 429


def test_paid_document_kept_for_a_full_window_after_payment(paid, client, fake):
    sid = _process(client).json()["id"]
    poid = _provider_order_id(_checkout(client, sid)["order_id"])
    fake.pay(poid)
    _webhook(client, fake, poid)
    _age(sid, 30, unlocked=2, orders=30)  # uploaded long ago, paid recently
    assert _sweep() == 0
    assert client.get(f"/api/download/{sid}").status_code == 200


def test_paid_document_expires_without_a_refund(paid, client, fake):
    sid = _process(client).json()["id"]
    order_id = _checkout(client, sid)["order_id"]
    poid = _provider_order_id(order_id)
    fake.pay(poid)
    _webhook(client, fake, poid)
    _age(sid, 50, unlocked=25, orders=50)
    assert _sweep() == 1
    r = client.get(f"/api/download/{sid}")
    assert r.status_code == 410 and "privacy policy" in r.json()["detail"]
    assert client.get(f"/api/results/{sid}").status_code == 410
    assert get_store().order(order_id)["status"] == "paid"  # not refunded
    assert fake.checkouts[poid].refunds == []


def test_pending_checkout_protects_the_document(paid, client):
    sid = _process(client).json()["id"]
    _checkout(client, sid)
    _age(sid, 25)  # the order is fresh: someone is paying right now
    assert _sweep() == 0
    assert (billing.sessions_dir() / sid).exists()


def test_reopening_checkout_restarts_the_window(paid, client):
    sid = _process(client).json()["id"]
    _checkout(client, sid)
    _age(sid, 30, orders=30)
    _checkout(client, sid)  # the same pending link, opened again
    assert _sweep() == 0


def test_abandoned_checkout_no_longer_holds_the_document(paid, client):
    sid = _process(client).json()["id"]
    _checkout(client, sid)
    _age(sid, 30, orders=25)
    assert _sweep() == 1


def test_lost_webhook_is_reconciled_before_deleting(paid, client, fake):
    sid = _process(client).json()["id"]
    poid = _provider_order_id(_checkout(client, sid)["order_id"])
    fake.pay(poid)  # paid, but the webhook never came
    _age(sid, 30, orders=25)
    assert _sweep() == 0
    assert get_store().document(sid)["unlocked_at"]
    assert client.get(f"/api/download/{sid}").status_code == 200


def test_payment_after_deletion_is_refunded(paid, client, fake):
    sid = _process(client).json()["id"]
    order_id = _checkout(client, sid)["order_id"]
    poid = _provider_order_id(order_id)
    _age(sid, 30, orders=25)
    assert _sweep() == 1
    fake.pay(poid)
    r, _, _ = _webhook(client, fake, poid)
    assert r.json()["outcome"] == "files_missing"
    assert get_store().order(order_id)["status"] == "refunded"


def _old_dir(parent: Path, name: str, hours: float) -> Path:
    d = parent / name
    d.mkdir(parents=True)
    (d / "input.docx").write_bytes(b"x")
    t = time.time() - hours * 3600
    os.utime(d, (t, t))
    return d


def test_free_documents_in_the_temp_dir_are_deleted(tmp_path):
    old = _old_dir(tmp_path, str(uuid.uuid4()), 25)
    fresh = _old_dir(tmp_path, str(uuid.uuid4()), 1)
    other = _old_dir(tmp_path, "not-a-session", 100)
    assert retention.sweep(tmp_path) == 1
    assert not old.exists() and fresh.exists() and other.exists()


def test_orphan_paid_folders_are_deleted(paid):
    orphan = _old_dir(billing.sessions_dir(), str(uuid.uuid4()), 25)
    get_store()  # the database exists
    assert _sweep() == 1
    assert not orphan.exists()


def test_sweep_runs_at_startup(tmp_path, monkeypatch):
    old = _old_dir(tmp_path, str(uuid.uuid4()), 25)
    monkeypatch.setattr(api, "_TEMP_DIR", tmp_path)
    with TestClient(api.app):
        for _ in range(100):
            if not old.exists():
                break
            time.sleep(0.02)
    assert not old.exists()


def test_sweep_interval_follows_the_window(monkeypatch):
    assert retention.sweep_interval() == 3600
    monkeypatch.setenv("AGLC_RETENTION_HOURS", "1")
    assert retention.sweep_interval() == 900


# ---- smaller protections ----------------------------------------------------------- #


def test_errors_dont_reach_the_client(client):
    with mock.patch("aglc.pipeline.process_docx", side_effect=RuntimeError("/secret/path sk-or-key")):
        r = _upload(client, ESSAY.read_bytes())
    assert r.status_code == 500 and "secret" not in r.text and "sk-or" not in r.text


def test_llm_errors_dont_reach_the_client(client):
    from aglc.llm.base import LLMError
    with mock.patch("aglc.pipeline.process_docx", side_effect=LLMError("401 bad key sk-or-123")):
        r = _upload(client, ESSAY.read_bytes())
    assert r.status_code == 502 and "sk-or" not in r.text


def test_security_headers(client):
    r = client.get("/api/config")
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/").headers["referrer-policy"] == "no-referrer"


def test_access_log_redacts_session_ids():
    sid = str(uuid.uuid4())
    record = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4:5", "GET", f"/api/download/{sid}?x=1", "1.1", 200), None)
    guards.RedactSessionIds().filter(record)
    assert sid not in record.getMessage() and sid[:8] in record.getMessage()
    assert any(isinstance(f, guards.RedactSessionIds) for f in logging.getLogger("uvicorn.access").filters)


def _request(headers=None, peer="127.0.0.1"):
    req = mock.Mock()
    req.headers = headers or {}
    req.client.host = peer
    return req


def test_forwarded_for_uses_the_address_the_proxy_added(monkeypatch):
    monkeypatch.setenv("AGLC_CLIENT_IP_HEADER", "X-Forwarded-For")
    assert billing._client_ip(_request({"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})) == "203.0.113.9"


def test_cf_connecting_ip_is_used_when_configured(monkeypatch):
    monkeypatch.setenv("AGLC_CLIENT_IP_HEADER", "CF-Connecting-IP")
    assert billing._client_ip(_request({"CF-Connecting-IP": "203.0.113.9"})) == "203.0.113.9"
    assert billing._client_ip(_request()) == "127.0.0.1"


def test_ipv6_counts_as_its_64():
    a = billing._client_ip(_request(peer="2001:db8:1:2::1"))
    b = billing._client_ip(_request(peer="2001:db8:1:2:ffff::9"))
    assert a == b == "2001:db8:1:2::/64"
    assert billing._client_ip(_request(peer="::ffff:203.0.113.9")) == "203.0.113.9"


def test_entitlement_says_expired_after_deletion(paid, client, fake):
    sid = _process(client).json()["id"]
    poid = _provider_order_id(_checkout(client, sid)["order_id"])
    fake.pay(poid)
    _webhook(client, fake, poid)
    _age(sid, 50, unlocked=25, orders=50)
    _sweep()
    assert client.get(f"/api/entitlement/{sid}").json() == {"session_id": sid, "unlocked": False, "status": "expired"}


def test_too_large_message_keeps_fractions(monkeypatch):
    monkeypatch.setenv("AGLC_MAX_UPLOAD_MB", "0.5")
    assert "0.5 MB" in guards.too_large_message()
