"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture
def sentry_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[dict[str, Any]]]:
    """Initialise Sentry through the production init path with an in-memory transport.

    Yields the list events land in. Imported lazily so the rest of the suite
    doesn't depend on the observability module.
    """
    from tests.fakes.sentry import TEST_DSN, CapturingTransport, reset_sentry
    from yas.config import Settings
    from yas.observability import init_sentry

    monkeypatch.setenv("YAS_ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("SENTRY_DSN", TEST_DSN)
    transport = CapturingTransport()
    assert init_sentry(Settings(_env_file=None), transport=transport)  # type: ignore[call-arg]
    try:
        yield transport.events
    finally:
        reset_sentry()
