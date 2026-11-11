# Словарь данных OquMap Jury — SYNTHETIC

Источник истины: `services/onboarding.py`, `services/imports.py`, модели и OpenAPI
**базового commit 9cac9a267b23a704dab514b40a662dc68fec0769**. Дополнительные fixtures
не объявляются API-контрактом. Все данные синтетические; KZ не проверен носителем.

## Кодировки и единицы

CSV: UTF-8, запятая, LF; JSON: UTF-8, finite numbers. Даты ISO 8601 без времени.
Баллы не проценты; аналитические доли в [0,1], разность ×100 = процентные пункты.
ID в файлах — стабильные псевдокоды, в БД импортёр создаёт собственные UUID.
Отсутствующее значение CSV — пустая ячейка, JSON — null. Оно не означает ноль.

## 1_program.csv — 18 целей, по строке на цель

| Поля | Тип и смысл |
|---|---|
| subject, grade | Строка «Математика»; целое 6 |
| program_code, program_version, program_title | Код/версия/название синтетической программы; одинаковы во всех строках |
| language | ru — язык метаданных программы; язык класса задаётся отдельно |
| topic_code | FK-ключ темы, JURY-T1…JURY-T6 |
| topic_title_ru, topic_title_kz | Непустые RU/KZ названия |
| topic_order | Целое 1…6 |
| objective_code | Уникальный ключ цели; основная 6.2.1 |
| objective_text_ru, objective_text_kz | Непустые формулировки; KZ unverified |
| prerequisite_codes | Существующие objective_code через `;`; направленные предпосылки, без циклов |
| hours_current, hours_min, hours_max, hours_elapsed | Целые часы; elapsed≤current, min≤current≤max; повторяются согласованно для каждой цели темы |

Итого 38 часов: дроби 6 (min6/max8/elapsed4), десятичные 8 (min6/max8/elapsed4),
прочие по6 (min=max6, elapsed 3/3/2/2). Название темы не является FK.

## 2_editions.csv — 2 издания

| Поля | Тип и смысл |
|---|---|
| edition_code | Уникальный ключ JURY-A или JURY-B |
| title, edition_label | Синтетическое название и выпуск |
| year, grade | 2026 и 6, целые |
| language | ru; KZ-фрагмент в PDF отдельно обозначен непроверенным |
| usage_permission | Метка synthetic и лицензия CC0-1.0 |

## 3_item_bank.csv — 126 строк, 42 уникальных задания ×3 формы

| Поля | Тип и смысл |
|---|---|
| form_code, form_name | JURY-PRE / JURY-POST / JURY-FOLLOWUP и название |
| form_stage | pre / post / followup |
| scale_code, scale_linking | Общая JURY-IDENTICAL, identical_form; у всех трёх форм один и тот же состав |
| item_code, position | JURY-I01…JURY-I42; позиция 1…42 внутри формы |
| stem_ru, stem_kz | Непустые условия; KZ unverified |
| item_type | single_choice; для I34 — open с явной рубрикой и баллом |
| options | `буква=текст` через `|`; правильные буквы распределены, не всегда A |
| answer_key | Ключ выбора или точный численный ответ для open |
| max_points | 1; у I34 — 2 |
| objective_codes | `код` либо `код:вес;код:вес`; сумма весов 1, без двойного подсчёта |
| mapping_status | confirmed или proposed; I42 proposed, не участвует в confirmed_only |
| misconceptions | `буква=backend_code` через `|`; правильный вариант не помечается ошибкой |

| Случай | Задание и смысл |
|---|---|
| Основная подцель | I01–I04, разные знаменатели |
| Слишком лёгкое | I13, доля верных >95% |
| Слишком сложное | I30, доля верных <10% |
| Низкая/отрицательная discrimination | I36, item-rest correlation <0 |
| Много omissions | I35, >15% |
| Неработающий distractor | I14: третий сгенерированный distractor не выбирается; его буква хранится в item_math |
| Partial credit | I34: 2 — верное преобразование и ответ; 1 — верное деление обеих частей, вычисление не закончено; 0 — неверное преобразование |
| Множественная связь | I41: 6.7.3:0.7;6.7.1:0.3 |
| Предложенная связь | I42: proposed |

`item_math.json`: по заданию code, topic, objective, op, params, answer, options с
key/text/tag, distractors, answer_key, difficulty, mapping_status, objective_codes,
quality и rubric. Точные ключи и все distractors пересчитываются рациональной
арифметикой. Отрицательная discrimination — свойство сгенерированных ответов,
не математически неверный ключ. Item-rest QA — отдельная проверка: production evidence
сейчас показывает p_correct, omission и распределение вариантов, а не эту корреляцию.

## Misconceptions

| Демо-код | backend_code | Значение |
|---|---|---|
| M1 | add_across | Складывание числителей и знаменателей по отдельности |
| M2 | numerators_not_scaled | Общий знаменатель найден, числители не домножены |
| M3 | sign_lost | Потеря знака |
| M4 | order_error | Порядок действий/вычислительная ошибка |
| M5 | area_perimeter | Путаница площади и периметра |
| CALC | calc_error | Общая вычислительная ошибка/выбор действия, без приписывания M4 |

Точный sidecar — `misconceptions.json`. M1/M2 используют уже поддерживаемые коды,
поэтому штатный генератор diagnostic quizzes может работать с этими ответами.
Один выбранный distractor означает гипотезу, не диагноз ученика.

## 4_roster.csv — 384 ученика

