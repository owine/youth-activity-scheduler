from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class CredentialStatus(BaseModel):
    """Per-credential status: where the value resolves from, if anywhere.

    via:
      - "form" — user pasted a value into the Settings UI (stored in DB)
      - "env"  — conventional env var is set (e.g. YAS_PUSHOVER_USER_KEY)
      - null   — neither; channel can't construct
    """

    via: str | None
    env_var: str


class HouseholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    home_location_id: int | None
    home_address: str | None
    home_location_name: str | None
    home_lat: float | None
    home_lon: float | None
    default_max_distance_mi: float | None
    digest_time: str
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    daily_llm_cost_cap_usd: float
    email_configured: bool
    ntfy_configured: bool
    pushover_configured: bool
    # Per-credential status: tells the UI whether each secret resolves
    # from a form-stored override, an env var, or is unset. Empty when
    # the corresponding *_config_json is null (channel not configured).
    credential_status: dict[str, CredentialStatus] = {}
    # Redacted channel configs — secret *_value keys are stripped so
    # the UI can pre-populate non-secret fields (transport, host,
    # from_addr, to_addrs, devices, etc.) on edit. Credentials are
    # never returned; the form leaves those fields blank and the
    # credential_status badge tells the user where the secret resolves.
    smtp_config_json: dict[str, Any] | None = None
    ntfy_config_json: dict[str, Any] | None = None
    pushover_config_json: dict[str, Any] | None = None


class HouseholdPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Ergonomic: set home by address; handler creates/updates the Location row.
    home_address: str | None = None
    home_location_name: str | None = None
    # Or set directly by id.
    home_location_id: int | None = None
    default_max_distance_mi: float | None = None
    digest_time: str | None = None
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    daily_llm_cost_cap_usd: float | None = None
    smtp_config_json: dict[str, Any] | None = None
    ha_config_json: dict[str, Any] | None = None
    ntfy_config_json: dict[str, Any] | None = None
    pushover_config_json: dict[str, Any] | None = None
