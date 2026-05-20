"""Email type to renderer registry.

A single explicit dict is the type-to-renderer mapping for kinds rendered
through ``render_email``. Membership is asserted by
``tests/unit/test_email_registry.py``; a missing entry is a CI failure, not a
runtime fallback.

Note on the digest: ``AlertType.digest`` is deliberately NOT in this registry.
Digest payloads are assembled outside the Alert lifecycle by
``yas.worker.digest_loop`` and rendered via ``render_digest_payload``. The
completeness test special-cases digest accordingly.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from yas.db.models._types import AlertType
from yas.email.builders import (
    build_new_match,
    build_reg_opens_1h,
    build_reg_opens_24h,
    build_reg_opens_now,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from yas.db.models import Alert

EmailKind = AlertType | Literal["test_send"]


@dataclass(frozen=True)
class TypeRenderer:
    """How one outbound email kind is built and rendered."""

    build: Callable[[AsyncSession, Alert, list[Alert]], Awaitable[object]]
    html_template: str
    txt_template: str


# Populated incrementally across Tasks 5-14. Task 1 ships it empty so the
# completeness test is initially red and the layer can't be silently used.
RENDERERS: dict[EmailKind, TypeRenderer] = {
    AlertType.new_match: TypeRenderer(
        build=build_new_match,
        html_template="new_match.html.j2",
        txt_template="new_match.txt.j2",
    ),
    AlertType.reg_opens_now: TypeRenderer(
        build=build_reg_opens_now,
        html_template="reg_opens_now.html.j2",
        txt_template="reg_opens_now.txt.j2",
    ),
    AlertType.reg_opens_1h: TypeRenderer(
        build=build_reg_opens_1h,
        html_template="reg_opens_1h.html.j2",
        txt_template="reg_opens_1h.txt.j2",
    ),
    AlertType.reg_opens_24h: TypeRenderer(
        build=build_reg_opens_24h,
        html_template="reg_opens_24h.html.j2",
        txt_template="reg_opens_24h.txt.j2",
    ),
}
