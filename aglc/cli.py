"""Command-line interface for the AGLC4 citation tool."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich import print as rprint
from rich.table import Table

from . import pipeline
from .formatters import formatter_for
from .llm.base import DEFAULT_SPEC, available_providers, get_provider
from .models import Citation
from .config import load_env

load_env()

app = typer.Typer(
    name="aglc",
    help="Format legal citations in Word documents to AGLC4 (Australian Guide to Legal Citation, 4th ed)",
)


@app.command()
def fix(
    input_path: Annotated[Path, typer.Argument(help="Input .docx file")],
    output_path: Annotated[Optional[Path], typer.Option("-o", "--output", help="Output .docx file (default: INPUT stem + '.aglc.docx')")] = None,
    model: Annotated[Optional[str], typer.Option("--model", help="LLM provider:model (default: AGLC_LLM or anthropic:claude-opus-5)")] = None,
    no_track_changes: Annotated[bool, typer.Option("--no-track-changes", help="Don't use tracked changes")] = False,
    no_bibliography: Annotated[bool, typer.Option("--no-bibliography", help="Don't generate bibliography")] = False,
    report: Annotated[Optional[Path], typer.Option("--report", help="Save JSON report to file")] = None,
) -> None:
    """Fix citations in a Word document to AGLC4 format.

    Reads footnotes from INPUT, processes them through an LLM to extract and
    normalize citations, then writes the result to OUTPUT with tracked changes.
    """
    try:
        # Validate input
        if not input_path.exists():
            rprint(f"[red]Error: Input file not found: {input_path}[/red]")
            raise typer.Exit(code=1)

        if not input_path.suffix.lower() == ".docx":
            rprint(f"[red]Error: Input must be a .docx file, got {input_path.suffix}[/red]")
            raise typer.Exit(code=1)

        # Set default output
        if output_path is None:
            output_path = input_path.parent / f"{input_path.stem}.aglc.docx"

        # Process
        rprint(f"[blue]Processing {input_path}...[/blue]")
        result = pipeline.process_docx(
            input_path,
            output_path,
            provider=model,
            bibliography=not no_bibliography,
            track_changes=not no_track_changes,
        )

        # Write output
        rprint(f"[green]✓ Saved to {output_path}[/green]")

        # Print summary
        changed_count = sum(1 for fn in result.footnotes if fn.changed)
        total_count = len(result.footnotes)
        rprint(f"\n[bold]Summary:[/bold] {changed_count}/{total_count} footnotes changed")

        # Print changed footnotes
        if result.footnotes and any(fn.changed for fn in result.footnotes):
            rprint("\n[bold]Changed footnotes:[/bold]")
            for fn in result.footnotes:
                if fn.changed:
                    before = fn.original.to_markup()
                    after = fn.formatted.to_markup()
                    rprint(f"  {fn.number}: {before} → {after}")

        # Print warnings
        if result.warnings:
            rprint("\n[bold yellow]Warnings:[/bold yellow]")
            for w in result.warnings:
                if w.footnote:
                    rprint(f"  Footnote {w.footnote}: {w.message}")
                else:
                    rprint(f"  {w.message}")

        # Save report if requested
        if report:
            report_data = result.model_dump(mode="json")
            with open(report, "w") as f:
                json.dump(report_data, f, indent=2)
            rprint(f"\n[blue]Report saved to {report}[/blue]")

    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        if "--debug" in sys.argv:
            traceback.print_exc()
        raise typer.Exit(code=1)


@app.command()
def providers() -> None:
    """List available LLM providers and the default specification."""
    try:
        available = available_providers()
        rprint("[bold]Available LLM providers:[/bold]")
        for name in available:
            rprint(f"  • {name}")

        rprint(f"\n[bold]Default:[/bold] {DEFAULT_SPEC}")
        env_spec = get_provider()
        rprint(f"[bold]Current (from $AGLC_LLM or default):[/bold] {env_spec.name}:{env_spec.model}")
    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@app.command()
def format_json(
    input_file: Annotated[Path, typer.Argument(help="JSON file containing Citation objects")],
) -> None:
    """Format a JSON list of Citation objects to AGLC4.

    Useful for testing formatters without an LLM. INPUT should be a JSON file
    containing a list of Citation objects (as serialized by Pydantic).
    """
    try:
        if not input_file.exists():
            rprint(f"[red]Error: File not found: {input_file}[/red]")
            raise typer.Exit(code=1)

        with open(input_file) as f:
            data = json.load(f)

        if not isinstance(data, list):
            rprint("[red]Error: JSON must be a list of Citation objects[/red]")
            raise typer.Exit(code=1)

        for item in data:
            try:
                citation = Citation.model_validate(item)
                formatter = formatter_for(citation)
                full = formatter.full(citation)
                rprint(full.to_markup())
            except Exception as e:
                rprint(f"[red]Error formatting citation: {e}[/red]")

    except json.JSONDecodeError as e:
        rprint(f"[red]Error: Invalid JSON: {e}[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


@app.command()
def serve(
    host: Annotated[str, typer.Option("--host", help="Host to bind to")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port", help="Port to bind to")] = 8000,
) -> None:
    """Start the FastAPI web server.

    Runs the API on http://HOST:PORT. The web UI is available at the root path.
    """
    try:
        import uvicorn

        from . import api

        rprint(f"[blue]Starting server on http://{host}:{port}[/blue]")
        uvicorn.run(api.app, host=host, port=port, log_level="info")
    except ImportError:
        rprint("[red]Error: FastAPI/uvicorn not installed. Run: uv sync[/red]")
        raise typer.Exit(code=1)
    except Exception as e:
        rprint(f"[red]Error: {e}[/red]")
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
