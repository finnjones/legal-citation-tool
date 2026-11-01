# Aforecite vs Obiter

*Hands-on comparison, 1 November 2026. Obiter v1.17.10 (github.com/karwalski/obiter, last commit 8 October 2026) against this repository on branch `claude/admiring-sagan-kpusgj`.*

## Short answer

**For the job Aforecite sells (fixing the footnotes in an essay that is already written), Aforecite is clearly better today.** Obiter repairs **0 of 24** footnotes in Aforecite's messy test essay; that figure comes from Obiter's own developer, who ran Obiter's code on it. It writes no tracked changes, and its AI features need the student's own API key.

**For writing an essay from scratch inside Word, Obiter is better, and it is free.** It inserts citations as you write, with lookups from AustLII and Jade. It keeps a citation library and refreshes Ibid and "(n x)" as footnotes move. It covers far more of AGLC4 (all 26 chapters), plus the OSCOLA and New Zealand style guides and court-filing modes.

So the two tools mostly do different jobs. The risk is that **Obiter's developer has read this repository and plans to close the gap** (see the last section).

## How this was tested

1. **Obiter's source code was read**, focusing on Scan & Repair: `src/word/scanRepair.ts` and `src/api/citationParser.ts`. Scan & Repair is the feature that brings plain-text footnotes in an existing essay under Obiter's management.
2. **Obiter's adoption rules were re-implemented in a short Python script** and run on two sets of 24 footnotes. Installing and running Obiter's own code in this session was refused by the session's safety policy. The script is in the session scratchpad, not the repository.
   - **Messy set:** `examples/test_essay.docx` as written (dotted abbreviations, `supra`, `op cit`, signals, prose, several citations in one footnote).
   - **Near-correct set:** the same 24 sources, written almost correctly in AGLC4. This is the kindest case for Obiter.
3. **Obiter's own review of this repository was read**, together with the follow-up tasks it opened. The review is `docs/research/legal-citation-tool-review.md` in Obiter's repo, dated 27 September 2026, and it was checked against this repo's commit `c067149`. Its developer ran Obiter's real code on our test essay.

What was **not** done: no live run of Aforecite. The session has no OpenRouter key, so there is no side-by-side output, footnote by footnote. Aforecite's 1,412 automated tests pass. Its side of the comparison rests on what the pipeline is built to do, those tests, and Obiter's review.

## Result: repairing an existing essay

Obiter's Scan & Repair only takes over a plain-text footnote if a fixed pattern-matcher recognises the **whole** note as a single bare case, Act or Hansard reference. It never uses AI here; its comments say "never the LLM — Scan & Repair is offline". Every other footnote is kept **verbatim**, and the engine "renders the text exactly as it read". A verbatim footnote gets no reformatting, no Ibid and no "(n x)".

