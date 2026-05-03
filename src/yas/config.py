"""Application configuration loaded from environment."""

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="YAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Storage
    database_url: str = "sqlite+aiosqlite:////data/activities.db"
    data_dir: str = "/data"

    # LLM
    anthropic_api_key: str = Field(..., description="Anthropic API key (required)")

    # HTTP server
    host: str = "0.0.0.0"
    port: int = 8080

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Worker
    worker_heartbeat_interval_s: int = 10
    worker_heartbeat_staleness_s: int = 60

    # Crawl scheduler
    crawl_scheduler_enabled: bool = True
    crawl_scheduler_tick_s: int = 30
    crawl_scheduler_batch_size: int = 10

    # LLM extraction
    llm_extraction_model: str = "claude-haiku-4-5-20251001"

    # Geocoder
    geocode_enabled: bool = True
    geocode_tick_s: int = 300
    geocode_batch_size: int = 20
    geocode_nominatim_min_interval_s: float = 1.0

    # Drive-time (OSRM-backed routed driving distance/duration). Off
    # by default so existing great-circle behavior is unchanged. When
    # enabled, the matcher uses drive minutes against
    # `kid.max_drive_minutes` instead of haversine miles.
    drive_time_enabled: bool = False
    osrm_base_url: str = "https://router.project-osrm.org"

    # Daily sweep
    sweep_enabled: bool = True
    sweep_time_utc: str = "07:00"

    # Site discovery
    discovery_enabled: bool = True
    discovery_max_candidates: int = 50
    discovery_max_returned: int = 20
    discovery_min_score: float = 0.5
    discovery_head_fetch_concurrency: int = 10
    discovery_head_fetch_timeout_s: int = 10

    # Alerting
    alerts_enabled: bool = True
    alert_delivery_tick_s: int = 60
    alert_coalesce_normal_s: int = 600
    alert_max_pushes_per_hour: int = 5
    alert_digest_time_utc: str = "07:00"
    alert_detector_time_utc: str = "09:00"
    alert_stagnant_site_days: int = 30
    alert_no_matches_kid_days: int = 7
    alert_countdown_past_due_grace_s: int = 86400
    alert_digest_empty_skip: bool = True

    # Channel secrets (env-only). Missing env disables the channel at runtime.
    smtp_password: str | None = None
    forwardemail_api_token: str | None = None
    ntfy_auth_token: str | None = None
    pushover_user_key: str | None = None
    pushover_app_token: str | None = None


def get_settings() -> Settings:
    """Factory so callers get a fresh read when needed (tests, reload)."""
    return Settings()
