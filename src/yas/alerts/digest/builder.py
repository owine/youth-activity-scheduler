"""Digest payload builder and template renderer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.alerts.detectors.site_stagnant import detect_stagnant_sites
from yas.alerts.digest.filters import fmt as fmt_filter
from yas.alerts.digest.filters import price as price_filter
from yas.alerts.digest.filters import rel_date as rel_date_filter
from yas.db.models._types import AlertType
from yas.db.models.alert import Alert
from yas.db.models.kid import Kid
from yas.db.models.match import Match
from yas.db.models.offering import Offering

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
)
_env.filters["price"] = price_filter
_env.filters["rel_date"] = rel_date_filter
_env.filters["fmt"] = fmt_filter


@dataclass(frozen=True)
class DigestPayload:
    """All data sections needed to render a digest for one kid."""

    kid_id: int
    kid_name: str
    for_date: date
    new_matches: list[dict[str, Any]] = field(default_factory=list)
    starting_soon: list[dict[str, Any]] = field(default_factory=list)
    registration_calendar: list[dict[str, Any]] = field(default_factory=list)
    delivery_failures: list[dict[str, Any]] = field(default_factory=list)
    site_stagnant_ids: list[int] = field(default_factory=list)
    silent_schedule_posts: list[dict[str, Any]] = field(default_factory=list)
    under_no_matches_threshold: bool = False


def _offering_to_dict(offering: Offering, score: float) -> dict[str, Any]:
    """Convert an Offering ORM row + score into the standard match dict."""
    return {
        "offering_id": offering.id,
        "offering_name": offering.name,
        "score": score,
        "site_id": offering.site_id,
        "start_date": offering.start_date,
        "price_cents": offering.price_cents,
        "registration_opens_at": offering.registration_opens_at,
        "registration_url": offering.registration_url,
        # site_name populated separately by caller when available
        "site_name": "",
    }


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
        Active async SQLAlchemy session (read-only queries — caller owns commit).
    kid:
        The Kid ORM instance for whom the digest is being assembled.
    window_start:
        Inclusive lower bound for "new matches" window (typically yesterday 00:00 UTC).
    window_end:
        Exclusive upper bound for the window (typically today 00:00 UTC).
    alert_no_matches_kid_days:
        Number of days after kid creation before we suppress the no-match flag.
    now:
        Test seam — defaults to ``datetime.now(UTC)``.
    """
    now_val = now if now is not None else datetime.now(UTC)
    today = now_val.date()
    soon_cutoff = today + timedelta(days=14)

    # ------------------------------------------------------------------
    # 1. new_matches — matches computed within the window
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
    # 2. starting_soon — any matched offering starting in (today, today+14d]
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
    # 3. registration_calendar — matched offerings with reg_opens in (now, now+14d]
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
    # 4. delivery_failures — skipped alerts since the last digest (or window_start)
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
    # 5. site_stagnant_ids — global detector (not per-kid)
    # ------------------------------------------------------------------
    site_stagnant_ids = await detect_stagnant_sites(session, now=now_val)

    # ------------------------------------------------------------------
    # 6. silent_schedule_posts — schedule_posted alerts within the window
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


def render_digest(payload: DigestPayload, top_line: str) -> tuple[str, str]:
    """Render the digest to plain text and HTML.

    Returns
    -------
    (body_plain, body_html)
    """
    text_tpl = _env.get_template("digest.txt.j2")
    html_tpl = _env.get_template("digest.html.j2")
    ctx: dict[str, Any] = {"payload": payload, "top_line": top_line}
    return text_tpl.render(**ctx), html_tpl.render(**ctx)
