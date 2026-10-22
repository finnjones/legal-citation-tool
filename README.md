# Aforecite: AGLC4 Citation Tool

Format legal citations in Word documents to the *Australian Guide to Legal Citation* (4th ed), including *Ibid*, (*n x*) subsequent references, short titles, signals, and a generated bibliography.

## Features

- **Extract citations** from footnotes using an LLM (Claude, GPT, Gemini, or any OpenAI-compatible API)
- **Reformat to AGLC4** with deterministic, tested formatters
- **Preserve source documents** with Word tracked changes
- **Generate bibliography** sorted by category (cases, legislation, secondary sources, etc.)
- **Fix the body text around citations**: moves footnote numbers after punctuation (r 1.1.2,
  "Act¹." → "Act.¹") and removes spaces before them, sets italic footnote numbers upright,
  italicises citations in the text correctly (not the jurisdiction or the medium neutral
  citation; the 'v' too), writes "ss 57–64" for section ranges, and keeps headings with the
  text that follows them
- **Flags what it can't safely fix**: a missing full stop before a new sentence, an italicised
  possessive like "*Maynard’s* affidavit" (the person, not the case), and *Ibid* or "(n x)" with
  no pinpoint
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
# AGLC_LLM is optional: the default is the OpenRouter preset "aglc" (openrouter:@preset/aglc)
OPENROUTER_API_KEY=sk-or-...
```

Any model on OpenRouter works: use `openrouter:<model id from openrouter.ai/models>`.
Real environment variables override `.env`. Other providers:

```bash
AGLC_LLM=anthropic:claude-opus-5       # ANTHROPIC_API_KEY
AGLC_LLM=openai:<model>                # OPENAI_API_KEY
AGLC_LLM=gemini:<model>                # GEMINI_API_KEY
AGLC_LLM=openai-compatible:llama3.1    # local Ollama / LM Studio / vLLM;
                                       # AGLC_OPENAI_BASE_URL=http://localhost:11434/v1
```

You can also pick a model per run: `aglc fix essay.docx --model openrouter:deepseek/deepseek-v4.1-flash-1017`,
or type it into the Model field in the web app. `aglc providers` lists what's available.

If the model sends back an empty reply, times out or its host is overloaded, the request is
retried after 1s and then 3s (on OpenRouter, the retry is routed away from the upstream host
that failed). A batch that still fails is asked again in batches of 5, then one footnote at a
time, so one bad request doesn't leave a whole batch unformatted.

Each request has a hard limit, `AGLC_REQUEST_DEADLINE` (default 90s): on OpenAI and OpenRouter the
reply is streamed and given up on at the deadline, even if the host keeps the connection open with
keep-alive bytes. Replies are capped at `AGLC_MAX_OUTPUT_TOKENS` (default 16000), so a model stuck
repeating itself stops. A whole document gets `AGLC_DOCUMENT_DEADLINE` (default 300s) of model time;
footnotes not read by then are left as written and marked, rather than keeping the student waiting.

You can also name a second model to ask when the first gives up:

```bash
AGLC_LLM_FALLBACK=openrouter:<model id>   # any provider:model; only used on failure
```

On OpenRouter, some upstream hosts are skipped altogether: `AGLC_OPENROUTER_IGNORE` is a
comma-separated list of OpenRouter provider names, by default `DigitalOcean,Sail Research` (in
testing with DeepSeek V4.1 Flash, the first sent fast empty replies and the second answered a batch of
15 footnotes with one footnote and no citations). Set it empty to use every host. If skipping them
leaves no host for the model, they are allowed again rather than failing. A host that answers less than
half a batch during a run is avoided for the rest of that run, as is one that sends an empty reply.

A footnote left unchanged because extraction failed (rather than deliberately left for
review) has `extraction_failed` set (`"provider_error"` or `"not_returned"`) in the result
and in the web API's footnote objects.

### Nothing dropped, nothing invented

The AI model's output is checked deterministically (no second AI involved, see
`aglc/validate.py`):

1. **Coverage:** every meaningful word and number in the original footnote must be captured
   somewhere in the extraction. If anything is missing, the model is asked once more with
   the exact gaps named; if it still can't account for them, **that footnote is left exactly
   as written** and listed in the warnings for you to fix by hand.
2. **Grounding:** every number the model returns (year, volume, page, edition...) must
   appear in the original; invented values are removed and show as `[MISSING: ...]`.
3. **Rendering:** every field of a source must appear in its formatted citation; anything
   the formatter omits is reported as a warning.

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
aglc fix essay.docx --no-body-fixes          # Leave the body text alone
aglc fix essay.docx --report changes.json    # Save JSON report
```

**Output:**
- Processed `.docx` with tracked changes and bibliography
- Console summary: number of footnotes changed, before/after list, body text fixes, warnings
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

Hosting it publicly with payments on: see [DEPLOY.md](DEPLOY.md).

### HTTP API

#### `GET /`
Serves the web UI: the landing page and the tool are one page (`web/index.html`).

#### `GET /privacy`, `/terms`, `/refunds`, `/about`
Static pages (`web/pages/`), wrapped in `web/page.html`. Unknown facts are marked `[TODO: …]`.
The brand name is one constant, `BRAND` in `aglc/site.py`, filled into every page.

#### `GET /api/sample`
The demo essay (`examples/test_essay.docx`), used by "Try a sample essay".

#### `GET /status`
`{"status": "ok", "version": "0.1.0", "payments": false}` for uptime checks.

#### `GET /api/providers`
```json
{"providers": ["anthropic", "fake", "gemini", "openai", "openai-compatible", "openrouter"], "default": "openrouter:@preset/aglc"}
```

#### `POST /api/process`
Multipart form submission (e.g., from the web UI or `curl`).

**Parameters:**
- `file` (required): `.docx` document
- `model` (optional): `"provider:model"` (defaults to `$AGLC_LLM`)
- `track_changes` (optional, bool, default true)
- `bibliography` (optional, bool, default true)
- `fix_body` (optional, bool, default true): fix footnote numbers and headings in the body text

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
  ],
  "body_fixes": [
    {"footnote": 1, "message": "footnote number moved after the ‘.’ (AGLC4 r 1.1.2: footnote numbers go after punctuation)"}
  ]
}
```

#### `GET /api/download/{session_id}`
Download the processed `.docx` file from a session.

### Web UI

1. **Upload**: drop a `.docx` (10 MB max) on the drop zone, or click it (or press Enter); "Try a sample essay" uses the demo essay
2. **Process**: "Check my footnotes" shows named stages while the AI model reads the footnotes
3. **Review**: each footnote's original next to the AGLC4 result, marked Amended, Check or Unchanged; "Show changes" turns on the redline, "Next Check" jumps to the next footnote to look at
4. **Download**: the `.docx` with every edit as a Word tracked change (with payments on, after unlocking)

The design system is in `DESIGN.md`. The UI works on phones; light/dark mode follows the system.
Analytics (Plausible, cookieless) are off unless `AGLC_PLAUSIBLE_DOMAIN` is set.

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

Rule chips on the results page (eg "r 3.1.2") link to the official AGLC4 PDF, opened at the
rule's page. The pages come from the PDF's bookmarks, in `aglc/data/aglc4_pages.json`; if the
official PDF changes, rebuild the table from the new copy:

```bash
uv run --no-project --with pypdf --with cryptography python scripts/build_aglc4_pages.py reference/AGLC4.pdf
```

## References

- [Australian Guide to Legal Citation (4th ed)](https://law.unimelb.edu.au/research/australian-guide-to-legal-citation)
- Project architecture: see `PLAN.md` for detailed design decisions.

## License

MIT
