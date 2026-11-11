"""Agent council on a topic: orchestrator + Measurement Analyst + Curriculum & Materials Expert + Critic/Auditor.

Public audit trail only (no chain-of-thought): which typed tool was called with which input, which stored
analysis / data version it produced, which facts were extracted, what each role claimed (with evidence IDs),
where roles agree or disagree and which claims the Critic weakened or blocked.

Guarantees enforced by the server, whatever produced the role statements (template or live model):
* evidence IDs must exist among the extracted facts or the topic's evidence-graph nodes, otherwise the claim is
  blocked (``unknown_evidence_ids``);
* every number in a claim must match an extracted fact, otherwise the claim is blocked (``unverified_numbers``);
* comparisons are never causal; a raw difference whose sign contradicts the adjusted one is blocked;
* misconceptions stay hypotheses. The Critic is a deterministic rule-based auditor, so its verdicts are
  reproducible and do not depend on a model.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from ..errors import ApiError
from ..services import analysis as an
from ..services import graph as gr
from ..services.messages import COMPARABILITY
from . import verify
from .tasks import _live_or_none, _pct, _pp, _record, generation_payload

COUNCIL_VERSION = "council-v1"

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {"claims": {"type": "array", "items": {
        "type": "object",
        "properties": {"kind": {"type": "string", "enum": ["level", "raw_comparison", "adjusted_comparison", "misconception",
                                                           "materials", "prerequisite", "hours", "action"]},
                       "text": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}},
        "required": ["kind", "text", "evidence_ids"], "additionalProperties": False}}},
    "required": ["claims"], "additionalProperties": False,
}

ROLES = {
    "orchestrator": ("Оркестратор", "Үйлестіруші"),
    "analyst": ("Аналитик измерений", "Өлшеу талдаушысы"),
    "curriculum": ("Эксперт по программе и материалам", "Бағдарлама және материалдар сарапшысы"),
    "critic": ("Критик-аудитор", "Сыншы-аудитор"),
}

CRITIC_TEXT = {
    "unknown_evidence_ids": "Ссылки на несуществующие доказательства",
    "unverified_numbers": "В утверждении есть числа, которых нет в фактах",
    "confounded_by_entry_level": "Сырая разница противоречит скорректированной: группы различаются по входному уровню, вывод по ней запрещён",
    "raw_ignores_entry_level": "Сырая разница не учитывает входной уровень групп",
    "association_not_causal": "Наблюдательные данные: это связь, а не эффект пособия",
    "ci_includes_zero": "Доверительный интервал включает ноль",
    "not_comparable": "Группы несопоставимы — сравнение не интерпретируется",
    "hypothesis_requires_check": "Выбор дистрактора — гипотеза, нужна диагностическая проверка",
    "few_classes": "Мало классов для устойчивого вывода",
    "unconfirmed_link": "Связь материала с целью не подтверждена методистом",
    "no_evidence": "Утверждение без доказательств",
}


def _fact(facts: dict, fid: str, label: str, value, provenance: dict) -> None:
    facts[fid] = {"id": fid, "label_ru": label, "value": value, "provenance": provenance}


def run(session: Session, p, dataset_id: str, topic_id: str, edition_a_id: str | None = None,
        edition_b_id: str | None = None, lang: str = "ru") -> dict:
    f = an.Filters()
    steps: list[dict] = []
    facts: dict[str, dict] = {}

    def step(role: str, action: str, **kw) -> None:
        steps.append({"n": len(steps) + 1, "role": role, "role_label": ROLES[role][0 if lang == "ru" else 1], "action": action, **kw})

    meta = an.load_meta(session, p.org_id, dataset_id)
    ds = meta.dataset
    step("orchestrator", "plan", tools=["get_topic_evidence", "get_evidence_graph", "compare_editions", "get_plan_hours"],
         note_ru="Порядок фиксирован: сначала измерение, затем материалы и план, затем аудит.")

    # 1) typed tools -------------------------------------------------------------------------------------
    g = gr.build(session, p.org_id, dataset_id, topic_id, f, p.user_id)
    ev = an.get_run(session, p.org_id, g["context"]["analysis_id"])
    tr, tctx = ev["result"], ev["context"]
    aid = tctx["analysis_id"]
    prov = {"analysis_id": aid, "dataset_version": tctx["dataset_version"], "method_version": tctx["method_version"]}
    s = tr["summary"] or {}
    _fact(facts, "fact:topic_level", "Средняя доля баллов по теме", {"mean": s.get("mean"), "n_learners": s.get("n_learners"),
          "n_classes": s.get("n_classes")}, {**prov, "path": "summary"})
    for i, o in enumerate(tr["objectives"]):
        if o["score"]:
            _fact(facts, f"fact:objective:{o['code']}", f"Доля баллов по цели {o['code']}", {"mean": o["score"]["mean"]},
                  {**prov, "path": f"objectives[{i}].score"})
    for i, mc in enumerate(tr["misconceptions"][:5]):
        _fact(facts, f"fact:misconception:{mc['code']}", f"Выбор дистрактора «{mc['label_ru']}»",
              {"n_learners": mc["n_learners"], "share": mc["share_of_learners"]}, {**prov, "path": f"misconceptions[{i}]"})
    for i, it in enumerate(tr["items"]):
        _fact(facts, f"fact:item:{it['code']}", f"Доля верных ответов на {it['code']}", {"p_correct": it["p_correct"],
              "n_answered": it["n_answered"]}, {**prov, "path": f"items[{i}]"})
    step("analyst", "tool", tool="get_topic_evidence", input={"dataset_id": dataset_id, "topic_id": topic_id, "filters": f.model_dump()},
         output_ref=prov, facts=[k for k in facts])
    nodes = {n["id"]: n for n in g["result"]["nodes"]}
    step("curriculum", "tool", tool="get_evidence_graph", input={"topic_id": topic_id},
         output_ref={**prov, "nodes": len(nodes), "gaps": len(g["result"]["gaps"])},
         facts=[n for n in nodes if n.startswith(("source:", "hours:", "gap:"))][:12])

    hours = next((n for n in nodes.values() if n["kind"] == "hours"), None)
    if hours:
        hm = dict(hours["metrics"])
        if hm.get("max_hours") is not None:
            hm["room_to_max"] = hm["max_hours"] - hm["planned_hours"]
        _fact(facts, "fact:hours", "Часы темы в плане", hm, {"plan_id": hours["open"]["plan_id"]})
        step("curriculum", "tool", tool="get_plan_hours", input={"topic_id": topic_id}, output_ref={"plan_id": hours["open"]["plan_id"]},
             facts=["fact:hours"])

    comp = None
    eds = [e for e in meta.editions.values() if any(v == e.id for (_, t), v in meta.cohort_edition.items() if t == topic_id)]
    eds.sort(key=lambda e: e.code)
    a_id = edition_a_id or (eds[0].id if len(eds) > 1 else None)
    b_id = edition_b_id or (eds[1].id if len(eds) > 1 else None)
    if a_id and b_id:
        try:
            cr = an.comparison(session, p.org_id, an.ComparisonRequest(dataset_id=dataset_id, topic_id=topic_id, edition_a_id=a_id,
                                                                      edition_b_id=b_id, filters=f), p.user_id)
            comp, cctx = cr["result"], cr["context"]
            cprov = {"analysis_id": cctx["analysis_id"], "dataset_version": cctx["dataset_version"], "method_version": cctx["method_version"]}
            _fact(facts, "fact:cmp_raw", "Сырая разница (B − A)", {"difference": comp["raw"]["difference"], "a": comp["raw"]["a"]["mean"],
                  "b": comp["raw"]["b"]["mean"]}, {**cprov, "path": "raw"})
            _fact(facts, "fact:cmp_adjusted", "Разница после стандартизации по входному уровню (B − A)",
                  {"difference": comp["adjusted"]["difference"], "a": comp["adjusted"]["a"], "b": comp["adjusted"]["b"]}, {**cprov, "path": "adjusted"})
            _fact(facts, "fact:cmp_ci", "95% ДИ скорректированной разницы", comp["uncertainty"]["adjusted_difference_ci"],
                  {**cprov, "path": "uncertainty.adjusted_difference_ci"})
            _fact(facts, "fact:cmp_status", "Сопоставимость и уровень вывода", {"status": comp["status"], "inference_level": comp["inference_level"],
                  "reasons": [r["code"] for r in comp["reasons"]]}, {**cprov, "path": "status"})
            step("analyst", "tool", tool="compare_editions", input={"edition_a": comp["editions"]["a"]["code"], "edition_b": comp["editions"]["b"]["code"]},
                 output_ref=cprov, facts=["fact:cmp_raw", "fact:cmp_adjusted", "fact:cmp_ci", "fact:cmp_status"])
        except ApiError as exc:
            step("analyst", "tool", tool="compare_editions", input={"edition_a_id": a_id, "edition_b_id": b_id}, blocked=exc.code)
    else:
        step("analyst", "tool", tool="compare_editions", input={}, blocked="fewer_than_two_editions_for_topic")

    synthetic = bool(tctx.get("is_synthetic", ds.is_synthetic))
    # only verbatim mathematical content (fractions such as "3 1/4") from items and pages may appear besides facts
    context_text = " ".join(verify.FRACTION_RE.findall(" ".join([*(n.get("excerpt", "") for n in nodes.values()),
                                                                   *(it["stem_ru"] for it in tr["items"])])))

    # 2) role statements (live model when allowed, otherwise deterministic templates) ---------------------
    def role_claims(role: str, template: list[dict], task_hint: str) -> tuple[list[dict], dict]:
        data, lm = _live_or_none(
            f"council_{role}",
            "Ты — " + ROLES[role][0].lower() + " в методическом консилиуме. Используй только переданные факты; "
            "числа — только из фактов; evidence_ids — только из allowed_evidence_ids. " + task_hint
            + " Пиши на " + ("русском" if lang == "ru" else "казахском") + " языке, кратко. Ответ строго JSON.",
            {"facts": list(facts.values()), "allowed_evidence_ids": sorted(known_ids), "lang": lang}, CLAIMS_SCHEMA, synthetic=synthetic)
        if data is not None and data.get("claims"):
            return [{**c, "role": role} for c in data["claims"][:6]], {"mode": lm["mode"], "provider": lm["provider"], "model": lm["model"]}
        return template, {"mode": "template", "fallback_reason": lm.get("fallback_reason")}

    weakest = min((o for o in tr["objectives"] if o["score"]), key=lambda o: o["score"]["mean"], default=None)
    top = tr["misconceptions"][0] if tr["misconceptions"] else None
    if weakest:  # prefer the hypothesis signalled by items of the weakest objective
        w_items = {it["code"] for it in tr["items"] if any(ol["objective_id"] == weakest["objective_id"] for ol in it["objectives"])}
        top = next((mc for mc in tr["misconceptions"] if set(mc["items"]) & w_items), top)
    analyst_t: list[dict] = []
    if s.get("mean") is not None:
        txt = f"Тема {tr['topic']['code']}: средняя доля баллов {_pct(s['mean'])} ({s['n_learners']} уч., {s['n_classes']} кл.)"
        ids = ["fact:topic_level", f"topic:{topic_id}"]
        if weakest:
            txt += f"; слабее всего цель {weakest['code']} — {_pct(weakest['score']['mean'])}"
            ids += [f"fact:objective:{weakest['code']}", f"objective:{weakest['objective_id']}"]
        analyst_t.append({"role": "analyst", "kind": "level", "text": txt + ".", "evidence_ids": ids})
    if comp is not None:
        ea, eb = comp["editions"]["a"]["code"], comp["editions"]["b"]["code"]
        analyst_t.append({"role": "analyst", "kind": "raw_comparison", "evidence_ids": ["fact:cmp_raw"],
                          "text": f"Без поправки {eb} − {ea} = {_pp(comp['raw']['difference'])}"})
        ci = comp["uncertainty"]["adjusted_difference_ci"]
        analyst_t.append({"role": "analyst", "kind": "adjusted_comparison", "evidence_ids": ["fact:cmp_adjusted", "fact:cmp_ci", "fact:cmp_status"],
                          "text": f"После стандартизации по входному уровню {eb} − {ea} = {_pp(comp['adjusted']['difference'])}"
                                  + (f" (95% ДИ от {_pp(ci['low'])} до {_pp(ci['high'])})" if ci else "")})
    if top:
        mis_node = f"misconception:{top['code']}"
        item_nodes = [f"item:{it['item_id']}" for it in tr["items"] if it["code"] in top["items"]][:2]
        analyst_t.append({"role": "analyst", "kind": "misconception", "evidence_ids": [f"fact:misconception:{top['code']}", mis_node, *item_nodes],
                          "text": f"Дистрактор «{top['label_ru']}» выбрали {top['n_learners']} уч. ({_pct(top['share_of_learners'])}) "
                                  f"в заданиях {', '.join(top['items'][:3])}."})
    curriculum_t: list[dict] = []
    if weakest:
        srcs = [e["to"] for e in g["result"]["edges"] if e["from"] == f"objective:{weakest['objective_id']}" and e["kind"] == "taught_in"]
        if srcs:
            curriculum_t.append({"role": "curriculum", "kind": "materials", "evidence_ids": srcs[:3] + [f"objective:{weakest['objective_id']}"],
                                 "text": f"Цель {weakest['code']} раскрыта в: " + "; ".join(dict.fromkeys(nodes[x]["label_ru"] for x in srcs[:3])) + "."})
    for pr in tr["prerequisites"][:1]:
        curriculum_t.append({"role": "curriculum", "kind": "prerequisite", "evidence_ids": [f"prereq:{pr['objective_id']}"],
                             "text": f"Пререквизит {pr['code']} ({pr['topic_code']}) "
                                     + (f"измерен: {_pct(pr['score']['mean'])}." if pr["score"] else "на итоговых формах не измерен.")})
        if pr["score"]:
            _fact(facts, f"fact:prereq:{pr['code']}", f"Пререквизит {pr['code']}", {"mean": pr["score"]["mean"]}, {**prov, "path": "prerequisites"})
            curriculum_t[-1]["evidence_ids"].append(f"fact:prereq:{pr['code']}")
    if hours:
        h = hours["metrics"]
        room = (h["max_hours"] - h["planned_hours"]) if h.get("max_hours") is not None else None
        curriculum_t.append({"role": "curriculum", "kind": "hours", "evidence_ids": ["fact:hours", hours["id"]],
                             "text": f"В плане {h['planned_hours']} ч" + (f", допустимо до {h['max_hours']} ч" if h.get("max_hours") is not None else "") + "."})
        if weakest:
            curriculum_t.append({"role": "curriculum", "kind": "action", "evidence_ids": [f"objective:{weakest['objective_id']}", hours["id"]]
                                 + ([f"misconception:{top['code']}"] if top else []),
                                 "text": f"Перераспределить часы в пределах плана на цель {weakest['code']}"
                                         + (f" (запас по плану — {room} ч)" if room else "")
                                         + (f"; начать с диагностического задания на гипотезу «{top['label_ru']}»" if top else "") + "."})
    known_ids = set(facts) | set(nodes)
    allowed_values = {k: v["value"] for k, v in facts.items()}
    allowed_values["_pages"] = [int(n["metrics"]["page"]) for n in nodes.values()
                                if n["kind"] == "source" and str(n["metrics"].get("page") or "").isdigit()]
    allowed_values["_ci_level"] = 95
    analyst, am = role_claims("analyst", analyst_t, "Опиши уровень темы, сравнение изданий (если есть) и частую ошибку.")
    curriculum, cm = role_claims("curriculum", curriculum_t, "Опиши материалы по слабой цели, пререквизиты, часы и действие.")
    for c in analyst:
        step("analyst", "statement", claim=c, mode=am["mode"])
    for c in curriculum:
        step("curriculum", "statement", claim=c, mode=cm["mode"])

    # 3) critic ---------------------------------------------------------------------------------------
    claims = analyst + curriculum
    verdicts = []
    for i, c in enumerate(claims):
        c["id"] = f"C{i + 1}"
        reasons: list[str] = []
        verdict = "accepted"
        unknown = [e for e in c["evidence_ids"] if e not in known_ids]
        num = verify.check_numbers(c["text"], allowed_values, context_text)
        if not c["evidence_ids"]:
            verdict, reasons = "blocked", ["no_evidence"]
        elif unknown:
            verdict, reasons = "blocked", ["unknown_evidence_ids"]
        elif num["status"] != "passed":
            verdict, reasons = "blocked", ["unverified_numbers"]
        elif c["kind"] == "raw_comparison" and comp is not None:
            rd, ad = comp["raw"]["difference"], comp["adjusted"]["difference"]
            if rd is not None and ad is not None and rd * ad < 0:
                verdict, reasons = "blocked", ["confounded_by_entry_level"]
            else:
                verdict, reasons = "weakened", ["raw_ignores_entry_level"]
        elif c["kind"] == "adjusted_comparison" and comp is not None:
            ci = comp["uncertainty"]["adjusted_difference_ci"]
            if comp["status"] == "not_comparable":
                verdict, reasons = "blocked", ["not_comparable"]
            else:
                verdict, reasons = "weakened", ["association_not_causal"] + (["ci_includes_zero"] if ci and ci["low"] <= 0 <= ci["high"] else [])
        elif c["kind"] == "misconception":
            verdict, reasons = "weakened", ["hypothesis_requires_check"]
        elif c["kind"] == "level" and (s.get("n_classes") or 0) < an.MIN_CLASSES_TOPIC:
            verdict, reasons = "weakened", ["few_classes"]
        elif c["kind"] == "materials" and any(nodes.get(e, {}).get("status") not in (None, "confirmed") for e in c["evidence_ids"] if e.startswith("source:")):
            verdict, reasons = "weakened", ["unconfirmed_link"]
        v = {"claim_id": c["id"], "role": c["role"], "kind": c["kind"], "verdict": verdict, "reasons": reasons,
             "reasons_ru": [CRITIC_TEXT[r] for r in reasons], "numbers": num, "unknown_evidence_ids": unknown}
        verdicts.append(v)
        step("critic", "critique", **{("claim_role" if k == "role" else k): val for k, val in v.items()})

    agreements, disagreements = [], []
    by_kind = {c["kind"]: c for c in claims}
    if "level" in by_kind and "action" in by_kind and weakest and f"objective:{weakest['objective_id']}" in by_kind["action"]["evidence_ids"] \
            and f"objective:{weakest['objective_id']}" in by_kind["level"]["evidence_ids"]:
        agreements.append({"claims": [by_kind["level"]["id"], by_kind["action"]["id"]],
                           "text_ru": f"Аналитик и эксперт указывают на одну цель — {weakest['code']}."})
    for v in verdicts:
        if v["verdict"] != "accepted":
            disagreements.append({"claim_id": v["claim_id"], "between": [v["role"], "critic"], "verdict": v["verdict"],
                                  "text_ru": "; ".join(v["reasons_ru"])})

    # 4) final card ------------------------------------------------------------------------------------
    ok = {v["claim_id"]: v for v in verdicts if v["verdict"] != "blocked"}
    kept = [c for c in claims if c["id"] in ok]
    claim_parts = [c["text"] for c in kept if c["kind"] in ("level", "misconception")]
    adj = next((c for c in kept if c["kind"] == "adjusted_comparison"), None)
    if adj:
        claim_parts.append(adj["text"] + " — связь в сопоставимых группах, не эффект пособия.")
    action = next((c["text"] for c in kept if c["kind"] == "action"), "Собрать недостающие данные (см. пробелы графа).")
    limitations = list(dict.fromkeys(r for v in verdicts if v["verdict"] != "accepted" for r in v["reasons_ru"]))
    if comp is not None:
        limitations.append(f"Статус сравнения: {COMPARABILITY[comp['status']][0].lower()}.")
    limitations += [n["label_ru"] for n in g["result"]["gaps"]][:3]
    verification = ("Повторная проверка на общих заданиях той же шкалы со стандартизацией по входному уровню"
                    + (f"; диагностическое задание: {top['diagnostic_check_ru'].rstrip('.')}" if top else "") + ".")
    card = {"claim": " ".join(claim_parts) or "Данных недостаточно для вывода.",
            "evidence_ids": list(dict.fromkeys(e for c in kept for e in c["evidence_ids"])),
            "limitations": limitations, "recommended_action": action, "verification_plan": verification}
    final_num = verify.check_numbers(card["claim"] + " " + card["recommended_action"], allowed_values, context_text)
    bad_ids = [e for e in card["evidence_ids"] if e not in known_ids]
    if bad_ids or final_num["status"] != "passed":  # never show an unverifiable final card
        raise ApiError("council_verification_failed", "Итог консилиума не прошёл проверку", 500,
                       {"unknown": bad_ids, "numbers": final_num["unverified_numbers"]})
    step("orchestrator", "final", card_evidence=len(card["evidence_ids"]), verification={"numbers": final_num, "evidence_ids": "passed"})
    highlight = next((v for v in verdicts if v["verdict"] == "blocked"), None) or next((v for v in verdicts if v["verdict"] == "weakened"), None)
    mode = "live_model" if "live_model" in (am["mode"], cm["mode"]) else ("recorded_demo" if "recorded_demo" in (am["mode"], cm["mode"]) else "template")
    out = {"council_version": COUNCIL_VERSION, "topic": tr["topic"], "dataset_version": tctx["dataset_version"],
           "roles": {k: v[0 if lang == "ru" else 1] for k, v in ROLES.items()},
           "role_modes": {"analyst": am, "curriculum": cm, "critic": {"mode": "rules"}},
           "steps": steps, "facts": list(facts.values()), "claims": claims, "verdicts": verdicts,
           "agreements": agreements, "disagreements": disagreements, "highlight": highlight, "final": card,
           "note_ru": "Журнал показывает вызовы инструментов, факты и утверждения ролей; скрытые рассуждения модели не "
                      "сохраняются и не показываются. Критик — детерминированный аудитор правил."}
    gen = _record(session, p.org_id, "council", mode, {"dataset_id": dataset_id, "topic_id": topic_id, "analysis_id": aid,
                                                         "dataset_version": tctx["dataset_version"]},
                  out, [e for e in card["evidence_ids"] if e.startswith("source:")],
                  {"numbers": final_num, "evidence_ids": {"status": "passed", "checked": len(card["evidence_ids"])}},
                  model=am.get("model") or cm.get("model"), provider=am.get("provider") or cm.get("provider") or "none",
                  fallback_reason=am.get("fallback_reason"), template_version=COUNCIL_VERSION)
    return generation_payload(gen, lang)
