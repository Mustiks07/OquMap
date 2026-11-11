"""Intervention library: versioned, reviewable, archivable — never physically deleted once published.

Rules (docs/INTERVENTION_AND_PILOT_PROTOCOL.md):
* identity (``Intervention``) + immutable content versions (``InterventionVersion``);
* only a ``draft`` version can be edited or deleted (and only if no pilot references it);
* ``reviewed`` versions are immutable; changes create a new draft version (``POST …/versions``);
* review / archive require the ``approver`` role; drafting requires ``methodist``;
* archived interventions keep their history and existing pilot snapshots; they cannot start new pilots;
* evidence accumulated from pilots lives in ``InterventionEvidenceEntry`` rows (accepted by a human), never in
  the version itself.
"""

from __future__ import annotations

import hashlib
import json
import re

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import measurement_models as mm
from .. import models as m
from ..db import utcnow
from ..demo.content import MISCONCEPTIONS
from ..errors import ApiError, not_found
from ..schemas import interventions as S
from .auth import Principal
from .common import audit, get_dataset
from .measurement_messages import render

CONTENT_FIELDS = ("title_ru", "title_kz", "description_ru", "description_kz", "grades", "languages", "minutes_per_session",
                  "sessions_per_week", "duration_weeks", "cadence_ru", "instructions_ru", "instructions_kz", "resources",
                  "evidence_level", "evidence_links", "contraindications_ru", "limitations_ru", "limitations_kz", "targets")

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: str, limit: int = 4000) -> str:
    """Strip control characters and surrounding whitespace, cap the length (notes and free text)."""
    return _CTRL.sub("", value or "").strip()[:limit]


def _clean_value(field: str, value):
    if isinstance(value, str):
        return clean_text(value, 8000)
    if field == "resources":
        return [clean_text(x, 300) for x in value if clean_text(x, 300)][:50]
    if field == "languages":
        return sorted({clean_text(x, 8).lower() for x in value if clean_text(x, 8)})
    if field == "grades":
        out = sorted({int(g) for g in value})
        if any(g < 1 or g > 12 for g in out):
            raise ApiError("validation_error", "grades: 1..12", 422, {"field": "grades"})
        return out
    if field == "evidence_links":
        links = []
        for x in value:
            d = x.model_dump() if hasattr(x, "model_dump") else dict(x)
            url = clean_text(d.get("url") or "", 1000) or None
            if url and not re.match(r"^(https?://|doc:|source:)", url):
                raise ApiError("validation_error", "evidence_links.url: http(s)://, doc: или source:", 422, {"field": "evidence_links"})
            links.append({"title": clean_text(d["title"], 300), "url": url, "kind": clean_text(d.get("kind") or "source", 40)})
        return links
    return value


def content_hash(content: dict) -> str:
    payload = {k: content.get(k) for k in CONTENT_FIELDS}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _program_ids(session: Session, org_id: str) -> set[str]:
    return set(session.scalars(select(m.ProgramVersion.id).where((m.ProgramVersion.org_id == org_id) | (m.ProgramVersion.org_id.is_(None)))))


def _resolve_targets(session: Session, org_id: str, targets) -> list[dict]:
    pv_ids = _program_ids(session, org_id)
    out, seen = [], set()
    for t in targets:
        d = t.model_dump() if hasattr(t, "model_dump") else dict(t)
        tt = d["target_type"]
        if tt == "misconception":
            code = (d.get("misconception_code") or "").strip()
            if code not in MISCONCEPTIONS:
                raise ApiError("unknown_misconception", "Неизвестный код типичной ошибки", 422, {"code": code})
            key = (tt, code)
            row = {"target_type": tt, "target_id": None, "misconception_code": code}
        else:
            model = m.Topic if tt == "topic" else m.LearningObjective
            obj = session.get(model, d.get("target_id") or "")
            if obj is None or obj.program_version_id not in pv_ids:
                raise not_found(tt, d.get("target_id"))
            key = (tt, obj.id)
            row = {"target_type": tt, "target_id": obj.id, "misconception_code": None}
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def _content_from(session: Session, org_id: str, body) -> dict:
    data = body.model_dump() if hasattr(body, "model_dump") else dict(body)
    content = {}
    for f in CONTENT_FIELDS:
        if f == "targets":
            content[f] = _resolve_targets(session, org_id, data.get("targets") or [])
        else:
            content[f] = _clean_value(f, data[f])
    if not content["title_ru"]:
        raise ApiError("validation_error", "Поле title_ru не заполнено", 422, {"field": "title_ru"})
    return content


