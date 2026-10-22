"""Checks that a case cited by medium neutral citation exists, against an offline index of
published decisions (aglc/data/case_index.json.gz, built by scripts/build_case_index.py
from the Open Australian Legal Corpus). Nothing is sent anywhere.

A citation is only flagged where the index can answer for it. Two flags:
  - name mismatch:  [1956] HCA 14 is in the index, but is a different case
  - not found:      [2015] NSWSC 9999 is well past the court's last decision that year, in
                    a year the index has (nearly) every decision of

A number inside a year's range that the index lacks is never flagged: even in complete
years the Corpus is missing some decisions (about 8% of the High Court's, 1-3% of the
Federal Court's and NSW courts'), so a gap can't tell a fake case from a real one. Other
courts, years after the index was built and years the court's site barely has are not
checked either.
"""

from __future__ import annotations

import gzip
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from .models import CaseSource, Citation

_INDEX = Path(__file__).resolve().parent / "data" / "case_index.json.gz"

#: A year counts as covered when the index has at least this share of the court's
#: decisions up to the highest number it has (some are never published, eg suppressed),
#: and at least MIN_YEAR of them (with fewer, one missing decision changes the share a lot).
COMPLETE = 0.85
MIN_YEAR = 10


@lru_cache(maxsize=1)
def _index() -> dict:
    """The index, or an empty one if it hasn't been built (then nothing is checked)."""
    try:
        with gzip.open(_INDEX, "rt", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"courts": {}}


def index_covers(court: str, year: str) -> bool:
    """Whether the index has (nearly) every decision of `court` in `year`."""
    entry = _index()["courts"].get(court)
    if not entry:
        return False
    numbers = entry["years"].get(year)
    if not numbers or len(numbers) < MIN_YEAR:
        return False
    # Still being added to when scraped: a missing number may just be newer
    if year >= entry["scraped"][:4]:
        return False
    return len(numbers) / _last(numbers) >= COMPLETE


def _last(numbers: dict) -> int:
    return max(int(n) for n in numbers)


class CaseCheck(NamedTuple):
    checked: bool  # the index could say whether the citation is right
    warning: str | None = None  # what's wrong with it, if anything


def check_citation(citation: Citation) -> CaseCheck | None:
    """None if `citation` isn't a case. Otherwise whether the index could check it (only a
    medium neutral citation can be) and, if it's wrong, a warning saying why."""
    source = citation.source
    if not isinstance(source, CaseSource):
        return None
    if not (source.court_id and source.year and source.judgment_number):
        return CaseCheck(False)
    court, year = source.court_id, source.year.strip()
    number = source.judgment_number.strip().lstrip("0")
    numbers = _index()["courts"].get(court, {}).get("years", {}).get(year)
    if not number.isdigit() or not numbers:
        return CaseCheck(False)
    mnc = f"[{year}] {court} {number}"
    if number in numbers:
        names = numbers[number] if isinstance(numbers[number], list) else [numbers[number]]
        if not any(same_case(source.name, name) for name in names):
            return CaseCheck(True, f"Case name mismatch: {mnc} is '{names[0]}', not '{source.name}'")
        return CaseCheck(True)
    # Well past the year's last decision, not just past the last one the Corpus has
    last = _last(numbers)
    if index_covers(court, year) and int(number) > last + max(3, last // 20):
        return CaseCheck(True, f"Case not found: {mnc} is past the court's last decision that year, [{year}] {court} {last}")
    return CaseCheck(False)


# --------------------------------------------------------------------------- #
# Case names
# --------------------------------------------------------------------------- #
# The index has each court's own title ('Australian Competition & Consumer Commission v
# George Weston Foods Limited & Anor'); the footnote has the author's, often shortened
# ('ACCC v George Weston Foods Ltd'). So two names are the same case unless they share no
# distinctive word at all: this flags a citation borrowed from another case, not a variant
# spelling of the right one.

# Words too common in case names to tell two cases apart
_COMMON = frozenset(
    """
    v and the of for in on by a an as to re ex parte matter application appeal appeals
    pty ltd limited co company inc incorporated corp corporation plc llc nl holdings group
    anor ors another others no t as trading
    r rex regina queen king crown the commonwealth state cth nsw
    attorney general attorneygeneral director public prosecutions dpp
    minister ministers commissioner commissioners deputy chief secretary department
    taxation tax immigration citizenship multicultural ethnic affairs border protection home
    indigenous services council shire city municipal local government authority
    australia australian new south wales victoria queensland western tasmania northern territory capital
    commission board tribunal court registrar trustee trustees bank
    """.split()
)


def _words(name: str) -> set[str]:
    name = re.sub(r"\[No\s*\d+\]|\(No\s*\d+\)", " ", name, flags=re.I)
    words = re.findall(r"[a-z0-9]+", name.lower().replace("’", "'").replace("'", ""))
    return {w for w in words if w not in _COMMON and not w.isdigit()}


def _match(a: str, b: str) -> bool:
    """'aust' ~ 'australian', 'commr' is common anyway; anonymised names ('agv20') exactly."""
    return a == b or (min(len(a), len(b)) >= 4 and (a.startswith(b) or b.startswith(a)))


def same_case(cited: str, indexed: str) -> bool:
    """Whether `cited` could be a name for the decision titled `indexed`. A name with no
    distinctive words ('R v R', 'Re an Application') can't be checked, so it passes."""
    mine, theirs = _words(cited), _words(indexed)
    if not mine or not theirs:
        return True
    return any(_match(a, b) for a in mine for b in theirs)
