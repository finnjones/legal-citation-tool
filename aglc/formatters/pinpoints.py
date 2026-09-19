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
    return f"{plural if p.plural else singular} {span(v)}"
