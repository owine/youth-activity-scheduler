"""POST /api/notifiers/{channel}/test — send a fixed test message."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from yas.alerts.channels.base import NotifierMessage
from yas.alerts.channels.email import EmailChannel
from yas.alerts.channels.ntfy import NtfyChannel
from yas.alerts.channels.pushover import PushoverChannel
from yas.db.models import HouseholdSettings
from yas.db.models._types import AlertType
from yas.db.session import session_scope
from yas.web.routes.notifier_test_schemas import TestSendOut

router = APIRouter(prefix="/api/notifiers", tags=["notifiers"])

# Map URL path → (channel class, HouseholdSettings field name)
_CHANNELS: dict[str, tuple[type, str]] = {
    "email": (EmailChannel, "smtp_config_json"),
    "ntfy": (NtfyChannel, "ntfy_config_json"),
    "pushover": (PushoverChannel, "pushover_config_json"),
}


def _engine(req: Request) -> Any:
    return req.app.state.yas.engine


def _test_message(channel: str) -> NotifierMessage:
    # AlertType.new_match (NOT reg_opens_now — would trigger Pushover emergency mode).
    return NotifierMessage(
        kid_id=None,
        alert_type=AlertType.new_match,
        subject="YAS test notification",
        body_plain=f"If you see this, the {channel} channel is working.",
    )


@router.post("/{channel}/test", response_model=TestSendOut)
async def test_notifier(channel: str, request: Request) -> TestSendOut:
    if channel not in _CHANNELS:
        raise HTTPException(status_code=404, detail=f"unknown channel: {channel}")
    channel_cls, field = _CHANNELS[channel]
    async with session_scope(_engine(request)) as s:
        hh = (await s.execute(select(HouseholdSettings))).scalars().first()
        config = getattr(hh, field, None) if hh else None
    if config is None:
        raise HTTPException(status_code=503, detail=f"{channel} not configured")
    # Channel constructors raise ValueError if a credential is missing in
    # both the form-stored value and the conventional env var. Surface as
    # ok=false rather than 500.
    settings = request.app.state.yas.settings
    try:
        ch = channel_cls(config, settings)
    except ValueError as exc:
        return TestSendOut(ok=False, detail=f"channel init failed: {exc}")
    result = await ch.send(_test_message(channel))
    return TestSendOut(ok=result.ok, detail=result.detail)
