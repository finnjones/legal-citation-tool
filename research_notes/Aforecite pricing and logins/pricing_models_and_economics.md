# Aforecite: Pricing Models and Unit Economics (AUD, as at 1 November 2026)

Method note: Direct page fetches of stripe.com, support.stripe.com, square.com/www.square.com and openrouter.ai were blocked by this session's network allowlist (DNS failure). All figures below come from web-search results that quote those pages, and from third-party trackers. Treat every rate as "check the live page before publishing". The arithmetic was done with a small script (scratchpad `calc.py`) using the stated assumptions.

Working assumptions used throughout (all flagged, change as needed):
- FX: 1 AUD = 0.693 USD (1 Oct 2026 rate), so 1 USD = A$1.443.
- OpenRouter 5.5% card top-up fee added to all LLM costs.
- Batch = 15 footnotes. "Typical" batch = 4,000 input + 3,000 output tokens (~200 output tokens per footnote). "Max" batch = 5,000 input + 16,000 output tokens (every batch hits the output cap: a worst case, eg reasoning-heavy or runaway output).
- Documents: 30 footnotes = 2 batches, 100 = 7 batches, 400 = 27 batches.

---

## 1. Payment fees (Stripe vs Square, Australia) and net revenue per sale

### Takeaway
After the 1 October 2026 RBA-driven changes, Stripe domestic is 1.65% + A$0.30 and Square online is a flat 2.2% with no fixed fee. For any price below about A$54.50 Square nets more, and at A$2–A$5 the gap is large (Stripe takes 16.6% of a A$2 sale, Square 2.2%). Neither has a published Australian micropayment rate. Card surcharging is now banned, so fees have to be absorbed into the price.

