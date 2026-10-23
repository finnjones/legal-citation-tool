"""Checks that a cited case exists, against an offline index of published decisions
(aglc/data/case_index.json.gz, built by scripts/build_case_index.py from the Open
Australian Legal Corpus). Nothing is sent anywhere.

A case cited only by a report (CLR, FCR, NSWLR) is looked for by name, and counts as
checked if it is found; it is never flagged (see _check_reported).

A medium neutral citation is only flagged where the index can answer for it. Two flags:
  - name mismatch:  [1956] HCA 14 is in the index, but is a different case
  - not found:      [2015] NSWSC 9999 is well past the court's last decision that year, in
                    a year the index has (nearly) every decision of

A number inside a year's range that the index lacks is never flagged: even in complete
years the Corpus is missing some decisions (about 8% of the High Court's, 1-3% of the
Federal Court's and NSW courts'), so a gap can't tell a fake case from a real one. Other
courts, years after the index was built and years the court's site barely has are not
checked either.

The same index has the Acts and instruments in force in the Commonwealth, NSW, Queensland,
WA, SA and Tasmania, so an Act cited with the wrong year is flagged (check_legislation).
"""

from __future__ import annotations

import gzip
import json
import re
from urllib.parse import quote_plus
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from .models import CaseSource, Citation, LegislationSource

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


class Decision(NamedTuple):
    """A decision in the index: its title as the court gives it, and its medium neutral
    citation where the title has one."""
    title: str
    court: str | None = None
    year: str | None = None
    number: str | None = None

    @property
    def citation(self) -> str | None:
        return f"[{self.year}] {self.court} {self.number}" if self.number else None

    @property
    def url(self) -> str | None:
        """The judgment on AustLII, for the student to read (the tool never fetches it)."""
        if not self.number:
            return None
        jurisdiction = "nsw" if self.court.startswith("NSW") else "nf" if self.court == "NFSC" else "cth"
        return f"https://www.austlii.edu.au/cgi-bin/viewdoc/au/cases/{jurisdiction}/{self.court}/{self.year}/{self.number}.html"


class CaseCheck(NamedTuple):
    checked: bool  # the index could say whether the citation is right
    warning: str | None = None  # what's wrong with it, if anything
    found: Decision | None = None  # the decision it is, when it's right


def check_legislation(citation: Citation) -> str | None:
    """A warning if an Act or instrument is in the index for its jurisdiction under a
    different year ('Evidence Act 1993 (Cth)': the one in force is 1995), else None.

    The index has only what was in force (and Tasmania's repealed Acts), so an Act it lacks
    is never flagged, and the warning allows for an earlier Act of the same name that has
    since been repealed ('Mental Health Act 1990 (NSW)' before the 2007 Act)."""
    source = citation.source
    if not isinstance(source, LegislationSource) or source.kind not in ("act", "delegated"):
        return None
    year, jurisdiction = (source.year or "").strip(), (source.jurisdiction or "").strip()
    entry = _index().get("legislation", {}).get(jurisdiction, {}).get(legislation_key(source.title or ""))
    if not year or not entry or year in entry[1]:
        return None
    title, years = entry
    return f"Legislation year: the {title} ({jurisdiction}) in force is from {' or '.join(years)}, not {year}"


def legislation_key(title: str) -> str:
    """'Railway Discontinuance Act (No. 2)' -> 'railway discontinuance act no 2', as
    scripts/build_case_index.py keys the index."""
    return " ".join(re.findall(r"[a-z0-9]+", title.lower().replace("&", " and ")))


def search_url(name: str) -> str:
    """A web search for a case on AustLII and Jade, for the student to check one the index
    couldn't. Neither site's own search can be linked to: AustLII's turns away automated
    checks of the link, and Jade's needs signing in."""
    query = f'"{name}" site:austlii.edu.au OR site:jade.io'
    return f"https://www.google.com/search?q={quote_plus(query)}"


