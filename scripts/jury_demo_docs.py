"""Versioned documentation sources included by the deterministic corpus generator."""

README = r"""# OquMap Jury: математика 6 класса — SYNTHETIC

Полностью синтетический, изолированный проект. **8 школ, 16 классов, 384 ученика,
18 демонстрационных целей, 42 задания, 3 измерения, 46 074 item-level responses**.
Школы, учителя, ученики, издания, практика и результаты вымышлены. Никаких ФИО,
адресов и контактов. `6.2.1` — демонстрационный код, а не утверждение о соответствии
официальной программе Казахстана. Все KZ-поля и фрагменты **не проверены носителем**.

## Сгенерировать и проверить

Из корня репозитория, Python 3.11–3.13 (проверено на 3.12), зависимости backend:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e apps/api pytest
.venv/bin/python scripts/generate_jury_demo.py
.venv/bin/python scripts/generate_jury_demo.py --out /tmp/oqumap-jury-copy
.venv/bin/python scripts/verify_jury_demo.py --report data/jury_demo/validation_report.json
.venv/bin/python -m pytest apps/api/tests/test_jury_demo.py -q
```

Для Windows используйте `.venv\Scripts\python.exe` вместо `.venv/bin/python`.
PDF требуют DejaVu Sans (`fonts-dejavu-core` на Debian/Ubuntu); можно передать
`--font /путь/DejaVuSans.ttf`. Для идентичных PDF нужен тот же файл шрифта: его SHA256
сохранён в manifest. Версии reportlab и backend закреплены в `apps/api/pyproject.toml`.
Генератор не требует сервера, LLM или сети; seed **20261111**. CSV UTF-8 без BOM,
разделитель запятая, JSON UTF-8, строки LF. Все ключи и порядок стабильны; даты PDF
зафиксированы режимом `invariant`. Содержимое `README.md` и `DATA_DICTIONARY.md`
создаётся из `scripts/jury_demo_docs.py`. Для изменения документации редактируйте источник.
`manifest.json` содержит SHA256/размер всех генерируемых файлов, кроме себя.
`validation_report.json` — отдельно воспроизводимый результат проверки, не вход генератора.

Проверка использует **временную SQLite**, создаёт отдельную организацию, проходит
настоящие HTTP validate/commit, загрузку PDF, extraction, аналитику, диагностику и planner.
Она не подключается к пользовательской БД. PostgreSQL и браузер отдельно не проверялись.

## Импорт в приложение

1. В обычной организации с правами методиста создайте **новый** проект
   `OquMap Jury - Математика 6 (synthetic)` с `is_synthetic=true`.
   Не используйте штатный `/demo-3min`: его тур привязан к другому корпусу.
2. На `/import` выбирайте именно этот проект. Импортируйте по очереди:
   `1_program.csv` → kind `program`; `2_editions.csv` → `editions`;
   `3_item_bank.csv` → `item_bank`; `4_roster.csv` → `roster`;
   `5_responses.csv` → `responses`. На каждом шаге validate, **0 rejected**, затем commit.
3. На `/quality` проверьте 384 ученика, 16 классов, 8 школ и уровень
   `pre_post_with_exposure`. В 5-м CSV 46 129 строк: 46 074 ответа и 55 отсутствий.
   Отсутствия импортируются в Sitting, не в Response и не как нулевые баллы.
4. На `/materials` загрузите `materials/textbook_A.pdf` в издание `JURY-A`,
   `materials/textbook_B.pdf` — в `JURY-B`. Дождитесь `ready`, 50 страниц у каждого.
5. После извлечения PDF подключите заранее подготовленные связи с целями:

```bash
# OQUMAP_DATABASE_URL должен указывать на ту же БД, что и ваш backend.
# Значения подключений храните в окружении, не в git и не в аргументах команды.
.venv/bin/python scripts/load_jury_material_links.py --dataset-id ID_НОВОГО_ПРОЕКТА
```

Это явный локальный fixture-adapter, а не новый endpoint. Он проверяет synthetic,
состав целей и SHA256 обоих PDF, работает по текущим моделям и идемпотентен.
Он создаёт FragmentObjective, помечает коды как демонстрационные и снимает
ошибочно выставляемые импортёром `kz_verified` для непроверенного перевода.
Без этого шага CSV уже анализируются, но цепочка до страницы PDF не подключена.
Item→страница хранится в sidecar; backend связывает источник через цель, не через
отдельную production-модель ItemFragment. Связи означают релевантность, не причинность.

Вместо ручного импорта можно использовать действующие API с токеном методиста:

```bash
# OQUMAP_TOKEN задаётся в окружении. --url — origin, без /api/v1.
.venv/bin/python scripts/import_jury_demo.py --url http://localhost:8000
```

Команда создаёт **новый** проект, импортирует пять CSV и загружает PDF. Затем нужен
тот же локальный adapter с напечатанным dataset ID. При ошибке ID уже созданного
проекта остаётся в выводе; проверьте его качество и продолжайте недостающий шаг через UI.
Повторный запуск import-команды создаёт другой проект, это не команда сброса.

**Файлы 6–9 не загружать в production imports.** На базовом commit нет моделей
interventions/pilots/fidelity и соответствующих endpoints. Они проверяются отдельно
по FK, типам и правилам fixtures; результаты доступны в `validation_report.json`.
Никакого несуществующего экрана пилотов в этой ветке не добавлено.

## Демо данных за 5 минут

Начните с уже импортированного и выбранного проекта, чтобы время не ушло на загрузку.
Фильтры: post, первая попытка, confirmed_only, learner aggregation,
omitted_policy=as_incorrect. Omitted хранится NULL и учитывается как неправильный
**только выбранным правилом расчёта**, не подменяется нулём в исходных данных.

| Время | Экран или файл | Действие и ожидаемый сигнал |
|---|---|---|
| 0:00–0:30 | `/datasets`, `/overview` | Выбрать Jury. Дроби `JURY-T1` около 62% (фактически 61,3%); входная проверка около 69,6% |
| 0:30–1:00 | `/topic`, `/graph` | Открыть дроби → цель `6.2.1`, около 46%, самая слабая цель темы |
| 1:00–1:30 | `/topic`, `/materials` | M2 = `numerators_not_scaled`; открыть источник «Учебник B», физическая и печатная страница **47** |
| 1:30–2:15 | `/compare` | A=`JURY-A`, B=`JURY-B`, pre_three_level, pooled. Сырая A−B ≈ −6,1 п.п.; скорректированная ≈ +6,3 п.п. API/UI отображают **B−A**, поэтому их знаки противоположны этой записи |
| 2:15–2:45 | `/planner` | Дроби 6→8, десятичные 8→6; остальные темы фиксировать. У дробей min=max=8, у десятичных min=max=6 в сценарии. Бюджет **38**, solver optimal, независимый validator valid |
| 2:45–3:15 | `/quizzes` | Сформировать 3 диагностических задания по наблюдаемым ошибкам, проверить ключи. diagnostic_only, не итоговая оценка |
| 3:15–4:15 | `7_pilots.csv`, `8_fidelity_logs.csv`, `validation_report.json` | Fixture-пилот A: два класса, 100% выполнения. B: отмены, fidelity 18,75%, invalid_due_to_fidelity |
| 4:15–4:45 | `validation_report.json`, раздел pilots | Через 21 день: A около +9,2 п.п. на 46 парах; B около +3,3 п.п. на 45 парах; C needs_more_data, малые outcome-ячейки скрыты |
| 4:45–5:00 | Итог | Наблюдаемая связь и описательная динамика. Проверить гипотезу M2 и провести пилот с лучшим дизайном; причинный эффект не доказан |

Файл `expected_findings.json` задаёт интервалы, а не хрупкие точные числа:
дроби 59–65%, цель 43–50%, сырая A−B −7…−4 п.п., скорректированная +3…+7 п.п.
Пилот A +8…+12 п.п., B −5…+5 п.п. при недопустимости вывода об эффективности.
Числа вычисляются из ответов; production-формулы не менялись.

## Почему меняется знак

Каждая школа использует оба учебника; в каждом издании есть классы RU и KZ.
В A чаще попадают ученики из слабой компоненты перекрывающейся смеси, в B — из
сильной. Это вероятностное распределение, а не идеально отделённые группы.
Индивидуальный уровень, школьный и классный эффекты, сложность, язык, практика,
склонность к M2, шум, пропуски и отсутствие участвуют в генерации. После учёта
входных low/mid/high страт практика A связана с более высоким результатом.
Схема pre_three_level и pooled веса объявлены заранее; нет подбора seed или
переписывания отдельных ответов ради целевых процентов.

Страница 47 B содержит 6 упражнений на сложение, 1 на вычитание, без отдельных
упражнений на домножение числителей. В A на странице 47 — 4 сложения, 6 вычитаний,
на странице 48 ещё 4 упражнения на дополнительный множитель. Полный реестр заданий
и точных ответов — `materials/exercises.json`. На M2 приходится большая часть
неверных ответов на проблемных заданиях; среди неверных ответов B эта доля выше.
**Это условная доля среди ошибок, а не доля всех учеников.** Сырая частота M2 среди
всех ответов A может быть выше из-за более слабого входного состава.

Десятичные дроби — единственный допустимый донор по min/max; уже проведённые часы
не изымаются. Planner показывает допустимость выбранного сценария, не прогноз прироста.

## Допустимые и недопустимые выводы

Допустимо: проблемная подцель, распространённая гипотеза ошибки, разрыв в покрытии,
наблюдаемая скорректированная связь учебника с результатом, выполнимый план часов,
описательная повторная динамика при проверенном выполнении.

Недопустимо: «B вызвал ошибки», «A доказанно лучше», «два часа обеспечат +10%»,
«метод B не работает», «pilot A доказал причинность», «много строк = много независимых
кластеров», «proposed = confirmed», «KZ проверен специалистом».

Оба успешных по объёму пилота имеют лишь **два класса**. Текущий production
`paired_change` требует ≥3 классов и честно возвращает unavailable/too_few_pairs;
fixture-only positive_signal A означает лишь положительную **описательную** динамику,
без CI и без подмены действующего backend-статуса. C использует малую удобную
выборку и не проходит сопоставимость. Повторяется та же форма: запоминание,
созревание, регрессия к среднему, учитель и неучтённые факторы остаются альтернативами.

**Известный блокер privacy в базовом backend:** малые фильтры помечаются
insufficient_data, но численные сводки всё ещё возвращаются. Новый pilot-report
скрывает n<10; это не исправляет production API. Отдельный strict xfail фиксирует
незакрытое требование. Не используйте этот проект как подтверждение готовности
production-защиты реальных персональных данных. Все поставляемые записи синтетические.

## Сброс и повторение

Генератор перезаписывает только свои именованные файлы в `data/jury_demo/` или --out,
не трогает `data/demo`, шаблоны и существующие пользовательские материалы. Для нового
прогона создайте новый изолированный проект (новый ID), импортируйте те же файлы.
Повторный commit того же batch идемпотентен; дубликат программы в том же проекте
правильно блокируется. Автоматического destructive reset или удаления нет.
Отдельная verify-команда сама удаляет только свою временную БД и storage.
"""

DICTIONARY = r"""# Словарь данных OquMap Jury — SYNTHETIC

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
"""
