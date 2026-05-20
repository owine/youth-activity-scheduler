"""End-to-end render goldens -- every kind must produce a stable subject/txt/html."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.golden._scenarios import seed_new_match, seed_reg_opens_1h, seed_reg_opens_now
from yas.db.base import Base
from yas.db.models import Alert
from yas.db.models._types import AlertType
from yas.db.session import create_engine_for, session_scope
from yas.email import render_email
from yas.email.registry import EmailKind

_GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "email"

# Type for a scenario seeder.
Scenario = Callable[[AsyncSession], Awaitable[tuple[Alert, list[Alert]]]]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,seed",
    [
        (AlertType.new_match, seed_new_match),
        (AlertType.reg_opens_now, seed_reg_opens_now),
        (AlertType.reg_opens_1h, seed_reg_opens_1h),
        # Tasks 8-14 append more entries here.
    ],
    ids=lambda v: getattr(v, "value", v.__name__ if callable(v) else str(v)),
)
async def test_render_golden(kind: EmailKind, seed: Scenario, tmp_path: Any) -> None:
    eng = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/g.db")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with session_scope(eng) as s:
        lead, members = await seed(s)
        rendered = await render_email(s, kind, lead, members)

    name = kind.value if hasattr(kind, "value") else str(kind)
    expected_subject = (_GOLDEN_DIR / f"{name}.subject").read_text().rstrip("\n")
    expected_txt = (_GOLDEN_DIR / f"{name}.txt").read_text()
    expected_html = (_GOLDEN_DIR / f"{name}.html").read_text()

    assert rendered.subject == expected_subject, f"subject diverges for {name}"
    assert rendered.body_plain == expected_txt, f"text diverges for {name}"
    assert rendered.body_html == expected_html, f"html diverges for {name}"
