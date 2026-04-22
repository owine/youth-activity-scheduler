from datetime import date, datetime, time

import pytest
from pydantic import ValidationError

from yas.db.models._types import ProgramType
from yas.llm.schemas import ExtractedOffering, ExtractionResponse


def _minimal(**overrides):
    base = {"name": "Little Kickers", "program_type": ProgramType.soccer}
    base.update(overrides)
    return base


def test_minimal_offering_is_valid():
    o = ExtractedOffering(**_minimal())
    assert o.name == "Little Kickers"
    assert o.program_type == ProgramType.soccer
    assert o.age_min is None
    assert o.days_of_week == []


def test_offering_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ExtractedOffering(**_minimal(unknown="x"))


def test_offering_rejects_unknown_program_type():
    with pytest.raises(ValidationError):
        ExtractedOffering(**_minimal(program_type="rhetoric"))


def test_offering_accepts_dates_and_times():
    o = ExtractedOffering(
        **_minimal(
            age_min=6,
            age_max=8,
            start_date=date(2026, 5, 3),
            end_date=date(2026, 6, 21),
            time_start=time(9, 0),
            time_end=time(10, 0),
            days_of_week=["sat"],
            registration_opens_at=datetime(2026, 4, 25, 9, 0),
            price_cents=8500,
        )
    )
    assert o.price_cents == 8500
    assert o.days_of_week == ["sat"]


def test_extraction_response_collects_offerings():
    r = ExtractionResponse(offerings=[ExtractedOffering(**_minimal())])
    assert len(r.offerings) == 1


def test_extraction_response_rejects_unknown_top_level():
    with pytest.raises(ValidationError):
        ExtractionResponse(offerings=[], model="oops")
