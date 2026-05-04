"""Pure sync scoring of (kid, offering) pairs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

_W_AVAILABILITY = 0.4
_W_DISTANCE = 0.2
_W_PRICE = 0.1
_W_REGISTRATION = 0.2
_W_FRESHNESS = 0.1

_FRESHNESS_DAYS = 60


@dataclass(frozen=True)
class ScoreBreakdown:
    availability: float
    distance: float
    price: float
    registration_timing: float
    freshness: float

    @property
    def score(self) -> float:
        total = (
            self.availability * _W_AVAILABILITY
            + self.distance * _W_DISTANCE
            + self.price * _W_PRICE
            + self.registration_timing * _W_REGISTRATION
            + self.freshness * _W_FRESHNESS
        )
        return max(0.0, min(1.0, total))

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def compute_score(
    kid: Any,
    offering: Any,
    *,
    distance_mi: float | None,
    household_max_distance_mi: float | None,
    today: date,
    drive_minutes: float | None = None,
) -> tuple[float, dict[str, Any]]:
    """Compute the score for one (kid, offering) pair.

    When `drive_minutes` is provided AND the kid has `max_drive_minutes`
    set, the distance component uses routed-driving time instead of
    great-circle miles. Otherwise falls back to miles. The breakdown
    field is named `distance` in both cases — it's a normalized
    "how far is this" signal regardless of the underlying unit.
    """
    availability = _availability_signal(kid, offering)
    distance = _distance_signal(
        kid, offering, distance_mi, household_max_distance_mi, drive_minutes
    )
    price = _price_signal(kid, offering)
    registration = _registration_signal(offering, today=today)
    freshness = _freshness_signal(offering, today=today)

    bd = ScoreBreakdown(availability, distance, price, registration, freshness)
    return bd.score, bd.as_dict()


def _availability_signal(kid: Any, offering: Any) -> float:
    # Availability is a JSON dict with day→list of time windows. Without a richer
    # schema here the minimum viable signal is: if the offering schedule is fully
    # specified and intersects any kid availability window, 1.0; if the kid has no
    # availability configured, 0.5; otherwise 0.0.
    windows = getattr(kid, "availability", None) or {}
    if not windows:
        return 0.5
    if not (offering.days_of_week and offering.time_start and offering.time_end):
        return 0.5
    offering_days = {str(getattr(d, "value", d)).lower() for d in offering.days_of_week}
    for day, slots in windows.items():
        if day.lower() not in offering_days:
            continue
        for slot in slots or []:
            ws = slot.get("start")
            we = slot.get("end")
            if not (ws and we):
                continue
            if offering.time_start.isoformat() >= ws and offering.time_end.isoformat() <= we:
                return 1.0
    return 0.0


def _distance_signal(
    kid: Any,
    offering: Any,
    distance_mi: float | None,
    household_default: float | None,
    drive_minutes: float | None = None,
) -> float:
    """Normalized 0..1 closeness signal.

    Prefers drive-time when both (a) the kid has `max_drive_minutes` set
    AND (b) `drive_minutes` is computable. Falls back to great-circle
    miles (`distance_mi` against `kid.max_distance_mi` or household
    default) otherwise. Same shape: 1.0 at ≤30% of cap, linear decay to
    0.0 at the cap.
    """
    drive_cap_raw = getattr(kid, "max_drive_minutes", None)
    if drive_cap_raw is not None and drive_minutes is not None and drive_cap_raw > 0:
        drive_cap = float(drive_cap_raw)
        threshold = drive_cap * 0.3
        if drive_minutes <= threshold:
            return 1.0
        if drive_minutes >= drive_cap:
            return 0.0
        return max(0.0, 1.0 - (drive_minutes - threshold) / (drive_cap - threshold))

    cap = kid.max_distance_mi if kid.max_distance_mi is not None else household_default
    if distance_mi is None or cap is None or cap <= 0:
        return 0.5
    threshold = cap * 0.3
    if distance_mi <= threshold:
        return 1.0
    if distance_mi >= cap:
        return 0.0
    return max(0.0, 1.0 - (distance_mi - threshold) / (cap - threshold))


def _price_signal(kid: Any, offering: Any) -> float:
    max_price = getattr(kid, "max_price_cents", None)
    if max_price is None:
        return 1.0
    if offering.price_cents is None:
        return 1.0  # unknown price → don't penalize
    if offering.price_cents <= max_price:
        return 1.0
    if offering.price_cents >= 2 * max_price:
        return 0.0
    return max(0.0, 1.0 - float(offering.price_cents - max_price) / float(max_price))


def _registration_signal(offering: Any, *, today: date) -> float:
    # If end_date < today, treat as closed.
    if offering.end_date is not None and offering.end_date < today:
        return 0.0
    opens = offering.registration_opens_at
    if opens is None:
        return 0.5
    opens_date = opens.date() if isinstance(opens, datetime) else opens
    delta = (opens_date - today).days
    if delta <= 0:
        return 1.0
    if delta <= 7:
        return 0.8
    if delta <= 30:
        return 0.6
    return 0.4


def _freshness_signal(offering: Any, *, today: date) -> float:
    first_seen = offering.first_seen
    if first_seen is None:
        return 0.5
    first_seen_date = first_seen.date() if isinstance(first_seen, datetime) else first_seen
    age_days = (today - first_seen_date).days
    if age_days <= 0:
        return 1.0
    if age_days >= _FRESHNESS_DAYS:
        return 0.0
    return 1.0 - (age_days / _FRESHNESS_DAYS)
