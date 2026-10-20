"""OpenAI and OpenAI-compatible providers."""

import logging
import os
import threading
from types import SimpleNamespace
from typing import Any

from aglc.llm.base import LLMError, LLMProvider, TransientLLMError, register_provider

from ._common import schema_instructions

log = logging.getLogger("aglc")


@register_provider("openai")
class OpenAIProvider(LLMProvider):
    """Uses OpenAI with json_schema structured outputs, falling back to json_object
    mode with the schema in the prompt if the endpoint rejects json_schema."""

    #: env var holding the API key (None -> the SDK's own OPENAI_API_KEY lookup)
    api_key_env: str | None = None
    #: default endpoint (None -> OpenAI)
    default_base_url: str | None = None
    #: the request field capping the reply's length (OpenAI's reasoning models reject max_tokens)
    max_tokens_param = "max_completion_tokens"

    def __init__(self, model: str, **options: Any) -> None:
        super().__init__(model, **options)
        self._client = None
        self._use_fallback = False
        #: upstream hosts (as named in OpenRouter's `provider` field) that sent an empty reply
        self._failed_hosts: list[str] = []
        #: False once the endpoint has refused a streamed request
        self._stream = bool(options.get("stream", True))
        #: the upstream host (OpenRouter's `provider` field) of the latest reply
        self._last_host: str | None = None

    def avoid_last_host(self) -> bool:
        """Send the next requests to another upstream host than the one that just answered
        (its reply was valid JSON but useless, eg one footnote of fifteen)."""
        host = self._last_host
        if not host or host in self._failed_hosts:
            return False
        log.info("%s: avoiding upstream host %s, which answered only part of the batch", self, host)
        self._failed_hosts.append(host)
        return True

    def _client_kwargs(self) -> dict[str, Any]:
        api_key = self.options.get("api_key") or (os.environ.get(self.api_key_env) if self.api_key_env else None)
        return {
            "api_key": api_key,
            "base_url": self.options.get("base_url") or self.default_base_url,
            # a silent connection: the request's own deadline (_deadline) is the real limit,
            # since a host that sends keep-alive bytes never trips this
            "timeout": self._deadline(),
            # one retry, not two: a stalled host should be abandoned quickly
            "max_retries": int(self.options.get("max_retries", 1)),
        }

    def _extra_body(self, structured: bool) -> dict[str, Any] | None:
        """Vendor-specific request fields (see OpenRouterProvider)."""
        return None

    def _deadline(self) -> float:
        """Seconds one request may take in all, from $AGLC_REQUEST_DEADLINE (or the older
        $AGLC_TIMEOUT), default 90."""
        value = self.options.get("timeout") or os.environ.get("AGLC_REQUEST_DEADLINE") or os.environ.get("AGLC_TIMEOUT")
        return float(value or 90)

    def _max_tokens(self) -> int:
        """A cap on the reply, so a model stuck repeating itself stops: $AGLC_MAX_OUTPUT_TOKENS."""
        return int(self.options.get("max_tokens") or os.environ.get("AGLC_MAX_OUTPUT_TOKENS") or 16000)

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
        kwargs[self.max_tokens_param] = self._max_tokens()
        extra = self._extra_body(structured)
        if extra:
            kwargs["extra_body"] = extra
        import openai

        try:
            if self._stream:
                try:
                    return self._with_deadline(lambda abort: self._streamed(kwargs, abort))
                except openai.BadRequestError as e:
                    if "stream" not in str(e).lower():
                        raise
                    log.info("%s doesn't take streamed requests; asking without streaming", self)
                    self._stream = False
            return self._with_deadline(lambda abort: self.client.chat.completions.create(**kwargs))
        except (openai.APIConnectionError, openai.InternalServerError, openai.RateLimitError) as e:
            # timeouts, dropped connections, 5xx and 429: worth another try, unlike a bad key
            raise TransientLLMError(f"{self.name}:{self.model}: {type(e).__name__}: {e}") from e

    def _with_deadline(self, call):
        """Run `call(abort)` with a hard limit on the whole request. A host that keeps the
        connection open with keep-alive bytes (OpenRouter does, while the model works) never
        trips the client's read timeout, so the request runs in a worker thread and is given up
        on at the deadline; `abort` is set, and the client closed, so the worker ends soon after."""
        deadline = self._deadline()
        abort = threading.Event()
        box: dict[str, Any] = {}
        finished = threading.Event()

        def run() -> None:
            try:
                box["value"] = call(abort)
            except BaseException as e:  # noqa: BLE001 - handed back to the caller
                box["error"] = e
            finally:
                finished.set()

        threading.Thread(target=run, name="aglc-llm-request", daemon=True).start()
        if not finished.wait(deadline):
            abort.set()
            client, self._client = self._client, None  # a fresh client for the next request
            if client is not None:
                try:
                    client.close()
                except Exception:  # noqa: BLE001 - closing is best effort
                    pass
            raise TransientLLMError(f"{self.name}:{self.model}: no answer within {deadline:g}s")
        if "error" in box:
            raise box["error"]
        return box["value"]

    def _streamed(self, kwargs: dict[str, Any], abort: threading.Event):
        """The reply as it arrives, put back together in the shape of a non-streamed response
        (choices[0].message, finish_reason, provider, id). Each piece of text is passed to
        `self.on_text` so progress can be shown while the model writes."""
        stream = self.client.chat.completions.create(stream=True, **kwargs)
        content: list[str] = []
        refusal: list[str] = []
        reasoning: list[str] = []
        finish_reason = error = host = response_id = None
        try:
            for chunk in stream:
                if abort.is_set():
                    break
                host = getattr(chunk, "provider", None) or host
                response_id = getattr(chunk, "id", None) or response_id
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                delta = choice.delta
                if delta is not None:
                    if delta.content:
                        content.append(delta.content)
                        self._emit_text(delta.content)
                    if getattr(delta, "refusal", None):
                        refusal.append(delta.refusal)
                    if isinstance(getattr(delta, "reasoning", None), str):
                        reasoning.append(delta.reasoning)
                finish_reason = choice.finish_reason or finish_reason
                error = getattr(choice, "error", None) or error
        finally:
            stream.close()
        message = SimpleNamespace(content="".join(content), refusal="".join(refusal) or None,
                                  reasoning="".join(reasoning) or None)
        choice = SimpleNamespace(message=message, finish_reason=finish_reason, error=error)
        return SimpleNamespace(choices=[choice], provider=host, id=response_id)

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

        host = getattr(response, "provider", None)
        self._last_host = host if isinstance(host, str) and host else None
        if not response.choices:
            raise TransientLLMError(f"{self.name}:{self.model} returned no choices ({_diagnose(response, None)})")
        choice = response.choices[0]
        message = choice.message
        refusal = getattr(message, "refusal", None)
        if refusal:
            raise LLMError(f"Model refused: {refusal}")
        if getattr(choice, "finish_reason", None) == "length":
            raise LLMError("output truncated (max tokens reached)")
        content = message.content or ""
        if not content.strip():
            # Seen from OpenRouter: a quick 200 with nothing in it, from one upstream host.
            # Not a schema problem, so it mustn't be fed back to the model as one.
            host = getattr(response, "provider", None)
            if isinstance(host, str) and host and host not in self._failed_hosts:
                self._failed_hosts.append(host)
            raise TransientLLMError(f"{self.name}:{self.model} returned an empty reply ({_diagnose(response, choice)})")
        return content


