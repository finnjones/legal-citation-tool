"""Tests for the FastAPI API."""

from __future__ import annotations

import json
import re
import tempfile
import uuid
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from aglc import api, guards, pipeline, site
from aglc.llm.base import LLMError
from aglc.models import (
    BibliographySection,
    BodyFix,
    FootnoteResult,
    ProcessResult,
    RichText,
    Run,
    Warning_,
)

client = TestClient(api.app)
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---- Fixtures -------------------------------------------------------------- #


@pytest.fixture
def fake_process_result():
    """Create a sample ProcessResult for mocking."""
    return ProcessResult(
        footnotes=[
            FootnoteResult(
                number=1,
                original=RichText(runs=[Run(text="Competition and Consumer Act 2010 (Cth)", italic=False)]),
                formatted=RichText(
                    runs=[
                        Run(text="Competition and Consumer Act", italic=True),
                        Run(text=" 2010 (Cth)", italic=False),
                    ]
                ),
            ),
        ],
        bibliography=[
            BibliographySection(
                heading="C Legislation",
                entries=[
                    RichText(
                        runs=[
                            Run(text="Competition and Consumer Act", italic=True),
                            Run(text=" 2010 (Cth)", italic=False),
                        ]
                    ),
                ],
            ),
        ],
        warnings=[
            Warning_(footnote=1, message="Test warning"),
        ],
        body_fixes=[
            BodyFix(footnote=1, message="footnote number moved after the ‘.’"),
        ],
    )


@pytest.fixture
def minimal_docx():
    """Create a minimal valid .docx file."""
    # Minimal ZIP-based docx (just magic bytes + minimal structure)
    docx_bytes = BytesIO()
    # PK zip header
    docx_bytes.write(b"PK\x03\x04")
    docx_bytes.seek(0)
    return docx_bytes.getvalue()


# ---- Tests: GET / ---------------------------------------------------------- #


def test_root_serves_html():
    """Test that GET / serves index.html."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>AGLC4 Citation Checker and Fixer for Word (.docx)</title>" in response.text
    assert "{{" not in response.text  # every placeholder filled
    assert site.BRAND in response.text


def test_root_file_not_found_handled():
    """Test that missing index.html is handled gracefully."""
    # Temporarily mock the file to not exist
    with mock.patch("pathlib.Path.exists", return_value=False):
        response = client.get("/")
        assert response.status_code == 404


# ---- Tests: GET /api/providers --------------------------------------------- #


def test_providers_endpoint():
    """Test /api/providers returns provider list."""
    response = client.get("/api/providers")
    assert response.status_code == 200

    data = response.json()
    assert "providers" in data
    assert "default" in data
    assert isinstance(data["providers"], list)
    assert "anthropic" in data["providers"]
    assert ":" in data["default"]


# ---- Tests: POST /api/process ---------------------------------------------- #


def test_process_minimal(minimal_docx, fake_process_result):
    """Test minimal POST /api/process request."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        response = client.post(
            "/api/process",
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "footnotes" in data
        assert "bibliography" in data
        assert "warnings" in data


def test_process_with_options(minimal_docx, fake_process_result):
    """Test POST /api/process with model and options."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        response = client.post(
            "/api/process",
            data={
                "model": "openai:gpt-4",
                "track_changes": "false",
                "bibliography": "true",
                "fix_body": "false",
            },
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert response.status_code == 200
        call_args = mock_process.call_args
        assert call_args[0][2] == "openai:gpt-4"
        assert call_args[1]["track_changes"] is False
        assert call_args[1]["bibliography"] is True
        assert call_args[1]["fix_body"] is False


def test_process_response_format(minimal_docx, fake_process_result):
    """Test response format of /api/process."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        response = client.post(
            "/api/process",
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert response.status_code == 200
        data = response.json()

        # Check footnotes format
        assert len(data["footnotes"]) == 1
        fn = data["footnotes"][0]
        assert fn["number"] == 1
        assert "original" in fn
        assert "original_html" in fn
        assert "formatted" in fn
        assert "formatted_html" in fn
        assert "changed" in fn
        assert fn["extraction_failed"] is None
        assert "<em>" in fn["formatted_html"]

        # Check bibliography format
        assert len(data["bibliography"]) == 1
        bib_section = data["bibliography"][0]
        assert bib_section["heading"] == "C Legislation"
        assert len(bib_section["entries"]) > 0

        # Check warnings format
        assert len(data["warnings"]) == 1
        assert data["warnings"][0]["footnote"] == 1
        assert "message" in data["warnings"][0]

        # Check body text fixes format
        assert data["body_fixes"] == [{"footnote": 1, "message": "footnote number moved after the ‘.’", "applied": True}]


def test_process_non_docx_rejected():
    """Test that non-.docx files are rejected."""
    response = client.post(
        "/api/process",
        files={"file": ("test.txt", b"Not a docx", "text/plain")},
    )

    assert response.status_code == 400
    assert "docx" in response.json()["detail"].lower()


