# Digest Site → Program Grouping — Design

**Date:** 2026-05-20
**Status:** Draft (spec review pending)
**Scope:** Backend digest rendering (`src/yas/email/`). No API or frontend changes.

## Problem

The daily digest's "New Matches" section is a flat, score-sorted list of activities with no indication of **which site/organization** each activity came from. Worse, the site name is missing entirely: `gather_digest_payload` builds each match dict via `_offering_to_dict(o, m.score)` without passing a `site_name`, so it defaults to `""`, and the `offering_row_*` macro's `{% if m.site_name %}` guard silently drops it. A parent reading the digest sees activity names with no source attribution.

The request: show what site/program each activity was detected from, grouping the activities under each site and, within a site, under each program type.

## Goals

1. Group the digest's **New Matches** section by **site → program type → activities**.
2. Fix the latent empty-site bug so site names are actually resolved and shown (this is a prerequisite for grouping).
3. Preserve the existing "highest-signal first" ordering: a parent should still see the strongest match near the top.
4. Keep the change isolated to the New Matches section and the digest builder — no churn in other sections, other email kinds, or the immediate-alert path.

## Non-goals

- Grouping the "Starting Soon" or "Registration Opens" sections. Those are deliberately time-ordered (by start date / open date); grouping by site would fight that ordering. They stay flat.
- Any change to the immediate-alert renderers (`new_match`, `reg_opens_*`, etc.). They already resolve site names and render single offerings or short lists; grouping is a digest concern.
- A new `program`/category data model. `Offering.program_type` (an existing enum) is the inner grouping key as-is.
- Frontend or API changes. The digest-preview endpoint renders the same payload, so it inherits the new layout for free.

## Data model context

`Site (org/website) → Page (where detected) → Offering (the activity)`. `Offering` carries `site_id` and `program_type: ProgramType` (a `StrEnum`: `soccer`, `dance`, `swim`, …, default `unknown`). The digest already joins `Match → Offering`; it does not currently join `Site`.

## Design

### Payload shape

`DigestPayload` keeps its existing flat `new_matches: list[dict]` (still used for the header count, the empty-day skip check in `yas.worker.digest_loop`, and the LLM top-line generator). It gains one derived field:

```python
new_match_groups: list[dict[str, Any]] = field(default_factory=list)
# Each entry is one site:
#   {
#     "site_id": int,
#     "site_name": str,            # "" only if the Site row is somehow missing
#     "programs": [
#       {
#         "program_type": str,     # raw enum value, e.g. "soccer"
#         "program_label": str,    # display form, e.g. "Soccer"; "unknown" -> "Other"
#         "offerings": list[dict], # the existing offering-row dicts, score desc
#       },
#       ...                        # programs ordered by their best offering's score desc
#     ],
#   },
#   ...                            # sites ordered by their best offering's score desc
```

`new_match_groups` is a pure reorganization of `new_matches` — same dicts, regrouped. It is not a second query.

### Builder changes (`gather_digest_payload`)

1. **Resolve site names** (fixes the bug): after building `new_matches`, collect the distinct `site_id`s, run one `select(Site).where(Site.id.in_(site_ids))`, build a `{site_id: name}` map, and populate `site_name` on each new-match dict. This mirrors the batch-resolve `build_new_match` already does. (Only the `new_matches` list needs this for now; `starting_soon`/`registration_calendar` are unchanged and out of scope.)
2. **Add `program_type`** to `_offering_to_dict` output so the inner grouping key is present on every offering dict. The key is always set (`Offering.program_type` defaults to `unknown`). Adding a key to this dict is backward-compatible: existing templates ignore unknown keys, and the immediate-alert offering rows simply don't read it.
3. **Group:** call a new pure helper `_group_matches_by_site(new_matches) -> list[dict]` and store the result as `new_match_groups`.

### Grouping helper (`_group_matches_by_site`)

Pure function over the already-score-sorted flat list — no DB, no I/O:

