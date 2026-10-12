"""Tests for aglc.body: footnote reference marks and headings in the body text.

The cases come from marker feedback on a real essay: "Footnote placement is
consistently incorrect" ("(Crimes Act)¹."), "Footnotes should not be italicised"
(reference marks typed after an italic title), and "Keep with text" (headings
stranded at the foot of a page).
"""

from __future__ import annotations

import zipfile

import docx
import pytest

from aglc.docx_io import DOCUMENT_PATH, _parse_xml, qn, read_footnotes, write_document

from tests.fixtures.build_fixtures import build_docx

FOOTNOTES = [(i, [[("text", f"Source {i}.", False)]]) for i in range(1, 8)]

BODY = [
    ("heading", "Introduction"),  # Heading 1: keepNext already comes from the style
    ("para", [
        ("text", "Dorek will be charged under the ", False),
        ("text", "Crimes Act 1900", True),
        ("text", " (NSW) (", False),
        ("text", "Crimes Act", True),
        ("text", ")", False),
        ("fnref", 1),
        ("text", ". The burden rests on the prosecution", False),
        ("fnref", 2),
        ("text", ". The deceased was a human being", False),
        ("fnref", 3),
        ("text", ", as per the ", False),
        ("text", "Human Tissue Act 1983", True),
        ("text", " (NSW).", False),
        ("fnref", 4, True),
        ("text", " The operating and substantial", False),
        ("fnref", 5),
        ("text", " cause – drawing from ", False),
        ("text", "Jordan", True),
        ("fnref", 6, True),
        ("text", " – was the act.", False),
    ]),
    ("bold_heading", "Reckless Indifference to Human Life"),
    ("blank", None),
    ("para", [
        ("text", "Recklessness requires foresight of death", False),
        ("fnref", 7),
        ("text", "; not merely of harm.", False),
    ]),
    ("heading", "Temporal Coincidence"),
    ("blank", None),
    ("para", [("text", "The act and intent must coincide.", False)]),
]


def _visible_body(path) -> list[str]:
    """Body paragraphs as Word shows them with tracked changes accepted,
    footnote references as [n] (by w:id)."""
    with zipfile.ZipFile(path) as z:
        root = _parse_xml(z.read(DOCUMENT_PATH))
    out = []
    for p in root.iter(qn("w:p")):
        text = ""
        for el in p.iter(qn("w:t"), qn("w:footnoteReference")):
            if any(a.tag == qn("w:del") for a in el.iterancestors()):
                continue
            text += el.text or "" if el.tag == qn("w:t") else f"[{el.get(qn('w:id'))}]"
        out.append(text)
    return out


def _body_root(path):
    with zipfile.ZipFile(path) as z:
        return _parse_xml(z.read(DOCUMENT_PATH))


@pytest.fixture
def essay(tmp_path):
    return build_docx(tmp_path / "essay.docx", BODY, FOOTNOTES)


@pytest.mark.parametrize("track_changes", [True, False])
def test_reference_marks_move_after_punctuation(essay, tmp_path, track_changes):
    out = tmp_path / "out.docx"
    write_document(essay, out, [], track_changes=track_changes)
    body = _visible_body(out)[1]
    assert body == (
        "Dorek will be charged under the Crimes Act 1900 (NSW) (Crimes Act).[1]"
        " The burden rests on the prosecution.[2]"
        " The deceased was a human being,[3] as per the Human Tissue Act 1983 (NSW).[4]"
        # mid-sentence after a word, and before a dash, are both allowed (r 1.1.2)
        " The operating and substantial[5] cause – drawing from Jordan[6] – was the act."
    )
    assert _visible_body(out)[4] == "Recklessness requires foresight of death;[7] not merely of harm."
    root = _body_root(out)
    assert (root.find(f".//{qn('w:ins')}") is not None) == track_changes
    docx.Document(str(out))  # still a valid package


def test_reference_marks_are_set_upright(essay, tmp_path):
    out = tmp_path / "out.docx"
    fixes = write_document(essay, out, [])
    root = _body_root(out)
    for ref in root.iter(qn("w:footnoteReference")):
        rpr = ref.getparent().find(qn("w:rPr"))
        assert rpr.find(qn("w:i")) is None and rpr.find(qn("w:iCs")) is None
    # the old (italic) formatting is kept as a tracked formatting change
    changes = list(root.iter(qn("w:rPrChange")))
    assert len(changes) == 2
    assert all(c.find(f"{qn('w:rPr')}/{qn('w:i')}") is not None for c in changes)
    assert sorted(f.footnote for f in fixes if "italic" in f.message) == [4, 6]


def test_headings_keep_with_their_text(essay, tmp_path):
    out = tmp_path / "out.docx"
    fixes = write_document(essay, out, [])
    paragraphs = list(_body_root(out).iter(qn("w:p")))
    keep = [p.find(f"{qn('w:pPr')}/{qn('w:keepNext')}") is not None for p in paragraphs]
    # 0 Introduction (style already keeps), 1 para, 2 bold heading, 3 blank, 4 para,
    # 5 Temporal Coincidence (style keeps), 6 blank, 7 para
    assert keep == [False, False, True, True, False, False, True, False]
    assert [f.message for f in fixes if f.footnote is None] == [
        "Heading ‘Reckless Indifference to Human Life’ set to keep with the following text, "
        "so it can't be left alone at the foot of a page",
        "Heading ‘Temporal Coincidence’ set to keep with the following text, "
        "so it can't be left alone at the foot of a page",
    ]
    assert paragraphs[2].find(f"{qn('w:pPr')}/{qn('w:pPrChange')}") is not None


def test_fix_report(essay, tmp_path):
    fixes = write_document(essay, tmp_path / "out.docx", [])
    moved = {f.footnote: f.message for f in fixes if "moved" in f.message}
    assert sorted(moved) == [1, 2, 3, 7]
    assert moved[3] == "footnote number moved after the ‘,’ (AGLC4 r 1.1.2: footnote numbers go after punctuation)"


def test_body_fixes_can_be_turned_off(essay, tmp_path):
    out = tmp_path / "out.docx"
    assert write_document(essay, out, [], fix_body=False) == []
    with zipfile.ZipFile(essay) as a, zipfile.ZipFile(out) as b:
        assert a.read(DOCUMENT_PATH) == b.read(DOCUMENT_PATH)


def test_footnotes_unaffected(essay, tmp_path):
    out = tmp_path / "out.docx"
    write_document(essay, out, [])
    assert [f.original.text for f in read_footnotes(out)] == [f"Source {i}." for i in range(1, 8)]


def test_correct_document_is_left_alone(tmp_path):
    src = build_docx(tmp_path / "ok.docx", [
        ("heading", "Introduction"),
        ("para", [("text", "A sentence.", False), ("fnref", 1), ("text", " Another, ", False),
                  ("text", "Mabo", True), ("fnref", 2), ("text", " says.", False)]),
    ], FOOTNOTES[:2])
    out = tmp_path / "out.docx"
    assert write_document(src, out, []) == []
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
        assert a.read(DOCUMENT_PATH) == b.read(DOCUMENT_PATH)
