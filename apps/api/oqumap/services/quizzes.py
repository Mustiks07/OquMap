"""Diagnostic quiz generator (3–7 items) with automated checks and teacher review.

* Template mode: parametric item families. The key is computed exactly (``fractions.Fraction``) and every
  distractor is produced by *applying the misconception rule* to the same numbers, so each wrong option has a
  mechanical, checkable rationale. Families are chosen by the misconception hypotheses that the topic analysis
  actually observed, and every item links back to evidence (graph node IDs of the signalling items and the
  misconception).
* Only template families are implemented; for hypotheses without a family generation refuses honestly
  (``no_template_family``). Items whose numbers a teacher changes lose the recomputed key and need the
  teacher's explicit key confirmation before approval.
* Review: draft → edited (each teacher edit creates a new version) → approved | rejected. Approval requires
  every blocking check to pass. Quizzes are formative only: ``use = diagnostic_only``; responses imported back
  are summarised per item and per hypothesis and are never written into grades or the outcome assessments.
"""

from __future__ import annotations

import csv
import io
import random
import re
from datetime import UTC, datetime
from fractions import Fraction
from math import gcd

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..errors import ApiError, not_found
from . import analysis as an
from . import graph as gr
from .common import audit, sha256_bytes
from .quiz_families import EXTRA_FAMILIES, FAMILY_TITLES

GENERATOR_VERSION = "quiz-gen-v1"
DIFFICULTY = ("easy", "medium", "hard")


def _fs(x: Fraction) -> str:
    """Fraction as a school answer: mixed number when > 1."""
    if x.denominator == 1:
        return str(x.numerator)
    if abs(x) > 1:
        w = int(x.numerator / x.denominator)
        r = abs(x - w)
        return f"{w} {r.numerator}/{r.denominator}"
    return f"{x.numerator}/{x.denominator}"


def _lcm(a: int, b: int) -> int:
    return a * b // gcd(a, b)


def _opt(text: str, correct: bool, misconception: str | None, ru: str, kz: str) -> dict:
    return {"text": text, "correct": correct, "misconception": misconception, "rationale_ru": ru, "rationale_kz": kz}


# ---------------------------------------------------------------------------
# Item families: params → (stem, options with rationales, key value) ; all arithmetic exact
# ---------------------------------------------------------------------------


def fam_frac_add(rng: random.Random, level: int) -> dict:
    dens = [(2, 3), (3, 4), (2, 5), (4, 6), (3, 5), (4, 5), (5, 6), (3, 8)][level * 2 + rng.randint(0, 1)]
    b, d = dens
    a = rng.choice([x for x in range(1, b) if gcd(x, b) == 1])  # stems use fractions in lowest terms
    c = rng.choice([x for x in range(1, d) if gcd(x, d) == 1])
    return {"family": "frac_add", "params": {"a": a, "b": b, "c": c, "d": d}}


def render_frac_add(p: dict) -> dict:
    a, b, c, d = p["a"], p["b"], p["c"], p["d"]
    key = Fraction(a, b) + Fraction(c, d)
    L = _lcm(b, d)
    opts = [
        _opt(_fs(key), True, None, "Верно: привели к общему знаменателю и сложили числители.", "Дұрыс: ортақ бөлімге келтіріп, алымдарын қосты."),
        _opt(f"{a + c}/{b + d}", False, "add_across", f"Сложил числители ({a}+{c}) и знаменатели ({b}+{d}) по отдельности.",
             f"Алымдарын ({a}+{c}) және бөлімдерін ({b}+{d}) бөлек қосты."),
        _opt(f"{a + c}/{L}", False, "numerators_not_scaled", f"Нашёл общий знаменатель {L}, но не домножил числители.",
             f"Ортақ бөлім {L} тапты, бірақ алымдарын көбейтпеді."),
        _opt(_fs(Fraction(a * c, b * d)), False, "multiplied_instead", "Перемножил дроби вместо сложения.", "Қосудың орнына бөлшектерді көбейтті."),
    ]
    return {"stem_ru": f"Вычислите: {a}/{b} + {c}/{d}.", "stem_kz": f"Есептеңіз: {a}/{b} + {c}/{d}.", "options": opts, "key_value": key,
            "rubric_ru": "1 балл за верный ответ; выбор дистрактора указывает на проверяемую гипотезу об ошибке.",
            "rubric_kz": "Дұрыс жауапқа 1 ұпай; дистрактор таңдау қате туралы тексерілетін гипотезаны көрсетеді."}


