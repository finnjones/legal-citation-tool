# AGLC4 Citation Tool

Format legal citations in Word documents to the *Australian Guide to Legal Citation* (4th ed), including *Ibid*, (*n x*) subsequent references, short titles, signals, and a generated bibliography.

## Features

- **Extract citations** from footnotes using an LLM (Claude, GPT, Gemini, or any OpenAI-compatible API)
- **Reformat to AGLC4** with deterministic, tested formatters
- **Preserve source documents** with Word tracked changes
- **Generate bibliography** sorted by category (cases, legislation, secondary sources, etc.)
- **Multiple interfaces**: CLI, HTTP API, and web UI
- **Model-agnostic**: Works with Anthropic Claude, OpenAI, Google Gemini, Ollama, LM Studio, etc.

## Installation

```bash
# Clone and install
git clone https://github.com/yourusername/aglc-citation-tool.git
cd Legal\ Citation\ Tool
uv sync --all-extras
```

## Configuration

The tool needs an AI model to read the citations in your footnotes. The model only
extracts structured data; all AGLC formatting is done by deterministic code, so a
small, cheap model is enough.

The easiest setup is a `.env` file in the project folder (git-ignored):

```bash
cp .env.example .env    # then edit it
```

```bash
# .env: recommended, cheap and fast via OpenRouter (https://openrouter.ai/keys)
AGLC_LLM=openrouter:deepseek/deepseek-v4-flash
OPENROUTER_API_KEY=sk-or-...
```

Any model on OpenRouter works: use `openrouter:<model id from openrouter.ai/models>`.
Real environment variables override `.env`. Other providers:

```bash
AGLC_LLM=anthropic:claude-opus-5       # ANTHROPIC_API_KEY (the built-in default)
AGLC_LLM=openai:<model>                # OPENAI_API_KEY
AGLC_LLM=gemini:<model>                # GEMINI_API_KEY
AGLC_LLM=openai-compatible:llama3.1    # local Ollama / LM Studio / vLLM;
                                       # AGLC_OPENAI_BASE_URL=http://localhost:11434/v1
```

You can also pick a model per run: `aglc fix essay.docx --model openrouter:deepseek/deepseek-v4-flash`,
or type it into the Model field in the web app. `aglc providers` lists what's available.

### Try it

`examples/test_essay.docx` is a short essay with 24 deliberately messy footnotes
(regenerate it with `uv run python examples/make_test_essay.py`):

```bash
uv run aglc fix examples/test_essay.docx
```

## Usage

### CLI: `aglc fix`

Process a Word document:

```bash
aglc fix essay.docx                           # Output: essay.aglc.docx
aglc fix essay.docx -o output.docx           # Custom output path
aglc fix essay.docx --model openai:gpt-4o    # Specify model
aglc fix essay.docx --no-track-changes       # Disable tracked changes
aglc fix essay.docx --no-bibliography        # Skip bibliography
aglc fix essay.docx --report changes.json    # Save JSON report
```

**Output:**
- Processed `.docx` with tracked changes and bibliography
- Console summary: number of footnotes changed, before/after list, warnings
- Optional JSON report with all changes and metadata

### CLI: `aglc format-json`

Format Citation objects from JSON (useful for testing formatters):

```bash
aglc format-json citations.json
```

`citations.json` should contain a list of Citation objects (as Pydantic serialized JSON). Outputs each formatted citation to stdout.

### CLI: `aglc providers`

List available LLM providers:

```bash
aglc providers
# Available LLM providers:
#   • anthropic
#   • gemini
#   • openai
#   • openai-compatible
#   • openrouter
# Default: anthropic:claude-opus-5
```

### CLI: `aglc serve`

Start the web server:

```bash
aglc serve                    # http://127.0.0.1:8000
aglc serve --host 0.0.0.0   # All interfaces
aglc serve --port 9000      # Custom port
```

Opens at http://localhost:8000 — upload documents, view results, download processed files.

### HTTP API

#### `GET /`
Serves the web UI.

#### `GET /api/providers`
```json
{"providers": ["anthropic", "fake", "gemini", "openai", "openai-compatible", "openrouter"], "default": "openrouter:deepseek/deepseek-v4-flash"}
```

#### `POST /api/process`
Multipart form submission (e.g., from the web UI or `curl`).

**Parameters:**
- `file` (required): `.docx` document
- `model` (optional): `"provider:model"` (defaults to `$AGLC_LLM`)
- `track_changes` (optional, bool, default true)
- `bibliography` (optional, bool, default true)