### Cited Findings
- Stripe cut its standard domestic online card rate in Australia from 1.7% + A$0.30 to **1.65% + A$0.30** from 1 October 2026. In-person goes to 1.65% + A$0.10. Stripe says it is passing on the RBA's interchange cuts. Only standard pricing is affected: custom-pricing accounts follow their own agreement. — [Stripe support: Updates to card pricing in Australia from October 2026](https://support.stripe.com/questions/updates-to-card-pricing-in-australia-from-october-2026); [Wise AU: Stripe fees 2026](https://wise.com/au/blog/stripe-fees); [PetBoost: Stripe cuts Australian card rates](https://petboost.com.au/business/blog/stripe-lowers-australian-card-rates-2026-vs-square/)
- Stripe international cards stay at **3.5% + A$0.30**, plus 2% where currency conversion applies. Several sources say international pricing falls to 2.8% + A$0.30 from **1 April 2027**, not October 2026. Wise's article lists 2.80% as if already current, which conflicts with the others. — [Digital Advisors: Square vs Stripe 2026](https://digitaladvisors.com.au/journal/card-payment-fees-square-vs-stripe/); [Croissant Baguette: Payment fees in Australia 2026](https://croissantbaguette.com.au/guides/payment-fees-in-australia/); [Aspire: Stripe fees Australia](https://aspireapp.com/en-au/blog/stripe-fees-australia); conflicting: [Wise](https://wise.com/au/blog/stripe-fees)
- The task brief quotes 1.65% + A$0.30, which matches the post-October domestic rate. Some secondary pages still show 1.7% with a "lower pricing from 1 Oct 2026" label. — [Aspire](https://aspireapp.com/au/blog/stripe-fees-australia)
- Stripe refunds: there's no fee for issuing most refunds, but **the original processing fee is not returned**. — [Wise AU](https://wise.com/au/blog/stripe-fees)
- Stripe disputes: **A$25 dispute fee**, plus an A$25 "dispute countered" fee from the June 2025 pricing update. The counter fee is refunded if you win; the base fee is not. — [Stripe support: June 2025 pricing updates for disputes](https://support.stripe.com/questions/june-2025-pricing-updates-for-disputes); [Chargeback Gurus](https://www.chargebackgurus.com/blog/stripe-dispute-fees)
- Square Australia online rate is a flat **2.2%**. It covers Online Checkout, Payment Links, Square Online, eCommerce API, invoices and subscription payments, with no fixed per-transaction fee and no monthly fee. — [Square AU: Our fees](https://www.square.com/au/en/payments/our-fees); [Square AU Fees and payments FAQ](https://squareup.com/help/au/en/article/6109-fees-and-payments-faqs); [Square developer: payments pricing](https://developer.squareup.com/docs/payments-pricing)
- Square says the single percentage fee covers "everything from PCI-compliance fees to interchange and chargeback fees", with no additional processing fees. That implies no separate dispute fee, which needs confirming. — [Square developer: payments pricing](https://developer.squareup.com/docs/payments-pricing) (as quoted in search results)
- Square charges the same rate for international cards online: Visa, Mastercard, eftpos, JCB and Amex, local or international, at 2.2%. This comes from a third-party summary; Square's accepted-cards help page says all cards are processed at the same standard rate. — [Square AU: Accepted cards](https://square.com/help/au/en/article/5085-accepted-cards)
- Square's fee page has a "No fees for refunds" section. **I could not confirm whether the original 2.2% is returned on refund.** — [Square AU: Our fees](https://www.square.com/au/en/payments/our-fees)
- Square online checkout links accept Apple Pay and Google Pay. — [Square AU accepted cards / help](https://squareup.com/help/au/en/article/5085-accepted-cards)
- An older third-party article quoting Square AU online at 2.9% + 30c is outdated. — [Jotform](https://www.jotform.com/blog/square-transaction-fees/)
- **Surcharge ban:** from 1 October 2026 Australian businesses can no longer add surcharges to eftpos, Visa or Mastercard payments, and Stripe disabled surcharging. Amex, UnionPay and JCB followed the same day, and PayPal on 5 October. — [Stripe support: Australia is removing card surcharges](https://support.stripe.com/questions/australia-is-removing-card-surcharges-what-stripe-users-need-to-know); [Digital Advisors](https://digitaladvisors.com.au/journal/card-payment-fees-square-vs-stripe/)

### Net revenue per sale (computed; fee rates from the sources above)

| Price | Stripe domestic (1.65% + 0.30) | Stripe international (3.5% + 0.30) | Square online (2.2%) |
|---|---|---|---|
| A$2 | A$1.667 (fee 16.6%) | A$1.630 (18.5%) | A$1.956 (2.2%) |
| A$4 | A$3.634 (9.2%) | A$3.560 (11.0%) | A$3.912 |
| A$5 | A$4.617 (7.7%) | A$4.525 (9.5%) | A$4.890 |
| A$9 | A$8.552 (5.0%) | A$8.385 (6.8%) | A$8.802 |
| A$12 | A$11.502 (4.1%) | A$11.280 (6.0%) | A$11.736 |
| A$15 | A$14.453 (3.6%) | A$14.175 (5.5%) | A$14.670 |
| A$20 | A$19.370 (3.1%) | A$19.000 (5.0%) | A$19.560 |

Crossover: 0.022P = 0.0165P + 0.30 gives **P = A$54.55**. Below that, Square is cheaper than Stripe domestic. Against Stripe international, Square is cheaper at every price.

### Inferences
- At A$4 the Stripe/Square gap is A$0.28 per sale (about 7.6% more net on Square). For a low-price product that's material, and it grows as the price falls (A$0.29 at A$2 is 15% of net).
- Stripe's fixed 30c punishes small tickets, so any model that splits payments into tiny charges (eg A$0.20 per use charged separately) is unviable on Stripe. On Square a A$0.20 charge would still net A$0.196, but no one would run checkout 20 times. In practice "A$0.20 per use" only exists as a prepaid bundle.
- One Stripe chargeback (A$25 + A$25 if contested, plus the lost sale) wipes out the net of roughly 7–14 A$4 sales. That's a strong reason to offer a fast, no-quibble self-serve refund before a student goes to their bank. Square's apparent inclusion of chargebacks in the 2.2% is an advantage if confirmed.
- With surcharging banned, there's no lever to pass fees on. Price points have to be chosen to absorb them.
- The international-card share is likely small for an AGLC tool (Australian law students), though international students using foreign-issued cards are possible.

### Gaps
- Could not fetch stripe.com/au/pricing directly. Not confirmed: whether Apple Pay/Google Pay are priced identically to cards on Stripe AU (they normally are, but no source in this session confirmed it); whether Stripe Checkout or Payment Links add any fee in AU; and whether Stripe AU's quoted fees include or exclude GST (see Stripe support "Taxes on Stripe fees for Australia-based businesses", which wasn't retrieved).
- No evidence found of a Stripe or Square **micropayment rate in Australia**. Stripe historically offered custom micropayment pricing on request in the US, but I found no AU source. Treat it as unavailable on standard pricing.
- Whether Square AU returns the processing fee on refunds is unconfirmed.

---

## 2. LLM cost per document (OpenRouter), including free previews

### Takeaway
At the most-quoted OpenRouter price for DeepSeek V4.1 Flash (US$0.15 in / US$0.60 out per million tokens), a typical 100-footnote essay costs about **A$0.03**. Even the worst case (every batch hitting the 16k output cap) is about A$0.11, and a 400-footnote document A$0.10 typical to A$0.43 worst case. LLM cost is roughly 1% of a A$4 price. Free previews are cheap individually but can matter if abuse is uncapped.

### Cited Findings
- **DeepSeek V4.1 Flash** was formally launched on 10 September 2026, and DeepSeek routes V4 Pro requests to Flash. — [TechNode](https://technode.com/2026/09/10/deepseek-formally-launches-v4-1-flash-routes-v4-pro-requests-to-flash/)
- OpenRouter has a `deepseek/deepseek-v4.1-flash` listing (also a `-20260910` snapshot and a `1017` variant). Three providers serve it: DeepSeek, NovitaAI and DeepInfra. — [OpenRouter: DeepSeek V4.1 Flash](https://openrouter.ai/deepseek/deepseek-v4.1-flash); [OpenRouter 20260910 snapshot](https://openrouter.ai/deepseek/deepseek-v4.1-flash-20260910); [LLM Reference providers](https://www.llmreference.com/model/deepseek-v4.1-flash/providers)
- **Price conflict.** Most trackers list OpenRouter V4.1 Flash at **US$0.15 / M input and US$0.60 / M output** ([pricepertoken](https://pricepertoken.com/pricing-page/model/deepseek-deepseek-v4.1-flash); [computeprices](https://computeprices.com/providers/openrouter/models/deepseek-v4-1-flash)). A search snippet of the OpenRouter page itself showed **~US$0.0134 / M input and US$0.5307 / M output**, cache read US$0.006 ([OpenRouter](https://openrouter.ai/deepseek/deepseek-v4.1-flash)). Other trackers cite US$0.030–0.035 / M input on OpenRouter ([computeprices](https://computeprices.com/providers/openrouter/models/deepseek-v4-1-flash); [modelgrep](https://modelgrep.com/models/deepseek/deepseek-v4.1-flash)). Some providers ran promotional near-zero input pricing in October 2026 ([ProPakistani: "DeepSeek V4.1 currently 1500x cheaper than usual"](https://propakistani.pk/2026/10/11/deepseek-v4-1-currently-1500x-cheaper-than-usual/)).
- DeepSeek's own API lists V4.1 Flash at **US$0.30 / US$1.20 per M (peak)** and US$0.15 / US$0.60 off-peak, with cache read around US$0.003. That's DeepSeek-direct, not OpenRouter. — [TechJack Solutions: DeepSeek pricing (updated 4 Oct 2026)](https://techjacksolutions.com/ai-tools/deepseek/deepseek-pricing/); [developersdigest](https://www.developersdigest.tech/blog/deepseek-v4-flash-free-and-cheap-access-2026)
- Earlier DeepSeek Flash listings on OpenRouter: V4 Flash 0731 at US$0.0304 / US$0.30; V4 Flash 0423 at US$0.05 / US$0.45. — [OpenRouter V4 Flash 0731](https://openrouter.ai/deepseek/deepseek-v4-flash-0731); [OpenRouter V4 Flash 0423](https://openrouter.ai/deepseek/deepseek-v4-flash)
- Alternatives on OpenRouter (third-party trackers, mid-2026 snapshots): **GPT-5 mini** US$0.25 / US$2.00; **Gemini 2.5 Flash** US$0.30 / US$2.50; **Gemini 2.5 Flash Lite** US$0.10 / US$0.40; **Gemini 3.5 Flash** US$1.50 / US$9.00; Gemini 3.5 Flash Lite about US$0.30–0.54 / US$2.50, with input reportedly up 80% in 90 days. — [computeprices GPT-5 mini](https://computeprices.com/providers/openrouter/models/gpt-5-mini); [OpenRouter blog: Gemini 2.5 Flash](https://openrouter.ai/blog/gemini-25-flash-api-pricing-quickstart-provider-comparison); [LLM Reference Gemini 2.5 Flash Lite](https://www.llmreference.com/provider/openrouter/gemini-2.5-flash-lite); [computeprices Gemini 3.5 Flash](https://computeprices.com/providers/openrouter/models/gemini-3-5-flash); [pricepertoken Gemini 3.5 Flash Lite](https://pricepertoken.com/pricing-page/model/google-gemini-3.5-flash-lite)
- OpenRouter charges a **5.5% fee on card credit purchases (US$0.80 minimum)**; crypto is 5.0%. Sources conflict on whether the fee is added on top or deducted from the balance. A US$5 top-up carries an effective 16% fee because of the minimum. — [OpenRouter: Simplifying our platform fee](https://openrouter.ai/blog/announcements/simplifying-our-platform-fee/); [apicostcalc](https://apicostcalc.com/blog/openrouter-credit-fee-is-5-5-not-5-percent.html)
- FX: AUD/USD was 0.6928 on 1 October 2026; the 2026 high was 0.7260 (13 May). — [exchange-rates.org](https://www.exchange-rates.org/exchange-rate-history/aud-usd-2026-10-01)

### LLM cost per document (computed, A$, includes the 5.5% OpenRouter fee)

| Model (US$ in/out per M) | 30 fn typical | 30 fn max | 100 fn typical | 100 fn max | 400 fn typical | 400 fn max |
|---|---|---|---|---|---|---|
| DeepSeek V4.1 Flash, OR tracker price (0.15/0.60) | 0.007 | 0.032 | **0.026** | 0.110 | 0.099 | 0.425 |
| DeepSeek V4.1 Flash at peak-direct price (0.30/1.20), stress case | 0.015 | 0.063 | 0.051 | 0.221 | 0.197 | 0.851 |
| Gemini 2.5 Flash Lite (0.10/0.40) | 0.005 | 0.021 | 0.017 | 0.074 | 0.066 | 0.284 |
| GPT-5 mini (0.25/2.00) | 0.021 | 0.101 | 0.075 | 0.354 | 0.288 | 1.367 |
| Gemini 2.5 Flash (0.30/2.50) | 0.027 | 0.126 | 0.093 | 0.442 | 0.358 | 1.706 |
| Gemini 3.5 Flash (1.50/9.00) | 0.101 | 0.461 | 0.352 | 1.615 | 1.356 | 6.227 |

If the OpenRouter page price (US$0.013 in / US$0.53 out) is the real current rate, DeepSeek costs come out slightly *below* the first row, because output dominates.

### Free-preview overhead (computed)
- The brief says a free preview runs the full extraction (and presumably the full correction pass) but shows only 3 corrections. So **every preview costs the same as a paid document**.
- Overhead per paid sale = (previews per sale − 1) × cost per document. With DeepSeek at a typical A$0.026 per 100-fn document:
  - 20% preview-to-paid conversion (4 non-paying previews per sale): A$0.10 per sale.
  - 5% conversion (19 non-paying): A$0.49 per sale.
  - 2% conversion (49 non-paying): A$1.28 per sale.
- Worst case (abuse: 400-fn documents at the max-output cap, 50 previews per sale): about A$21 per sale. That's why the per-browser/IP/day preview cap matters.

### Inferences
- With DeepSeek V4.1 Flash, LLM cost is a rounding error against any price of A$4 or more. **Payment fees, not inference, are the dominant variable cost** at A$4 (A$0.37 Stripe fee vs about A$0.03 LLM).
- Even a stronger model (GPT-5 mini or Gemini 2.5 Flash) would cost about A$0.07–0.09 per typical 100-fn essay, so there's room to upgrade quality (eg a second verification pass or a better model for hard citations) without changing price.
- Cheaper preview option: run the correction pass only on the first batch (15 footnotes) for the preview, which cuts preview cost by up to 85–95% on long documents. The trade-off is that a full-document count can't be shown ("we found 47 issues").
- Prices for DeepSeek models have swung by 10x or more across versions and providers in 2026. Budget against the stress row (peak-direct), not the promotional rates.
- Prompt caching of the fixed system prompt (a few thousand tokens per batch) could cut input cost further, but input is already a small share.

### Gaps
- Actual token counts per batch for Aforecite aren't known. The 3k-output "typical" figure is an assumption, and if V4.1 Flash emits reasoning tokens by default the real output could be higher. The owner should log `usage` from OpenRouter responses for 20–30 real essays.
- Could not load the OpenRouter model page directly to settle the US$0.15/0.60 vs US$0.013/0.53 conflict.
- Whether the US$0.80 minimum on OpenRouter top-ups matters depends on top-up size (it's negligible on US$50+ top-ups).

---

## 3. Is "A$4 for ~20 uses" (A$0.20/use) viable?

### Takeaway
It's technically profitable per document (LLM cost of about A$0.03 against about A$0.18 net per use), but commercially it's a roughly 80–90% cut in revenue per student. Most students would use only 4–10 of the 20 credits a semester, so the extra credits buy no extra volume. It also signals low value for a high-stakes task. If the owner's real concern is redrafts, a "free re-runs of the same essay" allowance on a per-document price solves it more cheaply.

### Computed figures (fees from §1, LLM from §2; DeepSeek typical 100-fn A$0.026/doc)
- One A$4 sale nets A$3.634 on Stripe domestic or A$3.912 on Square.
- Per use, if all 20 are used: A$3.634 / 20 = **A$0.182 net before LLM**, or about **A$0.156 after LLM** (A$0.170 on Square).
- Per student per semester:
  - A$4/document model, student processes 6 documents and pays for all: gross A$24, Stripe net 6 × 3.634 − 6 × 0.026 = **A$21.65** (Square A$23.32).
  - A$4 for 20 uses, same student: one purchase, gross A$4, net 3.634 − 0.156 = **A$3.48** (Square A$3.76).
  - Revenue per student falls about **84%**. At 4 documents the fall is 75%; at 10 documents, 90%.
  - To earn the same total, the bundle would need roughly 6x as many paying students (at 6 docs per student). Cheaper pricing could plausibly lift conversion somewhat, but not by 6x in a niche where the number of AGLC-using law students is fixed.
- Breakage: most of the 20 credits would go unused, so the cost of serving the bundle stays low. But breakage doesn't make up for the lost revenue, because the student would otherwise have paid per document.

### Cited Findings (supporting principles)
- Prelec & Loewenstein's "double-entry" mental accounting: prepaid consumption is enjoyed "as if free", and the pain of prepayment is buffered by thoughts of future benefit. That's why prepaid or flat bundles feel good to buyers. — [Prelec & Loewenstein (1998), Marketing Science 17(1):4–28, via RePEc](https://ideas.repec.org/a/inm/ormksc/v17y1998i1p4-28.html)
- Consumers often choose flat rates even when pay-per-use would be cheaper ("flat-rate bias", Train 1991). The opposite pay-per-use bias is less important and less regular (Lambrecht & Skiera 2006). Drivers include the "taxi meter effect", insurance against bill volatility, convenience and overestimating usage. — [Uni Frankfurt repository paper (Lambrecht/Skiera line of work)](https://publikationen.ub.uni-frankfurt.de/files/86311/BF03342716.pdf); [Lambrecht & Skiera "Paying too much" (UCLA)](https://www.anderson.ucla.edu/documents/areas/fac/marketing/paying_too_much.pdf)
- Comparable student products price per document by size, not by cheap bulk use: Scribbr's plagiarism check is a one-off **US$19.95 (up to 7,500 words) / US$29.95 (7,500–50,000) / US$39.95 (50,000+)** per check, with no subscription. — [Scribbr Plagiarism Checker](https://app.scribbr.com/plagiarism-checker); [Scribbr FAQ](https://www.scribbr.com/frequently-asked-questions/when-to-buy-the-premium-plagiarism-checker/)

### Inferences
- A$0.20 per use anchors the tool's value at "trivial". A student facing an essay deadline worth 30–50% of a unit grade, where AGLC errors lose marks, is buying risk reduction, and the price should reflect that rather than compute cost. Scribbr charges US$20–40 per check for a related "make my essay safe to submit" job.
- Flat-rate bias means students will happily prepay for more than they need. That's an argument for a modest pack priced near expected usage (eg 3–5 docs), not for 20 uses at a token price.
- The legitimate need behind "20 uses" is iteration: students fix the essay, add footnotes, and re-run. The better fix is **one paid document = unlimited or up to 3 re-runs of the same essay for 7–14 days** (matched by filename/hash or a token in the download link). That keeps per-essay revenue and removes the fear of paying twice. The re-runs are cheap to serve (about A$0.03 each).
- If the owner wants a low entry price, a single A$5 document plus a pack discount (see §6) gets most of the "feels cheap" benefit without destroying revenue per student.

### Gaps
- No data on Aforecite's actual conversion elasticity: whether A$0.20 per use would convert enough extra students to matter. A short Van Westendorp survey of law students, or an A/B test, would settle it.

---

## 4. Comparing pricing structures for an infrequent, deadline-driven, high-anxiety use case

### Takeaway
The evidence favours **per-document pricing (optionally size-tiered) as the core, with a small credit pack as a decoy-anchored upsell**, plus optionally a **fixed-term, non-renewing exam or semester pass**. Monthly subscriptions fit badly: usage is lumpy and tied to assessment deadlines, and auto-renewing student subscriptions are a growing ACCC enforcement and legislative target. Freemium is already in place as the 3-correction preview, and that's the right form of it.

### Cited Findings
- **Charm pricing:** Anderson & Simester's field experiments found that a $9 price ending increased demand in all three experiments, more strongly for new items. In one test, a dress at $39 outsold both $34 and $44. — [Anderson & Simester (2003), Quantitative Marketing and Economics, Kellogg summary](https://www.kellogg.northwestern.edu/faculty/research/detail/2003/effects-of-9-price-endings-on-retail-sales-evidence); [DOI 10.1023/A:1023581927405](https://www.doi.org/10.1023/A:1023581927405); [The Media Leader (Shotton)](https://uk.themedialeader.com/brilliance-in-advertising-charm-pricing/)
- **Decoy / anchoring:** In Ariely's Economist experiment (web $59 / print $125 / print + web $125), 84% chose print + web and 16% web only. With the decoy removed, 68% chose web only and 32% print + web, a revenue difference of about 30–43% depending on the write-up. — [Wikipedia: Decoy effect](https://en.wikipedia.org/wiki/Decoy_effect); [UBC blog](https://blogs.ubc.ca/onurkurtic/2015/07/10/the-decoy-effect/)
- **Willingness-to-pay research:** Patrick Campbell (Price Intelligently/ProfitWell, sold to Paddle for over US$200m) argues pricing should come from customer WTP data, eg Van Westendorp surveys, not guesswork. — [Antoine Buteau: Lessons from Patrick Campbell](https://www.antoinebuteau.com/lessons-from-patrick-campbell/); [Monetizely](https://www.getmonetizely.com/articles/understanding-willingness-to-pay-a-critical-metric-for-saas-success)
- **Pain of paying / flat-rate bias:** see §3 (Prelec & Loewenstein 1998; Lambrecht & Skiera 2006). — [RePEc](https://ideas.repec.org/a/inm/ormksc/v17y1998i1p4-28.html); [Uni Frankfurt](https://publikationen.ub.uni-frankfurt.de/files/86311/BF03342716.pdf)
- **Comparable products:**
  - Scribbr: per-document, size-tiered, one-off (US$19.95 / 29.95 / 39.95). — [Scribbr](https://app.scribbr.com/plagiarism-checker)
  - Turnitin Draft Coach: free to students where the institution licenses Turnitin, typically limited to **3 similarity checks** per document. — [Baylor](https://library.web.baylor.edu/news/story/2022/turnitin-draft-coach-now-available-students); [Iowa State CELT](https://celt.iastate.edu/learning-teaching-technology/turnitin-draft-coach)
  - remove.bg: monthly credit subscriptions (eg Lite US$9/mo for 40 credits, Pro US$39 / 200, Volume+ US$89 / 500; a plan was removed in July 2026), with API credits priced separately. Sources conflict. — [CostBench](https://costbench.com/software/ai-design-tools/remove-bg); [CostBench changelog Jul 2026](https://costbench.com/changelog/remove-bg-plan-removed-2026-07/)
  - ElevenLabs: subscription credits roll over up to 2x the monthly quota (no rollover on the free tier); unused credits are lost on cancel or downgrade; separate pay-as-you-go prepaid credits. — [ElevenLabs docs: credit rollover](https://elevenlabs.io/docs/help-center/account/general/how-does-credit-rollover-work.md); [ElevenLabs billing docs](https://elevenlabs.io/docs/product-guides/administration/billing)
  - AI-tool credit expiry policies vary widely (12 months from purchase, 12 months from last purchase, never). Expiring paid credits draw user anger as "breakage", for example in an OpenAI community thread about expired paid credits. — [OpenAI community thread](https://community.openai.com/t/paid-credits-expired-wth/1041718?page=3); [GPT for Work pricing FAQ](https://gptforwork.com/help/billing/pay-per-use-packs/faq); [wavespeed](https://wavespeed.ai/blog/cost-and-billing/do-unused-ai-api-credits-expire/)
  - Credit-based pricing collects cash before usage, and packs are typically volume-tiered. — [Lava: credit-based pricing for AI](https://www.lava.so/blog/credit-based-pricing-ai)
- **Direct competitor risk:** "Obiter" is listed on Microsoft Marketplace as a **free, open-source Word add-in implementing AGLC4**, with automatic formatting for 80+ source types and document validation against AGLC4 rules. Zotero no longer reliably supports AGLC4. — [Microsoft Marketplace: Obiter](https://marketplace.microsoft.com/en-au/product/office/WA200010629); [Zotero forums](https://forums.zotero.org/discussion/comment/486653/)

### Structure-by-structure assessment (inference, grounded in the above)

| Model | Fit to infrequent, deadline-driven, high-anxiety use | Pros | Cons |
|---|---|---|---|
| Pay per document (current) | Strong | Matches the job ("fix *this* essay"); no account needed; price can reflect stakes; simple to explain | Fixed fee hurts at low prices on Stripe; fear of paying again for redrafts (fix with free re-runs) |
| Tiered by footnote count | Good | Scribbr precedent; captures more from theses and long research papers; protects margin on 400-fn worst cases | Adds a decision at checkout; the preview must show the tier up front |
| Credit packs (1/3/10) | Good as an upsell | Flat-rate bias and prepaid "as if free" consumption; a decoy middle pack lifts average order value; pre-collects cash | Needs a way to hold balance without accounts (code or magic link); expiry is legally sensitive (§5); GST complexity once registered |
| Time passes (exam period / semester), non-renewing | Good for heavy users | Removes the taxi-meter feeling during crunch; one purchase per semester; no subscription-trap exposure if it doesn't auto-renew | Heavy users get the most value; needs identity (email link or code); share/abuse risk without accounts |
| Monthly subscription | Poor | Recurring revenue | Lumpy usage means students cancel; auto-renewal is an ACCC priority, with new UTP subscription duties proposed from July 2027 (§5); conflicts with "no accounts" |
| Freemium (preview of 3 fixes) | Already right | Shows the value specifically on the student's own essay; drives conversion | Full-run cost per preview; abuse needs caps (already in place) |

### Inferences
- **Per-document should stay the anchor**, priced at a charm point (A$5 or A$9 rather than A$4 or A$10). Students compare against the cost of lost marks and against Scribbr-type checks (about A$29–58 at current FX), not against compute.
- A **3-pack** works as the "obvious value" middle option, with a 10-pack acting partly as an anchor and decoy, following the Economist pattern.
- A **semester pass** suits students in heavy writing units, but it's worth adding only if the owner is willing to introduce a lightweight identity (emailed magic link or pass code).
- **Free competition (Obiter, library guides, Turnitin via institutions)** caps willingness to pay. Aforecite's differentiation is "fixes your existing footnotes with tracked changes in one go", so the price should sit well below Scribbr but clearly above trivial. A$5–9 per essay looks like the band. This needs validation by WTP testing.

### Gaps
- "Monetizing Innovation" (Ramanujam & Tacke) and Paddle/Price Intelligently benchmark data on usage-based or credit pricing weren't retrieved in this session. No citable statistics from them are included.
- No public data found on student conversion rates for per-document AI tools, or on breakage rates for consumer AI credit packs.
- Midjourney's current plan structure wasn't found in search results.
- No commercial AGLC4 checker with published student pricing was found (Obiter is free).

---

## 5. Australian legal constraints: credits, passes, refunds, subscriptions, GST, surcharging

### Takeaway
Avoid auto-renewing subscriptions and expiring credits. Make credits non-expiring, or valid at least 3 years to sit safely inside the gift-card regime if it applies. Never use "no refunds" wording, because ACL consumer guarantees can't be excluded. Below A$75k turnover there's no GST. After registration, packs priced in documents are likely GST-on-sale, while dollar-value credit is GST-on-redemption with an adjustment on expiry. Card surcharges are banned from 1 October 2026.

### Cited Findings
- **Unfair trading practices (UTP) and subscription traps:** Treasury's exposure draft (9 Feb 2026; consultation closed 23 Feb 2026) proposes a general prohibition on unfair trading practices in the ACL, plus specific subscription obligations (simpler cancellation, timely renewal notices) and drip-pricing rules, with proposed commencement **1 July 2027**. — [Allens](https://www.allens.com.au/insights-news/insights/2026/02/unfair-trading-practices-treasury-unveils-blueprint-for-new-regime/); [King & Wood Mallesons: UTPs arriving mid-2027](https://www.mallesons.com/au/en/insights/latest-thinking/unfair-trading-practices-arriving-mid-2027-but-utp-style-enforcement-has-already-landed.html); [APH Bills Digest: Competition and Consumer Amendment (Unfair Trading Practices) Bill 2026](https://www.aph.gov.au/Parliamentary_Business/Bills_Legislation/bd/bd2526/26bd058)
- One law-firm source says the Bill **passed Parliament without amendment on 2 July 2026**. This is single-source and unverified. — [Boettcher Law](https://boettcher.law/commercial-law/unfair-trading-practices-dark-patterns-australia/)
- The ACCC's 2026–27 priorities include manipulative conduct in the digital economy, specifically subscription traps and dark patterns, and it is already suing under existing ACL provisions (eg HelloFresh, Youfoodz). — [Norton Rose Fulbright](https://www.nortonrosefulbright.com/en-au/knowledge/publications/e88ea652/accc-confirms-2026-27-compliance-and-enforcement-priorities); [HSF Kramer](https://www.hsfkramer.com/insights/2026-02/accc-enforcement-priorities)
- **Unfair contract terms (UCT):** from 9 November 2023 it is an offence to propose or rely on an unfair term in a standard-form consumer or small-business contract. The maximum corporate penalty is the greatest of several measures with a floor of A$50m; for individuals (eg a sole trader) it's A$2.5m. — [ACCC media release](https://www.accc.gov.au/media-release/businesses-urged-to-remove-unfair-contract-terms-ahead-of-law-changes); [NSW Small Business Commissioner](https://www.smallbusiness.nsw.gov.au/news/new-unfair-contract-penalties-win-small-business); [KWM UCT Nov 2023 PDF](https://www.kwm.com/content/dam/kwm/insights/download-publication/australia/2023/Unfair%20Contract%20Terms%20-%20ACL%20-%20November%202023.pdf)
- **Gift-card regime:** gift cards supplied from 1 November 2019 must be valid for at least 3 years, and post-purchase fees (activation, account-keeping, balance-enquiry) are banned. It generally applies even if the card is redeemable only at your own business. Exemptions sit in regs 89A–89C of the Competition and Consumer Regulations 2010; reloadable or top-up cards are reportedly exempt. — [consumer.gov.au: New gift card laws](https://consumer.gov.au/node/161); [Sprintlaw](https://sprintlaw.com.au/articles/do-gift-cards-expire-in-australia-what-businesses-should-know/); [Consumer Affairs Victoria](https://www.consumer.vic.gov.au/consumers-and-businesses/products-and-services/business-practices/gift-vouchers-and-gift-cards); [Qld Govt](https://www.qld.gov.au/law/laws-regulated-industries-and-accountability/queensland-laws-and-regulations/selling-your-products-and-services/selling-products/selling-gift-cards)
- **Consumer guarantees for services:** due care and skill (ACL s 60), fitness for a disclosed purpose (s 61), and supply within a reasonable time. Remedies for failure include refund, re-supply, compensation or cancellation, and the guarantees can't be excluded by contract. Cloud or online access is generally treated as a service. — [Law Handbook (FLS)](https://fls.org.au/law-handbook/consumers-contracts-the-internet-and-copyright/consumer-guarantees/consumer-guarantees-services/); [ACCC small business toolkit](https://www.accc.gov.au/business/selling-products-and-services/small-business-toolkit/consumer-rights-and-guarantees/introduction); [LegalVision: can I exclude the consumer guarantees](https://legalvision.com.au/can-i-exclude-the-consumer-guarantees)
- **GST on vouchers / prepaid credit (ATO):** the sale of a *face-value voucher* (stated monetary value, redeemable for a reasonable choice of goods or services) at or below face value is not a taxable supply; GST is accounted for on redemption, and an **increasing adjustment** is required when it expires or isn't fully redeemed (GSTR 2003/5). *Non-face-value vouchers* (redeemable only for specific goods or services) are taxed at sale. — [ATO: GST and vouchers](https://www.ato.gov.au/businesses-and-organisations/gst-excise-and-indirect-taxes/gst/in-detail/rules-for-specific-transactions/gst-and-vouchers); [ATO small business newsroom](https://www.ato.gov.au/businesses-and-organisations/small-business-newsroom/are-you-applying-gst-correctly-for-vouchers)
- **Surcharging:** banned for eftpos, Visa and Mastercard from 1 October 2026 (other networks followed). — [Stripe support](https://support.stripe.com/questions/australia-is-removing-card-surcharges-what-stripe-users-need-to-know)

### Inferences
- **Expiring credits:** whether a digital credit balance on Aforecite is a "gift card" under ACL Pt 3-1 Div 3A is uncertain. The definition isn't limited to gifts, and the regime covers "any other thing" redeemable for goods or services, but exemptions exist. The low-risk design is **no expiry**, or at least 3 years, with no fees on balances. Breakage revenue on packs this small is negligible, so expiry gains little and creates UCT ("unfair term") and gift-card risk.
- **Passes:** a fixed-term pass (eg 14 days or "until 30 June") that **doesn't auto-renew** stays outside the coming subscription-trap rules and the ACCC's current focus. If auto-renewal is ever added, it will need clear pre-renewal notices and one-click cancellation from 1 July 2027 (proposed), and is already risky under the existing misleading-conduct provisions.
- **Refunds:** terms like "all sales final" or "no refunds" risk breaching the ACL's false or misleading representations provisions about consumer-guarantee rights, and could be an unfair term. A clear policy works better: an automatic refund or re-run if the output fails (eg corrupt .docx, footnotes missed), and goodwill refunds within X days. On Stripe the original fee isn't returned, so each refund at A$4 costs about A$0.37 plus LLM cost. Refunds are still far cheaper than chargebacks (A$25+).
- **Unused credit refunds:** consumers are generally not entitled to a refund of unused prepaid credit for change of mind under the ACL (unless there's a guarantee failure), but offering refunds of unused packs within, say, 30 days is cheap goodwill.
- **GST once registered** (turnover ≥ A$75k): a pack defined as "3 documents" is likely a non-face-value voucher, so GST is payable on the full sale at purchase. A dollar wallet ("A$15 credit") would be a face-value voucher, with GST on redemption and an increasing adjustment on expiry or breakage. Document-count packs are simpler to account for. Until registered, prices are GST-free and no GST is charged.
- GST registration would cost 1/11 of gross (about 9.1%) unless prices rise. Pricing at A$5 or A$9 GST-inclusive from day one avoids having to raise the price later.
- A sole trader's UCT exposure is the individual cap (A$2.5m). Keep the terms plain: no unilateral variation, no unreasonable expiry, no blanket liability exclusions.

### Gaps
- Not confirmed whether online prepaid credit for a single-supplier digital service is caught by the gift-card 3-year rule, or which reg 89A–89C exemption might apply. Advice or a reading of the Regulations is needed.
- The UTP Bill's passage and final text are unverified (single source). Check the APH Bills Digest and the Federal Register of Legislation.
- GSTR 2003/5 itself wasn't retrieved; the voucher analysis relies on the ATO summary page.

---

## 6. Recommended price structures and expected net per student per semester

### Takeaway
Three options, from simplest to most ambitious. All three are worth roughly 4–6x more per student than "A$4 for 20 uses". Option A, size-tiered per-document pricing with a 3-pack and free re-runs, is the best fit for a no-accounts, deadline-driven product.

Common assumptions for the per-semester estimates: student processes 6 essays a semester (sensitivity 4 and 10); essays are about 100 fn; LLM cost A$0.03 per paid essay plus A$0.03 per free re-run (2 re-runs per essay); preview overhead A$0.10 per sale (20% conversion); Square 2.2% vs Stripe domestic 1.65% + A$0.30. These are estimates, not data.

### Option A (recommended): per-document, size-tiered, with a 3-pack and free re-runs
- **Essay (up to 150 footnotes): A$5.** **Long work (151–400 footnotes, eg thesis or research paper): A$9.** **3-Essay pack: A$12** (A$4 each, "save 20%"). Credits never expire (or 3 years minimum). Every purchase includes **free re-runs of the same document for 14 days**.
- Display the 1 / 3 / 10 ladder with a **10-pack at A$35** as an anchor, so the 3-pack reads as the sensible middle option. Some students will buy the 10-pack, which is fine.
- No accounts: deliver pack credits as a redeem code plus an emailed receipt link.
- Per sale net (Stripe / Square): A$5 is A$4.62 / A$4.89; A$9 is A$8.55 / A$8.80; A$12 is A$11.50 / A$11.74; A$35 is A$34.12 / A$34.23.
- **Expected per student per semester (6 essays):** two 3-packs = gross A$24. Net Stripe 2 × 11.50 − 6 × (0.03 + 0.06) − 2 × 0.10 ≈ **A$22.3** (Square ≈ **A$22.8**).
  - Light user (4 essays: one 3-pack + one single, A$17): about A$15.6 Stripe / A$16.1 Square.
  - Heavy user (10 essays: 10-pack, A$35): about A$33.0 Stripe / A$33.2 Square.

### Option B: keep A$4 headline, add packs and an exam pass (minimal change from today)
- **Single essay A$4.99** (charm price; any re-run of the same essay free for 7 days). **5-pack A$15** (A$3 each). **14-day Exam Pass A$9.99**: unlimited essays (fair-use cap, eg 15 runs) for 14 days, **no auto-renew**, delivered as a pass code or magic link.
- Per sale net Stripe / Square: A$4.99 is A$4.61 / A$4.88; A$15 is A$14.45 / A$14.67; A$9.99 is A$9.53 / A$9.77.
- **Expected per student per semester (6 essays):** a 5-pack plus one single = A$19.99 gross. Net about A$18.3 Stripe / A$18.8 Square, after LLM of about A$0.5 and preview overhead.
  - Two exam passes (mid-sem and end-of-sem crunch) = A$19.98 gross, net about A$18.3 (Stripe) to A$18.8 (Square).
  - Light user (4 essays as singles): about A$17.7 (Stripe) to A$18.8 (Square).

### Option C: semester pass plus per-essay (for owners willing to add light identity)
- **Per essay A$5** (as in Option A). **Semester Pass A$19**: unlimited essays until a fixed date (eg 31 July or 30 November), fair use 20 runs, **no auto-renewal**, email magic link. Optional **Year Pass A$29** shown as an anchor.
- Per sale net Stripe / Square: A$19 is A$18.39 / A$18.58; A$29 is A$28.22 / A$28.36.
- **Expected per student per semester:** semester pass buyer about **A$17.9** (Stripe) / A$18.1 (Square) after 6–10 essays of LLM cost. Per-essay buyers at 6 essays about A$26.7 net (6 × A$4.62 Stripe, less LLM). A pass is the better deal for the student from 4 essays up, which concentrates passes among heavy users. Blended net is likely A$18–25 per paying student.

### Comparison with the floated "A$4 for 20 uses"
- Per student per semester: about **A$3.5 net** (Stripe) / A$3.8 (Square), and that student won't buy again until next semester or later.
- Options A to C are worth about **A$16–33 per paying student per semester**, which is 5–9x more, with LLM still under 3% of revenue.

### Inferences
- Under current prices, **switching processor to Square** adds about 1–7% net at A$4–A$20, more at lower prices, which matters for Option B. The trade-off is that Stripe Checkout is more flexible for codes, passes and webhooks.
- The pricing decision is about **perceived value and conversion**, not cost: LLM is about 1% and fees 3–9% of price at A$5–A$20.
- Validate before committing with a quick Van Westendorp survey of 30–50 law students (Campbell's method), or an A/B test of A$5 vs A$9 single-essay pricing on the preview page.

### Gaps
- The 6 essays per semester figure, the 20% preview conversion and the 2 re-runs per essay are assumptions, not measured data.
- No elasticity data exists for this niche. The relative conversion of the options can't be estimated from the sources found.
- Per-semester figures exclude refunds and chargebacks. On Stripe each refund loses the original fee (about A$0.37–0.63) and each dispute costs A$25+.