def fam_mixed_sub(rng: random.Random, level: int) -> dict:
    den = [4, 5, 6][level]
    reduced = [x for x in range(1, den) if gcd(x, den) == 1]
    n1 = rng.choice(reduced[:-1])
    n2 = rng.choice([x for x in reduced if x > n1])
    w1 = rng.randint(3, 5 + level)
    w2 = rng.randint(1, w1 - 1)
    return {"family": "mixed_sub", "params": {"w1": w1, "n1": n1, "w2": w2, "n2": n2, "d": den}}


def render_mixed_sub(p: dict) -> dict:
    w1, n1, w2, n2, d = p["w1"], p["n1"], p["w2"], p["n2"], p["d"]
    key = Fraction(w1 * d + n1, d) - Fraction(w2 * d + n2, d)
    reverse = Fraction((w1 - w2) * d + (n2 - n1), d)  # subtracts the smaller fractional part from the larger
    no_borrow_whole = Fraction((w1 - w2) * d + (d + n1 - n2), d)  # borrows in the fraction but not in the whole part
    ignore = Fraction(w1 - w2, 1)
    opts = [
        _opt(_fs(key), True, None, "Верно: занял единицу и вычел.", "Дұрыс: бірлікті алып, азайтты."),
        _opt(_fs(reverse), False, "mixed_subtract_reverse", f"Вычел {n1}/{d} из {n2}/{d} (меньшее из большего), не занимая единицу.",
             f"{n2}/{d}-ден {n1}/{d}-ді азайтты, бірлікті алмады."),
        _opt(_fs(no_borrow_whole), False, "borrow_error", "Занял единицу для дробной части, но не уменьшил целую часть.",
             "Бөлшек бөлігі үшін бірлік алды, бірақ бүтін бөлігін азайтпады."),
        _opt(_fs(ignore), False, "ignore_fraction", "Вычел только целые части, дробные отбросил.", "Тек бүтін бөліктерін азайтты."),
    ]
    return {"stem_ru": f"Вычислите: {w1} {n1}/{d} − {w2} {n2}/{d}.", "stem_kz": f"Есептеңіз: {w1} {n1}/{d} − {w2} {n2}/{d}.",
            "options": opts, "key_value": key,
            "rubric_ru": "1 балл за верный ответ. Попросите показать запись с занятием единицы.",
            "rubric_kz": "Дұрыс жауапқа 1 ұпай. Бірлікті алып жазуды көрсетуді сұраңыз."}


def fam_frac_compare(rng: random.Random, level: int) -> dict:
    pairs = [((1, 3), (1, 4)), ((2, 5), (2, 7)), ((3, 8), (2, 3)), ((4, 9), (3, 5)), ((5, 12), (3, 7)), ((3, 10), (2, 5))]
    (a, b), (c, d) = pairs[min(level * 2 + rng.randint(0, 1), len(pairs) - 1)]
    return {"family": "frac_compare", "params": {"a": a, "b": b, "c": c, "d": d}}


def render_frac_compare(p: dict) -> dict:
    a, b, c, d = p["a"], p["b"], p["c"], p["d"]
    x, y = Fraction(a, b), Fraction(c, d)
    big = f"{a}/{b}" if x > y else f"{c}/{d}"
    small = f"{c}/{d}" if x > y else f"{a}/{b}"
    larger_den = f"{a}/{b}" if b > d else f"{c}/{d}"
    larger_num = f"{a}/{b}" if a > c else f"{c}/{d}"
    opts = [_opt(big, True, None, "Верно: сравнили после приведения к общему знаменателю.", "Дұрыс: ортақ бөлімге келтіріп салыстырды.")]
    seen = {big}
    for text, mc, ru, kz in [(larger_den, "larger_denominator_larger", "Решил, что больше дробь с большим знаменателем.",
                              "Бөлімі үлкен бөлшек үлкен деп шешті."),
                             (larger_num, "compare_numerators_only", "Сравнил только числители.", "Тек алымдарын салыстырды."),
                             ("Их нельзя сравнить", "cannot_compare_diff_den", "Считает, что дроби с разными знаменателями сравнить нельзя.",
                              "Бөлімдері әртүрлі бөлшектерді салыстыруға болмайды деп санайды."),
                             ("Они равны", "equal_difference", "Сравнил по разности числителя и знаменателя.", "Алым мен бөлімнің айырмасы бойынша салыстырды.")]:
        if text not in seen and len(opts) < 4:
            seen.add(text)
            opts.append(_opt(text, False, mc, ru, kz))
    return {"stem_ru": f"Какая дробь больше: {a}/{b} или {c}/{d}?", "stem_kz": f"Қай бөлшек үлкен: {a}/{b} әлде {c}/{d}?",
            "options": opts, "key_value": max(x, y), "key_text": big, "small": small,
            "rubric_ru": "1 балл за верный ответ; попросите обосновать на модели.", "rubric_kz": "Дұрыс жауапқа 1 ұпай; модельде негіздеуді сұраңыз."}


