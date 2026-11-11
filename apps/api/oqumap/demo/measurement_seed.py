"""Synthetic demo for the measurement & learning loop (idempotent, deterministic content).

Adds to the demo organisation (all data SYNTHETIC, fictional schools/classes/learners):
* scale ``S-T3-DIAG`` and form ``F-T3-DIAG`` (12 items on topic T3) with deliberately varied quality:
  Q03 two defensible answers (only the reduced form is keyed → suspicious distractor), Q05 a wrong answer key
  (negative discrimination), Q07 a distractor nobody chooses (non-functional), Q09 very easy, Q11 long item with
  many omissions, Q12 very hard; the other items behave well;
* dataset ``measurement_loop`` (2026–2027, 6 schools × 4 classes) imported through the regular pipeline:
  PRE-2026M (F-PRE), DIAG-BASE and DIAG-END (both F-T3-DIAG → identical form, paired change measurable);
* 6 interventions (practice_based / observational / experimental; reviewed, draft, archived, a v2 revision);
* language DIF demo: M05/M06 classes are Kazakh-medium; Q10 is deliberately harder for them (screening signal),
  Q08 behaves the same in both groups;
* pilots: PIL-M01 completed matched comparison with full fidelity (known synthetic effect +0.8 logit on the
  6А classes → expected ``positive_signal``), PIL-M02 completed single group with low fidelity (expected
  ``invalid_due_to_fidelity`` — never "ineffective"), PIL-M03 active with partial logs and no outcome yet
  (``needs_more_data``), PIL-M04 draft cluster-randomised protocol with too few clusters (cannot become ready);
* a conclusion for PIL-M01 with an accepted evidence entry and a draft next decision.

Mechanism: θ = school + class + N(0,1); DIAG logit = 1.2·(θ + growth·[end] + effect·[end] − b_item);
omission p = 0.02 + 0.04·σ(−θ) (+0.25 on Q11); absence 3% per assessment. Seed 20261020.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import measurement_models as mm
from .. import models as m
from ..db import stable_id
from ..schemas import interventions as S
from ..services import fidelity as fid
from ..services import imports as imp
from ..services import interventions as ivs
from ..services import learning_loop as loop
from ..services import pilots as pls
from ..services import sessions as cal
from ..services.auth import Principal
from . import generator as gen
from .content import FORMS, ITEMS_BY_CODE, PROGRAM

DATASET_CODE = "measurement_loop"
SEED = 20261020
FORM_CODE = "F-T3-DIAG"
SCALE_CODE = "S-T3-DIAG"
O = "DEMO-M6-"  # noqa: E741

# code, objective, stem_ru, stem_kz, [(text, misconception|None)], key letter, difficulty, behaviour
DIAG_ITEMS = [
    ("Q01", "3.1", "Вычислите: 1/4 + 2/4.", "Есептеңіз: 1/4 + 2/4.",
     [("3/4", None), ("3/8", "add_across"), ("2/16", "multiplied_instead"), ("1/4", "calc_error")], "A", -1.0, None),
    ("Q02", "3.1", "Вычислите: 1/3 + 1/6.", "Есептеңіз: 1/3 + 1/6.",
     [("2/9", "add_across"), ("1/2", None), ("2/6", "numerators_not_scaled"), ("1/18", "multiplied_instead")], "B", 0.0, None),
    ("Q03", "3.1", "Какая дробь равна разности 5/6 − 1/3?", "5/6 − 1/3 айырмасына қай бөлшек тең?",
     [("1/2", None), ("3/6", "incomplete_simplification"), ("4/3", "subtract_across"), ("4/6", "numerators_not_scaled")],
     "A", 0.2, "two_defensible"),
    ("Q04", "3.2", "Вычислите: 1 1/2 + 2 1/4.", "Есептеңіз: 1 1/2 + 2 1/4.",
     [("3 2/6", "add_across"), ("3 3/4", None), ("3 2/4", "numerators_not_scaled"), ("4 3/4", "whole_part_error")], "B", 0.3, None),
    ("Q05", "3.1", "Вычислите: 3/5 − 1/5.", "Есептеңіз: 3/5 − 1/5.",
     [("2/5", None), ("4/5", "wrong_operation"), ("2/10", "denominators_added"), ("3/25", "multiplied_instead")],
     "C", -0.5, "wrong_key"),
    ("Q06", "3.2", "Вычислите: 3 − 1 1/3.", "Есептеңіз: 3 − 1 1/3.",
     [("2 1/3", "mixed_subtract_reverse"), ("1 2/3", None), ("2 2/3", "borrow_error"), ("1 1/3", "whole_part_error")], "B", 0.5, None),
    ("Q07", "3.1", "Вычислите: 2/7 + 3/7.", "Есептеңіз: 2/7 + 3/7.",
     [("5/7", None), ("5/14", "add_across"), ("6/49", "multiplied_instead"), ("7/5", "inverted")], "A", -0.5, "dead_distractor"),
    ("Q08", "3.3", "Вася съел 1/4 пирога, Петя — 1/3 пирога. Какую часть пирога они съели вместе?",
     "Вася бәліштің 1/4 бөлігін, Петя 1/3 бөлігін жеді. Олар бірге бәліштің қандай бөлігін жеді?",
     [("2/7", "add_across"), ("7/12", None), ("2/12", "numerators_not_scaled"), ("5/12", "answered_complement")], "B", 0.4, None),
    ("Q09", "3.1", "Вычислите: 1/2 + 1/2.", "Есептеңіз: 1/2 + 1/2.",
     [("1", None), ("2/4", "add_across"), ("1/4", "multiplied_instead"), ("1/2", "calc_error")], "A", -3.0, None),
    ("Q10", "3.3", "В бутылке было 3/4 л сока, выпили 1/2 л. Сколько сока осталось?",
     "Бөтелкеде 3/4 л шырын болды, 1/2 л ішті. Қанша шырын қалды?",
     [("2/2", "subtract_across"), ("2/4", "numerators_not_scaled"), ("1/4", None), ("5/4", "wrong_operation")], "C", 0.2, "dif_kz"),
    ("Q11", "3.3", "От ленты длиной 5/6 м отрезали сначала 1/4 м, затем ещё 1/3 м. Сколько метров ленты осталось?",
     "Ұзындығы 5/6 м таспадан алдымен 1/4 м, сосын тағы 1/3 м кесіп алды. Таспаның неше метрі қалды?",
     [("1/4", None), ("7/12", "answered_complement"), ("3/7", "subtract_across"), ("1/12", "calc_error")], "A", 0.6, "long_item"),
    ("Q12", "3.2", "Вычислите: 2 5/6 − 1 7/8.", "Есептеңіз: 2 5/6 − 1 7/8.",
     [("23/24", None), ("1 1/24", "mixed_subtract_reverse"), ("1 2/24", "borrow_error"), ("23/48", "calc_error")], "A", 3.0, None),
]
LETTERS = ["A", "B", "C", "D"]

SCHOOLS = [("M01", 0.4), ("M02", -0.3), ("M03", 0.2), ("M04", -0.1), ("M05", 0.0), ("M06", 0.3)]
CLASS_EFFECT_ON_END = {0: 0.8, 1: 0.0, 2: 0.15, 3: 0.0, 4: 0.0}  # 6А pilot 1, 6Б comparison, 6В pilot 2, 6Г pilot 3, 6Д none
GROWTH = 0.35
# Language DIF demo: classes of M05/M06 are taught in Kazakh; Q10 (a word problem) is made harder for them only
# (+1.5 logit, e.g. an unclear translation). Q08 (also a word problem) has no shift → the "normal" example.
KZ_SCHOOLS = {"M05", "M06"}
KZ_DIF_SHIFT = 1.5
ASSESSMENTS = [("PRE-2026M", "F-PRE", "2026-09-07"), ("DIAG-BASE", FORM_CODE, "2026-09-14"), ("DIAG-END", FORM_CODE, "2026-10-30")]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def generate_rows(seed: int = SEED) -> list[dict]:
    rng = np.random.default_rng(seed)
    sc = gen.Scenario(code=DATASET_CODE, seed=seed, schools=[], assessments=[], edition_effects={})
    rows: list[dict] = []
    n = 0
    for school, s_eff in SCHOOLS:
        # M06 has a 5th class (6Д) whose DIAG-END results were never submitted: it is explicitly assigned to that
        # assessment but has no sitting record at all (shows as "no sitting record" in Quality Lab). Generated last,
        # so it does not change the random stream of the other classes.
        for ci in range(5 if school == "M06" else 4):
            cls = f"{school}-6{gen.LETTERS_RU[ci]}"
            size = int(rng.integers(22, 29))
            c_eff = float(rng.normal(0, 0.2))
            for _ in range(size):
                n += 1
                theta = s_eff + c_eff + float(rng.normal(0, 1))
                language = "kz" if school in KZ_SCHOOLS else "ru"
                base = dict(school_code=school, class_code=cls, teacher_code=f"T-{school}-{ci + 1}", language=language, grade=6,
                            academic_year="2026-2027", edition_code="EDA" if ci % 2 == 0 else "EDB", learner_code=f"ML{n:04d}")
                for acode, form, day in ASSESSMENTS:
                    if ci == 4 and acode == "DIAG-END":
                        continue
                    common = dict(base, assessment_code=acode, form_code=form, date=day)
                    if rng.random() < 0.03:
                        rows.append(dict(common, item_code="", attempt=1, status="absent", score="", response=""))
                        continue
                    if form == "F-PRE":
                        for code in FORMS["F-PRE"]["items"]:
                            rows.append(dict(common, item_code=code, attempt=1,
                                             **gen._answer(rng, sc, ITEMS_BY_CODE[code], theta, "pre", base["edition_code"])))
                        continue
                    end = acode == "DIAG-END"
                    shift = (GROWTH + CLASS_EFFECT_ON_END[ci]) if end else 0.0
                    for code, _obj, _ru, _kz, opts, key, b, beh in DIAG_ITEMS:
                        b_eff = b + (KZ_DIF_SHIFT if (beh == "dif_kz" and language == "kz") else 0.0)
                        rows.append(dict(common, item_code=code, attempt=1, **_diag_answer(rng, theta + shift, opts, key, b_eff, beh)))
    return rows


def _diag_answer(rng, theta: float, opts, key: str, b: float, beh: str | None) -> dict:
    p_omit = 0.02 + 0.04 * _sigmoid(-theta) + (0.25 if beh == "long_item" else 0.0)
    if rng.random() < p_omit:
        return {"status": "omitted", "score": "", "response": ""}
    true_key = "A" if beh == "wrong_key" else key  # Q05: the bank key is wrong, the mathematically correct option is A
    if rng.random() < _sigmoid(1.2 * (theta - b)):
        if beh == "two_defensible":
            return {"status": "answered", "score": "", "response": "A" if rng.random() < 0.5 else "B"}
        return {"status": "answered", "score": "", "response": true_key}
    letters, weights = [], []
    for letter, (_t, tag) in zip(LETTERS, opts, strict=True):
        if letter == true_key or (beh == "two_defensible" and letter == "B"):
            continue
        if beh == "dead_distractor" and letter == "D":
            continue
        letters.append(letter)
        weights.append(2.0 if tag in ("add_across", "numerators_not_scaled", "mixed_subtract_reverse") else 1.0)
    pw = np.array(weights) / sum(weights)
    return {"status": "answered", "score": "", "response": letters[int(rng.choice(len(letters), p=pw))]}


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------


def _ref(session: Session, org_id: str, entity: str, code: str) -> str:
    """ID of the organisation's programme / topic / objective by code (integration: works for the seeded template
    and for disposable demo tenants, whose programme rows are clones with remapped IDs)."""
    pv = session.scalar(select(m.ProgramVersion.id).where(m.ProgramVersion.org_id == org_id, m.ProgramVersion.title == PROGRAM["title"],
                                                         m.ProgramVersion.version == PROGRAM["version"]))
    if pv is None:
        raise RuntimeError("measurement seed needs the demo programme in the organisation")
    if entity == "program":
        return pv
    model = m.Topic if entity == "topic" else m.LearningObjective
    rid = session.scalar(select(model.id).where(model.program_version_id == pv, model.code == code))
    if rid is None:
        raise RuntimeError(f"{entity} {code} not found in the demo programme")
    return rid


def _seed_form(session: Session, org_id: str) -> None:
    pv_id = _ref(session, org_id, "program", PROGRAM["code"])
    if session.scalar(select(m.AssessmentForm.id).where(m.AssessmentForm.program_version_id == pv_id,
                                                        m.AssessmentForm.code == FORM_CODE)) is not None:
        return  # a demo tenant already has the form and items (cloned with the template programme)
    if session.scalar(select(m.Scale).where(m.Scale.code == SCALE_CODE)) is None:
        session.add(m.Scale(id=stable_id("scale", SCALE_CODE), code=SCALE_CODE, name="Диагностика T3 (одна форма, до и после)",
                            linking_method="identical_form",
                            description="Одна и та же форма до и после пилота; изменение измеримо на одной шкале."))
        session.flush()
    fid_ = stable_id(org_id, "form", FORM_CODE)
    session.add(m.AssessmentForm(id=fid_, program_version_id=pv_id, code=FORM_CODE, name="Диагностика по теме T3 (12 заданий)",
                                 scale_id=stable_id("scale", SCALE_CODE), stage_hint="followup"))
    session.flush()
    for code, obj, ru, kz, opts, key, _b, _beh in DIAG_ITEMS:
        iid = stable_id(org_id, "item", code)
        session.add(m.Item(id=iid, program_version_id=pv_id, code=code, version=1, item_type="single_choice", stem_ru=ru, stem_kz=kz,
                           options=[{"key": letter, "text": t, "correct": letter == key, "misconception": tag}
                                    for letter, (t, tag) in zip(LETTERS, opts, strict=True)],
                           answer_key=key, max_points=1.0))
        session.add(m.ItemObjective(id=stable_id(org_id, "io", code, O + obj), item_id=iid, objective_id=_ref(session, org_id, "objective", O + obj),
                                    weight=1.0, status="confirmed", origin="item_bank_author", org_id=org_id))
    session.flush()  # items before form items (no ORM relationships → explicit ordering)
    for pos, (code, *_rest) in enumerate(DIAG_ITEMS, start=1):
        session.add(m.FormItem(id=stable_id(org_id, "fi", FORM_CODE, code), form_id=fid_, item_id=stable_id(org_id, "item", code),
                               position=pos))
    session.flush()


def _seed_dataset(session: Session, org: m.Organization) -> m.Dataset:
    csv_text = gen.to_csv(generate_rows())
    ds = m.Dataset(id=stable_id(org.id, "dataset", DATASET_CODE), org_id=org.id,
                   program_version_id=_ref(session, org.id, "program", PROGRAM["code"]), code=DATASET_CODE,
                   name_ru="Контур измерения и обучения: диагностика T3 и пилоты, 2026–2027",
                   name_kz="Өлшеу және оқу контуры: T3 диагностикасы және пилоттар, 2026–2027",
                   description_ru="Синтетический набор: 6 школ × 4 класса, входная проверка, диагностика T3 до и после пилотов. "
                                  "Форма диагностики содержит задания с заведомыми проблемами качества (см. MANIFEST).",
                   description_kz="Синтетикалық жиынтық: 6 мектеп × 4 сынып, пилотқа дейін және кейін T3 диагностикасы.",
                   is_synthetic=True, scenario=DATASET_CODE, version=0,
                   manifest={"generator": "oqumap.demo.measurement_seed", "seed": SEED, "growth_logit": GROWTH,
                             "class_effect_on_end_logit": {"6А (PIL-M01)": 0.8, "6Б (comparison)": 0.0, "6В (PIL-M02)": 0.15, "6Г": 0.0},
                             "language_dif": {"kz_schools": sorted(KZ_SCHOOLS), "item": "Q10", "shift_logit": KZ_DIF_SHIFT,
                                              "control_item": "Q08"},
                             "problem_items": {"Q03": "two_defensible_answers", "Q05": "wrong_answer_key", "Q07": "non_functional_distractor",
                                               "Q09": "very_easy", "Q11": "high_omission", "Q12": "very_hard"},
                             "expected_behaviour": ["PIL-M01 positive_signal", "PIL-M02 invalid_due_to_fidelity",
                                                    "PIL-M03 needs_more_data", "PIL-M04 cannot_be_ready"]})
    session.add(ds)
    session.commit()
    batch = imp.validate_upload(session, org=org, user_id=None, data=csv_text.encode("utf-8"), filename=f"{DATASET_CODE}.csv",
                                kind="responses", dataset_id=ds.id, new_dataset=None, sheet=None, mapping=None, options={})
    if batch.rows_rejected:
        raise RuntimeError(f"measurement dataset has rejected rows: {batch.report.get('errors_by_code')}")
    imp.commit_batch(session, org.id, batch.id, None)
    session.refresh(ds)
    # explicit assignment: every class of the dataset is assigned to every assessment (6Д included for DIAG-END)
    for a in session.scalars(select(m.Assessment).where(m.Assessment.dataset_id == ds.id)):
        for c in session.scalars(select(m.Cohort).where(m.Cohort.dataset_id == ds.id)):
            session.add(mm.AssessmentCohort(org_id=org.id, dataset_id=ds.id, assessment_id=a.id, cohort_id=c.id, source="seed"))
    session.commit()
    return ds


def _iv(code, title_ru, title_kz, targets, level, *, minutes=20, per_week=3, weeks=5, desc="", instr="", limits="", contra="",
        resources=(), links=()):
    return S.InterventionCreate(
        code=code, title_ru=title_ru, title_kz=title_kz, description_ru=desc, description_kz="", grades=[6], languages=["ru", "kz"],
        minutes_per_session=minutes, sessions_per_week=per_week, duration_weeks=weeks, cadence_ru=f"{per_week} раза в неделю по {minutes} мин",
        instructions_ru=instr, instructions_kz="", resources=list(resources), evidence_level=level,
        evidence_links=[S.EvidenceLink(title=t, url=u, kind=k) for t, u, k in links], contraindications_ru=contra,
        limitations_ru=limits, limitations_kz="", targets=targets)


_SESSION: list[Session] = []  # the session of the running seed (set in seed_measurement)


def _t(org_id: str, kind: str, code: str) -> S.TargetIn:
    if kind == "misconception":
        return S.TargetIn(target_type="misconception", misconception_code=code)
    entity = "topic" if kind == "topic" else "objective"
    return S.TargetIn(target_type=kind, target_id=_ref(_SESSION[-1], org_id, entity, code))


def _weekly_dates(start: date, end: date, weekdays: tuple[int, ...]) -> list[date]:
    out, d = [], start
    while d <= end:
        if d.weekday() in weekdays:
            out.append(d)
        d += timedelta(days=1)
    return out


def seed_measurement(session: Session, org_id: str, user_id: str | None = None) -> dict:
    """Idempotent: does nothing when the dataset already exists. ``user_id`` — the methodist acting in the organisation
    (default: the demo template's methodist; a disposable demo tenant passes its own user)."""
    if session.scalar(select(m.Dataset).where(m.Dataset.org_id == org_id, m.Dataset.code == DATASET_CODE)) is not None:
        return {"status": "exists"}
    _SESSION.append(session)
    try:
        return _seed_measurement(session, org_id, user_id)
    finally:
        _SESSION.pop()


def _seed_measurement(session: Session, org_id: str, user_id: str | None) -> dict:
    org = session.get(m.Organization, org_id)
    user = session.get(m.User, user_id or stable_id("user", "demo-methodist"))
    p = Principal(user, org)  # demo methodist holds methodist + approver roles
    _seed_form(session, org_id)
    session.commit()
    ds = _seed_dataset(session, org)

    lib = {}
    lib["INT-STRIPS"] = ivs.create(session, p, _iv(
        "INT-STRIPS", "Модель «полоса дробей» при сложении дробей с разными знаменателями",
        "Әртүрлі бөлімді бөлшектерді қосуда «бөлшек жолағы» моделі",
        [_t(org_id, "objective", O + "3.1"), _t(org_id, "misconception", "add_across"), _t(org_id, "misconception", "numerators_not_scaled")],
        "observational", desc="Ученики складывают дроби, сначала изображая обе дроби на полосах одинаковой длины.",
        instr="1) Разминка: изобразить две дроби на полосах (5 мин). 2) Найти общее деление полос (5 мин). "
              "3) Сложить и записать результат (7 мин). 4) Проверка соседом по чек-листу (3 мин).",
        limits="Наблюдательные данные демо-сети; эффект не установлен экспериментально.",
        contra="Не заменяет отработку алгоритма; не применять как единственный формат дольше 6 недель.",
        resources=["Полосы дробей (распечатка)", "Чек-лист самопроверки"],
        links=[("Внутренний отчёт демо-сети о наблюдениях (синтетический)", "doc:demo-strips-observations", "internal")]))
    lib["INT-PEER"] = ivs.create(session, p, _iv(
        "INT-PEER", "Взаимная проверка шагов решения в парах", "Жұптасып шешім қадамдарын өзара тексеру",
        [_t(org_id, "objective", O + "3.2"), _t(org_id, "objective", O + "3.3")], "practice_based",
        desc="Пары по очереди объясняют шаги решения и проверяют их по карточке.",
        instr="Пары по 2 ученика; карточка из 4 шагов; учитель обходит пары и фиксирует типичные ошибки.",
        limits="Основано на практике учителей; систематической оценки нет.", resources=["Карточки шагов"]))
    lib["INT-NUMLINE"] = ivs.create(session, p, _iv(
        "INT-NUMLINE", "Числовая прямая для вычитания смешанных чисел", "Аралас сандарды азайтуға арналған сандық түзу",
        [_t(org_id, "objective", O + "3.2"), _t(org_id, "misconception", "mixed_subtract_reverse"), _t(org_id, "misconception", "borrow_error")],
        "experimental", minutes=25, per_week=2, weeks=8,
        desc="Вычитание смешанных чисел как «движение» по числовой прямой с занятием единицы.",
        instr="Каждое занятие: 2 примера с прямой, 3 — без прямой, 1 — объяснение ошибки.",
        limits="Ссылка на экспериментальные данные — демонстрационная запись; перед реальным применением проверить источник.",
        links=[("Демонстрационная запись об экспериментальной проверке (синтетическая)", "doc:demo-numline-trial", "internal")]))
    lib["INT-ERRDIAG"] = ivs.create(session, p, _iv(
        "INT-ERRDIAG", "Короткие диагностические задания по типичным ошибкам", "Типтік қателер бойынша қысқа диагностикалық тапсырмалар",
        [_t(org_id, "topic", "T2"), _t(org_id, "topic", "T3")], "practice_based", minutes=10, per_week=2, weeks=4,
        desc="Черновик: 5-минутные проверки гипотез о типичных ошибках перед уроком."))
    lib["INT-WORKED"] = ivs.create(session, p, _iv(
        "INT-WORKED", "Разобранные примеры с самопроверкой", "Өзін-өзі тексеретін талданған мысалдар",
        [_t(org_id, "topic", "T4"), _t(org_id, "objective", O + "4.2")], "observational", minutes=15, per_week=2, weeks=6,
        instr="Пара «разобранный пример — похожая задача», самопроверка по ключу в конце.",
        limits="Наблюдательные данные; не проверялось на теме T4 в демо-сети."))
    lib["INT-OLDDRILL"] = ivs.create(session, p, _iv(
        "INT-OLDDRILL", "Тренировочные карточки без обратной связи", "Кері байланыссыз жаттығу карточкалары",
        [_t(org_id, "topic", "T3")], "practice_based", instr="Карточки по 10 примеров без разбора ошибок."))
    for code in ("INT-STRIPS", "INT-PEER", "INT-NUMLINE", "INT-WORKED", "INT-OLDDRILL"):
        ivs.review(session, p, lib[code]["id"], 1, S.ReviewRequest(note="Демо: рецензия методического совета"))
    ivs.archive(session, p, lib["INT-OLDDRILL"]["id"], S.ArchiveRequest(reason="Заменено интервенциями с обратной связью (INT-PEER)."))

    cohorts = {c.code: c.id for c in session.scalars(select(m.Cohort).where(m.Cohort.dataset_id == ds.id))}
    assess = {a.code: a.id for a in session.scalars(select(m.Assessment).where(m.Assessment.dataset_id == ds.id))}
    letter = gen.LETTERS_RU
    t3 = _ref(session, org_id, "topic", "T3")

    def group(ci):
        return [cohorts[f"{s}-6{letter[ci]}"] for s, _ in SCHOOLS]

    plan = S.AnalysisPlan(adjustment="baseline_strata", strata_scheme="pre_three_level", min_matched_learners=30,
                          notes="Зарегистрировано до анализа: стандартизация изменений по уровню входной диагностики.")
    p1 = pls.create(session, p, S.PilotCreate(
        dataset_id=ds.id, title="Полоса дробей в 6А классах (сравнение с 6Б)", intervention_id=lib["INT-STRIPS"]["id"], topic_id=t3,
        objective_id=_ref(session, org_id, "objective", O + "3.1"),
        primary_outcome_ru="Доля баллов по диагностике T3 (цель 3.1): изменение DIAG-BASE → DIAG-END",
        design="matched_comparison", assignment_unit="cohort",
        cohorts=[S.PilotCohortIn(cohort_id=c, arm="intervention") for c in group(0)] + [S.PilotCohortIn(cohort_id=c, arm="comparison") for c in group(1)],
        baseline_assessment_id=assess["DIAG-BASE"], outcome_assessment_id=assess["DIAG-END"], start_date=date(2026, 9, 21),
        end_date=date(2026, 10, 23), follow_up_due=date(2026, 10, 30), owner="Методист (демо)",
        inclusion_criteria="Все 6А классы сети; классы сравнения — 6Б тех же школ.", exclusion_criteria="Нет.", analysis_plan=plan),
        code="PIL-M01")
    p2 = pls.create(session, p, S.PilotCreate(
        dataset_id=ds.id, title="Взаимная проверка в 6В классах", intervention_id=lib["INT-PEER"]["id"], topic_id=t3,
        primary_outcome_ru="Доля баллов по диагностике T3: изменение DIAG-BASE → DIAG-END", design="single_group",
        cohorts=[S.PilotCohortIn(cohort_id=c, arm="intervention") for c in group(2)], baseline_assessment_id=assess["DIAG-BASE"],
        outcome_assessment_id=assess["DIAG-END"], start_date=date(2026, 9, 21), end_date=date(2026, 10, 23),
        follow_up_due=date(2026, 10, 30), owner="Методист (демо)", inclusion_criteria="6В классы."), code="PIL-M02")
    p3 = pls.create(session, p, S.PilotCreate(
        dataset_id=ds.id, title="Числовая прямая для смешанных чисел в 6Г классах", intervention_id=lib["INT-NUMLINE"]["id"], topic_id=t3,
        objective_id=_ref(session, org_id, "objective", O + "3.2"),
        primary_outcome_ru="Доля баллов по цели 3.2 на следующей диагностике T3", design="single_group",
        cohorts=[S.PilotCohortIn(cohort_id=c, arm="intervention") for c in group(3)], baseline_assessment_id=assess["DIAG-END"],
        start_date=date(2026, 11, 2), end_date=date(2026, 12, 25), follow_up_due=date(2026, 12, 28), owner="Методист (демо)",
        inclusion_criteria="6Г классы."), code="PIL-M03")
    pls.create(session, p, S.PilotCreate(
        dataset_id=ds.id, title="Кластерная рандомизация полосы дробей по школам (план на 2027)", intervention_id=lib["INT-STRIPS"]["id"],
        topic_id=t3, primary_outcome_ru="Доля баллов по диагностике T3", design="cluster_randomized", assignment_unit="school",
        baseline_assessment_id=assess["DIAG-END"], start_date=date(2027, 1, 18), end_date=date(2027, 3, 12),
        follow_up_due=date(2027, 3, 19), owner="Методист (демо)"), code="PIL-M04")
    p4 = session.scalar(select(mm.Pilot).where(mm.Pilot.org_id == org_id, mm.Pilot.code == "PIL-M04"))
    pls.randomize(session, p, p4.id, S.RandomizeRequest(seed=2027, cohort_ids=[cohorts[f"{s}-6{letter[ci]}"] for s, _ in SCHOOLS[:4] for ci in (0, 1)]))

    # planned session calendars (draft schedules from the cadence, before activation)
    for pl in (p1, p2):
        cal.generate(session, p, pl["id"], S.SessionGenerate())  # Mon/Wed/Fri, 21.09–23.10 → 15 sessions per class
    cal.generate(session, p, p3["id"], S.SessionGenerate(blackout_ranges=[S.DateRange(**{"from": date(2026, 12, 21), "to": date(2026, 12, 25)})]))
    for pl in (p1, p2, p3):
        pls.transition(session, p, pl["id"], S.TransitionRequest(to_status="ready"))
        pls.transition(session, p, pl["id"], S.TransitionRequest(to_status="active", note="Демо: запуск утверждён"))
    rng = np.random.default_rng(SEED + 1)
    sizes = pls._learners_per_cohort(session, group(0) + group(2) + group(3))
    checklist = [("model", "Модель показана"), ("practice", "Самостоятельная практика"), ("check", "Проверка по чек-листу")]
    days1 = _weekly_dates(date(2026, 9, 21), date(2026, 10, 23), (0, 2, 4))  # 15 sessions
    for i, cid in enumerate(group(0)):
        for j, d in enumerate(days1):
            short = (i + j) % 11 == 0
            fid.add_log(session, p, p1["id"], S.FidelityLogCreate(
                cohort_id=cid, session_date=d, planned_minutes=20, delivered_minutes=14 if short else 20, activities_planned=4,
                activities_completed=3 if short else 4, learners_present=sizes[cid] - int(rng.integers(0, 3)), learners_assigned=sizes[cid],
                adherence=[S.AdherenceItem(key=k, label=lbl, done=not (short and k == "check")) for k, lbl in checklist],
                disruption="shortened" if short else "none", source="teacher_log"))
    for cid in group(2):
        for j, d in enumerate(days1[: 9]):
            cancelled = j % 2 == 1
            fid.add_log(session, p, p2["id"], S.FidelityLogCreate(
                cohort_id=cid, session_date=d, planned_minutes=20, delivered_minutes=0 if cancelled else 10, activities_planned=4,
                activities_completed=0 if cancelled else 2, learners_present=None if cancelled else sizes[cid] - 2,
                learners_assigned=sizes[cid],
                adherence=[] if cancelled else [S.AdherenceItem(key=k, label=lbl, done=k == "model") for k, lbl in checklist],
                disruption=("holiday" if j == 3 else "cancelled") if cancelled else "shortened",
                disruption_note="Занятие заменено контрольной работой" if cancelled else "", source="teacher_log"))
    for i, cid in enumerate(group(3)[:4]):
        for d in _weekly_dates(date(2026, 11, 2), date(2026, 11, 6), (1, 3)):
            fid.add_log(session, p, p3["id"], S.FidelityLogCreate(
                cohort_id=cid, session_date=d, planned_minutes=25, delivered_minutes=25 - 5 * (i % 2), activities_planned=3,
                activities_completed=3, learners_present=sizes[cid] - 1, learners_assigned=sizes[cid],
                adherence=[S.AdherenceItem(key=k, label=lbl, done=True) for k, lbl in checklist], source="observation"))
    # PIL-M03: one class had its 05.11 session moved to 13.11 (a reschedule is not a missed session)
    moved = next(x for x in cal.get_calendar(session, p, p3["id"])["sessions"]
                 if x["cohort_id"] == group(3)[5] and x["planned_date"] == "2026-11-05")
    cal.update(session, p, p3["id"], moved["id"], S.SessionPatch(planned_date=date(2026, 11, 13), note="Перенос: экскурсия"))
    for pl in (p1, p2):
        pls.transition(session, p, pl["id"], S.TransitionRequest(to_status="completed", note="Период пилота завершён"))
    o1 = loop.run_follow_up(session, p, p1["id"], S.FollowUpRun())
    loop.run_follow_up(session, p, p2["id"], S.FollowUpRun())
    c1 = loop.create_conclusion(session, p, p1["id"], S.ConclusionCreate(
        outcome_id=o1["id"], decision="continue", decision_basis="evidence_supports",
        acknowledged_limitation_codes=["observational_design", "synthetic_data_only"],
        summary_ru="В 6А классах изменение по цели 3.1 больше, чем в 6Б, при высокой реализации. Дизайн — подобранное сравнение: "
                   "это связь с поправкой на входной уровень, а не доказанный эффект.",
        lessons_ru="Полоса дробей выполнима в формате 3×20 минут; чек-лист самопроверки удобен для журнала реализации.",
        open_questions=["Сохранится ли сигнал в другой когорте и в казахскоязычных классах?",
                        "Даёт ли модель перенос на смешанные числа (цель 3.2)?"],
        create_next_decision_version=True,
        next_action_ru="Продолжить полосу дробей в 6А и запустить кластерно-рандомизированный пилот на 10+ школах (PIL-M04 расширить).",
        propose_evidence_update=True))
    entry = session.scalar(select(mm.InterventionEvidenceEntry).where(mm.InterventionEvidenceEntry.conclusion_id == c1["id"]))
    loop.review_evidence(session, p, entry.id, S.EvidenceReview(accept=True, note="Принято методическим советом (демо)."))
    # revision v2 of INT-STRIPS (reviewed); PIL-M01 keeps its v1 snapshot
    ivs.new_version(session, p, lib["INT-STRIPS"]["id"], S.NewVersionRequest(
        minutes_per_session=25, cadence_ru="3 раза в неделю по 25 мин", change_note="Добавлен этап объяснения ошибки (+5 мин) по итогам PIL-M01."))
    ivs.review(session, p, lib["INT-STRIPS"]["id"], 2, S.ReviewRequest(note="Демо: версия 2 утверждена"))
    return {"status": "created", "dataset_id": ds.id}
