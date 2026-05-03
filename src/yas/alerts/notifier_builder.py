"""Build channel notifiers from current household config + settings.

Lives outside the worker module so the delivery loop can rebuild them
per tick (so config changes via Settings UI take effect without a
worker restart). Previously the worker built notifiers once at startup
and held them for the lifetime of the process.
"""

from __future__ import annotations

from typing import Any, cast

from yas.alerts.channels.base import Notifier
from yas.alerts.channels.email import EmailChannel
from yas.alerts.channels.ntfy import NtfyChannel
from yas.alerts.channels.pushover import PushoverChannel
from yas.config import Settings
from yas.db.models import HouseholdSettings
from yas.logging import get_logger

log = get_logger("yas.alerts.notifier_builder")


def build_notifiers(
    household: HouseholdSettings | None,
    settings: Settings,
) -> dict[str, Notifier]:
    """Construct one Notifier per configured channel.

    For each channel:
    - Pushover can construct from env-only credentials (config dict is
      everything else), so we attempt with `{}` even when the channel's
      config_json is null. The constructor raises if both DB and env
      lack the credential.
    - Email and Ntfy require structural config the user must save
      (transport, host, base_url, topic, from_addr, etc.) — null
      config_json means the channel is unconfigured and we skip it
      silently rather than constructing a broken channel.
    """
    notifiers: dict[str, Notifier] = {}

    smtp_cfg = getattr(household, "smtp_config_json", None) if household else None
    ntfy_cfg = getattr(household, "ntfy_config_json", None) if household else None
    pushover_cfg = getattr(household, "pushover_config_json", None) if household else None

    if smtp_cfg is not None:
        try:
            notifiers["email"] = cast(Notifier, EmailChannel(smtp_cfg, settings))
        except ValueError as exc:
            log.warning("channel.disabled", channel="email", reason=str(exc))

    if ntfy_cfg is not None:
        try:
            notifiers["ntfy"] = cast(Notifier, NtfyChannel(ntfy_cfg, settings))
        except ValueError as exc:
            log.warning("channel.disabled", channel="ntfy", reason=str(exc))

    # Pushover: try even with null config_json, so users with the
    # conventional YAS_PUSHOVER_* env vars don't have to click Save in
    # the UI just to enable the channel. Empty dict + env credentials
    # is a valid configuration.
    pushover_attempt: dict[str, Any] = pushover_cfg if pushover_cfg is not None else {}
    try:
        notifiers["pushover"] = cast(Notifier, PushoverChannel(pushover_attempt, settings))
    except ValueError as exc:
        # Only log when the user explicitly configured a row but it
        # failed; the empty-and-no-env case is common for fresh installs.
        if pushover_cfg is not None:
            log.warning("channel.disabled", channel="pushover", reason=str(exc))

    return notifiers


_last_logged_keys: tuple[str, ...] | None = None


def log_constructed(notifiers: dict[str, Notifier]) -> None:
    """Log the constructed-channels summary, but only when the set
    changes — otherwise the per-tick rebuild floods the logs."""
    global _last_logged_keys
    keys = tuple(sorted(notifiers.keys()))
    if keys == _last_logged_keys:
        return
    _last_logged_keys = keys
    if keys:
        log.info("channels.constructed", channels=list(keys))
    else:
        log.warning("channels.none_constructed", note="all channels disabled or unconfigured")
