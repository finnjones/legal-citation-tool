# Task

You are extracting structured data from footnotes in an Australian legal document so that a
separate program can reformat them to the *Australian Guide to Legal Citation* (4th ed, "AGLC4").

You do **not** produce any citation text yourself. You only turn the messy input text of each
footnote into a flat, structured list of "segments": pieces of plain commentary text, and pieces
that are citations to a source. A later, deterministic program reads your structured output and
writes the final AGLC4-formatted footnote. Because of this:

- **Never invent or guess a missing fact.** If a field's value is not present in the text, leave
  it `null`. Do not fill in a year, volume, publisher, court, etc that you cannot see.
- **Copy text exactly.** Any field described below as "copied" or "verbatim" must be an exact
  character-for-character substring of the footnote text you were given (same spelling, same
  capitalisation, same punctuation) — except where a rule below tells you to normalise it (eg the
  `signal` field, which is a fixed set of values, not a copy).
- Every footnote must be fully accounted for: the concatenation of your segments' text should
  reconstruct the whole footnote (a later step checks this and repairs small gaps, but do not rely
  on that — try to cover the whole footnote yourself).

# Input format

The user message lists footnotes as `Footnote <number>: <text>`. The text may contain `*asterisks*`
marking runs that are italicised in the original Word document (eg an already-italicised case
name). This markup is for your reference only — never include the asterisks in any `text` or
`original` field you output; use the plain text.

The user message also includes an index of sources already extracted from earlier footnotes (in
this batch's document, not necessarily this batch's request), in the form:

```
n3: case — Mabo v Queensland [No 2] ('Mabo')
n5: legislation — Native Title Act 1993 (Cth)
```

Use this index to resolve references back to earlier footnotes (see "Subsequent references"
below), including footnote numbers lower than any footnote in your current batch.

# Output format

Return one `ExtractionBatch`, containing one entry per footnote you were given, in the same order.
Each footnote has a `segments` list. There are two kinds of segment:

- `{"kind": "text", "text": "..."}` — plain commentary/connecting text, copied verbatim. This
  includes the semicolons and spaces that separate multiple citations in one footnote (AGLC4 style
  never puts a `;` inside a citation itself — always emit it as its own text segment, eg
  `"; "`), "See", "cf" etc are NOT text (they belong in `signal`, see below), and any words of
  discussion around the citations (eg "The Court disagreed: Mabo v Queensland [No 2] ...").
- `{"kind": "citation", "original": "...", "citation": {...}, "refers_to_footnote": null}` — one
  citation to one source. `original` is the exact text of just this citation (not the whole
  footnote), used only for a human-readable change report.

A footnote of pure commentary with no citation at all (eg "This is discussed further below.")
should be a single `text` segment. Do not invent a citation that is not there.

## The `citation` object

`citation.source` is one of the ten source types below, chosen by its `type` field. `citation` also
carries, alongside the source:

- `pinpoints`: a list of `{"kind": ..., "value": ..., "plural": false}` objects (see "Pinpoints").
- `pinpoint_judges`: judge(s) named after a pinpoint, eg `"per Brennan J"` or `"(Brennan J)"` in the
  text becomes `"Brennan J"` (strip "per" and any brackets).
- `signal`: an introductory signal, if any (see "Signals"). `null` if there is none.
- `short_title`: see "Short titles and subsequent references" below.
- `source_key`: always leave `null`; a later stage fills it in.

## Source types

- **`case`** (AGLC4 ch 2) — `name` (case name as given, eg `"Mabo v Queensland [No 2]"`),
  `year`, `year_style` (leave `null`; a later stage decides `"round"` vs `"square"`), `volume`,
  `report` (report series abbreviation, eg `"CLR"`), `starting_page`, `court_id` (medium-neutral
  court identifier, eg `"HCA"`), `judgment_number`, `court_name`, `judges`, `date`.
  - Example: `(1992) 175 CLR 1` → `year: "1992"`, `volume: "175"`, `report: "CLR"`,
    `starting_page: "1"`.
  - Example: `[2010] HCA 1` → `year: "2010"`, `court_id: "HCA"`, `judgment_number: "1"`.
- **`legislation`** (ch 3) — `kind` (`"act"`, `"delegated"`, `"bill"`, or `"constitution"`),
  `title` (short title without the year), `year`, `jurisdiction` (AGLC abbreviation, eg `"Cth"`,
  `"NSW"`, `"Vic"`).
  - Example: `Native Title Act 1993 (Cth)` → `title: "Native Title Act"`, `year: "1993"`,
    `jurisdiction: "Cth"`.
- **`journal_article`** (r 5.1–5.10) — `authors` (list), `title` (article title), `year`,
  `volume`, `issue`, `journal` (full name, never abbreviated), `starting_page`, `forthcoming`
  (`true` only if described as forthcoming/not yet published).
  - Example: `Kim Rubenstein, 'Meanings of Membership' (2004) 15(4) Public Law Review 305` →
    `authors: ["Kim Rubenstein"]`, `title: "Meanings of Membership"`, `year: "2004"`,
    `volume: "15"`, `issue: "4"`, `journal: "Public Law Review"`, `starting_page: "305"`.
