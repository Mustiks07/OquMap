from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..db import utcnow
from ..errors import not_found

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def audit(session: Session, org_id: str | None, user_id: str | None, action: str, entity_type: str,
          entity_id: str | None = None, **details) -> None:
    session.add(
        m.AuditLog(org_id=org_id, user_id=user_id, action=action, entity_type=entity_type, entity_id=entity_id,
                   request_id=request_id_var.get(), details=details)
    )


def bump_dataset_version(session: Session, dataset: m.Dataset, reason: str, import_batch_id: str | None = None) -> int:
    dataset.version += 1
    dataset.version_updated_at = utcnow()
    session.add(m.DatasetVersionEvent(dataset_id=dataset.id, version=dataset.version, reason=reason,
                                      import_batch_id=import_batch_id))
    return dataset.version


def get_dataset(session: Session, org_id: str, dataset_id: str) -> m.Dataset:
    ds = session.scalar(select(m.Dataset).where(m.Dataset.id == dataset_id, m.Dataset.org_id == org_id))
    if ds is None:
        raise not_found("dataset", dataset_id)
    return ds


def fingerprint(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
