"""Relational schema. Every tenant-owned row carries ``org_id``; queries are always scoped by it.

Shared curriculum content (program versions, topics, objectives, item bank, forms, scales) may be
global (``org_id`` NULL) and readable by every organisation.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, IdMixin, TimestampMixin, TZDateTime, utcnow

# ---------------------------------------------------------------------------
# Tenancy and access
# ---------------------------------------------------------------------------


class Organization(IdMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(200))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # Disposable public-demo tenant (cloned from the demo template, deleted after expires_at).
    is_ephemeral: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True, index=True)
    storage_quota_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    username: Mapped[str] = mapped_column(String(120), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    # roles: methodist, approver, teacher, viewer, admin
    roles: Mapped[list] = mapped_column(JSON, default=list)
    password_hash: Mapped[str | None] = mapped_column(String(300), nullable=True)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class ApiSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "api_sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime(), index=True)


class RateLimitCounter(Base):
    """Fixed-window counters shared by all API/worker processes (stored in the database)."""

    __tablename__ = "rate_limits"
    key: Mapped[str] = mapped_column(String(250), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime] = mapped_column(TZDateTime(), index=True)


class AuditLog(IdMixin, TimestampMixin, Base):
    __tablename__ = "audit_log"
    org_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict)


# ---------------------------------------------------------------------------
# Curriculum (shared or org-specific)
# ---------------------------------------------------------------------------


class ProgramVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "program_versions"
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    subject: Mapped[str] = mapped_column(String(80))
    grade: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(8))
    version: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(Text)
    # True when objective codes are demonstration codes (not the official programme).
    is_demo_codes: Mapped[bool] = mapped_column(Boolean, default=True)


class Topic(IdMixin, Base):
    __tablename__ = "topics"
    program_version_id: Mapped[str] = mapped_column(ForeignKey("program_versions.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    order_index: Mapped[int] = mapped_column(Integer)
    title_ru: Mapped[str] = mapped_column(String(300))
    title_kz: Mapped[str] = mapped_column(String(300))
    kz_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("program_version_id", "code"),)


class LearningObjective(IdMixin, Base):
    __tablename__ = "objectives"
    program_version_id: Mapped[str] = mapped_column(ForeignKey("program_versions.id"), index=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    text_ru: Mapped[str] = mapped_column(Text)
    text_kz: Mapped[str] = mapped_column(Text)
    kz_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("program_version_id", "code"),)


class ObjectiveRelation(IdMixin, Base):
    __tablename__ = "objective_relations"
    source_objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"))
    target_objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"))
    # prerequisite: source must be mastered before target
    relation_type: Mapped[str] = mapped_column(String(40), default="prerequisite")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)


class Scale(IdMixin, Base):
    __tablename__ = "scales"
    # NULL org_id = shared definition used by the demo programme; imported projects get their own scales.
    org_id: Mapped[str | None] = mapped_column(ForeignKey("organizations.id"), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    # identical_form | common_anchor_equated | none
    linking_method: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text, default="")
    __table_args__ = (UniqueConstraint("org_id", "code"),)


class Item(IdMixin, Base):
    __tablename__ = "items"
    program_version_id: Mapped[str] = mapped_column(ForeignKey("program_versions.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer, default=1)
    item_type: Mapped[str] = mapped_column(String(30))  # single_choice | numeric
    stem_ru: Mapped[str] = mapped_column(Text)
    stem_kz: Mapped[str] = mapped_column(Text)
    # [{"key":"A","text":"5/6","correct":true,"misconception":null}, ...]
    options: Mapped[list] = mapped_column(JSON, default=list)
    answer_key: Mapped[str] = mapped_column(String(80))
    max_points: Mapped[float] = mapped_column(Float, default=1.0)
    kz_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (UniqueConstraint("program_version_id", "code", "version"),)


class ItemObjective(IdMixin, Base):
    """Link item -> objective with a weight. Weights of one item sum to 1 so that an item linked to
    several objectives is never double counted (see METHODOLOGY.md §2.2)."""

    __tablename__ = "item_objectives"
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), index=True)
    objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")  # proposed|confirmed|rejected
    origin: Mapped[str] = mapped_column(String(20), default="human")  # human|ai|template
    generation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    org_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)


class AssessmentForm(IdMixin, Base):
    __tablename__ = "assessment_forms"
    program_version_id: Mapped[str] = mapped_column(ForeignKey("program_versions.id"), index=True)
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    scale_id: Mapped[str] = mapped_column(ForeignKey("scales.id"))
    stage_hint: Mapped[str] = mapped_column(String(20))  # pre|post|followup
    __table_args__ = (UniqueConstraint("program_version_id", "code"),)


class FormItem(IdMixin, Base):
    __tablename__ = "form_items"
    form_id: Mapped[str] = mapped_column(ForeignKey("assessment_forms.id"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"))
    position: Mapped[int] = mapped_column(Integer)
    is_anchor: Mapped[bool] = mapped_column(Boolean, default=False)


# ---------------------------------------------------------------------------
# Datasets, organisation structure, measurements
# ---------------------------------------------------------------------------


class Dataset(IdMixin, TimestampMixin, Base):
    __tablename__ = "datasets"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    program_version_id: Mapped[str | None] = mapped_column(ForeignKey("program_versions.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(80))
    name_ru: Mapped[str] = mapped_column(String(300))
    name_kz: Mapped[str] = mapped_column(String(300))
    description_ru: Mapped[str] = mapped_column(Text, default="")
    description_kz: Mapped[str] = mapped_column(Text, default="")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    scenario: Mapped[str | None] = mapped_column(String(60), nullable=True)
    # data level: grades_only | item_responses | pre_post_with_exposure
    data_level: Mapped[str] = mapped_column(String(40), default="item_responses")
    version: Mapped[int] = mapped_column(Integer, default=1)
    version_updated_at: Mapped[datetime] = mapped_column(TZDateTime(), default=utcnow)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (UniqueConstraint("org_id", "code"),)


class DatasetVersionEvent(IdMixin, TimestampMixin, Base):
    __tablename__ = "dataset_versions"
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    import_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class School(IdMixin, Base):
    __tablename__ = "schools"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    code: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint("dataset_id", "code"),)


class Teacher(IdMixin, Base):
    __tablename__ = "teachers"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    code: Mapped[str] = mapped_column(String(60))  # pseudonymous
    __table_args__ = (UniqueConstraint("dataset_id", "code"),)


class Cohort(IdMixin, Base):
    """A class (group of learners) in a school year."""

    __tablename__ = "cohorts"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    school_id: Mapped[str] = mapped_column(ForeignKey("schools.id"), index=True)
    teacher_id: Mapped[str | None] = mapped_column(ForeignKey("teachers.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(60))
    grade: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(8))
    academic_year: Mapped[str] = mapped_column(String(20))
    __table_args__ = (UniqueConstraint("dataset_id", "code"),)


class Learner(IdMixin, Base):
    __tablename__ = "learners"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("cohorts.id"), index=True)
    code: Mapped[str] = mapped_column(String(60))  # pseudonymous, never a name
    __table_args__ = (UniqueConstraint("dataset_id", "code"),)


class TextbookEdition(IdMixin, TimestampMixin, Base):
    __tablename__ = "editions"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    edition_label: Mapped[str] = mapped_column(String(100))
    year: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(8))
    grade: Mapped[int] = mapped_column(Integer)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    usage_permission: Mapped[str] = mapped_column(String(200), default="")
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (UniqueConstraint("org_id", "code"),)


class MaterialExposure(IdMixin, Base):
    """Which edition a class used for a topic in a period. Planned and actual hours are separate."""

    __tablename__ = "material_exposures"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    cohort_id: Mapped[str] = mapped_column(ForeignKey("cohorts.id"), index=True)
    edition_id: Mapped[str] = mapped_column(ForeignKey("editions.id"), index=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    planned_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    actual_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    usage_level: Mapped[str] = mapped_column(String(20), default="primary")  # primary|supplementary


class Assessment(IdMixin, Base):
    """An administration of a form within a dataset."""

    __tablename__ = "assessments"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    form_id: Mapped[str] = mapped_column(ForeignKey("assessment_forms.id"))
    code: Mapped[str] = mapped_column(String(60))
    stage: Mapped[str] = mapped_column(String(20))  # pre|post|followup
    administered_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    __table_args__ = (UniqueConstraint("dataset_id", "code"),)


class Sitting(IdMixin, Base):
    """Whether a learner was present for an assessment. Absent learners have no responses and are
    reported as exclusions, never as zero scores."""

    __tablename__ = "sittings"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"), index=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    status: Mapped[str] = mapped_column(String(20))  # present|absent
    import_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (UniqueConstraint("assessment_id", "learner_id"),)


class Response(IdMixin, Base):
    """One attempt at one item.

    status: answered (score is the measured score, may be 0 = wrong) | omitted (item shown but skipped,
    score NULL). Items not on the form produce no rows (= not measured)."""

    __tablename__ = "responses"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    assessment_id: Mapped[str] = mapped_column(ForeignKey("assessments.id"), index=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    response_value: Mapped[str | None] = mapped_column(String(200), nullable=True)
    import_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    __table_args__ = (
        UniqueConstraint("assessment_id", "learner_id", "item_id", "attempt"),
        Index("ix_responses_dataset_assessment", "dataset_id", "assessment_id"),
    )


class GradeRecord(IdMixin, Base):
    """Final grades (overview only; cannot be turned into skill-level diagnostics)."""

    __tablename__ = "grade_records"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    learner_id: Mapped[str] = mapped_column(ForeignKey("learners.id"), index=True)
    period: Mapped[str] = mapped_column(String(40))
    grade_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    grade_scale_max: Mapped[float] = mapped_column(Float, default=5)
    import_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class ImportBatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "import_batches"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str | None] = mapped_column(ForeignKey("datasets.id"), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    kind: Mapped[str] = mapped_column(String(30))  # responses|grades
    filename: Mapped[str] = mapped_column(String(300))
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sheet: Mapped[str | None] = mapped_column(String(120), nullable=True)
    column_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    transform_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))  # validated|committing|committed|failed
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    rows_total: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    committed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    resulting_dataset_version: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Documents, sources, mappings, AI generations
# ---------------------------------------------------------------------------


class Document(IdMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    edition_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    filename: Mapped[str] = mapped_column(String(300))
    media_type: Mapped[str] = mapped_column(String(100))
    sha256: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(500))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    # Documents of the same edition form a lineage; version increments on every new upload.
    lineage_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20))  # queued|processing|ready|failed
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ocr_status: Mapped[str] = mapped_column(String(30), default="not_needed")
    extraction_report: Mapped[dict] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (UniqueConstraint("org_id", "sha256"),)


class ContentFragment(IdMixin, Base):
    """A citable piece of a source document. PDF fragments carry the physical page (1-based) and the
    printed page label when the document defines one. DOCX fragments carry a stable anchor and no page."""

    __tablename__ = "fragments"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), index=True)
    document_version: Mapped[int] = mapped_column(Integer)
    anchor: Mapped[str] = mapped_column(String(80))
    page_physical: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_printed: Mapped[str | None] = mapped_column(String(20), nullable=True)
    heading: Mapped[str | None] = mapped_column(String(300), nullable=True)
    text: Mapped[str] = mapped_column(Text)
    text_sha256: Mapped[str] = mapped_column(String(64))
    order_index: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("document_id", "document_version", "anchor"),)


class FragmentObjective(IdMixin, TimestampMixin, Base):
    __tablename__ = "fragment_objectives"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    fragment_id: Mapped[str] = mapped_column(ForeignKey("fragments.id"), index=True)
    objective_id: Mapped[str] = mapped_column(ForeignKey("objectives.id"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="explains")  # explains|practices|example
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    origin: Mapped[str] = mapped_column(String(20), default="ai")
    rationale: Mapped[str] = mapped_column(Text, default="")
    generation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)


class AIGeneration(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_generations"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    task: Mapped[str] = mapped_column(String(60))
    mode: Mapped[str] = mapped_column(String(20))  # live_model|recorded_demo|template
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_template_version: Mapped[str] = mapped_column(String(40))
    input_sha256: Mapped[str] = mapped_column(String(64))
    context: Mapped[dict] = mapped_column(JSON, default=dict)
    output: Mapped[dict] = mapped_column(JSON, default=dict)
    citations: Mapped[list] = mapped_column(JSON, default=list)
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    review_status: Mapped[str] = mapped_column(String(20), default="unreviewed")
    fallback_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


# ---------------------------------------------------------------------------
# Analyses, plans, decisions, follow-up
# ---------------------------------------------------------------------------


class AnalysisRun(IdMixin, TimestampMixin, Base):
    """Immutable snapshot of an analysis: inputs, dataset version, method version and full result."""

    __tablename__ = "analysis_runs"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    dataset_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))  # overview|topic_evidence|comparison|plan|follow_up
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    method_version: Mapped[str] = mapped_column(String(40))
    code_version: Mapped[str] = mapped_column(String(40))
    input_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class TeachingPlan(IdMixin, TimestampMixin, Base):
    __tablename__ = "teaching_plans"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    plan_group_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    scope: Mapped[str] = mapped_column(String(200))  # e.g. "6 класс, все классы набора"
    horizon: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="current")  # current|proposed|approved|superseded
    source_analysis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class PlanTopicHours(IdMixin, Base):
    __tablename__ = "plan_topic_hours"
    plan_id: Mapped[str] = mapped_column(ForeignKey("teaching_plans.id"), index=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"))
    planned_hours: Mapped[int] = mapped_column(Integer)
    actual_hours: Mapped[float | None] = mapped_column(Float, nullable=True)
    elapsed_hours: Mapped[int] = mapped_column(Integer, default=0)
    min_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Decision(IdMixin, TimestampMixin, Base):
    __tablename__ = "decisions"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    decision_group_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    dataset_version: Mapped[int] = mapped_column(Integer)
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    target_group: Mapped[str] = mapped_column(String(300))
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), nullable=True)
    problem: Mapped[str] = mapped_column(Text)
    hypothesis: Mapped[str] = mapped_column(Text)
    action: Mapped[str] = mapped_column(Text)
    responsible: Mapped[str] = mapped_column(String(200))
    follow_up_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    follow_up_criterion: Mapped[str] = mapped_column(Text, default="")
    analysis_ids: Mapped[list] = mapped_column(JSON, default=list)
    plan_analysis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    snapshot: Mapped[dict] = mapped_column(JSON, default=dict)  # metrics, sources, limits, hours change
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|approved|superseded
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_status: Mapped[str | None] = mapped_column(String(30), nullable=True)


class FollowUp(IdMixin, TimestampMixin, Base):
    __tablename__ = "follow_ups"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    decision_id: Mapped[str] = mapped_column(ForeignKey("decisions.id"), index=True)
    analysis_id: Mapped[str] = mapped_column(ForeignKey("analysis_runs.id"))
    status: Mapped[str] = mapped_column(String(30))  # needs_more_data|positive_signal|not_confirmed|needs_revision
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Job(IdMixin, TimestampMixin, Base):
    __tablename__ = "jobs"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), default="queued")
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    started_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


__all__ = [name for name in dir() if name[0].isupper()]

# Measurement & learning-loop tables live in a separate module (registered on the same metadata).
from . import measurement_models as _measurement_models  # noqa: E402,F401

_ = relationship  # relationships are intentionally explicit queries; keeps tenant scoping visible


# ---------------------------------------------------------------------------
# Diagnostic quizzes (formative only: never part of a final grade)
# ---------------------------------------------------------------------------


class Quiz(IdMixin, TimestampMixin, Base):
    __tablename__ = "quizzes"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    topic_id: Mapped[str] = mapped_column(ForeignKey("topics.id"))
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft|edited|approved|rejected
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    use: Mapped[str] = mapped_column(String(30), default="diagnostic_only")
    source_analysis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    generation_mode: Mapped[str] = mapped_column(String(20), default="template")
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TZDateTime(), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class QuizVersion(IdMixin, TimestampMixin, Base):
    __tablename__ = "quiz_versions"
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quizzes.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    items: Mapped[list] = mapped_column(JSON, default=list)
    checks: Mapped[dict] = mapped_column(JSON, default=dict)
    author_kind: Mapped[str] = mapped_column(String(20))  # generator|teacher
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (UniqueConstraint("quiz_id", "version", name="uq_quiz_versions_quiz_version"),)


class QuizResponseSet(IdMixin, TimestampMixin, Base):
    __tablename__ = "quiz_response_sets"
    org_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    quiz_id: Mapped[str] = mapped_column(ForeignKey("quizzes.id"), index=True)
    quiz_version: Mapped[int] = mapped_column(Integer)
    decision_id: Mapped[str | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)
    n_learners: Mapped[int] = mapped_column(Integer, default=0)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    file_sha256: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
