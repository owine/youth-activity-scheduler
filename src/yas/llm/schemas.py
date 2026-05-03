"""Pydantic schemas for LLM-extracted offerings.

Strict on shape (`extra="forbid"` so drift surfaces loudly), tolerant on
specific value enums. Previously a single LLM-returned program_type
that wasn't in our enum (e.g. 'tennis' before it was added) would fail
validation on the WHOLE batch — losing every offering on the page.
Now unknown program_types coerce to `ProgramType.unknown` and unknown
days_of_week entries are dropped, so one weird value doesn't poison
the rest."""

from __future__ import annotations

from datetime import date, datetime, time

from pydantic import BaseModel, ConfigDict, field_validator

from yas.db.models._types import DayOfWeek, ProgramType


class ExtractedOffering(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    program_type: ProgramType
    start_date: date | None = None
    end_date: date | None = None
    days_of_week: list[DayOfWeek] = []
    time_start: time | None = None
    time_end: time | None = None
    location_name: str | None = None
    location_address: str | None = None
    price_cents: int | None = None
    registration_opens_at: datetime | None = None
    registration_url: str | None = None

    @field_validator("program_type", mode="before")
    @classmethod
    def _coerce_unknown_program_type(cls, v: object) -> object:
        """Coerce any string outside the enum to ProgramType.unknown.

        The LLM occasionally invents new sport names (a new sport in
        the area, a typo, a translation). Dropping the whole offering
        for that is worse than tagging it 'unknown' and letting the
        matcher fall through to interest-text matching.
        """
        if isinstance(v, str):
            try:
                return ProgramType(v)
            except ValueError:
                return ProgramType.unknown
        return v

    @field_validator("days_of_week", mode="before")
    @classmethod
    def _drop_unknown_days(cls, v: object) -> object:
        """Filter out unknown day strings rather than failing the row."""
        if isinstance(v, list):
            valid: list[DayOfWeek] = []
            for item in v:
                if isinstance(item, DayOfWeek):
                    valid.append(item)
                    continue
                if isinstance(item, str):
                    try:
                        valid.append(DayOfWeek(item))
                    except ValueError:
                        continue
            return valid
        return v


class ExtractionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offerings: list[ExtractedOffering]
