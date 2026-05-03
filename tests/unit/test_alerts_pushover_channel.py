"""Tests for PushoverChannel."""

from __future__ import annotations

from urllib.parse import parse_qs

import httpx
import pytest
import respx

from yas.alerts.channels.base import NotifierCapability, NotifierMessage
from yas.alerts.channels.pushover import PushoverChannel
from yas.config import Settings
from yas.db.models._types import AlertType

_PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**overrides: object) -> Settings:
    """Build a Settings with credentials stubbed. Pass kwargs to override
    specific credential fields; otherwise they default to None so tests
    fully control resolution via the config dict."""
    defaults: dict = {"anthropic_api_key": "sk-test"}
    defaults.update(overrides)
    return Settings(**defaults)


def _cfg(**kwargs: object) -> dict:
    base: dict = {
        "user_key_value": "user123",
        "app_token_value": "tok123",
        "emergency_retry_s": 30,
        "emergency_expire_s": 600,
    }
    base.update(kwargs)
    return base


def _msg(
    subject: str = "Test Subject",
    body_plain: str = "Plain body.",
    *,
    alert_type: AlertType = AlertType.reg_opens_24h,
    url: str | None = None,
    urgent: bool = False,
) -> NotifierMessage:
    return NotifierMessage(
        kid_id=None,
        alert_type=alert_type,
        subject=subject,
        body_plain=body_plain,
        url=url,
        urgent=urgent,
    )


def _parse_form(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(request.content.decode())


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


def test_pushover_capabilities():
    ch = PushoverChannel(_cfg(), _settings())
    assert ch.capabilities == {NotifierCapability.push, NotifierCapability.push_emergency}
    assert ch.name == "pushover"


# ---------------------------------------------------------------------------
# Basic POST
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pushover_posts_to_api_url():
    with respx.mock() as m:
        route = m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(200, json={"status": 1, "request": "abc"})
        )
        ch = PushoverChannel(_cfg(), _settings())
        result = await ch.send(_msg())
        await ch.aclose()

    assert route.called
    assert result.ok is True


@pytest.mark.asyncio
async def test_pushover_form_fields_token_user_title_message():
    with respx.mock() as m:
        route = m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(200, json={"status": 1, "request": "abc"})
        )
        ch = PushoverChannel(_cfg(), _settings())
        await ch.send(_msg(subject="My Subject", body_plain="My body"))
        await ch.aclose()

    form = _parse_form(route.calls.last.request)
    assert form["token"] == ["tok123"]
    assert form["user"] == ["user123"]
    assert form["title"] == ["My Subject"]
    assert form["message"] == ["My body"]


# ---------------------------------------------------------------------------
# URL fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pushover_url_and_url_title_set_when_url_given():
    with respx.mock() as m:
        route = m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(200, json={"status": 1, "request": "abc"})
        )
        ch = PushoverChannel(_cfg(), _settings())
        await ch.send(_msg(subject="Sign Up", url="https://example.com/reg"))
        await ch.aclose()

    form = _parse_form(route.calls.last.request)
    assert form["url"] == ["https://example.com/reg"]
    assert form["url_title"] == ["Sign Up"]


@pytest.mark.asyncio
async def test_pushover_url_fields_absent_when_no_url():
    with respx.mock() as m:
        route = m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(200, json={"status": 1, "request": "abc"})
        )
        ch = PushoverChannel(_cfg(), _settings())
        await ch.send(_msg(url=None))
        await ch.aclose()

    form = _parse_form(route.calls.last.request)
    assert "url" not in form
    assert "url_title" not in form


# ---------------------------------------------------------------------------
# Priority — named must-have test
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pushover_priority_2_for_reg_opens_now():
    """reg_opens_now → form contains priority=2 plus retry/expire from config."""
    with respx.mock() as m:
        route = m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(200, json={"status": 1, "request": "abc"})
        )
        ch = PushoverChannel(_cfg(emergency_retry_s=30, emergency_expire_s=600), _settings())
        await ch.send(_msg(alert_type=AlertType.reg_opens_now))
        await ch.aclose()

    form = _parse_form(route.calls.last.request)
    assert form["priority"] == ["2"]
    assert form["retry"] == ["30"]
    assert form["expire"] == ["600"]


@pytest.mark.asyncio
async def test_pushover_priority_0_for_non_emergency():
    """Non-emergency alert types → priority=0, no retry/expire."""
    with respx.mock() as m:
        route = m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(200, json={"status": 1, "request": "abc"})
        )
        ch = PushoverChannel(_cfg(), _settings())
        await ch.send(_msg(alert_type=AlertType.reg_opens_24h))
        await ch.aclose()

    form = _parse_form(route.calls.last.request)
    assert form["priority"] == ["0"]
    assert "retry" not in form
    assert "expire" not in form


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pushover_devices_comma_joined_when_list_nonempty():
    with respx.mock() as m:
        route = m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(200, json={"status": 1, "request": "abc"})
        )
        ch = PushoverChannel(_cfg(devices=["iphone", "ipad"]), _settings())
        await ch.send(_msg())
        await ch.aclose()

    form = _parse_form(route.calls.last.request)
    assert form["device"] == ["iphone,ipad"]


