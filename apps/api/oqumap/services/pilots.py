"""Pilot protocol: snapshot of an intervention version, cohorts and assignment, design, measurements, dosage,
analysis plan, causal ceiling and a server-side status machine.

    draft ──► ready ──► active ──► completed
      │  ◄──    │          │
      └──► stopped ◄───────┘           (stopped/completed are terminal)

All checks are server-side. The intervention snapshot is frozen when the pilot leaves ``draft``; activation
re-verifies its hash against the reviewed (immutable) version.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import measurement_models as mm
from .. import models as m
from ..db import utcnow
from ..errors import ApiError, forbidden, not_found
from ..schemas import interventions as S
from . import clock
from . import interventions as ivs
from .auth import Principal
from .common import audit, get_dataset
from .measurement_messages import CAUSAL_LEVELS, label, render

MIN_CLUSTERS_RANDOMIZED = 5
MIN_ITS_PRE_POINTS = 3
MIN_STEPPED_WAVES = 2

# (from, to) -> roles allowed (any of)
TRANSITIONS: dict[tuple[str, str], tuple[str, ...]] = {
    ("draft", "ready"): ("methodist",),
    ("ready", "draft"): ("methodist",),
    ("draft", "stopped"): ("approver",),
    ("ready", "stopped"): ("approver",),
    ("ready", "active"): ("approver",),
    ("active", "completed"): ("methodist", "approver"),
    ("active", "stopped"): ("approver",),
}

DESIGN_CEILING = {
    "single_group": "descriptive_change",
    "matched_comparison": "descriptive_comparison",  # → adjusted_association when baseline adjustment is pre-registered
    "interrupted_time_series": "external_analysis_required",  # protocol only: no built-in estimate
    "cluster_randomized": "causal_estimate",
    "stepped_wedge": "external_analysis_required",
}
PROTOCOL_ONLY_DESIGNS = {"interrupted_time_series", "stepped_wedge"}
COMPARISON_DESIGNS = {"matched_comparison", "cluster_randomized"}


def analysis_mode(design: str) -> str:
    return "protocol_only_external_analysis" if design in PROTOCOL_ONLY_DESIGNS else "built_in"


def causal_ceiling(design: str, analysis_plan: dict) -> str:
    if design == "matched_comparison" and (analysis_plan or {}).get("adjustment") == "baseline_strata":
        return "adjusted_association"
    return DESIGN_CEILING[design]


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _snapshot(session: Session, v: mm.InterventionVersion) -> dict:
    snap = ivs.version_payload(session, v)
    snap.pop("used_by_pilots", None)
    return snap


def canonical_content(snapshot: dict) -> dict:
    """Content fields of a snapshot in the form used by ``content_hash`` (targets without display labels)."""
    out = {f: snapshot.get(f) for f in ivs.CONTENT_FIELDS if f != "targets"}
    out["targets"] = [{"target_type": t.get("target_type"), "target_id": t.get("target_id"),
                       "misconception_code": t.get("misconception_code")} for t in snapshot.get("targets") or []]
    return out


def snapshot_integrity(session: Session, pl: mm.Pilot) -> list[str]:
    """All checks must pass before activation; returns the codes of failed checks (never content)."""
    failed = []
    snap = pl.intervention_snapshot or {}
    v = session.get(mm.InterventionVersion, pl.intervention_version_id)
    if _sha(snap) != pl.snapshot_sha256:
        failed.append("stored_snapshot_hash")
    if v is None or v.intervention_id != pl.intervention_id or v.org_id != pl.org_id:
        return failed + ["version_reference"]
    if snap.get("id") != v.id or snap.get("version") != v.version or snap.get("intervention_id") != v.intervention_id:
        failed.append("snapshot_version_reference")
    if v.status != "reviewed":
        failed.append("version_not_reviewed")
    current = ivs.content_hash({f: getattr(v, f) for f in ivs.CONTENT_FIELDS})
    if current != v.content_sha256:
        failed.append("reviewed_version_modified")
    if snap.get("content_sha256") != v.content_sha256:
        failed.append("snapshot_content_sha")
    if ivs.content_hash(canonical_content(snap)) != v.content_sha256:
        failed.append("snapshot_canonical_content")
    return failed


def get_pilot(session: Session, org_id: str, pilot_id: str) -> mm.Pilot:
    pl = session.scalar(select(mm.Pilot).where(mm.Pilot.id == pilot_id, mm.Pilot.org_id == org_id))
    if pl is None:
        raise not_found("pilot", pilot_id)
    return pl


def pilot_cohorts(session: Session, pl: mm.Pilot) -> list[mm.PilotCohort]:
    return list(session.scalars(select(mm.PilotCohort).where(mm.PilotCohort.pilot_id == pl.id, mm.PilotCohort.org_id == pl.org_id)))


def _check_refs(session: Session, org_id: str, ds: m.Dataset, data: dict) -> None:
    """Every referenced object must belong to the pilot's dataset / organisation (404 otherwise)."""
    if data.get("topic_id"):
        t = session.get(m.Topic, data["topic_id"])
        if t is None or t.program_version_id != ds.program_version_id:
            raise not_found("topic", data["topic_id"])
    if data.get("objective_id"):
        o = session.get(m.LearningObjective, data["objective_id"])
        if o is None or o.program_version_id != ds.program_version_id:
            raise not_found("objective", data["objective_id"])
        if data.get("topic_id") and o.topic_id != data["topic_id"]:
            raise ApiError("objective_topic_mismatch", "Цель не относится к выбранной теме", 422)
    for key in ("baseline_assessment_id", "outcome_assessment_id"):
        if data.get(key):
            a = session.get(m.Assessment, data[key])
            if a is None or a.dataset_id != ds.id or a.org_id != org_id:
                raise not_found("assessment", data[key])
    for aid in data.get("pre_period_assessment_ids") or []:
        a = session.get(m.Assessment, aid)
        if a is None or a.dataset_id != ds.id or a.org_id != org_id:
            raise not_found("assessment", aid)
    if data.get("decision_id"):
        d = session.get(m.Decision, data["decision_id"])
        if d is None or d.org_id != org_id or d.dataset_id != ds.id:
            raise not_found("decision", data["decision_id"])
    seen = set()
    for c in data.get("cohorts") or []:
        cid = c["cohort_id"]
        co = session.get(m.Cohort, cid)
        if co is None or co.dataset_id != ds.id or co.org_id != org_id:
            raise not_found("cohort", cid)
        if cid in seen:
            raise ApiError("cohort_in_two_arms", "Класс указан дважды", 422, {"cohort_id": cid})
        seen.add(cid)


