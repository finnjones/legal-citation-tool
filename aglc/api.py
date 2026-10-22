"""FastAPI web server and API endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from lxml.etree import XMLSyntaxError

from . import __version__, billing, guards, pipeline, retention, site
from .progress import Progress, jobs, safe
from .docx_io import UnsafeDocxError
from .llm.base import LLMError, available_providers, default_spec, get_provider
from .models import ProcessResult

from .config import load_env

log = logging.getLogger("aglc")


_NOT_A_DOCX = (zipfile.BadZipFile, KeyError, UnsafeDocxError, XMLSyntaxError)


def _status_for(e: Exception) -> int:
    if isinstance(e, (*_NOT_A_DOCX, ValueError)):
        return 400  # not a valid (or safe) .docx, or a malformed model spec
    if isinstance(e, LLMError) or type(e).__module__.split(".")[0] in ("openai", "anthropic", "google"):
        return 502  # the AI provider failed (bad key, no credit, model unavailable...)
    return 500


def _describe(e: Exception) -> str:
    """What the page is told. Never the exception's own text (it can carry provider
    responses, paths or footnote text); that goes to the server log."""
    if isinstance(e, _NOT_A_DOCX):
        return "That file isn't a valid Word (.docx) document. Open it in Word and save it as .docx, then try again."
    status = _status_for(e)
    if status == 400:
        return "That document couldn't be read. Check it opens in Word as a .docx, then try again."
    if status == 502:
        return "The AI model didn't respond. Nothing has been charged; please try again in a minute."
    return "Something went wrong processing your document. Nothing has been charged; please try again."


DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_WRONG_TYPE = {
    ".doc": "That's an older Word .doc file. Open it in Word, choose File > Save As > Word Document (.docx), then upload that.",
    ".pdf": "That's a PDF. This tool edits Word documents: upload the .docx you wrote the essay in.",
    ".pages": "That's a Pages file. In Pages, choose File > Export To > Word, then upload the .docx.",
    ".odt": "That's an OpenDocument file. Save it as Word (.docx), then upload that.",
    ".rtf": "That's an RTF file. Save it as Word (.docx), then upload that.",
}


def wrong_type_message(filename: str | None) -> str:
    suffix = Path(filename or "").suffix.lower()
    return _WRONG_TYPE.get(suffix, "This tool reads Word documents (.docx) only. Save your essay as .docx, then upload that.")

load_env()

# Temporary directory for uploads and outputs
_TEMP_DIR = Path(tempfile.gettempdir()) / "aglc_sessions"
_TEMP_DIR.mkdir(parents=True, exist_ok=True)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Delete documents past $AGLC_RETENTION_HOURS now and every few minutes (aglc/retention.py)."""
    guards.install_log_redaction()
    sweeper = asyncio.create_task(retention.run_periodically(_TEMP_DIR))
    try:
        yield
    finally:
        sweeper.cancel()


app = FastAPI(title="Aforecite API", lifespan=_lifespan)
app.add_middleware(guards.GuardMiddleware)  # 413 over $AGLC_MAX_UPLOAD_MB, security headers
app.include_router(billing.router)  # every route 404s unless AGLC_PAYMENTS is set
app.mount("/assets", StaticFiles(directory=site.WEB_DIR / "assets", check_dir=False), name="assets")
guards.install_log_redaction()
guards.install_app_logging()


def _sessions_dir() -> Path:
    """Paid documents are kept in $AGLC_DATA_DIR, which outlives the temp directory."""
    return billing.sessions_dir() if billing.enabled() else _TEMP_DIR


# ---- Shared dependencies -------------------------------------------------- #


def _clean_provider(spec: str | None) -> str | None:
    """Validate and normalize provider spec."""
    if spec is None:
        return None
    if ":" not in spec:
        raise ValueError(f"Provider spec must be 'name:model', got {spec!r}")
    return spec


# ---- Static files ---------------------------------------------------------- #


@app.get("/")
async def root(request: Request) -> HTMLResponse:
    """Serve the web UI (the landing page and the tool are one page)."""
    return site.index(request)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> FileResponse:
    """Browsers ask for this whatever the page says; the icon is an SVG."""
    return FileResponse(site.WEB_DIR / "assets" / "favicon.svg", media_type="image/svg+xml")


@app.get("/privacy")
@app.get("/terms")
@app.get("/refunds")
@app.get("/about")
async def static_page(request: Request) -> HTMLResponse:
    return site.page(request.url.path.strip("/"), request)


