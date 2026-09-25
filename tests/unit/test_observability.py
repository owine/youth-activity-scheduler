"""Sentry/GlitchTip init contract: off without a DSN, private when on."""

from __future__ import annotations

import logging

import httpx
import pytest
import sentry_sdk

from tests.fakes.sentry import TEST_DSN, CapturingTransport, reset_sentry
from yas.config import Settings
from yas.observability import init_sentry


def _settings(monkeypatch: pytest.MonkeyPatch, **env: str) -> Settings:
    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    for key in ("SENTRY_DSN", "SENTRY_ENVIRONMENT", "YAS_GIT_SHA"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return Settings(_env_file=None)  # type: ignore[call-arg]


@pytest.fixture(autouse=True)
def _no_leaked_client():
    yield
    reset_sentry()


def test_init_is_a_noop_without_a_dsn(monkeypatch):
    assert init_sentry(_settings(monkeypatch)) is False
    assert not sentry_sdk.get_client().is_active()


def test_init_is_a_noop_with_an_empty_dsn(monkeypatch):
    # Compose renders an unset ${YAS_SENTRY_DSN} as an empty string, not absent.
    assert init_sentry(_settings(monkeypatch, SENTRY_DSN="")) is False
    assert not sentry_sdk.get_client().is_active()


def test_events_carry_release_and_environment(monkeypatch):
    transport = CapturingTransport()
    settings = _settings(
        monkeypatch, SENTRY_DSN=TEST_DSN, SENTRY_ENVIRONMENT="staging", YAS_GIT_SHA="abc123"
    )
    assert init_sentry(settings, transport=transport) is True

    sentry_sdk.capture_message("hello")

    [event] = transport.events
    assert event["release"] == "abc123"
    assert event["environment"] == "staging"


def test_environment_defaults_to_production(monkeypatch):
    transport = CapturingTransport()
    init_sentry(_settings(monkeypatch, SENTRY_DSN=TEST_DSN), transport=transport)

    sentry_sdk.capture_message("hello")

    assert transport.events[0]["environment"] == "production"


def test_tracing_profiling_and_pii_are_off(monkeypatch):
    init_sentry(_settings(monkeypatch, SENTRY_DSN=TEST_DSN), transport=CapturingTransport())
    options = sentry_sdk.get_client().options
    assert options["traces_sample_rate"] == 0
    assert options["send_default_pii"] is False
    assert options["profiles_sample_rate"] is None
    assert options["profiles_sampler"] is None


async def test_outgoing_requests_carry_no_trace_headers(monkeypatch):
    """API handlers fetch third-party sites (/discover, household geocode); none of
    them should get our GlitchTip key.

    Inside a transaction, sentry-sdk's httpx integration attaches sentry-trace +
    baggage (which embeds the DSN public key) to every outgoing request by
    default. The FastAPI integration opens one per request even at
    traces_sample_rate=0 — unsampled, but still propagating.
    """
    init_sentry(_settings(monkeypatch, SENTRY_DSN=TEST_DSN), transport=CapturingTransport())
    seen: list[httpx.Headers] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers)
        return httpx.Response(200)

    with sentry_sdk.start_transaction(name="GET /api/sites/{site_id}/discover"):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await client.get("https://some-youth-league.example/programs")

    assert "sentry-trace" not in seen[0]
    assert "baggage" not in seen[0]


async def test_http_breadcrumbs_do_not_leak_geocoded_addresses(monkeypatch):
    """Nominatim requests carry the household address in `q=`; keep it out of events."""
    transport = CapturingTransport()
    init_sentry(_settings(monkeypatch, SENTRY_DSN=TEST_DSN), transport=transport)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await client.get("https://nominatim.example/search", params={"q": "123 Elm St"})
    logging.getLogger("httpx").warning("HTTP Request: GET /search?q=123+Elm+St")
    sentry_sdk.capture_message("after geocode")

    [event] = transport.events
    assert "Elm" not in repr(event.get("breadcrumbs"))
