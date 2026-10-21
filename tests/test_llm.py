"""Tests for LLM providers."""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, ValidationError

from aglc.llm.base import LLMError, available_providers, get_provider
from aglc.llm.providers.fake import FakeProvider


# Test models
class SimpleModel(BaseModel):
    name: str
    age: int


class NestedModel(BaseModel):
    title: str
    items: list[str]


# ============================================================================
# Provider parsing and registry
# ============================================================================


def test_get_provider_with_spec():
    """Test parsing a provider:model spec."""
    provider = get_provider("fake:test-model")
    assert provider.name == "fake"
    assert provider.model == "test-model"


def test_get_provider_missing_colon():
    """Test error when spec lacks colon."""
    with pytest.raises(ValueError, match="must look like 'provider:model'"):
        get_provider("invalid-spec")


def test_get_provider_unknown_provider():
    """Test error for unknown provider name."""
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_provider("nonexistent:model")


def test_get_provider_from_env(monkeypatch):
    """Test provider selection from AGLC_LLM env var."""
    monkeypatch.setenv("AGLC_LLM", "fake:from-env")
    provider = get_provider()
    assert provider.name == "fake"
    assert provider.model == "from-env"


def test_get_provider_default():
    """Test default provider when nothing specified."""
    provider = get_provider()
    assert provider.name == "openrouter"
    assert provider.model == "@preset/aglc"


def test_available_providers():
    """Test that all built-in providers are registered."""
    providers = available_providers()
    expected = {"anthropic", "fake", "gemini", "openai", "openai-compatible", "openrouter"}
    assert set(providers) == expected


# ============================================================================
# Base class retry logic and validation
# ============================================================================


def test_retry_with_invalid_json():
    """Test that invalid JSON triggers retry with error feedback."""
    responses = [
        "not json at all",
        '{"title": "Valid", "items": ["a", "b"]}',
    ]
    provider = FakeProvider("test", responses=responses)
    result = provider.generate_json(
        system="test system",
        user="test user",
        output_model=NestedModel,
    )
    assert result.title == "Valid"
    assert result.items == ["a", "b"]
    assert len(provider.calls) == 2
    assert "not valid for the required JSON schema" in provider.calls[1]["user"]


def test_retry_with_validation_error():
    """Test that schema validation errors trigger retry."""
    responses = [
        '{"title": "Test"}',  # Missing required 'items'
        '{"title": "Test", "items": ["x"]}',  # Valid
    ]
    provider = FakeProvider("test", responses=responses)
    result = provider.generate_json(
        system="test system",
        user="test user",
        output_model=NestedModel,
    )
    assert result.title == "Test"
    assert result.items == ["x"]
    assert len(provider.calls) == 2


def test_max_attempts_exceeded():
    """Test LLMError when max attempts is reached."""
    provider = FakeProvider("test", responses=["{}"]*5)
    with pytest.raises(LLMError, match="did not return valid NestedModel"):
        provider.generate_json(
            system="test",
            user="test",
            output_model=NestedModel,
            max_attempts=2,
        )


def test_code_fence_stripping():
    """Test that ```json fences are stripped."""
    provider = FakeProvider("test", responses=['```json\n{"title": "T", "items": []}\n```'])
    result = provider.generate_json(
        system="test",
        user="test",
        output_model=NestedModel,
    )
    assert result.title == "T"


def test_code_fence_stripping_with_extra_whitespace():
    """Test code fence stripping with surrounding whitespace."""
    provider = FakeProvider(
        "test",
        responses=['  ```json\n{"title": "T", "items": []}\n```  \n'],
    )
    result = provider.generate_json(
        system="test",
        user="test",
        output_model=NestedModel,
    )
    assert result.title == "T"


# ============================================================================
# Anthropic provider
# ============================================================================


