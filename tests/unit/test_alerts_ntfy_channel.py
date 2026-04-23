"""Tests for NtfyChannel."""

from __future__ import annotations

import httpx
import pytest
import respx

from yas.alerts.channels.base import NotifierCapability, NotifierMessage
from yas.alerts.channels.ntfy import NtfyChannel
from yas.db.models._types import AlertType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_URL = "https://ntfy.example.com"
_TOPIC = "mytopic"


def _cfg(**kwargs: object) -> dict:
    return {"base_url": _BASE_URL, "topic": _TOPIC, **kwargs}


def _msg(
    subject: str = "Test Subject",
    body_plain: str = "Plain body.",
    *,
    urgent: bool = False,
    url: str | None = None,
    alert_type: AlertType = AlertType.reg_opens_24h,
) -> NotifierMessage:
    return NotifierMessage(
        kid_id=None,
        alert_type=alert_type,
        subject=subject,
        body_plain=body_plain,
        urgent=urgent,
        url=url,
    )


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------

def test_ntfy_capabilities():
    ch = NtfyChannel(_cfg())
    assert ch.capabilities == {NotifierCapability.push}
    assert ch.name == "ntfy"


# ---------------------------------------------------------------------------
# Basic POST
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ntfy_posts_to_exact_url():
    with respx.mock() as m:
        route = m.post(f"{_BASE_URL}/{_TOPIC}").mock(
            return_value=httpx.Response(200, text="ok")
        )
        ch = NtfyChannel(_cfg())
        result = await ch.send(_msg())
        await ch.aclose()

    assert route.called
    assert result.ok is True
    assert result.transient_failure is False


@pytest.mark.asyncio
async def test_ntfy_title_header_is_subject():
    with respx.mock() as m:
        route = m.post(f"{_BASE_URL}/{_TOPIC}").mock(
            return_value=httpx.Response(200, text="ok")
        )
        ch = NtfyChannel(_cfg())
        await ch.send(_msg(subject="Hello World"))
        await ch.aclose()

    assert route.calls.last.request.headers["Title"] == "Hello World"


@pytest.mark.asyncio
async def test_ntfy_body_is_body_plain_bytes():
    with respx.mock() as m:
        route = m.post(f"{_BASE_URL}/{_TOPIC}").mock(
            return_value=httpx.Response(200, text="ok")
        )
        ch = NtfyChannel(_cfg())
        await ch.send(_msg(body_plain="my body text"))
        await ch.aclose()

    assert route.calls.last.request.content == b"my body text"


# ---------------------------------------------------------------------------
# Priority header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ntfy_priority_high_when_urgent():
    with respx.mock() as m:
        route = m.post(f"{_BASE_URL}/{_TOPIC}").mock(
            return_value=httpx.Response(200, text="ok")
        )
        ch = NtfyChannel(_cfg())
        await ch.send(_msg(urgent=True))
        await ch.aclose()

    assert route.calls.last.request.headers["Priority"] == "high"


@pytest.mark.asyncio
async def test_ntfy_priority_header_absent_when_not_urgent():
    with respx.mock() as m:
        route = m.post(f"{_BASE_URL}/{_TOPIC}").mock(
            return_value=httpx.Response(200, text="ok")
        )
        ch = NtfyChannel(_cfg())
        await ch.send(_msg(urgent=False))
        await ch.aclose()

    assert "Priority" not in route.calls.last.request.headers


# ---------------------------------------------------------------------------
# Click header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ntfy_click_header_set_when_url_given():
    with respx.mock() as m:
        route = m.post(f"{_BASE_URL}/{_TOPIC}").mock(
            return_value=httpx.Response(200, text="ok")
        )
        ch = NtfyChannel(_cfg())
        await ch.send(_msg(url="https://example.com/register"))
        await ch.aclose()

    assert route.calls.last.request.headers["Click"] == "https://example.com/register"