def _next_code(session: Session, org_id: str, skip: set[str] | None = None) -> str:
    n = int(session.scalar(select(func.count()).select_from(mm.Pilot).where(mm.Pilot.org_id == org_id)) or 0)
    while True:
        n += 1
        code = f"PIL-{n:03d}"
        if code in (skip or set()):
            continue
        if not session.scalar(select(mm.Pilot.id).where(mm.Pilot.org_id == org_id, mm.Pilot.code == code)):
            return code


def create(session: Session, p: Principal, body: S.PilotCreate, code: str | None = None) -> dict:
    """Create a draft pilot. An auto-generated code that another request took in the meantime is retried with the
    next free code (unique constraint + full rollback); an explicit code collision is a 409."""
    p.require("methodist")
    skip: set[str] = set()
    for attempt in range(5):
        chosen = code or _next_code(session, p.org_id, skip)
        try:
            return _create(session, p, body, chosen)
        except IntegrityError:
            session.rollback()
            if code is not None or attempt == 4:
                raise ApiError("concurrent_modification", "Код пилота уже занят; повторите", 409, {"code": chosen}) from None
            skip.add(chosen)
    raise AssertionError("unreachable")


def _create(session: Session, p: Principal, body: S.PilotCreate, code: str) -> dict:
    ds = get_dataset(session, p.org_id, body.dataset_id)
    iv = ivs.get_intervention(session, p.org_id, body.intervention_id)
    if iv.status == "archived":
        raise ApiError("intervention_archived", "Интервенция в архиве; новый пилот с ней не создаётся", 409)
    if iv.dataset_id and iv.dataset_id != ds.id:
        raise ApiError("intervention_scope_mismatch", "Интервенция относится к другому набору данных", 422)
    v = ivs.get_version(session, iv, body.intervention_version, prefer_reviewed=True)
    data = body.model_dump()
    _check_refs(session, p.org_id, ds, data)
    snap = _snapshot(session, v)
    plan = body.analysis_plan.model_dump()
    pl = mm.Pilot(
        org_id=p.org_id, dataset_id=ds.id, code=code, title=ivs.clean_text(body.title, 300),
        status="draft", design=body.design, assignment_unit=body.assignment_unit,
        causal_ceiling=causal_ceiling(body.design, plan), intervention_id=iv.id, intervention_version_id=v.id,
        intervention_snapshot=snap, snapshot_sha256=_sha(snap), decision_id=body.decision_id, topic_id=body.topic_id,
        objective_id=body.objective_id, primary_outcome_ru=ivs.clean_text(body.primary_outcome_ru, 1000),
        baseline_assessment_id=body.baseline_assessment_id, outcome_assessment_id=body.outcome_assessment_id,
        pre_period_assessment_ids=list(body.pre_period_assessment_ids), start_date=body.start_date, end_date=body.end_date,
        follow_up_due=body.follow_up_due, owner=ivs.clean_text(body.owner, 200),
        minutes_per_session=body.minutes_per_session or v.minutes_per_session,
        sessions_per_week=body.sessions_per_week or v.sessions_per_week,
        duration_weeks=body.duration_weeks or v.duration_weeks,
        inclusion_criteria=ivs.clean_text(body.inclusion_criteria, 2000),
        exclusion_criteria=ivs.clean_text(body.exclusion_criteria, 2000),
        analysis_plan=plan, created_by=p.user_id, is_synthetic=ds.is_synthetic)
    session.add(pl)
    session.flush()
    for c in body.cohorts:
        session.add(mm.PilotCohort(org_id=p.org_id, pilot_id=pl.id, cohort_id=c.cohort_id, arm=c.arm, wave=c.wave))
    session.add(mm.PilotEvent(org_id=p.org_id, pilot_id=pl.id, from_status=None, to_status="draft", note="", user_id=p.user_id))
    audit(session, p.org_id, p.user_id, "pilot.create", "pilot", pl.id, code=pl.code, design=pl.design,
          intervention_version=v.version)
    session.commit()
    return payload(session, pl, p)


