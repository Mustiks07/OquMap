"""Drop all OquMap tables, re-apply migrations and re-seed the synthetic demo (cross-platform).

Usage (from apps/api):  uv run python ../../scripts/reset_demo.py
Uses OQUMAP_DATABASE_URL / OQUMAP_STORAGE_DIR like the API. Destroys data in that database.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "apps" / "api"
sys.path.insert(0, str(API))

from sqlalchemy import text  # noqa: E402

from oqumap import db, models  # noqa: E402,F401
from oqumap.config import get_settings  # noqa: E402

s = get_settings()
print(f"database: {db.engine().url.render_as_string(hide_password=True)}")
db.Base.metadata.drop_all(db.engine())
with db.engine().begin() as c:
    c.execute(text("DROP TABLE IF EXISTS alembic_version"))
if s.storage_dir.exists():
    shutil.rmtree(s.storage_dir)
subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API, check=True)
subprocess.run([sys.executable, "-m", "oqumap.demo.seed"], cwd=API, check=True)
print("demo reset complete")
