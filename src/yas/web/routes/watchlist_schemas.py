"""Pydantic models for /api/kids/{id}/watchlist endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class WatchlistCreate(BaseModel):
    """Shared shape consumed by `/api/kids/{id}/watchlist` POST and by
    the nested atomic-create inside `/api/kids` POST."""

    model_config = ConfigDict(extra="forbid")
    pattern: str = Field(min_length=1)
    site_id: int | None = None
    priority: str = "normal"
    notes: str | None = None
    active: bool = True
    # Reserved for a future "strict mode" opt-in; not consulted by the matcher
    # in Phase 3. See src/yas/db/models/watchlist.py.
    ignore_hard_gates: bool = False


class WatchlistPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pattern: str | None = None
    site_id: int | None = None
    priority: str | None = None
    notes: str | None = None
    active: bool | None = None
    ignore_hard_gates: bool | None = None


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    kid_id: int
    site_id: int | None
    pattern: str
    priority: str
    notes: str | None
    active: bool
    ignore_hard_gates: bool
    created_at: datetime
