"""Portfolio effectiveness: aggregates over pilots of the organisation (optionally one dataset).

No league tables of schools or teachers are produced; no "best intervention" is named (comparability and
repetition across contexts are not established by this data). Counts are by status/category only.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import measurement_models as mm
from .. import models as m
from ..db import utcnow
from . import analysis as an
from . import interventions as ivs
from .auth import Principal
from .fidelity import fidelity_for, resolve_as_of
from .measurement_messages import STATUS_LABELS, render
from .pilots import list_pilots, pilot_cohorts


def portfolio(session: Session, p: Principal, dataset_id: str | None = None, as_of: date | None = None) -> dict:
    as_of = resolve_as_of(None, as_of)  # one date for deadlines, fidelity and the pilot list
    q = select(mm.Pilot).where(mm.Pilot.org_id == p.org_id)
    if dataset_id:
        an.get_dataset(session, p.org_id, dataset_id)
        q = q.where(mm.Pilot.dataset_id == dataset_id)
    pilots = list(session.scalars(q.order_by(mm.Pilot.code)))
    counts = {s: 0 for s in mm.PILOT_STATUSES}
    fid_dist = {k: 0 for k in ("high", "moderate", "low", "unknown")}
    out_dist = {k: 0 for k in STATUS_LABELS}
    due, overdue, upcoming = [], [], []
    missing, queue = [], []
    topics_cov: dict[str, dict] = {}
    for pl in pilots:
        counts[pl.status] += 1
        latest = session.scalar(select(mm.PilotOutcome).where(mm.PilotOutcome.pilot_id == pl.id)
                                .order_by(mm.PilotOutcome.created_at.desc()))
        if latest is not None and not latest.interim:
            out_dist[latest.status] += 1
        fid = None
        if pl.status in ("active", "completed", "stopped"):
            fid = fidelity_for(session, pl, as_of)["overall"]
            fid_dist[fid["classification"]["code"]] += 1
        topic = session.get(m.Topic, pl.topic_id)
        tc = topics_cov.setdefault(topic.id, {"topic_id": topic.id, "code": topic.code, "title_ru": topic.title_ru,
                                              "title_kz": topic.title_kz, "pilots": 0, "active": 0, "with_outcome": 0,
                                              "objectives": set()})
        tc["pilots"] += 1
        tc["active"] += int(pl.status == "active")
        tc["with_outcome"] += int(latest is not None and not latest.interim)
        if pl.objective_id:
            tc["objectives"].add(session.get(m.LearningObjective, pl.objective_id).code)
        ref = {"pilot_id": pl.id, "code": pl.code, "title": pl.title, "status": pl.status,
               "follow_up_due": pl.follow_up_due.isoformat() if pl.follow_up_due else None}
        has_final = latest is not None and not latest.interim
        if pl.status in ("active", "completed") and pl.follow_up_due and not has_final:
            if pl.follow_up_due < as_of:
                overdue.append(ref)
                queue.append({**ref, "action": "run_follow_up_overdue", "priority": 1})
            elif (pl.follow_up_due - as_of).days <= 14:
                due.append(ref)
                queue.append({**ref, "action": "run_follow_up_due_soon", "priority": 2})
            else:
                upcoming.append(ref)
        # data needed for a conclusion
        gaps = []
        if not pl.baseline_assessment_id and pl.design != "interrupted_time_series":
            gaps.append("baseline_assessment")
        if pl.status in ("active", "completed") and not pl.outcome_assessment_id:
            gaps.append("outcome_assessment")
        if fid is not None and fid["missing_logs"] > 0:
            gaps.append("fidelity_logs")
        if fid is not None and fid["classification"]["code"] in ("low", "unknown"):
            gaps.append("adequate_implementation")
        if pl.design in ("matched_comparison", "cluster_randomized") and not any(c.arm == "comparison" for c in pilot_cohorts(session, pl)):
            gaps.append("comparison_group")
        if latest is not None and latest.status == "needs_more_data":
            gaps.append("more_matched_learners_or_clusters")
        if gaps:
            missing.append({**ref, "missing": gaps})
        if pl.status == "ready":
            queue.append({**ref, "action": "activate_or_return_to_draft", "priority": 3})
        if pl.status == "draft":
            queue.append({**ref, "action": "complete_protocol", "priority": 4})
        if has_final and not session.scalar(select(mm.PilotConclusion.id).where(mm.PilotConclusion.outcome_id == latest.id)):
            queue.append({**ref, "action": "record_conclusion", "priority": 2})
    pending = list(session.scalars(select(mm.InterventionEvidenceEntry).where(mm.InterventionEvidenceEntry.org_id == p.org_id,
                                                                              mm.InterventionEvidenceEntry.review_status == "proposed")))
    for e in pending:
        if any(e.pilot_id == pl.id for pl in pilots):
            pl = next(x for x in pilots if x.id == e.pilot_id)
            queue.append({"pilot_id": pl.id, "code": pl.code, "title": pl.title, "status": pl.status,
                          "follow_up_due": None, "action": "review_evidence_entry", "entry_id": e.id, "priority": 3})
    queue.sort(key=lambda r: (r["priority"], r["code"]))
    # interventions with repeated, comparable, accepted positive signals (≥ 2) — listed, not ranked
    ivq = select(mm.Intervention).where(mm.Intervention.org_id == p.org_id)
    repeated, repeated_synthetic, synthetic_evidence = [], [], 0
    for iv in session.scalars(ivq.order_by(mm.Intervention.code)):
        ev = ivs.evidence_summary(session, iv)
        synthetic_evidence += ev["accepted_synthetic_entries"]
        if ev["comparable_positive_signals"] >= 2:  # accepted real evidence only
            repeated.append({"intervention_id": iv.id, "code": iv.code, "comparable_positive_signals": ev["comparable_positive_signals"],
                             "by_status": ev["by_status"]})
        if ev["synthetic_comparable_positive_signals"] >= 2:
            repeated_synthetic.append({"intervention_id": iv.id, "code": iv.code, "is_synthetic": True,
                                       "comparable_positive_signals": ev["synthetic_comparable_positive_signals"]})
    # coverage: topics/objectives targeted by reviewed interventions vs piloted
    cur_ds = an.get_dataset(session, p.org_id, dataset_id) if dataset_id else None
    targeted_topics: set[str] = set()
    for t in session.scalars(select(mm.InterventionTarget).where(mm.InterventionTarget.org_id == p.org_id)):
        if t.topic_id:
            targeted_topics.add(t.topic_id)
        if t.objective_id:
            o = session.get(m.LearningObjective, t.objective_id)
            if o:
                targeted_topics.add(o.topic_id)
    topic_rows = []
    if cur_ds is not None:
        for t in session.scalars(select(m.Topic).where(m.Topic.program_version_id == cur_ds.program_version_id).order_by(m.Topic.order_index)):
            row = topics_cov.get(t.id, {"topic_id": t.id, "code": t.code, "title_ru": t.title_ru, "title_kz": t.title_kz,
                                        "pilots": 0, "active": 0, "with_outcome": 0, "objectives": set()})
            topic_rows.append({**row, "objectives": sorted(row["objectives"]), "has_interventions": t.id in targeted_topics})
    else:
        topic_rows = [{**r, "objectives": sorted(r["objectives"]), "has_interventions": r["topic_id"] in targeted_topics}
                      for r in topics_cov.values()]
    return {
        "generated_at": utcnow().isoformat(), "as_of": as_of.isoformat(), "dataset_id": dataset_id,
        "counts_by_status": counts,
        "follow_ups": {"overdue": overdue, "due_within_14_days": due, "upcoming": upcoming},
        "fidelity_distribution": fid_dist,
        "outcome_distribution": out_dist,
        "interventions_with_repeated_signals": repeated,
        "synthetic_evidence": {"accepted_entries": synthetic_evidence, "repeated_signals_demo_only": repeated_synthetic,
                               "counts_toward_recommendations": False},
        "coverage": {"topics": topic_rows, "topics_with_pilots": sum(1 for r in topic_rows if r["pilots"]),
                     "topics_total": len(topic_rows)},
        "missing_for_conclusions": missing,
        "action_queue": queue,
        "best_intervention": None,
        "best_intervention_reason": "not_shown_without_comparability_and_repetition",
        "pilots": list_pilots(session, p.org_id, dataset_id, as_of=as_of),
        "limitations": [
            {"code": "no_league_tables", "severity": "info", "params": {},
             "message_ru": "Портфель не ранжирует школы, учителей или интервенции; показываются только агрегаты по статусам.",
             "message_kz": "Портфель мектептерді, мұғалімдерді немесе интервенцияларды рейтингтемейді."},
            {"code": "best_not_shown", "severity": "info", "params": {},
             "message_ru": "«Лучшая интервенция» не определяется: нужны сопоставимые повторные пилоты в разных контекстах.",
             "message_kz": "«Ең жақсы интервенция» анықталмайды: әртүрлі контексте салыстырмалы қайталама пилоттар қажет."},
            *([render("synthetic_data")] if any(pl.is_synthetic for pl in pilots) else []),
        ],
    }