def test_anthropic_provider_basic(monkeypatch):
    """Test basic Anthropic provider flow with mocked client."""

    # Mock response - create a real object so iteration works
    class MockContent:
        def __init__(self):
            self.type = "text"
            self.text = '{"name": "Alice", "age": 30}'

    class MockResponse:
        def __init__(self):
            self.stop_reason = "end_turn"
            self.content = [MockContent()]

    # Mock the anthropic module and client
    mock_response = MockResponse()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.beta.messages.create.return_value = mock_response

    def mock_anthropic_init(*args, **kwargs):
        return mock_client

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic = mock_anthropic_init
    monkeypatch.setitem(__import__("sys").modules, "anthropic", mock_anthropic_module)

    provider = get_provider("anthropic:claude-opus-5")
    result = provider.generate_json(
        system="sys",
        user="user",
        output_model=SimpleModel,
    )

    assert result.name == "Alice"
    assert result.age == 30


def test_anthropic_provider_refusal(monkeypatch):
    """Test Anthropic provider raises LLMError on refusal."""

    class MockResponse:
        def __init__(self):
            self.stop_reason = "refusal"
            self.stop_details = "policy violation"
            self.content = []

    mock_response = MockResponse()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.beta.messages.create.return_value = mock_response

    def mock_anthropic_init(*args, **kwargs):
        return mock_client

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic = mock_anthropic_init
    monkeypatch.setitem(__import__("sys").modules, "anthropic", mock_anthropic_module)

    provider = get_provider("anthropic:claude-opus-5")
    with pytest.raises(LLMError, match="Model refused.*policy violation"):
        provider.generate_json(
            system="sys",
            user="user",
            output_model=SimpleModel,
        )


def test_anthropic_provider_max_tokens(monkeypatch):
    """Test Anthropic provider raises LLMError on truncation."""

    class MockResponse:
        def __init__(self):
            self.stop_reason = "max_tokens"
            self.content = []

    mock_response = MockResponse()
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    mock_client.beta.messages.create.return_value = mock_response

    def mock_anthropic_init(*args, **kwargs):
        return mock_client

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic = mock_anthropic_init
    monkeypatch.setitem(__import__("sys").modules, "anthropic", mock_anthropic_module)

    provider = get_provider("anthropic:claude-opus-5")
    with pytest.raises(LLMError, match="output truncated"):
        provider.generate_json(
            system="sys",
            user="user",
            output_model=SimpleModel,
        )


def test_anthropic_fallbacks_for_opus(monkeypatch):
    """Test Anthropic uses fallbacks for claude-opus-5."""

    class MockContent:
        def __init__(self):
            self.type = "text"
            self.text = '{"name": "Test", "age": 1}'

    class MockResponse:
        def __init__(self):
            self.stop_reason = "end_turn"
            self.content = [MockContent()]

    mock_client = MagicMock()
    mock_beta = MagicMock()
    mock_beta.messages.create.return_value = MockResponse()
    mock_client.beta = mock_beta

    def mock_anthropic_init(*args, **kwargs):
        return mock_client

    mock_anthropic_module = MagicMock()
    mock_anthropic_module.Anthropic = mock_anthropic_init
    monkeypatch.setitem(__import__("sys").modules, "anthropic", mock_anthropic_module)

    provider = get_provider("anthropic:claude-opus-5")
    result = provider.generate_json(
        system="sys",
        user="user",
        output_model=SimpleModel,
    )

    assert result.name == "Test"
    # Verify beta.messages.create was called
    assert mock_beta.messages.create.called


# ============================================================================
# OpenAI provider
# ============================================================================


def test_openai_provider_basic(monkeypatch):
    """Test basic OpenAI provider flow."""

    class MockMessage:
        def __init__(self):
            self.content = '{"name": "Charlie", "age": 35}'
            self.refusal = None

    class MockChoice:
        def __init__(self):
            self.message = MockMessage()

    class MockResponse:
        def __init__(self):
            self.choices = [MockChoice()]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse()

    def mock_openai_init(*args, **kwargs):
        return mock_client

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI = mock_openai_init
    monkeypatch.setitem(__import__("sys").modules, "openai", mock_openai_module)

    provider = get_provider("openai:gpt-4", stream=False)
    result = provider.generate_json(
        system="sys",
        user="user",
        output_model=SimpleModel,
    )

    assert result.name == "Charlie"
    assert result.age == 35


