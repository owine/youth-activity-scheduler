"""Alert routing: reads alert_routing table; seeds defaults on first run."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import AlertRouting
from yas.db.models._types import AlertType

DEFAULT_ROUTING: dict[str, list[str]] = {
    AlertType.watchlist_hit.value: ["push", "email"],
    AlertType.new_match.value: ["email"],
    AlertType.reg_opens_24h.value: ["email"],
    AlertType.reg_opens_1h.value: ["push"],
    AlertType.reg_opens_now.value: ["push", "email"],
    AlertType.schedule_posted.value: [],  # digest only
    AlertType.crawl_failed.value: ["email"],
    AlertType.digest.value: ["email"],
    AlertType.site_stagnant.value: [],  # digest only
    AlertType.no_matches_for_kid.value: [],  # digest only
    AlertType.push_cap.value: [
        "push"
    ],  # consolidated push that replaces over-cap pushes (spec §3.7)
}


async def seed_default_routing(session: AsyncSession) -> None:
    """Ensure alert_routing has a row for every AlertType. Idempotent."""
    existing_types = set((await session.execute(select(AlertRouting.type))).scalars().all())
    for alert_type, channels in DEFAULT_ROUTING.items():
        if alert_type in existing_types:
            continue
        session.add(
            AlertRouting(
                type=alert_type,
                channels=channels,
                enabled=True,
            )
        )
    await session.flush()


async def get_routing(
    session: AsyncSession,
    alert_type: AlertType,
) -> tuple[list[str], bool]:
    """Return (channels, enabled) for the given alert type.

    Falls back to (DEFAULT_ROUTING[type], True) if the row is missing.
    Note: a missing row is treated as "enabled with default channels", not
    "disabled". To disable an alert type, set enabled=False on the row;
    do not delete it.
    """
    row = (
        await session.execute(select(AlertRouting).where(AlertRouting.type == alert_type.value))
    ).scalar_one_or_none()
    if row is None:
        return (DEFAULT_ROUTING.get(alert_type.value, []), True)
    return (list(row.channels or []), bool(row.enabled))
