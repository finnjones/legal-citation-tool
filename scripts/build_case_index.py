"""Build aglc/data/case_index.json.gz, the medium neutral citations of every decision in the
Open Australian Legal Corpus, so aglc/verify.py can flag a cited case that doesn't exist,
and the titles and years of its Acts and instruments, so it can catch an Act's wrong year.

The Corpus has every decision published by the High Court, the Federal Court and NSW Caselaw
when it was scraped. Each decision's `citation` is its title ending in its medium neutral
citation ('Muir v Open Brethren [1956] HCA 14'); only that is kept, never the text. Its
legislation is what was in force in the Commonwealth, NSW, Queensland, WA, SA and Tasmania
('Evidence Act 1995 (Cth)'); likewise only the titles are kept.

    uv run python scripts/build_case_index.py                 # streams the 9.4 GB file
    uv run python scripts/build_case_index.py corpus.jsonl    # or reads a local copy

Run it again whenever a new version of the Corpus is published.

The Corpus is by Isaacus, licensed under CC BY 4.0. Decisions remain the work of their courts.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

CORPUS_URL = "https://huggingface.co/datasets/isaacus/open-australian-legal-corpus/resolve/main/corpus.jsonl"
CORPUS_PAGE = "https://huggingface.co/datasets/isaacus/open-australian-legal-corpus"

OUT = Path(__file__).parent.parent / "aglc" / "data" / "case_index.json.gz"

# The citation at the end of a title. Tolerates the Corpus's typos: '[2014) FCA 55', '2003] FCA 897',
# '[ 1999] FCA 1310'.
_MNC = re.compile(r"\s*[\[(]?\s*(\d{4})\s*[\])]\s*([A-Za-z]+)\s+(\d+)\s*$")

#: Courts with fewer decisions than this in the Corpus are left out: too few to tell a missing
#: decision from a court the Corpus barely covers.
MIN_DECISIONS = 50


_KEPT = (b'"type":"decision"', b'"type":"primary_legislation"', b'"type":"secondary_legislation"')


def records(lines):
    """The fields before `text` of each decision and Act or instrument (parsing the whole
    line would mean parsing every document's text). `text` is the last field."""
    for line in lines:
        if not any(kind in line[:200] for kind in _KEPT):
            continue
        head = line[: line.find(b',"text":')] + b"}"
        try:
            yield json.loads(head)
        except ValueError:
            continue


# An Act's or instrument's title: 'Evidence Act 1995 (Cth)', 'Railway Discontinuance Act (No. 2)
# 2006 (WA)', 'Lord Howe Island Regulation 2014 (2014-497) (NSW)', '... Act 2009 (Repealed) (Tas)'
_LEGISLATION = re.compile(r"^(?P<title>.+?)\s+(?P<year>\d{4})(?:\s*\(\d{4}-\d+\))?(?:\s*\(Repealed\))?\s*\((?P<jurisdiction>[A-Za-z ]+)\)\s*$")


def legislation_key(title: str) -> str:
    """'Railway Discontinuance Act (No. 2)' -> 'railway discontinuance act no 2'. aglc/verify.py
    keys the cited title the same way."""
    return " ".join(re.findall(r"[a-z0-9]+", title.lower().replace("&", " and ")))


#: Where a decision without a medium neutral citation came from, for matching a reported
#: case by name (aglc/verify.py): its court isn't known, only the site's.
_SITES = {"high_court_of_australia": "HCA", "federal_court_of_australia": "FCA", "nsw_caselaw": "NSW"}


def build(lines) -> dict:
    cases: dict[str, dict[str, dict[str, str | list[str]]]] = defaultdict(lambda: defaultdict(dict))
    unnumbered: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    scraped: dict[str, str] = {}
    # jurisdiction -> legislation_key(title) -> [title as the register gives it, years]
    legislation: dict[str, dict[str, list]] = defaultdict(dict)
    seen = 0
    for rec in records(lines):
        if rec.get("type") != "decision":
            if m := _LEGISLATION.match(rec.get("citation") or ""):
                entry = legislation[m["jurisdiction"]].setdefault(legislation_key(m["title"]), [m["title"].replace("(No. ", "(No "), []])
                if m["year"] not in entry[1]:
                    entry[1] = sorted(entry[1] + [m["year"]])
            continue
        seen += 1
        m = _MNC.search(rec.get("citation") or "")
        if not m:
            # eg 'Commissioner of Taxation (Cth) v Westfield Ltd': findable by name and year,
            # or by name alone ('?') when the site gives no date, as the High Court's doesn't
            site, year = _SITES.get(rec.get("source")), (rec.get("date") or "")[:4] or "?"
            if site and rec.get("citation"):
                unnumbered[site][year].append(rec["citation"].strip())
            continue
        year, court, number = m[1], m[2], str(int(m[3]))
        name = rec["citation"][: m.start()].strip()
        names = cases[court][year]
        if number not in names:
            names[number] = name
        elif name not in (old := names[number] if isinstance(names[number], list) else [names[number]]):
            names[number] = old + [name]
        scraped[court] = max(scraped.get(court, ""), (rec.get("when_scraped") or "")[:10])
        if seen % 20000 == 0:
            print(f"{seen} decisions read", file=sys.stderr)

    courts = {}
    for court, years in sorted(cases.items()):
        if sum(len(v) for v in years.values()) < MIN_DECISIONS:
            continue
        courts[court] = {
            "scraped": scraped[court],
            "years": {y: {k: years[y][k] for k in sorted(years[y], key=int)} for y in sorted(years)},
        }
    return {
        "source": f"Open Australian Legal Corpus by Isaacus, CC BY 4.0 ({CORPUS_PAGE})",
        "built": date.today().isoformat(),
        "courts": courts,
        # decisions whose title has no medium neutral citation: site -> year decided -> titles
        "unnumbered": {site: {y: sorted(t) for y, t in sorted(years.items())} for site, years in sorted(unnumbered.items())},
        # Acts and instruments in force when scraped (and Tasmania's repealed ones):
        # jurisdiction -> legislation_key(title) -> [title, years]
        "legislation": {j: dict(sorted(titles.items())) for j, titles in sorted(legislation.items())},
    }


def main() -> None:
    if len(sys.argv) > 1:
        stream = open(sys.argv[1], "rb")
    else:
        stream = io.BufferedReader(urllib.request.urlopen(CORPUS_URL), buffer_size=1 << 20)
    with stream:
        index = build(stream)
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    total = sum(len(v) for c in index["courts"].values() for v in c["years"].values())
    acts = sum(len(titles) for titles in index["legislation"].values())
    print(f"wrote {OUT} ({total} decisions, {len(index['courts'])} courts, {acts} Acts and instruments)")


if __name__ == "__main__":
    main()
