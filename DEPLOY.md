# Deploying the paid site (homelab)

What the homelab needs before `AGLC_PAYMENTS=square` (or `stripe`, see 3a) is switched on. Local use needs none
of this. GitHub Actions deploys every push to `main` over SSH (`.github/workflows/deploy.yml`
runs `deploy <sha>` on `deployer@legal-citation.home`); the server-side `deploy` script is
not in this repository, so the checklist below says what it must do.

## 1. Data directory outside the release folder

`AGLC_DATA_DIR` holds the SQLite database (`aglc.db`: documents, orders, webhook events)
and the kept documents (`sessions/`). It must survive a redeploy, so it can't live in the
checked-out release:

```bash
sudo install -d -o aglc -g aglc -m 700 /var/lib/aglc
```

```ini
# /etc/aglc/env  (mode 600, owned by the service user; never in the repo)
AGLC_DATA_DIR=/var/lib/aglc
AGLC_PAYMENTS=square
AGLC_PUBLIC_URL=https://<your domain>
AGLC_CLIENT_IP_HEADER=CF-Connecting-IP
AGLC_LLM=openrouter:@preset/aglc
# AGLC_LLM_FALLBACK=openrouter:<model>   # once the reliability branch is merged
OPENROUTER_API_KEY=sk-or-...
SQUARE_ENVIRONMENT=production
SQUARE_ACCESS_TOKEN=...
SQUARE_LOCATION_ID=...
SQUARE_WEBHOOK_SIGNATURE_KEY=...
SQUARE_WEBHOOK_URL=https://<your domain>/api/webhooks/square
# AGLC_RETENTION_HOURS=24   # quoted by /api/config for the privacy page
# AGLC_MAX_UPLOAD_MB=10
```

OpenRouter chooses the model from **Settings > Presets**, preset slug `aglc`. Change the model
there to switch models; no code change or redeploy is needed.

If the data directory is lost, paid documents are gone (their payments are refunded when
someone asks for them) and the webhook replay log is lost, so back it up (next section).

## 2. Nightly SQLite backup

Copy the database with SQLite's online backup, never `cp` (the database is in WAL mode, and
a plain copy taken mid-write can be corrupt):

```bash
# /etc/cron.d/aglc-backup
15 3 * * * aglc sqlite3 /var/lib/aglc/aglc.db ".backup '/var/backups/aglc/aglc-$(date +\%F).db'" && find /var/backups/aglc -name 'aglc-*.db' -mtime +30 -delete
```

Back up the database only, not `sessions/`: documents are deleted after
`AGLC_RETENTION_HOURS` anyway, and copying them into backups would keep students' work
longer than the privacy page says. Check a restore once (`sqlite3 <backup> 'PRAGMA integrity_check'`).

## 3. Cloudflare Tunnel

- Run `aglc serve` bound to `127.0.0.1` (the default) so that `cloudflared` is the only way
  in. The per-IP free limit trusts `CF-Connecting-IP`; if the port were reachable directly,
  anyone could send that header and pick their own address.
- uvicorn trusts `X-Forwarded-For`/`X-Forwarded-Proto` only from `127.0.0.1` by default
  (`aglc serve` runs it with proxy headers on). If `cloudflared` runs in another container
  or host, set `FORWARDED_ALLOW_IPS=<its address>`, not `*`.
- **`/api/webhooks/*` must not be behind Cloudflare Access** (or a WAF challenge, Bot Fight
  Mode or a "Under Attack" rule): Square can't log in or solve a challenge, and every
  payment would then only be picked up by the late-webhook reconcile when the customer's
  page polls. Add an Access bypass (or no Access application) for that path. If the rest
  of the site is behind Access during a soft launch, the public page must not be.
- Register the webhook in the Square Developer Dashboard at exactly
  `SQUARE_WEBHOOK_URL` (scheme, host, path, no trailing slash): the signature covers that
  URL byte for byte. Subscribe to `payment.created`, `payment.updated`, `refund.updated`.
