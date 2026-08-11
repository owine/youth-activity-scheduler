#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
. "$(dirname "$0")/lib.sh"

if ! grep -q '^YAS_ANTHROPIC_API_KEY=sk-' .env 2>/dev/null; then
  echo "ERROR: .env must set YAS_ANTHROPIC_API_KEY" >&2; exit 2
fi

COMPOSE="docker compose -f docker-compose.yml"
[ "$(uname)" = "Darwin" ] && COMPOSE="$COMPOSE -f docker-compose.macos.yml"
# docker-compose.yml pins `image: ghcr.io/...:latest` with no `build:`, so
# without this override `$COMPOSE build` below is a silent no-op ("No services
# to build") and `up` pulls the published image — the suite would then validate
# whatever is on GHCR rather than the working tree, and pass. dev.yml swaps in
# `build: .`. It goes last because it overrides `image:` from the base file.
COMPOSE="$COMPOSE -f docker-compose.dev.yml"

# Regression guard for exactly that failure mode.
assert_local_build $COMPOSE || exit 2

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
