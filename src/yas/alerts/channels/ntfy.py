"""NtfyChannel — push notifications via a self-hosted or public ntfy server."""

from __future__ import annotations

from typing import Any, ClassVar

import httpx

from yas.alerts.channels.base import (
    NotifierCapability,
    NotifierMessage,
    SendResult,
)
from yas.config import Settings


class NtfyChannel:
    name: str = "ntfy"
    capabilities: ClassVar[set[NotifierCapability]] = {NotifierCapability.push}

    def __init__(self, config: dict[str, Any], settings: Settings) -> None:
        self._base_url = str(config["base_url"]).rstrip("/")
        self._topic = str(config["topic"])

        # ntfy auth is optional. Resolution: form-stored value → conventional
        # env var → unauthenticated. Treat empty form value as "use env".
        token: str | None = config.get("auth_token_value") or settings.ntfy_auth_token or None
        self._token = token if token else None

        self._client = httpx.AsyncClient()

    async def send(self, msg: NotifierMessage) -> SendResult:
        url = f"{self._base_url}/{self._topic}"

        headers: dict[str, str] = {
            "Title": msg.subject,
        }
        if msg.urgent:
            headers["Priority"] = "high"
        if msg.url is not None:
            headers["Click"] = msg.url
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"

        try:
            response = await self._client.post(
                url,
                content=msg.body_plain.encode(),
                headers=headers,
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
            return SendResult(ok=False, transient_failure=True, detail=f"http {code}")
        return SendResult(ok=False, transient_failure=False, detail=f"http {code}")

    async def aclose(self) -> None:
        await self._client.aclose()