**Response:**
```json
{
  "id": "uuid-string",
  "footnotes": [
    {
      "number": 1,
      "original": "*Case v State* [2020] HCA 1",
      "original_html": "<em>Case v State</em> [2020] HCA 1",
      "formatted": "*Case v State* [2020] HCA 1",
      "formatted_html": "<em>Case v State</em> [2020] HCA 1",
      "changed": false
    }
  ],
  "bibliography": [
    {
      "heading": "B Cases",
      "entries": ["<em>Case v State</em> [2020] HCA 1"]
    }
  ],
  "warnings": [
    {"footnote": 3, "message": "[MISSING: report] — manual review needed"}
  ]
}
```

#### `GET /api/download/{session_id}`
Download the processed `.docx` file from a session.

### Web UI

1. **Upload**: Drag-and-drop or click to select a `.docx` file
2. **Configure**: Choose LLM, enable/disable tracked changes and bibliography
3. **Process**: Click the "Process" button; results appear below
4. **Review**: View summary, changed footnotes (highlighted), warnings, and bibliography
5. **Download**: Click "Download" to save the processed `.docx`

The UI is responsive and works on phones; light/dark mode follows system preference.

## Architecture

The processing pipeline (see `PLAN.md` for details):

```
.docx
  ↓ (read_footnotes)
Footnote (raw runs)
  ↓ (Extractor: LLM)
Footnote (segments: text + Citation objects)
  ↓ (normalise_citation)
Footnote (segments: resolved short titles, ibid rules)
  ↓ (render_document)
ProcessResult (FootnoteResult list, bibliography, warnings)
  ↓ (write_document)
.docx (tracked changes + bibliography)
```

**Key principles:**
- **An LLM extracts; code formats.** The model only turns messy text into structured `Citation` objects. Every character of output is produced by deterministic, tested formatters.
- **Model-agnostic.** Only `aglc/llm/providers/` imports vendor SDKs.
- **Never invent.** Missing data is rendered as `[MISSING: field]` and reported.
- **The user stays in control.** Changes are written as Word tracked changes plus a JSON report.

## Adding a New AI Provider

Create a subclass of `LLMProvider` in a new file `aglc/llm/providers/yourprovider.py`:

```python
from aglc.llm.base import LLMProvider, register_provider

@register_provider("yourprovider")
class YourProvider(LLMProvider):
    """YourProvider: llm_name:model_name (e.g., 'yourprovider:model-1')"""
    
    def _complete_json(self, *, system: str, user: str, schema: dict, schema_name: str) -> str:
        """Return raw JSON text matching the schema.
        
        The base class handles validation and retries with errors fed back.
        You only need to call the model and return its response text.
        """
        import yourprovider_sdk
        
        client = yourprovider_sdk.Client(api_key=os.environ["YOURPROVIDER_API_KEY"])
        response = client.messages.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # Use native structured output if available, else instruct the model
        )
        return response.content[0].text
```

Then register it in `aglc/llm/providers/__init__.py`:

```python
from . import yourprovider  # noqa: F401
```

Now use it:

```bash
export AGLC_LLM=yourprovider:model-1
aglc fix essay.docx
```

## AGLC4 Coverage

| Phase | Content |
|-------|---------|
| ✓ Implemented | Ch 1 General rules (*Ibid*, *(n x)*, short titles, signals, pinpoints, bibliography) |
| ✓ Implemented | Ch 2 Cases (reported, medium-neutral, unreported) |
| ✓ Implemented | Ch 3 Legislation (Acts, delegated, bills, constitutions) |
| ✓ Implemented | Ch 5-7 Secondary sources (journal articles, books, chapters, reports, newspapers, websites) |
| ✓ Implemented | Ch 8 Treaties |
| ✗ Not yet | Ch 9-14 Other international materials |
| ✗ Not yet | Ch 15-26 Foreign domestic law |
| ✗ Not yet | Body-text citations (footnotes only) |

## Limitations

- **Footnotes only**: Body-text citations are not supported.
- **Always review tracked changes**: The LLM extracts citations from free text, which can be ambiguous. Use the report and tracked changes to verify and correct.
- **Manual review for edge cases**: Unreported cases, complex pinpoints, and non-standard sources may need manual adjustment.
- **No API keys in code**: Keep `ANTHROPIC_API_KEY` and similar environment variables secret; never commit them.

## Development

Run tests:

```bash
uv run pytest tests/ -xvs
```

Formatter examples come from `reference/AGLC4.pdf` and live in `tests/aglc4_examples/`.

## References

- [Australian Guide to Legal Citation (4th ed)](https://law.unimelb.edu.au/research/australian-guide-to-legal-citation)
- Project architecture: see `PLAN.md` for detailed design decisions.

## License

MIT
