# Data Agent handoff — OquMap Jury synthetic dataset

Дата: 11 ноября 2026. Набор полностью синтетический. Личные данные не использовались.

## Git и статус передачи

- Рабочая ветка: `data/jury-demo-dataset`.
- Запрошенный и фактически использованный base: `9cac9a267b23a704dab514b40a662dc68fec0769`.
- Удалённая `origin/claude/serene-carson-m1pbvz` при clone уже была на
  `2633882c963da0a94a53f4e69b5436d86bb1a0d3`; её новые commits **не включались**.
  Последняя доступная версия models также проверена: interventions/pilots/fidelity там нет.
- Commit 1, генератор/корпус/учебники/документация набора:
  `0fad0d7042c8a51b4643a1e4de2f7c6a83ffd7f3`.
- Commit 2, импортер/адаптер/проверки/отчёт:
  `d07e33c8900b73ec46a50e3b158ae68be85e8c8b`.
- Commit 3 содержит только этот handoff; его SHA — вершина локальной
  `data/jury-demo-dataset` (`git rev-parse data/jury-demo-dataset`).
- На момент подготовки handoff GitHub write-доступ отсутствует:
  `fatal: could not read Username for 'https://github.com': No such device or address`.
  **Remote commit не подтверждён, push нельзя считать выполненным.**
  PR и merge не создавались. Main и ветки Claude не изменялись.
- Для завершения отправки после подключения GitHub, из корня этого checkout:

```bash
git push --set-upstream origin HEAD:refs/heads/data/jury-demo-dataset
git ls-remote origin refs/heads/data/jury-demo-dataset
```

Сравните возвращённый SHA с `git rev-parse HEAD`. Не используйте force и не
отправляйте изменения в main либо другую ветку.

## Созданные файлы

Все изменения — новые файлы; production backend/frontend, validation и формулы
не редактировались, существующие пользовательские материалы не заменялись.

| Группа | Файлы |
|---|---|
| Основной импорт | `data/jury_demo/1_program.csv`, `2_editions.csv`, `3_item_bank.csv`, `4_roster.csv`, `5_responses.csv` |
| Будущие pilot fixtures | `data/jury_demo/6_interventions.csv`, `7_pilots.csv`, `8_fidelity_logs.csv`, `9_followups.csv` |
| Сопроводительные | `data/jury_demo/README.md`, `DATA_DICTIONARY.md`, `manifest.json`, `expected_findings.json`, `validation_report.json` |
| Точная математика и mappings | `data/jury_demo/item_math.json`, `misconceptions.json`, `material_mappings.json`, `materials/exercises.json` |
| Учебные материалы | `data/jury_demo/materials/textbook_A.pdf`, `textbook_B.pdf` — по 50 страниц |
| Генерация | `scripts/generate_jury_demo.py`, `scripts/jury_demo_docs.py` |
| Импорт и локальное подключение источников | `scripts/import_jury_demo.py`, `scripts/load_jury_material_links.py` |
| Валидация и integration runner | `scripts/jury_demo_support.py`, `scripts/verify_jury_demo.py` |
| Автотесты | `apps/api/tests/test_jury_demo.py` |
| Передача | `docs/DATA_AGENT_HANDOFF.md` |

## Размер и воспроизводимость

Seed **20261111**; отдельные deterministic RNG streams для состава, attendance,
item noise и response cells. Нет LLM/API, перебора seed, отбраковки генераций или
ручного редактирования отдельных ответов. Перекрывающиеся смеси входного уровня,
случайные школьные/классные/индивидуальные эффекты, практика, язык, сложность и M2.

| Сущность | Количество |
|---|---:|
| Школы | 8 |
| Классы | 16 (по 2 на школу) |
| Ученики | 384 (по 24 на класс) |
| Темы / цели | 6 / 18 |
| Учебники | 2 |
| Уникальные задания | 42 |
| Формы / assessments | 3 / 3 |
| Item bank строки | 126 |
| Responses CSV строки | 46 129 |
| Response ORM строки | 46 074 |
| Absent sittings | 55 |
| Omitted Response строки | 1 467 |

