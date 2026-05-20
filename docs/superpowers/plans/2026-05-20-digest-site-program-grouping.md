# Digest Site → Program Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group the daily digest's "New Matches" section by site → program type → activities, and fix the latent bug where the digest never resolved site names.

**Architecture:** `gather_digest_payload` resolves site names (one batch `Site` query — fixing the empty-site bug), adds `program_type` to each offering dict, and stores a derived `new_match_groups` structure (built by a pure `_group_matches_by_site` helper from the already-score-sorted flat list). The digest templates' New Matches section iterates `new_match_groups`; the `offering_row_*` macros gain an optional `show_site` flag so grouped rows don't repeat the site that's already in the header.

**Tech Stack:** Python 3.14, SQLAlchemy 2.x async, Jinja2 (StrictUndefined env), pytest/pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-20-digest-site-program-grouping-design.md`

---

## File Structure

**Modify:**
- `src/yas/email/payloads.py` — add `new_match_groups` field to `DigestPayload`
- `src/yas/email/builders.py` — add `program_type` to `_offering_to_dict`; add `_group_matches_by_site` + `_program_label` helpers; resolve site names + populate `new_match_groups` in `gather_digest_payload`
- `src/yas/email/templates/macros.j2` — add `show_site=true` param to `offering_row_html` / `offering_row_text`
- `src/yas/email/templates/digest.html.j2` — grouped New Matches section
- `src/yas/email/templates/digest.txt.j2` — grouped New Matches section (adopts `offering_row_text`)
- `tests/unit/test_email_builders.py` — site-name regression + `new_match_groups` shape tests
- `tests/unit/test_email_render_pair.py` — `show_site` flag test
- `tests/unit/test_digest_golden.py` — build `new_match_groups` in fixtures; add multi-site case

**Create:**
- `tests/unit/test_email_grouping.py` — pure `_group_matches_by_site` / `_program_label` unit tests
- `tests/golden/digest/multi_site.txt`, `tests/golden/digest/multi_site.html` — new golden snapshot
- (re-baselined) `tests/golden/digest/with_matches.txt`, `tests/golden/digest/with_matches.html`

## Conventions

- Run a single test: `uv run pytest tests/unit/test_X.py::test_Y -v --no-cov`
- Full check before commit: `uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src && uv run pytest tests/unit tests/integration -q --no-cov`
  - **Note:** `ruff format --check` is a *separate* CI gate from `ruff check`. Run both. (A prior PR failed CI on format-only.)
- TDD per @superpowers:test-driven-development. @superpowers:verification-before-completion before claiming done.
- Conventional commits: `feat(email):` / `test:` / `refactor(email):`.

---

## Task 1: Grouping helper + program label (pure, no DB)

The core grouping logic, fully testable without a database.

**Files:**
- Modify: `src/yas/email/builders.py` (add `_program_label`, `_group_matches_by_site`)
- Create: `tests/unit/test_email_grouping.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_email_grouping.py
"""Pure unit tests for the digest site->program grouping helper."""
from __future__ import annotations

from yas.email.builders import _group_matches_by_site, _program_label


def _m(site_id, site_name, program_type, name, score):
    return {
        "offering_id": hash((site_id, name)) & 0xFFFF,
        "offering_name": name,
        "site_id": site_id,
        "site_name": site_name,
        "program_type": program_type,
        "score": score,
        "start_date": None,
        "price_cents": None,
        "registration_opens_at": None,
        "registration_url": None,
    }


def test_program_label_titlecases_and_maps_unknown():
    assert _program_label("soccer") == "Soccer"
    assert _program_label("martial_arts") == "Martial Arts"
    assert _program_label("unknown") == "Other"


