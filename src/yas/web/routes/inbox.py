"""GET /api/inbox/summary — single-roundtrip aggregate for the dashboard inbox."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.alerts.detectors.site_stagnant import detect_stagnant_sites
from yas.db.models import Alert, CrawlRun, Kid, Match, Offering
from yas.db.models._types import AlertType, CrawlStatus
from yas.db.session import session_scope
from yas.web.routes.inbox_alert_summary import summarize_alert
from yas.web.routes.inbox_schemas import (
    InboxAlertOut,
    InboxKidMatchCountOut,
    InboxSiteActivityOut,
    InboxSummaryOut,
)

router = APIRouter(prefix="/api/inbox", tags=["inbox"])


def _engine(req: Request) -> AsyncEngine:
    engine: AsyncEngine = req.app.state.yas.engine
    return engine


@router.get("/summary", response_model=InboxSummaryOut)
async def inbox_summary(
    request: Request,
    since: Annotated[datetime, Query()],
    until: Annotated[datetime, Query()],
    include_closed: Annotated[bool, Query()] = False,
) -> InboxSummaryOut:
    if since >= until:
        raise HTTPException(status_code=422, detail="since must be before until")

    settings = request.app.state.yas.settings
    now = datetime.now(UTC)
    opens_soon_window_end = now + timedelta(days=7)

    async with session_scope(_engine(request)) as s:
        # --- Alerts in window with kid_name joined ---
        alerts_q = (
            select(Alert, Kid.name)
            .outerjoin(Kid, Kid.id == Alert.kid_id)
            .where(Alert.scheduled_for >= since)
            .where(Alert.scheduled_for < until)
            .order_by(Alert.scheduled_for.desc())
            .limit(50)
        )
        if not include_closed:
            alerts_q = alerts_q.where(Alert.closed_at.is_(None))
        alert_rows = (await s.execute(alerts_q)).all()
        inbox_alerts: list[InboxAlertOut] = []
        for alert, kid_name in alert_rows:
            try:
                at: AlertType | str = AlertType(alert.type)
            except ValueError:
                # Unknown type stored — defensive; summarize_alert handles str too.
                at = alert.type
            summary = summarize_alert(at, kid_name=kid_name, payload=alert.payload_json or {})
            inbox_alerts.append(
                InboxAlertOut(
                    id=alert.id,
                    type=alert.type,
                    kid_id=alert.kid_id,
                    kid_name=kid_name,
                    offering_id=alert.offering_id,
                    site_id=alert.site_id,
                    channels=list(alert.channels or []),
                    scheduled_for=alert.scheduled_for,
                    sent_at=alert.sent_at,
                    skipped=alert.skipped,
                    dedup_key=alert.dedup_key,
                    payload_json=alert.payload_json or {},
                    summary_text=summary,
                    closed_at=alert.closed_at,
                    close_reason=alert.close_reason,
                )
            )

        # --- New matches grouped by kid ---
        # total_new: matches where computed_at IN [since, until)
        # opening_soon_count: subset whose offering has registration_opens_at IN [now, now+7d]
        per_kid_total_q = (
            select(Kid.id, Kid.name, func.count())
            .join(Match, Match.kid_id == Kid.id)
            .where(Match.computed_at >= since)
            .where(Match.computed_at < until)
            .group_by(Kid.id, Kid.name)
        )
        per_kid_total_rows = (await s.execute(per_kid_total_q)).all()

        per_kid_opens_q = (
            select(Kid.id, func.count())
            .join(Match, Match.kid_id == Kid.id)
            .join(Offering, Offering.id == Match.offering_id)
            .where(Match.computed_at >= since)
            .where(Match.computed_at < until)
            .where(Offering.registration_opens_at.is_not(None))
            .where(Offering.registration_opens_at >= now)
            .where(Offering.registration_opens_at < opens_soon_window_end)
            .group_by(Kid.id)
        )
        per_kid_opens_rows: dict[int, int] = {
            kid_id: count for kid_id, count in (await s.execute(per_kid_opens_q)).all()
        }

        new_matches_by_kid = [
            InboxKidMatchCountOut(
                kid_id=kid_id,
                kid_name=kid_name,
                total_new=total,
                opening_soon_count=per_kid_opens_rows.get(kid_id, 0),
            )
            for kid_id, kid_name, total in per_kid_total_rows
        ]

        # --- Site activity ---
        refreshed_count = (
            await s.execute(
                select(func.count(func.distinct(CrawlRun.site_id)))
                .where(CrawlRun.started_at >= since)
                .where(CrawlRun.started_at < until)
                .where(CrawlRun.status == CrawlStatus.ok.value)
            )
        ).scalar_one()

        posted_new_count = (
            await s.execute(
                select(func.count(func.distinct(Alert.site_id)))
                .where(Alert.type == AlertType.schedule_posted.value)
                .where(Alert.scheduled_for >= since)
                .where(Alert.scheduled_for < until)
                .where(Alert.site_id.is_not(None))
            )
        ).scalar_one()

        stagnant_ids = await detect_stagnant_sites(
            s,
            threshold_days=settings.alert_stagnant_site_days,
            now=now,
        )
        stagnant_count = len(stagnant_ids)

    return InboxSummaryOut(
        window_start=since,
        window_end=until,
        alerts=inbox_alerts,
        new_matches_by_kid=new_matches_by_kid,
        site_activity=InboxSiteActivityOut(
            refreshed_count=refreshed_count,
            posted_new_count=posted_new_count,
            stagnant_count=stagnant_count,
        ),
    )