@app.get("/guides")
async def guides_index(request: Request) -> HTMLResponse:
    return site.guides_index(request)


@app.get("/guides/{slug}")
async def guide_page(slug: str, request: Request) -> HTMLResponse:
    """One AGLC4 guide page; an unknown slug is a 404."""
    return site.guide(slug, request)


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap(request: Request) -> Response:
    return site.sitemap(request)


@app.get("/robots.txt", include_in_schema=False)
async def robots(request: Request) -> Response:
    return site.robots(request)


@app.get("/api/sample")
async def sample_essay() -> FileResponse:
    """The demo essay (examples/test_essay.docx), so "Try a sample essay" needs no upload."""
    if not site.SAMPLE_ESSAY.is_file():
        raise HTTPException(status_code=404, detail="The sample essay isn't available")
    return FileResponse(site.SAMPLE_ESSAY, media_type=DOCX_TYPE, filename="sample-essay.docx")


@app.get("/status")
async def service_status() -> dict:
    """For uptime checks: the server is up and whether payments are on."""
    return {"status": "ok", "version": __version__, "payments": billing.enabled()}


# ---- API endpoints --------------------------------------------------------- #


@app.get("/api/providers")
async def get_providers() -> dict:
    """Get available LLM providers and the default (local use only: with payments on the
    server alone picks the model, so there is nothing to choose from)."""
    if billing.enabled():
        raise HTTPException(status_code=404, detail="Not found")
    try:
        providers = available_providers()
        return {"providers": providers, "default": default_spec()}
    except Exception as e:
        log.exception("listing providers failed")
        raise HTTPException(status_code=500, detail="Couldn't list the AI model providers.") from e


