"""Matcher orchestrator — composes gates + scoring + watchlist into matches rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.alerts.enqueuer import (
    _kid_alert_on,
    dedup_key_for,
    enqueue_new_match,
    enqueue_watchlist_hit,
)
from yas.config import get_settings
from yas.db.models import (
    Alert,
    Enrollment,
    HouseholdSettings,
    Kid,
    Location,
    Match,
    Offering,
    UnavailabilityBlock,
    WatchlistEntry,
)
from yas.db.models._types import AlertType, OfferingStatus
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


# Coordinates of every geocoded location, keyed by id. rematch_kid loads it once
# rather than querying per offering.
LocationCoords = dict[int, tuple[float, float]]


async def _location_coords(session: AsyncSession) -> LocationCoords:
    rows = await session.execute(
        select(Location.id, Location.lat, Location.lon).where(
            Location.lat.is_not(None), Location.lon.is_not(None)
        )
    )
    return {loc_id: (lat, lon) for loc_id, lat, lon in rows if lat is not None and lon is not None}


async def _offering_coords(
    session: AsyncSession, offering: Offering, coords: LocationCoords | None = None
) -> tuple[float, float] | None:
    if offering.location_id is None:
        return None
    if coords is not None:
        return coords.get(offering.location_id)
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
    location_coords: LocationCoords | None = None,
) -> float | None:
    if home is None:
        return None
    coords = await _offering_coords(session, offering, location_coords)
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
    location_coords: LocationCoords | None = None,
    *,
    provider: DriveTimeProvider | None,
) -> float | None:
    """Cache-first drive-time lookup. Returns None when feature disabled
    (`provider` is None), when no home/offering coords, or when the OSRM
    provider fails."""
    if provider is None or home is None:
        return None
    coords = await _offering_coords(session, offering, location_coords)
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
        except ValueError:
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
    location_coords: LocationCoords | None = None,
    drive_time_provider: DriveTimeProvider | None,
) -> tuple[bool, float, dict[str, Any]]:
    distance_mi = await _compute_distance_mi(session, home, offering, location_coords)
    drive_minutes = await _compute_drive_minutes(
        session, home, offering, location_coords, provider=drive_time_provider
    )
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
        drive_minutes=drive_minutes,
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
    kid_matches: dict[int, Match] | None = None,
    alerted_keys: set[str] | None = None,
) -> bool:
    """Returns True if new (insert), False if existing row updated.

    `kid_matches` (the kid's match rows by offering id) and `alerted_keys` (see
    `_alerted_keys`) are rematch_kid's preloads; without them each is a query.

    Either way, alerts the match the first time it is alert-worthy; see
    `_alert_match_once`. This is the only place new_match / watchlist_hit alerts
    are created, for both the crawl pipeline's rematch and the sweep
    (rematch_kid)."""
    if kid_matches is not None:
        existing = kid_matches.get(offering_id)
    else:
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
    else:
        existing.score = score
        existing.reasons = reasons
        existing.computed_at = now
    await _alert_match_once(session, kid, offering_id, score, reasons, alerted_keys)
    return existing is None


def _match_alert_keys(kid_id: int, offering_id: int) -> list[str]:
    # Either type counts: a match is alerted once, whichever it was. Otherwise
    # deleting a watchlist entry turns its sent watchlist_hit matches into
    # new_match ones, and each would alert again.
    return [
        dedup_key_for(t, kid_id=kid_id, offering_id=offering_id)
        for t in (AlertType.new_match, AlertType.watchlist_hit)
    ]


async def _alerted_keys(session: AsyncSession, kid_id: int) -> set[str]:
    """Dedup keys of the kid's match alerts already sent or skipped, any offering.

    The column filters only narrow the rows loaded; callers still test exact
    keys, and the enqueuers write each key with this kid_id and type."""
    rows = await session.execute(
        select(Alert.dedup_key)
        .where(Alert.kid_id == kid_id)
        .where(Alert.type.in_([AlertType.new_match.value, AlertType.watchlist_hit.value]))
        .where(or_(Alert.sent_at.is_not(None), Alert.skipped.is_(True)))
    )
    return set(rows.scalars())


async def _alert_match_once(
    session: AsyncSession,
    kid: Kid,
    offering_id: int,
    score: float,
    reasons: dict[str, Any],
    alerted_keys: set[str] | None = None,
) -> None:
    """Enqueue the match's alert unless one was already sent or skipped, of
    either type.

    A match becomes alert-worthy when it hits a watchlist pattern, or else when
    its score reaches the kid's threshold. That can happen on insert or on a
    later update (an edit raises the score, or a new watchlist entry matches).
    Recomputing an already-alerted match must not alert again: the crawl
    pipeline used to enqueue for every recomputed match, so each edit to an
    alerted offering re-sent "New match". An unsent row is still updated in
    place by `_upsert_alert`.

    A skipped alert counts as alerted, so delivery must not skip what it can
    still deliver later (it defers a group whose channel isn't configured yet).
    Prod's new_match rows skipped as unrenderable before #640 count too, which
    is what keeps the deploy from sending a catch-up wave.
    """
    watchlist_hit = (reasons or {}).get("watchlist_hit")
    if not watchlist_hit and score < kid.alert_score_threshold:
        return
    if not watchlist_hit and not _kid_alert_on(kid, "new_match", default=True):
        # enqueue_new_match's own first check, made before its kid query: each
        # query autoflushes, so on a sweep it kept the write lock from the first
        # match row to the commit.
        return
    keys = _match_alert_keys(kid.id, offering_id)
    if alerted_keys is not None:
        if any(k in alerted_keys for k in keys):
            return
    elif (
        await session.execute(
            select(Alert.id)
            .where(Alert.dedup_key.in_(keys))
            .where(or_(Alert.sent_at.is_not(None), Alert.skipped.is_(True)))
            .limit(1)
        )
    ).first() is not None:
        return
    if watchlist_hit:
        await enqueue_watchlist_hit(
            session,
            kid_id=kid.id,
            offering_id=offering_id,
            watchlist_entry_id=watchlist_hit["entry_id"],
            reasons=reasons,
        )
    else:
        await enqueue_new_match(
            session, kid_id=kid.id, offering_id=offering_id, score=score, reasons=reasons
        )


async def _delete_match_if_exists(
    session: AsyncSession,
    kid_id: int,
    offering_id: int,
    kid_matches: dict[int, Match] | None = None,
) -> bool:
    if kid_matches is not None:
        existing = kid_matches.get(offering_id)
    else:
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
    # Per-offering lookups, preloaded: the sweep runs this for every kid against
    # every offering, and ~3 queries per pair kept its transaction (and SQLite's
    # write lock) open for seconds.
    location_coords = await _location_coords(session)
    kid_matches = {
        m.offering_id: m
        for m in (await session.execute(select(Match).where(Match.kid_id == kid_id))).scalars()
    }
    alerted_keys = await _alerted_keys(session, kid_id)
    # Resolved once per call: it reads Settings, which re-parses the environment
    # and .env, and per offering that was most of a sweep's run time.
    drive_time_provider = _get_drive_time_provider()
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
            location_coords=location_coords,
            drive_time_provider=drive_time_provider,
        )
        key = (kid_id, off.id)
        if include:
            inserted = await _upsert_match(
                session,
                kid_id,
                off.id,
                score,
                reasons,
                kid=kid,
                kid_matches=kid_matches,
                alerted_keys=alerted_keys,
            )
            (result.new if inserted else result.updated).append(key)
        else:
            if await _delete_match_if_exists(session, kid_id, off.id, kid_matches):
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
    drive_time_provider = _get_drive_time_provider()
    result = MatchResult(offering_id=offering_id)
    for kid in await _active_kids(session):
        include, score, reasons = await _evaluate_pair(
            session,
            kid,
            off,
            home=home,
            default_max_distance=default_distance,
            today=today,
            drive_time_provider=drive_time_provider,
        )
        key = (kid.id, offering_id)
        if include:
            inserted = await _upsert_match(session, kid.id, offering_id, score, reasons, kid=kid)
            (result.new if inserted else result.updated).append(key)
        else:
            if await _delete_match_if_exists(session, kid.id, offering_id):
                result.removed.append(key)
    return result