def _index_targets(session: Session, v: mm.InterventionVersion) -> None:
    for old in session.scalars(select(mm.InterventionTarget).where(mm.InterventionTarget.intervention_version_id == v.id)):
        session.delete(old)
    for t in v.targets:
        session.add(mm.InterventionTarget(org_id=v.org_id, intervention_version_id=v.id, target_type=t["target_type"],
                                          topic_id=t["target_id"] if t["target_type"] == "topic" else None,
                                          objective_id=t["target_id"] if t["target_type"] == "objective" else None,
                                          misconception_code=t["misconception_code"]))


def get_intervention(session: Session, org_id: str, intervention_id: str) -> mm.Intervention:
    iv = session.scalar(select(mm.Intervention).where(mm.Intervention.id == intervention_id, mm.Intervention.org_id == org_id))
    if iv is None:
        raise not_found("intervention", intervention_id)
    return iv


def versions_of(session: Session, iv: mm.Intervention) -> list[mm.InterventionVersion]:
    return list(session.scalars(select(mm.InterventionVersion).where(mm.InterventionVersion.intervention_id == iv.id,
                                                                     mm.InterventionVersion.org_id == iv.org_id)
                                .order_by(mm.InterventionVersion.version)))


def get_version(session: Session, iv: mm.Intervention, version: int | None = None, prefer_reviewed: bool = False) -> mm.InterventionVersion:
    vs = versions_of(session, iv)
    if version is not None:
        v = next((x for x in vs if x.version == version), None)
        if v is None:
            raise not_found("intervention_version", f"{iv.id}:v{version}")
        return v
    if prefer_reviewed:
        rev = [x for x in vs if x.status == "reviewed"]
        if rev:
            return rev[-1]
    return vs[-1]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def create(session: Session, p: Principal, body: S.InterventionCreate) -> dict:
    p.require("methodist")
    if body.dataset_id:
        get_dataset(session, p.org_id, body.dataset_id)
    code = body.code.strip()
    if session.scalar(select(mm.Intervention).where(mm.Intervention.org_id == p.org_id, mm.Intervention.code == code)):
        raise ApiError("duplicate_code", "Интервенция с таким кодом уже есть", 409, {"code": code})
    content = _content_from(session, p.org_id, body)
    iv = mm.Intervention(org_id=p.org_id, dataset_id=body.dataset_id, code=code, created_by=p.user_id, is_synthetic=p.org.is_demo)
    session.add(iv)
    session.flush()
    v = mm.InterventionVersion(org_id=p.org_id, intervention_id=iv.id, version=1, status="draft", author_id=p.user_id,
                               content_sha256=content_hash(content), change_note="", **content)
    session.add(v)
    session.flush()
    _index_targets(session, v)
    audit(session, p.org_id, p.user_id, "intervention.create", "intervention", iv.id, code=code, version=1)
    session.commit()
    return payload(session, iv)


def _used_by_pilots(session: Session, version_id: str) -> int:
    return int(session.scalar(select(func.count()).select_from(mm.Pilot).where(mm.Pilot.intervention_version_id == version_id)) or 0)


