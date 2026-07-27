# Outbound Email Template Layer — Design

**Date:** 2026-05-19
**Status:** Draft (spec review pending)
**Scope:** Backend (`src/yas/`); no API or frontend changes.

## Problem

Outbound email today has two unrelated rendering paths:

- **The digest** uses Jinja2 templates (`digest.html.j2`, `digest.txt.j2`) with hand-rolled inline styles. It joins to `Offering`/`Kid`/`Match` and produces useful content.
- **All immediate alerts** (`watchlist_hit`, `new_match`, `reg_opens_now`, `reg_opens_24h`, `reg_opens_1h`, `schedule_posted`, `site_stagnant`, `crawl_failed`, `no_matches_for_kid`, `push_cap`) go through placeholder helpers in `src/yas/alerts/delivery.py`:

  ```python
  def _render_subject(...): return f"{prefix}{alert_type}"
  def _render_body(...):    return f"Alert: {alert_type}\nMembers: {n}"
  ...
  body_html = f"<pre>{body_plain}</pre>"
  ```

  The HTML body is literally a `<pre>` tag wrapping a label. The body doesn't include kid name, offering, date, price, or a register link. The emails are not useful.

Both problems — *content emptiness* and *visual inconsistency* — are symptoms of the same gap: there is no general outbound-email template layer. The digest works because someone built it bespoke; everything else falls back to TODO-tagged stubs.

## Goals

1. **Content quality (Bar 3):** every outbound email type carries the minimum useful payload — kid, offering, site, date, price, register link — plus an explicit call-to-action and countdown for time-critical reg-opens alerts.
2. **Visual consistency:** one shared, branded HTML base (DOCTYPE, body chrome, header, footer); no `<pre>` fallbacks.
3. **Per-type templates:** one HTML + one text template per `AlertType`, plus per-type frozen payload dataclasses and async builders that re-derive content from the database.
4. **Explicit extensibility:** adding a new outbound-email type is "add a builder + 2 templates + 1 registry line" — no edits to dispatch conditionals, no magic discovery.
5. **Loud failures:** missing fields, missing rows, missing registry entries fail at build/render/CI time, never as silently-degraded emails.

## Non-goals

- New email types beyond what `AlertType` already defines today (extensibility is in the seam, not in speculative templates).
- Frontend or API changes (`digest_preview.py` keeps working; no new endpoints added speculatively).
- Replacing the email transport layer (`EmailChannel` is unchanged).
- Replacing other channels' rendering (push/ntfy continue to use `body_plain` only).
- Mobile-app-grade visual polish; the bar is "useful + branded + consistent across clients," not pixel art.

## Architecture

A new package `src/yas/email/` owns all outbound-email rendering. `delivery.py` and `digest_loop.py` become callers, not renderers.

```
src/yas/email/
  __init__.py            # public API: render_email(), RenderedEmail
  environment.py         # shared Jinja Environment + filters (price, rel_date, fmt)
  registry.py            # RENDERERS: dict[AlertType, TypeRenderer]
  payloads.py            # frozen dataclass per alert type + DigestPayload (moved)
  builders.py            # async builder per type: (session, lead, members) -> payload
  templates/
    base.html.j2         # DOCTYPE, branded <body>, header, footer chrome
    base.txt.j2          # plain-text frame (top line + footer)
    macros.j2            # offering_row, reg_countdown, kid_header (HTML + text)
    digest.html.j2       # migrated: extends base, uses macros
    digest.txt.j2        # migrated: extends base.txt
    new_match.html.j2 / .txt.j2
    reg_opens_now.html.j2 / .txt.j2
    reg_opens_24h.html.j2 / .txt.j2
    reg_opens_1h.html.j2 / .txt.j2
    schedule_posted.html.j2 / .txt.j2
    site_stagnant.html.j2 / .txt.j2
    test_send.html.j2 / .txt.j2
```

### Public contract

```python
# yas/email/__init__.py


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    body_plain: str
    body_html: str


async def render_email(
    session: AsyncSession,
    alert_type: AlertType,
    lead: Alert,
    members: list[Alert],
) -> RenderedEmail: ...
```