| Стадия | answered | omitted | absent sittings |
|---|---:|---:|---:|
| pre | 14 870 | 502 | 18 |
| post | 14 816 | 472 | 20 |
| followup | 14 921 | 493 | 17 |

Absent не получает балл; omitted хранится NULL. I34 поддерживает 0/1/2 балла,
рубрика задана. I41 имеет веса 0.7/0.3; I42 proposed и исключён из confirmed_only.
Все три формы имеют одинаковые 42 задания и одну шкалу identical_form. Повторение
формы обосновывает техническую сопоставимость, но сохраняет риск запоминания.

SHA256 `manifest.json`:
`637f0db0a80b428052a48610414619c4cf037bb0f397a9993cdea0e8dac4992f`.
SHA256 `5_responses.csv`:
`07a35ab762e96bf0bdc68721d57f0b9cddb39688561854d2cfcac52bf3426633`.
Остальные хэши и размеры — в manifest. Сам manifest и отдельно вычисляемый отчёт
не входят в его список хэшей. Шрифт DejaVu Sans фиксируется собственным SHA256.
Две чистые генерации и повторная генерация в том же каталоге дают идентичные байты,
включая оба PDF и документацию; проверки включены в pytest.

## Фактический импорт

Проверено настоящими `/api/v1/imports/validate` и `/api/v1/imports/commit` в новой
организации и временной SQLite, без использования обходного seed для Jury.
Повторный commit batch идемпотентен.

| Kind | Accepted | Rejected |
|---|---:|---:|
| program | 18 | 0 |
| editions | 2 | 0 |
| item_bank | 126 | 0 |
| roster | 384 | 0 |
| responses | 46 129 | 0 |

Data level: `pre_post_with_exposure`. Оба PDF загружены через `/api/v1/documents`,
извлечены штатной job: ready, по 50 страниц, реальная страница 47 читается.
Подключение source links — отдельный явный локальный fixture adapter по существующим
FragmentObjective/ContentFragment. Он проверяет SHA PDF, synthetic dataset, цели и
владельца, повторный запуск добавляет 0 связей. Этот же adapter исправляет только
метаданные этого fixture: demo codes=true и kz_verified=false. Стандартный CSV
импортер ошибочно приравнивает наличие KZ к verified; production код не менялся.

## Аналитические сигналы

Фильтры: post / first / confirmed_only / as_incorrect / learner; стандартизация
pre_three_level / pooled. Актуальные числа — `validation_report.json`.

| Сигнал | Получено | Допустимый диапазон |
|---|---:|---:|
| Обыкновенные дроби pre | 69.58% | Контроль направления падения |
| Обыкновенные дроби post | 61.31% | 59–65% |
| Цель 6.2.1 post | 46.02% | 43–50% |
| Сырая A−B | −6.07 п.п. | −7…−4 п.п. |
| Скорректированная A−B | +6.25 п.п. | +3…+7 п.п. |
| Donor: десятичные post / followup | 85.85% / 87.01% | Оба ≥80%, расхождение ≤5 п.п. |
| Пилот A, paired descriptive change | +9.24 п.п., 46 пар | +8…+12 п.п. |
| Пилот B, paired descriptive change | +3.33 п.п., 45 пар | −5…+5 п.п.; не оценка эффективности |

API и UI сравнения возвращают **B−A**, то есть противоположные знаки!
Кластер bootstrap — class, 8 классов на издание, 2000 повторов. Скорректированный
95% ДИ для **A−B** примерно +3.44…+8.93 п.п.; уровень adjusted_association,
causal_protocol_available=false. Каждая входная страта в каждом издании имеет ≥10
учеников. Сырая отрицательная связь объясняется разным входным составом классов.

M2 = текущий backend-код `numerators_not_scaled`, 316 учеников хотя бы с одним таким
ответом. Среди **неверных answered** ответов target items доля M2: A≈82.87%, B≈86.69%.
Это условные доли, не доли всех учеников и не причинный эффект страницы. Из-за более
слабого состава A его сырая частота M2 среди всех ответов может быть выше.