def test_process_missing_file():
    """Test POST /api/process without file."""
    response = client.post("/api/process")
    assert response.status_code == 422  # Unprocessable Entity


def test_process_error_handling(minimal_docx):
    """Test error handling in POST /api/process."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.side_effect = RuntimeError("Test error")

        response = client.post(
            "/api/process",
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "went wrong" in detail
        assert "Test error" not in detail  # the exception is logged, never shown


def test_process_ai_error_hides_provider_text(minimal_docx):
    with mock.patch("aglc.pipeline.process_docx", side_effect=LLMError("401 invalid key sk-secret")):
        response = client.post("/api/process", files={"file": ("test.docx", minimal_docx, DOCX)})
    assert response.status_code == 502
    assert "sk-secret" not in response.json()["detail"]
    assert "AI model" in response.json()["detail"]


@pytest.mark.parametrize(("name", "expected"), [
    ("essay.doc", "older Word .doc"),
    ("essay.pdf", "PDF"),
    ("essay.pages", "Pages"),
    ("essay.txt", ".docx"),
])
def test_wrong_file_type_gets_a_specific_message(name, expected):
    response = client.post("/api/process", files={"file": (name, b"x", "application/octet-stream")})
    assert response.status_code == 400
    assert expected in response.json()["detail"]


def test_process_rejects_files_over_10_mb():
    big = b"PK\x03\x04" + b"\0" * guards.max_upload_bytes()
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        response = client.post("/api/process", files={"file": ("big.docx", big, DOCX)})
    assert response.status_code == 413
    assert "10 MB" in response.json()["detail"]
    mock_process.assert_not_called()


def test_failed_extraction_warning_hides_provider_error(minimal_docx, fake_process_result):
    fake_process_result.warnings = [
        Warning_(message="extraction failed for footnotes [1, 2]: Error code: 402 - {'error': 'no credit'}; left unchanged"),
    ]
    with mock.patch("aglc.pipeline.process_docx", return_value=fake_process_result):
        data = client.post("/api/process", files={"file": ("test.docx", minimal_docx, DOCX)}).json()
    assert data["warnings"][0]["message"] == "extraction failed for footnotes [1, 2]; left unchanged"
    assert pipeline.failed_footnotes(data["warnings"]) == {1, 2}  # still recognised as failed


# ---- Tests: GET /api/download/{id} ----------------------------------------- #


def test_download_success(minimal_docx, fake_process_result):
    """Test successful download of processed document."""
    def mock_process_docx(src, dst, *args, **kwargs):
        """Mock process_docx that creates output file."""
        # Create the output file
        Path(dst).write_bytes(b"PK\x03\x04")
        return fake_process_result

    with mock.patch("aglc.pipeline.process_docx", side_effect=mock_process_docx):
        # First, process a document to get a session_id
        process_response = client.post(
            "/api/process",
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert process_response.status_code == 200
        session_id = process_response.json()["id"]

        # Now try to download
        download_response = client.get(f"/api/download/{session_id}")
        assert download_response.status_code == 200
        assert "application/vnd.openxmlformats" in download_response.headers["content-type"]


def test_download_nonexistent_session():
    """Test download with non-existent session ID."""
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/download/{fake_id}")
    assert response.status_code == 404


def test_download_invalid_uuid():
    """Test download with invalid UUID."""
    response = client.get("/api/download/not-a-uuid")
    assert response.status_code == 422


def test_download_filename(minimal_docx, fake_process_result):
    """Test that download has correct filename."""
    def mock_process_docx(src, dst, *args, **kwargs):
        """Mock process_docx that creates output file."""
        # Create the output file
        Path(dst).write_bytes(b"PK\x03\x04")
        return fake_process_result

    with mock.patch("aglc.pipeline.process_docx", side_effect=mock_process_docx):
        # Process
        process_response = client.post(
            "/api/process",
            files={"file": ("myessay.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        session_id = process_response.json()["id"]

        # Download
        download_response = client.get(f"/api/download/{session_id}")
        assert "myessay.aglc.docx" in download_response.headers.get("content-disposition", "")


# ---- Tests: HTML escaping -------------------------------------------------- #


def test_process_escapes_html_in_footnotes(minimal_docx):
    """Test that HTML special characters are escaped in response."""
    result_with_html_chars = ProcessResult(
        footnotes=[
            FootnoteResult(
                number=1,
                original=RichText(runs=[Run(text="Case v State <special> & \"quoted\"", italic=False)]),
                formatted=RichText(runs=[Run(text="Case v State <special> & \"quoted\"", italic=False)]),
            ),
        ],
        bibliography=[],
        warnings=[],
    )

    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = result_with_html_chars

        response = client.post(
            "/api/process",
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        data = response.json()
        html = data["footnotes"][0]["original_html"]

        # Check that special chars are escaped
        assert "&lt;" in html
        assert "&gt;" in html
        assert "&amp;" in html
        assert "&quot;" in html or "&#39;" in html


# ---- Tests: RichText HTML conversion --------------------------------------- #


def test_richtext_italic_conversion(minimal_docx):
    """Test that italic runs are converted to <em> tags."""
    result_with_italics = ProcessResult(
        footnotes=[
            FootnoteResult(
                number=1,
                original=RichText(
                    runs=[
                        Run(text="Case", italic=True),
                        Run(text=" v ", italic=False),
                        Run(text="State", italic=True),
                    ]
                ),
                formatted=RichText(
                    runs=[
                        Run(text="Case", italic=True),
                        Run(text=" v ", italic=False),
                        Run(text="State", italic=True),
                    ]
                ),
            ),
        ],
        bibliography=[],
        warnings=[],
    )

    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = result_with_italics

        response = client.post(
            "/api/process",
            files={"file": ("test.docx", b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        data = response.json()
        html = data["footnotes"][0]["original_html"]

        assert "<em>Case</em>" in html
        assert "<em>State</em>" in html
        assert " v " in html


# ---- Tests: the public site --------------------------------------------- #


@pytest.mark.parametrize("path", ["/privacy", "/terms", "/refunds", "/about"])
def test_static_pages(path):
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "{{" not in response.text
    assert site.BRAND in response.text
    for link in ("/about", "/privacy", "/terms", "/refunds"):  # the shared footer
        assert f'href="{link}"' in response.text


@pytest.mark.parametrize("path", ["/terms", "/refunds"])
def test_policy_pages_keep_consumer_law_rights(path):
    assert "Nothing here limits your rights under the Australian Consumer Law." in client.get(path).text


def test_privacy_page_marks_unknown_facts_as_todo():
    text = client.get("/privacy").text
    assert "[TODO: confirm the OpenRouter account's data settings" in text
    assert "OpenRouter" in text and "DeepSeek" in text
    assert "never used for training" not in text


def test_privacy_page_states_the_real_retention_period(monkeypatch):
    assert "deleted automatically 24 hours after" in client.get("/privacy").text  # the default
    monkeypatch.setenv("AGLC_RETENTION_HOURS", "48")
    text = client.get("/privacy").text
    assert "deleted automatically 48 hours after" in text and "TODO: retention" not in text


@pytest.mark.parametrize("path", ["/", "/privacy"])
def test_pages_load_no_third_party_fonts(path):
    text = client.get(path).text
    assert "fonts.googleapis.com" not in text and "fonts.gstatic.com" not in text
    assert 'href="/assets/fonts/fonts.css"' in text and 'rel="icon"' in text


def test_self_hosted_fonts_and_favicon_are_served():
    css = client.get("/assets/fonts/fonts.css")
    assert css.status_code == 200 and css.text.count("@font-face") == 6
    for url in sorted(set(re.findall(r'url\("(/assets/fonts/[^"]+)"\)', css.text))):
        font = client.get(url)
        assert font.status_code == 200 and font.content[:4] == b"wOF2", url
    icon = client.get("/favicon.ico")
    assert icon.status_code == 200 and icon.headers["content-type"].startswith("image/svg+xml")


def test_status():
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": api.__version__, "payments": False}


def test_sample_essay_is_served():
    response = client.get("/api/sample")
    assert response.status_code == 200
    assert response.headers["content-type"] == DOCX
    assert response.content == site.SAMPLE_ESSAY.read_bytes()
    assert "sample-essay.docx" in response.headers["content-disposition"]


def test_shared_stylesheet_is_served():
    response = client.get("/assets/chambers.css")
    assert response.status_code == 200
    assert "--accent: #1F3A5F" in response.text


def test_open_graph_tags_use_the_public_url(monkeypatch):
    monkeypatch.setenv("AGLC_PUBLIC_URL", "https://cite.example.com/")
    text = client.get("/").text
    assert '<meta property="og:image" content="https://cite.example.com/assets/og.png">' in text
    assert '<meta property="og:url" content="https://cite.example.com/">' in text
    assert '<meta name="description"' in text
    assert client.get("/assets/og.png").headers["content-type"] == "image/png"


def test_plausible_is_off_unless_configured(monkeypatch):
    assert "plausible.io" not in client.get("/").text
    monkeypatch.setenv("AGLC_PLAUSIBLE_DOMAIN", "cite.example.com")
    for path in ("/", "/privacy"):
        assert '<script defer data-domain="cite.example.com" src="https://plausible.io/js/script.js"></script>' in client.get(path).text


def test_price_on_the_page_comes_from_the_server():
    from aglc import billing

    text = client.get("/").text
    assert f"{billing.PRODUCTS['document'].display} per document" in text
    assert f"first {billing.PREVIEW_FULL} fixes free" in text
