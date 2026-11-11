"""OpenAPI drift: packages/contracts/openapi.json must match the running app (frontend types are generated from it)."""

import json
from pathlib import Path

from oqumap.main import create_app

CONTRACT = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi.json"


def test_openapi_contract_is_up_to_date():
    current = json.dumps(create_app().openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    assert CONTRACT.read_text(encoding="utf-8") == current, "run: cd apps/api && uv run python ../../scripts/export_openapi.py"


def test_measurement_endpoints_are_in_the_contract():
    paths = json.loads(CONTRACT.read_text(encoding="utf-8"))["paths"]
    for p in ("/api/v1/quality/assessments", "/api/v1/quality/assessments/{assessment_id}", "/api/v1/quality/assessments/{assessment_id}/items",
              "/api/v1/quality/items/{item_id}", "/api/v1/interventions", "/api/v1/interventions/suggest", "/api/v1/pilots",
              "/api/v1/pilots/{pilot_id}/transition", "/api/v1/pilots/{pilot_id}/fidelity", "/api/v1/pilots/{pilot_id}/follow-up",
              "/api/v1/pilots/{pilot_id}/conclusions", "/api/v1/learning/summary", "/api/v1/portfolio/interventions"):
        assert p in paths, p
