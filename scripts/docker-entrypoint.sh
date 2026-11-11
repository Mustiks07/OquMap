#!/bin/sh
# Container entrypoint: wait for the database, apply migrations, seed the synthetic demo once, then start.
set -e
python - <<'PY'
import time, sys
from sqlalchemy import create_engine, text
from oqumap.config import get_settings
url = get_settings().database_url
for i in range(60):
    try:
        with create_engine(url).connect() as c:
            c.execute(text("select 1"))
        sys.exit(0)
    except Exception:
        time.sleep(1)
print("database is not reachable", file=sys.stderr)
sys.exit(1)
PY
case "$1" in
  api)
    alembic upgrade head
    if [ "${OQUMAP_SEED_DEMO:-true}" = "true" ]; then python -m oqumap.demo.seed; fi
    exec uvicorn oqumap.main:app --host 0.0.0.0 --port 8000 --proxy-headers
    ;;
  worker)
    exec python -m oqumap.worker
    ;;
  *)
    exec "$@"
    ;;
esac
