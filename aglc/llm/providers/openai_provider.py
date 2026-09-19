"""OpenAI and OpenAI-compatible providers."""

import os
from typing import Any

from aglc.llm.base import LLMError, LLMProvider, register_provider

from ._common import schema_instructions


@register_provider("openai")
class OpenAIProvider(LLMProvider):
    """Uses OpenAI with json_schema structured outputs, falling back to json_object
    mode with the schema in the prompt if the endpoint rejects json_schema."""

    #: env var holding the API key (None -> the SDK's own OPENAI_API_KEY lookup)
    api_key_env: str | None = None
    #: default endpoint (None -> OpenAI)
    default_base_url: str | None = None

    def __init__(self, model: str, **options: Any) -> None:
        super().__init__(model, **options)
        self._client = None
        self._use_fallback = False

    def _client_kwargs(self) -> dict[str, Any]:
        api_key = self.options.get("api_key") or (os.environ.get(self.api_key_env) if self.api_key_env else None)
        return {"api_key": api_key, "base_url": self.options.get("base_url") or self.default_base_url}

    def _extra_body(self, structured: bool) -> dict[str, Any] | None:
        """Vendor-specific request fields (see OpenRouterProvider)."""
        return None

    @property
    def client(self):
        """Lazy-load the OpenAI client."""
        if self._client is None:
            try:
                import openai
            except ImportError:
                raise LLMError(
                    f'The "{self.name}" provider requires the "openai" package. '
                    'Install with: pip install "aglc[openai]"'
                )
            self._client = openai.OpenAI(**self._client_kwargs())
        return self._client

    def _create(self, system: str, user: str, response_format: dict[str, Any], structured: bool):
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=response_format,
        )
        extra = self._extra_body(structured)
        if extra:
            kwargs["extra_body"] = extra
        return self.client.chat.completions.create(**kwargs)

    def _complete_json(self, *, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        import openai

        json_object = {"type": "json_object"}
        prompted_system = system + "\n\n" + schema_instructions(schema)
        if self._use_fallback:
            response = self._create(prompted_system, user, json_object, structured=False)
        else:
            json_schema = {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": False},
            }
            try:
                response = self._create(system, user, json_schema, structured=True)
            except openai.BadRequestError:
                # Schema not supported; remember and retry with json_object + instructions
                self._use_fallback = True
                response = self._create(prompted_system, user, json_object, structured=False)

        if not response.choices:
            raise LLMError(f"{self.name}:{self.model} returned no choices")
        message = response.choices[0].message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise LLMError(f"Model refused: {refusal}")
        if getattr(response.choices[0], "finish_reason", None) == "length":
            raise LLMError("output truncated (max tokens reached)")
        return message.content or ""


@register_provider("openrouter")
class OpenRouterProvider(OpenAIProvider):
    """OpenRouter (https://openrouter.ai): one API key, hundreds of models, eg
    openrouter:deepseek/deepseek-v4-flash. Key from $OPENROUTER_API_KEY."""

    api_key_env = "OPENROUTER_API_KEY"
    default_base_url = "https://openrouter.ai/api/v1"

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs = super()._client_kwargs()
        if not kwargs["api_key"]:
            raise LLMError("OpenRouter needs an API key: set OPENROUTER_API_KEY (https://openrouter.ai/keys)")
        # Optional app attribution shown on openrouter.ai
        kwargs["default_headers"] = {"X-Title": "AGLC4 Citation Tool"}
        return kwargs

    def _extra_body(self, structured: bool) -> dict[str, Any] | None:
        # Only route to upstream hosts that honour response_format, so JSON mode is enforced.
        return {"provider": {"require_parameters": True}}


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
