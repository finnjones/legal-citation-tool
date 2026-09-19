"""LLM-driven extraction: raw footnote text -> structured segments.
CONTRACT (implemented by workstream agent)."""

from __future__ import annotations

from .llm.base import LLMProvider
from .models import Footnote


class Extractor:
    def __init__(self, provider: LLMProvider, batch_size: int = 15) -> None:
        self.provider = provider
        self.batch_size = batch_size

    def extract(self, footnotes: list[Footnote]) -> list[Footnote]:
        """Return copies of `footnotes` with `.segments` filled in."""
        raise NotImplementedError
