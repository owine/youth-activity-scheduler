"""Datetime field types shared by the API's request and response schemas."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator


def _as_utc(value: datetime) -> datetime:
    """Read a naive datetime as UTC and normalize an aware one to UTC.

    Every timestamp column is written as UTC (`timestamp_column`), but SQLite
    stores no offset and hands the value back naive. Serialized as-is it reaches
    the browser as "2026-11-02T18:00:00", which JavaScript parses as *local*
    time, so alert and crawl times shift by the viewer's UTC offset.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


UtcDatetime = Annotated[datetime, AfterValidator(_as_utc)]
"""A response timestamp, always serialized in UTC with a "Z" suffix.

Use it on response (`*Out`) schemas. Request fields use `UtcDatetimeIn`.
"""

UtcDatetimeIn = Annotated[datetime, AfterValidator(_as_utc)]
"""A client-supplied timestamp, converted to UTC before it reaches the database.

SQLite's `DateTime(timezone=True)` drops a value's offset without converting
it, so "2026-11-09T00:00:00-05:00" would be stored, and later served, as
00:00 UTC, five hours early. Converting on the way in stores the instant the
client meant. A naive value is read as UTC, the zone every column is kept in.
Use it on request bodies and query parameters that take a datetime.
"""
