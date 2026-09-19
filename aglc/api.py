"""FastAPI web server and API endpoints."""

from __future__ import annotations

import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import pipeline
from .llm.base import DEFAULT_SPEC, available_providers, get_provider
from .models import ProcessResult

app = FastAPI(title="AGLC4 Citation Tool API")

# Temporary directory for uploads and outputs
_TEMP_DIR = Path(tempfile.gettempdir()) / "aglc_sessions"
_TEMP_DIR.mkdir(parents=True, exist_ok=True)


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
async def root() -> FileResponse:
    """Serve the web UI."""
    web_dir = Path(__file__).parent.parent / "web"
    index_file = web_dir / "index.html"

    if not index_file.exists():
        raise HTTPException(status_code=404, detail="index.html not found")

    return FileResponse(index_file, media_type="text/html")


# ---- API endpoints --------------------------------------------------------- #


@app.get("/api/providers")
async def get_providers() -> dict:
    """Get available LLM providers and the default."""
    try:
        providers = available_providers()
        return {"providers": providers, "default": DEFAULT_SPEC}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing providers: {str(e)}")


@app.post("/api/process")
async def process_document(
    file: Annotated[UploadFile, File(description="Word document (.docx)")],
    model: Annotated[str | None, Form()] = None,
    track_changes: Annotated[bool, Form()] = True,
    bibliography: Annotated[bool, Form()] = True,
) -> dict:
    """Process a Word document and return formatted citations.

    Args:
        file: .docx document
        model: LLM provider:model (optional)
        track_changes: Whether to use tracked changes in output
        bibliography: Whether to generate a bibliography

    Returns:
        JSON with id, footnotes, bibliography, warnings
    """
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="File must be a .docx document")

    # Create session directory
    session_id = str(uuid.uuid4())
    session_dir = _TEMP_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Save original filename for later download
        original_stem = Path(file.filename or "document").stem

        # Save upload
        input_file = session_dir / "input.docx"
        with open(input_file, "wb") as f:
            content = await file.read()
            f.write(content)

        # Store original filename for download
        (session_dir / "original_filename.txt").write_text(original_stem)

        # Process in thread pool
        output_file = session_dir / "output.docx"
        result: ProcessResult = await run_in_threadpool(
            pipeline.process_docx,
            input_file,
            output_file,
            model,
            bibliography=bibliography,
            track_changes=track_changes,
        )

        # Format response
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
                }
            )

        bibliography = []
        for section in result.bibliography:
            entries = [_richtext_to_html(entry) for entry in section.entries]
            bibliography.append({"heading": section.heading, "entries": entries})

        warnings = [{"footnote": w.footnote, "message": w.message} for w in result.warnings]

        return {
            "id": session_id,
            "footnotes": footnotes,
            "bibliography": bibliography,
            "warnings": warnings,
        }

    except Exception as e:
        # Clean up on error
        try:
            shutil.rmtree(session_dir)
        except Exception:
            pass

        raise HTTPException(
            status_code=500, detail=f"Error processing document: {str(e)}"
        )


@app.get("/api/download/{session_id}")
async def download_document(session_id: str) -> FileResponse:
    """Download the processed .docx file.

    Args:
        session_id: Session UUID from /api/process response

    Returns:
        The processed .docx file
    """
    # Validate session_id is a valid UUID
    try:
        uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid session ID")

    session_dir = _TEMP_DIR / session_id
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
