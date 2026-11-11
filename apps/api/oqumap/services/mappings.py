"""Review of proposed links (item→objective, fragment→objective): proposed → confirmed | rejected.

Confirming/rejecting an item link changes how scores are computed, so every dataset of the organisation that uses
the programme gets a new version (old analyses become visibly stale). Item link weights are renormalised so that
the confirmed links of one item always sum to 1 (no double counting).
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..db import utcnow
from ..errors import ApiError, not_found
from .auth import Principal
from .common import audit, bump_dataset_version


class ReviewRequest(BaseModel):
    decision: str  # confirm | reject
    note: str | None = None


def mapping_hash(session: Session, org_id: str) -> str:
    h = hashlib.sha256()
    for row in session.execute(select(m.ItemObjective.id, m.ItemObjective.status, m.ItemObjective.weight)
                               .where(m.ItemObjective.org_id == org_id).order_by(m.ItemObjective.id)):
        h.update(f"{row[0]}{row[1]}{row[2]:.6f}".encode())
    for row in session.execute(select(m.FragmentObjective.id, m.FragmentObjective.status)
                               .where(m.FragmentObjective.org_id == org_id).order_by(m.FragmentObjective.id)):
        h.update(f"{row[0]}{row[1]}".encode())
    return h.hexdigest()


def review(session: Session, p: Principal, link_id: str, req: ReviewRequest) -> dict:
    p.require("methodist", "teacher")
    if req.decision not in ("confirm", "reject"):
        raise ApiError("invalid_parameter", "decision: confirm | reject", 422)
    status = "confirmed" if req.decision == "confirm" else "rejected"
    item_link = session.scalar(select(m.ItemObjective).where(m.ItemObjective.id == link_id, m.ItemObjective.org_id == p.org_id))
    if item_link is not None:
        item_link.status = status
        item_link.reviewed_by = p.user_id
        item_link.reviewed_at = utcnow()
        session.flush()
        _renormalise(session, p.org_id, item_link.item_id)
        item = session.get(m.Item, item_link.item_id)
        bumped = []
        for ds in session.scalars(select(m.Dataset).where(m.Dataset.org_id == p.org_id,
                                                          m.Dataset.program_version_id == item.program_version_id)):
            bumped.append({"dataset_id": ds.id, "version": bump_dataset_version(session, ds, f"mapping_review:{item.code}")})
        audit(session, p.org_id, p.user_id, f"mapping.{req.decision}", "item_objective", link_id, note=req.note)
        session.commit()
        return {"link_id": link_id, "kind": "item", "status": status, "datasets_bumped": bumped}
    frag_link = session.scalar(select(m.FragmentObjective).where(m.FragmentObjective.id == link_id,
                                                                 m.FragmentObjective.org_id == p.org_id))
    if frag_link is None:
        raise not_found("mapping", link_id)
    frag_link.status = status
    frag_link.reviewed_by = p.user_id
    frag_link.reviewed_at = utcnow()
    if frag_link.generation_id:
        g = session.get(m.AIGeneration, frag_link.generation_id)
        if g is not None and g.org_id == p.org_id:
            g.review_status = "reviewed"
    audit(session, p.org_id, p.user_id, f"mapping.{req.decision}", "fragment_objective", link_id, note=req.note)
    session.commit()
    return {"link_id": link_id, "kind": "fragment", "status": status, "datasets_bumped": []}


def _renormalise(session: Session, org_id: str, item_id: str) -> None:
    links = list(session.scalars(select(m.ItemObjective).where(m.ItemObjective.item_id == item_id,
                                                               m.ItemObjective.org_id == org_id)))
    for group in ("confirmed", "proposed"):
        sel = [x for x in links if x.status == group]
        total = sum(x.weight for x in sel)
        if sel and total > 0 and abs(total - 1) > 1e-9:
            for x in sel:
                x.weight = x.weight / total


def list_links(session: Session, org_id: str, document_id: str | None = None, status: str | None = None) -> dict:
    q = (select(m.FragmentObjective, m.ContentFragment, m.LearningObjective)
         .join(m.ContentFragment, m.ContentFragment.id == m.FragmentObjective.fragment_id)
         .join(m.LearningObjective, m.LearningObjective.id == m.FragmentObjective.objective_id)
         .where(m.FragmentObjective.org_id == org_id, m.ContentFragment.org_id == org_id))
    if document_id:
        q = q.where(m.ContentFragment.document_id == document_id)
    if status:
        q = q.where(m.FragmentObjective.status == status)
    frag_links = [{"link_id": fo.id, "kind": "fragment", "fragment_id": f.id, "anchor": f.anchor,
                   "page_physical": f.page_physical, "page_printed": f.page_printed, "objective_id": o.id,
                   "objective_code": o.code, "objective_text_ru": o.text_ru, "status": fo.status, "origin": fo.origin,
                   "rationale": fo.rationale, "generation_id": fo.generation_id,
                   "reviewed_at": fo.reviewed_at.isoformat() if fo.reviewed_at else None}
                  for fo, f, o in session.execute(q.order_by(m.ContentFragment.order_index))]
    iq = (select(m.ItemObjective, m.Item, m.LearningObjective)
          .join(m.Item, m.Item.id == m.ItemObjective.item_id)
          .join(m.LearningObjective, m.LearningObjective.id == m.ItemObjective.objective_id)
          .where(m.ItemObjective.org_id == org_id))
    if status:
        iq = iq.where(m.ItemObjective.status == status)
    item_links = [{"link_id": io.id, "kind": "item", "item_id": it.id, "item_code": it.code, "stem_ru": it.stem_ru,
                   "objective_id": o.id, "objective_code": o.code, "objective_text_ru": o.text_ru, "weight": io.weight,
                   "status": io.status, "origin": io.origin} for io, it, o in session.execute(iq.order_by(m.Item.code))]
    return {"fragment_links": frag_links if document_id or status else frag_links, "item_links": item_links if not document_id else []}