async def _save_upload(file: UploadFile, dest: Path) -> None:
    """Copy the upload to `dest` in chunks; 413 once it passes $AGLC_MAX_UPLOAD_MB (the
    middleware has already refused bodies far over it)."""
    limit, size = guards.max_upload_bytes(), 0
    with open(dest, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise HTTPException(status_code=413, detail=guards.too_large_message())
            f.write(chunk)


@app.post("/api/process")
async def process_document(
    request: Request,
    response: Response,
    file: Annotated[UploadFile, File(description="Word document (.docx)")],
    model: Annotated[str | None, Form()] = None,
    track_changes: Annotated[bool, Form()] = True,
    bibliography: Annotated[bool, Form()] = True,
    fix_body: Annotated[bool, Form()] = True,
    progress: Annotated[bool, Form()] = False,
) -> dict:
    """Process a Word document and return formatted citations.

    Args:
        file: .docx document
        model: LLM provider:model (optional)
        track_changes: Whether to use tracked changes in output
        bibliography: Whether to generate a bibliography
        fix_body: Whether to fix footnote numbers and headings in the body text
        progress: Answer straight away (202, `{id, status: "processing"}`) and process in the
            background; GET /api/progress/{id} then reports progress and, at the end, the result

    Returns:
        JSON with id, footnotes, bibliography, warnings, body_fixes. With payments on
        (see aglc/billing.py) this is a redacted preview with `locked: true`.
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail=wrong_type_message(file.filename))
    if file.size is not None and file.size > guards.max_upload_bytes():
        raise HTTPException(status_code=413, detail=guards.too_large_message())

    paid = billing.enabled()
    visitor = billing.admit(request, response) if paid else None  # free-use quotas: 429
    if paid:
        model = None  # the server's $AGLC_LLM (and $AGLC_LLM_FALLBACK) only: it pays for the calls

    # Create session directory
    session_id = str(uuid.uuid4())
    session_dir = _sessions_dir() / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    started = False
    slot = None

    try:
        # Save original filename for later download
        original_stem = Path(file.filename or "document").stem

        # Save upload
        input_file = session_dir / "input.docx"
        await _save_upload(file, input_file)

        # Store original filename for download
        (session_dir / "original_filename.txt").write_text(original_stem)

        output_file = session_dir / "output.docx"
        options = {"model": model, "bibliography": bibliography, "track_changes": track_changes, "fix_body": fix_body}
        process = lambda **again: pipeline.process_docx(  # noqa: E731
            input_file, output_file, model,
            bibliography=bibliography, track_changes=track_changes, fix_body=fix_body, session=session_id, **again,
        )
        job = _Job(session_id, session_dir, file.filename, paid, process, options)
        if paid:
            await run_in_threadpool(billing.check_footnote_cap, input_file)  # 413, before any LLM call
            slot = billing.processing_slot()  # 503 when too many documents are in flight
            slot.__enter__()
            billing.start_document(session_id, file.filename, visitor)
            started = True
        if progress:
            job.start(slot)  # the job releases the slot when it finishes
            response.status_code = status.HTTP_202_ACCEPTED
            return {"id": session_id, "status": "processing"}
        try:
            return await run_in_threadpool(job.run)
        finally:
            if slot is not None:
                slot.__exit__(None, None, None)

    except Exception as e:
        # Clean up on error
        shutil.rmtree(session_dir, ignore_errors=True)
        if started:
            billing.fail_document(session_id)
        if slot is not None and (progress or not started):
            slot.__exit__(None, None, None)  # the job never started
        if isinstance(e, HTTPException):
            raise
        log.exception("processing session %s failed", session_id[:8])
        raise HTTPException(status_code=_status_for(e), detail=_describe(e)) from e


class _Job:
    """One document's processing: the pipeline, the paid second pass, saving the result."""

    def __init__(self, session_id: str, session_dir: Path, filename: str, paid: bool, process, options: dict) -> None:
        self.session_id, self.session_dir, self.filename = session_id, session_dir, filename
        self.paid, self.process, self.options = paid, process, options

    def run(self, progress: Progress | None = None) -> dict:
        """Process and save; the response body (with payments on, the preview)."""
        kwargs = {"progress": progress} if progress is not None else {}
        result: ProcessResult = self.process(**kwargs)
        if self.paid:
            # Nobody pays for footnotes the model failed to read: try those once more now.
            failed = pipeline.failed_footnotes(result)
            # Not when the provider looks down: the Extractor has already retried, and asking
            # again at once only doubles the wait. The free re-run is there for later.
            if failed and result.extraction is not None and not result.extraction.provider_down:
                log.info("retrying %d footnotes the model failed to read", len(failed))
                safe(progress)("note", {"kind": "retry_failed", "count": len(failed)})
                result = self.process(previous=result.extraction, only=failed, **kwargs)
            full = _result_json(self.session_id, result)
            return billing.save_result(self.session_id, self.filename, full, extraction=result.extraction,
                                       options=self.options)
        full = _result_json(self.session_id, result)
        # Kept for the same 24 hours as the documents, so a complaint can be looked into.
        billing.write_result(self.session_dir, self.filename, full, extraction=result.extraction, options=self.options)
        return full

    def start(self, slot) -> None:
        """Run in the background, reporting to `jobs`; the page polls /api/progress/{id}."""
        report = jobs.start(self.session_id)

        def work() -> None:
            try:
                jobs.finish(self.session_id, result=self.run(report))
            except Exception as e:  # noqa: BLE001 - reported to the page, logged in full here
                log.exception("processing session %s failed", self.session_id[:8])
                shutil.rmtree(self.session_dir, ignore_errors=True)
                if self.paid:
                    billing.fail_document(self.session_id)
                status_code = e.status_code if isinstance(e, HTTPException) else _status_for(e)
                detail = e.detail if isinstance(e, HTTPException) else _describe(e)
                jobs.finish(self.session_id, error={"status": status_code, "detail": detail})
            finally:
                if slot is not None:
                    slot.__exit__(None, None, None)

        threading.Thread(target=work, name=f"aglc-job-{self.session_id[:8]}", daemon=True).start()


@app.get("/api/progress/{session_id}")
async def get_progress(session_id: str) -> dict:
    """How far a document started with `progress=true` has got: footnote numbers read so far,
    the text of the few footnotes the page is about to show (with the citations read in
    them), the stage, what the tool is doing about any problem, and at the end the result
    (`status: "done"`) or the error (`status: "failed"`)."""
    snapshot = jobs.snapshot(session_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="That document isn't being processed (it may have finished a while ago).")
    return snapshot


@app.post("/api/rerun/{session_id}")
async def rerun_document(session_id: str) -> dict:
    """Re-run extraction, free, for just the footnotes the model failed to read (payments on).

    Doesn't use the daily free quota; limited to billing.MAX_RERUNS per document; a paid
    document stays unlocked. Returns the updated preview (or full result, once paid for).
    """
    if not billing.enabled():
        raise HTTPException(status_code=404, detail="Not found")
    session_id = billing.check_session_id(session_id)
    full, extraction, options = billing.rerun_inputs(session_id)
    failed = pipeline.failed_footnotes(full)
    if not failed:
        return billing.view(session_id, full)
    if extraction is None:
        raise HTTPException(status_code=409, detail="This document can't be re-run. Please process it again.")

    session_dir = billing.sessions_dir() / session_id
    # A paid document's .docx is only replaced once this works; one staging file per request,
    # so two re-runs at once (a double click) can't write into the same file.
    staged = session_dir / f"output.rerun.{uuid.uuid4().hex}.docx"
    with billing.processing_slot():
        billing.claim_rerun(session_id)  # 429 once the free re-runs are used up
        try:
            result = await run_in_threadpool(
                pipeline.process_docx, session_dir / "input.docx", staged, None,  # the server's model
                bibliography=options.get("bibliography", True), track_changes=options.get("track_changes", True),
                fix_body=options.get("fix_body", True), previous=extraction, only=failed,
            )
        except Exception as e:
            staged.unlink(missing_ok=True)
            log.exception("re-running session %s failed", session_id[:8])
            raise HTTPException(status_code=_status_for(e), detail=_describe(e)) from e
    staged.replace(session_dir / "output.docx")
    return billing.save_result(session_id, full["filename"], _result_json(session_id, result),
                               extraction=result.extraction)


def _result_json(session_id: str, result: ProcessResult) -> dict:
    """The API's view of a ProcessResult."""
    footnotes = []
    for fn in result.footnotes:
        footnotes.append(
            {
                "number": fn.number,
                "original": fn.original.to_markup(),
                "original_html": _richtext_to_html(fn.original),
                "formatted": fn.formatted.to_markup(),
                "formatted_html": _richtext_to_html(fn.formatted),
                "changed": fn.changed,
                # what changed and why, in plain words: [{"kind", "text", "rule"}] (aglc/explain.py)
                "changes": [c.model_dump() for c in fn.changes] if fn.changed else [],
                # "provider_error" / "not_returned" when left unchanged because extraction failed
                "extraction_failed": fn.extraction_failed,
            }
        )

    bibliography = []
    for section in result.bibliography:
        entries = [_richtext_to_html(entry) for entry in section.entries]
        bibliography.append({"heading": section.heading, "entries": entries})

    warnings = [{"footnote": w.footnote, "message": _public_warning(w.message)} for w in result.warnings]

    return {
        "id": session_id,
        "footnotes": footnotes,
        "bibliography": bibliography,
        "warnings": warnings,
        "body_fixes": [{"footnote": b.footnote, "message": b.message, "applied": b.applied}
                       for b in result.body_fixes],
        # cases checked against the case index: {"total", "checked", "flagged"} (aglc/verify.py)
        "case_check": result.case_check.model_dump(),
    }


@app.get("/api/download/{session_id}")
async def download_document(session_id: str) -> FileResponse:
    """Download the processed .docx file.

    Args:
        session_id: Session UUID from /api/process response

    Returns:
        The processed .docx file (402 until paid for, when payments are on)
    """
    # Validate session_id is a valid UUID
    try:
        session_id = str(uuid.UUID(session_id))
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid session ID")

    if billing.enabled():
        billing.require_unlocked(session_id)

    session_dir = _sessions_dir() / session_id
    output_file = session_dir / "output.docx"
    filename_file = session_dir / "original_filename.txt"

    if not output_file.exists():
        raise HTTPException(status_code=404, detail="Session not found or output not ready")

    # Get original filename
    original_stem = "document"
    if filename_file.exists():
        try:
            original_stem = filename_file.read_text().strip()
        except Exception:
            pass

    original_name = f"{original_stem}.aglc.docx"

    return FileResponse(
        output_file, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=original_name
    )


# ---- Utilities ------------------------------------------------------------ #


_FAILED_DETAIL = re.compile(r"^(extraction failed for footnotes \[[\d,\s]+\]):.*?(; left unchanged)$", re.I | re.S)


def _public_warning(message: str) -> str:
    """Drop the provider's error text from a failed-extraction warning (the extractor logs it).
    pipeline.failed_footnotes still recognises what is left."""
    return _FAILED_DETAIL.sub(r"\1\2", message)


def _richtext_to_html(richtext) -> str:
    """Convert RichText to HTML with <em> for italics."""
    html_parts = []
    for run in richtext.runs:
        text = _escape_html(run.text)
        if run.italic:
            html_parts.append(f"<em>{text}</em>")
        else:
            html_parts.append(text)
    return "".join(html_parts)


def _escape_html(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )
