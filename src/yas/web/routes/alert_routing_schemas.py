"""Pydantic models for /api/alert_routing endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from yas.db.models._types import AlertType


class AlertRoutingOut(BaseModel):
    """Alert routing detail for GET responses."""

    model_config = ConfigDict(from_attributes=True)

    type: AlertType
    channels: list[str]
    enabled: bool


class AlertRoutingPatch(BaseModel):
    """Patch request for alert routing."""

    channels: list[str] | None = None
    enabled: bool | None = None

    @field_validator("channels")
    @classmethod
    def _channels_not_empty(cls, v: list[str] | None) -> list[str] | None:
        if v is not None and len(v) == 0:
            raise ValueError("channels must not be empty; set enabled=false to disable")
        return v