def update(session: Session, p: Principal, pilot_id: str, body: S.PilotPatch) -> dict:
    p.require("methodist")
    pl = get_pilot(session, p.org_id, pilot_id)
    if pl.status != "draft":
        raise ApiError("protocol_locked", "Протокол можно менять только в статусе draft", 409, {"status": pl.status})
    ds = session.get(m.Dataset, pl.dataset_id)
    data = body.model_dump(exclude_unset=True)
    merged = {"topic_id": data.get("topic_id", pl.topic_id), "objective_id": data.get("objective_id", pl.objective_id),
              **{k: v for k, v in data.items() if k not in ("topic_id", "objective_id")}}
    _check_refs(session, p.org_id, ds, merged)
    for f in ("title", "primary_outcome_ru", "owner", "inclusion_criteria", "exclusion_criteria"):
        if data.get(f) is not None:
            setattr(pl, f, ivs.clean_text(data[f], 2000))
    for f in ("decision_id", "topic_id", "objective_id", "assignment_unit", "design", "baseline_assessment_id",
              "outcome_assessment_id", "start_date", "end_date", "follow_up_due", "minutes_per_session", "sessions_per_week",
              "duration_weeks"):
        if f in data:
            setattr(pl, f, data[f])
    if data.get("pre_period_assessment_ids") is not None:
        pl.pre_period_assessment_ids = list(data["pre_period_assessment_ids"])
    if data.get("analysis_plan") is not None:
        pl.analysis_plan = body.analysis_plan.model_dump()
    if data.get("intervention_version") is not None:
        iv = ivs.get_intervention(session, p.org_id, pl.intervention_id)
        v = ivs.get_version(session, iv, data["intervention_version"])
        snap = _snapshot(session, v)
        pl.intervention_version_id, pl.intervention_snapshot, pl.snapshot_sha256 = v.id, snap, _sha(snap)
    if body.cohorts is not None:
        for old in pilot_cohorts(session, pl):
            session.delete(old)
        session.flush()
        for c in body.cohorts:
            session.add(mm.PilotCohort(org_id=p.org_id, pilot_id=pl.id, cohort_id=c.cohort_id, arm=c.arm, wave=c.wave))
        pl.randomization = None  # any manual change of assignment invalidates a recorded randomisation
    if "design" in data or "cohorts" in data or "assignment_unit" in data:
        if pl.randomization and pl.randomization.get("design") != pl.design:
            pl.randomization = None
    pl.causal_ceiling = causal_ceiling(pl.design, pl.analysis_plan)
    audit(session, p.org_id, p.user_id, "pilot.update", "pilot", pl.id, fields=sorted(data))
    session.commit()
    return payload(session, pl, p)


