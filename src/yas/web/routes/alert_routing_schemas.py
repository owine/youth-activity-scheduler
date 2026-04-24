"""Pydantic models for /api/alert_routing endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

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
