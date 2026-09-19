"""OpenAI and OpenAI-compatible providers."""

import os
from typing import Any

from aglc.llm.base import LLMError, LLMProvider, register_provider

from ._common import schema_instructions


@register_provider("openai")
class OpenAIProvider(LLMProvider):
    """Uses OpenAI with json_schema structured outputs."""

    def __init__(self, model: str, **options: Any) -> None:
        super().__init__(model, **options)
        self._client = None
        self._use_fallback = False

    @property
    def client(self):
        """Lazy-load the OpenAI client."""
        if self._client is None:
            try:
                import openai
            except ImportError:
                raise LLMError(
                    'OpenAI provider requires the "openai" package. '
                    'Install with: pip install "aglc[openai]"'
                )
            self._client = openai.OpenAI(api_key=self.options.get("api_key"))
        return self._client

    def _complete_json(self, *, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        """Generate JSON using OpenAI's json_schema."""
        import openai

        if self._use_fallback:
            # Use json_object with schema instructions in the prompt
            system = system + "\n\n" + schema_instructions(schema)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={"type": "json_object"},
            )
        else:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": schema_name, "schema": schema, "strict": False},
                    },
                )
            except openai.BadRequestError:
                # Schema not supported; retry with json_object + instructions
                self._use_fallback = True
                system = system + "\n\n" + schema_instructions(schema)
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={"type": "json_object"},
                )

        # Check for refusal
        message = response.choices[0].message
        if message.refusal:
            raise LLMError(f"Model refused: {message.refusal}")

        return message.content


@register_provider("openai-compatible")
class OpenAICompatibleProvider(OpenAIProvider):
    """Uses OpenAI-compatible services (Ollama, LM Studio, vLLM, OpenRouter, Groq)."""

    def __init__(self, model: str, **options: Any) -> None:
        super().__init__(model, **options)
        self._structured = options.get("structured", False)

    @property
    def client(self):
        """Lazy-load the OpenAI-compatible client."""
        if self._client is None:
            try:
                import openai
            except ImportError:
                raise LLMError(
                    'OpenAI-compatible provider requires the "openai" package. '
                    'Install with: pip install "aglc[openai]"'
                )
            base_url = (
                self.options.get("base_url")
                or os.environ.get("AGLC_OPENAI_BASE_URL")
                or "http://localhost:11434/v1"
            )
            api_key = self.options.get("api_key") or os.environ.get("AGLC_OPENAI_API_KEY") or "not-needed"
            self._client = openai.OpenAI(api_key=api_key, base_url=base_url)
        return self._client

    def _complete_json(self, *, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        """Generate JSON using OpenAI-compatible API."""
        if self._structured:
            # Try strict mode if explicitly requested
            try:
                import openai

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": schema_name, "schema": schema, "strict": False},
                    },
                )
                message = response.choices[0].message
                if message.refusal:
                    raise LLMError(f"Model refused: {message.refusal}")
                return message.content
            except Exception:
                # Fall back to json_object + schema instructions
                pass

        # Use json_object with schema instructions (default for compatible services)
        system = system + "\n\n" + schema_instructions(schema)
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content
