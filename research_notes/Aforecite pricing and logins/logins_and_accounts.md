# Logins and accounts for Aforecite: accounts vs no accounts, light ways to hold credits, and Australian legal and security duties (as of 1 Nov 2026)

Research method note: in this session WebFetch could not reach any site (oaic.gov.au, hsfkramer.com and solway.au all failed DNS resolution under the session's network allowlist). Every finding below comes from search-result snippets and summaries, not from reading the full pages. Most legal-status findings come from law-firm and compliance commentary rather than primary OAIC or AGD pages. Check the primary sources before relying on exact dates.

## 1. Conversion evidence: what forced sign-up costs, and when an account helps

### Takeaway
Forcing account creation before payment is a well-documented conversion killer. About 18-19% of US online shoppers say they have abandoned an order because a site wanted them to create an account, and the "$300 million button" case is the classic example of the gain from removing a register step. Accounts mainly pay off for repeat-purchase relationships: holding a balance, re-engagement, and a legal basis for marketing email. Aforecite's credit packs or passes would create exactly that kind of relationship. The usual best practice is to sell without an account and offer the account (or a lighter identity) after purchase.

### Cited Findings
- Baymard's survey of 1,026 US adults found that 18% abandoned an order because "the site wanted me to create an account". Other write-ups round this to 19%. This is about the fourth-biggest reason, after extra costs (~40%), slow delivery (~20%) and distrust of the site with card details (~19%). The full ranking comes from secondary sites because Baymard's page could not be opened. — [Baymard: reduce cart abandonment](https://baymard.com/blog/reduce-cart-abandonment); [Baymard: current state of checkout UX](https://baymard.com/blog/current-state-of-checkout-ux)
- A "26% abandoned due to mandatory account creation" figure also circulates. It appears to come from an older (2024) ranking, so it conflicts with Baymard's 2025 figure of about 18%. — [RetailBoss 2024 ranking](https://retailboss.co/10-reasons-for-abandonment-during-checkout-in-the-u-s); [Statista](https://statista.com/statistics/1228452/reasons-for-abandonments-during-checkout-united-states)
- Baymard's 2025 benchmark: 62% of sites still fail to make guest checkout the most prominent option. Baymard testing also found that strict password rules can cause up to 19% checkout abandonment among existing account holders who have trouble signing in. That is a cost of passwords even after users have accounts. — [Baymard: current state of checkout UX](https://baymard.com/blog/current-state-of-checkout-ux)
- "$300 million button" (Jared Spool, UIE/Center Centre): a major retailer's checkout forced login or registration. Replacing the "Register" button with "Continue", plus a note that no account was needed, reportedly added $300m in the first year. The secondary claim that purchases rose 45% is not in Spool's excerpt, so treat it as unverified. The retailer's identity (often guessed to be Best Buy) is speculation. — [Center Centre (Spool original)](https://articles.centercentre.com/three_hund_million_button/); [Boing Boing summary](https://boingboing.net/2011/08/05/300-million-button-making-customers-create-logins-to-buy-cost-etailer-300myear.html)
- In the same case, 45% of repeat customers had multiple accounts because they forgot their logins or lost email access and signed up again. This shows that password accounts do not reliably give one identity per person. — [Boing Boing](https://boingboing.net/2011/08/05/300-million-button-making-customers-create-logins-to-buy-cost-etailer-300myear.html)
- Where accounts help with marketing: under the Spam Act, inferred consent to market by email "usually comes from a provable, ongoing relationship, such as a membership or an account", and consent "should not be inferred from one-off purchases". A one-off A$4 guest purchase therefore gives weak grounds for marketing emails. An account or credit-balance relationship gives stronger grounds, though still only for related messages. — [Sprintlaw](https://sprintlaw.com.au/articles/email-marketing-in-australia-essential-legal-compliance-guide/); [Addisons on ACMA consent statement](https://addisons.com/article/the-acma-has-issued-a-statement-about-its-expectations-for-using-consent-to-conduct-e-marketing-and-telemarketing/)

### Inferences
- Aforecite's current flow (preview, then pay, then download, no account) matches the evidence-backed pattern. Adding a mandatory sign-up before the preview or before payment would probably cost a material share of first-time buyers. The ~18% figure is an upper-bound signal from e-commerce, not a measured number for Aforecite. The cost may be larger for a low-price, one-off, deadline-driven student purchase.
- A balance (credit pack or pass) does need some persistent identity. The least damaging place to ask for it is after payment ("Save your remaining 19 uses: enter or confirm your email"). Stripe Checkout already collects the email, so this step can be nearly free.
- Accounts do bring real benefits: holding credits across devices, recovering purchases, receipts and history, re-engagement around exam and essay seasons, and a lawful basis for related marketing. Credit packs only work commercially if students can find their balance again a week later.

### Gaps
- No studies were found that measure sign-up walls specifically for AI or SaaS tools, or for student tools, in conversion terms. Figures beyond e-commerce checkout are not sourced.
- Baymard's 2025 reason ranking could not be read first-hand. The 18% vs 19% figures conflict slightly.

## 2. Ways to hold a balance without full accounts: options, effort and costs for a solo FastAPI + SQLite developer

### Takeaway
The lightest workable option is email as identity, verified by a one-time code or magic link (passwordless). The email can be pre-filled from what Stripe Checkout already collects, and credits sit in a SQLite balance table keyed to a verified email. Emailed redeem or licence codes are an even lighter fallback that needs no login at all. Social sign-in (Google) is cheap to add with Authlib. "Sign in with Microsoft" for university accounts is hampered by education tenants that commonly block user consent. Hosted auth providers have generous free tiers, but they add a third party holding student identity data for little gain at this scale.

### Cited Findings
- **Stripe no-code customer portal:** it can be set up "in a few minutes, without writing any code". Customers log in "with their email address and a one-time passcode" via a login link you share, and the email can be pre-filled with a `prefilled_email` parameter. If several customers share an email, Stripe picks the most recent one with an active subscription. The portal is designed around subscriptions, invoices and payment methods, so it does not obviously show a custom credit balance. — [Stripe docs: activate no-code customer portal](https://docs.stripe.com/customer-management/activate-no-code-customer-portal)
- **Resend (transactional email for magic links or codes):** the free plan is permanent, with 3,000 emails a month capped at 100 a day. Sources say 1 to 3 custom domains. On the free tier, sends fail at the cap (no surprise bills) until the day or month resets. — [Resend blog: new free tier](https://resend.com/blog/new-free-tier); [Flexprice Resend pricing guide](https://flexprice.io/blog/detailed-resend-pricing-guide)
- **Hosted auth free tiers (2026, secondary comparison sites):**
  - Clerk Hobby: 50,000 monthly retained users per app, then $0.02 per user. Older guides that say 10,000 are out of date.
  - Supabase Auth: 50,000 MAU free; Pro is $25 a month with 100,000 included.
  - WorkOS AuthKit: free up to 1,000,000 MAU, including email/password, social OAuth, MFA and passkeys.
  - Auth0: 25,000 MAU free, with MFA not included on the free plan.
  - — [devshot.co comparison](https://devshot.co/blog/authentication-pricing-compared); [buildmvpfast](https://www.buildmvpfast.com/blog/best-auth-providers-2026-clerk-supabase-comparison); [aibizhub](https://aibizhub.io/articles/clerk-vs-auth0-vs-supabase-auth-pricing-2026/); [publicapis.dev](https://publicapis.dev/blog/auth0-alternatives)
- **Sign in with Microsoft for university accounts:** new Entra app registrations are single-tenant by default and must be set to "Accounts in any organizational directory". "A tenant administrator can disable the ability for regular users to consent to applications. If this capability is disabled, admin consent is always required." Microsoft's own M365 Education tenant guidance recommends that admins "disable user consent". Admin consent is per tenant, with no bulk mechanism. — [MS Learn: convert app to multitenant](https://learn.microsoft.com/en-us/entra/identity-platform/howto-convert-app-to-be-multi-tenant); [MS Learn: consent types](https://learn.microsoft.com/en-us/entra/identity-platform/consent-types-developer); [MS Learn: M365 Education tenant design](https://learn.microsoft.com/en-us/microsoft-365/education/guide/1-reference/design-tenant-configurations); [MS Q&A: bulk admin consent](https://learn.microsoft.com/en-us/answers/questions/2235966/admin-consent-to-enterprise-app-for-multiple-tenan)

### Inferences
- **Option A: emailed redeem code or licence key (no login).** After a credit-pack purchase (Stripe webhook), generate a random code, store a hash of it in SQLite with its remaining uses, and email it and show it on the success page. The student pastes the code to spend a credit.
  - Effort: about a day.
  - Pros: no accounts or passwords, and the only extra data is the email Stripe already holds.
  - Cons: codes can be shared (acceptable or limitable by device or rate), lost codes need a "resend my codes to my email" flow, and it is a bearer token.
- **Option B: passwordless email (magic link or 6-digit OTP), recommended if a "login" is wanted.** Use a `users(email, credits)` table and a short-lived single-use token table, send through Resend or Postmark, and keep a signed session cookie (Starlette `SessionMiddleware` or itsdangerous). Pre-fill from the Stripe Checkout email and auto-credit on the `checkout.session.completed` webhook.
  - Effort: about 1 to 3 days hand-rolled. The free email tier covers expected volume.
  - Pros: no password storage, one identity across devices, and verified email.
  - Cons: depends on email deliverability. Uni mail filters may delay links, so a 6-digit OTP is more robust than a link (link scanners can consume single-use links).
- **Option C: Sign in with Google (and optionally Apple) via Authlib.** This is a few hours of work on top of B. Personal Gmail is near-universal among students.
- **Option D: Microsoft sign-in.** Personal Microsoft accounts work. University work or school accounts will often hit "Need admin approval" because education tenants are advised to disable user consent. That would put a confusing wall in front of exactly the users it targets, so it is not recommended as the main method.
- **Option E: hosted provider (Clerk, Supabase, WorkOS, Auth0).** The free tiers dwarf Aforecite's scale. These are mostly JS-first, though FastAPI can verify their JWTs. They add a US-hosted sub-processor (relevant to APP 8 cross-border disclosure if the business is ever covered) and vendor lock-in. Mostly overkill compared with B.
- **fastapi-users:** a FastAPI library supporting SQLAlchemy and SQLite, with password and OAuth backends. It is not verified in this session; see Gaps.
- **Stripe Customer Portal:** useful as a receipts and payment-methods page, with Stripe's email OTP serving as "login". It does not natively display a custom credit balance, and it centres on subscriptions. A pass could be a Stripe subscription or a one-off "time-limited" product. Do not treat the portal as the balance store.
- **Passkeys:** high friction to explain to students for an occasional A$4 tool. WorkOS bundles them for free if wanted later.
- **Stripe Link:** it saves the buyer's card across Stripe merchants and speeds up checkout. It is not a merchant-side identity or balance mechanism (unverified this session).

### Gaps
- No current fastapi-users, Authlib or Postmark pricing or maintenance status was retrieved. Postmark's free tier (historically about 100 emails a month) was not verified.
- Stripe "billing credits" and customer credit balance features, and Checkout's `customer_creation` parameter, were not retrieved. These could store a balance on the Stripe Customer object.
- Whether Square (the other payment rail) offers an equivalent customer-login portal was not researched.

## 3. Abuse: does a login cut free-preview abuse compared with cookie and IP limits?

### Takeaway
Only modestly. An email-verified login raises the cost of abuse a little (a new inbox per free preview), but disposable and alias emails make it cheap to get around. Google sign-in is a stronger speed bump because each Google account carries its own anti-abuse checks. No sourced quantitative evidence was found. Because the free preview only reveals the first 3 corrections and the paid output is the tracked-changes file, the value an abuser can extract is already capped. That matters more than identity checks.

### Cited Findings
- Even without abuse intent, 45% of repeat customers in the $300m-button study held multiple accounts. Account systems do not naturally enforce one person, one identity. — [Boing Boing](https://boingboing.net/2011/08/05/300-million-button-making-customers-create-logins-to-buy-cost-etailer-300myear.html)
- The Aforecite context (cookie limits plus a salted, daily-rotated IP hash) is supplied by the brief. No external source was found comparing these with login-based limits.

### Inferences
- If abuse becomes material, options in rising order of friction:
  - a lightweight bot challenge (eg Cloudflare Turnstile) on upload
  - a document fingerprint (hash of normalised footnote text) so the same essay cannot get repeat free previews under new cookies or IPs
  - requiring a verified email or Google sign-in only for the free preview, not for buying
- Requiring a login before the free preview would convert the preview into a sign-up wall (see section 1). That likely costs more paying conversions than it saves in abuse at a A$4 price point.
- Collecting emails purely for abuse control creates personal information. It should be kept minimal (or hashed) and covered in the privacy notice.

### Gaps
- No sourced data on trial abuse rates, disposable-email share, or the effect of Google sign-in versus email verification on multi-accounting. The search returned nothing on this.

## 4. Australian legal obligations once accounts and emails are held (status as of late 2026)

### Takeaway
A sole trader with turnover of A$3m or less is generally exempt from the Privacy Act 1988 (s 6D small business exemption), unless an exception applies. Holding logins and emails does not by itself trigger an exception. The exemption has NOT been removed: the August 2026 tranche 2 exposure draft leaves it in place, and its removal is agreed "in principle" only. Even an exempt business is still subject to:
- the Spam Act 2003 for any commercial email
- the Australian Consumer Law for credit or pass terms
- the statutory privacy tort that commenced on 10 June 2025

Opting in voluntarily, or simply following the APPs as best practice, is advisable because student essays and emails are personal information.

### Cited Findings
**Privacy Act coverage and the small business exemption**
- A business with annual turnover of A$3,000,000 or less in a financial year is a small business and generally exempt, unless an exception applies. A new business must project its full-year turnover.
  - Exceptions found include: providing a health service and holding health information; trading in personal information for a benefit, service or advantage; and protected action ballot agents. The search did not give the full s 6D list.
  - A small business can opt in, becoming subject to the whole Act, and can later opt out.
  - — [OAIC small business FAQ](https://oaic.gov.au/agencies-and-organisations/faqs-for-agencies-orgs/businesses/small-business); [OAIC opting in](https://www.oaic.gov.au/privacy/privacy-guidance-for-organisations-and-government-agencies/organisations/opting-in-to-the-privacy-act); [HWL Ebsworth](https://hwlebsworth.com.au/privacy-for-small-businesses/)
- From 1 July 2026, AML/CTF reforms made lawyers, accountants, real estate professionals and others reporting entities. These are covered by the Privacy Act for AML-related data even if under A$3m. This is not relevant to Aforecite unless it provides designated services. — [4it](https://4it.com.au/compliance/privacy-act-small-business-exemption-2026/); [CoterieLabs](https://coterielabs.com.au/field-notes/privacy-act-small-business-exemption-not-removed-2026)

**Tranche 2 (proposed, not law)**
- The Privacy Amendment (Personal Data Protection) Bill 2026 exposure draft was released for consultation on 31 August 2026, with submissions closing on 18 September 2026. AGD says it remains "subject to further consideration by government". It does not remove the small business exemption. The government agrees in principle to remove it only after further consultation and support for small businesses. Sources conflict on when a Bill will be introduced; none has been introduced and no commencement date is set. — [Clayton Utz](https://www.claytonutz.com/insights/2026/august/the-next-wave-of-australian-privacy-reform-key-proposals-in-the-draft-personal-data-protection-bill-2026); [CoterieLabs](https://coterielabs.com.au/field-notes/privacy-act-small-business-exemption-not-removed-2026); [compliancekit](https://compliancekit.co/blog/oaic-small-business-exemption-removed); [HSF Kramer (title/snippet only)](https://www.hsfkramer.com/insights/2026-09/the-draft-tranche-2-privacy-act-reforms-whats-there-whats-new-and-whats-missing)
- Draft contents:
  - APPs 3, 4 and 6 replaced by a single "fair and reasonable" test for collection, use and disclosure
  - a simplified direct marketing regime replacing APP 7
  - personal information expanded to cover technical identifiers and adtech data
  - a controller/processor framework
  - consent required to collect sensitive information or trade personal information
  - a limited destruction right against large platforms
  - The draft's commencement table is blank.
  - — [Landers](https://landers.com.au/legal-insights-news/australias-next-wave-of-privacy-reform-key-changes-proposed-in-the-privacy-amendment-personal-data-protection-bill-2026); [JWS](https://jws.com.au/what-we-think/second-tranche-of-australian-privacy-act-reform-exposure-draft-legislation-key-proposals-and-practical-implications/); [Dentons](https://www.dentons.com/en/insights/articles/2026/september/3/privacy-reform-take-two-a-substantial-rewrite-of-australias-privacy-act); [Baker McKenzie](https://www.bakermckenzie.com/en/insight/publications/2026/09/australia-privacy-reform-a-significant-expansion-of-privacy-framework)

**Privacy and Other Legislation Amendment Act 2024 (law)**
- **Statutory tort:** commenced on 10 June 2025. It covers intrusion upon seclusion and misuse of information, where the invasion was intentional or reckless, serious, and breached a reasonable expectation of privacy. It is enforced through the courts (not the OAIC), with damages up to A$478,550, and first claims have been filed. — [NatLawReview](https://natlawreview.com/article/new-serious-invasion-privacy-tort-australia-privacy-comes-effect); [LK Law](https://www.lk.law/2025/12/privacy-in-the-courts-privacy-litigation-and-enforcement-ramps-up/); [Corrs](https://www.corrs.com.au/insights/australias-ongoing-privacy-reforms-bolstering-australias-privacy-regulatory-framework)
- **Automated decision-making transparency in APP 1 privacy policies:** due 10 December 2026 (one source says 11 December). It applies to APP entities only. — [Compliance Council](https://compliancecouncil.com.au/insights/automated-decision-making-privacy-policy-10-december-2026/); [RecordingLaw](https://www.recordinglaw.com/world-laws/world-data-privacy-laws/australia-data-privacy-laws/privacy-act-reforms-2024-2025/)
- **Children's Online Privacy Code:** the OAIC must register it by 10 December 2026. It was reportedly still not registered as of late September 2026, with its commencement date not fixed. — [Helios Salinger](https://www.heliossalinger.com.au/privacy-reforms/); [GRM Law](https://grmlaw.com.au/articles/privacy-act-reforms-2026-boards/)

**Notifiable Data Breaches (NDB) scheme**
- It applies to APP entities where a breach is likely to result in serious harm. Exempt small businesses are therefore outside it unless covered or opted in. This was confirmed only via a practitioner source; check against Part IIIC. — [Sprintlaw](https://sprintlaw.com.au/articles/email-marketing-in-australia-essential-legal-compliance-guide/)

**Spam Act 2003 (applies regardless of turnover)**
- Commercial emails need consent (express or inferred), sender identification, and a functional unsubscribe that is honoured within 5 working days. The sender bears the burden of proving consent (s 16(5)). ACMA says consent should not be inferred from one-off purchases, or where the message is unrelated to the relationship. Transactional emails (login codes, receipts, balance notices) are not marketing. — [Sprintlaw](https://sprintlaw.com.au/articles/email-marketing-in-australia-essential-legal-compliance-guide/); [Addisons](https://addisons.com/article/the-acma-has-issued-a-statement-about-its-expectations-for-using-consent-to-conduct-e-marketing-and-telemarketing/); [Corrs on ACMA enforcement](https://www.corrs.com.au/insights/acma-spam-act-enforcement-and-the-implications-for-business); [Artificer Legal](https://artificer.legal/unsolicited-email-compliance-australia)

### Inferences
- **Aforecite's likely status:** exempt from the Privacy Act and NDB while turnover is at most A$3m and it does not "trade" in personal information. Using Stripe, Square or Resend as processors is not trading; selling or sharing email lists for benefit would be. The exemption's removal is a live policy direction, so building to APP standards now avoids rework.
- **Student essays are personal information:** a law essay normally contains the student's name and student number, and is "information or an opinion about an identified individual". Accounts make it easier to link stored files to a person. The current 24-hour deletion should be kept, and accounts should store only email, balance and transaction references, never essay content.
- **Statutory tort:** it is not limited to APP entities (no small-business carve-out was found). A breach exposing students' essays plus identities through reckless security could in theory found a claim, though the "serious" and "intentional or reckless" thresholds are high. Note this is inference; the tort's exact defendant exemptions were not verified.
- **Children:** most users are adults, but some law students (for example first-year combined degrees) may be 17. The Children's Online Privacy Code would apply to APP entities providing online services "likely to be accessed by children". As an exempt business it would not bind Aforecite unless it opts in. Its content is not final.
- **Spam Act in practice:** send marketing only with an opt-in tick box at sign-up or purchase (express consent). Put an unsubscribe link in every marketing email, and do not require login to unsubscribe. Balance-remaining reminders that are purely factual are arguably transactional, but adding promotions makes them commercial.
- **Australian Consumer Law for credits and passes:** state the number of uses, what counts as a use (eg per document, re-runs of the same document), any expiry, and the refund position clearly up front. Avoid terms letting the business unilaterally cancel credits, which risks being unfair contract terms in standard-form consumer contracts (penalties apply since Nov 2023). Consumer guarantees (service rendered with due care and skill, fit for purpose) cannot be excluded. Unverified this session; see Gaps.

### Gaps
- The full s 6D(4) list of small-business exception categories was not retrieved from the primary text.
- The NDB scheme's applicability to exempt businesses was confirmed only by a practitioner source.
- No sources were retrieved for the ACL (unfair contract terms penalties from 9 Nov 2023, gift-card expiry rules, refunds on unused credits). Whether ACL gift card rules (3-year minimum expiry) could apply to credit packs sold or used as gifts is unverified.
- The exact statutory tort exemptions and defences, and whether the Children's Online Privacy Code was registered by 10 Dec 2026, could not be confirmed (it is future-dated relative to some sources).
- No primary AGD or OAIC pages could be fetched. Dates rely on law-firm commentary.

## 5. Security burden: passwords vs passwordless, and the minimum responsible setup

### Takeaway
Passwordless (email OTP or magic link, optionally plus Google OAuth) avoids the biggest risks of a solo-run account system: storing password hashes and handling credential stuffing and resets. The account then becomes only as secure as the user's email. For a balance worth a few dollars and no stored essays, that is proportionate. Passwords also cost conversion among existing users: Baymard found up to 19% abandonment from strict password rules.

### Cited Findings
- Strict password rules caused up to 19% checkout abandonment among existing account users in Baymard testing. — [Baymard](https://baymard.com/blog/current-state-of-checkout-ux)
- 45% of repeat users held multiple accounts due to forgotten passwords or lost email. Password-based identity is fragile. — [Boing Boing](https://boingboing.net/2011/08/05/300-million-button-making-customers-create-logins-to-buy-cost-etailer-300myear.html)
- The NDB scheme (if covered) applies to breaches "likely to result in serious harm", eg unauthorised access to a mailing list combined with other identifying data. — [Sprintlaw](https://sprintlaw.com.au/articles/email-marketing-in-australia-essential-legal-compliance-guide/)

### Inferences
Minimum responsible setup for Aforecite if accounts are added:
- **No passwords.** Use 6-digit email OTPs (10-minute expiry, single use, stored hashed, max ~5 attempts) and/or magic links. Rate-limit code requests per email and per IP hash.
- **Sessions:** signed, HttpOnly, Secure, SameSite=Lax cookies, rotated at login. Give the user a "log out everywhere" option by storing a session version in SQLite.
- **Data minimisation:** store email, credit balance, a ledger of credit grants and spends (with Stripe or Square IDs), created and last-login dates, and a marketing opt-in flag with timestamp. Store no essay content beyond the 24-hour job store, and no card data (Stripe and Square hold it).
- **Webhook integrity:** verify Stripe and Square webhook signatures, and credit balances idempotently using event IDs.
- **Homelab hygiene:** encrypted backups of SQLite, disk encryption, TLS, OS patching, no admin panel exposed publicly, and logs that avoid emails and essay text.
- **Breach readiness:** a one-page response plan (contain, assess serious harm, notify users voluntarily). This is good practice even when the NDB scheme does not strictly apply.
- **Account deletion:** a self-serve delete or "forget me" flow, and a privacy policy listing sub-processors (Stripe, Square, email provider) and overseas locations.
- **If passwords were ever used:** a modern memory-hard hash (Argon2id), breached-password checks and MFA. These add ongoing burden, which supports going passwordless. (Specific OWASP parameters were not verified this session.)

### Gaps
- OWASP Password Storage and Authentication cheat-sheet specifics (Argon2id parameters), and guidance on magic-link security pitfalls (email link scanners consuming tokens), were not retrieved this session.
- No data on account-takeover rates for small SaaS.

## 6. What comparable student and AI tools do

### Takeaway
The single-task file tools closest to Aforecite's model (remove.bg, iLovePDF, Smallpdf, QuillBot's basic paraphraser) let users try without an account within tight free limits, then push accounts or subscriptions for more. Credit packs (remove.bg-style "credits") are typically tied to an account. Evidence came only from listicles, so first-hand checks of each site's current flow are needed.

### Cited Findings
- QuillBot: the paraphraser is usable as a guest, limited to 125 words per paraphrase. — [topaifinder](https://topaifinder.com/free-ai-tools-without-login/)
- remove.bg: basic background removal works without login, at limited free resolution. — [awesome-no-signup-tools (GitHub)](https://github.com/techwork168/awesome-no-signup-tools); [creativetoolsai](https://www.creativetoolsai.com/free-ai-tools-without-signup/)
- Smallpdf: occasional use without sign-up, with limited free conversions. iLovePDF: usable "a few times per day without an account". — [creativetoolsai](https://www.creativetoolsai.com/free-ai-tools-without-signup/); [thefreeaitools](https://www.thefreeaitools.com/)
- These sources caution that "limits and policies on these tools change often". — same as above

### Inferences
- The common pattern is: anonymous free use (rate-limited by cookie or IP), then an account wall for higher limits, saved history or credit balances, then subscriptions. Aforecite's guest preview and guest A$4 purchase is more permissive than most at the purchase step, which is a competitive advantage for one-off buyers.
- Recommended hybrid for Aforecite:
  - keep the guest single purchase as is
  - offer credit packs or passes with identity created at or after Stripe Checkout, using the Checkout email plus email-OTP sign-in (and optionally Google)
  - email a backup redeem code
  - never require login for the free preview
  - add an optional marketing opt-in tick box

### Gaps
- Scribbr (citation checker, plagiarism checker and proofreading purchase flow; reportedly sells per-document checks) and Grammarly sign-up requirements were not returned by search and remain unverified.
- remove.bg credit pack or pay-as-you-go account requirements, and whether any comparable tool sells credits without an account, are unverified.
- No Australian-specific comparable (eg AGLC tools) was researched.