def test_openai_provider_refusal(monkeypatch):
    """Test OpenAI provider raises LLMError on refusal."""

    class MockMessage:
        def __init__(self):
            self.content = ""
            self.refusal = "I cannot help with that"

    class MockChoice:
        def __init__(self):
            self.message = MockMessage()

    class MockResponse:
        def __init__(self):
            self.choices = [MockChoice()]

    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = MockResponse()

    def mock_openai_init(*args, **kwargs):
        return mock_client

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI = mock_openai_init
    monkeypatch.setitem(__import__("sys").modules, "openai", mock_openai_module)

    provider = get_provider("openai:gpt-4", stream=False)
    with pytest.raises(LLMError, match="Model refused"):
        provider.generate_json(
            system="sys",
            user="user",
            output_model=SimpleModel,
        )


# ============================================================================
# OpenAI-compatible provider
# ============================================================================


def test_openai_compatible_provider_default_base_url(monkeypatch):
    """Test OpenAI-compatible provider defaults to localhost:11434."""
    call_args = {}

    def capture_openai_init(api_key=None, base_url=None):
        call_args["api_key"] = api_key
        call_args["base_url"] = base_url
        return MagicMock()

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI = capture_openai_init
    monkeypatch.setitem(__import__("sys").modules, "openai", mock_openai_module)

    provider = get_provider("openai-compatible:model")
    # Trigger client creation
    _ = provider.client

    assert call_args["base_url"] == "http://localhost:11434/v1"


def test_openai_compatible_provider_base_url(monkeypatch):
    """Test OpenAI-compatible provider uses base_url option."""
    call_args = {}

    def capture_openai_init(api_key=None, base_url=None):
        call_args["api_key"] = api_key
        call_args["base_url"] = base_url
        return MagicMock()

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI = capture_openai_init
    monkeypatch.setitem(__import__("sys").modules, "openai", mock_openai_module)

    provider = get_provider("openai-compatible:llama", base_url="http://localhost:8000/v1")
    _ = provider.client

    assert call_args["base_url"] == "http://localhost:8000/v1"


def test_openai_compatible_provider_base_url_env(monkeypatch):
    """Test OpenAI-compatible provider reads base_url from env."""
    monkeypatch.setenv("AGLC_OPENAI_BASE_URL", "http://custom:9000/v1")

    call_args = {}

    def capture_openai_init(api_key=None, base_url=None):
        call_args["api_key"] = api_key
        call_args["base_url"] = base_url
        return MagicMock()

    mock_openai_module = MagicMock()
    mock_openai_module.OpenAI = capture_openai_init
    monkeypatch.setitem(__import__("sys").modules, "openai", mock_openai_module)

    provider = get_provider("openai-compatible:model")
    _ = provider.client

    assert call_args["base_url"] == "http://custom:9000/v1"


# ============================================================================
# Gemini provider
# ============================================================================


def test_gemini_provider_can_be_created():
    """Test Gemini provider can be instantiated."""
    provider = get_provider("gemini:gemini-2.5-pro")
    assert provider.name == "gemini"
    assert provider.model == "gemini-2.5-pro"


# ============================================================================
# Fake provider
# ============================================================================


def test_fake_provider_default_response():
    """Test fake provider returns {} by default."""
    provider = FakeProvider("test")
    raw = provider._complete_json(
        system="s",
        user="u",
        schema={},
        schema_name="Test",
    )
    assert raw == "{}"


def test_fake_provider_list_responses():
    """Test fake provider with list of responses."""
    provider = FakeProvider(
        "test",
        responses=['{"x": 1}', '{"x": 2}', '{"x": 3}'],
    )

    r1 = provider._complete_json(system="s", user="u", schema={}, schema_name="T")
    r2 = provider._complete_json(system="s", user="u", schema={}, schema_name="T")
    r3 = provider._complete_json(system="s", user="u", schema={}, schema_name="T")
    r4 = provider._complete_json(system="s", user="u", schema={}, schema_name="T")

    assert r1 == '{"x": 1}'
    assert r2 == '{"x": 2}'
    assert r3 == '{"x": 3}'
    assert r4 == '{"x": 3}'  # Last response repeats


