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
class WatchlistHitPayload:
    """Coalesced ``watchlist_hit`` alert: offerings matching a watched query."""

    kid_id: int
    kid_name: str
    matches: list[dict[str, Any]]  # same shape as NewMatchPayload.matches
    watchlist_label: str | None = None


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
class SchedulePostedPayload:
    """Site-scoped ``schedule_posted`` alert: one or more new offerings on a site.

    Site-keyed (not kid-keyed): the alert references ``Alert.site_id`` rather
    than a kid. ``new_offerings`` carries offering_row dicts with the ``score``
    key omitted (this kind is not match-driven).
    """

    site_id: int
    site_name: str
    new_offerings: list[dict[str, Any]]
    notes: str | None = None


@dataclass(frozen=True)
class CrawlFailedPayload:
    """Site-scoped ``crawl_failed`` alert: crawler has been failing for a site.

    Site-keyed (``Alert.site_id``, ``kid_id`` is None). ``error_summary`` is
    truncated to ~200 chars by the builder. ``last_success_at`` may be None
    when there has never been a successful crawl.
    """

    site_id: int
    site_name: str
    error_summary: str
    last_success_at: datetime | None
    failure_count: int


@dataclass(frozen=True)
class SiteStagnantPayload:
    """Site-scoped ``site_stagnant`` alert: site has shown no changes for a while.

    Site-keyed (``Alert.site_id``, ``kid_id`` is None). ``days_since_change``
    is set by the detector / enqueuer (``days_silent`` key); the builder
    raises ``EmailRenderError`` if it is missing so silent half-rendered
    emails never go out.
    """

    site_id: int
    site_name: str
    site_base_url: str
    days_since_change: int
    last_change_at: datetime | None


@dataclass(frozen=True)
class NoMatchesForKidPayload:
    """Per-kid ``no_matches_for_kid`` alert: still no matches after N days."""

    kid_id: int
    kid_name: str
    days_since_added: int


@dataclass(frozen=True)
class PushCapPayload:
    """Consolidated ``push_cap`` notice when per-hour push cap is hit.

    ``kid_id`` / ``kid_name`` may be None for system-wide caps. This kind is
    push-only in default routing; the renderer exists for registry completeness
    and the rare case where someone routes it to email.
    """

    kid_id: int | None
    kid_name: str | None
    suppressed_count: int


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
    "CrawlFailedPayload",
    "DigestPayload",
    "NewMatchPayload",
    "NoMatchesForKidPayload",
    "PushCapPayload",
    "RegOpens1hPayload",
    "RegOpens24hPayload",
    "RegOpensNowPayload",
    "SchedulePostedPayload",
    "SiteStagnantPayload",
    "WatchlistHitPayload",
]
