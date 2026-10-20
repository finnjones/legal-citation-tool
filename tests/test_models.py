"""Tests for aglc.models helpers."""

from aglc.models import FootnoteResult, RichText


def _rt(*parts: tuple[str, bool]) -> RichText:
    r = RichText()
    for text, italic in parts:
        r.append(text, italic)
    return r


def test_visible_drops_end_whitespace_and_italic_spaces():
    rt = _rt((" ", False), ("Crimes Act ", True), ("(n 1). ", False))
    assert rt.visible().to_markup() == "*Crimes* *Act* (n 1)."
    assert _rt(("Crimes Act", True), (" (n 1).", False)).visible().to_markup() == rt.visible().to_markup()


def test_visible_keeps_a_double_space_and_real_italics():
    assert _rt(("2016)  215.", False)).visible().to_markup() == "2016)  215."
    assert _rt(("Act 1900", True)).visible() != _rt(("Act", True), (" 1900", False)).visible()


def test_changed_means_a_visible_change():
    original = _rt(("Ibid s 214A(1)(b). ", False))
    assert not FootnoteResult(number=1, original=original, formatted=_rt(("Ibid s 214A(1)(b).", False))).changed
    assert FootnoteResult(number=1, original=original, formatted=_rt(("Ibid s 214A(1)(c).", False))).changed


def test_slice_keeps_italics():
    assert _rt(("ab", True), ("cd", False)).slice(1, 3).to_markup() == "*b*c"
