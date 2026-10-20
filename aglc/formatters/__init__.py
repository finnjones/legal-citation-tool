"""Formatter registry. Importing a module registers its formatters."""

from .base import BIB_CASES, BIB_ORDER, BIB_SECONDARY, Formatter, formatter_for, missing

__all__ = ["BIB_CASES", "BIB_ORDER", "BIB_SECONDARY", "Formatter", "formatter_for", "missing"]


def _load_all() -> None:
    from . import cases, legislation, other, parliamentary, secondary, treaties  # noqa: F401


_load_all()