def _require_editable(session: Session, iv: mm.Intervention, v: mm.InterventionVersion) -> None:
    if iv.status == "archived":
        raise ApiError("intervention_archived", "Интервенция в архиве", 409)
    if v.status != "draft":
        raise ApiError("version_immutable", "Версия прошла рецензирование и не изменяется; создайте новую версию", 409,
                       {"version": v.version, "status": v.status})


def update_draft(session: Session, p: Principal, intervention_id: str, body: S.InterventionPatch) -> dict:
    p.require("methodist")
    iv = get_intervention(session, p.org_id, intervention_id)
    v = get_version(session, iv)
    if body.expected_version is not None and body.expected_version != v.version:
        raise ApiError("version_conflict", "Версия изменилась; обновите страницу", 409, {"latest": v.version})
    _require_editable(session, iv, v)
    patch = body.model_dump(exclude_unset=True, exclude={"expected_version"})
    for f, val in patch.items():
        if val is None:
            continue
        setattr(v, f, _resolve_targets(session, p.org_id, val) if f == "targets" else _clean_value(f, getattr(body, f)))
    if not v.title_ru:
        raise ApiError("validation_error", "Поле title_ru не заполнено", 422, {"field": "title_ru"})
    v.content_sha256 = content_hash({f: getattr(v, f) for f in CONTENT_FIELDS})
    _index_targets(session, v)
    audit(session, p.org_id, p.user_id, "intervention.update_draft", "intervention", iv.id, version=v.version,
          fields=sorted(k for k, val in patch.items() if val is not None))
    session.commit()
    return payload(session, iv)


def new_version(session: Session, p: Principal, intervention_id: str, body: S.NewVersionRequest) -> dict:
    p.require("methodist")
    iv = get_intervention(session, p.org_id, intervention_id)
    if iv.status == "archived":
        raise ApiError("intervention_archived", "Интервенция в архиве", 409)
    latest = get_version(session, iv)
    if latest.status == "draft":
        raise ApiError("draft_exists", "Последняя версия ещё черновик: измените её или отправьте на рецензирование", 409,
                       {"version": latest.version})
    content = {f: getattr(latest, f) for f in CONTENT_FIELDS}
    patch = body.model_dump(exclude_unset=True, exclude={"expected_version", "change_note"})
    for f, val in patch.items():
        if val is not None:
            content[f] = _resolve_targets(session, p.org_id, val) if f == "targets" else _clean_value(f, getattr(body, f))
    v = mm.InterventionVersion(org_id=p.org_id, intervention_id=iv.id, version=latest.version + 1, status="draft",
                               author_id=p.user_id, content_sha256=content_hash(content),
                               change_note=clean_text(body.change_note, 1000), **content)
    session.add(v)
    session.flush()
    _index_targets(session, v)
    audit(session, p.org_id, p.user_id, "intervention.new_version", "intervention", iv.id, version=v.version)
    session.commit()
    return payload(session, iv)


def review(session: Session, p: Principal, intervention_id: str, version: int, body: S.ReviewRequest) -> dict:
    p.require("approver")
    iv = get_intervention(session, p.org_id, intervention_id)
    v = get_version(session, iv, version)
    _require_editable(session, iv, v)
    problems = []
    if not v.instructions_ru:
        problems.append("instructions_ru")
    if not v.targets:
        problems.append("targets")
    if problems:
        raise ApiError("incomplete_for_review", "Для рецензирования нужны инструкции и хотя бы одна цель", 422, {"missing": problems})
    v.status = "reviewed"
    v.reviewed_by = p.user_id
    v.reviewed_at = utcnow()
    v.review_note = clean_text(body.note, 1000) or None
    v.content_sha256 = content_hash({f: getattr(v, f) for f in CONTENT_FIELDS})
    audit(session, p.org_id, p.user_id, "intervention.review", "intervention", iv.id, version=v.version, sha256=v.content_sha256)
    session.commit()
    return payload(session, iv)


