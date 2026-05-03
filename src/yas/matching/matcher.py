"""Matcher orchestrator — composes gates + scoring + watchlist into matches rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.alerts.enqueuer import enqueue_new_match, enqueue_watchlist_hit
from yas.config import get_settings
from yas.db.models import (
    Enrollment,
    HouseholdSettings,
    Kid,
    Location,
    Match,
    Offering,
    UnavailabilityBlock,
    WatchlistEntry,
)
from yas.db.models._types import OfferingStatus
from yas.geo.distance import great_circle_miles
from yas.geo.drive_time import DriveTimeProvider, OsrmClient, compute_drive_time
from yas.logging import get_logger
from yas.matching.aliases import INTEREST_ALIASES
from yas.matching.gates import (
    GateResult,
    age_fits,
    distance_fits,
    interests_overlap,
    no_conflict_with_unavailability,
    offering_active_and_not_ended,
)
from yas.matching.scoring import compute_score
from yas.matching.soft_conflicts import find_soft_conflicts
from yas.matching.watchlist import matches_watchlist

log = get_logger("yas.matching.matcher")


@dataclass(frozen=True)
class MatchResult:
    kid_id: int | None = None
    offering_id: int | None = None
    new: list[tuple[int, int]] = field(default_factory=list)
    updated: list[tuple[int, int]] = field(default_factory=list)
    removed: list[tuple[int, int]] = field(default_factory=list)


async def _household_defaults(session: AsyncSession) -> tuple[int | None, float | None]:
    hh = (await session.execute(select(HouseholdSettings))).scalars().first()
    if hh is None:
        return None, None
    return hh.home_location_id, hh.default_max_distance_mi


async def _home_coords(session: AsyncSession, home_id: int | None) -> tuple[float, float] | None:
    if home_id is None:
        return None
    loc = (
        await session.execute(select(Location).where(Location.id == home_id))
    ).scalar_one_or_none()
    if loc is None or loc.lat is None or loc.lon is None:
        return None
    return (loc.lat, loc.lon)


async def _offering_coords(session: AsyncSession, offering: Offering) -> tuple[float, float] | None:
    if offering.location_id is None:
        return None
    loc = (
        await session.execute(select(Location).where(Location.id == offering.location_id))
    ).scalar_one_or_none()
    if loc is None or loc.lat is None or loc.lon is None:
        return None
    return (loc.lat, loc.lon)


async def _compute_distance_mi(
    session: AsyncSession,
    home: tuple[float, float] | None,
    offering: Offering,
) -> float | None:
    if home is None:
        return None
    coords = await _offering_coords(session, offering)
    if coords is None:
        return None
    return great_circle_miles(home[0], home[1], coords[0], coords[1])


# Module-level OSRM client. Lazily constructed on first use (and only
# when YAS_DRIVE_TIME_ENABLED=true) so the default opt-out path costs
# nothing. Re-used across rematch calls so we don't churn HTTP clients.
_drive_time_provider: DriveTimeProvider | None = None


def _get_drive_time_provider() -> DriveTimeProvider | None:
    global _drive_time_provider
    settings = get_settings()
    if not settings.drive_time_enabled:
        return None
    if _drive_time_provider is None:
        _drive_time_provider = OsrmClient(base_url=settings.osrm_base_url)
    return _drive_time_provider


def _reset_drive_time_provider() -> None:
    """Test-only: clear the module-level provider singleton."""
    global _drive_time_provider
    _drive_time_provider = None


async def _compute_drive_minutes(
    session: AsyncSession,
    home: tuple[float, float] | None,
    offering: Offering,
) -> float | None:
    """Cache-first drive-time lookup. Returns None when feature disabled,
    when no home/offering coords, or when the OSRM provider fails."""
    provider = _get_drive_time_provider()
    if provider is None or home is None:
        return None
    coords = await _offering_coords(session, offering)
    if coords is None:
        return None
    result = await compute_drive_time(session, provider, home, coords)
    return result.drive_minutes if result is not None else None


async def _kid_blocks(session: AsyncSession, kid_id: int) -> list[UnavailabilityBlock]:
    return list(
        (
            await session.execute(
                select(UnavailabilityBlock).where(UnavailabilityBlock.kid_id == kid_id)
            )
        )
        .scalars()
        .all()
    )


async def _kid_watchlist(session: AsyncSession, kid_id: int) -> list[WatchlistEntry]:
    return list(
        (await session.execute(select(WatchlistEntry).where(WatchlistEntry.kid_id == kid_id)))
        .scalars()
        .all()
    )


async def _kid_enrollment_offering_map(session: AsyncSession, kid_id: int) -> dict[int, int]:
    """Map enrollment_id -> offering_id for the kid's enrollments.

    Used to filter out enrollment-sourced blocks when evaluating the source
    offering itself — a kid's enrollment in offering X should not block the kid
    from matching X (it must continue to match so the UI can show the enrolled
    row). It should still block sibling offerings that share the timeslot.
    """
    rows = (
        await session.execute(
            select(Enrollment.id, Enrollment.offering_id).where(Enrollment.kid_id == kid_id)
        )
    ).all()
    return {eid: oid for eid, oid in rows}


def _school_holidays(kid: Kid) -> set[date]:
    result: set[date] = set()
    for d in kid.school_holidays or []:
        try:
            result.add(date.fromisoformat(d) if isinstance(d, str) else d)
        except Exception:
            continue
    return result


async def _eligible_offerings(session: AsyncSession) -> list[Offering]:
    return list(
        (
            await session.execute(
                select(Offering).where(Offering.status == OfferingStatus.active.value)
            )
        )
        .scalars()
        .all()
    )


async def _active_kids(session: AsyncSession) -> list[Kid]:
    return list((await session.execute(select(Kid).where(Kid.active.is_(True)))).scalars().all())


def _gates_passed(gates: list[GateResult]) -> bool:
    return all(g.passed for g in gates)


def _reasons_payload(
    gates: list[GateResult],
    score_bd: dict[str, Any],
    watchlist_hit: Any,
) -> dict[str, Any]:
    return {
        "gates": {g.code: {"passed": g.passed, "detail": g.detail} for g in gates},
        "score_breakdown": score_bd,
        "watchlist_hit": (
            {
                "entry_id": watchlist_hit.entry.id,
                "pattern": watchlist_hit.entry.pattern,
                "match_type": watchlist_hit.reason,
                "priority": getattr(
                    watchlist_hit.entry.priority, "value", watchlist_hit.entry.priority
                ),
            }
            if watchlist_hit
            else None
        ),
    }


async def _evaluate_pair(
    session: AsyncSession,
    kid: Kid,
    offering: Offering,
    *,
    home: tuple[float, float] | None,
    default_max_distance: float | None,
    today: date,
    # Optional precomputed per-kid state (hoisted by rematch_kid for N-offering loops).
    blocks: list[UnavailabilityBlock] | None = None,
    watchlist_entries: list[WatchlistEntry] | None = None,
    school_holidays: set[date] | None = None,
    enrollment_offering_map: dict[int, int] | None = None,
) -> tuple[bool, float, dict[str, Any]]:
    distance_mi = await _compute_distance_mi(session, home, offering)
    drive_minutes = await _compute_drive_minutes(session, home, offering)
    if blocks is None:
        blocks = await _kid_blocks(session, kid.id)
    if watchlist_entries is None:
        watchlist_entries = await _kid_watchlist(session, kid.id)
    if school_holidays is None:
        school_holidays = _school_holidays(kid)
    if enrollment_offering_map is None:
        enrollment_offering_map = await _kid_enrollment_offering_map(session, kid.id)
    watchlist = matches_watchlist(offering, watchlist_entries, site_id=offering.site_id)

    # Exclude enrollment-sourced blocks whose source enrollment is on THIS
    # offering so the kid still matches the offering they're enrolled in.
    filtered_blocks = [
        b
        for b in blocks
        if b.source_enrollment_id is None
        or enrollment_offering_map.get(b.source_enrollment_id) != offering.id
    ]

    gates = [
        age_fits(kid, offering, today=today),
        distance_fits(
            kid,
            offering,
            distance_mi=distance_mi,
            household_default=default_max_distance,
            drive_minutes=drive_minutes,
        ),
        interests_overlap(kid, offering, INTEREST_ALIASES),
        offering_active_and_not_ended(offering, today=today),
        no_conflict_with_unavailability(offering, filtered_blocks, school_holidays, today=today),
    ]
    score, breakdown = compute_score(
        kid,
        offering,
        distance_mi=distance_mi,
        household_max_distance_mi=default_max_distance,
        today=today,
    )
    include = watchlist is not None or _gates_passed(gates)
    reasons = _reasons_payload(gates, breakdown, watchlist)
    # Stash drive-time minutes in reasons so the UI can render an
    # "X min drive" chip when present. Float | None — None means
    # either the feature is off or computation failed.
    if drive_minutes is not None:
        reasons["drive_minutes"] = round(drive_minutes, 1)
    # Surface soft (tight) conflicts on included matches so the UI can
    # warn about near-misses the hard gate let through. Computed only
    # for matches we'd surface anyway — pure waste otherwise.
    if include:
        soft = find_soft_conflicts(offering, filtered_blocks, school_holidays, today=today)
        if soft:
            reasons["soft_conflicts"] = [sc.to_dict() for sc in soft]
    return include, score, reasons


async def _upsert_match(
    session: AsyncSession,
    kid_id: int,
    offering_id: int,
    score: float,
    reasons: dict[str, Any],
    *,
    kid: Kid,
) -> bool:
    """Returns True if new (insert), False if existing row updated.

    On fresh inserts fires alert enqueue calls so the sweep path (rematch_kid /
    rematch_all_active_kids) also produces alerts. The pipeline path fires its
    own enqueue AFTER the session commits; the shared dedup_key ensures both
    paths converge to a single alerts row."""
    existing = (
        await session.execute(
            select(Match).where(Match.kid_id == kid_id, Match.offering_id == offering_id)
        )
    ).scalar_one_or_none()
    now = datetime.now(UTC)
    if existing is None:
        session.add(
            Match(
                kid_id=kid_id,
                offering_id=offering_id,
                score=score,
                reasons=reasons,
                computed_at=now,
            )
        )
        # Enqueue alerts for fresh inserts (sweep path).
        watchlist_hit = (reasons or {}).get("watchlist_hit")
        if watchlist_hit:
            await enqueue_watchlist_hit(
                session,
                kid_id=kid_id,
                offering_id=offering_id,
                watchlist_entry_id=watchlist_hit["entry_id"],
                reasons=reasons,
            )
        elif score >= kid.alert_score_threshold:
            await enqueue_new_match(
                session,
                kid_id=kid_id,
                offering_id=offering_id,
                score=score,
                reasons=reasons,
            )
        return True
    existing.score = score
    existing.reasons = reasons
    existing.computed_at = now
    return False


async def _delete_match_if_exists(session: AsyncSession, kid_id: int, offering_id: int) -> bool:
    existing = (
        await session.execute(
            select(Match).where(Match.kid_id == kid_id, Match.offering_id == offering_id)
        )
    ).scalar_one_or_none()
    if existing is None:
        return False
    await session.delete(existing)
    return True


async def rematch_kid(
    session: AsyncSession, kid_id: int, *, today: date | None = None
) -> MatchResult:
    kid = (await session.execute(select(Kid).where(Kid.id == kid_id))).scalar_one()
    if today is None:
        today = date.today()
    home_id, default_distance = await _household_defaults(session)
    home = await _home_coords(session, home_id)
    offerings = await _eligible_offerings(session)
    # Hoist per-kid queries out of the per-offering loop.
    blocks = await _kid_blocks(session, kid_id)
    watchlist_entries = await _kid_watchlist(session, kid_id)
    school_holidays = _school_holidays(kid)
    enrollment_offering_map = await _kid_enrollment_offering_map(session, kid_id)
    result = MatchResult(kid_id=kid_id)
    for off in offerings:
        include, score, reasons = await _evaluate_pair(
            session,
            kid,
            off,
            home=home,
            default_max_distance=default_distance,
            today=today,
            blocks=blocks,
            watchlist_entries=watchlist_entries,
            school_holidays=school_holidays,
            enrollment_offering_map=enrollment_offering_map,
        )
        key = (kid_id, off.id)
        if include:
            inserted = await _upsert_match(session, kid_id, off.id, score, reasons, kid=kid)
            (result.new if inserted else result.updated).append(key)
        else:
            if await _delete_match_if_exists(session, kid_id, off.id):
                result.removed.append(key)
    return result


async def rematch_offering(
    session: AsyncSession, offering_id: int, *, today: date | None = None
) -> MatchResult:
    off = (await session.execute(select(Offering).where(Offering.id == offering_id))).scalar_one()
    if today is None:
        today = date.today()
    home_id, default_distance = await _household_defaults(session)
    home = await _home_coords(session, home_id)
    result = MatchResult(offering_id=offering_id)
    for kid in await _active_kids(session):
        include, score, reasons = await _evaluate_pair(
            session,
            kid,
            off,
            home=home,
            default_max_distance=default_distance,
            today=today,
        )
        key = (kid.id, offering_id)
        if include:
            inserted = await _upsert_match(session, kid.id, offering_id, score, reasons, kid=kid)
            (result.new if inserted else result.updated).append(key)
        else:
            if await _delete_match_if_exists(session, kid.id, offering_id):
                result.removed.append(key)
    return result


async def rematch_all_active_kids(
    session: AsyncSession, *, today: date | None = None
) -> list[MatchResult]:
    results: list[MatchResult] = []
    for kid in await _active_kids(session):
        results.append(await rematch_kid(session, kid.id, today=today))
    return results
