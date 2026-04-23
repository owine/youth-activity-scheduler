"""Thin wrapper over aiosmtpd for in-memory SMTP testing.

Used by EmailChannel SMTP-transport tests so we don't have to mock
aiosmtplib. Spin up the server in a fixture; it records every message."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from email.message import EmailMessage, Message
from email.parser import BytesParser
from email.policy import default as default_policy
from typing import cast

from aiosmtpd.controller import Controller


@dataclass
class CapturedMessage:
    from_addr: str
    to_addrs: tuple[str, ...]
    message: EmailMessage


class _Handler:
    def __init__(self, sink: list[CapturedMessage]):
        self._sink = sink

    async def handle_DATA(self, server, session, envelope):
        msg: Message = BytesParser(policy=default_policy).parsebytes(envelope.content)
        self._sink.append(CapturedMessage(
            from_addr=envelope.mail_from,
            to_addrs=tuple(envelope.rcpt_tos),
            message=cast(EmailMessage, msg),
        ))
        return "250 OK"


@dataclass
class FakeSMTPServer:
    host: str
    port: int
    captured: list[CapturedMessage] = field(default_factory=list)


@asynccontextmanager
async def fake_smtp_server() -> AsyncIterator[FakeSMTPServer]:
    captured: list[CapturedMessage] = []
    controller = Controller(_Handler(captured), hostname="127.0.0.1", port=0)
    controller.start()
    try:
        yield FakeSMTPServer(
            host=controller.hostname,
            port=controller.server.sockets[0].getsockname()[1],
            captured=captured,
        )
    finally:
        controller.stop()