def fam_lcm(rng: random.Random, level: int) -> dict:
    pairs = [(4, 6), (6, 8), (6, 9), (8, 12), (10, 15), (12, 18)]
    a, b = pairs[min(level * 2 + rng.randint(0, 1), len(pairs) - 1)]
    return {"family": "lcm", "params": {"a": a, "b": b}}


def render_lcm(p: dict) -> dict:
    a, b = p["a"], p["b"]
    key = _lcm(a, b)
    opts = [_opt(str(key), True, None, "Верно: наименьшее число, кратное обоим.", "Дұрыс: екеуіне де еселік ең кіші сан."),
            _opt(str(a * b), False, "lcm_as_product", "Взял произведение чисел.", "Сандардың көбейтіндісін алды."),
            _opt(str(gcd(a, b)), False, "gcd_lcm_confusion", "Нашёл НОД вместо НОК.", "ЕКОЕ орнына ЕҮОБ тапты."),
            _opt(str(a + b), False, "lcm_as_sum", "Сложил числа.", "Сандарды қосты.")]
    return {"stem_ru": f"Найдите НОК({a}, {b}).", "stem_kz": f"ЕКОЕ({a}, {b}) табыңыз.", "options": opts, "key_value": Fraction(key),
            "rubric_ru": "1 балл; попросите выписать первые кратные.", "rubric_kz": "1 ұпай; алғашқы еселіктерді жазуды сұраңыз."}


def fam_percent(rng: random.Random, level: int) -> dict:
    pr = [(10, 50), (20, 60), (25, 80), (15, 120), (30, 90), (40, 75)]
    pc, base = pr[min(level * 2 + rng.randint(0, 1), len(pr) - 1)]
    return {"family": "percent", "params": {"p": pc, "n": base}}


def render_percent(p: dict) -> dict:
    pc, n = p["p"], p["n"]
    key = Fraction(pc * n, 100)
    opts = [_opt(_fs(key), True, None, f"Верно: {pc}% = {pc}/100, умножили на {n}.", f"Дұрыс: {pc}% = {pc}/100, {n}-ге көбейтті."),
            _opt(str(pc), False, "percent_as_number", "Взял число процентов как ответ.", "Пайыз санын жауап ретінде алды."),
            _opt(_fs(Fraction(n, pc)), False, "percent_divide", "Разделил число на количество процентов.", "Санды пайыз санына бөлді."),
            _opt(_fs(Fraction(n * 100, pc)), False, "divides_by_percent_fraction", "Разделил на долю вместо умножения.",
                 "Үлеске көбейтудің орнына бөлді.")]
    return {"stem_ru": f"Найдите {pc}% от {n}.", "stem_kz": f"{n} санының {pc}%-ын табыңыз.", "options": opts, "key_value": key,
            "rubric_ru": "1 балл; спросите, больше или меньше ответ исходного числа.", "rubric_kz": "1 ұпай; жауап бастапқы саннан үлкен бе, кіші ме — сұраңыз."}


FAMILIES = {
    "frac_add": (fam_frac_add, render_frac_add, {"add_across", "numerators_not_scaled", "multiplied_instead", "denominators_added"}),
    "mixed_sub": (fam_mixed_sub, render_mixed_sub, {"mixed_subtract_reverse", "borrow_error", "ignore_fraction", "whole_part_error"}),
    "frac_compare": (fam_frac_compare, render_frac_compare, {"larger_denominator_larger", "compare_numerators_only",
                                                             "cannot_compare_diff_den", "equal_difference"}),
    "lcm": (fam_lcm, render_lcm, {"lcm_as_product", "gcd_lcm_confusion", "lcm_as_sum"}),
    "percent": (fam_percent, render_percent, {"percent_as_number", "percent_divide", "divides_by_percent_fraction"}),
}
FAMILIES.update(EXTRA_FAMILIES)


