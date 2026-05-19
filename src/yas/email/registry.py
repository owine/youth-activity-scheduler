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
