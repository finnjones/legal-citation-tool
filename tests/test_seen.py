"""One free preview per essay (aglc/fingerprint.py, the seen check in aglc/billing.py)."""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from aglc import api, billing, fingerprint, retention
from aglc.docx_io import read_footnotes
from aglc.store import get_store

from test_billing import DOCX, ESSAY, _checkout, _provider_order_id, _webhook, fake, paid  # noqa: F401
from tests.fixtures.build_fixtures import build_docx

SAMPLE_TEXTS = [fn.original.text for fn in read_footnotes(ESSAY)]
NEW_TEXTS = [  # footnotes of other essays, each distinctive
    "Commonwealth v Tasmania (1983) 158 CLR 1, 59.",
    "Australian Capital Television Pty Ltd v Commonwealth (1992) 177 CLR 106.",
    "Lange v Australian Broadcasting Corporation (1997) 189 CLR 520, 567.",
    "Plaintiff S157/2002 v Commonwealth (2003) 211 CLR 476.",
    "Kable v Director of Public Prosecutions (NSW) (1996) 189 CLR 51.",
    "R v Kirby; Ex parte Boilermakers' Society of Australia (1956) 94 CLR 254.",
]


@pytest.fixture
def seen(paid, monkeypatch):
    """The seen check at its defaults."""
    monkeypatch.delenv("AGLC_SEEN_OVERLAP")
    return paid


def _docx(tmp_path, texts, name="essay.docx"):
    body = [("para", [("text", "Paragraph. ", False), ("fnref", i + 1)]) for i in range(len(texts))]
    specs = [(i + 1, [[("text", t, False)]]) for i, t in enumerate(texts)]
    return build_docx(tmp_path / name, body, specs).read_bytes()


def _upload(content=None, name="essay.docx", ip="1.1.1.1", client=None):
    """Upload from `client`, by default a new browser: the abuse is new cookies and addresses."""
    client = client or TestClient(api.app)
    return client, client.post("/api/process", files={"file": (name, content or ESSAY.read_bytes(), DOCX)},
                               headers={"X-Forwarded-For": ip})


def _seen(r):
    """'preview' (the browser's own earlier preview again), 'elsewhere' (409: someone's) or None."""
    if r.status_code == 409 and r.json()["detail"].get("seen"):
        return "elsewhere"
    return "preview" if r.status_code == 200 and r.json().get("seen") else None


def _shown(data):
    return [f["number"] for f in data["footnotes"] if f["changed"] and not f.get("locked")]


# ---- fingerprints ------------------------------------------------------------------ #


def test_normalising_ignores_case_quotes_dashes_and_spacing():
    a = fingerprint.compute(["J Smith, ‘Native Title’ (1995) 19 MULR 195–7."], "k")
    b = fingerprint.compute(["j  smith, 'NATIVE title' (1995) 19 MULR 195-7"], "k")
    c = fingerprint.compute(["Ｊ Smith, \"Native Title\" (1995) 19 MULR 195—7"], "k")  # full-width J (NFKC)
    assert a == b == c and len(a.hashes) == 1


def test_common_footnotes_dont_count():
    for text in ("Ibid.", "Ibid, at 45.", "Ibid 45 [12].", "Mabo (n 1) 60.", "Mabo, above n 1, 60.", "See above.",
                 "Smith v Jones (n 5) 12 per Kirby J."):
        assert not fingerprint.counts(fingerprint.normalise(text)), text
    for text in SAMPLE_TEXTS[:2] + NEW_TEXTS[:2]:
        assert fingerprint.counts(fingerprint.normalise(text)), text


def test_fingerprints_are_keyed_hashes_not_text():
    fp = fingerprint.compute(SAMPLE_TEXTS, "key-1")
    assert len(fp.hashes) == 8  # 10 footnotes less a bare Ibid and a bare (n x)
    assert all(len(h) == 32 and int(h, 16) >= 0 for h in fp.hashes)
    assert "mabo" not in json.dumps(fp.hashes).lower()
    assert set(fingerprint.compute(SAMPLE_TEXTS, "key-2").hashes).isdisjoint(fp.hashes)