`render_email` looks up `RENDERERS[alert_type]` → runs that type's async builder (which joins to `Offering`/`Kid` as needed) → renders `{type}.html.j2` / `.txt.j2` (both extending the shared base) → extracts the subject from the template's `{% block subject %}`. A missing registry entry raises `KeyError`; a registry-completeness unit test makes this fail in CI rather than at delivery.

### Registry shape

```python
# yas/email/registry.py
@dataclass(frozen=True)
class TypeRenderer:
    build: Callable[[AsyncSession, Alert, list[Alert]], Awaitable[Any]]  # returns payload
    html_template: str  # e.g. "new_match.html.j2"
    txt_template: str


RENDERERS: dict[AlertType, TypeRenderer] = {
    AlertType.new_match: TypeRenderer(build_new_match, "new_match.html.j2", "new_match.txt.j2"),
    AlertType.reg_opens_now: TypeRenderer(
        build_reg_opens_now, "reg_opens_now.html.j2", "reg_opens_now.txt.j2"
    ),
    # ... one line per type
}
```

An explicit dict so the type→behavior mapping is greppable and reviewable — same idiom as the `notifiers` dict in `delivery.py`.

**`test_send` keying:** `test_send` is a channel-test concept, not an `AlertType` enum member. The registry key is therefore `AlertType | Literal["test_send"]` (a small `EmailKind` union alias), with `test_send` carrying its own builder + templates and the channel test endpoint calling `render_email(..., "test_send", ...)`. No new `AlertType` value is added — that would leak a UI concept into the alert taxonomy.

### Styling approach

Inline `style="..."` attributes in the shared `base.html.j2` and macros. No external CSS, no inliner dependency. This matches the existing digest pattern and is what survives Gmail/Outlook/Apple Mail without surprises.

## Data flow

### Delivery path (immediate alerts)

`src/yas/alerts/delivery.py::send_alert_group` today:

```python
subject = _render_subject(group.alert_type, lead.payload_json, len(members))
body_plain = _render_body(group.alert_type, lead.payload_json, member_payloads)
body_html = f"<pre>{body_plain}</pre>"
```

After:

```python
rendered = await render_email(session, AlertType(group.alert_type), lead, members)
msg = NotifierMessage(
    kid_id=group.kid_id,
    alert_type=AlertType(group.alert_type),
    subject=rendered.subject,
    body_plain=rendered.body_plain,
    body_html=rendered.body_html,
    url=lead.payload_json.get("registration_url"),
    urgent=(group.alert_type == AlertType.reg_opens_now.value),
)
```

`_render_subject`, `_render_body`, and the `<pre>` line are deleted. `delivery.py` already holds an `AsyncSession` and the `lead`/`members` it now passes through.

### Digest path

`src/yas/worker/digest_loop.py` and `src/yas/web/routes/digest_preview.py` currently import `from yas.alerts.digest.builder import gather_digest_payload, render_digest`. After the move:

- `gather_digest_payload` and `DigestPayload` move to `yas.email.builders` / `yas.email.payloads`.
- `render_digest` is replaced by `render_email(session, AlertType.digest, ...)`. Where the digest is not driven by an `Alert` row (the daily roll-up assembles its own payload), `render_email` gains a sibling `render_digest_payload(payload: DigestPayload, top_line: str) -> RenderedEmail` for that callsite — a small concession to the digest's distinct lifecycle, kept in the same module so all rendering still lives in one place.
- `yas.alerts.digest.builder` becomes a thin re-export shim (or callers update) so `digest_preview.py` and `digest_loop.py` keep working without changing their public behavior.

### Per-type builders

Each is `async (session, lead, members) -> <TypePayload>`:

- `new_match` / `schedule_posted`: join `Match`/`Offering`/`Kid` from ids in `payload_json`, reusing the digest's `_offering_to_dict` shape so the **shared `offering_row` macro renders identically** in digest and immediate alerts. Coalesced `members` → list of offering dicts grouped under one `kid_header`.
- `reg_opens_now` / `reg_opens_1h` / `reg_opens_24h`: offering essentials **plus** `opens_at` and a computed `time_remaining` for the prominent CTA block (Bar 3).
- `site_stagnant`: site name/id + last-change age (no offering join).
- `test_send`: trivial static payload (used by the channel test-send endpoint).
- `digest`: existing `gather_digest_payload` moves in unchanged.