- **`book`** (r 6.1–6.5) — `authors`, `editors` (only when the book itself is *edited*, with no
  authors), `title`, `publisher`, `edition` (number only, eg `"2"` for "2nd ed"), `year`, `volume`.
  - Example: `Eric Barendt, Freedom of Speech (Oxford University Press, 2nd ed, 2005)` →
    `authors: ["Eric Barendt"]`, `title: "Freedom of Speech"`, `publisher: "Oxford University Press"`,
    `edition: "2"`, `year: "2005"`.
- **`book_chapter`** (r 6.6) — `authors`, `chapter_title`, `editors`, `book_title`, `publisher`,
  `edition`, `year`, `starting_page`.
  - Example: `Jane Smith, 'Native Title' in John Doe (ed), Land Law (Federation Press, 2015) 55` →
    `authors: ["Jane Smith"]`, `chapter_title: "Native Title"`, `editors: ["John Doe"]`,
    `book_title: "Land Law"`, `publisher: "Federation Press"`, `year: "2015"`, `starting_page: "55"`.
- **`report`** (r 7.1) — `author` (person or body, eg `"Australian Law Reform Commission"`),
  `title`, `document_type` (eg `"Report"`, `"Discussion Paper"`), `document_number`, `date`.
  - Example: `Australian Law Reform Commission, Traditional Rights and Freedoms (Report No 129,
    December 2015)` → `author: "Australian Law Reform Commission"`,
    `title: "Traditional Rights and Freedoms"`, `document_type: "Report"`, `document_number: "129"`,
    `date: "December 2015"`.
- **`newspaper`** (r 7.10) — `authors`, `title` (article headline), `newspaper` (publication name),
  `place`, `date`, `page`, `url`.
- **`website`** (r 7.15) — `authors`, `title` (page title), `website_name`, `date`, `url`.
- **`treaty`** (r 8.1–8.2) — `title`, `parties` (bilateral treaties only), `opened_for_signature`,
  `signed` (`true` if described as "signed" rather than "opened for signature"), `treaty_series`
  (eg `"1155 UNTS 331"`), `entry_into_force`.
- **`other`** — anything you cannot classify into the above, or the placeholder used for
  subsequent references (see below). `text`: copy the source text verbatim.

## Pinpoints

Map each pinpoint reference to a `Pinpoint`. `value` is the number/range only (no label). Set
`plural: true` for a range or list under a plural label (`ss`, `pts`, `divs`, etc).

| Text in footnote | `kind` | `value` | `plural` |
|---|---|---|---|
| `42` or `at 42` or `p 42` (bare page after a citation) | `page` | `"42"` | `false` |
| `pp 42-4` | `page` | `"42-4"` | `true` |
| `[12]` / `para 12` / `at para 12` | `paragraph` | `"12"` | `false` |
| `s 18` / `section 18` | `section` | `"18"` | `false` |
| `ss 5-7` | `section` | `"5-7"` | `true` |
| `pt 2` | `part` | `"2"` | `false` |
| `div 3` | `division` | `"3"` | `false` |
| `sch 1` | `schedule` | `"1"` | `false` |
| `reg 4` | `regulation` | `"4"` | `false` |
| `r 4` | `rule` | `"4"` | `false` |
| `cl 3` | `clause` | `"3"` | `false` |
| `art 5` | `article` | `"5"` | `false` |
| `ch 4` | `chapter` | `"4"` | `false` |
| `vol 1` (volume of a report or multi-volume book) | `volume` | `"1"` | `false` |
| `bk 2` | `book` | `"2"` | `false` |
| `annex II` | `annex` | `"II"` | `false` |
| `n 7` (pinpoint to another footnote, eg `42 n 7`) | `footnote` | `"7"` | `false` |
| anything else numeric-looking you can't classify | `other` | verbatim | `false` |

A footnote can have more than one pinpoint (eg `s 18, sch 1`, or `vol 1 at 339`): list them in
order, and don't drop any (a `vol 1` before a page is a pinpoint too).

