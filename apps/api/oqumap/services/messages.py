"""Server-side message catalog (RU/KZ) for reason codes that appear in analyses and reports.

The API always returns the code + params; the rendered text is added for convenience so that the screen,
the assistant and the PDF report use identical wording. Kazakh wording is unverified (see handoff).
"""

from __future__ import annotations

REASONS: dict[str, tuple[str, str]] = {
    "edition_confounded_with_teacher": (
        "Издание {arm_code} используют классы только одного учителя: влияние пособия неотделимо от влияния учителя. Рейтинг недопустим.",
        "{arm_code} басылымын тек бір мұғалімнің сыныптары қолданады: құрал әсерін мұғалім әсерінен ажырату мүмкін емес. Рейтинг жасауға болмайды.",
    ),
    "edition_confounded_with_school": (
        "Издание {arm_code} используется только в одной школе: влияние пособия неотделимо от влияния школы.",
        "{arm_code} басылымы тек бір мектепте қолданылады: құрал әсерін мектеп әсерінен ажырату мүмкін емес.",
    ),
    "arm_without_outcome": ("Для издания {arm_code} нет результатов итоговой проверки.",
                            "{arm_code} басылымы үшін қорытынды тексеру нәтижелері жоқ."),
    "assignment_at_school_level": (
        "Издание выбрано на уровне школы; неопределённость оценивается по школам, а не по классам.",
        "Басылым мектеп деңгейінде таңдалған; белгісіздік сыныптар бойынша емес, мектептер бойынша бағаланады.",
    ),
    "few_clusters": (
        "Мало независимых групп ({unit}): А — {a}, Б — {b}, требуется не менее {min} на издание. Интервал не рассчитывается; число ответов не заменяет число групп.",
        "Тәуелсіз топтар аз ({unit}): А — {a}, Б — {b}, әр басылымға кемінде {min} қажет. Интервал есептелмейді.",
    ),
    "no_baseline_measure": ("Нет входной проверки: поправка на исходный уровень невозможна, доступно только описание.",
                            "Кіріс тексеру жоқ: бастапқы деңгейге түзету мүмкін емес, тек сипаттама қолжетімді."),
    "low_baseline_coverage": ("Входной уровень известен только у {coverage_pct} учеников с итоговым результатом.",
                              "Қорытынды нәтижесі бар оқушылардың тек {coverage_pct} бастапқы деңгейі белгілі."),
    "empty_stratum": (
        "Пустые группы входного уровня: {strata_list}. Скорректированный показатель не рассчитывается — экстраполяция не выполняется.",
        "Кіріс деңгейінің бос топтары: {strata_list}. Түзетілген көрсеткіш есептелмейді — экстраполяция жасалмайды.",
    ),
    "small_stratum": ("Малочисленные группы входного уровня (менее {min} учеников): {strata_list}.",
                      "Кіріс деңгейінің шағын топтары ({min} оқушыдан аз): {strata_list}."),
    "mixed_exposure_excluded": ("Классы с несколькими основными изданиями по теме исключены: {classes_list}.",
                                "Тақырып бойынша бірнеше негізгі басылымы бар сыныптар алынып тасталды: {classes_list}."),
    "forms_not_linked": (
        "Издания проверялись разными формами ({forms_list}) на разных шкалах ({scales_list}) без выравнивания. Сравнение баллов недопустимо.",
        "Басылымдар әртүрлі формалармен ({forms_list}) теңестірілмеген әртүрлі шкалаларда ({scales_list}) тексерілген. Ұпайларды салыстыруға болмайды.",
    ),
    "common_items_only": ("Формы связаны общими заданиями; результат считается только по {n_common_items} общим заданиям.",
                          "Формалар ортақ тапсырмалармен байланысқан; нәтиже тек {n_common_items} ортақ тапсырма бойынша есептеледі."),
    "mapping_unverified": ("Связи заданий темы с целями не подтверждены методистом.",
                           "Тақырып тапсырмаларының мақсаттармен байланысы әдіскермен расталмаған."),
    "language_mismatch": ("Различается язык обучения групп: А — {a_list}, Б — {b_list}.",
                          "Топтардың оқыту тілі әртүрлі: А — {a_list}, Б — {b_list}."),
    "grade_mismatch": ("Различается класс обучения групп: А — {a_list}, Б — {b_list}.",
                       "Топтардың оқу сыныбы әртүрлі: А — {a_list}, Б — {b_list}."),
    "periods_do_not_overlap": ("Периоды обучения групп не пересекаются: А — {a_list}, Б — {b_list}.",
                               "Топтардың оқу кезеңдері қиылыспайды: А — {a_list}, Б — {b_list}."),
    "edition_language_differs": ("Издания на разных языках: А — {a}, Б — {b}.", "Басылымдар әртүрлі тілде: А — {a}, Б — {b}."),
    "multiple_comparisons_exploratory": (
        "Таблица по всем темам — разведочная: при множестве сравнений часть различий может быть случайной.",
        "Барлық тақырыптар бойынша кесте — барлау сипатында: көп салыстыруда кейбір айырмалар кездейсоқ болуы мүмкін.",
    ),
}

