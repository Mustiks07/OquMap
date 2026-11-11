"""Intervention library, pilot protocol, fidelity, follow-up / learning loop and portfolio endpoints.

Permissions (adapted to the existing role model, see docs/INTERVENTION_AND_PILOT_PROTOCOL.md §Права):
* any authenticated member (viewer/analyst included): read library, pilots, aggregates, portfolio;
* methodist: draft interventions/pilots, randomise, fidelity logs, follow-up, conclusions;
* approver/admin: review/archive interventions, activate/stop pilots, accept evidence entries;
* cohort-level fidelity/outcome rows: methodist, approver, teacher, admin only.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query

from ..schemas import interventions as S
from ..services import design_studio as eds
from ..services import fidelity as fid
from ..services import interventions as ivs
from ..services import learning_loop as loop
from ..services import pilots as pls
from ..services import portfolio as pf
from ..services import sessions as cal
from .routes import DB, P

router = APIRouter(prefix="/api/v1")

# ---------------------------------------------------------------------------
# Intervention library
# ---------------------------------------------------------------------------


Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def page(rows: list, limit: int, offset: int) -> dict:
    """Stable page of an already ordered list (order: code, then id)."""
    return {"items": rows[offset:offset + limit], "total": len(rows), "limit": limit, "offset": offset}


@router.get("/interventions", response_model=S.InterventionPage, tags=["interventions"])
def list_interventions(p: P, session: DB, dataset_id: str | None = None, status: str | None = None,
                       evidence_level: str | None = None, topic_id: str | None = None, objective_id: str | None = None,
                       misconception: str | None = None, grade: int | None = None, language: str | None = None,
                       q: str | None = None, limit: Limit = 50, offset: Offset = 0):
    rows = ivs.list_interventions(session, p.org_id, dataset_id, status, evidence_level, topic_id, objective_id, misconception,
                                  grade, language, q)
    return page(sorted(rows, key=lambda r: (r["code"], r["id"])), limit, offset)


@router.post("/interventions", response_model=S.InterventionOut, tags=["interventions"])
def create_intervention(body: S.InterventionCreate, p: P, session: DB):
    return ivs.create(session, p, body)


@router.get("/interventions/suggest", response_model=S.SuggestionsOut, tags=["interventions"])
def suggest_interventions(p: P, session: DB, dataset_id: str | None = None, topic_id: str | None = None,
                          objective_id: str | None = None, misconception: str | None = None, grade: int | None = None,
                          language: str | None = None):
    return ivs.suggest(session, p.org_id, dataset_id, topic_id, objective_id, misconception, grade, language)


@router.get("/interventions/{intervention_id}", response_model=S.InterventionOut, tags=["interventions"])
def get_intervention(intervention_id: str, p: P, session: DB):
    return ivs.payload(session, ivs.get_intervention(session, p.org_id, intervention_id))


@router.patch("/interventions/{intervention_id}", response_model=S.InterventionOut, tags=["interventions"])
def update_intervention(intervention_id: str, body: S.InterventionPatch, p: P, session: DB):
    return ivs.update_draft(session, p, intervention_id, body)


@router.post("/interventions/{intervention_id}/versions", response_model=S.InterventionOut, tags=["interventions"])
def new_intervention_version(intervention_id: str, body: S.NewVersionRequest, p: P, session: DB):
    return ivs.new_version(session, p, intervention_id, body)


@router.post("/interventions/{intervention_id}/versions/{version}/review", response_model=S.InterventionOut, tags=["interventions"])
def review_intervention_version(intervention_id: str, version: int, body: S.ReviewRequest, p: P, session: DB):
    return ivs.review(session, p, intervention_id, version, body)


@router.delete("/interventions/{intervention_id}/versions/{version}", tags=["interventions"])
def delete_intervention_draft(intervention_id: str, version: int, p: P, session: DB) -> dict[str, Any]:
    return ivs.delete_draft(session, p, intervention_id, version)


@router.post("/interventions/{intervention_id}/archive", response_model=S.InterventionOut, tags=["interventions"])
def archive_intervention(intervention_id: str, body: S.ArchiveRequest, p: P, session: DB):
    return ivs.archive(session, p, intervention_id, body)


@router.post("/interventions/{intervention_id}/targets", response_model=S.InterventionOut, tags=["interventions"])
def link_intervention_target(intervention_id: str, body: S.TargetIn, p: P, session: DB):
    return ivs.add_target(session, p, intervention_id, body)


@router.get("/interventions/{intervention_id}/evidence", response_model=S.EvidenceSummary, tags=["interventions"])
def intervention_evidence(intervention_id: str, p: P, session: DB):
    return ivs.evidence_summary(session, ivs.get_intervention(session, p.org_id, intervention_id))


@router.post("/intervention-evidence/{entry_id}/review", response_model=S.EvidenceSummary, tags=["interventions", "learning"])
def review_evidence_entry(entry_id: str, body: S.EvidenceReview, p: P, session: DB):
    return loop.review_evidence(session, p, entry_id, body)


# ---------------------------------------------------------------------------
# Pilots
# ---------------------------------------------------------------------------


@router.get("/pilots", response_model=S.PilotPage, tags=["pilots"])
def list_pilots(p: P, session: DB, dataset_id: str | None = None, status: str | None = None, intervention_id: str | None = None,
                limit: Limit = 50, offset: Offset = 0):
    rows = pls.list_pilots(session, p.org_id, dataset_id, status, intervention_id)
    return page(sorted(rows, key=lambda r: (r["code"], r["id"])), limit, offset)


@router.post("/pilots", response_model=S.PilotOut, tags=["pilots"])
def create_pilot(body: S.PilotCreate, p: P, session: DB):
    return pls.create(session, p, body)


@router.get("/pilots/{pilot_id}", response_model=S.PilotOut, tags=["pilots"])
def get_pilot(pilot_id: str, p: P, session: DB):
    return pls.payload(session, pls.get_pilot(session, p.org_id, pilot_id), p)


@router.patch("/pilots/{pilot_id}", response_model=S.PilotOut, tags=["pilots"])
def update_pilot(pilot_id: str, body: S.PilotPatch, p: P, session: DB):
    return pls.update(session, p, pilot_id, body)


@router.post("/pilots/{pilot_id}/randomize", response_model=S.PilotOut, tags=["pilots"])
def randomize_pilot(pilot_id: str, body: S.RandomizeRequest, p: P, session: DB):
    return pls.randomize(session, p, pilot_id, body)


@router.post("/pilots/{pilot_id}/transition", response_model=S.PilotOut, tags=["pilots"])
def transition_pilot(pilot_id: str, body: S.TransitionRequest, p: P, session: DB):
    return pls.transition(session, p, pilot_id, body)


@router.get("/pilots/{pilot_id}/fidelity", response_model=S.FidelityOut, tags=["fidelity"])
def pilot_fidelity(pilot_id: str, p: P, session: DB, as_of: date | None = None):
    return fid.fidelity_payload(session, p, pilot_id, as_of)


@router.post("/pilots/{pilot_id}/fidelity-logs", response_model=S.FidelityLogOut, tags=["fidelity"])
def add_fidelity_log(pilot_id: str, body: S.FidelityLogCreate, p: P, session: DB):
    return fid.add_log(session, p, pilot_id, body)


@router.post("/pilots/{pilot_id}/follow-up", response_model=S.PilotOutcomeOut, tags=["learning"])
def run_follow_up(pilot_id: str, body: S.FollowUpRun, p: P, session: DB):
    return loop.run_follow_up(session, p, pilot_id, body)


@router.get("/pilots/{pilot_id}/outcomes", response_model=list[S.PilotOutcomeOut], tags=["learning"])
def pilot_outcomes(pilot_id: str, p: P, session: DB):
    return loop.list_outcomes(session, p, pilot_id)


@router.post("/pilots/{pilot_id}/conclusions", response_model=S.ConclusionOut, tags=["learning"])
def create_conclusion(pilot_id: str, body: S.ConclusionCreate, p: P, session: DB):
    return loop.create_conclusion(session, p, pilot_id, body)


@router.get("/pilots/{pilot_id}/conclusions", response_model=list[S.ConclusionOut], tags=["learning"])
def list_conclusions(pilot_id: str, p: P, session: DB):
    return loop.list_conclusions(session, p, pilot_id)


@router.get("/learning/summary", response_model=S.LearningSummary, tags=["learning"])
def learning_summary(p: P, session: DB, dataset_id: str | None = None):
    return loop.learning_summary(session, p, dataset_id)


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


@router.get("/portfolio/interventions", response_model=S.PortfolioOut, tags=["portfolio"])
def intervention_portfolio(p: P, session: DB, dataset_id: str | None = None, as_of: date | None = None):
    return pf.portfolio(session, p, dataset_id, as_of)


# ---------------------------------------------------------------------------
# Experiment Design Studio
# ---------------------------------------------------------------------------


@router.post("/design-studio/evaluate", response_model=S.DesignStudioOut, tags=["design-studio"])
def design_studio(body: S.DesignStudioRequest, p: P, session: DB):
    """Deterministic design comparison for planning; never approves or changes a pilot."""
    return eds.evaluate(session, p.org_id, body)


# ---------------------------------------------------------------------------
# Session calendar
# ---------------------------------------------------------------------------


@router.get("/pilots/{pilot_id}/sessions", response_model=S.SessionCalendarOut, tags=["calendar"])
def pilot_sessions(pilot_id: str, p: P, session: DB):
    return cal.get_calendar(session, p, pilot_id)


@router.post("/pilots/{pilot_id}/sessions/generate", response_model=S.SessionCalendarOut, tags=["calendar"])
def generate_sessions(pilot_id: str, body: S.SessionGenerate, p: P, session: DB):
    return cal.generate(session, p, pilot_id, body)


@router.post("/pilots/{pilot_id}/sessions", response_model=S.SessionCalendarOut, tags=["calendar"])
def add_session(pilot_id: str, body: S.SessionCreate, p: P, session: DB):
    return cal.add(session, p, pilot_id, body)


@router.patch("/pilots/{pilot_id}/sessions/{session_id}", response_model=S.SessionCalendarOut, tags=["calendar"])
def update_session(pilot_id: str, session_id: str, body: S.SessionPatch, p: P, session: DB):
    return cal.update(session, p, pilot_id, session_id, body)


@router.delete("/pilots/{pilot_id}/sessions/{session_id}", response_model=S.SessionCalendarOut, tags=["calendar"])
def delete_session(pilot_id: str, session_id: str, p: P, session: DB):
    return cal.delete(session, p, pilot_id, session_id)