@pytest.mark.parametrize("shared,new,expected", [
    (5, 0, True), (4, 0, False),  # at least 5 matching footnotes
    (6, 4, True), (5, 4, False),  # at least 60% of the new document's footnotes (6/10, 5/9)
])
def test_overlap_thresholds(shared, new, expected):
    earlier = [f"e{i}" for i in range(10)]
    upload = earlier[:shared] + [f"n{i}" for i in range(new)]
    assert fingerprint.matches(upload, earlier, 0.6) is expected


# ---- the seen check ------------------------------------------------------------------ #


def test_the_same_essay_gets_its_free_preview_once(seen):
    client, first = _upload()
    assert first.status_code == 200 and not first.json().get("seen")
    _, again = _upload(name="renamed.docx", ip="1.1.1.1", client=client)  # the same browser, again
    data = again.json()
    assert _seen(again) == "preview" and data["message"] == billing.SEEN_MESSAGE
    assert seen.call_count == 1  # no model run for the second upload
    assert data["id"] != first.json()["id"] and data["filename"] == "renamed.docx"
    assert first.json()["id"] not in json.dumps(data)
    assert data["locked"] is True and _shown(data) == _shown(first.json())  # the same preview footnotes
    assert data["changed_count"] == 10 and data["price"]["display"] == "A$5"
    doc = get_store().document(data["id"])
    assert (doc["kind"], doc["seen_of"], doc["status"], doc["seen_shown"]) == ("seen", first.json()["id"], "seen", 1)
    assert client.get(f"/api/results/{data['id']}").json()["seen"] is True


def test_someone_elses_matching_upload_is_shown_nothing_of_the_earlier_essay(seen, tmp_path):
    """Regression: five distinctive footnotes of a victim's essay used to return the victim's
    whole preview: every footnote as written, the warnings and the corrections shown."""
    victim, first = _upload(_docx(tmp_path, SAMPLE_TEXTS + ["Victim's own secret footnote about the case at hand."]))
    countable = [t for t in SAMPLE_TEXTS if fingerprint.counts(fingerprint.normalise(t))]
    runs = seen.call_count
    attacker, r = _upload(_docx(tmp_path, countable[:5], "probe.docx"), name="probe.docx", ip="1.1.1.1")
    assert _seen(r) == "elsewhere" and seen.call_count == runs
    detail = r.json()["detail"]
    assert set(detail) == {"message", "seen", "session_id", "filename", "tier", "credits_needed", "price"}
    assert detail["message"] == billing.SEEN_ELSEWHERE and detail["filename"] == "probe.docx"
    text = r.text + attacker.get(f"/api/results/{detail['session_id']}").text
    assert attacker.get(f"/api/results/{detail['session_id']}").status_code == 409
    for leak in ("Victim's own secret", "Brennan", "Wik Peoples", first.json()["id"], "essay.docx"):
        assert leak not in text, leak


def test_deleting_the_shown_footnotes_reveals_nothing_new(seen, tmp_path):
    """The attack: delete the footnotes the preview showed in full, upload again, see the next."""
    client, first = _upload()
    shown = _shown(first.json())
    assert shown == [1]
    rest = [t for i, t in enumerate(SAMPLE_TEXTS, start=1) if i not in shown]
    _, again = _upload(_docx(tmp_path, rest), client=client)  # the same browser: its own preview again
    assert _seen(again) == "preview" and seen.call_count == 1
    assert set(_shown(again.json())) <= set(shown)  # no correction the first preview didn't show
    _, other = _upload(_docx(tmp_path, rest), ip="3.3.3.3")  # a new browser: nothing at all
    assert _seen(other) == "elsewhere" and seen.call_count == 1


def test_a_mostly_new_essay_is_not_seen(seen, tmp_path):
    client, _ = _upload()
    countable = [t for t in SAMPLE_TEXTS if fingerprint.counts(fingerprint.normalise(t))]
    _, below = _upload(_docx(tmp_path, countable[:5] + NEW_TEXTS[:4], "b.docx"), client=client)  # 5/9 < 0.6
    assert _seen(below) is None and seen.call_count == 2
    _, above = _upload(_docx(tmp_path, countable[:6] + NEW_TEXTS[:3], "a.docx"), client=client)  # 6/9 >= 0.6
    assert _seen(above) == "preview" and seen.call_count == 2


