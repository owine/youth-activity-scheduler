import pytest
from pydantic import ValidationError

from yas.config import Settings


def _settings() -> Settings:
    """Build Settings without reading a developer's local .env file."""
    return Settings(_env_file=None)  # type: ignore[call-arg]


def test_settings_load_defaults(monkeypatch):
    monkeypatch.delenv("YAS_DATABASE_URL", raising=False)
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    assert s.database_url == "sqlite+aiosqlite:////data/activities.db"
    assert s.anthropic_api_key == "sk-test"
    assert s.log_level == "INFO"
    assert s.host == "0.0.0.0"
    assert s.port == 8080


def test_settings_override_via_env(monkeypatch):
    monkeypatch.setenv("YAS_DATABASE_URL", "sqlite+aiosqlite:///tmp/x.db")
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("YAS_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("YAS_PORT", "9999")
    s = _settings()
    assert s.database_url == "sqlite+aiosqlite:///tmp/x.db"
    assert s.log_level == "DEBUG"
    assert s.port == 9999


def test_settings_requires_anthropic_key(monkeypatch):
    monkeypatch.delenv("YAS_ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        _settings()
