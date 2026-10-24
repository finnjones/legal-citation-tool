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
        # repeat the last response if asked again (eg the single-footnote retry)
        return self._responses[min(i, len(self._responses) - 1)]


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
    result = Extractor(provider, verify=False).extract(footnotes)
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
    result = Extractor(provider, verify=False).extract(footnotes)
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
    result = Extractor(provider, verify=False).extract(footnotes)
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
    result = Extractor(provider, verify=False).extract(footnotes)
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
    result = Extractor(provider, verify=False).extract(footnotes)
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
    result = Extractor(provider, verify=False).extract(footnotes)
    seg2 = result[1].segments[0]
    assert isinstance(seg2, CitationSegment)
    assert seg2.citation.source.type == "case"
    assert seg2.citation.source.name == "Mabo v Queensland [No 2]"
    assert seg2.citation.pinpoints[0].value == "45"


def test_ibid_bare_takes_the_pinpoint_before_it():
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
    result = Extractor(provider, verify=False).extract(footnotes)
    seg2 = result[1].segments[0]
    assert seg2.citation.source.name == "Mabo v Queensland [No 2]"
    # r 1.4.3: a bare 'Ibid' means the same pinpoint, not the whole source
    assert [p.value for p in seg2.citation.pinpoints] == ["42"]


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
    result = Extractor(provider, verify=False).extract(footnotes)
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
    result = Extractor(provider, verify=False).extract(footnotes)
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
    result = Extractor(provider, verify=False).extract(footnotes)
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
    result = Extractor(provider, batch_size=1, verify=False).extract(footnotes)
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
    Extractor(provider, batch_size=1, verify=False).extract(footnotes)
    assert len(provider.calls) == 2
    assert "this is the first batch" in provider.calls[0]["user"]
    assert "n1: case" in provider.calls[1]["user"]
    assert "Mabo v Queensland [No 2]" in provider.calls[1]["user"]


def test_batching_splits_footnotes_into_correctly_sized_groups():
    footnotes = [fn(i, f"Footnote text {i}.") for i in range(1, 6)]
    provider = CannedProvider(echo_responses)
    Extractor(provider, batch_size=2, verify=False).extract(footnotes)
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
    extractor = Extractor(provider, verify=False)
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
    extractor = Extractor(provider, verify=False)
    result = extractor.extract(footnotes)
    seg = result[0].segments[0]
    assert isinstance(seg.citation.source, OtherSource)
    assert any("footnote 2" in w and "could not resolve" in w for w in extractor.warnings)


