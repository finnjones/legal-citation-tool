"""The free preview can't stand in for paying (docs/paywall-audit.md): every path that could
carry a corrected footnote, the bibliography or the .docx to an unpaid page is checked here."""

from __future__ import annotations

import json
import time

import pytest
from unittest import mock

from aglc import billing, progress
from aglc.store import get_store

from test_billing import (  # noqa: F401
    DOCX, ESSAY, _checkout, _process, _provider_order_id, _webhook, client, fake, paid)


def _full(sid):
    return json.loads((billing.sessions_dir() / sid / "result.json").read_text())


def _secrets(full):
    """What an unpaid page must never receive: each locked footnote's corrected text (where it
    isn't also the student's own text), the bibliography's entries and the found cases' titles
    on locked footnotes."""
    shown = set(n for n in [f["number"] for f in full["footnotes"] if f["changed"]][:billing.preview_size(
        sum(f["changed"] for f in full["footnotes"]))])
    # the student's own text, and what the preview may show, can't be a leak
    originals = " ".join(f[k] for f in full["footnotes"] for k in ("original", "original_html"))
    originals += " ".join(f[k] for f in full["footnotes"] if f["number"] in shown or not f["changed"]
                          for k in ("formatted", "formatted_html"))
    out = []
    for f in full["footnotes"]:
        if f["changed"] and f["number"] not in shown:
            out += [f["formatted"], f["formatted_html"]]
    out += [e for section in full["bibliography"] for e in section["entries"]]
    out += [f"{c['title']} {c['citation']}" for c in full["case_check"]["found"] if c["footnote"] not in shown]
    return [s for s in out if s and s not in originals]


def _assert_no_leak(payload, full):
    text = json.dumps(payload, ensure_ascii=False)
    leaked = [s for s in _secrets(full) if s in text]
    assert not leaked, leaked[:3]


# ---- the preview's size ----------------------------------------------------------- #


@pytest.mark.parametrize("changed,shown", [(0, 1), (1, 1), (5, 1), (10, 1), (11, 2), (19, 2), (20, 2), (21, 3),
                                           (30, 3), (31, 3), (400, 3)])
def test_preview_size_scales_with_the_document(changed, shown):
    assert billing.preview_size(changed) == shown


def test_preview_constants_sit_together():
    assert (billing.PREVIEW_FULL, billing.PREVIEW_SHARE, billing.PREVIEW_MIN) == (3, 0.10, 1)


def _synthetic(n_changed, n_unchanged=2):
    footnotes = []
    for n in range(1, n_changed + n_unchanged + 1):
        changed = n <= n_changed
        footnotes.append({"number": n, "original": f"orig {n}", "original_html": f"orig {n}",
                          "formatted": f"FIXED {n}" if changed else f"orig {n}",
                          "formatted_html": f"FIXED {n}" if changed else f"orig {n}", "changed": changed,
                          "changes": [{"kind": "x", "text": f"why {n}", "rule": None}] if changed else [],
                          "extraction_failed": None})
    return {
        "id": "s", "footnotes": footnotes, "warnings": [{"footnote": 2, "message": "has no pinpoint"}],
        "bibliography": [{"heading": "B Cases", "entries": ["BIB ENTRY"]}],
        "body_fixes": [{"footnote": 3, "message": "‘s 5-7’ changed to ‘ss 5–7’", "applied": True},
                       {"footnote": 4, "message": "a new sentence starts after this footnote number", "applied": False}],
        "case_check": {"total": 3, "checked": 2, "flagged": 0,
                       "found": [{"footnote": 1, "title": "CASE ONE", "citation": "[1] HCA 1", "url": "u"},
                                 {"footnote": 20, "title": "CASE TWENTY", "citation": "[2] HCA 2", "url": "u"}],
                       "unchecked": [{"footnote": 21, "name": "Name As Read", "search_url": "s"}]},
    }


def test_preview_shows_only_the_first_changed_footnotes_and_counts_the_rest():
    full = _synthetic(25)
    p = billing.preview(full)
    shown = [f["number"] for f in p["footnotes"] if f["changed"] and not f.get("locked")]
    assert shown == [1, 2, 3]  # 10% of 25, rounded up
    assert (p["changed_count"], p["preview_count"], p["locked_count"]) == (25, 3, 22)
    assert all(f["formatted"] == f["original"] for f in p["footnotes"] if not f["changed"])
    assert p["warnings"] == full["warnings"]
    assert p["bibliography"] == [] and p["bibliography_entries"] == 1
    # body fixes made are part of the paid result; checks left for the student are like warnings
    assert p["body_fixes"] == [full["body_fixes"][1]] and p["body_fixes_locked"] == 1
    # the cases found (by their real names) or not checked on locked footnotes are counted only
    assert [c["footnote"] for c in p["case_check"]["found"]] == [1]
    assert p["case_check"]["found_locked"] == 1 and p["case_check"]["unchecked"] == []
    assert p["case_check"]["unchecked_locked"] == 1 and p["case_check"]["total"] == 3
    text = json.dumps(p)
    for secret in ("FIXED 4", "FIXED 25", "why 4", "BIB ENTRY", "CASE TWENTY", "Name As Read", "ss 5–7"):
        assert secret not in text