def archive(session: Session, p: Principal, intervention_id: str, body: S.ArchiveRequest) -> dict:
    p.require("approver")
    iv = get_intervention(session, p.org_id, intervention_id)
    if iv.status == "archived":
        raise ApiError("invalid_state", "Интервенция уже в архиве", 409)
    iv.status = "archived"
    iv.archived_reason = clean_text(body.reason, 1000)
    iv.archived_at = utcnow()
    iv.archived_by = p.user_id
    for v in versions_of(session, iv):
        if v.status == "draft":
            v.status = "archived"
    audit(session, p.org_id, p.user_id, "intervention.archive", "intervention", iv.id)
    session.commit()
    return payload(session, iv)


def delete_draft(session: Session, p: Principal, intervention_id: str, version: int) -> dict:
    """Physically delete an unpublished draft version that no pilot references. Reviewed history is never deleted."""
    p.require("methodist")
    iv = get_intervention(session, p.org_id, intervention_id)
    v = get_version(session, iv, version)
    if v.status != "draft":
        raise ApiError("version_immutable", "Удалять можно только черновик; используйте архивирование", 409, {"status": v.status})
    if _used_by_pilots(session, v.id):
        raise ApiError("version_in_use", "Черновик используется в пилоте", 409)
    vs = versions_of(session, iv)
    for t in session.scalars(select(mm.InterventionTarget).where(mm.InterventionTarget.intervention_version_id == v.id)):
        session.delete(t)
    session.delete(v)
    deleted_identity = len(vs) == 1
    if deleted_identity:
        session.flush()
        session.delete(iv)
    audit(session, p.org_id, p.user_id, "intervention.delete_draft", "intervention", iv.id, version=version)
    session.commit()
    return {"deleted_version": version, "intervention_deleted": deleted_identity,
            "intervention": None if deleted_identity else payload(session, iv)}


def add_target(session: Session, p: Principal, intervention_id: str, target: S.TargetIn) -> dict:
    p.require("methodist")
    iv = get_intervention(session, p.org_id, intervention_id)
    v = get_version(session, iv)
    _require_editable(session, iv, v)
    v.targets = _resolve_targets(session, p.org_id, list(v.targets) + [target])
    v.content_sha256 = content_hash({f: getattr(v, f) for f in CONTENT_FIELDS})
    _index_targets(session, v)
    audit(session, p.org_id, p.user_id, "intervention.link_target", "intervention", iv.id, version=v.version,
          target_type=target.target_type)
    session.commit()
    return payload(session, iv)


# ---------------------------------------------------------------------------
# Read models
# ---------------------------------------------------------------------------


def _target_labels(session: Session, targets: list[dict]) -> list[dict]:
    out = []
    for t in targets:
        if t["target_type"] == "misconception":
            ru, kz, _ = MISCONCEPTIONS.get(t["misconception_code"], (t["misconception_code"], t["misconception_code"], ""))
            out.append({**t, "code": t["misconception_code"], "label_ru": ru, "label_kz": kz})
        elif t["target_type"] == "topic":
            obj = session.get(m.Topic, t["target_id"])
            out.append({**t, "code": obj.code if obj else None, "label_ru": obj.title_ru if obj else None,
                        "label_kz": obj.title_kz if obj else None})
        else:
            obj = session.get(m.LearningObjective, t["target_id"])
            out.append({**t, "code": obj.code if obj else None, "label_ru": obj.text_ru if obj else None,
                        "label_kz": obj.text_kz if obj else None})
    return out


def _users(session: Session, ids) -> dict[str, str]:
    ids = [i for i in ids if i]
    if not ids:
        return {}
    return {u.id: u.display_name for u in session.scalars(select(m.User).where(m.User.id.in_(ids)))}


