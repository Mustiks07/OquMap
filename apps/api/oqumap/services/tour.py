"""Preflight for the read-only "Демо за 3 минуты" presentation: every step's data must be available before the
jury clicks through. Each check is a real call to the same service the step uses; nothing is mocked."""

from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..ai.provider import get_provider
from ..errors import ApiError
from . import analysis as an
from . import graph as gr
from . import planning

TOUR_TOPIC = "T3"


def preflight(session: Session, p, dataset_id: str) -> dict:
    checks = []
    t0 = time.monotonic()

    def run(code: str, fn):
        s = time.monotonic()
        try:
            detail = fn()
            checks.append({"code": code, "ok": True, "detail": detail, "ms": int((time.monotonic() - s) * 1000)})
        except ApiError as exc:
            checks.append({"code": code, "ok": False, "detail": exc.code, "ms": int((time.monotonic() - s) * 1000)})

    ds = an.get_dataset(session, p.org_id, dataset_id)
    meta = an.load_meta(session, p.org_id, dataset_id)
    topic = next((t for t in meta.topics if t.code == TOUR_TOPIC), None)
    run("dataset", lambda: {"version": ds.version, "is_synthetic": ds.is_synthetic, "topic_found": topic is not None})
    if topic is None:
        return {"ready": False, "checks": checks, "topic_id": None}
    run("overview", lambda: {"analysis_id": an.overview(session, p.org_id, dataset_id, an.Filters(), p.user_id)["context"]["analysis_id"]})
    run("graph", lambda: {"path_len": len(gr.build(session, p.org_id, dataset_id, topic.id, an.Filters(), p.user_id)["result"]["path"])})
    eds = sorted({v for (_, t), v in meta.cohort_edition.items() if t == topic.id and v in meta.editions},
                 key=lambda e: meta.editions[e].code)

    def comp():
        if len(eds) < 2:
            raise ApiError("fewer_than_two_editions", "", 422)
        r = an.comparison(session, p.org_id, an.ComparisonRequest(dataset_id=dataset_id, topic_id=topic.id, edition_a_id=eds[0],
                                                                  edition_b_id=eds[1]), p.user_id)
        return {"status": r["result"]["status"], "analysis_id": r["context"]["analysis_id"]}

    run("comparison", comp)
    run("plan", lambda: {"topics": len(planning.plan_context(session, p.org_id, dataset_id, an.Filters(), p.user_id)["topics"])})
    from ..demo.measurement_seed import DATASET_CODE as MEASUREMENT_CODE

    ml = session.scalar(select(m.Dataset.id).where(m.Dataset.org_id == p.org_id, m.Dataset.code == MEASUREMENT_CODE))
    # informational: in a fresh demo tenant the measurement & learning-loop demo is built by a background job
    checks.append({"code": "measurement_loop", "ok": True, "detail": {"status": "ready" if ml else "preparing"}, "ms": 0})
    prov = get_provider()
    mode = "live_model" if prov.available and not prov.is_recorded else ("recorded_demo" if prov.is_recorded else "template")
    checks.append({"code": "ai_mode", "ok": True, "detail": {"mode": mode, "provider": prov.name, "model": prov.model,
                                                            "config_error": prov.config_error}, "ms": 0})
    return {"ready": all(c["ok"] for c in checks), "checks": checks, "topic_id": topic.id, "topic_code": topic.code,
            "edition_ids": eds[:2], "dataset_version": ds.version, "total_ms": int((time.monotonic() - t0) * 1000)}