- Cloudflare limits request bodies to 100 MB on the free plan; the app itself refuses
  bodies over `AGLC_MAX_UPLOAD_MB` (10) with 413.

## 3a. Stripe instead of Square

`AGLC_PAYMENTS=stripe` switches the whole site to Stripe Checkout; nothing else changes.
Install the extra (`uv sync --frozen --extra stripe ...`, or `--all-extras`) and set, in
`/etc/aglc/env` in place of the `SQUARE_*` lines:

```ini
AGLC_PAYMENTS=stripe
STRIPE_SECRET_KEY=sk_live_...        # sk_test_... while testing
STRIPE_WEBHOOK_SECRET=whsec_...      # the endpoint's signing secret
```

- **Webhook endpoint:** in the Stripe Dashboard (Developers > Webhooks) add
  `https://<domain>/api/webhooks/stripe` and subscribe it to `checkout.session.completed`,
  `checkout.session.async_payment_succeeded`, `checkout.session.expired` and
  `charge.refunded`. The same Cloudflare rule applies as in section 3: no Access or
  challenge on `/api/webhooks/*`. Unlike Square, the signature doesn't cover the URL, so
  there is no `*_WEBHOOK_URL` setting.
- **Testing locally:** `stripe listen --forward-to localhost:8766/api/webhooks/stripe`
  prints a `whsec_...` secret for that session; use it as `STRIPE_WEBHOOK_SECRET` with a
  `sk_test_...` key, then pay with test card `4242 4242 4242 4242` (any future expiry, any CVC).
- **Statement descriptor:** Dashboard > Settings > Public details > set the statement
  descriptor to `AFORECITE`, so the charge is recognisable on a card statement.
- **Wallets and methods:** Apple Pay and Google Pay come with Checkout; manage other
  methods in Dashboard > Settings > Payment methods.
- **Fees:** 1.65% + 30c per domestic card payment (check the current rate in the
  Dashboard). A refund doesn't return the fee.
- **Checkouts last an hour.** A document's pending checkout is reused for 55 minutes, then
  a new one is made when the customer clicks Unlock again. A refund made in the Dashboard
  locks the document again only when it is a full refund.

## 4. OpenRouter spend limit

Free previews cost real model calls. Create a key just for the site and set a credit limit
on it at openrouter.ai/keys (eg a little above `AGLC_FREE_GLOBAL_PER_DAY` × the cost of a
long essay × a few days). With payments on, the client can't choose the model (the server
uses `AGLC_LLM` only), so the limit maps directly to the configured model's price.

The privacy page says footnotes only go to hosts that don't store or train on requests.
The app enforces that with OpenRouter's `data_collection: "deny"` routing
(`AGLC_OPENROUTER_DATA_COLLECTION`, default `deny`; never set it to `allow` in production
without changing the page). Also keep **prompt logging off** in the OpenRouter account's
privacy settings. If OpenRouter ever has no such host for the model, requests fail with a
"No endpoints" error instead of falling back: switch `AGLC_LLM` to a model that has one.

## 4a. Who runs the site (the legal pages)

The Privacy, Terms, Refunds and About pages and the footer read these from the environment;
any that's unset shows on the page as a visible TODO:

```bash
AGLC_OWNER_NAME="Your Name"            # or your business name
AGLC_CONTACT_EMAIL=hello@example.com    # shown as a mailto link
AGLC_ABN="12 345 678 901"
AGLC_STATE="New South Wales"            # whose law governs the terms
AGLC_OWNER_ABOUT="..."                # optional; nothing shows on the About page when unset
AGLC_LOG_RETENTION_DAYS=14              # and configure journald/your proxy to match
AGLC_GST_REGISTERED=false               # true once registered: the price then "includes GST"
```

Update `POLICY_DATE` in `aglc/site.py` whenever you change those pages.

