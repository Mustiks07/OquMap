"""Filled example of a complete project for the onboarding templates (synthetic, deterministic).

Writes data/templates/example_project/{1_program,2_editions,3_item_bank,4_roster,5_responses}.csv.
Uses its own codes (EX-*, no demo identifiers): 3 topics, 6 objectives, 12 items, a pre- and a post-form,
2 editions, 2 schools × 6 classes × 20 learners. Run: ``python -m oqumap.demo.example_project``.
"""

from __future__ import annotations

import csv
import io
import math
from pathlib import Path

import numpy as np

from ..config import REPO_ROOT

OUT = REPO_ROOT / "data" / "templates" / "example_project"

PROGRAM = [
    # topic, title_ru, title_kz, order, objective, text_ru, prereq, hours (cur, min, max, elapsed)
    ("EX-T1", "Натуральные числа", "Натурал сандар", 1, "EX-1.1", "Складывать и вычитать многозначные числа", "", (10, 8, 12, 0)),
    ("EX-T1", "Натуральные числа", "Натурал сандар", 1, "EX-1.2", "Умножать многозначные числа", "EX-1.1", (10, 8, 12, 0)),
    ("EX-T2", "Обыкновенные дроби", "Жай бөлшектер", 2, "EX-2.1", "Сравнивать дроби", "", (12, 10, 16, 0)),
    ("EX-T2", "Обыкновенные дроби", "Жай бөлшектер", 2, "EX-2.2", "Складывать дроби с одинаковыми знаменателями", "EX-2.1", (12, 10, 16, 0)),
    ("EX-T3", "Десятичные дроби", "Ондық бөлшектер", 3, "EX-3.1", "Записывать десятичные дроби", "EX-2.1", (10, 8, 14, 0)),
    ("EX-T3", "Десятичные дроби", "Ондық бөлшектер", 3, "EX-3.2", "Складывать десятичные дроби", "EX-3.1;EX-1.1", (10, 8, 14, 0)),
]

# code, objective spec, stem, options, key, difficulty, forms
ITEMS = [
    ("EX-I01", "EX-1.1", "Вычислите 248 + 175", "A=423|B=413|C=323|D=4213", "A", -0.8, ["EX-PRE", "EX-POST"]),
    ("EX-I02", "EX-1.1", "Вычислите 502 − 137", "A=375|B=365|C=435|D=465", "B", -0.3, ["EX-PRE"]),
    ("EX-I03", "EX-1.2", "Вычислите 34 · 12", "A=68|B=408|C=348|D=46", "B", 0.0, ["EX-POST"]),
    ("EX-I04", "EX-1.2", "Вычислите 125 · 8", "A=1000|B=1008|C=900|D=133", "A", -0.4, ["EX-PRE", "EX-POST"]),
    ("EX-I05", "EX-2.1", "Какая дробь больше: 3/7 или 4/7?", "A=3/7|B=4/7|C=равны|D=нельзя сравнить", "B", -0.6, ["EX-PRE", "EX-POST"]),
    ("EX-I06", "EX-2.1", "Какая дробь меньше: 1/3 или 1/5?", "A=1/3|B=1/5|C=равны|D=нельзя сравнить", "B", 0.3, ["EX-POST"]),
    ("EX-I07", "EX-2.2", "Вычислите 2/9 + 5/9", "A=7/18|B=7/9|C=10/9|D=3/9", "B", 0.2, ["EX-POST"]),
    ("EX-I08", "EX-2.2", "Вычислите 7/10 − 3/10", "A=4/10|B=4/0|C=10/10|D=4/20", "A", 0.4, ["EX-POST"]),
    ("EX-I09", "EX-3.1", "Запишите 3/10 десятичной дробью", "A=0,03|B=3,10|C=0,3|D=0,310", "C", -0.2, ["EX-PRE", "EX-POST"]),
    ("EX-I10", "EX-3.2", "Вычислите 0,4 + 0,35", "A=0,39|B=0,75|C=7,5|D=0,075", "B", 0.5, ["EX-POST"]),
    ("EX-I11", "EX-3.2:0.5;EX-1.1:0.5", "Купили 1,2 кг яблок и 0,8 кг груш. Сколько всего?", "A=2|B=1,10|C=2,0|D=20", "A", 0.6, ["EX-POST"]),
    ("EX-I12", "EX-3.1", "Какое число больше: 0,5 или 0,45?", "A=0,45|B=0,5|C=равны|D=нельзя сравнить", "B", 0.1, ["EX-PRE", "EX-POST"]),
]

