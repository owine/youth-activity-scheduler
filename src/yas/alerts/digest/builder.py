"""Re-export shim -- contents moved to yas.email in Task 4.

Kept so existing callers (``digest_loop.py``, ``digest_preview.py``, and tests)
continue to resolve. New code should import directly from yas.email.
"""
from __future__ import annotations

from yas.email import render_digest_payload as _render_digest_payload
from yas.email.builders import gather_digest_payload
from yas.email.payloads import DigestPayload


def render_digest(payload: DigestPayload, top_line: str) -> tuple[str, str]:
    """Render the digest to plain text and HTML.

    Returns
    -------
    (body_plain, body_html)
    """
    rendered = _render_digest_payload(payload, top_line)
    return rendered.body_plain, rendered.body_html


__all__ = ["DigestPayload", "gather_digest_payload", "render_digest"]