## 5. The deploy script and workflow

The workflow tests with `uv sync --all-extras` and then runs the server-side `deploy` script.
For payments, that script must:

- install the provider's extra: `uv sync --frozen --extra square --extra openai` (or
  `--extra stripe`, or `--all-extras`); without it checkout fails with "The Square SDK is not
  installed" (or the Stripe equivalent);
- load `/etc/aglc/env` into the service (eg systemd `EnvironmentFile=/etc/aglc/env`), not a
  `.env` in the release folder;
- restart the service, then check `GET /api/config` returns `"payments": true`;
- run as a dedicated `aglc` user that owns `AGLC_DATA_DIR` and nothing in the release.

Nothing in `deploy.yml` itself needs to change: secrets stay on the homelab, and the
deploy job only runs for pushes to `main`. Migrations run automatically when the server
first opens the database (`aglc/store.py`), so a deploy needs no separate step; take the
nightly backup (or a manual `.backup`) before deploying a release that adds one.

## 5a. Live progress (one server process)

The page sends `progress=true` with each upload: `/api/process` answers at once (202) and the page
polls `GET /api/progress/{id}` every 0.7s for the footnotes read so far, then the result. Each poll
is short, so Cloudflare's 100-second limit on a request that sends nothing back (error 524) no
longer applies to long documents. The progress is held in memory, so run **one** uvicorn worker
(`aglc serve` does); with several, a poll can land on a worker that doesn't know the document.
Model time is bounded by `AGLC_REQUEST_DEADLINE` (per request, default 90s) and
`AGLC_DOCUMENT_DEADLINE` (per document, default 300s).

## 6. Logs

- uvicorn's access log keeps only the first 8 characters of session ids (`aglc/guards.py`),
  since a session id unlocks a paid document. It still records client IP addresses:
  keep journald retention short (eg `MaxRetentionSec=14day`) and say so on the privacy page.
- Make the journal persistent, or a reboot empties it: in `/etc/systemd/journald.conf` set
  ```ini
  [Journal]
  Storage=persistent
  MaxRetentionSec=14day
  ```
  then `sudo systemctl restart systemd-journald`. Match `MaxRetentionSec` to
  `AGLC_LOG_RETENTION_DAYS` (§4a).
- Read the service's log with `journalctl -u <unit>` (the name of the systemd unit that runs
  uvicorn), eg `journalctl -u aglc --since "2 days ago"`, or `-f` to follow it live. Each
  document leaves one summary line:
  `formatted session 1a2b3c4d with openrouter:<model>: 32 footnotes, 20 changed, 0 extraction
  failures, 3 body fixes; 5 warnings (could not resolve 2, has no pinpoint 3); 41.2s`.
  The 8 characters are the start of the session id, which is also the name of the session's
  folder (in `aglc_sessions` in the temp dir, under `/tmp/systemd-private-*` if the unit sets
  `PrivateTmp=yes`; or `$AGLC_DATA_DIR/sessions` with payments on). Until the retention sweep
  deletes it, that folder holds the input and output documents, `result.json` (what the page
  was sent), `extraction.json` (the model's structured answer, before normalising) and
  `options.json`.
- Footnote text, filenames and payment ids are not logged at info level. Errors are logged
  with tracebacks server-side; clients get a generic message.

## 7. Before launch

- `AGLC_PAYMENTS=fake` must never be used on the public site: its checkout page marks
  anything paid.
- Do one Square **sandbox** run end to end (pay, late webhook, refund from the dashboard)
  with the real tunnel before switching `SQUARE_ENVIRONMENT=production`.
- Turn on Apple Pay and Google Pay in Square Dashboard > Payment links > Settings.
- For Stripe: do one **test-mode** run end to end (`stripe listen`, pay with the 4242 card,
  refund from the Dashboard) before switching to the live keys, and register the live webhook
  endpoint separately: test and live have different signing secrets.
