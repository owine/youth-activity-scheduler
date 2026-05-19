"""Outbound email rendering — see docs/superpowers/specs/2026-05-19-outbound-email-template-layer-design.md."""
from __future__ import annotations

from dataclasses import dataclass

from yas.email._errors import EmailRenderError


@dataclass(frozen=True)
class RenderedEmail:
    """A fully-rendered outbound email, ready to hand to a notifier."""

    subject: str
    body_plain: str
    body_html: str


__all__ = ["EmailRenderError", "RenderedEmail"]
