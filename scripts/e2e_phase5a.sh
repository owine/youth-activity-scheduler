#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! grep -q '^YAS_ANTHROPIC_API_KEY=sk-' .env 2>/dev/null; then
  echo "ERROR: .env must set YAS_ANTHROPIC_API_KEY" >&2; exit 2
fi

COMPOSE="docker compose -f docker-compose.yml"
[ "$(uname)" = "Darwin" ] && COMPOSE="$COMPOSE -f docker-compose.macos.yml"

$COMPOSE down -v 2>/dev/null || true
$COMPOSE build yas-api yas-worker yas-migrate
$COMPOSE up -d yas-migrate
$COMPOSE up -d yas-worker yas-api
sleep 8

echo "--- seed e2e fixtures ---"
$COMPOSE exec -T yas-api uv run python - "sqlite+aiosqlite:////data/activities.db" < scripts/seed_e2e.py

echo "--- run playwright ---"
cd frontend
PLAYWRIGHT_BASE_URL=http://localhost:8080 npx playwright test
cd ..

$COMPOSE down -v
