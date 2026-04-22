#!/usr/bin/env bash
set -euo pipefail

# Phase 2 end-of-phase manual smoke. Requires:
#   - Docker Compose
#   - A real YAS_ANTHROPIC_API_KEY in .env
#   - Network access to www.lilsluggerschicago.com

cd "$(dirname "$0")/.."

if ! grep -q '^YAS_ANTHROPIC_API_KEY=sk-' .env 2>/dev/null || grep -q '^YAS_ANTHROPIC_API_KEY=sk-test-nonop$' .env; then
  echo "ERROR: .env must set YAS_ANTHROPIC_API_KEY to a real key." >&2
  exit 2
fi

rm -f data/activities.db data/activities.db-shm data/activities.db-wal
docker compose up -d yas-migrate
docker compose logs yas-migrate | tail -5
docker compose up -d yas-worker yas-api
sleep 10

echo "Registering Lil Sluggers..."
curl -sS -X POST localhost:8080/api/sites \
  -H 'content-type: application/json' \
  -d '{
    "name": "Lil Sluggers Chicago",
    "base_url": "https://www.lilsluggerschicago.com/",
    "needs_browser": true,
    "pages": [
      {"url": "https://www.lilsluggerschicago.com/spring-session-24.html", "kind": "schedule"}
    ]
  }' | jq .

echo "Waiting 90s for scheduler tick + crawl + extract..."
sleep 90

echo ""
echo "--- site detail ---"
curl -sS localhost:8080/api/sites/1 | jq .

echo ""
echo "--- offerings ---"
sqlite3 data/activities.db 'select id, name, program_type, age_min, age_max, start_date, time_start from offerings'

echo ""
echo "--- last 5 crawl_runs ---"
sqlite3 data/activities.db 'select id, site_id, status, pages_fetched, changes_detected, llm_calls, printf("%.5f", llm_cost_usd), substr(coalesce(error_text,""),1,120) from crawl_runs order by id desc limit 5'

echo ""
echo "Re-running crawl-now to verify cache hit on second run..."
curl -sS -X POST localhost:8080/api/sites/1/crawl-now | jq .
sleep 45

echo ""
echo "--- last 5 crawl_runs after second run ---"
sqlite3 data/activities.db 'select id, site_id, status, pages_fetched, changes_detected, llm_calls, printf("%.5f", llm_cost_usd), substr(coalesce(error_text,""),1,120) from crawl_runs order by id desc limit 5'

echo ""
echo "done. bringing compose down..."
docker compose down
