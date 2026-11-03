"""Read-only /api/alerts endpoints with filters, pagination, and resend."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from yas.db.models import Alert, Kid
from yas.db.models._types import AlertType
from yas.db.session import session_scope
from yas.web.routes.alerts_schemas import (
    AlertBulkCloseIn,
    AlertBulkCloseOut,
    AlertCloseIn,
    AlertListResponse,
    AlertOut,
)
from yas.web.routes.inbox_alert_summary import AlertNames, load_alert_names, summarize_alert

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


def _alert_out(alert: Alert, kid_name: str | None, names: AlertNames) -> AlertOut:
    try:
        at: AlertType | str = AlertType(alert.type)
    except ValueError:
        at = alert.type
    offering_name, site_name = names
    summary = summarize_alert(
        at,
        kid_name=kid_name,
        payload=alert.payload_json or {},
        offering_name=offering_name,
        site_name=site_name,
    )
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


async def _to_outs(s: AsyncSession, rows: Sequence[tuple[Alert, str | None]]) -> list[AlertOut]:
    """AlertOut for each (alert, kid_name) row, with names loaded in one batch."""
    names = await load_alert_names(s, [a for a, _ in rows])
    return [_alert_out(a, kid_name, names[a.id]) for a, kid_name in rows]


async def _to_out(s: AsyncSession, alert: Alert) -> AlertOut:
    """Convert one Alert row to AlertOut, looking up its kid's name."""
    kid_name = None
    if alert.kid_id is not None:
        kid_name = (
            await s.execute(select(Kid.name).where(Kid.id == alert.kid_id))
        ).scalar_one_or_none()
    return (await _to_outs(s, [(alert, kid_name)]))[0]


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

        items = await _to_outs(s, [(alert, kid_name) for alert, kid_name in rows])
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
        return (await _to_outs(s, [(alert, kid_name)]))[0]


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
            # A fresh send: delivery appends the channels it reaches, and the
            # original's "_"-prefixed bookkeeping (_attempts, _skipped_reason,
            # _failed) would make a resent give-up fail on its first hiccup.
            channels=[],
            scheduled_for=now,
            sent_at=None,
            skipped=False,
            dedup_key=new_dedup_key,
            payload_json={
                k: copy.deepcopy(v)
                for k, v in (original.payload_json or {}).items()
                if not k.startswith("_")
            },
        )
        s.add(cloned)
        await s.flush()
        await s.refresh(cloned)

        return await _to_out(s, cloned)


# NOTE: /bulk/close MUST be declared before /{alert_id}/close. Otherwise
# FastAPI tries to match "bulk" as the {alert_id: int} path param and
# returns 422 before the literal route is consulted.
@router.post("/bulk/close", response_model=AlertBulkCloseOut)
async def bulk_close_alerts(request: Request, body: AlertBulkCloseIn) -> AlertBulkCloseOut:
    """Close many alerts in one request. Idempotent: already-closed alerts
    have their close_reason updated but closed_at preserved. Missing IDs are
    returned in `not_found` rather than 404'ing the whole request — partial
    success is the common case for bulk UX."""
    if not body.alert_ids:
        return AlertBulkCloseOut(closed=[], not_found=[])
    requested = list(set(body.alert_ids))
    async with session_scope(_engine(request)) as s:
        rows = (await s.execute(select(Alert).where(Alert.id.in_(requested)))).scalars().all()
        found_ids = {a.id for a in rows}
        not_found = [aid for aid in requested if aid not in found_ids]
        now = datetime.now(UTC)
        for alert in rows:
            if alert.closed_at is None:
                alert.closed_at = now
            alert.close_reason = body.reason
        await s.flush()
        for alert in rows:
            await s.refresh(alert)
        kid_ids = {a.kid_id for a in rows if a.kid_id is not None}
        kid_names: dict[int, str] = {}
        if kid_ids:
            kid_rows = await s.execute(select(Kid.id, Kid.name).where(Kid.id.in_(kid_ids)))
            kid_names = {kid_id: name for kid_id, name in kid_rows.all()}
        closed_outs = await _to_outs(
            s, [(a, kid_names.get(a.kid_id) if a.kid_id else None) for a in rows]
        )
        closed_outs.sort(key=lambda a: a.id)
        return AlertBulkCloseOut(closed=closed_outs, not_found=sorted(not_found))


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
