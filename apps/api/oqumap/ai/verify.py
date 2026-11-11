"""Checks applied to every generated text before it is shown.

* Numbers: each number in the text must match a value of the structured metrics it was generated from
  (shares may appear as percentages, differences as percentage points). Mathematical content of items or
  sources (e.g. "1/2 + 1/3") is allowed when it appears verbatim in the provided context.
* Citations: every cited source must exist and belong to the caller's organisation.
"""

from __future__ import annotations

import math
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m

NUM_RE = re.compile(r"(?<![\w/.,])[-−]?\d+(?:[.,]\d+)?(?![\w/])")
CODE_RE = re.compile(r"\b(?:DEMO-M6-\d+\.\d+|[TI]\d{1,2}|S\d{2}(?:-\S+)?|F-[A-Z\-0-9]+|ED[AB])\b")
FRACTION_RE = re.compile(r"\d+\s*/\s*\d+|\d+\s+\d+/\d+")


def collect_numbers(obj, out: set[float] | None = None) -> set[float]:
    out = out if out is not None else set()
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        if math.isfinite(float(obj)):
            v = float(obj)
            out.add(v)
            if -1.0 <= v <= 1.0:
                out.add(v * 100)  # share or difference shown in % / p.p.
        return out
    if isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_numbers(v, out)
    return out


def check_numbers(text: str, metrics: dict, context_text: str = "", tolerance: float = 0.6) -> dict:
    allowed = collect_numbers(metrics)
    stripped = CODE_RE.sub(" ", text)
    ctx_fracs = {re.sub(r"\s+", "", f) for f in FRACTION_RE.findall(context_text)}
    for frac in FRACTION_RE.findall(stripped):
        if re.sub(r"\s+", "", frac) in ctx_fracs:
            stripped = stripped.replace(frac, " ")
    ctx_numbers = {float(x.replace(",", ".").replace("−", "-")) for x in NUM_RE.findall(CODE_RE.sub(" ", context_text))}
    unverified = []
    checked = 0
    for raw in NUM_RE.findall(stripped):
        v = float(raw.replace(",", ".").replace("−", "-"))
        checked += 1
        if any(abs(v - a) <= tolerance for a in allowed) or v in ctx_numbers or abs(v) in {abs(a) for a in allowed}:
            continue
        unverified.append(raw)
    return {"status": "passed" if not unverified else "failed", "numbers_checked": checked, "unverified_numbers": unverified}


def check_citations(session: Session, org_id: str, source_ids: list[str]) -> dict:
    if not source_ids:
        return {"status": "passed", "missing": [], "checked": 0}
    found = set(session.scalars(select(m.ContentFragment.id).where(m.ContentFragment.id.in_(source_ids),
                                                                   m.ContentFragment.org_id == org_id)))
    missing = [s for s in source_ids if s not in found]
    return {"status": "passed" if not missing else "failed", "missing": missing, "checked": len(source_ids)}
