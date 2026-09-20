"""Golden tests for the document pass (ibid, '(n x)', short titles, signals, multiple
sources): footnote sequences taken verbatim from AGLC4 chapter 1's worked examples."""

import json
from pathlib import Path

import pytest

from aglc.document import render_document
from aglc.models import Citation, CitationSegment, Footnote, OtherSource, RichText

SEQUENCES = json.loads((Path(__file__).parent / "aglc4_examples" / "subsequent.json").read_text())


@pytest.mark.parametrize("seq", SEQUENCES, ids=[s["id"] for s in SEQUENCES])
def test_aglc4_footnote_sequence(seq):
    footnotes = []
    for f in seq["footnotes"]:
        # The guide elides footnotes between examples ('…'); an elided footnote cites
        # something else, which matters for ibid, so fill gaps with an unrelated source.
        while footnotes and footnotes[-1].number + 1 < f["number"]:
            n = footnotes[-1].number + 1
            filler = Citation(source=OtherSource(text=f"Elided source {n}"), source_key=f"elided-{n}")
            footnotes.append(Footnote(number=n, original=RichText.plain(""), segments=[CitationSegment(citation=filler)]))
        footnotes.append(Footnote(
            number=f["number"],
            original=RichText.plain(""),
            segments=[CitationSegment(citation=Citation.model_validate(c)) for c in f["citations"]],
        ))
    result = render_document(footnotes, bibliography=False)
    by_number = {r.number: r for r in result.footnotes}
    for f in seq["footnotes"]:
        got = by_number[f["number"]]
        assert got.formatted.to_markup() == f["expected"], (
            f"AGLC4 r {seq['rule']} (PDF p {seq['page']}), footnote {f['number']}"
        )
