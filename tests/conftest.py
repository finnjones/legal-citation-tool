import pytest


@pytest.fixture(autouse=True)
def _isolate_from_local_env(monkeypatch):
    """The CLI/API load the developer's .env on import; tests must not depend on it."""
    for var in ("AGLC_LLM", "OPENROUTER_API_KEY", "AGLC_OPENAI_BASE_URL", "AGLC_OPENAI_API_KEY", "AGLC_REASONING",
                "AGLC_PAYMENTS", "AGLC_DATA_DIR", "AGLC_PUBLIC_URL", "AGLC_CLIENT_IP_HEADER", "AGLC_IP_SALT",
                "AGLC_FREE_PER_DAY", "AGLC_FREE_PER_IP_PER_DAY", "AGLC_FREE_GLOBAL_PER_DAY", "AGLC_MAX_FOOTNOTES",
                "AGLC_MAX_CONCURRENT", "AGLC_FAKE_WEBHOOK_SECRET", "AGLC_MAX_FAILED_SHARE", "AGLC_RETENTION_HOURS",
                "AGLC_MAX_UPLOAD_MB", "SQUARE_WEBHOOK_URL", "SQUARE_WEBHOOK_SIGNATURE_KEY", "AGLC_LLM_FALLBACK", "AGLC_PLAUSIBLE_DOMAIN",
                "AGLC_OPENROUTER_IGNORE"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture(autouse=True)
def _no_retry_pauses(monkeypatch):
    """Retries after an empty or failed reply pause for a second or two; not in tests."""
    monkeypatch.setattr("aglc.llm.base._sleep", lambda seconds: None)
