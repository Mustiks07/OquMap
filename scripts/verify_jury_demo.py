#!/usr/bin/env python3
"""Verify files, real API onboarding/analysis/documents, and fixture-only pilot semantics.

Always uses a disposable local SQLite database. Never connects to a user database.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path

from generate_jury_demo import OUT


def configure_local(storage):
    os.environ["OQUMAP_STORAGE_DIR"] = str(storage)
    os.environ["OQUMAP_JOB_MODE"] = "inline"
    os.environ["OQUMAP_LLM_PROVIDER"] = "none"
    os.environ["OQUMAP_DEPLOYMENT_MODE"] = "dev"
    os.environ["OQUMAP_RATE_COMPUTE"] = "100000/60"
    os.environ["OQUMAP_LOG_LEVEL"] = "WARNING"
    from oqumap.config import get_settings

    get_settings.cache_clear()


def api_checks(client, headers, root=OUT):
    """Reusable against a fresh, authorized tenant; five files use the actual HTTP import path."""
    from jury_demo_support import connect_material_links, evaluate, in_range
    from oqumap import db
    from oqumap import models as m

    expected = json.loads((root / "expected_findings.json").read_text())

    def request(method, path, **kwargs):
        r = getattr(client, method)("/api/v1" + path, headers=headers, **kwargs)
        assert r.status_code == 200, (path, r.status_code, r.text[:2000])
        return r.json()

    ds = request(
        "post",
        "/datasets",
        json=dict(name_ru="OquMap Jury - Математика 6 (synthetic)", is_synthetic=True),
    )
    did = ds["id"]
    imports = {}
    for num, kind in enumerate(
        ("program", "editions", "item_bank", "roster", "responses"), 1
    ):
        name = f"{num}_{kind}.csv"
        validated = request(
            "post",
            "/imports/validate",
            files={"file": (name, (root / name).read_bytes(), "text/csv")},
            data={"dataset_id": did, "kind": kind},
        )
        assert validated["rows_rejected"] == 0, (kind, validated["report"])
        assert validated["report"].get("commit_allowed", True), (
            kind,
            validated["report"],
        )
        job = request(
            "post", "/imports/commit", json={"batch_id": validated["id"], "wait": True}
        )
        assert job["status"] == "succeeded", (kind, job)
        again = request(
            "post", "/imports/commit", json={"batch_id": validated["id"], "wait": True}
        )
        assert again["id"] == job["id"]
        imports[kind] = dict(
            rows_total=validated["rows_total"],
            rows_accepted=validated["rows_accepted"],
            rows_rejected=validated["rows_rejected"],
        )
    quality = request("get", f"/datasets/{did}/quality")
    assert (
        quality["counts"]["learners"] == 384
        and quality["data_level"] == "pre_post_with_exposure"
    )
    cur = request("get", "/curriculum", params={"dataset_id": did})
    topics = {t["code"]: t["id"] for t in cur["topics"]}
    editions = {e["code"]: e["id"] for e in cur["editions"]}
    tid = topics["JURY-T1"]
    # Material uploads and extraction run the actual application document pipeline.
    documents = []
    for ed in "AB":
        name = f"textbook_{ed}.pdf"
        result = request(
            "post",
            "/documents",
            files={
                "file": (
                    name,
                    (root / "materials" / name).read_bytes(),
                    "application/pdf",
                )
            },
            data={"edition_id": editions[f"JURY-{ed}"]},
        )
        job = result["job"]
        for _ in range(300):
            if job["status"] in ("succeeded", "failed"):
                break
            time.sleep(0.1)
            job = request("get", f"/jobs/{result['job']['id']}")
        assert job["status"] == "succeeded", job
        doc = request("get", f"/documents/{result['document']['id']}")
        assert (
            doc["document"]["status"] == "ready" and doc["document"]["page_count"] == 50
        )
        assert any(
            f["page_physical"] == 47 and "6.2.1" in f["text"] for f in doc["fragments"]
        )
        documents.append(dict(edition=f"JURY-{ed}", status="ready", pages=50))
    with db.session_factory()() as session:
        attached = connect_material_links(session, did, root)
        assert attached > 0
        assert connect_material_links(session, did, root) == 0
        program = session.get(
            m.ProgramVersion, session.get(m.Dataset, did).program_version_id
        )
        assert program.is_demo_codes
        assert all(
            not o.kz_verified
            for o in session.query(m.LearningObjective).filter_by(
                program_version_id=program.id
            )
        )
    overview = request("post", f"/datasets/{did}/overview", json={})["result"]
    frac = next(t for t in overview["topics"] if t["code"] == "JURY-T1")
    in_range(frac["score"]["mean"], expected["fractions_mean"])
    evidence = request("get", f"/topics/{tid}/evidence", params={"dataset_id": did})[
        "result"
    ]
    target = next(o for o in evidence["objectives"] if o["code"] == "6.2.1")
    in_range(target["score"]["mean"], expected["target_mean"])
    assert target["score"]["mean"] == min(
        o["score"]["mean"] for o in evidence["objectives"] if o["score"]
    )
    m2 = next(
        mc for mc in evidence["misconceptions"] if mc["code"] == "numerators_not_scaled"
    )
    assert m2["n_learners"] >= 100 and m2["interpretation"] == "hypothesis"
    assert any(
        s["edition_code"] == "JURY-B"
        and s["page_physical"] == 47
        and s["objective_code"] == "6.2.1"
        for s in evidence["sources"]
    )
    comparison = request(
        "post",
        "/comparisons",
        json=dict(
            dataset_id=did,
            topic_id=tid,
            edition_a_id=editions["JURY-A"],
            edition_b_id=editions["JURY-B"],
        ),
    )["result"]
    in_range(-comparison["raw"]["difference"], expected["raw_A_minus_B"])
    in_range(-comparison["adjusted"]["difference"], expected["adjusted_A_minus_B"])
    assert comparison["raw"]["difference"] * comparison["adjusted"]["difference"] < 0
    assert (
        comparison["causal_protocol_available"] is False
        and comparison["inference_level"] == "adjusted_association"
    )
    assert comparison["uncertainty"]["cluster_unit"] == "class"
    context = request("get", "/plans/context", params={"dataset_id": did})
    plan_topics = []
    for t in context["topics"]:
        p = {
            k: t[k]
            for k in (
                "topic_id",
                "code",
                "current_hours",
                "priority",
                "min_hours",
                "max_hours",
                "elapsed_hours",
            )
        }
        if t["code"] == "JURY-T1":
            p["min_hours"] = p["max_hours"] = 8
        elif t["code"] == "JURY-T2":
            p["min_hours"] = p["max_hours"] = 6
        else:
            p["fixed"] = True
        plan_topics.append(p)
    plan = request(
        "post",
        "/plans/solve",
        json={"dataset_id": did, "topics": plan_topics, "budget": context["budget"]},
    )["result"]
    scenario = plan["scenarios"][0]
    assert scenario["status"] == "optimal" and scenario["validation"]["valid"], scenario
    changes = {c["code"]: c for c in scenario["changes"]}
    assert changes["JURY-T1"]["after"] == 8 and changes["JURY-T2"]["after"] == 6
    assert scenario["total_before"] == scenario["total_after"] == 38
    assert all(
        c["delta"] == 0
        for code, c in changes.items()
        if code not in ("JURY-T1", "JURY-T2")
    )
    assert (
        next(t for t in overview["topics"] if t["code"] == "JURY-T2")["status"]
        == "stable"
    )
    # Diagnostic quiz must be generated from observed supported misconceptions, with mathematical checks.
    quiz = request(
        "post",
        "/quizzes/preview",
        json={"dataset_id": did, "topic_id": tid, "n_items": 3, "seed": 20261111},
    )
    assert quiz["checks"]["approvable"], quiz
    # A deliberately tiny filter must be labelled insufficient_data by current API.
    one_class = next(c["id"] for c in cur["cohorts"]) if "cohorts" in cur else None
    if one_class is None:
        with db.session_factory()() as session:
            one_class = session.query(m.Cohort).filter_by(dataset_id=did).first().id
    small = request(
        "post", f"/datasets/{did}/overview", json={"cohort_ids": [one_class]}
    )["result"]
    assert all(
        t["status"] == "insufficient_data" for t in small["topics"] if t["score"]
    )
    # This is NOT numerical suppression: record the known production gap without claiming it is fixed.
    result = evaluate(root)
    assert abs(result["fractions_mean"] - frac["score"]["mean"]) < 1e-12
    assert abs(result["target_mean"] - target["score"]["mean"]) < 1e-12
    assert abs(result["raw_A_minus_B"] + comparison["raw"]["difference"]) < 1e-12
    assert (
        abs(result["adjusted_A_minus_B"] + comparison["adjusted"]["difference"]) < 1e-12
    )
    result.update(
        production_small_filter_numbers_suppressed=all(
            t["score"] is None for t in small["topics"]
        ),
        imports=imports,
        documents=documents,
        planner=dict(
            status=scenario["status"],
            validation=scenario["validation"],
            budget=context["budget"],
            requested_hours={"JURY-T1": 8, "JURY-T2": 6},
        ),
        diagnostic=dict(valid=quiz["checks"]["approvable"], n_items=len(quiz["items"])),
        limitations=[
            "Pilot statuses are fixture-only; no interventions/pilots/fidelity core schema on the base commit.",
            "Existing API marks small filters insufficient_data but still returns numerical summaries; production privacy suppression remains a blocker for real data.",
            "Fixture pilot report suppresses n<10 outcomes. All provided students and schools are synthetic.",
            "Source mappings require the explicit local fixture adapter after document upload; no CSV material-link endpoint exists.",
            "No browser or live deployment verification; API integration only.",
        ],
    )
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, default=OUT)
    p.add_argument("--report", type=Path)
    args = p.parse_args()
    with tempfile.TemporaryDirectory(prefix="oqumap-jury-") as temp:
        configure_local(Path(temp) / "storage")
        from fastapi.testclient import TestClient
        from jury_demo_support import validate_files
        from oqumap import db
        from oqumap.main import create_app
        from oqumap.services.admin import create_organization

        counts = validate_files(args.root)
        url = f"sqlite:///{Path(temp) / 'verify.db'}"
        db.configure(url)
        db.Base.metadata.create_all(db.engine())
        with db.session_factory()() as session:
            create_organization(
                session,
                "OquMap Jury Synthetic",
                "jury.fixture.admin",
                "Synthetic-Local-2026!",
            )
        with TestClient(create_app(url)) as client:
            r = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "jury.fixture.admin",
                    "password": "Synthetic-Local-2026!",
                },
            )
            assert r.status_code == 200, r.text
            report = api_checks(
                client, {"Authorization": f"Bearer {r.json()['token']}"}, args.root
            )
        report["counts"] = counts
        encoded = (
            json.dumps(
                report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
            )
            + "\n"
        )
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(encoded, encoding="utf-8")
        print(encoded)


if __name__ == "__main__":
    main()
