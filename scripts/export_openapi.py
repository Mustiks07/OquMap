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


def _normalise(obj):
    """Python 3.12 and 3.13 name HTTP 422 differently ("Unprocessable Entity" vs "Unprocessable Content",
    RFC 9110); FastAPI copies the phrase into the schema. Use the RFC 9110 name so the contract does not depend
    on the interpreter version."""
    if isinstance(obj, dict):
        return {k: ("Unprocessable Content" if k == "description" and v == "Unprocessable Entity" else _normalise(v))
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalise(v) for v in obj]
    return obj


schema = json.dumps(_normalise(create_app().openapi()), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
if "--check" in sys.argv:
    if not out.exists() or out.read_text(encoding="utf-8") != schema:
        print("openapi.json is out of date: run scripts/export_openapi.py", file=sys.stderr)
        sys.exit(1)
    print("openapi.json is up to date")
else:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(schema, encoding="utf-8")
    print(f"wrote {out}")
