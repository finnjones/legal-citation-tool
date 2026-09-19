"""Generate examples/test_essay.docx: a short law essay whose footnotes use messy,
inconsistent, non-AGLC citation styles, for trying the tool end to end.

    uv run python examples/make_test_essay.py

Markup below: *italic*, and [n] in body text places footnote n.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests" / "fixtures"))
from build_fixtures import build_docx  # noqa: E402

OUT = Path(__file__).resolve().parent / "test_essay.docx"

TITLE = "Duty, Policy and Statute: The Modern Law of Negligence in Australia"

BODY = [
    "The modern law of negligence traces its origins to Lord Atkin's neighbour principle.[1] "
    "In Australia, however, the High Court has repeatedly cautioned against treating "
    "reasonable foreseeability as sufficient to establish a duty of care.[2] The Court has "
    "instead emphasised the need for coherence with other legal obligations.[3]",

    "The rejection of a single unifying test was made explicit in the context of pure "
    "economic loss.[4] Even so, the neighbour principle continues to be invoked,[5] and "
    "its influence remains visible in the statutory reforms that followed the insurance "
    "crisis of the early 2000s.",

    "Those reforms now largely govern the breach inquiry. The New South Wales provisions "
    "restate the common law calculus of negligence,[6] while also setting out the factors "
    "a court must consider.[7] Other jurisdictions adopted similar, though not identical, "
    "provisions.[8] The reforms were driven by the recommendations of the Ipp Panel.[9]",

    "The vulnerability of the plaintiff has emerged as an important consideration.[10] "
    "Commentators have long observed that the law of torts resists reduction to a single "
    "principle,[11] and the High Court has continued to decide cases on their own "
    "facts.[12] Some theorists would go further and deny that legal reasoning can be "
    "separated from moral reasoning at all.[13] Others remain sceptical.[14]",

    "Beyond private law, questions of duty increasingly intersect with privacy,[15] "
    "constitutional limits on legislative power,[16] and Australia's international "
    "obligations.[17] Whether judges reason morally when resolving such questions remains "
    "contested.[18]",

    "Public commentary on the Court has intensified since the appointment of its first "
    "female Chief Justice,[19] and the Court now publishes detailed biographical material "
    "about its members.[20] The central cases nonetheless continue to be read "
    "together.[21] The statutory test, too, remains the starting point.[22]",

    "Ultimately, the enduring lesson is the one drawn in Sullivan: duties must cohere with "
    "the wider legal system.[23] Leading texts continue to organise the law around that "
    "insight.[24]",
]

FOOTNOTES = {
    1: "Donoghue v. Stevenson [1932] A.C. 562 at 580 per Lord Atkin.",
    2: "*Sullivan v Moody* (2001) 207 C.L.R. 562 at [42].",
    3: "Ibid. at [50]-[53].",
    4: "See: Perre v. Apand Pty. Ltd. (1999) 198 C.L.R. 180 (hereafter \"Perre\").",
    5: "*Donoghue v Stevenson*, supra n 1, p. 599.",
    6: "Civil Liability Act 2002 (N.S.W.), section 5B(1).",
    7: "Ibid, s. 5B(2).",
    8: "See also *Wrongs Act 1958* (Vic.) s 48; cf. Civil Liability Act 2003 (Qld) s 9.",
    9: "Review of the Law of Negligence: Final Report (September 2002) at 25-27.",
    10: "Perre, above n 4, at 225 per McHugh J.",
    11: "Harold Luntz, \"A Personal Journey through the Law of Torts\" (2005) 27(3) Sydney Law Review 393, at 400.",
    12: "Kuhl v Zurich Financial Services Australia Ltd [2011] HCA 11 at para 20.",
    13: "For a strong statement of this view, see Ronald Dworkin, *Justice for Hedgehogs* (Belknap Press 2011) p 10.",
    14: "Luntz, op cit, 402.",
    15: "Australian Law Reform Commission, For Your Information: Australian Privacy Law and Practice, "
        "Report No. 108 (May 2008) vol 1 at 339.",
    16: "Commonwealth Constitution s.51(xxix).",
    17: "International Covenant on Civil and Political Rights, opened for signature 16 December 1966, "
        "999 U.N.T.S. 171 (entered into force 23 March 1976), article 14.",
    18: "Jeremy Waldron, 'Do Judges Reason Morally?', in G Huscroft (ed.), *Expounding the Constitution: "
        "Essays in Constitutional Theory*, Cambridge University Press, 2008, p. 38.",
    19: "Stephanie Peatling, \"Female Chief Justice Rewrites the Script\", The Age (Melbourne), 31 January 2017, p. 6.",
    20: "High Court of Australia, \"James Edelman\", http://www.hcourt.gov.au/justices/current/justice-james-edelman",
    21: "Sullivan v Moody, above n 2, [62]; Perre, above n 4, 253 (Gummow J).",
    22: "Civil Liability Act 2002 (NSW) s 5B.",
    23: "The majority emphasised coherence with other legal duties: Sullivan, above n 2, at [55]-[60].",
    24: "Fleming's The Law of Torts, ed C Sappideen & P Vines, 10th edn, Lawbook Co., 2011, pp. 150-155.",
}


def _italic_tokens(text: str) -> list[tuple]:
    """'a *b* c' -> [("text", "a ", False), ("text", "b", True), ("text", " c", False)]"""
    return [("text", part, i % 2 == 1) for i, part in enumerate(text.split("*")) if part]


def _body_tokens(text: str) -> list[tuple]:
    tokens: list[tuple] = []
    for part in re.split(r"(\[\d+\])", text):
        if m := re.fullmatch(r"\[(\d+)\]", part):
            tokens.append(("fnref", int(m.group(1))))
        elif part:
            tokens += _italic_tokens(part)
    return tokens


def main() -> Path:
    body = [("heading", TITLE)] + [("para", _body_tokens(p)) for p in BODY]
    notes = [(n, [_italic_tokens(text)]) for n, text in sorted(FOOTNOTES.items())]
    return build_docx(OUT, body, notes)


if __name__ == "__main__":
    print(f"wrote {main()}")
