"""Payload builders that gather DB state into render contexts."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.alerts.detectors.site_stagnant import detect_stagnant_sites
from yas.db.models._types import AlertType, CrawlStatus
from yas.db.models.alert import Alert
from yas.db.models.crawl_run import CrawlRun
from yas.db.models.kid import Kid
from yas.db.models.match import Match
from yas.db.models.offering import Offering
from yas.db.models.site import Site
from yas.email._errors import EmailRenderError
from yas.email.payloads import (
    CrawlFailedPayload,
    DigestPayload,
    NewMatchPayload,
    NoMatchesForKidPayload,
    PushCapPayload,
    RegOpens1hPayload,
    RegOpens24hPayload,
    RegOpensNowPayload,
    SchedulePostedPayload,
    SiteStagnantPayload,
    WatchlistHitPayload,
)

_ERROR_SUMMARY_MAX = 200


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


async def _resolve_kid_matches(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> tuple[Kid, list[dict[str, Any]]]:
    """Shared kid lookup + offering id collection + Match join + site name resolution.

    Used by both :func:`build_new_match` and :func:`build_watchlist_hit` since
    they share identical coalesced-offering shape.
    """
    if lead.kid_id is None:
        raise EmailRenderError(
            f"{lead.type} alert has no kid_id", alert_id=lead.id
        )
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
            f"{lead.type} alert missing offering_id", alert_id=lead.id
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
    return kid, matches


async def build_new_match(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> NewMatchPayload:
    """Build a NewMatchPayload from a coalesced group of new_match alerts."""
    kid, matches = await _resolve_kid_matches(session, lead, members)
    return NewMatchPayload(
        kid_id=kid.id,
        kid_name=kid.name,
        matches=matches,
        generated_at=datetime.now(UTC),
    )


async def build_watchlist_hit(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> WatchlistHitPayload:
    """Build a WatchlistHitPayload from a coalesced group of watchlist_hit alerts.

    Same shape as :func:`build_new_match`; additionally reads
    ``watchlist_label`` from ``lead.payload_json`` (None if absent).
    """
    kid, matches = await _resolve_kid_matches(session, lead, members)
    label = lead.payload_json.get("watchlist_label")
    return WatchlistHitPayload(
        kid_id=kid.id,
        kid_name=kid.name,
        matches=matches,
        watchlist_label=label if isinstance(label, str) else None,
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


async def build_reg_opens_1h(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
    *,
    now: datetime | None = None,
) -> RegOpens1hPayload:
    """Build a RegOpens1hPayload for a "registration opens in ~1 hour" alert.

    Same shape/joins as :func:`build_reg_opens_now`. ``now`` is a test seam so
    goldens stay deterministic — defaults to ``datetime.now(UTC)``. The
    registry calls this with no kwargs and ``now`` defaults at call time.
    """
    base = await build_reg_opens_now(session, lead, members)
    now_val = now if now is not None else datetime.now(UTC)
    return RegOpens1hPayload(
        kid_id=base.kid_id,
        kid_name=base.kid_name,
        offering=base.offering,
        opens_at=base.opens_at,
        registration_url=base.registration_url,
        now=now_val,
    )


async def build_reg_opens_24h(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
    *,
    now: datetime | None = None,
) -> RegOpens24hPayload:
    """Build a RegOpens24hPayload for a "registration opens in ~24 hours" alert.

    Same shape/joins as :func:`build_reg_opens_now`. ``now`` is a test seam so
    goldens stay deterministic — defaults to ``datetime.now(UTC)``. The
    registry calls this with no kwargs and ``now`` defaults at call time.
    """
    base = await build_reg_opens_now(session, lead, members)
    now_val = now if now is not None else datetime.now(UTC)
    return RegOpens24hPayload(
        kid_id=base.kid_id,
        kid_name=base.kid_name,
        offering=base.offering,
        opens_at=base.opens_at,
        registration_url=base.registration_url,
        now=now_val,
    )


async def build_schedule_posted(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> SchedulePostedPayload:
    """Build a SchedulePostedPayload for a site-scoped schedule_posted alert.

    Source-of-truth for offerings (in priority order):

    1. ``lead.payload_json["offering_ids"]`` -- explicit list of ints. Each id
       must resolve to an Offering row; missing ids raise ``EmailRenderError``.
    2. Fallback query: offerings on this site whose ``first_seen`` falls inside
       a 24h window ending at ``lead.scheduled_for``. The current enqueuer
       (``enqueue_schedule_posted``) only stores ``{"summary": ...}`` in
       ``payload_json`` and does NOT populate ``offering_ids``, so this
       fallback is the production path. The explicit ``offering_ids`` path is
       supported so callers (or future enqueuer changes) can pin an exact set.

    Notes are read from ``payload_json.get("notes")`` (falls back to
    ``payload_json.get("summary")`` for compatibility with the current
    enqueuer, which writes ``summary``).

    Site-keyed alert: requires ``lead.site_id``; ``members`` is unused (this
    kind is one alert per (site, page) dedup key, not coalesced across
    offerings).
    """
    del members  # site-scoped, not coalesced
    if lead.site_id is None:
        raise EmailRenderError(
            "schedule_posted alert has no site_id", alert_id=lead.id
        )

    site = (
        await session.execute(select(Site).where(Site.id == lead.site_id))
    ).scalar_one_or_none()
    if site is None:
        raise EmailRenderError(f"site {lead.site_id} not found", alert_id=lead.id)

    offerings: list[Offering] = []

    raw_ids = lead.payload_json.get("offering_ids")
    if isinstance(raw_ids, list) and raw_ids:
        offering_ids = [int(x) for x in raw_ids]
        rows = (
            await session.execute(
                select(Offering).where(Offering.id.in_(offering_ids))
            )
        ).scalars().all()
        found = {o.id: o for o in rows}
        missing = [oid for oid in offering_ids if oid not in found]
        if missing:
            raise EmailRenderError(
                f"offerings not found: {missing}", alert_id=lead.id
            )
        # Preserve caller-supplied order.
        offerings = [found[oid] for oid in offering_ids]
    else:
        # Fallback: offerings on this site first_seen within the 24h leading
        # up to scheduled_for.
        scheduled_for = lead.scheduled_for
        if scheduled_for is None:
            raise EmailRenderError(
                "schedule_posted alert has no scheduled_for for fallback window",
                alert_id=lead.id,
            )
        window_start = scheduled_for - timedelta(hours=24)
        # SQLite strips tzinfo on read-back; pass naive bounds when the column
        # round-trips as naive UTC.
        ws_param: datetime = window_start
        se_param: datetime = scheduled_for
        offerings = list(
            (
                await session.execute(
                    select(Offering)
                    .where(Offering.site_id == lead.site_id)
                    .where(Offering.first_seen >= ws_param)
                    .where(Offering.first_seen <= se_param)
                    .order_by(Offering.first_seen)
                )
            ).scalars().all()
        )

    if not offerings:
        raise EmailRenderError(
            f"schedule_posted alert has no offerings (site {lead.site_id})",
            alert_id=lead.id,
        )

    new_offerings = [
        _offering_to_dict(o, score=None, site_name=site.name) for o in offerings
    ]

    notes_raw = lead.payload_json.get("notes")
    if not isinstance(notes_raw, str) or not notes_raw:
        summary_raw = lead.payload_json.get("summary")
        notes_raw = summary_raw if isinstance(summary_raw, str) and summary_raw else None

    return SchedulePostedPayload(
        site_id=site.id,
        site_name=site.name,
        new_offerings=new_offerings,
        notes=notes_raw,
    )


async def build_crawl_failed(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> CrawlFailedPayload:
    """Build a CrawlFailedPayload for a site-scoped crawl_failed alert.

    Source-of-truth for fields (matches ``enqueue_crawl_failed`` in
    ``src/yas/alerts/enqueuer.py``):

    * ``error_summary`` <- ``payload_json["last_error"]`` (also accepts
      ``error_summary`` / ``error`` keys for forward-compatibility).
      Truncated to 200 characters with an ellipsis indicator.
    * ``failure_count`` <- ``payload_json["consecutive_failures"]`` (also
      accepts legacy ``failure_count``); defaults to ``1`` when absent.
    * ``last_success_at`` <- ``payload_json["last_success_at"]`` (ISO string)
      when supplied; otherwise queried from ``CrawlRun`` as
      ``max(finished_at) where site_id == lead.site_id and status == ok``
      (None when no successful crawl has ever completed).

    Site-keyed alert (``Alert.kid_id`` is None); ``members`` is unused (one
    alert per site dedup key, no coalescing).
    """
    del members  # site-scoped, not coalesced
    if lead.site_id is None:
        raise EmailRenderError(
            "crawl_failed alert has no site_id", alert_id=lead.id
        )

    site = (
        await session.execute(select(Site).where(Site.id == lead.site_id))
    ).scalar_one_or_none()
    if site is None:
        raise EmailRenderError(f"site {lead.site_id} not found", alert_id=lead.id)

    pj = lead.payload_json or {}

    raw_err: Any = (
        pj.get("error_summary") or pj.get("last_error") or pj.get("error") or ""
    )
    if not isinstance(raw_err, str):
        raw_err = str(raw_err)
    if len(raw_err) > _ERROR_SUMMARY_MAX:
        # Reserve 1 char for the truncation marker so the total stays bounded.
        error_summary = raw_err[: _ERROR_SUMMARY_MAX - 1] + "…"
    else:
        error_summary = raw_err

    failure_raw = pj.get("consecutive_failures", pj.get("failure_count", 1))
    try:
        failure_count = int(failure_raw)
    except (TypeError, ValueError):
        failure_count = 1

    last_success_at: datetime | None = None
    raw_lsa = pj.get("last_success_at")
    if isinstance(raw_lsa, str) and raw_lsa:
        try:
            last_success_at = datetime.fromisoformat(raw_lsa)
        except ValueError:
            last_success_at = None
    elif isinstance(raw_lsa, datetime):
        last_success_at = raw_lsa

    if last_success_at is None:
        last_success_at = (
            await session.execute(
                select(func.max(CrawlRun.finished_at))
                .where(CrawlRun.site_id == lead.site_id)
                .where(CrawlRun.status == CrawlStatus.ok.value)
            )
        ).scalar_one_or_none()

    if last_success_at is not None and last_success_at.tzinfo is None:
        last_success_at = last_success_at.replace(tzinfo=UTC)

    return CrawlFailedPayload(
        site_id=site.id,
        site_name=site.name,
        error_summary=error_summary,
        last_success_at=last_success_at,
        failure_count=failure_count,
    )


async def build_site_stagnant(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> SiteStagnantPayload:
    """Build a SiteStagnantPayload for a site-scoped site_stagnant alert.

    Source-of-truth for fields (matches ``enqueue_site_stagnant`` in
    ``src/yas/alerts/enqueuer.py`` and the site_stagnant detector):

    * ``days_since_change`` <- ``payload_json["days_silent"]`` (also accepts
      ``days_since_change`` for forward-compatibility). Required: if missing
      we raise ``EmailRenderError`` so a half-rendered email never ships.
    * ``last_change_at`` <- ``payload_json["last_change_at"]`` ISO string when
      present; otherwise None (detector does not currently supply it).

    Site-keyed alert; ``members`` is unused (one alert per site dedup key).
    """
    del members  # site-scoped, not coalesced
    if lead.site_id is None:
        raise EmailRenderError(
            "site_stagnant alert has no site_id", alert_id=lead.id
        )

    site = (
        await session.execute(select(Site).where(Site.id == lead.site_id))
    ).scalar_one_or_none()
    if site is None:
        raise EmailRenderError(f"site {lead.site_id} not found", alert_id=lead.id)

    pj = lead.payload_json or {}
    days_raw = pj.get("days_since_change", pj.get("days_silent"))
    if days_raw is None:
        raise EmailRenderError(
            "site_stagnant alert missing days_since_change/days_silent",
            alert_id=lead.id,
        )
    try:
        days_since_change = int(days_raw)
    except (TypeError, ValueError) as exc:
        raise EmailRenderError(
            f"site_stagnant days value not int-coercible: {days_raw!r}",
            alert_id=lead.id,
        ) from exc

    last_change_at: datetime | None = None
    raw_lca = pj.get("last_change_at")
    if isinstance(raw_lca, str) and raw_lca:
        try:
            last_change_at = datetime.fromisoformat(raw_lca)
        except ValueError:
            last_change_at = None
    elif isinstance(raw_lca, datetime):
        last_change_at = raw_lca
    if last_change_at is not None and last_change_at.tzinfo is None:
        last_change_at = last_change_at.replace(tzinfo=UTC)

    return SiteStagnantPayload(
        site_id=site.id,
        site_name=site.name,
        site_base_url=site.base_url,
        days_since_change=days_since_change,
        last_change_at=last_change_at,
    )


async def build_no_matches_for_kid(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> NoMatchesForKidPayload:
    """Build a NoMatchesForKidPayload for a per-kid no_matches_for_kid alert.

    Source-of-truth for fields (matches ``enqueue_no_matches_for_kid`` in
    ``src/yas/alerts/enqueuer.py``):

    * ``days_since_added`` <- ``payload_json["days_since_created"]`` (the
      key the enqueuer writes). Also accepts ``days_since_added`` for
      forward-compatibility. If neither key is present we fall back to
      computing ``(lead.scheduled_for - kid.created_at).days``.

    Kid-keyed alert; ``members`` is unused (not coalesced).
    """
    del members  # not coalesced
    if lead.kid_id is None:
        raise EmailRenderError(
            "no_matches_for_kid alert has no kid_id", alert_id=lead.id
        )
    kid = (
        await session.execute(select(Kid).where(Kid.id == lead.kid_id))
    ).scalar_one_or_none()
    if kid is None:
        raise EmailRenderError(f"kid {lead.kid_id} not found", alert_id=lead.id)

    pj = lead.payload_json or {}
    days_raw = pj.get("days_since_created", pj.get("days_since_added"))
    days_since_added: int
    if days_raw is not None:
        try:
            days_since_added = int(days_raw)
        except (TypeError, ValueError) as exc:
            raise EmailRenderError(
                f"no_matches_for_kid days value not int-coercible: {days_raw!r}",
                alert_id=lead.id,
            ) from exc
    else:
        # Fallback: compute from kid.created_at vs lead.scheduled_for.
        scheduled_for = lead.scheduled_for
        if scheduled_for is None:
            raise EmailRenderError(
                "no_matches_for_kid alert missing days_since_created and"
                " has no scheduled_for to compute from",
                alert_id=lead.id,
            )
        # SQLite strips tzinfo on read-back; normalize both sides.
        sched_cmp = (
            scheduled_for.replace(tzinfo=None)
            if kid.created_at.tzinfo is None and scheduled_for.tzinfo is not None
            else scheduled_for
        )
        days_since_added = (sched_cmp - kid.created_at).days

    return NoMatchesForKidPayload(
        kid_id=kid.id,
        kid_name=kid.name,
        days_since_added=days_since_added,
    )


async def build_push_cap(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> PushCapPayload:
    """Build a PushCapPayload for a consolidated push_cap notice.

    Source-of-truth for fields (matches ``enqueue_push_cap`` in
    ``src/yas/alerts/enqueuer.py``):

    * ``suppressed_count`` <- ``payload_json["suppressed_count"]``. Required:
      the count is the whole point of this alert, so we raise
      ``EmailRenderError`` when it is missing.
    * ``kid_id`` <- ``lead.kid_id`` (may be None for system-wide caps).
    * ``kid_name`` looked up from ``Kid`` when ``kid_id`` is non-None.

    ``members`` is unused (not coalesced).
    """
    del members  # not coalesced
    pj = lead.payload_json or {}
    count_raw = pj.get("suppressed_count")
    if count_raw is None:
        raise EmailRenderError(
            "push_cap alert missing suppressed_count", alert_id=lead.id
        )
    try:
        suppressed_count = int(count_raw)
    except (TypeError, ValueError) as exc:
        raise EmailRenderError(
            f"push_cap suppressed_count not int-coercible: {count_raw!r}",
            alert_id=lead.id,
        ) from exc

    kid_name: str | None = None
    if lead.kid_id is not None:
        kid = (
            await session.execute(select(Kid).where(Kid.id == lead.kid_id))
        ).scalar_one_or_none()
        if kid is not None:
            kid_name = kid.name

    return PushCapPayload(
        kid_id=lead.kid_id,
        kid_name=kid_name,
        suppressed_count=suppressed_count,
    )


__all__ = [
    "build_crawl_failed",
    "build_new_match",
    "build_no_matches_for_kid",
    "build_push_cap",
    "build_reg_opens_1h",
    "build_reg_opens_24h",
    "build_reg_opens_now",
    "build_schedule_posted",
    "build_site_stagnant",
    "build_watchlist_hit",
    "gather_digest_payload",
]