def _diagnose(response: Any, choice: Any) -> str:
    """What the response says about itself, for the log: finish reason, upstream host..."""
    parts = []
    if choice is not None:
        parts.append(f"finish_reason={getattr(choice, 'finish_reason', None)}")
        reasoning = getattr(choice.message, "reasoning", None)
        if isinstance(reasoning, str) and reasoning:
            parts.append(f"reasoning={len(reasoning)} chars")
        error = getattr(choice, "error", None)
        if error:
            parts.append(f"error={error}")
    for label, attr in (("upstream", "provider"), ("id", "id")):
        value = getattr(response, attr, None)
        if isinstance(value, str) and value:
            parts.append(f"{label}={value}")
    return ", ".join(parts)


@register_provider("openrouter")
class OpenRouterProvider(OpenAIProvider):
    """OpenRouter (https://openrouter.ai): one API key, hundreds of models, eg
    openrouter:deepseek/deepseek-v4.1-flash-1017. Key from $OPENROUTER_API_KEY."""

    api_key_env = "OPENROUTER_API_KEY"
    default_base_url = "https://openrouter.ai/api/v1"
    max_tokens_param = "max_tokens"
    #: upstream hosts never routed to unless $AGLC_OPENROUTER_IGNORE says otherwise: DigitalOcean
    #: sent fast empty replies for DeepSeek V4.1 Flash in testing (Oct 2026); Sail Research
    #: answered a 15-footnote batch with one footnote and no citations, every time (21 Oct 2026)
    default_ignored_hosts = ("DigitalOcean", "Sail Research")

    def __init__(self, model: str, **options: Any) -> None:
        super().__init__(model, **options)
        #: from $AGLC_OPENROUTER_IGNORE (comma-separated OpenRouter provider names; empty for
        #: none), else the default; dropped for the rest of the run if it leaves no host at all
        self._ignored_hosts = _ignored_hosts(options.get("ignore"), self.default_ignored_hosts)

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs = super()._client_kwargs()
        key = kwargs["api_key"]
        if not key:
            raise LLMError("OpenRouter needs an API key: set OPENROUTER_API_KEY (https://openrouter.ai/keys)")
        if not key.startswith("sk-or-"):
            hint = " (that looks like a Groq key)" if key.startswith("gsk_") else ""
            raise LLMError(
                f"OPENROUTER_API_KEY doesn't look like an OpenRouter key{hint}: OpenRouter keys start "
                "with 'sk-or-'. Create one at https://openrouter.ai/keys"
            )
        # Optional app attribution shown on openrouter.ai
        kwargs["default_headers"] = {"X-Title": "Aforecite"}
        return kwargs

    def _create(self, system: str, user: str, response_format: dict[str, Any], structured: bool):
        import openai

        try:
            return super()._create(system, user, response_format, structured)
        except (openai.NotFoundError, openai.BadRequestError):
            excluded = [*self._ignored_hosts, *self._failed_hosts]
            if not excluded:
                raise
            # Ruling out these hosts may leave none that serve this model; let OpenRouter use
            # any of them again rather than fail outright.
            log.info("%s: no other upstream host available; allowing %s again", self, ", ".join(excluded))
            self._ignored_hosts = []
            self._failed_hosts.clear()
            return super()._create(system, user, response_format, structured)

    def _extra_body(self, structured: bool) -> dict[str, Any] | None:
        # Only route to upstream hosts that honour response_format, so JSON mode is enforced,
        # and let OpenRouter fall through to another host when one is down.
        routing: dict[str, Any] = {"require_parameters": True, "allow_fallbacks": True}
        # Only hosts that don't store or train on requests, unless $AGLC_OPENROUTER_DATA_COLLECTION
        # is "allow". The privacy page says so; it is never relaxed to find a host.
        if _data_collection() == "deny":
            routing["data_collection"] = "deny"
        # hosts known to misbehave, plus any that just sent an empty reply (send the retry elsewhere)
        excluded = list(dict.fromkeys([*self._ignored_hosts, *self._failed_hosts]))
        if excluded:
            routing["ignore"] = excluded
        body: dict[str, Any] = {"provider": routing}
        # Extraction doesn't benefit from "thinking": on reasoning models like DeepSeek V4
        # Flash it made a 3-footnote batch take ~90s instead of ~7s with equally valid output.
        # AGLC_REASONING=off (default) | low | medium | high | default (the model's own setting)
        reasoning = (self.options.get("reasoning") or os.environ.get("AGLC_REASONING") or "off").lower()
        if reasoning == "off":
            body["reasoning"] = {"enabled": False}
        elif reasoning in ("low", "medium", "high"):
            body["reasoning"] = {"effort": reasoning}
        return body


def _data_collection() -> str:
    value = (os.environ.get("AGLC_OPENROUTER_DATA_COLLECTION") or "deny").strip().lower()
    return "allow" if value == "allow" else "deny"


def _ignored_hosts(option: str | list[str] | None, default: tuple[str, ...]) -> list[str]:
    value = option if option is not None else os.environ.get("AGLC_OPENROUTER_IGNORE")
    if value is None:
        return list(default)
    names = value.split(",") if isinstance(value, str) else value
    return [n.strip() for n in names if n.strip()]


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
