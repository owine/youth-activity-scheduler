"""Tests for the LLM top-line generator with template fallback."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

from yas.alerts.digest.builder import DigestPayload
from yas.alerts.digest.llm_summary import generate_top_line

# ---------------------------------------------------------------------------
# Test double
# ---------------------------------------------------------------------------


@dataclass
class _StubLLM:
    """Test double for LLMClient.call_tool only."""

    response: dict[str, Any] = field(default_factory=dict)
    raise_exc: Exception | None = None
    call_count: int = 0
    last_user: str = ""
    last_system: str = ""

    async def extract_offerings(self, **_: Any) -> Any:
        raise NotImplementedError

    async def call_tool(
        self,
        *,
        system: str,
        user: str,
        tool_name: str,
        tool_description: str,
        input_schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> tuple[dict[str, Any], str, float]:
        self.call_count += 1
        self.last_user = user
        self.last_system = system
        if self.raise_exc:
            raise self.raise_exc
        return self.response, "stub-model", 0.0001


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_payload(
    kid_name: str = "Alex",
    new_matches: list[dict[str, Any]] | None = None,
    starting_soon: list[dict[str, Any]] | None = None,
    registration_calendar: list[dict[str, Any]] | None = None,
) -> DigestPayload:
    return DigestPayload(
        kid_id=1,
        kid_name=kid_name,
        for_date=date(2026, 4, 23),
        new_matches=new_matches or [],
        starting_soon=starting_soon or [],
        registration_calendar=registration_calendar or [],
    )


def _offering(name: str) -> dict[str, Any]:
    return {"offering_name": name, "offering_id": 1}


# ---------------------------------------------------------------------------
# Named must-have tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_top_line_falls_back_to_template_on_failure() -> None:
    stub = _StubLLM(raise_exc=RuntimeError("nope"))
    payload = _make_payload(
        new_matches=[_offering("Swim")],
        registration_calendar=[_offering("Soccer")],
    )
    result = await generate_top_line(payload, stub, cost_cap_remaining_usd=1.00)
    assert result == "Alex's activities — 1 new matches, 1 opening soon"


@pytest.mark.asyncio
async def test_llm_top_line_falls_back_to_template_when_llm_is_none() -> None:
    payload = _make_payload(
        new_matches=[_offering("Swim"), _offering("Tennis")],
        registration_calendar=[_offering("Soccer"), _offering("Art")],
    )
    result = await generate_top_line(payload, None, cost_cap_remaining_usd=1.00)
    assert result == "Alex's activities — 2 new matches, 2 opening soon"


# ---------------------------------------------------------------------------
# Additional tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_top_line_returns_llm_value_on_success() -> None:
    stub = _StubLLM(response={"top_line": "3 swim classes opening soon"})
    payload = _make_payload()
    result = await generate_top_line(payload, stub, cost_cap_remaining_usd=1.00)
    assert result == "3 swim classes opening soon"


@pytest.mark.asyncio
async def test_llm_top_line_falls_back_on_empty_string() -> None:
    stub = _StubLLM(response={"top_line": ""})
    payload = _make_payload(
        new_matches=[_offering("Swim")],
        registration_calendar=[],
    )
    result = await generate_top_line(payload, stub, cost_cap_remaining_usd=1.00)
    assert result == "Alex's activities — 1 new matches, 0 opening soon"


@pytest.mark.asyncio
async def test_llm_top_line_falls_back_on_over_200_chars() -> None:
    long_str = "x" * 201
    stub = _StubLLM(response={"top_line": long_str})
    payload = _make_payload(
        new_matches=[_offering("Swim")],
        registration_calendar=[_offering("Soccer"), _offering("Art")],
    )
    result = await generate_top_line(payload, stub, cost_cap_remaining_usd=1.00)
    assert result == "Alex's activities — 1 new matches, 2 opening soon"


@pytest.mark.asyncio
async def test_llm_top_line_falls_back_on_cost_cap_exhausted() -> None:
    """LLM must NOT be called when cost cap is exhausted."""

    class _FailIfCalled(_StubLLM):
        async def call_tool(self, **kwargs: Any) -> Any:
            raise AssertionError("LLM should not have been called")

    stub = _FailIfCalled()
    payload = _make_payload(
        new_matches=[_offering("Swim")],
        registration_calendar=[_offering("Soccer")],
    )
    result = await generate_top_line(payload, stub, cost_cap_remaining_usd=0.005)
    assert result == "Alex's activities — 1 new matches, 1 opening soon"
    assert stub.call_count == 0


@pytest.mark.asyncio
async def test_llm_top_line_user_prompt_includes_counts_and_top_names() -> None:
    """Pins the user prompt shape so future edits don't silently break it."""
    stub = _StubLLM(response={"top_line": "Some summary"})
    new_matches = [
        _offering("Swim A"),
        _offering("Swim B"),
        _offering("Tennis"),
        _offering("Soccer"),  # 4th — should NOT appear in top_new_matches
    ]
    registration_calendar = [
        _offering("Art"),
        _offering("Ballet"),
    ]
    payload = _make_payload(
        kid_name="Jordan",
        new_matches=new_matches,
        starting_soon=[_offering("Yoga")],
        registration_calendar=registration_calendar,
    )

    await generate_top_line(payload, stub, cost_cap_remaining_usd=1.00)

    prompt = json.loads(stub.last_user)

    assert prompt["kid_name"] == "Jordan"
    assert prompt["new_matches_count"] == 4
    assert prompt["starting_soon_count"] == 1
    assert prompt["registration_opens_soon_count"] == 2
    assert prompt["top_new_matches"] == ["Swim A", "Swim B", "Tennis"]
    assert prompt["top_registration_opens"] == ["Art", "Ballet"]