def test_fake_provider_callable_response():
    """Test fake provider with callable response."""
    def response_fn(system, user, schema):
        return f'{{"system_len": {len(system)}, "user_len": {len(user)}}}'

    provider = FakeProvider("test", responses=response_fn)
    raw = provider._complete_json(
        system="hello",
        user="world",
        schema={},
        schema_name="T",
    )
    assert raw == '{"system_len": 5, "user_len": 5}'


def test_fake_provider_records_calls():
    """Test fake provider records all calls."""
    provider = FakeProvider("test", responses=['{"x": 1}'])

    schema1 = {"type": "object"}
    provider._complete_json(system="s1", user="u1", schema=schema1, schema_name="M1")

    schema2 = {"type": "array"}
    provider._complete_json(system="s2", user="u2", schema=schema2, schema_name="M2")

    assert len(provider.calls) == 2
    assert provider.calls[0]["system"] == "s1"
    assert provider.calls[0]["user"] == "u1"
    assert provider.calls[0]["schema"] == schema1
    assert provider.calls[0]["schema_name"] == "M1"
    assert provider.calls[1]["system"] == "s2"
    assert provider.calls[1]["user"] == "u2"


# ============================================================================
# OpenRouter
# ============================================================================


class _FakeStream:
    """What the SDK returns for stream=True: the chunks of a reply, then close()."""

    def __init__(self, response):
        self.response = response
        self.closed = False

    def __iter__(self):
        for choice in getattr(self.response, "choices", None) or []:
            delta = type("D", (), {"content": choice.message.content, "refusal": getattr(choice.message, "refusal", None)})()
            yield type("Chunk", (), {
                "id": getattr(self.response, "id", None), "provider": getattr(self.response, "provider", None),
                "choices": [type("CC", (), {"delta": delta, "finish_reason": getattr(choice, "finish_reason", None),
                                             "error": getattr(choice, "error", None)})()],
            })()

    def close(self):
        self.closed = True


def _maybe_streamed(req, response):
    already_a_stream = hasattr(response, "__iter__")
    return _FakeStream(response) if req.get("stream") and not already_a_stream else response


class _RecordingOpenAI:
    """Stands in for openai.OpenAI; records constructor and request kwargs."""

    instances: list = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.requests: list = []
        _RecordingOpenAI.instances.append(self)
        outer = self

        class _Completions:
            def create(self, **req):
                outer.requests.append(req)
                msg = type("M", (), {"content": '{"value": "ok"}', "refusal": None})()
                choice = type("C", (), {"message": msg, "finish_reason": "stop"})()
                return _maybe_streamed(req, type("R", (), {"choices": [choice]})())

        self.chat = type("Chat", (), {"completions": _Completions()})()


def test_openrouter_uses_openrouter_endpoint_and_key(monkeypatch):
    import openai
    from pydantic import BaseModel

    class Out(BaseModel):
        value: str

    monkeypatch.setattr(openai, "OpenAI", _RecordingOpenAI)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    provider = get_provider("openrouter:deepseek/deepseek-v4.1-flash-1017")
    assert provider.generate_json(system="s", user="u", output_model=Out).value == "ok"

    client = _RecordingOpenAI.instances[-1]
    assert client.kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert client.kwargs["api_key"] == "sk-or-v1-test"
    req = client.requests[0]
    assert req["model"] == "deepseek/deepseek-v4.1-flash-1017"
    assert req["response_format"]["type"] == "json_schema"
    assert req["extra_body"] == {
        "provider": {"require_parameters": True, "allow_fallbacks": True, "data_collection": "deny", "ignore": ["DigitalOcean", "Sail Research"]},
        "reasoning": {"enabled": False},
    }


def test_openrouter_without_key_gives_helpful_error(monkeypatch):
    from pydantic import BaseModel

    class Out(BaseModel):
        value: str

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = get_provider("openrouter:deepseek/deepseek-v4.1-flash-1017")
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        provider.generate_json(system="s", user="u", output_model=Out)


