# Интеграция OquMap: состояние и как продолжать (Claude №1 → следующий агент)

**Статус: ИНТЕГРАЦИЯ НЕ ЗАВЕРШЕНА — targeted-проверки зелёные, полный PostgreSQL-прогон, общий Playwright и
Docker cold start ещё не зафиксированы ниже как завершённые.** Удалённая ветка содержит более раннее WIP-состояние;
коммиты readiness ниже пока только локальные и не отправлены. `main` в репозитории отсутствует и не создавался;
PR не создавался; force-push не было; исходные ветки не менялись.

## Ветки
| Ветка | Вершина |
|---|---|
| `origin/claude/serene-carson-m1pbvz` (Claude №1, основа) | `2633882` (совпала с ожидаемой) |
| `origin/claude/measurement-learning-loop` (Claude №2) | `d5b5665` (совпала с ожидаемой) |
| `claude/integrated-oqumap-final` (интеграция) | см. `git log`, коммиты ниже |

## Что сделано (коммиты интеграции, по порядку)
1. `7803c35` — merge `d5b5665` → `2633882` с семантическим разрешением конфликтов:
   * `App.tsx`: оставлены маршруты обеих веток; **коллизия `/quality`**: качество проверок (Claude №2) осталось на
     `/quality` и `/quality/:id`, страница качества данных набора (Claude №1) переехала на **`/data-quality`**
     (ссылка в `Layout.tsx` обновлена; подписи: «Качество данных» и «Качество проверок»).
   * `Layout.tsx`: оставлены и демо-гид, и группа навигации «Измерение и обучение».
   * `tests/test_calendar.py` был в обеих ветках для разных функций: недельный календарь — `test_calendar.py`,
     календарь пилотных занятий — **`test_session_calendar.py`**.
   * `docs/API.md` — обе секции; `docs/METHODOLOGY.md` — §6а–7г (Claude №1), §8 — измерение (Claude №2),
     §9 — «Чего система не утверждает».
   * `openapi.json`, `schema.d.ts` — **перегенерированы** из объединённого кода; `tsconfig.tsbuildinfo` не отслеживается.
2. `ecfcad3` — миграции: merge-ревизия **`6e837767b573`** (`down_revision = (d5085df1f375, b5e7f0a2d4c6)`), одна голова.
   Исправлен баг в `15d3c925b7da` (на SQLite падало удаление безымянного `UNIQUE(code)` у `scales`; путь PostgreSQL
   не изменён). `tests/test_migrations.py`: чистая БД без дрейфа моделей, апгрейд БД на голове Claude №1 (с данными)
   и на голове Claude №2 (с данными), откат/повтор merge-ревизии — **6 passed на SQLite и PostgreSQL**.
3. `8de4afa` — тесты после интеграции: DIF на базовом наборе теперь `insufficient_sample` (в базе 3 казахскоязычных
   класса < 100 учеников); vitest-пользователь с `org_is_ephemeral`.
4. `4bb7a59` — **публичное демо + измерение**: каждый одноразовый арендатор получает демо контура измерения, построенное
   штатным сидом (`seed_measurement(session, org_id, user_id)`; ссылки на программу/темы/цели ищутся по кодам в
   организации; клонированная форма диагностики переиспользуется). Режим `OQUMAP_DEMO_TENANT_MEASUREMENT`:
   `background` (по умолчанию, задача `demo_measurement`), `sync`, `off` (по умолчанию в тестах). Очистка арендатора
   удаляет все 13 таблиц измерения. Preflight тура показывает готовность. Тесты в `test_public_demo.py`.
5. `ad1d810` — **импорт явных назначений**: необязательный строгий этап `assignments` (`assessment_code, class_code,
   note`) → `AssessmentCohort(source="import")`; неизвестные проверки/классы, дубликаты и уже существующие пары
   отклоняются; без этапа охват остаётся `inferred_from_sittings`, `assigned_is_exact=false`. Пример
   `data/templates/example_project/6_assignments.csv`, пункт мастера импорта, этап помечен `optional`.
6. `929b556` — **наблюдаемая готовность measurement demo**: API состояния `preparing | ready | failed | unavailable`,
   ограниченный polling с backoff, скрытие measurement-навигации до готовности, явная ошибка и повтор задачи без
   раскрытия секретов или фиксированных задержек.
7. `d5b7a38` — readiness теперь считает набор готовым только после `demo_measurement.status=succeeded`, а не после
   раннего commit строки `measurement_loop`. Это устраняет окно, когда UI видел dataset без assessments/pilots.
   Выбор этого набора ведёт прямо в `/quality`; browser-тест ждёт observable state и не использует fixed sleep.

Проверено вручную: модули Claude №2 не вызывают LLM напрямую (нет обхода шлюза ИИ); дублей маршрутов/operationId
нет (110 операций); один обработчик `IntegrityError`; один индекс `uq_decisions_group_version`; 53 таблицы.
Последний зафиксированный здесь полный прогон pytest на SQLite (до поздних интеграционных коммитов): **300 passed**.
После readiness-фикса: `test_demo_measurement_runs_as_a_background_job` и retry regression — **2 passed**;
`measurement.spec.ts` — **2 passed** (полный measurement flow и keyboard); frontend — **20 passed**, typecheck и
build зелёные, initial chunk **467.28 kB**. Ruff изменённых backend-файлов и `git diff --check` — чисто.

## Что осталось сделать (по порядку)
```bash
git fetch origin && git checkout claude/integrated-oqumap-final
cd apps/api && uv sync --frozen
uv run ruff check . && uv run pytest -q                                  # ожидается ~305 passed
OQUMAP_TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/postgres uv run pytest -q
uv run alembic heads                                                      # одна: 6e837767b573
uv run python ../../scripts/export_openapi.py --check
cd ../web && npm ci && npm test && npm run typecheck && npm run build   # проверить, нет ли предупреждения о чанке > 500 kB
npm run gen:types && git diff --exit-code src/api/schema.d.ts
cd ../.. && scripts/docker_cold_start.sh 2 --e2e                          # 2 холодных старта + все Playwright
```
1. Полный pytest SQLite + PostgreSQL после последних интеграционных коммитов; повторный seed на заполненной БД (идемпотентность,
   ветка «уже засеяно» досеивает `measurement_loop`); перегенерировать `data/demo/manifest.json` штатным seed.
2. E2E: `measurement.spec.ts` уже прошёл на свежем локальном `public_demo` (**2 passed, 2.2 min**) и ждёт завершения
   job через API readiness. Ещё требуется общий прогон `scenario.spec.ts`, `wow.spec.ts`, `a11y.spec.ts`,
   `calendar.spec.ts` и остальных тестов на итоговом состоянии.
3. Docker: 2 холодных старта, healthcheck, 0 рестартов worker, 0 traceback, Playwright поверх Docker.
4. Ручной проход экранов жюри (список в задании интегратора), RU/KZ, viewer/methodist, без ключа API.
5. После полного прогона синхронизировать итог в `docs/CLAUDE_HANDOFF.md`, затем push и CI; PR — по желанию,
   без merge. README уже описывает фоновую готовность measurement demo.

## Что не проверено вообще
Живая модель ИИ ни на одном провайдере (ключей не было) — только контрактные тесты/mock; полный Windows-прогон;
OCR; казахские тексты носителем; нагрузка. Targeted readiness API и measurement Playwright проверены на Windows.
