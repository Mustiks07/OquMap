#!/usr/bin/env bash
# Cold-start check: empty volumes → build → wait for health of every service → verify worker survived
# the migration window → optionally run Playwright. Repeats N times to catch start-order races.
#   scripts/docker_cold_start.sh [repeats=3] [--e2e]
# Extra compose files (e.g. -f docker-compose.ca.yml behind a TLS proxy) via COMPOSE_FILES="-f a.yml -f b.yml".
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
REPEATS="${1:-3}"
E2E="${2:-}"
FILES="${COMPOSE_FILES:--f docker-compose.yml}"
dc() { docker compose $FILES "$@"; }
for i in $(seq 1 "$REPEATS"); do
  echo "=== cold start $i/$REPEATS ==="
  dc down -v --remove-orphans >/dev/null 2>&1 || true
  # generous per-IP demo limits only for the automated e2e run (all requests come from one IP)
  OQUMAP_DEMO_TENANTS_PER_IP_PER_HOUR="${OQUMAP_DEMO_TENANTS_PER_IP_PER_HOUR:-100}" OQUMAP_RATE_LOGIN="${OQUMAP_RATE_LOGIN:-200/600}" \
    dc up -d --build >/dev/null
  ok=""
  for _ in $(seq 1 120); do
    states="$(dc ps --format '{{.Service}}={{.Health}}' | sort | tr '\n' ' ')"
    if echo "$states" | grep -q "api=healthy" && echo "$states" | grep -q "db=healthy" \
       && echo "$states" | grep -q "web=healthy" && echo "$states" | grep -q "worker=healthy"; then ok=1; break; fi
    sleep 2
  done
  dc ps
  [ -n "$ok" ] || { echo "services did not become healthy"; dc logs --tail 80; exit 1; }
  restarts="$(docker inspect -f '{{.RestartCount}}' "$(dc ps -q worker)")"
  echo "worker restarts: $restarts"
  curl -fsS "http://localhost:${OQUMAP_WEB_PORT:-8080}/health/ready"; echo
  if dc logs api worker 2>&1 | grep -q "Traceback"; then echo "Traceback found in logs"; dc logs api worker | grep -B5 -A20 Traceback | head -80; exit 1; fi
  docker run --rm --entrypoint oqumap-entrypoint "$(dc images -q api | head -1)" selfcheck
done
if [ "$E2E" = "--e2e" ]; then
  cd tests/e2e && npm ci --no-audit --no-fund && OQUMAP_WEB_URL="http://localhost:${OQUMAP_WEB_PORT:-8080}" npx playwright test --trace off
fi
echo "cold start OK"
