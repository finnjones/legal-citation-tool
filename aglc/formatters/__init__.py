"""Formatter registry. Importing a module registers its formatters."""

from .base import BIB_ORDER, Formatter, formatter_for, missing

__all__ = ["BIB_ORDER", "Formatter", "formatter_for", "missing"]


def _load_all() -> None:
    from . import cases, legislation, other, secondary, treaties  # noqa: F401


_load_all()
