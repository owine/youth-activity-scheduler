"""Alert routing: reads alert_routing table; seeds defaults on first run."""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.alerts.channels.base import Notifier, NotifierCapability
from yas.db.models import AlertRouting
from yas.db.models._types import AlertType
from yas.logging import get_logger

log = get_logger("yas.alerts.routing")

# The channel names a notifier can be built under (alerts/notifier_builder.py).
KNOWN_CHANNELS: frozenset[str] = frozenset({"email", "ntfy", "pushover"})

# Routing alias for "whichever push channel is configured" (spec §3.10). It names
# no notifier itself; resolve_channels() maps it onto one at send time, so a
# household can add ntfy or Pushover without editing every routing row.
PUSH_ALIAS = "push"

# Every name a routing row may hold.
ROUTABLE_CHANNELS: frozenset[str] = KNOWN_CHANNELS | {PUSH_ALIAS}

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


def resolve_channels(
    channels: list[str],
    notifiers: Mapping[str, Notifier],
    alert_type: AlertType,
) -> list[str]:
    """Map a routing row's channel names onto notifier names, in routing order.

    ``"push"`` becomes the first configured push-capable notifier. For
    ``reg_opens_now`` it prefers one that can push with emergency priority
    (Pushover), falling back to plain push with a log line. When no push
    notifier exists, ``"push"`` is kept as-is, so the caller sees a routed
    channel with no notifier and can hold the alert until one is configured.

    Each notifier appears once: ``["push", "ntfy"]`` with only ntfy configured
    sends one ntfy message, not two.
    """
    resolved: list[str] = []
    for name in channels:
        target = _resolve_push(notifiers, alert_type) if name == PUSH_ALIAS else name
        if target not in resolved:
            resolved.append(target)
    return resolved


def _resolve_push(notifiers: Mapping[str, Notifier], alert_type: AlertType) -> str:
    push = [n for n, x in notifiers.items() if NotifierCapability.push in x.capabilities]
    if not push:
        return PUSH_ALIAS
    if alert_type == AlertType.reg_opens_now:
        for name in push:
            if NotifierCapability.push_emergency in notifiers[name].capabilities:
                return name
        log.info("routing.push_emergency_downgraded", alert_type=alert_type.value, channel=push[0])
    return push[0]


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