| Поля | Тип и смысл |
|---|---|
| school_code, school_name | JURY-S01…08, «Синтетическая школа NN» |
| class_code | Уникальный класс JURY-SNN-61/62; по два на школу |
| teacher_code | JDT01…JDT16, только псевдокод |
| grade, language, academic_year | 6; ru/kz; 2026-2027 |
| learner_code | JDL0001…JDL0384, уникален, никаких настоящих ФИО |
| edition_code | FK в editions; одна основная книга на класс, обе книги в каждой школе |
| period_start, period_end | ISO dates: 2026-09-01…2026-12-20 |

Отдельного неподдерживаемого класса-FK в CSV не придумано: onboarding создаёт School,
Cohort, Teacher, Learner и MaterialExposure из согласованных строк roster.
В каждом классе ровно 24 ученика. Индивидуальные latent ability и misconception propensity
используются только генератором и не экспортируются как «измеренные» признаки.

## 5_responses.csv — 46 129 строк

| Поля | Тип и смысл |
|---|---|
| learner_code | FK в roster |
| assessment_code | JURY-PRE-2026 / JURY-POST-2026 / JURY-FOLLOWUP-2026 |
| form_code | FK в forms, согласован с assessment |
| item_code | FK в items формы; пусто только для absent |
| attempt | Целое 1; уникальный ключ assessment+learner+item+attempt |
| date | 2026-09-01 / 2026-10-12 / 2026-11-02; 21 день post→followup |
| status | answered / omitted / absent |
| score | Число 0…max_points у answered; пусто у остальных |
| response | Буква выбора; у open — точный ответ или описание выполненного шага; пусто для omitted/absent |

Одна absent-строка на sitting, без item/score/response; иных строк этого ученика на
этом тестировании нет. Present даёт 42 строки, включая omissions. Всего 55 absent
sittings; для каждой стадии 4–7% отсутствий. Из 46 074 Response часть omitted:
они не wrong в хранилище, но правило as_incorrect включает их в знаменатель и
нулевой вклад в числитель при расчёте. answered+score0 — реальная ошибка.
Неизмеренное задание вообще не создаёт строку. Формы одинаковы, но ретест имеет
риск запоминания; это не независимая оценка переноса навыка.

## 6–9: отдельный контракт fixtures (не production imports)

| Файл | Поля и проверки |
|---|---|
| 6_interventions.csv | intervention_id PK; objective_code FK; misconception M2; title_ru; sessions_planned=2; minutes_per_session=45; practice_items=16; is_synthetic=true |
| 7_pilots.csv | pilot_id PK; intervention_id FK; class_codes через `;` FK roster; start_date/end_date; baseline_assessment/followup_assessment FK; design=nonrandomized_within_group; is_synthetic |
| 8_fidelity_logs.csv | log_id PK; pilot_id FK; class_code в этом пилоте; session 1/2; date; planned_minutes/actual_minutes; planned_items/completed_items; status completed/cancelled; is_synthetic |
| 9_followups.csv | followup_id PK; pilot_id/learner_code/assessment_code FK; included true/false; exclusion_reason пусто либо not_sampled; comparable true/false; days_since_post=21; is_synthetic |

Одна запись followups на eligible learner, не отдельный балл; повторные ответы находятся
в 5_responses. В C include лишь 6 учеников, остальные not_sampled. Это отдельная
ограниченная выборка **пилота**, даже если более широкий проект имеет followup-ответы:
для анализа C нельзя тихо расширить заранее объявленную выборку до всех 384.
Строки C несопоставимы по дизайну и не должны интерпретироваться как эффект.

Fixture evaluator: fidelity = min(сумма actual_minutes/сумма planned_minutes,
сумма completed_items/сумма planned_items). Сначала требуется ≥30 пар, ≥70% coverage
и comparable; затем fidelity≥0.8. При нарушении fidelity статус
invalid_due_to_fidelity независимо от знака динамики. Положительная описательная
динамика при прошедших проверках — positive_signal; это не production FollowUp.status.
Для n<10 n_paired и observed_gain скрыты (null), ученические ID в сводке отсутствуют.
Два класса в A/B не позволяют production paired_change построить интервал; backend
available=false фиксируется отдельно, без обхода минимального числа кластеров.

## Материалы, provenance, результаты

| Файл | Содержимое |
|---|---|
| materials/textbook_A.pdf, textbook_B.pdf | По 50 физических страниц, номера внизу равны физическим; содержание на стр.2; главная стр.47 |
| materials/exercises.json | edition_code, page, number (составной PK), op, params, answer, objective_code, role; точный реестр практики |
| material_mappings.json | edition_code, item_code, objective_code, page_physical, page_printed, status, role, origin; ссылки проверены по существующим кодам |
| manifest.json | is_synthetic, seed, base_commit, counts, font_sha256, algorithm, kz_note, files[name].sha256/bytes |
| expected_findings.json | Интервалы допустимых сигналов; фильтры, знак сравнения, схема стандартизации, ожидания пилотов |
| validation_report.json | Фактический API import, source extraction, scoring/comparison, planner, diagnostic, fixture pilots и ограничения |

Генерация не включает текущую дату, случайные UUID или runtime durations. Manifest
не включает сам себя и отдельно создаваемый validation_report. Исходные документы
построены программно, лицензия только на синтетическое учебное содержимое CC0-1.0;
шрифт берётся из среды под собственной лицензией, его файл здесь не распространяется.
