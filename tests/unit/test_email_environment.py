"""Jinja Environment shared by all outbound-email templates."""
from __future__ import annotations

import pytest
from jinja2 import StrictUndefined, UndefinedError

from yas.email.environment import env


def test_uses_strict_undefined() -> None:
    assert env.undefined is StrictUndefined


def test_autoescape_on_for_html() -> None:
    # autoescape is configured by extension; verify by checking the policy fn.
    assert env.autoescape("foo.html.j2") is True
    assert env.autoescape("foo.txt.j2") is False


def test_price_filter_registered() -> None:
    assert env.from_string("{{ 1234 | price }}").render() == "$12.34"


def test_strict_undefined_raises_on_missing_field() -> None:
    tpl = env.from_string("{{ payload.missing }}")
    with pytest.raises(UndefinedError):
        tpl.render(payload=object())
