# Передача: контур «качество оценивания → интервенция → реализация → повторное измерение → обучение» (Claude №2)

## 1. Ветка и база
* Ветка: `claude/measurement-learning-loop` (запушена в `origin`). Merge/rebase в `main` или в ветку первого Claude
  (`claude/serene-carson-m1pbvz`) **не выполнялись**.
* База: `cd70f1c7290a09801ddeb7aa19690042056782bf` (+ коммит брифа `cd9fafe`).
* Отличие от брифа: бриф запрещал push, пользователь в задании явно попросил push только в эту ветку — выполнено так.
  Рабочий каталог — облачный клон, а не `C:\Users\User\Documents\ChatGPT\OquMap-claude2-c2`.

Коммиты (от старых к новым):
| Коммит | Содержание |
|---|---|
| `dcf13a7` | Assessment quality analytics and tests |
| `122e74a` | Регистрация quality-роутера (main.py), схемы `schemas/interventions.py` |
| `76c5fba` | Модели `measurement_models.py`, импорт из `models.py`, Alembic `c2a7e5f1b3d9`, тест миграций |
| `22a04c5` | `ruff check .` проходит на сгенерированных миграциях (pyproject) |
| `ae5284d` | Intervention library models and API |
| `55d4f0a` | Pilot protocol and state machine |
| `6132859` | Fidelity tracking and learning loop |
| `cb76541` | Intervention portfolio API, routes, OpenAPI drift test |
| `5842229` | Детерминированное демо `measurement_loop` |
| `55d78eb` | Перегенерированный `data/demo/manifest.json` |
| `468c839` | Уточнение правила дистрактора, запрет будущих дат журнала, поле `fidelity` в результате |
| `56fb174` | Functional frontend for quality and interventions (+ vitest) |
| `79808ba` | Маршруты/навигация (App.tsx, Layout.tsx), перегенерированные типы |
| `5452ebc` | Playwright-сценарий `tests/e2e/measurement.spec.ts` |
| `a75931c` | Документация |
| (этот) | Handoff |

## 2. Что реализовано
### Модели (миграция `c2a7e5f1b3d9`, поверх `d964e255551f`; все таблицы с `org_id`)
`interventions`, `intervention_versions` (неизменяемы после рецензии, `content_sha256`), `intervention_targets`,
`pilots` (снимок версии + sha256, дизайн, предел вывода, рандомизация), `pilot_cohorts`, `pilot_events`,
`fidelity_logs` (append-only, исправления через `corrects_log_id`), `pilot_outcomes` (неизменяемые, по fingerprint),
`pilot_conclusions`, `intervention_evidence` (proposed/accepted/rejected). CHECK-ограничения на статусы, дизайны,
группы, уровни доказательств; уникальность кодов в организации и версий; FK на наборы, классы, темы, цели, проверки,
решения.

### Endpoints
`/api/v1/quality/assessments`, `/quality/assessments/{id}`, `/quality/assessments/{id}/items`, `/quality/items/{id}`;
`/interventions` (list/create/get/patch/versions/review/delete draft/archive/targets/suggest/evidence),
`/intervention-evidence/{id}/review`; `/pilots` (list/create/get/patch/randomize/transition), `/pilots/{id}/fidelity`,
`/pilots/{id}/fidelity-logs`, `/pilots/{id}/follow-up`, `/pilots/{id}/outcomes`, `/pilots/{id}/conclusions`,
`/learning/summary`, `/portfolio/interventions`. Полный список — `docs/API.md` (раздел «Измерение и организационное
обучение»), контракт — `packages/contracts/openapi.json`.

### Экраны (`apps/web/src/features/{quality,interventions,followup,measurement}`)
`/quality`, `/quality/:assessmentId`, `/interventions` (+ подбор `?suggest=1`), `/interventions/:id`, `/pilots/new`,
`/pilots/:id`, `/pilots/:id/fidelity`, `/pilots/:id/follow-up`, `/portfolio/interventions`. Отдельная группа навигации
«Измерение и обучение». Словарь RU/KZ — `features/measurement/i18n.ts` (общий переключатель языка). Стили — только
существующие классы/токены; декоративный редизайн не делался.

