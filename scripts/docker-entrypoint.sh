#!/bin/sh
# Container entrypoint: wait for the database, apply migrations, seed the synthetic demo once, then start.
# Must be stored with LF line endings (.gitattributes); `oqumap-entrypoint selfcheck` verifies it runs.
set -e
if [ "$1" = "selfcheck" ]; then
  python -c "import oqumap.main, oqumap.worker; print('entrypoint ok')"
  exit 0
fi
wait_for_db() {
python - <<'PY'
import sys, time
from sqlalchemy import create_engine, text
from oqumap.config import get_settings
url = get_settings().database_url
delay = 1.0
for _ in range(60):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("select 1"))
        sys.exit(0)
    except Exception:
        time.sleep(delay)
        delay = min(5.0, delay * 1.5)
print("database is not reachable", file=sys.stderr)
sys.exit(1)
PY
}
case "$1" in
  api)
    wait_for_db
    alembic upgrade head
    if [ "${OQUMAP_SEED_DEMO:-true}" = "true" ]; then python -m oqumap.demo.seed; fi
    python -m oqumap.maintenance check-config || echo "WARNING: live LLM configuration problem (see above); AI falls back to template/recorded modes"
    exec uvicorn oqumap.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="${OQUMAP_FORWARDED_ALLOW_IPS:-127.0.0.1}"
    ;;
  worker)
    # no DB wait needed: the worker retries with bounded backoff until the schema exists
    exec python -m oqumap.worker
    ;;
  *)
    exec "$@"
    ;;
esac
