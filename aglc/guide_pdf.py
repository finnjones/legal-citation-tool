"""Where each AGLC4 rule is in the official PDF of the *Guide*, so a rule chip can link to it.

aglc/data/aglc4_pages.json maps each numbered section ('3.1.2') to the PDF page it starts on,
the page number printed on that page, and its heading. It is built from the PDF's own
bookmarks by scripts/build_aglc4_pages.py. A link is the PDF's URL with '#page=N', which
desktop browsers open at that page (Safari on iPhone and iPad opens the first page, which is
why the tooltip gives the printed page too).

The results page resolves rules itself (ruleSection in web/index.html, which mirrors
`section` here); the table reaches it through the {{rule_pages}} placeholder (aglc/site.py).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

_TABLE = Path(__file__).parent / "data" / "aglc4_pages.json"

# The first section number in a rule as the formatters write it: 'r 3.1.2', 'rr 3.1.1–3.1.2', 'ch 5'
_FIRST = re.compile(r"^(?:AGLC4\s+)?(?:rr?|ch)?\s*(\d+(?:\.\d+)*)")


@lru_cache(maxsize=1)
def _table() -> dict:
    return json.loads(_TABLE.read_text(encoding="utf-8"))


def pdf_url() -> str:
    return _table()["pdf"]


def sections() -> dict[str, list]:
    """'3.1.2' -> [PDF page, printed page, heading]."""
    return _table()["sections"]


def section(rule: str) -> str | None:
    """The section a rule's link opens: its first number, or the closest section above it
    with a bookmark ('2.5.9' -> '2.5'). None when there's no number in it."""
    m = _FIRST.match(rule.strip())
    if not m:
        return None
    parts = m[1].split(".")
    while parts:
        if ".".join(parts) in sections():
            return ".".join(parts)
        parts.pop()
    return None


def url(rule: str) -> str | None:
    """The official PDF, opened at the page the rule starts on."""
    found = section(rule)
    return f"{pdf_url()}#page={sections()[found][0]}" if found else None


def page_json() -> str:
    """The table for the results page, compact, and safe inside a <script> element."""
    data = {"pdf": pdf_url(), "sections": sections()}
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
