"""Email type → renderer registry.

A single explicit dict is the type-to-renderer mapping. Membership is
asserted by tests/unit/test_email_registry.py - a missing entry is a CI
failure, not a runtime fallback.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Alert
from yas.db.models._types import AlertType

EmailKind = AlertType | Literal["test_send"]


@dataclass(frozen=True)
class TypeRenderer:
    """How one outbound email kind is built and rendered."""

    build: Callable[[AsyncSession, Alert, list[Alert]], Awaitable[object]]
    html_template: str
    txt_template: str


# Populated incrementally across Tasks 5-14. Task 1 ships it empty so the
# completeness test is initially red and the layer can't be silently used.
RENDERERS: dict[EmailKind, TypeRenderer] = {}


# ---- Digest registration (Task 4) -----------------------------------------
# The digest is special: its payload is assembled outside the Alert lifecycle
# by yas.worker.digest_loop, so render_email's TypeRenderer.build is never
# called for it. We register a stub that raises if reached -- callers must use
# render_digest_payload instead.
from yas.email._errors import EmailRenderError  # noqa: E402


async def _build_digest_from_alert(
    session: AsyncSession, lead: Alert, members: list[Alert]
) -> object:
    raise EmailRenderError(
        "digest is rendered via render_digest_payload from worker/digest_loop.py, "
        "not via render_email; this branch should not be reached"
    )


RENDERERS[AlertType.digest] = TypeRenderer(
    build=_build_digest_from_alert,
    html_template="digest.html.j2",
    txt_template="digest.txt.j2",
)
