# Search and AI answer-engine notes

Last updated 1 November 2026. What we found about the search landscape for Aforecite's queries, the strategy, everything that changed in the code, and what the owner has to do off-site.

## 1. Landscape (quick check, 1 November 2026)

Queries checked with web search: "AGLC referencing generator", "AGLC4 footnote checker", "AGLC ibid rule", "how to cite a case AGLC", "AGLC4 website citation example", "AGLC signals see cf see generally", "AGLC4 checker free", "AGLC treaty citation example ATS UNTS", "AGLC report citation law reform commission", "AGLC5 release date".

What ranks:

- **University library guides dominate every rule query.** Melbourne (Re:cite), UNSW, ANU, Monash, UQ, UWA, Deakin, USQ/UniSQ, Curtin, SCU, ACU, Murdoch, Griffith, Swinburne, UTS PDFs, QUT CiteWrite. They are thorough but generic, often long, and frequently say "check the AGLC itself". Many answer the rule but not the follow-up questions students actually ask ("is Cf italic?", "is the jurisdiction italic?").
- **Generators and checkers are thin.** For "AGLC referencing generator" the results are library pages, Evernote's generic citation generator, Proofed blog posts, a Reddit thread asking for a reliable AGLC4 generator (no good answer), EndNote/Zotero styles, and UNE's "AGLC4 SmartCite" chat agent. For "AGLC4 footnote checker" and "AGLC4 checker free" nothing checks a whole essay's footnotes except one Microsoft Marketplace Word add-in. That is the gap Aforecite fills.
- **Proofed (getproofed.com.au) blog posts** rank for "how to cite a case AGLC" and similar how-to queries.
- **Signals are answered badly.** "AGLC signals see cf" returns Wikipedia and US Bluebook pages; AGLC-specific answers are scarce, and the answer engines fall back on Bluebook definitions (which differ: Bluebook italicises signals, AGLC4 doesn't).
- **AGLC5 is uncertain.** MULR's AGLC site has an "AGLC 5" page (consultation); Wikipedia mentions a 2023 call for submissions. No release date surfaced. Students ask; nobody answers plainly.
- Obiter (the AGLC citation builder) didn't appear in these results, but is the obvious comparison; the home page FAQ already addresses it.

Answer engines tend to quote the first sentence or two of a page that directly answers the question. Library guides often bury the answer, which is the opening for short, direct guide pages.

## 2. Strategy

1. **Be the clearest direct answer** for each rule query: the first paragraph of every guide answers the query in one or two quotable sentences, with a worked citation, followed by the pattern, examples and a short visible "Common questions" section (marked up as `FAQPage`).
2. **Own the gaps**: signals (AGLC-specific, roman type), a common-mistakes checklist (strong intent from students about to submit), and AGLC4 vs AGLC5.
3. **Be the checker**: "AGLC4 referencing generator / footnote checker" intent goes to the home page; every guide ends with "Fix every footnote in your essay" linking to the upload.
4. **Make the site easy for crawlers and AI to read and cite**: canonical URLs, structured data, a sitemap with dates, an explicit robots.txt welcome for search and AI answer crawlers, and `/llms.txt`.
5. **Truthfulness**: no reviews, ratings, user counts or testimonials anywhere, including structured data. FAQPage markup is generated from the questions visible on the page, so it can't drift from them.

## 3. What changed (technical)

All in `aglc/site.py` unless noted.

- **Canonical, Open Graph and Twitter tags** on every public page from one partial, `web/partials/meta.html` (`{{canonical}}`, `{{og_title}}`, `{{og_type}}`, `{{description}}`), used by `web/page.html` and `web/guide.html`. The home page keeps its own head tags; it gained `twitter:title`, `twitter:image` and its JSON-LD. Canonicals use `$AGLC_PUBLIC_URL` (or the request origin).
- **JSON-LD** (one `@graph` per page, `{{jsonld}}` filled after the page is rendered):
  - every page: `Organization` (name: `$AGLC_OWNER_NAME`, else the brand) and `WebSite`;
  - home: `WebApplication` (applicationCategory `EducationalApplication`, operatingSystem `Web`); `offers` with the live price from `billing.PRODUCTS` only when payments are on (read-only use of billing);
  - guides: `TechArticle` (headline, description, `dateModified` from the guide's `updated`, author and publisher = the Organization) and `BreadcrumbList`;
  - guides index: `CollectionPage` with an `ItemList` of the guides; static pages: `WebPage`/`AboutPage` and `BreadcrumbList`;
  - `FAQPage` only where the page shows questions: read from the rendered HTML by `page_faq()` (home `<div class="faq">` details; guides' `<section class="g-faq">`). Home questions marked `data-paid` are left out when payments are off, because the page hides them then.
  - `<` is escaped inside the JSON so no string can close the script element.
- **Visible breadcrumbs** on guides (Home / AGLC4 guides) and a visible "Last updated" date that matches `dateModified`.
- **Sitemap**: `<lastmod>` per URL (guides: `Guide.updated`; policy pages: `POLICY_DATE`; home, about and the guides index: `PAGE_DATES`, each page's real last change, which for /about is 18 October 2026 from the repository history). The API stays out.
- **robots.txt**: `/api/` disallowed in every group (a crawler obeys only its most specific group). Search and AI answer crawlers named explicitly and allowed: Googlebot, Bingbot, Applebot, DuckDuckBot, OAI-SearchBot, ChatGPT-User, Claude-SearchBot, Claude-User, PerplexityBot, Perplexity-User. AI training crawlers (GPTBot, ClaudeBot, Google-Extended, Applebot-Extended) are allowed too.
  - **Why**: the goal is to be cited in AI answers. Answer engines fetch pages with their search/user agents; models trained on the guides are also more likely to know and mention the site.
  - **How to reverse**: set `AGLC_BLOCK_AI_TRAINING=1` to give the training crawlers `Disallow: /` while keeping search and answer crawlers. To block an answer engine too, remove it from `SEARCH_CRAWLERS` (it then falls back to the `*` group, which allows everything but the API) and add a group with `Disallow: /`.
- **`/llms.txt`** (route in `aglc/api.py`): plain-language description of what the tool is and isn't (formats the citations it recognises, writes no content, every change listed for review and, by default, a tracked change, never guesses, not affiliated with MULRA, check your unit's AI rules), and every guide with its one-line summary, generated from `GUIDES`. States the price only when payments are on.
- **Titles and descriptions**: every guide title ≤ 48 characters (≤ 60 with " | Aforecite"), descriptions ≤ 155; home title is now "AGLC4 Referencing Generator & Footnote Checker | Aforecite". Tests enforce uniqueness and length across `PUBLIC_PATHS`.
- **CSS** (`web/assets/chambers.css`): `.g-pattern` (a citation's shape with named parts) and `.g-faq` (Common questions).
- **Guide template**: the "Guide is the authority" note now says the pages explain in our own words, with examples "from the Guide" marked as such; the call to action reads "Fix every footnote in your essay".
- **Tests**: `tests/test_api.py` (canonical and social tags on every public page; JSON-LD parses with `@context`/`@type`, no review/rating types; home, guide, index and static page graphs; FAQPage equals the visible questions, with and without payments; offer only with payments; owner name; sitemap lastmod; robots groups and the training switch; llms.txt; unique, short titles and descriptions; one `<h1>`; `alt` on images; every guide has 3–5 Common questions and the call to action). `tests/test_guide_examples.py` pins every example citation of our own on the guides to the real formatters' output, which is what lets the guides' guard test accept them.

### New and changed guides

| Guide | Slug | Target query |
|---|---|---|
| How to cite a journal article in AGLC4 | `/guides/journal-articles` | AGLC4 journal article citation |
| How to cite a website or web page in AGLC4 | `/guides/websites` | AGLC website citation |
| How to cite reports and ALRC reports in AGLC4 | `/guides/reports` | AGLC report citation, ALRC report AGLC |
| AGLC4 signals: See, See also, Cf and Contra | `/guides/signals` | AGLC signals see cf |
| How to cite a treaty in AGLC4, with examples | `/guides/treaties` | AGLC treaty citation |
| How to cite Hansard in AGLC4, with examples | `/guides/hansard` | AGLC Hansard, second reading speech, explanatory memorandum |
| Common AGLC4 footnote mistakes: a checklist | `/guides/common-mistakes` | AGLC footnote checker, AGLC common mistakes |
| AGLC4 or AGLC5: which edition should you use? | `/guides/aglc4-vs-aglc5` | AGLC5, AGLC 5th edition |

`articles-and-books` (same slug) is now "How to cite books and chapters in AGLC4", pointing to the new journal-articles page so the two don't compete. Every existing guide got a tighter first paragraph where needed and a Common questions section. The legislation guide no longer says explanatory memoranda are unsupported (they are: `aglc/formatters/parliamentary.py`).

Examples on the new pages are our own citations of real sources (Mason and Gageler in the *Federal Law Review*, Dixon in the *ALJ*, ALRC Report No 133, Productivity Commission Inquiry Report No 72, the Royal Commission's Final Report, the CRC, ICCPR and VCLT, the 2008 Apology in Hansard, the Native Title Bill 1993 EM), each checked against the formatter in `tests/test_guide_examples.py`. Pinpoints only illustrate the form. Before-and-after examples come from the sample essay that `tests/test_end_to_end.py` runs through the tool. Some of that essay's sources are invented (the J Smith article, *Smith v Jones*, *Attorney-General (NSW) v X*); every figure that shows one says so in its caption. The websites guide no longer uses the essay's footnote 9 (really a report, with a year-only date) as a before-and-after.

### Home page

Edits limited to `<head>` (title, Twitter tags, JSON-LD) and the existing Questions section: one sentence added to the academic-integrity answer ("Every change is listed for you to review before you download and, with tracked changes on (the default), shown in your .docx as a Word tracked change, so you decide what stays.") and six questions appended after the existing ones (changes to essay text; free preview, marked `data-paid` and using `{{preview_full}}`, no price; Ibid and (n x); bibliography; common mistakes, linking the checklist; AGLC4 or AGLC5). The existing FAQ already covered Word files, privacy and academic integrity, so a second FAQ section would have duplicated it.

## 4. Off-site checklist for the owner (in priority order)

1. **Google Search Console**: add the domain property (DNS TXT record), submit `https://<domain>/sitemap.xml`, then use URL Inspection → Request indexing for `/`, `/guides` and the new guides. Check Enhancements for FAQ and Breadcrumbs after a week.
2. **Bing Webmaster Tools**: import the site from Search Console (fastest) or verify by DNS, submit the sitemap, and turn on IndexNow if offered. This matters more than its search share suggests: ChatGPT search and Copilot draw on Bing's index.
3. **Set `AGLC_PUBLIC_URL`** in production so canonicals, the sitemap, robots.txt and llms.txt use the real domain, and **`AGLC_OWNER_NAME`** so the structured data names the publisher.
4. **University library AGLC pages**: email the law librarians who maintain the AGLC guides (Melbourne Re:cite, UNSW, ANU, Monash, UQ, UWA, Deakin, UniSQ, Curtin, Griffith, Macquarie, UTS, Murdoch, SCU, ACU, Newcastle, Canberra, Swinburne). Ask to be listed under "tools" next to Zotero/EndNote styles; point out it writes no content and shows every change as a tracked change (their main academic-integrity concern). Expect a few yeses; each is a high-authority link.
5. **Law student societies and law society student/member pages**: MULS, UNSW Law Society, ANU LSS, etc. publish AGLC resources and member deals; offer a student-society discount code if pricing allows.
6. **Genuine forum answers**: where students ask for an AGLC4 generator or checker (r/auslaw, r/LawSchoolAus, university subreddits such as r/UTS, r/unimelb, r/UNSW), answer the actual question first (link the relevant free guide), disclose that you make the tool, and mention it only where it fits. A few honest answers, not a campaign.
7. **Measure AI referrals**: with Plausible on (`AGLC_PLAUSIBLE_DOMAIN`), watch Sources for `chatgpt.com`, `perplexity.ai`, `copilot.microsoft.com`, `gemini.google.com`, `claude.ai` and `bing.com`. Monthly, ask ChatGPT, Perplexity and Google (AI Overviews) the target queries and note whether Aforecite is cited.
8. **Refresh dates honestly**: when a guide changes, update its `updated` in `GUIDES` (it feeds the page, the sitemap and the JSON-LD). Don't bump dates without changes.

## 5. Notes, deviations and left undone

- **Newspaper articles guide: not written.** The brief cited r 7.7; in AGLC4 newspapers are r 7.11 (r 7.7 is legal encyclopedias). I couldn't verify real article details (author, title, date, page) well enough to use as our own examples, and the Guide's examples shouldn't be copied, so I left it out rather than invent citations. A future page can use the pattern (Author, ‘Title’, *Newspaper* (Place, Full date) Page; online: (online, Full date) <URL>) with articles the owner has checked.
- **The home page meta description is about 230 characters** and contains the price. Left for the coordinator to handle at merge time with the pricing work; Google truncates it. Suggested shorter wording once pricing settles: "Fix every AGLC4 footnote in your Word essay: Ibid, (n x), short titles and a bibliography, returned as tracked changes. First {{preview_full}} fixes free."
- **Two `<h1>` on the home page**: the second is the results view's heading ("Your footnotes"), hidden until a document is checked. Left for the coordinator to handle at merge time; tests require exactly one `<h1>` everywhere else.
- **The "What it fixes" table on the home page** doesn't list Hansard/explanatory memoranda, which the tool formats; not edited (outside the allowed edits).
- **AGLC5**: as at 1 November 2026, searches found MULR's consultation page and no release date; `law.unimelb.edu.au` couldn't be fetched from this environment, so the page states only that and links MULR's AGLC page. Re-check it when updating.
- Tracked changes are an option (on by default), so every claim about them says "by default" or "with tracked changes on"; every change is listed for review on the page either way.
- The guides claim only what the code does: the common-mistakes page separates what the tool fixes, what it flags (an Ibid or (n x) to a case or secondary source with no pinpoint; a body-text footnote number it can't safely move) and what the student must check (pinpoints on first citations, choice of signal, footnotes it couldn't read).
- Signals: I kept to what the code and the Guide's own examples show (roman type, capitalisation, a new sentence when the signal changes). Whether a signal carries over to later sources in a semicolon list isn't stated on the page.
