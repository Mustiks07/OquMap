"""Additional exact item families: decimals, proportions, negative numbers, linear equations, order of operations,
area and perimeter.

Same contract as the fraction families in ``quizzes.py``: ``gen(rng, level) -> {"family", "params"}`` and
``render(params) -> {stem_ru, stem_kz, options, key_value, rubric_ru, rubric_kz}``. The key is computed with exact
arithmetic (``fractions.Fraction``); every distractor is the result of applying a named misconception rule to the
same numbers. The server re-renders from ``params`` to re-check the key, so nothing here depends on a model.
"""

from __future__ import annotations

import random
from fractions import Fraction


def _opt(text, correct, mc, ru, kz):
    return {"text": text, "correct": correct, "misconception": mc, "rationale_ru": ru, "rationale_kz": kz}


def fmt(x: Fraction) -> str:
    """Exact number in school notation: integers, finite decimals with a comma, otherwise a fraction."""
    x = Fraction(x)
    sign = "−" if x < 0 else ""
    x = abs(x)
    if x.denominator == 1:
        return f"{sign}{x.numerator}"
    d = x.denominator
    for p in range(1, 7):
        if (10 ** p) % d == 0:
            n = x.numerator * (10 ** p // d)
            s = str(n).rjust(p + 1, "0")
            return f"{sign}{s[:-p]},{s[-p:]}".rstrip("0").rstrip(",")
    whole = x.numerator // d
    rest = x - whole
    return f"{sign}{whole} {rest.numerator}/{rest.denominator}" if whole else f"{sign}{x.numerator}/{d}"


def dec(units: int, places: int) -> Fraction:
    return Fraction(units, 10 ** places)


def _rub(ru: str, kz: str) -> dict:
    return {"rubric_ru": ru, "rubric_kz": kz}


# ---- decimals --------------------------------------------------------------------------------------------


def gen_dec_add(rng: random.Random, level: int) -> dict:
    a = rng.choice([x for x in range(1, 10)]) + 10 * level * rng.randint(0, 1)  # tenths
    b = rng.choice([x for x in range(11, 99) if x % 10])  # hundredths
    return {"family": "dec_add", "params": {"a": a, "b": b}}


def render_dec_add(p: dict) -> dict:
    a, b = dec(p["a"], 1), dec(p["b"], 2)
    key = a + b
    right = Fraction(p["a"] + p["b"], 100)  # digits added as if aligned on the right: 0,5 + 0,25 → 0,30
    opts = [
        _opt(fmt(key), True, None, "Верно: сложили разряд с разрядом (0,5 = 0,50).", "Дұрыс: разрядты разрядпен қосты (0,5 = 0,50)."),
        _opt(fmt(right), False, "decimal_align_right", "Выровнял дроби по правому краю, а не по запятой.", "Бөлшектерді үтір бойынша емес, оң жақ шет бойынша теңестірді."),
        _opt(fmt(key * 10), False, "decimal_point_count", "Поставил запятую на разряд правее.", "Үтірді бір разряд оңға қойды."),
        _opt(fmt(Fraction(p["a"] + p["b"], 1000)), False, "decimal_place_value", "Сложил цифры и отсчитал три знака после запятой.",
             "Цифрларды қосып, үтірден кейін үш таңба санады."),
    ]
    return {"stem_ru": f"Вычислите: {fmt(a)} + {fmt(b)}.", "stem_kz": f"Есептеңіз: {fmt(a)} + {fmt(b)}.", "options": opts, "key_value": key,
            **_rub("1 балл; попросите записать в столбик с выравниванием по запятой.", "1 ұпай; үтір бойынша бағанмен жазуды сұраңыз.")}


def gen_dec_compare(rng: random.Random, level: int) -> dict:
    a = rng.randint(2, 8)  # tenths, e.g. 0,3
    b = rng.choice([x for x in range(10 * a - 9, 10 * a) if x % 10 and x > 10])  # hundredths smaller than a/10, longer
    return {"family": "dec_compare", "params": {"a": a, "b": b}}


def render_dec_compare(p: dict) -> dict:
    a, b = dec(p["a"], 1), dec(p["b"], 2)
    big, longer = (fmt(a), fmt(b)) if a > b else (fmt(b), fmt(a))
    eq = f"{fmt(a)} = {fmt(a)}0" if a > b else f"{fmt(b)} = {fmt(b)}0"
    opts = [_opt(big, True, None, f"Верно: {eq} > {longer}.", f"Дұрыс: {eq} > {longer}."),
            _opt(longer, False, "decimal_longer_larger", "Считает больше дробь с бо́льшим числом знаков.", "Таңбасы көп бөлшекті үлкен деп санайды."),
            _opt("Они равны", False, "decimal_place_value", "Сравнивает цифры без учёта разрядов.", "Цифрларды разрядтарды ескермей салыстырады.")]
    return {"stem_ru": f"Какое число больше: {fmt(a)} или {fmt(b)}?", "stem_kz": f"Қай сан үлкен: {fmt(a)} әлде {fmt(b)}?", "options": opts,
            "key_value": max(a, b), "key_text": big,
            **_rub("1 балл; попросите отметить оба числа на прямой.", "1 ұпай; екі санды түзуде белгілеуді сұраңыз.")}


def gen_dec_mul(rng: random.Random, level: int) -> dict:
    return {"family": "dec_mul", "params": {"a": rng.randint(11, 19 + 10 * level), "b": rng.randint(2, 9)}}


def render_dec_mul(p: dict) -> dict:
    a, b = dec(p["a"], 1), dec(p["b"], 1)
    key = a * b
    opts = [_opt(fmt(key), True, None, "Верно: два знака после запятой (1 + 1).", "Дұрыс: үтірден кейін екі таңба (1 + 1)."),
            _opt(fmt(key * 10), False, "decimal_point_count", "Отсчитал только один знак после запятой.", "Үтірден кейін тек бір таңба санады."),
            _opt(fmt(key / 10), False, "decimal_point_count", "Отсчитал три знака после запятой.", "Үтірден кейін үш таңба санады."),
            _opt(fmt(a + b), False, "wrong_operation", "Сложил вместо умножения.", "Көбейтудің орнына қосты.")]
    return {"stem_ru": f"Вычислите: {fmt(a)} · {fmt(b)}.", "stem_kz": f"Есептеңіз: {fmt(a)} · {fmt(b)}.", "options": opts, "key_value": key,
            **_rub("1 балл; попросите оценить ответ округлением.", "1 ұпай; жауапты дөңгелектеу арқылы бағалауды сұраңыз.")}


# ---- proportions -------------------------------------------------------------------------------------------


def gen_proportion(rng: random.Random, level: int) -> dict:
    while True:
        c = rng.randint(2, 6 + level)
        b = rng.randint(1, c * 2)
        a = c * rng.randint(1, 4)
        vals = {Fraction(a * b, c), Fraction(a * c, b), Fraction(a + b - c), Fraction(b * c, a)}
        if b != c and a != c and (a * b) % c == 0 and len(vals) == 4:
            return {"family": "proportion", "params": {"a": a, "b": b, "c": c}}


def render_proportion(p: dict) -> dict:
    a, b, c = p["a"], p["b"], p["c"]  # x : a = b : c
    key = Fraction(a * b, c)
    opts = [_opt(fmt(key), True, None, "Верно: x = a·b : c (основное свойство пропорции).", "Дұрыс: x = a·b : c (пропорцияның негізгі қасиеті)."),
            _opt(fmt(Fraction(a * c, b)), False, "cross_multiply_wrong", "Перемножил не те члены пропорции.", "Пропорцияның басқа мүшелерін көбейтті."),
            _opt(fmt(Fraction(a + b - c)), False, "proportion_additive", "Сохранил разность вместо отношения.", "Қатынастың орнына айырманы сақтады."),
            _opt(fmt(Fraction(b * c, a)), False, "ratio_order", "Переставил члены отношения.", "Қатынас мүшелерінің орнын ауыстырды.")]
    return {"stem_ru": f"Решите пропорцию: x : {a} = {b} : {c}.", "stem_kz": f"Пропорцияны шешіңіз: x : {a} = {b} : {c}.", "options": opts,
            "key_value": key, **_rub("1 балл; попросите проверить подстановкой.", "1 ұпай; орнына қою арқылы тексеруді сұраңыз.")}


def _notebooks(k: int) -> str:
    if k % 10 == 1 and k % 100 != 11:
        return "тетрадь"
    return "тетради" if k % 10 in (2, 3, 4) and k % 100 not in (12, 13, 14) else "тетрадей"


def gen_unit_rate(rng: random.Random, level: int) -> dict:
    n = rng.randint(2, 4)
    price = rng.choice([50, 60, 75, 80, 120, 150]) * n
    m = rng.choice([x for x in range(n + 1, n + 6) if x != 2 * n])
    return {"family": "unit_rate", "params": {"n": n, "price": price, "m": m}}


def render_unit_rate(p: dict) -> dict:
    n, price, m = p["n"], p["price"], p["m"]
    key = Fraction(price * m, n)
    opts = [_opt(fmt(key), True, None, "Верно: цена одной тетради × количество.", "Дұрыс: бір дәптердің бағасы × саны."),
            _opt(fmt(Fraction(price + (m - n))), False, "proportion_additive", "Прибавил разность количеств к цене.", "Сандардың айырмасын бағаға қосты."),
            _opt(fmt(Fraction(price * n, m)), False, "inverse_proportion", "Применил обратную пропорциональность.", "Кері пропорционалдықты қолданды."),
            _opt(fmt(Fraction(price * m)), False, "wrong_operation", "Умножил цену всех тетрадей на новое количество.", "Барлық дәптердің бағасын жаңа санға көбейтті.")]
    return {"stem_ru": f"{n} {_notebooks(n)} стоят {price} тг. Сколько стоят {m} таких {_notebooks(m)}?",
            "stem_kz": f"{n} дәптер {price} теңге тұрады. Осындай {m} дәптер қанша тұрады?", "options": opts, "key_value": key,
            **_rub("1 балл; спросите, больше или меньше должна быть цена.", "1 ұпай; баға көп болуы керек пе, аз ба — сұраңыз.")}


# ---- negative numbers ---------------------------------------------------------------------------------------


def gen_neg_add(rng: random.Random, level: int) -> dict:
    a = rng.randint(4, 9 + 5 * level)
    b = rng.randint(1, a - 1)
    return {"family": "neg_add", "params": {"a": a, "b": b}}


def render_neg_add(p: dict) -> dict:
    a, b = p["a"], p["b"]  # −a + b with a > b
    key = Fraction(-a + b)
    opts = [_opt(fmt(key), True, None, "Верно: модуль больше у отрицательного слагаемого, знак «−».", "Дұрыс: теріс қосылғыштың модулі үлкен, таңба «−»."),
            _opt(fmt(Fraction(a - b)), False, "neg_wrong_sign", "Вычел модули, но взял знак «+».", "Модульдерді азайтты, бірақ «+» таңбасын алды."),
            _opt(fmt(Fraction(-(a + b))), False, "neg_add_absolute", "Сложил модули и оставил «−».", "Модульдерді қосып, «−» қалдырды."),
            _opt(fmt(Fraction(a + b)), False, "neg_ignore_signs", "Не учёл знаки.", "Таңбаларды ескермеді.")]
    return {"stem_ru": f"Вычислите: −{a} + {b}.", "stem_kz": f"Есептеңіз: −{a} + {b}.", "options": opts, "key_value": key,
            **_rub("1 балл; попросите показать на числовой прямой.", "1 ұпай; сан түзуінде көрсетуді сұраңыз.")}


def gen_neg_compare(rng: random.Random, level: int) -> dict:
    a = rng.randint(2, 6 + level)
    b = rng.randint(a + 1, a + 6)
    return {"family": "neg_compare", "params": {"a": a, "b": b}}


def render_neg_compare(p: dict) -> dict:
    a, b = p["a"], p["b"]  # −a vs −b with a < b → −a is greater
    opts = [_opt(f"−{a}", True, None, "Верно: на прямой −a правее −b.", "Дұрыс: түзуде −a −b-дан оңға қарай орналасқан."),
            _opt(f"−{b}", False, "neg_compare_by_absolute", "Сравнил по модулю, как натуральные числа.", "Натурал сандар сияқты модуль бойынша салыстырды."),
            _opt("Они равны", False, "neg_ignore_signs", "Не различает числа с одинаковым знаком.", "Таңбасы бірдей сандарды ажыратпайды.")]
    return {"stem_ru": f"Какое число больше: −{a} или −{b}?", "stem_kz": f"Қай сан үлкен: −{a} әлде −{b}?", "options": opts,
            "key_value": Fraction(-a), "key_text": f"−{a}", **_rub("1 балл; попросите отметить числа на прямой.", "1 ұпай; сандарды түзуде белгілеуді сұраңыз.")}


# ---- linear equations ---------------------------------------------------------------------------------------


def gen_linear(rng: random.Random, level: int) -> dict:
    a = rng.randint(2, 5 + level)
    x = rng.randint(2, 9)
    b = rng.randint(1, 12)
    return {"family": "linear_eq", "params": {"a": a, "b": b, "c": a * x + b}}


def render_linear(p: dict) -> dict:
    a, b, c = p["a"], p["b"], p["c"]  # a·x + b = c
    key = Fraction(c - b, a)
    opts = [_opt(fmt(key), True, None, "Верно: x = (c − b) : a.", "Дұрыс: x = (c − b) : a."),
            _opt(fmt(Fraction(c + b, a)), False, "eq_transfer_sign", "Перенёс слагаемое, не сменив знак.", "Қосылғышты таңбасын өзгертпей көшірді."),
            _opt(fmt(Fraction(c, a) - b), False, "eq_divide_first", "Разделил на коэффициент только правую часть, потом вычел.", "Тек оң жағын коэффициентке бөліп, содан кейін азайтты."),
            _opt(fmt(Fraction(c - b - a)), False, "eq_subtract_coefficient", "Вычел коэффициент вместо деления на него.", "Коэффициентке бөлудің орнына оны азайтты.")]
    return {"stem_ru": f"Решите уравнение: {a}x + {b} = {c}.", "stem_kz": f"Теңдеуді шешіңіз: {a}x + {b} = {c}.", "options": opts, "key_value": key,
            **_rub("1 балл; попросите сделать проверку подстановкой.", "1 ұпай; орнына қойып тексеруді сұраңыз.")}


# ---- order of operations ------------------------------------------------------------------------------------


def gen_order_ops(rng: random.Random, level: int) -> dict:
    c = rng.randint(3, 8)
    return {"family": "order_ops", "params": {"a": rng.randint(2, 9), "b": rng.randint(2, 6), "c": c, "d": rng.randint(1, c - 1)}}


def render_order_ops(p: dict) -> dict:
    a, b, c, d = p["a"], p["b"], p["c"], p["d"]  # a + b · c − d
    key = Fraction(a + b * c - d)
    opts = [_opt(fmt(key), True, None, "Верно: сначала умножение, затем сложение и вычитание слева направо.",
                 "Дұрыс: алдымен көбейту, содан кейін солдан оңға қосу мен азайту."),
            _opt(fmt(Fraction((a + b) * c - d)), False, "ops_left_to_right", "Выполнил действия строго слева направо.", "Амалдарды қатаң солдан оңға орындады."),
            _opt(fmt(Fraction(a + b * (c - d))), False, "ops_subtraction_first", "Вычел раньше умножения.", "Көбейтуден бұрын азайтты."),
            _opt(fmt(Fraction(a + b + c - d)), False, "ops_multiplication_as_addition", "Заменил умножение сложением.", "Көбейтуді қосумен алмастырды.")]
    return {"stem_ru": f"Вычислите: {a} + {b} · {c} − {d}.", "stem_kz": f"Есептеңіз: {a} + {b} · {c} − {d}.", "options": opts, "key_value": key,
            **_rub("1 балл; попросите пронумеровать порядок действий.", "1 ұпай; амалдардың ретін нөмірлеуді сұраңыз.")}


# ---- area and perimeter -------------------------------------------------------------------------------------


def gen_area_perimeter(rng: random.Random, level: int) -> dict:
    a = rng.randint(3, 9 + 3 * level)
    b = rng.choice([x for x in range(2, a + 5) if x != a and b_area_ok(a, x)])
    return {"family": "area_perimeter", "params": {"a": a, "b": b, "ask": rng.choice(["area", "perimeter"])}}


def b_area_ok(a: int, b: int) -> bool:
    return a * b != 2 * (a + b)  # area and perimeter must differ to discriminate


def render_area_perimeter(p: dict) -> dict:
    a, b, ask = p["a"], p["b"], p["ask"]
    area, per = a * b, 2 * (a + b)
    if ask == "area":
        opts = [_opt(f"{area} см²", True, None, "Верно: S = a · b.", "Дұрыс: S = a · b."),
                _opt(f"{per} см²", False, "area_perimeter_confusion", "Нашёл периметр вместо площади.", "Ауданның орнына периметрді тапты."),
                _opt(f"{a + b} см²", False, "area_adds_sides", "Сложил стороны.", "Қабырғаларды қосты."),
                _opt(f"{2 * area} см²", False, "area_doubles", "Умножил произведение на 2 по аналогии с периметром.", "Периметрге ұқсатып, көбейтіндіні 2-ге көбейтті.")]
        stem_ru, stem_kz, key = f"Найдите площадь прямоугольника со сторонами {a} см и {b} см.", \
            f"Қабырғалары {a} см және {b} см тіктөртбұрыштың ауданын табыңыз.", Fraction(area)
    else:
        opts = [_opt(f"{per} см", True, None, "Верно: P = 2 · (a + b).", "Дұрыс: P = 2 · (a + b)."),
                _opt(f"{area} см", False, "area_perimeter_confusion", "Нашёл площадь вместо периметра.", "Периметрдің орнына ауданды тапты."),
                _opt(f"{a + b} см", False, "perimeter_half", "Сложил только две стороны.", "Тек екі қабырғаны қосты."),
                _opt(f"{4 * a} см", False, "perimeter_square_rule", "Применил формулу периметра квадрата.", "Шаршы периметрінің формуласын қолданды.")]
        stem_ru, stem_kz, key = f"Найдите периметр прямоугольника со сторонами {a} см и {b} см.", \
            f"Қабырғалары {a} см және {b} см тіктөртбұрыштың периметрін табыңыз.", Fraction(per)
    return {"stem_ru": stem_ru, "stem_kz": stem_kz, "options": opts, "key_value": key, "key_text": opts[0]["text"],
            **_rub("1 балл; попросите нарисовать фигуру и подписать стороны.", "1 ұпай; фигураны салып, қабырғаларын белгілеуді сұраңыз.")}


EXTRA_FAMILIES = {
    "dec_add": (gen_dec_add, render_dec_add, {"decimal_align_right", "decimal_point_count", "decimal_place_value"}),
    "dec_compare": (gen_dec_compare, render_dec_compare, {"decimal_longer_larger", "decimal_place_value"}),
    "dec_mul": (gen_dec_mul, render_dec_mul, {"decimal_point_count"}),
    "proportion": (gen_proportion, render_proportion, {"cross_multiply_wrong", "proportion_additive", "ratio_order"}),
    "unit_rate": (gen_unit_rate, render_unit_rate, {"inverse_proportion", "proportion_additive"}),
    "neg_add": (gen_neg_add, render_neg_add, {"neg_wrong_sign", "neg_add_absolute", "neg_ignore_signs"}),
    "neg_compare": (gen_neg_compare, render_neg_compare, {"neg_compare_by_absolute"}),
    "linear_eq": (gen_linear, render_linear, {"eq_transfer_sign", "eq_divide_first", "eq_subtract_coefficient"}),
    "order_ops": (gen_order_ops, render_order_ops, {"ops_left_to_right", "ops_subtraction_first", "ops_multiplication_as_addition"}),
    "area_perimeter": (gen_area_perimeter, render_area_perimeter, {"area_perimeter_confusion", "area_adds_sides", "perimeter_half"}),
}

FAMILY_TITLES = {
    "frac_add": ("Сложение дробей с разными знаменателями", "Бөлімдері әртүрлі бөлшектерді қосу"),
    "mixed_sub": ("Вычитание смешанных чисел", "Аралас сандарды азайту"),
    "frac_compare": ("Сравнение дробей", "Бөлшектерді салыстыру"),
    "lcm": ("НОК", "ЕКОЕ"),
    "percent": ("Процент от числа", "Санның пайызы"),
    "dec_add": ("Сложение десятичных дробей", "Ондық бөлшектерді қосу"),
    "dec_compare": ("Сравнение десятичных дробей", "Ондық бөлшектерді салыстыру"),
    "dec_mul": ("Умножение десятичных дробей", "Ондық бөлшектерді көбейту"),
    "proportion": ("Решение пропорции", "Пропорцияны шешу"),
    "unit_rate": ("Прямая пропорциональность (задача)", "Тура пропорционалдық (есеп)"),
    "neg_add": ("Сложение чисел с разными знаками", "Таңбалары әртүрлі сандарды қосу"),
    "neg_compare": ("Сравнение отрицательных чисел", "Теріс сандарды салыстыру"),
    "linear_eq": ("Линейное уравнение", "Сызықтық теңдеу"),
    "order_ops": ("Порядок действий", "Амалдар реті"),
    "area_perimeter": ("Площадь и периметр прямоугольника", "Тіктөртбұрыштың ауданы мен периметрі"),
}