### Методы
`aq-v1` (качество проверок), `fidelity-v1`, `loop-v1` — определения в `docs/ASSESSMENT_QUALITY.md`,
`docs/INTERVENTION_AND_PILOT_PROTOCOL.md`, `docs/LEARNING_LOOP.md`.

## 3. Изменённые общие файлы и потенциальные конфликты
| Файл | Изменение | Риск конфликта |
|---|---|---|
| `apps/api/oqumap/models.py` | +1 импорт `measurement_models` в конце файла | низкий |
| `apps/api/oqumap/main.py` | +2 импорта и 2 `include_router` | низкий/средний (если Claude №1 добавляет роутеры) |
| `apps/api/oqumap/demo/seed.py` | вызов `seed_measurement` в конце `seed()` и в ветке «уже засеяно» | средний (если меняется `seed()`) |
| `apps/api/pyproject.toml` | per-file-ignores для `alembic/*` | низкий |
| `apps/web/src/App.tsx` | +6 импортов, +9 `<Route>` | низкий |
| `apps/web/src/features/Layout.tsx` | +1 импорт, `<MeasurementNav />` после списка шагов | низкий |
| `apps/web/src/api/schema.d.ts`, `packages/contracts/openapi.json` | перегенерированы | **высокий — не сливать вручную, перегенерировать** |
| `apps/web/tsconfig.tsbuildinfo` | артефакт сборки | перегенерировать |
| `data/demo/manifest.json` | добавлен набор `measurement_loop` | средний; перегенерируется seed |
| `docs/API.md`, `docs/METHODOLOGY.md` | только добавленные разделы (последний заголовок METHODOLOGY стал §9) | низкий |
| Alembic | новая голова `c2a7e5f1b3d9` с `down_revision = d964e255551f` | **если Claude №1 тоже добавил ревизию от `d964e255551f` — будет две головы**: переназначить `down_revision` одной из ревизий (или `alembic merge`) |
Семантика существующих scoring/comparison/planning/decisions **не менялась**; новые решения создаются как новые
версии `Decision` через существующие поля.

## 4. Результаты команд (выполнены в этой сессии, 11.11.2026; Python 3.13.18, Node 22.23.4, PostgreSQL 16.15)
| Команда | Результат |
|---|---|
| `cd apps/api && uv run ruff check .` | All checks passed (до изменения pyproject падал на сгенерированной initial-миграции) |
| `cd apps/api && uv run pytest` (SQLite) | **170 passed** (102 прежних + 68 новых; 2 мин 24 с) |
| `OQUMAP_TEST_DATABASE_URL=postgresql+psycopg://…/postgres uv run pytest` (через Alembic) | **170 passed** (4 мин 25 с) |
| `uv run python ../../scripts/export_openapi.py --check` | up to date (+ тест `test_contract.py`) |
| Миграции: `alembic upgrade head` на чистой БД, `upgrade d964e255551f → head` на БД с данными, `downgrade`, `alembic check` (PostgreSQL) | OK, «No new upgrade operations detected»; то же в `tests/test_migrations.py` для SQLite и PG |
| `cd apps/web && npm ci` | OK |
| `npm test` | **14 passed** (7 прежних + 7 новых `src/test/measurement.test.tsx`) |
| `npm run typecheck` | без ошибок |
| `npm run build` | собрано (предупреждение Vite о чанке > 500 kB) |
| Playwright `measurement.spec.ts` (uvicorn + vite dev, свежий seed на SQLite) | **1 passed** |
| Playwright `scenario.spec.ts` (тот же стек) | **3 passed** — существующий сценарий не сломан |
| Ручной проход в Chromium (скриншоты всех 9 экранов, RU/KZ, роль viewer) | без ошибок консоли |
Docker Compose в этой среде не запускался.