def version_payload(session: Session, v: mm.InterventionVersion, users: dict | None = None) -> dict:
    users = users if users is not None else _users(session, [v.author_id, v.reviewed_by])
    return {
        "id": v.id, "intervention_id": v.intervention_id, "version": v.version, "status": v.status,
        **{f: getattr(v, f) for f in CONTENT_FIELDS if f != "targets"},
        "total_minutes": v.minutes_per_session * v.sessions_per_week * v.duration_weeks,
        "targets": _target_labels(session, v.targets or []),
        "content_sha256": v.content_sha256, "change_note": v.change_note or "",
        "author": users.get(v.author_id), "reviewed_by": users.get(v.reviewed_by),
        "reviewed_at": v.reviewed_at.isoformat() if v.reviewed_at else None, "review_note": v.review_note,
        "created_at": v.created_at.isoformat(), "used_by_pilots": _used_by_pilots(session, v.id),
    }


COMPARABLE_DESIGNS = {"matched_comparison", "cluster_randomized", "stepped_wedge", "interrupted_time_series"}


def evidence_summary(session: Session, iv: mm.Intervention) -> dict:
    rows = list(session.scalars(select(mm.InterventionEvidenceEntry).where(
        mm.InterventionEvidenceEntry.intervention_id == iv.id, mm.InterventionEvidenceEntry.org_id == iv.org_id)
        .order_by(mm.InterventionEvidenceEntry.created_at)))
    accepted = [r for r in rows if r.review_status == "accepted"]
    by_status: dict[str, int] = {}
    for r in accepted:
        by_status[r.outcome_status] = by_status.get(r.outcome_status, 0) + 1
    comparable_pos = sum(1 for r in accepted if r.outcome_status == "positive_signal" and r.design in COMPARABLE_DESIGNS
                         and r.fidelity_class == "high")
    versions = {v.id: v.version for v in versions_of(session, iv)}
    return {
        "accepted_entries": len(accepted),
        "proposed_entries": sum(1 for r in rows if r.review_status == "proposed"),
        "by_status": by_status,
        "repeated_positive_signal": comparable_pos >= 2,
        "comparable_positive_signals": comparable_pos,
        "entries": [{"id": r.id, "pilot_id": r.pilot_id, "conclusion_id": r.conclusion_id, "outcome_id": r.outcome_id,
                     "intervention_version": versions.get(r.intervention_version_id), "outcome_status": r.outcome_status,
                     "causal_level": r.causal_level, "fidelity_class": r.fidelity_class, "design": r.design,
                     "review_status": r.review_status, "summary": r.summary,
                     "reviewed_at": r.reviewed_at.isoformat() if r.reviewed_at else None,
                     "created_at": r.created_at.isoformat()} for r in rows],
        "note_ru": ("Сводка строится только из записей, принятых человеком. Версии интервенции при этом не изменяются; "
                    "один положительный сигнал не доказывает эффективность."),
        "note_kz": ("Жиынтық тек адам қабылдаған жазбалардан құрылады. Интервенция нұсқалары өзгермейді; "
                    "бір оң сигнал тиімділікті дәлелдемейді."),
    }


def payload(session: Session, iv: mm.Intervention) -> dict:
    vs = versions_of(session, iv)
    users = _users(session, [x for v in vs for x in (v.author_id, v.reviewed_by)] + [iv.created_by])
    reviewed = [v for v in vs if v.status == "reviewed"]
    return {
        "id": iv.id, "code": iv.code, "org_id": iv.org_id, "dataset_id": iv.dataset_id, "status": iv.status,
        "archived_reason": iv.archived_reason, "archived_at": iv.archived_at.isoformat() if iv.archived_at else None,
        "latest_version": vs[-1].version, "reviewed_version": reviewed[-1].version if reviewed else None,
        "current": version_payload(session, vs[-1], users),
        "versions": [version_payload(session, v, users) for v in reversed(vs)],
        "evidence_summary": evidence_summary(session, iv),
        "created_at": iv.created_at.isoformat(), "created_by": users.get(iv.created_by), "is_synthetic": iv.is_synthetic,
    }