def test_groups_by_site_then_program():
    # Flat list, already score-sorted desc (as gather_digest_payload produces).
    matches = [
        _m(1, "Park District", "soccer", "Soccer Camp", 0.91),
        _m(1, "Park District", "swim", "Summer Swim", 0.80),
        _m(1, "Park District", "soccer", "Lil Kickers", 0.74),
        _m(2, "YMCA", "dance", "Ballet I", 0.66),
    ]
    groups = _group_matches_by_site(matches)

    # Two sites, ordered by best score desc: Park District (0.91) then YMCA (0.66).
    assert [g["site_name"] for g in groups] == ["Park District", "YMCA"]

    park = groups[0]
    # Programs ordered by their best offering's score: soccer (0.91) before swim (0.80).
    assert [p["program_type"] for p in park["programs"]] == ["soccer", "swim"]
    assert [p["program_label"] for p in park["programs"]] == ["Soccer", "Swimming" if False else "Swim"]
    # Offerings within soccer ordered by score desc.
    soccer = park["programs"][0]
    assert [o["offering_name"] for o in soccer["offerings"]] == ["Soccer Camp", "Lil Kickers"]

    ymca = groups[1]
    assert ymca["site_id"] == 2
    assert [p["program_type"] for p in ymca["programs"]] == ["dance"]


def test_empty_list_returns_empty():
    assert _group_matches_by_site([]) == []


def test_missing_site_name_groups_under_blank():
    groups = _group_matches_by_site([_m(5, "", "art", "Painting", 0.5)])
    assert groups[0]["site_id"] == 5
    assert groups[0]["site_name"] == ""
```

Note: fix the `program_label` assertion line — `_program_label("swim")` returns `"Swim"`. Write it as `assert [p["program_label"] for p in park["programs"]] == ["Soccer", "Swim"]`.

- [ ] **Step 2: Run, expect failure (ImportError)**

`uv run pytest tests/unit/test_email_grouping.py -v --no-cov`
Expected: FAIL — `_group_matches_by_site` / `_program_label` not importable.

- [ ] **Step 3: Implement the helpers in `src/yas/email/builders.py`**

Add near the top (after `_offering_to_dict`):

```python
def _program_label(program_type: str) -> str:
    """Human display label for a ProgramType value. `unknown` -> 'Other'."""
    if program_type == "unknown":
        return "Other"
    return program_type.replace("_", " ").title()
    # Note: acronyms like 'stem' render as 'Stem'. Acceptable; do not special-case.


