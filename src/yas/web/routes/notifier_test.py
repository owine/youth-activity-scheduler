"""POST /api/notifiers/{channel}/test — send a fixed test message."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from yas.alerts.channels.base import NotifierMessage
from yas.alerts.channels.email import EmailChannel
from yas.alerts.channels.ntfy import NtfyChannel
from yas.alerts.channels.pushover import PushoverChannel
from yas.db.models import Alert, HouseholdSettings
from yas.db.models._types import AlertType
from yas.db.session import session_scope
from yas.email import render_email
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


def _synthetic_alert(channel: str) -> Alert:
    """Build an un-persisted Alert that carries the test_send context.

    The Alert is never added to the session — it exists only to give
    ``render_email`` a lead carrying ``payload_json={"channel": <channel>}``.
    The ``type`` field is required by the model but unused, since dispatch in
    ``render_email`` goes through the explicit ``kind="test_send"`` literal,
    not the alert's type.
    """
    return Alert(
        type=AlertType.digest.value,
        kid_id=None,
        channels=[],
        scheduled_for=datetime.now(UTC),
        dedup_key=f"test-send-{channel}",
        payload_json={"channel": channel},
        skipped=False,
    )


async def _test_message(
    request: Request, channel: str
) -> NotifierMessage:
    """Render the test_send email through the shared email layer so the user
    sees the branded base chrome -- not a one-line inline string."""
    synthetic = _synthetic_alert(channel)
    async with session_scope(_engine(request)) as s:
        rendered = await render_email(s, "test_send", synthetic, [synthetic])
    # AlertType.new_match (NOT reg_opens_now — would trigger Pushover emergency mode).
    return NotifierMessage(
        kid_id=None,
        alert_type=AlertType.new_match,
        subject=rendered.subject,
        body_plain=rendered.body_plain,
        body_html=rendered.body_html,
    )


@router.post("/{channel}/test", response_model=TestSendOut)
async def test_notifier(channel: str, request: Request) -> TestSendOut:
    if channel not in _CHANNELS:
        raise HTTPException(status_code=404, detail=f"unknown channel: {channel}")
    channel_cls, field = _CHANNELS[channel]
    async with session_scope(_engine(request)) as s:
        hh = (await s.execute(select(HouseholdSettings))).scalars().first()
        config = getattr(hh, field, None) if hh else None
    # Pushover can construct from env-only credentials, so missing
    # config_json is fine — fall through with `{}`. Email and Ntfy
    # require structural config the user must save first; surface that
    # as a clear error rather than letting the constructor's ValueError
    # bubble up.
    if config is None:
        if channel == "pushover":
            config = {}
        else:
            return TestSendOut(
                ok=False,
                detail=f"{channel} not configured — fill in the form and click Save first",
            )
    # Channel constructors raise ValueError if a credential is missing in
    # both the form-stored value and the conventional env var. Surface as
    # ok=false rather than 500.
    settings = request.app.state.yas.settings
    try:
        ch = channel_cls(config, settings)
    except ValueError as exc:
        return TestSendOut(ok=False, detail=f"channel init failed: {exc}")
    message = await _test_message(request, channel)
    result = await ch.send(message)
    return TestSendOut(ok=result.ok, detail=result.detail)
