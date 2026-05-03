# v1 Completion Roadmap (Reset)

**Date:** 2026-04-30
**Status:** Draft — awaiting user review.
**Master design:** `docs/superpowers/specs/2026-04-21-youth-activity-scheduler-design.md`

## 1. Why this document exists

The project shipped Phases 1–5d-1 in nine days through 11 individual specs, each brainstormed in isolation against its immediate predecessor. None reconciled back to the master design's §7 (Web UI) and §10 (Terminal state for v1).

Result: production deploy on 2026-04-30 hits **5 of 8** master-design terminal criteria, leaves 2 blocked by missing setup-flow UI, has 1 in observation, and covers ~3 of the 9 master-spec UI pages.

This document is the realignment. It is **not** a deep spec of every remaining phase — premature for any phase whose UX will be reshaped by real usage. It names the remaining phases, sequences them, justifies the order, and points to the next brainstorming target.

## 2. What shipped (chronological)

| Phase | What | Merged |
|---|---|---|
| 1 | Foundation (data model, FastAPI scaffold, alembic) | pre-`790f223` lineage |
| 2 | Crawl pipeline (adapters, LLM cache, scheduler) | ✓ |
| 3 | Matching + watchlist | ✓ |
| 3.5 | Site discovery (`/discover` Claude-ranked candidates) | ✓ |
| 4 | Alerting (channels, dedup, routing, digest) | ✓ |
| 5a | Read-only dashboard (Inbox, Sites, per-kid Matches/Watchlist) | ✓ |
| 5b-1a | Alert close lifecycle (backend) | `790f223` |
| 5b-1b | Alert close (frontend mutation, optimistic + rollback) | `f7816a1` |
| 5c-1 | Per-kid calendar (week + month) | `9cae68b` |
| 5c-2 | Calendar match overlay + click-to-enroll | `c5fdf9e` |
| 5d-1 | Site/offering mute (one-click) | `5aa5d69` |
| infra | GHCR multi-arch publish + compose split | `b817c86` |
| hotfix | Inherited HEALTHCHECK disabled on worker/migrate | `0f98362` |
| 6-1 | Add/Edit Kid form (closes criterion #6) | ✓ |
| 6-2 | Add Site wizard + discovery picker (closes criterion #1) | ✓ |
| 6-3 | Watchlist add/edit (per-kid mutations) | ✓ |
| 6-4 | Site detail mutations (Crawl-now / Pause) | ✓ |
| 7-1 | Settings page | ✓ |
| 7-2 | Offerings browser | ✓ |
| 7-3 | Enrollments page | ✓ |
| 7-4 | Alerts page (Outbox + digest preview) | #29 |
| 8-1 | Combined multi-kid calendar | #37 |
| 8-2 | Holiday / school-year calendar integration | #38 |
| 8-3 | Watchlist matches visually distinct on calendar | #39 |
| 8-4 | Bulk close-many alerts | #40 |
| 8-5 | E2E tests in CI | #33 |
| 8-6 | Prettier sweep + frontend-check CI gate | #32 |
| infra | OCI labels + git_sha at /healthz | #34, #35 |
| infra | Python 3.14 alignment in CI | #38 (bundled) |

## 3. The deviations, named

The master design implied **Phase 5 = "self-hosted web UI"** (§7's nine pages). We split it ad-hoc:

| Original intent | Actual outcome |
|---|---|
| **5b** = "Add Site wizard + mutation UIs + alert ack/dismiss" | Only the **alert ack/dismiss** third shipped (as 5b-1a + 5b-1b). Add Site wizard + kid mutation UIs were carved out and never picked back up. |
| **Calendar** = part of 5a's vision | Deferred from 5a; introduced as 5c-1 + 5c-2 later, including click-to-enroll which expanded beyond the master § 7 spec. |
| **Site/offering mute** = no original phase | Added as 5d-1 to close terminal criterion #5 explicitly. Not in master § 7. |

Each deviation was individually defensible (close-the-loop UX wins). The cumulative effect is that **the master design's terminal criterion #1 — "user can add a site via the UI in <2 min" — has no UI**. The whole setup flow is curl-only.

## 4. Audit against master § 10 terminal state

| # | Criterion | Status | Blocking phase |
|---|---|---|---|
| 1 | User can add a site via the UI in <2 min | ✅ Phase 6-2 (2026-04-30) | — |
| 2 | New matching offering → alert within 10 min | ✓ | — |
| 3 | Reg-opens countdown (T−24h / T−1h / T) | ✓ | — |
| 4 | 30-day run, <$5 LLM, zero silent failures | ⏳ in observation | **Phase 9** |
| 5 | Disable alerts for site/offering with one click | ✓ | — |
| 6 | School hours → unavailability blocks filter matches | ⚠️ backend ✓, no UI | **Phase 6-1** |
| 7 | Enrolled creates linked block; cancelled restores | ✓ | — |
| 8 | Calendar week view for a kid | ✓ | — |

## 5. Audit against master § 7 — nine pages

| # | Page | Shipped? |
|---|---|---|
| 1 | Dashboard | ✓ Inbox |
| 2 | Offerings browser (cross-kid) | ✅ Phase 7-2 (2026-05-01) |
| 3 | Calendar (per-kid + combined) | ✅ per-kid ✓; combined ✅ Phase 8-1 (2026-05-02) |
| 4 | Kids: list + detail editing | ✅ list + Add/Edit form (Phase 6-1) |
| 5 | Sites: list + detail + Add Site flow | ✅ list/detail + Crawl-now/Pause (Phase 6-4) + Add Site wizard (Phase 6-2) |
| 6 | Watchlist: cross-kid + mutations | ✅ per-kid mutations (Phase 6-3); cross-kid view deferred (low value for single-household; Phase 8 if needed) |
| 7 | Enrollments: list, status transitions | ✅ Phase 7-3 (2026-05-01) |
| 8 | Alerts: outbox, resend, digest preview | ✅ Phase 7-4 (2026-05-02) |
| 9 | Settings | ✅ Phase 7-1 (2026-05-01) |

## 6. Remaining roadmap to v1

Three build phases + one observation phase. Renumbered to Phase 6 / 7 / 8 / 9 (the original `5e/5f/5g/5h` sub-letter scheme had stretched past usefulness). Anything past v1's master scope (multi-tenant, mobile app, ICS export) becomes Phase 10+.

### Phase 6 — Setup-flow mutation UIs

**Why first:** the only phase that closes blocked terminal criteria (#1 and #6). Unblocks "user can set up the app without touching curl." Concrete and unblocked by usage data — every household has to do these once.

- **Phase 6-1: Add Kid + Edit Kid form.** DOB, interests, school weekdays/times/year ranges/holidays, max distance, alert thresholds. Reuses the canonical mutation pattern from 5b-1b. Closes criterion #6.
- **Phase 6-2: Add Site wizard.** Two-path flow: paste URL → either (a) confirm a known schedule URL, or (b) call `/api/sites/{id}/discover` and let the user pick from Claude-ranked candidates. Closes criterion #1. The discover-then-pick step is the most interesting UX in the whole roadmap.
- **Phase 6-3: Watchlist add/edit.** Per-kid view (already exists, read-only) gains add/remove. Cross-kid view introduced.
- **Phase 6-4: Site detail mutations.** "Crawl now" + "Pause" buttons on the existing site detail page. Already-built backend routes (`POST /api/sites/{id}/crawl-now`, the `active: bool` field).

Estimated size: 4 PRs, ~2 days of work each.

### Phase 7 — Remaining master § 7 pages

**Why second:** rounds out the master vision but each item is curl-around-able. Real usage will reshape priorities here — defer detailed brainstorming until Phase 6 ships and you've used v1 for a couple weeks.

- **Phase 7-1: Settings page.** Home location (with Nominatim preview), channel configs (SMTP/HA/ntfy/Pushover JSON editor or form), routing matrix, digest time, cost cap, quiet hours.
- **Phase 7-2: Offerings browser.** Cross-kid filters/sort, match-reason chips. Closest to the master design's vision of a "browse mode."
- **Phase 7-3: Enrollments list page.** Per-kid history, status transitions, linked unavailability viewer.
- **Phase 7-4: Alerts outbox + digest preview.** Read views over `alerts` table beyond the inbox window. Resend button (route exists).

Estimated size: 4 PRs.

### Phase 8 — Polish & hardening

**Why third:** quality-of-life. None block v1 terminal state.

- Phase 8-1: ✅ shipped 2026-05-02. Multi-kid combined calendar (deferred from 5c-1) — new top-level `/calendar` route, color-by-kid, kid + event-type filters in URL search params.
- Phase 8-2: ✅ shipped 2026-05-02. Calendar respects `kid.school_holidays` (school blocks skip holiday dates) and emits explicit `holiday` events for in-range, in-school-year holidays.
- Phase 8-3: ✅ shipped 2026-05-02. Match events now carry a `watchlist_hit: bool` flag (set from `Match.reasons.watchlist_hit`); frontend renders watchlist-driven matches with a solid gold ring vs the default dashed border.
- Phase 8-4: ✅ shipped 2026-05-02 (close-many alerts only — mute-many and enroll-many deferred until usage signals justify them). New `POST /api/alerts/bulk/close` + multi-select on Outbox.
- Phase 8-5: ✅ shipped 2026-05-02. E2E tests automated in CI as a new `e2e` job. Plain processes (no docker-in-CI), reuses `python -m yas api` + `YAS_STATIC_DIR` to serve the SPA. `scripts/e2e_phase5a.sh` preserved for local docker-compose dogfooding.
- Phase 8-6: ✅ shipped 2026-05-02. Fixed 26 pre-existing prettier failures + wired `frontend-check` CI job (typecheck/lint/format/test). Audit revealed the deeper gap: no frontend gates ran in CI at all — fixed in the same PR.

Estimated size: 5-6 small PRs.

### Phase 9 — Observation

**Not a build phase.** Closes criterion #4 by running v1 for 30 calendar days and observing:

- LLM spend stays under $5
- No silent failures in worker logs
- Match quality is subjectively useful (the only criterion that's not mechanically measurable)

**Gated by Phase 6.** The observation clock starts when there is something to observe — i.e., when at least one site + one kid have been seeded via the new UI. Until then, v1 is deployed but inert.

## 7. Sequencing rationale

```
Phase 6 (blocking) ──► Phase 7 (informed by usage) ──► Phase 8/Phase 9 (parallel)
```

- **Phase 6 gates everything else.** It's not just "the next phase" — without setup-flow UI, you cannot meaningfully use v1, which means:
  - You cannot observe terminal criterion #4 (no usage = no LLM spend, no silent failures to detect)
  - You cannot reprioritize Phase 7 based on real-world friction (no friction without real use)
  - The "deploy and let it cook" advice given earlier was premature; v1 is deployed but inert
- **Phase 7 after Phase 6** — rounds out master § 7. By the time Phase 6 ships and you've used the app for 1-2 weeks, your priority order within Phase 7 will be different from what's in §6.Phase 7 above. That's the point — the doc names the items, the order gets re-decided after usage.
- **Phase 8/Phase 9 in parallel** — once Phase 7 is well underway, Phase 8 (polish) and Phase 9 (observation) can interleave. Phase 9 is a calendar timer that needs nothing from us.

## 8. Methodology change: re-audit after every phase

The deviation root cause was **no re-audit step**. Each phase's spec referenced its predecessor but never reconciled to the master design. Going forward:

1. Every phase spec gets a section: *"Master § 10 terminal criteria delta"* — which criterion this phase closes (or "none — polish only").
2. Every phase plan's exit criteria include: *"verify master § 10 status changed as expected."*
3. After each merged phase, this roadmap doc is updated with the new shipped row + reconciliation row. Treat it as a living document.

## 9. Open questions deferred from prior specs

These remain open from each shipped phase's "Out of scope":

- **Pushover channel** (master § 9) — ✅ already shipped during Phase 7-1 Settings work (`PushoverChannel` + Settings UI + routing matrix + test-send all wired). The roadmap line was a pre-Phase-7 carry-over.
- **Gotify channel** (master § 9) — ❌ not implemented. Small slice when actually needed (mirror PushoverChannel against Gotify's HTTP API).
- **`.ics` calendar export** (master § 9) — ✅ shipped 2026-05-03. Per-kid feed at `GET /api/kids/{id}/calendar.ics`; default −7d/+90d window, 400-day cap. Match suggestions excluded; enrollment/unavailability/holiday included. Subscribe link on per-kid calendar page. (.ics *import* still deferred.)
- **Driving-time vs great-circle distance** (master § 9) — only if real usage shows great-circle is misleading
- **Soft conflicts as warnings** (master § 9) — e.g., "offering ends at 3:15pm but school ends at 3:00pm — too tight?"
- **Mute reasons / per-channel mute** (5d-1 §1.2) — only if mute volume justifies it
- **User-controllable match score threshold** (5c-2 §1.2) — only if 0.6 fixed feels wrong
- **Watchlist on calendar** (5c-1 §1.2) — ✅ shipped 2026-05-02 as Phase 8-3
- **Holiday calendar integration** (5c-1 §1.2) — ✅ shipped 2026-05-02 as Phase 8-2
- **Bulk mute-many offerings** (8-4 deferral) — only if mute volume becomes routine toil
- **Bulk enroll-many** (8-4 deferral) — probably never (enrollment is high-stakes per kid)

## 10. Next step

**Phase 9 — 30-day observation.** Phases 6, 7, and 8 all shipped (2026-04-30 → 2026-05-02). Master §7 has all 9 pages met; master §10 has 7 of 8 terminal criteria — only #4 (30-day run, <$5 LLM, zero silent failures) remains, and it closes by passage of time + active observation rather than code.

The observation clock starts when there is something to observe. Use the now-complete UI to seed at least one site + one kid, then watch:

1. Trailing LLM spend (sum `CrawlRun.llm_cost_usd`) stays under $5/30d.
2. No `ERROR`-level worker log entries; no `CrawlRun.status="error"` rows with non-empty `error_text`.
3. Match volume is non-zero per active kid each week (subjective check on quality).

After 30 days, if all three signals are green, mark criterion #4 ✓ and v1 is shipped. The deferred questions in §9 above become candidate Phase 10+ work, prioritized by what real usage exposes as friction.
