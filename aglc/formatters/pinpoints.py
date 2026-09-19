"""Pinpoint rendering (AGLC4 r 1.1.6, 2.5, 3.1.4)."""

from __future__ import annotations

from ..models import Pinpoint, PinpointKind

_LABELS: dict[PinpointKind, tuple[str, str]] = {
    PinpointKind.section: ("s", "ss"),
    PinpointKind.part: ("pt", "pts"),
    PinpointKind.division: ("div", "divs"),
    PinpointKind.schedule: ("sch", "schs"),
    PinpointKind.regulation: ("reg", "regs"),
    PinpointKind.rule: ("r", "rr"),
    PinpointKind.clause: ("cl", "cls"),
    PinpointKind.article: ("art", "arts"),
    PinpointKind.chapter: ("ch", "chs"),
    PinpointKind.annex: ("annex", "annexes"),
    PinpointKind.volume: ("vol", "vols"),
    PinpointKind.book: ("bk", "bks"),
}


def span(value: str) -> str:
    """AGLC uses an en dash for ranges (r 1.1.6)."""
    return value.replace("--", "–").replace("-", "–")


def render_pinpoint(p: Pinpoint) -> str:
    v = p.value.strip()
    if p.kind is PinpointKind.other:
        return v
    if p.kind is PinpointKind.page:
        return span(v)
    if p.kind is PinpointKind.paragraph:
        v = span(v.strip("[]"))
        return f"[{v}]".replace("–", "]–[") if "–" in v and "]" not in v else f"[{v}]"
    if p.kind is PinpointKind.footnote:
        return v if " n " in v else f"n {v}"
    singular, plural = _LABELS[p.kind]
    label = plural if p.plural else singular
    # A single provision can't be a range, so its hyphen is part of the number
    # (eg ITAA 1997 's 20-110(1)(a)', r 3.1.4); only plural labels take en dashes.
    value = span(v) if p.plural else v.replace(")-(", ")–(")
    return f"{label} {value}" if v else label
