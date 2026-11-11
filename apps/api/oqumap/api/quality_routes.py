"""Assessment Quality Lab endpoints (read-only; any authenticated member of the organisation)."""

from __future__ import annotations

from fastapi import APIRouter

from ..schemas import interventions as S
from ..services import quality as svc
from .routes import DB, P

router = APIRouter(prefix="/api/v1/quality", tags=["quality"])


def _params(attempt_rule: str, omitted_policy: str) -> svc.QualityParams:
    return svc.QualityParams(attempt_rule=attempt_rule, omitted_policy=omitted_policy)


@router.get("/assessments", response_model=S.AssessmentQualityList)
def list_quality(p: P, session: DB, dataset_id: str | None = None, attempt_rule: str = "first",
                 omitted_policy: str = "as_incorrect"):
    return svc.list_assessments(session, p.org_id, dataset_id, _params(attempt_rule, omitted_policy), p.user_id)


@router.get("/assessments/{assessment_id}", response_model=S.AssessmentQualityOut)
def assessment_quality(assessment_id: str, p: P, session: DB, dataset_id: str | None = None, attempt_rule: str = "first",
                       omitted_policy: str = "as_incorrect"):
    return svc.assessment_quality(session, p.org_id, assessment_id, _params(attempt_rule, omitted_policy), p.user_id, dataset_id)


@router.get("/assessments/{assessment_id}/items", response_model=S.AssessmentItemsOut)
def assessment_items(assessment_id: str, p: P, session: DB, dataset_id: str | None = None, attempt_rule: str = "first",
                     omitted_policy: str = "as_incorrect", flag: str | None = None):
    return svc.item_items(session, p.org_id, assessment_id, _params(attempt_rule, omitted_policy), p.user_id, dataset_id, flag)


@router.get("/items/{item_id}", response_model=S.ItemQualityDetail)
def item_quality(item_id: str, p: P, session: DB, dataset_id: str | None = None, attempt_rule: str = "first",
                 omitted_policy: str = "as_incorrect"):
    return svc.item_detail(session, p.org_id, item_id, _params(attempt_rule, omitted_policy), p.user_id, dataset_id)


@router.get("/assessments/{assessment_id}/assignments", response_model=S.AssignmentsOut)
def get_assignments(assessment_id: str, p: P, session: DB):
    return svc.assignments(session, p.org_id, assessment_id)


@router.put("/assessments/{assessment_id}/assignments", response_model=S.AssignmentsOut)
def put_assignments(assessment_id: str, body: S.AssignmentsIn, p: P, session: DB):
    return svc.set_assignments(session, p, assessment_id, body.cohort_ids, body.note)
