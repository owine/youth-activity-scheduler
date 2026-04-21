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


def get_settings() -> Settings:
    """Factory so callers get a fresh read when needed (tests, reload)."""
    return Settings()