@pytest.mark.asyncio
async def test_ntfy_click_header_absent_when_no_url():
    with respx.mock() as m:
        route = m.post(f"{_BASE_URL}/{_TOPIC}").mock(
            return_value=httpx.Response(200, text="ok")
        )
        ch = NtfyChannel(_cfg())
        await ch.send(_msg(url=None))
        await ch.aclose()

    assert "Click" not in route.calls.last.request.headers


# ---------------------------------------------------------------------------
# Authorization header
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ntfy_auth_header_when_token_configured(monkeypatch):
    monkeypatch.setenv("YAS_NTFY_TOKEN", "secret-token")

    with respx.mock() as m:
        route = m.post(f"{_BASE_URL}/{_TOPIC}").mock(
            return_value=httpx.Response(200, text="ok")
        )
        ch = NtfyChannel(_cfg(auth_token_env="YAS_NTFY_TOKEN"))
        await ch.send(_msg())
        await ch.aclose()

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
async def test_ntfy_auth_header_absent_when_no_token_env():
    with respx.mock() as m:
        route = m.post(f"{_BASE_URL}/{_TOPIC}").mock(
            return_value=httpx.Response(200, text="ok")
        )
        ch = NtfyChannel(_cfg())  # no auth_token_env
        await ch.send(_msg())
        await ch.aclose()

    assert "Authorization" not in route.calls.last.request.headers


def test_ntfy_missing_token_env_raises(monkeypatch):
    monkeypatch.delenv("YAS_NTFY_TOKEN", raising=False)

    with pytest.raises(ValueError, match="YAS_NTFY_TOKEN"):
        NtfyChannel(_cfg(auth_token_env="YAS_NTFY_TOKEN"))


def test_ntfy_blank_token_env_raises(monkeypatch):
    monkeypatch.setenv("YAS_NTFY_TOKEN", "")

    with pytest.raises(ValueError, match="set but empty"):
        NtfyChannel(_cfg(auth_token_env="YAS_NTFY_TOKEN"))


# ---------------------------------------------------------------------------
# HTTP status → SendResult taxonomy
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ntfy_2xx_ok():
    with respx.mock() as m:
        m.post(f"{_BASE_URL}/{_TOPIC}").mock(return_value=httpx.Response(200, text="ok"))
        ch = NtfyChannel(_cfg())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is True
    assert result.transient_failure is False


@pytest.mark.asyncio
async def test_ntfy_4xx_non_transient():
    with respx.mock() as m:
        m.post(f"{_BASE_URL}/{_TOPIC}").mock(return_value=httpx.Response(403, text="forbidden"))
        ch = NtfyChannel(_cfg())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is False


@pytest.mark.asyncio
async def test_ntfy_429_transient():
    with respx.mock() as m:
        m.post(f"{_BASE_URL}/{_TOPIC}").mock(return_value=httpx.Response(429, text="rate limited"))
        ch = NtfyChannel(_cfg())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_ntfy_5xx_transient():
    with respx.mock() as m:
        m.post(f"{_BASE_URL}/{_TOPIC}").mock(return_value=httpx.Response(503, text="unavailable"))
        ch = NtfyChannel(_cfg())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is True


# ---------------------------------------------------------------------------
# Transport errors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ntfy_timeout_is_transient():
    with respx.mock() as m:
        m.post(f"{_BASE_URL}/{_TOPIC}").mock(side_effect=httpx.TimeoutException("timed out"))
        ch = NtfyChannel(_cfg())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is True
    assert "timeout" in result.detail


@pytest.mark.asyncio
async def test_ntfy_connect_error_is_transient():
    with respx.mock() as m:
        m.post(f"{_BASE_URL}/{_TOPIC}").mock(side_effect=httpx.ConnectError("dns failure"))
        ch = NtfyChannel(_cfg())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is True
    assert "network error" in result.detail


# ---------------------------------------------------------------------------
# URL normalisation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ntfy_trailing_slash_base_url_is_normalised():
    with respx.mock() as m:
        route = m.post("https://ntfy.example.com/mytopic").mock(
            return_value=httpx.Response(200, text="ok")
        )
        ch = NtfyChannel(_cfg(base_url="https://ntfy.example.com/"))
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is True
    assert route.called
