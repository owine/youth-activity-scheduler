"""Payload builders that gather DB state into render contexts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.alerts.detectors.site_stagnant import detect_stagnant_sites
from yas.db.models._types import AlertType
from yas.db.models.alert import Alert
from yas.db.models.kid import Kid
from yas.db.models.match import Match
from yas.db.models.offering import Offering
from yas.db.models.site import Site
from yas.email._errors import EmailRenderError
from yas.email.payloads import DigestPayload, NewMatchPayload, RegOpensNowPayload


def _offering_to_dict(
    offering: Offering, score: float | None = None, site_name: str = ""
) -> dict[str, Any]:
    """Convert an Offering ORM row (+ optional score) into the standard match dict.

    When ``score`` is None, the ``score`` key is omitted entirely so the macro's
    ``{% if m.score is defined %}`` guard falls through cleanly under
    StrictUndefined (used by reg_opens_now where no Match row may exist yet).
    """
    d: dict[str, Any] = {
        "offering_id": offering.id,
        "offering_name": offering.name,
        "site_id": offering.site_id,
        "start_date": offering.start_date,
        "price_cents": offering.price_cents,
        "registration_opens_at": offering.registration_opens_at,
        "registration_url": offering.registration_url,
        # site_name populated separately by caller when available
        "site_name": site_name,
    }
    if score is not None:
        d["score"] = score
    return d


async def gather_digest_payload(
    session: AsyncSession,
    kid: Kid,
    *,
    window_start: datetime,
    window_end: datetime,
    alert_no_matches_kid_days: int,
    now: datetime | None = None,
) -> DigestPayload:
    """Assemble all sections of a digest for *kid* covering *window_start..window_end*.

    Parameters
    ----------
    session:
        Active async SQLAlchemy session (read-only queries -- caller owns commit).
    kid:
        The Kid ORM instance for whom the digest is being assembled.
    window_start:
        Inclusive lower bound for "new matches" window (typically yesterday 00:00 UTC).
    window_end:
        Exclusive upper bound for the window (typically today 00:00 UTC).
    alert_no_matches_kid_days:
        Number of days after kid creation before we suppress the no-match flag.
    now:
        Test seam -- defaults to ``datetime.now(UTC)``.
    """
    now_val = now if now is not None else datetime.now(UTC)
    today = now_val.date()
    soon_cutoff = today + timedelta(days=14)

    # ------------------------------------------------------------------
    # 1. new_matches -- matches computed within the window
    # ------------------------------------------------------------------
    match_stmt = (
        select(Match, Offering)
        .join(Offering, Offering.id == Match.offering_id)
        .where(Match.kid_id == kid.id)
        .where(Match.computed_at >= window_start)
        .where(Match.computed_at < window_end)
        .order_by(Match.score.desc())
    )
    match_rows = (await session.execute(match_stmt)).all()
    new_matches: list[dict[str, Any]] = []
    for m, o in match_rows:
        d = _offering_to_dict(o, m.score)
        new_matches.append(d)

    # ------------------------------------------------------------------
    # 2. starting_soon -- any matched offering starting in (today, today+14d]
    # ------------------------------------------------------------------
    soon_stmt = (
        select(Match, Offering)
        .join(Offering, Offering.id == Match.offering_id)
        .where(Match.kid_id == kid.id)
        .where(Offering.start_date > today)
        .where(Offering.start_date <= soon_cutoff)
        .order_by(Offering.start_date)
    )
    soon_rows = (await session.execute(soon_stmt)).all()
    starting_soon: list[dict[str, Any]] = [_offering_to_dict(o, m.score) for m, o in soon_rows]

    # ------------------------------------------------------------------
    # 3. registration_calendar -- matched offerings with reg_opens in (now, now+14d]
    # ------------------------------------------------------------------
    reg_cutoff = now_val + timedelta(days=14)
    reg_stmt = (
        select(Match, Offering)
        .join(Offering, Offering.id == Match.offering_id)
        .where(Match.kid_id == kid.id)
        .where(Offering.registration_opens_at > now_val)
        .where(Offering.registration_opens_at <= reg_cutoff)
        .order_by(Offering.registration_opens_at)
    )
    reg_rows = (await session.execute(reg_stmt)).all()
    registration_calendar: list[dict[str, Any]] = [
        _offering_to_dict(o, m.score) for m, o in reg_rows
    ]

    # ------------------------------------------------------------------
    # 4. delivery_failures -- skipped alerts since the last digest (or window_start)
    #    Skipped alerts never have sent_at stamped (only successful sends do), so
    #    we filter on scheduled_for instead.
    # ------------------------------------------------------------------
    prev_digest_stmt = (
        select(Alert.sent_at)
        .where(Alert.kid_id == kid.id)
        .where(Alert.type == AlertType.digest.value)
        .where(Alert.sent_at.isnot(None))
        .order_by(Alert.sent_at.desc())
        .limit(1)
    )
    prev_digest_sent_at: datetime | None = (
        await session.execute(prev_digest_stmt)
    ).scalar_one_or_none()

    # SQLite strips tzinfo on read-back; strip from window_start for the comparison
    # so both sides are in the same timezone domain (both UTC, both naive).
    failure_cutoff: datetime
    if prev_digest_sent_at is not None:
        window_start_cmp = (
            window_start.replace(tzinfo=None)
            if prev_digest_sent_at.tzinfo is None
            else window_start
        )
        failure_cutoff = (
            prev_digest_sent_at if prev_digest_sent_at > window_start_cmp else window_start
        )
    else:
        failure_cutoff = window_start

    failures_stmt = (
        select(Alert)
        .where(Alert.kid_id == kid.id)
        .where(Alert.skipped.is_(True))
        .where(Alert.scheduled_for >= failure_cutoff)
        .order_by(Alert.scheduled_for)
    )
    failure_rows = (await session.execute(failures_stmt)).scalars().all()
    delivery_failures: list[dict[str, Any]] = [
        {
            "alert_type": row.type,
            "detail": row.payload_json.get("_last_error", "unknown error"),
            "scheduled_for": row.scheduled_for,
        }
        for row in failure_rows
    ]

    # ------------------------------------------------------------------
    # 5. site_stagnant_ids -- global detector (not per-kid)
    # ------------------------------------------------------------------
    site_stagnant_ids = await detect_stagnant_sites(session, now=now_val)

    # ------------------------------------------------------------------
    # 6. silent_schedule_posts -- schedule_posted alerts within the window
    # ------------------------------------------------------------------
    posts_stmt = (
        select(Alert)
        .where(Alert.type == AlertType.schedule_posted.value)
        .where(Alert.scheduled_for >= window_start)
        .where(Alert.scheduled_for < window_end)
        .order_by(Alert.scheduled_for)
    )
    post_rows = (await session.execute(posts_stmt)).scalars().all()
    silent_schedule_posts: list[dict[str, Any]] = [
        {
            "site_id": row.site_id,
            "offering_id": row.offering_id,
            "notes": row.payload_json.get("notes", ""),
        }
        for row in post_rows
    ]

    # ------------------------------------------------------------------
    # 7. under_no_matches_threshold
    # ------------------------------------------------------------------
    any_match = (
        await session.execute(select(Match).where(Match.kid_id == kid.id).limit(1))
    ).scalar_one_or_none()
    # SQLite strips tzinfo on read-back; strip tzinfo from the threshold too so the
    # comparison is always naive vs. naive (both in UTC).
    threshold_dt = now_val - timedelta(days=alert_no_matches_kid_days)
    kid_created = kid.created_at
    if kid_created.tzinfo is None:
        threshold_naive = threshold_dt.replace(tzinfo=None)
        created_recently = kid_created >= threshold_naive
    else:
        created_recently = kid_created >= threshold_dt
    under_no_matches_threshold = created_recently and any_match is None

    return DigestPayload(
        kid_id=kid.id,
        kid_name=kid.name,
        for_date=today,
        new_matches=new_matches,
        starting_soon=starting_soon,
        registration_calendar=registration_calendar,
        delivery_failures=delivery_failures,
        site_stagnant_ids=site_stagnant_ids,
        silent_schedule_posts=silent_schedule_posts,
        under_no_matches_threshold=under_no_matches_threshold,
    )


async def build_new_match(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> NewMatchPayload:
    """Build a NewMatchPayload from a coalesced group of new_match alerts."""
    if lead.kid_id is None:
        raise EmailRenderError("new_match alert has no kid_id", alert_id=lead.id)
    kid = (
        await session.execute(select(Kid).where(Kid.id == lead.kid_id))
    ).scalar_one_or_none()
    if kid is None:
        raise EmailRenderError(f"kid {lead.kid_id} not found", alert_id=lead.id)

    offering_ids = [
        int(a.payload_json["offering_id"])
        for a in members
        if "offering_id" in a.payload_json
    ]
    if not offering_ids:
        raise EmailRenderError(
            "new_match alert missing offering_id", alert_id=lead.id
        )

    stmt = (
        select(Offering, Match.score)
        .join(Match, (Match.offering_id == Offering.id) & (Match.kid_id == kid.id))
        .where(Offering.id.in_(offering_ids))
        .order_by(Match.score.desc())
    )
    rows = (await session.execute(stmt)).all()
    if len(rows) != len(offering_ids):
        found = {o.id for o, _ in rows}
        missing = [oid for oid in offering_ids if oid not in found]
        raise EmailRenderError(
            f"offerings not found: {missing}", alert_id=lead.id
        )

    site_ids = list({o.site_id for o, _ in rows})
    site_rows = (
        await session.execute(select(Site).where(Site.id.in_(site_ids)))
    ).scalars().all()
    site_names = {s.id: s.name for s in site_rows}

    matches = [
        _offering_to_dict(o, score, site_names.get(o.site_id, ""))
        for o, score in rows
    ]
    return NewMatchPayload(
        kid_id=kid.id,
        kid_name=kid.name,
        matches=matches,
        generated_at=datetime.now(UTC),
    )


async def build_reg_opens_now(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> RegOpensNowPayload:
    """Build a RegOpensNowPayload from a single reg_opens_now alert.

    reg_opens_now alerts are NOT coalesced (each opening is its own urgent
    alert), so ``members`` is ignored. Requires a valid kid, offering, and
    registration_url — without the URL the alert is useless and we raise.
    """
    del members  # not coalesced; signature kept uniform for the registry
    if lead.kid_id is None:
        raise EmailRenderError("reg_opens_now alert has no kid_id", alert_id=lead.id)

    offering_id_raw = lead.payload_json.get("offering_id")
    if offering_id_raw is None:
        raise EmailRenderError(
            "reg_opens_now alert missing offering_id", alert_id=lead.id
        )
    offering_id = int(offering_id_raw)

    kid = (
        await session.execute(select(Kid).where(Kid.id == lead.kid_id))
    ).scalar_one_or_none()
    if kid is None:
        raise EmailRenderError(f"kid {lead.kid_id} not found", alert_id=lead.id)

    offering = (
        await session.execute(select(Offering).where(Offering.id == offering_id))
    ).scalar_one_or_none()
    if offering is None:
        raise EmailRenderError(
            f"offering {offering_id} not found", alert_id=lead.id
        )

    if not offering.registration_url:
        raise EmailRenderError(
            f"offering {offering_id} has no registration_url", alert_id=lead.id
        )

    site_name = ""
    if offering.site_id is not None:
        site = (
            await session.execute(select(Site).where(Site.id == offering.site_id))
        ).scalar_one_or_none()
        if site is not None:
            site_name = site.name

    # Optional Match lookup: include score if available, omit otherwise.
    score: float | None = (
        await session.execute(
            select(Match.score)
            .where(Match.kid_id == kid.id)
            .where(Match.offering_id == offering.id)
        )
    ).scalar_one_or_none()

    offering_dict = _offering_to_dict(offering, score=score, site_name=site_name)

    # Prefer the Offering column for opens_at; fall back to payload_json.
    opens_at: datetime | None = offering.registration_opens_at
    if opens_at is None:
        raw = lead.payload_json.get("opens_at")
        if isinstance(raw, str):
            opens_at = datetime.fromisoformat(raw)
    if opens_at is None:
        raise EmailRenderError(
            f"offering {offering_id} has no registration_opens_at", alert_id=lead.id
        )
    if opens_at.tzinfo is None:
        opens_at = opens_at.replace(tzinfo=UTC)

    return RegOpensNowPayload(
        kid_id=kid.id,
        kid_name=kid.name,
        offering=offering_dict,
        opens_at=opens_at,
        registration_url=offering.registration_url,
    )


__all__ = ["build_new_match", "build_reg_opens_now", "gather_digest_payload"]
