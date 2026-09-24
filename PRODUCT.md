# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Australian law students fixing the footnotes in an essay or assignment before they submit it, often close to a deadline. They know AGLC4 exists and roughly how it works, but not every rule (Ibid, (n x) references, short titles, signals).

## Product Purpose
Takes a Word (.docx) essay, reads every footnote, and rewrites each citation to the *Australian Guide to Legal Citation* (4th ed). It adds Ibid and (n x) references, short titles and an optional bibliography, then returns the .docx with the edits shown as Word tracked changes. Success means the student downloads a corrected document fast and trusts every change, because each one was shown to them. Fast download and a thorough review matter equally.

## Positioning
An AI model only extracts structured data from the footnotes. All AGLC formatting is done by deterministic, tested code, and the output is checked for coverage (nothing dropped) and grounding (no invented numbers). A footnote the tool can't fully account for is left exactly as written and flagged; the tool never guesses.

## Operating Context
- Runs locally with `aglc serve` (FastAPI) on a single page, `web/index.html`. The same pipeline is also available as a CLI and an HTTP API.
- Flow: upload a .docx (10 MB max), choose the model spec (for example `openrouter:deepseek/deepseek-v4-flash`), toggle track changes and bibliography, then process. Processing can take a minute. The student reviews the footnotes before and after, reads the warnings and bibliography, then downloads `<name>.aglc.docx`.
- The results include each footnote's number, its original and formatted HTML (italics as `<em>`) and a `changed` flag, plus the bibliography sections (heading and entries) and any warnings (footnote number and message).

## Capabilities and Constraints
- Italics carry meaning in citations (case names, titles) and must always render faithfully.
- `[MISSING: ...]` markers can appear in formatted output where a value was not grounded.
- There are no accounts and no persistence beyond a session id for the download.

## Evidence on Hand
- `examples/test_essay.docx`: a short essay with 24 deliberately messy footnotes, useful for demos.
- There are no testimonials, users or benchmarks. Do not fabricate any.

## Product Principles
1. Every change is visible and reviewable before download.
2. Flag problems; never hide them or guess.
3. The fast path (upload, process, download) is never blocked by the review path.
4. The citation text is the content; the interface exists to serve it.
