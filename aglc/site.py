"""The public web pages: the tool's landing page and the static policy pages.

Pages live in web/ and use a few placeholders, filled in here so the brand name, price
and analytics are set in one place:

    {{brand}}         BRAND below (a placeholder until the name is chosen)
    {{price}}         the server's price, eg "A$4" (billing.PRODUCTS)
    {{preview_full}}  changed footnotes shown free before paying
    {{base_url}}      $AGLC_PUBLIC_URL or the request's own origin (for Open Graph URLs)
    {{analytics}}     the Plausible script, only when $AGLC_PLAUSIBLE_DOMAIN is set
    {{retention_hours}} how long documents are kept: $AGLC_RETENTION_HOURS (aglc/retention.py)
    {{report_days}}     how long problem reports are kept: $AGLC_REPORT_DAYS (aglc/reports.py)
    {{policy_date}}   POLICY_DATE below: when the policy pages last changed
    {{owner}} {{abn}} {{state}} {{contact}} {{owner_about}} {{log_retention}}
                      who runs the site, from $AGLC_OWNER_NAME, $AGLC_ABN, $AGLC_STATE,
                      $AGLC_CONTACT_EMAIL (shown as a mailto link) and $AGLC_LOG_RETENTION_DAYS;
                      an unset one shows as a visible TODO. $AGLC_OWNER_ABOUT is optional
                      (nothing shows when it's unset)
    {{gst_note}}      from $AGLC_GST_REGISTERED (default: not registered)
    {{analytics_note}} whether analytics is on ($AGLC_PLAUSIBLE_DOMAIN)
    {{payment_provider}} "Stripe" when $AGLC_PAYMENTS=stripe, otherwise "Square"
    {{rule_pages}}    index only: where each rule is in the AGLC4 PDF (aglc/guide_pdf.py)
    {{> name}}        web/partials/<name>.html

The AGLC4 guides (/guides and /guides/<slug>, GUIDES below) use web/guide.html with the
page body from web/pages/guides/<slug>.html, plus {{title}} {{description}} {{path}}
{{crumbs}} {{related}} {{guide_list}}. /sitemap.xml and /robots.txt are built here too.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html import escape
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from . import billing, guide_pdf, reports, retention

#: The product's name ("aforecited": cited above, which is what Ibid and (n x) do). Set here only.
BRAND = "Aforecite"

#: When the policy pages (privacy, terms, refunds) last changed: update it with them.
POLICY_DATE = "23 October 2026"

#: Who runs the site: placeholder -> (environment variable, what to set)
OWNER_SETTINGS = {
    "owner": ("AGLC_OWNER_NAME", "your name or business name"),
    "abn": ("AGLC_ABN", "your ABN"),
    "state": ("AGLC_STATE", "the state or territory whose law applies, eg New South Wales"),
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



@dataclass(frozen=True)
class Guide:
    """One AGLC4 guide page, served at /guides/<slug> from web/pages/guides/<slug>.html."""

    slug: str
    title: str  # the <title> and og:title, without the brand
    name: str  # the short name used in lists
    summary: str  # one line under the name in the index
    description: str  # the meta description


#: The guides, in the order they are listed. Every rule number and example on these pages
#: is grounded in the formatter code and tests/aglc4_examples (see the guides tests).
GUIDES: dict[str, Guide] = {g.slug: g for g in (
    Guide("ibid", "Ibid in AGLC4: when and how to use it", "Ibid",
          "When Ibid is allowed, how to write it, and when to use (n x) instead.",
          "When AGLC4 lets you use Ibid, how to write it with and without a pinpoint, and when you must use (n x) instead. Worked examples from the Guide."),
    Guide("subsequent-references", "AGLC4 subsequent references and (n x) explained", "Subsequent references and (n x)",
          "Short forms that point back to the first full citation, for books, articles, cases and Acts.",
          "How AGLC4 subsequent references work: the short form, (n x) and the pinpoint, for books, articles, cases and legislation. Worked examples from the Guide."),
    Guide("short-titles", "AGLC4 short titles: how to define and use them", "Short titles",
          "How to define a short title in the first footnote and use it afterwards.",
          "How to define a short title in AGLC4 and use it in later references, for cases, Acts, reports and articles. Worked examples from the Guide."),
    Guide("pinpoints", "AGLC4 pinpoint references: pages, paragraphs and sections", "Pinpoint references",
          "Pages, paragraphs, ranges and sections, for cases, legislation, books and articles.",
          "How to write pinpoint references in AGLC4: pages, paragraphs, ranges and sections, for cases, legislation, books and articles. Worked examples."),
    Guide("cases", "How to cite cases in AGLC4, with examples", "Citing cases",
          "Reported, medium neutral and unreported decisions, and how to write case names.",
          "How to cite reported, medium neutral and unreported cases in AGLC4, and how to write case names. Worked examples from the Guide."),
    Guide("legislation", "How to cite legislation in AGLC4, with examples", "Citing legislation",
          "Acts, Bills, regulations and constitutions, with pinpoints and short titles.",
          "How to cite Acts, Bills, regulations and constitutions in AGLC4, with pinpoints and short titles. Worked examples from the Guide."),
    Guide("articles-and-books", "AGLC4 journal article and book citations, with examples", "Journal articles and books",
          "Authors, titles, editions, publishers and pinpoints for articles, books and chapters.",
          "How to cite journal articles, books and book chapters in AGLC4: authors, titles, editions, publishers and pinpoints. Worked examples."),
    Guide("bibliography", "AGLC4 bibliography: layout, categories and examples", "The bibliography",
          "The five groups, inverted author names, no pinpoints and alphabetical order.",
          "How an AGLC4 bibliography is laid out: the five groups, inverted author names, no pinpoints and alphabetical order. Worked examples."),
)}

GUIDES_INDEX_TITLE = "AGLC4 guides: footnote rules with worked examples"
GUIDES_INDEX_DESCRIPTION = (
    "Short guides to the AGLC4 rules that trip up most footnotes: Ibid, (n x), short titles, "
    "pinpoints, cases, legislation, articles, books and the bibliography."
)

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


def owner_about() -> str:
    """Optional: a line about who runs the site. Nothing at all when unset."""
    return escape((os.environ.get("AGLC_OWNER_ABOUT") or "").strip())


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
        "report_days": f"{reports.report_days():g}",
        "policy_date": POLICY_DATE,
        **{key: _setting(var, what) for key, (var, what) in OWNER_SETTINGS.items()},
        "owner_about": owner_about(),
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
    return HTMLResponse(_fill(_read(WEB_DIR / "index.html"), request, {"rule_pages": guide_pdf.page_json()}))


def page(name: str, request: Request) -> HTMLResponse:
    file, title, description = PAGES[name]
    body = _read(WEB_DIR / "pages" / file)
    extra = {"title": escape(title), "description": escape(description), "content": body, "page": name}
    # The page body is filled first so its own placeholders ({{brand}}...) are filled too.
    return HTMLResponse(_fill(_fill(_read(WEB_DIR / "page.html"), request, extra), request))


# ---- Guides -------------------------------------------------------------------------- #


def _guide_list() -> str:
    items = "\n".join(
        f'                    <li><a href="/guides/{g.slug}"><span class="g-name">{escape(g.name)}</span>'
        f'<span class="g-sum">{escape(g.summary)}</span></a></li>'
        for g in GUIDES.values()
    )
    return f'                <ul class="g-index">\n{items}\n                </ul>'


def _related(current: str) -> str:
    links = "\n".join(
        f'                    <li><a href="/guides/{g.slug}">{escape(g.name)}</a></li>'
        for g in GUIDES.values() if g.slug != current
    )
    return (
        '                <h2>More AGLC4 guides</h2>\n'
        f'                <ul class="g-related">\n{links}\n                </ul>\n'
        '                <p><a href="/guides">All the guides</a></p>'
    )


def _guide_page(request: Request, *, file: str, title: str, description: str, path: str,
                crumbs: str, related: str) -> HTMLResponse:
    body = _read(WEB_DIR / "pages" / "guides" / file)
    extra = {
        "title": escape(title), "description": escape(description), "content": body, "path": path,
        "crumbs": crumbs, "related": related, "guide_list": _guide_list(),
    }
    # The body is filled first so its own placeholders ({{brand}}, {{guide_list}}...) are filled too.
    return HTMLResponse(_fill(_fill(_read(WEB_DIR / "guide.html"), request, extra), request, extra))


def guides_index(request: Request) -> HTMLResponse:
    return _guide_page(request, file="index.html", title=GUIDES_INDEX_TITLE, description=GUIDES_INDEX_DESCRIPTION,
                       path="/guides", crumbs="", related="")


def guide(slug: str, request: Request) -> HTMLResponse:
    """One guide; a slug that isn't in GUIDES is a 404."""
    entry = GUIDES.get(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="Page not found")
    crumbs = '                <p class="crumbs"><a href="/guides">AGLC4 guides</a></p>'
    return _guide_page(request, file=f"{slug}.html", title=entry.title, description=entry.description,
                       path=f"/guides/{slug}", crumbs=crumbs, related=_related(slug))


# ---- Sitemap and robots.txt ----------------------------------------------------------- #

#: The public pages, in sitemap order.
PUBLIC_PATHS = ["/", "/about", "/privacy", "/terms", "/refunds", "/guides", *(f"/guides/{slug}" for slug in GUIDES)]


def sitemap(request: Request) -> Response:
    base = base_url(request)
    urls = "\n".join(f"  <url><loc>{escape(base + path)}</loc></url>" for path in PUBLIC_PATHS)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )
    return Response(xml, media_type="application/xml")


def robots(request: Request) -> PlainTextResponse:
    """Everything is open to crawlers except the API, and the sitemap is named."""
    return PlainTextResponse(f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {base_url(request)}/sitemap.xml\n")
