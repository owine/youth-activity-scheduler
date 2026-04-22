"""Pure helpers: coalesce, push-cap check, quiet-hours check."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Alert
from yas.db.models._types import AlertType

_NEVER_COALESCE = frozenset({
    AlertType.reg_opens_now.value,
    AlertType.reg_opens_1h.value,
    AlertType.watchlist_hit.value,
    AlertType.crawl_failed.value,
    AlertType.digest.value,
})


@dataclass(frozen=True)
class AlertGroup:
    lead: Any
    members: list[Any] = field(default_factory=list)
    kid_id: int | None = None
    alert_type: str = ""


def coalesce(due: list[Any], *, window_s: int) -> list[AlertGroup]:
    """Group alerts sharing (kid_id, type) where consecutive members'
    scheduled_for timestamps are within window_s of each other. Types in
    _NEVER_COALESCE pass through as singleton groups regardless."""
    sorted_alerts = sorted(due, key=lambda a: (a.scheduled_for, a.id))
    groups: list[AlertGroup] = []
    pending: dict[tuple[int | None, str], list[Any]] = {}

    def _flush_group(key: tuple[int | None, str]) -> None:
        members = pending.pop(key, [])
        if not members:
            return
        groups.append(AlertGroup(
            lead=members[0],
            members=members,
            kid_id=key[0],
            alert_type=key[1],
        ))

    for a in sorted_alerts:
        if a.type in _NEVER_COALESCE:
            groups.append(AlertGroup(lead=a, members=[a], kid_id=a.kid_id, alert_type=a.type))
            continue
        key = (a.kid_id, a.type)
        existing = pending.get(key)
        if existing is None:
            pending[key] = [a]
            continue
        last = existing[-1]
        if (a.scheduled_for - last.scheduled_for).total_seconds() <= window_s:
            existing.append(a)
        else:
            _flush_group(key)
            pending[key] = [a]

    for key in list(pending.keys()):
        _flush_group(key)

    groups.sort(key=lambda g: (g.lead.scheduled_for, g.lead.id))
    return groups


def should_rate_limit_push(sent_count: int, max_per_hour: int) -> bool:
    """True if the per-kid push cap has been reached in the last hour."""
    return sent_count >= max_per_hour


async def count_pushes_sent_in_last_hour(
    session: AsyncSession, kid_id: int, push_channels: list[str],
) -> int:
    """Count alerts.sent_at >= now-1h where any configured push channel was used."""
    if not push_channels:
        return 0
    window_start = datetime.now(UTC) - timedelta(hours=1)
    count = (
        await session.execute(
            select(func.count(Alert.id)).where(
                Alert.kid_id == kid_id,
                Alert.sent_at.isnot(None),
                Alert.sent_at >= window_start,
            )
        )
    ).scalar_one()
    if count == 0:
        return 0
    alerts = (
        await session.execute(
            select(Alert).where(
                Alert.kid_id == kid_id,
                Alert.sent_at.isnot(None),
                Alert.sent_at >= window_start,
            )
        )
    ).scalars().all()
    return sum(1 for a in alerts if any(c in push_channels for c in (a.channels or [])))


def _parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def is_in_quiet_hours(
    now: datetime,
    quiet_start: str | None,
    quiet_end: str | None,
) -> bool:
    """Check if now falls in the household's quiet-hours window (UTC HH:MM).
    Wrap-around (e.g. 22:00..07:00) handled. Either None -> False."""
    if quiet_start is None or quiet_end is None:
        return False
    start = _parse_hhmm(quiet_start)
    end = _parse_hhmm(quiet_end)
    now_t = now.time()
    if start <= end:
        return start <= now_t < end
    return now_t >= start or now_t < end
