"""Notifier protocol, message + result dataclasses, capability enum."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from yas.db.models._types import AlertType


class NotifierCapability(StrEnum):
    email = "email"
    push = "push"
    push_emergency = "push_emergency"  # retry-until-ack (Pushover priority=2)


@dataclass(frozen=True)
class NotifierMessage:
    kid_id: int | None
    alert_type: AlertType
    subject: str
    body_plain: str
    body_html: str | None = None
    url: str | None = None
    urgent: bool = False


@dataclass(frozen=True)
class SendResult:
    ok: bool
    transient_failure: bool
    detail: str


class Notifier(Protocol):
    name: str
    capabilities: set[NotifierCapability]

    async def send(self, msg: NotifierMessage) -> SendResult: ...
    async def aclose(self) -> None: ...
