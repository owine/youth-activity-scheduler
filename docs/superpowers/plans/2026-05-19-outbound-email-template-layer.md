# Outbound Email Template Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a unified `src/yas/email/` package that renders every outbound email (digest + every `AlertType` + channel `test_send`) from typed per-type payloads through a shared inline-styled HTML base, replacing the `<pre>`-wrapped placeholder rendering in `delivery.py`.

**Architecture:** A new `yas.email` package owns rendering. A single async public function `render_email(session, kind, lead, members) -> RenderedEmail` looks up an explicit `RENDERERS` dict, runs the per-kind async builder (which joins `Offering`/`Kid`/`Match` to produce Bar-3 useful content), and renders `{kind}.html.j2`/`.txt.j2` templates extending a shared `base.html.j2`/`base.txt.j2` using shared `macros.j2`. `delivery.py` and the digest worker become callers. Loud failures via `jinja2.StrictUndefined` + a typed `EmailRenderError` route into the existing skipped-alert + digest "Delivery Issues" machinery.

**Tech Stack:** Python 3.14, Jinja2 (already a dep, `select_autoescape` + `FileSystemLoader`), SQLAlchemy 2.x async (existing), `pytest`/`pytest-asyncio` (existing), `aiosqlite` in tests (existing).

**Spec:** `docs/superpowers/specs/2026-05-19-outbound-email-template-layer-design.md`

---

## File Structure (target end-state)

**Create:**
- `src/yas/email/__init__.py` — public API (`RenderedEmail`, `render_email`, `render_digest_payload`, `EmailRenderError`, `EmailKind`)
- `src/yas/email/environment.py` — shared Jinja `Environment` with `StrictUndefined` + filters
- `src/yas/email/registry.py` — `EmailKind` type alias, `TypeRenderer` dataclass, `RENDERERS` dict
- `src/yas/email/payloads.py` — frozen dataclass per kind (one file is fine; ~12 small dataclasses)
- `src/yas/email/builders.py` — async builder per kind (one file; each is ~10–30 lines)
- `src/yas/email/templates/base.html.j2`, `base.txt.j2`, `macros.j2`
- `src/yas/email/templates/{kind}.html.j2` + `.txt.j2` for: `digest`, `watchlist_hit`, `new_match`, `reg_opens_24h`, `reg_opens_1h`, `reg_opens_now`, `schedule_posted`, `crawl_failed`, `site_stagnant`, `no_matches_for_kid`, `push_cap`, `test_send`
- `tests/unit/test_email_environment.py`
- `tests/unit/test_email_registry.py`
- `tests/unit/test_email_builders.py`
- `tests/unit/test_email_render_golden.py`
- `tests/golden/email/<kind>.{subject,txt,html}` — committed golden files
- `tests/golden/digest/<scenario>.{txt,html}` — pre-migration baselines (Task 3)

**Modify:**
- `src/yas/alerts/delivery.py` — delete `_render_subject`, `_render_body`, `<pre>` line; call `render_email`
- `src/yas/alerts/digest/builder.py` — shrink to a re-export shim (`from yas.email.payloads import DigestPayload; from yas.email.builders import gather_digest_payload; from yas.email import render_digest_payload as render_digest`) OR update callers and delete; the shim keeps test diff small
- `src/yas/worker/digest_loop.py` — import from `yas.email` (only if shim not used)
- `src/yas/web/routes/digest_preview.py` — same (only if shim not used)
- `src/yas/alerts/digest/templates/digest.html.j2`, `digest.txt.j2` — moved to `src/yas/email/templates/` and refactored to extend the shared base + use macros
- `src/yas/web/routes/notifier_test.py` — call `render_email(..., "test_send", ...)` for body content (currently hand-builds a one-liner)
- `tests/integration/test_alerts_delivery_loop.py` — add assertions about real-content HTML body
- `tests/unit/test_alerts_digest_builder.py` — update imports (or leave if shim used)

**Delete (after migration complete):**
- `src/yas/alerts/digest/templates/digest.html.j2`, `digest.txt.j2` (moved into `yas.email`)
- `src/yas/alerts/delivery.py::_render_subject`, `::_render_body`

---

## Conventions referenced in tasks

- Run all backend tests: `uv run pytest tests/unit tests/integration -q`
- Run a single test: `uv run pytest tests/unit/test_X.py::test_Y -v`
- Run lint+types: `uv run ruff check src tests && uv run mypy src`
- TDD discipline per @superpowers:test-driven-development — failing test first, then minimal code.
- One commit per task unless noted. Conventional Commit prefix: `feat(email):` for new code, `refactor(email):` for migration, `test:` for test-only changes.
- The plan does **not** check `git status` between tasks; the executor's review skill handles that.

---

## Task 1: Package skeleton, `RenderedEmail`, `EmailRenderError`, empty registry

**Files:**
- Create: `src/yas/email/__init__.py`
- Create: `src/yas/email/registry.py`
- Create: `tests/unit/test_email_registry.py`

- [ ] **Step 1: Write failing registry-completeness test**

```python
# tests/unit/test_email_registry.py
"""Registry completeness: every AlertType plus test_send has a renderer."""
from __future__ import annotations

from yas.db.models._types import AlertType
from yas.email.registry import RENDERERS


def test_every_alert_type_has_a_renderer() -> None:
    expected = {at.value for at in AlertType} | {"test_send"}
    actual = {str(k) for k in RENDERERS.keys()}
    assert actual == expected, (
        f"missing: {expected - actual}, extra: {actual - expected}"
    )
```

- [ ] **Step 2: Run, expect ImportError / empty-dict fail**

```bash
uv run pytest tests/unit/test_email_registry.py -v
```
Expected: FAIL (module does not exist yet).

- [ ] **Step 3: Create `src/yas/email/registry.py` (empty registry)**

```python
"""Email type → renderer registry.

A single explicit dict is the type-to-renderer mapping. Membership is
asserted by tests/unit/test_email_registry.py — a missing entry is a CI
failure, not a runtime fallback.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal

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


# Populated incrementally across Tasks 5–14. Task 1 ships it empty so the
# completeness test is initially red and the layer can't be silently used.
RENDERERS: dict[EmailKind, TypeRenderer] = {}
```

- [ ] **Step 4: Create `src/yas/email/__init__.py` with public types**

```python
"""Outbound email rendering — see docs/superpowers/specs/2026-05-19-outbound-email-template-layer-design.md."""
from __future__ import annotations

from dataclasses import dataclass


class EmailRenderError(RuntimeError):
    """Raised when a payload builder or template render cannot produce a useful email.

    Carries the offending alert id (when known) so the delivery layer can mark
    members skipped with a clear reason instead of sending an empty body.
    """

    def __init__(self, message: str, *, alert_id: int | None = None) -> None:
        super().__init__(message)
        self.alert_id = alert_id


@dataclass(frozen=True)
class RenderedEmail:
    """A fully-rendered outbound email, ready to hand to a notifier."""

    subject: str
    body_plain: str
    body_html: str


__all__ = ["EmailRenderError", "RenderedEmail"]
```

- [ ] **Step 5: Run test, expect RED with `missing: {...}` message**

```bash
uv run pytest tests/unit/test_email_registry.py -v
```
Expected: FAIL with the assertion message listing every AlertType + `test_send` as missing. This RED state is intentional — Tasks 5–14 turn it green.

