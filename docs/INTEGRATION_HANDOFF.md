# Интеграция OquMap: состояние и как продолжать (Claude №1 → следующий агент)

**Статус: ИНТЕГРАЦИЯ НЕ ЗАВЕРШЕНА — полная проверка ещё не пройдена.** Ветка отправлена в `origin` как
промежуточное состояние (WIP), чтобы работа не потерялась. `main` в репозитории отсутствует и не создавался;
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

Проверено вручную: модули Claude №2 не вызывают LLM напрямую (нет обхода шлюза ИИ); дублей маршрутов/operationId
нет (110 операций); один обработчик `IntegrityError`; один индекс `uq_decisions_group_version`; 53 таблицы.
Последний полный прогон pytest на SQLite (до коммитов 4–5): **300 passed**. После 4–5 прогонялись только затронутые
тесты (public_demo, onboarding, assignments, wow, migrations) — зелёные.

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
1. Полный pytest SQLite + PostgreSQL после коммитов 4–5; повторный seed на заполненной БД (идемпотентность,
   ветка «уже засеяно» досеивает `measurement_loop`); перегенерировать `data/demo/manifest.json` штатным seed.
2. Frontend: `npm test` (ожидалось 20), typecheck, build; размер начального чанка.
3. E2E: `scenario.spec.ts`, `measurement.spec.ts`, `wow.spec.ts`, `a11y.spec.ts`, `calendar.spec.ts` — **ещё не
   запускались на интеграционной ветке**. Возможные поломки: e2e-ссылки на `/quality` из страницы качества данных
   (теперь `/data-quality`); `measurement.spec.ts` ожидает данные `measurement_loop` — в режиме `public_demo` они
   строятся фоновой задачей через несколько секунд после входа (тесту может понадобиться ожидание или вход в режиме `dev`).
4. Docker: 2 холодных старта, healthcheck, 0 рестартов worker, 0 traceback, Playwright поверх Docker.
5. Ручной проход экранов жюри (список в задании интегратора), RU/KZ, viewer/methodist, без ключа API.
6. Обновить `docs/CLAUDE_HANDOFF.md`/README (ссылка на `/data-quality`, этап `assignments`, режим
   `OQUMAP_DEMO_TENANT_MEASUREMENT`), затем push и CI; PR — по желанию, без merge.

## Что не проверено вообще
Живая модель ИИ ни на одном провайдере (ключей не было) — только контрактные тесты/mock; Windows; OCR; казахские
тексты носителем; нагрузка.
