"""Onboarding of a real project (dataset) from files, without any demo identifiers.

Stages (each one is ``validate → report/preview → explicit commit`` through the regular import batches):

    1. program     — subject/grade, topics, learning objectives, prerequisites, current/min/max/elapsed hours
    2. editions    — textbook editions used by classes
    3. item_bank   — assessment forms, scales, items, answer keys, item→objective links (weights, status)
    4. roster      — schools, classes, pseudonymous learners, edition exposure
    5. responses   — item responses (existing ``responses`` kind), referencing the forms/items above

Structural stages (program, editions, item_bank) are strict: one invalid row blocks the commit, so the
programme is never half-imported. Roster and responses accept valid rows and report rejected ones.
External keys (codes) are stable and unique within the project; internal ids are generated.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m
from ..db import new_id

STRICT_KINDS = {"program", "editions", "item_bank", "assignments"}
KINDS = ("program", "editions", "item_bank", "roster", "assignments")
ORDER = ["program", "editions", "item_bank", "roster", "responses", "assignments"]
OPTIONAL_KINDS = {"assignments"}  # without it the assessment scope is inferred from sittings and labelled as such

# field: (required, description, example)
FIELD_DOCS: dict[str, dict[str, tuple[bool, str, str]]] = {
    "program": {
        "topic_code": (True, "Стабильный код темы внутри проекта", "TOP-1"),
        "topic_title_ru": (True, "Название темы (русский)", "Натуральные числа"),
        "objective_code": (True, "Стабильный код цели обучения (уникален в проекте)", "OBJ-1.1"),
        "objective_text_ru": (True, "Формулировка цели (русский)", "Складывать многозначные числа"),
        "subject": (False, "Предмет (одинаков для всех строк)", "Математика"),
        "grade": (False, "Класс обучения 1–12 (одинаков для всех строк)", "5"),
        "program_code": (False, "Код программы", "MATH-5"),
        "program_version": (False, "Версия программы", "2026.1"),
        "program_title": (False, "Название программы", "Математика 5 класс"),
        "language": (False, "Язык программы: ru | kz", "ru"),
        "topic_title_kz": (False, "Название темы (казахский)", "Натурал сандар"),
        "topic_order": (False, "Порядок темы (целое)", "1"),
        "objective_text_kz": (False, "Формулировка цели (казахский)", ""),
        "prerequisite_codes": (False, "Коды целей-предпосылок через «;»", "OBJ-1.1;OBJ-1.2"),
        "hours_current": (False, "Текущие плановые часы темы (на первой строке темы)", "12"),
        "hours_min": (False, "Минимум часов темы", "10"),
        "hours_max": (False, "Максимум часов темы", "16"),
        "hours_elapsed": (False, "Уже проведённые часы темы (не перераспределяются)", "0"),
    },
    "editions": {
        "edition_code": (True, "Стабильный код издания", "BOOK-1"),
        "title": (True, "Название издания", "Учебник математики, часть 1"),
        "edition_label": (False, "Выпуск/издание", "2-е изд."),
        "year": (False, "Год выпуска", "2024"),
        "language": (False, "Язык: ru | kz", "ru"),
        "grade": (False, "Класс", "5"),
        "usage_permission": (False, "Основание использования материалов", "собственные материалы школы"),
    },
    "item_bank": {
        "form_code": (True, "Код формы проверки", "POST-1"),
        "item_code": (True, "Стабильный код задания", "IT-01"),
        "max_points": (True, "Максимальный балл задания (> 0)", "1"),
        "objective_codes": (True, "Цели задания: «КОД» или «КОД:вес;КОД:вес» (веса в сумме 1)", "OBJ-1.1:0.5;OBJ-1.2:0.5"),
        "form_name": (False, "Название формы", "Итоговая проверка"),
        "form_stage": (False, "Этап: pre | post | followup (по умолчанию post)", "post"),
        "scale_code": (False, "Шкала формы (по умолчанию = код формы)", "SCALE-POST"),
        "scale_name": (False, "Название шкалы", "Итоговая шкала"),
        "scale_linking": (False, "Связывание: identical_form | common_items | none", "identical_form"),
        "position": (False, "Номер задания в форме", "1"),
        "stem_ru": (False, "Условие (русский)", "Вычислите 24 + 18"),
        "stem_kz": (False, "Условие (казахский)", ""),
        "item_type": (False, "single_choice | numeric | open", "single_choice"),
        "options": (False, "Варианты: «A=текст|B=текст|…» (для single_choice)", "A=42|B=32|C=46|D=412"),
        "answer_key": (False, "Ключ (буква варианта или правильный ответ)", "A"),
        "misconceptions": (False, "Коды типичных ошибок по вариантам: «B=код|C=код»", "B=carry_error"),
        "mapping_status": (False, "Статус связей с целями: confirmed | proposed", "confirmed"),
    },
    "roster": {
        "school_code": (True, "Псевдонимный код школы", "SCH-1"),
        "class_code": (True, "Код класса (уникален в проекте)", "SCH-1-5A"),
        "learner_code": (True, "Псевдонимный код ученика, без ФИО", "L0001"),
        "school_name": (False, "Название/псевдоним школы", "Школа 1"),
        "teacher_code": (False, "Псевдонимный код учителя", "T-01"),
        "grade": (False, "Класс обучения", "5"),
        "language": (False, "Язык обучения класса: ru | kz", "ru"),
        "academic_year": (False, "Учебный год", "2025-2026"),
        "edition_code": (False, "Основное издание класса", "BOOK-1"),
        "topic_codes": (False, "Темы, к которым относится издание («;»), пусто = все", "TOP-1;TOP-2"),
        "period_start": (False, "Начало использования (ГГГГ-ММ-ДД)", "2025-09-01"),
        "period_end": (False, "Окончание использования (ГГГГ-ММ-ДД)", "2026-05-31"),
    },
    # Optional stage: which classes an assessment was *assigned* to (from the school's schedule/order), so that a class
    # with no sitting records at all is visible. Without it the scope is only inferred from sittings and reported so.
    "assignments": {
        "assessment_code": (True, "Код проведения проверки (уже загружено с ответами)", "POST-2026"),
        "class_code": (True, "Код класса, которому проверка была назначена", "SCH-1-5A"),
        "note": (False, "Основание назначения (приказ, график)", "График проверок, приказ №12"),
    },
}

RESPONSES_DOCS = {
    "learner_code": (True, "Код ученика из состава", "L0001"),
    "assessment_code": (True, "Код проведения проверки (например, POST-2026)", "POST-2026"),
    "item_code": (True, "Код задания из банка", "IT-01"),
    "form_code": (False, "Форма (нужна, если проведение ещё не создано)", "POST-1"),
    "score": (False, "Балл (пусто = вычислить по ключу из response)", "1"),
    "response": (False, "Выбранный вариант", "A"),
    "status": (False, "answered | omitted | absent", "answered"),
    "attempt": (False, "Номер попытки (по умолчанию 1)", "1"),
    "date": (False, "Дата проведения", "2026-05-20"),
    "class_code": (False, "Класс (для новых учеников)", "SCH-1-5A"),
    "school_code": (False, "Школа (для новых классов)", "SCH-1"),
}

ONBOARDING_FIELDS = {k: {"required": [f for f, v in d.items() if v[0]], "optional": [f for f, v in d.items() if not v[0]]}
                     for k, d in FIELD_DOCS.items()}

DEPENDENCY_TEXT = {
    "program": "Сначала загрузите учебную программу (темы и цели).",
    "editions": "Сначала загрузите список изданий.",
    "item_bank": "Сначала загрузите банк заданий и формы проверок.",
    "roster": "Сначала загрузите состав: школы, классы и учеников.",
    "responses": "Сначала загрузите ответы: проведения проверок создаются вместе с ними.",
}

CODE_RE = re.compile(r"^[\w\-.:/ ]{1,60}$", re.UNICODE)
STAGES = {"pre", "post", "followup"}
LINKING = {"identical_form", "common_items", "none"}


def project_status(session: Session, dataset: m.Dataset) -> dict:
    """What has been imported into a project and what each stage still needs."""
    pv = dataset.program_version_id
    n_topics = n_forms = n_items = 0
    if pv:
        n_topics = len(session.scalars(select(m.Topic.id).where(m.Topic.program_version_id == pv)).all())
        n_forms = len(session.scalars(select(m.AssessmentForm.id).where(m.AssessmentForm.program_version_id == pv)).all())
        n_items = len(session.scalars(select(m.Item.id).where(m.Item.program_version_id == pv)).all())
    n_editions = len(session.scalars(select(m.TextbookEdition.id).where(m.TextbookEdition.org_id == dataset.org_id)).all())
    n_learners = len(session.scalars(select(m.Learner.id).where(m.Learner.dataset_id == dataset.id)).all())
    n_responses = session.query(m.Response).filter(m.Response.dataset_id == dataset.id).count()
    from .. import measurement_models as mm

    n_assign = session.query(mm.AssessmentCohort).filter(mm.AssessmentCohort.dataset_id == dataset.id).count()
    done = {"program": n_topics > 0, "editions": n_editions > 0, "item_bank": n_forms > 0, "roster": n_learners > 0,
            "responses": n_responses > 0, "assignments": n_assign > 0}
    requires = {"program": [], "editions": [], "item_bank": ["program"], "roster": [], "responses": ["program", "item_bank"],
                "assignments": ["responses"]}
    stages = []
    for k in ORDER:
        missing = [d for d in requires[k] if not done[d]]
        stages.append({"kind": k, "done": done[k], "optional": k in OPTIONAL_KINDS, "blocked_by": missing,
                       "blocked_message": " ".join(DEPENDENCY_TEXT[d] for d in missing) or None})
    return {"dataset_id": dataset.id, "stages": stages,
            "counts": {"topics": n_topics, "forms": n_forms, "items": n_items, "editions": n_editions,
                       "learners": n_learners, "responses": n_responses, "assignments": n_assign}}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate(session: Session, dataset: m.Dataset, org_id: str, kind: str, table, mapping: dict) -> dict:
    return validate_full(session, dataset, org_id, kind, table, mapping)[0]


def validate_full(session: Session, dataset: m.Dataset, org_id: str, kind: str, table, mapping: dict):
    from .imports import RowResult

    spec = ONBOARDING_FIELDS[kind]
    missing_cols = [f for f in spec["required"] if f not in mapping or mapping[f] not in table.headers]
    if missing_cols:
        return {"rows_total": len(table.rows), "rows_accepted": 0, "rows_rejected": 0,
                "mapping_error": {"missing": missing_cols}, "commit_allowed": False, "blocking": []}, []
    col = {f: table.headers.index(h) for f, h in mapping.items() if h in table.headers}
    rows: list[RowResult] = []
    for n, raw in enumerate(table.rows, start=1):
        if not any(c.strip() for c in raw):
            continue
        rows.append(RowResult(n, {f: (raw[i].strip() if i < len(raw) else "") for f, i in col.items()}, []))
    blocking: list[dict] = []
    for r in rows:
        for f, v in r.values.items():
            if v[:1] in ("=", "+", "@") and f not in ("options", "stem_ru", "stem_kz", "misconceptions"):
                r.errors.append({"code": "formula_not_allowed", "field": f})
            elif v.startswith("="):
                r.errors.append({"code": "formula_not_allowed", "field": f})
        for f in spec["required"]:
            if not r.values.get(f):
                r.errors.append({"code": "missing_required", "field": f})
    {"program": _v_program, "editions": _v_editions, "item_bank": _v_item_bank, "roster": _v_roster,
     "assignments": _v_assignments}[kind](
        session, dataset, org_id, rows, blocking)
    accepted = [r for r in rows if not r.errors]
    rejected = [r for r in rows if r.errors]
    by_code: dict[str, int] = defaultdict(int)
    for r in rejected:
        for e in r.errors:
            by_code[e["code"]] += 1
    strict = kind in STRICT_KINDS
    commit_allowed = not blocking and bool(accepted) and (not strict or not rejected)
    return {
        "rows_total": len(rows), "rows_accepted": len(accepted), "rows_rejected": len(rejected),
        "errors_by_code": dict(by_code),
        "rejected_rows": [{"row_number": r.row_number, "errors": r.errors, "values": r.values} for r in rejected[:200]],
        "rejected_rows_truncated": len(rejected) > 200,
        "blocking": blocking, "strict": strict, "commit_allowed": commit_allowed,
        "commit_rule": ("Структурный импорт: загружается только целиком, без ошибок." if strict else
                        "Принимаются корректные строки; отклонённые перечислены в отчёте."),
        "project": project_status(session, dataset),
    }, accepted


def _ok_code(r, field):
    v = r.values.get(field, "")
    if v and not CODE_RE.match(v):
        r.errors.append({"code": "invalid_code", "field": field})


def _int(r, field, lo=0, hi=10_000):
    v = r.values.get(field, "")
    if v == "":
        return None
    try:
        x = int(float(v.replace(",", ".")))
        if not lo <= x <= hi:
            raise ValueError
        return x
    except ValueError:
        r.errors.append({"code": "invalid_number", "field": field, "value": v})
        return None


def _v_program(session, dataset, org_id, rows, blocking) -> None:
    if dataset.program_version_id:
        blocking.append({"code": "program_already_defined",
                         "message": "У проекта уже есть программа. Для другой программы создайте новый проект."})
    obj_seen, topic_info = {}, {}
    first = rows[0].values if rows else {}
    for r in rows:
        v = r.values
        for f in ("topic_code", "objective_code"):
            _ok_code(r, f)
        if v.get("objective_code") in obj_seen:
            r.errors.append({"code": "duplicate_row", "field": "objective_code"})
        obj_seen.setdefault(v.get("objective_code"), r)
        for f in ("subject", "grade", "program_code", "program_version", "language"):
            if v.get(f) and first.get(f) and v[f] != first[f]:
                r.errors.append({"code": "program_conflict", "field": f})
        if v.get("language") and v["language"] not in ("ru", "kz"):
            r.errors.append({"code": "invalid_value", "field": "language"})
        _int(r, "grade", 1, 12)
        _int(r, "topic_order", 0, 1000)
        hours = [_int(r, f, 0, 2000) for f in ("hours_current", "hours_min", "hours_max", "hours_elapsed")]
        cur, lo, hi, el = hours
        if (lo is not None and hi is not None and lo > hi) or (cur is not None and hi is not None and cur > hi) or \
                (cur is not None and lo is not None and cur < lo) or (cur is not None and el is not None and el > cur):
            r.errors.append({"code": "hours_inconsistent", "field": "hours_current"})
        t = v.get("topic_code")
        sig = (v.get("topic_title_ru"), tuple(x for x in hours))
        if t in topic_info:
            prev = topic_info[t]
            if v.get("topic_title_ru") != prev[0] or any(h is not None and p is not None and h != p for h, p in zip(sig[1], prev[1], strict=True)):
                r.errors.append({"code": "topic_conflict", "field": "topic_code"})
        else:
            topic_info[t] = sig
    codes = set(obj_seen)
    graph: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        for p in [x.strip() for x in r.values.get("prerequisite_codes", "").split(";") if x.strip()]:
            if p not in codes:
                r.errors.append({"code": "unknown_prerequisite", "field": "prerequisite_codes", "value": p})
            elif p == r.values.get("objective_code"):
                r.errors.append({"code": "prerequisite_cycle", "field": "prerequisite_codes", "value": p})
            else:
                graph[p].append(r.values.get("objective_code"))
    # cycle detection (DFS)
    state: dict[str, int] = {}

    def dfs(u) -> bool:
        state[u] = 1
        for w in graph.get(u, []):
            if state.get(w) == 1 or (state.get(w) is None and dfs(w)):
                return True
        state[u] = 2
        return False

    for u in list(graph):
        if state.get(u) is None and dfs(u):
            blocking.append({"code": "prerequisite_cycle", "message": "В предпосылках есть цикл."})
            break


def _v_editions(session, dataset, org_id, rows, blocking) -> None:
    existing = {e.code: e for e in session.scalars(select(m.TextbookEdition).where(m.TextbookEdition.org_id == org_id))}
    seen = set()
    for r in rows:
        v = r.values
        _ok_code(r, "edition_code")
        if v.get("edition_code") in seen:
            r.errors.append({"code": "duplicate_row", "field": "edition_code"})
        seen.add(v.get("edition_code"))
        e = existing.get(v.get("edition_code"))
        if e is not None and e.title != v.get("title"):
            r.errors.append({"code": "edition_conflict", "field": "title", "existing": e.title})
        if v.get("language") and v["language"] not in ("ru", "kz", "en"):
            r.errors.append({"code": "invalid_value", "field": "language"})
        _int(r, "year", 1900, 2100)
        _int(r, "grade", 1, 12)


def parse_weights(spec: str) -> list[tuple[str, float]] | None:
    parts = [p.strip() for p in spec.split(";") if p.strip()]
    if not parts:
        return None
    out = []
    explicit = any(":" in p for p in parts)
    for p in parts:
        if ":" in p:
            code, w = p.rsplit(":", 1)
            out.append((code.strip(), float(w.replace(",", "."))))
        else:
            if explicit:
                return None
            out.append((p, 1.0 / len(parts)))
    return out


def parse_pairs(spec: str) -> list[tuple[str, str]]:
    out = []
    for p in [x for x in spec.split("|") if x.strip()]:
        if "=" not in p:
            raise ValueError(p)
        k, val = p.split("=", 1)
        out.append((k.strip().upper(), val.strip()))
    return out


def _v_item_bank(session, dataset, org_id, rows, blocking) -> None:
    if not dataset.program_version_id:
        blocking.append({"code": "missing_dependency", "dependency": "program", "message": DEPENDENCY_TEXT["program"]})
        objs = set()
        existing_items = set()
        existing_forms = set()
    else:
        objs = set(session.scalars(select(m.LearningObjective.code).where(
            m.LearningObjective.program_version_id == dataset.program_version_id)))
        existing_items = set(session.scalars(select(m.Item.code).where(m.Item.program_version_id == dataset.program_version_id)))
        existing_forms = set(session.scalars(select(m.AssessmentForm.code).where(
            m.AssessmentForm.program_version_id == dataset.program_version_id)))
    item_sig: dict[str, tuple] = {}
    form_sig: dict[str, tuple] = {}
    scale_sig: dict[str, str] = {}
    pairs = set()
    for r in rows:
        v = r.values
        for f in ("form_code", "item_code", "scale_code"):
            _ok_code(r, f)
        key = (v.get("form_code"), v.get("item_code"))
        if key in pairs:
            r.errors.append({"code": "duplicate_row", "field": "item_code"})
        pairs.add(key)
        if v.get("item_code") in existing_items:
            r.errors.append({"code": "item_exists", "field": "item_code"})
        if v.get("form_code") in existing_forms:
            r.errors.append({"code": "form_exists", "field": "form_code"})
        stage = v.get("form_stage") or "post"
        if stage not in STAGES:
            r.errors.append({"code": "invalid_value", "field": "form_stage"})
        linking = v.get("scale_linking") or "identical_form"
        if linking not in LINKING:
            r.errors.append({"code": "invalid_value", "field": "scale_linking"})
        scale = v.get("scale_code") or v.get("form_code")
        if scale in scale_sig and scale_sig[scale] != linking:
            r.errors.append({"code": "scale_conflict", "field": "scale_linking"})
        scale_sig.setdefault(scale, linking)
        fs = (stage, scale)
        if v.get("form_code") in form_sig and form_sig[v["form_code"]] != fs:
            r.errors.append({"code": "form_conflict", "field": "form_stage"})
        form_sig.setdefault(v.get("form_code"), fs)
        try:
            mp = float(v.get("max_points", "").replace(",", "."))
            if not 0 < mp <= 1000:
                raise ValueError
        except ValueError:
            r.errors.append({"code": "invalid_number", "field": "max_points"})
            mp = None
        try:
            weights = parse_weights(v.get("objective_codes", ""))
        except ValueError:
            weights = None
        if weights is None:
            r.errors.append({"code": "invalid_value", "field": "objective_codes"})
        else:
            if abs(sum(w for _, w in weights) - 1) > 0.01 or any(w <= 0 for _, w in weights):
                r.errors.append({"code": "weights_not_normalized", "field": "objective_codes"})
            for code, _ in weights:
                if objs and code not in objs:
                    r.errors.append({"code": "unknown_objective", "field": "objective_codes", "value": code})
        itype = v.get("item_type") or ("single_choice" if v.get("options") else "open")
        if itype not in ("single_choice", "numeric", "open"):
            r.errors.append({"code": "invalid_value", "field": "item_type"})
        options = []
        if v.get("options"):
            try:
                options = parse_pairs(v["options"])
            except ValueError:
                r.errors.append({"code": "invalid_value", "field": "options"})
        if itype == "single_choice":
            letters = [k for k, _ in options]
            if len(options) < 2 or len(set(letters)) != len(letters):
                r.errors.append({"code": "invalid_value", "field": "options"})
            if (v.get("answer_key") or "").upper() not in letters:
                r.errors.append({"code": "answer_key_not_in_options", "field": "answer_key"})
        if v.get("misconceptions"):
            try:
                mis = parse_pairs(v["misconceptions"])
                if any(k not in {x for x, _ in options} for k, _ in mis):
                    r.errors.append({"code": "invalid_value", "field": "misconceptions"})
            except ValueError:
                r.errors.append({"code": "invalid_value", "field": "misconceptions"})
        if (v.get("mapping_status") or "confirmed") not in ("confirmed", "proposed"):
            r.errors.append({"code": "invalid_value", "field": "mapping_status"})
        sig = (v.get("stem_ru"), v.get("options"), v.get("answer_key"), mp, v.get("objective_codes"), itype)
        if v.get("item_code") in item_sig and item_sig[v["item_code"]] != sig:
            r.errors.append({"code": "item_conflict", "field": "item_code"})
        item_sig.setdefault(v.get("item_code"), sig)
        _int(r, "position", 0, 1000)


def _v_roster(session, dataset, org_id, rows, blocking) -> None:
    editions = set(session.scalars(select(m.TextbookEdition.code).where(m.TextbookEdition.org_id == org_id)))
    topics = set()
    if dataset.program_version_id:
        topics = set(session.scalars(select(m.Topic.code).where(m.Topic.program_version_id == dataset.program_version_id)))
    cohorts = {c.code: c for c in session.scalars(select(m.Cohort).where(m.Cohort.dataset_id == dataset.id))}
    existing = dict(session.execute(select(m.Learner.code, m.Cohort.code).join(m.Cohort, m.Cohort.id == m.Learner.cohort_id)
                                    .where(m.Learner.dataset_id == dataset.id)).all())
    seen: dict[str, str] = {}
    class_school: dict[str, str] = {c.code: c.school_id for c in cohorts.values()}
    for r in rows:
        v = r.values
        for f in ("school_code", "class_code", "learner_code", "teacher_code", "edition_code"):
            _ok_code(r, f)
        lc, cc = v.get("learner_code"), v.get("class_code")
        if lc in seen and seen[lc] != cc:
            r.errors.append({"code": "learner_class_conflict", "field": "class_code", "existing": seen[lc]})
        elif lc in seen:
            r.errors.append({"code": "duplicate_row", "field": "learner_code"})
        seen.setdefault(lc, cc)
        if lc in existing and existing[lc] != cc:
            r.errors.append({"code": "learner_class_conflict", "field": "class_code", "existing": existing[lc]})
        if v.get("edition_code") and v["edition_code"] not in editions:
            r.errors.append({"code": "unknown_edition", "field": "edition_code", "value": v["edition_code"]})
        if v.get("topic_codes"):
            if not dataset.program_version_id:
                r.errors.append({"code": "missing_dependency", "field": "topic_codes", "dependency": "program"})
            for t in [x.strip() for x in v["topic_codes"].split(";") if x.strip()]:
                if topics and t not in topics:
                    r.errors.append({"code": "unknown_topic", "field": "topic_codes", "value": t})
        if v.get("language") and v["language"] not in ("ru", "kz", "en"):
            r.errors.append({"code": "invalid_value", "field": "language"})
        _int(r, "grade", 1, 12)
        for f in ("period_start", "period_end"):
            if v.get(f):
                try:
                    date.fromisoformat(v[f])
                except ValueError:
                    r.errors.append({"code": "invalid_date", "field": f})
        _ = class_school
    if editions == set() and any(r.values.get("edition_code") for r in rows):
        blocking.append({"code": "missing_dependency", "dependency": "editions", "message": DEPENDENCY_TEXT["editions"]})


def _v_assignments(session, dataset, org_id, rows, blocking) -> None:
    from .. import measurement_models as mm

    assessments = {a.code: a.id for a in session.scalars(select(m.Assessment).where(m.Assessment.dataset_id == dataset.id))}
    cohorts = {c.code: c.id for c in session.scalars(select(m.Cohort).where(m.Cohort.dataset_id == dataset.id))}
    if not assessments:
        blocking.append({"code": "missing_dependency", "dependency": "responses", "message": DEPENDENCY_TEXT["responses"]})
    existing = set(session.execute(select(mm.AssessmentCohort.assessment_id, mm.AssessmentCohort.cohort_id)
                                   .where(mm.AssessmentCohort.dataset_id == dataset.id)).all())
    seen = set()
    for r in rows:
        v = r.values
        for f in ("assessment_code", "class_code"):
            _ok_code(r, f)
        a, c = assessments.get(v.get("assessment_code")), cohorts.get(v.get("class_code"))
        if v.get("assessment_code") and a is None:
            r.errors.append({"code": "unknown_assessment", "field": "assessment_code", "value": v["assessment_code"]})
        if v.get("class_code") and c is None:
            r.errors.append({"code": "unknown_class", "field": "class_code", "value": v["class_code"]})
        key = (v.get("assessment_code"), v.get("class_code"))
        if key in seen:
            r.errors.append({"code": "duplicate_row", "field": "class_code"})
        seen.add(key)
        if a and c and (a, c) in existing:
            r.errors.append({"code": "already_assigned", "field": "class_code"})


# ---------------------------------------------------------------------------
# Commit
# ---------------------------------------------------------------------------


def commit(session: Session, dataset: m.Dataset, batch: m.ImportBatch, kind: str, accepted: list) -> dict:
    fn = {"program": _c_program, "editions": _c_editions, "item_bank": _c_item_bank, "roster": _c_roster,
          "assignments": _c_assignments}[kind]
    return fn(session, dataset, batch, accepted)


def _c_program(session, dataset, batch, rows) -> dict:
    first = rows[0].values
    pv = m.ProgramVersion(org_id=dataset.org_id, subject=first.get("subject") or "—", grade=int(float(first.get("grade") or 0)) or 0,
                          language=first.get("language") or "ru", version=first.get("program_version") or "1",
                          title=first.get("program_title") or first.get("program_code") or dataset.name_ru,
                          source=f"Импорт пользователя: {batch.filename} (sha256 {batch.file_sha256[:12]})", is_demo_codes=False)
    session.add(pv)
    session.flush()
    topics: dict[str, m.Topic] = {}
    objectives: dict[str, m.LearningObjective] = {}
    hours: dict[str, dict] = {}
    for r in rows:
        v = r.values
        tc = v["topic_code"]
        if tc not in topics:
            order = int(float(v["topic_order"])) if v.get("topic_order") else len(topics)
            topics[tc] = m.Topic(program_version_id=pv.id, code=tc, order_index=order, title_ru=v["topic_title_ru"],
                                 title_kz=v.get("topic_title_kz") or v["topic_title_ru"], kz_verified=bool(v.get("topic_title_kz")))
            session.add(topics[tc])
            session.flush()
        h = hours.setdefault(tc, {})
        for f in ("hours_current", "hours_min", "hours_max", "hours_elapsed"):
            if v.get(f) and f not in h:
                h[f] = int(float(v[f]))
        o = m.LearningObjective(program_version_id=pv.id, topic_id=topics[tc].id, code=v["objective_code"],
                                text_ru=v["objective_text_ru"], text_kz=v.get("objective_text_kz") or v["objective_text_ru"],
                                kz_verified=bool(v.get("objective_text_kz")))
        session.add(o)
        objectives[o.code] = o
    session.flush()
    n_rel = 0
    for r in rows:
        for p in [x.strip() for x in r.values.get("prerequisite_codes", "").split(";") if x.strip()]:
            session.add(m.ObjectiveRelation(source_objective_id=objectives[p].id,
                                            target_objective_id=objectives[r.values["objective_code"]].id,
                                            relation_type="prerequisite", confirmed=True))
            n_rel += 1
    dataset.program_version_id = pv.id
    plan_rows = 0
    if any("hours_current" in h for h in hours.values()):
        plan = m.TeachingPlan(org_id=dataset.org_id, dataset_id=dataset.id, plan_group_id=new_id(), version=1,
                              name="Действующий план часов (импорт)", scope=dataset.name_ru, horizon="из файла программы",
                              status="current")
        session.add(plan)
        session.flush()
        for tc, h in hours.items():
            if "hours_current" not in h:
                continue
            session.add(m.PlanTopicHours(plan_id=plan.id, topic_id=topics[tc].id, planned_hours=h["hours_current"],
                                         elapsed_hours=h.get("hours_elapsed", 0), min_hours=h.get("hours_min"),
                                         max_hours=h.get("hours_max")))
            plan_rows += 1
    return {"program_version_id": pv.id, "topics": len(topics), "objectives": len(objectives), "prerequisites": n_rel,
            "plan_topics": plan_rows}


def _c_editions(session, dataset, batch, rows) -> dict:
    existing = {e.code for e in session.scalars(select(m.TextbookEdition).where(m.TextbookEdition.org_id == dataset.org_id))}
    created = 0
    for r in rows:
        v = r.values
        if v["edition_code"] in existing:
            continue
        session.add(m.TextbookEdition(org_id=dataset.org_id, code=v["edition_code"], title=v["title"],
                                      edition_label=v.get("edition_label") or "", year=int(float(v["year"])) if v.get("year") else 0,
                                      language=v.get("language") or "ru", grade=int(float(v["grade"])) if v.get("grade") else 0,
                                      is_demo=False, usage_permission=v.get("usage_permission") or ""))
        created += 1
    return {"editions_created": created, "editions_existing": len(rows) - created}


def _c_item_bank(session, dataset, batch, rows) -> dict:
    pv = dataset.program_version_id
    objs = {o.code: o for o in session.scalars(select(m.LearningObjective).where(m.LearningObjective.program_version_id == pv))}
    scales = {s.code: s for s in session.scalars(select(m.Scale).where(m.Scale.org_id == dataset.org_id))}
    forms: dict[str, m.AssessmentForm] = {}
    items: dict[str, m.Item] = {}
    n_links = n_fi = 0
    positions: dict[str, int] = defaultdict(int)
    for r in rows:
        v = r.values
        scode = v.get("scale_code") or v["form_code"]
        if scode not in scales:
            scales[scode] = m.Scale(org_id=dataset.org_id, code=scode, name=v.get("scale_name") or scode,
                                    linking_method=v.get("scale_linking") or "identical_form",
                                    description="Импорт пользователя")
            session.add(scales[scode])
            session.flush()
        fcode = v["form_code"]
        if fcode not in forms:
            forms[fcode] = m.AssessmentForm(program_version_id=pv, code=fcode, name=v.get("form_name") or fcode,
                                            scale_id=scales[scode].id, stage_hint=v.get("form_stage") or "post")
            session.add(forms[fcode])
            session.flush()
        icode = v["item_code"]
        if icode not in items:
            options = parse_pairs(v.get("options") or "")
            mis = dict(parse_pairs(v.get("misconceptions") or ""))
            key = (v.get("answer_key") or "").upper()
            itype = v.get("item_type") or ("single_choice" if options else "open")
            items[icode] = m.Item(program_version_id=pv, code=icode, version=1, item_type=itype,
                                  stem_ru=v.get("stem_ru") or icode, stem_kz=v.get("stem_kz") or v.get("stem_ru") or icode,
                                  options=[{"key": k, "text": t, "correct": k == key, "misconception": mis.get(k)} for k, t in options],
                                  answer_key=key if itype == "single_choice" else (v.get("answer_key") or ""),
                                  max_points=float(v["max_points"].replace(",", ".")), kz_verified=bool(v.get("stem_kz")))
            session.add(items[icode])
            session.flush()
            for code, w in parse_weights(v["objective_codes"]):
                session.add(m.ItemObjective(item_id=items[icode].id, objective_id=objs[code].id, weight=w,
                                            status=v.get("mapping_status") or "confirmed", origin="import",
                                            org_id=dataset.org_id))
                n_links += 1
        positions[fcode] += 1
        session.add(m.FormItem(form_id=forms[fcode].id, item_id=items[icode].id,
                               position=int(float(v["position"])) if v.get("position") else positions[fcode]))
        n_fi += 1
    return {"forms": len(forms), "items": len(items), "item_objective_links": n_links, "form_items": n_fi,
            "scales": len({(r.values.get("scale_code") or r.values["form_code"]) for r in rows})}


def _c_roster(session, dataset, batch, rows) -> dict:
    from .imports import _EntityCache, program_index

    idx = program_index(session, dataset.org_id, dataset.program_version_id) if dataset.program_version_id else _empty_index()
    ctx = _EntityCache(session, dataset, idx)
    editions = {e.code: e for e in session.scalars(select(m.TextbookEdition).where(m.TextbookEdition.org_id == dataset.org_id))}
    topics = {t.code: t for t in (ctx.idx.topics or [])}
    before = len(ctx.learners)
    exposures = 0
    for r in rows:
        v = dict(r.values)
        learner = ctx.learner(v)
        if v.get("school_name"):
            sc = ctx.schools.get(v["school_code"])
            if sc is not None and sc.name == sc.code:
                sc.name = v["school_name"][:200]
        if v.get("edition_code"):
            ed = editions[v["edition_code"]]
            tcodes = [x.strip() for x in v.get("topic_codes", "").split(";") if x.strip()] or list(topics)
            y0 = _year(v.get("academic_year"))
            start = date.fromisoformat(v["period_start"]) if v.get("period_start") else date(y0, 9, 1)
            end = date.fromisoformat(v["period_end"]) if v.get("period_end") else date(y0 + 1, 5, 31)
            for tc in tcodes:
                t = topics.get(tc)
                if t is None or (learner.cohort_id, t.id) in ctx.exposures:
                    continue
                ctx.exposures.add((learner.cohort_id, t.id))
                session.add(m.MaterialExposure(org_id=dataset.org_id, dataset_id=dataset.id, cohort_id=learner.cohort_id,
                                               edition_id=ed.id, topic_id=t.id, period_start=start, period_end=end,
                                               usage_level="primary"))
                exposures += 1
    return {"learners_created": len(ctx.learners) - before, "classes": len(ctx.cohorts), "schools": len(ctx.schools),
            "exposures": exposures}


def _c_assignments(session, dataset, batch, rows) -> dict:
    from .. import measurement_models as mm

    assessments = {a.code: a.id for a in session.scalars(select(m.Assessment).where(m.Assessment.dataset_id == dataset.id))}
    cohorts = {c.code: c.id for c in session.scalars(select(m.Cohort).where(m.Cohort.dataset_id == dataset.id))}
    n = 0
    for r in rows:
        v = r.values
        session.add(mm.AssessmentCohort(org_id=dataset.org_id, dataset_id=dataset.id, assessment_id=assessments[v["assessment_code"]],
                                        cohort_id=cohorts[v["class_code"]], source="import", created_by=batch.created_by,
                                        note=(v.get("note") or f"Импорт {batch.filename}")[:500]))
        n += 1
    return {"assignments_created": n, "assessments": len({r.values["assessment_code"] for r in rows})}


def _year(s: str | None) -> int:
    try:
        return int((s or "")[:4])
    except ValueError:
        return date.today().year


def _empty_index():
    from .imports import ProgramIndex

    return ProgramIndex(items={}, forms={}, form_items={}, editions={}, topics=[])


def template_rows(kind: str) -> list[list[str]]:
    docs = FIELD_DOCS[kind] if kind in FIELD_DOCS else RESPONSES_DOCS
    return [list(docs.keys()), [ex for _, _, ex in docs.values()]]


def docs_for(kind: str) -> dict:
    return FIELD_DOCS.get(kind) or RESPONSES_DOCS