def test_openrouter_rejects_non_openrouter_key(monkeypatch):
    from pydantic import BaseModel

    class Out(BaseModel):
        value: str

    monkeypatch.setenv("OPENROUTER_API_KEY", "gsk_notopenrouter")
    provider = get_provider("openrouter:deepseek/deepseek-v4.1-flash-1017")
    with pytest.raises(LLMError, match="Groq key"):
        provider.generate_json(system="s", user="u", output_model=Out)


# ============================================================================
# Empty / failed replies: retried as-is, then the fallback model
# ============================================================================


def test_empty_reply_is_retried_unchanged_then_succeeds():
    provider = FakeProvider("test", responses=["", '{"title": "T", "items": []}'])
    result = provider.generate_json(system="s", user="the prompt", output_model=NestedModel)
    assert result.title == "T"
    assert len(provider.calls) == 2
    # an empty reply is not fed back to the model as a schema correction
    assert provider.calls[1]["user"] == "the prompt"


def test_retries_after_empty_replies_back_off(monkeypatch):
    pauses = []
    monkeypatch.setattr("aglc.llm.base._sleep", pauses.append)
    provider = FakeProvider("test", responses=["", "  ", '{"title": "T", "items": []}'])
    provider.generate_json(system="s", user="u", output_model=NestedModel)
    assert pauses == [1.0, 3.0]


def test_only_empty_replies_raise_transient_error():
    from aglc.llm.base import TransientLLMError

    provider = FakeProvider("test", responses=[""])
    with pytest.raises(TransientLLMError, match="empty reply"):
        provider.generate_json(system="s", user="u", output_model=NestedModel)
    assert len(provider.calls) == 3


def test_fallback_model_used_when_first_fails_every_attempt():
    primary = FakeProvider("primary", responses=[""])
    backup = FakeProvider("backup", responses=['{"title": "from backup", "items": []}'])
    primary.fallback = backup
    result = primary.generate_json(system="s", user="u", output_model=NestedModel)
    assert result.title == "from backup"
    assert len(primary.calls) == 3
    assert len(backup.calls) == 1


def test_fallback_model_not_used_when_first_succeeds():
    primary = FakeProvider("primary", responses=['{"title": "T", "items": []}'])
    primary.fallback = backup = FakeProvider("backup")
    primary.generate_json(system="s", user="u", output_model=NestedModel)
    assert backup.calls == []


def test_fallback_model_from_env(monkeypatch):
    monkeypatch.setenv("AGLC_LLM_FALLBACK", "fake:backup")
    provider = get_provider("fake:primary")
    assert provider.fallback is not None and provider.fallback.model == "backup"
    assert provider.fallback.fallback is None
    # the same model as its own fallback, or "" to turn it off
    assert get_provider("fake:backup").fallback is None
    assert get_provider("fake:primary", fallback="").fallback is None


def test_no_fallback_model_by_default():
    assert get_provider("fake:primary").fallback is None


# ============================================================================
# OpenAI / OpenRouter: empty content, transient errors, rerouting
# ============================================================================


def _completion(content, *, finish_reason="stop", host=None):
    msg = type("M", (), {"content": content, "refusal": None})()
    choice = type("C", (), {"message": msg, "finish_reason": finish_reason})()
    return type("R", (), {"choices": [choice], "provider": host, "id": "gen-123"})()


class _ScriptedCompletions:
    """chat.completions stand-in: each request gets the next item; exceptions are raised."""

    def __init__(self, script):
        self.script = list(script)
        self.requests = []

    def create(self, **req):
        self.requests.append(req)
        item = self.script[min(len(self.requests) - 1, len(self.script) - 1)]
        if isinstance(item, Exception):
            raise item
        return _maybe_streamed(req, item)


def _scripted_provider(monkeypatch, spec, script):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    provider = get_provider(spec)
    completions = _ScriptedCompletions(script)
    provider._client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    return provider, completions


