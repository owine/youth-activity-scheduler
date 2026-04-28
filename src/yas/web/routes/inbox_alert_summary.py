"""Pure dispatch from (AlertType, payload) → human one-liner for the Inbox."""

from __future__ import annotations

from typing import Any

from yas.db.models._types import AlertType


def summarize_alert(
    alert_type: AlertType | str,
    *,
    kid_name: str | None,
    payload: dict[str, Any],
) -> str:
    """Return a one-line human summary for an alert.

    Pure function; no DB access. The inbox endpoint joins kid_name from the
    DB and passes it in. Payload shape varies per type — keys we don't find
    fall back to defaults so this never raises on real data.
    """
    name = kid_name or "—"
    offering = payload.get("offering_name", "an activity")
    site = payload.get("site_name", "a site")
    type_value = getattr(alert_type, "value", str(alert_type))

    if type_value == AlertType.watchlist_hit.value:
        return f"Watchlist hit for {name} — {offering} · {site}"
    if type_value == AlertType.new_match.value:
        return f"New match for {name} — {offering}"
    if type_value == AlertType.reg_opens_24h.value:
        return f"Registration opens in 24h — {offering} for {name}"
    if type_value == AlertType.reg_opens_1h.value:
        return f"Registration opens in 1 hour — {offering} for {name}"
    if type_value == AlertType.reg_opens_now.value:
        return f"Registration is open now — {offering} for {name}"
    if type_value == AlertType.schedule_posted.value:
        n = payload.get("n_offerings", 0)
        return f"{site} posted {n} new offering{'s' if n != 1 else ''}"
    if type_value == AlertType.crawl_failed.value:
        return f"Crawl failed — {site}"
    if type_value == AlertType.site_stagnant.value:
        return f"{site} appears stagnant"
    if type_value == AlertType.no_matches_for_kid.value:
        return f"No matches for {name} yet"
    if type_value == AlertType.push_cap.value:
        cap = payload.get("cap", "?")
        return f"Push cap reached for {name} ({cap} this period)"
    if type_value == AlertType.digest.value:
        return str(payload.get("top_line", f"Daily digest for {name}"))
    return f"{type_value} alert"
