"""Pydantic models for /api/alerts endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from yas.db.models._types import CloseReason


class AlertOut(BaseModel):
    """Alert detail for GET responses."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    kid_id: int | None
    offering_id: int | None
    site_id: int | None
    channels: list[str]
    scheduled_for: datetime
    sent_at: datetime | None
    skipped: bool
    dedup_key: str
    payload_json: dict[str, Any]
    closed_at: datetime | None = None
    close_reason: CloseReason | None = None
    summary_text: str = ""  # populated by handlers via summarize_alert


class AlertListResponse(BaseModel):
    """Paginated alert list response."""

    items: list[AlertOut]
    total: int
    limit: int
    offset: int


class AlertCloseIn(BaseModel):
    """Request body for POST /api/alerts/{id}/close."""

    reason: CloseReason


class AlertBulkCloseIn(BaseModel):
    """Request body for POST /api/alerts/bulk/close."""

    alert_ids: list[int]
    reason: CloseReason


class AlertBulkCloseOut(BaseModel):
    """Response for POST /api/alerts/bulk/close."""

    closed: list[AlertOut]
    not_found: list[int]
