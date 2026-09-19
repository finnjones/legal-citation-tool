import pytest


@pytest.fixture(autouse=True)
def _isolate_from_local_env(monkeypatch):
    """The CLI/API load the developer's .env on import; tests must not depend on it."""
    for var in ("AGLC_LLM", "OPENROUTER_API_KEY", "AGLC_OPENAI_BASE_URL", "AGLC_OPENAI_API_KEY", "AGLC_REASONING"):
        monkeypatch.delenv(var, raising=False)
