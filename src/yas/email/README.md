# `yas.email` — outbound email rendering

This package renders every outbound email the system sends: the daily digest,
every immediate alert (`new_match`, `reg_opens_now`, `watchlist_hit`, …), and
the channel-test message from the settings UI.

See the design spec for the why:
[`docs/superpowers/specs/2026-05-19-outbound-email-template-layer-design.md`](../../../docs/superpowers/specs/2026-05-19-outbound-email-template-layer-design.md)

## What lives here

```
yas/email/
├── __init__.py        — public API: render_email, render_digest_payload, RenderedEmail, EmailRenderError
├── _errors.py         — EmailRenderError
├── environment.py     — shared Jinja Environment (StrictUndefined, autoescape, filters)
├── filters.py         — price, rel_date, fmt
├── payloads.py        — one frozen dataclass per kind (the typed contract)
├── builders.py        — async builder per kind: (session, lead, members) → payload
├── llm_summary.py     — generate_top_line: LLM digest top-line with template fallback
├── registry.py        — RENDERERS: dict[EmailKind, TypeRenderer]
└── templates/
    ├── base.html.j2   — shared branded chrome (DOCTYPE, body styles, header, footer)
    ├── base.txt.j2    — shared plain-text frame
    ├── macros.j2      — reusable fragments (offering_row_html/_text, reg_countdown_html)
    └── <kind>.{html,txt}.j2  — one pair per kind, extending the base
```

## Public API

```python
from yas.email import render_email, render_digest_payload, RenderedEmail, EmailRenderError

# Driven by an Alert row (immediate alerts, test_send):
rendered: RenderedEmail = await render_email(session, kind, lead, members)

# Driven by a pre-built payload (digest only — bypasses the registry):
rendered: RenderedEmail = render_digest_payload(digest_payload, top_line)

rendered.subject  # str — pulled from the .txt template's {% block subject %}
rendered.body_plain  # str — the .txt template's full render
rendered.body_html  # str — the .html template's full render
```

`kind` is `EmailKind = AlertType | Literal["test_send"]`. `test_send` is the
channel-test concept (used by `yas.web.routes.notifier_test`); it's not a real
`AlertType`.

## To add a new outbound-email kind

Five files, one commit:

1. **Payload** — add a frozen dataclass to `payloads.py` with the fields the
   templates need. The dataclass is the contract; templates can't read fields
   that aren't on it (StrictUndefined raises).
2. **Builder** — add an async function `build_<kind>(session, lead, members) -> <kind>Payload`
   to `builders.py`. Join `Kid` / `Offering` / `Site` etc. as needed. Raise
   `EmailRenderError(message, alert_id=lead.id)` on missing data — never
   silently return an empty payload.
3. **Templates** — create `templates/<kind>.html.j2` and `templates/<kind>.txt.j2`.
   Both `{% extends "base.{html,txt}.j2" %}`. Both must override
   `{% block subject %}` (a test enforces this). HTML can `{% from "macros.j2"
   import offering_row_html %}` for offering rows; text uses
   `offering_row_text`. The HTML CTA button convention is a blue `#2a6df4`
   for normal urgency, red `#d9534f` for "act now."
4. **Registry entry** — add to `RENDERERS` in `registry.py`:
   ```python
   AlertType.<kind>: TypeRenderer(
       build=build_<kind>,
       html_template="<kind>.html.j2",
       txt_template="<kind>.txt.j2",
   ),
   ```
5. **Tests** — add `build_<kind>_*` cases to `tests/unit/test_email_builders.py`,
   a `seed_<kind>(session)` scenario to `tests/golden/_scenarios.py`, a
   `parametrize` entry to `tests/unit/test_email_render_golden.py`, and bootstrap
   the three golden files (`tests/golden/email/<kind>.{subject,txt,html}`) by
   running an in-process render once.

The registry-completeness test
(`tests/unit/test_email_registry.py::test_every_alert_type_has_a_renderer`)
will catch a missing registry entry; the subject-block test catches a missing
`{% block subject %}` override.

## Failure mode

Every error path raises `EmailRenderError`. The delivery layer
(`yas.alerts.delivery.send_alert_group`) catches it, logs
`email.render_failed`, and marks the group's members `skipped=True` with the
failure reason — the same terminal handling as a permanent send failure. The
skipped alert surfaces in the next digest's "Delivery Issues" section, so the
user sees that something didn't render rather than receiving a half-rendered
email.

## Digest is special

`AlertType.digest` is deliberately **not** in `RENDERERS`. The digest payload
is assembled by `yas.worker.digest_loop` from a full kid-window query
(`gather_digest_payload`), not from a single Alert row. Calling
`render_email(session, AlertType.digest, ...)` raises `EmailRenderError`
("no renderer registered for ...") by design — callers must use
`render_digest_payload(payload, top_line)` instead.

The digest worker pre-renders the subject/body into the digest `Alert` row's
`payload_json` before enqueueing, and `send_alert_group` pulls those
pre-rendered fields out for the actual delivery. This split is the only kind
that doesn't follow the "register a builder, render through render_email"
pattern; everything else does.
