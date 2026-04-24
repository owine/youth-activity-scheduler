"""Alert delivery loop — polls due alerts, coalesces, sends, retries."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.alerts.channels.base import Notifier
from yas.alerts.delivery import _apply_grace_window, send_alert_group
from yas.alerts.rate_limit import coalesce
from yas.config import Settings
from yas.db.models import Alert, HouseholdSettings
from yas.db.session import session_scope
from yas.logging import get_logger


async def alert_delivery_loop(
    engine: AsyncEngine,
    settings: Settings,
    notifiers: dict[str, Notifier],
) -> None:
    """Polling delivery loop.  Runs until cancelled."""
    log = get_logger("yas.alerts.delivery")
    log.info("delivery.start", tick_s=settings.alert_delivery_tick_s)
    try:
        while True:
            async with session_scope(engine) as s:
                household = (
                    await s.execute(select(HouseholdSettings).limit(1))
                ).scalar_one_or_none()

                now = datetime.now(UTC)
                due_rows = (
                    (
                        await s.execute(
                            select(Alert)
                            .where(
                                Alert.sent_at.is_(None),
                                Alert.skipped.is_(False),
                                Alert.scheduled_for <= now,
                            )
                            .order_by(Alert.scheduled_for)
                            .limit(100)
                        )
                    )
                    .scalars()
                    .all()
                )

                due = _apply_grace_window(
                    list(due_rows),
                    now,
                    settings.alert_countdown_past_due_grace_s,
                )

                groups = coalesce(due, window_s=settings.alert_coalesce_normal_s)
                for g in groups:
                    await send_alert_group(s, g, notifiers, settings, household)

            await asyncio.sleep(settings.alert_delivery_tick_s)
    except asyncio.CancelledError:
        log.info("delivery.stop")
        raise