SCHOOLS = [("EX-SCH1", "Школа 1", 0.3), ("EX-SCH2", "Школа 2", -0.3)]


def _csv(rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def build() -> dict[str, str]:
    rng = np.random.default_rng(424242)
    files: dict[str, str] = {}
    prog = [["subject", "grade", "program_code", "program_version", "program_title", "language", "topic_code",
             "topic_title_ru", "topic_title_kz", "topic_order", "objective_code", "objective_text_ru",
             "prerequisite_codes", "hours_current", "hours_min", "hours_max", "hours_elapsed"]]
    for t, tr, tk, o, oc, ot, pre, (c, lo, hi, el) in PROGRAM:
        prog.append(["Математика", 5, "EX-MATH5", "2026.1", "Математика 5 класс (пример)", "ru", t, tr, tk, o, oc, ot, pre,
                     c, lo, hi, el])
    files["1_program.csv"] = _csv(prog)
    files["2_editions.csv"] = _csv([["edition_code", "title", "edition_label", "year", "language", "grade", "usage_permission"],
                                    ["EX-BOOK1", "Пример: учебник 1", "1-е изд.", 2024, "ru", 5, "пример OquMap"],
                                    ["EX-BOOK2", "Пример: учебник 2", "1-е изд.", 2025, "ru", 5, "пример OquMap"]])
    bank = [["form_code", "form_name", "form_stage", "scale_code", "scale_linking", "item_code", "position", "stem_ru",
             "item_type", "options", "answer_key", "max_points", "objective_codes", "mapping_status"]]
    for form, name, stage, scale in (("EX-PRE", "Входная проверка", "pre", "EX-S-PRE"), ("EX-POST", "Итоговая проверка", "post", "EX-S-POST")):
        pos = 0
        for code, obj, stem, opts, key, _, forms in ITEMS:
            if form in forms:
                pos += 1
                bank.append([form, name, stage, scale, "identical_form", code, pos, stem, "single_choice", opts, key, 1, obj, "confirmed"])
    files["3_item_bank.csv"] = _csv(bank)
    roster = [["school_code", "school_name", "class_code", "teacher_code", "grade", "language", "academic_year",
               "learner_code", "edition_code"]]
    resp = [["learner_code", "assessment_code", "form_code", "item_code", "attempt", "status", "response", "date"]]
    n = 0
    for sc, sname, seff in SCHOOLS:
        for ci in range(6):
            cls = f"{sc}-5{'АБВГДЕ'[ci]}"
            ed = "EX-BOOK1" if ci % 2 == 0 else "EX-BOOK2"
            ceff = float(rng.normal(0, 0.2))
            for _ in range(20):
                n += 1
                lc = f"EXL{n:04d}"
                roster.append([sc, sname, cls, f"EX-T-{cls}", 5, "ru", "2025-2026", lc, ed])
                theta = seff + ceff + float(rng.normal(0, 1))
                for acode, form, d, shift in (("EX-PRE-2025", "EX-PRE", "2025-09-10", 0.0), ("EX-POST-2026", "EX-POST", "2026-05-15", 0.6)):
                    if rng.random() < 0.03:
                        resp.append([lc, acode, form, "", 1, "absent", "", d])
                        continue
                    for code, _, _, opts, key, b, forms in ITEMS:
                        if form not in forms:
                            continue
                        if rng.random() < 0.02:
                            resp.append([lc, acode, form, code, 1, "omitted", "", d])
                            continue
                        eff = 0.25 if (ed == "EX-BOOK2" and code in ("EX-I07", "EX-I08")) else 0.0
                        p = 1 / (1 + math.exp(-1.2 * (theta + shift + eff - b)))
                        letters = [x.split("=")[0] for x in opts.split("|")]
                        ans = key if rng.random() < p else str(rng.choice([x for x in letters if x != key]))
                        resp.append([lc, acode, form, code, 1, "answered", ans, d])
    files["4_roster.csv"] = _csv(roster)
    files["5_responses.csv"] = _csv(resp)
    return files


def write(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, text in build().items():
        p = out / name
        p.write_bytes(text.encode("utf-8"))
        paths.append(p)
    (out / "README.md").write_text(
        "# Пример проекта для импорта\n\nСинтетический пример (EX-*), загружается по порядку: 1_program → 2_editions → "
        "3_item_bank → 4_roster → 5_responses. Создан `python -m oqumap.demo.example_project`.\n", encoding="utf-8")
    return paths


if __name__ == "__main__":
    for p in write():
        print(p)
