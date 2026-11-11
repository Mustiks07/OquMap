"""Write the server OpenAPI schema to packages/contracts/openapi.json (used to generate frontend types).

Usage: cd apps/api && uv run python ../../scripts/export_openapi.py [--check]
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from oqumap.main import create_app  # noqa: E402

out = ROOT / "packages" / "contracts" / "openapi.json"
schema = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
if "--check" in sys.argv:
    if not out.exists() or out.read_text(encoding="utf-8") != schema:
        print("openapi.json is out of date: run scripts/export_openapi.py", file=sys.stderr)
        sys.exit(1)
    print("openapi.json is up to date")
else:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(schema, encoding="utf-8")
    print(f"wrote {out}")
