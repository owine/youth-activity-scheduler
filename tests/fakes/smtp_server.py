"""Thin wrapper over aiosmtpd for in-memory SMTP testing.

Used by EmailChannel SMTP-transport tests so we don't have to mock
aiosmtplib. Spin up the server in a fixture; it records every message."""

from __future__ import annotations

import socket
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
        self._sink.append(
            CapturedMessage(
                from_addr=envelope.mail_from,
                to_addrs=tuple(envelope.rcpt_tos),
                message=cast(EmailMessage, msg),
            )
        )
        return "250 OK"


@dataclass
class FakeSMTPServer:
    host: str
    port: int
    captured: list[CapturedMessage] = field(default_factory=list)


def _free_port() -> int:
    """Allocate a free TCP port on 127.0.0.1 and immediately release it.

    Note: This is intentionally a pre-allocate-and-close pattern (TOCTOU race).
    The idiomatic approach would be Controller(port=0) and reading the bound port
    from controller.server.sockets[0].getsockname()[1] after start(). However,
    aiosmtpd's _trigger_server() calls create_connection() back to (hostname, port)
    during start(), which fails with EADDRNOTAVAIL when port=0 is given (it tries
    to connect to port 0 rather than the OS-assigned port). This is an aiosmtpd
    design limitation that prevents the port=0 idiom. The TOCTOU window is
    negligible in a loopback test context.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@asynccontextmanager
async def fake_smtp_server() -> AsyncIterator[FakeSMTPServer]:
    captured: list[CapturedMessage] = []
    port = _free_port()
    controller = Controller(_Handler(captured), hostname="127.0.0.1", port=port)
    controller.start()
    try:
        yield FakeSMTPServer(
            host=controller.hostname,
            port=port,
            captured=captured,
        )
    finally:
        controller.stop()