| Footnote set | Obiter: footnotes it could repair | Kept verbatim |
|---|---|---|
| Messy test essay (24) | **0** (Obiter's own run); at most 1 by the re-implemented rules | 24 |
| Same sources, near-correct AGLC4 (24) | **at most 2** | 22 |

Which footnotes miss out, and why:

- **Starts with a signal** ("See", "cf", "For…"). Rejected, even when the citation itself is perfect.
- **Secondary sources:** journal articles, books, chapters, reports, newspapers and web pages. Never repaired; Scan & Repair has no pattern for them.
- **Ibid and "(n x)" footnotes.** Never repaired.
- **More than one citation in a footnote,** or a citation with explanatory text. Never repaired.
- **An Act with a lettered section,** eg `Civil Liability Act 2002 (NSW) s 5B`, even when written perfectly. Rejected because of a bug: the pinpoint pattern accepts digits only. Obiter's developer logged this as task LCT-002, not yet done.
- **A medium neutral citation with a pinpoint,** eg `[2011] HCA 11, [20]`. Rejected because of a bug, also LCT-002.
- **Dotted abbreviations** such as `C.L.R.` and `(N.S.W.)`. Not recognised at all.

In a typical law essay most footnotes fall into one of these groups. So for "I've written my essay, fix my footnotes", Obiter today mostly leaves the student to fix them by hand. Its other tools for this are slower:

- **Parse with AI** works one citation at a time: paste a citation, check the form, insert it. It needs the student's own OpenAI, Anthropic or other API key.
- **Validate** flags problems; it doesn't rewrite them.

Aforecite reads every footnote with an AI model, then formats with tested code. That covers signals, prose, several citations in one footnote, secondary sources, treaties, Ibid, "(n x)", `supra` and `op cit`. It writes the result back as **Word tracked changes**.

## Side by side

| | Aforecite | Obiter |
|---|---|---|
| Price | A$4 per document today (free preview of 3 fixes) | Free (GPLv3, open source) |
| Main job | Fix an essay that's already written, in one pass | Cite as you write, inside Word |
| Repairs messy existing footnotes | Yes: every footnote; unaccounted text is left and flagged | 0 of 24 messy; at most 2 of 24 near-correct |
| Ibid / (n x) / short titles | Generated for the whole document | Yes, but only for citations Obiter manages (inserted or repaired) |
| Shows changes as Word tracked changes | Yes (word-level) | No: "`changeTrackingMode` appears nowhere" (Obiter's review) |
| Checks the AI didn't drop or invent anything | Yes: coverage and number-grounding checks | No grounding check (confirmed in Obiter's review; task LCT-001 added one to Parse with AI) |
| Body-text fixes (footnote number after punctuation, italics) | Yes | Some (Latin italics, case names in the body) |
| Flags cases that may not exist | Yes (offline check) | No equivalent found |
| Source-type coverage | AGLC4 Ch 1–8 core sources, plus speeches, media releases, UN documents, US cases | All 26 AGLC4 chapters, OSCOLA 4/5, NZLSG 3, court modes |
| Citation lookup (AustLII, Jade, legislation register) | No | Yes |
| Citation library, EndNote/Zotero/BibTeX import | No | Yes |
| Bibliography | Yes | Yes |
| Where it runs | Any browser; no install | Word 2024 or Microsoft 365 add-in (desktop, web, iPad) |
| AI key needed by the student | No | Yes, for every AI feature |
| Student's essay leaves their device | Yes (uploaded; deleted after 24 h) | No for Scan & Repair; yes, to the student's own AI provider, for AI features |
| Maturity | ~6 weeks old, one developer | v1.17, ~140k lines of TypeScript, 224 test files |

## What this means for Aforecite

1. **Position against Obiter by job, not by "AGLC formatting".** Obiter wins for a student who starts in Word and cites as they go. Aforecite wins for the much more common case: an essay written over weeks, in mixed formats, due tomorrow. The messages to lead with are "upload, and every footnote is fixed and shown as tracked changes" and "no install, no API key".
2. **It supports charging.** A student who already wrote the essay can either retype 50–100 footnotes in Obiter or pay A$5. That trade is the case for the price.
3. **The gap is being closed, partly using this repository.** On 27 September 2026 Obiter's developer reviewed this repo and opened a project called "Lessons from legal-citation-tool" (14 tasks). Relevant open tasks:
   - **LCT-008: opt-in AI-assisted repair of verbatim notes.** This is Aforecite's core feature.
   - **LCT-007: tracked changes during Scan & Repair.**
   - **LCT-002: fix the s 5B, MNC-pinpoint and `[1932] AC` parser bugs.**
   - **LCT-006: build their own messy-essay benchmark.**

   The review is careful about copying. It notes this repo has no licence, says the test essay must not be committed, and restates ideas "in Obiter's own words". But it openly borrows the design: coverage and grounding checks, re-asking the model, regression fixtures from real runs, and the anti-invention prompt rules.
4. **Obiter's likely ceiling.** Even if LCT-008 ships, Obiter's AI needs the student to get and pay for their own API key. That is real friction for most law students, so Aforecite stays easier: no key, no install, any device. The parts that are hard to copy are speed to market, the tracked-change output, and trust, so those deserve the investment.
5. **Consider making the repository private.** It is public, which is how Obiter (and anyone else) could study it in detail. With no licence the code can't legally be reused, but the ideas can. Making it private costs nothing for a hosted product.

## To strengthen this comparison

- **A live head-to-head:** run both tools on 2–3 real student essays, not our test essay, and count footnotes correct, left alone and wrong. Running Aforecite live needs an OpenRouter key in the session. Running Obiter needs Word with the add-in installed, or permission to run its code here.
- **Check the claims about Obiter's features** against the installed add-in, since this comparison is from source code and docs as at 8 October 2026.
