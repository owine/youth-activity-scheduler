"""NtfyChannel — push notifications via a self-hosted or public ntfy server."""

from __future__ import annotations

import os
from typing import Any, ClassVar

import httpx

from yas.alerts.channels.base import (
    NotifierCapability,
    NotifierMessage,
    SendResult,
)


class NtfyChannel:
    name: str = "ntfy"
    capabilities: ClassVar[set[NotifierCapability]] = {NotifierCapability.push}

    def __init__(self, config: dict[str, Any]) -> None:
        self._base_url = str(config["base_url"]).rstrip("/")
        self._topic = str(config["topic"])

        auth_token_env: str | None = config.get("auth_token_env")
        if auth_token_env is not None:
            token = os.environ.get(auth_token_env)
            if token is None:
                raise ValueError(f"channel disabled: missing env var {auth_token_env}")
            if token == "":
                raise ValueError(f"channel disabled: env var {auth_token_env} is set but empty")
            self._token: str | None = token
        else:
            self._token = None

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
