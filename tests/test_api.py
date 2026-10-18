"""Tests for the FastAPI API."""

from __future__ import annotations

import json
import re
import tempfile
import uuid
from io import BytesIO
from pathlib import Path
from unittest import mock

import pytest
from fastapi.testclient import TestClient

from aglc import api, guards, pipeline, site
from aglc.llm.base import LLMError
from aglc.models import (
    BibliographySection,
    BodyFix,
    FootnoteResult,
    ProcessResult,
    RichText,
    Run,
    Warning_,
)

client = TestClient(api.app)
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ---- Fixtures -------------------------------------------------------------- #


@pytest.fixture
def fake_process_result():
    """Create a sample ProcessResult for mocking."""
    return ProcessResult(
        footnotes=[
            FootnoteResult(
                number=1,
                original=RichText(runs=[Run(text="Competition and Consumer Act 2010 (Cth)", italic=False)]),
                formatted=RichText(
                    runs=[
                        Run(text="Competition and Consumer Act", italic=True),
                        Run(text=" 2010 (Cth)", italic=False),
                    ]
                ),
            ),
        ],
        bibliography=[
            BibliographySection(
                heading="C Legislation",
                entries=[
                    RichText(
                        runs=[
                            Run(text="Competition and Consumer Act", italic=True),
                            Run(text=" 2010 (Cth)", italic=False),
                        ]
                    ),
                ],
            ),
        ],
        warnings=[
            Warning_(footnote=1, message="Test warning"),
        ],
        body_fixes=[
            BodyFix(footnote=1, message="footnote number moved after the ‘.’"),
        ],
    )


@pytest.fixture
def minimal_docx():
    """Create a minimal valid .docx file."""
    # Minimal ZIP-based docx (just magic bytes + minimal structure)
    docx_bytes = BytesIO()
    # PK zip header
    docx_bytes.write(b"PK\x03\x04")
    docx_bytes.seek(0)
    return docx_bytes.getvalue()


# ---- Tests: GET / ---------------------------------------------------------- #


def test_root_serves_html():
    """Test that GET / serves index.html."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<title>AGLC4 Footnote Generator &amp; Citation Checker for Word | Aforecite</title>" in response.text
    assert "{{" not in response.text  # every placeholder filled
    assert site.BRAND in response.text


def test_root_file_not_found_handled():
    """Test that missing index.html is handled gracefully."""
    # Temporarily mock the file to not exist
    with mock.patch("pathlib.Path.exists", return_value=False):
        response = client.get("/")
        assert response.status_code == 404


# ---- Tests: GET /api/providers --------------------------------------------- #


def test_providers_endpoint():
    """Test /api/providers returns provider list."""
    response = client.get("/api/providers")
    assert response.status_code == 200

    data = response.json()
    assert "providers" in data
    assert "default" in data
    assert isinstance(data["providers"], list)
    assert "anthropic" in data["providers"]
    assert ":" in data["default"]


# ---- Tests: POST /api/process ---------------------------------------------- #


def test_process_minimal(minimal_docx, fake_process_result):
    """Test minimal POST /api/process request."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        response = client.post(
            "/api/process",
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "footnotes" in data
        assert "bibliography" in data
        assert "warnings" in data


