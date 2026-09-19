# AGLC4 golden examples

Golden test fixtures drawn from the *Australian Guide to Legal Citation* (4th ed)'s own
worked examples (`reference/aglc4.txt`). Loaded and run by `tests/test_aglc4_golden.py`.

## Format

Every `*.json` file in this directory is a list of entries:

```json
{
  "id": "2.2.1-a",
  "rule": "2.2.1",
  "page": 49,
  "citation": { "...": "a JSON object accepted by aglc.models.Citation.model_validate" },
  "expected_full": "*R v Lester* (2008) 190 A Crim R 468"
}
```

- `id`: unique within the file, conventionally `<rule>-<letter>` (or `<rule>-example` for a
  worked "Example" box rather than a numbered footnote example).
- `rule`: the AGLC4 rule number the example illustrates (for failure messages).
- `page`: the printed page number of the *Guide* (not the PDF page) the example appears on.
- `citation`: parsed with `Citation.model_validate`, exactly as the extractor would produce it.
- `expected_full`: the example **exactly as the guide prints it** (same characters -- en dashes
  `–`, curly quotes `‘’`, square brackets, etc), with the following removed, to match
  what `Formatter.full()` is documented to produce (see `aglc/formatters/base.py`):
  - the footnote number:  `56 *R v Lester* ...` -> `*R v Lester* ...`
  - any introductory signal: `See, eg, *McGinty* ...` -> `*McGinty* ...`
  - the short-title definition: `... 599 (‘*McGinty*’).` -> `... 599`
  - the closing full stop.

  The `citation` may still set `signal` and/or `short_title` (as the guide's example does) --
  `full()` is documented to ignore both, so this doubles as a regression test that it does.

The test file (`tests/test_aglc4_golden.py`) asserts:

```python
formatter_for(citation).full(citation).to_markup() == expected_full
```

for every entry in every `*.json` file here, parametrised by `<file>:<id>`. On failure the
assertion message names the rule and guide page so you can go back to the *Guide* text.

## Adding examples

1. Find a worked example in `reference/aglc4.txt` (chapter 1-3 coverage lives in `cases.json`
   and `legislation.json`; other source types can add their own `*.json` file following the
   same schema -- the test loader picks up every file in this directory automatically).
2. Build the `citation` object by hand from `aglc/models.py`'s `CaseSource` / `LegislationSource`
   (or another `Source` subtype) plus `pinpoints` / `pinpoint_judges` / `short_title` / `signal`
   as needed.
3. Validate it parses: `Citation.model_validate(citation)`.
4. Copy `expected_full` verbatim from the guide, applying the stripping rules above. Watch for
   en dashes (`–`, not a hyphen `-`) and curly quotes (`‘ ’`, not straight `'`).
5. Run `uv run pytest tests/test_aglc4_golden.py -k <id>` to check it.

## Coverage

`cases.json` (68 examples, ch 2 "Cases", rr 2.1.1-2.4.3): party-name rules (corporations,
the Crown, the Commonwealth/States, ministers, `A-G`/`DPP`, `Re`, `Ex parte`, `ex rel`, `v`,
admiralty, `[No 2]`/`[Nos 4 and 5]`), reported decisions with both round-year (volume-numbered)
and square-year (year-numbered) report series, with and without an explicit volume number,
medium-neutral (unreported) citations, unreported decisions without a medium-neutral citation,
pinpoints to pages, paragraphs, and combined page+paragraph, page/paragraph ranges, pinpoints
that repeat the starting page, unique (non-numeric) starting-page references, and a wide range
of `pinpoint_judges` forms (single/multiple judges, "agreeing at", "for the Court"/"for X and Y").

`legislation.json` (40 examples, ch 3 "Legislative Materials", rr 3.1.1-3.6): Acts, an ordinance,
`(No X)` Acts, Bills (including a `(No 2)` Bill), delegated legislation (regulations and rules),
the Commonwealth Constitution and state Constitution Acts, pinpoints to `s`/`ss`/`pt`/`div`/`sch`/
`cl`/`reg`/`r` (singular and plural, consecutive and non-consecutive ranges, decimal/hyphenated
section numbers), an `item` pinpoint, `(definition of '...')` pinpoints, and short titles defined
for a portion of an Act (`sch 1 ('Criminal Code')`).

## Skipped categories

Not every worked example in ch 2-3 can be represented by the current model
(`aglc/models.py`); these are left out, grouped by why:

**Not modelled at all (no `Source`/field for the shape of the citation):**
- Case history / subsequent history (`affd`, `revd`) -- r 2.5, combines two citations.
- Parallel citations -- r 2.2.7 (the rule itself says never to use them; its "example" is a
  `[Not: ...]` counter-example, not a citation to encode).
- Proceedings not yet judged (`commenced <date>`) -- r 2.3.3 -- and court orders
  (`Order of X in Case (...)`) -- r 2.3.4.
- Quasi-judicial bodies (tribunals, arbitration) -- rr 2.6.1-2.6.2.
- Transcripts of proceedings (`Transcript of Proceedings, ...`) -- r 2.7.
- Submissions in cases -- r 2.8.
- Identifying the court in a reported citation (`... 346 (Court of Appeal)`) -- r 2.2.6 -- there
  is no field for a trailing court-identification parenthetical on a reported case (only
  `court_name` on the *unreported* shape).
- "Identifying judicial officers" examples that are plain running text rather than a footnote
  citation -- r 2.4.5.
- Statements made during argument (`(during argument)`) -- r 2.4.4 -- needs a second, independent
  parenthetical alongside `pinpoint_judges`, which the model can only render as one.
- Cubillo-style single footnotes citing several distinct cases (with different short titles)
  together -- r 2.1.13 example 35 -- and parallel multi-jurisdiction Act/Bill lists in one
  footnote -- r 3.3.
- Explanatory memoranda/statements/notes -- r 3.7.
- Legislative history (`as amended by`, `as repealed by`, ...) -- r 3.8, combines two citations.
- Quasi-legislative materials: gazettes, instrumentality/officer orders and rulings (ASIC class
  orders, taxation rulings), legislation delegated to non-government entities (ASX Listing
  Rules etc), court practice directions/notes -- r 3.9.
- `ord`/`ords` (delegated-legislation "Order") pinpoints -- r 3.4 example 41 -- `PinpointKind`
  has no `order` kind (only `regulation`/`rule`/etc).
- `sub-div` pinpoints -- r 3.1.5 example 20 -- `PinpointKind` has `division` but no
  sub-division kind.

**Omits data the model requires:**
- Examples relying on r 2.1.15 (omitting the case name from a footnote because the name already
  appears in the surrounding sentence) -- `CaseSource.name` is required. Where the case name was
  recoverable from the guide's surrounding text (e.g. the `Tasmanian Dam Case` example, r 2.1.14),
  the full name was substituted in so the citation's *substance* could still be tested; footnotes
  that only ever give `(1983) 158 CLR 1.` with no name anywhere nearby were skipped outright.

**Excluded pinpoint shapes** (present in the guide but not exercised here because they either
duplicate coverage already present elsewhere or combine multiple distinct pinpoint/judge groups
in one citation, e.g. r 2.1.13 example 91's three separately-attributed page pinpoints, or
r 2.4.4 example 102's two `(during argument)` groups) -- these would need `pinpoint_judges` to
support more than one parenthetical group, which it does not.
