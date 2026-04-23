"""Read-only /api/alerts endpoints with filters, pagination, and resend."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.db.models import Alert
from yas.db.models._types import AlertType
from yas.db.session import session_scope
from yas.web.routes.alerts_schemas import AlertListResponse, AlertOut

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    request: Request,
    kid_id: int | None = Query(default=None),
    type: AlertType | None = Query(default=None),
    status: Literal["pending", "sent", "skipped"] | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=25, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> AlertListResponse:
    async with session_scope(_engine(request)) as s:
        q = select(Alert)

        # Apply filters
        if kid_id is not None:
            q = q.where(Alert.kid_id == kid_id)

        if type is not None:
            q = q.where(Alert.type == type.value)

        if status is not None:
            if status == "pending":
                q = q.where(and_(Alert.sent_at.is_(None), ~Alert.skipped))
            elif status == "sent":
                q = q.where(Alert.sent_at.is_not(None))
            elif status == "skipped":
                q = q.where(Alert.skipped)

        if since is not None:
            q = q.where(Alert.scheduled_for >= since)

        if until is not None:
            q = q.where(Alert.scheduled_for <= until)

        # Get total count before pagination
        count_q = select(func.count()).select_from(Alert)
        # Re-apply filters to count query
        if kid_id is not None:
            count_q = count_q.where(Alert.kid_id == kid_id)
        if type is not None:
            count_q = count_q.where(Alert.type == type.value)
        if status is not None:
            if status == "pending":
                count_q = count_q.where(and_(Alert.sent_at.is_(None), ~Alert.skipped))
            elif status == "sent":
                count_q = count_q.where(Alert.sent_at.is_not(None))
            elif status == "skipped":
                count_q = count_q.where(Alert.skipped)
        if since is not None:
            count_q = count_q.where(Alert.scheduled_for >= since)
        if until is not None:
            count_q = count_q.where(Alert.scheduled_for <= until)

        total = await s.scalar(count_q)

        # Apply pagination and fetch
        q = q.order_by(Alert.id.desc()).limit(limit).offset(offset)
        rows = (await s.execute(q)).scalars().all()

        items = [AlertOut.model_validate(row) for row in rows]
        return AlertListResponse(items=items, total=total or 0, limit=limit, offset=offset)


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(request: Request, alert_id: int) -> AlertOut:
    async with session_scope(_engine(request)) as s:
        alert = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        return AlertOut.model_validate(alert)


@router.post("/{alert_id}/resend", response_model=AlertOut, status_code=status.HTTP_202_ACCEPTED)
async def resend_alert(request: Request, alert_id: int) -> AlertOut:
    async with session_scope(_engine(request)) as s:
        # Fetch the original alert
        original = (
            await s.execute(select(Alert).where(Alert.id == alert_id))
        ).scalar_one_or_none()
        if original is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")

        # Clone the alert
        now = datetime.now(UTC)
        new_dedup_key = f"{original.dedup_key}:resend:{now.isoformat()}"
        cloned = Alert(
            type=original.type,
            kid_id=original.kid_id,
            offering_id=original.offering_id,
            site_id=original.site_id,
            channels=original.channels,
            scheduled_for=now,
            sent_at=None,
            skipped=False,
            dedup_key=new_dedup_key,
            payload_json=copy.deepcopy(original.payload_json),
        )
        s.add(cloned)
        await s.flush()

        return AlertOut.model_validate(cloned)