def test_process_with_options(minimal_docx, fake_process_result):
    """Test POST /api/process with model and options."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        response = client.post(
            "/api/process",
            data={
                "model": "openai:gpt-4",
                "track_changes": "false",
                "bibliography": "true",
                "fix_body": "false",
            },
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert response.status_code == 200
        call_args = mock_process.call_args
        assert call_args[0][2] == "openai:gpt-4"
        assert call_args[1]["track_changes"] is False
        assert call_args[1]["bibliography"] is True
        assert call_args[1]["fix_body"] is False


def test_process_response_format(minimal_docx, fake_process_result):
    """Test response format of /api/process."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = fake_process_result

        response = client.post(
            "/api/process",
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert response.status_code == 200
        data = response.json()

        # Check footnotes format
        assert len(data["footnotes"]) == 1
        fn = data["footnotes"][0]
        assert fn["number"] == 1
        assert "original" in fn
        assert "original_html" in fn
        assert "formatted" in fn
        assert "formatted_html" in fn
        assert "changed" in fn
        assert fn["extraction_failed"] is None
        assert "<em>" in fn["formatted_html"]

        # Check bibliography format
        assert len(data["bibliography"]) == 1
        bib_section = data["bibliography"][0]
        assert bib_section["heading"] == "C Legislation"
        assert len(bib_section["entries"]) > 0

        # Check warnings format
        assert len(data["warnings"]) == 1
        assert data["warnings"][0]["footnote"] == 1
        assert "message" in data["warnings"][0]

        # Check body text fixes format
        assert data["body_fixes"] == [{"footnote": 1, "message": "footnote number moved after the ‘.’", "applied": True}]


def test_process_non_docx_rejected():
    """Test that non-.docx files are rejected."""
    response = client.post(
        "/api/process",
        files={"file": ("test.txt", b"Not a docx", "text/plain")},
    )

    assert response.status_code == 400
    assert "docx" in response.json()["detail"].lower()


def test_process_missing_file():
    """Test POST /api/process without file."""
    response = client.post("/api/process")
    assert response.status_code == 422  # Unprocessable Entity


def test_process_error_handling(minimal_docx):
    """Test error handling in POST /api/process."""
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.side_effect = RuntimeError("Test error")

        response = client.post(
            "/api/process",
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert response.status_code == 500
        detail = response.json()["detail"]
        assert "went wrong" in detail
        assert "Test error" not in detail  # the exception is logged, never shown


def test_process_ai_error_hides_provider_text(minimal_docx):
    with mock.patch("aglc.pipeline.process_docx", side_effect=LLMError("401 invalid key sk-secret")):
        response = client.post("/api/process", files={"file": ("test.docx", minimal_docx, DOCX)})
    assert response.status_code == 502
    assert "sk-secret" not in response.json()["detail"]
    assert "AI model" in response.json()["detail"]


@pytest.mark.parametrize(("name", "expected"), [
    ("essay.doc", "older Word .doc"),
    ("essay.pdf", "PDF"),
    ("essay.pages", "Pages"),
    ("essay.txt", ".docx"),
])
def test_wrong_file_type_gets_a_specific_message(name, expected):
    response = client.post("/api/process", files={"file": (name, b"x", "application/octet-stream")})
    assert response.status_code == 400
    assert expected in response.json()["detail"]


def test_process_rejects_files_over_10_mb():
    big = b"PK\x03\x04" + b"\0" * guards.max_upload_bytes()
    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        response = client.post("/api/process", files={"file": ("big.docx", big, DOCX)})
    assert response.status_code == 413
    assert "10 MB" in response.json()["detail"]
    mock_process.assert_not_called()


def test_failed_extraction_warning_hides_provider_error(minimal_docx, fake_process_result):
    fake_process_result.warnings = [
        Warning_(message="extraction failed for footnotes [1, 2]: Error code: 402 - {'error': 'no credit'}; left unchanged"),
    ]
    with mock.patch("aglc.pipeline.process_docx", return_value=fake_process_result):
        data = client.post("/api/process", files={"file": ("test.docx", minimal_docx, DOCX)}).json()
    assert data["warnings"][0]["message"] == "extraction failed for footnotes [1, 2]; left unchanged"
    assert pipeline.failed_footnotes(data["warnings"]) == {1, 2}  # still recognised as failed


# ---- Tests: GET /api/download/{id} ----------------------------------------- #


def test_download_success(minimal_docx, fake_process_result):
    """Test successful download of processed document."""
    def mock_process_docx(src, dst, *args, **kwargs):
        """Mock process_docx that creates output file."""
        # Create the output file
        Path(dst).write_bytes(b"PK\x03\x04")
        return fake_process_result

    with mock.patch("aglc.pipeline.process_docx", side_effect=mock_process_docx):
        # First, process a document to get a session_id
        process_response = client.post(
            "/api/process",
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        assert process_response.status_code == 200
        session_id = process_response.json()["id"]

        # Now try to download
        download_response = client.get(f"/api/download/{session_id}")
        assert download_response.status_code == 200
        assert "application/vnd.openxmlformats" in download_response.headers["content-type"]


def test_download_nonexistent_session():
    """Test download with non-existent session ID."""
    fake_id = str(uuid.uuid4())
    response = client.get(f"/api/download/{fake_id}")
    assert response.status_code == 404


def test_download_invalid_uuid():
    """Test download with invalid UUID."""
    response = client.get("/api/download/not-a-uuid")
    assert response.status_code == 422


def test_download_filename(minimal_docx, fake_process_result):
    """Test that download has correct filename."""
    def mock_process_docx(src, dst, *args, **kwargs):
        """Mock process_docx that creates output file."""
        # Create the output file
        Path(dst).write_bytes(b"PK\x03\x04")
        return fake_process_result

    with mock.patch("aglc.pipeline.process_docx", side_effect=mock_process_docx):
        # Process
        process_response = client.post(
            "/api/process",
            files={"file": ("myessay.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        session_id = process_response.json()["id"]

        # Download
        download_response = client.get(f"/api/download/{session_id}")
        assert "myessay.aglc.docx" in download_response.headers.get("content-disposition", "")


# ---- Tests: HTML escaping -------------------------------------------------- #


def test_process_escapes_html_in_footnotes(minimal_docx):
    """Test that HTML special characters are escaped in response."""
    result_with_html_chars = ProcessResult(
        footnotes=[
            FootnoteResult(
                number=1,
                original=RichText(runs=[Run(text="Case v State <special> & \"quoted\"", italic=False)]),
                formatted=RichText(runs=[Run(text="Case v State <special> & \"quoted\"", italic=False)]),
            ),
        ],
        bibliography=[],
        warnings=[],
    )

    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = result_with_html_chars

        response = client.post(
            "/api/process",
            files={"file": ("test.docx", minimal_docx, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        data = response.json()
        html = data["footnotes"][0]["original_html"]

        # Check that special chars are escaped
        assert "&lt;" in html
        assert "&gt;" in html
        assert "&amp;" in html
        assert "&quot;" in html or "&#39;" in html


# ---- Tests: RichText HTML conversion --------------------------------------- #


def test_richtext_italic_conversion(minimal_docx):
    """Test that italic runs are converted to <em> tags."""
    result_with_italics = ProcessResult(
        footnotes=[
            FootnoteResult(
                number=1,
                original=RichText(
                    runs=[
                        Run(text="Case", italic=True),
                        Run(text=" v ", italic=False),
                        Run(text="State", italic=True),
                    ]
                ),
                formatted=RichText(
                    runs=[
                        Run(text="Case", italic=True),
                        Run(text=" v ", italic=False),
                        Run(text="State", italic=True),
                    ]
                ),
            ),
        ],
        bibliography=[],
        warnings=[],
    )

    with mock.patch("aglc.pipeline.process_docx") as mock_process:
        mock_process.return_value = result_with_italics

        response = client.post(
            "/api/process",
            files={"file": ("test.docx", b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        )

        data = response.json()
        html = data["footnotes"][0]["original_html"]

        assert "<em>Case</em>" in html
        assert "<em>State</em>" in html
        assert " v " in html


# ---- Tests: the public site --------------------------------------------- #


@pytest.mark.parametrize("path", ["/privacy", "/terms", "/refunds", "/about"])
def test_static_pages(path):
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "{{" not in response.text
    assert site.BRAND in response.text
    for link in ("/about", "/privacy", "/terms", "/refunds"):  # the shared footer
        assert f'href="{link}"' in response.text


@pytest.mark.parametrize("path", ["/terms", "/refunds"])
def test_policy_pages_keep_consumer_law_rights(path):
    assert "Nothing here limits your rights under the Australian Consumer Law." in client.get(path).text


def test_privacy_page_describes_the_ai_model_honestly():
    text = client.get("/privacy").text
    assert "OpenRouter" in text and "DeepSeek" in text and "don't store or train on" in text
    assert "outside Australia" in text and "never used for training" not in text


@pytest.mark.parametrize("path", ["/privacy", "/terms", "/about", "/refunds"])
def test_unset_owner_details_show_as_todo(path):
    text = client.get(path).text
    assert "[TODO: set AGLC_CONTACT_EMAIL" in text  # the footer, at least
    assert site.POLICY_DATE in text or path == "/about"


def test_owner_details_fill_the_legal_pages(monkeypatch):
    for var, value in {"AGLC_OWNER_NAME": "Sam Example", "AGLC_CONTACT_EMAIL": "hi@example.com",
                       "AGLC_ABN": "12 345 678 901", "AGLC_STATE": "Victoria",
                       "AGLC_OWNER_ABOUT": "A law student.", "AGLC_LOG_RETENTION_DAYS": "14"}.items():
        monkeypatch.setenv(var, value)
    pages = {p: client.get(p).text for p in ("/privacy", "/terms", "/about", "/refunds")}
    assert all("[TODO" not in text for text in pages.values()), [p for p, t in pages.items() if "[TODO" in t]
    assert "Sam Example" in pages["/terms"] and "law of Victoria, Australia" in pages["/terms"]
    assert '<a href="mailto:hi@example.com">hi@example.com</a>' in pages["/refunds"]
    assert "kept for 14 days" in pages["/privacy"] and "A law student." in pages["/about"]


def test_owner_details_are_escaped(monkeypatch):
    monkeypatch.setenv("AGLC_OWNER_NAME", "<script>x</script>")
    assert "<script>x</script>" not in client.get("/terms").text


def test_gst_and_analytics_notes_follow_the_settings(monkeypatch):
    assert "aren't registered for GST" in client.get("/terms").text
    assert "don't use analytics" in client.get("/privacy").text
    monkeypatch.setenv("AGLC_GST_REGISTERED", "true")
    monkeypatch.setenv("AGLC_PLAUSIBLE_DOMAIN", "cite.example.com")
    assert "The price includes GST." in client.get("/terms").text
    assert "Analytics is on" in client.get("/privacy").text


def test_terms_limit_liability_but_keep_consumer_law():
    text = client.get("/terms").text
    assert "No guarantee of accuracy" in text and "To the extent the law allows" in text
    assert "marks or grades" in text
    refunds = client.get("/refunds").text
    assert "within 14 days of paying" in refunds and "change of mind" in refunds


def test_privacy_page_states_the_real_retention_period(monkeypatch):
    assert "deleted automatically 24 hours after" in client.get("/privacy").text  # the default
    monkeypatch.setenv("AGLC_RETENTION_HOURS", "48")
    text = client.get("/privacy").text
    assert "deleted automatically 48 hours after" in text and "TODO: retention" not in text


@pytest.mark.parametrize("path", ["/", "/privacy"])
def test_pages_load_no_third_party_fonts(path):
    text = client.get(path).text
    assert "fonts.googleapis.com" not in text and "fonts.gstatic.com" not in text
    assert 'href="/assets/fonts/fonts.css"' in text and 'rel="icon"' in text


def test_self_hosted_fonts_and_favicon_are_served():
    css = client.get("/assets/fonts/fonts.css")
    assert css.status_code == 200 and css.text.count("@font-face") == 6
    for url in sorted(set(re.findall(r'url\("(/assets/fonts/[^"]+)"\)', css.text))):
        font = client.get(url)
        assert font.status_code == 200 and font.content[:4] == b"wOF2", url
    icon = client.get("/favicon.ico")
    assert icon.status_code == 200 and icon.headers["content-type"].startswith("image/svg+xml")


def test_status():
    response = client.get("/status")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": api.__version__, "payments": False}


def test_sample_essay_is_served():
    response = client.get("/api/sample")
    assert response.status_code == 200
    assert response.headers["content-type"] == DOCX
    assert response.content == site.SAMPLE_ESSAY.read_bytes()
    assert "sample-essay.docx" in response.headers["content-disposition"]


def test_shared_stylesheet_is_served():
    response = client.get("/assets/chambers.css")
    assert response.status_code == 200
    assert "--accent: #1F3A5F" in response.text


def test_open_graph_tags_use_the_public_url(monkeypatch):
    monkeypatch.setenv("AGLC_PUBLIC_URL", "https://cite.example.com/")
    text = client.get("/").text
    assert '<meta property="og:image" content="https://cite.example.com/assets/og.png">' in text
    assert '<meta property="og:url" content="https://cite.example.com/">' in text
    assert '<meta name="description"' in text
    assert client.get("/assets/og.png").headers["content-type"] == "image/png"


def test_plausible_is_off_unless_configured(monkeypatch):
    assert "plausible.io" not in client.get("/").text
    monkeypatch.setenv("AGLC_PLAUSIBLE_DOMAIN", "cite.example.com")
    for path in ("/", "/privacy"):
        assert '<script defer data-domain="cite.example.com" src="https://plausible.io/js/script.js"></script>' in client.get(path).text


def test_price_on_the_page_comes_from_the_server():
    from aglc import billing

    text = client.get("/").text
    assert f"{billing.PRODUCTS['document'].display} per document" in text
    assert f"first {billing.PREVIEW_FULL} fixes free" in text


# ---- Tests: the AGLC4 guides, sitemap and robots.txt ------------------------------ #

GUIDE_PATHS = [f"/guides/{slug}" for slug in site.GUIDES]
_REPO = Path(__file__).parent.parent


@pytest.mark.parametrize("path", GUIDE_PATHS)
def test_each_guide_renders(path):
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    text = response.text
    guide = site.GUIDES[path.rsplit("/", 1)[1]]
    assert "{{" not in text
    assert site.BRAND in text
    assert f"<title>{guide.title} | {site.BRAND}</title>" in text
    assert f'<link rel="canonical" href="http://testserver{path}">' in text
    assert f'<meta name="description" content="{guide.description}">' in text
    assert text.count("<h1") == 1 and text.count("<h2") >= 3
    assert 'href="/#uploadCard"' in text  # the call to action goes to the home page's upload
    assert "https://law.unimelb.edu.au/mulr/aglc/about" in text
    assert "isn't affiliated with or endorsed by the Melbourne University Law Review Association" in text
    assert 'href="/guides"' in text and 'href="/privacy"' in text  # the shared header, footer and index link


def test_guide_titles_and_descriptions_are_distinct():
    titles = [g.title for g in site.GUIDES.values()] + [site.GUIDES_INDEX_TITLE]
    assert len(set(titles)) == len(titles)
    descriptions = [g.description for g in site.GUIDES.values()] + [site.GUIDES_INDEX_DESCRIPTION]
    assert len(set(descriptions)) == len(descriptions)
    assert "Ibid in AGLC4: when and how to use it | Aforecite" in client.get("/guides/ibid").text


def test_guide_urls_use_the_public_url(monkeypatch):
    monkeypatch.setenv("AGLC_PUBLIC_URL", "https://cite.example.com/")
    text = client.get("/guides/ibid").text
    assert '<link rel="canonical" href="https://cite.example.com/guides/ibid">' in text
    assert '<meta property="og:url" content="https://cite.example.com/guides/ibid">' in text


def test_guides_index_lists_every_guide():
    response = client.get("/guides")
    assert response.status_code == 200
    text = response.text
    assert "{{" not in text and site.BRAND in text
    assert f"<title>{site.GUIDES_INDEX_TITLE} | {site.BRAND}</title>" in text
    assert '<link rel="canonical" href="http://testserver/guides">' in text
    for slug, guide in site.GUIDES.items():
        assert f'href="/guides/{slug}"' in text and guide.name in text
    assert 'href="/#uploadCard"' in text


def test_a_guide_links_to_the_other_guides_but_not_itself():
    text = client.get("/guides/ibid").text
    assert 'href="/guides/subsequent-references"' in text and 'href="/guides/bibliography"' in text
    assert 'href="/guides/ibid"' not in text


@pytest.mark.parametrize("slug", ["nope", "index", "ibid.html", "..%2Fprivacy", "IBID"])
def test_unknown_guide_is_404(slug):
    assert client.get(f"/guides/{slug}").status_code == 404


def test_the_site_links_to_the_guides():
    assert 'href="/guides"' in client.get("/privacy").text  # the footer partial
    landing = client.get("/").text
    assert 'href="/guides"' in landing  # the footer, and a link from "What it fixes"
    assert "Read the rules with worked examples.</a>" in landing


def test_sitemap_lists_every_public_page_and_is_valid_xml():
    import xml.etree.ElementTree as ET

    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert "xml" in response.headers["content-type"]
    root = ET.fromstring(response.text)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    assert root.tag == "{http://www.sitemaps.org/schemas/sitemap/0.9}urlset"
    locs = [loc.text for loc in root.findall("s:url/s:loc", ns)]
    paths = ["/", "/about", "/privacy", "/terms", "/refunds", "/guides", *GUIDE_PATHS]
    assert locs == ["http://testserver" + path for path in paths]
    assert len(set(locs)) == len(locs)
    for path in paths:  # everything the sitemap names really exists
        assert client.get(path).status_code == 200


def test_sitemap_uses_the_public_url(monkeypatch):
    import xml.etree.ElementTree as ET

    monkeypatch.setenv("AGLC_PUBLIC_URL", "https://cite.example.com/")
    root = ET.fromstring(client.get("/sitemap.xml").text)
    locs = [el.text for el in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    assert locs[0] == "https://cite.example.com/" and "https://cite.example.com/guides/ibid" in locs
    assert all(loc.startswith("https://cite.example.com/") for loc in locs)


def test_robots_txt_allows_the_site_but_not_the_api():
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    lines = response.text.splitlines()
    assert "User-agent: *" in lines and "Disallow: /api/" in lines
    assert "Disallow: /" not in lines and not any(line.startswith("Disallow: /guides") for line in lines)
    assert "Sitemap: http://testserver/sitemap.xml" in lines


def test_robots_txt_names_the_sitemap_on_the_public_url(monkeypatch):
    monkeypatch.setenv("AGLC_PUBLIC_URL", "https://cite.example.com")
    assert "Sitemap: https://cite.example.com/sitemap.xml" in client.get("/robots.txt").text.splitlines()


# ---- Guard tests: the guides may only cite rules and examples this repo knows -------- #

from html.parser import HTMLParser  # noqa: E402

_RULE_CITE = re.compile(r"\brr? (\d+(?:\.\d+)+(?:(?:,| and) \d+(?:\.\d+)+)*)")
_NUMBER = re.compile(r"\d+(?:\.\d+)+")


class _GuideText(HTMLParser):
    """Splits a guide page into its prose and its citation examples (<p class="g-cite ...">)."""

    def __init__(self):
        super().__init__()
        self.prose: list[str] = []
        self.examples: list[dict] = []  # {"kind": "was"|"redline"|"plain", "with_del", "with_ins"}
        self._cur: dict | None = None
        self._skip: list[str] = []

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        if tag in ("script", "style"):
            self._skip.append(tag)
        if tag == "p" and "g-cite" in classes:
            kind = "was" if "g-was" in classes else "redline" if "g-redline" in classes else "plain"
            self._cur = {"kind": kind, "with_del": "", "with_ins": "", "open": []}
            self.examples.append(self._cur)
        elif self._cur is not None and tag in ("del", "ins"):
            self._cur["open"].append(tag)

    def handle_endtag(self, tag):
        if self._skip and tag == self._skip[-1]:
            self._skip.pop()
        if self._cur is None:
            return
        if tag == "p":
            self._cur = None
        elif tag in ("del", "ins") and self._cur["open"]:
            self._cur["open"].pop()

    def handle_data(self, data):
        if self._skip:
            return
        if self._cur is None:
            self.prose.append(data)
            return
        if "ins" not in self._cur["open"]:
            self._cur["with_del"] += data  # the "as written" text: everything but insertions
        if "del" not in self._cur["open"]:
            self._cur["with_ins"] += data  # the AGLC4 text: everything but deletions


def _guide_parts(path: str) -> _GuideText:
    parser = _GuideText()
    parser.feed(client.get(path).text)
    return parser


def _flat(text: str) -> str:
    """Plain comparison text: no italics markup, one kind of space, no closing full stop."""
    text = text.replace("\xa0", " ").replace("*", "")
    return re.sub(r"\s+", " ", text).strip().rstrip(".").strip()


def _rule_numbers(text: str) -> list[str]:
    text = text.replace("\xa0", " ")
    return [n for m in _RULE_CITE.finditer(text) for n in _NUMBER.findall(m[1])]


def _known_rule_numbers() -> set[str]:
    """Rule numbers the repo itself uses: in the formatter and document code (on lines that
    cite a rule), and as the 'rule' of a golden example from the Guide."""
    known: set[str] = set()
    for path in (_REPO / "aglc").rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"\brr? ?\d", line):
                known.update(_NUMBER.findall(line))
    for path in (_REPO / "tests" / "aglc4_examples").glob("*.json"):
        known.update(entry["rule"] for entry in json.loads(path.read_text(encoding="utf-8")))
    return known


def _example_corpus() -> str:
    """Everything the guides' examples may come from: the golden examples (the Guide's own)
    and the other tests. This file is left out so that it can't vouch for itself."""
    pieces = []
    for path in (_REPO / "tests" / "aglc4_examples").glob("*.json"):
        for entry in json.loads(path.read_text(encoding="utf-8")):
            pieces.append(entry.get("expected_full", ""))
            pieces += [fn["expected"] for fn in entry.get("footnotes", [])]
    for path in (_REPO / "tests").glob("test_*.py"):
        if path.name != Path(__file__).name:
            pieces.append(path.read_text(encoding="utf-8"))
    return _flat("\n".join(pieces))


def test_rule_number_guard_catches_an_invented_rule():
    assert _rule_numbers("see r\xa09.9.9, and rr 1.4.3 and 1.1.6; also ch 2 and s 5, 10") == ["9.9.9", "1.4.3", "1.1.6"]
    assert "9.9.9" not in _known_rule_numbers()
    assert {"1.4.1", "1.4.3", "1.4.4", "1.1.6", "1.13", "3.1.4"} <= _known_rule_numbers()


@pytest.mark.parametrize("path", GUIDE_PATHS)
def test_guide_rule_numbers_are_ones_the_repo_knows(path):
    prose = "".join(_guide_parts(path).prose)
    unknown = sorted(set(_rule_numbers(prose)) - _known_rule_numbers())
    assert not unknown, f"{path} cites rules that appear nowhere in aglc/ or tests/aglc4_examples: {unknown}"
    code = "\n".join(p.read_text(encoding="utf-8") for p in (_REPO / "aglc").rglob("*.py"))
    for chapter in re.findall(r"\b[Cc]hapters? (\d+)", prose):
        assert re.search(rf"\bch(?:apter)? {chapter}\b", code), f"{path} cites chapter {chapter}"


def test_guides_cite_rules_at_all():
    cited = {n for path in GUIDE_PATHS for n in _rule_numbers("".join(_guide_parts(path).prose))}
    assert {"1.4.1", "1.4.3", "1.4.4", "1.1.6", "1.13", "3.1.4"} <= cited


@pytest.mark.parametrize("path", GUIDE_PATHS)
def test_guide_examples_are_from_the_golden_examples_or_the_tests(path):
    corpus = _example_corpus()
    examples = _guide_parts(path).examples
    assert examples
    for ex in examples:
        if ex["kind"] == "was":
            continue
        shown = _flat(ex["with_ins"])
        assert shown in corpus, f"{path}: example not found in tests/: {shown!r}"


@pytest.mark.parametrize("path", GUIDE_PATHS)
def test_guide_before_and_after_examples_are_real_and_consistent(path):
    from aglc.docx_io import read_footnotes

    sample = _REPO / "tests" / "fixtures" / "sample_essay.docx"
    originals = {_flat(f.original.to_markup()) for f in read_footnotes(sample)}
    examples = _guide_parts(path).examples
    for i, ex in enumerate(examples):
        if ex["kind"] == "was":
            # "As written" is a footnote from the sample essay, which test_end_to_end runs through the tool
            assert _flat(ex["with_del"]) in originals, f"{path}: not a sample-essay footnote: {ex['with_del']!r}"
            assert examples[i + 1]["kind"] == "redline"
        if ex["kind"] == "redline":
            # the redline, read without its insertions, is the line above it
            assert examples[i - 1]["kind"] == "was"
            assert _flat(ex["with_del"]) == _flat(examples[i - 1]["with_del"])
