"""Full-text search over the organisation's source fragments (BM25 with a light Russian/Kazakh stemmer).

Returns document, fragment, version and the matched terms as the relevance rationale. On a small corpus a
verified lexical search is adequate; a vector index is not required for the task.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m

TOKEN_RE = re.compile(r"[a-zа-яёәғқңөұүһі0-9]+", re.IGNORECASE)
SUFFIXES = sorted(["ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими", "ая", "яя", "ое", "ее", "ые", "ие", "ой",
                   "ей", "ий", "ый", "ов", "ев", "ам", "ям", "ах", "ях", "ом", "ем", "ую", "юю", "ть", "ти", "ет", "ут",
                   "ют", "ит", "ат", "ят", "ия", "ий", "ия", "ья", "ы", "и", "а", "я", "о", "е", "у", "ю", "ь",
                   "лар", "лер", "дар", "дер", "тар", "тер", "ның", "нің", "дың", "дің"], key=len, reverse=True)
STOP = {"и", "в", "во", "на", "с", "со", "к", "по", "из", "у", "о", "а", "но", "не", "что", "это", "как", "для", "от",
        "или", "the", "of", "және", "мен", "бен"}


def stem(token: str) -> str:
    t = token.lower().replace("ё", "е")
    if len(t) <= 3 or t.isdigit():
        return t
    for s in SUFFIXES:
        if t.endswith(s) and len(t) - len(s) >= 3:
            return t[: -len(s)]
    return t


def tokens(text: str) -> list[str]:
    return [stem(t) for t in TOKEN_RE.findall(text.lower()) if t.lower() not in STOP]


def search(session: Session, org_id: str, query: str, limit: int = 10, edition_id: str | None = None) -> dict:
    q = [t for t in tokens(query)]
    if not q:
        return {"query": query, "results": [], "method": "bm25-lexical-v1"}
    stmt = (select(m.ContentFragment, m.Document).join(m.Document, m.Document.id == m.ContentFragment.document_id)
            .where(m.ContentFragment.org_id == org_id, m.Document.org_id == org_id,
                   m.ContentFragment.document_version == m.Document.version))
    if edition_id:
        stmt = stmt.where(m.Document.edition_id == edition_id)
    rows = session.execute(stmt).all()
    docs = [(f, d, tokens(f.text + " " + (f.heading or ""))) for f, d in rows]
    if not docs:
        return {"query": query, "results": [], "method": "bm25-lexical-v1"}
    N = len(docs)
    avgdl = sum(len(t) for _, _, t in docs) / N
    df = Counter()
    for _, _, toks in docs:
        for term in set(toks):
            df[term] += 1
    k1, b = 1.4, 0.75
    scored = []
    for f, d, toks in docs:
        tf = Counter(toks)
        score = 0.0
        matched = []
        for term in set(q):
            if tf[term] == 0:
                continue
            idf = math.log(1 + (N - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(toks) / avgdl))
            matched.append(term)
        if score > 0:
            scored.append((score, f, d, matched))
    scored.sort(key=lambda x: -x[0])
    editions = {e.id: e for e in session.scalars(select(m.TextbookEdition).where(m.TextbookEdition.org_id == org_id))}
    results = []
    for score, f, d, matched in scored[:limit]:
        ed = editions.get(d.edition_id)
        results.append({"source_id": f.id, "document_id": d.id, "document_filename": d.filename,
                        "document_version": f.document_version, "edition_code": ed.code if ed else None,
                        "anchor": f.anchor, "page_physical": f.page_physical, "page_printed": f.page_printed,
                        "excerpt": f.text[:300], "score": round(score, 4),
                        "relevance": {"matched_terms": sorted(matched), "query_terms": sorted(set(q))}})
    return {"query": query, "results": results, "method": "bm25-lexical-v1"}
