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

## Quickstart (local)

```bash
uv sync
cp .env.example .env
echo "YAS_ANTHROPIC_API_KEY=sk-ant-…" >> .env
mkdir -p data
uv run alembic upgrade head
uv run python -m yas all
```

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
  config.py        pydantic-settings
  logging.py       structlog setup
  __main__.py      CLI entrypoint (api|worker|all)
  db/              SQLAlchemy models + session
  web/             FastAPI app
  worker/          background loop
alembic/           DB migrations
tests/             pytest suite
```
