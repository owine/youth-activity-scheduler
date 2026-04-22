# Youth Activity Scheduler (yas)

Self-hosted crawler + alerter for youth activity / sports / enrichment websites.
See `docs/superpowers/specs/` for the design spec.

## Quickstart (Docker)

```bash
cp .env.example .env
echo "YAS_ANTHROPIC_API_KEY=sk-ant-…" >> .env
docker compose up -d
curl http://localhost:8080/healthz
```

### Local dev on macOS

Docker Desktop's VirtioFS bind mount doesn't fully honor SQLite's locking
primitives; you'll see sporadic `disk I/O error` under concurrent api ↔ worker
access. Real Linux deployments are unaffected. For local dev on macOS, use the
overlay that switches `./data` to a Docker-managed named volume:

```bash
docker compose -f docker-compose.yml -f docker-compose.macos.yml up -d

# inspect the db (it's inside the named volume, not on the host)
docker compose -f docker-compose.yml -f docker-compose.macos.yml \
    exec yas-api sqlite3 /data/activities.db '.tables'
```

## Quickstart (local)

```bash
uv sync
cp .env.example .env
echo "YAS_ANTHROPIC_API_KEY=sk-ant-…" >> .env
mkdir -p data
uv run alembic upgrade head
uv run python -m yas all
```

## Managing sites

Sites and their tracked pages are registered via HTTP. The API is un-authed and
bound to the container network; expose it only on trusted hosts.

```bash
# Register a site with one tracked schedule page.
curl -sS -X POST localhost:8080/api/sites \
  -H 'content-type: application/json' \
  -d '{
    "name": "Example Sports",
    "base_url": "https://example.com/",
    "needs_browser": false,
    "pages": [{"url": "https://example.com/schedule", "kind": "schedule"}]
  }'

curl localhost:8080/api/sites              # list
curl localhost:8080/api/sites/1            # one site with pages
curl -X POST localhost:8080/api/sites/1/crawl-now   # schedule now
curl -X DELETE localhost:8080/api/sites/1  # remove site + pages + offerings
```

`robots.txt` is **ignored by default**. Set `crawl_hints: {"respect_robots": true}`
on a site to opt in.

The scheduler ticks every 30s and crawls pages whose `next_check_at` is in the
past, respecting `site.default_cadence_s` after each successful crawl.

## Managing kids and matches

Kids, watchlists, unavailability blocks, and enrollments are all HTTP-managed.
Matches are computed automatically — any mutation of a kid, offering, block,
or enrollment triggers a rematch. A daily sweep at `YAS_SWEEP_TIME_UTC` (default
`07:00`) re-matches all active kids to catch date-based shifts.

```bash
# Create a household with a home address (geocoded immediately via Nominatim).
curl -sS -X PATCH localhost:8080/api/household -H 'content-type: application/json' \
  -d '{"home_address":"2045 N Lincoln Park W, Chicago, IL","default_max_distance_mi":20}'

# Create a kid. DOB drives age at offering start_date; school schedule drives
# an auto-materialized no-conflict gate during school weekdays.
curl -sS -X POST localhost:8080/api/kids -H 'content-type: application/json' -d '{
  "name":"Sam","dob":"2019-05-01","interests":["baseball"],
  "school_weekdays":["mon","tue","wed","thu","fri"],
  "school_time_start":"08:00","school_time_end":"15:00",
  "school_year_ranges":[{"start":"2026-09-02","end":"2027-06-14"}]
}'

# Read matches, ordered by score desc.
curl 'localhost:8080/api/matches?kid_id=1'

# Add a wildcard watchlist entry — hits bypass all hard gates because
# watchlist entries represent manually-verified programs.
curl -X POST localhost:8080/api/kids/1/watchlist -H 'content-type: application/json' \
  -d '{"pattern":"t*ball*","priority":"high"}'

# Mark an enrollment — status=enrolled creates a linked unavailability block
# so conflicting offerings stop matching.
curl -X POST localhost:8080/api/enrollments -H 'content-type: application/json' \
  -d '{"kid_id":1,"offering_id":42,"status":"enrolled"}'
```

Geocoding: the worker geocodes new location addresses every
`YAS_GEOCODE_TICK_S` (default 5 min). Nominatim is rate-limited to 1 req/s per
policy. Addresses that can't be resolved are recorded in `geocode_attempts` so
they're not retried until they change.

## Development

```bash
uv run pytest          # tests
uv run ruff check .    # lint
uv run ruff format .   # format
uv run mypy src        # typecheck
```

## Project layout

```
src/yas/
  config.py          pydantic-settings
  logging.py         structlog setup
  __main__.py        CLI entrypoint (api|worker|all)
  db/                SQLAlchemy models + session
  crawl/             fetcher, change detector, extractor, reconciler, scheduler, pipeline
  llm/               Pydantic schemas, prompt builder, AnthropicClient
  matching/          pure gates + scoring + watchlist + aliases, async matcher orchestrator
  unavailability/    school-block and enrollment-block materializers
  geo/               haversine distance, Nominatim client, geocode enricher
  web/               FastAPI app
  web/routes/        HTTP endpoints (sites, kids, watchlist, unavailability, enrollments, matches, household)
  worker/            background loops (heartbeat, crawl scheduler, daily sweep, geocode enricher)
alembic/             DB migrations
scripts/             manual smoke scripts
tests/               pytest suite
```
