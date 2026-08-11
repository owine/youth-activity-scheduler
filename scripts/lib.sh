#!/usr/bin/env bash
# Shared helpers for the compose-driven smoke and e2e scripts.
# Source it, don't execute it:  . "$(dirname "$0")/lib.sh"

# Refuse to run against a pulled image.
#
# docker-compose.yml targets prod: it pins `image: ghcr.io/...:latest` with no
# `build:`. Scripts that must exercise local source layer in
# docker-compose.dev.yml, which overrides `image:` with `build: .`. Drop that
# override and the failure is silent, not loud — `docker compose build` prints
# "No services to build" and exits 0, `--build` becomes a no-op, `up` pulls
# from GHCR, and the suite validates the published image while passing.
#
# Takes the full compose invocation as arguments, e.g.
#   assert_local_build $COMPOSE
assert_local_build() {
  local config
  if ! config=$("$@" config 2>/dev/null); then
    echo "ERROR: 'docker compose config' failed — cannot verify the build override." >&2
    return 1
  fi
  if ! printf '%s\n' "$config" | grep -q '^ *build:'; then
    echo "ERROR: no 'build:' in the resolved compose config." >&2
    echo "       Add -f docker-compose.dev.yml (last) so this tests the working" >&2
    echo "       tree instead of whatever is published on GHCR." >&2
    return 1
  fi
}
