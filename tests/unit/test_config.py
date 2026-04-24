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


def test_crawl_scheduler_defaults(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    assert s.crawl_scheduler_enabled is True
    assert s.crawl_scheduler_tick_s == 30
    assert s.crawl_scheduler_batch_size == 10
    assert s.llm_extraction_model == "claude-haiku-4-5-20251001"


def test_crawl_scheduler_overrides(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("YAS_CRAWL_SCHEDULER_TICK_S", "5")
    monkeypatch.setenv("YAS_CRAWL_SCHEDULER_BATCH_SIZE", "3")
    monkeypatch.setenv("YAS_CRAWL_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("YAS_LLM_EXTRACTION_MODEL", "claude-sonnet-4-6")
    s = _settings()
    assert s.crawl_scheduler_tick_s == 5
    assert s.crawl_scheduler_batch_size == 3
    assert s.crawl_scheduler_enabled is False
    assert s.llm_extraction_model == "claude-sonnet-4-6"


def test_geocode_settings_defaults(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    assert s.geocode_enabled is True
    assert s.geocode_tick_s == 300
    assert s.geocode_batch_size == 20
    assert s.geocode_nominatim_min_interval_s == 1.0


def test_sweep_settings_defaults(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    assert s.sweep_enabled is True
    assert s.sweep_time_utc == "07:00"


def test_discovery_settings_defaults(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    assert s.discovery_enabled is True
    assert s.discovery_max_candidates == 50
    assert s.discovery_max_returned == 20
    assert s.discovery_min_score == 0.5
    assert s.discovery_head_fetch_concurrency == 10
    assert s.discovery_head_fetch_timeout_s == 10


def test_discovery_settings_overrides(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("YAS_DISCOVERY_MAX_CANDIDATES", "30")
    monkeypatch.setenv("YAS_DISCOVERY_MIN_SCORE", "0.7")
    s = _settings()
    assert s.discovery_max_candidates == 30
    assert s.discovery_min_score == 0.7


def test_alert_settings_defaults(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    assert s.alerts_enabled is True
    assert s.alert_delivery_tick_s == 60
    assert s.alert_coalesce_normal_s == 600
    assert s.alert_max_pushes_per_hour == 5
    assert s.alert_digest_time_utc == "07:00"
    assert s.alert_detector_time_utc == "09:00"
    assert s.alert_stagnant_site_days == 30
    assert s.alert_no_matches_kid_days == 7
    assert s.alert_countdown_past_due_grace_s == 86400
    assert s.alert_digest_empty_skip is True


def test_alert_channel_secrets_optional(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    s = _settings()
    # All None by default — channel adapters disable themselves when None.
    assert s.smtp_password is None
    assert s.forwardemail_api_token is None
    assert s.ntfy_auth_token is None
    assert s.pushover_user_key is None
    assert s.pushover_app_token is None


def test_alert_channel_secrets_from_env(monkeypatch):
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("YAS_SMTP_PASSWORD", "hunter2")
    monkeypatch.setenv("YAS_PUSHOVER_USER_KEY", "u123")
    s = _settings()
    assert s.smtp_password == "hunter2"
    assert s.pushover_user_key == "u123"
