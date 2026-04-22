from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HouseholdOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    home_location_id: int | None
    default_max_distance_mi: float | None
    digest_time: str
    quiet_hours_start: str | None
    quiet_hours_end: str | None
    daily_llm_cost_cap_usd: float


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
