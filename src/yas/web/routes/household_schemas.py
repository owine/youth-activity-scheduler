from __future__ import annotations

import re
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# 00:00-23:59. The delivery loop parses quiet hours with datetime.time on every
# tick, so a value it can't parse ("24:00") must not get stored.
_HHMM = re.compile(r"(?:[01]\d|2[0-3]):[0-5]\d")


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

    @field_validator("digest_time", "quiet_hours_start", "quiet_hours_end")
    @classmethod
    def _valid_hhmm(cls, v: str | None) -> str | None:
        if v is not None and not _HHMM.fullmatch(v):
            raise ValueError("must be HH:MM, 00:00-23:59")
        return v

    @field_validator("digest_time", "daily_llm_cost_cap_usd")
    @classmethod
    def _not_null(cls, v: object) -> object:
        # Omitting a field leaves it alone (the default isn't validated), but an
        # explicit null would write None into a NOT NULL column and 500. Quiet
        # hours stay nullable: null there clears them.
        if v is None:
            raise ValueError("cannot be null")
        return v

    @model_validator(mode="after")
    def _no_home_id_while_clearing_address(self) -> Self:
        # Clearing the address deletes the home Location, so an id in the same
        # patch would point at a deleted row (or contradict the clear).
        clearing = "home_address" in self.model_fields_set and not (self.home_address or "").strip()
        if clearing and self.home_location_id is not None:
            raise ValueError("home_location_id cannot be set while clearing home_address")
        return self
