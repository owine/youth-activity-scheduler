#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! grep -q '^YAS_ANTHROPIC_API_KEY=sk-' .env 2>/dev/null || grep -q '^YAS_ANTHROPIC_API_KEY=sk-test-nonop$' .env; then
  echo "ERROR: .env must set YAS_ANTHROPIC_API_KEY to a real key." >&2
  exit 2
fi

COMPOSE="docker compose"
if [ "$(uname)" = "Darwin" ]; then
  COMPOSE="$COMPOSE -f docker-compose.yml -f docker-compose.macos.yml"
fi

$COMPOSE down 2>/dev/null || true
$COMPOSE up -d yas-migrate
$COMPOSE up -d yas-worker yas-api
sleep 10

echo "--- set home location (geocoded immediately) ---"
curl -sS -X PATCH localhost:8080/api/household -H 'content-type: application/json' \
  -d '{"home_address":"2045 N Lincoln Park W, Chicago, IL","home_location_name":"Home","default_max_distance_mi":20.0}' | jq .

echo ""
echo "--- create kid ---"
curl -sS -X POST localhost:8080/api/kids -H 'content-type: application/json' -d '{
  "name":"Sam",
  "dob":"2019-05-01",
  "interests":["baseball"],
  "school_weekdays":["mon","tue","wed","thu","fri"],
  "school_time_start":"08:00",
  "school_time_end":"15:00",
  "school_year_ranges":[{"start":"2026-09-02","end":"2027-06-14"}]
}' | jq .

echo ""
echo "--- register Lil Sluggers ---"
curl -sS -X POST localhost:8080/api/sites -H 'content-type: application/json' -d '{
  "name":"Lil Sluggers Chicago",
  "base_url":"https://www.lilsluggerschicago.com/",
  "needs_browser":true,
  "pages":[{"url":"https://www.lilsluggerschicago.com/spring-session-24.html","kind":"schedule"}]
}' | jq .

echo ""
echo "Waiting 90s for scheduler + crawl + extract + rematch..."
sleep 90

echo ""
echo "--- offerings ---"
$COMPOSE exec -T yas-api sqlite3 /data/activities.db \
  'select id, name, program_type, age_min, age_max, start_date, time_start from offerings'

echo ""
echo "--- matches (initial) ---"
curl -sS 'localhost:8080/api/matches?kid_id=1' | jq '.[] | {offering_id, score, gates: .reasons.gates, watchlist: .reasons.watchlist_hit}'

echo ""
echo "--- add wildcard watchlist entry ---"
curl -sS -X POST localhost:8080/api/kids/1/watchlist -H 'content-type: application/json' \
  -d '{"pattern":"t*ball*","priority":"high"}' | jq .

sleep 2
echo ""
echo "--- matches after watchlist ---"
curl -sS 'localhost:8080/api/matches?kid_id=1' | jq '.[] | {offering_id, score, watchlist: .reasons.watchlist_hit}'

echo ""
echo "done. bringing compose down..."
$COMPOSE down