def check_citation(citation: Citation) -> CaseCheck | None:
    """None if `citation` isn't a case. Otherwise whether the index could check it (a
    medium neutral citation, or a case found by name for a report in _REPORTS) and, if
    it's wrong, a warning saying why."""
    source = citation.source
    if not isinstance(source, CaseSource):
        return None
    if not (source.court_id and source.year and source.judgment_number):
        return _check_reported(source)
    court, year = source.court_id, source.year.strip()
    number = source.judgment_number.strip().lstrip("0")
    numbers = _index()["courts"].get(court, {}).get("years", {}).get(year)
    if not number.isdigit() or not numbers:
        return CaseCheck(False)
    mnc = f"[{year}] {court} {number}"
    if number in numbers:
        names = numbers[number] if isinstance(numbers[number], list) else [numbers[number]]
        same = [name for name in names if same_case(source.name, name)]
        if not same:
            return CaseCheck(True, f"Case name mismatch: {mnc} is '{names[0]}', not '{source.name}'")
        return CaseCheck(True, found=Decision(same[0], court, year, number))
    # Well past the year's last decision, not just past the last one the Corpus has
    last = _last(numbers)
    if index_covers(court, year) and int(number) > last + max(3, last // 20):
        return CaseCheck(True, f"Case not found: {mnc} is past the court's last decision that year, [{year}] {court} {last}")
    return CaseCheck(False)


# --------------------------------------------------------------------------- #
# Reported cases
# --------------------------------------------------------------------------- #
# A case cited only by its report ('(2006) 229 CLR 1') has no number to look up, but the
# authorised reports each report one court's decisions, so the case can be looked for by
# name among that court's decisions of the report's year or the year before (a decision
# of December 2005 is reported in 2006). Finding it confirms the case exists; not finding
# it proves nothing, so it is never flagged: the Corpus lacks some of the most cited
# decisions of all ('Pape v Federal Commissioner of Taxation' (2009) 238 CLR 1,
# 'Momcilovic v The Queen' (2011) 245 CLR 1), under any title.
#
# report -> the courts whose decisions it reports
_REPORTS = {
    "CLR": ("HCA", "UKPCHCA"),
    "FCR": ("FCA", "FCAFC"),
    "NSWLR": ("NSWCA", "NSWSC", "NSWCCA", "NSWLEC", "NSWDC"),
}
# The site a court's decisions come from, for the decisions whose titles have no number
_SITE = {"HCA": "HCA", "UKPCHCA": "HCA", "FCA": "FCA", "FCAFC": "FCA"}


def _check_reported(source: CaseSource) -> CaseCheck:
    courts = _REPORTS.get((source.report or "").strip())
    year = (source.year or "").strip()
    if not courts or not year.isdigit() or not _parties(source.name):
        return CaseCheck(False)
    years = [str(int(year) - 1), year]
    found = next((d for d in _decisions(courts, years) if plausible_name(source.name, d.title)), None)
    return CaseCheck(found is not None, found=found)


def _decisions(courts: tuple[str, ...], years: list[str]):
    """Every decision the index has for `courts` in `years`, those without a number last."""
    index = _index()
    for court in courts:
        for y in years:
            for number, names in index["courts"].get(court, {}).get("years", {}).get(y, {}).items():
                for name in names if isinstance(names, list) else [names]:
                    yield Decision(name, court, y, number)
    for site in sorted({_SITE.get(c, "NSW") for c in courts}):
        unnumbered = index.get("unnumbered", {}).get(site, {})
        for y in [*years, "?"]:
            for title in unnumbered.get(y, []):
                yield Decision(title)


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


# Searching a year's decisions for a reported case needs a closer match than comparing two
# names for one citation: one shared word would match something among the Federal Court's
# 1,500 decisions a year. So every party named must match, though one word of each will do
# ('Kvelde v The State of New South Wales' ~ 'Kvelde v New South Wales'). Words that
# identify no party ('Pty Ltd', 'R', 'Re') are left out; place names count here.
_FILLER = frozenset(
    """
    v and the of for in on by a an as to at ex parte re matter application appeal appeals
    pty ltd limited co company inc incorporated corp corporation plc llc nl
    anor ors another others no t trading r rex regina queen king
    plaintiff plaintiffs applicant applicants respondent respondents appellant appellants
    """.split()
)


#: Abbreviations in case names (r 2.1.10 and common usage) and the words they stand for.
#: Words are matched whole: by prefix, 'Johnson' would match 'John Holland'.
_ABBREVIATIONS = {
    "aust": "australia", "commr": "commissioner", "dept": "department", "govt": "government",
    "intl": "international", "assn": "association", "bros": "brothers", "natl": "national",
    "cth": "commonwealth", "fed": "federal",
}


def _tokens(name: str) -> list[str]:
    name = re.sub(r"\[No\s*\d+\]|\(No\s*\d+\)", " ", name, flags=re.I).replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", name.lower().replace("’", "'").replace("'", ""))
    return [_ABBREVIATIONS.get(w, w) for w in words]


def _parties(name: str) -> list[list[str]]:
    """'Re Colina; Ex parte Torney' -> [['colina'], ['torney']]; parties with no words dropped."""
    parts = re.split(r"\s+v\s+|;|\bex parte\b", name, flags=re.I)
    return [words for part in parts if (words := [w for w in _tokens(part) if w not in _FILLER])]


def _initials(words: list[str]) -> str:
    """'Australian Competition and Consumer Commission' -> 'accc'."""
    return "".join(w[0] for w in words if w not in ("and", "of", "the", "for"))


def plausible_name(cited: str, title: str) -> bool:
    """Whether the decision titled `title` could be the case cited as `cited`: every party
    has a word in the title, or initials of it ('ACCC', 'NSW'), or the other way round."""
    words = _tokens(title)
    title_words, title_initials = set(words), _initials(words)

    def matches(party: list[str]) -> bool:
        return any(
            w in title_words
            or (w == "australia" and "australian" in title_words)
            or (len(w) >= 3 and w in title_initials)
            or any(len(t) >= 3 and t in _initials(party) for t in title_words if t not in _FILLER)
            for w in party
        )

    return all(matches(party) for party in _parties(cited))
