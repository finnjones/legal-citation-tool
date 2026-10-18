"""The public web pages: the tool's landing page and the static policy pages.

Pages live in web/ and use a few placeholders, filled in here so the brand name, price
and analytics are set in one place:

    {{brand}}         BRAND below (a placeholder until the name is chosen)
    {{price}}         the server's price, eg "A$4" (billing.PRODUCTS)
    {{preview_full}}  changed footnotes shown free before paying
    {{base_url}}      $AGLC_PUBLIC_URL or the request's own origin (for Open Graph URLs)
    {{analytics}}     the Plausible script, only when $AGLC_PLAUSIBLE_DOMAIN is set
    {{> name}}        web/partials/<name>.html
"""

from __future__ import annotations

import os
import re
from html import escape
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse

from . import billing

#: The product's name. A placeholder until one is chosen; swap it here only.
BRAND = "Wordmark"

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


def _fill(html: str, request: Request, extra: dict[str, str] | None = None) -> str:
    html = _PARTIAL.sub(lambda m: _read(WEB_DIR / "partials" / f"{m[1]}.html"), html)
    values = {
        "brand": escape(BRAND),
        "price": escape(billing.PRODUCTS["document"].display),
        "preview_full": str(billing.PREVIEW_FULL),
        "base_url": escape(base_url(request)),
        "analytics": analytics_tag(),
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
