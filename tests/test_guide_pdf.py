"""Tests for aglc/guide_pdf.py: every rule the tool cites links to its page in the AGLC4 PDF."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aglc import api, guide_pdf

ROOT = Path(__file__).parent.parent

# Rules as the code writes them: "r 3.1.2" in explain.py, "(AGLC4 r 1.1.6)" in a note,
# rule: "r 1.1.2" in the page's body-fix kinds, data-rule="1.1.6" in its own markup
_RULE = re.compile(r"""(?:["'(]|AGLC4 )((?:rr?|ch) \d+(?:\.\d+)*(?:[–-]\d+(?:\.\d+)*)?)""")
_DATA_RULE = re.compile(r'data-rule="([^"]+)"')


def _cited() -> set[str]:
    rules = set()
    for path in ("aglc/explain.py", "aglc/body.py", "aglc/document.py", "aglc/validate.py", "web/index.html"):
        text = (ROOT / path).read_text(encoding="utf-8")
        rules |= set(_RULE.findall(text)) | set(_DATA_RULE.findall(text))
    return rules


def test_the_table_covers_the_guide():
    sections = guide_pdf.sections()
    assert len(sections) == 444
    assert sections["3.1.2"] == [93, "68", "Year"]
    assert sections["1.1.6"][2] == "Pinpoint References"
    assert sections["2"][2] == "Cases"
    # The printed page numbers start at chapter 1, 25 pages into the PDF
    assert all(page - int(printed) == 25 for page, printed, _ in sections.values())
    assert guide_pdf.pdf_url().startswith("https://law.unimelb.edu.au/")


def test_the_scan_finds_the_rules_the_tool_cites():
    cited = _cited()
    assert {"r 3.1.2", "ch 2", "r 1.1.6", "rr 3.1.1–3.1.2", "r 1.1.2", "1.4.4"} <= cited


@pytest.mark.parametrize("rule", sorted(_cited()))
def test_every_cited_rule_has_its_own_page(rule):
    """A typo'd rule number would quietly link to the section above it, so each one the tool
    cites must be a section in the PDF in its own right."""
    number = re.search(r"\d+(?:\.\d+)*", rule)[0]
    assert number in guide_pdf.sections(), f"{rule} isn't a section of AGLC4"
    assert guide_pdf.section(rule) == number


@pytest.mark.parametrize("rule, section", [
    ("r 3.1.2", "3.1.2"),
    ("rr 3.1.1–3.1.2", "3.1.1"),  # a range opens at its first rule
    ("ch 5", "5"),
    ("AGLC4 r 1.1.6", "1.1.6"),
    ("1.13", "1.13"),
    ("r 2.5.9", "2.5"),  # no such rule: the section above it
    ("r 99.1", None),
    ("Ibid", None),
])
def test_section(rule, section):
    assert guide_pdf.section(rule) == section


def test_url_opens_the_pdf_at_the_rule():
    assert guide_pdf.url("r 3.1.2") == f"{guide_pdf.pdf_url()}#page=93"
    assert guide_pdf.url("nothing") is None


def test_the_landing_page_carries_the_table():
    text = TestClient(api.app).get("/").text
    m = re.search(r'<script type="application/json" id="rulePages">(.*?)</script>', text, re.S)
    assert m, "the table isn't on the page"
    data = json.loads(m[1])
    assert data["pdf"] == guide_pdf.pdf_url()
    assert data["sections"]["3.1.2"] == [93, "68", "Year"]


def test_page_json_cannot_close_its_script_element():
    assert "</" not in guide_pdf.page_json()
