"""Alert delivery loop — polls due alerts, coalesces, sends, retries."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from yas.alerts.delivery import _apply_grace_window, send_alert_group
from yas.alerts.notifier_builder import build_notifiers, log_constructed
from yas.alerts.rate_limit import coalesce
from yas.config import Settings
from yas.db.models import Alert, HouseholdSettings
from yas.db.session import session_scope
from yas.logging import get_logger


async def alert_delivery_loop(
    engine: AsyncEngine,
    settings: Settings,
    notifiers_override: dict[str, Any] | None = None,
) -> None:
    """Polling delivery loop. Runs until cancelled.

    Notifiers are rebuilt each tick from the current household state, so
    saving config in the Settings UI takes effect within ~60s without
    requiring a worker restart. Each tick disposes the channels it
    constructed at the end so httpx clients don't leak.

    `notifiers_override` is a test affordance: when provided, the loop
    skips the per-tick build/aclose dance and uses the injected dict.
    Production code should never pass this.
    """
    log = get_logger("yas.alerts.delivery")
    log.info("delivery.start", tick_s=settings.alert_delivery_tick_s)
    try:
        while True:
            async with session_scope(engine) as s:
                household = (
                    await s.execute(select(HouseholdSettings).limit(1))
                ).scalar_one_or_none()

                if notifiers_override is not None:
                    notifiers = notifiers_override
                    own_notifiers = False
                else:
                    notifiers = build_notifiers(household, settings)
                    log_constructed(notifiers)
                    own_notifiers = True

                try:
                    now = datetime.now(UTC)
                    due_rows = (
                        (
                            await s.execute(
                                select(Alert)
                                .where(
                                    Alert.sent_at.is_(None),
                                    Alert.skipped.is_(False),
                                    Alert.scheduled_for <= now,
                                    Alert.closed_at.is_(None),
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
                finally:
                    if own_notifiers:
                        for n in notifiers.values():
                            await n.aclose()

            await asyncio.sleep(settings.alert_delivery_tick_s)
    except asyncio.CancelledError:
        log.info("delivery.stop")
        raise