def list_interventions(session: Session, org_id: str, dataset_id: str | None = None, status: str | None = None,
                       evidence_level: str | None = None, topic_id: str | None = None, objective_id: str | None = None,
                       misconception: str | None = None, grade: int | None = None, language: str | None = None,
                       q: str | None = None) -> list[dict]:
    stmt = select(mm.Intervention).where(mm.Intervention.org_id == org_id)
    if dataset_id:
        get_dataset(session, org_id, dataset_id)
        stmt = stmt.where((mm.Intervention.dataset_id == dataset_id) | (mm.Intervention.dataset_id.is_(None)))
    if status in ("active", "archived"):
        stmt = stmt.where(mm.Intervention.status == status)
    out = []
    for iv in session.scalars(stmt.order_by(mm.Intervention.code)):
        vs = versions_of(session, iv)
        cur = vs[-1]
        reviewed = [v for v in vs if v.status == "reviewed"]
        if evidence_level and cur.evidence_level != evidence_level:
            continue
        tg = cur.targets or []
        if topic_id and not any(t["target_type"] == "topic" and t["target_id"] == topic_id for t in tg) and not any(
                t["target_type"] == "objective" and _objective_topic(session, t["target_id"]) == topic_id for t in tg):
            continue
        if objective_id and not any(t["target_type"] == "objective" and t["target_id"] == objective_id for t in tg):
            continue
        if misconception and not any(t["misconception_code"] == misconception for t in tg):
            continue
        if grade and cur.grades and grade not in cur.grades:
            continue
        if language and cur.languages and language not in cur.languages:
            continue
        if q and q.lower() not in f"{iv.code} {cur.title_ru} {cur.title_kz} {cur.description_ru}".lower():
            continue
        ev = evidence_summary(session, iv)
        out.append({
            "id": iv.id, "code": iv.code, "status": iv.status, "dataset_id": iv.dataset_id, "latest_version": cur.version,
            "reviewed_version": reviewed[-1].version if reviewed else None, "current_status": cur.status,
            "title_ru": cur.title_ru, "title_kz": cur.title_kz, "evidence_level": cur.evidence_level, "grades": cur.grades,
            "languages": cur.languages, "targets": _target_labels(session, tg),
            "total_minutes": cur.minutes_per_session * cur.sessions_per_week * cur.duration_weeks,
            "n_pilots": int(session.scalar(select(func.count()).select_from(mm.Pilot).where(mm.Pilot.intervention_id == iv.id)) or 0),
            "accepted_evidence": ev["accepted_entries"],
        })
    return out


def _objective_topic(session: Session, objective_id: str | None) -> str | None:
    o = session.get(m.LearningObjective, objective_id or "")
    return o.topic_id if o else None


# ---------------------------------------------------------------------------
# Suggestions with an explainable score
# ---------------------------------------------------------------------------

SCORING_RULE = {"misconception_match": 3.0, "objective_match": 2.0, "topic_match": 1.0, "grade_applicable": 0.5,
                "language_applicable": 0.5, "evidence_experimental": 1.0, "evidence_observational": 0.5,
                "accepted_positive_signal_each": 0.5, "accepted_positive_signal_cap": 1.0}