def test_a_short_essay_shows_one_correction():
    p = billing.preview(_synthetic(4))
    assert p["preview_count"] == 1 and p["locked_count"] == 3


# ---- every path, on a real (fake-model) run --------------------------------------- #


def test_process_results_and_rerun_carry_no_locked_correction(paid, client):
    data = _process(client).json()
    full = _full(data["id"])
    assert data["locked"] is True and data["preview_count"] == 1 and data["changed_count"] == 10
    _assert_no_leak(data, full)
    # the cases found on locked footnotes (Wik, the A-G case) are withheld by name
    assert [c["footnote"] for c in data["case_check"]["found"]] == [1]
    assert data["case_check"]["found_locked"] == 2
    _assert_no_leak(client.get(f"/api/results/{data['id']}").json(), full)
    _assert_no_leak(client.post(f"/api/rerun/{data['id']}").json(), full)
    _assert_no_leak(client.get(f"/api/entitlement/{data['id']}").json(), full)
    _assert_no_leak(_checkout(client, data["id"]), full)


def test_the_same_essay_previews_the_same_footnotes(paid, client):
    first, second = _process(client).json(), _process(client).json()
    pick = lambda d: [f["number"] for f in d["footnotes"] if f["changed"] and not f.get("locked")]  # noqa: E731
    assert pick(first) == pick(second) == [1]


def test_progress_never_sends_a_locked_correction_even_mid_run(paid, client):
    """Every state the progress endpoint could report, recorded after each update the
    pipeline makes, and every poll the page makes, carry no locked correction."""
    snapshots = []
    original = progress.Job.update

    def record(self, kind, data):
        original(self, kind, data)
        snapshots.append(json.loads(json.dumps(self.snapshot(), default=str)))

    with mock.patch.object(progress.Job, "update", record):
        started = client.post("/api/process", data={"progress": "true"},
                              files={"file": ("essay.docx", ESSAY.read_bytes(), DOCX)})
        assert started.status_code == 202
        sid = started.json()["id"]
        polls = []
        for _ in range(400):
            polls.append(client.get(f"/api/progress/{sid}").json())
            if polls[-1]["status"] != "processing":
                break
            time.sleep(0.02)
    full = _full(sid)
    assert polls[-1]["status"] == "done" and polls[-1]["result"]["locked"] is True
    assert len(snapshots) > 5  # the run reported its progress along the way
    for snap in snapshots + polls:
        _assert_no_leak(snap, full)
        assert not any(k in snap for k in ("footnotes", "formatted", "bibliography"))


def test_download_and_report_give_nothing_before_paying(paid, client):
    sid = _process(client).json()["id"]
    r = client.get(f"/api/download/{sid}")
    assert r.status_code == 402 and not r.content.startswith(b"PK")
    locked = next(f for f in client.get(f"/api/results/{sid}").json()["footnotes"] if f.get("locked"))
    r = client.post(f"/api/report/{sid}", json={"footnote": locked["number"], "comment": "wrong?"})
    assert r.json() == {"ok": True}  # the report is kept server-side; nothing comes back


def test_paying_unlocks_everything(paid, client, fake):
    sid = _process(client).json()["id"]
    poid = _provider_order_id(_checkout(client, sid)["order_id"])
    fake.pay(poid)
    _webhook(client, fake, poid)
    data = client.get(f"/api/results/{sid}").json()
    full = _full(sid)
    assert data["locked"] is False and data["footnotes"] == full["footnotes"]
    assert data["case_check"] == full["case_check"] and data["bibliography"] == full["bibliography"]


def test_payments_off_returns_everything(client, monkeypatch):
    with mock.patch("aglc.pipeline.get_provider", side_effect=lambda *a, **k: __import__("aglc.llm", fromlist=["x"])
                    .get_provider("fake:e2e", responses=[(ESSAY.parent / "sample_essay_extraction.json").read_text()])):
        data = _process(client).json()
    assert "locked" not in data and all("formatted" in f for f in data["footnotes"]) and data["bibliography"]
    assert client.get("/api/config").json() == {"payments": False, "retention_hours": 24}
