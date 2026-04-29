"""Pydantic models for GET /api/inbox/summary."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict

from yas.db.models._types import CloseReason


class InboxAlertOut(BaseModel):
    """Enriched alert shape for the inbox endpoint.

    Distinct from AlertOut in alerts_schemas.py: adds kid_name (joined) and
    summary_text (server-composed). Existing /api/alerts endpoints continue
    to return the plain AlertOut.
    """

    model_config = ConfigDict(from_attributes=True)
    id: int
    type: str
    kid_id: int | None
    kid_name: str | None
    offering_id: int | None
    site_id: int | None
    channels: list[str]
    scheduled_for: datetime
    sent_at: datetime | None
    skipped: bool
    dedup_key: str
    payload_json: dict[str, Any]
    summary_text: str
    closed_at: datetime | None = None
    close_reason: CloseReason | None = None


class InboxKidMatchCountOut(BaseModel):
    kid_id: int
    kid_name: str
    total_new: int
    opening_soon_count: int


class InboxSiteActivityOut(BaseModel):
    refreshed_count: int
    posted_new_count: int
    stagnant_count: int


class InboxSummaryOut(BaseModel):
    window_start: datetime
    window_end: datetime
    alerts: list[InboxAlertOut]
    new_matches_by_kid: list[InboxKidMatchCountOut]
    site_activity: InboxSiteActivityOut