Материалы: B стр.47 — 6 сложений, 1 вычитание; A стр.47 — 4 сложения, 6 вычитаний,
стр.48 — 4 denominator drills. Реестр упражнений и точные ответы проверяются Fraction.
Связи source→objective подтверждены как синтетические fixture labels; proposed
разметка I42 различима. Source association не является причиной ошибки.

Штатная диагностика: preview на 3 задания, approvable=true, ключи перепроверены
текущим quiz service. Только diagnostic_only. Planner: явно заданный пилотный
сценарий дроби 6→8, десятичные 8→6, остальные темы fixed; сумма 38, optimal,
независимый validation.valid=true. Проведённые часы и минимумы соблюдены. Это
допустимость педагогического плана, не обещание прироста.

QA выявляет I13≈99% правильных, I30≈2.5%, I35≈19.5% omissions, I36 item-rest
correlation≈−0.49, один distractor I14 без выборов, реальные partial scores I34.
Production evidence выводит p/omissions/distractors; correlation пока доступна в
fixture validation_report, не объявляется существующим экраном приложения.

## Пилоты и схема Claude №2

В базовом commit нет Intervention, Pilot, FidelityLog; существующий FollowUp связан
с Decision и AnalysisRun и не является схемой trial/pilot. Поэтому 6–9 не импортируются
в core и не показываются как якобы существующий UI.

| Пилот | Выполнение | Fixture статус и границы |
|---|---:|---|
| A | 100%, все дополнительные упражнения | positive_signal: только положительная описательная динамика |
| B | 18.75% по минимуму minutes/items, половина занятий отменена | invalid_due_to_fidelity, запрещено интерпретировать как «метод не работает» |
| C | Удобная малая выборка, comparable=false | needs_more_data, n и outcome скрыты при n<10 |

**В A/B по два класса.** Production `analytics.paired.paired_change` требует ≥3 и
выдаёт unavailable/too_few_pairs. Это проверяется и сохраняется отдельно; порог
не ослаблен. Fixture positive_signal A не заменяет backend FollowUp.status и не
содержит доверительного интервала. Штатный decision follow-up на этих двух классах
может честно потребовать больше данных.

Для будущего подключения Claude №2, в порядке зависимостей:

1. `6_interventions.csv` → новая Intervention: цель, M2, 2×45 минут, 16 упражнений.
2. `7_pilots.csv` → новая Pilot и связи с Cohort; сохранять дизайн, даты, predeclared scope.
3. `8_fidelity_logs.csv` → FidelityLog, уникальность pilot+class+session, cancelled с нулевым actual.
4. `9_followups.csv` → eligibility/comparability scope; **не** превращать excluded в нули/absent
   и не расширять C всеми имеющимися project followup-ответами.
5. Зафиксировать policy: coverage≥70%, ≥30 пар; fidelity≥80%; small-cell suppression;
   правила числа кластеров/CI оставить явными. При недостаточной fidelity не возвращать
   «ineffective» независимо от знака динамики.
6. Добавить adapter для фактических новых моделей и интеграционные тесты. До этого
   6–9 — валидируемые fixtures, не production-import контракт.

## Проверки и команды

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e apps/api pytest ruff
.venv/bin/python scripts/generate_jury_demo.py
.venv/bin/python scripts/generate_jury_demo.py --out /tmp/jury-clean-copy
.venv/bin/python scripts/verify_jury_demo.py --report data/jury_demo/validation_report.json
.venv/bin/python -m pytest \
  apps/api/tests/test_jury_demo.py \
  apps/api/tests/test_onboarding.py apps/api/tests/test_imports.py \
  apps/api/tests/test_scoring.py apps/api/tests/test_comparison.py \
  apps/api/tests/test_planner.py apps/api/tests/test_determinism.py -q