Each payload is a **frozen dataclass** with explicit fields — the per-type contract. The builder is the only place that touches `payload_json` keys, so malformed/empty payloads raise in the builder with a clear error, not as a blank section in a delivered email.

### Diagram

```
Alert rows (lead + members)
   │  delivery.send_alert_group
   ▼
render_email(session, alert_type, lead, members)
   │  RENDERERS[alert_type]
   ▼
builder ──(DB joins: Offering/Kid/Match)──► frozen TypePayload
   │
   ▼
{type}.html.j2 / .txt.j2  (extend base, use macros.j2)
   │
   ▼
RenderedEmail(subject, body_plain, body_html)
   │
   ▼
NotifierMessage ──► EmailChannel transport (unchanged)
```

## Content bar per type (Bar 3)

| Alert type        | Subject                                     | Body essentials                                                                                                        |
|-------------------|---------------------------------------------|------------------------------------------------------------------------------------------------------------------------|
| `watchlist_hit`   | `Watchlist hit for <kid>: <offering>`       | kid header, offering rows (same macro as new_match), explicit "this matches your watchlist" framing                  |
| `new_match`     | `New match for <kid>: <offering>` (or `N new matches for <kid>` if coalesced) | kid header, per-offering row (name, site, start_date, price, score, register link), match-reason snippet              |
| `crawl_failed`    | `Crawl failed: <site>`                      | site name, last successful crawl, error summary, link to site                                                          |
| `no_matches_for_kid` | `Still searching for activities for <kid>` | kid header, days since kid added, encouragement copy                                                                  |
| `push_cap`        | (push-only; no email body needed)           | minimal renderer present for registry completeness; never actually delivered via email under default routing          |
| `reg_opens_now`   | `Register now: <offering> for <kid>`        | prominent CTA button-style block, register link, opens-at time, "Open now" indicator, offering essentials             |
| `reg_opens_1h`    | `Registration opens in 1h: <offering>`      | countdown to `opens_at`, register link, offering essentials, prep checklist line                                      |
| `reg_opens_24h`   | `Registration opens tomorrow: <offering>`   | countdown, register link, offering essentials                                                                          |
| `schedule_posted` | `New schedule posted: <site>`               | site header, new offering rows (same macro as digest), per-offering register links                                    |
| `site_stagnant`   | `<site> hasn't changed in <N> days`         | site name, days since last change, link to site                                                                        |
| `digest`          | (unchanged)                                  | (unchanged content; chrome migrated to shared base)                                                                    |
| `test_send`       | `<channel> test`                            | one line confirming the channel is wired                                                                               |

The shared `offering_row` macro renders identically in `digest` and in `new_match`/`schedule_posted` — that uniformity is the whole point of the macro.

## Error handling

1. **Missing registry entry** — `RENDERERS[alert_type]` raises `KeyError`. A registry-completeness unit test asserts every email-routable `AlertType` has an entry, so this is a CI failure, not a delivery failure. At runtime, the `KeyError` is caught by `send_alert_group`'s existing error path and treated like any other permanent failure.

2. **Builder failure (missing/stale row)** — e.g. an offering deleted between enqueue and delivery. The builder raises a typed `EmailRenderError(alert_id, reason)`. `render_email` lets it propagate; `delivery.py` catches it, logs `email.render_failed` (structured: `alert_id`, `alert_type`, `reason`), and marks the group's members **skipped with that reason** — same terminal handling as a permanent send failure. The skipped alert surfaces in the digest's existing "Delivery Issues" section, so the failure is visible.

3. **Template rendering error** — the shared `Environment` uses `jinja2.StrictUndefined`. A template referencing a field the payload doesn't have raises `UndefinedError` immediately (caught as in #2). This is deliberate: loud failure beats delivered-but-useless. Golden tests catch field drift first.

4. **Digest regression risk** — the migration to the shared base is guarded by golden/snapshot tests capturing current `digest.html.j2`/`digest.txt.j2` output for representative payloads *before* the refactor. Chrome differences are intentional and re-baselined deliberately in one reviewed commit.

