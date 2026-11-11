#!/usr/bin/env bash
# Development without Docker (Linux/macOS). Requires: PostgreSQL, Python 3.11–3.13 with uv, Node 20+.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apps/api"
uv sync
uv run alembic upgrade head
uv run python -m oqumap.demo.seed
uv run uvicorn oqumap.main:app --reload --port 8000 &
API_PID=$!
cd "$ROOT/apps/web"
npm ci
trap 'kill $API_PID' EXIT
npm run dev
