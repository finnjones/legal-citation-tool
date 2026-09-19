"""Anthropic provider using native structured outputs."""

from typing import Any

from aglc.llm.base import LLMError, LLMProvider, register_provider

from ._common import schema_instructions


@register_provider("anthropic")
class AnthropicProvider(LLMProvider):
    """Uses Claude with native JSON schema structured outputs."""

    def __init__(self, model: str, **options: Any) -> None:
        super().__init__(model, **options)
        self._client = None
        self._use_fallback = False

    @property
    def client(self):
        """Lazy-load the Anthropic client."""
        if self._client is None:
            try:
                import anthropic
            except ImportError:
                raise LLMError(
                    'Anthropic provider requires the "anthropic" package. '
                    'Install with: pip install "aglc[anthropic]"'
                )
            self._client = anthropic.Anthropic(api_key=self.options.get("api_key"))
        return self._client

    def _complete_json(self, *, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        """Generate JSON using Anthropic's native structured output."""
        import anthropic

        # If we learned the schema doesn't work, use prompt mode
        if self._use_fallback:
            system = system + "\n\n" + schema_instructions(schema)
            kwargs = dict(
                model=self.model,
                max_tokens=self.options.get("max_tokens", 16000),
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            response = self.client.messages.create(**kwargs)
        else:
            # Try native structured output mode
            kwargs = dict(
                model=self.model,
                max_tokens=self.options.get("max_tokens", 16000),
                system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )

            try:
                # Use fallback mode for models that support it
                if self.model in ("claude-opus-5", "claude-fable-5-1") and self.options.get("fallbacks", True):
                    response = self.client.beta.messages.create(
                        **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                    )
                else:
                    response = self.client.messages.create(**kwargs)
            except anthropic.BadRequestError as e:
                # Schema not supported; retry with prompt mode
                if "schema" in str(e) or "output_config" in str(e):
                    self._use_fallback = True
                    kwargs["system"] = system + "\n\n" + schema_instructions(schema)
                    kwargs.pop("output_config")
                    response = self.client.messages.create(**kwargs)
                else:
                    raise

        # Check for refusals
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            msg = "Model refused to generate output"
            if details:
                msg += f": {details}"
            raise LLMError(msg)

        # Check for truncation
        if response.stop_reason == "max_tokens":
            raise LLMError("output truncated (max_tokens reached)")

        # Extract text from first text block
        for block in response.content:
            if block.type == "text":
                return block.text

        raise LLMError("No text content in response")