def test_tiny_documents_never_match(seen, tmp_path):
    content = _docx(tmp_path, NEW_TEXTS[:4])  # 4 counted footnotes: under the minimum of 5
    _upload(content)
    _, again = _upload(content, ip="6.6.6.6")
    assert _seen(again) is None and seen.call_count == 2


def test_the_threshold_comes_from_the_environment(seen, monkeypatch):
    monkeypatch.setenv("AGLC_SEEN_OVERLAP", "0")  # off
    _upload()
    assert _seen(_upload(ip="7.7.7.7")[1]) is None


def test_a_failed_or_unreadable_first_run_doesnt_use_up_the_preview(seen):
    works, seen.side_effect = seen.side_effect, RuntimeError("model down")
    assert _upload()[1].status_code == 500
    seen.side_effect = works
    assert _seen(_upload(ip="8.8.8.8")[1]) is None


def test_the_sample_essay_is_never_seen(seen):
    store = get_store()
    fp = billing.fingerprint_of(read_footnotes(api.site.SAMPLE_ESSAY))
    store.add_document("00000000-0000-4000-8000-000000000001", "s.docx", ip_hash=None, anon_id=None)
    store.add_fingerprint("00000000-0000-4000-8000-000000000001", fp.doc_hash, fp.hashes)
    store.index_fingerprint("00000000-0000-4000-8000-000000000001")
    visitor = billing.Visitor(ip_hash=None, anon_id="a" * 32, new_cookie=False)
    assert len(fp.hashes) >= fingerprint.MIN_MATCHES and billing.seen_before(fp, visitor) is None


def test_seen_uploads_count_against_the_free_limits(seen, monkeypatch):
    """So the check can't be used as an unlimited lookup service."""
    monkeypatch.setenv("AGLC_FREE_PER_DAY", "2")
    client, first = _upload()
    assert _seen(_upload(client=client)[1]) == "preview"
    assert _upload(client=client)[1].status_code == 429  # two free uploads today, the seen one included
    monkeypatch.setenv("AGLC_FREE_GLOBAL_PER_DAY", "3")
    assert _seen(_upload(ip="9.9.9.9")[1]) == "elsewhere"
    assert _upload(ip="10.10.10.10")[1].status_code == 429  # the global cap counts seen uploads too


# ---- paying for a seen essay: a fresh run ------------------------------------------- #


def test_a_seen_essay_can_be_paid_for_and_is_run_fresh(seen, fake):
    first_client, first = _upload()
    client, again = _upload(client=first_client)
    sid = again.json()["id"]
    assert client.post(f"/api/run/{sid}").status_code == 402
    assert client.get(f"/api/download/{sid}").status_code == 402
    order = _checkout(client, sid)
    assert get_store().order(order["order_id"])["amount"] == 500
    poid = _provider_order_id(order["order_id"])
    fake.pay(poid)
    assert _webhook(client, fake, poid)[0].json()["outcome"] == "unlocked"
    waiting = client.get(f"/api/results/{sid}").json()
    assert waiting["needs_run"] is True and waiting["locked"] is False
    assert client.get(f"/api/download/{sid}").status_code == 409  # not run yet: no refund
    data = client.post(f"/api/run/{sid}").json()
    assert seen.call_count == 2  # the fresh run
    assert data["locked"] is False and all("formatted" in f for f in data["footnotes"]) and data["bibliography"]
    assert client.get(f"/api/download/{sid}").status_code == 200
    assert client.post(f"/api/run/{sid}").status_code == 409  # once
    assert get_store().order(order["order_id"])["status"] == "paid"


def test_someone_else_can_pay_for_a_matching_essay_and_gets_their_own_run(seen, fake, tmp_path):
    _upload()
    countable = [t for t in SAMPLE_TEXTS if fingerprint.counts(fingerprint.normalise(t))]
    client, r = _upload(_docx(tmp_path, countable[:6]), ip="2.2.2.2")
    sid = r.json()["detail"]["session_id"]
    poid = _provider_order_id(_checkout(client, sid)["order_id"])
    fake.pay(poid)
    _webhook(client, fake, poid)
    data = client.post(f"/api/run/{sid}").json()
    assert data["locked"] is False and len(data["footnotes"]) == 6  # the new upload, not the earlier essay


