"""Delivery orchestrator: send_alert_group + grace-window helper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yas.alerts.channels.base import Notifier, NotifierCapability, NotifierMessage
from yas.alerts.enqueuer import enqueue_push_cap
from yas.alerts.rate_limit import (
    AlertGroup,
    count_pushes_sent_in_last_hour,
    is_in_quiet_hours,
    should_rate_limit_push,
)
from yas.alerts.routing import get_routing
from yas.config import Settings
from yas.db.models import Alert, HouseholdSettings
from yas.db.models._types import AlertType
from yas.logging import get_logger

log = get_logger("yas.alerts.delivery")

# ---------------------------------------------------------------------------
# Retry back-off table (indexed by attempt number; 1-based)
# ---------------------------------------------------------------------------
_RETRY_DELAYS: dict[int, timedelta] = {
    1: timedelta(seconds=60),
    2: timedelta(minutes=5),
    3: timedelta(minutes=30),
}
_MAX_RETRIES = 3  # after attempt 3 → skipped


# ---------------------------------------------------------------------------
# Minimal subject / body renderers (Task 10 will provide rich digest rendering)
# ---------------------------------------------------------------------------


def _render_subject(
    alert_type: str,
    payload: dict[str, Any],
    member_count: int,
) -> str:
    # TODO(Task 10): replace with Jinja template rendering.
    prefix = f"[{member_count}] " if member_count > 1 else ""
    return f"{prefix}{alert_type}"


def _render_body(
    alert_type: str,
    lead_payload: dict[str, Any],
    member_payloads: list[dict[str, Any]],
) -> str:
    # TODO(Task 10): replace with Jinja template rendering.
    lines = [f"Alert: {alert_type}"]
    if len(member_payloads) > 1:
        lines.append(f"Members: {len(member_payloads)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Grace-window filter — extracted so the delivery loop can call it and tests
# can exercise it in isolation.
# ---------------------------------------------------------------------------

_COUNTDOWN_TYPES: frozenset[str] = frozenset(
    {
        AlertType.reg_opens_24h.value,
        AlertType.reg_opens_1h.value,
    }
)


def _apply_grace_window(
    alerts: list[Alert],
    now: datetime,
    grace_s: int,
) -> list[Alert]:
    """Mark past-grace countdown alerts as skipped and return the remainder.

    Modifies the Alert objects in-place for the skipped ones (sets
    ``skipped=True`` and stamps a reason in ``payload_json``) and returns a
    new list containing only the alerts that should still be delivered.

    SQLite stores naive datetimes even for timezone-aware columns; we normalise
    both sides to UTC-naive before comparing.
    """
    grace = timedelta(seconds=grace_s)
    keep: list[Alert] = []
    for a in alerts:
        if a.type not in _COUNTDOWN_TYPES:
            keep.append(a)
            continue
        sched = a.scheduled_for
        # SQLite strips tzinfo — normalise to naive UTC for comparison.
        if sched.tzinfo is not None:
            sched = sched.replace(tzinfo=None)
        now_naive = now.replace(tzinfo=None) if now.tzinfo is not None else now
        if (now_naive - sched) > grace:
            a.skipped = True
            a.payload_json = {**a.payload_json, "_skipped_reason": "past grace"}
            log.info(
                "delivery.grace_window.skip",
                alert_id=a.id,
                alert_type=a.type,
                scheduled_for=a.scheduled_for.isoformat() if a.scheduled_for else None,
            )
        else:
            keep.append(a)
    return keep


# ---------------------------------------------------------------------------
# Core orchestrator
# ---------------------------------------------------------------------------


async def send_alert_group(
    session: AsyncSession,
    group: AlertGroup,
    notifiers: dict[str, Notifier],
    settings: Settings,
    household: HouseholdSettings | None,
) -> None:
    """Deliver one coalesced AlertGroup through all routed channels.

    Outcomes:
    - At least one channel ok  → sent_at + channels list updated on all members.
    - All transient failures   → retry scheduled via back-off table.
    - All permanent failures   → members marked skipped.
    - Routing disabled         → members marked skipped with "routing disabled".
    - Rate-capped              → members marked skipped with "rate capped",
                                  enqueue_push_cap called.
    - Quiet hours (push only)  → channel silently skipped (not retried).
    """
    lead = group.lead
    members: list[Alert] = group.members

    # 1. Routing lookup -------------------------------------------------------
    channels, enabled = await get_routing(session, AlertType(group.alert_type))
    if not enabled:
        _mark_all_skipped(members, "routing disabled")
        log.info("delivery.routing_disabled", alert_type=group.alert_type)
        return

    if not channels:
        log.debug("delivery.no_channels", alert_type=group.alert_type)
        return

    # 2. Build message --------------------------------------------------------
    member_payloads = [a.payload_json for a in members]
    subject = _render_subject(group.alert_type, lead.payload_json, len(members))
    body_plain = _render_body(group.alert_type, lead.payload_json, member_payloads)
    body_html = f"<pre>{body_plain}</pre>"
    msg = NotifierMessage(
        kid_id=group.kid_id,
        alert_type=AlertType(group.alert_type),
        subject=subject,
        body_plain=body_plain,
        body_html=body_html,
        url=lead.payload_json.get("registration_url"),
        urgent=(group.alert_type == AlertType.reg_opens_now.value),
    )

    # 3. Per-channel send ------------------------------------------------------
    now = datetime.now(UTC)

    # Track outcomes per channel
    ok_channel_names: list[str] = []
    any_transient: bool = False
    permanent_errors: dict[str, str] = {}

    # Push cap check (shared across all push channels) -------------------------
    # Global per-kid push budget across ALL configured push notifiers (not just this alert's routing).
    push_channels = [
        name for name, n in notifiers.items() if NotifierCapability.push in n.capabilities
    ]
    push_cap_checked = False

    for channel_name in channels:
        notifier = notifiers.get(channel_name)
        if notifier is None:
            log.warning(
                "delivery.notifier_missing",
                channel=channel_name,
                alert_type=group.alert_type,
            )
            continue

        is_push = NotifierCapability.push in notifier.capabilities

        # Quiet hours check ---------------------------------------------------
        if is_push and group.alert_type != AlertType.reg_opens_now.value:
            qstart = household.quiet_hours_start if household else None
            qend = household.quiet_hours_end if household else None
            if is_in_quiet_hours(now, qstart, qend):
                log.info(
                    "delivery.quiet_hours.suppressed",
                    channel=channel_name,
                    alert_type=group.alert_type,
                )
                continue  # hard suppression — no retry advancement

        # Push rate cap check (run once for the whole group) ------------------
        if is_push and group.kid_id is not None and not push_cap_checked:
            push_cap_checked = True
            count = await count_pushes_sent_in_last_hour(session, group.kid_id, push_channels)
            if should_rate_limit_push(count, settings.alert_max_pushes_per_hour):
                await enqueue_push_cap(
                    session,
                    kid_id=group.kid_id,
                    hour_bucket=now.strftime("%Y-%m-%dT%H"),
                    suppressed_count=len(members),
                )
                _mark_all_skipped(members, "rate capped")
                log.info(
                    "delivery.rate_cap.triggered",
                    kid_id=group.kid_id,
                    count=count,
                    max=settings.alert_max_pushes_per_hour,
                )
                return  # rate cap terminates processing for the entire group

        # Send ----------------------------------------------------------------
        result = await notifier.send(msg)

        if result.ok:
            ok_channel_names.append(notifier.name)
        elif result.transient_failure:
            any_transient = True
            log.warning(
                "delivery.transient_failure",
                channel=channel_name,
                detail=result.detail,
            )
        else:
            # Permanent failure
            permanent_errors[channel_name] = result.detail
            log.error(
                "delivery.permanent_failure",
                channel=channel_name,
                detail=result.detail,
            )
            # Continue to next channel (one channel's permanent failure does not
            # block others from being tried).

    # 4. Apply outcomes -------------------------------------------------------
    if ok_channel_names:
        for a in members:
            a.sent_at = now
            a.channels = list(a.channels or []) + ok_channel_names
        log.info(
            "delivery.sent",
            alert_type=group.alert_type,
            channels=ok_channel_names,
            member_count=len(members),
        )
        if permanent_errors:
            log.warning(
                "delivery.partial_success",
                alert_type=group.alert_type,
                kid_id=group.kid_id,
                ok_channels=ok_channel_names,
                permanent_failures=permanent_errors,
            )
        return

    if any_transient:
        # Apply retry back-off using the max attempt count across all coalesced members.
        current_attempts = max((a.payload_json.get("_attempts", 0) or 0) for a in members)
        new_attempts = current_attempts + 1
        if new_attempts > _MAX_RETRIES:
            detail = f"transient failed after {_MAX_RETRIES} retries: " + "; ".join(
                permanent_errors.values() or ["transient"]
            )
            _mark_all_skipped(members, detail)
        else:
            delay = _RETRY_DELAYS[new_attempts]
            scheduled_for = now + delay
            for a in members:
                a.scheduled_for = scheduled_for
                a.payload_json = {**a.payload_json, "_attempts": new_attempts}
            log.info(
                "delivery.retry_scheduled",
                alert_type=group.alert_type,
                attempt=new_attempts,
                retry_at=scheduled_for.isoformat(),
            )
        return

    if permanent_errors:
        errors_summary = "; ".join(f"{ch}: {msg}" for ch, msg in permanent_errors.items())
        for a in members:
            a.skipped = True
            a.payload_json = {**a.payload_json, "_errors": permanent_errors}
        log.error(
            "delivery.all_channels_failed",
            alert_type=group.alert_type,
            errors=errors_summary,
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _mark_all_skipped(alerts: list[Alert], detail: str) -> None:
    for a in alerts:
        a.skipped = True
        a.payload_json = {**a.payload_json, "_skipped_reason": detail}
