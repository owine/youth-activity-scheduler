"""Read-only /api/alerts endpoints with filters, pagination, and resend."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.db.models import Alert, Kid
from yas.db.models._types import AlertType
from yas.db.session import session_scope
from yas.web.routes.alerts_schemas import AlertCloseIn, AlertListResponse, AlertOut
from yas.web.routes.inbox_alert_summary import summarize_alert

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


async def _to_out(s: AsyncSession, alert: Alert) -> AlertOut:
    """Convert an Alert row to AlertOut, populating summary_text."""
    kid_name = None
    if alert.kid_id is not None:
        kid_name = (
            await s.execute(select(Kid.name).where(Kid.id == alert.kid_id))
        ).scalar_one_or_none()
    try:
        at: AlertType | str = AlertType(alert.type)
    except ValueError:
        at = alert.type
    summary = summarize_alert(at, kid_name=kid_name, payload=alert.payload_json or {})
    return AlertOut(
        id=alert.id,
        type=alert.type,
        kid_id=alert.kid_id,
        offering_id=alert.offering_id,
        site_id=alert.site_id,
        channels=list(alert.channels or []),
        scheduled_for=alert.scheduled_for,
        sent_at=alert.sent_at,
        skipped=alert.skipped,
        dedup_key=alert.dedup_key,
        payload_json=alert.payload_json or {},
        closed_at=alert.closed_at,
        close_reason=alert.close_reason,
        summary_text=summary,
    )


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    request: Request,
    kid_id: Annotated[int | None, Query()] = None,
    type: Annotated[AlertType | None, Query()] = None,
    status: Annotated[Literal["pending", "sent", "skipped"] | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AlertListResponse:
    async with session_scope(_engine(request)) as s:
        q = select(Alert, Kid.name).outerjoin(Kid, Kid.id == Alert.kid_id)

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
        rows = (await s.execute(q)).all()

        items: list[AlertOut] = []
        for alert, kid_name in rows:
            try:
                at: AlertType | str = AlertType(alert.type)
            except ValueError:
                at = alert.type
            summary = summarize_alert(
                at,
                kid_name=kid_name,
                payload=alert.payload_json or {},
            )
            items.append(
                AlertOut(
                    id=alert.id,
                    type=alert.type,
                    kid_id=alert.kid_id,
                    offering_id=alert.offering_id,
                    site_id=alert.site_id,
                    channels=list(alert.channels or []),
                    scheduled_for=alert.scheduled_for,
                    sent_at=alert.sent_at,
                    skipped=alert.skipped,
                    dedup_key=alert.dedup_key,
                    payload_json=alert.payload_json or {},
                    closed_at=alert.closed_at,
                    close_reason=alert.close_reason,
                    summary_text=summary,
                )
            )
        return AlertListResponse(items=items, total=total or 0, limit=limit, offset=offset)


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert(request: Request, alert_id: int) -> AlertOut:
    async with session_scope(_engine(request)) as s:
        row = (
            await s.execute(
                select(Alert, Kid.name)
                .outerjoin(Kid, Kid.id == Alert.kid_id)
                .where(Alert.id == alert_id)
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        alert, kid_name = row
        try:
            at: AlertType | str = AlertType(alert.type)
        except ValueError:
            at = alert.type
        summary = summarize_alert(at, kid_name=kid_name, payload=alert.payload_json or {})
        return AlertOut(
            id=alert.id,
            type=alert.type,
            kid_id=alert.kid_id,
            offering_id=alert.offering_id,
            site_id=alert.site_id,
            channels=list(alert.channels or []),
            scheduled_for=alert.scheduled_for,
            sent_at=alert.sent_at,
            skipped=alert.skipped,
            dedup_key=alert.dedup_key,
            payload_json=alert.payload_json or {},
            closed_at=alert.closed_at,
            close_reason=alert.close_reason,
            summary_text=summary,
        )


@router.post("/{alert_id}/resend", response_model=AlertOut, status_code=status.HTTP_202_ACCEPTED)
async def resend_alert(request: Request, alert_id: int) -> AlertOut:
    async with session_scope(_engine(request)) as s:
        # Fetch the original alert
        original = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
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
            channels=list(original.channels),
            scheduled_for=now,
            sent_at=None,
            skipped=False,
            dedup_key=new_dedup_key,
            payload_json=copy.deepcopy(original.payload_json),
        )
        s.add(cloned)
        await s.flush()

        return await _to_out(s, cloned)


@router.post("/{alert_id}/close", response_model=AlertOut)
async def close_alert(request: Request, alert_id: int, body: AlertCloseIn) -> AlertOut:
    async with session_scope(_engine(request)) as s:
        alert = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        if alert.closed_at is None:
            alert.closed_at = datetime.now(UTC)
        alert.close_reason = body.reason
        await s.flush()
        await s.refresh(alert)
        return await _to_out(s, alert)


@router.post("/{alert_id}/reopen", response_model=AlertOut)
async def reopen_alert(request: Request, alert_id: int) -> AlertOut:
    async with session_scope(_engine(request)) as s:
        alert = (await s.execute(select(Alert).where(Alert.id == alert_id))).scalar_one_or_none()
        if alert is None:
            raise HTTPException(status_code=404, detail=f"alert {alert_id} not found")
        alert.closed_at = None
        alert.close_reason = None
        await s.flush()
        return await _to_out(s, alert)
