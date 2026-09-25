"""In-memory Sentry transport: capture events instead of sending them."""

from __future__ import annotations

from typing import Any

import sentry_sdk
from sentry_sdk.envelope import Envelope
from sentry_sdk.transport import Transport

TEST_DSN = "https://public@glitchtip.example/1"


class CapturingTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict[str, Any]] = []

    def capture_envelope(self, envelope: Envelope) -> None:
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


def reset_sentry() -> None:
    """Drop the active client so later tests run with Sentry uninitialised."""
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)
