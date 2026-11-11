"""Response/request contracts for the measurement & learning-loop modules (assessment quality, interventions,
pilots, fidelity, follow-up, learning loop, portfolio). Exported to OpenAPI → frontend types.

Shares are 0..1; missing values are ``null`` with a separate reason. Models allow extra fields so that richer
payloads stay forward compatible; the fields declared here are the ones the frontend relies on.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from .api import Model

# ---------------------------------------------------------------------------
# Common
# ---------------------------------------------------------------------------


class Message(Model):
    code: str
    severity: str = "info"
    params: dict[str, Any] = Field(default_factory=dict)
    message_ru: str
    message_kz: str


class Label(Model):
    code: str | None
    label_ru: str
    label_kz: str


class StatValue(Model):
    value: float | None
    unavailable_reason: str | None


class Provenance(Model):
    analysis_id: str
    code_version: str
    kind: str
    method_version: str


# ---------------------------------------------------------------------------
# Assessment quality
# ---------------------------------------------------------------------------


class QualityAssessmentRef(Model):
    assessment_id: str
    code: str
    stage: str
    administered_on: str | None
    form_id: str
    form_code: str
    form_name: str
    scale_code: str
    linking_method: str
    dataset_id: str


class FormDenominators(Model):
    assigned: int
    present: int
    absent: int
    no_sitting_record: int
    n_items: int
    expected_item_responses: int


class HistogramBin(Model):
    from_: float = Field(alias="from")
    to: float
    count: int


class ScoreDistribution(Model):
    n: int
    mean: float | None
    median: float | None
    sd: float | None
    min: float | None
    max: float | None
    floor_share: float | None
    ceiling_share: float | None
    histogram: list[HistogramBin]
    unavailable_reason: str | None


class Reliability(Model):
    cronbach_alpha: StatValue
    n_complete_learners: int
    n_items: int
    n_zero_variance_items: int
    min_learners: int
    min_items: int


class FormQuality(Model):
    denominators: FormDenominators
    participation_rate: float | None
    completion_rate: float | None
    omission_rate: float | None
    missing_rate: float | None
    item_responses: dict[str, int]
    score_distribution: ScoreDistribution
    reliability: Reliability


class SliceRow(Model):
    value: str
    n: int | None
    mean: float | None
    median: float | None
    sd: float | None
    suppressed: bool
    suppression: str | None


class UpperLower(Model):
    value: float | None
    unavailable_reason: str | None
    group_size: int
    p_upper: float | None
    p_lower: float | None


class OptionQuality(Model):
    key: str
    text: str | None
    is_key: bool
    misconception: str | None
    count: int
    share_of_answered: float | None
    mean_rest_score: float | None
    point_biserial_rest: StatValue


class ItemObjectiveRef(Model):
    objective_id: str
    code: str | None
    status: str
    weight: float
    topic_code: str | None


class ItemQuality(Model):
    item_id: str
    code: str
    max_points: float
    stem_ru: str
    stem_kz: str
    denominators: dict[str, int]
    p_value: float | None
    p_value_among_answered: float | None
    omission_rate: float | None
    missing_rate: float | None
    item_rest_correlation: StatValue
    upper_lower: UpperLower
    options: list[OptionQuality]
    invalid_response_values: int
    flags: list[Message]
    objectives: list[ItemObjectiveRef]
    misconceptions: list[str]


class QualityExclusions(Model):
    absent_learners: int
    assigned_without_sitting_record: int
    rows_excluded_by_attempt_rule: int
    learners_with_repeat_attempts: int
    responses_outside_form: int
    rejected_import_rows_in_dataset: int


class AssessmentQualityOut(Model):
    method_version: str
    dataset_id: str
    dataset_version: int
    current_dataset_version: int
    is_stale: bool
    is_synthetic: bool
    generated_at: str
    provenance: Provenance
    assessment: QualityAssessmentRef
    rules: dict[str, str]
    form: FormQuality
    slices: dict[str, list[SliceRow]]
    items: list[ItemQuality]
    flag_counts: dict[str, int]
    n_flagged_items: int
    exclusions: QualityExclusions
    thresholds: dict[str, float]
    limitations: list[Message]


class QualityDatasetRef(Model):
    id: str
    code: str
    name_ru: str
    name_kz: str


class AssessmentQualitySummary(Model):
    assessment: QualityAssessmentRef
    dataset: QualityDatasetRef
    method_version: str
    dataset_version: int
    generated_at: str
    provenance: Provenance
    is_synthetic: bool
    denominators: FormDenominators
    completion_rate: float | None
    omission_rate: float | None
    mean_score: float | None
    cronbach_alpha: StatValue
    n_items: int
    n_flagged_items: int
    flag_counts: dict[str, int]


class AssessmentQualityList(Model):
    method_version: str
    rules: dict[str, str]
    assessments: list[AssessmentQualitySummary]


class AssessmentItemsOut(Model):
    method_version: str
    dataset_id: str
    dataset_version: int
    generated_at: str
    provenance: Provenance
    assessment: QualityAssessmentRef
    rules: dict[str, str]
    thresholds: dict[str, float]
    limitations: list[Message]
    is_synthetic: bool
    items: list[ItemQuality]


class ItemAdministration(Model):
    assessment: QualityAssessmentRef
    dataset_version: int
    provenance: Provenance
    generated_at: str
    stats: ItemQuality


class ItemQualityDetail(Model):
    method_version: str
    item: dict[str, Any]
    administrations: list[ItemAdministration]
    pooled: dict[str, Any] | None
    pooled_unavailable_reason: str
    limitations: list[Message]


# ---------------------------------------------------------------------------
# Intervention library
# ---------------------------------------------------------------------------

EvidenceLevel = Literal["practice_based", "observational", "experimental"]
VersionStatus = Literal["draft", "reviewed", "archived"]


class EvidenceLink(BaseModel):
    title: str = Field(max_length=300)
    url: str | None = Field(default=None, max_length=1000)
    kind: str = Field(default="source", max_length=40)


class TargetIn(BaseModel):
    target_type: Literal["topic", "objective", "misconception"]
    target_id: str | None = None  # topic/objective id
    misconception_code: str | None = None


class InterventionContent(BaseModel):
    """Versioned content. Every field is part of the immutable version once reviewed."""

    title_ru: str = Field(min_length=1, max_length=300)
    title_kz: str = Field(default="", max_length=300)
    description_ru: str = Field(default="", max_length=4000)
    description_kz: str = Field(default="", max_length=4000)
    grades: list[int] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    minutes_per_session: int = Field(default=20, ge=1, le=600)
    sessions_per_week: int = Field(default=2, ge=1, le=14)
    duration_weeks: int = Field(default=4, ge=1, le=52)
    cadence_ru: str = Field(default="", max_length=300)
    instructions_ru: str = Field(default="", max_length=8000)
    instructions_kz: str = Field(default="", max_length=8000)
    resources: list[str] = Field(default_factory=list)
    evidence_level: EvidenceLevel = "practice_based"
    evidence_links: list[EvidenceLink] = Field(default_factory=list)
    contraindications_ru: str = Field(default="", max_length=4000)
    limitations_ru: str = Field(default="", max_length=4000)
    limitations_kz: str = Field(default="", max_length=4000)
    targets: list[TargetIn] = Field(default_factory=list)


class InterventionCreate(InterventionContent):
    code: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    dataset_id: str | None = None


class InterventionPatch(BaseModel):
    """Partial update of a *draft* version (reviewed versions are immutable)."""

    title_ru: str | None = Field(default=None, min_length=1, max_length=300)
    title_kz: str | None = Field(default=None, max_length=300)
    description_ru: str | None = Field(default=None, max_length=4000)
    description_kz: str | None = Field(default=None, max_length=4000)
    grades: list[int] | None = None
    languages: list[str] | None = None
    minutes_per_session: int | None = Field(default=None, ge=1, le=600)
    sessions_per_week: int | None = Field(default=None, ge=1, le=14)
    duration_weeks: int | None = Field(default=None, ge=1, le=52)
    cadence_ru: str | None = Field(default=None, max_length=300)
    instructions_ru: str | None = Field(default=None, max_length=8000)
    instructions_kz: str | None = Field(default=None, max_length=8000)
    resources: list[str] | None = None
    evidence_level: EvidenceLevel | None = None
    evidence_links: list[EvidenceLink] | None = None
    contraindications_ru: str | None = Field(default=None, max_length=4000)
    limitations_ru: str | None = Field(default=None, max_length=4000)
    limitations_kz: str | None = Field(default=None, max_length=4000)
    targets: list[TargetIn] | None = None
    expected_version: int | None = None


class NewVersionRequest(InterventionPatch):
    change_note: str = Field(default="", max_length=1000)


class ReviewRequest(BaseModel):
    note: str = Field(default="", max_length=1000)


class ArchiveRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class TargetOut(Model):
    target_type: str
    target_id: str | None
    misconception_code: str | None
    code: str | None
    label_ru: str | None
    label_kz: str | None


class InterventionVersionOut(Model):
    id: str
    intervention_id: str
    version: int
    status: VersionStatus
    title_ru: str
    title_kz: str
    description_ru: str
    description_kz: str
    grades: list[int]
    languages: list[str]
    minutes_per_session: int
    sessions_per_week: int
    duration_weeks: int
    total_minutes: int
    cadence_ru: str
    instructions_ru: str
    instructions_kz: str
    resources: list[str]
    evidence_level: EvidenceLevel
    evidence_links: list[dict[str, Any]]
    contraindications_ru: str
    limitations_ru: str
    limitations_kz: str
    targets: list[TargetOut]
    content_sha256: str
    change_note: str
    author: str | None
    reviewed_by: str | None
    reviewed_at: str | None
    created_at: str
    used_by_pilots: int


class EvidenceSummary(Model):
    accepted_entries: int
    proposed_entries: int
    by_status: dict[str, int]
    repeated_positive_signal: bool
    comparable_positive_signals: int
    entries: list[dict[str, Any]]
    note_ru: str
    note_kz: str


class InterventionOut(Model):
    id: str
    code: str
    org_id: str
    dataset_id: str | None
    status: Literal["active", "archived"]
    archived_reason: str | None
    archived_at: str | None
    latest_version: int
    reviewed_version: int | None
    current: InterventionVersionOut
    versions: list[InterventionVersionOut]
    evidence_summary: EvidenceSummary
    created_at: str
    created_by: str | None


class InterventionListItem(Model):
    id: str
    code: str
    status: str
    dataset_id: str | None
    latest_version: int
    reviewed_version: int | None
    current_status: str
    title_ru: str
    title_kz: str
    evidence_level: str
    grades: list[int]
    languages: list[str]
    targets: list[TargetOut]
    total_minutes: int
    n_pilots: int
    accepted_evidence: int


class SuggestionComponent(Model):
    code: str
    points: float
    detail: str


class Suggestion(Model):
    intervention_id: str
    code: str
    version: int
    title_ru: str
    title_kz: str
    evidence_level: str
    score: float
    components: list[SuggestionComponent]
    contraindications_ru: str
    limitations_ru: str


class SuggestionsOut(Model):
    ranking_kind: Literal["explainable_match_score"]
    scoring_rule: dict[str, float]
    query: dict[str, Any]
    suggestions: list[Suggestion]
    excluded: list[dict[str, Any]]
    limitations: list[Message]


# ---------------------------------------------------------------------------
# Pilots
# ---------------------------------------------------------------------------

Design = Literal["single_group", "matched_comparison", "cluster_randomized", "interrupted_time_series", "stepped_wedge"]
PilotStatus = Literal["draft", "ready", "active", "completed", "stopped"]


class PilotCohortIn(BaseModel):
    cohort_id: str
    arm: Literal["intervention", "comparison"] = "intervention"
    wave: int | None = Field(default=None, ge=1, le=12)


class AnalysisPlan(BaseModel):
    primary_estimand: Literal["mean_paired_change", "difference_in_mean_changes"] | None = None
    adjustment: Literal["none", "baseline_strata"] = "none"
    strata_scheme: Literal["pre_three_level", "pre_two_level"] = "pre_three_level"
    attempt_rule: Literal["first", "last"] = "first"
    omitted_policy: Literal["as_incorrect", "exclude"] = "as_incorrect"
    min_matched_learners: int = Field(default=30, ge=10, le=10000)
    notes: str = Field(default="", max_length=2000)


class PilotCreate(BaseModel):
    dataset_id: str
    title: str = Field(min_length=3, max_length=300)
    intervention_id: str
    intervention_version: int | None = None  # default: latest reviewed, else latest
    decision_id: str | None = None
    topic_id: str
    objective_id: str | None = None
    primary_outcome_ru: str = Field(default="", max_length=1000)
    assignment_unit: Literal["cohort", "school"] = "cohort"
    design: Design = "single_group"
    cohorts: list[PilotCohortIn] = Field(default_factory=list)
    baseline_assessment_id: str | None = None
    outcome_assessment_id: str | None = None
    pre_period_assessment_ids: list[str] = Field(default_factory=list)
    start_date: date | None = None
    end_date: date | None = None
    follow_up_due: date | None = None
    owner: str = Field(default="", max_length=200)
    minutes_per_session: int | None = Field(default=None, ge=1, le=600)
    sessions_per_week: int | None = Field(default=None, ge=1, le=14)
    duration_weeks: int | None = Field(default=None, ge=1, le=52)
    inclusion_criteria: str = Field(default="", max_length=2000)
    exclusion_criteria: str = Field(default="", max_length=2000)
    analysis_plan: AnalysisPlan = Field(default_factory=AnalysisPlan)


class PilotPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    intervention_version: int | None = None
    decision_id: str | None = None
    topic_id: str | None = None
    objective_id: str | None = None
    primary_outcome_ru: str | None = Field(default=None, max_length=1000)
    assignment_unit: Literal["cohort", "school"] | None = None
    design: Design | None = None
    cohorts: list[PilotCohortIn] | None = None
    baseline_assessment_id: str | None = None
    outcome_assessment_id: str | None = None
    pre_period_assessment_ids: list[str] | None = None
    start_date: date | None = None
    end_date: date | None = None
    follow_up_due: date | None = None
    owner: str | None = Field(default=None, max_length=200)
    minutes_per_session: int | None = Field(default=None, ge=1, le=600)
    sessions_per_week: int | None = Field(default=None, ge=1, le=14)
    duration_weeks: int | None = Field(default=None, ge=1, le=52)
    inclusion_criteria: str | None = Field(default=None, max_length=2000)
    exclusion_criteria: str | None = Field(default=None, max_length=2000)
    analysis_plan: AnalysisPlan | None = None


class TransitionRequest(BaseModel):
    to_status: PilotStatus
    note: str = Field(default="", max_length=1000)


class RandomizeRequest(BaseModel):
    seed: int = Field(ge=0, le=2**31 - 1)
    cohort_ids: list[str] = Field(min_length=2)


class SetOutcomeRequest(BaseModel):
    outcome_assessment_id: str


class PilotCohortOut(Model):
    cohort_id: str
    code: str | None
    school_id: str | None
    school_code: str | None
    arm: str
    wave: int | None
    n_learners: int | None


class PilotEventOut(Model):
    from_status: str | None
    to_status: str
    note: str
    at: str
    by: str | None


class PilotOut(Model):
    id: str
    code: str
    title: str
    dataset_id: str
    status: PilotStatus
    design: Design
    assignment_unit: str
    causal_ceiling: Label
    intervention_id: str
    intervention_version_id: str
    intervention_version: int
    intervention_snapshot: dict[str, Any]
    snapshot_sha256: str
    snapshot_locked: bool
    decision_id: str | None
    topic: dict[str, Any] | None
    objective: dict[str, Any] | None
    primary_outcome_ru: str
    cohorts: list[PilotCohortOut]
    randomization: dict[str, Any] | None
    baseline_assessment: dict[str, Any] | None
    outcome_assessment: dict[str, Any] | None
    pre_period_assessment_ids: list[str]
    start_date: str | None
    end_date: str | None
    follow_up_due: str | None
    owner: str
    planned: dict[str, int]
    inclusion_criteria: str
    exclusion_criteria: str
    analysis_plan: dict[str, Any]
    validation: dict[str, Any]
    allowed_transitions: list[str]
    events: list[PilotEventOut]
    latest_outcome: dict[str, Any] | None
    created_at: str
    created_by: str | None
    is_synthetic: bool


class PilotListItem(Model):
    id: str
    code: str
    title: str
    dataset_id: str
    status: str
    design: str
    intervention_code: str
    intervention_version: int
    topic_code: str | None
    start_date: str | None
    end_date: str | None
    follow_up_due: str | None
    n_cohorts: int
    fidelity: str | None
    outcome_status: str | None


# ---------------------------------------------------------------------------
# Fidelity
# ---------------------------------------------------------------------------


class AdherenceItem(BaseModel):
    key: str = Field(min_length=1, max_length=60)
    label: str = Field(default="", max_length=300)
    done: bool


class FidelityLogCreate(BaseModel):
    cohort_id: str
    session_date: date
    planned_minutes: int = Field(ge=0, le=600)
    delivered_minutes: int = Field(ge=0, le=600)
    activities_planned: int = Field(default=0, ge=0, le=100)
    activities_completed: int = Field(default=0, ge=0, le=100)
    completed_tasks: list[str] = Field(default_factory=list, max_length=50)
    learners_present: int | None = Field(default=None, ge=0, le=500)
    learners_assigned: int | None = Field(default=None, ge=0, le=500)
    adherence: list[AdherenceItem] = Field(default_factory=list, max_length=30)
    adaptation_note: str = Field(default="", max_length=2000)
    disruption: Literal["none", "cancelled", "shortened", "teacher_absent", "holiday", "other"] = "none"
    disruption_note: str = Field(default="", max_length=1000)
    source: Literal["teacher_log", "observation", "coach_visit", "import"] = "teacher_log"
    corrects_log_id: str | None = None


class FidelityLogOut(Model):
    id: str
    pilot_id: str
    cohort_id: str
    cohort_code: str | None
    session_date: str
    planned_minutes: int
    delivered_minutes: int
    activities_planned: int
    activities_completed: int
    completed_tasks: list[str]
    learners_present: int | None
    learners_assigned: int | None
    adherence: list[dict[str, Any]]
    adaptation_note: str
    disruption: str
    disruption_note: str
    source: str
    recorder: str | None
    corrects_log_id: str | None
    superseded_by: str | None
    created_at: str


class FidelityMetrics(Model):
    expected_sessions: int
    logged_sessions: int
    delivered_sessions: int
    cancelled_sessions: int
    missing_logs: int
    log_coverage: float | None
    dosage_completion: float | None
    session_completion: float | None
    reach: float | None
    adherence: float | None
    classification: Label
    reasons: list[str]


class FidelityCohortRow(Model):
    cohort_id: str
    code: str | None
    metrics: FidelityMetrics


class FidelityOut(Model):
    pilot_id: str
    method_version: str
    as_of: str
    rule_set: dict[str, Any]
    overall: FidelityMetrics
    distribution: dict[str, int]
    cohorts: list[FidelityCohortRow] | None
    cohort_detail_visible: bool
    logs: list[FidelityLogOut] | None
    limitations: list[Message]


# ---------------------------------------------------------------------------
# Follow-up / learning loop / portfolio
# ---------------------------------------------------------------------------


class FollowUpRun(BaseModel):
    outcome_assessment_id: str | None = None
    as_of: date | None = None


class PilotOutcomeOut(Model):
    id: str
    pilot_id: str
    status: str
    status_label: Label
    causal_level: Label
    causal_ceiling: Label
    fidelity: Label
    method_version: str
    dataset_version: int
    current_dataset_version: int
    is_stale: bool
    interim: bool
    as_of: str | None
    created_at: str
    result: dict[str, Any]


class ConclusionCreate(BaseModel):
    outcome_id: str
    decision: Literal["continue", "modify", "stop", "extend_data_collection"]
    summary_ru: str = Field(min_length=10, max_length=4000)
    summary_kz: str = Field(default="", max_length=4000)
    lessons_ru: str = Field(default="", max_length=4000)
    open_questions: list[str] = Field(default_factory=list, max_length=20)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    create_next_decision_version: bool = True
    next_action_ru: str = Field(default="", max_length=4000)
    propose_evidence_update: bool = True


class EvidenceReview(BaseModel):
    accept: bool
    note: str = Field(default="", max_length=1000)


class ConclusionOut(Model):
    id: str
    pilot_id: str
    outcome_id: str
    outcome_status: str
    decision: str
    summary_ru: str
    summary_kz: str
    lessons_ru: str
    open_questions: list[str]
    evidence_ids: list[str]
    next_decision_id: str | None
    evidence_entry: dict[str, Any] | None
    created_at: str
    created_by: str | None


class LearningSummary(Model):
    interventions: list[dict[str, Any]]
    lessons: list[dict[str, Any]]
    open_questions: list[dict[str, Any]]
    pending_evidence_reviews: list[dict[str, Any]]
    note_ru: str
    note_kz: str


class PortfolioOut(Model):
    generated_at: str
    as_of: str
    dataset_id: str | None
    counts_by_status: dict[str, int]
    follow_ups: dict[str, Any]
    fidelity_distribution: dict[str, int]
    outcome_distribution: dict[str, int]
    interventions_with_repeated_signals: list[dict[str, Any]]
    coverage: dict[str, Any]
    missing_for_conclusions: list[dict[str, Any]]
    action_queue: list[dict[str, Any]]
    best_intervention: None
    best_intervention_reason: str
    pilots: list[PilotListItem]
    limitations: list[Message]
