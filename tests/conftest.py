import pytest


@pytest.fixture(autouse=True)
def _isolate_from_local_env(monkeypatch):
    """The CLI/API load the developer's .env on import; tests must not depend on it."""
    for var in ("AGLC_LLM", "OPENROUTER_API_KEY", "AGLC_OPENAI_BASE_URL", "AGLC_OPENAI_API_KEY", "AGLC_REASONING",
                "AGLC_PAYMENTS", "AGLC_DATA_DIR", "AGLC_PUBLIC_URL", "AGLC_CLIENT_IP_HEADER", "AGLC_IP_SALT",
                "AGLC_FREE_PER_DAY", "AGLC_FREE_PER_IP_PER_DAY", "AGLC_FREE_GLOBAL_PER_DAY", "AGLC_MAX_FOOTNOTES",
                "AGLC_MAX_CONCURRENT", "AGLC_FAKE_WEBHOOK_SECRET"):
        monkeypatch.delenv(var, raising=False)
