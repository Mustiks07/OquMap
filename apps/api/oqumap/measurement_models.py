"""Tables of the measurement & learning loop: intervention library (versioned), pilot protocol, implementation
fidelity, follow-up outcomes, conclusions and intervention evidence entries.

Kept in a separate module (imported by ``models.py``) to minimise merge conflicts. Every row is tenant scoped by
``org_id``; queries always filter by it. History is append-only where the brief requires immutability:
reviewed intervention versions, pilot snapshots, fidelity logs, outcomes and evidence entries are never updated
in place (corrections/supersessions create new rows).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, IdMixin, TimestampMixin, TZDateTime

EVIDENCE_LEVELS = ("practice_based", "observational", "experimental")
VERSION_STATUSES = ("draft", "reviewed", "archived")
PILOT_STATUSES = ("draft", "ready", "active", "completed", "stopped")
DESIGNS = ("single_group", "matched_comparison", "cluster_randomized", "interrupted_time_series", "stepped_wedge")
OUTCOME_STATUSES = ("positive_signal", "mixed", "not_confirmed", "needs_more_data", "invalid_due_to_fidelity",
                    "invalid_due_to_comparability")


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class Intervention(IdMixin, TimestampMixin, Base):
    """Stable identity of an intervention. Content lives in immutable ``InterventionVersion`` rows."""

    __tablename__ = "interventions"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | archived
    archived_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    archived_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_interventions_org_code"),
                      CheckConstraint(_in("status", ("active", "archived")), name="ck_interventions_status"))


class InterventionVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "intervention_versions"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    intervention_id: Mapped[str] = mapped_column(ForeignKey("interventions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="draft")
    title_ru: Mapped[str] = mapped_column(String(300))
    title_kz: Mapped[str] = mapped_column(String(300), default="")
    description_ru: Mapped[str] = mapped_column(Text, default="")
    description_kz: Mapped[str] = mapped_column(Text, default="")
    grades: Mapped[list] = mapped_column(JSON, default=list)
    languages: Mapped[list] = mapped_column(JSON, default=list)
    minutes_per_session: Mapped[int] = mapped_column(Integer)
    sessions_per_week: Mapped[int] = mapped_column(Integer)
    duration_weeks: Mapped[int] = mapped_column(Integer)
    cadence_ru: Mapped[str] = mapped_column(String(300), default="")
    instructions_ru: Mapped[str] = mapped_column(Text, default="")
    instructions_kz: Mapped[str] = mapped_column(Text, default="")
    resources: Mapped[list] = mapped_column(JSON, default=list)
    evidence_level: Mapped[str] = mapped_column(String(30))
    evidence_links: Mapped[list] = mapped_column(JSON, default=list)
    contraindications_ru: Mapped[str] = mapped_column(Text, default="")
    limitations_ru: Mapped[str] = mapped_column(Text, default="")
    limitations_kz: Mapped[str] = mapped_column(Text, default="")
    targets: Mapped[list] = mapped_column(JSON, default=list)  # [{target_type, target_id, misconception_code}]
    content_sha256: Mapped[str] = mapped_column(String(64))
    change_note: Mapped[str] = mapped_column(Text, default="")
    author_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("intervention_id", "version", name="uq_intervention_versions_version"),
                      UniqueConstraint("id", "intervention_id", name="uq_intervention_versions_id_intervention"),
                      CheckConstraint("minutes_per_session > 0 AND sessions_per_week > 0 AND duration_weeks > 0",
                                      name="ck_intervention_versions_dosage"),
                      CheckConstraint(_in("status", VERSION_STATUSES), name="ck_intervention_versions_status"),
                      CheckConstraint(_in("evidence_level", EVIDENCE_LEVELS), name="ck_intervention_versions_evidence"))


class InterventionTarget(IdMixin, Base):
    """Denormalised index of version targets (topic / objective / misconception) for filtering and coverage."""

    __tablename__ = "intervention_targets"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    intervention_version_id: Mapped[str] = mapped_column(ForeignKey("intervention_versions.id"), index=True)
    target_type: Mapped[str] = mapped_column(String(20))
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True, index=True)
    objective_id: Mapped[str | None] = mapped_column(ForeignKey("objectives.id"), nullable=True, index=True)
    misconception_code: Mapped[str | None] = mapped_column(String(60), nullable=True, index=True)
    __table_args__ = (CheckConstraint(
        "(target_type = 'topic' AND topic_id IS NOT NULL AND objective_id IS NULL AND misconception_code IS NULL) OR "
        "(target_type = 'objective' AND objective_id IS NOT NULL AND topic_id IS NULL AND misconception_code IS NULL) OR "
        "(target_type = 'misconception' AND misconception_code IS NOT NULL AND topic_id IS NULL AND objective_id IS NULL)",
        name="ck_intervention_targets_one_field"),
        CheckConstraint(_in("target_type", ("topic", "objective", "misconception")),
                                      name="ck_intervention_targets_type"),)


class Pilot(IdMixin, TimestampMixin, Base):
    __tablename__ = "pilots"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    design: Mapped[str] = mapped_column(String(40))
    assignment_unit: Mapped[str] = mapped_column(String(20), default="cohort")
    causal_ceiling: Mapped[str] = mapped_column(String(40))
    intervention_id: Mapped[str] = mapped_column(ForeignKey("interventions.id"), index=True)
    intervention_version_id: Mapped[str] = mapped_column(ForeignKey("intervention_versions.id"), index=True)
    intervention_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    snapshot_sha256: Mapped[str] = mapped_column(String(64))
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("decisions.id"), nullable=True, index=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"))
    objective_id: Mapped[str | None] = mapped_column(ForeignKey("objectives.id"), nullable=True)
    primary_outcome_ru: Mapped[str] = mapped_column(Text, default="")
    baseline_assessment_id: Mapped[str | None] = mapped_column(ForeignKey("assessments.id"), nullable=True)
    outcome_assessment_id: Mapped[str | None] = mapped_column(ForeignKey("assessments.id"), nullable=True)
    pre_period_assessment_ids: Mapped[list] = mapped_column(JSON, default=list)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    follow_up_due: Mapped[date | None] = mapped_column(Date, nullable=True)
    owner: Mapped[str] = mapped_column(String(200), default="")
    minutes_per_session: Mapped[int] = mapped_column(Integer)
    sessions_per_week: Mapped[int] = mapped_column(Integer)
    duration_weeks: Mapped[int] = mapped_column(Integer)
    inclusion_criteria: Mapped[str] = mapped_column(Text, default="")
    exclusion_criteria: Mapped[str] = mapped_column(Text, default="")
    analysis_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    randomization: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {seed, method, by, at, clusters}
    stop_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    activated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("org_id", "code", name="uq_pilots_org_code"),
                      ForeignKeyConstraint(["intervention_version_id", "intervention_id"],
                                           ["intervention_versions.id", "intervention_versions.intervention_id"],
                                           name="fk_pilots_version_of_intervention"),
                      CheckConstraint("minutes_per_session > 0 AND sessions_per_week > 0 AND duration_weeks > 0",
                                      name="ck_pilots_dosage"),
                      CheckConstraint(_in("status", PILOT_STATUSES), name="ck_pilots_status"),
                      CheckConstraint(_in("design", DESIGNS), name="ck_pilots_design"),
                      CheckConstraint(_in("assignment_unit", ("cohort", "school")), name="ck_pilots_unit"))


class PilotCohort(IdMixin, Base):
    __tablename__ = "pilot_cohorts"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    pilot_id: Mapped[str] = mapped_column(ForeignKey("pilots.id"), index=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("cohorts.id"), index=True)
    arm: Mapped[str] = mapped_column(String(20))
    wave: Mapped[int | None] = mapped_column(Integer, nullable=True)
    __table_args__ = (UniqueConstraint("pilot_id", "cohort_id", name="uq_pilot_cohorts_pilot_cohort"),
                      CheckConstraint(_in("arm", ("intervention", "comparison")), name="ck_pilot_cohorts_arm"))


class PilotEvent(IdMixin, TimestampMixin, Base):
    """Status transitions of a pilot (append-only)."""

    __tablename__ = "pilot_events"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    pilot_id: Mapped[str] = mapped_column(ForeignKey("pilots.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20))
    note: Mapped[str] = mapped_column(Text, default="")
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class FidelityLog(IdMixin, TimestampMixin, Base):
    """One implementation session record. Append-only: a correction is a new row with ``corrects_log_id``."""

    __tablename__ = "fidelity_logs"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    pilot_id: Mapped[str] = mapped_column(ForeignKey("pilots.id"), index=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("cohorts.id"), index=True)
    session_date: Mapped[date] = mapped_column(Date)
    planned_minutes: Mapped[int] = mapped_column(Integer)
    delivered_minutes: Mapped[int] = mapped_column(Integer)
    activities_planned: Mapped[int] = mapped_column(Integer, default=0)
    activities_completed: Mapped[int] = mapped_column(Integer, default=0)
    completed_tasks: Mapped[list] = mapped_column(JSON, default=list)
    learners_present: Mapped[int | None] = mapped_column(Integer, nullable=True)
    learners_assigned: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adherence: Mapped[list] = mapped_column(JSON, default=list)
    adaptation_note: Mapped[str] = mapped_column(Text, default="")
    disruption: Mapped[str] = mapped_column(String(30), default="none")
    disruption_note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(30), default="teacher_log")
    recorder_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    corrects_log_id: Mapped[str | None] = mapped_column(ForeignKey("fidelity_logs.id"), nullable=True)
    __table_args__ = (Index("ix_fidelity_logs_pilot_cohort_date", "pilot_id", "cohort_id", "session_date"),
                      UniqueConstraint("corrects_log_id", name="uq_fidelity_logs_single_correction"),
                      CheckConstraint("activities_planned >= 0 AND activities_completed >= 0 AND "
                                      "(learners_present IS NULL OR learners_present >= 0) AND "
                                      "(learners_assigned IS NULL OR learners_assigned >= 0)", name="ck_fidelity_logs_counts"),
                      CheckConstraint("delivered_minutes >= 0 AND planned_minutes >= 0", name="ck_fidelity_logs_minutes"),
                      CheckConstraint(_in("disruption", ("none", "cancelled", "shortened", "teacher_absent", "holiday", "other")),
                                      name="ck_fidelity_logs_disruption"))


class PilotOutcome(IdMixin, TimestampMixin, Base):
    """Immutable follow-up analysis of a pilot (same inputs → same row via ``input_fingerprint``)."""

    __tablename__ = "pilot_outcomes"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    pilot_id: Mapped[str] = mapped_column(ForeignKey("pilots.id"), index=True)
    dataset_version: Mapped[int] = mapped_column(Integer)
    outcome_assessment_id: Mapped[str | None] = mapped_column(ForeignKey("assessments.id"), nullable=True)
    method_version: Mapped[str] = mapped_column(String(40))
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40))
    causal_level: Mapped[str] = mapped_column(String(40))
    fidelity_class: Mapped[str] = mapped_column(String(20))
    interim: Mapped[bool] = mapped_column(Boolean, default=False)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (UniqueConstraint("org_id", "input_fingerprint", name="uq_pilot_outcomes_fingerprint"),
                      UniqueConstraint("id", "pilot_id", "org_id", name="uq_pilot_outcomes_id_pilot_org"),
                      CheckConstraint(_in("status", OUTCOME_STATUSES), name="ck_pilot_outcomes_status"))


class PilotConclusion(IdMixin, TimestampMixin, Base):
    """Human conclusion after a follow-up: what was learned and what happens next (continue/modify/stop)."""

    __tablename__ = "pilot_conclusions"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    pilot_id: Mapped[str] = mapped_column(ForeignKey("pilots.id"), index=True)
    outcome_id: Mapped[str] = mapped_column(ForeignKey("pilot_outcomes.id"), index=True)
    decision: Mapped[str] = mapped_column(String(30))
    summary_ru: Mapped[str] = mapped_column(Text)
    summary_kz: Mapped[str] = mapped_column(Text, default="")
    lessons_ru: Mapped[str] = mapped_column(Text, default="")
    open_questions: Mapped[list] = mapped_column(JSON, default=list)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    next_decision_id: Mapped[str | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decision_basis: Mapped[str] = mapped_column(String(30), default="insufficient_evidence", server_default="insufficient_evidence")
    stop_reason_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    acknowledged_limitation_codes: Mapped[list] = mapped_column(JSON, default=list, server_default=text("'[]'"))
    __table_args__ = (ForeignKeyConstraint(["outcome_id", "pilot_id", "org_id"],
                                           ["pilot_outcomes.id", "pilot_outcomes.pilot_id", "pilot_outcomes.org_id"],
                                           name="fk_pilot_conclusions_outcome_same_pilot"),
                      CheckConstraint(_in("decision", ("continue", "modify", "stop", "extend_data_collection")),
                                      name="ck_pilot_conclusions_decision"),
                      CheckConstraint(_in("decision_basis", ("evidence_supports", "operational", "insufficient_evidence",
                                                             "external_factors")), name="ck_pilot_conclusions_basis"),
                      CheckConstraint("decision <> 'stop' OR stop_reason_code IS NOT NULL", name="ck_pilot_conclusions_stop_reason"))


class InterventionEvidenceEntry(IdMixin, TimestampMixin, Base):
    """Evidence accumulated for an intervention from pilots. Proposed by a conclusion, accepted/rejected by a
    human approver. Never edits the intervention version itself; summaries are computed from accepted rows."""

    __tablename__ = "intervention_evidence"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    intervention_id: Mapped[str] = mapped_column(ForeignKey("interventions.id"), index=True)
    intervention_version_id: Mapped[str] = mapped_column(ForeignKey("intervention_versions.id"))
    pilot_id: Mapped[str] = mapped_column(ForeignKey("pilots.id"), index=True)
    conclusion_id: Mapped[str] = mapped_column(ForeignKey("pilot_conclusions.id"), unique=True)
    outcome_id: Mapped[str] = mapped_column(ForeignKey("pilot_outcomes.id"))
    outcome_status: Mapped[str] = mapped_column(String(40))
    causal_level: Mapped[str] = mapped_column(String(40))
    fidelity_class: Mapped[str] = mapped_column(String(20))
    design: Mapped[str] = mapped_column(String(40))
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed|accepted|rejected
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (ForeignKeyConstraint(["intervention_version_id", "intervention_id"],
                                           ["intervention_versions.id", "intervention_versions.intervention_id"],
                                           name="fk_intervention_evidence_version_of_intervention"),
                      CheckConstraint(_in("review_status", ("proposed", "accepted", "rejected")),
                                      name="ck_intervention_evidence_review"),)


class AssessmentCohort(IdMixin, TimestampMixin, Base):
    """Explicit assignment of an assessment to a class. When an assessment has such rows, Quality Lab counts
    ``assigned`` from them (a class with no sitting records at all is visible as ``no_sitting_record``); without
    them the scope is only inferred from sittings and reported as such."""

    __tablename__ = "assessment_cohorts"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"), index=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("cohorts.id"), index=True)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # manual | seed | import
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (UniqueConstraint("assessment_id", "cohort_id", name="uq_assessment_cohorts_assessment_cohort"),
                      CheckConstraint(_in("source", ("manual", "seed", "import")), name="ck_assessment_cohorts_source"))


# Decision versions created by the learning loop must not collide under concurrency (shared table, index only).
from .models import Decision  # noqa: E402

Index("uq_decisions_group_version", Decision.decision_group_id, Decision.version, unique=True)