## 5. Допущения по API
* Роли: используется существующая модель (`methodist`, `approver`, `teacher`, `viewer`, `admin`); `analyst`
  принимается как роль чтения (в демо-сиде пользователя с ней нет). Чтение всех новых данных — любой участник
  организации; данные по отдельным классам (журналы, строки результата) — `methodist/approver/teacher/admin`.
* Ответы качества кешируются как `AnalysisRun` вида `assessment_quality` (`kind` вне `Literal` схемы `AnalysisContext`,
  но через `Envelope` не отдаются — свой формат ответа с `provenance`).
* «Класс» в разрезах качества трактуется как класс обучения (grade); разрезы по классам-коллективам/учителям не
  строятся.
* Итоговое измерение пилота можно задать при создании или при повторном измерении (`follow-up` с
  `outcome_assessment_id`, фиксируется событием).
* Пилоты, созданные через UI, получают коды `PIL-NNN`; демо — `PIL-M01…M04`.
* Каталог кодов типичных ошибок берётся из `demo/content.py: MISCONCEPTIONS` (общий для организаций).

## 6. Известные ограничения
| Приоритет | Ограничение |
|---|---|
| P1 | Анализ для `interrupted_time_series` и `stepped_wedge` не реализован: протокол валидируется, результат — `needs_more_data` с причиной `analysis_not_implemented_for_design` |
| P1 | Казахские строки нового словаря — черновик разработчика, не проверены специалистом |
| P2 | Страница решения (`DecisionsPage`, общий файл) не показывает блок `snapshot.learning_loop`; у решений, созданных из пилота без связанного решения, в списке тема отображается «—» (в снимке нет `topic`) — стоит добавить при доводке UI |
| P2 | Кластерно-устойчивая SE по классам; при школьных эффектах может занижать неопределённость (как и в существующем методе) |
| P2 | Классическая теория тестов (без IRT/DIF); пороги сигналов — условные |
| P2 | Ожидаемые занятия считаются равномерно по периоду (каникулы не учитываются) |
| P3 | Для активного пилота агрегаты реализации зависят от текущей даты (`as_of` по умолчанию — сегодня) |
| P3 | Нет пагинации списков интервенций/пилотов (объёмы демо малы) |
| P3 | Сплит бандла не делался (предупреждение Vite) |

## 7. Порядок интеграции
1. Влить ветку первого Claude в целевую ветку как основу (платформенные изменения).
2. Влить `claude/measurement-learning-loop`; конфликты разрешать так:
   * `models.py`, `main.py`, `App.tsx`, `Layout.tsx`, `seed.py`, `pyproject.toml`, `docs/*` — оставить обе стороны;
   * `openapi.json`, `schema.d.ts`, `tsconfig.tsbuildinfo` — взять любую сторону и **перегенерировать**:
     `cd apps/api && uv run python ../../scripts/export_openapi.py && cd ../web && npm run gen:types`;
   * Alembic: `uv run alembic heads`; при двух головах — выставить `down_revision` более поздней ревизии на другую
     голову (или `uv run alembic merge -m merge heads`), затем `alembic upgrade head` на чистой БД и `alembic check`;
     обновить константы в `tests/test_migrations.py` (`MEASUREMENT`, `test_head_is_the_measurement_revision`);
   * `data/demo/manifest.json` — перегенерировать seed’ом.
3. Если Claude №1 менял провайдер ИИ/импорт/безопасность — новые сервисы их не используют (кроме обычного конвейера
   импорта в демо-сиде и `services/auth.Principal`).
4. Прогнать: `scripts/check.sh`, pytest на PostgreSQL, Playwright (`scenario.spec.ts`, `measurement.spec.ts`) на
   свежем seed.

## 8. Что проверить вручную после merge
* `docker compose down -v && docker compose up --build`: миграции до головы, seed создаёт `measurement_loop`;
  на существующем томе без пересоздания seed добавляет набор (ветка «уже засеяно»).
