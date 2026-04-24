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
from yas.db.models._types import AlertType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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
            username=None,
            password=None,
            use_tls=False,
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
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
            username=None,
            password=None,
            use_tls=False,
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
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
            username=None,
            password=None,
            use_tls=False,
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
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
            username=None,
            password=None,
            use_tls=False,
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
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
        username=None,
        password=None,
        use_tls=False,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
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
        username=None,
        password=None,
        use_tls=False,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
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
        username=None,
        password=None,
        use_tls=False,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
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
        username=None,
        password=None,
        use_tls=False,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
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
        username=None,
        password=None,
        use_tls=False,
        from_addr="from@example.com",
        to_addrs=["to@example.com"],
    )
    result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_smtp_password_env_missing_raises(monkeypatch):
    """password_env set but env var absent → ValueError at init."""
    monkeypatch.delenv("YAS_SMTP_PASSWORD", raising=False)

    with pytest.raises(ValueError, match="YAS_SMTP_PASSWORD"):
        _SMTPTransport(
            host="smtp.example.com",
            port=587,
            username="user",
            password_env="YAS_SMTP_PASSWORD",
            use_tls=True,
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )


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
            username=None,
            password=None,
            use_tls=False,
            from_addr="from@example.com",
            to_addrs=["bad@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


# ---------------------------------------------------------------------------
# ForwardEmail transport tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forwardemail_transport_posts_to_api(monkeypatch):
    """POST to ForwardEmail API with correct URL and Basic Auth."""
    monkeypatch.setenv("YAS_FE_TOKEN", "test-api-token")

    with respx.mock:
        route = respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "abc123"})
        )
        transport = _ForwardEmailTransport(
            api_token_env="YAS_FE_TOKEN",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert route.called
    assert result.ok is True
    assert result.transient_failure is False


@pytest.mark.asyncio
async def test_forwardemail_transport_basic_auth(monkeypatch):
    """Basic Auth uses the token as username, empty password."""
    monkeypatch.setenv("YAS_FE_TOKEN", "my-secret-token")

    with respx.mock:
        route = respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "abc123"})
        )
        transport = _ForwardEmailTransport(
            api_token_env="YAS_FE_TOKEN",
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
async def test_forwardemail_transport_form_fields(monkeypatch):
    """Form fields: from, to, subject, text, html."""
    monkeypatch.setenv("YAS_FE_TOKEN", "tok")

    with respx.mock:
        route = respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        transport = _ForwardEmailTransport(
            api_token_env="YAS_FE_TOKEN",
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
async def test_forwardemail_transport_http_200_detail(monkeypatch):
    """detail is 'http 200' on success."""
    monkeypatch.setenv("YAS_FE_TOKEN", "tok")

    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        transport = _ForwardEmailTransport(
            api_token_env="YAS_FE_TOKEN",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.detail == "http 200"


@pytest.mark.asyncio
async def test_forwardemail_transport_4xx_non_transient(monkeypatch):
    """4xx (not 429) → ok=False, transient_failure=False."""
    monkeypatch.setenv("YAS_FE_TOKEN", "tok")

    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(400, json={"message": "Bad request"})
        )
        transport = _ForwardEmailTransport(
            api_token_env="YAS_FE_TOKEN",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is False
    assert "400" in result.detail


@pytest.mark.asyncio
async def test_forwardemail_transport_429_transient(monkeypatch):
    """429 → ok=False, transient_failure=True."""
    monkeypatch.setenv("YAS_FE_TOKEN", "tok")

    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(429, json={"message": "rate limited"})
        )
        transport = _ForwardEmailTransport(
            api_token_env="YAS_FE_TOKEN",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_forwardemail_transport_5xx_transient(monkeypatch):
    """5xx → ok=False, transient_failure=True."""
    monkeypatch.setenv("YAS_FE_TOKEN", "tok")

    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(503, json={"message": "unavailable"})
        )
        transport = _ForwardEmailTransport(
            api_token_env="YAS_FE_TOKEN",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_forwardemail_transport_timeout_transient(monkeypatch):
    """httpx.TimeoutException → transient failure."""
    monkeypatch.setenv("YAS_FE_TOKEN", "tok")

    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        transport = _ForwardEmailTransport(
            api_token_env="YAS_FE_TOKEN",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_forwardemail_connect_error_is_transient(monkeypatch):
    """httpx.ConnectError (DNS failure, connection refused) → transient failure."""
    monkeypatch.setenv("YAS_FE_TOKEN", "tok")

    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            side_effect=httpx.ConnectError("dns failure")
        )
        transport = _ForwardEmailTransport(
            api_token_env="YAS_FE_TOKEN",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )
        result = await transport.send(_msg())

    assert result.ok is False
    assert result.transient_failure is True


@pytest.mark.asyncio
async def test_forwardemail_token_env_missing_raises(monkeypatch):
    """api_token_env set but env var absent → ValueError at init."""
    monkeypatch.delenv("YAS_FE_TOKEN", raising=False)

    with pytest.raises(ValueError, match="YAS_FE_TOKEN"):
        _ForwardEmailTransport(
            api_token_env="YAS_FE_TOKEN",
            from_addr="from@example.com",
            to_addrs=["to@example.com"],
        )


# ---------------------------------------------------------------------------
# EmailChannel tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_channel_selects_smtp(monkeypatch):
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
        channel = EmailChannel(config)
        result = await channel.send(_msg())
        await channel.aclose()

    assert result.ok is True
    assert len(server.captured) == 1


@pytest.mark.asyncio
async def test_email_channel_selects_forwardemail(monkeypatch):
    """EmailChannel with transport=forwardemail creates a working FE channel."""
    monkeypatch.setenv("YAS_FE_TOKEN", "tok")

    config = {
        "transport": "forwardemail",
        "api_token_env": "YAS_FE_TOKEN",
        "from_addr": "yas@example.com",
        "to_addrs": ["user@example.com"],
    }
    with respx.mock:
        respx.post("https://api.forwardemail.net/v1/emails").mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        channel = EmailChannel(config)
        result = await channel.send(_msg())
        await channel.aclose()

    assert result.ok is True


def test_email_channel_unknown_transport_raises():
    """Unknown transport value → ValueError."""
    config = {
        "transport": "pigeon",
        "from_addr": "a@b.com",
        "to_addrs": ["c@d.com"],
    }
    with pytest.raises(ValueError, match="pigeon"):
        EmailChannel(config)


def test_email_channel_capabilities():
    """EmailChannel reports email capability."""
    # Use fake_smtp_server is overkill here — just verify without sending.
    # We can't easily construct without a running SMTP so we check the class attr.
    assert hasattr(EmailChannel, "__init__")
    # Verify via a mock config (smtp without tls/auth)
    # We can't start a server synchronously so inspect the capability in the
    # channel_selects_smtp test — but also verify the class has the right set.
    # Instantiate with a port that won't be used for init (smtp init is lazy).
    config = {
        "transport": "smtp",
        "host": "127.0.0.1",
        "port": 1,
        "use_tls": False,
        "from_addr": "a@b.com",
        "to_addrs": ["c@d.com"],
    }
    ch = EmailChannel(config)
    assert NotifierCapability.email in ch.capabilities
    assert ch.name == "email"
