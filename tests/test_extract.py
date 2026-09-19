"""Tests for aglc.extract.Extractor.

Uses a canned LLMProvider test double (no network, no dependency on the concurrently-written
providers in aglc/llm/providers/) that returns pre-baked JSON strings shaped like
aglc.extract.ExtractionBatch, and records every (system, user) prompt it was asked to complete.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from aglc.extract import Extractor
from aglc.llm.base import LLMError, LLMProvider
from aglc.models import CaseSource, CitationSegment, Footnote, LegislationSource, OtherSource, RichText, TextSegment

# --------------------------------------------------------------------------- #
# Test double
# --------------------------------------------------------------------------- #


class CannedProvider(LLMProvider):
    """Returns pre-canned JSON strings instead of calling a real vendor API.

    `responses` is either a list of raw JSON strings (one per call to `_complete_json`) or a
    callable `(call_index, system, user) -> raw_json_str` for tests that need to generate a
    response based on what was actually asked.
    """

    def __init__(self, responses: list[str] | Callable[[int, str, str], str], model: str = "test-model") -> None:
        super().__init__(model)
        self._responses = responses
        self.calls: list[dict[str, Any]] = []

    def _complete_json(self, *, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        i = len(self.calls)
        self.calls.append({"system": system, "user": user, "schema_name": schema_name})
        if callable(self._responses):
            return self._responses(i, system, user)
        return self._responses[i]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def fn(number: int, text: str) -> Footnote:
    return Footnote(number=number, original=RichText.plain(text))


def fn_rich(number: int, runs: list[tuple[str, bool]]) -> Footnote:
    rt = RichText()
    for text, italic in runs:
        rt.append(text, italic)
    return Footnote(number=number, original=rt)


def batch_json(footnotes: list[dict]) -> str:
    return json.dumps({"footnotes": footnotes})


def text_seg(text: str) -> dict:
    return {"kind": "text", "text": text}


def cite_seg(original: str, citation: dict, refers_to_footnote: int | None = None) -> dict:
    return {"kind": "citation", "original": original, "citation": citation, "refers_to_footnote": refers_to_footnote}


def case(name: str, **kw: Any) -> dict:
    return {"type": "case", "name": name, **kw}


def legislation(title: str, **kw: Any) -> dict:
    return {"type": "legislation", "title": title, **kw}


def echo_responses(i: int, system: str, user: str) -> str:
    """Turn every requested footnote into a single verbatim text segment."""
    lines = re.findall(r"Footnote (\d+): (.*)", user)
    return batch_json([{"number": int(num), "segments": [text_seg(text)]} for num, text in lines])


# --------------------------------------------------------------------------- #
# Basic extraction
# --------------------------------------------------------------------------- #


def test_simple_case_citation():
    footnotes = [fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1.")]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [
                            cite_seg(
                                "Mabo v Queensland [No 2] (1992) 175 CLR 1",
                                {"source": case("Mabo v Queensland [No 2]", year="1992", volume="175", report="CLR", starting_page="1")},
                            ),
                            text_seg("."),
                        ],
                    }
                ]
            )
        ]
    )
    result = Extractor(provider).extract(footnotes)
    assert len(result) == 1
    segs = result[0].segments
    assert len(segs) == 2
    assert isinstance(segs[0], CitationSegment)
    assert segs[0].citation.source.type == "case"
    assert segs[0].citation.source.name == "Mabo v Queensland [No 2]"
    assert segs[0].citation.source.starting_page == "1"
    assert isinstance(segs[1], TextSegment)
    assert segs[1].text.text == "."


def test_pure_commentary_footnote_becomes_single_text_segment():
    footnotes = [fn(1, "This point is discussed further below.")]
    provider = CannedProvider([batch_json([{"number": 1, "segments": [text_seg("This point is discussed further below.")]}])])
    result = Extractor(provider).extract(footnotes)
    segs = result[0].segments
    assert len(segs) == 1
    assert isinstance(segs[0], TextSegment)
    assert segs[0].text.text == "This point is discussed further below."


def test_signal_mapped_into_citation_not_text():
    footnotes = [fn(1, "See Mabo v Queensland [No 2] (1992) 175 CLR 1.")]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [
                            cite_seg(
                                "Mabo v Queensland [No 2] (1992) 175 CLR 1",
                                {"source": case("Mabo v Queensland [No 2]", year="1992"), "signal": "See"},
                            ),
                            text_seg("."),
                        ],
                    }
                ]
            )
        ]
    )
    result = Extractor(provider).extract(footnotes)
    segs = result[0].segments
    assert segs[0].citation.signal == "See"
    # "See" must not leak into any text segment
    assert all("See" not in s.text.text for s in segs if isinstance(s, TextSegment))


def test_semicolon_separator_is_its_own_text_segment():
    footnotes = [fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1; Native Title Act 1993 (Cth) s 223.")]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [
                            cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1", {"source": case("Mabo v Queensland [No 2]", year="1992")}),
                            text_seg("; "),
                            cite_seg(
                                "Native Title Act 1993 (Cth) s 223",
                                {"source": legislation("Native Title Act", year="1993", jurisdiction="Cth")},
                            ),
                            text_seg("."),
                        ],
                    }
                ]
            )
        ]
    )
    result = Extractor(provider).extract(footnotes)
    segs = result[0].segments
    assert len(segs) == 4
    assert isinstance(segs[1], TextSegment)
    assert segs[1].text.text == "; "
    # the ';' never appears inside a citation's `original`
    for s in segs:
        if isinstance(s, CitationSegment):
            assert ";" not in s.original


def test_short_title_definition_captured():
    footnotes = [fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1 ('Mabo').")]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [
                            cite_seg(
                                "Mabo v Queensland [No 2] (1992) 175 CLR 1 ('Mabo')",
                                {"source": case("Mabo v Queensland [No 2]", year="1992"), "short_title": "Mabo"},
                            ),
                            text_seg("."),
                        ],
                    }
                ]
            )
        ]
    )
    result = Extractor(provider).extract(footnotes)
    assert result[0].segments[0].citation.short_title == "Mabo"


# --------------------------------------------------------------------------- #
# Subsequent references
# --------------------------------------------------------------------------- #


def test_ibid_resolves_source_from_immediately_preceding_footnote():
    footnotes = [
        fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1."),
        fn(2, "Ibid 45."),
    ]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [
                            cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1", {"source": case("Mabo v Queensland [No 2]", year="1992", volume="175", report="CLR", starting_page="1")}),
                            text_seg("."),
                        ],
                    },
                    {
                        "number": 2,
                        "segments": [
                            cite_seg(
                                "Ibid 45",
                                {"source": {"type": "other", "text": "Ibid 45"}, "pinpoints": [{"kind": "page", "value": "45", "plural": False}]},
                                refers_to_footnote=1,
                            ),
                            text_seg("."),
                        ],
                    },
                ]
            )
        ]
    )
    result = Extractor(provider).extract(footnotes)
    seg2 = result[1].segments[0]
    assert isinstance(seg2, CitationSegment)
    assert seg2.citation.source.type == "case"
    assert seg2.citation.source.name == "Mabo v Queensland [No 2]"
    assert seg2.citation.pinpoints[0].value == "45"


def test_ibid_bare_has_no_new_pinpoint():
    footnotes = [
        fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1, 42."),
        fn(2, "Ibid."),
    ]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [
                            cite_seg(
                                "Mabo v Queensland [No 2] (1992) 175 CLR 1, 42",
                                {"source": case("Mabo v Queensland [No 2]", year="1992"), "pinpoints": [{"kind": "page", "value": "42", "plural": False}]},
                            ),
                            text_seg("."),
                        ],
                    },
                    {
                        "number": 2,
                        "segments": [
                            cite_seg("Ibid", {"source": {"type": "other", "text": "Ibid"}}, refers_to_footnote=1),
                            text_seg("."),
                        ],
                    },
                ]
            )
        ]
    )
    result = Extractor(provider).extract(footnotes)
    seg2 = result[1].segments[0]
    assert seg2.citation.source.name == "Mabo v Queensland [No 2]"
    assert seg2.citation.pinpoints == []


def test_n_x_reference_disambiguated_by_short_title():
    footnotes = [
        fn(3, "Mabo v Queensland [No 2] (1992) 175 CLR 1 ('Mabo'); Native Title Act 1993 (Cth)."),
        fn(4, "Mabo (n 3) 60."),
    ]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 3,
                        "segments": [
                            cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1 ('Mabo')", {"source": case("Mabo v Queensland [No 2]", year="1992"), "short_title": "Mabo"}),
                            text_seg("; "),
                            cite_seg("Native Title Act 1993 (Cth)", {"source": legislation("Native Title Act", year="1993", jurisdiction="Cth")}),
                            text_seg("."),
                        ],
                    },
                    {
                        "number": 4,
                        "segments": [
                            cite_seg(
                                "Mabo (n 3) 60",
                                {"source": {"type": "other", "text": "Mabo (n 3) 60"}, "short_title": "Mabo", "pinpoints": [{"kind": "page", "value": "60", "plural": False}]},
                                refers_to_footnote=3,
                            ),
                            text_seg("."),
                        ],
                    },
                ]
            )
        ]
    )
    result = Extractor(provider).extract(footnotes)
    seg = result[1].segments[0]
    assert seg.citation.source.type == "case"
    assert seg.citation.source.name == "Mabo v Queensland [No 2]"
    assert seg.citation.short_title == "Mabo"
    assert seg.citation.pinpoints[0].value == "60"


def test_above_n_x_reference_resolves_same_as_n_x():
    footnotes = [
        fn(3, "Mabo v Queensland [No 2] (1992) 175 CLR 1 ('Mabo')."),
        fn(4, "Mabo, above n 3, 60."),
    ]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 3,
                        "segments": [
                            cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1 ('Mabo')", {"source": case("Mabo v Queensland [No 2]", year="1992"), "short_title": "Mabo"}),
                            text_seg("."),
                        ],
                    },
                    {
                        "number": 4,
                        "segments": [
                            cite_seg(
                                "Mabo, above n 3, 60",
                                {"source": {"type": "other", "text": "Mabo, above n 3, 60"}, "short_title": "Mabo", "pinpoints": [{"kind": "page", "value": "60", "plural": False}]},
                                refers_to_footnote=3,
                            ),
                            text_seg("."),
                        ],
                    },
                ]
            )
        ]
    )
    result = Extractor(provider).extract(footnotes)
    seg = result[1].segments[0]
    assert seg.citation.source.name == "Mabo v Queensland [No 2]"
    assert seg.citation.pinpoints[0].value == "60"


def test_reference_disambiguated_by_source_name_when_no_short_title_was_defined():
    # footnote 4 has two sources, neither with an author-defined short title; "Smith (n 4)"
    # must match by the case name rather than an exact short_title lookup.
    footnotes = [
        fn(4, "Smith v Jones [2001] HCA 1; Jones Act 2001 (Cth)."),
        fn(5, "Smith (n 4) 12."),
    ]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 4,
                        "segments": [
                            cite_seg("Smith v Jones [2001] HCA 1", {"source": case("Smith v Jones", year="2001", court_id="HCA", judgment_number="1")}),
                            text_seg("; "),
                            cite_seg("Jones Act 2001 (Cth)", {"source": legislation("Jones Act", year="2001", jurisdiction="Cth")}),
                            text_seg("."),
                        ],
                    },
                    {
                        "number": 5,
                        "segments": [
                            cite_seg(
                                "Smith (n 4) 12",
                                {"source": {"type": "other", "text": "Smith (n 4) 12"}, "short_title": "Smith", "pinpoints": [{"kind": "page", "value": "12", "plural": False}]},
                                refers_to_footnote=4,
                            ),
                            text_seg("."),
                        ],
                    },
                ]
            )
        ]
    )
    result = Extractor(provider).extract(footnotes)
    seg = result[1].segments[0]
    assert seg.citation.source.type == "case"
    assert seg.citation.source.name == "Smith v Jones"


def test_short_title_resolution_works_across_batches():
    footnotes = [
        fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1 ('Mabo')."),
        fn(2, "Mabo (n 1) 60."),
    ]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [
                            cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1 ('Mabo')", {"source": case("Mabo v Queensland [No 2]", year="1992"), "short_title": "Mabo"}),
                            text_seg("."),
                        ],
                    }
                ]
            ),
            batch_json(
                [
                    {
                        "number": 2,
                        "segments": [
                            cite_seg(
                                "Mabo (n 1) 60",
                                {"source": {"type": "other", "text": "Mabo (n 1) 60"}, "short_title": "Mabo", "pinpoints": [{"kind": "page", "value": "60", "plural": False}]},
                                refers_to_footnote=1,
                            ),
                            text_seg("."),
                        ],
                    }
                ]
            ),
        ]
    )
    result = Extractor(provider, batch_size=1).extract(footnotes)
    seg = result[1].segments[0]
    assert seg.citation.source.name == "Mabo v Queensland [No 2]"
    assert seg.citation.source.type == "case"


def test_prompt_includes_prior_source_index_across_batches():
    footnotes = [
        fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1."),
        fn(2, "Ibid 45."),
    ]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1", {"source": case("Mabo v Queensland [No 2]", year="1992")})],
                    }
                ]
            ),
            batch_json(
                [
                    {
                        "number": 2,
                        "segments": [cite_seg("Ibid 45", {"source": {"type": "other", "text": "Ibid 45"}}, refers_to_footnote=1)],
                    }
                ]
            ),
        ]
    )
    Extractor(provider, batch_size=1).extract(footnotes)
    assert len(provider.calls) == 2
    assert "this is the first batch" in provider.calls[0]["user"]
    assert "n1: case" in provider.calls[1]["user"]
    assert "Mabo v Queensland [No 2]" in provider.calls[1]["user"]


def test_batching_splits_footnotes_into_correctly_sized_groups():
    footnotes = [fn(i, f"Footnote text {i}.") for i in range(1, 6)]
    provider = CannedProvider(echo_responses)
    Extractor(provider, batch_size=2).extract(footnotes)
    assert len(provider.calls) == 3  # 5 footnotes / batch_size 2 -> batches of 2, 2, 1
    assert "Footnote 1:" in provider.calls[0]["user"] and "Footnote 2:" in provider.calls[0]["user"]
    assert "Footnote 3:" not in provider.calls[0]["user"]
    assert "Footnote 3:" in provider.calls[1]["user"] and "Footnote 4:" in provider.calls[1]["user"]
    assert "Footnote 5:" in provider.calls[2]["user"]


# --------------------------------------------------------------------------- #
# Fallbacks and error handling
# --------------------------------------------------------------------------- #


def test_unresolvable_reference_falls_back_to_other_source_and_warns():
    footnotes = [
        fn(4, "Smith v Jones [2001] HCA 1; Jones Act 2001 (Cth)."),
        fn(5, "Nonexistent (n 4) 12."),
    ]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 4,
                        "segments": [
                            cite_seg("Smith v Jones [2001] HCA 1", {"source": case("Smith v Jones", year="2001")}),
                            text_seg("; "),
                            cite_seg("Jones Act 2001 (Cth)", {"source": legislation("Jones Act", year="2001", jurisdiction="Cth")}),
                            text_seg("."),
                        ],
                    },
                    {
                        "number": 5,
                        "segments": [
                            cite_seg(
                                "Nonexistent (n 4) 12",
                                {"source": {"type": "other", "text": "Nonexistent (n 4) 12"}, "short_title": "Nonexistent", "pinpoints": [{"kind": "page", "value": "12", "plural": False}]},
                                refers_to_footnote=4,
                            ),
                            text_seg("."),
                        ],
                    },
                ]
            )
        ]
    )
    extractor = Extractor(provider)
    result = extractor.extract(footnotes)
    seg = result[1].segments[0]
    assert isinstance(seg.citation.source, OtherSource)
    assert "Nonexistent (n 4) 12" in seg.citation.source.text
    assert any("could not resolve" in w for w in extractor.warnings)


def test_reference_to_nonexistent_footnote_falls_back_and_warns():
    footnotes = [fn(2, "Ibid 45.")]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 2,
                        "segments": [
                            cite_seg("Ibid 45", {"source": {"type": "other", "text": "Ibid 45"}}, refers_to_footnote=1),
                            text_seg("."),
                        ],
                    }
                ]
            )
        ]
    )
    extractor = Extractor(provider)
    result = extractor.extract(footnotes)
    seg = result[0].segments[0]
    assert isinstance(seg.citation.source, OtherSource)
    assert any("footnote 2" in w and "could not resolve" in w for w in extractor.warnings)


def test_batch_failure_leaves_footnotes_unchanged_and_records_warning():
    footnotes = [fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1.")]
    # invalid JSON for every retry attempt inside generate_json (default max_attempts=3)
    provider = CannedProvider(["not valid json"] * 3)
    extractor = Extractor(provider)
    result = extractor.extract(footnotes)
    assert result[0].segments == []
    assert len(provider.calls) == 3
    assert any("failed" in w and "1" in w for w in extractor.warnings)


def test_missing_footnote_in_response_left_unchanged_and_warns():
    footnotes = [fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1."), fn(2, "Ibid 45.")]
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1", {"source": case("Mabo v Queensland [No 2]", year="1992")})],
                    }
                    # footnote 2 is missing from the response entirely
                ]
            )
        ]
    )
    extractor = Extractor(provider)
    result = extractor.extract(footnotes)
    assert result[1].segments == []
    assert any("footnote 2" in w for w in extractor.warnings)


def test_llm_returns_empty_segments_for_nonempty_footnote_falls_back_to_original_text():
    footnotes = [fn(1, "This is pure commentary with no citation.")]
    provider = CannedProvider([batch_json([{"number": 1, "segments": []}])])
    extractor = Extractor(provider)
    result = extractor.extract(footnotes)
    assert len(result[0].segments) == 1
    assert isinstance(result[0].segments[0], TextSegment)
    assert result[0].segments[0].text.text == "This is pure commentary with no citation."
    assert any("no segments" in w for w in extractor.warnings)


# --------------------------------------------------------------------------- #
# Italics preservation
# --------------------------------------------------------------------------- #


def test_italics_preserved_in_text_segment():
    # original footnote: 'See ' (plain) + 'Mabo' (italic) + ' for background.' (plain)
    footnote = fn_rich(1, [("See ", False), ("Mabo", True), (" for background.", False)])
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [text_seg("See "), text_seg("Mabo"), text_seg(" for background.")],
                    }
                ]
            )
        ]
    )
    result = Extractor(provider).extract([footnote])
    segs = result[0].segments
    assert len(segs) == 3
    mabo_seg = segs[1]
    assert isinstance(mabo_seg, TextSegment)
    assert mabo_seg.text.text == "Mabo"
    assert mabo_seg.text.runs[0].italic is True
    # the plain runs around it stayed plain
    assert segs[0].text.runs[0].italic is False
    assert segs[2].text.runs[0].italic is False


def test_italics_fallback_to_plain_when_text_not_found_verbatim():
    footnote = fn_rich(1, [("Mabo", True), (" is a case.", False)])
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        # LLM mis-copies "Mabo" as "Mabo " (typo/extra space) which is not a
                        # substring of the original text -> must fall back to plain, not crash.
                        "number": 1,
                        "segments": [text_seg("Maboo"), text_seg(" is a case.")],
                    }
                ]
            )
        ]
    )
    result = Extractor(provider).extract([footnote])
    segs = result[0].segments
    assert segs[0].text.text == "Maboo"
    assert segs[0].text.runs[0].italic is False  # fell back to plain, not the original's italic run


def test_trailing_uncovered_text_is_appended_verbatim():
    footnote = fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1, cited with approval.")
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        "number": 1,
                        "segments": [
                            cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1", {"source": case("Mabo v Queensland [No 2]", year="1992")}),
                            # LLM forgot to emit the trailing commentary as a text segment
                        ],
                    }
                ]
            )
        ]
    )
    extractor = Extractor(provider)
    result = extractor.extract([footnote])
    segs = result[0].segments
    assert isinstance(segs[-1], TextSegment)
    assert segs[-1].text.text == ", cited with approval."
    assert any("trailing text" in w for w in extractor.warnings)


def test_system_prompt_is_loaded_and_nonempty():
    footnotes = [fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1.")]
    provider = CannedProvider(
        [batch_json([{"number": 1, "segments": [cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1", {"source": case("Mabo v Queensland [No 2]", year="1992")})]}])]
    )
    Extractor(provider).extract(footnotes)
    system_prompt = provider.calls[0]["system"]
    assert len(system_prompt) > 500
    assert "AGLC4" in system_prompt
    assert "Ibid" in system_prompt
