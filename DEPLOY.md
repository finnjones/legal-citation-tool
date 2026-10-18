# Deploying the paid site (homelab)

What the homelab needs before `AGLC_PAYMENTS=square` is switched on. Local use needs none
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
AGLC_LLM=openrouter:<model>
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
AGLC_OWNER_ABOUT="A sentence or two about who you are and why you built it."
AGLC_LOG_RETENTION_DAYS=14              # and configure journald/your proxy to match
AGLC_GST_REGISTERED=false               # true once registered: the price then "includes GST"
```

Update `POLICY_DATE` in `aglc/site.py` whenever you change those pages.

## 5. The deploy script and workflow

The workflow tests with `uv sync --all-extras` and then runs the server-side `deploy` script.
For payments, that script must:

- install the Square extra: `uv sync --frozen --extra square --extra openai` (or
  `--all-extras`); without it checkout fails with "The Square SDK is not installed";
- load `/etc/aglc/env` into the service (eg systemd `EnvironmentFile=/etc/aglc/env`), not a
  `.env` in the release folder;
- restart the service, then check `GET /api/config` returns `"payments": true`;
- run as a dedicated `aglc` user that owns `AGLC_DATA_DIR` and nothing in the release.

Nothing in `deploy.yml` itself needs to change: secrets stay on the homelab, and the
deploy job only runs for pushes to `main`. Migrations run automatically when the server
first opens the database (`aglc/store.py`), so a deploy needs no separate step; take the
nightly backup (or a manual `.backup`) before deploying a release that adds one.

## 6. Logs

- uvicorn's access log keeps only the first 8 characters of session ids (`aglc/guards.py`),
  since a session id unlocks a paid document. It still records client IP addresses:
  keep journald retention short (eg `MaxRetentionSec=14day`) and say so on the privacy page.
- Footnote text, filenames and payment ids are not logged at info level. Errors are logged
  with tracebacks server-side; clients get a generic message.

## 7. Before launch

- `AGLC_PAYMENTS=fake` must never be used on the public site: its checkout page marks
  anything paid.
- Do one Square **sandbox** run end to end (pay, late webhook, refund from the dashboard)
  with the real tunnel before switching `SQUARE_ENVIRONMENT=production`.
- Turn on Apple Pay and Google Pay in Square Dashboard > Payment links > Settings.
