"""Registry completeness: every email-deliverable AlertType plus test_send has a renderer.

The digest is deliberately excluded from RENDERERS -- it bypasses the registry
path entirely and is rendered via ``yas.email.render_digest_payload``. See the
note in ``yas.email.registry`` for the rationale.
"""
from __future__ import annotations

from yas.db.models._types import AlertType
from yas.email.registry import RENDERERS

# Digest is rendered via a separate code path; see yas.email.render_digest_payload.
_REGISTRY_EXCLUDED: frozenset[str] = frozenset({AlertType.digest.value})


def test_every_alert_type_has_a_renderer() -> None:
    """The registry is complete: every email-deliverable AlertType (digest
    excluded) plus the ``test_send`` literal has a renderer.

    Task 14 completed the registry; this is the live completeness guarantee.
    Adding a new AlertType without a corresponding RENDERERS entry fails CI.
    """
    expected = ({at.value for at in AlertType} - _REGISTRY_EXCLUDED) | {"test_send"}
    actual = {str(k) for k in RENDERERS}
    assert actual == expected, (
        f"missing: {expected - actual}, extra: {actual - expected}"
    )


def test_digest_is_not_in_registry() -> None:
    """Digest deliberately bypasses the registry; render_digest_payload handles it."""
    assert AlertType.digest not in RENDERERS
    assert "digest" not in RENDERERS

    from yas.email import render_digest_payload  # importable + callable
    assert callable(render_digest_payload)


def test_every_concrete_txt_template_overrides_subject_block() -> None:
    """Each kind's .txt.j2 must override {% block subject %}.

    The base.txt.j2 default subject is deliberately payload-free (``YAS
    Update``); a kind that fails to override would silently fall back to this
    generic line. This test catches that drift the moment a new template lands.
    """
    from pathlib import Path

    templates_dir = Path("src/yas/email/templates")
    txt_templates = sorted(templates_dir.glob("*.txt.j2"))
    # Exclude base.txt.j2 itself.
    txt_templates = [p for p in txt_templates if p.name != "base.txt.j2"]

    assert txt_templates, "no concrete .txt.j2 templates found"
    missing = [p.name for p in txt_templates if "{% block subject %}" not in p.read_text()]
    assert not missing, f"these .txt.j2 templates do not override block subject: {missing}"
