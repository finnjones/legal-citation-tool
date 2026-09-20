"""Golden tests built from AGLC4's own worked examples.

Loads every ``*.json`` file in ``tests/aglc4_examples/`` (see that directory's
``README.md`` for the file format and how to add more examples) and checks
that ``formatter_for(citation).full(citation).to_markup()`` reproduces the
example exactly as the *Australian Guide to Legal Citation* (4th ed) prints
it -- minus the footnote number, any introductory signal, the short-title
definition, and the closing full stop, per ``Formatter.full``'s contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aglc.formatters.base import formatter_for
from aglc.models import Citation

EXAMPLES_DIR = Path(__file__).parent / "aglc4_examples"


def _load_examples() -> list[dict]:
    examples: list[dict] = []
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        for entry in data:
            if "expected_full" not in entry:
                continue  # eg subsequent.json holds footnote sequences (test_aglc4_subsequent.py)
            entry = dict(entry)
            entry["_file"] = path.name
            examples.append(entry)
    return examples


EXAMPLES = _load_examples()


def _id(entry: dict) -> str:
    return f"{entry['_file']}:{entry['id']}"


@pytest.mark.parametrize("entry", EXAMPLES, ids=_id)
def test_golden_example(entry: dict) -> None:
    citation = Citation.model_validate(entry["citation"])
    formatter = formatter_for(citation)
    actual = formatter.full(citation).to_markup()
    assert actual == entry["expected_full"], (
        f"AGLC4 r {entry['rule']} (guide p {entry['page']}, {entry['_file']}#{entry['id']}): "
        f"expected {entry['expected_full']!r}, got {actual!r}"
    )
