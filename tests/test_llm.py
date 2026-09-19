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
    assert provider.name == "anthropic"
    assert provider.model == "claude-opus-5"


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

    provider = get_provider("openai:gpt-4")
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

    provider = get_provider("openai:gpt-4")
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
                return type("R", (), {"choices": [choice]})()

        self.chat = type("Chat", (), {"completions": _Completions()})()


def test_openrouter_uses_openrouter_endpoint_and_key(monkeypatch):
    import openai
    from pydantic import BaseModel

    class Out(BaseModel):
        value: str

    monkeypatch.setattr(openai, "OpenAI", _RecordingOpenAI)
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    provider = get_provider("openrouter:deepseek/deepseek-v4-flash")
    assert provider.generate_json(system="s", user="u", output_model=Out).value == "ok"

    client = _RecordingOpenAI.instances[-1]
    assert client.kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert client.kwargs["api_key"] == "sk-or-test"
    req = client.requests[0]
    assert req["model"] == "deepseek/deepseek-v4-flash"
    assert req["response_format"]["type"] == "json_schema"
    assert req["extra_body"] == {"provider": {"require_parameters": True}}


def test_openrouter_without_key_gives_helpful_error(monkeypatch):
    from pydantic import BaseModel

    class Out(BaseModel):
        value: str

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    provider = get_provider("openrouter:deepseek/deepseek-v4-flash")
    with pytest.raises(LLMError, match="OPENROUTER_API_KEY"):
        provider.generate_json(system="s", user="u", output_model=Out)
