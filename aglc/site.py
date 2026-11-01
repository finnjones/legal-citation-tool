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
{{crumbs}} {{related}} {{guide_list}} {{updated}}. /sitemap.xml, /robots.txt and /llms.txt
are built here too.

Search and answer engines (see docs/seo-notes.md): every public page gets its canonical URL,
Open Graph and Twitter tags from web/partials/meta.html ({{canonical}} {{og_title}}
{{og_type}} {{description}}), and JSON-LD structured data in place of {{jsonld}}, built
after the page is filled so that its FAQPage is read from the questions actually on the page.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from . import billing, guards, guide_pdf, reports, retention

#: The product's name ("aforecited": cited above, which is what Ibid and (n x) do). Set here only.
BRAND = "Aforecite"

#: When the policy pages (privacy, terms, refunds) last changed: update it with them.
POLICY_DATE = "23 October 2026"

#: When the pages that aren't guides or policy pages last changed (ISO dates, for the
#: sitemap's <lastmod>): update each with its page.
PAGE_DATES = {"/": "2026-11-01", "/about": "2026-10-18", "/guides": "2026-11-01"}

#: What the tool is and isn't, in two sentences: the home page's structured data and llms.txt.
SITE_DESCRIPTION = (
    "Aforecite fixes the footnotes in an Australian law essay to the Australian Guide to Legal "
    "Citation (4th ed, AGLC4): upload a Word .docx and each citation it recognises is rewritten to "
    "AGLC4, with Ibid, (n x), short titles and an optional bibliography. Every change is listed for "
    "review before download and, by default, shown in the .docx as Word tracked changes."
)

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
    title: str  # the <title> and og:title, without the brand (at most 48 characters)
    name: str  # the short name used in lists
    summary: str  # one line under the name in the index, and in llms.txt
    description: str  # the meta description (at most 155 characters)
    updated: str  # ISO date the page last changed: the sitemap, the page and its JSON-LD


