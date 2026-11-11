"""Expand the arithmetic composition fixture into learner rows (used by tests and by the demo seed)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..config import REPO_ROOT

FIXTURE_PATH = REPO_ROOT / "data" / "demo" / "fixtures" / "composition_fixture.json"
STRATUM_BASELINE = {"high": 1.0, "low": 0.0}  # baseline share placing a learner in the stratum (pre_two_level)


def load_fixture(path: Path = FIXTURE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_learners(fixture: dict, classes_per_cell: int = 2) -> pd.DataFrame:
    rows = []
    for cell in fixture["cells"]:
        for i in range(cell["total"]):
            cls = f"{cell['arm']}-{cell['stratum']}-{i % classes_per_cell}"
            rows.append(
                {
                    "learner_id": f"{cell['arm']}-{cell['stratum']}-{i}",
                    "arm": cell["arm"],
                    "cohort_id": cls,
                    "school_id": f"school-{cls}",
                    "teacher_id": f"teacher-{cls}",
                    "outcome": 1.0 if i < cell["passed"] else 0.0,
                    "baseline": STRATUM_BASELINE[cell["stratum"]],
                }
            )
    return pd.DataFrame(rows)