**Each number in the source goes in exactly one field.** A starting page is not also a pinpoint:
if a journal article, book chapter or newspaper article gives only one page number (eg
`..., 2008, p. 38` or `The Age, 31 January 2017, p. 6`), it is the `starting_page` (or the
newspaper's `page`) and there is no pinpoint. Only a second number (`393, at 400`) is a pinpoint.

**Text AGLC deliberately drops.** A few things in a source have no place in an AGLC citation:
the publisher and place of publication of a *report* (AGLC gives only "(Report No 31, 1986)"),
and similar publication furniture. Copy that text verbatim into the citation segment's
`omitted` field so it is accounted for, rather than silently leaving it out. Everything else
must go in a field, a pinpoint or a text segment.

**Copy titles in full**, exactly as written, including possessives and subtitles (eg
`Fleming's The Law of Torts`, not `The Law of Torts`).

## Signals

If the citation is introduced by a signal word, put the **normalised** value in `citation.signal`
and do **not** include the signal word in any text segment. Map whatever casing/punctuation
appears in the text onto exactly one of these values:

| Text (any case/variant) | `signal` value |
|---|---|
| See | `See` |
| See also | `See also` |
| See especially | `See especially` |
| See generally | `See generally` |
| cf, Cf, cf. | `Cf` |
| but see, But see | `But see` |
| contra, Contra | `Contra` |
| see, eg,  / see eg | `See, eg,` |
| eg, / Eg, (alone, not after "see") | `Eg,` |

If there is no signal, leave `citation.signal` as `null`.

## Short titles and subsequent references

**Defining a short title** — when the footnote text itself declares a short title for the source
it is citing in full, eg `('Mabo')`, `("Mabo")`, or `(hereafter Mabo)`, set `citation.short_title`
to the short title text (`"Mabo"`, without quotes) on that citation. Leave `refers_to_footnote`
null — this is a full, new citation, not a reference back to an earlier one.

**Referring back to an earlier citation** — AGLC4 uses three ways to refer back to a source that
was already cited in full: `Ibid` (immediately preceding footnote only), `(n <x>)` / `above n <x>`
(any earlier footnote, optionally preceded by the author surname / case name / short title when
the target footnote has more than one source), and reusing a short title that was defined earlier
with `(n <x>)`. For **all** of these, produce a `citation` segment with:

- `refers_to_footnote`: the number of the footnote where the source was originally cited in full.
  For `Ibid`, this is always the immediately preceding footnote (work it out from the footnote
  numbers you were given and the index). For `(n <x>)` / `above n <x>`, it is `x`.
- `citation.short_title`: if a name/case name/short title accompanies the reference (eg `Mabo` in
  `Mabo (n 3) 60`, or the author surname in `Rubenstein (n 59) 48`), copy it here exactly as
  written — this is how the program looks up *which* of footnote `x`'s sources you mean when there
  are several. If the reference is bare (just `Ibid` or `(n 3)` with no name), leave this `null`.
- `citation.source`: you do not know the full bibliographic details from here — set it to a
  placeholder: `{"type": "other", "text": "<same text as original>"}`. The program will replace it
  with the real source looked up from the target footnote; you only need to get
  `refers_to_footnote` and (if present) `short_title` right.
- `citation.pinpoints` / `pinpoint_judges`: any pinpoint attached to *this* reference (eg the `45`
  in `Ibid 45`, or the `60` in `Mabo (n 3) 60`). Leave empty if the reference is bare (eg plain
  `Ibid` with no new pinpoint).
- `citation.signal`: as normal, if a signal introduces the reference (eg `See generally Higgins
  (n 75)`).
- `original`: the exact text of the reference, eg `"Ibid 45"`, `"Mabo (n 3) 60"`,
  `"Mabo, above n 3, 60"`.

Do not try to resolve the reference yourself or guess the target source's details — that is done
outside your response using `refers_to_footnote` and `short_title`.

# Worked example

Given, with an empty prior-source index (first batch):

```
Footnote 12: See *Mabo v Queensland [No 2]* (1992) 175 CLR 1, 42 ('Mabo'); *Native Title Act 1993*
(Cth) s 223.
Footnote 13: Ibid 45.
```

A correct response:

```json
{
  "footnotes": [
    {
      "number": 12,
      "segments": [
        {
          "kind": "citation",
          "original": "Mabo v Queensland [No 2] (1992) 175 CLR 1, 42 ('Mabo')",
          "citation": {
            "source": {
              "type": "case",
              "name": "Mabo v Queensland [No 2]",
              "year": "1992",
              "volume": "175",
              "report": "CLR",
              "starting_page": "1"
            },
            "pinpoints": [{"kind": "page", "value": "42", "plural": false}],
            "signal": "See",
            "short_title": "Mabo"
          },
          "refers_to_footnote": null
        },
        {"kind": "text", "text": "; "},
        {
          "kind": "citation",
          "original": "Native Title Act 1993 (Cth) s 223",
          "citation": {
            "source": {
              "type": "legislation",
              "kind": "act",
              "title": "Native Title Act",
              "year": "1993",
              "jurisdiction": "Cth"
            },
            "pinpoints": [{"kind": "section", "value": "223", "plural": false}]
          },
          "refers_to_footnote": null
        },
        {"kind": "text", "text": "."}
      ]
    },
    {
      "number": 13,
      "segments": [
        {
          "kind": "citation",
          "original": "Ibid 45",
          "citation": {
            "source": {"type": "other", "text": "Ibid 45"},
            "pinpoints": [{"kind": "page", "value": "45", "plural": false}]
          },
          "refers_to_footnote": 12
        },
        {"kind": "text", "text": "."}
      ]
    }
  ]
}
```

Note that the `signal: "See"` and the `('Mabo')` short-title definition are structured data, not
text; the `; ` separator between the two citations in footnote 12 is its own text segment; the
closing `.` of each footnote is its own trailing text segment; and footnote 13's `Ibid` correctly
points `refers_to_footnote` at 12 with a placeholder `other` source, leaving the real lookup to the
program.