#: The guides, in the order they are listed. Every rule number and example on these pages
#: is grounded in the formatter code and the tests (see the guides tests in test_api.py):
#: examples marked "from the Guide" are its own (tests/aglc4_examples); the rest are ours,
#: checked against the formatters in tests/test_guide_examples.py.
GUIDES: dict[str, Guide] = {g.slug: g for g in (
    Guide("ibid", "Ibid in AGLC4: when and how to use it", "Ibid",
          "When Ibid is allowed, how to write it, and when to use (n x) instead.",
          "When AGLC4 lets you use Ibid, how to write it with and without a pinpoint, and when you must use (n x) instead. Worked examples from the Guide.",
          "2026-11-01"),
    Guide("subsequent-references", "AGLC4 subsequent references and (n x) explained", "Subsequent references and (n x)",
          "Short forms that point back to the first full citation, for books, articles, cases and Acts.",
          "How AGLC4 subsequent references work: the short form, (n x) and the pinpoint, for books, articles, cases and legislation. Worked examples from the Guide.",
          "2026-11-01"),
    Guide("short-titles", "AGLC4 short titles: how to define and use them", "Short titles",
          "How to define a short title in the first footnote and use it afterwards.",
          "How to define a short title in AGLC4 and use it in later references, for cases, Acts, reports and articles. Worked examples from the Guide.",
          "2026-11-01"),
    Guide("pinpoints", "AGLC4 pinpoints: pages, paragraphs and sections", "Pinpoint references",
          "Pages, paragraphs, ranges and sections, for cases, legislation, books and articles.",
          "How to write pinpoint references in AGLC4: pages, paragraphs, ranges and sections, for cases, legislation, books and articles. Worked examples.",
          "2026-11-01"),
    Guide("signals", "AGLC4 signals: See, See also, Cf and Contra", "Signals: See, Cf and the rest",
          "What each introductory signal means, how to write it, and how it changes punctuation.",
          "What the AGLC4 introductory signals mean (See, See also, See generally, Cf, But see, Contra), how to write them and how they change punctuation (r 1.2).",
          "2026-11-01"),
    Guide("common-mistakes", "Common AGLC4 footnote mistakes: a checklist", "Common footnote mistakes",
          "A checklist of the usual errors: above n, at, full stops, Ibid misuse, missing pinpoints.",
          "A checklist of common AGLC4 footnote mistakes: above n and op cit, “at” before pinpoints, full stops in abbreviations, Ibid misuse and missing pinpoints.",
          "2026-11-01"),
    Guide("cases", "How to cite cases in AGLC4, with examples", "Citing cases",
          "Reported, medium neutral and unreported decisions, and how to write case names.",
          "How to cite reported, medium neutral and unreported cases in AGLC4, and how to write case names. Worked examples from the Guide.",
          "2026-11-01"),
    Guide("legislation", "How to cite legislation in AGLC4, with examples", "Citing legislation",
          "Acts, Bills, regulations and constitutions, with pinpoints and short titles.",
          "How to cite Acts, Bills, regulations and constitutions in AGLC4, with pinpoints and short titles. Worked examples from the Guide.",
          "2026-11-01"),
    Guide("hansard", "How to cite Hansard in AGLC4, with examples", "Hansard and explanatory memoranda",
          "Parliamentary debates, second reading speeches and explanatory memoranda.",
          "How to cite Hansard (parliamentary debates), second reading speeches and explanatory memoranda in AGLC4 (rr 7.5.1 and 3.7), with examples.",
          "2026-11-01"),
    Guide("treaties", "How to cite a treaty in AGLC4, with examples", "Citing treaties",
          "Title, parties, signature, treaty series and entry into force, with article pinpoints.",
          "How to cite a treaty in AGLC4 (chapter 8): title, parties, date of signature, treaty series, entry into force and article pinpoints, with examples.",
          "2026-11-01"),
    Guide("journal-articles", "How to cite a journal article in AGLC4", "Journal articles",
          "Author, title, year, volume, issue, journal and pages, in print or online.",
          "How to cite a journal article in AGLC4: author, title in quotation marks, year, volume and issue, journal in italics, first page and pinpoint. Examples.",
          "2026-11-01"),
    Guide("articles-and-books", "How to cite books and chapters in AGLC4", "Books and book chapters",
          "Authors, titles, editions, publishers and pinpoints for books, chapters and articles.",
          "How to cite books and chapters in edited books in AGLC4: authors, titles, editions, publishers and pinpoints, with worked examples.",
          "2026-11-01"),
    Guide("reports", "How to cite reports and ALRC reports in AGLC4", "Reports",
          "Government, law reform commission, royal commission and inquiry reports.",
          "How to cite a report in AGLC4 (r 7.1): law reform commission, Productivity Commission, royal commission and government reports, with examples.",
          "2026-11-01"),
    Guide("websites", "How to cite a website or web page in AGLC4", "Websites and web pages",
          "Web pages, blog posts and online documents, with and without an author or date.",
          "How to cite a website, web page or blog post in AGLC4 (r 7.15): author, page title, website name, document type, date and URL, with examples.",
          "2026-11-01"),
    Guide("bibliography", "AGLC4 bibliography: layout and examples", "The bibliography",
          "The five groups, inverted author names, no pinpoints and alphabetical order.",
          "How an AGLC4 bibliography is laid out: the five groups, inverted author names, no pinpoints and alphabetical order. Worked examples.",
          "2026-11-01"),
    Guide("aglc4-vs-aglc5", "AGLC4 or AGLC5: which edition should you use?", "AGLC4 or AGLC5?",
          "AGLC4 is the current edition. What we know about a fifth edition.",
          "Is there an AGLC5? AGLC4 (2018) is the current edition of the Australian Guide to Legal Citation. What we know of a fifth edition, and what AGLC4 changed.",
          "2026-11-01"),
)}

