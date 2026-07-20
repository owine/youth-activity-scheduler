# syntax=docker/dockerfile:1.25.0@sha256:0adf442eae370b6087e08edc7c50b552d80ddf261576f4ebd6421006b2461f12

# --- Stage 1: build the React SPA ---
FROM node:24.18.0-alpine@sha256:a0b9bf06e4e6193cf7a0f58816cc935ff8c2a908f81e6f1a95432d679c54fbfd AS frontend-build
WORKDIR /build
# Corepack ships with Node and pins pnpm to the version recorded in
# package.json's `packageManager` field. No network install of pnpm needed.
RUN corepack enable
# Cache deps separately. .npmrc enforces minimum-release-age soak so a
# compromised version can't slip into the image build.
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml frontend/.npmrc ./
RUN pnpm install --frozen-lockfile
# Build
COPY frontend/ ./
RUN pnpm run build  # emits /build/dist with index.html + assets/

# --- Stage 2: Python backend ---
FROM python:3.14.6-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.30@sha256:93b61e21202b1dab861092748e46bbd6e0e41dd84f59b9174efd2353186e1b47 /uv /usr/local/bin/uv

WORKDIR /app

# Layer 1: install deps only (not the project). README.md is required by
# hatchling metadata validation even when the project itself isn't built here.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: copy source and install the project itself.
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN uv sync --frozen --no-dev

# Playwright browser + OS deps. Done after uv sync so `playwright` is on PATH.
RUN uv run playwright install --with-deps chromium

RUN mkdir -p /data

ENV YAS_DATABASE_URL=sqlite+aiosqlite:////data/activities.db \
    YAS_DATA_DIR=/data

# Copy the SPA bundle into the static dir consumed by yas.web.spa_fallback
COPY --from=frontend-build /build/dist /app/static

# Bake the git commit SHA into the image so /healthz can report it.
# Placed at the very end so cache invalidation per-commit only rebuilds
# this trivial layer, not the heavy frontend/backend/playwright layers
# above. Default is "unknown" so non-CI builds still succeed.
ARG GIT_SHA=unknown
ENV YAS_GIT_SHA=$GIT_SHA

HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
  CMD curl -fsS http://localhost:8080/healthz || exit 1

CMD ["python", "-m", "yas", "all"]
