"""The public web pages: the tool's landing page and the static policy pages.

Pages live in web/ and use a few placeholders, filled in here so the brand name, price
and analytics are set in one place:

    {{brand}}         BRAND below (a placeholder until the name is chosen)
    {{price}}         the server's price, eg "A$4" (billing.PRODUCTS)
    {{preview_full}}  changed footnotes shown free before paying
    {{base_url}}      $AGLC_PUBLIC_URL or the request's own origin (for Open Graph URLs)
    {{analytics}}     the Plausible script, only when $AGLC_PLAUSIBLE_DOMAIN is set
    {{retention_hours}} how long documents are kept: $AGLC_RETENTION_HOURS (aglc/retention.py)
    {{policy_date}}   POLICY_DATE below: when the policy pages last changed
    {{owner}} {{abn}} {{state}} {{contact}} {{owner_about}} {{log_retention}}
                      who runs the site, from $AGLC_OWNER_NAME, $AGLC_ABN, $AGLC_STATE,
                      $AGLC_CONTACT_EMAIL (shown as a mailto link), $AGLC_OWNER_ABOUT and
                      $AGLC_LOG_RETENTION_DAYS; an unset one shows as a visible TODO
    {{gst_note}}      from $AGLC_GST_REGISTERED (default: not registered)
    {{analytics_note}} whether analytics is on ($AGLC_PLAUSIBLE_DOMAIN)
    {{payment_provider}} "Stripe" when $AGLC_PAYMENTS=stripe, otherwise "Square"
    {{> name}}        web/partials/<name>.html
"""

from __future__ import annotations

import os
import re
from html import escape
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from . import billing, retention

#: The product's name ("aforecited": cited above, which is what Ibid and (n x) do). Set here only.
BRAND = "Aforecite"

#: When the policy pages (privacy, terms, refunds) last changed: update it with them.
POLICY_DATE = "18 October 2026"

#: Who runs the site: placeholder -> (environment variable, what to set)
OWNER_SETTINGS = {
    "owner": ("AGLC_OWNER_NAME", "your name or business name"),
    "abn": ("AGLC_ABN", "your ABN"),
    "state": ("AGLC_STATE", "the state or territory whose law applies, eg New South Wales"),
    "owner_about": ("AGLC_OWNER_ABOUT", "a sentence or two about who you are and why you built this"),
}

WEB_DIR = Path(__file__).parent.parent / "web"
SAMPLE_ESSAY = Path(__file__).parent.parent / "examples" / "test_essay.docx"

#: Static pages: route -> (file in web/pages, <title>, meta description)
PAGES: dict[str, tuple[str, str, str]] = {
    "privacy": ("privacy.html", "Privacy", "What happens to your essay and your footnotes, and what is kept."),
    "terms": ("terms.html", "Terms", "The terms for using the AGLC4 citation checker."),
    "refunds": ("refunds.html", "Refunds", "When you're not asked to pay, and how to get a refund."),
    "about": ("about.html", "About", "Who makes the AGLC4 citation checker and how it works."),
}

_PARTIAL = re.compile(r"\{\{>\s*([a-z_-]+)\s*\}\}")


def base_url(request: Request) -> str:
    return (os.environ.get("AGLC_PUBLIC_URL") or str(request.base_url)).rstrip("/")


def analytics_tag() -> str:
    """Plausible (cookieless), off unless $AGLC_PLAUSIBLE_DOMAIN is set."""
    domain = (os.environ.get("AGLC_PLAUSIBLE_DOMAIN") or "").strip()
    if not domain:
        return ""
    return f'<script defer data-domain="{escape(domain)}" src="https://plausible.io/js/script.js"></script>'


def _todo(var: str, what: str) -> str:
    return f'<span class="todo">[TODO: set {var} to {escape(what)}]</span>'


def _setting(var: str, what: str) -> str:
    value = (os.environ.get(var) or "").strip()
    return escape(value) if value else _todo(var, what)


def contact_link() -> str:
    email = (os.environ.get("AGLC_CONTACT_EMAIL") or "").strip()
    if not email:
        return _todo("AGLC_CONTACT_EMAIL", "the email address people should write to")
    return f'<a href="mailto:{escape(email)}">{escape(email)}</a>'


def gst_note() -> str:
    if (os.environ.get("AGLC_GST_REGISTERED") or "").strip().lower() in ("1", "true", "yes"):
        return "The price includes GST."
    return "We aren't registered for GST, so no GST is charged."


def analytics_note() -> str:
    if (os.environ.get("AGLC_PLAUSIBLE_DOMAIN") or "").strip():
        return "Analytics is on: we use Plausible, which counts page views without cookies and without personal data."
    return "We don't use analytics or tracking scripts."


def payment_provider() -> str:
    """The name of the payment provider the legal pages mention (Square unless $AGLC_PAYMENTS=stripe)."""
    return "Stripe" if (os.environ.get("AGLC_PAYMENTS") or "").strip().lower() == "stripe" else "Square"


def log_retention() -> str:
    days = (os.environ.get("AGLC_LOG_RETENTION_DAYS") or "").strip()
    if not days:
        return _todo("AGLC_LOG_RETENTION_DAYS", "how many days the server keeps its logs (and set the server to match)")
    return f"They are kept for {escape(days)} days and then deleted."


def _fill(html: str, request: Request, extra: dict[str, str] | None = None) -> str:
    html = _PARTIAL.sub(lambda m: _read(WEB_DIR / "partials" / f"{m[1]}.html"), html)
    values = {
        "brand": escape(BRAND),
        "price": escape(billing.PRODUCTS["document"].display),
        "preview_full": str(billing.PREVIEW_FULL),
        "base_url": escape(base_url(request)),
        "analytics": analytics_tag(),
        "retention_hours": f"{retention.retention_hours():g}",
        "policy_date": POLICY_DATE,
        **{key: _setting(var, what) for key, (var, what) in OWNER_SETTINGS.items()},
        "contact": contact_link(),
        "gst_note": gst_note(),
        "analytics_note": analytics_note(),
        "payment_provider": payment_provider(),
        "log_retention": log_retention(),
        **(extra or {}),
    }
    return re.sub(r"\{\{\s*([a-z_]+)\s*\}\}", lambda m: values.get(m[1], m[0]), html)


def _read(path: Path) -> str:
    if not path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return path.read_text(encoding="utf-8")


def index(request: Request) -> HTMLResponse:
    return HTMLResponse(_fill(_read(WEB_DIR / "index.html"), request))


def page(name: str, request: Request) -> HTMLResponse:
    file, title, description = PAGES[name]
    body = _read(WEB_DIR / "pages" / file)
    extra = {"title": escape(title), "description": escape(description), "content": body, "page": name}
    # The page body is filled first so its own placeholders ({{brand}}...) are filled too.
    return HTMLResponse(_fill(_fill(_read(WEB_DIR / "page.html"), request, extra), request))
