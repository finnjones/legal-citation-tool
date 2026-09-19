"""Provider-agnostic LLM interface.

The rest of the codebase only ever sees `LLMProvider.generate_json()`. Adding a new
model vendor means writing one small subclass and registering it; nothing else in
the pipeline changes.

Providers are selected with a spec string "<provider>:<model>", eg

    anthropic:claude-opus-5
    openai:gpt-5
    gemini:gemini-2.5-pro
    openrouter:deepseek/deepseek-v4-flash   (any model on openrouter.ai)
    openai-compatible:llama3.1        (Ollama, LM Studio, vLLM, Groq...)

via `get_provider(spec)` or the AGLC_LLM environment variable.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_SPEC = "anthropic:claude-opus-5"


class LLMError(RuntimeError):
    """Raised when a provider cannot produce valid output after retries."""


class LLMProvider(ABC):
    """A chat model that can return JSON conforming to a schema."""

    #: registry name, eg "anthropic"
    name: str = ""

    def __init__(self, model: str, **options: Any) -> None:
        self.model = model
        self.options = options

    # ---- the one method subclasses must implement -------------------------- #
    @abstractmethod
    def _complete_json(self, *, system: str, user: str, schema: dict[str, Any], schema_name: str) -> str:
        """Return raw text that should be a JSON document matching `schema`.

        Implementations should use the vendor's native structured-output feature
        where available, and fall back to instructing the model in the prompt.
        They must not validate; `generate_json` does that.
        """

    # ---- shared behaviour -------------------------------------------------- #
    def generate_json(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        max_attempts: int = 3,
    ) -> T:
        """Ask the model for JSON, validate it against `output_model`, retry with the
        validation error fed back if it doesn't conform."""
        schema = output_model.model_json_schema()
        prompt = user
        last_error: Exception | None = None
        for _ in range(max_attempts):
            raw = self._complete_json(system=system, user=prompt, schema=schema, schema_name=output_model.__name__)
            try:
                return output_model.model_validate_json(_strip_fences(raw))
            except (ValidationError, json.JSONDecodeError, ValueError) as e:
                last_error = e
                prompt = (
                    f"{user}\n\nYour previous response was not valid for the required JSON schema.\n"
                    f"Error:\n{e}\n\nPrevious response:\n{raw}\n\nReturn corrected JSON only."
                )
        raise LLMError(f"{self.name}:{self.model} did not return valid {output_model.__name__}: {last_error}")

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name}:{self.model}>"


def _strip_fences(raw: str) -> str:
    """Tolerate ```json fences from models without native structured output."""
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s.strip()


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #

_REGISTRY: dict[str, Callable[..., LLMProvider]] = {}


def register_provider(name: str) -> Callable[[type[LLMProvider]], type[LLMProvider]]:
    def deco(cls: type[LLMProvider]) -> type[LLMProvider]:
        cls.name = name
        _REGISTRY[name] = cls
        return cls

    return deco


def available_providers() -> list[str]:
    _load_builtin_providers()
    return sorted(_REGISTRY)


def default_spec() -> str:
    """The model used when none is given: $AGLC_LLM, else DEFAULT_SPEC."""
    return os.environ.get("AGLC_LLM") or DEFAULT_SPEC


def get_provider(spec: str | None = None, **options: Any) -> LLMProvider:
    """Build a provider from "<provider>:<model>" (default: $AGLC_LLM or DEFAULT_SPEC)."""
    _load_builtin_providers()
    spec = spec or default_spec()
    if ":" not in spec:
        raise ValueError(f"LLM spec must look like 'provider:model', got {spec!r}")
    name, model = spec.split(":", 1)
    try:
        factory = _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown LLM provider {name!r}. Available: {', '.join(sorted(_REGISTRY))}") from None
    return factory(model, **options)


def _load_builtin_providers() -> None:
    # Imported lazily so that vendor SDKs are only required when used.
    from . import providers  # noqa: F401
