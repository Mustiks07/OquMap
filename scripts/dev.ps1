# Development without Docker (Windows PowerShell). Requires: PostgreSQL, Python 3.11–3.13 with uv, Node 20+.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Push-Location "$Root\apps\api"
uv sync
uv run alembic upgrade head
uv run python -m oqumap.demo.seed
$api = Start-Process -PassThru -NoNewWindow uv -ArgumentList "run","uvicorn","oqumap.main:app","--reload","--port","8000"
Pop-Location
Push-Location "$Root\apps\web"
npm ci
try { npm run dev } finally { Stop-Process -Id $api.Id -ErrorAction SilentlyContinue; Pop-Location }
