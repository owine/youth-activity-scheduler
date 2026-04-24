#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if ! grep -q '^YAS_ANTHROPIC_API_KEY=sk-' .env 2>/dev/null || grep -q '^YAS_ANTHROPIC_API_KEY=sk-test-nonop$' .env; then
  echo "ERROR: .env must set YAS_ANTHROPIC_API_KEY to a real key." >&2
  exit 2
fi

COMPOSE="docker compose -f docker-compose.yml"
if [ "$(uname)" = "Darwin" ]; then
  COMPOSE="$COMPOSE -f docker-compose.macos.yml"
fi
COMPOSE="$COMPOSE -f docker-compose.smoke.yml"

$COMPOSE down 2>/dev/null || true
$COMPOSE up -d yas-migrate
$COMPOSE up -d yas-worker yas-api
sleep 10

echo "--- configure household email via Mailpit SMTP ---"
curl -sS -X PATCH localhost:8080/api/household -H 'content-type: application/json' \
  -d '{
    "smtp_config_json": {
      "transport": "smtp",
      "host": "mailpit",
      "port": 1025,
      "secure": false
    }
  }' | jq .

echo ""
echo "--- set home location ---"
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
echo "--- verify digest preview returns rendered content ---"
curl -sS 'localhost:8080/api/digest/preview?kid_id=1' | jq .

echo ""
echo "--- Check Mailpit UI at http://localhost:8025 for emails ---"
echo ""
echo "Optional: If YAS_PUSHOVER_USER_KEY is set, Pushover channel will be tested..."
if [ -n "${YAS_PUSHOVER_USER_KEY:-}" ]; then
  echo ""
  echo "--- configure pushover channel ---"
  curl -sS -X PATCH localhost:8080/api/household -H 'content-type: application/json' \
    -d "{
      \"pushover_config_json\": {
        \"user_key\": \"${YAS_PUSHOVER_USER_KEY}\"
      }
    }" | jq .

  echo ""
  echo "Pushover channel configured. Monitor for priority=2 push notifications."
fi

echo ""
echo "done. bringing compose down..."
$COMPOSE down
