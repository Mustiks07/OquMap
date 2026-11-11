#!/usr/bin/env bash
# Full local verification: lint, API tests, contract check, web typecheck/tests/build.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/apps/api"
uv run ruff check oqumap tests
uv run pytest -q
uv run python ../../scripts/export_openapi.py --check
cd "$ROOT/apps/web"
npm run typecheck
npm test
npm run build
echo "all checks passed"
