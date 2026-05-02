# Phase 8-5: E2E Tests in CI — Design

**Date:** 2026-05-02
**Status:** Approved
**Roadmap:** `docs/superpowers/specs/2026-04-30-v1-completion-roadmap.md` §6 Phase 8-5

## 1. Problem

`scripts/e2e_phase5a.sh` is a manual gate today. It brings up the full docker-compose stack (`yas-migrate`, `yas-worker`, `yas-api`), seeds via `scripts/seed_e2e.py`, and runs `npx playwright test` from `frontend/`. It's only run when the developer remembers to run it locally — which means e2e regressions can land on `main`.

The existing e2e suite is small but real: 4 Playwright tests across `frontend/e2e/{inbox,deep-link,kid-matches}.spec.ts`. All are read-side smokes against seeded fixtures; none exercise the LLM or worker paths.

**Goal:** every PR and push to `main` automatically runs these 4 e2e specs and blocks merge on failure.

## 2. Approach: plain processes, no docker-compose-in-CI

The API already serves the built SPA via `YAS_STATIC_DIR` (see `src/yas/web/spa_fallback.py:13-19`). One uvicorn process serves both `/api/*` and the static SPA bundle, mirroring the prod deployment.

This means CI doesn't need docker-compose orchestration at all. The bash script's compose-in-compose dance is optimized for local dogfooding (testing the actual container build); CI can run plain Python + Node processes against the same source. Faster, no docker-in-docker overhead, fewer moving parts.

## 3. New `e2e` job in `.github/workflows/ci.yml`

```yaml
e2e:
  runs-on: ubuntu-latest
  env:
    YAS_ANTHROPIC_API_KEY: sk-test-nonop
    YAS_DATABASE_URL: sqlite+aiosqlite:///data/activities.db
    YAS_STATIC_DIR: ${{ github.workspace }}/frontend/dist
  steps:
    - uses: actions/checkout@<sha>  # v6.0.2
    - uses: astral-sh/setup-uv@<sha>  # v8.1.0 (cache enabled)
    - uses: actions/setup-node@<sha>  # v5.0.0
      with:
        node-version: 24.15.0
        cache: npm
        cache-dependency-path: frontend/package-lock.json
    - run: uv python install 3.12
    - run: uv sync --all-extras --dev
    - run: npm ci
      working-directory: frontend
    - run: npm run build
      working-directory: frontend
    - run: mkdir -p data && uv run alembic upgrade head
    - run: uv run python scripts/seed_e2e.py "$YAS_DATABASE_URL"
    - run: npx playwright install --with-deps chromium
      working-directory: frontend
    - name: Start API in background
      env:
        YAS_PORT: "8080"
      run: |
        uv run python -m yas api &
        echo $! > /tmp/yas-api.pid
    - name: Wait for /healthz
      run: |
        for i in {1..30}; do
          if curl -fsS http://localhost:8080/healthz >/dev/null; then exit 0; fi
          sleep 1
        done
        echo "API did not become ready" >&2; exit 1
    - run: PLAYWRIGHT_BASE_URL=http://localhost:8080 npx playwright test
      working-directory: frontend
    - name: Upload Playwright report on failure
      if: failure()
      uses: actions/upload-artifact@<sha>  # v4
      with:
        name: playwright-report
        path: |
          frontend/playwright-report/
          frontend/test-results/
        retention-days: 7
```

## 4. Decisions

**D1. New job vs steps in `frontend-check`.** New job. Isolation: e2e flakes shouldn't block the fast typecheck/lint/format/unit gates. Also, e2e doesn't need to re-run those gates' steps.

**D2. Plain processes vs docker-compose.** Plain. Three reasons: (a) faster — no compose pull/build overhead; (b) mirrors the API-serves-SPA prod setup via `YAS_STATIC_DIR`; (c) avoids docker-in-docker complications. The bash script is preserved for local use because it tests the actual container build, which CI's `docker-build` matrix already covers.

**D3. LLM key.** `YAS_ANTHROPIC_API_KEY=sk-test-nonop` — the same dummy already used in the `check` job. Verified safe: `seed_e2e.py` writes DB rows directly without LLM calls, and the 4 e2e specs are read-side. The dummy passes startup validation; if any e2e accidentally hits a real LLM path it will fail loudly rather than silently spending money.

**D4. Healthcheck endpoint.** `/healthz` exists at `src/yas/web/app.py:32`. CI polls it for up to 30 seconds before running Playwright.

**D4a. API entrypoint.** `python -m yas api` (matches the prod docker-compose `command:`) rather than direct `uvicorn yas.web.app:app`. The latter fails because `app` is constructed by `create_app(...)` factory at runtime — there's no module-level `app` symbol. Reusing the prod entrypoint also keeps CI honest about the wiring (LLM client, geocoder, settings) the real API gets.

**D5. Keep or remove `scripts/e2e_phase5a.sh`.** Keep. CI's plain-process path and the script's docker-compose path serve different purposes: CI gates regressions fast; the script tests the actual prod container shape. Phase 8-5 doesn't touch the script.

**D6. Chromium only.** Matches `playwright.config.ts`'s current single-browser setup. No multi-browser matrix; YAGNI for a single-household app.

**D7. Artifact upload on failure.** Yes. `frontend/playwright-report/` and `frontend/test-results/` give screenshots, traces, and HTML reports for debugging CI failures. 7-day retention is enough (PRs usually merge or get fixed within a week).

## 5. Master §10 terminal criteria delta

None. Phase 8-5 is polish. It hardens the existing test infrastructure without changing user-visible behavior.

## 6. Out of scope

- Adding new e2e tests (just CI-ize the existing 4)
- Multi-browser matrix (chromium-only, matches current config)
- Visual-regression tooling (Percy, Chromatic, etc.)
- Worker/LLM-path e2e coverage (the existing specs are read-side; expanding coverage is a separate spec if it ever matters)
- Replacing `scripts/e2e_phase5a.sh`