5. **Plain text is the source of truth** — `body_plain` is mandatory and never depends on HTML rendering succeeding (it's its own template). Push/ntfy continue to use only `body_plain`, so a hypothetical HTML-only failure (would still raise as #3) cannot silently demote those channels.

## Testing

Mirrors the existing `tests/unit` + `tests/integration` split and the codebase's `pytest`-async style. Written TDD-first: registry-completeness and golden tests fail before implementation; builders and templates make them pass.

### Unit

- **`tests/unit/test_email_builders.py`** — per type: given seeded `Alert`/`Offering`/`Kid`/`Match` rows, assert the builder returns a payload with correct fields, correct coalesced-member handling, and correct countdown math for `reg_opens_*`. Failure cases: deleted offering → `EmailRenderError(alert_id, ...)`; empty members.
- **`tests/unit/test_email_registry.py`** — assert `set(RENDERERS) == set(AlertType) | {"test_send"}` (every `AlertType` has a renderer, plus the `test_send` channel-test concept); assert each entry's templates exist and load. Guards "forgot to wire a new type." Routing decisions (which types actually get emailed by default) live in `routing.py`, not the registry — the layer renders whatever the router asks for.
- **`tests/unit/test_email_render_golden.py`** — for each type, render `RenderedEmail` from a fixed payload and compare `subject`/`body_plain`/`body_html` against committed goldens in `tests/golden/email/`. Verifies Bar-3 content present (kid, offering, date, price, register link; countdown + CTA for reg-opens types), shared base chrome present, `StrictUndefined` raises on field drift. Regenerated only via an explicit, reviewed step.
- **`tests/unit/test_digest_golden.py`** — capture current digest HTML/text output as goldens **before** migration; the shared-base refactor must keep them green except the deliberately re-baselined chrome diff (one reviewed commit, called out in its message).

### Integration

- **`tests/integration/test_alerts_delivery_loop.py`** (extend) — end-to-end: enqueue an immediate alert → run delivery → assert the captured `NotifierMessage` has a non-empty branded `body_html` (no `<pre>`), correct subject, and that a builder failure marks members skipped and surfaces in the digest's "Delivery Issues" section.
- **`tests/integration/test_api_digest_preview.py`** (extend) — `digest_preview.py` still returns valid output post-migration.

## Migration & rollout

The work is internal-only (no API/contract changes), so rollout is by commits, not feature flags:

1. Add `yas.email` package skeleton + `RenderedEmail` + empty `RENDERERS`; registry-completeness test fails.
2. Add `base.html.j2` / `base.txt.j2` / `macros.j2` + the `Environment` with `StrictUndefined` + golden infrastructure.
3. Capture digest goldens against the *current* templates (pre-migration baseline).
4. Move `DigestPayload` and `gather_digest_payload` into `yas.email`; add `render_email`/`render_digest_payload`; migrate digest templates to extend the shared base; update `digest_loop.py` and `digest_preview.py` imports. The digest **content** goldens (sections, data, plain-text body) must stay green; the **chrome** golden (DOCTYPE, `<body>` wrapper, header/footer) is re-baselined deliberately in this same commit as the only intentional diff.
5. Per immediate alert type, in its own commit: payload dataclass, builder, two templates, registry line, golden, builder unit tests.
6. Switch `delivery.py` to call `render_email`; delete `_render_subject`/`_render_body`/`<pre>`; extend delivery integration test.

Each step keeps the test suite green; nothing in `delivery.py` switches over until all per-type renderers exist and the registry-completeness test passes.

## YAGNI list

Explicitly out of scope, not just deferred:

- A second alternative styling track (CSS inliner, MJML, etc.) — revisit only if a real client-rendering bug demands it.
- Per-recipient personalization beyond what `payload_json` + DB joins already provide.
- Email open/click tracking.
- A webhook/REST surface for previewing arbitrary alert types — `digest_preview` is the only preview surface; no new ones added without a concrete user.
- Localization / i18n.
- A `Renderer` protocol with auto-discovery — the explicit `RENDERERS` dict is the discovery mechanism.

## Open questions

None blocking. The decisions taken during brainstorming:

- Full template layer (digest + immediate + test send), architected for trivial extension. ✅
- One template file per alert type + shared base + shared macros. ✅
- Typed frozen payload dataclass per type, built by an async builder. ✅
- Inline styles in a shared base (no inliner). ✅
- Full digest migration to the shared base, guarded by pre-migration goldens. ✅
- Bar-3 content (essentials + context + actions) across all immediate types. ✅
- Explicit `RENDERERS` registry in a new `yas.email` package, not subclass auto-discovery. ✅