* Набор «Контур измерения и обучения…»: `/quality` → DIAG-BASE → Q05 с `negative_discrimination`; Q03/Q07/Q09/Q11/Q12
  с ожидаемыми сигналами; хорошие задания без сигналов.
* `/portfolio/interventions`: PIL-M01 `positive_signal`, PIL-M02 `invalid_due_to_fidelity`, PIL-M03 активен, PIL-M04
  черновик; «лучшая интервенция» не показывается.
* PIL-M02 → «Повторное измерение»: текст «ни её эффективности, ни неэффективности»; решение «остановить» без упоминания
  реализации отклоняется.
* Вход `viewer`: нет кнопок изменения, журналы и строки по классам скрыты; `other_org` не видит ничего (404).
* Переключение RU/KZ на всех девяти экранах; клавиатурная навигация по таблицам/формам.
* Создание интервенции → рецензия → пилот → журнал → повторное измерение → вывод → новая версия решения открывается
  на странице решений и утверждается существующим процессом.


---

# Round 2 audit fixes (точка входа раунда: `07a35346c9e9418c7c7821e432d2baf6ec69d42c`)

Ветка та же: `claude/measurement-learning-loop`; merge/rebase с веткой первого Claude и `main` не выполнялись, PR не
создавался. Финальный дизайн и presentation mode не менялись (использованы существующие компоненты/токены).

## R2.1 Коммиты раунда
| Коммит | Содержание |
|---|---|
| `221903c` | Fix as-of consistency and outcome fingerprints |
| `d236213` | Add explicit assessment assignments (Alembic `e1a4b7c9d2f0`) |
| `b4735f5` | Harden snapshot integrity tenant scope and synthetic evidence |
| `f29f211` | Strengthen protocol invariants and structured conclusions (Alembic `f3c5d8e2a7b1`) |
| `69d9c7e` | Add privacy suppression concurrency constraints and pagination (Alembic `a4d6e9f1c3b5`) |
| `86dea03` | Fix measurement accessibility localization and decision integration |
| `64d1d85` | Add Experiment Design Studio |
| `5ee300c` | Add planned pilot session calendar (Alembic `b5e7f0a2d4c6`) |
| `caeabf3` | Add language DIF screening |
| `282942e` | Update contracts tests documentation and handoff |
| `35ae74a` | Deterministic composite-FK test on PostgreSQL |
| (этот) | Final check results in the handoff |

Цепочка миграций: `d964e255551f → c2a7e5f1b3d9 → e1a4b7c9d2f0 → f3c5d8e2a7b1 → a4d6e9f1c3b5 → b5e7f0a2d4c6` (голова).
Проверено: чистая БД; БД на `d964e255551f` с данными; БД на голове раунда 1 `c2a7e5f1b3d9` с данными измерения;
`downgrade`/`upgrade` каждой ревизии; `alembic check` без расхождений (PostgreSQL 16 и SQLite — `tests/test_migrations.py`).

