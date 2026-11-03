from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from pydantic import BaseModel

from yas.web.routes._types import UtcDatetime


class _Out(BaseModel):
    at: UtcDatetime
    maybe: UtcDatetime | None = None


def test_naive_value_is_read_as_utc_and_serialized_with_z() -> None:
    out = _Out(at=datetime(2026, 11, 2, 18, 0))
    assert out.at == datetime(2026, 11, 2, 18, 0, tzinfo=UTC)
    assert out.model_dump(mode="json")["at"] == "2026-11-02T18:00:00Z"


def test_aware_value_is_normalized_to_utc() -> None:
    eastern = timezone(timedelta(hours=-5))
    out = _Out(at=datetime(2026, 11, 2, 13, 0, tzinfo=eastern))
    assert out.model_dump(mode="json")["at"] == "2026-11-02T18:00:00Z"


def test_none_stays_none() -> None:
    assert _Out(at=datetime(2026, 1, 1)).model_dump(mode="json")["maybe"] is None