.venv/bin/ruff check --config apps/api/pyproject.toml scripts/*jury*.py apps/api/tests/test_jury_demo.py
git diff --check
```

Итоговые два последовательных прогона набора: **53 passed, 1 xfailed**
(56.01 и 58.41 секунд). До расширения негативных проверок также 45 passed, 1 xfailed.
Реальный API import/analysis/documents/planner/diagnostics прогнан более двух раз;
два итоговых JSON-отчёта совпадают побайтно. Генератор повторён много раз; два финальных
вывода статистики и SHA совпадают. Математика проверена независимым Fraction-oracle;
искажённые FK, score, status, learner identifiers и fidelity fixtures отвергаются.
Ruff и git diff --check чистые. PDF визуально проверены после Poppler render: обложка,
типовой практикум, страницы 47 обоих учебников и KZ/denominator drills на странице 48.
Все 100 страниц открываются и имеют текстовый слой и номера.

Один warning — deprecation httpx/Starlette testclient в зависимостях исходного backend;
ради корпуса зависимости приложения не менялись.

## Известные незакрытые ограничения

1. **Production privacy suppression не реализована в базе.** Малый фильтр получает
   insufficient_data, но API продолжает возвращать численные сводки. Отдельный strict
   xfail документирует именно этот дефект и станет XPASS при его исправлении.
   Fixture pilot-report скрывает n<10, но не чинит приложение. Нельзя утверждать, что
   требование production-защиты малых групп выполнено.
2. Пилоты и fidelity — отдельные fixtures до реальной схемы Claude №2; UI пилотов нет.
3. Два класса A/B недостаточны для штатного парного интервала. Сигнал описательный.
4. KZ не проверен носителем; коды целей демонстрационные, материалы не реальные учебники.
5. Ретест той же формы, нерандомизированное распределение, различия учителей,
   созревание и регрессия к среднему ограничивают интерпретацию. Причинность не заявляется.
6. SQLite API integration проверена; PostgreSQL, браузерный end-to-end и последующий
   продвинувшийся origin tip отдельно не проверялись.
7. GitHub push требует авторизации, отсутствующей в исходной среде.

## Точный порядок передачи/cherry-pick

Данные зависят от исходного onboarding-кода на указанном base; новые production
миграции/формулы не нужны. В этом задании merge и cherry-pick **не выполнялись**.
Для координатора после получения ветки:

```bash
git fetch origin refs/heads/data/jury-demo-dataset:refs/remotes/origin/data/jury-demo-dataset
git switch -c integrate/jury-demo origin/claude/serene-carson-m1pbvz
git cherry-pick 0fad0d7042c8a51b4643a1e4de2f7c6a83ffd7f3
git cherry-pick d07e33c8900b73ec46a50e3b158ae68be85e8c8b
git cherry-pick origin/data/jury-demo-dataset
```

Последняя команда переносит отдельный commit этого handoff. Она предполагает
трёхкоммитный snapshot этой передачи: проверьте порядок через
`git log --reverse --oneline 9cac9a267b23a704dab514b40a662dc68fec0769..origin/data/jury-demo-dataset`.
Делайте это в новой integration-ветке, не в main и не в ветке другого Claude.
После переноса на более новый base повторите указанные проверки; при конфликтах
не ослабляйте валидацию и не подменяйте формулы.

Если push ещё заблокирован, предоставлен git bundle `OquMap-jury-demo.bundle`.
В существующем clone с исходным base импортируйте **только** эту ветку:

```bash
git bundle verify /path/OquMap-jury-demo.bundle
git fetch /path/OquMap-jury-demo.bundle refs/heads/data/jury-demo-dataset:refs/heads/data/jury-demo-dataset
# Далее три cherry-pick в том же порядке; вместо origin/data/... используйте data/...
```

Bundle требует наличия базового commit. Он сохраняет commits, PDF и CSV без потери
истории. После подключения GitHub можно просто переключиться на data/jury-demo-dataset
и выполнить разрешённый push в эту же ветку. Не создавайте PR и не merge без отдельной задачи.
