"""Google Gemini provider using native structured outputs."""

from typing import Any

from aglc.llm.base import LLMError, LLMProvider, register_provider

from ._common import schema_instructions


@register_provider("gemini")
class GeminiProvider(LLMProvider):
    """Uses Google Gemini with native JSON schema structured outputs."""

    def __init__(self, model: str, **options: Any) -> None:
        super().__init__(model, **options)
        self._client = None
        self._use_fallback = False

    @property
    def client(self):
        """Lazy-load the Gemini client."""
        if self._client is None:
            try:
                from google import genai
            except ImportError:
                raise LLMError(
                    'Gemini provider requires the "google-genai" package. '
                    'Install with: pip install "aglc[gemini]"'
                )
            self._client = genai.Client(api_key=self.options.get("api_key"))
        return self._client

    def _complete_json(self, *, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        """Generate JSON using Gemini's native structured output."""
        from google.genai import types

        if self._use_fallback:
            # Use prompt mode with schema instructions
            system = system + "\n\n" + schema_instructions(schema)
            config = types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="text/plain",
            )
        else:
            try:
                config = types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                )
            except (AttributeError, TypeError, ValueError):  # pydantic ValidationError is a ValueError
                # response_json_schema not supported; use prompt mode
                self._use_fallback = True
                system = system + "\n\n" + schema_instructions(schema)
                config = types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="text/plain",
                )

        response = self.client.models.generate_content(
            model=self.model,
            contents=user,
            config=config,
        )

        return response.text
