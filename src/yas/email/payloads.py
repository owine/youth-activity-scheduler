"""Email payload dataclasses — context dicts passed to Jinja templates."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


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


@dataclass(frozen=True)
class NewMatchPayload:
    """Coalesced ``new_match`` alert: one or more offerings matched for one kid."""

    kid_id: int
    kid_name: str
    matches: list[dict[str, Any]]  # same shape as DigestPayload.new_matches
    generated_at: datetime


@dataclass(frozen=True)
class RegOpensNowPayload:
    """Per-offering reg_opens_now alert. Not coalesced."""

    kid_id: int
    kid_name: str
    offering: dict[str, Any]  # offering_row dict shape (same as new_match.matches[*])
    opens_at: datetime
    registration_url: str


@dataclass(frozen=True)
class RegOpens1hPayload:
    """Per-offering reg_opens_1h alert. Not coalesced.

    ``now`` is captured at build time and passed into templates so any
    time-to-open computation is deterministic for goldens.
    """

    kid_id: int
    kid_name: str
    offering: dict[str, Any]
    opens_at: datetime
    registration_url: str
    now: datetime


@dataclass(frozen=True)
class RegOpens24hPayload:
    """Per-offering reg_opens_24h alert. Not coalesced.

    Same shape as :class:`RegOpens1hPayload`; kept separate because future
    divergence (different fields per cadence) is likely.
    """

    kid_id: int
    kid_name: str
    offering: dict[str, Any]
    opens_at: datetime
    registration_url: str
    now: datetime


__all__ = [
    "DigestPayload",
    "NewMatchPayload",
    "RegOpens1hPayload",
    "RegOpens24hPayload",
    "RegOpensNowPayload",
]