## R2.2 Пункты аудита → реализация → тест → коммит
| # | Пункт | Что сделано | Тесты | Коммит |
|---|---|---|---|---|
| P1-1 | `effective_as_of` и отпечаток | `services/clock.py`; дата по умолчанию (окончание → дата итогового измерения; иначе сегодня) входит в отпечаток, расчёт и результат; будущая дата → 422; измерение после `as_of` → 422 | `test_asof.py::test_default_as_of_is_part_of_the_fingerprint`, `::test_explicit_as_of_reuses_and_future_as_of_is_rejected` | `221903c` |
| P1-2 | Единый `as_of` портфеля | `as_of` передаётся в каждый расчёт реализации и в список пилотов | `test_asof.py::test_portfolio_uses_one_date_everywhere` | `221903c` |
| P1-3 | Явное назначение проверок | `assessment_cohorts`, API GET/PUT, сид, `assignment_scope`/`assigned_is_exact`, класс без записей → `no_sitting_record`; UI бейдж и редактор | `test_assignments.py` (оба теста), `test_migrations.py::test_upgrade_from_round1_head_keeps_measurement_rows` | `d236213`, `86dea03` |
| P1-4 | Полная проверка снимка | `snapshot_integrity()` (5 проверок), 409 + безопасный аудит | `test_integrity.py::test_tampered_snapshot_blocks_activation` (4 варианта подмены) | `b4735f5` |
| P1-5 | Синтетические доказательства | разделение real/synthetic; баллы и повторные сигналы — только принятые реальные | `test_integrity.py::test_synthetic_evidence_never_boosts_but_real_evidence_does`, обновлённые `test_interventions`/`test_learning_loop` | `b4735f5` |
| P1-6 | Tenant scope задания | задание видно только через проверку организации; строгий `dataset_id` | `test_integrity.py::test_item_from_shared_programme_is_visible_only_through_own_assessments` | `b4735f5` |
| P1-7 | Хронология и инварианты | `follow_up_before_end`, `outcome_before_start`, предупреждение о длительности, согласование оценки и дизайна, override раннего завершения, ITS/SW как `protocol_only_external_analysis` с подтверждением и 409 на расчёт | `test_protocol.py` (3 теста + 2 параметра) | `f29f211`, UI `86dea03` |
| P1-8 | Структурированный вывод | `decision_basis`, `stop_reason_code`, `acknowledged_limitation_codes`; текст не проверяется | `test_learning_loop.py::test_stop_after_low_fidelity_requires_structured_operational_basis` | `f29f211`, UI `86dea03` |
| P2-9 | Ограничения и гонки | CHECK/UNIQUE/составные FK; гонки → 409; общий обработчик `IntegrityError` | `test_robustness.py::test_database_constraints`, `::test_races_become_conflicts_not_500` | `69d9c7e` |
| P2-10 | Подавление малых групп | `privacy.py` (первичное + дополнительное), результаты и портфель для viewer/analyst | `test_robustness.py::test_primary_and_complementary_suppression`, `::test_outcome_filter_hides_small_arm_and_derived_estimate`, `::test_viewer_sees_suppressed_outcome_methodist_sees_values`, `::test_portfolio_learner_cells_are_suppressed_for_viewers` | `69d9c7e` |
| P2-11 | Доступность и локализация | ссылки вместо `<tr onClick>`, row headers, видимый фокус, все новые строки в RU/KZ, коды в подсказках | vitest `list rows are real links…`, `pager moves…`; Playwright `keyboard: list links…` | `86dea03` |
| P2-12 | Страница решения | `LearningLoopCard` (пилот, версия, результат, реализация, уровень вывода, вывод, основания, ограничения, ссылка назад); процесс утверждения не тронут | Playwright `keyboard…` (блок learning loop), `test_learning_loop` (снимок) | `69d9c7e`, `86dea03` |
| P2-13 | Производительность | пагинация трёх списков, стабильный порядок, фильтры в URL, lazy routes (initial JS 481 kB вместо > 500 kB) | `test_robustness.py::test_pagination_is_stable_and_complete` (3 эндпоинта), vitest pager | `69d9c7e`, `86dea03` |
| 14 | Experiment Design Studio | `analytics/design_studio.py`, API, карточка в конструкторе | `test_design_studio.py` (24 теста, монотонность), vitest DesignStudio | `64d1d85` |
| 15 | Календарь занятий | `pilot_sessions`/`pilot_session_events`, API, UI, интеграция в реализацию | `test_calendar.py`, vitest calendar | `5ee300c` |
| 16 | DIF screening | `analytics/dif.py`, API, UI, демо Q10/Q08 | `test_dif.py`, vitest DIF | `caeabf3` |

