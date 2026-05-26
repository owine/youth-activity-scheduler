"""Unit tests for the internal _render_pair helper and its guards.

Covers behavior that the per-kind golden tests don't exercise directly:
the subject-newline guard and the macro score=None tolerance.
"""

from __future__ import annotations

from datetime import date

import pytest

from yas.email import EmailRenderError, _render_pair
from yas.email.environment import env


def test_subject_with_embedded_newline_raises(tmp_path, monkeypatch) -> None:
    """A subject block that renders multi-line must raise, not emit a bad header."""
    # Register a throwaway template whose subject block spans two lines.
    bad_txt = env.from_string(
        "{% block subject %}line one\nline two{% endblock %}{% block body %}b{% endblock %}"
    )
    bad_html = env.from_string("ok")

    def fake_get_template(name: str):
        return bad_txt if name.endswith(".txt.j2") else bad_html

    monkeypatch.setattr(env, "get_template", fake_get_template)

    with pytest.raises(EmailRenderError, match="embedded newline"):
        _render_pair("x.html.j2", "x.txt.j2", payload=object(), today=date(2026, 5, 19))


def test_render_pair_passes_extras_into_context(monkeypatch) -> None:
    """Keyword extras land in the render context alongside payload."""
    txt = env.from_string(
        "{% block subject %}{{ top_line }}{% endblock %}{% block body %}{{ top_line }}{% endblock %}"
    )
    html = env.from_string("{{ top_line }}")
    monkeypatch.setattr(env, "get_template", lambda name: txt if name.endswith(".txt.j2") else html)

    rendered = _render_pair(
        "x.html.j2", "x.txt.j2", payload=object(), today=date(2026, 5, 19), top_line="Hello there"
    )
    assert rendered.subject == "Hello there"
    assert "Hello there" in rendered.body_html


def _offering(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "offering_id": 1,
        "offering_name": "Soccer Camp",
        "site_name": "Park",
        "start_date": date(2026, 6, 1),
        "price_cents": 1000,
        "registration_url": "https://e.example.com/r/1",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize("variant", ["html", "text"])
def test_offering_row_macro_omits_score_when_none(variant: str) -> None:
    """offering_row_* with score=None must skip the score fragment, not emit 'nan'.

    The `is not none` guard protects future kinds that set score=None (vs.
    omitting the key) -- "%.2f" | format(None) would raise TypeError otherwise.
    """
    macro = f"offering_row_{variant}"
    tpl = env.from_string(f'{{% from "macros.j2" import {macro} %}}{{{{ {macro}(m) }}}}')
    out = tpl.render(m=_offering(score=None))
    assert "nan" not in out.lower()
    assert "score" not in out


@pytest.mark.parametrize("variant", ["html", "text"])
def test_offering_row_macro_omits_score_when_absent(variant: str) -> None:
    """offering_row_* with the score key entirely absent also omits the fragment."""
    macro = f"offering_row_{variant}"
    tpl = env.from_string(f'{{% from "macros.j2" import {macro} %}}{{{{ {macro}(m) }}}}')
    out = tpl.render(m=_offering())  # no score key at all
    assert "score" not in out


@pytest.mark.parametrize("variant", ["html", "text"])
def test_offering_row_macro_renders_score_when_present(variant: str) -> None:
    """Sanity: a real float score still renders."""
    macro = f"offering_row_{variant}"
    tpl = env.from_string(f'{{% from "macros.j2" import {macro} %}}{{{{ {macro}(m) }}}}')
    out = tpl.render(m=_offering(score=0.91))
    assert "score 0.91" in out


@pytest.mark.parametrize("variant", ["html", "text"])
def test_offering_row_show_site_false_omits_site(variant: str) -> None:
    macro = f"offering_row_{variant}"
    tpl = env.from_string(
        f'{{% from "macros.j2" import {macro} %}}{{{{ {macro}(m, show_site=false) }}}}'
    )
    out = tpl.render(m=_offering(site_name="Park District", score=0.9))
    assert "Park District" not in out


@pytest.mark.parametrize("variant", ["html", "text"])
def test_offering_row_default_includes_site(variant: str) -> None:
    macro = f"offering_row_{variant}"
    tpl = env.from_string(f'{{% from "macros.j2" import {macro} %}}{{{{ {macro}(m) }}}}')
    out = tpl.render(m=_offering(site_name="Park District", score=0.9))
    assert "Park District" in out


@pytest.mark.parametrize("variant", ["html", "text"])
def test_offering_row_includes_registration_url(variant: str) -> None:
    """Both row variants surface the registration link (text digests rely on this
    after adopting offering_row_text in the grouped New Matches section)."""
    macro = f"offering_row_{variant}"
    tpl = env.from_string(f'{{% from "macros.j2" import {macro} %}}{{{{ {macro}(m) }}}}')
    out = tpl.render(m=_offering(registration_url="https://e.example.com/r/42"))
    assert "https://e.example.com/r/42" in out
