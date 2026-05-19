"""Registry completeness: every AlertType plus test_send has a renderer."""
from __future__ import annotations

import pytest

from yas.db.models._types import AlertType
from yas.email.registry import RENDERERS


@pytest.mark.xfail(
    strict=True,
    reason="Renderers wired incrementally across Tasks 5-14; flips to PASS at Task 14.",
)
def test_every_alert_type_has_a_renderer() -> None:
    expected = {at.value for at in AlertType} | {"test_send"}
    actual = {str(k) for k in RENDERERS.keys()}
    assert actual == expected, (
        f"missing: {expected - actual}, extra: {actual - expected}"
    )
