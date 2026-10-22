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


# --------------------------------------------------------------------------- #
# Citations in the running text (feedback on a case note)
# --------------------------------------------------------------------------- #

CASE_NOTE = [
    ("para", [
        ("text", "Adoption of Maynard (a pseudonym)", True),
        ("text", " [2026] NSWSC 921 ", False),
        ("text", "(‘Maynard’)", True),
        ("text", " was heard with Rees J presiding.", False),
        ("fnref", 1),
        ("text", " As per the ", False),
        ("text", "Adoption Act 2000 (NSW)", True),  # "jurisdiction should not be italicised"
        ("fnref", 2, True),
        ("text", " ", False),
        ("text", "(‘Adoption Act’)", True),
        ("text", " s 180, the judgement anonymises the parties.", False),
        ("fnref", 3),
        ("text", " The test is in the ", False),
        ("text", "Aboriginal Land Rights Act 1983 (NSW) (‘ALRA’)", True),
        ("fnref", 4, True),
        ("text", " This case attempts to clarify the law.", False),  # "Full stop needed"
    ]),
    ("para", [
        ("text", "Maynard", True),
        ("text", " was born in April 2007. ", False),
        ("text", "Maynard’s", True),  # the person, not the case
        ("text", " sworn affidavit was valid under the ", False),
        ("text", "Adoption Act", True),
        ("text", " ", False),  # "Adoption Act ⁹"
        ("fnref", 5),
        ("text", " and more.", False),
    ]),
    ("para", [
        ("text", "The legislation required the processes in s 57-64", False),  # "write 'ss'"
        ("fnref", 6),
        ("text", " to be undertaken, drawing from ", False),
        # "the medium neutral citation should not be italicised"
        ("text", "Hackett v Secretary, Department of Communities and Justice [2020] NSWCA 83", True),
        ("text", ". See also ", False),
        ("text", "Mabo", True),
        ("text", " v ", False),
        ("text", "Queensland", True),
        ("text", " and ", False),
        ("text", "Maynard’s", True),
        ("text", " Aboriginality.", False),
    ]),
]


def _italic_spans(path) -> list[list[str]]:
    """Per body paragraph, the visible italic stretches of text (changes accepted),
    ignoring italic spaces at their edges, which look the same either way."""
    out = []
    for p in _body_root(path).iter(qn("w:p")):
        spans, current = [], ""
        for r in p.iter(qn("w:r")):
            if any(a.tag == qn("w:del") for a in r.iterancestors()):
                continue
            rpr = r.find(qn("w:rPr"))
            i = rpr.find(qn("w:i")) if rpr is not None else None
            italic = i is not None and i.get(qn("w:val")) not in ("0", "false")
            text = "".join(t.text or "" for t in r.findall(qn("w:t")))
            if r.find(qn("w:footnoteReference")) is not None:
                italic, text = False, ""
            if italic:
                current += text
            elif current and text:
                spans.append(current)
                current = ""
        if current:
            spans.append(current)
        out.append([span.strip() for span in spans if span.strip()])
    return out


@pytest.fixture
def case_note(tmp_path):
    return build_docx(tmp_path / "case_note.docx", CASE_NOTE, FOOTNOTES[:6])


@pytest.mark.parametrize("track_changes", [True, False])
def test_case_note_text(case_note, tmp_path, track_changes):
    out = tmp_path / "out.docx"
    write_document(case_note, out, [], track_changes=track_changes)
    assert _visible_body(out) == [
        "Adoption of Maynard (a pseudonym) [2026] NSWSC 921 (‘Maynard’) was heard with Rees J presiding.[1]"
        " As per the Adoption Act 2000 (NSW)[2] (‘Adoption Act’) s 180, the judgement anonymises the parties.[3]"
        " The test is in the Aboriginal Land Rights Act 1983 (NSW) (‘ALRA’)[4] This case attempts to clarify the law.",
        "Maynard was born in April 2007. Maynard’s sworn affidavit was valid under the Adoption Act[5] and more.",
        "The legislation required the processes in ss 57–64[6] to be undertaken, drawing from Hackett v "
        "Secretary, Department of Communities and Justice [2020] NSWCA 83. See also Mabo v Queensland and "
        "Maynard’s Aboriginality.",
    ]
    assert _italic_spans(out) == [
        ["Adoption of Maynard (a pseudonym)", "(‘Maynard’)", "Adoption Act 2000", "(‘Adoption Act’)",
         "Aboriginal Land Rights Act 1983", "(‘ALRA’)"],
        ["Maynard", "Maynard’s", "Adoption Act"],
        ["Hackett v Secretary, Department of Communities and Justice", "Mabo v Queensland", "Maynard’s"],
    ]
    docx.Document(str(out))


def test_case_note_report(case_note, tmp_path):
    fixes = write_document(case_note, tmp_path / "out.docx", [])
    applied = [(f.footnote, f.message) for f in fixes if f.applied]
    checks = [(f.footnote, f.message) for f in fixes if not f.applied]
    assert applied == [
        (None, "‘(NSW)’ after an Act’s title set upright (AGLC4 r 3.1.2: the jurisdiction is not italicised)"),
        (None, "‘(NSW)’ after an Act’s title set upright (AGLC4 r 3.1.2: the jurisdiction is not italicised)"),
        (5, "space before the footnote number removed"),
        (None, "‘s 57-64’ changed to ‘ss 57–64’ (AGLC4 r 3.1.4: ‘ss’ for more than one section, "
               "and an en dash for a range)"),
        (None, "‘[2020] NSWCA 83’ set upright (AGLC4 ch 2: only the case name is italicised, "
               "not the year, report or medium neutral citation)"),
        (None, "‘v’ in ‘Mabo v Queensland’ italicised (AGLC4 r 2.1.1: it is part of the case name)"),
        (2, "footnote number in the text was italic; set upright"),
        (4, "footnote number in the text was italic; set upright"),
    ]
    assert checks == [
        (4, "a new sentence (‘This …’) starts after this footnote number, but the sentence before it "
            "has no full stop"),
        (None, "‘Maynard’s’ is italicised (2 times). Italicise a case name only when you mean the case; "
               "when you mean the person (‘Maynard’s affidavit’), use roman type"),
    ]


def test_provision_numbers_with_hyphens_are_left_alone(tmp_path):
    # ITAA-style provision numbers ('s 20-110(1)', 's 995-1') aren't ranges.
    src = build_docx(tmp_path / "itaa.docx", [
        ("para", [("text", "See s 20-110(1) and s 995-1 of the Act, and ss 4–9.", False)]),
    ], [])
    out = tmp_path / "out.docx"
    assert write_document(src, out, []) == []


def test_an_ascending_hyphenated_section_in_a_tax_paper_is_only_flagged(tmp_path):
    # 's 26-52' is one section of the ITAA 1997, not ss 26–52; in a paper citing that Act
    # it is reported for the author to decide, not rewritten
    src = build_docx(tmp_path / "itaa.docx", [
        ("para", [("text", "Under the Income Tax Assessment Act 1997 (Cth), s 26-52 denies the deduction.", False)]),
    ], [])
    fixes = write_document(src, tmp_path / "out.docx", [])
    assert [(f.applied, f.message) for f in fixes] == [
        (False, "‘s 26-52’: if this is a range of sections, write ‘ss 26–52’ (AGLC4 r 3.1.4); "
                "if it is one section’s number, leave it"),
    ]
    text = "\n".join(p.text for p in docx.Document(str(tmp_path / "out.docx")).paragraphs)
    assert "s 26-52 denies" in text
