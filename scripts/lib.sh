#!/usr/bin/env bash
# Shared helpers for the compose-driven smoke and e2e scripts.
# Source it, don't execute it:  . "$(dirname "$0")/lib.sh"

# Build the compose invocation for testing local source.
#
#   COMPOSE=$(compose_cmd)                          # base (+ macOS) + dev
#   COMPOSE=$(compose_cmd docker-compose.smoke.yml) # ... with an extra overlay
#
# Order matters: base first, platform overlay next, caller overlays after
# that, and docker-compose.dev.yml LAST so its `build: .` overrides the base
# file's `image: ghcr.io/...:latest`.
compose_cmd() {
  local cmd="docker compose -f docker-compose.yml"
  [ "$(uname)" = "Darwin" ] && cmd="$cmd -f docker-compose.macos.yml"
  local overlay
  for overlay in "$@"; do
    cmd="$cmd -f $overlay"
  done
  printf '%s -f docker-compose.dev.yml' "$cmd"
}

# Refuse to run against a pulled image.
#
#   assert_local_build "$COMPOSE" yas-worker yas-api
#
# docker-compose.yml targets prod: it pins `image: ghcr.io/...:latest` with no
# `build:`. Scripts that must exercise local source layer in
# docker-compose.dev.yml, which overrides `image:` with `build: .`. Drop that
# override and the failure is silent, not loud — `docker compose build` prints
# "No services to build" and exits 0, `--build` becomes a no-op, `up` pulls
# from GHCR, and the suite validates the published image while passing.
#
# Checks each named service individually rather than grepping the whole config
# for any `build:`. An overlay that names a service the base file doesn't have
# ADDS it rather than erroring, so a stale overlay can leave a phantom service
# carrying `build:` while the service actually under test still pulls.
assert_local_build() {
  local compose="$1"
  shift
  if ! command -v jq >/dev/null 2>&1; then
    echo "ERROR: jq is required to verify the compose build override." >&2
    return 1
  fi
  local config
  # shellcheck disable=SC2086  # $compose is a command line, split on purpose
  if ! config=$($compose config --format json 2>/dev/null); then
    echo "ERROR: 'docker compose config' failed — cannot verify the build override." >&2
    return 1
  fi
  local svc
  for svc in "$@"; do
    if ! printf '%s' "$config" \
      | jq -e --arg s "$svc" '.services[$s].build != null' >/dev/null 2>&1; then
      echo "ERROR: service '$svc' has no 'build:' in the resolved compose config." >&2
      echo "       Add -f docker-compose.dev.yml (last) so this tests the working" >&2
      echo "       tree instead of whatever is published on GHCR." >&2
      return 1
    fi
  done
}
