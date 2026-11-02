"""Delivery orchestrator: send_alert_group + grace-window helper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import sentry_sdk
from sqlalchemy.ext.asyncio import AsyncSession

from yas.alerts.channels.base import Notifier, NotifierCapability, NotifierMessage
from yas.alerts.enqueuer import enqueue_push_cap
from yas.alerts.outcomes import FAILED_KEY, SKIPPED_REASON_KEY
from yas.alerts.rate_limit import (
    AlertGroup,
    count_pushes_sent_in_last_hour,
    is_in_quiet_hours,
    should_rate_limit_push,
)
from yas.alerts.routing import ROUTABLE_CHANNELS, get_routing, resolve_channels
from yas.config import Settings
from yas.db.models import Alert, HouseholdSettings
from yas.db.models._types import AlertType
from yas.email import EmailRenderError, render_email
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
# How long to hold a group whose routed channels are real but have no notifier.
_NO_NOTIFIER_DEFER = timedelta(hours=1)


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
    - No routed channel has a notifier → deferred an hour if any is a known
                                  channel, else members marked skipped.
    - Rate-capped              → push channels skipped and enqueue_push_cap
                                  called; other channels still send. Members
                                  are marked skipped "rate capped" only when
                                  push was all they routed to.
    - Quiet hours (push only)  → channel silently skipped (not retried).
    """
    lead = group.lead
    members: list[Alert] = group.members

    # 1. Routing lookup -------------------------------------------------------
    routed, enabled = await get_routing(session, AlertType(group.alert_type))
    channels = resolve_channels(routed, notifiers, AlertType(group.alert_type))
    if not enabled:
        _mark_all_skipped(members, "routing disabled")
        log.info("delivery.routing_disabled", alert_type=group.alert_type)
        return

    if not channels:
        # Digest-only types (site_stagnant, schedule_posted, no_matches_for_kid)
        # route here by design. Returning without touching the rows left them
        # unsent and unskipped, so the due-query re-selected them on every tick
        # forever. Retire them instead: `skipped` drops them from delivery while
        # leaving them visible in the inbox, which filters on `closed_at`.
        # The digest itself is unaffected — build_digest re-derives its content
        # from live state rather than reading these rows.
        _mark_all_skipped(members, "digest only")
        log.debug("delivery.no_channels", alert_type=group.alert_type)
        return

    if not any(name in notifiers for name in channels):
        # No routed channel has a notifier. The send loop would skip each one and
        # leave the rows unsent and unskipped, so the due query re-selected and
        # re-rendered them every tick. Routing setup, not a failure, so no
        # GlitchTip event either way.
        if any(name in ROUTABLE_CHANNELS for name in channels):
            # A real channel (or the "push" alias) that isn't configured yet,
            # or whose notifier failed to build this tick: hold the group and
            # deliver once it exists. Skipping would lose it for good, since a
            # skipped match alert counts as alerted.
            later = datetime.now(UTC) + _NO_NOTIFIER_DEFER
            for a in members:
                a.scheduled_for = later
            log.info(
                "delivery.no_notifier_deferred",
                alert_type=group.alert_type,
                channels=list(channels),
            )
            return
        # Only names no notifier can exist under. The routing API rejects
        # these, so this is a row written some other way.
        _mark_all_skipped(members, f"no notifier for {', '.join(channels)}", failed=True)
        log.warning("delivery.no_notifier", alert_type=group.alert_type, channels=list(channels))
        return

    # 2. Build message --------------------------------------------------------
    # Digest is special: yas.worker.digest_loop pre-renders subject/body_plain/
    # body_html into the Alert.payload_json BEFORE enqueueing (because it
    # assembles its own DigestPayload outside the Alert lifecycle and calls
    # render_digest_payload directly). render_email has no renderer registered
    # for AlertType.digest by design, so we pull the pre-rendered values out
    # of payload_json here instead of going through the registry.
    if group.alert_type == AlertType.digest.value:
        pj = lead.payload_json or {}
        subject = pj.get("subject") or ""
        body_plain = pj.get("body_plain") or ""
        body_html = pj.get("body_html") or ""
        if not subject or not body_plain or not body_html:
            log.warning(
                "delivery.digest_missing_prerender",
                alert_id=lead.id,
            )
            _mark_all_skipped(members, "digest missing pre-rendered subject/body", failed=True)
            return
        msg = NotifierMessage(
            kid_id=group.kid_id,
            alert_type=AlertType(group.alert_type),
            subject=subject,
            body_plain=body_plain,
            body_html=body_html,
            url=lead.payload_json.get("registration_url"),
            urgent=False,
        )
    else:
        try:
            rendered = await render_email(session, AlertType(group.alert_type), lead, members)
        except EmailRenderError as exc:
            log.warning(
                "email.render_failed",
                alert_id=lead.id,
                alert_type=group.alert_type,
                reason=str(exc),
            )
            _mark_all_skipped(members, f"render failed: {exc}", failed=True)
            return

        msg = NotifierMessage(
            kid_id=group.kid_id,
            alert_type=AlertType(group.alert_type),
            subject=rendered.subject,
            body_plain=rendered.body_plain,
            body_html=rendered.body_html,
            url=rendered.url or lead.payload_json.get("registration_url"),
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
    # The push_cap notice is what the cap produces, so the cap can't hold it
    # back: it is enqueued while the kid is over budget and would otherwise
    # suppress itself on every attempt.
    push_cap_checked = group.alert_type == AlertType.push_cap.value
    push_capped = False

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
        # The cap holds back push only. Email is uncapped (spec §3.7), so an
        # alert routed to both still goes out by email.
        if is_push and group.kid_id is not None and not push_cap_checked:
            push_cap_checked = True
            count = await count_pushes_sent_in_last_hour(session, group.kid_id, push_channels)
            if should_rate_limit_push(count, settings.alert_max_pushes_per_hour):
                push_capped = True
                await enqueue_push_cap(
                    session,
                    kid_id=group.kid_id,
                    hour_bucket=now.strftime("%Y-%m-%dT%H"),
                    suppressed_count=len(members),
                )
                log.info(
                    "delivery.rate_cap.triggered",
                    kid_id=group.kid_id,
                    count=count,
                    max=settings.alert_max_pushes_per_hour,
                )
        if is_push and push_capped:
            continue

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
            # Warning, not error: usually a channel config problem (bad token,
            # SMTP auth). One issue per channel rather than one per alert.
            sentry_sdk.capture_message(
                "Alert channel failed permanently",
                level="warning",
                fingerprint=["delivery.permanent_failure", channel_name],
                tags={"channel": channel_name, "alert_type": group.alert_type},
                extras={"detail": result.detail},
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
            _mark_all_skipped(members, detail, failed=True)
            # This is the only path that discards an alert the user was meant to
            # receive, so it is the one that must be loud. Without it the last
            # trace is a warning-level transient_failure indistinguishable from
            # the retryable attempts before it.
            log.error(
                "delivery.gave_up",
                alert_type=group.alert_type,
                alert_ids=[a.id for a in members],
                attempts=current_attempts,
                detail=detail,
            )
            sentry_sdk.capture_message(
                "Alert dropped after exhausting retries",
                level="error",
                fingerprint=["delivery.gave_up", group.alert_type],
                tags={"alert_type": group.alert_type},
                extras={"alert_ids": [a.id for a in members], "detail": detail},
            )
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
            a.payload_json = {
                **a.payload_json,
                "_errors": permanent_errors,
                SKIPPED_REASON_KEY: errors_summary,
                FAILED_KEY: True,
            }
        log.error(
            "delivery.all_channels_failed",
            alert_type=group.alert_type,
            errors=errors_summary,
        )
        sentry_sdk.capture_message(
            "Alert dropped: every channel failed permanently",
            level="error",
            fingerprint=["delivery.all_channels_failed", group.alert_type],
            tags={"alert_type": group.alert_type},
            extras={"errors": permanent_errors},
        )
        return

    if push_capped:
        # Push was all this group routed to, and the cap held it back. The
        # push_cap notice enqueued above stands in for it.
        _mark_all_skipped(members, "rate capped")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _mark_all_skipped(alerts: list[Alert], detail: str, *, failed: bool = False) -> None:
    """Retire ``alerts`` with ``detail`` as the reason.

    ``failed`` marks an alert someone was meant to receive and didn't: a render
    error, exhausted retries, an unroutable channel. The digest lists those under
    delivery issues. Deliberate skips (routing disabled, digest-only, rate cap,
    past grace) leave it unset.
    """
    for a in alerts:
        a.skipped = True
        extra: dict[str, Any] = {SKIPPED_REASON_KEY: detail}
        if failed:
            extra[FAILED_KEY] = True
        a.payload_json = {**a.payload_json, **extra}