GUIDES_INDEX_TITLE = "AGLC4 referencing guide: rules with examples"
GUIDES_INDEX_DESCRIPTION = (
    "Plain guides to the AGLC4 footnote rules: Ibid, (n x), signals, cases, legislation, "
    "articles, books, reports, websites, treaties and the bibliography."
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


# ---- Structured data (JSON-LD) -------------------------------------------------------- #

#: Left in the page by _fill (it isn't one of its values) and replaced once the page is done.
JSONLD = "{{jsonld}}"

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _FaqReader(HTMLParser):
    """The questions and answers a page shows, as [question, answer] pairs of plain text.

    Reads the home page's <div class="faq"> (each <details> has a <summary> question and an
    answer) and a guide's <section class="g-faq"> (each <h3> question is followed by its
    answer). Anything marked data-paid is skipped when payments are off, because the page
    hides it then. FAQPage markup is built only from this, so it never says more than the
    page does."""

    def __init__(self, include_paid: bool) -> None:
        super().__init__(convert_charrefs=True)
        self.include_paid = include_paid
        self.pairs: list[list[str]] = []
        self._stack: list[str] = []
        self._container: int | None = None  # stack depth of the FAQ container
        self._skip: int | None = None  # stack depth of an element whose text isn't read
        self._question: int | None = None  # stack depth of the question being read
        self._open = False  # whether text belongs to the last pair (not before a container's first question)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _VOID:
            return
        self._stack.append(tag)
        depth = len(self._stack)
        named = dict(attrs)
        if self._container is None:
            if {"faq", "g-faq"} & set((named.get("class") or "").split()):
                self._container, self._open = depth, False
            return
        if self._skip is not None:
            return
        if tag in ("svg", "script", "style") or ("data-paid" in named and not self.include_paid):
            self._skip = depth
        elif tag in ("summary", "h3"):
            self.pairs.append(["", ""])
            self._question, self._open = depth, True

    def handle_endtag(self, tag: str) -> None:
        if tag in _VOID or tag not in self._stack:
            return
        while self._stack:
            depth = len(self._stack)
            for attr in ("_skip", "_question", "_container"):
                if getattr(self, attr) == depth:
                    setattr(self, attr, None)
            if self._stack.pop() == tag:
                break

    def handle_data(self, data: str) -> None:
        if self._container is None or self._skip is not None or not self._open:
            return
        self.pairs[-1][0 if self._question is not None else 1] += data


def page_faq(html: str) -> list[tuple[str, str]]:
    """The visible questions and answers on a filled page (see _FaqReader)."""
    reader = _FaqReader(include_paid=billing.enabled())
    reader.feed(html)
    reader.close()
    tidy = [(" ".join(q.split()), " ".join(a.split())) for q, a in reader.pairs]
    return [(q, a) for q, a in tidy if q and a]


def _owner_name() -> str:
    """Who publishes the site, for author and publisher: $AGLC_OWNER_NAME, else the brand."""
    return (os.environ.get("AGLC_OWNER_NAME") or "").strip() or BRAND


def _site_nodes(base: str) -> list[dict]:
    org = {"@type": "Organization", "@id": f"{base}/#organization", "name": _owner_name(), "url": f"{base}/"}
    site = {
        "@type": "WebSite", "@id": f"{base}/#website", "name": BRAND, "url": f"{base}/",
        "inLanguage": "en-AU", "description": SITE_DESCRIPTION, "publisher": {"@id": org["@id"]},
    }
    return [org, site]


def _breadcrumbs(base: str, trail: list[tuple[str, str]]) -> dict:
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": base + path}
            for i, (name, path) in enumerate(trail, start=1)
        ],
    }


