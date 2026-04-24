"""Digest preview endpoint."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.alerts.digest.builder import gather_digest_payload, render_digest
from yas.alerts.digest.llm_summary import generate_top_line
from yas.db.models import HouseholdSettings, Kid
from yas.db.session import session_scope
from yas.web.routes.digest_preview_schemas import DigestPreviewOut

router = APIRouter(prefix="/api/digest", tags=["digest"])

_DEFAULT_COST_CAP_USD = 1.0


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


@router.get("/preview", response_model=DigestPreviewOut)
async def preview_digest(
    request: Request,
    kid_id: Annotated[int, Query()],
) -> DigestPreviewOut:
    """Generate a digest preview for a kid without enqueueing.

    Uses the past 24 hours of activity and renders the digest.
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=24)
    window_end = now

    async with session_scope(_engine(request)) as s:
        # Fetch the kid
        kid = (await s.execute(select(Kid).where(Kid.id == kid_id))).scalar_one_or_none()
        if kid is None:
            raise HTTPException(status_code=404, detail=f"kid {kid_id} not found")

        # Load household settings for cost cap
        household = (await s.execute(select(HouseholdSettings).limit(1))).scalar_one_or_none()
        cost_cap = (
            household.daily_llm_cost_cap_usd if household is not None else _DEFAULT_COST_CAP_USD
        )

        # Gather payload
        settings = request.app.state.yas.settings
        payload = await gather_digest_payload(
            s,
            kid,
            window_start=window_start,
            window_end=window_end,
            alert_no_matches_kid_days=settings.alert_no_matches_kid_days,
            now=now,
        )

        # Generate top line with LLM (may be None)
        llm = request.app.state.yas.llm
        top_line = await generate_top_line(
            payload,
            llm,
            cost_cap_remaining_usd=cost_cap,
        )

        # Render digest
        body_plain, body_html = render_digest(payload, top_line)
        subject = f"Daily digest — {kid.name} — {now.date().isoformat()}"

        return DigestPreviewOut(
            subject=subject,
            body_plain=body_plain,
            body_html=body_html,
        )
