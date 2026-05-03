"""PushoverChannel — push notifications via the Pushover API (supports emergency priority)."""

from __future__ import annotations

import json
from typing import Any, ClassVar

import httpx

from yas.alerts.channels.base import (
    NotifierCapability,
    NotifierMessage,
    SendResult,
)
from yas.config import Settings
from yas.db.models._types import AlertType

_PUSHOVER_URL = "https://api.pushover.net/1/messages.json"


class PushoverChannel:
    name: str = "pushover"
    capabilities: ClassVar[set[NotifierCapability]] = {
        NotifierCapability.push,
        NotifierCapability.push_emergency,
    }

    def __init__(self, config: dict[str, Any], settings: Settings) -> None:
        # Resolution: form-stored value → conventional env var. Form value
        # wins when both are set so the user can override env in the UI.
        user_key = config.get("user_key_value") or settings.pushover_user_key
        if not user_key:
            raise ValueError(
                "channel disabled: pushover user key not set "
                "(form override or YAS_PUSHOVER_USER_KEY env var)"
            )
        self._user_key = user_key

        app_token = config.get("app_token_value") or settings.pushover_app_token
        if not app_token:
            raise ValueError(
                "channel disabled: pushover app token not set "
                "(form override or YAS_PUSHOVER_APP_TOKEN env var)"
            )
        self._app_token = app_token

        devices: list[str] = list(config.get("devices") or [])
        self._devices = devices

        self._emergency_retry_s = int(config.get("emergency_retry_s", 60))
        self._emergency_expire_s = int(config.get("emergency_expire_s", 3600))

        self._client = httpx.AsyncClient()

    async def send(self, msg: NotifierMessage) -> SendResult:
        is_emergency = msg.alert_type == AlertType.reg_opens_now

        data: dict[str, str] = {
            "token": self._app_token,
            "user": self._user_key,
            "title": msg.subject,
            "message": msg.body_plain,
            "priority": "2" if is_emergency else "0",
        }

        if is_emergency:
            data["retry"] = str(self._emergency_retry_s)
            data["expire"] = str(self._emergency_expire_s)

        if msg.url is not None:
            data["url"] = msg.url
            data["url_title"] = msg.subject

        if self._devices:
            data["device"] = ",".join(self._devices)

        try:
            response = await self._client.post(_PUSHOVER_URL, data=data)
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
        if code == 429 or code >= 500:
            return SendResult(ok=False, transient_failure=True, detail=f"http {code}")

        try:
            body = response.json()
        except json.JSONDecodeError:
            body = {}

        if code < 400 and body.get("status") == 1:
            return SendResult(ok=True, transient_failure=False, detail=f"http {code}")

        # Pushover returns status:0 for permanent errors like invalid tokens even
        # on HTTP 200 (e.g. {"status":0, "errors":["application token is invalid"]}).
        # Classify as non-transient so retries don't exhaust on a bad config.
        errors = body.get("errors", [])
        detail = (
            f"http {code} errors={errors}" if errors else f"http {code} status={body.get('status')}"
        )
        return SendResult(ok=False, transient_failure=False, detail=detail)

    async def aclose(self) -> None:
        await self._client.aclose()
