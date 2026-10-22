# AGLC4 Citation Tool: Plan

Takes a Word document, finds the citations in its footnotes, and rewrites them to the
*Australian Guide to Legal Citation* (4th ed), including `Ibid`, `(n x)` subsequent
references, short titles, signals and a generated bibliography.

## Principles

1. **An LLM extracts; code formats.** The model only turns messy text into structured data.
   Every character of output is produced by deterministic, tested formatters.
2. **Model-agnostic.** No module except `aglc/llm/providers/*` imports a vendor SDK.
3. **Never invent.** Missing data is rendered as `[MISSING: field]` and reported.
4. **The user stays in control.** Changes are written as Word tracked changes, plus a report.

## Pipeline

```
.docx ─► docx_io.read_footnotes ─► extract.Extractor (LLM) ─► normalise ─► document.render_document ─► docx_io.write_document
          Footnote(original)        Footnote(segments)        Citation      ProcessResult               tracked-change .docx
```

`aglc/pipeline.py` is the only module that wires stages together.

## Pluggable AI models

```
aglc/llm/base.py          LLMProvider (abstract): generate_json(system, user, output_model) -> validated pydantic model
                          registry + get_provider("provider:model") / $AGLC_LLM
aglc/llm/providers/
    anthropic_provider.py anthropic:claude-opus-5   
    openai_provider.py    openai:<model>            (response_format json_schema)
                          openai-compatible:<model> (any OpenAI-compatible base_url: Ollama, LM Studio, vLLM, OpenRouter, Groq)
    gemini_provider.py    gemini:<model>            (response_json_schema)
    fake.py               fake:<name>               (canned responses for tests; no network)
```

- A provider implements a single method, `_complete_json(system, user, schema, schema_name) -> str`.
  Validation, retrying with the validation error fed back, and code-fence stripping all live
  in the base class, so each provider is about 40 lines.
- To add a vendor, write a subclass decorated with `@register_provider("name")`, then import it in
  `providers/__init__.py`.
- Provider selection, in order: the CLI's `--model`, then the API's `model` field, then `$AGLC_LLM`,
  then the default `openrouter:@preset/aglc`.
- Vendor SDKs are optional extras (`pip install aglc[openai]`) and are imported lazily.

## Paid hosting (optional)

Off unless `AGLC_PAYMENTS` is set, so local use is unchanged. With it on, `/api/process`
returns a redacted preview (`locked: true`: every stamp, all warnings, the first 3 changed
footnotes in full) and keeps the full result server-side; paying A$4 per document unlocks it.

```
aglc/payments/base.py     PaymentProvider: create_checkout, parse_webhook (verifies the signature),
                          retrieve, refund; registry + get_payment_provider() / $AGLC_PAYMENTS
aglc/payments/providers/
    square_provider.py    square   (Checkout API payment links; HMAC-SHA256 over URL + raw body)
    fake.py               fake     (offline, HMAC-signed events; a stand-in checkout page)
aglc/store.py             SQLite in $AGLC_DATA_DIR (WAL, user_version migrations):
                          documents, orders, webhook_events
aglc/billing.py           /api/config, /api/checkout, /api/webhooks/{provider},
                          /api/entitlement/{id}, /api/results/{id}; free-use limits
```

- Prices live only in `billing.PRODUCTS`. In v1 the processing session id is the entitlement.
- Webhooks are verified, deduplicated by event id and applied in one transaction; a late
  webhook is reconciled by `retrieve()` when the page polls `/api/entitlement`.
- If a paid document's files are missing, or a document is paid for twice, it is refunded.
- Free processing is limited before any LLM call: per browser and per salted, daily-rotated
  IP hash, a global daily cap, a footnote cap and a concurrency cap.
- Nobody pays for footnotes the model failed to read (`pipeline.failed_footnotes`). They are
  re-extracted once before the preview, reusing the saved `Extraction` for the rest. If more
  than `AGLC_MAX_FAILED_SHARE` (or a whole batch) still failed, the document isn't `payable`
  and checkout returns 409. `POST /api/rerun/{id}` re-reads them free (2 per document, paid or not).

## AGLC4 coverage

| Phase | Content |
|---|---|
| MVP (built) | Ch 1 general rules (ibid, n x, short titles, signals, pinpoints, bibliography); Ch 2 cases; Ch 3 legislation |
| MVP (built) | Journal articles, books, chapters, reports, newspapers, websites (Ch 5–7); treaties (Ch 8) |
| Later | Other international materials (Ch 9–14), foreign domestic (Ch 15–26), body-text citations |

## Testing

- Unit tests per formatter, using AGLC4's own examples as golden cases (`tests/aglc4_examples/`,
  filled from the PDF in `reference/`).
- End-to-end tests on generated `.docx` fixtures using the `fake` LLM provider, with no network.

## Interfaces

- CLI: `aglc fix essay.docx -o essay.aglc.docx --model openai:gpt-5`
- HTTP API: FastAPI, `POST /api/process` (multipart .docx) returning the processed .docx plus a JSON report
- Web UI: a single static page served by the API
- Later: a Word add-in (Office.js) calling the same API
