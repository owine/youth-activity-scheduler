"""Schemas for POST /api/notifiers/{channel}/test."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class TestSendOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    ok: bool
    detail: str
