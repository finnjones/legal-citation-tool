"""Fake provider for testing (no network, canned responses)."""

from typing import Any, Callable, Optional

from aglc.llm.base import LLMProvider, register_provider


@register_provider("fake")
class FakeProvider(LLMProvider):
    """Returns canned JSON responses for testing."""

    def __init__(self, model: str, **options: Any) -> None:
        super().__init__(model, **options)
        self.calls: list[dict[str, Any]] = []

        responses = options.get("responses")
        if responses is None:
            self._responses = ["{}"]
            self._callable_response = None
        elif callable(responses):
            self._responses = []
            self._callable_response = responses
        else:
            self._responses = list(responses) if responses else ["{}"]
            self._callable_response = None

        self._response_index = 0

    def _complete_json(self, *, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        """Return the next canned response."""
        # Record the call
        self.calls.append({
            "system": system,
            "user": user,
            "schema": schema,
            "schema_name": schema_name,
        })

        # Get response
        if self._callable_response:
            return self._callable_response(system, user, schema)

        if self._responses:
            response = self._responses[min(self._response_index, len(self._responses) - 1)]
            self._response_index += 1
            return response

        return "{}"
