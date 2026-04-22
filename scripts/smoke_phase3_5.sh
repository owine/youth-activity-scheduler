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

echo "--- household ---"
curl -sS -X PATCH localhost:8080/api/household -H 'content-type: application/json' \
  -d '{"home_address":"2045 N Lincoln Park W, Chicago, IL","default_max_distance_mi":30.0}' > /dev/null

echo "--- kid ---"
curl -sS -X POST localhost:8080/api/kids -H 'content-type: application/json' -d '{
  "name":"Sam","dob":"2019-05-01","interests":["soccer"]
}' > /dev/null

echo "--- site with only base_url (no pages) ---"
curl -sS -X POST localhost:8080/api/sites -H 'content-type: application/json' -d '{
  "name":"YSIFC","base_url":"https://ysifc.com/","needs_browser":true
}' | jq .

echo ""
echo "--- discover ---"
DISCOVER=$(curl -sS -X POST localhost:8080/api/sites/1/discover)
echo "$DISCOVER" | jq .

echo ""
echo "--- picking top HTML candidate ---"
TOP_URL=$(echo "$DISCOVER" | jq -r '[.candidates[] | select(.kind == "html")] | first | .url')
if [ -z "$TOP_URL" ] || [ "$TOP_URL" = "null" ]; then
  echo "No HTML candidate discovered; exiting smoke." && $COMPOSE down && exit 1
fi
echo "Picked: $TOP_URL"

curl -sS -X POST "localhost:8080/api/sites/1/pages" -H 'content-type: application/json' \
  -d "{\"url\":\"$TOP_URL\",\"kind\":\"schedule\"}" | jq .

echo ""
echo "Waiting 90s for scheduler + crawl + extract + rematch..."
sleep 90

echo ""
echo "--- offerings ---"
$COMPOSE exec -T yas-api sqlite3 /data/activities.db \
  'select id, name, program_type, age_min, age_max, start_date from offerings'

echo ""
echo "--- matches ---"
curl -sS 'localhost:8080/api/matches?kid_id=1' | jq '.[] | {offering_id, score, gates: .reasons.gates}'

echo ""
echo "--- PDF rejection check ---"
curl -sS -w "\nHTTP %{http_code}\n" -X POST localhost:8080/api/sites/1/pages \
  -H 'content-type: application/json' \
  -d '{"url":"https://ysifc.com/brochure.pdf","kind":"pdf"}'

$COMPOSE down
