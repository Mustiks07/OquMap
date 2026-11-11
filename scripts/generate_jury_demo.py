#!/usr/bin/env python3
"""Offline deterministic OquMap jury corpus. Production import columns only.

Run with the backend environment: python scripts/generate_jury_demo.py.
No fitted outcomes, rejection sampling, seed search, or row-level score overrides.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/jury_demo"
SYSTEM_FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
REPO_FONT = ROOT / "apps/api/oqumap/assets/fonts/DejaVuSans.ttf"
DEFAULT_FONT = SYSTEM_FONT if SYSTEM_FONT.is_file() else REPO_FONT
SEED = 20261111
LABEL = "Синтетический материал для демонстрации OquMap"
KZ_NOTE = "KZ: перевод не проверен носителем языка"
MC = {
    "M1": ("add_across", "Складывание знаменателей"),
    "M2": ("numerators_not_scaled", "Неверное приведение к общему знаменателю"),
    "M3": ("sign_lost", "Потеря знака"),
    "M4": ("order_error", "Ошибка порядка действий"),
    "M5": ("area_perimeter", "Путаница площади и периметра"),
    "CALC": ("calc_error", "Ошибка выбора действия или вычисления"),
}
TOPICS = [
    ("Обыкновенные дроби", "Жай бөлшектер", 6, 6, 8, 4),
    ("Десятичные дроби", "Ондық бөлшектер", 8, 6, 8, 4),
    ("Пропорции", "Пропорциялар", 6, 6, 6, 3),
    ("Отрицательные числа", "Теріс сандар", 6, 6, 6, 3),
    ("Линейные уравнения", "Сызықтық теңдеулер", 6, 6, 6, 2),
    ("Площадь и периметр", "Аудан және периметр", 6, 6, 6, 2),
]
OBJECTIVES = [
    [
        (
            "Складывать и вычитать дроби с разными знаменателями",
            "Бөлімдері әртүрлі бөлшектерді қосу және азайту",
        ),
        ("Сравнивать и сокращать дроби", "Бөлшектерді салыстыру және қысқарту"),
        ("Умножать и делить дроби", "Бөлшектерді көбейту және бөлу"),
    ],
    [
        ("Складывать десятичные дроби", "Ондық бөлшектерді қосу"),
        ("Вычитать десятичные дроби", "Ондық бөлшектерді азайту"),
        ("Умножать десятичные дроби", "Ондық бөлшектерді көбейту"),
    ],
    [
        ("Решать пропорции", "Пропорцияларды шешу"),
        ("Находить отношение", "Қатынасты табу"),
        ("Применять масштаб", "Масштабты қолдану"),
    ],
    [
        ("Складывать отрицательные числа", "Теріс сандарды қосу"),
        ("Вычитать отрицательные числа", "Теріс сандарды азайту"),
        ("Умножать числа со знаками", "Таңбалы сандарды көбейту"),
    ],
    [
        ("Решать уравнения вида x+a=b", "x+a=b түріндегі теңдеулерді шешу"),
        ("Решать уравнения вида ax=b", "ax=b түріндегі теңдеулерді шешу"),
        ("Соблюдать порядок действий", "Амалдардың ретін сақтау"),
    ],
    [
        ("Находить площадь прямоугольника", "Тіктөртбұрыштың ауданын табу"),
        ("Находить периметр", "Периметрді табу"),
        ("Решать составные задачи", "Құрама есептерді шешу"),
    ],
]


def objective(t, j):
    return f"6.{t + 2}.{j + 1}"


def truth(spec):
    """Exact arithmetic from structured params; no eval of generated text."""
    op, p = spec["op"], spec["params"]
    if op == "add":
        return F(p[0]) + F(p[1])
    if op == "sub":
        return F(p[0]) - F(p[1])
    if op == "mul":
        return F(p[0]) * F(p[1])
    if op == "div":
        return F(p[0]) / F(p[1])
    if op == "max":
        return max(F(p[0]), F(p[1]))
    if op == "order":
        return F(p[0]) + F(p[1]) * F(p[2])
    if op == "area":
        return F(p[0]) * F(p[1])
    if op == "perimeter":
        return 2 * (F(p[0]) + F(p[1]))
    raise ValueError(op)


def distractors(spec):
    """Apply explicit error rules; reject mathematically equivalent options."""
    ans = truth(spec)
    a, b = map(F, spec["params"][:2])
    if spec["op"] in ("add", "sub") and a.denominator > 1 and b.denominator > 1:
        sign = 1 if spec["op"] == "add" else -1
        wrong = [
            F(a.numerator + sign * b.numerator, math.lcm(a.denominator, b.denominator)),
            F(a.numerator + b.numerator, a.denominator + b.denominator),
            a * b,
        ]
        tags = ["M2", "M1", "CALC"]
    elif spec["op"] == "order":
        wrong = [(a + b) * F(spec["params"][2]), ans + 1, ans - 1]
        tags = ["M4", "CALC", "CALC"]
    elif spec["op"] in ("area", "perimeter"):
        wrong = [2 * (a + b) if spec["op"] == "area" else a * b, ans + 1, ans - 1]
        tags = ["M5", "CALC", "CALC"]
    else:
        wrong = [-ans, ans + 1, ans - 1]
        tags = ["M3" if a < 0 or b < 0 else "CALC", "CALC", "CALC"]
    used = {ans}
    result = []
    for value, tag in zip(wrong, tags, strict=True):
        # Degenerate misconception values are replaced with an explicitly labelled arithmetic error.
        if value in used:
            tag = "CALC"
            value = ans + 2
            while value in used:
                value += 1
        used.add(value)
        result.append((str(value), tag))
    return result


def item_specs():
    specs = []

    def add(t, j, op, params, stem, kz, difficulty=0):
        specs.append(
            dict(
                code=f"JURY-I{len(specs) + 1:02}",
                topic=f"JURY-T{t + 1}",
                objective=objective(t, j),
                op=op,
                params=list(map(str, params)),
                stem_ru=stem,
                stem_kz=kz,
                difficulty=difficulty,
            )
        )

    for j in range(3):
        for k in range(4):
            if j == 0:
                a, b = [("2/3", "1/4"), ("5/6", "1/4"), ("3/4", "1/6"), ("7/8", "1/3")][
                    k
                ]
                op = "add" if k % 2 == 0 else "sub"
                add(
                    0,
                    j,
                    op,
                    [a, b],
                    f"Вычислите {a} {'+' if op == 'add' else '-'} {b}",
                    f"Есептеңіз: {a} {'+' if op == 'add' else '-'} {b}",
                    0.10 * k,
                )
            elif j == 1:
                a, b = [
                    ("2/5", "3/7"),
                    ("3/8", "1/2"),
                    ("5/9", "2/3"),
                    ("7/12", "3/5"),
                ][k]
                add(
                    0,
                    j,
                    "max",
                    [a, b],
                    f"Выберите большую дробь: {a} или {b}",
                    f"Үлкен бөлшекті таңдаңыз: {a} немесе {b}",
                    -0.15 * k,
                )
            else:
                a, b = [("2/3", "3/5"), ("3/4", "2/7"), ("4/9", "3/8"), ("5/6", "2/5")][
                    k
                ]
                add(
                    0,
                    j,
                    "mul",
                    [a, b],
                    f"Вычислите {a} · {b}",
                    f"Есептеңіз: {a} · {b}",
                    0.10 * k,
                )
    for t in range(1, 6):
        for j in range(3):
            for k in range(2):
                a, b = 3 + k + j, 7 + j
                if t == 1:
                    op = ["add", "sub", "mul"][j]
                    p = [str(F(a, 10)), str(F(b, 10))]
                    stem = f"Вычислите {float(F(a, 10)):g} {['+', '-', '·'][j]} {float(F(b, 10)):g}"
                    kz = f"Есептеңіз: {float(F(a, 10)):g} {['+', '-', '·'][j]} {float(F(b, 10)):g}"
                elif t == 2:
                    op = "div"
                    p = [a * b, a]
                    stem = [
                        f"Решите x : {b} = {a} : {a}",
                        f"Найдите отношение {a * b} к {a}",
                        f"Масштаб 1:{b}. Длина на плане {a} см. Найдите длину в см",
                    ][j]
                    if j == 2:
                        op = "mul"
                        p = [a, b]
                    kz = [
                        f"x : {b} = {a} : {a} теңдеуін шешіңіз",
                        f"{a * b} санының {a} санына қатынасын табыңыз",
                        f"Масштаб 1:{b}. Жоспарда {a} см. Нақты ұзындығын см-мен табыңыз",
                    ][j]
                elif t == 3:
                    op = ["add", "sub", "mul"][j]
                    p = [-a, -b]
                    stem = f"Вычислите ({-a}) {['+', '-', '·'][j]} ({-b})"
                    kz = f"Есептеңіз: ({-a}) {['+', '-', '·'][j]} ({-b})"
                elif t == 4:
                    op = ["sub", "div", "order"][j]
                    p = [a * b, a] if j < 2 else [a, b, 2]
                    stem = [
                        f"Решите x + {a} = {a * b}",
                        f"Решите {a}x = {a * b}",
                        f"Вычислите {a} + {b} · 2",
                    ][j]
                    kz = [
                        f"x + {a} = {a * b} теңдеуін шешіңіз",
                        f"{a}x = {a * b} теңдеуін шешіңіз",
                        f"Есептеңіз: {a} + {b} · 2",
                    ][j]
                else:
                    op = "perimeter" if j == 1 else "area"
                    p = [a, b]
                    stem = f"Прямоугольник {a} см × {b} см. Найдите " + (
                        "периметр (см)" if j == 1 else "площадь (см²)"
                    )
                    kz = f"Тіктөртбұрыш: {a} см × {b} см. " + (
                        "Периметрін табыңыз (см)" if j == 1 else "Ауданын табыңыз (см²)"
                    )
                add(t, j, op, p, stem, kz, (-0.16, 0.12)[k])
    for s in specs:
        s["answer"] = str(truth(s))
        s["distractors"] = distractors(s)
        options = [dict(text=s["answer"], tag=None)] + [
            dict(text=value, tag=tag) for value, tag in s["distractors"]
        ]
        random.Random(f"{SEED}/options/{s['code']}").shuffle(options)
        s["options"] = [
            dict(key=key, **o) for key, o in zip("ABCD", options, strict=True)
        ]
        s["answer_key"] = next(o["key"] for o in s["options"] if o["tag"] is None)
        s["mapping_status"] = "proposed" if s["code"] == "JURY-I42" else "confirmed"
        s["objective_codes"] = s["objective"]
        if s["code"] == "JURY-I41":
            s["objective_codes"] = "6.7.3:0.7;6.7.1:0.3"
        s["rubric"] = (
            {
                "max_points": 2,
                "full": "Верное деление обеих частей и правильный ответ",
                "partial": "Верно указано деление обеих частей, вычисление не завершено",
                "zero": "Преобразование не обосновано",
            }
            if s["code"] == "JURY-I34"
            else None
        )
        s["quality"] = {
            "JURY-I13": "too_easy",
            "JURY-I30": "too_hard",
            "JURY-I36": "negative_discrimination",
            "JURY-I35": "high_omission",
            "JURY-I14": "dead_distractor",
            "JURY-I34": "partial_credit",
        }.get(s["code"], "regular")
    return specs


def csv_bytes(rows):
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue().encode()


def json_bytes(value):
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n"
    ).encode()


def sigmoid(x):
    return 1 / (1 + math.exp(-x))


def generate_tables():
    specs = item_specs()
    files = {}
    program = []
    for t, (ru, kz, cur, lo, hi, elapsed) in enumerate(TOPICS):
        for j, (text_ru, text_kz) in enumerate(OBJECTIVES[t]):
            prereq = (
                ""
                if (t, j) == (0, 1)
                else ("6.2.2" if t == 0 else (objective(t, j - 1) if j else "6.2.2"))
            )
            program.append(
                dict(
                    subject="Математика",
                    grade=6,
                    program_code="JURY-M6-SYNTHETIC",
                    program_version="2026.1",
                    program_title="OquMap Jury: математика 6 (synthetic, демонстрационные коды)",
                    language="ru",
                    topic_code=f"JURY-T{t + 1}",
                    topic_title_ru=ru,
                    topic_title_kz=kz,
                    topic_order=t + 1,
                    objective_code=objective(t, j),
                    objective_text_ru=text_ru,
                    objective_text_kz=text_kz,
                    prerequisite_codes=prereq,
                    hours_current=cur,
                    hours_min=lo,
                    hours_max=hi,
                    hours_elapsed=elapsed,
                )
            )
    files["1_program.csv"] = csv_bytes(program)
    files["2_editions.csv"] = csv_bytes(
        [
            dict(
                edition_code=f"JURY-{ed}",
                title=f"Учебник {ed} (synthetic)",
                edition_label="Синтетическое демо 1",
                year=2026,
                language="ru",
                grade=6,
                usage_permission=LABEL + "; CC0-1.0",
            )
            for ed in "AB"
        ]
    )
    bank = []
    for stage in ("pre", "post", "followup"):
        for pos, s in enumerate(specs, 1):
            partial = s["quality"] == "partial_credit"
            bank.append(
                dict(
                    form_code=f"JURY-{stage.upper()}",
                    form_name=f"{stage} (synthetic, та же форма)",
                    form_stage=stage,
                    scale_code="JURY-IDENTICAL",
                    scale_linking="identical_form",
                    item_code=s["code"],
                    position=pos,
                    stem_ru=s["stem_ru"],
                    stem_kz=s["stem_kz"],
                    item_type="open" if partial else "single_choice",
                    options=""
                    if partial
                    else "|".join(f"{o['key']}={o['text']}" for o in s["options"]),
                    answer_key=s["answer"] if partial else s["answer_key"],
                    max_points=2 if partial else 1,
                    objective_codes=s["objective_codes"],
                    mapping_status=s["mapping_status"],
                    misconceptions=""
                    if partial
                    else "|".join(
                        f"{o['key']}={MC[o['tag']][0]}"
                        for o in s["options"]
                        if o["tag"]
                    ),
                )
            )
    files["3_item_bank.csv"] = csv_bytes(bank)
    # Independent RNG streams keep roster, absence and response draws stable as materials evolve.
    roster = []
    latent = {}
    rng = random.Random(SEED)
    schools = [rng.gauss(0, 0.045) for _ in range(8)]
    for si in range(8):
        for ci in range(2):
            ed = "A" if ci == 0 else "B"
            cls = f"JURY-S{si + 1:02}-6{ci + 1}"
            ce = rng.gauss(0, 0.075)
            # Overlapping mixtures, not perfectly separated classrooms. Each school uses both books.
            for _li in range(24):
                code = f"JDL{len(roster) + 1:04}"
                high = rng.random() < (0.30 if ed == "A" else 0.70)
                theta = rng.gauss(0.82 if high else -0.82, 0.26) + ce + schools[si]
                lang = "ru" if si % 2 == 0 else "kz"
                practice = max(1, rng.gauss(13 if ed == "A" else 7, 1.8))
                latent[code] = dict(
                    theta=theta,
                    practice=practice,
                    mis=rng.betavariate(2, 4),
                    noise=rng.gauss(0, 0.08),
                )
                roster.append(
                    dict(
                        school_code=f"JURY-S{si + 1:02}",
                        school_name=f"Синтетическая школа {si + 1:02}",
                        class_code=cls,
                        teacher_code=f"JDT{si * 2 + ci + 1:02}",
                        grade=6,
                        language=lang,
                        academic_year="2026-2027",
                        learner_code=code,
                        edition_code=f"JURY-{ed}",
                        period_start="2026-09-01",
                        period_end="2026-12-20",
                    )
                )
    files["4_roster.csv"] = csv_bytes(roster)
    responses = []
    rng = random.Random(SEED + 1)
    attendance_rng = random.Random(SEED + 2)
    absence = {
        stage: set(
            attendance_rng.sample(
                [r["learner_code"] for r in roster], attendance_rng.randint(16, 26)
            )
        )
        for stage in ("pre", "post", "followup")
    }
    # Common item-specific noise shared over stages, deliberately imperfect quality.
    item_noise = {s["code"]: rng.gauss(0, 0.06) for s in specs}
    for row in roster:
        lc = row["learner_code"]
        z = latent[lc]
        theta = z["theta"]
        cls = row["class_code"]
        for stage, date in [
            ("pre", "2026-09-01"),
            ("post", "2026-10-12"),
            ("followup", "2026-11-02"),
        ]:
            shared = dict(
                learner_code=lc,
                assessment_code=f"JURY-{stage.upper()}-2026",
                form_code=f"JURY-{stage.upper()}",
                attempt=1,
                date=date,
            )
            if lc in absence[stage]:
                responses.append(
                    dict(**shared, item_code="", status="absent", score="", response="")
                )
                continue
            for s in specs:
                # Cell-local stream: a parameter change cannot shift other response draws.
                rng = random.Random(
                    int.from_bytes(
                        hashlib.sha256(
                            f"{SEED}/{lc}/{stage}/{s['code']}".encode()
                        ).digest()[:8],
                        "big",
                    )
                )
                omission = (
                    0.24
                    if s["quality"] == "high_omission"
                    else 0.018 + 0.018 * sigmoid(-theta)
                )
                if rng.random() < omission:
                    responses.append(
                        dict(
                            **shared,
                            item_code=s["code"],
                            status="omitted",
                            score="",
                            response="",
                        )
                    )
                    continue
                target = s["objective"] == "6.2.1"
                frac = s["topic"] == "JURY-T1"
                if stage == "pre":
                    logit = (
                        1.05
                        + 1.8 * theta
                        - s["difficulty"] * 0.35
                        + (0.3 if frac else 0)
                    )
                else:
                    base = (
                        (0.08 if target else 1.0)
                        if frac
                        else (2.05 if s["topic"] == "JURY-T2" else 1.48)
                    )
                    # Practice is a mediator in this synthetic mechanism, not an estimated causal coefficient.
                    practice = (
                        (z["practice"] - 10) * (0.055 if target else 0.030)
                        if frac
                        else 0
                    )
                    logit = (
                        base
                        + 0.91 * theta
                        + practice
                        - s["difficulty"]
                        + z["noise"]
                        + item_noise[s["code"]]
                    )
                    if target:
                        logit -= 0.35 * z["mis"]
                    if stage == "followup" and target:
                        if cls in ("JURY-S01-61", "JURY-S02-62"):
                            logit += 0.60
                        elif cls in ("JURY-S03-61", "JURY-S04-62"):
                            logit -= 0.10
                        else:
                            logit += 0.045
                logit += -0.025 if row["language"] == "kz" else 0
                if s["quality"] == "too_easy":
                    logit = 4.4 + 0.1 * theta
                if s["quality"] == "too_hard":
                    logit = -3.5 + 0.15 * theta
                if s["quality"] == "negative_discrimination":
                    logit = 0.7 - 1.6 * theta
                correct = rng.random() < sigmoid(logit)
                partial = s["quality"] == "partial_credit"
                if correct:
                    score = 2 if partial else 1
                    response = s["answer"] if partial else s["answer_key"]
                elif partial:
                    score = 1 if rng.random() < 0.55 else 0
                    response = (
                        "Шаг 1 верен; вычисление не завершено"
                        if score
                        else "Неверное преобразование"
                    )
                else:
                    weights = [
                        (
                            7
                            + 5 * z["mis"]
                            + (4 if row["edition_code"] == "JURY-B" else 0)
                        )
                        if tag == "M2"
                        else 1
                        for _, tag in s["distractors"]
                    ]
                    if s["quality"] == "dead_distractor":
                        weights[-1] = 0
                    wrong_keys = [
                        next(o["key"] for o in s["options"] if o["text"] == value)
                        for value, _ in s["distractors"]
                    ]
                    response = rng.choices(wrong_keys, weights=weights)[0]
                    score = 0
                responses.append(
                    dict(
                        **shared,
                        item_code=s["code"],
                        status="answered",
                        score=score,
                        response=response,
                    )
                )
    # Stable key order, including absent sentinel before individual items.
    responses.sort(
        key=lambda r: (
            r["assessment_code"],
            r["learner_code"],
            r["item_code"],
            r["attempt"],
        )
    )
    files["5_responses.csv"] = csv_bytes(responses)
    return files, specs, roster, responses


def material_pages(ed, specs):
    """50 physical = printed pages; compact original workbook, no blank padding."""
    pages = []
    exercises = []
    for page in range(1, 51):
        if page == 1:
            heading = f"Учебник {ed}"
            paragraphs = [
                LABEL,
                "Математика. 6 класс. Полностью вымышленный учебный материал.",
                "CC0-1.0: разрешено копирование, изменение и демонстрация.",
                KZ_NOTE,
                "Бұл OquMap жүйесіне арналған синтетикалық оқу материалы.",
                "Коды целей демонстрационные и не являются официальной программой.",
            ]
        elif page == 2:
            heading = "Содержание"
            paragraphs = [
                "3-10. Обыкновенные дроби",
                "11-18. Десятичные дроби",
                "19-26. Пропорции",
                "27-34. Отрицательные числа",
                "35-42. Линейные уравнения",
                "43-46. Площадь и периметр",
                "47. Повторение: сложение и вычитание дробей",
                "48. Самопроверка",
                "49. Ключи к странице 47",
                "50. Методические заметки",
            ]
        elif page in (47, 48, 49):
            pool = []
            # B: six additions, one subtraction and no isolated denominator drill.
            # A: four additions, six subtractions and four isolated scaling drills (both pages).
            for i in range(10 if ed == "A" else 7):
                op = (
                    "sub" if (ed == "A" and i >= 4) or (ed == "B" and i == 6) else "add"
                )
                pool.append(dict(op=op, params=[f"{i + 2}/{i + 5}", f"1/{i + 3}"]))
            heading = {
                47: "Сложение и вычитание дробей. Цель 6.2.1",
                48: "Самопроверка и рассуждение",
                49: "Ключи к странице 47",
            }[page]
            paragraphs = []
            if page == 47:
                paragraphs = [
                    "Сначала найдите общий знаменатель. Затем домножьте числитель каждой дроби на дополнительный множитель.",
                    "Пример: 2/3 + 1/4 = 8/12 + 3/12 = 11/12.",
                    "Почему 2/3 нельзя заменить на 2/12? Объясните, какие доли изменились.",
                ]
                if ed == "A":
                    paragraphs += [
                        "Пример вычитания: 5/6 - 1/4 = 10/12 - 3/12 = 7/12. Проверьте обратным действием."
                    ]
                for i, s in enumerate(pool, 1):
                    paragraphs.append(
                        f"{i}. Вычислите {s['params'][0]} {'+' if s['op'] == 'add' else '-'} {s['params'][1]}."
                    )
                    exercises.append(
                        dict(
                            edition_code=f"JURY-{ed}",
                            page=page,
                            number=i,
                            **s,
                            answer=str(truth(s)),
                            objective_code="6.2.1",
                            role="practices",
                        )
                    )
            elif page == 48:
                paragraphs = [
                    "Объясните правило соседу. Сверьте вычисления с ключами. Запишите вопрос учителю."
                ]
                if ed == "A":
                    for i in range(2, 6):
                        s = dict(op="mul", params=[f"1/{i}", i * 3])
                        paragraphs.append(
                            f"{i - 1}. Какой числитель у дроби 1/{i} после приведения к знаменателю {i * 3}?"
                        )
                        exercises.append(
                            dict(
                                edition_code="JURY-A",
                                page=page,
                                number=i - 1,
                                **s,
                                answer=str(truth(s)),
                                objective_code="6.2.1",
                                role="denominator_drill",
                            )
                        )
                    paragraphs += [
                        "Сравните два решения: 5/6 - 1/4 = 7/12 и 5/6 - 1/4 = 4/12. Найдите первый неверный шаг."
                    ]
                else:
                    paragraphs += [
                        "Нарисуйте модель суммы 1/2 + 1/3. Придумайте свой пример сложения."
                    ]
                paragraphs += [
                    KZ_NOTE,
                    "Ортақ бөлімді тап. Алымдарды тиісті көбейткіштерге көбейт.",
                ]
            else:
                paragraphs = [
                    f"{i}. {s['params'][0]} {'+' if s['op'] == 'add' else '-'} {s['params'][1]} = {truth(s)}"
                    for i, s in enumerate(pool, 1)
                ]
        elif page == 50:
            heading = "Методические заметки"
            paragraphs = [
                LABEL,
                "Материал создан программно. Это не реальное издание и не рекомендация для учебного процесса.",
                "Сопоставление результатов и покрытия допускает гипотезу о практике. Оно не доказывает причинность.",
                "Повторение тех же заданий может создавать эффект запоминания. Нужна независимая диагностическая проверка.",
                KZ_NOTE,
            ]
        else:
            t = (
                0
                if page < 11
                else 1
                if page < 19
                else 2
                if page < 27
                else 3
                if page < 35
                else 4
                if page < 43
                else 5
            )
            subset = [
                s
                for s in specs
                if s["topic"] == f"JURY-T{t + 1}" and s["objective"] != "6.2.1"
            ]
            selected = [subset[(page + i) % len(subset)] for i in range(3)]
            heading = f"{TOPICS[t][0]}. Практикум {page}"
            paragraphs = [
                "Работайте по шагам: запишите действие, выполните вычисление, оцените правдоподобие ответа.",
                "Разберите пример и объясните каждый шаг: "
                + selected[0]["stem_ru"]
                + ". Ответ: "
                + selected[0]["answer"]
                + ".",
            ]
            for i, s in enumerate(selected, 1):
                paragraphs.append(
                    f"{i}. {s['stem_ru']}. Объясните решение другим способом."
                )
                exercises.append(
                    dict(
                        edition_code=f"JURY-{ed}",
                        page=page,
                        number=i,
                        op=s["op"],
                        params=s["params"],
                        answer=s["answer"],
                        objective_code=s["objective"],
                        role="practices",
                    )
                )
            paragraphs += [
                "Самопроверка: сравните два решения. Если ответы различаются, найдите первый неверный шаг.",
                KZ_NOTE,
                TOPICS[t][1] + ". " + selected[0]["stem_kz"],
            ]
        pages.append(dict(page=page, heading=heading, paragraphs=paragraphs))
    return pages, exercises


def pdf_bytes(ed, pages, font):
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.platypus import Paragraph

    pdfmetrics.registerFont(TTFont("JurySans", str(font)))
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=(595.28, 841.89), invariant=1, pageCompression=1)
    c.setTitle(f"Учебник {ed} - synthetic OquMap")
    c.setAuthor("OquMap synthetic generator")
    body = ParagraphStyle(
        "body", fontName="JurySans", fontSize=11, leading=17, spaceAfter=12
    )
    title = ParagraphStyle("title", parent=body, fontSize=19, leading=25)
    for p in pages:
        c.setFillColorRGB(0.12, 0.26, 0.36)
        c.rect(0, 790, 596, 52, fill=1, stroke=0)
        c.setFillColorRGB(1, 1, 1)
        c.setFont("JurySans", 10)
        c.drawString(40, 811, f"OquMap / SYNTHETIC / Учебник {ed}")
        c.setFillColorRGB(0.12, 0.18, 0.23)
        y = 760
        for text, style in [(p["heading"], title)] + [
            (v, body) for v in p["paragraphs"]
        ]:
            para = Paragraph(text, style)
            _, h = para.wrap(515, 700)
            if y - h < 65:
                raise ValueError(f"Page overflow {ed}/{p['page']}")
            para.drawOn(c, 40, y - h)
            y -= h + 12
        c.setStrokeColorRGB(0.7, 0.75, 0.8)
        c.line(40, 47, 555, 47)
        c.setFont("JurySans", 8)
        c.drawString(40, 30, "Синтетический материал OquMap / CC0-1.0")
        c.drawRightString(555, 30, str(p["page"]))
        c.showPage()
    c.save()
    return buf.getvalue()


def extra_fixtures(roster):
    interventions = [
        dict(
            intervention_id="JURY-INT-M2",
            objective_code="6.2.1",
            misconception="M2",
            title_ru="Два занятия: общий знаменатель и вычитание",
            sessions_planned=2,
            minutes_per_session=45,
            practice_items=16,
            is_synthetic="true",
        )
    ]
    pilots = []
    fidelity = []
    followups = []
    groups = {
        "A": ["JURY-S01-61", "JURY-S02-62"],
        "B": ["JURY-S03-61", "JURY-S04-62"],
        "C": ["JURY-S05-61", "JURY-S06-62"],
    }
    for group, classes in groups.items():
        pid = f"JURY-PILOT-{group}"
        pilots.append(
            dict(
                pilot_id=pid,
                intervention_id="JURY-INT-M2",
                class_codes=";".join(classes),
                start_date="2026-10-13",
                end_date="2026-11-02",
                baseline_assessment="JURY-POST-2026",
                followup_assessment="JURY-FOLLOWUP-2026",
                design="nonrandomized_within_group",
                is_synthetic="true",
            )
        )
        for cls in classes:
            for session in (1, 2):
                completed = group != "B" or session == 1
                fidelity.append(
                    dict(
                        log_id=f"{pid}-{cls}-{session}",
                        pilot_id=pid,
                        class_code=cls,
                        session=session,
                        date=f"2026-10-{14 + 7 * (session - 1):02}",
                        planned_minutes=45,
                        actual_minutes=(
                            45 if group == "A" else 20 if group == "B" else 40
                        )
                        if completed
                        else 0,
                        planned_items=8,
                        completed_items=(
                            8 if group == "A" else 3 if group == "B" else 6
                        )
                        if completed
                        else 0,
                        status="completed" if completed else "cancelled",
                        is_synthetic="true",
                    )
                )
        eligible = [r for r in roster if r["class_code"] in classes]
        for i, row in enumerate(eligible):
            # C has a six-person convenience sample; not a fake zero score or an absence.
            followups.append(
                dict(
                    followup_id=f"{pid}-{row['learner_code']}",
                    pilot_id=pid,
                    learner_code=row["learner_code"],
                    assessment_code="JURY-FOLLOWUP-2026",
                    included="true" if group != "C" or i < 6 else "false",
                    exclusion_reason="" if group != "C" or i < 6 else "not_sampled",
                    comparable="false" if group == "C" else "true",
                    days_since_post=21,
                    is_synthetic="true",
                )
            )
    return {
        "6_interventions.csv": csv_bytes(interventions),
        "7_pilots.csv": csv_bytes(pilots),
        "8_fidelity_logs.csv": csv_bytes(fidelity),
        "9_followups.csv": csv_bytes(followups),
    }


def build(font):
    files, specs, roster, responses = generate_tables()
    files.update(extra_fixtures(roster))
    exercises = []
    pages_by_ed = {}
    for ed in "AB":
        pages, ex = material_pages(ed, specs)
        pages_by_ed[ed] = pages
        exercises += ex
        files[f"materials/textbook_{ed}.pdf"] = pdf_bytes(ed, pages, font)
    files["materials/exercises.json"] = json_bytes(exercises)
    links = []
    for ed in "AB":
        for s in specs:
            page = (
                47
                if s["objective"] == "6.2.1"
                else next(
                    (
                        p["page"]
                        for p in pages_by_ed[ed]
                        if s["stem_ru"] in " ".join(p["paragraphs"])
                    ),
                    None,
                )
            )
            if page:
                links.append(
                    dict(
                        edition_code=f"JURY-{ed}",
                        item_code=s["code"],
                        objective_code=s["objective"],
                        page_physical=page,
                        page_printed=str(page),
                        status=s["mapping_status"],
                        role="practices",
                        origin="human_fixture",
                    )
                )
    files["material_mappings.json"] = json_bytes(links)
    files["item_math.json"] = json_bytes(specs)
    files["misconceptions.json"] = json_bytes(
        {k: dict(backend_code=v[0], label_ru=v[1]) for k, v in MC.items()}
    )
    files["expected_findings.json"] = json_bytes(
        dict(
            is_synthetic=True,
            seed=SEED,
            filters=dict(
                outcome_stage="post",
                mapping_status="confirmed_only",
                omitted_policy="as_incorrect",
                attempt_rule="first",
                aggregation="learner",
            ),
            fractions_mean=[0.59, 0.65],
            target_objective="6.2.1",
            target_mean=[0.43, 0.50],
            raw_A_minus_B=[-0.07, -0.04],
            adjusted_A_minus_B=[0.03, 0.07],
            comparison=dict(
                strata_scheme="pre_three_level",
                weight_mode="pooled",
                api_difference="B minus A; negate to report A minus B",
            ),
            pilots=dict(
                A=dict(gain=[0.08, 0.12], status="positive_signal"),
                B=dict(gain=[-0.05, 0.05], status="invalid_due_to_fidelity"),
                C=dict(status="needs_more_data"),
            ),
        )
    )
    counts = dict(
        schools=8,
        classes=16,
        learners=384,
        objectives=18,
        topics=6,
        items=len(specs),
        forms=3,
        assessments=3,
        response_rows=sum(r["status"] != "absent" for r in responses),
        absence_rows=sum(r["status"] == "absent" for r in responses),
        import_response_file_rows=len(responses),
    )
    from jury_demo_docs import DICTIONARY, README

    files["README.md"] = README.encode("utf-8")
    files["DATA_DICTIONARY.md"] = DICTIONARY.encode("utf-8")
    files["manifest.json"] = json_bytes(
        dict(
            dataset_name="OquMap Jury - Математика 6 (synthetic)",
            is_synthetic=True,
            seed=SEED,
            base_commit="9cac9a267b23a704dab514b40a662dc68fec0769",
            counts=counts,
            kz_note=KZ_NOTE,
            algorithm="Python random MT19937; independent roster and response streams; see generator source",
            font_sha256=hashlib.sha256(font.read_bytes()).hexdigest(),
            files={
                name: dict(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
                for name, data in sorted(files.items())
            },
        )
    )
    return files


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument(
        "--font",
        type=Path,
        default=DEFAULT_FONT,
        help="DejaVu Sans TTF (defaults to the Linux system font, then the checked-in application font)",
    )
    args = p.parse_args()
    files = build(args.font)
    for name, data in sorted(files.items()):
        path = args.out / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(json.loads(files["manifest.json"])["counts"])
    for name, data in sorted(files.items()):
        print(hashlib.sha256(data).hexdigest(), name)


if __name__ == "__main__":
    main()
