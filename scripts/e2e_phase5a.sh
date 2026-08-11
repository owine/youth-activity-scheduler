#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. "$(dirname "$0")/lib.sh"

if ! grep -q '^YAS_ANTHROPIC_API_KEY=sk-' .env 2>/dev/null; then
  echo "ERROR: .env must set YAS_ANTHROPIC_API_KEY" >&2; exit 2
fi

COMPOSE=$(compose_cmd)

# Regression guard for exactly that failure mode.
assert_local_build "$COMPOSE" yas-worker yas-api || exit 2

$COMPOSE down -v 2>/dev/null || true
$COMPOSE build yas-api yas-worker
$COMPOSE up -d yas-worker yas-api
sleep 8

echo "--- seed e2e fixtures ---"
# Bare `python`, not `uv run python`: the image no longer ships the uv binary
# (it's bind-mounted at build time only), and PATH prefers /app/.venv/bin.
$COMPOSE exec -T yas-api python - "sqlite+aiosqlite:////data/activities.db" < scripts/seed_e2e.py

echo "--- run playwright ---"
cd frontend
PLAYWRIGHT_BASE_URL=http://localhost:8080 npx playwright test
cd ..

$COMPOSE down -v