def suggest(session: Session, org_id: str, dataset_id: str | None, topic_id: str | None, objective_id: str | None,
            misconception: str | None, grade: int | None, language: str | None) -> dict:
    """Rank *reviewed, active* interventions by a transparent additive match score. Every point is explained;
    no learned model and no automatic change of recommendations without human-accepted evidence."""
    if not (topic_id or objective_id or misconception):
        raise ApiError("validation_error", "Укажите тему, цель или типичную ошибку", 422)
    if dataset_id:
        get_dataset(session, org_id, dataset_id)
    obj_topic = _objective_topic(session, objective_id) if objective_id else None
    topic_id = topic_id or obj_topic
    suggestions, excluded = [], []
    stmt = select(mm.Intervention).where(mm.Intervention.org_id == org_id)
    if dataset_id:
        stmt = stmt.where((mm.Intervention.dataset_id == dataset_id) | (mm.Intervention.dataset_id.is_(None)))
    for iv in session.scalars(stmt.order_by(mm.Intervention.code)):
        if iv.status == "archived":
            excluded.append({"intervention_id": iv.id, "code": iv.code, "reason": "archived"})
            continue
        vs = versions_of(session, iv)
        rev = [v for v in vs if v.status == "reviewed"]
        if not rev:
            excluded.append({"intervention_id": iv.id, "code": iv.code, "reason": "no_reviewed_version"})
            continue
        v = rev[-1]
        comps = []
        tg = v.targets or []
        if misconception and any(t["misconception_code"] == misconception for t in tg):
            comps.append(("misconception_match", SCORING_RULE["misconception_match"], misconception))
        if objective_id and any(t["target_type"] == "objective" and t["target_id"] == objective_id for t in tg):
            comps.append(("objective_match", SCORING_RULE["objective_match"], objective_id))
        if topic_id and (any(t["target_type"] == "topic" and t["target_id"] == topic_id for t in tg)
                         or any(t["target_type"] == "objective" and _objective_topic(session, t["target_id"]) == topic_id for t in tg)):
            comps.append(("topic_match", SCORING_RULE["topic_match"], topic_id))
        if not comps:
            excluded.append({"intervention_id": iv.id, "code": iv.code, "reason": "no_target_match"})
            continue
        if grade is not None:
            if v.grades and grade not in v.grades:
                excluded.append({"intervention_id": iv.id, "code": iv.code, "reason": "grade_not_applicable"})
                continue
            comps.append(("grade_applicable", SCORING_RULE["grade_applicable"], str(grade)))
        if language:
            if v.languages and language not in v.languages:
                excluded.append({"intervention_id": iv.id, "code": iv.code, "reason": "language_not_applicable"})
                continue
            comps.append(("language_applicable", SCORING_RULE["language_applicable"], language))
        if v.evidence_level in ("experimental", "observational"):
            comps.append((f"evidence_{v.evidence_level}", SCORING_RULE[f"evidence_{v.evidence_level}"], v.evidence_level))
        ev = evidence_summary(session, iv)
        pos = ev["by_status"].get("positive_signal", 0)
        if pos:
            comps.append(("accepted_positive_signals", min(SCORING_RULE["accepted_positive_signal_cap"],
                                                           pos * SCORING_RULE["accepted_positive_signal_each"]), str(pos)))
        suggestions.append({
            "intervention_id": iv.id, "code": iv.code, "version": v.version, "title_ru": v.title_ru, "title_kz": v.title_kz,
            "evidence_level": v.evidence_level, "score": round(sum(c[1] for c in comps), 3),
            "components": [{"code": c, "points": pts, "detail": det} for c, pts, det in comps],
            "contraindications_ru": v.contraindications_ru, "limitations_ru": v.limitations_ru,
        })
    suggestions.sort(key=lambda s: (-s["score"], s["code"]))
    return {
        "ranking_kind": "explainable_match_score",
        "scoring_rule": SCORING_RULE,
        "query": {"dataset_id": dataset_id, "topic_id": topic_id, "objective_id": objective_id, "misconception": misconception,
                  "grade": grade, "language": language},
        "suggestions": suggestions,
        "excluded": excluded,
        "limitations": [
            {"code": "match_score_not_effect", "severity": "info", "params": {},
             "message_ru": "Балл отражает соответствие проблеме и уровень доказательств, а не ожидаемый прирост результатов.",
             "message_kz": "Балл мәселеге сәйкестікті және дәлел деңгейін көрсетеді, күтілетін өсімді емес."},
            render("synthetic_data") if dataset_id and get_dataset(session, org_id, dataset_id).is_synthetic else
            {"code": "human_review", "severity": "info", "params": {},
             "message_ru": "Выбор интервенции остаётся за методистом.", "message_kz": "Интервенцияны таңдау әдіскерде қалады."},
        ],
    }
