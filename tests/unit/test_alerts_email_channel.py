"""Tests for EmailChannel with SMTP and ForwardEmail transports."""

from __future__ import annotations

import base64
from unittest.mock import patch

import aiosmtplib
import httpx
import pytest
import respx

from tests.fakes.smtp_server import fake_smtp_server
from yas.alerts.channels.base import NotifierCapability, NotifierMessage
from yas.alerts.channels.email import EmailChannel, _ForwardEmailTransport, _SMTPTransport
from yas.config import Settings
from yas.db.models._types import AlertType

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


def _msg(
    subject: str = "Test Subject",
    body_plain: str = "Plain body text.",
    body_html: str | None = "<p>HTML body</p>",
) -> NotifierMessage:
    return NotifierMessage(
        kid_id=1,
        alert_type=AlertType.new_match,
        subject=subject,
        body_plain=body_plain,
        body_html=body_html,
    )


# ---------------------------------------------------------------------------
# SMTP transport tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smtp_transport_sends_message():
    """Message arrives at the fake SMTP server."""
    async with fake_smtp_server() as server:
        transport = _SMTPTransport(
            host=server.host,
            port=server.port,
            use_tls=False,
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
            username=None,
            password=None,
        )
        msg = _msg()
        result = await transport.send(msg)

    assert result.ok is True
    assert result.transient_failure is False
    assert len(server.captured) == 1


@pytest.mark.asyncio
async def test_smtp_transport_message_headers():
    """Captured message has correct Subject, From, To."""
    async with fake_smtp_server() as server:
        transport = _SMTPTransport(
            host=server.host,
            port=server.port,
            use_tls=False,
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
            username=None,
            password=None,
        )
        msg = _msg(subject="Hello Scheduler")
        await transport.send(msg)

    captured = server.captured[0]
    assert captured.from_addr == "from@example.com"
    assert "to@example.com" in captured.to_addrs
    assert captured.message["Subject"] == "Hello Scheduler"
    assert captured.message["From"] == "from@example.com"
    assert "to@example.com" in captured.message["To"]


@pytest.mark.asyncio
async def test_smtp_transport_multipart_alternative():
    """Email has multipart/alternative with both plain and HTML parts."""
    async with fake_smtp_server() as server:
        transport = _SMTPTransport(
            host=server.host,
            port=server.port,
            use_tls=False,
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
            username=None,
            password=None,
        )
        msg = _msg(body_plain="Plain text.", body_html="<p>HTML</p>")
        await transport.send(msg)

    captured = server.captured[0]
    email_msg = captured.message
    assert email_msg.get_content_type() == "multipart/alternative"
    parts = list(email_msg.iter_parts())
    content_types = [p.get_content_type() for p in parts]
    assert "text/plain" in content_types
    assert "text/html" in content_types


@pytest.mark.asyncio
async def test_smtp_transport_send_result_detail():
    """detail string is log-friendly."""
    async with fake_smtp_server() as server:
        transport = _SMTPTransport(
            host=server.host,
            port=server.port,
            use_tls=False,
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
            username=None,
            password=None,
        )
        result = await transport.send(_msg())

    assert "250" in result.detail or "smtp" in result.detail.lower()


@pytest.mark.asyncio
async def test_smtp_4xx_is_transient(monkeypatch):
    """4xx SMTP response → ok=False, transient_failure=True (RFC 5321: retry later)."""

    async def _fake_send(*args, **kwargs):
        raise aiosmtplib.SMTPResponseException(450, "Requested mail action not taken")

    monkeypatch.setattr("yas.alerts.channels.email.aiosmtplib.send", _fake_send)

    transport = _SMTPTransport(
        host="127.0.0.1",
        port=9999,
        use_tls=False,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
        username=None,
        password=None,
    )
    result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True
    assert "450" in result.detail


