"""(AlertType, payload, names) → human one-liner for the Inbox and /api/alerts.

``summarize_alert`` is pure. The offering and site an alert is about come from
its ``offering_id`` / ``site_id`` columns, not its payload: most enqueuers
(``new_match``, ``watchlist_hit``, ``crawl_failed``) write no names there, so
callers look them up with ``load_alert_names`` and pass them in (#641).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Alert, Offering, Site
from yas.db.models._types import AlertType

AlertNames = tuple[str | None, str | None]  # (offering_name, site_name)


async def load_alert_names(session: AsyncSession, alerts: Sequence[Alert]) -> dict[int, AlertNames]:
    """Offering and site names for each alert, keyed by alert id, in two queries.

    The site is the alert's own ``site_id`` when set (site-scoped types), else
    its offering's site. Ids whose rows are gone map to None.
    """
    offering_ids = {a.offering_id for a in alerts if a.offering_id is not None}
    offerings: dict[int, tuple[str, int]] = {}
    if offering_ids:
        rows = await session.execute(
            select(Offering.id, Offering.name, Offering.site_id).where(
                Offering.id.in_(offering_ids)
            )
        )
        offerings = {oid: (name, site_id) for oid, name, site_id in rows.all()}

    def site_of(a: Alert) -> int | None:
        if a.site_id is not None:
            return a.site_id
        offering = offerings.get(a.offering_id) if a.offering_id is not None else None
        return offering[1] if offering else None

    site_ids = {sid for a in alerts if (sid := site_of(a)) is not None}
    sites: dict[int, str] = {}
    if site_ids:
        site_rows = await session.execute(select(Site.id, Site.name).where(Site.id.in_(site_ids)))
        sites = {sid: name for sid, name in site_rows.all()}

    out: dict[int, AlertNames] = {}
    for a in alerts:
        offering = offerings.get(a.offering_id) if a.offering_id is not None else None
        sid = site_of(a)
        out[a.id] = (offering[0] if offering else None, sites.get(sid) if sid else None)
    return out


def summarize_alert(
    alert_type: AlertType | str,
    *,
    kid_name: str | None,
    payload: dict[str, Any],
    offering_name: str | None = None,
    site_name: str | None = None,
) -> str:
    """Return a one-line human summary for an alert.

    ``offering_name`` / ``site_name`` come from ``load_alert_names``; the payload
    is a fallback for the types whose enqueuer does write them there
    (registration countdowns, ``site_stagnant``). Missing values fall back to
    generic words so this never raises on real data.
    """
    name = kid_name or "—"
    offering = offering_name or payload.get("offering_name") or "an activity"
    site = site_name or payload.get("site_name") or "a site"
    type_value = getattr(alert_type, "value", str(alert_type))

    if type_value == AlertType.watchlist_hit.value:
        return f"Watchlist hit for {name} — {offering} · {site}"
    if type_value == AlertType.new_match.value:
        return f"New match for {name} — {offering} · {site}"
    if type_value == AlertType.reg_opens_24h.value:
        return f"Registration opens in 24h — {offering} for {name}"
    if type_value == AlertType.reg_opens_1h.value:
        return f"Registration opens in 1 hour — {offering} for {name}"
    if type_value == AlertType.reg_opens_now.value:
        return f"Registration is open now — {offering} for {name}"
    if type_value == AlertType.schedule_posted.value:
        return f"New schedule posted — {site}"
    if type_value == AlertType.crawl_failed.value:
        return f"Crawl failed — {site}"
    if type_value == AlertType.site_stagnant.value:
        return f"{site} appears stagnant"
    if type_value == AlertType.no_matches_for_kid.value:
        return f"No matches for {name} yet"
    if type_value == AlertType.push_cap.value:
        held = payload.get("suppressed_count")
        if held:
            return f"Push cap reached for {name} ({held} held back this hour)"
        return f"Push cap reached for {name}"
    if type_value == AlertType.digest.value:
        return str(payload.get("top_line", f"Daily digest for {name}"))
    return f"{type_value} alert"