def test_a_swept_preview_gets_a_409_offering_to_unlock(seen, fake):
    client, first = _upload()
    shutil.rmtree(billing.sessions_dir() / first.json()["id"])  # deleted by the retention sweep
    _, again = _upload(client=client)
    assert again.status_code == 409 and seen.call_count == 1
    detail = again.json()["detail"]
    assert detail["seen"] is True and detail["price"]["display"] == "A$5" and "Unlock" in detail["message"]
    sid = detail["session_id"]
    assert (billing.sessions_dir() / sid / "input.docx").is_file()  # kept for the paid run
    poid = _provider_order_id(_checkout(client, sid)["order_id"])
    fake.pay(poid)
    _webhook(client, fake, poid)
    started = client.post(f"/api/run/{sid}", data={"progress": "true"})
    assert started.status_code == 202
    for _ in range(200):
        snap = client.get(f"/api/progress/{sid}").json()
        if snap["status"] != "processing":
            break
    assert snap["status"] == "done" and snap["result"]["locked"] is False


def _seen_session(ip="2.2.2.2"):
    _upload()
    client, again = _upload(ip=ip)
    return client, again.json()["detail"]["session_id"]


def test_a_seen_essay_can_be_unlocked_with_credits(seen, fake):
    client, sid = _seen_session()
    r = client.post("/api/checkout", json={"product": "pack3"})
    poid = _provider_order_id(r.json()["order_id"])
    fake.pay(poid)
    _webhook(client, fake, poid)
    code = client.get(f"/api/pack/{r.json()['order_id']}").json()["code"]
    assert client.post("/api/redeem", json={"session_id": sid, "code": code}).json()["credits_spent"] == 1
    assert client.post(f"/api/run/{sid}").json()["locked"] is False


def test_a_failed_paid_run_can_be_started_again(seen, fake):
    client, sid = _seen_session()
    poid = _provider_order_id(_checkout(client, sid)["order_id"])
    fake.pay(poid)
    _webhook(client, fake, poid)
    works, seen.side_effect = seen.side_effect, RuntimeError("model down")
    assert client.post(f"/api/run/{sid}").status_code == 500
    assert get_store().document(sid)["status"] == "seen" and (billing.sessions_dir() / sid / "input.docx").is_file()
    seen.side_effect = works
    assert client.post(f"/api/run/{sid}").json()["locked"] is False


def test_run_is_off_without_payments():
    assert TestClient(api.app).post("/api/run/00000000-0000-4000-8000-000000000000").status_code == 404


# ---- retention and privacy ------------------------------------------------------------ #


def test_fingerprints_outlive_the_documents_then_go(seen):
    _, first = _upload()
    sid = first.json()["id"]
    now = datetime.now(timezone.utc)
    retention.sweep(None, at=now + timedelta(hours=25))
    assert get_store().document(sid)["purged_at"] and get_store().fingerprint(sid)
    assert _seen(_upload(ip="2.2.2.2")[1]) == "elsewhere"  # still seen, though its preview has gone
    retention.sweep(None, at=now + timedelta(days=181))
    assert get_store().fingerprint(sid) is None
    with sqlite3.connect(get_store().path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM fingerprint_index WHERE session_id = ?", (sid,)).fetchone()[0] == 0


def test_no_footnote_text_is_stored_with_a_fingerprint(seen):
    _upload()
    with sqlite3.connect(get_store().path) as conn:
        rows = conn.execute("SELECT * FROM fingerprints").fetchall() + conn.execute(
            "SELECT * FROM fingerprint_index").fetchall()
    assert rows and "Mabo" not in json.dumps(rows) and "mabo" not in json.dumps(rows)


def test_privacy_page_describes_fingerprints(monkeypatch):
    text = TestClient(api.app).get("/privacy").text
    assert "fingerprint" in text.lower() and "180 days" in text
    monkeypatch.setenv("AGLC_FINGERPRINT_DAYS", "90")
    assert "90 days" in TestClient(api.app).get("/privacy").text