def test_batch_failure_leaves_footnotes_unchanged_and_records_warning():
    footnotes = [fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1.")]
    # invalid JSON for every retry attempt inside generate_json (default max_attempts=3)
    provider = CannedProvider(["not valid json"] * 3)
    extractor = Extractor(provider, verify=False)
    result = extractor.extract(footnotes)
    assert result[0].segments == []
    assert len(provider.calls) == 3
    assert any("failed" in w and "1" in w for w in extractor.warnings)


def _asked_for(user: str) -> list[int]:
    return [int(n) for n in re.findall(r"Footnote (\d+):", user)]


def test_empty_reply_then_success_extracts_batch():
    footnotes = [fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1.")]
    provider = CannedProvider(lambda i, s, u: "" if i == 0 else echo_responses(i, s, u))
    extractor = Extractor(provider, verify=False)
    result = extractor.extract(footnotes)
    assert result[0].segments and result[0].extraction_failed is None
    assert len(provider.calls) == 2
    assert not any("failed" in w for w in extractor.warnings)


def test_failed_batch_is_split_into_fives_before_giving_up():
    footnotes = [fn(n, f"Commentary number {n}.") for n in range(1, 16)]
    # the provider sends empty replies for the big request, but answers smaller ones
    provider = CannedProvider(lambda i, s, u: "" if len(_asked_for(u)) > 5 else echo_responses(i, s, u))
    extractor = Extractor(provider, verify=False)
    result = extractor.extract(footnotes)
    assert all(f.segments and f.extraction_failed is None for f in result)
    sizes = [len(_asked_for(c["user"])) for c in provider.calls]
    assert sizes == [15, 15, 15, 5, 5, 5]
    assert not any("failed" in w for w in extractor.warnings)


def test_failed_batch_is_split_down_to_single_footnotes():
    footnotes = [fn(n, f"Commentary number {n}.") for n in range(1, 8)]
    provider = CannedProvider(lambda i, s, u: "" if len(_asked_for(u)) > 1 else echo_responses(i, s, u))
    extractor = Extractor(provider, verify=False)
    result = extractor.extract(footnotes)
    assert all(f.segments and f.extraction_failed is None for f in result)
    asked_alone = [_asked_for(c["user"]) for c in provider.calls if len(_asked_for(c["user"])) == 1]
    assert asked_alone == [[n] for n in range(1, 8)]


def test_split_batches_keep_resolving_references_in_order():
    footnotes = [
        fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1."),
        *[fn(n, f"Commentary number {n}.") for n in range(2, 7)],
        fn(7, "Ibid 45."),
    ]
    mabo = cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1", {"source": case("Mabo v Queensland [No 2]", year="1992")})
    ibid = cite_seg("Ibid 45", {"source": {"type": "other", "text": "Ibid"}, "pinpoints": [{"value": "45"}]}, refers_to_footnote=1)

    def respond(i: int, system: str, user: str) -> str:
        numbers = _asked_for(user)
        if len(numbers) > 5:
            return ""
        segs = {1: [mabo], 7: [ibid]}
        return batch_json([{"number": n, "segments": segs.get(n, [text_seg(f"Commentary number {n}.")])} for n in numbers])

    result = Extractor(CannedProvider(respond), verify=False).extract(footnotes)
    assert isinstance(result[6].segments[0].citation.source, CaseSource)


def test_provider_down_records_failure_reason_on_each_footnote():
    footnotes = [fn(n, f"Commentary number {n}.") for n in range(1, 16)]
    provider = CannedProvider([""])
    extractor = Extractor(provider, verify=False)
    result = extractor.extract(footnotes)
    assert [f.extraction_failed for f in result] == ["provider_error"] * 15
    assert all(f.segments == [] for f in result)
    # stops splitting once the provider looks down, rather than asking for every footnote
    assert len(provider.calls) == 3 * Extractor.max_failures_in_a_row
    failed = [w for w in extractor.warnings if w.startswith("extraction failed")]
    assert failed and sorted(int(n) for w in failed for n in re.findall(r"\d+", w.split("]")[0])) == list(range(1, 16))


def test_footnote_missing_from_every_answer_is_marked_not_returned():
    footnotes = [fn(1, "Commentary one."), fn(2, "Commentary two.")]
    provider = CannedProvider(lambda i, s, u: batch_json([{"number": 1, "segments": [text_seg("Commentary one.")]}]))
    result = Extractor(provider, verify=False).extract(footnotes)
    assert result[0].extraction_failed is None
    assert result[1].extraction_failed == "not_returned"


def test_deliberately_unchanged_footnote_is_not_marked_as_failed():
    # the extraction keeps dropping '175 CLR 1', so strict mode keeps the footnote as written
    footnotes = [fn(1, "Mabo v Queensland [No 2] (1992) 175 CLR 1.")]
    provider = CannedProvider([batch_json([{"number": 1, "segments": [
        cite_seg("Mabo v Queensland [No 2] (1992) 175 CLR 1", {"source": case("Mabo v Queensland [No 2]", year="1992")})
    ]}])])
    extractor = Extractor(provider)
    result = extractor.extract(footnotes)
    assert any("left unchanged for manual review" in w for w in extractor.warnings)
    assert result[0].extraction_failed is None


def test_fallback_model_used_by_extractor():
    footnotes = [fn(n, f"Commentary number {n}.") for n in range(1, 4)]
    primary = CannedProvider([""])
    primary.fallback = backup = CannedProvider(echo_responses)
    result = Extractor(primary, verify=False).extract(footnotes)
    assert all(f.segments and f.extraction_failed is None for f in result)
    assert len(primary.calls) == 3 and len(backup.calls) == 1


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
    extractor = Extractor(provider, verify=False)
    result = extractor.extract(footnotes)
    assert result[1].segments == []
    assert any("footnote 2" in w for w in extractor.warnings)


def test_llm_returns_empty_segments_for_nonempty_footnote_falls_back_to_original_text():
    footnotes = [fn(1, "This is pure commentary with no citation.")]
    provider = CannedProvider([batch_json([{"number": 1, "segments": []}])])
    extractor = Extractor(provider, verify=False)
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
    result = Extractor(provider, verify=False).extract([footnote])
    segs = result[0].segments
    assert len(segs) == 3
    mabo_seg = segs[1]
    assert isinstance(mabo_seg, TextSegment)
    assert mabo_seg.text.text == "Mabo"
    assert mabo_seg.text.runs[0].italic is True
    # the plain runs around it stayed plain
    assert segs[0].text.runs[0].italic is False
    assert segs[2].text.runs[0].italic is False


def test_text_not_found_verbatim_is_replaced_by_the_original_text():
    footnote = fn_rich(1, [("Mabo", True), (" is a case.", False)])
    provider = CannedProvider(
        [
            batch_json(
                [
                    {
                        # LLM mis-copies "Mabo" as "Maboo", which is not in the original: its
                        # text is never emitted; the original's "Mabo" is kept in its place.
                        "number": 1,
                        "segments": [text_seg("Maboo"), text_seg(" is a case.")],
                    }
                ]
            )
        ]
    )
    extractor = Extractor(provider, verify=False)
    segs = extractor.extract([footnote])[0].segments
    assert "".join(s.text.text for s in segs) == "Mabo is a case."
    assert segs[0].text.runs[0].italic is True  # the original's own italic run
    assert any("not in the footnote: 'Maboo'" in w for w in extractor.warnings)


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
    extractor = Extractor(provider, verify=False)
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
    Extractor(provider, verify=False).extract(footnotes)
    system_prompt = provider.calls[0]["system"]
    assert len(system_prompt) > 500
    assert "AGLC4" in system_prompt
    assert "Ibid" in system_prompt


# --------------------------------------------------------------------------- #
# Subsequent references are resolved by rule, not by the model's say-so
# --------------------------------------------------------------------------- #

MABO = "Mabo v Queensland [No 2] (1992) 175 CLR 1"
WIK = "Wik Peoples v Queensland (1996) 187 CLR 1"


def _mabo() -> dict:
    return cite_seg(MABO, {"source": case("Mabo v Queensland [No 2]", year="1992", volume="175", report="CLR", starting_page="1")})


def _wik() -> dict:
    return cite_seg(WIK, {"source": case("Wik Peoples v Queensland", year="1996", volume="187", report="CLR", starting_page="1")})


def _ibid(ref: int) -> dict:
    return cite_seg("Ibid 45", {"source": {"type": "other", "text": "Ibid"}, "pinpoints": [{"value": "45"}]}, refers_to_footnote=ref)


def _run(footnotes: list[Footnote], segments: dict[int, list[dict]]) -> tuple[list[Footnote], Extractor]:
    raw = batch_json([{"number": f.number, "segments": segments[f.number]} for f in footnotes])
    extractor = Extractor(CannedProvider([raw]), verify=False)
    return extractor.extract(footnotes), extractor


def test_ibid_means_the_footnote_before_whatever_footnote_the_model_named():
    result, ex = _run([fn(1, MABO + "."), fn(2, WIK + "."), fn(3, "Ibid 45.")],
                      {1: [_mabo(), text_seg(".")], 2: [_wik(), text_seg(".")], 3: [_ibid(1), text_seg(".")]})
    assert result[2].segments[0].citation.source.name == "Wik Peoples v Queensland"
    assert any("'Ibid' points to footnote 2" in w for w in ex.warnings)


def test_ibid_after_a_footnote_citing_two_sources_is_not_guessed():
    result, ex = _run([fn(1, MABO + "; " + WIK + "."), fn(2, "Ibid 45.")],
                      {1: [_mabo(), text_seg("; "), _wik(), text_seg(".")], 2: [_ibid(1), text_seg(".")]})
    assert isinstance(result[1].segments[0].citation.source, OtherSource)
    assert any("unclear" in w for w in ex.warnings)


def test_ibid_later_in_a_footnote_means_the_citation_before_it():
    result, _ = _run([fn(1, MABO + "."), fn(2, WIK + "; ibid 45.")],
                     {1: [_mabo(), text_seg(".")],
                      2: [_wik(), text_seg("; "),
                          cite_seg("ibid 45", {"source": {"type": "other", "text": "ibid"}, "pinpoints": [{"value": "45"}]},
                                   refers_to_footnote=1), text_seg(".")]})
    assert result[1].segments[2].citation.source.name == "Wik Peoples v Queensland"


def _book(author: str, title: str) -> dict:
    return {"source": {"type": "book", "authors": [author], "title": title, "publisher": "Federation Press", "year": "2020"}}


def test_a_surname_shared_by_two_sources_in_the_footnote_is_flagged_not_guessed():
    first = "Jane Smith, Torts (Federation Press, 2020); John Smith, Contracts (Federation Press, 2020)."
    result, ex = _run([fn(1, first), fn(2, "Smith (n 1) 4.")], {
        1: [cite_seg("Jane Smith, Torts (Federation Press, 2020)", _book("Jane Smith", "Torts")), text_seg("; "),
            cite_seg("John Smith, Contracts (Federation Press, 2020)", _book("John Smith", "Contracts")), text_seg(".")],
        2: [cite_seg("Smith (n 1) 4", {"source": {"type": "other", "text": "Smith"}, "pinpoints": [{"value": "4"}]},
                     refers_to_footnote=1), text_seg(".")],
    })
    assert isinstance(result[1].segments[0].citation.source, OtherSource)
    assert any("'Smith' could mean any of 2 sources" in w for w in ex.warnings)


def test_an_exact_surname_beats_one_that_merely_contains_it():
    first = "John Smithers, Torts (Federation Press, 2020); Jane Smith, Contracts (Federation Press, 2020)."
    result, _ = _run([fn(1, first), fn(2, "Smith (n 1) 4.")], {
        1: [cite_seg("John Smithers, Torts (Federation Press, 2020)", _book("John Smithers", "Torts")), text_seg("; "),
            cite_seg("Jane Smith, Contracts (Federation Press, 2020)", _book("Jane Smith", "Contracts")), text_seg(".")],
        2: [cite_seg("Smith (n 1) 4", {"source": {"type": "other", "text": "Smith"}, "pinpoints": [{"value": "4"}]},
                     refers_to_footnote=1), text_seg(".")],
    })
    assert result[1].segments[0].citation.source.title == "Contracts"


def test_a_pinpoint_borrowed_from_another_citation_in_the_footnote_is_removed():
    # 42 is Wik's pinpoint; it appears in the footnote, but not in Mabo's citation
    text = MABO + "; " + WIK + ", 42."
    mabo = cite_seg(MABO, {"source": case("Mabo v Queensland [No 2]", year="1992", volume="175", report="CLR",
                                          starting_page="1"), "pinpoints": [{"value": "42"}]})
    wik = cite_seg(WIK + ", 42", {"source": case("Wik Peoples v Queensland", year="1996", volume="187", report="CLR",
                                                 starting_page="1"), "pinpoints": [{"value": "42"}]})
    extractor = Extractor(CannedProvider([batch_json([{"number": 1, "segments": [mabo, text_seg("; "), wik, text_seg(".")]}])]))
    segs = extractor.extract([fn(1, text)])[0].segments
    assert segs[0].citation.pinpoints == [] and [p.value for p in segs[2].citation.pinpoints] == ["42"]


def test_a_pinpoint_just_outside_the_citations_original_still_counts():
    # the model's `original` stops before the pinpoint, which is still this citation's
    seg = cite_seg(MABO, {"source": case("Mabo v Queensland [No 2]", year="1992", volume="175", report="CLR",
                                         starting_page="1"), "pinpoints": [{"value": "42"}]})
    extractor = Extractor(CannedProvider([batch_json([{"number": 1, "segments": [seg]}])]))
    segs = extractor.extract([fn(1, MABO + ", 42.")])[0].segments
    assert [p.value for p in segs[0].citation.pinpoints] == ["42"]
