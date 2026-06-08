# syntax=docker/dockerfile:1.24.0@sha256:87999aa3d42bdc6bea60565083ee17e86d1f3339802f543c0d03998580f9cb89

# --- Stage 1: build the React SPA ---
FROM node:24.16.0-alpine@sha256:2bdb65ed1dab192432bc31c95f94155ca5ad7fc1392fb7eb7526ab682fa5bf14 AS frontend-build
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
FROM python:3.14.5-slim@sha256:c845af9399020c7e562969a13689e929074a10fd057acd1b1fad06a2fb068e97 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 /uv /usr/local/bin/uv

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