@pytest.mark.asyncio
async def test_smtp_5xx_is_non_transient(monkeypatch):
    """5xx SMTP response → ok=False, transient_failure=False (RFC 5321: permanent failure)."""

    async def _fake_send(*args, **kwargs):
        raise aiosmtplib.SMTPResponseException(554, "Transaction failed")

    monkeypatch.setattr("yas.alerts.channels.email.aiosmtplib.send", _fake_send)

    transport = _SMTPTransport(
        host="127.0.0.1",
        port=9999,
        use_tls=False,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
        username=None,
        password=None,
    )
    result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is False


@pytest.mark.asyncio
async def test_smtp_transport_421_transient(monkeypatch):
    """421 (service unavailable) → transient."""

    async def _fake_send(*args, **kwargs):
        raise aiosmtplib.SMTPResponseException(421, "Service not available")

    monkeypatch.setattr("yas.alerts.channels.email.aiosmtplib.send", _fake_send)

    transport = _SMTPTransport(
        host="127.0.0.1",
        port=9999,
        use_tls=False,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
        username=None,
        password=None,
    )
    result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_smtp_transport_connect_error_transient(monkeypatch):
    """SMTPConnectError → transient failure."""

    async def _fake_send(*args, **kwargs):
        raise aiosmtplib.SMTPConnectError("Connection refused")

    monkeypatch.setattr("yas.alerts.channels.email.aiosmtplib.send", _fake_send)

    transport = _SMTPTransport(
        host="127.0.0.1",
        port=9999,
        use_tls=False,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
        username=None,
        password=None,
    )
    result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_smtp_transport_timeout_transient(monkeypatch):
    """TimeoutError → transient failure."""

    async def _fake_send(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr("yas.alerts.channels.email.aiosmtplib.send", _fake_send)

    transport = _SMTPTransport(
        host="127.0.0.1",
        port=9999,
        use_tls=False,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
        username=None,
        password=None,
    )
    result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_smtp_recipients_refused_is_transient():
    """SMTPRecipientsRefused → ok=False, transient_failure=True (catch-all SMTPException)."""
    with patch("yas.alerts.channels.email.aiosmtplib.send") as mock_send:
        mock_send.side_effect = aiosmtplib.SMTPRecipientsRefused(
            {"bad@example.com": (550, b"no such user")}
        )
        transport = _SMTPTransport(
            host="127.0.0.1",
            port=9999,
            use_tls=False,
            from_addr="from@example.com",
            to_addrs=["bad@example.com"],
            username=None,
            password=None,
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


# ---------------------------------------------------------------------------
# ForwardEmail transport tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forwardemail_transport_posts_to_api():
    """POST to ForwardEmail API with correct URL and Basic Auth."""
    with respx.mock:
        route = respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "abc123"})
        )
        transport = _ForwardEmailTransport(
            api_token="test-api-token",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert route.called
    assert result.ok is True
    assert result.transient_failure is False


@pytest.mark.asyncio
async def test_forwardemail_transport_basic_auth():
    """Basic Auth uses the token as username, empty password."""
    with respx.mock:
        route = respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "abc123"})
        )
        transport = _ForwardEmailTransport(
            api_token="my-secret-token",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        await transport.send(_msg())

    request = route.calls[0].request
    auth_header = request.headers.get("authorization", "")
    assert auth_header.startswith("Basic ")
    decoded = base64.b64decode(auth_header[6:]).decode()
    token, _sep, password = decoded.partition(":")
    assert token == "my-secret-token"
    assert password == ""


@pytest.mark.asyncio
async def test_forwardemail_transport_form_fields():
    """Form fields: from, to, subject, text, html."""
    with respx.mock:
        route = respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        transport = _ForwardEmailTransport(
            api_token="tok",
            from_addr="yas@example.com",
            to_addrs=["user@example.com", "user2@example.com"],
        )
        msg = _msg(
            subject="Test Subject",
            body_plain="Plain body",
            body_html="<p>HTML body</p>",
        )
        await transport.send(msg)

    request = route.calls[0].request
    content = request.content.decode()
    assert "from=yas%40example.com" in content
    assert "subject=" in content
    assert "text=" in content
    assert "html=" in content
    # to_addrs joined as comma string
    assert "to=" in content


@pytest.mark.asyncio
async def test_forwardemail_transport_http_200_detail():
    """detail is 'http 200' on success."""
    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        transport = _ForwardEmailTransport(
            api_token="tok",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.detail == "http 200"


@pytest.mark.asyncio
async def test_forwardemail_transport_4xx_non_transient():
    """4xx (not 429) → ok=False, transient_failure=False."""
    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(400, json={"message": "Bad request"})
        )
        transport = _ForwardEmailTransport(
            api_token="tok",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is False
    assert "400" in result.detail


@pytest.mark.asyncio
async def test_forwardemail_transport_429_transient():
    """429 → ok=False, transient_failure=True."""
    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(429, json={"message": "rate limited"})
        )
        transport = _ForwardEmailTransport(
            api_token="tok",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_forwardemail_transport_5xx_transient():
    """5xx → ok=False, transient_failure=True."""
    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(503, json={"message": "unavailable"})
        )
        transport = _ForwardEmailTransport(
            api_token="tok",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_forwardemail_transport_timeout_transient():
    """httpx.TimeoutException → transient failure."""
    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        transport = _ForwardEmailTransport(
            api_token="tok",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_forwardemail_connect_error_is_transient():
    """httpx.ConnectError (DNS failure, connection refused) → transient failure."""
    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            side_effect=httpx.ConnectError("dns failure")
        )
        transport = _ForwardEmailTransport(
            api_token="tok",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


def test_forwardemail_token_missing_raises():
    """Empty api_token → ValueError at init."""
    with pytest.raises(ValueError, match="not set"):
        _ForwardEmailTransport(
            api_token="",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )


# ---------------------------------------------------------------------------
# EmailChannel tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_channel_selects_smtp():
    """EmailChannel with transport=smtp creates a working SMTP channel."""
    async with fake_smtp_server() as server:
        config = {
            "transport": "smtp",
            "host": server.host,
            "port": server.port,
            "use_tls": False,
            "from_addr": "yas@example.com",
            "to_addrs": ["user@example.com"],
        }
        channel = EmailChannel(config, _settings())
        result = await channel.send(_msg())
        await channel.aclose()

    assert result.ok is True
    assert len(server.captured) == 1


@pytest.mark.asyncio
async def test_email_channel_selects_forwardemail():
    """EmailChannel with transport=forwardemail creates a working FE channel."""
    config = {
        "transport": "forwardemail",
        "api_token_value": "tok",
        "from_addr": "yas@example.com",
        "to_addrs": ["user@example.com"],
    }
    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        channel = EmailChannel(config, _settings())
        result = await channel.send(_msg())
        await channel.aclose()

    assert result.ok is True


@pytest.mark.asyncio
async def test_email_channel_forwardemail_uses_settings_fallback():
    """When config has no api_token_value, EmailChannel falls back to Settings."""
    config = {
        "transport": "forwardemail",
        "from_addr": "yas@example.com",
        "to_addrs": ["user@example.com"],
    }
    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        channel = EmailChannel(config, _settings(forwardemail_api_token="env-tok"))
        result = await channel.send(_msg())
        await channel.aclose()

    assert result.ok is True


def test_email_channel_forwardemail_missing_token_raises():
    """forwardemail with neither config value nor settings → ValueError."""
    config = {
        "transport": "forwardemail",
        "from_addr": "yas@example.com",
        "to_addrs": ["user@example.com"],
    }
    with pytest.raises(ValueError, match="not set"):
        EmailChannel(config, _settings())


def test_email_channel_unknown_transport_raises():
    """Unknown transport value → ValueError."""
    config = {
        "transport": "pigeon",
        "from_addr": "a@b.com",
        "to_addrs": ["c@d.com"],
    }
    with pytest.raises(ValueError, match="pigeon"):
        EmailChannel(config, _settings())


def test_email_channel_capabilities():
    """EmailChannel reports email capability."""
    config = {
        "transport": "smtp",
        "host": "127.0.0.1",
        "port": 1,
        "use_tls": False,
        "from_addr": "a@b.com",
        "to_addrs": ["c@d.com"],
    }
    ch = EmailChannel(config, _settings())
    assert NotifierCapability.email in ch.capabilities
    assert ch.name == "email"