def _http_request():
    import httpx

    return httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def test_openai_empty_content_is_transient_with_diagnostics(monkeypatch, caplog):
    from aglc.llm.base import TransientLLMError

    provider, completions = _scripted_provider(monkeypatch, "openai:gpt-test", [_completion("", host="SomeHost")])
    with pytest.raises(TransientLLMError) as err:
        provider.generate_json(system="s", user="u", output_model=SimpleModel)
    assert "empty reply" in str(err.value)
    assert "finish_reason=stop" in str(err.value) and "upstream=SomeHost" in str(err.value)
    assert len(completions.requests) == 3
    # never sent back to the model as a correction
    assert all(r["messages"][1]["content"] == "u" for r in completions.requests)


def test_openrouter_retry_after_empty_reply_avoids_that_host(monkeypatch):
    provider, completions = _scripted_provider(
        monkeypatch,
        "openrouter:deepseek/deepseek-v4.1-flash-1017",
        [_completion("", host="FlakyHost"), _completion('{"name": "A", "age": 1}', host="GoodHost")],
    )
    assert provider.generate_json(system="s", user="u", output_model=SimpleModel).name == "A"
    first, second = (r["extra_body"]["provider"] for r in completions.requests)
    assert first["ignore"] == ["DigitalOcean", "Sail Research"] and first["allow_fallbacks"] is True
    assert second["ignore"] == ["DigitalOcean", "Sail Research", "FlakyHost"]


def test_openrouter_ignored_hosts_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("AGLC_OPENROUTER_IGNORE", " HostA, HostB ,")
    provider, completions = _scripted_provider(
        monkeypatch, "openrouter:deepseek/deepseek-v4.1-flash-1017", [_completion('{"name": "A", "age": 1}')]
    )
    provider.generate_json(system="s", user="u", output_model=SimpleModel)
    assert completions.requests[0]["extra_body"]["provider"]["ignore"] == ["HostA", "HostB"]


def test_openrouter_data_collection_is_denied_unless_allowed(monkeypatch):
    provider, completions = _scripted_provider(
        monkeypatch, "openrouter:deepseek/deepseek-v4.1-flash-1017", [_completion('{"name": "A", "age": 1}')] * 2
    )
    provider.generate_json(system="s", user="u", output_model=SimpleModel)
    assert completions.requests[0]["extra_body"]["provider"]["data_collection"] == "deny"
    monkeypatch.setenv("AGLC_OPENROUTER_DATA_COLLECTION", "allow")
    provider.generate_json(system="s", user="u", output_model=SimpleModel)
    assert "data_collection" not in completions.requests[1]["extra_body"]["provider"]


def test_openrouter_ignore_list_can_be_turned_off(monkeypatch):
    monkeypatch.setenv("AGLC_OPENROUTER_IGNORE", "")
    provider, completions = _scripted_provider(
        monkeypatch, "openrouter:deepseek/deepseek-v4.1-flash-1017", [_completion('{"name": "A", "age": 1}')]
    )
    provider.generate_json(system="s", user="u", output_model=SimpleModel)
    assert "ignore" not in completions.requests[0]["extra_body"]["provider"]


def test_openrouter_allows_failed_hosts_again_when_none_left(monkeypatch):
    import httpx
    import openai

    no_endpoints = openai.NotFoundError(
        "No endpoints found", response=httpx.Response(404, request=_http_request()), body=None
    )
    provider, completions = _scripted_provider(
        monkeypatch,
        "openrouter:deepseek/deepseek-v4.1-flash-1017",
        [_completion("", host="OnlyHost"), no_endpoints, _completion('{"name": "A", "age": 1}', host="OnlyHost")],
    )
    assert provider.generate_json(system="s", user="u", output_model=SimpleModel).name == "A"
    assert completions.requests[1]["extra_body"]["provider"]["ignore"] == ["DigitalOcean", "Sail Research", "OnlyHost"]
    assert "ignore" not in completions.requests[2]["extra_body"]["provider"]  # the default list too


def test_openai_timeout_is_retried(monkeypatch):
    import openai

    provider, completions = _scripted_provider(
        monkeypatch,
        "openai:gpt-test",
        [openai.APITimeoutError(request=_http_request()), _completion('{"name": "A", "age": 1}')],
    )
    assert provider.generate_json(system="s", user="u", output_model=SimpleModel).name == "A"
    assert len(completions.requests) == 2