def _parse_value(text: str) -> Fraction | None:
    t = re.sub(r"\s*(см²|см|тг)$", "", text.strip()).replace("−", "-")
    try:
        if " " in t and "/" in t:
            w, fr = t.split(" ", 1)
            n, d = fr.split("/")
            w_ = int(w)
            return Fraction(w_) + (Fraction(int(n), int(d)) if w_ >= 0 else -Fraction(int(n), int(d)))
        if "/" in t:
            n, d = t.split("/")
            return Fraction(int(n), int(d))
        return Fraction(t.replace(",", "."))
    except (ValueError, ZeroDivisionError):
        return None


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_item(it: dict, known_objectives: set[str], known_nodes: set[str]) -> list[dict]:
    out = []

    def add(code: str, ok: bool, blocking: bool = True, detail: str = ""):
        out.append({"code": code, "passed": bool(ok), "blocking": blocking, "detail": detail})

    opts = it.get("options", [])
    keys = [o for o in opts if o.get("correct")]
    add("one_correct_option", len(keys) == 1)
    add("answer_key_matches", bool(keys) and it.get("answer_key") == keys[0].get("key"))
    add("options_unique", len({o["text"].strip() for o in opts}) == len(opts) and 3 <= len(opts) <= 5)
    add("distractor_rationale", all(o.get("rationale_ru") and (o.get("correct") or o.get("misconception")) for o in opts))
    add("bilingual", bool(it.get("stem_ru", "").strip()) and bool(it.get("stem_kz", "").strip())
        and all(o.get("rationale_kz") for o in opts), blocking=False, detail="казахский текст не проверен носителем")
    add("objective_exists", it.get("objective_id") in known_objectives)
    add("evidence_link", bool(it.get("evidence_ids")) and set(it.get("evidence_ids", [])) <= known_nodes)
    add("difficulty_set", it.get("difficulty") in DIFFICULTY)
    add("rubric_present", bool(it.get("rubric_ru")))
    fam = it.get("family")
    if fam in FAMILIES and it.get("params"):
        exp = FAMILIES[fam][1](it["params"])
        key_ok = bool(keys) and (_parse_value(keys[0]["text"]) == exp["key_value"] or keys[0]["text"] == exp.get("key_text"))
        distinct = all(_parse_value(o["text"]) is None or _parse_value(o["text"]) != exp["key_value"] for o in opts if not o.get("correct"))
        add("key_recomputed", key_ok, detail="ключ пересчитан точной арифметикой")
        add("distractors_differ_from_key", distinct)
    else:
        add("key_recomputed", False, blocking=True, detail="нет параметров семейства: ключ должен подтвердить учитель (teacher_key_verified)")
        if it.get("teacher_key_verified"):
            out[-1]["passed"] = True
            out[-1]["detail"] = "ключ подтверждён учителем"
    return out


def check_quiz(items: list[dict], known_objectives: set[str], known_nodes: set[str]) -> dict:
    per = {it["code"]: check_item(it, known_objectives, known_nodes) for it in items}
    quiz_level = [{"code": "item_count_3_7", "passed": 3 <= len(items) <= 7, "blocking": True, "detail": ""},
                  {"code": "stems_unique", "passed": len({i["stem_ru"] for i in items}) == len(items), "blocking": True, "detail": ""},
                  {"code": "not_for_final_grade", "passed": True, "blocking": True, "detail": "use = diagnostic_only"}]
    blocking_failed = [f"{c}:{x['code']}" for c, xs in per.items() for x in xs if x["blocking"] and not x["passed"]] + \
                      [x["code"] for x in quiz_level if x["blocking"] and not x["passed"]]
    return {"items": per, "quiz": quiz_level, "blocking_failed": blocking_failed, "approvable": not blocking_failed}


# ---------------------------------------------------------------------------
# Generation, versions, review
# ---------------------------------------------------------------------------


class GenerateReq(BaseModel):
    dataset_id: str
    topic_id: str
    n_items: int = 5
    seed: int | None = None
    # explicit families chosen by the teacher (e.g. for a topic that was not measured); otherwise families are
    # chosen by the misconception hypotheses observed in the topic
    families: list[str] | None = None
    objective_id: str | None = None


class EditReq(BaseModel):
    items: list[dict]
    note: str = ""


class ReviewReq(BaseModel):
    action: str  # approve | reject
    note: str = ""


def _known(session: Session, org_id: str, quiz: m.Quiz) -> tuple[set[str], set[str]]:
    g = gr.build(session, org_id, quiz.dataset_id, quiz.topic_id, an.Filters(), None)
    meta = an.load_meta(session, org_id, quiz.dataset_id)
    return {o.id for o in meta.objectives}, {n["id"] for n in g["result"]["nodes"]}


