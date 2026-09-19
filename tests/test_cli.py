"""Tests for the CLI interface."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from typer.testing import CliRunner

from aglc import pipeline
from aglc.cli import app
from aglc.models import (
    Citation,
    FootnoteResult,
    LegislationSource,
    ProcessResult,
    RichText,
    Run,
)

runner = CliRunner()


# ---- Fixtures -------------------------------------------------------------- #


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_docx(temp_dir):
    """Create a minimal test .docx file."""
    docx_path = temp_dir / "sample.docx"
    # Create a minimal valid docx (just a mock file for testing)
    docx_path.write_bytes(b"PK\x03\x04")  # ZIP magic
    return docx_path


@pytest.fixture
def fake_process_result():
    """Create a sample ProcessResult for mocking."""
    return ProcessResult(
        footnotes=[
            FootnoteResult(
                number=1,
                original=RichText(runs=[Run(text="Competition and Consumer Act 2010 (Cth)", italic=False)]),
                formatted=RichText(runs=[Run(text="*Competition and Consumer Act*", italic=True), Run(text=" 2010 (Cth)", italic=False)]),
            ),
        ],
        bibliography=[],
        warnings=[],
    )


# ---- Tests: aglc fix ------------------------------------------------------- #


def test_fix_command_success(sample_docx, temp_dir, fake_process_result):
    """Test successful fix command."""
    output_file = temp_dir / "output.docx"

    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        result = runner.invoke(
            app,
            ["fix", str(sample_docx), "-o", str(output_file)],
        )

        assert result.exit_code == 0
        assert "1/1 footnotes changed" in result.stdout
        mock_process.assert_called_once()


def test_fix_command_missing_file(temp_dir):
    """Test fix command with missing input file."""
    result = runner.invoke(app, ["fix", str(temp_dir / "nonexistent.docx")])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


def test_fix_command_invalid_extension(sample_docx, temp_dir):
    """Test fix command with non-.docx file."""
    txt_file = temp_dir / "file.txt"
    txt_file.write_text("test")

    result = runner.invoke(app, ["fix", str(txt_file)])
    assert result.exit_code == 1
    assert ".docx" in result.stdout.lower()


def test_fix_command_default_output(sample_docx, temp_dir, fake_process_result):
    """Test fix command generates default output filename."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        result = runner.invoke(app, ["fix", str(sample_docx)])

        assert result.exit_code == 0
        # Check that the call used the default output name
        call_args = mock_process.call_args
        output_path = call_args[0][1]
        assert output_path.name == "sample.aglc.docx"


def test_fix_command_with_model(sample_docx, temp_dir, fake_process_result):
    """Test fix command with explicit model."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        result = runner.invoke(
            app,
            ["fix", str(sample_docx), "--model", "openai:gpt-4"],
        )

        assert result.exit_code == 0
        call_args = mock_process.call_args
        # call_args.args are positional args, call_args.kwargs are keyword args
        # The provider is passed as a positional argument in position 2
        model_arg = call_args.args[2] if len(call_args.args) > 2 else call_args.kwargs.get("provider")
        assert model_arg == "openai:gpt-4"


def test_fix_command_no_track_changes(sample_docx, temp_dir, fake_process_result):
    """Test fix command with --no-track-changes."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        result = runner.invoke(
            app,
            ["fix", str(sample_docx), "--no-track-changes"],
        )

        assert result.exit_code == 0
        call_args = mock_process.call_args
        assert call_args[1]["track_changes"] is False


def test_fix_command_no_bibliography(sample_docx, temp_dir, fake_process_result):
    """Test fix command with --no-bibliography."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        result = runner.invoke(
            app,
            ["fix", str(sample_docx), "--no-bibliography"],
        )

        assert result.exit_code == 0
        call_args = mock_process.call_args
        assert call_args[1]["bibliography"] is False


def test_fix_command_with_report(sample_docx, temp_dir, fake_process_result):
    """Test fix command saves JSON report."""
    report_file = temp_dir / "report.json"

    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        result = runner.invoke(
            app,
            ["fix", str(sample_docx), "--report", str(report_file)],
        )

        assert result.exit_code == 0
        assert report_file.exists()

        with open(report_file) as f:
            report_data = json.load(f)

        assert "footnotes" in report_data
        assert len(report_data["footnotes"]) == 1


def test_fix_command_display_warnings(sample_docx, temp_dir):
    """Test fix command displays warnings."""
    result_with_warnings = ProcessResult(
        footnotes=[
            FootnoteResult(
                number=1,
                original=RichText(runs=[Run(text="something")]),
                formatted=RichText(runs=[Run(text="something")]),
            ),
        ],
        bibliography=[],
        warnings=[
            {"footnote": 1, "message": "Missing author name"},
        ],
    )

    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = result_with_warnings

        result = runner.invoke(app, ["fix", str(sample_docx)])

        assert result.exit_code == 0
        assert "Warnings" in result.stdout
        assert "Missing author name" in result.stdout


# ---- Tests: aglc providers ------------------------------------------------- #


def test_providers_command():
    """Test providers command lists available providers."""
    result = runner.invoke(app, ["providers"])
    assert result.exit_code == 0
    assert "Available LLM providers" in result.stdout
    assert "anthropic" in result.stdout
    assert "Default" in result.stdout


# ---- Tests: aglc format-json ----------------------------------------------- #


def test_format_json_command(temp_dir):
    """Test format-json command."""
    citations = [
        {
            "source": {
                "type": "legislation",
                "kind": "act",
                "title": "Competition and Consumer Act",
                "year": "2010",
                "jurisdiction": "Cth",
            },
            "pinpoints": [],
            "signal": None,
            "short_title": None,
        }
    ]

    json_file = temp_dir / "citations.json"
    with open(json_file, "w") as f:
        json.dump(citations, f)

    result = runner.invoke(app, ["format-json", str(json_file)])
    assert result.exit_code == 0
    assert "Competition and Consumer Act" in result.stdout


def test_format_json_missing_file(temp_dir):
    """Test format-json with missing file."""
    result = runner.invoke(app, ["format-json", str(temp_dir / "nonexistent.json")])
    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


def test_format_json_invalid_json(temp_dir):
    """Test format-json with invalid JSON."""
    json_file = temp_dir / "invalid.json"
    json_file.write_text("{invalid json")

    result = runner.invoke(app, ["format-json", str(json_file)])
    assert result.exit_code == 1
    assert "invalid json" in result.stdout.lower()


def test_format_json_not_a_list(temp_dir):
    """Test format-json with non-list JSON."""
    json_file = temp_dir / "not_list.json"
    with open(json_file, "w") as f:
        json.dump({"key": "value"}, f)

    result = runner.invoke(app, ["format-json", str(json_file)])
    assert result.exit_code == 1
    assert "list" in result.stdout.lower()


# ---- Tests: aglc serve (basic) --------------------------------------------- #


def test_serve_command_starts():
    """Test serve command (basic check that it's callable)."""
    # We can't really test that uvicorn starts, but we can check the command exists
    result = runner.invoke(app, ["serve", "--help"])
    assert result.exit_code == 0
    assert "Start the FastAPI web server" in result.stdout
