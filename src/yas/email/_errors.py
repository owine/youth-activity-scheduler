"""Errors raised by the outbound-email layer."""

from __future__ import annotations


class EmailRenderError(RuntimeError):
    """Raised when a payload builder or template render cannot produce a useful email."""

    def __init__(self, message: str, *, alert_id: int | None = None) -> None:
        super().__init__(message)
        self.alert_id = alert_id
