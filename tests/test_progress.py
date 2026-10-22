"""Live progress (aglc/progress.py): the pipeline's events, the job store, and the
/api/process?progress=true + /api/progress/{id} flow the page uses."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from aglc import api, billing
from aglc.extract import Extractor, _WritingWatcher
from aglc.llm import get_provider
from aglc.llm.base import LLMError
from aglc.models import Footnote, RichText
from aglc.payments import reset_payment_providers
from aglc.progress import Jobs, safe

FIXTURES = Path(__file__).parent / "fixtures"
ESSAY = FIXTURES / "sample_essay.docx"
EXTRACTION = (FIXTURES / "sample_essay_extraction.json").read_text()
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _fn(n: int, text: str) -> Footnote:
    return Footnote(number=n, original=RichText.plain(text))


def _answer(*numbers: int) -> str:
    return json.dumps({"footnotes": [
        {"number": n, "segments": [{"kind": "text", "text": f"Commentary {n}."}]} for n in numbers]})


# ---- the job store ------------------------------------------------------------- #


def test_job_snapshot_tracks_counts_notes_and_the_result():
    store = Jobs()
    report = store.start("abc")
    report("total", {"footnotes": 3})
    report("writing", {"numbers": [1, 2]})
    report("done", {"numbers": [1]})
    report("done", {"numbers": [2], "failed": True})
    report("note", {"kind": "reask", "answered": 1, "count": 3})
    report("stage", {"name": "formatting"})
    snap = store.snapshot("abc")
    assert (snap["status"], snap["total"], snap["done"], snap["failed"], snap["writing"]) == ("processing", 3, [1, 2], [2], [])
    assert snap["stage"] == "formatting" and snap["notes"][-1]["kind"] == "reask"
    assert "result" not in snap
    store.finish("abc", result={"id": "abc"})
    assert store.snapshot("abc")["status"] == "done" and store.snapshot("abc")["result"] == {"id": "abc"}
    assert store.snapshot("nope") is None


def test_a_snapshot_shows_only_the_footnotes_the_page_is_about_to_show():
    store = Jobs()
    report = store.start("abc")
    report("total", {"footnotes": 40, "texts": {n: {"text": f"Footnote {n}.", "italic": []} for n in range(1, 41)}})
    report("writing", {"numbers": [30]})
    report("done", {"numbers": list(range(1, 26)), "found": {1: [{"kind": "Case", "text": "Footnote 1"}]}})
    snap = store.snapshot("abc")
    # the 20 read most recently (in the order read), the next 3 not read, and the one being written
    assert snap["read"] == list(range(6, 26))
    assert sorted(map(int, snap["showing"])) == list(range(6, 29)) + [30]
    assert snap["showing"][30] == {"text": "Footnote 30.", "italic": []}
    assert snap["showing"][6] == {"text": "Footnote 6.", "italic": [], "found": []}
    assert snap["kinds"] == {"Case": 1}
    assert store.snapshot("abc")["showing"][25]["text"] == "Footnote 25."


def test_footnote_texts_keep_the_italics():
    from aglc.models import Run
    from aglc.progress import footnote_texts

    fn = Footnote(number=3, original=RichText(runs=[Run(text=" See "), Run(text="Mabo", italic=True), Run(text=" at 4.")]))
    assert footnote_texts([fn]) == {3: {"text": "See Mabo at 4.", "italic": [[4, 8]]}}


def test_found_in_lists_the_citations_read_in_a_footnote():
    from aglc.models import CaseSource, Citation, CitationSegment, TextSegment, OtherSource
    from aglc.progress import found_in

    fn = _fn(1, "See Mabo v Queensland (No 2) (1992) 175 CLR 1; something odd.")
    fn.segments = [
        TextSegment(text=RichText.plain("See ")),
        CitationSegment(citation=Citation(source=CaseSource(name="Mabo v Queensland [No 2]", year="1992")),
                        original="Mabo v Queensland (No 2) (1992) 175 CLR 1"),
        CitationSegment(citation=Citation(source=OtherSource(text="something odd")), original="something odd"),
    ]
    assert found_in(fn) == [{"kind": "Case", "text": "Mabo v Queensland (No 2) (1992) 175 CLR 1"}]


def test_finished_jobs_are_dropped_after_a_while(monkeypatch):
    store = Jobs()
    store.start("old")
    store.finish("old", error={"status": 502, "detail": "x"})
    monkeypatch.setattr("aglc.progress.time.time", lambda: time.time_ns() / 1e9 + 3600)
    assert store.snapshot("old") is None


def test_a_failing_progress_callback_never_breaks_a_run():
    def broken(kind, data):
        raise RuntimeError("boom")

    safe(broken)("done", {"numbers": [1]})  # no exception
    fns = [_fn(1, "Commentary 1.")]
    out = Extractor(get_provider("fake:x", responses=[_answer(1)]), verify=False, progress=broken).extract(fns)
    assert out[0].segments


# ---- events from the extractor ------------------------------------------------- #


def _events(footnotes, responses, **kwargs):
    events: list[tuple[str, dict]] = []
    extractor = Extractor(get_provider("fake:x", responses=responses), verify=False,
                          progress=lambda kind, data: events.append((kind, data)), **kwargs)
    extractor.extract(footnotes)
    return events


def test_every_footnote_is_reported_done_and_a_reask_is_explained():
    fns = [_fn(n, f"Commentary {n}.") for n in (1, 2, 3)]
    events = _events(fns, [_answer(1), _answer(1, 2, 3)])  # first answer covers 1 of 3
    assert ("note", {"kind": "reask", "answered": 1, "count": 3}) in events
    done = [n for kind, data in events if kind == "done" for n in data["numbers"]]
    assert done == [1, 2, 3]
    assert not any(data.get("failed") for kind, data in events if kind == "done")


def test_a_half_answered_batch_is_asked_again_somewhere_else():
    provider = get_provider("fake:x", responses=[_answer(1), _answer(1, 2, 3)])
    with mock.patch.object(provider, "avoid_last_host", return_value=True) as avoid:
        Extractor(provider, verify=False).extract([_fn(n, f"Commentary {n}.") for n in (1, 2, 3)])
    avoid.assert_called_once()


def test_out_of_time_gives_up_the_rest_and_says_so():
    fns = [_fn(n, f"Commentary {n}.") for n in (1, 2)]
    events = _events(fns, [_answer(1, 2)], deadline=-1)
    assert ("note", {"kind": "deadline", "count": 2}) in events
    assert ("done", {"numbers": [1, 2], "failed": True}) in events


def test_footnotes_being_written_are_read_from_the_streamed_reply():
    seen = []
    watch = _WritingWatcher([16, 17, 18], lambda kind, data: seen.append(data["numbers"]))
    for piece in ['{"footnotes": [{"num', 'ber": 16, "segments": []}, {"number"', ': 17', ', "x": 1}, {"number": 99}']:
        watch(piece)
    assert seen == [[16], [17]]  # each once, and only the batch's own footnotes


# ---- /api/process?progress=true and /api/progress/{id} ------------------------- #


@pytest.fixture
def fake_model():
    with mock.patch("aglc.pipeline.get_provider",
                    side_effect=lambda *a, **k: get_provider("fake:e2e", responses=[EXTRACTION])) as m:
        yield m


def _start(client):
    return client.post("/api/process", data={"progress": "true"}, files={"file": ("essay.docx", ESSAY.read_bytes(), DOCX)})


def _wait(client, session_id, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        snap = client.get(f"/api/progress/{session_id}").json()
        if snap["status"] != "processing":
            return snap
        time.sleep(0.05)
    raise AssertionError("the job didn't finish")


def test_progress_flow_ends_with_the_same_result_as_the_direct_call(fake_model):
    client = TestClient(api.app)
    started = _start(client)
    assert started.status_code == 202 and started.json()["status"] == "processing"
    snap = _wait(client, started.json()["id"])
    assert snap["status"] == "done" and snap["total"] == 10
    assert snap["done"] == list(range(1, 11)) and snap["stage"] == "writing_doc"
    direct = client.post("/api/process", files={"file": ("essay.docx", ESSAY.read_bytes(), DOCX)}).json()
    assert [f["formatted"] for f in snap["result"]["footnotes"]] == [f["formatted"] for f in direct["footnotes"]]
    # the progress itself carries only the text of the footnotes the page is about to show
    assert not any(key in snap for key in ("footnotes", "original", "formatted"))
    assert set(snap["showing"]) == {str(n) for n in snap["read"]} and snap["read"] == list(range(1, 11))
    assert all(set(entry) == {"text", "italic", "found"} for entry in snap["showing"].values())
    assert sum(snap["kinds"].values()) == sum(len(entry["found"]) for entry in snap["showing"].values())


def test_a_failure_in_the_background_is_reported_without_details(fake_model, tmp_path):
    client = TestClient(api.app)
    with mock.patch("aglc.pipeline.process_docx", side_effect=LLMError("sk-secret upstream said no")):
        snap = _wait(client, _start(client).json()["id"])
    assert snap["status"] == "failed" and snap["error"]["status"] == 502
    assert "sk-secret" not in json.dumps(snap)


def test_unknown_progress_is_404():
    assert TestClient(api.app).get("/api/progress/not-a-session").status_code == 404


@pytest.fixture
def paid(monkeypatch, tmp_path, fake_model):
    monkeypatch.setenv("AGLC_PAYMENTS", "fake")
    monkeypatch.setenv("AGLC_DATA_DIR", str(tmp_path / "data"))
    reset_payment_providers()
    billing._last_checked.clear()
    billing._semaphore = None
    yield fake_model
    reset_payment_providers()


def test_paid_jobs_hold_the_processing_slot_until_they_finish(paid, monkeypatch):
    monkeypatch.setenv("AGLC_MAX_CONCURRENT", "1")
    client = TestClient(api.app)
    with billing.processing_slot():  # another document in flight: refused straight away
        busy = _start(client)
    assert busy.status_code == 503 and busy.headers["retry-after"]
    started = _start(client)
    assert started.status_code == 202 and started.cookies.get(billing.ANON_COOKIE)  # set as on a direct call
    snap = _wait(client, started.json()["id"])
    assert snap["status"] == "done" and snap["result"]["locked"] is True  # the preview, as before
    assert _start(client).status_code == 202  # the slot was given back
