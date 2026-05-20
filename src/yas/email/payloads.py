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


__all__ = ["DigestPayload", "NewMatchPayload"]
