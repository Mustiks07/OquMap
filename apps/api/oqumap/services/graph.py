"""Evidence graph: one verifiable chain from a weak topic to the decision and its follow-up.

topic → prerequisite objectives → objectives → items → misconception hypotheses → edition pages (sources)
→ planned hours → decisions → follow-up checks.

Every node points to something that can be opened and checked: a stored analysis run plus a JSON path (the
calculation), a source fragment (the page), an item with its answer distribution (the rows), a plan row or a
decision. Missing links are shown as explicit ``gap`` nodes instead of being hidden. A model never adds nodes:
it may only *select* node IDs, and ``validate_selection`` rejects anything that is not in the graph.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import ApiError
from . import analysis as an

GAP_TEXT = {
    "prerequisite_not_measured": ("Пререквизит не измерен на итоговых формах", "Пререквизит қорытынды формаларда өлшенбеген"),
    "objective_not_measured": ("Цель не измерена: нет заданий на формах", "Мақсат өлшенбеген: формаларда тапсырма жоқ"),
    "objective_unverified_mapping": ("Есть только предложенные связи заданий с целью", "Тапсырмалардың мақсатпен тек ұсынылған байланыстары бар"),
    "no_source_for_objective": ("Нет подтверждённого фрагмента пособия для цели", "Мақсат үшін құралдың расталған үзіндісі жоқ"),
    "no_plan_hours": ("Тема отсутствует в учебном плане", "Тақырып оқу жоспарында жоқ"),
    "no_decision": ("По теме ещё нет решения", "Тақырып бойынша әлі шешім жоқ"),
    "no_follow_up": ("Повторная проверка решения ещё не проводилась", "Шешімді қайта тексеру әлі жүргізілмеген"),
    "topic_insufficient_data": ("Данных по теме недостаточно для вывода", "Тақырып бойынша қорытынды үшін дерек жеткіліксіз"),
}


def _gap(code: str, near: str) -> dict:
    ru, kz = GAP_TEXT[code]
    return {"id": f"gap:{code}:{near}", "kind": "gap", "label_ru": ru, "label_kz": kz, "status": "gap", "code": code,
            "metrics": {}, "open": None}


def build(session: Session, org_id: str, dataset_id: str, topic_id: str, f: an.Filters, user_id: str | None) -> dict:
    ev = an.topic_evidence(session, org_id, dataset_id, topic_id, f, user_id)
    res, ctx = ev["result"], ev["context"]
    aid = ctx["analysis_id"]
    nodes: list[dict] = []
    edges: list[dict] = []

    def edge(a: str, b: str, kind: str) -> None:
        edges.append({"from": a, "to": b, "kind": kind})

    t = res["topic"]
    tnode = f"topic:{t['topic_id']}"
    nodes.append({"id": tnode, "kind": "topic", "label_ru": f"{t['code']} {t['title_ru']}", "label_kz": f"{t['code']} {t['title_kz']}",
                  "status": res["status"], "metrics": {"mean": (res["summary"] or {}).get("mean"),
                                                       "n_learners": (res["summary"] or {}).get("n_learners"),
                                                       "n_classes": (res["summary"] or {}).get("n_classes")},
                  "open": {"type": "calculation", "analysis_id": aid, "path": "summary", "rules": res["rules"]}})
    if res["status"] in ("insufficient_data",):
        g = _gap("topic_insufficient_data", t["code"])
        nodes.append(g)
        edge(tnode, g["id"], "gap")

    for i, pr in enumerate(res["prerequisites"]):
        nid = f"prereq:{pr['objective_id']}"
        nodes.append({"id": nid, "kind": "prerequisite", "label_ru": f"{pr['code']} {pr['text_ru']}", "label_kz": f"{pr['code']} {pr['text_kz']}",
                      "status": "measured" if pr["score"] else "not_measured", "metrics": {"mean": (pr["score"] or {}).get("mean")},
                      "open": {"type": "calculation", "analysis_id": aid, "path": f"prerequisites[{i}]"}})
        target = next((o for o in res["objectives"] if o["code"] == pr["target_code"]), None)
        edge(nid, f"objective:{target['objective_id']}" if target else tnode, "prerequisite_of")
        if not pr["score"]:
            g = _gap("prerequisite_not_measured", pr["code"])
            nodes.append(g)
            edge(nid, g["id"], "gap")

    sources_by_obj: dict[str, list[dict]] = {}
    for s in res["sources"]:
        sources_by_obj.setdefault(s["objective_code"], []).append(s)
    item_by_code = {it["code"]: it for it in res["items"]}
    for i, o in enumerate(res["objectives"]):
        nid = f"objective:{o['objective_id']}"
        nodes.append({"id": nid, "kind": "objective", "label_ru": f"{o['code']} {o['text_ru']}", "label_kz": f"{o['code']} {o['text_kz']}",
                      "status": o["status"], "metrics": {"mean": (o["score"] or {}).get("mean"), "n_items_confirmed": o["n_items_confirmed"],
                                                         "n_items_proposed": o["n_items_proposed"]},
                      "open": {"type": "calculation", "analysis_id": aid, "path": f"objectives[{i}]"}})
        edge(tnode, nid, "has_objective")
        if o["status"] == "not_measured":
            g = _gap("objective_not_measured", o["code"])
            nodes.append(g)
            edge(nid, g["id"], "gap")
        elif o["status"] == "unverified_mapping":
            g = _gap("objective_unverified_mapping", o["code"])
            nodes.append(g)
            edge(nid, g["id"], "gap")
        srcs = [s for s in sources_by_obj.get(o["code"], []) if s["status"] == "confirmed"] or sources_by_obj.get(o["code"], [])
        for s in srcs[:4]:
            sid = f"source:{s['source_id']}"
            if not any(n["id"] == sid for n in nodes):
                page = s["page_printed"] or s["page_physical"]
                nodes.append({"id": sid, "kind": "source", "label_ru": f"{s['edition_title']} · с. {page}" if page else s["edition_title"],
                              "label_kz": f"{s['edition_title']} · б. {page}" if page else s["edition_title"],
                              "status": s["status"], "metrics": {"edition_code": s["edition_code"], "page": page},
                              "excerpt": s["excerpt"], "open": {"type": "source", "source_id": s["source_id"]}})
            edge(nid, sid, "taught_in")
        if not srcs:
            g = _gap("no_source_for_objective", o["code"])
            nodes.append(g)
            edge(nid, g["id"], "gap")

    for i, it in enumerate(res["items"]):
        nid = f"item:{it['item_id']}"
        nodes.append({"id": nid, "kind": "item", "label_ru": f"{it['code']}: {it['stem_ru'][:80]}", "label_kz": f"{it['code']}: {it['stem_kz'][:80]}",
                      "status": "measured", "metrics": {"p_correct": it["p_correct"], "n_answered": it["n_answered"], "omit_rate": it["omit_rate"]},
                      "open": {"type": "item", "analysis_id": aid, "path": f"items[{i}]"}})
        for ol in it["objectives"]:
            if ol["status"] == "confirmed" or f.mapping_status == "include_proposed":
                edge(nid, f"objective:{ol['objective_id']}", "measures")

    for i, mc in enumerate(res["misconceptions"]):
        nid = f"misconception:{mc['code']}"
        nodes.append({"id": nid, "kind": "misconception", "label_ru": mc["label_ru"], "label_kz": mc["label_kz"], "status": "hypothesis",
                      "metrics": {"n_learners": mc["n_learners"], "share_of_learners": mc["share_of_learners"]},
                      "check_ru": mc["diagnostic_check_ru"],
                      "open": {"type": "calculation", "analysis_id": aid, "path": f"misconceptions[{i}]"}})
        for code in mc["items"]:
            if code in item_by_code:
                edge(f"item:{item_by_code[code]['item_id']}", nid, "signals")

    # plan hours
    plan = session.scalar(select(m.TeachingPlan).where(m.TeachingPlan.dataset_id == dataset_id, m.TeachingPlan.org_id == org_id)
                          .order_by(m.TeachingPlan.created_at.desc(), m.TeachingPlan.version.desc()))
    row = None
    if plan is not None:
        row = session.scalar(select(m.PlanTopicHours).where(m.PlanTopicHours.plan_id == plan.id, m.PlanTopicHours.topic_id == topic_id))
    if row is not None:
        hid = f"hours:{row.id}"
        nodes.append({"id": hid, "kind": "hours", "label_ru": f"{row.planned_hours} ч в плане «{plan.name}»",
                      "label_kz": f"«{plan.name}» жоспарында {row.planned_hours} сағ", "status": plan.status,
                      "metrics": {"planned_hours": row.planned_hours, "elapsed_hours": row.elapsed_hours, "min_hours": row.min_hours,
                                  "max_hours": row.max_hours},
                      "open": {"type": "plan", "plan_id": plan.id, "plan_version": plan.version}})
        edge(tnode, hid, "allocated")
        anchor = hid
    else:
        g = _gap("no_plan_hours", t["code"])
        nodes.append(g)
        edge(tnode, g["id"], "gap")
        anchor = tnode

    decisions = list(session.scalars(select(m.Decision).where(m.Decision.org_id == org_id, m.Decision.dataset_id == dataset_id,
                                                               m.Decision.topic_id == topic_id, m.Decision.status != "superseded")
                                     .order_by(m.Decision.created_at)))
    if not decisions:
        g = _gap("no_decision", t["code"])
        nodes.append(g)
        edge(anchor, g["id"], "gap")
    for d in decisions:
        did = f"decision:{d.id}"
        nodes.append({"id": did, "kind": "decision", "label_ru": d.action[:90], "label_kz": d.action[:90], "status": d.status,
                      "metrics": {"version": d.version, "dataset_version": d.dataset_version, "outcome_status": d.outcome_status},
                      "open": {"type": "decision", "decision_id": d.id}})
        edge(anchor, did, "addressed_by")
        fus = list(session.scalars(select(m.FollowUp).where(m.FollowUp.decision_id == d.id).order_by(m.FollowUp.created_at)))
        if not fus:
            g = _gap("no_follow_up", d.id[:8])
            nodes.append(g)
            edge(did, g["id"], "gap")
        for fu in fus:
            fid = f"followup:{fu.id}"
            nodes.append({"id": fid, "kind": "followup", "label_ru": fu.status, "label_kz": fu.status, "status": fu.status,
                          "metrics": {}, "open": {"type": "calculation", "analysis_id": fu.analysis_id, "path": "status"}})
            edge(did, fid, "checked_by")

    path = _weak_path(res, nodes, edges)
    return {"context": ctx, "result": {
        "topic": t, "status": res["status"], "nodes": nodes, "edges": edges, "path": path,
        "gaps": [n for n in nodes if n["kind"] == "gap"],
        "note_ru": "Каждый узел открывается: расчёт (сохранённый анализ и путь в нём), страница пособия, строки ответов, "
                   "план или решение. Ошибки учеников — гипотезы для проверки, а не диагноз.",
    }}


def _weak_path(res: dict, nodes: list[dict], edges: list[dict]) -> list[str]:
    """Deterministic chain for the weakest measured objective (prerequisite → objective → item → misconception →
    source → hours → decision → follow-up), including gap nodes where a link is missing."""
    ids = {n["id"] for n in nodes}
    measured = [o for o in res["objectives"] if o["score"]]
    obj = min(measured, key=lambda o: o["score"]["mean"]) if measured else (res["objectives"][0] if res["objectives"] else None)
    path = [f"topic:{res['topic']['topic_id']}"]
    if obj is None:
        return path
    oid = f"objective:{obj['objective_id']}"
    pre = [e["from"] for e in edges if e["to"] == oid and e["kind"] == "prerequisite_of"]
    path += pre[:1] + [oid]
    items = [e["from"] for e in edges if e["to"] == oid and e["kind"] == "measures"]
    pc = {n["id"]: n["metrics"].get("p_correct") for n in nodes if n["kind"] == "item"}
    items.sort(key=lambda i: (pc.get(i) is None, pc.get(i) or 0))
    if items:
        path.append(items[0])
        mis = [e["to"] for e in edges if e["from"] == items[0] and e["kind"] == "signals"]
        path += mis[:1]
    after_obj = [e["to"] for e in edges if e["from"] == oid and e["kind"] in ("taught_in", "gap")]
    path += after_obj[:1]
    def first(src: str, kinds: tuple[str, ...], last: bool = False) -> str | None:
        hits = [e["to"] for e in edges if e["from"] == src and e["kind"] in kinds]
        return (hits[-1] if last else hits[0]) if hits else None

    hours = first(path[0], ("allocated",)) or next((e["to"] for e in edges if e["from"] == path[0]
                                                     and e["to"].startswith("gap:no_plan_hours")), None)
    if hours:
        path.append(hours)
    anchor = hours if hours and hours.startswith("hours:") else path[0]
    dec = first(anchor, ("addressed_by",), last=True) or next((e["to"] for e in edges if e["from"] == anchor
                                                               and e["to"].startswith("gap:no_decision")), None)
    if dec:
        path.append(dec)
        if dec.startswith("decision:"):
            fu = first(dec, ("checked_by", "gap"), last=True)
            if fu:
                path.append(fu)
    return [p for p in path if p in ids]


def validate_selection(graph: dict, node_ids: list[str]) -> dict:
    """A model (or a user) may only reference nodes that exist in this graph."""
    known = {n["id"] for n in graph["result"]["nodes"]}
    unknown = [i for i in node_ids if i not in known]
    if unknown:
        raise ApiError("unknown_evidence_ids", "Ссылки на несуществующие узлы графа отклонены", 422, {"unknown": unknown[:20]})
    adj = {(e["from"], e["to"]) for e in graph["result"]["edges"]}
    broken = [[a, b] for a, b in zip(node_ids, node_ids[1:], strict=False) if (a, b) not in adj and (b, a) not in adj]
    return {"status": "passed", "node_ids": node_ids, "non_adjacent_steps": broken}