def _group_matches_by_site(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group a score-sorted flat match list into site -> program -> offerings.

    Pure reorganization of the same dicts (no DB). Ordering:
      - sites by their best (max) offering score, descending
      - programs within a site by their best offering score, descending
      - offerings within a program preserve the input order (score desc)

    `matches` is expected pre-sorted by score desc (as gather_digest_payload
    produces). Offerings without a 'score' key sort last within their bucket.
    """

    def _score(o: dict[str, Any]) -> float:
        s = o.get("score")
        return s if isinstance(s, (int, float)) else float("-inf")

    # Preserve first-seen order while bucketing so we can sort buckets by max score.
    sites: dict[int, dict[str, Any]] = {}
    for m in matches:
        site_id = m["site_id"]
        site = sites.setdefault(
            site_id,
            {"site_id": site_id, "site_name": m.get("site_name", ""), "_programs": {}},
        )
        pt = m.get("program_type", "unknown")
        prog = site["_programs"].setdefault(
            pt, {"program_type": pt, "program_label": _program_label(pt), "offerings": []}
        )
        prog["offerings"].append(m)

    result: list[dict[str, Any]] = []
    for site in sites.values():
        programs = list(site["_programs"].values())
        # offerings already score-sorted from input; sort programs by their best score.
        programs.sort(key=lambda p: max(_score(o) for o in p["offerings"]), reverse=True)
        result.append(
            {
                "site_id": site["site_id"],
                "site_name": site["site_name"],
                "programs": programs,
            }
        )
    # sites by their best offering score across all programs.
    result.sort(
        key=lambda s: max(_score(o) for p in s["programs"] for o in p["offerings"]),
        reverse=True,
    )
    return result
```

- [ ] **Step 4: Run tests, expect PASS**

`uv run pytest tests/unit/test_email_grouping.py -v --no-cov`

- [ ] **Step 5: Lint/format/types**

`uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`

- [ ] **Step 6: Commit**

```bash
git add src/yas/email/builders.py tests/unit/test_email_grouping.py
git commit -m "feat(email): add site->program grouping helper for the digest

Pure _group_matches_by_site reorganizes the score-sorted flat match list
into site -> program-type -> offerings, ordering sites and programs by
their best offering score. _program_label maps ProgramType values to
display labels (unknown -> Other). No DB access; fully unit-tested."
```

---

## Task 2: Add `program_type` to the offering dict + populate the payload

Wire site-name resolution (the bug fix), `program_type`, and `new_match_groups` into `gather_digest_payload`.

**Files:**
- Modify: `src/yas/email/payloads.py` (add `new_match_groups` field)
- Modify: `src/yas/email/builders.py` (`_offering_to_dict` + `gather_digest_payload`)
- Modify: `tests/unit/test_email_builders.py` (regression + shape tests)

- [ ] **Step 1: Add the field to `DigestPayload`**

In `src/yas/email/payloads.py`, add to `DigestPayload` (after `new_matches`):

```python
    new_match_groups: list[dict[str, Any]] = field(default_factory=list)
```

- [ ] **Step 2: Write failing builder tests**

Add to `tests/unit/test_email_builders.py` (it already has DB-backed digest tests; reuse the existing engine/seed helpers in that file — check their names first, e.g. `_make_engine`, and the Site/Page/Kid/Offering/Match factories):

```python
@pytest.mark.asyncio
async def test_gather_digest_populates_site_name_and_groups(tmp_path: Any) -> None:
    """Regression: site_name is resolved (was always ''); new_match_groups nests by site->program."""
    eng = await _make_engine(tmp_path)
    async with session_scope(eng) as s:
        site_a = Site(name="Park District", base_url="https://a.example.com", active=True)
        site_b = Site(name="YMCA", base_url="https://b.example.com", active=True)
        s.add_all([site_a, site_b]); await s.flush()
        page_a = Page(site_id=site_a.id, url="https://a.example.com/s", kind=PageKind.schedule)
        page_b = Page(site_id=site_b.id, url="https://b.example.com/s", kind=PageKind.schedule)
        s.add_all([page_a, page_b]); await s.flush()
        kid = Kid(name="Ada", dob=date(2017, 1, 1), created_at=NOW - timedelta(days=30))
        s.add(kid); await s.flush()
        # Two offerings at site A (soccer + swim), one at site B (dance).
        o1 = Offering(site_id=site_a.id, page_id=page_a.id, name="Soccer Camp",
                      normalized_name="soccer camp", program_type="soccer",
                      start_date=date(2026, 6, 1), price_cents=15000,
                      registration_url="https://a.example.com/r/1")
        o2 = Offering(site_id=site_a.id, page_id=page_a.id, name="Summer Swim",
                      normalized_name="summer swim", program_type="swim",
                      start_date=date(2026, 6, 15), price_cents=14000)
        o3 = Offering(site_id=site_b.id, page_id=page_b.id, name="Ballet I",
                      normalized_name="ballet i", program_type="dance",
                      start_date=date(2026, 6, 3), price_cents=12000)
        s.add_all([o1, o2, o3]); await s.flush()
        # Matches inside the window, scores set so ordering is deterministic.
        s.add_all([
            Match(kid_id=kid.id, offering_id=o1.id, score=0.91, computed_at=NOW),
            Match(kid_id=kid.id, offering_id=o2.id, score=0.80, computed_at=NOW),
            Match(kid_id=kid.id, offering_id=o3.id, score=0.66, computed_at=NOW),
        ]); await s.flush()

        payload = await gather_digest_payload(
            s, kid,
            window_start=NOW - timedelta(days=1), window_end=NOW + timedelta(hours=1),
            alert_no_matches_kid_days=7, now=NOW,
        )

    # Bug fix: site_name is populated on the flat list (previously always "").
    assert all(m["site_name"] for m in payload.new_matches)
    # program_type present on every offering dict.
    assert all("program_type" in m for m in payload.new_matches)
    # Grouped: Park District (best 0.91) before YMCA (0.66).
    assert [g["site_name"] for g in payload.new_match_groups] == ["Park District", "YMCA"]
    park = payload.new_match_groups[0]
    assert [p["program_type"] for p in park["programs"]] == ["soccer", "swim"]
```

(Adjust imports/seed-helper names to match what already exists at the top of `test_email_builders.py`. `NOW`, `date`, `timedelta` are already imported there from the Task-5 work; verify.)

- [ ] **Step 3: Run, expect failure**

`uv run pytest tests/unit/test_email_builders.py::test_gather_digest_populates_site_name_and_groups -v --no-cov`
Expected: FAIL — `new_match_groups` empty / `site_name` blank / `program_type` missing.

- [ ] **Step 4: Add `program_type` to `_offering_to_dict`**

In `src/yas/email/builders.py::_offering_to_dict`, add to the dict literal:

```python
        "program_type": offering.program_type,
```

(Always present — the column defaults to `unknown`.)

- [ ] **Step 5: Resolve site names + build groups in `gather_digest_payload`**

After the `new_matches` list is built (the loop over `match_rows`), insert:

```python
    # Resolve site names for the new-match offerings (one batch query) and
    # populate site_name on each dict. Without this the digest showed no site
    # (site_name defaulted to "" and the macro guard dropped it).
    if new_matches:
        site_ids = {m["site_id"] for m in new_matches}
        site_names = dict(
            (
                await session.execute(
                    select(Site.id, Site.name).where(Site.id.in_(site_ids))
                )
            ).all()
        )
        for m in new_matches:
            m["site_name"] = site_names.get(m["site_id"], "")

    new_match_groups = _group_matches_by_site(new_matches)
```

Ensure `Site` is imported in `builders.py` (the `new_match` builder already imports it — confirm it's module-level).

Then add `new_match_groups=new_match_groups,` to the `DigestPayload(...)` constructor call at the end of the function.

- [ ] **Step 6: Run the new test + the full builder/digest suite**

```bash
uv run pytest tests/unit/test_email_builders.py tests/unit/test_email_digest_builder.py -v --no-cov
```
Expected: PASS. (The existing `test_email_digest_builder.py` `gather_digest_payload` tests should still pass; if any asserted `site_name == ""`, update them to the resolved name — but they likely don't assert site_name at all.)

- [ ] **Step 7: Lint/format/types + full suite**

`uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src && uv run pytest tests/unit tests/integration -q --no-cov`

- [ ] **Step 8: Commit**

```bash
git add src/yas/email/payloads.py src/yas/email/builders.py tests/unit/test_email_builders.py
git commit -m "feat(email): resolve digest site names + build new_match_groups

gather_digest_payload now batch-resolves site_id->name for the new-match
offerings (fixing the long-standing empty-site bug where site_name
defaulted to '' and the row macro silently dropped it) and adds
program_type to each offering dict. The derived new_match_groups field on
DigestPayload nests the score-sorted matches by site -> program type via
_group_matches_by_site. The flat new_matches list is unchanged (still used
for the header count, empty-day skip, and LLM top-line)."
```

---

## Task 3: `show_site` flag on the offering-row macros

So grouped rows don't repeat the site that's in the group header. Default preserves all existing callers.

**Files:**
- Modify: `src/yas/email/templates/macros.j2`
- Modify: `tests/unit/test_email_render_pair.py`

- [ ] **Step 1: Write failing macro tests**

Add to `tests/unit/test_email_render_pair.py` (it already renders macros via `env.from_string`; mirror the existing `_offering` helper there):

```python
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
    tpl = env.from_string(
        f'{{% from "macros.j2" import {macro} %}}{{{{ {macro}(m) }}}}'
    )
    out = tpl.render(m=_offering(site_name="Park District", score=0.9))
    assert "Park District" in out
```

(Confirm the `_offering` helper in that file accepts `site_name`; it builds a base dict — add `site_name` to its base or pass via overrides.)

- [ ] **Step 2: Run, expect failure**

`uv run pytest tests/unit/test_email_render_pair.py -k show_site -v --no-cov`
Expected: FAIL — `show_site=false` still renders the site (param ignored / unknown).

- [ ] **Step 3: Add the `show_site` parameter to both macros**

In `src/yas/email/templates/macros.j2`, change the macro signatures and the site guard:

```jinja
{% macro offering_row_html(m, show_site=true) %}
<li>
  <strong>{{ m.offering_name }}</strong>
  {% if show_site and m.site_name %} @ {{ m.site_name }}{% endif %}
  ...
```

```jinja
{% macro offering_row_text(m, show_site=true) -%}
  - {{ m.offering_name }}{% if show_site and m.site_name %} @ {{ m.site_name }}{% endif %}...
```

(Only the site-name guard changes — every other fragment is untouched.)

- [ ] **Step 4: Run macro tests + the full render-pair file**

`uv run pytest tests/unit/test_email_render_pair.py -v --no-cov`
Expected: PASS (new + existing).

- [ ] **Step 5: Confirm no golden drift from existing callers**

`uv run pytest tests/unit/test_email_render_golden.py -v --no-cov`
Expected: PASS unchanged — `new_match`/others call the macro with no `show_site` arg, so default `true` preserves output byte-for-byte.

- [ ] **Step 6: Lint/format/types**

`uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src`

- [ ] **Step 7: Commit**

```bash
git add src/yas/email/templates/macros.j2 tests/unit/test_email_render_pair.py
git commit -m "feat(email): optional show_site flag on offering-row macros

offering_row_html/_text gain show_site=true (default unchanged). The
grouped digest section will pass show_site=false so rows don't repeat the
site already shown in the group header. All existing callers omit the arg
and render identically."
```

---

## Task 4: Grouped New Matches templates + golden re-baseline

Render the grouping, and re-baseline the digest goldens (the change *is* the golden diff).

**Files:**
- Modify: `src/yas/email/templates/digest.html.j2`
- Modify: `src/yas/email/templates/digest.txt.j2`
- Modify: `tests/unit/test_digest_golden.py` (build `new_match_groups` in fixtures + multi-site case)
- Re-baseline: `tests/golden/digest/with_matches.{txt,html}`
- Create: `tests/golden/digest/multi_site.{txt,html}`

**Content note (intentional):** the text digest's New Matches rows currently use an inline format with NO registration URL. This task switches them to `offering_row_text(m, show_site=false)`, which DRYs the template and **adds a per-row registration link to text digests** — a small, deliberate content improvement within the New Matches section. Call it out in the commit.

- [ ] **Step 1: Update `test_digest_golden.py` fixtures to build groups**

The golden fixtures construct `DigestPayload` directly (bypassing the builder), so they must populate `new_match_groups` via the helper, exactly as the builder does.

In `tests/unit/test_digest_golden.py`:
- Import the helper: `from yas.email.builders import _group_matches_by_site`.
- In `_payload_with_matches()`, ensure each match dict has a `program_type` key (e.g. `"program_type": "soccer"`), and set `new_match_groups=_group_matches_by_site(new_matches)` on the returned payload. (The match dict already has `site_name="Park District"`.)
- Add a `_payload_multi_site()` factory: two sites (e.g. "Park District" with soccer + swim, "YMCA" with dance), three matches, scores 0.91/0.80/0.66, each dict with `site_name`, `site_id`, `program_type`, `score`, `start_date`, `price_cents`, `registration_url`. Build `new_match_groups` via the helper. Add it to the `_CASES` list with top_line `"Ada — 3 new matches"`.

- [ ] **Step 2: Update the HTML template New Matches section**

In `src/yas/email/templates/digest.html.j2`, replace the New Matches block:

```jinja
{% if payload.new_matches %}
<h1 style="font-size: 1em; border-bottom: 1px solid #ccc;">New Matches ({{ payload.new_matches|length }})</h1>
{% for site in payload.new_match_groups %}
<h2 style="font-size: 0.95em; margin: 12px 0 4px;">{{ site.site_name or "Unknown site" }}</h2>
{% for prog in site.programs %}
<h3 style="font-size: 0.85em; color: #555; margin: 6px 0 2px;">{{ prog.program_label }}</h3>
<ul style="margin-top: 0;">
  {% for m in prog.offerings %}
  {{ offering_row_html(m, show_site=false) }}
  {% endfor %}
</ul>
{% endfor %}
{% endfor %}
{% endif %}
```

- [ ] **Step 3: Update the text template New Matches section**

In `src/yas/email/templates/digest.txt.j2`, add the macro import at the top (after `{% extends %}`):

```jinja
{% from "macros.j2" import offering_row_text %}
```

Replace the NEW MATCHES block:

```jinja
{% if payload.new_matches -%}
NEW MATCHES ({{ payload.new_matches|length }}):
{% for site in payload.new_match_groups -%}
{{ site.site_name or "Unknown site" }}:
{% for prog in site.programs -%}
  {{ prog.program_label }}:
{% for m in prog.offerings -%}
  {{ offering_row_text(m, show_site=false) }}
{% endfor -%}
{% endfor -%}
{% endfor -%}
{%- endif %}
```

(Watch indentation/whitespace — the env uses `trim_blocks` + `lstrip_blocks`. The exact rendered shape is locked by the golden in the next step; iterate the template until the golden looks right, then capture it.)

- [ ] **Step 4: Run the golden test — expect FAIL (old goldens), inspect, re-baseline**

`uv run pytest tests/unit/test_digest_golden.py -v --no-cov`
Expected: FAIL for `with_matches` (layout changed) and `multi_site` (no golden yet).

Re-capture goldens with a one-shot script (mirrors how the digest goldens were originally captured):

```bash
uv run python -c "
from tests.unit.test_digest_golden import _payload_with_matches, _payload_multi_site
from yas.email import render_digest_payload
from pathlib import Path
out = Path('tests/golden/digest')
for name, payload, top in [
    ('with_matches', _payload_with_matches(), 'Ada — 1 new match'),
    ('multi_site', _payload_multi_site(), 'Ada — 3 new matches'),
]:
    r = render_digest_payload(payload, top)
    (out / f'{name}.txt').write_text(r.body_plain)
    (out / f'{name}.html').write_text(r.body_html)
print('captured')
"
```

(Use the actual `top_line` values that `_CASES` uses for each case so the golden matches the test. If `_payload_with_matches`'s case in `_CASES` uses a specific top_line, reuse it verbatim.)

- [ ] **Step 5: Manually inspect the re-baselined goldens**

```bash
sed -n '1,40p' tests/golden/digest/multi_site.txt
```
Confirm: New Matches header with total count, then per-site headers, per-program sub-headers, activity rows beneath, no per-row site repetition, and (text) the registration URL now present on rows. Open `multi_site.html` in a browser to confirm the nesting reads cleanly.

- [ ] **Step 6: Run golden test, expect PASS**

`uv run pytest tests/unit/test_digest_golden.py -v --no-cov`

- [ ] **Step 7: Full verification**

`uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src && uv run pytest tests/unit tests/integration -q --no-cov`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/yas/email/templates/digest.html.j2 src/yas/email/templates/digest.txt.j2 tests/unit/test_digest_golden.py tests/golden/digest/
git commit -m "feat(email): group digest New Matches by site -> program type

The New Matches section now renders site headers, program-type
sub-headers, and the activities beneath each, replacing the flat
site-less list. Uses offering_row_*(show_site=false) so rows don't repeat
the site in the header. The text digest rows adopt offering_row_text,
which also adds a per-row registration link to text digests (small
intentional content improvement). Re-baselines the with_matches digest
golden and adds a multi_site golden exercising two sites x program types."
```

---

## Final verification

- [ ] `uv run pytest tests/unit tests/integration -q --no-cov` green.
- [ ] `uv run ruff check src tests` and `uv run ruff format --check src tests` clean.
- [ ] `uv run mypy src` clean.
- [ ] Manual: open `tests/golden/digest/multi_site.html` and `with_matches.html` in a browser — site → program → activity nesting reads cleanly; no "@ Site" repetition under a site header.
- [ ] Confirm other digest sections (Starting Soon, Registration Opens, Delivery Issues) and the empty/under-threshold states are visually unchanged in the goldens.

## Notes

- **Scope discipline:** only the New Matches section changes. Starting Soon / Registration Opens / Delivery Issues / empty states are untouched — verify their golden output is byte-identical except where the New Matches block sits.
- **One source of truth:** `new_match_groups` is derived from `new_matches` via the pure helper. Both the builder (real path) and the golden fixtures (test path) call `_group_matches_by_site` — never hand-build the nested structure.
- @superpowers:test-driven-development — failing test first for Tasks 1–3. Task 4 is template+golden; the golden re-baseline is the verification.