- [ ] **Step 6: Mark the test xfail for now so CI stays green**

Replace the test body with:

```python
import pytest

from yas.db.models._types import AlertType
from yas.email.registry import RENDERERS


@pytest.mark.xfail(
    strict=True,
    reason="Renderers wired incrementally across Tasks 5–14; flips to PASS at Task 14.",
)
def test_every_alert_type_has_a_renderer() -> None:
    expected = {at.value for at in AlertType} | {"test_send"}
    actual = {str(k) for k in RENDERERS.keys()}
    assert actual == expected, (
        f"missing: {expected - actual}, extra: {actual - expected}"
    )
```

`strict=True` means the moment the registry is complete (Task 14), the xfail flips to XPASS and *that* fails — forcing the executor to remove the marker. This is the registry's TDD ratchet.

- [ ] **Step 7: Run lint, types, full unit suite**

```bash
uv run ruff check src tests
uv run mypy src
uv run pytest tests/unit -q
```
Expected: ruff clean, mypy clean, unit suite green (the xfail counts as expected-fail, not failure).

- [ ] **Step 8: Commit**

```bash
git add src/yas/email/__init__.py src/yas/email/registry.py tests/unit/test_email_registry.py
git commit -m "feat(email): scaffold yas.email package + empty renderer registry

Adds RenderedEmail, EmailRenderError, EmailKind, and an empty RENDERERS
dict. Registry-completeness test is xfail(strict=True) so it flips to
red the moment Task 14 lands the final renderer, forcing the executor
to remove the marker."
```

---

## Task 2: Shared Jinja environment with `StrictUndefined`

**Files:**
- Create: `src/yas/email/environment.py`
- Create: `tests/unit/test_email_environment.py`

- [ ] **Step 1: Write failing env tests**

```python
# tests/unit/test_email_environment.py
"""Jinja Environment shared by all outbound-email templates."""
from __future__ import annotations

import pytest
from jinja2 import StrictUndefined, UndefinedError

from yas.email.environment import env


def test_uses_strict_undefined() -> None:
    assert env.undefined is StrictUndefined


def test_autoescape_on_for_html() -> None:
    tpl = env.from_string("{{ x }}", template_class=None)
    # autoescape is configured by extension; verify by rendering an html string in a
    # template that the FileSystemLoader sees as .html.j2. We test the loader-side
    # behavior in test_email_render_golden.py; here we just assert the policy fn.
    assert env.autoescape("foo.html.j2") is True
    assert env.autoescape("foo.txt.j2") is False


def test_price_filter_registered() -> None:
    assert env.from_string("{{ 1234 | price }}").render() == "$12.34"


def test_strict_undefined_raises_on_missing_field() -> None:
    tpl = env.from_string("{{ payload.missing }}")
    with pytest.raises(UndefinedError):
        tpl.render(payload=object())
```

- [ ] **Step 2: Run, expect ImportError**

```bash
uv run pytest tests/unit/test_email_environment.py -v
```
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `environment.py`**

```python
"""Shared Jinja Environment for all outbound-email templates.

StrictUndefined is the linchpin: a template referencing a field its payload
doesn't have raises UndefinedError at render, which the delivery layer routes
into the same skipped-alert + 'Delivery Issues' machinery as a permanent send
failure. Silent half-rendered emails are the bug we're fixing.
"""
from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from yas.alerts.digest.filters import fmt as fmt_filter
from yas.alerts.digest.filters import price as price_filter
from yas.alerts.digest.filters import rel_date as rel_date_filter

_TEMPLATES_DIR = Path(__file__).parent / "templates"

env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(enabled_extensions=("html", "html.j2")),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
env.filters["price"] = price_filter
env.filters["rel_date"] = rel_date_filter
env.filters["fmt"] = fmt_filter
```

Note: filters are imported from the existing `yas.alerts.digest.filters` until Task 4 moves that module under `yas.email`. Until then this is the one cross-package import — it goes away in Task 4.

- [ ] **Step 4: Create the templates directory placeholder**

```bash
mkdir -p src/yas/email/templates
```

- [ ] **Step 5: Run env tests, expect PASS**

```bash
uv run pytest tests/unit/test_email_environment.py -v
```

- [ ] **Step 6: Lint + types + full unit suite**

```bash
uv run ruff check src tests && uv run mypy src && uv run pytest tests/unit -q
```

- [ ] **Step 7: Commit**

```bash
git add src/yas/email/environment.py src/yas/email/templates tests/unit/test_email_environment.py
git commit -m "feat(email): shared Jinja Environment with StrictUndefined

Reuses the existing digest filters (price, rel_date, fmt). StrictUndefined
turns missing payload fields into UndefinedError at render time so the
delivery layer can mark the alert skipped rather than send a blank body.
The filter import from yas.alerts.digest.filters is temporary; Task 4
moves that module under yas.email."
```

---

## Task 3: Capture pre-migration digest goldens

Captures the *current* digest output as snapshots so Task 4's refactor can prove behavior preservation. **This task must land before any digest code moves.**

**Files:**
- Create: `tests/golden/digest/with_matches.txt`, `with_matches.html`
- Create: `tests/golden/digest/empty.txt`, `empty.html`
- Create: `tests/golden/digest/under_threshold.txt`, `under_threshold.html`
- Create: `tests/unit/test_digest_golden.py`

- [ ] **Step 1: Write golden test (will write fresh goldens on first run)**

```python
# tests/unit/test_digest_golden.py
"""Pre-migration digest snapshots.

These goldens lock the current digest output BEFORE the shared-base
refactor. After Task 4 lands, the `chrome` portions (DOCTYPE, <body>, footer)
are re-baselined deliberately; section content must remain byte-identical.
"""
from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from yas.alerts.digest.builder import DigestPayload, render_digest

_GOLDEN_DIR = Path(__file__).parent.parent / "golden" / "digest"


def _payload_with_matches() -> DigestPayload:
    return DigestPayload(
        kid_id=1,
        kid_name="Ada",
        for_date=date(2026, 5, 19),
        new_matches=[
            {
                "offering_id": 10,
                "offering_name": "Soccer Camp",
                "score": 0.91,
                "site_id": 1,
                "site_name": "Park District",
                "start_date": date(2026, 6, 1),
                "price_cents": 15000,
                "registration_opens_at": datetime(2026, 5, 25, 9, 0, tzinfo=UTC),
                "registration_url": "https://example.com/reg/10",
            }
        ],
        starting_soon=[],
        registration_calendar=[],
        delivery_failures=[],
        site_stagnant_ids=[],
        silent_schedule_posts=[],
        under_no_matches_threshold=False,
    )


def _payload_empty() -> DigestPayload:
    return DigestPayload(kid_id=2, kid_name="Bo", for_date=date(2026, 5, 19))


def _payload_under_threshold() -> DigestPayload:
    return DigestPayload(
        kid_id=3,
        kid_name="Cy",
        for_date=date(2026, 5, 19),
        under_no_matches_threshold=True,
    )


_CASES = [
    ("with_matches", _payload_with_matches, "Ada — 1 new match"),
    ("empty", _payload_empty, "Bo — quiet day"),
    ("under_threshold", _payload_under_threshold, "Cy — still searching"),
]


@pytest.mark.parametrize("name, factory, top_line", _CASES, ids=[c[0] for c in _CASES])
def test_digest_golden(name: str, factory, top_line: str) -> None:
    txt, html = render_digest(factory(), top_line)
    expected_txt = (_GOLDEN_DIR / f"{name}.txt").read_text()
    expected_html = (_GOLDEN_DIR / f"{name}.html").read_text()
    assert txt == expected_txt, f"text diverges for {name}"
    assert html == expected_html, f"html diverges for {name}"
```