def test_openai_auth_error_is_not_retried(monkeypatch):
    import httpx
    import openai

    bad_key = openai.AuthenticationError("bad key", response=httpx.Response(401, request=_http_request()), body=None)
    provider, completions = _scripted_provider(monkeypatch, "openai:gpt-test", [bad_key])
    with pytest.raises(openai.AuthenticationError):
        provider.generate_json(system="s", user="u", output_model=SimpleModel)
    assert len(completions.requests) == 1


# ============================================================================
# OpenAI / OpenRouter: a hard deadline on each request, streamed replies
# ============================================================================


class _HangingStream:
    """A reply that never finishes, like a host sending keep-alive bytes forever."""

    def __init__(self):
        import threading

        self.closed = threading.Event()

    def __iter__(self):
        self.closed.wait(5)
        return iter([])

    def close(self):
        self.closed.set()


def test_a_request_that_never_finishes_is_given_up_at_the_deadline(monkeypatch):
    import time

    from aglc.llm.base import TransientLLMError

    hanging = _HangingStream()
    provider, completions = _scripted_provider(monkeypatch, "openrouter:x/y", [hanging])
    monkeypatch.setenv("AGLC_REQUEST_DEADLINE", "0.2")
    t0 = time.monotonic()
    with pytest.raises(TransientLLMError, match="no answer within 0.2s"):
        provider._complete_json(system="s", user="u", schema={}, schema_name="X")
    assert time.monotonic() - t0 < 2
    assert provider._client is None  # the stuck client is dropped; the next request gets a new one


def test_requests_stream_and_cap_the_reply(monkeypatch):
    provider, completions = _scripted_provider(monkeypatch, "openrouter:x/y", [_completion('{"name": "A", "age": 1}')])
    seen = []
    provider.on_text = seen.append
    assert provider.generate_json(system="s", user="u", output_model=SimpleModel).name == "A"
    req = completions.requests[0]
    assert req["stream"] is True and req["max_tokens"] == 16000
    assert "".join(seen) == '{"name": "A", "age": 1}'
    # OpenAI's own API names the cap differently
    provider, completions = _scripted_provider(monkeypatch, "openai:gpt-test", [_completion('{"name": "A", "age": 1}')])
    provider.generate_json(system="s", user="u", output_model=SimpleModel)
    assert completions.requests[0]["max_completion_tokens"] == 16000


def test_an_endpoint_that_refuses_streaming_is_asked_without_it(monkeypatch):
    import openai

    import httpx

    refused = openai.BadRequestError("stream is not supported", response=httpx.Response(400, request=_http_request()),
                                     body=None)
    provider, completions = _scripted_provider(
        monkeypatch, "openai:gpt-test", [refused, _completion('{"name": "B", "age": 2}')])
    assert provider.generate_json(system="s", user="u", output_model=SimpleModel).name == "B"
    assert completions.requests[0].get("stream") is True and "stream" not in completions.requests[1]
    assert provider._stream is False


def test_retries_and_the_fallback_model_are_reported(monkeypatch):
    from aglc.llm import get_provider as gp

    events = []
    provider = gp("fake:primary", fallback="fake:backup", responses=["", "", ""])
    provider.fallback._responses = ['{"name": "C", "age": 3}']
    provider.options["retry_delays"] = [0]
    provider.on_event = lambda kind, data: events.append(kind)
    provider.generate_json(system="s", user="u", output_model=SimpleModel)
    assert events == ["retry", "retry", "fallback"]


def test_a_host_that_half_answers_is_avoided_for_the_rest_of_the_run(monkeypatch):
    provider, completions = _scripted_provider(
        monkeypatch, "openrouter:x/y", [_completion('{"name": "A", "age": 1}', host="PartialHost")] * 2)
    provider.generate_json(system="s", user="u", output_model=SimpleModel)
    assert provider.avoid_last_host() is True and provider.avoid_last_host() is False  # once
    provider.generate_json(system="s", user="u", output_model=SimpleModel)
    assert "PartialHost" in completions.requests[1]["extra_body"]["provider"]["ignore"]
