# syntax=docker/dockerfile:1.26.0@sha256:ecfaec9ed6d810b56388c508f4121597bfbba70d41a6dfeee4d8cad5f295fc32

# --- Stage 1: build the React SPA ---
FROM node:24.19.0-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS frontend-build
WORKDIR /build
# Corepack ships with Node and pins pnpm to the version recorded in
# package.json's `packageManager` field. No network install of pnpm needed.
RUN corepack enable
# Cache deps separately. --frozen-lockfile means the image can only ever install
# the exact, already-reviewed versions in pnpm-lock.yaml; nothing is resolved
# fresh at build time, so a compromised release can't slip into the image.
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
# Build
COPY frontend/ ./
RUN pnpm run build  # emits /build/dist with index.html + assets/

# --- Stage 2: Python backend ---
FROM python:3.14.7-slim@sha256:83c1cebb322d099ac9e3a3a532ba74b0146d702838b25e4c75c02fa81ffeb910 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl sqlite3 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.3@sha256:2d890623d310b57771ce840f0da5eed5fc6d657da05ffaa45d82797b53fa3abc /uv /usr/local/bin/uv

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