- [ ] **Step 2: Run once to write the goldens (bootstrap)**

The fastest way to capture goldens is a one-shot script the executor runs *manually* and then deletes — or, equivalently, write them by running a small script via `python -c`:

```bash
mkdir -p tests/golden/digest
uv run python -c "
from datetime import UTC, date, datetime
from pathlib import Path
from yas.alerts.digest.builder import DigestPayload, render_digest

out = Path('tests/golden/digest')

cases = [
    ('with_matches', DigestPayload(
        kid_id=1, kid_name='Ada', for_date=date(2026, 5, 19),
        new_matches=[dict(offering_id=10, offering_name='Soccer Camp', score=0.91,
                          site_id=1, site_name='Park District',
                          start_date=date(2026, 6, 1), price_cents=15000,
                          registration_opens_at=datetime(2026, 5, 25, 9, 0, tzinfo=UTC),
                          registration_url='https://example.com/reg/10')],
    ), 'Ada — 1 new match'),
    ('empty', DigestPayload(kid_id=2, kid_name='Bo', for_date=date(2026, 5, 19)), 'Bo — quiet day'),
    ('under_threshold', DigestPayload(
        kid_id=3, kid_name='Cy', for_date=date(2026, 5, 19),
        under_no_matches_threshold=True,
    ), 'Cy — still searching'),
]

for name, payload, top in cases:
    txt, html = render_digest(payload, top)
    (out / f'{name}.txt').write_text(txt)
    (out / f'{name}.html').write_text(html)
print('captured')
"
```

- [ ] **Step 3: Run the golden test, expect PASS**

```bash
uv run pytest tests/unit/test_digest_golden.py -v
```

- [ ] **Step 4: Sanity-check goldens visually**

```bash
ls tests/golden/digest
wc -l tests/golden/digest/*.html tests/golden/digest/*.txt
```
Expected: 6 files, non-zero sizes. Open one HTML in a browser to confirm it renders.

- [ ] **Step 5: Lint + full unit suite**

```bash
uv run ruff check src tests && uv run pytest tests/unit -q
```

- [ ] **Step 6: Commit**

```bash
git add tests/golden/digest tests/unit/test_digest_golden.py
git commit -m "test: pre-migration digest golden snapshots

Locks in current digest text+html output for three representative payloads
(with_matches, empty, under_threshold). Task 4's refactor onto the shared
base must keep section content byte-identical; chrome (DOCTYPE/body/footer)
is re-baselined deliberately in that same commit."
```

---

## Task 4: Move digest payload/builder/templates into `yas.email`; introduce shared base

This is the highest-risk task. It does four things in one commit so the digest goldens stay coherent:
1. Move `DigestPayload` to `yas.email.payloads`, `gather_digest_payload` to `yas.email.builders`, filters to `yas.email.filters`.
2. Add `templates/base.html.j2`, `templates/base.txt.j2`, `templates/macros.j2`.
3. Move `templates/digest.{html,txt}.j2` to `src/yas/email/templates/` and refactor to extend the shared base + use macros.
4. Add `render_email` (with `EmailKind="digest"` only for now) and `render_digest_payload` to `yas.email.__init__`; register the digest in `RENDERERS`; replace `yas.alerts.digest.builder` with a thin re-export shim.

**Files:**
- Create: `src/yas/email/payloads.py`
- Create: `src/yas/email/builders.py`
- Create: `src/yas/email/filters.py` (move from `yas.alerts.digest.filters`)
- Create: `src/yas/email/templates/base.html.j2`, `base.txt.j2`, `macros.j2`
- Move: `src/yas/alerts/digest/templates/digest.html.j2` → `src/yas/email/templates/digest.html.j2` (refactor inline)
- Move: `src/yas/alerts/digest/templates/digest.txt.j2` → `src/yas/email/templates/digest.txt.j2` (refactor inline)
- Modify: `src/yas/email/__init__.py` (add `render_email`, `render_digest_payload`)
- Modify: `src/yas/email/registry.py` (add `digest` entry)
- Modify: `src/yas/email/environment.py` (import filters from `yas.email.filters` not `yas.alerts.digest.filters`)
- Replace: `src/yas/alerts/digest/builder.py` (thin shim)
- Replace: `src/yas/alerts/digest/filters.py` (thin shim re-exporting from `yas.email.filters`)
- Update: `tests/unit/test_alerts_digest_builder.py` imports unchanged (shim covers them)
- Update: `tests/golden/digest/*.html` re-baselined (chrome diff)

- [ ] **Step 1: Move the filters module first (smallest move, validates shim pattern)**

```bash
git mv src/yas/alerts/digest/filters.py src/yas/email/filters.py
```

Then create the shim at the old path:

```python
# src/yas/alerts/digest/filters.py
"""Re-export shim — filters moved to yas.email.filters."""
from yas.email.filters import fmt, price, rel_date  # noqa: F401
```

Run filter tests:

```bash
uv run pytest tests/unit/test_alerts_digest_filters.py -v
```
Expected: PASS unchanged.

- [ ] **Step 2: Move `DigestPayload` into `yas.email.payloads`**

Create `src/yas/email/payloads.py` with the existing `DigestPayload` definition (copy from `src/yas/alerts/digest/builder.py`, verbatim, no changes to fields/defaults). Leave `gather_digest_payload` in place for now.

```python
# src/yas/email/payloads.py
"""Frozen per-kind payload dataclasses.

Each payload is the typed contract between a builder and its templates.
Templates render from these only — never from raw Alert.payload_json — so
StrictUndefined catches drift at render time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any


@dataclass(frozen=True)
class DigestPayload:
    """All data sections needed to render a digest for one kid."""

    kid_id: int
    kid_name: str
    for_date: date
    new_matches: list[dict[str, Any]] = field(default_factory=list)
    starting_soon: list[dict[str, Any]] = field(default_factory=list)
    registration_calendar: list[dict[str, Any]] = field(default_factory=list)
    delivery_failures: list[dict[str, Any]] = field(default_factory=list)
    site_stagnant_ids: list[int] = field(default_factory=list)
    silent_schedule_posts: list[dict[str, Any]] = field(default_factory=list)
    under_no_matches_threshold: bool = False
```

Update `src/yas/alerts/digest/builder.py` to import `DigestPayload` from `yas.email.payloads` (re-export it for back-compat).

- [ ] **Step 3: Run digest tests to confirm move is transparent**

```bash
uv run pytest tests/unit/test_alerts_digest_builder.py tests/unit/test_digest_golden.py -v
```
Expected: PASS.

- [ ] **Step 4: Create `base.txt.j2` and `base.html.j2`**

`src/yas/email/templates/base.txt.j2`:

```jinja
{% block subject %}YAS — {{ payload.kid_name | default('Update') }}{% endblock %}

{% block body %}{% endblock %}

---
Youth Activity Scheduler
```

`src/yas/email/templates/base.html.j2`:

```jinja
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{% block title %}YAS Update{% endblock %}</title>
</head>
<body style="font-family: -apple-system, Segoe UI, sans-serif; max-width: 600px; margin: 0 auto; padding: 16px; color: #222;">
<header style="border-bottom: 1px solid #ccc; padding-bottom: 8px; margin-bottom: 16px;">
  <strong style="font-size: 1.05em;">{% block heading %}Youth Activity Scheduler{% endblock %}</strong>
</header>

{% block body %}{% endblock %}

<footer style="margin-top: 32px; padding-top: 8px; border-top: 1px solid #eee; font-size: 0.8em; color: #999;">
  Youth Activity Scheduler{% if payload is defined and payload.for_date is defined %} · {{ payload.for_date }}{% endif %}
</footer>
</body>
</html>
```

`src/yas/email/templates/macros.j2`:

```jinja
{# Reusable fragments shared by digest and immediate alerts. #}

{% macro offering_row_html(m) %}
<li>
  <strong>{{ m.offering_name }}</strong>
  {% if m.site_name %} @ {{ m.site_name }}{% endif %}
  {% if m.start_date %}&middot; {{ m.start_date | rel_date }}{% endif %}
  {% if m.price_cents is not none %}&middot; {{ m.price_cents | price }}{% endif %}
  {% if m.score is defined %}&middot; score {{ "%.2f" | format(m.score) }}{% endif %}
  {% if m.registration_url %}&middot; <a href="{{ m.registration_url }}">Register</a>{% endif %}
</li>
{% endmacro %}

{% macro offering_row_text(m) -%}
  - {{ m.offering_name }}{% if m.site_name %} @ {{ m.site_name }}{% endif %}{% if m.start_date %} · {{ m.start_date | rel_date }}{% endif %}{% if m.price_cents is not none %} · {{ m.price_cents | price }}{% endif %}{% if m.score is defined %} · score {{ "%.2f" | format(m.score) }}{% endif %}{% if m.registration_url %} · {{ m.registration_url }}{% endif %}
{%- endmacro %}

{% macro reg_countdown_html(opens_at, label) %}
<div style="background: #fff8e1; border-left: 4px solid #f0a500; padding: 12px; margin: 16px 0;">
  <strong>{{ label }}</strong>
  <div style="color: #555; font-size: 0.9em; margin-top: 4px;">{{ opens_at | fmt }}</div>
</div>
{% endmacro %}
```

- [ ] **Step 5: Refactor `digest.html.j2` and `digest.txt.j2` to extend the base + use macros**

Move the files:

```bash
git mv src/yas/alerts/digest/templates/digest.html.j2 src/yas/email/templates/digest.html.j2
git mv src/yas/alerts/digest/templates/digest.txt.j2 src/yas/email/templates/digest.txt.j2
```

Rewrite `src/yas/email/templates/digest.html.j2` to extend the base. The structure: `{% extends "base.html.j2" %}`, `{% from "macros.j2" import offering_row_html %}`, `{% block heading %}Daily digest — {{ payload.kid_name }}{% endblock %}`, `{% block body %}` contains the existing section logic but each `<li>` uses `{{ offering_row_html(m) }}`. Section *content* must produce byte-identical output for the new_matches list — the macro intentionally outputs the same HTML the inlined `<li>` does. Chrome (DOCTYPE/body/footer) will differ deliberately.

Rewrite `src/yas/email/templates/digest.txt.j2` analogously: `{% extends "base.txt.j2" %}`, `{% block subject %}{{ top_line }}{% endblock %}`, body block contains the existing section logic using `offering_row_text(m)`.

The `{% block subject %}` content is what `render_email` extracts as the email subject — see Step 7.

- [ ] **Step 6: Move `gather_digest_payload` into `yas.email.builders`**

```python
# src/yas/email/builders.py
"""Async builders that turn Alert rows + DB joins into typed payloads."""
from __future__ import annotations

# (existing gather_digest_payload body, imports adjusted; copy verbatim from
# src/yas/alerts/digest/builder.py and remove from the original)
```

Update `src/yas/alerts/digest/builder.py` to be a shim:

```python
"""Re-export shim — digest implementation moved to yas.email."""
from yas.email import render_digest_payload as render_digest  # noqa: F401
from yas.email.builders import gather_digest_payload  # noqa: F401
from yas.email.payloads import DigestPayload  # noqa: F401
```

- [ ] **Step 7: Implement `render_email` and `render_digest_payload`**

Update `src/yas/email/__init__.py`:

```python
"""Outbound email rendering — see spec 2026-05-19."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Alert
from yas.email.environment import env
from yas.email.payloads import DigestPayload
from yas.email.registry import RENDERERS, EmailKind


class EmailRenderError(RuntimeError):
    def __init__(self, message: str, *, alert_id: int | None = None) -> None:
        super().__init__(message)
        self.alert_id = alert_id


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    body_plain: str
    body_html: str


def _render_pair(html_template: str, txt_template: str, ctx: dict) -> RenderedEmail:
    """Render one kind's two templates and pull the subject out of the .txt block."""
    txt_tpl = env.get_template(txt_template)
    html_tpl = env.get_template(html_template)
    # subject lives in {% block subject %} in the .txt template — single source of truth
    subject_module = txt_tpl.new_context(ctx).environment.from_string(
        "{% extends '" + txt_template + "' %}{% block subject %}{{ super() }}{% endblock %}"
    )
    # Cleaner: render the txt template and extract the first line + blank line is subject.
    # Simpler still: pull the rendered subject block directly via Jinja's block API.
    subject = "".join(txt_tpl.blocks["subject"](txt_tpl.new_context(ctx))).strip()
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
            f"no renderer registered for {kind!r}", alert_id=lead.id if lead else None
        ) from exc
    payload = await renderer.build(session, lead, members)
    return _render_pair(renderer.html_template, renderer.txt_template, {"payload": payload})


def render_digest_payload(payload: DigestPayload, top_line: str) -> RenderedEmail:
    """Synchronous render for the digest path, which assembles its own payload outside the Alert lifecycle."""
    renderer = RENDERERS["digest"] if "digest" in RENDERERS else None
    if renderer is None:
        raise EmailRenderError("digest renderer not registered")
    return _render_pair(
        renderer.html_template, renderer.txt_template, {"payload": payload, "top_line": top_line}
    )


__all__ = ["EmailRenderError", "RenderedEmail", "render_email", "render_digest_payload"]
```

Note: the inline subject-extraction comment above is a sketch. The simplest robust pattern is:
- Subject lives in `{% block subject %}...{% endblock %}` at the top of the `.txt` template.
- `subject = "".join(txt_tpl.blocks["subject"](txt_tpl.new_context(ctx))).strip()` extracts the block independently of the rest of the body.
- `body_plain = txt_tpl.render(ctx)` *includes* the subject as the first line; that's fine because the existing digest text body already starts with `{{ top_line }}` (the subject equivalent).

If body_plain duplicating the subject feels wrong, an alternative is a `subject.txt.j2` per kind, but that doubles file count. Keep the block approach.

- [ ] **Step 8: Register `digest` in `RENDERERS`**

```python
# src/yas/email/registry.py — append at module bottom

from yas.email.builders import gather_digest_payload  # noqa: E402

# `digest` uses render_digest_payload (sync) for the worker path; the registry
# entry covers the AlertType="digest" branch should a future caller pass one
# through render_email. build= adapter unwraps lead.payload_json into a payload.
async def _build_digest_from_alert(session, lead, members):
    raise EmailRenderError(
        "digest is rendered via render_digest_payload from worker/digest_loop.py, "
        "not via render_email; this branch should not be reached"
    )

RENDERERS["digest"] = TypeRenderer(
    build=_build_digest_from_alert,
    html_template="digest.html.j2",
    txt_template="digest.txt.j2",
)
```