def generate(session: Session, p, req: GenerateReq, persist: bool = True) -> dict:
    if persist:
        p.require("methodist")
    if not 3 <= req.n_items <= 7:
        raise ApiError("invalid_parameter", "От 3 до 7 заданий", 422)
    ds = an.get_dataset(session, p.org_id, req.dataset_id)
    g = gr.build(session, p.org_id, req.dataset_id, req.topic_id, an.Filters(), p.user_id)
    ev = an.get_run(session, p.org_id, g["context"]["analysis_id"])["result"]
    item_by_code = {it["code"]: it for it in ev["items"]}
    plan: list[tuple[str, dict | None]] = []
    if req.families:
        unknown = [f for f in req.families if f not in FAMILIES]
        if unknown:
            raise ApiError("unknown_family", "Неизвестное семейство заданий", 422, {"unknown": unknown, "allowed": sorted(FAMILIES)})
        observed = {mc["code"]: mc for mc in ev["misconceptions"]}
        for f in dict.fromkeys(req.families):
            plan.append((f, next((observed[c] for c in FAMILIES[f][2] if c in observed), None)))
    else:
        # hypotheses actually observed in this topic, most frequent first → families that test them
        for mc in ev["misconceptions"]:
            fam = next((f for f, (_, _, mcs) in FAMILIES.items() if mc["code"] in mcs), None)
            if fam and all(f != fam for f, _ in plan):
                plan.append((fam, mc))
    if not plan:
        raise ApiError("no_template_family", "Для гипотез этой темы нет шаблонного семейства заданий: выберите семейство "
                       "вручную или составьте задания сами", 422,
                       {"misconceptions": [x["code"] for x in ev["misconceptions"]], "families": sorted(FAMILIES)})
    topic_objs = [o for o in ev["objectives"]]
    if req.objective_id and not any(o["objective_id"] == req.objective_id for o in topic_objs):
        raise ApiError("unknown_objective", "Цель не относится к теме", 422)
    measured = [o for o in topic_objs if o["score"]]
    default_obj = next((o for o in topic_objs if o["objective_id"] == req.objective_id), None) or \
        (min(measured, key=lambda o: o["score"]["mean"]) if measured else (topic_objs[0] if topic_objs else None))
    rng = random.Random(req.seed if req.seed is not None else int(sha256_bytes(f"{req.topic_id}{ds.version}".encode())[:8], 16))
    items: list[dict] = []
    stems = set()
    i = 0
    while len(items) < req.n_items and i < req.n_items * 6:
        fam, mc = plan[i % len(plan)]
        level = min(2, (i // len(plan)))
        spec = FAMILIES[fam][0](rng, level)
        r = FAMILIES[fam][1](spec["params"])
        i += 1
        vals = [_parse_value(o["text"]) or o["text"] for o in r["options"]]
        if r["stem_ru"] in stems or len(set(vals)) < len(vals):  # coinciding distractors would not discriminate
            continue
        stems.add(r["stem_ru"])
        sig_items = [item_by_code[c] for c in mc["items"] if c in item_by_code] if mc else []
        obj = None
        if mc and not req.families:
            obj = next((ol for it in sig_items for ol in it["objectives"] if ol["status"] == "confirmed"), None) or \
                (sig_items[0]["objectives"][0] if sig_items and sig_items[0]["objectives"] else None)
        elif default_obj:
            obj = {"objective_id": default_obj["objective_id"], "code": default_obj["code"]}
        if obj is None:
            continue
        letters = "ABCD"
        opts = r["options"][:]
        rng.shuffle(opts)
        for k, o in enumerate(opts):
            o["key"] = letters[k]
        items.append({
            "code": f"Q{len(items) + 1}", "family": spec["family"], "params": spec["params"], "objective_id": obj["objective_id"],
            "objective_code": obj["code"], "stem_ru": r["stem_ru"], "stem_kz": r["stem_kz"], "options": opts,
            "answer_key": next(o["key"] for o in opts if o["correct"]), "rubric_ru": r["rubric_ru"], "rubric_kz": r["rubric_kz"],
            "difficulty": DIFFICULTY[level], "target_misconception": mc["code"] if mc else None,
            "evidence_ids": ([f"misconception:{mc['code']}"] + [f"item:{it['item_id']}" for it in sig_items[:2]] if mc else [])
            + ([f"objective:{obj['objective_id']}"] if not mc or req.families else []),
            "evidence_note_ru": (f"Гипотеза «{mc['label_ru']}»: {mc['n_learners']} уч. в заданиях {', '.join(mc['items'][:3])}." if mc else
                                 f"Семейство «{FAMILY_TITLES.get(spec['family'], (spec['family'],))[0]}» выбрано учителем для цели "
                                 f"{obj['code']}; в данных темы гипотез этого типа нет — работа проверяет их впервые."),
        })
    meta = an.load_meta(session, p.org_id, req.dataset_id)
    checks = check_quiz(items, {o.id for o in meta.objectives}, {n["id"] for n in g["result"]["nodes"]})
    t = next(x for x in meta.topics if x.id == req.topic_id)
    if not persist:  # read-only preview (presentation mode): nothing is stored
        return {"id": None, "title": f"Диагностика: {t.code} {t.title_ru}", "status": "preview", "use": "diagnostic_only",
                "counts_toward_grade": False, "items": items, "checks": checks, "generation_mode": "template",
                "source_analysis_id": g["context"]["analysis_id"]}
    q = m.Quiz(org_id=p.org_id, dataset_id=ds.id, topic_id=req.topic_id, title=f"Диагностика: {t.code} {t.title_ru}",
               status="draft", current_version=1, source_analysis_id=g["context"]["analysis_id"], generation_mode="template",
               created_by=p.user_id)
    session.add(q)
    session.flush()
    session.add(m.QuizVersion(quiz_id=q.id, version=1, items=items, checks=checks, author_kind="generator", created_by=p.user_id,
                              note=GENERATOR_VERSION))
    audit(session, p.org_id, p.user_id, "quiz.generate", "quiz", q.id, n_items=len(items), generator=GENERATOR_VERSION)
    session.commit()
    return payload(session, q)


def _get(session: Session, org_id: str, quiz_id: str) -> m.Quiz:
    q = session.scalar(select(m.Quiz).where(m.Quiz.id == quiz_id, m.Quiz.org_id == org_id))
    if q is None:
        raise not_found("quiz", quiz_id)
    return q


def payload(session: Session, q: m.Quiz) -> dict:
    versions = list(session.scalars(select(m.QuizVersion).where(m.QuizVersion.quiz_id == q.id).order_by(m.QuizVersion.version)))
    cur = next(v for v in versions if v.version == q.current_version)
    rsets = list(session.scalars(select(m.QuizResponseSet).where(m.QuizResponseSet.quiz_id == q.id).order_by(m.QuizResponseSet.created_at)))
    return {"id": q.id, "dataset_id": q.dataset_id, "topic_id": q.topic_id, "title": q.title, "status": q.status,
            "use": q.use, "counts_toward_grade": False, "generation_mode": q.generation_mode, "current_version": q.current_version,
            "source_analysis_id": q.source_analysis_id, "items": cur.items, "checks": cur.checks,
            "versions": [{"version": v.version, "author_kind": v.author_kind, "created_at": v.created_at.isoformat(), "note": v.note,
                          "approvable": v.checks.get("approvable")} for v in versions],
            "reviewed_by": q.reviewed_by, "reviewed_at": q.reviewed_at.isoformat() if q.reviewed_at else None, "review_note": q.review_note,
            "response_sets": [{"id": r.id, "quiz_version": r.quiz_version, "n_learners": r.n_learners, "summary": r.summary,
                               "decision_id": r.decision_id, "created_at": r.created_at.isoformat()} for r in rsets],
            "note_ru": "Диагностическая работа: результаты не входят в итоговую оценку и не меняют данные итоговых работ."}


def list_quizzes(session: Session, org_id: str, dataset_id: str) -> list[dict]:
    qs = session.scalars(select(m.Quiz).where(m.Quiz.org_id == org_id, m.Quiz.dataset_id == dataset_id).order_by(m.Quiz.created_at.desc()))
    return [{"id": q.id, "title": q.title, "status": q.status, "current_version": q.current_version, "topic_id": q.topic_id,
             "created_at": q.created_at.isoformat()} for q in qs]


ALLOWED_ITEM_FIELDS = {"code", "family", "params", "objective_id", "objective_code", "stem_ru", "stem_kz", "options", "answer_key",
                       "rubric_ru", "rubric_kz", "difficulty", "target_misconception", "evidence_ids", "evidence_note_ru",
                       "teacher_key_verified"}


def edit(session: Session, p, quiz_id: str, req: EditReq) -> dict:
    p.require("methodist")
    q = _get(session, p.org_id, quiz_id)
    if q.status == "approved":
        raise ApiError("quiz_locked", "Утверждённую работу нельзя менять: создайте новую", 409)
    if not 1 <= len(req.items) <= 7:
        raise ApiError("invalid_parameter", "От 1 до 7 заданий", 422)
    prev = session.scalar(select(m.QuizVersion).where(m.QuizVersion.quiz_id == q.id, m.QuizVersion.version == q.current_version))
    prev_by_code = {i["code"]: i for i in prev.items}
    items = []
    for it in req.items:
        clean = {k: v for k, v in it.items() if k in ALLOWED_ITEM_FIELDS}
        old = prev_by_code.get(clean.get("code"))
        # the teacher may rewrite text; if the numbers in the stem change, the recomputed key no longer applies
        if old and (clean.get("stem_ru") != old["stem_ru"] or clean.get("params") != old.get("params")):
            clean.pop("family", None)
            clean.pop("params", None)
        items.append(clean)
    objs, nodes = _known(session, p.org_id, q)
    checks = check_quiz(items, objs, nodes)
    v = q.current_version + 1
    session.add(m.QuizVersion(quiz_id=q.id, version=v, items=items, checks=checks, author_kind="teacher", created_by=p.user_id,
                              note=req.note[:500] or None))
    q.current_version, q.status = v, "edited"
    audit(session, p.org_id, p.user_id, "quiz.edit", "quiz", q.id, version=v)
    session.commit()
    return payload(session, q)


def review(session: Session, p, quiz_id: str, req: ReviewReq) -> dict:
    p.require("methodist")
    q = _get(session, p.org_id, quiz_id)
    cur = session.scalar(select(m.QuizVersion).where(m.QuizVersion.quiz_id == q.id, m.QuizVersion.version == q.current_version))
    if req.action == "approve":
        if not cur.checks.get("approvable"):
            raise ApiError("quiz_checks_failed", "Нельзя утвердить: не пройдены обязательные проверки", 422,
                           {"blocking_failed": cur.checks.get("blocking_failed", [])})
        q.status = "approved"
    elif req.action == "reject":
        q.status = "rejected"
    else:
        raise ApiError("invalid_parameter", "action: approve | reject", 422)
    q.reviewed_by, q.reviewed_at, q.review_note = p.user_id, datetime.now(UTC), req.note[:1000] or None
    audit(session, p.org_id, p.user_id, f"quiz.{req.action}", "quiz", q.id, version=q.current_version)
    session.commit()
    return payload(session, q)


# ---------------------------------------------------------------------------
# Export and responses
# ---------------------------------------------------------------------------


def export_rows(qd: dict, lang: str = "ru") -> list[list]:
    rows = [["code", "objective", "difficulty", "stem", "option", "text", "correct", "misconception", "rationale", "rubric"]]
    for it in qd["items"]:
        for o in it["options"]:
            rows.append([it["code"], it.get("objective_code", ""), it.get("difficulty", ""), it["stem_ru" if lang == "ru" else "stem_kz"],
                         o["key"], o["text"], "1" if o["correct"] else "0", o.get("misconception") or "",
                         o.get("rationale_ru" if lang == "ru" else "rationale_kz", ""), it.get("rubric_ru" if lang == "ru" else "rubric_kz", "")])
    return rows


def to_csv(qd: dict, lang: str = "ru") -> bytes:
    from .reports import safe_cell

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in export_rows(qd, lang):
        w.writerow([safe_cell(v) for v in r])
    return ("﻿" + buf.getvalue()).encode("utf-8")


def to_xlsx(qd: dict, lang: str = "ru") -> bytes:
    from openpyxl import Workbook

    from .reports import safe_cell

    wb = Workbook()
    ws = wb.active
    ws.title = "items"
    for r in export_rows(qd, lang):
        ws.append([safe_cell(v) for v in r])
    for row in ws.iter_rows():
        for c in row:
            if isinstance(c.value, str):
                c.data_type = "s"
    info = wb.create_sheet("about")
    for line in (qd["title"], f"Статус: {qd['status']} · версия {qd['current_version']}",
                 "Диагностическая работа: не входит в итоговую оценку.", "Формат ответов для загрузки: learner_code,item_code,response"):
        info.append([line])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_pdf(qd: dict, lang: str = "ru", teacher: bool = False) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab import rl_config
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    from .reports import FONT_DIR

    rl_config.invariant = 1
    try:
        pdfmetrics.getFont("OquSans")
    except KeyError:
        pdfmetrics.registerFont(TTFont("OquSans", str(FONT_DIR / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont("OquSans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    base = ParagraphStyle("b", fontName="OquSans", fontSize=10.5, leading=14)
    h1 = ParagraphStyle("h", parent=base, fontName="OquSans-Bold", fontSize=14, leading=18, spaceAfter=6)
    small = ParagraphStyle("s", parent=base, fontSize=8.5, leading=11, textColor=colors.HexColor("#4a5568"))
    warn = ParagraphStyle("w", parent=base, backColor=colors.HexColor("#fff4e5"), borderPadding=4, textColor=colors.HexColor("#7b341e"))

    def P(t, st=base):
        return Paragraph(escape(str(t)), st)

    story = [P(qd["title"], h1),
             P(("Ответы и обоснования для учителя" if teacher else "Диагностическая работа") + f" · версия {qd['current_version']}", small)]
    if qd["status"] != "approved":
        story.append(P("ЧЕРНОВИК: работа не утверждена учителем.", warn))
    story.append(P("Не входит в итоговую оценку. Результаты используются только для проверки гипотез об ошибках.", small))
    story.append(Spacer(1, 6))
    for it in qd["items"]:
        story.append(P(f"{it['code']}. {it['stem_ru' if lang == 'ru' else 'stem_kz']}", ParagraphStyle("q", parent=base, fontName="OquSans-Bold",
                                                                                                    spaceBefore=6)))
        for o in it["options"]:
            line = f"{o['key']}) {o['text']}"
            if teacher:
                line += " — " + ("верно" if o["correct"] else f"{o.get('misconception')}: {o.get('rationale_ru', '')}")
            story.append(P(line))
        if teacher:
            story.append(P(f"Цель: {it.get('objective_code', '')} · сложность: {it.get('difficulty', '')} · {it.get('rubric_ru', '')}", small))
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=qd["title"], author="OquMap", creator="OquMap")
    doc.build(story)
    return buf.getvalue()


def import_responses(session: Session, p, quiz_id: str, data: bytes, decision_id: str | None = None) -> dict:
    """learner_code,item_code,response → per-item correctness and per-hypothesis counts (never into grades)."""
    p.require("methodist")
    q = _get(session, p.org_id, quiz_id)
    if q.status != "approved":
        raise ApiError("quiz_not_approved", "Ответы принимаются только для утверждённой работы", 409)
    if decision_id and session.scalar(select(m.Decision).where(m.Decision.id == decision_id, m.Decision.org_id == p.org_id)) is None:
        raise not_found("decision", decision_id)
    from .imports import read_table

    tbl = read_table(data, "responses.csv")
    hdr = [h.lower() for h in tbl.headers]
    need = ["learner_code", "item_code", "response"]
    if any(h not in hdr for h in need):
        raise ApiError("missing_columns", "Нужны столбцы learner_code,item_code,response", 422, {"required": need, "found": tbl.headers})
    ix = {h: hdr.index(h) for h in need}
    cur = session.scalar(select(m.QuizVersion).where(m.QuizVersion.quiz_id == q.id, m.QuizVersion.version == q.current_version))
    items = {it["code"]: it for it in cur.items}
    per_item = {c: {"n": 0, "correct": 0, "by_option": {}} for c in items}
    per_mis: dict[str, set] = {}
    rejected = []
    learners = set()
    seen = set()
    for n, row in enumerate(tbl.rows, start=2):
        lc, ic, rv = (row[ix[k]].strip() if ix[k] < len(row) else "" for k in need)
        if not lc or ic not in items:
            rejected.append({"row": n, "reason": "unknown_item" if lc else "missing_learner"})
            continue
        if (lc, ic) in seen:
            rejected.append({"row": n, "reason": "duplicate"})
            continue
        seen.add((lc, ic))
        learners.add(lc)
        it = items[ic]
        opt = next((o for o in it["options"] if o["key"].upper() == rv.upper()), None)
        st = per_item[ic]
        st["n"] += 1
        st["by_option"][rv.upper() or "—"] = st["by_option"].get(rv.upper() or "—", 0) + 1
        if opt and opt["correct"]:
            st["correct"] += 1
        elif opt and opt.get("misconception"):
            per_mis.setdefault(opt["misconception"], set()).add(lc)
    summary = {"items": {c: {**v, "p_correct": (v["correct"] / v["n"]) if v["n"] else None} for c, v in per_item.items()},
               "hypotheses": {k: {"n_learners": len(v), "share": len(v) / len(learners) if learners else None} for k, v in per_mis.items()},
               "rejected_rows": rejected[:100], "n_rejected": len(rejected),
               "interpretation_ru": "Повторный выбор дистрактора одним учеником поддерживает гипотезу; единичный выбор — повод "
                                    "для беседы, а не диагноз. Результаты не входят в итоговую оценку."}
    rs = m.QuizResponseSet(org_id=p.org_id, quiz_id=q.id, quiz_version=q.current_version, decision_id=decision_id, n_learners=len(learners),
                           summary=summary, file_sha256=sha256_bytes(data), created_by=p.user_id)
    session.add(rs)
    audit(session, p.org_id, p.user_id, "quiz.responses", "quiz", q.id, n_learners=len(learners), decision_id=decision_id)
    session.commit()
    return {"response_set_id": rs.id, "n_learners": len(learners), "summary": summary}
