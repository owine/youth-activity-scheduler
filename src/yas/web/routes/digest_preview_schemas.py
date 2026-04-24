"""Pydantic models for /api/digest/preview endpoint."""

from __future__ import annotations

from pydantic import BaseModel


class DigestPreviewOut(BaseModel):
    """Digest preview response."""

    subject: str
    body_plain: str
    body_html: str