(Circular-import note: this needs `from yas.email import EmailRenderError`. If that creates a cycle, move `EmailRenderError` to its own module `yas/email/_errors.py` and import from both `__init__.py` and `registry.py`. Make the decision at implementation time.)

- [ ] **Step 9: Update `digest_loop.py` and `digest_preview.py` imports**

If the shim works (re-exports `render_digest`, `gather_digest_payload`, `DigestPayload` from `yas.alerts.digest.builder`), no change needed in callers. Confirm by running:

```bash
uv run pytest tests/unit/test_alerts_digest_builder.py tests/integration/test_api_digest_preview.py -v
```
If anything fails, update imports in the caller rather than expanding the shim.

- [ ] **Step 10: Re-run digest goldens — they will FAIL on chrome diff; re-baseline deliberately**

```bash
uv run pytest tests/unit/test_digest_golden.py -v
```
Expected: FAIL on chrome (DOCTYPE/body/footer) for all three cases; section content matches.

Re-capture with the same one-liner script from Task 3 Step 2 (it overwrites the golden files):

```bash
uv run python -c "
from datetime import UTC, date, datetime
from pathlib import Path
from yas.email import render_digest_payload
from yas.email.payloads import DigestPayload
# ...same three cases as Task 3 Step 2, but writing render_digest_payload(...).body_plain
# and .body_html instead of unpacking the tuple
"
```

`git diff tests/golden/digest/` — verify the diff is **only** chrome (DOCTYPE/header/footer) plus any whitespace adjustments from `trim_blocks`/`lstrip_blocks`. Section content (offering rows, headings, link URLs) must be unchanged. If section content differs, fix the template before continuing.

- [ ] **Step 11: Final test run — full unit + integration**

