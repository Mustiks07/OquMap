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
