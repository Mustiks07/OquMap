"""Jury corpus contracts: actual CSV onboarding, analytics, documents and honest fixture pilots."""

import hashlib
import json
import subprocess
import sys
from fractions import Fraction as F
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from generate_jury_demo import OUT, build  # noqa: E402
from jury_demo_support import evaluate, validate_files  # noqa: E402
from verify_jury_demo import api_checks  # noqa: E402

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


def test_two_clean_generations_identical_including_pdfs_and_docs(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for directory in (first, second):
        subprocess.run(
            [sys.executable, str(ROOT / "scripts/generate_jury_demo.py"), "--out", str(directory)],
            check=True,
            capture_output=True,
        )
    files = build(FONT)
    for name, data in files.items():
        assert (
            (first / name).read_bytes() == (second / name).read_bytes() == data == (OUT / name).read_bytes()
        ), name
    # In-place regeneration does not retain a creation timestamp or introduce non-deterministic IDs.
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/generate_jury_demo.py"), "--out", str(first)],
        check=True,
        capture_output=True,
    )
    assert all((first / name).read_bytes() == data for name, data in files.items())


def test_structural_privacy_relationship_math_and_status_contracts():
    counts = validate_files()
    assert counts["response_rows"] > 40000


@pytest.mark.parametrize("filename", ["materials/exercises.json", "item_math.json"])
def test_independent_exact_math_oracle(filename):
    """Independent Fraction oracle; also checks every wrong option mathematically."""
    for s in json.loads((OUT / filename).read_text()):
        p = list(map(F, s["params"]))
        a, b = p[:2]
        operations = {
            "add": lambda a=a, b=b: a + b,
            "sub": lambda a=a, b=b: a - b,
            "mul": lambda a=a, b=b: a * b,
            "div": lambda a=a, b=b: a / b,
            "max": lambda a=a, b=b: max(a, b),
            "order": lambda a=a, b=b, p=p: a + b * p[2],
            "area": lambda a=a, b=b: a * b,
            "perimeter": lambda a=a, b=b: 2 * (a + b),
        }
        expected = operations[s["op"]]()
        assert F(s["answer"]) == expected
        if "options" in s:
            correct = [o["key"] for o in s["options"] if F(o["text"]) == expected]
            assert correct == [s["answer_key"]]
            assert all(F(o["text"]) != expected for o in s["options"] if o["tag"])


def test_checked_in_manifest_has_no_untracked_or_stale_generated_entries():
    manifest = json.loads((OUT / "manifest.json").read_text())
    assert manifest["files"]
    for name, entry in manifest["files"].items():
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == entry["sha256"]


@pytest.fixture(scope="module")
def evaluated():
    return evaluate()


def test_ranges_sign_reversal_m2_and_problematic_items(evaluated):
    assert evaluated["raw_A_minus_B"] < 0 < evaluated["adjusted_A_minus_B"]
    assert evaluated["target_mean"] < evaluated["fractions_mean"]
    assert evaluated["item_quality"]["JURY-I36"]["item_rest_correlation"] < -0.2
    assert evaluated["M2"]["by_edition"]["JURY-B"] > evaluated["M2"]["by_edition"]["JURY-A"]


def test_low_fidelity_is_not_a_verdict_on_method_and_small_pilot_is_suppressed(evaluated):
    a, b, c = (evaluated["pilots"][k] for k in "ABC")
    assert a["status"] == "positive_signal" and 0.08 <= a["observed_gain"] <= 0.12
    assert b["status"] == "invalid_due_to_fidelity" and b["fidelity"] < 0.8
    assert b["status"] != "not_confirmed"
    assert c["status"] == "needs_more_data" and c["suppressed"]
    assert c["observed_gain"] is None and c["n_paired"] is None
    assert "JDL" not in json.dumps(evaluated["pilots"])


@pytest.fixture(scope="module")
def imported(fresh_client):
    from oqumap import db
    from oqumap.services.admin import create_organization

    with db.session_factory()() as session:
        create_organization(
            session, "Jury fixture synthetic tenant", "jury.test.admin", "Synthetic-Tests-2026!"
        )
    result = fresh_client.post(
        "/api/v1/auth/login", json={"username": "jury.test.admin", "password": "Synthetic-Tests-2026!"}
    )
    assert result.status_code == 200, result.text
    return api_checks(fresh_client, {"Authorization": f"Bearer {result.json()['token']}"})


def test_actual_onboarding_analysis_planner_and_diagnostic(imported):
    assert all(r["rows_rejected"] == 0 for r in imported["imports"].values())
    assert imported["planner"]["status"] == "optimal"
    assert imported["diagnostic"] == {"valid": True, "n_items": 3}
    assert all(d["status"] == "ready" and d["pages"] == 50 for d in imported["documents"])


@pytest.mark.xfail(
    strict=True,
    reason="Base backend flags insufficient_data but still exposes small-filter numerical summaries; fixture report alone suppresses them.",
)
def test_production_api_suppresses_small_group_numbers(imported):
    assert imported["production_small_filter_numbers_suppressed"]


@pytest.mark.parametrize(
    "filename,field,value",
    [
        ("4_roster.csv", "learner_code", "Реальное Имя"),
        ("5_responses.csv", "item_code", "MISSING-ITEM"),
        ("5_responses.csv", "score", "999"),
        ("5_responses.csv", "status", "omitted"),
        ("5_responses.csv", "status", "absent"),
        ("7_pilots.csv", "intervention_id", "MISSING-INTERVENTION"),
        ("8_fidelity_logs.csv", "actual_minutes", "-1"),
        ("9_followups.csv", "learner_code", "MISSING-LEARNER"),
    ],
)
def test_corrupted_fixtures_are_rejected_beyond_manifest_hash(tmp_path, filename, field, value):
    import csv
    import io
    import shutil

    shutil.copytree(OUT, tmp_path / "corpus")
    root = tmp_path / "corpus"
    target = root / filename
    records = list(csv.DictReader(io.StringIO(target.read_text())))
    index = (
        next(i for i, r in enumerate(records) if r.get("status", "answered") == "answered")
        if filename == "5_responses.csv"
        else 0
    )
    records[index][field] = value
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(records[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(records)
    target.write_text(buffer.getvalue(), encoding="utf-8")
    # Keep checksums consistent: this test must reach semantic validation rather than a hash mismatch.
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["files"][filename] = {
        "bytes": target.stat().st_size,
        "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AssertionError):
        validate_files(root)