STRATA = {"low": ("низкий", "төмен"), "mid": ("средний", "орташа"), "high": ("высокий", "жоғары")}


def _fmt(template: str, params: dict, lang: str) -> str:
    p = dict(params)
    for k, v in list(params.items()):
        if isinstance(v, list):
            if v and isinstance(v[0], dict) and "stratum" in v[0]:
                p[f"{k}_list"] = ", ".join(
                    f"{STRATA.get(x['stratum'], (x['stratum'],) * 2)[0 if lang == 'ru' else 1]} ({x.get('arm_code', x.get('arm'))}"
                    + (f", n={x['n']}" if "n" in x else "") + ")" for x in v)
            else:
                p[f"{k}_list"] = ", ".join(str(x) for x in v)
    if "coverage" in p and p["coverage"] is not None:
        p["coverage_pct"] = f"{round(100 * p['coverage'])}%"
    try:
        return template.format(**p)
    except (KeyError, IndexError, ValueError):
        return template


def render_reasons(reasons: list[dict], edition_codes: dict[str, str] | None = None) -> list[dict]:
    out = []
    for r in reasons:
        params = dict(r.get("params", {}))
        if edition_codes and "arm" in params:
            params["arm_code"] = edition_codes.get(params["arm"], params["arm"])
        params.setdefault("arm_code", params.get("arm", ""))
        if edition_codes and "strata" in params:
            params["strata"] = [dict(s, arm_code=edition_codes.get(s.get("arm"), s.get("arm"))) for s in params["strata"]]
        ru, kz = REASONS.get(r["code"], (r["code"], r["code"]))
        out.append({**r, "message_ru": _fmt(ru, params, "ru"), "message_kz": _fmt(kz, params, "kz")})
    return out


INFERENCE = {
    "descriptive": ("Описательное сравнение", "Сипаттамалық салыстыру"),
    "adjusted_association": ("Скорректированная связь (не причинный вывод)", "Түзетілген байланыс (себептік қорытынды емес)"),
    "causal_protocol": ("Оценка воздействия по протоколу", "Хаттама бойынша әсерді бағалау"),
}
COMPARABILITY = {
    "comparable": ("Сопоставимо", "Салыстыруға болады"),
    "limited": ("Ограниченно сопоставимо", "Шектеулі салыстыруға болады"),
    "not_comparable": ("Несопоставимо", "Салыстыруға болмайды"),
}
FOLLOW_UP = {
    "needs_more_data": ("Нужно больше данных", "Көбірек дерек қажет"),
    "positive_signal": ("Есть положительный сигнал", "Оң белгі бар"),
    "not_confirmed": ("Не подтверждено", "Расталмады"),
    "needs_revision": ("Требует пересмотра", "Қайта қарау қажет"),
}
PLAN_STATUS = {
    "optimal": ("Оптимальное решение при заданных весах", "Берілген салмақтар бойынша оңтайлы шешім"),
    "feasible": ("Допустимое решение (оптимальность не доказана)", "Жарамды шешім (оңтайлылығы дәлелденбеген)"),
    "infeasible": ("Ограничения несовместимы", "Шектеулер үйлеспейді"),
    "unknown": ("Решатель не успел определить результат; невозможность не доказана", "Шешуші нәтижені анықтай алмады; мүмкін еместігі дәлелденбеген"),
    "invalid": ("Некорректная постановка задачи", "Есептің қойылымы дұрыс емес"),
}
CONSTRAINT_LABELS = {
    "budget": ("Общий бюджет часов = {value}", "Сағаттардың жалпы бюджеті = {value}"),
    "min_hours": ("Тема {topic_code}: не меньше {value} ч", "{topic_code} тақырыбы: кемінде {value} сағ"),
    "max_hours": ("Тема {topic_code}: не больше {value} ч", "{topic_code} тақырыбы: көп дегенде {value} сағ"),
    "fixed": ("Тема {topic_code}: зафиксирована на {value} ч", "{topic_code} тақырыбы: {value} сағ бекітілген"),
    "elapsed_hours": ("Тема {topic_code}: уже проведено {value} ч", "{topic_code} тақырыбы: {value} сағ өткізілген"),
    "max_change": ("Тема {topic_code}: изменение не более ±{value} ч", "{topic_code} тақырыбы: өзгеріс ±{value} сағ артық емес"),
}


def label_constraint(c: dict) -> dict:
    ru, kz = CONSTRAINT_LABELS.get(c["constraint"], (c["constraint"], c["constraint"]))
    return {**c, "message_ru": ru.format(**c), "message_kz": kz.format(**c)}
