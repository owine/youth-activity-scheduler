"""Shared column types and enums for models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, func
from sqlalchemy.orm import mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def timestamp_column(nullable: bool = False, default_now: bool = True) -> Any:
    """Return a timezone-aware DateTime column with a UTC-now default.

    Returns `Any` because SQLAlchemy's `mapped_column()` return type narrows
    to `Mapped[T]` only once the caller annotates the attribute; this helper
    is intended to be used on the RHS of a `Mapped[datetime]` annotation.
    """
    kwargs: dict[str, Any] = {"nullable": nullable}
    if default_now:
        kwargs["server_default"] = func.current_timestamp()
        kwargs["default"] = utcnow
    return mapped_column(DateTime(timezone=True), **kwargs)


class ProgramType(StrEnum):
    # Team sports
    soccer = "soccer"
    baseball = "baseball"
    softball = "softball"
    basketball = "basketball"
    hockey = "hockey"
    football = "football"
    # Individual / racquet / other sports
    swim = "swim"
    martial_arts = "martial_arts"
    gymnastics = "gymnastics"
    dance = "dance"
    gym = "gym"  # general fitness / tumbling — retained for historical cache entries
    # Enrichment
    art = "art"
    music = "music"
    stem = "stem"
    academic = "academic"
    # Umbrella / other
    multisport = "multisport"
    outdoor = "outdoor"
    camp_general = "camp_general"
    unknown = "unknown"


class PageKind(StrEnum):
    schedule = "schedule"
    registration = "registration"
    list = "list"
    other = "other"


class OfferingStatus(StrEnum):
    active = "active"
    ended = "ended"
    withdrawn = "withdrawn"


class AlertType(StrEnum):
    watchlist_hit = "watchlist_hit"
    new_match = "new_match"
    reg_opens_24h = "reg_opens_24h"
    reg_opens_1h = "reg_opens_1h"
    reg_opens_now = "reg_opens_now"
    schedule_posted = "schedule_posted"
    crawl_failed = "crawl_failed"
    digest = "digest"
    # Phase 4 additions
    site_stagnant = "site_stagnant"
    no_matches_for_kid = "no_matches_for_kid"
    push_cap = "push_cap"


class WatchlistPriority(StrEnum):
    high = "high"
    normal = "normal"


class CrawlStatus(StrEnum):
    ok = "ok"
    failed = "failed"
    skipped = "skipped"


class UnavailabilitySource(StrEnum):
    manual = "manual"
    school = "school"
    enrollment = "enrollment"
    custom = "custom"


class EnrollmentStatus(StrEnum):
    interested = "interested"
    enrolled = "enrolled"
    waitlisted = "waitlisted"
    completed = "completed"
    cancelled = "cancelled"


class DayOfWeek(StrEnum):
    mon = "mon"
    tue = "tue"
    wed = "wed"
    thu = "thu"
    fri = "fri"
    sat = "sat"
    sun = "sun"
