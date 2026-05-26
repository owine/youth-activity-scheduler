"""Outbound email rendering -- see docs/superpowers/specs/2026-05-19-outbound-email-template-layer-design.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Alert
from yas.email._errors import EmailRenderError
from yas.email.environment import env
from yas.email.payloads import DigestPayload
from yas.email.registry import RENDERERS, EmailKind

# Digest is rendered through render_digest_payload (bypassing the Alert-driven
# registry path); these are the only hard-coded template names in the layer.
_DIGEST_HTML_TEMPLATE = "digest.html.j2"
_DIGEST_TXT_TEMPLATE = "digest.txt.j2"


@dataclass(frozen=True)
class RenderedEmail:
    """A fully-rendered outbound email, ready to hand to a notifier."""

    subject: str
    body_plain: str
    body_html: str


def _render_pair(
    html_template: str,
    txt_template: str,
    *,
    payload: Any,
    today: date,
    **extras: Any,
) -> RenderedEmail:
    """Render one kind's two templates and pull the subject out of the .txt block.

    The render context is always ``{"payload": payload, "today": today, **extras}`` —
    callers pass ``payload`` as a frozen dataclass, ``today`` as the reference
    date for relative date formatting (``rel_date`` filter), and any additional
    well-known keys (e.g. ``top_line`` for the digest) as keyword arguments.
    Threading ``today`` explicitly keeps rendered output deterministic: it
    reflects what was true when the alert was scheduled or the digest assembled,
    not whenever the template happens to render.
    """
    ctx: dict[str, Any] = {"payload": payload, "today": today, **extras}
    txt_tpl = env.get_template(txt_template)
    html_tpl = env.get_template(html_template)
    # Subject lives in {% block subject %} in the .txt template.
    subject = "".join(txt_tpl.blocks["subject"](txt_tpl.new_context(ctx))).strip()
    # Email subject headers must be a single line. A subject block that renders
    # with an embedded newline (typically from a multi-line ``{% block subject %}``
    # body) would produce an RFC-violating header. Fail loud here rather than
    # let the SMTP/HTTP transport see it.
    if "\n" in subject or "\r" in subject:
        raise EmailRenderError(f"subject block rendered with embedded newline: {subject!r}")
    body_plain = txt_tpl.render(ctx)
    body_html = html_tpl.render(ctx)
    return RenderedEmail(subject=subject, body_plain=body_plain, body_html=body_html)


async def render_email(
    session: AsyncSession,
    kind: EmailKind,
    lead: Alert,
    members: list[Alert],
) -> RenderedEmail:
    """Render one outbound email by looking up its TypeRenderer."""
    try:
        renderer = RENDERERS[kind]
    except KeyError as exc:
        raise EmailRenderError(
            f"no renderer registered for {kind!r}",
            alert_id=lead.id if lead else None,
        ) from exc
    payload = await renderer.build(session, lead, members)
    today = lead.scheduled_for.astimezone(UTC).date()
    return _render_pair(renderer.html_template, renderer.txt_template, payload=payload, today=today)


def render_digest_payload(payload: DigestPayload, top_line: str) -> RenderedEmail:
    """Synchronous render for the digest path.

    The digest assembles its own payload outside the Alert lifecycle (in
    yas.worker.digest_loop), so it bypasses ``render_email``, the registry, and
    the ``TypeRenderer.build`` callable. Template names are hard-coded here
    rather than registered as a stub TypeRenderer.
    """
    return _render_pair(
        _DIGEST_HTML_TEMPLATE,
        _DIGEST_TXT_TEMPLATE,
        payload=payload,
        today=payload.for_date,
        top_line=top_line,
    )


__all__ = [
    "EmailRenderError",
    "RenderedEmail",
    "render_digest_payload",
    "render_email",
]