def _cluster_of(cohort: m.Cohort, unit: str) -> str:
    return cohort.school_id if unit == "school" else cohort.id


def randomize(session: Session, p: Principal, pilot_id: str, body: S.RandomizeRequest) -> dict:
    """Server-side seeded assignment of clusters (cohort or school) to arms (cluster_randomized) or to waves
    (stepped_wedge). The seed, the clusters and the result are recorded and audited."""
    p.require("methodist")
    pl = get_pilot(session, p.org_id, pilot_id)
    if pl.status != "draft":
        raise ApiError("protocol_locked", "Назначение возможно только в статусе draft", 409)
    if pl.design not in ("cluster_randomized", "stepped_wedge"):
        raise ApiError("randomization_not_applicable", "Рандомизация применяется только к cluster_randomized и stepped_wedge", 422)
    ds = session.get(m.Dataset, pl.dataset_id)
    _check_refs(session, p.org_id, ds, {"cohorts": [{"cohort_id": c} for c in body.cohort_ids]})
    cohorts = {c: session.get(m.Cohort, c) for c in body.cohort_ids}
    clusters = sorted({_cluster_of(co, pl.assignment_unit) for co in cohorts.values()})
    rng = np.random.default_rng(body.seed)
    order = [clusters[i] for i in rng.permutation(len(clusters))]
    assignment: dict[str, dict] = {}
    if pl.design == "cluster_randomized":
        half = (len(order) + 1) // 2
        for i, cl in enumerate(order):
            assignment[cl] = {"arm": "intervention" if i < half else "comparison", "wave": None}
    else:
        n_waves = max(MIN_STEPPED_WAVES, min(4, len(order) // 2))
        for i, cl in enumerate(order):
            assignment[cl] = {"arm": "intervention", "wave": 1 + i % n_waves}
    for old in pilot_cohorts(session, pl):
        session.delete(old)
    session.flush()
    for cid, co in cohorts.items():
        a = assignment[_cluster_of(co, pl.assignment_unit)]
        session.add(mm.PilotCohort(org_id=p.org_id, pilot_id=pl.id, cohort_id=cid, arm=a["arm"], wave=a["wave"]))
    pl.randomization = {"seed": body.seed, "method": "numpy_default_rng_permutation", "unit": pl.assignment_unit,
                        "design": pl.design, "clusters": [{"cluster_id": cl, **assignment[cl]} for cl in order],
                        "by": p.user_id, "at": utcnow().isoformat()}
    audit(session, p.org_id, p.user_id, "pilot.randomize", "pilot", pl.id, seed=body.seed, n_clusters=len(clusters))
    session.commit()
    return payload(session, pl, p)


def validate_protocol(session: Session, pl: mm.Pilot, for_status: str = "ready") -> dict:
    errors, warnings = [], []
    cohorts = pilot_cohorts(session, pl)
    co = {c.cohort_id: session.get(m.Cohort, c.cohort_id) for c in cohorts}
    for f, val in (("title", pl.title), ("owner", pl.owner), ("start_date", pl.start_date), ("end_date", pl.end_date),
                   ("primary_outcome_ru", pl.primary_outcome_ru), ("follow_up_due", pl.follow_up_due)):
        if not val:
            errors.append(render("missing_field", {"field": f}, "fail"))
    if pl.design != "interrupted_time_series" and not pl.baseline_assessment_id:
        errors.append(render("missing_field", {"field": "baseline_assessment_id"}, "fail"))
    if pl.start_date and pl.end_date and pl.end_date < pl.start_date:
        errors.append(render("dates_invalid", {}, "fail"))
    if pl.baseline_assessment_id and pl.start_date:
        a = session.get(m.Assessment, pl.baseline_assessment_id)
        if a.administered_on and a.administered_on > pl.start_date:
            errors.append(render("baseline_after_start", {}, "fail"))
    if pl.end_date and pl.follow_up_due and pl.follow_up_due < pl.end_date:
        errors.append(render("follow_up_before_end", {}, "fail"))
    if pl.outcome_assessment_id and pl.start_date:
        oa = session.get(m.Assessment, pl.outcome_assessment_id)
        if oa.administered_on and oa.administered_on < pl.start_date:
            errors.append(render("outcome_before_start", {}, "fail"))
    if pl.start_date and pl.end_date and pl.end_date >= pl.start_date:
        cal_weeks = round(((pl.end_date - pl.start_date).days + 1) / 7)
        if abs(cal_weeks - pl.duration_weeks) > 1:
            warnings.append(render("duration_calendar_mismatch", {"weeks": pl.duration_weeks, "calendar_weeks": cal_weeks}, "warn"))
    plan = pl.analysis_plan or {}
    est = plan.get("primary_estimand")
    if est and ((pl.design in COMPARISON_DESIGNS and est != "difference_in_mean_changes")
                or (pl.design == "single_group" and est != "mean_paired_change")
                or pl.design in PROTOCOL_ONLY_DESIGNS):
        errors.append(render("estimand_design_mismatch", {"estimand": est, "design": pl.design}, "fail"))
    if pl.design in PROTOCOL_ONLY_DESIGNS:
        if not plan.get("external_analysis_acknowledged"):
            errors.append(render("external_analysis_not_acknowledged", {"design": pl.design}, "fail"))
        warnings.append(render("protocol_only_external_analysis", {"design": pl.design}, "warn"))
    inter = [c for c in cohorts if c.arm == "intervention"]
    comp = [c for c in cohorts if c.arm == "comparison"]
    if not inter:
        errors.append(render("no_intervention_cohorts", {}, "fail"))
    if pl.design == "single_group" and comp:
        errors.append(render("comparison_not_allowed", {}, "fail"))
    if pl.design in ("matched_comparison", "cluster_randomized") and not comp:
        errors.append(render("no_comparison_cohorts", {"design": pl.design}, "fail"))
    if pl.assignment_unit == "school":
        arms_by_school: dict[str, set] = {}
        for c in cohorts:
            arms_by_school.setdefault(co[c.cohort_id].school_id, set()).add((c.arm, c.wave))
        if any(len(v) > 1 for v in arms_by_school.values()):
            errors.append(render("assignment_unit_mixed", {}, "fail"))
    if pl.design in ("cluster_randomized", "stepped_wedge"):
        rec = pl.randomization or {}
        recorded = {x["cluster_id"]: (x["arm"], x["wave"]) for x in rec.get("clusters", [])}
        actual = {_cluster_of(co[c.cohort_id], pl.assignment_unit): (c.arm, c.wave) for c in cohorts}
        if not rec or rec.get("design") != pl.design or recorded != actual:
            errors.append(render("randomization_not_recorded", {}, "fail"))
        if pl.design == "cluster_randomized":
            na = len({_cluster_of(co[c.cohort_id], pl.assignment_unit) for c in inter})
            nb = len({_cluster_of(co[c.cohort_id], pl.assignment_unit) for c in comp})
            if na < MIN_CLUSTERS_RANDOMIZED or nb < MIN_CLUSTERS_RANDOMIZED:
                errors.append(render("too_few_clusters_for_randomization", {"min": MIN_CLUSTERS_RANDOMIZED, "a": na, "b": nb}, "fail"))
        else:
            waves = {c.wave for c in inter if c.wave}
            if len(waves) < MIN_STEPPED_WAVES:
                errors.append(render("stepped_wedge_needs_waves", {"min": MIN_STEPPED_WAVES}, "fail"))
    if pl.design == "interrupted_time_series":
        pts = set(pl.pre_period_assessment_ids or [])
        if len(pts) < MIN_ITS_PRE_POINTS:
            errors.append(render("its_needs_pre_points", {"min": MIN_ITS_PRE_POINTS, "n": len(pts)}, "fail"))
    v = session.get(mm.InterventionVersion, pl.intervention_version_id)
    iv = session.get(mm.Intervention, pl.intervention_id)
    if v.status != "reviewed":
        errors.append(render("intervention_not_reviewed", {"status": v.status}, "fail"))
    if iv.status == "archived" and for_status in ("ready", "active"):
        errors.append(render("intervention_archived", {}, "fail"))
    # cohorts already in another active pilot (warning: overlapping interventions confound each other)
    if cohorts:
        busy = session.execute(select(mm.PilotCohort.cohort_id, mm.Pilot.code).join(mm.Pilot, mm.Pilot.id == mm.PilotCohort.pilot_id)
                               .where(mm.PilotCohort.cohort_id.in_(list(co)), mm.Pilot.status == "active",
                                      mm.Pilot.id != pl.id, mm.Pilot.org_id == pl.org_id)).all()
        for cid, code in busy:
            warnings.append(render("cohort_in_active_pilot", {"cohort": co[cid].code, "pilot": code}, "warn"))
    if pl.design == "single_group":
        warnings.append(render("single_group_no_causal", {}, "info"))
    if pl.design == "matched_comparison":
        warnings.append(render("observational_comparison", {}, "info"))
    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _roles(p: Principal) -> set[str]:
    return set(p.user.roles or [])


def allowed_transitions(pl: mm.Pilot, p: Principal | None) -> list[str]:
    roles = _roles(p) if p else set()
    out = []
    for (frm, to), need in TRANSITIONS.items():
        if frm == pl.status and ("admin" in roles or roles & set(need)):
            out.append(to)
    return out


def transition(session: Session, p: Principal, pilot_id: str, body: S.TransitionRequest) -> dict:
    pl = get_pilot(session, p.org_id, pilot_id)
    key = (pl.status, body.to_status)
    if key not in TRANSITIONS:
        raise ApiError("invalid_transition", f"Переход {pl.status} → {body.to_status} не разрешён", 409,
                       {"from": pl.status, "to": body.to_status,
                        "allowed": sorted({t for (f, t) in TRANSITIONS if f == pl.status})})
    roles = _roles(p)
    if "admin" not in roles and not roles & set(TRANSITIONS[key]):
        raise forbidden(details={"required_roles": list(TRANSITIONS[key])})
    note = ivs.clean_text(body.note, 1000)
    if body.to_status in ("ready", "active"):
        val = validate_protocol(session, pl, body.to_status)
        if not val["ok"]:
            raise ApiError("protocol_invalid", "Протокол не готов", 422, {"errors": val["errors"]})
    if body.to_status == "active":
        failed = snapshot_integrity(session, pl)
        if failed:
            session.rollback()
            # safe audit: check codes only, never the intervention content
            audit(session, p.org_id, p.user_id, "pilot.snapshot_mismatch", "pilot", pl.id, failed_checks=failed)
            session.commit()
            raise ApiError("snapshot_mismatch", "Снимок интервенции не совпадает с рецензированной версией", 409,
                           {"failed_checks": failed})
        pl.activated_by, pl.activated_at = p.user_id, utcnow()
    if body.to_status == "completed" and pl.end_date and pl.end_date > clock.today():
        if not body.override_future_end or len(note) < 3:
            raise ApiError("end_date_in_future", "Плановая дата окончания ещё не наступила: нужен явный override с причиной", 409,
                           {"end_date": pl.end_date.isoformat(), "today": clock.today().isoformat()})
    if body.to_status == "stopped":
        if len(note) < 3:
            raise ApiError("validation_error", "Укажите причину остановки", 422, {"field": "note"})
        pl.stop_reason = note
    session.add(mm.PilotEvent(org_id=p.org_id, pilot_id=pl.id, from_status=pl.status, to_status=body.to_status, note=note,
                              user_id=p.user_id))
    audit(session, p.org_id, p.user_id, "pilot.transition", "pilot", pl.id, frm=pl.status, to=body.to_status)
    pl.status = body.to_status
    session.commit()
    return payload(session, pl, p)


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


def _assessment_ref(session: Session, aid: str | None) -> dict | None:
    if not aid:
        return None
    a = session.get(m.Assessment, aid)
    f = session.get(m.AssessmentForm, a.form_id)
    sc = session.get(m.Scale, f.scale_id)
    return {"assessment_id": a.id, "code": a.code, "stage": a.stage, "form_code": f.code, "scale_code": sc.code,
            "linking_method": sc.linking_method, "administered_on": a.administered_on.isoformat() if a.administered_on else None}


def _learners_per_cohort(session: Session, cohort_ids: list[str]) -> dict[str, int]:
    if not cohort_ids:
        return {}
    rows = session.execute(select(m.Learner.cohort_id, func.count()).where(m.Learner.cohort_id.in_(cohort_ids))
                           .group_by(m.Learner.cohort_id)).all()
    return {c: int(n) for c, n in rows}


def payload(session: Session, pl: mm.Pilot, p: Principal | None = None) -> dict:
    cohorts = pilot_cohorts(session, pl)
    sizes = _learners_per_cohort(session, [c.cohort_id for c in cohorts])
    rows = []
    for c in cohorts:
        co = session.get(m.Cohort, c.cohort_id)
        sch = session.get(m.School, co.school_id) if co else None
        rows.append({"cohort_id": c.cohort_id, "code": co.code if co else None, "school_id": co.school_id if co else None,
                     "school_code": sch.code if sch else None, "arm": c.arm, "wave": c.wave, "n_learners": sizes.get(c.cohort_id)})
    rows.sort(key=lambda r: (r["arm"] != "intervention", r["code"] or ""))
    topic = session.get(m.Topic, pl.topic_id)
    obj = session.get(m.LearningObjective, pl.objective_id) if pl.objective_id else None
    events = list(session.scalars(select(mm.PilotEvent).where(mm.PilotEvent.pilot_id == pl.id).order_by(mm.PilotEvent.created_at)))
    users = ivs._users(session, [e.user_id for e in events] + [pl.created_by])
    latest = session.scalar(select(mm.PilotOutcome).where(mm.PilotOutcome.pilot_id == pl.id, mm.PilotOutcome.org_id == pl.org_id)
                            .order_by(mm.PilotOutcome.created_at.desc()))
    v = session.get(mm.InterventionVersion, pl.intervention_version_id)
    iv = session.get(mm.Intervention, pl.intervention_id)
    rnd = dict(pl.randomization) if pl.randomization else None
    if rnd:
        rnd.pop("by", None)
    return {
        "id": pl.id, "code": pl.code, "title": pl.title, "dataset_id": pl.dataset_id, "status": pl.status, "design": pl.design,
        "assignment_unit": pl.assignment_unit, "causal_ceiling": label(CAUSAL_LEVELS, pl.causal_ceiling),
        "analysis_mode": analysis_mode(pl.design),
        "intervention_id": pl.intervention_id, "intervention_code": iv.code, "intervention_version_id": pl.intervention_version_id,
        "intervention_version": v.version, "intervention_snapshot": pl.intervention_snapshot, "snapshot_sha256": pl.snapshot_sha256,
        "snapshot_locked": pl.status != "draft", "decision_id": pl.decision_id,
        "topic": {"topic_id": topic.id, "code": topic.code, "title_ru": topic.title_ru, "title_kz": topic.title_kz} if topic else None,
        "objective": {"objective_id": obj.id, "code": obj.code, "text_ru": obj.text_ru, "text_kz": obj.text_kz} if obj else None,
        "primary_outcome_ru": pl.primary_outcome_ru, "cohorts": rows, "randomization": rnd,
        "baseline_assessment": _assessment_ref(session, pl.baseline_assessment_id),
        "outcome_assessment": _assessment_ref(session, pl.outcome_assessment_id),
        "pre_period_assessment_ids": pl.pre_period_assessment_ids or [],
        "start_date": pl.start_date.isoformat() if pl.start_date else None,
        "end_date": pl.end_date.isoformat() if pl.end_date else None,
        "follow_up_due": pl.follow_up_due.isoformat() if pl.follow_up_due else None,
        "owner": pl.owner,
        "planned": {"minutes_per_session": pl.minutes_per_session, "sessions_per_week": pl.sessions_per_week,
                    "duration_weeks": pl.duration_weeks, "total_sessions": pl.sessions_per_week * pl.duration_weeks,
                    "total_minutes": pl.minutes_per_session * pl.sessions_per_week * pl.duration_weeks},
        "inclusion_criteria": pl.inclusion_criteria, "exclusion_criteria": pl.exclusion_criteria,
        "analysis_plan": pl.analysis_plan, "stop_reason": pl.stop_reason,
        "validation": validate_protocol(session, pl) if pl.status in ("draft", "ready") else {"ok": True, "errors": [], "warnings": []},
        "allowed_transitions": allowed_transitions(pl, p),
        "events": [{"from_status": e.from_status, "to_status": e.to_status, "note": e.note, "at": e.created_at.isoformat(),
                    "by": users.get(e.user_id)} for e in events],
        "latest_outcome": ({"id": latest.id, "status": latest.status, "causal_level": latest.causal_level,
                            "fidelity_class": latest.fidelity_class, "interim": latest.interim,
                            "created_at": latest.created_at.isoformat()} if latest else None),
        "created_at": pl.created_at.isoformat(), "created_by": users.get(pl.created_by), "is_synthetic": pl.is_synthetic,
    }


def list_pilots(session: Session, org_id: str, dataset_id: str | None = None, status: str | None = None,
                intervention_id: str | None = None, as_of: date | None = None) -> list[dict]:
    from .fidelity import fidelity_for

    q = select(mm.Pilot).where(mm.Pilot.org_id == org_id)
    if dataset_id:
        get_dataset(session, org_id, dataset_id)
        q = q.where(mm.Pilot.dataset_id == dataset_id)
    if status:
        q = q.where(mm.Pilot.status == status)
    if intervention_id:
        q = q.where(mm.Pilot.intervention_id == intervention_id)
    out = []
    for pl in session.scalars(q.order_by(mm.Pilot.code)):
        iv = session.get(mm.Intervention, pl.intervention_id)
        v = session.get(mm.InterventionVersion, pl.intervention_version_id)
        topic = session.get(m.Topic, pl.topic_id)
        latest = session.scalar(select(mm.PilotOutcome).where(mm.PilotOutcome.pilot_id == pl.id)
                                .order_by(mm.PilotOutcome.created_at.desc()))
        fid = fidelity_for(session, pl, as_of)["overall"]["classification"]["code"] if pl.status in ("active", "completed", "stopped") else None
        out.append({"id": pl.id, "code": pl.code, "title": pl.title, "dataset_id": pl.dataset_id, "status": pl.status,
                    "design": pl.design, "intervention_id": iv.id, "intervention_code": iv.code, "intervention_version": v.version,
                    "topic_code": topic.code if topic else None,
                    "start_date": pl.start_date.isoformat() if pl.start_date else None,
                    "end_date": pl.end_date.isoformat() if pl.end_date else None,
                    "follow_up_due": pl.follow_up_due.isoformat() if pl.follow_up_due else None,
                    "n_cohorts": len(pilot_cohorts(session, pl)), "fidelity": fid,
                    "outcome_status": latest.status if latest else None})
    return out


def today() -> date:
    """Backward-compatible alias; use ``clock.today()``."""
    return clock.today()