```bash
uv run ruff check src tests && uv run mypy src && uv run pytest tests/unit tests/integration -q
```
Expected: green, except the xfail in `test_email_registry.py` is still xfail (digest is in but the other kinds aren't yet).

- [ ] **Step 12: Commit (single, large, reviewed commit)**

```bash
git add -A
git commit -m "refactor(email): move digest into yas.email + shared base/macros

- Move DigestPayload → yas.email.payloads, gather_digest_payload →
  yas.email.builders, filters → yas.email.filters.
- Add base.html.j2 / base.txt.j2 / macros.j2 with reusable offering_row
  (HTML + text variants) used by digest and forthcoming immediate-alert
  templates.
- Refactor digest.{html,txt}.j2 to extend base + import macros. Section
  content is byte-identical; chrome (DOCTYPE/<body>/footer) is the
  deliberate baseline diff — pre-migration goldens in
  tests/golden/digest/ updated in this same commit.
- yas.alerts.digest.{builder,filters} reduced to re-export shims.
- yas.email gains render_email() and render_digest_payload(); digest
  registered in RENDERERS.

Spec: docs/superpowers/specs/2026-05-19-outbound-email-template-layer-design.md"
```

---

## Tasks 5–14: One per email kind (uniform shape)

These ten tasks share an identical structure. Each adds: one frozen payload dataclass, one async builder, two templates (HTML + text extending the base), one golden trio, one builder unit test, and one registry entry. **Order is by impact** — the kinds users see most go first so the diff to "useless" experience is visible earliest.

For each kind below, follow this template:

```
1. Add payload dataclass to src/yas/email/payloads.py
2. Add builder to src/yas/email/builders.py (or a small per-kind submodule
   if builders.py exceeds ~250 lines — split by kind, not by layer)
3. Add {kind}.html.j2 + {kind}.txt.j2 in src/yas/email/templates/
4. Add registry entry in src/yas/email/registry.py
5. Add tests/unit/test_email_builders.py::test_build_{kind}_*
6. Write golden files tests/golden/email/{kind}.{subject,txt,html} via the
   bootstrap one-liner (same pattern as Task 3 Step 2)
7. Run goldens + builder tests, fix until green
8. Lint + types + full unit suite
9. Commit "feat(email): render {kind} from typed payload"
```

The first kind (Task 5) walks through the full granular checklist; Tasks 6–14 reference it for the shape and only call out kind-specific details.

---

## Task 5: `new_match` renderer (template walkthrough)

This is the most common alert type — coalesced match notifications for a kid. Worth doing first and in detail because Tasks 6–14 follow the same shape.

**Files:**
- Modify: `src/yas/email/payloads.py` (add `NewMatchPayload`)
- Modify: `src/yas/email/builders.py` (add `build_new_match`)
- Create: `src/yas/email/templates/new_match.html.j2`, `new_match.txt.j2`
- Modify: `src/yas/email/registry.py` (add entry)
- Modify: `tests/unit/test_email_builders.py` (add `test_build_new_match_*`)
- Create: `tests/unit/test_email_render_golden.py` (set up; subsequent tasks add cases)
- Create: `tests/golden/email/new_match.{subject,txt,html}`

- [ ] **Step 1: Define `NewMatchPayload`**

```python
# src/yas/email/payloads.py — append

from datetime import datetime


@dataclass(frozen=True)
class NewMatchPayload:
    """Coalesced `new_match` alert: one or more offerings matched for one kid."""

    kid_id: int
    kid_name: str
    matches: list[dict[str, Any]]  # same shape as DigestPayload.new_matches
    generated_at: datetime
```

`matches[*]` is the offering dict shape returned by `_offering_to_dict` so the shared `offering_row_*` macros render it.

- [ ] **Step 2: Write the failing builder test**

```python
# tests/unit/test_email_builders.py — new file
"""Per-kind builder tests: real DB joins, payload-shape assertions, failure modes."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from yas.db.base import Base
from yas.db.models import Alert, Kid, Match, Offering, Page, Site
from yas.db.models._types import AlertType, PageKind
from yas.db.session import create_engine_for, session_scope
from yas.email import EmailRenderError
from yas.email.builders import build_new_match
from yas.email.payloads import NewMatchPayload

NOW = datetime(2026, 5, 19, 12, 0, tzinfo=UTC)


async def _engine(tmp_path: Any):
    eng = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/b.db")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    return eng


@pytest.mark.asyncio
async def test_build_new_match_single(tmp_path: Any) -> None:
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        site = Site(name="Park", base_url="https://p.example.com", active=True); s.add(site); await s.flush()
        page = Page(site_id=site.id, url="https://p.example.com/s", kind=PageKind.schedule); s.add(page); await s.flush()
        kid = Kid(name="Ada", created_at=NOW - timedelta(days=30)); s.add(kid); await s.flush()
        off = Offering(site_id=site.id, page_id=page.id, name="Soccer Camp",
                       start_date=date(2026, 6, 1), price_cents=15000,
                       registration_url="https://p.example.com/r/10")
        s.add(off); await s.flush()
        m = Match(kid_id=kid.id, offering_id=off.id, score=0.9, computed_at=NOW); s.add(m); await s.flush()
        a = Alert(type=AlertType.new_match.value, kid_id=kid.id, channels=[],
                  scheduled_for=NOW, dedup_key="x", payload_json={"offering_id": off.id}, skipped=False)
        s.add(a); await s.flush()

        payload = await build_new_match(s, a, [a])

    assert isinstance(payload, NewMatchPayload)
    assert payload.kid_name == "Ada"
    assert len(payload.matches) == 1
    assert payload.matches[0]["offering_name"] == "Soccer Camp"
    assert payload.matches[0]["price_cents"] == 15000
    assert payload.matches[0]["registration_url"] == "https://p.example.com/r/10"


@pytest.mark.asyncio
async def test_build_new_match_coalesced(tmp_path: Any) -> None:
    """Two member alerts → both offerings in payload.matches, ordered by score desc."""
    # ...same setup, two offerings, two alerts, assert len(payload.matches) == 2

    ...  # (full body inline in implementation; omitted here for plan brevity)


@pytest.mark.asyncio
async def test_build_new_match_missing_offering(tmp_path: Any) -> None:
    """payload_json points at a non-existent offering → EmailRenderError."""
    eng = await _engine(tmp_path)
    async with session_scope(eng) as s:
        kid = Kid(name="Ada", created_at=NOW); s.add(kid); await s.flush()
        a = Alert(type=AlertType.new_match.value, kid_id=kid.id, channels=[],
                  scheduled_for=NOW, dedup_key="x", payload_json={"offering_id": 999999}, skipped=False)
        s.add(a); await s.flush()
        with pytest.raises(EmailRenderError):
            await build_new_match(s, a, [a])
```

Run, expect FAIL (`ImportError: build_new_match`).

- [ ] **Step 3: Implement `build_new_match`**

```python
# src/yas/email/builders.py — append

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yas.db.models import Alert, Kid, Match, Offering
from yas.email import EmailRenderError
from yas.email.payloads import NewMatchPayload


def _offering_to_dict(o: Offering, score: float, site_name: str) -> dict:
    return {
        "offering_id": o.id,
        "offering_name": o.name,
        "score": score,
        "site_id": o.site_id,
        "site_name": site_name,
        "start_date": o.start_date,
        "price_cents": o.price_cents,
        "registration_opens_at": o.registration_opens_at,
        "registration_url": o.registration_url,
    }


async def build_new_match(
    session: AsyncSession,
    lead: Alert,
    members: list[Alert],
) -> NewMatchPayload:
    if lead.kid_id is None:
        raise EmailRenderError("new_match alert has no kid_id", alert_id=lead.id)
    kid = (await session.execute(select(Kid).where(Kid.id == lead.kid_id))).scalar_one_or_none()
    if kid is None:
        raise EmailRenderError(f"kid {lead.kid_id} not found", alert_id=lead.id)

    offering_ids = [int(a.payload_json["offering_id"]) for a in members if "offering_id" in a.payload_json]
    if not offering_ids:
        raise EmailRenderError("new_match alert missing offering_id", alert_id=lead.id)

    stmt = (
        select(Offering, Match.score)
        .join(Match, (Match.offering_id == Offering.id) & (Match.kid_id == kid.id))
        .where(Offering.id.in_(offering_ids))
        .order_by(Match.score.desc())
    )
    rows = (await session.execute(stmt)).all()
    if len(rows) != len(offering_ids):
        found = {o.id for o, _ in rows}
        missing = [oid for oid in offering_ids if oid not in found]
        raise EmailRenderError(f"offerings not found: {missing}", alert_id=lead.id)

    # Resolve site names in one query
    site_ids = list({o.site_id for o, _ in rows})
    from yas.db.models import Site
    site_rows = (await session.execute(select(Site).where(Site.id.in_(site_ids)))).scalars().all()
    site_names = {s.id: s.name for s in site_rows}

    matches = [_offering_to_dict(o, score, site_names.get(o.site_id, "")) for o, score in rows]
    return NewMatchPayload(kid_id=kid.id, kid_name=kid.name, matches=matches, generated_at=datetime.now(UTC))
```

Run builder tests, expect PASS:

```bash
uv run pytest tests/unit/test_email_builders.py -v
```

- [ ] **Step 4: Write the templates**

`src/yas/email/templates/new_match.txt.j2`:

```jinja
{% extends "base.txt.j2" %}
{% from "macros.j2" import offering_row_text %}

{% block subject -%}
{% if payload.matches | length > 1 %}{{ payload.matches | length }} new matches for {{ payload.kid_name }}{% else %}New match for {{ payload.kid_name }}: {{ payload.matches[0].offering_name }}{% endif %}
{%- endblock %}

{% block body %}
{% if payload.matches | length > 1 %}{{ payload.matches | length }} new activities matched {{ payload.kid_name }}:{% else %}New activity for {{ payload.kid_name }}:{% endif %}

{% for m in payload.matches %}{{ offering_row_text(m) }}
{% endfor %}
{% endblock %}
```

`src/yas/email/templates/new_match.html.j2`:

```jinja
{% extends "base.html.j2" %}
{% from "macros.j2" import offering_row_html %}

{% block title %}New match — {{ payload.kid_name }}{% endblock %}
{% block heading %}New {% if payload.matches | length > 1 %}matches{% else %}match{% endif %} for {{ payload.kid_name }}{% endblock %}

{% block body %}
<ul>
  {% for m in payload.matches %}{{ offering_row_html(m) }}{% endfor %}
</ul>
{% if payload.matches | length == 1 and payload.matches[0].registration_url %}
<p style="margin-top: 16px;">
  <a href="{{ payload.matches[0].registration_url }}"
     style="background: #2a6df4; color: #fff; padding: 10px 16px; border-radius: 4px; text-decoration: none;">
    Register
  </a>
</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 5: Register**

```python
# src/yas/email/registry.py
from yas.email.builders import build_new_match

RENDERERS[AlertType.new_match] = TypeRenderer(
    build=build_new_match,
    html_template="new_match.html.j2",
    txt_template="new_match.txt.j2",
)
```

- [ ] **Step 6: Bootstrap golden files**

```bash
mkdir -p tests/golden/email
uv run python -c "
import asyncio, json
from datetime import UTC, date, datetime, timedelta
# ...construct an in-memory session, seed the same data as test_build_new_match_single,
# call: rendered = asyncio.run(render_email(session, AlertType.new_match, alert, [alert]))
# write rendered.subject → tests/golden/email/new_match.subject (no trailing newline)
# write rendered.body_plain → tests/golden/email/new_match.txt
# write rendered.body_html → tests/golden/email/new_match.html
"
```

(The bootstrap script reuses the fixture setup from the unit test. The executor should factor a `_seed_new_match_scenario(session)` helper into `tests/golden/_scenarios.py` so the same code drives the unit test setup AND the golden bootstrap — DRY.)

- [ ] **Step 7: Add render-golden test**

```python
# tests/unit/test_email_render_golden.py — new file
"""End-to-end render goldens — every kind must produce a stable subject/txt/html."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from yas.db.base import Base
from yas.db.models._types import AlertType
from yas.db.session import create_engine_for, session_scope
from yas.email import render_email
from tests.golden._scenarios import seed_new_match  # one helper per kind

_G = Path(__file__).parent.parent / "golden" / "email"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind, seed", [
    (AlertType.new_match, seed_new_match),
    # ...more kinds appended in tasks 6–14
])
async def test_render_golden(kind, seed, tmp_path: Any) -> None:
    eng = create_engine_for(f"sqlite+aiosqlite:///{tmp_path}/g.db")
    async with eng.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with session_scope(eng) as s:
        lead, members = await seed(s)
        rendered = await render_email(s, kind, lead, members)
    name = kind.value if hasattr(kind, "value") else kind
    assert rendered.subject == (_G / f"{name}.subject").read_text().rstrip("\n")
    assert rendered.body_plain == (_G / f"{name}.txt").read_text()
    assert rendered.body_html == (_G / f"{name}.html").read_text()
```

- [ ] **Step 8: Run goldens, expect PASS**

```bash
uv run pytest tests/unit/test_email_render_golden.py -v
```

- [ ] **Step 9: Lint + types + full unit + integration suite**

```bash
uv run ruff check src tests && uv run mypy src && uv run pytest tests/unit tests/integration -q
```

- [ ] **Step 10: Commit**

```bash
git add -A
git commit -m "feat(email): render new_match from typed payload

NewMatchPayload + build_new_match join Kid + Offering + Match for one or
more coalesced offerings. Templates extend base.{html,txt}.j2 and use
the shared offering_row_* macros so the HTML matches the digest's match
rows byte-for-byte. CTA button rendered when exactly one offering is
present. Golden: tests/golden/email/new_match.{subject,txt,html}."
```

---

## Task 6: `reg_opens_now` renderer

Same shape as Task 5. Kind-specific details:

- **Payload (`RegOpensNowPayload`):** `kid_id`, `kid_name`, `offering: dict` (single, not coalesced — registration-open alerts are per-offering), `opens_at: datetime`, `registration_url: str`.
- **Builder:** join `Kid` + `Offering` from `lead.payload_json["offering_id"]`; raise `EmailRenderError` if either missing. Members are not coalesced for this type (each opening is its own alert).
- **Template (text):** subject `Register now: {offering_name} for {kid_name}`. Body opens with "Registration is OPEN" line, then `offering_row_text`, then URL on its own line.
- **Template (html):** subject same. Body uses `reg_countdown_html(opens_at, "Registration is open now")` macro at top, then offering row, then a large CTA button styled as in Task 5 (`<a href="..." style="background:#d9534f;color:#fff;padding:14px 24px;font-size:1.1em;...">Register now</a>`). Red/orange because this is the urgent variant.
- **Bar 3 check:** the CTA button is the explicit next-step framing; the alert is useless without it.
- **Commit:** `feat(email): render reg_opens_now with prominent Register CTA`

---

## Task 7: `reg_opens_1h` renderer

- **Payload (`RegOpens1hPayload`):** same fields as `reg_opens_now` plus `now: datetime` (so the template can compute `time_remaining` deterministically; passing `now` in the payload also makes goldens stable).
- **Builder:** same joins; set `now=datetime.now(UTC)` (test seam: builder accepts an optional `now=` kwarg used only by tests).
- **Templates:** subject `Registration opens in 1h: {offering_name}`. Body uses `reg_countdown_html(opens_at, "Registration opens in ~1 hour")` and an "advance prep" line ("Have your account logged in"). Note: `reg_opens_1h` is push-only under default routing but the renderer is present for users who add email to its routing — see spec.
- **Commit:** `feat(email): render reg_opens_1h with countdown + prep hint`

---

## Task 8: `reg_opens_24h` renderer

Same as Task 7. Subject `Registration opens tomorrow: {offering_name}`. Body emphasizes calendar-add (no countdown urgency styling — `reg_countdown_html` with neutral label "Registration opens tomorrow at {opens_at|fmt}"). Commit: `feat(email): render reg_opens_24h with calendar-add framing`.

---

## Task 9: `watchlist_hit` renderer

- **Payload (`WatchlistHitPayload`):** `kid_id`, `kid_name`, `matches: list[dict]` (same shape as `NewMatchPayload`), `watchlist_label: str | None` (from `payload_json["watchlist_label"]` if present).
- **Builder:** identical to `build_new_match` *except* it pulls the watchlist label and may handle multiple offerings the same way.
- **Templates:** subject `Watchlist hit for {kid_name}: {offering_name}` (singular subject for 1, `N watchlist matches for {kid_name}` for >1). Body opens with "This is on your watchlist:" before the offering rows — Bar-3 explicit "why it matched" framing.
- **DRY note:** if builders share >70% of code, extract `_build_kid_offering_payload(session, lead, members, payload_cls, *, extras={})` and call it from both. Decide based on the actual diff size, not in advance.
- **Commit:** `feat(email): render watchlist_hit with watchlist framing`

---

## Task 10: `schedule_posted` renderer

- **Payload (`SchedulePostedPayload`):** `site_id`, `site_name`, `new_offerings: list[dict]` (offering_row dict shape, no score since not match-driven), `notes: str | None`.
- **Builder:** join `Site` from `lead.site_id` (note: this alert type uses `Alert.site_id`, not `kid_id`); pull offerings either from `payload_json["offering_ids"]` or from a fresh query for offerings first-seen since the last `schedule_posted` for this site. **Confirm at implementation time which is actually populated** by reading the enqueuer; pick whichever is the present, working source. If neither, raise `EmailRenderError`.
- **Templates:** subject `New schedule posted: {site_name}`. Body lists each new offering via `offering_row_*` (no score column).
- **Commit:** `feat(email): render schedule_posted from site offerings`

---

## Task 11: `crawl_failed` renderer

- **Payload (`CrawlFailedPayload`):** `site_id`, `site_name`, `error_summary: str` (truncated to ~200 chars), `last_success_at: datetime | None`, `failure_count: int`.
- **Builder:** join `Site`; pull error and last-success metadata from `payload_json` + a query of recent crawl rows (the latter is optional — start by reading from `payload_json` only and add the query if the test reveals it's needed).
- **Templates:** subject `Crawl failed: {site_name}`. Body: site header, "Last successful crawl: {last_success_at|fmt or 'never'}", error excerpt in a `<code>` block (HTML) / `>` quoted line (text).
- **Commit:** `feat(email): render crawl_failed with site + error excerpt`

---

## Task 12: `site_stagnant` renderer

- **Payload (`SiteStagnantPayload`):** `site_id`, `site_name`, `days_since_change: int`, `last_change_at: datetime | None`.
- **Builder:** join `Site`; compute days from `payload_json["days_since_change"]` (set by detector) or recompute defensively.
- **Templates:** subject `{site_name} hasn't changed in {N} days`. Body: site name, days, link to site, and a "Should we keep watching?" question framing (Bar 3 action context).
- **Commit:** `feat(email): render site_stagnant with days + action prompt`

---

## Task 13: `no_matches_for_kid` and `push_cap` renderers (minimal)

These two are paired because both are "thin" renderers without a deep DB join.

- **`no_matches_for_kid`:** payload = `kid_id, kid_name, days_since_added`. Template subject `Still searching for activities for {kid_name}`. Body: encouragement copy + link to the kid's page. Useful but short.
- **`push_cap`:** payload = `kid_id | None, kid_name | None, suppressed_count`. Template subject `[push] {N} alerts consolidated`. HTML body is a minimal note. **`push_cap` is push-only in default routing**; the renderer exists for registry completeness and the (rare) case where someone routes it to email. It must still produce valid output — a `<pre>`-style fallback would defeat the spec's goal — but it's allowed to be brief.
- **Commit:** `feat(email): render no_matches_for_kid and push_cap`

---

## Task 14: `test_send` renderer + flip the registry xfail green

- **Payload (`TestSendPayload`):** `channel: str, now: datetime`.
- **Builder:** synchronous-style (no DB access). It still must match the `Callable[[AsyncSession, Alert, list[Alert]], Awaitable[object]]` shape, so the builder is `async def build_test_send(session, lead, members) -> TestSendPayload: return TestSendPayload(channel=lead.payload_json.get("channel", "email"), now=datetime.now(UTC))`.
- **Templates:** subject `YAS {channel} test`. Body: one line confirming the channel works, plus the shared base chrome so the user sees the branded layout when testing.
- **Caller wiring:** update `src/yas/web/routes/notifier_test.py`. Today it builds `NotifierMessage(body_plain=f"If you see this, the {channel} channel is working.", ...)` directly. Replace with `rendered = await render_email(session, "test_send", synthetic_alert, [synthetic_alert])` where `synthetic_alert` is a not-persisted `Alert(type=AlertType.digest.value, ...)` — the lead is only used to pass `payload_json={"channel": channel}` through. (Or: split `render_email` so a `payload` kwarg can be passed directly, skipping the builder, for non-alert-driven kinds. Choose the simpler path at implementation time.)
- **Flip the xfail:** Remove the `@pytest.mark.xfail` decorator from `tests/unit/test_email_registry.py::test_every_alert_type_has_a_renderer`. With all 11 AlertTypes + `test_send` registered, this test now passes naturally.
- **Commit:** `feat(email): render test_send + complete the renderer registry`

---

## Task 15: Wire `delivery.py` to `render_email`; delete placeholders

After Task 14, every `AlertType` has a real renderer. Switch the consumer.

**Files:**
- Modify: `src/yas/alerts/delivery.py`
- Modify: `tests/integration/test_alerts_delivery_loop.py`

- [ ] **Step 1: Add a failing integration assertion**

```python
# tests/integration/test_alerts_delivery_loop.py — new test or extend existing
@pytest.mark.asyncio
async def test_immediate_alert_body_is_branded_html(tmp_path) -> None:
    """new_match through the delivery loop produces real HTML, not <pre>."""
    # ... seed kid + offering + match + alert + AlertRouting(new_match → ["email"])
    # ... run send_alert_group
    # ... grab the captured NotifierMessage from the FakeNotifier
    msg = email_notifier.sent[0]
    assert "<pre>" not in msg.body_html
    assert "<!DOCTYPE html>" in msg.body_html
    assert "Soccer Camp" in msg.body_html
    assert "Soccer Camp" in msg.body_plain
    assert msg.subject.startswith("New match for ")
```

Run, expect FAIL (still using `<pre>` placeholder).

- [ ] **Step 2: Switch `send_alert_group` to call `render_email`**

Replace:

```python
subject = _render_subject(group.alert_type, lead.payload_json, len(members))
body_plain = _render_body(group.alert_type, lead.payload_json, member_payloads)
body_html = f"<pre>{body_plain}</pre>"
```

with:

```python
from yas.email import EmailRenderError, render_email
...
try:
    rendered = await render_email(session, AlertType(group.alert_type), lead, members)
except EmailRenderError as exc:
    log.warning("email.render_failed", alert_id=lead.id, alert_type=group.alert_type, reason=str(exc))
    _mark_all_skipped(members, f"render failed: {exc}")
    return
subject = rendered.subject
body_plain = rendered.body_plain
body_html = rendered.body_html
```

Also delete the now-unused `_render_subject` and `_render_body` functions.

- [ ] **Step 3: Run the new integration test, expect PASS**

```bash
uv run pytest tests/integration/test_alerts_delivery_loop.py::test_immediate_alert_body_is_branded_html -v
```

- [ ] **Step 4: Run the full delivery integration suite to catch regressions**

```bash
uv run pytest tests/integration/test_alerts_delivery_loop.py -v
```

The existing tests expect specific subject/body shapes from the placeholder renderers — they will fail. Update each to assert the new shapes (or assert weaker invariants like "subject is non-empty", "body_plain mentions kid_name"). Do not weaken assertions that the test actually depends on (delivery routing, skipped/retried behaviors).

- [ ] **Step 5: Add a render-failure integration test**

Seed an alert whose `payload_json["offering_id"]` points at no offering → assert members marked `skipped=True` with reason `"render failed: ..."`, no notifier called, no retry scheduled.

- [ ] **Step 6: Lint + types + full suite**

```bash
uv run ruff check src tests && uv run mypy src && uv run pytest tests/unit tests/integration -q
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(alerts): delivery.py renders via yas.email, deletes placeholders

send_alert_group now calls render_email() for every outbound message;
EmailRenderError is caught and routed to _mark_all_skipped with the
failure reason — same terminal handling as a permanent send failure,
visible in the digest 'Delivery Issues' section. Deletes
_render_subject, _render_body, and the <pre> HTML fallback."
```

---

## Task 16: Documentation pass

**Files:**
- Modify: `src/yas/email/__init__.py` (module docstring)
- Modify: `CLAUDE.md` if it lists key directories
- Create: `src/yas/email/README.md` (short)

- [ ] **Step 1: Write `src/yas/email/README.md`**

Short — under one screen. Covers: (a) "what lives here," (b) "to add a new email kind: 1) payload, 2) builder, 3) two templates, 4) registry entry, 5) golden test"; (c) link to the design spec.

- [ ] **Step 2: Update `CLAUDE.md` if applicable**

If `CLAUDE.md` enumerates package responsibilities, add a one-liner for `yas.email`.

- [ ] **Step 3: Commit**

```bash
git add src/yas/email/README.md CLAUDE.md
git commit -m "docs(email): README + CLAUDE.md note on the email package"
```

---

## Final verification

- [ ] Branch contains the spec commit, all 16 task commits, and a clean test suite.
- [ ] `uv run pytest tests/unit tests/integration -q` is green.
- [ ] `uv run ruff check src tests` is clean.
- [ ] `uv run mypy src` is clean.
- [ ] Manual: open `tests/golden/email/new_match.html` and at least one `reg_opens_*.html` in a browser — they should look polished, branded, and visibly different from the pre-migration `<pre>` mess.
- [ ] Run `digest_preview` locally (or just hit the endpoint via httpx) and confirm the digest still renders correctly with the shared chrome.
- [ ] Open a PR. PR description should call out: "removes Task 10 placeholders," link to the spec, and call out the digest chrome re-baseline commit (Task 4) for reviewer attention.

---

## Notes on TDD discipline

Across all 16 tasks, the order inside each step block is non-negotiable: write the failing test, run it red, write the minimal code, run it green, commit. The xfail-strict in Task 1 + the parametrized golden test in Task 5 form the safety net: a new kind cannot be added without a passing golden, and a kind cannot be quietly skipped from the registry. See @superpowers:test-driven-development.

## Notes on commit hygiene

- Each task is one commit unless explicitly split. Don't squash across tasks — the reviewer should be able to revert any individual kind without affecting the others.
- The Task 4 commit is the only large one; its scope is justified by the goldens needing to move atomically with the templates.

## Pointers to relevant skills

- @superpowers:test-driven-development — RED/GREEN/REFACTOR discipline
- @superpowers:verification-before-completion — confirm assertions with output before declaring done
- @superpowers:subagent-driven-development — recommended way to execute this plan