@pytest.mark.asyncio
async def test_pushover_device_field_absent_when_no_devices():
    with respx.mock() as m:
        route = m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(200, json={"status": 1, "request": "abc"})
        )
        ch = PushoverChannel(_cfg(), _settings())  # no devices key
        await ch.send(_msg())
        await ch.aclose()

    form = _parse_form(route.calls.last.request)
    assert "device" not in form


@pytest.mark.asyncio
async def test_pushover_device_field_absent_when_empty_list():
    with respx.mock() as m:
        route = m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(200, json={"status": 1, "request": "abc"})
        )
        ch = PushoverChannel(_cfg(devices=[]), _settings())
        await ch.send(_msg())
        await ch.aclose()

    form = _parse_form(route.calls.last.request)
    assert "device" not in form


# ---------------------------------------------------------------------------
# Response / SendResult taxonomy
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pushover_status_1_ok():
    with respx.mock() as m:
        m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(200, json={"status": 1, "request": "abc"})
        )
        ch = PushoverChannel(_cfg(), _settings())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is True
    assert result.transient_failure is False


@pytest.mark.asyncio
async def test_pushover_status_0_non_transient():
    """HTTP 200 with JSON status:0 → ok=False, transient_failure=False, detail contains errors."""
    with respx.mock() as m:
        m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(
                200,
                json={"status": 0, "errors": ["user key is invalid"]},
            )
        )
        ch = PushoverChannel(_cfg(), _settings())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is False
    assert "user key is invalid" in result.detail


@pytest.mark.asyncio
async def test_pushover_http_429_transient():
    with respx.mock() as m:
        m.post(_PUSHOVER_URL).mock(return_value=httpx.Response(429, json={}))
        ch = PushoverChannel(_cfg(), _settings())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_pushover_http_5xx_transient():
    with respx.mock() as m:
        m.post(_PUSHOVER_URL).mock(return_value=httpx.Response(503, json={}))
        ch = PushoverChannel(_cfg(), _settings())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_pushover_http_4xx_status_0_non_transient():
    with respx.mock() as m:
        m.post(_PUSHOVER_URL).mock(
            return_value=httpx.Response(
                400,
                json={"status": 0, "errors": ["token is invalid"]},
            )
        )
        ch = PushoverChannel(_cfg(), _settings())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is False


# ---------------------------------------------------------------------------
# Transport errors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pushover_timeout_is_transient():
    with respx.mock() as m:
        m.post(_PUSHOVER_URL).mock(side_effect=httpx.TimeoutException("timed out"))
        ch = PushoverChannel(_cfg(), _settings())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is True
    assert "timeout" in result.detail


@pytest.mark.asyncio
async def test_pushover_connect_error_is_transient():
    with respx.mock() as m:
        m.post(_PUSHOVER_URL).mock(side_effect=httpx.ConnectError("dns failure"))
        ch = PushoverChannel(_cfg(), _settings())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is True
    assert "network error" in result.detail


# ---------------------------------------------------------------------------
# Missing credentials
# ---------------------------------------------------------------------------


def test_pushover_missing_user_key_raises():
    with pytest.raises(ValueError, match="not set"):
        PushoverChannel(_cfg(user_key_value=None), _settings())


def test_pushover_missing_app_token_raises():
    with pytest.raises(ValueError, match="not set"):
        PushoverChannel(_cfg(app_token_value=None), _settings())


def test_pushover_blank_user_key_raises():
    with pytest.raises(ValueError, match="not set"):
        PushoverChannel(_cfg(user_key_value=""), _settings())


def test_pushover_blank_app_token_raises():
    with pytest.raises(ValueError, match="not set"):
        PushoverChannel(_cfg(app_token_value=""), _settings())


def test_pushover_falls_back_to_settings_env():
    """When form value is unset, channel uses Settings (env-loaded) credentials."""
    cfg = _cfg(user_key_value=None, app_token_value=None)
    settings = _settings(pushover_user_key="env-user", pushover_app_token="env-tok")
    ch = PushoverChannel(cfg, settings)
    assert ch._user_key == "env-user"
    assert ch._app_token == "env-tok"


@pytest.mark.asyncio
async def test_pushover_malformed_json_response():
    """Non-JSON body (e.g. HTML error page) → body={}, status defaults to 0, non-transient."""
    with respx.mock() as m:
        m.post(_PUSHOVER_URL).mock(return_value=httpx.Response(200, text="<html>error</html>"))
        ch = PushoverChannel(_cfg(), _settings())
        result = await ch.send(_msg())
        await ch.aclose()

    assert result.ok is False
    assert result.transient_failure is False
