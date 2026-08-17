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

# --- Stage 2: uv, for build-time use only ---
# Named stage rather than a repeated inline image ref: the digest lives in one
# place, and Renovate's dockerfile manager tracks plain `FROM` (multi-stage
# included). An ARG would also deduplicate but `RUN --mount=from=${VAR}` is not
# a documented Renovate case, and a silently stale pin is worse than a repeat.
# Nothing COPYs from this stage, so it never reaches the final image.
FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv

# --- Stage 3: Python backend ---
FROM python:3.14.7-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl sqlite3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Layer 1: install deps only (not the project). README.md is required by
# hatchling metadata validation even when the project itself isn't built here.
#
# uv arrives via a build-time bind mount rather than COPY, so the 46 MB binary
# is usable during the RUN and absent from the committed layer. Nothing at
# runtime invokes uv — CMD is `python -m yas all`.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-install-project

# Playwright browser + OS deps. Two things matter here:
#
# 1. `--only-shell` installs just the Chromium headless shell, skipping the
#    641 MB headed build. crawl/fetcher.py launches with headless=True and no
#    channel=, which is exactly the case the headless shell serves.
# 2. Bare `playwright`, NOT `uv run playwright`. `uv run` re-syncs the project
#    environment first, and without --no-dev that reinstates the whole dev
#    group (pytest, ruff, mypy, pre-commit — ~90 MB), silently undoing the
#    --no-dev on the syncs around it. PATH already prefers /app/.venv/bin.
#
# Placed above `COPY src` on purpose: this layer depends only on the playwright
# version in uv.lock, so source-only commits reuse it instead of rebuilding
# ~1.1 GB on both matrix legs.
RUN playwright install --with-deps --only-shell chromium

# Layer 2: copy source and install the project itself.
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN --mount=type=bind,from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev

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

# --start-period covers boot: `all` mode applies Alembic migrations before
# uvicorn binds, so early probes are expected to fail. Failures inside the
# start period don't count toward --retries and don't mark the container
# unhealthy, which keeps a slow migration from looking like a runtime fault.
#
# Note this probes /healthz, which is shallow (status/git_sha/version). It
# deliberately does NOT check the worker — a stalled worker leaves the
# container healthy. That's covered by the process exiting instead: see
# yas.__main__._supervise. Docker's HEALTHCHECK only sets a status label, it
# never restarts anything; recovery comes from `restart: unless-stopped`
# reacting to the exit.
HEALTHCHECK --interval=30s --timeout=3s --retries=3 --start-period=30s \
  CMD curl -fsS http://localhost:8080/healthz || exit 1

CMD ["python", "-m", "yas", "all"]