## R2.3 Изменённые общие файлы (раунд 2)
| Файл | Изменение |
|---|---|
| `apps/api/oqumap/main.py` | +обработчик `IntegrityError` → 409 (`integrity_conflict`) |
| `apps/api/oqumap/measurement_models.py` | уникальный индекс `uq_decisions_group_version` на **общей** таблице `decisions` (объявлен здесь, миграция `a4d6e9f1c3b5`) — проверить, не добавил ли Claude №1 аналогичный |
| `apps/web/src/App.tsx` | маршруты измерения переведены на `lazy()` + `Suspense` |
| `apps/web/src/features/DecisionsPage.tsx` | +2 строки: импорт и `<LearningLoopCard …/>` после снимка |
| `apps/api/oqumap/demo/measurement_seed.py` | класс M06-6Д, назначения, календари, казахские классы M05/M06, DIF Q10 (поток случайных чисел остальных данных не менялся) |
| Контракты | `openapi.json` и `schema.d.ts` перегенерированы; **списки `/interventions` и `/pilots` стали страницами** `{items,total,limit,offset}` |
`imports.py` не менялся: явные назначения задаются API/сидом (импорт активно меняется в ветке Claude №1). React Router
и lock-файлы не обновлялись.

## R2.4 Результаты проверок (этой сессии)
| Проверка | Результат |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run pytest` (SQLite) | **228 passed** (≈4 мин 20 с) |
| pytest на PostgreSQL 16 через Alembic | **228 passed** (≈7 мин); первый прогон выявил недетерминированный выбор в `test_database_constraints` — исправлено в `35ae74a`, повторный прогон зелёный |
| Миграции от `c2a7e5f1b3d9` (с данными), чистая БД, downgrade/upgrade, `alembic check` | OK |
| OpenAPI drift (`test_contract.py`, `export_openapi.py --check`) | актуален |
| `npm test` | **19 passed** (3 файла) |
| `npm run typecheck`, `npm run build` | без ошибок; initial chunk 490,7 kB, предупреждения Vite нет |
| Playwright: `measurement.spec.ts` (сквозной + клавиатура/фокус) и `scenario.spec.ts` | **5 passed** (uvicorn + vite dev, свежий сид, SQLite) |
| `git status` | чисто после финального коммита |
Docker Compose не запускался (оставлено интегратору).

## R2.5 Известные ограничения раунда 2
* ITS и stepped wedge — только протокол: оценки эффекта в OquMap нет (честно помечено в API и UI).
* Design Studio — аналитическое приближение (одинаковый R² на двух уровнях, сдвинутое центральное t, равное деление
  кластеров); не заменяет симуляцию/консультацию статистика.
* DIF: только дихотомические задания одной формы, Mantel–Haenszel без очистки matching-переменной (purification) и без
  поправки на множественные сравнения; категории — screening.
* Историческая дата портфеля влияет на сроки и реализацию; статусы и результаты — текущие записи.
* Казахские строки нового словаря — черновик разработчика, носителем/специалистом **не проверены**.
* Подавление малых групп применяется к ролям viewer/analyst; методист/утверждающий/учитель видят значения.
* Импорт не создаёт явных назначений проверок (нужно решение интегратора после слияния с новым импортом).

## R2.6 Что проверить после merge
* `alembic heads` — одна голова; если у Claude №1 есть ревизии от `c2a7e5f1b3d9`/`d964e255551f`, переназначить
  `down_revision`; повторить `upgrade head` + `alembic check`; обновить `HEAD` в `tests/test_migrations.py`.
* Перегенерировать `openapi.json` и `schema.d.ts`; убедиться, что фронтенд Claude №1 не использует `/interventions`
  и `/pilots` как массивы.
* Если Claude №1 добавил свой обработчик `IntegrityError` или индекс на `decisions` — оставить один.
* Пройти `/quality` → DIAG-END (назначение, класс 6Д), DIF на DIAG-BASE (Q10 — сигнал, Q08 — нет), конструктор пилота
  с Design Studio, календарь PIL-M03 (перенос), решение из вывода PIL-M01 (блок learning loop), роль viewer (скрытые
  малые группы, нет календаря), переключение RU/KZ.
