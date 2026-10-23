"""Problem reports (aglc/reports.py) and POST /api/report/{id}."""

import json
import os
import time
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from aglc import api, reports, retention

client = TestClient(api.app)

RESULT = {
    "id": "x",
    "filename": "essay.docx",
    "footnotes": [
        {"number": 1, "original": "*Smith v Jones* [2019] HCA 99.", "formatted": "*Smith v Jones* [2019] HCA 99.",
         "changed": False, "changes": [], "extraction_failed": None},
        {"number": 2, "original": "Evidence Act 1995 (Cth) s 55.", "formatted": "*Evidence Act 1995* (Cth) s 55.",
         "changed": True, "changes": [{"kind": "act_title_italic", "text": "An Act's title is italic", "rule": "r 3.1.1"}],
         "extraction_failed": None},
    ],
    "warnings": [{"footnote": 1, "message": "Case not found: [2019] HCA 99 is past the court's last decision that year, [2019] HCA 50"},
                 {"footnote": 2, "message": "something else"}],
    "case_check": {"total": 1, "checked": 1, "flagged": 1, "found": [], "unchecked": []},
}


@pytest.fixture(autouse=True)
def data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("AGLC_DATA_DIR", str(tmp_path / "data"))
    return tmp_path / "data"


@pytest.fixture
def session(monkeypatch, tmp_path):
    """A document's saved result, where the API keeps it with payments off."""
    sessions = tmp_path / "sessions"
    monkeypatch.setattr(api, "_TEMP_DIR", sessions)
    session_id = str(uuid.uuid4())
    folder = sessions / session_id
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(json.dumps(RESULT))
    (folder / "extraction.json").write_text(json.dumps({"footnotes": [{"number": 1, "segments": [{"kind": "text"}]}]}))
    (folder / "options.json").write_text(json.dumps({"model": "fake:x"}))
    return session_id, folder


def test_report_holds_the_footnote_as_saved_and_nothing_else(session):
    session_id, folder = session
    path = reports.save(folder, session_id, 1, "  It says this case doesn't exist  ")
    report = json.loads(path.read_text())
    assert report["document"] == session_id[:8] and report["footnote"] == 1
    assert report["comment"] == "It says this case doesn't exist"
    assert report["original"] == RESULT["footnotes"][0]["original"]
    assert report["warnings"] == [RESULT["warnings"][0]["message"]]  # only this footnote's
    assert report["extraction"] == [{"kind": "text"}] and report["model"] == "fake:x"
    assert "essay.docx" not in path.read_text()  # not the file name


def test_report_without_a_comment(session):
    session_id, folder = session
    assert json.loads(reports.save(folder, session_id, 2).read_text())["comment"] is None


def test_unknown_footnote_and_deleted_document(session, tmp_path):
    session_id, folder = session
    with pytest.raises(LookupError):
        reports.save(folder, session_id, 9)
    with pytest.raises(FileNotFoundError):
        reports.save(tmp_path / "gone", session_id, 1)


def test_reports_per_document_are_limited(session, monkeypatch):
    session_id, folder = session
    monkeypatch.setattr(reports, "MAX_PER_DOCUMENT", 2)
    reports.save(folder, session_id, 1)
    reports.save(folder, session_id, 1)
    with pytest.raises(reports.TooManyReports):
        reports.save(folder, session_id, 2)


def test_load_lists_newest_first(session):
    session_id, folder = session
    reports.save(folder, session_id, 1, "first", at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    reports.save(folder, session_id, 2, "second", at=datetime(2026, 2, 1, tzinfo=timezone.utc))
    assert [r["comment"] for r in reports.load()] == ["second", "first"]
    assert len(reports.load(limit=1)) == 1


def test_old_reports_are_purged(session, monkeypatch):
    session_id, folder = session
    monkeypatch.setenv("AGLC_REPORT_DAYS", "30")
    old, new = reports.save(folder, session_id, 1), reports.save(folder, session_id, 2)
    month_ago = time.time() - 31 * 86400
    os.utime(old, (month_ago, month_ago))
    assert reports.purge() == 1
    assert not old.exists() and new.exists()


def test_the_retention_sweep_purges_reports(session, monkeypatch):
    session_id, folder = session
    path = reports.save(folder, session_id, 1)
    long_ago = time.time() - 365 * 86400
    os.utime(path, (long_ago, long_ago))
    retention.sweep_safely(None)
    assert not path.exists()


def test_api_saves_a_report(session):
    session_id, _ = session
    response = client.post(f"/api/report/{session_id}", json={"footnote": 1, "comment": "Wrong case"})
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert [r["comment"] for r in reports.load()] == ["Wrong case"]


@pytest.mark.parametrize("path_id, body, code", [
    ("not-a-uuid", {"footnote": 1}, 422),
    (None, {"footnote": 9}, 404),
    (None, {"footnote": 1, "comment": "x" * (reports.MAX_COMMENT + 1)}, 422),
    (str(uuid.UUID(int=1)), {"footnote": 1}, 410),  # deleted (or never existed)
])
def test_api_refuses_bad_reports(session, path_id, body, code):
    session_id, _ = session
    response = client.post(f"/api/report/{path_id or session_id}", json=body)
    assert response.status_code == code
    assert reports.load() == []


def test_privacy_page_says_how_long_reports_are_kept(monkeypatch):
    monkeypatch.setenv("AGLC_REPORT_DAYS", "45")
    text = client.get("/privacy").text
    assert "Problem reports" in text and "kept for 45 days" in text
