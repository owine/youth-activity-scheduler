"""Event-driven alert enqueuer.

Called synchronously from pipeline/matcher/detector sites with an open
AsyncSession. Each function computes a dedup_key and either inserts a new
alerts row or updates an existing unsent row in-place."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Alert, Kid, Site
from yas.db.models._types import AlertType
from yas.logging import get_logger

log = get_logger("yas.alerts.enqueuer")


def dedup_key_for(
    alert_type: AlertType,
    *,
    kid_id: int | None = None,
    offering_id: int | None = None,
    site_id: int | None = None,
    page_id: int | None = None,
    scheduled_for: datetime | None = None,
    for_date: date | None = None,
    hour_bucket: str | None = None,
) -> str:
    """Compute the dedup_key per the spec. See Phase 4 spec §3.1."""
    k = "-" if kid_id is None else str(kid_id)
    if alert_type == AlertType.digest:
        assert for_date is not None
        return f"digest:{k}:{for_date.isoformat()}"
    if alert_type in {AlertType.reg_opens_24h, AlertType.reg_opens_1h, AlertType.reg_opens_now}:
        assert offering_id is not None and scheduled_for is not None
        sf_min = scheduled_for.strftime("%Y-%m-%dT%H:%M")
        return f"{alert_type.value}:{k}:{offering_id}:{sf_min}"
    if alert_type == AlertType.crawl_failed:
        return f"crawl_failed:-:{site_id}"
    if alert_type == AlertType.site_stagnant:
        return f"site_stagnant:-:{site_id}"
    if alert_type == AlertType.no_matches_for_kid:
        return f"no_matches_for_kid:{k}:-"
    if alert_type == AlertType.schedule_posted:
        return f"schedule_posted:-:{site_id}:{page_id}"
    if alert_type == AlertType.watchlist_hit:
        assert offering_id is not None
        return f"watchlist_hit:{k}:{offering_id}"
    if alert_type == AlertType.new_match:
        assert offering_id is not None
        return f"new_match:{k}:{offering_id}"
    # push_cap is an internal alert used by delivery worker; not dispatched here.
    raise ValueError(f"no dedup_key rule for {alert_type!r}")


async def _upsert_alert(
    session: AsyncSession,
    *,
    alert_type: AlertType,
    dedup_key: str,
    kid_id: int | None,
    offering_id: int | None,
    site_id: int | None,
    scheduled_for: datetime,
    payload: dict[str, Any],
) -> int:
    """Insert a new unsent alert OR update an existing unsent row with the
    same dedup_key. Returns the row id."""
    existing = (
        await session.execute(
            select(Alert).where(
                Alert.dedup_key == dedup_key,
                Alert.sent_at.is_(None),
                Alert.skipped.is_(False),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.payload_json = payload
        existing.scheduled_for = scheduled_for
        return existing.id
    row = Alert(
        type=alert_type.value,
        kid_id=kid_id,
        offering_id=offering_id,
        site_id=site_id,
        channels=[],  # delivery worker fills from routing at send time
        scheduled_for=scheduled_for,
        dedup_key=dedup_key,
        payload_json=payload,
    )
    session.add(row)
    await session.flush()
    return row.id


def _kid_alert_on(kid: Kid, key: str, default: bool = True) -> bool:
    data = kid.alert_on or {}
    val = data.get(key, default)
    return bool(val)


async def enqueue_new_match(
    session: AsyncSession,
    *,
    kid_id: int,
    offering_id: int,
    score: float,
    reasons: dict[str, Any],
) -> int | None:
    """Insert or update a new_match alert. Respects kid.alert_on.new_match."""
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one()
    if not _kid_alert_on(kid, "new_match", default=True):
        return None
    dk = dedup_key_for(AlertType.new_match, kid_id=kid_id, offering_id=offering_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.new_match,
        dedup_key=dk,
        kid_id=kid_id,
        offering_id=offering_id,
        site_id=None,
        scheduled_for=datetime.now(UTC),
        payload={"score": score, "reasons": reasons},
    )


async def enqueue_watchlist_hit(
    session: AsyncSession,
    *,
    kid_id: int,
    offering_id: int,
    watchlist_entry_id: int,
    reasons: dict[str, Any],
) -> int:
    """Insert or update a watchlist_hit alert. Bypasses kid.alert_on — the user
    added the watchlist entry explicitly."""
    dk = dedup_key_for(AlertType.watchlist_hit, kid_id=kid_id, offering_id=offering_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.watchlist_hit,
        dedup_key=dk,
        kid_id=kid_id,
        offering_id=offering_id,
        site_id=None,
        scheduled_for=datetime.now(UTC),
        payload={
            "watchlist_entry_id": watchlist_entry_id,
            "reasons": reasons,
        },
    )


async def enqueue_schedule_posted(
    session: AsyncSession,
    *,
    page_id: int,
    site_id: int,
    summary: str | None,
) -> int:
    dk = dedup_key_for(AlertType.schedule_posted, site_id=site_id, page_id=page_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.schedule_posted,
        dedup_key=dk,
        kid_id=None,
        offering_id=None,
        site_id=site_id,
        scheduled_for=datetime.now(UTC),
        payload={"summary": summary},
    )


async def enqueue_crawl_failed(
    session: AsyncSession,
    *,
    site_id: int,
    consecutive_failures: int,
    last_error: str,
) -> int:
    dk = dedup_key_for(AlertType.crawl_failed, site_id=site_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.crawl_failed,
        dedup_key=dk,
        kid_id=None,
        offering_id=None,
        site_id=site_id,
        scheduled_for=datetime.now(UTC),
        payload={
            "consecutive_failures": consecutive_failures,
            "last_error": last_error,
        },
    )


async def enqueue_registration_countdowns(
    session: AsyncSession,
    *,
    offering_id: int,
    kid_id: int,
    opens_at: datetime,
) -> list[int]:
    """Delete any existing unsent reg_opens_* rows for this (kid, offering) and
    insert up to three fresh ones at T-24h, T-1h, T. Skips past-due schedules."""
    # Delete prior unsent countdowns for this pair.
    await session.execute(
        delete(Alert).where(
            Alert.kid_id == kid_id,
            Alert.offering_id == offering_id,
            Alert.type.in_([
                AlertType.reg_opens_24h.value,
                AlertType.reg_opens_1h.value,
                AlertType.reg_opens_now.value,
            ]),
            Alert.sent_at.is_(None),
            Alert.skipped.is_(False),
        )
    )

    now = datetime.now(UTC)
    offsets: list[tuple[AlertType, timedelta]] = [
        (AlertType.reg_opens_24h, timedelta(hours=24)),
        (AlertType.reg_opens_1h, timedelta(hours=1)),
        (AlertType.reg_opens_now, timedelta(0)),
    ]
    ids: list[int] = []
    payload_base = {"opens_at": opens_at.isoformat(), "offering_id": offering_id}
    for alert_type, offset in offsets:
        scheduled_for = opens_at - offset
        if scheduled_for < now:
            continue
        dk = dedup_key_for(
            alert_type, kid_id=kid_id, offering_id=offering_id,
            scheduled_for=scheduled_for,
        )
        aid = await _upsert_alert(
            session,
            alert_type=alert_type,
            dedup_key=dk,
            kid_id=kid_id,
            offering_id=offering_id,
            site_id=None,
            scheduled_for=scheduled_for,
            payload=payload_base,
        )
        ids.append(aid)
    return ids


async def enqueue_site_stagnant(
    session: AsyncSession,
    *,
    site_id: int,
    days_silent: int,
) -> int:
    site = (await session.execute(select(Site).where(Site.id == site_id))).scalar_one()
    dk = dedup_key_for(AlertType.site_stagnant, site_id=site_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.site_stagnant,
        dedup_key=dk,
        kid_id=None,
        offering_id=None,
        site_id=site_id,
        scheduled_for=datetime.now(UTC),
        payload={"site_name": site.name, "days_silent": days_silent},
    )


async def enqueue_no_matches_for_kid(
    session: AsyncSession,
    *,
    kid_id: int,
    days_since_created: int,
) -> int:
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one()
    dk = dedup_key_for(AlertType.no_matches_for_kid, kid_id=kid_id)
    return await _upsert_alert(
        session,
        alert_type=AlertType.no_matches_for_kid,
        dedup_key=dk,
        kid_id=kid_id,
        offering_id=None,
        site_id=None,
        scheduled_for=datetime.now(UTC),
        payload={"kid_name": kid.name, "days_since_created": days_since_created},
    )


async def enqueue_digest(
    session: AsyncSession,
    *,
    kid_id: int,
    for_date: date,
    payload: dict[str, Any],
) -> int:
    dk = dedup_key_for(AlertType.digest, kid_id=kid_id, for_date=for_date)
    return await _upsert_alert(
        session,
        alert_type=AlertType.digest,
        dedup_key=dk,
        kid_id=kid_id,
        offering_id=None,
        site_id=None,
        scheduled_for=datetime.now(UTC),
        payload=payload,
    )


async def enqueue_push_cap(
    session: AsyncSession,
    *,
    kid_id: int,
    hour_bucket: str,  # ISO hour, e.g. "2026-04-22T15"
    suppressed_count: int,
) -> int:
    """Consolidated alert emitted by delivery loop when per-hour push cap is
    hit. Kept in the enqueuer (not an inline Alert insert in delivery.py) so
    all alert inserts share the same dedup/upsert path."""
    dk = f"push_cap:{kid_id}:{hour_bucket}"
    return await _upsert_alert(
        session,
        alert_type=AlertType.push_cap,
        dedup_key=dk,
        kid_id=kid_id,
        offering_id=None,
        site_id=None,
        scheduled_for=datetime.now(UTC),
        payload={"suppressed_count": suppressed_count, "hour_bucket": hour_bucket},
    )
