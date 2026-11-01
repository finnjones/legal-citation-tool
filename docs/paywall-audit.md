# Paywall audit

Can the free preview be used instead of paying? Every path by which a corrected footnote,
the bibliography or the .docx could reach a page that hasn't paid, checked with payments on
(`AGLC_PAYMENTS` set). With payments off there is no paywall and everything is returned, as
before.

**The rule.** Before payment the page receives: the original text of every footnote, each
footnote's status (Amended, Check, Unchanged), every warning, the number of corrections
found, and the corrected text of the preview footnotes only. Nothing else from the result:
no other corrected text or explanation of it, no bibliography entries (a count only), no
body-text fixes that were made (a count only), no .docx.

**Preview size.** `billing.preview_size`: the first `min(3, max(1, ceil(0.10 x changed)))`
changed footnotes (`PREVIEW_FULL`, `PREVIEW_SHARE`, `PREVIEW_MIN`). Always the first ones in
document order, so uploading the same essay again shows the same ones. Uploading it again
from another browser and address, or with the shown footnotes deleted to see the next ones,
is stopped by the seen-essay check (`aglc/fingerprint.py`): the upload's footnotes are
mostly contained in an earlier free preview, so it gets that preview again, with no model
run (`tests/test_seen.py`, including that exact attack).

Tests: `tests/test_paywall.py`, plus the preview tests in `tests/test_billing.py`.

| Path | Locked (not paid for) | Unlocked | Finding |
|---|---|---|---|
| `POST /api/process` (synchronous) | `billing.preview` of the result | full result | ok |
| `POST /api/process` with `progress=true` (202) | `{id, status}` only; the result comes through `/api/progress` | same | ok |
| `GET /api/progress/{id}` while running | counts, stage, notes (no text), and for a few footnotes their **original** text and the citations read in them (`found`: the citation *as written*, a slice of the original) | same | ok: no formatted text is ever put in the job (`aglc/progress.py`); checked after every update of a real run |
| `GET /api/progress/{id}` when done | `result` = the preview | `result` = full | ok |
| `GET /api/results/{id}` | preview | full | ok |
| `GET /api/entitlement/{id}` | status only | status only | ok |
| `GET /api/download/{id}` (.docx) | 402 | file | ok |
| `POST /api/rerun/{id}` | preview after the re-read | full | ok |
| `POST /api/report/{id}` | `{"ok": true}`; the report is built from the saved result and kept server-side | same | ok |
| `GET /api/pack/{order}`, `GET /api/pack/latest` | a pack's status; its code only to the browser that bought it (cookie on the order), until that page confirms it has it | same | **leak, fixed** in review: the code went to whoever asked first, and the full order id was in the app log. The return URL carries the order id again (so the page asks about the pack that was paid), but it collects nothing without the buyer's cookie and the page removes it from the address before analytics runs |
| `POST /api/checkout` | `{checkout_url, order_id}` or `{unlocked: true}` | same | ok |
| `GET /api/sample` | the sample essay's *input* .docx | same | ok: no output |
| Bibliography | `bibliography: []`, `bibliography_entries` (count) | full | ok |
| Warnings | all, as written by the pipeline | all | ok: they describe a problem ("has no pinpoint", "Legislation year: ... in force is from 2001, not 2002", "Case name mismatch: ...") and never carry the formatted citation; the test checks no locked footnote's corrected text appears anywhere in the response |
| Per-footnote "Found" lines (`case_check.found`) | only on footnotes whose result is shown; `found_locked` counts the rest | all | **leak, fixed**: every found case's court title and medium neutral citation were sent for every footnote, eg footnote 8's `Wik Peoples v Queensland [1996] HCA 40`, and the title often *is* the corrected case name (`Mabo v Queensland [No 2]`) |
| "Not checked" lines (`case_check.unchecked`) | only on shown footnotes; `unchecked_locked` counts the rest | all | **leak, fixed**: the name is the model's normalised reading of the case name, not the student's text |
| Case summary banner | `total`, `checked`, `flagged` | same | ok: counts only |
| Body-text fixes (`body_fixes`) | the checks left for the student (`applied: false`, like warnings); fixes that were made are counted (`body_fixes_locked`) | all | **leak, fixed**: the fixes made were sent in full, eg "'s 5-7' changed to 'ss 5–7'", which are corrections in the paid .docx |
| Footnote `changes` (why each change was made) | only on shown footnotes; a locked footnote has `number`, `changed`, `locked`, `original`, `original_html` only | all | ok |
| Preview size | 1 to 3 changed footnotes, by document size | all | **fixed**: it was always 3, which fully corrected a short essay (3 of 3, or 3 of 4) for free |
| A seen essay (an earlier free preview's footnotes) | to the browser that made the earlier preview: that preview again, recomputed by `billing.preview` under a new session id; to any other browser: a 409 built from the new upload alone (its own name, tier and price) | after payment, a fresh run of the new upload | **leak, fixed** in review: any browser matching 5 distinctive footnotes used to get the earlier essay's whole preview (every footnote as written, warnings, body checks, the corrections shown); now only the same `aglc_anon` cookie does, and seen uploads count against the free limits |
| `POST /api/run/{id}` | 402 | the fresh run's full result | ok |
| `POST /api/process` with `rescan_token` | a token that doesn't fit (different essay, expired, used up, too long for an essay tier) gets the normal preview and a `rescan_note`, never a full result | a revision of the paid document: full result, one re-scan used | ok: the token is checked against the entitlement's fingerprint before anything is unlocked |
| `POST /api/rescan-link/{id}` | 402 | a new token (hash stored) | ok |
| The page (`web/index.html`) | renders what it is sent; a locked footnote shows "Result hidden until you unlock" because it has no result, not because one is hidden with CSS | full | ok |

Not in scope: someone who pays can share their own results link; that is a paid document,
and the link stops working when the document is deleted after `AGLC_RETENTION_HOURS`.
