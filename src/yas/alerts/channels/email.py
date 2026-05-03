"""EmailChannel — multi-transport email notifier (SMTP and ForwardEmail)."""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any, ClassVar, Protocol

import aiosmtplib
import httpx

from yas.alerts.channels.base import (
    NotifierCapability,
    NotifierMessage,
    SendResult,
)
from yas.config import Settings

_FORWARDEMAIL_API_URL = "https://api.forwardemail.net/v1/emails"


# ---------------------------------------------------------------------------
# Shared builder
# ---------------------------------------------------------------------------


def _build_email(
    subject: str,
    from_addr: str,
    to_addrs: list[str],
    text: str,
    html: str | None,
) -> EmailMessage:
    """Build a multipart/alternative EmailMessage (or plain-text if no html)."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)
    msg.set_content(text)
    if html is not None:
        msg.add_alternative(html, subtype="html")
    return msg


# ---------------------------------------------------------------------------
# Transport protocol
# ---------------------------------------------------------------------------


class _EmailTransport(Protocol):
    async def send(self, msg: NotifierMessage) -> SendResult: ...
    async def aclose(self) -> None: ...


# ---------------------------------------------------------------------------
# SMTP transport
# ---------------------------------------------------------------------------


class _SMTPTransport:
    def __init__(
        self,
        host: str,
        port: int,
        use_tls: bool,
        from_addr: str,
        to_addrs: list[str],
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._use_tls = use_tls
        self._from_addr = from_addr
        self._to_addrs = to_addrs
        if username is not None and username == "":
            raise ValueError("smtp username must be non-empty if provided")
        self._username = username
        self._password = password if password else None

    async def send(self, msg: NotifierMessage) -> SendResult:
        email = _build_email(
            subject=msg.subject,
            from_addr=self._from_addr,
            to_addrs=self._to_addrs,
            text=msg.body_plain,
            html=msg.body_html,
        )
        try:
            errors, response = await aiosmtplib.send(
                email,
                hostname=self._host,
                port=self._port,
                start_tls=self._use_tls,
                username=self._username,
                password=self._password,
            )
            if errors:
                return SendResult(
                    ok=False,
                    transient_failure=False,
                    detail=f"partial refusal: {errors}",
                )
            code_str = response.split()[0] if response else "250"
            return SendResult(ok=True, transient_failure=False, detail=f"smtp {code_str}")
        except aiosmtplib.SMTPResponseException as exc:
            # RFC 5321: 4xx → transient (retry later), 5xx → non-transient (permanent)
            transient = exc.code < 500
            return SendResult(
                ok=False,
                transient_failure=transient,
                detail=f"smtp {exc.code} {exc.message}",
            )
        except aiosmtplib.SMTPConnectError as exc:
            return SendResult(
                ok=False,
                transient_failure=True,
                detail=f"connection refused: {exc}",
            )
        except TimeoutError as exc:
            return SendResult(
                ok=False,
                transient_failure=True,
                detail=f"timeout: {exc}",
            )
        except aiosmtplib.SMTPException as exc:
            # Covers SMTPRecipientsRefused, SMTPServerDisconnected, and any other
            # aiosmtplib exception not already handled. Treat as transient — the
            # delivery worker will retry; if it's truly permanent (e.g. all recipients
            # invalid), the retries will exhaust and the alert gets a failed-digest note.
            return SendResult(ok=False, transient_failure=True, detail=f"smtp error: {exc}")

    async def aclose(self) -> None:
        pass


# ---------------------------------------------------------------------------
# ForwardEmail transport
# ---------------------------------------------------------------------------


class _ForwardEmailTransport:
    def __init__(
        self,
        api_token: str,
        from_addr: str,
        to_addrs: list[str],
    ) -> None:
        if not api_token:
            raise ValueError(
                "channel disabled: forwardemail api token not set "
                "(form override or YAS_FORWARDEMAIL_API_TOKEN env var)"
            )
        self._token = api_token
        self._from_addr = from_addr
        self._to_addrs = to_addrs
        self._client = httpx.AsyncClient()

    async def send(self, msg: NotifierMessage) -> SendResult:
        data: dict[str, str] = {
            "from": self._from_addr,
            "to": ", ".join(self._to_addrs),
            "subject": msg.subject,
            "text": msg.body_plain,
        }
        if msg.body_html is not None:
            data["html"] = msg.body_html

        try:
            response = await self._client.post(
                _FORWARDEMAIL_API_URL,
                data=data,
                auth=(self._token, ""),
            )
        except httpx.TimeoutException as exc:
            return SendResult(
                ok=False,
                transient_failure=True,
                detail=f"timeout: {exc}",
            )
        except httpx.TransportError as exc:
            return SendResult(
                ok=False,
                transient_failure=True,
                detail=f"network error: {exc}",
            )

        code = response.status_code
        if code < 400:
            return SendResult(ok=True, transient_failure=False, detail=f"http {code}")
        if code == 429 or code >= 500:
            return SendResult(
                ok=False,
                transient_failure=True,
                detail=f"http {code}",
            )
        return SendResult(ok=False, transient_failure=False, detail=f"http {code}")

    async def aclose(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# EmailChannel
# ---------------------------------------------------------------------------


class EmailChannel:
    name: str = "email"
    capabilities: ClassVar[set[NotifierCapability]] = {NotifierCapability.email}

    def __init__(self, config: dict[str, Any], settings: Settings) -> None:
        transport_name = config.get("transport")
        from_addr = str(config["from_addr"])
        to_addrs = [str(a) for a in config["to_addrs"]]

        if transport_name == "smtp":
            # Resolution: form-stored value → conventional env var. SMTP
            # password is optional (some servers use IP-based auth).
            password = config.get("password_value") or settings.smtp_password
            self._transport: _EmailTransport = _SMTPTransport(
                host=str(config["host"]),
                port=int(config["port"]),
                use_tls=bool(config.get("use_tls", True)),
                from_addr=from_addr,
                to_addrs=to_addrs,
                username=str(config["username"]) if "username" in config else None,
                password=password if password else None,
            )
        elif transport_name == "forwardemail":
            api_token = config.get("api_token_value") or settings.forwardemail_api_token or ""
            self._transport = _ForwardEmailTransport(
                api_token=api_token,
                from_addr=from_addr,
                to_addrs=to_addrs,
            )
        else:
            raise ValueError(
                f"EmailChannel: unknown transport {transport_name!r}; "
                "expected 'smtp' or 'forwardemail'"
            )

    async def send(self, msg: NotifierMessage) -> SendResult:
        return await self._transport.send(msg)

    async def aclose(self) -> None:
        await self._transport.aclose()