def _web_application(base: str) -> dict:
    """The tool itself. The offer is the live price, and only when payments are on."""
    app = {
        "@type": "WebApplication", "@id": f"{base}/#app", "name": BRAND, "url": f"{base}/",
        "description": SITE_DESCRIPTION, "applicationCategory": "EducationalApplication",
        "operatingSystem": "Web", "inLanguage": "en-AU", "publisher": {"@id": f"{base}/#organization"},
    }
    if billing.enabled():
        product = billing.PRODUCTS["document"]
        app["offers"] = {
            "@type": "Offer", "price": f"{product.amount / 100:.2f}", "priceCurrency": product.currency,
            "description": "One document: every corrected footnote and the .docx with tracked changes",
        }
    return app


def jsonld_script(graph: list[dict]) -> str:
    data = {"@context": "https://schema.org", "@graph": graph}
    # "<" is escaped so that no string in the data can close the script element.
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    return f'<script type="application/ld+json">{text}</script>'


def _finish(html: str, graph: list[dict], url: str) -> HTMLResponse:
    """Adds the page's FAQPage (from its visible questions) and puts the JSON-LD in."""
    faq = page_faq(html)
    if faq:
        graph.append({
            "@type": "FAQPage", "@id": f"{url}#faq", "url": url,
            "mainEntity": [
                {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
                for q, a in faq
            ],
        })
    return HTMLResponse(html.replace(JSONLD, jsonld_script(graph)))


def _human_date(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {d:%B %Y}"


# ---- Pages ---------------------------------------------------------------------------- #


def index(request: Request) -> HTMLResponse:
    base = base_url(request)
    html = _fill(_read(WEB_DIR / "index.html"), request, {"rule_pages": guide_pdf.page_json()})
    graph = [*_site_nodes(base), _web_application(base)]
    return _finish(html, graph, f"{base}/")


def page(name: str, request: Request) -> HTMLResponse:
    file, title, description = PAGES[name]
    base = base_url(request)
    url = f"{base}/{name}"
    body = _read(WEB_DIR / "pages" / file)
    extra = {
        "title": escape(title), "description": escape(description), "content": body, "page": name,
        "canonical": escape(url), "og_title": escape(f"{title} · {BRAND}"), "og_type": "website",
    }
    # The page body is filled first so its own placeholders ({{brand}}...) are filled too.
    html = _fill(_fill(_read(WEB_DIR / "page.html"), request, extra), request)
    webpage = {
        "@type": "AboutPage" if name == "about" else "WebPage", "@id": url, "url": url,
        "name": f"{title} · {BRAND}", "description": description, "inLanguage": "en-AU",
        "isPartOf": {"@id": f"{base}/#website"},
    }
    graph = [*_site_nodes(base), webpage, _breadcrumbs(base, [(BRAND, "/"), (title, f"/{name}")])]
    return _finish(html, graph, url)


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
        '                <p><a href="/guides">All the AGLC4 guides</a></p>'
    )


def _guide_page(request: Request, *, file: str, title: str, description: str, path: str,
                crumbs: str, related: str, updated: str, og_type: str) -> str:
    body = _read(WEB_DIR / "pages" / "guides" / file)
    extra = {
        "title": escape(title), "description": escape(description), "content": body, "path": path,
        "crumbs": crumbs, "related": related, "guide_list": _guide_list(), "updated": updated,
        "canonical": escape(base_url(request) + path), "og_title": escape(f"{title} | {BRAND}"),
        "og_type": og_type,
    }
    # The body is filled first so its own placeholders ({{brand}}, {{guide_list}}...) are filled too.
    return _fill(_fill(_read(WEB_DIR / "guide.html"), request, extra), request, extra)


def guides_index(request: Request) -> HTMLResponse:
    base = base_url(request)
    url = f"{base}/guides"
    html = _guide_page(request, file="index.html", title=GUIDES_INDEX_TITLE, description=GUIDES_INDEX_DESCRIPTION,
                       path="/guides", crumbs="", related="", updated="", og_type="website")
    collection = {
        "@type": "CollectionPage", "@id": url, "url": url, "name": GUIDES_INDEX_TITLE,
        "description": GUIDES_INDEX_DESCRIPTION, "inLanguage": "en-AU", "isPartOf": {"@id": f"{base}/#website"},
        "mainEntity": {
            "@type": "ItemList",
            "itemListElement": [
                {"@type": "ListItem", "position": i, "name": g.name, "url": f"{base}/guides/{g.slug}"}
                for i, g in enumerate(GUIDES.values(), start=1)
            ],
        },
    }
    graph = [*_site_nodes(base), collection, _breadcrumbs(base, [(BRAND, "/"), ("AGLC4 guides", "/guides")])]
    return _finish(html, graph, url)


def guide(slug: str, request: Request) -> HTMLResponse:
    """One guide; a slug that isn't in GUIDES is a 404."""
    entry = GUIDES.get(slug)
    if entry is None:
        raise HTTPException(status_code=404, detail="Page not found")
    base = base_url(request)
    path = f"/guides/{slug}"
    url = base + path
    crumbs = ('                <nav class="crumbs" aria-label="Breadcrumb"><a href="/">Home</a>'
              ' <span aria-hidden="true">/</span> <a href="/guides">AGLC4 guides</a></nav>')
    updated = (f'                <p class="updated">Last updated <time datetime="{entry.updated}">'
               f'{_human_date(entry.updated)}</time></p>')
    html = _guide_page(request, file=f"{slug}.html", title=entry.title, description=entry.description,
                       path=path, crumbs=crumbs, related=_related(slug), updated=updated, og_type="article")
    article = {
        "@type": "TechArticle", "@id": f"{url}#article", "url": url, "mainEntityOfPage": url,
        "headline": entry.title, "description": entry.description, "dateModified": entry.updated,
        "inLanguage": "en-AU", "image": f"{base}/assets/og.png",
        "author": {"@id": f"{base}/#organization"}, "publisher": {"@id": f"{base}/#organization"},
        "isPartOf": {"@id": f"{base}/#website"},
        "about": {"@type": "CreativeWork", "name": "Australian Guide to Legal Citation (4th ed)"},
    }
    trail = [(BRAND, "/"), ("AGLC4 guides", "/guides"), (entry.name, path)]
    graph = [*_site_nodes(base), article, _breadcrumbs(base, trail)]
    return _finish(html, graph, url)


# ---- Sitemap, robots.txt and llms.txt -------------------------------------------------- #

#: The public pages, in sitemap order.
PUBLIC_PATHS = ["/", "/about", "/privacy", "/terms", "/refunds", "/guides", *(f"/guides/{slug}" for slug in GUIDES)]


def lastmod(path: str) -> str:
    """When a public page last changed, as an ISO date (the sitemap's <lastmod>)."""
    if path.startswith("/guides/"):
        return GUIDES[path.removeprefix("/guides/")].updated
    if path in ("/privacy", "/terms", "/refunds"):
        return datetime.strptime(POLICY_DATE, "%d %B %Y").date().isoformat()
    return PAGE_DATES[path]


def sitemap(request: Request) -> Response:
    base = base_url(request)
    urls = "\n".join(
        f"  <url><loc>{escape(base + path)}</loc><lastmod>{lastmod(path)}</lastmod></url>" for path in PUBLIC_PATHS
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )
    return Response(xml, media_type="application/xml")


#: Crawlers named in robots.txt so that letting them in is an explicit choice: search engines,
#: and the AI answer engines that fetch and cite pages in their answers (docs/seo-notes.md).
SEARCH_CRAWLERS = (
    "Googlebot", "Bingbot", "Applebot", "DuckDuckBot",
    "OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "Claude-User", "PerplexityBot", "Perplexity-User",
)
#: Crawlers (and robots.txt tokens) for training AI models. They're let in too, unless
#: $AGLC_BLOCK_AI_TRAINING is set, which shuts them out without touching search or answers.
TRAINING_CRAWLERS = ("GPTBot", "ClaudeBot", "Google-Extended", "Applebot-Extended")


def _truthy(var: str) -> bool:
    return (os.environ.get(var) or "").strip().lower() in ("1", "true", "yes")


def robots(request: Request) -> PlainTextResponse:
    """Everything is open to crawlers except the API, and the sitemap is named. A crawler
    obeys only the most specific group that names it, so each group repeats the API rule."""
    blocked = _truthy("AGLC_BLOCK_AI_TRAINING")
    open_rules = "Allow: /\nDisallow: /api/"
    groups = [
        ("# Everyone: the whole site except the API", ("*",), open_rules),
        ("# Search engines and AI answer engines: welcome, so that answers can cite these pages",
         SEARCH_CRAWLERS, open_rules),
        ("# AI training crawlers: shut out (AGLC_BLOCK_AI_TRAINING is set)" if blocked
         else "# AI training crawlers: welcome too (set AGLC_BLOCK_AI_TRAINING=1 to shut them out)",
         TRAINING_CRAWLERS, "Disallow: /" if blocked else open_rules),
    ]
    text = "\n\n".join(
        comment + "\n" + "".join(f"User-agent: {agent}\n" for agent in agents) + rules
        for comment, agents, rules in groups
    )
    return PlainTextResponse(f"{text}\n\nSitemap: {base_url(request)}/sitemap.xml\n")


def llms_txt(request: Request) -> PlainTextResponse:
    """/llms.txt: what the site is, in plain words for AI models, with every guide (from GUIDES)."""
    base = base_url(request)
    limit = f"{guards.max_upload_bytes() / (1024 * 1024):g} MB"
    lines = [
        f"# {BRAND}",
        "",
        f"> {SITE_DESCRIPTION}",
        "",
        "What it is, and what it isn't:",
        "",
        "- It formats citations. It writes no essay content: it doesn't change the student's argument, "
        "quotations or choice of sources.",
        "- Every change is listed for the student to review before they download. By default (an "
        "option they can turn off) each change is also a Word tracked change they can accept or "
        "reject in Word.",
        "- An AI model only reads each footnote and pulls out its parts (names, years, report series, "
        "pinpoints). Ordinary, tested code builds every AGLC4 citation and decides where Ibid, (n x) "
        "and short titles go.",
        "- It never guesses. A footnote it can't fully account for is left exactly as written and marked "
        "Check, and a missing detail such as a year is marked [MISSING: year], never made up.",
        f"- It takes a Word .docx with real Word footnotes, up to {limit}. There is no account.",
    ]
    if billing.enabled():
        lines.append(
            f"- A free preview shows every footnote's status, every Check item and the first "
            f"{billing.PREVIEW_FULL} fixes in full; one payment of {billing.PRODUCTS['document'].display} "
            "unlocks the whole document."
        )
    lines += [
        "- It follows the Australian Guide to Legal Citation, 4th edition (AGLC4). It isn't affiliated "
        "with or endorsed by the Melbourne University Law Review Association, which publishes the Guide.",
        "- Students should check their own university's and unit's rules on using AI tools in assessed work.",
        "",
        "## AGLC4 guides",
        "",
        *(f"- [{g.name}]({base}/guides/{g.slug}): {g.summary}" for g in GUIDES.values()),
        "",
        "## About the site",
        "",
        f"- [{BRAND}]({base}/): the tool: upload a Word essay and get its footnotes fixed to AGLC4",
        f"- [About]({base}/about): who makes it and how it works",
        f"- [Privacy]({base}/privacy): what happens to an uploaded essay and what is kept",
        f"- [All the AGLC4 guides]({base}/guides)",
        "",
    ]
    return PlainTextResponse("\n".join(lines))
