"""Build aglc/data/aglc4_pages.json, the page of the AGLC4 PDF each rule starts on.

The rule chips on the results page link to the official PDF at that page (aglc/guide_pdf.py).
The pages come from the PDF's own bookmarks, which are titled '3.1.2 Year' and so on.

    uv run --no-project --with pypdf --with cryptography python scripts/build_aglc4_pages.py reference/AGLC4.pdf

Run it on the PDF that PDF_URL serves (or a copy with the same pages) whenever that changes.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

#: The official PDF, from https://law.unimelb.edu.au/mulr/aglc/about ("Download the view-only PDF")
PDF_URL = "https://law.unimelb.edu.au/__data/assets/pdf_file/0008/4625792/AGLC4-2021-v1.pdf"

OUT = Path(__file__).parent.parent / "aglc" / "data" / "aglc4_pages.json"

_SECTION = re.compile(r"^(\d+(?:\.\d+)*)\s+(.+)$")


def sections(reader: PdfReader) -> dict[str, list]:
    """'3.1.2' -> [PDF page, printed page, heading] for every numbered bookmark."""
    out: dict[str, list] = {}

    def walk(items):
        for item in items:
            if isinstance(item, list):
                walk(item)
                continue
            m = _SECTION.match(item.title.strip())
            if m:
                index = reader.get_destination_page_number(item)
                out[m[1]] = [index + 1, reader.page_labels[index], m[2].strip()]

    walk(reader.outline)
    return dict(sorted(out.items(), key=lambda kv: [int(n) for n in kv[0].split(".")]))


def main(pdf: str) -> None:
    found = sections(PdfReader(pdf))
    # One section per line, so a changed page reads as a one-line diff
    lines = ",\n".join(f"    {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in found.items())
    OUT.write_text(f'{{\n  "pdf": {json.dumps(PDF_URL)},\n  "sections": {{\n{lines}\n  }}\n}}\n', encoding="utf-8")
    print(f"{len(found)} sections -> {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