- Bucket offerings by `site_id` (carrying `site_name`), then within each site bucket by `program_type`.
- Order: sites by their best (max) offering score descending; programs within a site by their best offering score descending; offerings within a program by score descending (already sorted, preserved as a stable sub-order).
- `program_label`: `"Other"` for `unknown`, otherwise `program_type.replace("_", " ").title()` (e.g. `martial_arts` → "Martial Arts"). Acronym imperfections (e.g. "Stem") are acceptable; not worth special-casing.
- Offerings missing a score (shouldn't happen for digest matches, which always have a `Match.score`) sort last within their program.

### Template changes

Only the **New Matches** block of `digest.html.j2` and `digest.txt.j2` changes. It iterates `payload.new_match_groups`: each site is a sub-header, each program a nested heading, each activity a row rendered by the existing `offering_row_*` macro.

The header count stays total activities: `New Matches ({{ payload.new_matches|length }})`.

**Per-row site omission:** inside a grouped view, repeating "@ Park District" on every row under a "Park District" header is noise. `offering_row_html` / `offering_row_text` gain an optional `show_site=true` parameter (default preserves current behavior for `new_match` and all other callers). The grouped digest section calls the macros with `show_site=false`.

Rendered shape (HTML, illustrative):

```
New Matches (4)
─────────────────
Park District
  Soccer
    • Soccer Camp · Jun 1 · $150.00 · score 0.91 · Register
    • Lil Kickers · Jun 8 · $90.00 · score 0.74 · Register
  Swimming
    • Summer Swim · Jun 15 · $140.00 · score 0.80 · Register
YMCA
  Dance
    • Ballet I · Jun 3 · $120.00 · score 0.66 · Register
```

The text template mirrors this with indentation. Other sections (Starting Soon, Registration Opens, Delivery Issues) and all empty/under-threshold states are untouched.

## Error handling

- **Missing Site row:** `site_name` falls back to `""`; the offering still groups under its `site_id`. The grouping helper never raises — it buckets and sorts dicts.
- **`program_type`:** always present (enum default `unknown` → label "Other"), so the inner key is never missing.
- **StrictUndefined:** the grouped template reads only fields the builder always populates (`site_name`, `program_label`, offering-dict keys), so no new undefined-field exposure.

## Testing

- **Unit — `_group_matches_by_site`** (no DB): a flat list spanning two sites and multiple program types asserts site order (best score), program order within site (best score), offering order within program (score desc), and `program_label` mapping (`unknown` → "Other", underscore/titlecase).
- **Unit — `gather_digest_payload`** (extend the existing digest builder test): assert `site_name` is now populated on `new_matches` (regression guard for the bug) and that `new_match_groups` nests correctly for a seeded two-site scenario.
- **Macro — `test_email_render_pair.py`**: assert `offering_row_*(m, show_site=false)` omits the site fragment while the default still includes it.
- **Golden — digest**: update the existing `with_matches` golden (currently a flat, site-less row) to the grouped layout, and add a **multi-site** golden scenario (two sites, ≥2 program types) so grouping is exercised in a rendered snapshot. Both `.txt` and `.html`.

## Migration & rollout

Internal-only; no flags. Single feature branch:

1. Add `program_type` to `_offering_to_dict`; add `_group_matches_by_site` + unit test.
2. Resolve site names in `gather_digest_payload`; populate `new_match_groups`; extend builder test (asserts the bug fix).
3. Add `show_site` param to the macros + macro test.
4. Update digest templates' New Matches section.
5. Re-baseline the `with_matches` digest golden; add the multi-site golden scenario + seeder.

Each step keeps the suite green. The digest goldens change deliberately (grouping is the point); the change is reviewed as a golden diff.

## YAGNI

- No grouping of Starting Soon / Registration Opens.
- No collapsing/threshold ("show first N per site") — render all matches grouped; revisit only if real digests get unwieldy.
- No per-site links or site-level metadata beyond the name.
- No typed dataclasses for the group structure — nested dicts match the existing `DigestPayload` section style and keep the template StrictUndefined-friendly.

## Open questions

None blocking. Decisions taken during brainstorming:
- Grouping key: site → program type. ✅
- Sections: New Matches only. ✅
- Ordering: sites by best match score; programs by best score within site; activities by score. ✅
- Per-row site omitted inside groups (it's in the header). ✅
