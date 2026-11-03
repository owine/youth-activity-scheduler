"""Delivery bookkeeping keys in ``Alert.payload_json``, and their reader.

``alerts/delivery.py`` writes these; the digest builder reads them. They live in
this dependency-free module so both sides share one definition (#641) without
``yas.email`` importing the delivery code that imports it.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# Why delivery retired the row, as a human-readable string.
SKIPPED_REASON_KEY = "_skipped_reason"
# Set when a skip is a failure: someone was meant to receive the alert and didn't.
FAILED_KEY = "_failed"


def failure_detail(payload: Mapping[str, Any]) -> str | None:
    """Why a skipped alert failed to deliver, or None if it was skipped on purpose."""
    if not payload.get(FAILED_KEY):
        return None
    reason = payload.get(SKIPPED_REASON_KEY)
    return str(reason) if reason else "unknown error"
