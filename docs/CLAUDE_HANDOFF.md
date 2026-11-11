# Передача: состояние OquMap (Claude №1, итерация 3, 11.11.2026)

Ветка `claude/serene-carson-m1pbvz` — **отправлена в `origin`** (push выполнен по явной просьбе пользователя; merge
в `main`, rebase и force-push не выполнялись). Состояние remote и CI — в §0. Пользовательские файлы
`CLAUDE_IMPLEMENTATION_BRIEF.md`, `CODEX_REVIEW_AND_DESIGN_BRIEF.md`, `PROJECT_STRATEGY_RU.md` и файл промпта в этом
checkout отсутствуют — не создавались, не удалялись и не коммитились. Копии исходных заданий первой итерации —
`docs/briefs/` (не менялись). Модули Claude №2 (Assessment Quality Lab, Intervention Library, Pilot Protocol,
Fidelity Tracker, Learning Loop, Portfolio Effectiveness) в этой ветке не затрагивались; финальный редизайн и
presentation mode — зона Codex, здесь не делались.

## 0. Remote и CI (итерация 3)
| Коммит | Что | GitHub Actions |
|---|---|---|
| `9cac9a2` | конец итерации 2 | run #1 — **failure**: шаг «OpenAPI contract has no drift». Причина: FastAPI копирует фразу статуса 422 из `http.HTTPStatus`; в Python 3.12 (CI, Docker) это «Unprocessable Entity», в 3.13 (локально) — «Unprocessable Content». Шаги docker/pip-audit/«чистое дерево» были пропущены |
| `bc360c7` | `scripts/export_openapi.py` нормализует фразу к RFC 9110; проверено `--check` на 3.12 и 3.13 | run #2 — **success** (hygiene, backend на SQLite+PostgreSQL, контракт, pip-audit, frontend, docker: сборка образа, selfcheck, 2 холодных старта, Playwright) |
| `9399eaa` … `9da49b3` | итерация 3 (календарь, семейства заданий, казахскоязычные классы, запись live-прогона, документация) | см. строку ниже |
| `9da49b3` | последний коммит с кодом | run #3 ([43030543683](https://github.com/Mustiks07/OquMap/actions/runs/43030543683)) — **success**: hygiene, backend (SQLite + PostgreSQL, контракт, check-config, pip-audit, чистое дерево), frontend, docker (образ, selfcheck, 2 холодных старта, Playwright) |
| следующий коммит | только этот handoff (документация) | проверяется тем же workflow после push |

**Статус готовности.** Меры безопасности публичного демо (одноразовые арендаторы, лимиты в БД, очистка, режимы
развёртывания, заголовки безопасности, проверка Host/загрузок) реализованы и покрыты тестами. Система **не
объявляется production-ready**: не было внешнего аудита безопасности, нагрузочного теста, настройки TLS/бэкапов и
проверки живой модели на реальном API.

## 1. Пункт → изменённые файлы → тест/команда → фактический результат

### Итерация 2

| Пункт | Основные файлы | Тест / команда | Результат |
|---|---|---|---|
| P0-1 Провайдер-независимый ИИ | `oqumap/ai/llm/base.py` (контракт: структурированный вывод с серверной проверкой JSON Schema, типизированные инструменты, usage/latency, классифицированные ошибки, ретраи только retryable), `ai/llm/adapters.py` (Gemini, OpenRouter, OpenAI Responses, Anthropic Messages, recorded — чистый HTTP), `ai/provider.py` (диагностика конфигурации, цепочка с явным fallback, circuit breaker, probe), `ai/gate.py` (роли, квоты, потолок токенов, политика реальных данных, audit fallback), `config.py`, `api/routes.py` (`/ai/status`, `/config`), `maintenance.py` (`check-config`, `probe-llm`), `features/AiStatusCard.tsx`, `.env.example`; SDK `anthropic` удалён | `tests/test_llm_adapters.py` (17), `tests/test_llm_config.py` (7), `tests/test_provider_eval.py`, `src/test/aistatus.test.tsx` | passed; **live_model не проверен ни на одном реальном API** (ключей в среде нет; в окружении только `ANTHROPIC_BASE_URL` без ключа) |
| P0-1 Provider eval | `scripts/eval_llm_provider.py` | `test_provider_eval.py` (сценарный адаптер) | стенд работает; реальные прогоны не выполнялись |
| P0-2 Безопасность публичного демо | `services/demo_tenants.py`, `services/ratelimit.py`, `services/auth.py`, `worker.py`, `maintenance.py` | `tests/test_public_demo.py` (8) | passed; очистка удаляет все строки арендатора, включая работы/версии диагностики |
| P0-3 Импорт реальных проектов | `services/onboarding.py`, `services/imports.py`, `data/templates/example_project/*`, `features/ImportPage.tsx` | `tests/test_onboarding.py` (4), Playwright «empty organisation imports a real project» | passed |
| P0-4 Docker | `docker-compose*.yml`, `apps/api/Dockerfile`, `scripts/docker-entrypoint.sh`, `scripts/docker_cold_start.sh`, `.gitattributes`, `nginx.conf` | `scripts/docker_cold_start.sh 2 --e2e` | 2/2 холодных старта с пустыми томами: все сервисы healthy, рестартов worker 0, трейсбеков 0, selfcheck образа ok, **Playwright 7/7** |
| P0-5 Уязвимости | `pyproject.toml`/`uv.lock`/`requirements.lock.txt`, `apps/web/package*.json`, `tests/e2e/package*.json` | `pip-audit -r requirements.lock.txt --strict`; `npm audit --omit=dev`; `npm audit` (web, e2e) | 0 / 0 / 0 / 0 |
| P1-6 CI | `.github/workflows/ci.yml` (actions закреплены по SHA: checkout v7.0.1, setup-node v7.1.0, setup-uv v10.3.3, upload-artifact v7.0.2) | YAML разобран; все шаги выполнены локально эквивалентными командами | **на GitHub Actions не запускался** (push не выполнялся) |
| P1-6 Детерминизм | `demo/materials.py`, `demo/seed.py`, `services/quizzes.py` (`rl_config.invariant`) | `tests/test_determinism.py` (4), PDF диагностики дважды → байт-в-байт | passed |
| P1-7 Путь жюри | `LoginPage`, `GuidedDemo`, `DatasetsPage`, `TourPage` | Playwright `full methodist path`, `demo in 3 minutes` | passed |
| P1-8 Заголовки/загрузки | `main.py`, `nginx.conf`, `services/imports.py` (XLSX: сигнатура, `[Content_Types].xml`, макросы, path traversal, ≤ 2000 членов, ≤ 80 МБ распаковки, коэффициент сжатия, потоковый лимит строк, лимит колонок; CSV: отказ бинарного содержимого; имя хранимого файла — sha256 + белый список расширений) | `tests/test_imports.py` (новые 2), `curl -I` | passed; CSP/`frame-ancestors 'none'`/Permissions-Policy присутствуют, HSTS только при `X-Forwarded-Proto: https`, чужой Host → 400 |
| WOW-9 Граф доказательств | `services/graph.py`, `features/EvidenceGraph.tsx`, `features/GraphPage.tsx` | `tests/test_wow.py` (граф, пробелы, валидация ID, изоляция), Playwright | passed |
| WOW-10 Консилиум | `ai/council.py`, `features/Council.tsx` | `test_council_trail_critic_and_verified_card`, `test_council_rejects_invented_ids_and_numbers_from_a_model`, Playwright | passed; в демо критик блокирует сырую разницу (парадокс Симпсона) |
| WOW-11 Песочница | `services/sandbox.py`, `features/SandboxPage.tsx` | `test_sandbox_*` (2), Playwright | passed |
| WOW-12 Диагностика | `services/quizzes.py`, модели `Quiz/QuizVersion/QuizResponseSet`, миграция `20261111_d5085df1f375_diagnostic_quizzes.py`, `features/QuizPage.tsx` | `test_quiz_*` (4), Playwright (правка → блокировка → подтверждение ключа → утверждение) | passed; экспорт CSV/XLSX сверен с версией работы (20/20 строк) |
| WOW-13 Демо за 3 минуты | `services/tour.py`, `features/TourPage.tsx`, `tests/e2e/wow.spec.ts` | Playwright локально и в Docker | passed |
| P2 Парный follow-up | `analytics/paired.py`, `services/decisions.py`, `DecisionsPage.tsx` | `test_paired_change_*`, `test_api_flow` (`design=cohort`, `no_shared_learner_ids`) | passed |
| P2 Фильтры класса и языка | `features/Filters.tsx` | tsc, Playwright | passed (в демо все классы русскоязычные — фильтр показывает одно значение) |
| P2 Доступность | `tests/e2e/a11y.spec.ts` (`@axe-core/playwright` 4.14.0); исправлены имя progressbar, фокусируемые прокручиваемые таблицы, имена узлов графа | Playwright a11y | 0 нарушений уровня serious/critical на вход/обзор/граф/песочница/задания/тур/решения, RU и KZ |
| Шапка | `Layout.tsx`, `styles/base.css` | замер `scrollWidth` | было 1569 px при окне 1440/1280 (регрессия прошлой итерации), стало = ширине окна |

### Итерация 3
| Пункт | Основные файлы | Тест / команда | Результат |
|---|---|---|---|
| CI | `scripts/export_openapi.py` | `export_openapi.py --check` на Python 3.12 и 3.13; GitHub Actions run #2 | passed |
| Недельный календарь | `analytics/calendar.py` (CP-SAT: тема × неделя, нагрузка, каникулы, непрерывность, пререквизиты, порядок, закреплённые окна; валидатор; минимальный конфликт с арифметикой), `services/calendar.py` (действующий vs предлагаемый, причины переносов, часы из сценария планировщика/песочницы), `GET /calendar/context`, `POST /calendar/solve`, `features/CalendarPage.tsx` | `tests/test_calendar.py` (7), `tests/e2e/calendar.spec.ts` | passed |
| Семейства диагностики | `services/quiz_families.py` (десятичные: сложение/сравнение/умножение; пропорция; прямая пропорциональность; отрицательные: сложение/сравнение; линейное уравнение; порядок действий; площадь/периметр), `services/quizzes.py` (выбор семейств учителем, `GET /quizzes/families`), `QuizPage.tsx` | `test_extra_families_*`, `test_teacher_chosen_families_*`, `test_observed_decimal_*` | passed; модель для ключей/дистракторов не используется |
| Казахскоязычные классы | `demo/generator.py` (`ClassSpec.language`; S03-6Г, S07-6А, S07-6Б), `data/demo/MANIFEST.md`, `data/demo/imports/followup_2026_2027.csv` | `test_kazakh_medium_classes_*`, Playwright «language filter» | passed; остальные числа демо не изменились (язык не участвует в генерации); сравнение изданий по-прежнему «сопоставимо» |
| Запись live-прогона | `ai/llm/recording.py`, `ai/record_live.py`, `ai/llm/adapters.py` (`RecordedProvider` с нормализацией ID), `maintenance.py record-live`, `docs/LIVE_RECORDING.md` | `tests/test_recording.py` (4) | passed со сценарным тестовым адаптером во временный каталог; **реальная запись не создавалась** (нет ключа) |

## 2. Финальные проверки итерации 3 (после последнего изменения кода, 11.11.2026)

| Команда | Результат |
|---|---|
| `ruff check oqumap tests ../../scripts` | All checks passed |
| `pytest` (SQLite) | **172 passed** |
| `pytest` на PostgreSQL 16.15 (`OQUMAP_TEST_DATABASE_URL`) | **172 passed** |
| `export_openapi.py --check` | up to date на Python 3.13 и 3.12 |
| `npm run typecheck`, `vitest run`, `npm run build` | без ошибок, 8 passed |
| `npm audit --omit=dev` / `npm audit` (web), `npm audit` (e2e), `pip-audit --strict` | 0 / 0 / 0 / 0 |
| `scripts/docker_cold_start.sh 2 --e2e` | 2/2 healthy, worker restarts 0, Traceback 0, **Playwright 9 passed** (a11y, календарь, полный путь, конфликт планировщика, структурный импорт, пустая организация, «Демо за 3 минуты», граф/консилиум/песочница/диагностика, фильтр языка) |

Итерация 2 (для истории): 156 passed на SQLite и PostgreSQL, Playwright 7/7 в Docker, визуальная проверка PDF.

## 3. Что не проверено (честно)
* **live_model** — ни один провайдер не вызывался: ключей нет. Адаптеры проверены контрактными тестами на фикстурах,
  которые **составлены по публичной документации, а не записаны с реальных ответов**. Не проверены: принятие
  `responseJsonSchema`/`json_schema`/`output_config.format` реальными моделями, tool-loop, задержки, стоимость,
  качество RU/KZ. Записанного прогона живой модели для «Демо за 3 минуты» нет — не выдумывался.
* Идентификаторы `claude-opus-5-5` / `claude-sonnet-5-5`: по официальной таблице моделей Anthropic (проверено в
  прошлой итерации) — действующие; замечание аудита об их некорректности не подтвердилось. Модели по умолчанию
  больше нет: провайдер и model ID задаются явно.
* GitHub Actions: run #1 упал (дрейф OpenAPI из-за версии Python), исправлено; run #2 — success (см. §0).
* Запись live-прогона — механизм готов и протестирован, **настоящей записи нет** (нет ключа). Сценарий —
  `docs/LIVE_RECORDING.md`.
* Казахский язык: три синтетических класса с казахским языком обучения добавлены; тексты заданий и интерфейса на
  казахском — черновой перевод разработчика, **носителем не проверены**.
* Windows/PowerShell — не проверялись (нет среды).
* OCR (tesseract) — адаптер есть, бинарника нет; страницы без текста помечаются, текст не выдумывается.
* Excel/LibreOffice — XLSX открывался только openpyxl.
* Казахские тексты — черновой перевод разработчика (`KZ_REVIEWED=false`).
* Нагрузка, внешний pentest, TLS-терминация, резервное копирование — не делались.
* Docker Hub периодически отвечал 429 на HEAD-запросы манифестов; сборка прошла после повторной загрузки образов.

## 4. Как устроены новые части
* **ИИ.** `OQUMAP_LLM_PROVIDER=none|recorded|gemini|openrouter|openai|anthropic`, `OQUMAP_LLM_MODEL` (точный ID),
  ключ только своего провайдера (`OQUMAP_<PROVIDER>_API_KEY`), базовые URL, лимиты, `OQUMAP_LLM_FALLBACKS`
  (`provider:model`; другой провайдер — только с `OQUMAP_LLM_ALLOW_CROSS_PROVIDER_FALLBACK=true`, каждое
  использование пишется в аудит `llm.fallback_provider`). Бесплатный Gemini = политика `may_train`: только
  синтетика, предупреждение в UI; реальные данные не отправляются (ещё и `OQUMAP_LLM_REAL_DATA_ALLOWED=false` по
  умолчанию). Анонимное публичное демо live-модель не использует. Ключ не попадает в frontend, ответы API, логи,
  снимки, экспорт, трейсбеки (тест `test_llm_config.py` проверяет ответы, `/config`, `/ai/status`, логи, БД).
* **Граф** — `docs/METHODOLOGY.md §7а`; **консилиум** — §7б (критик детерминирован); **песочница** — §7в;
  **диагностика** — §7г; **парный follow-up** — §5.
* **Демо за 3 минуты** — `docs/DEMO_SCENARIO.md`.
* **Календарь по неделям** — `docs/METHODOLOGY.md §6а`, экран «Календарь по неделям» (`/calendar`); часы можно
  взять из сценария песочницы/планировщика (выбранный в решении `plan_analysis_id`).
* **Запись live-прогона** — `docs/LIVE_RECORDING.md`, `python -m oqumap.maintenance record-live`.

## 5. Команды
* Docker: `docker compose up --build` → http://localhost:8080; холодный старт: `scripts/docker_cold_start.sh 2 --e2e`.
  За TLS-прокси: `EXTRA_CA_FILE=… COMPOSE_FILES="-f docker-compose.yml -f docker-compose.ca.yml" scripts/docker_cold_start.sh`.
* Без Docker: см. README; тесты — `cd apps/api && uv run pytest`; PostgreSQL — `OQUMAP_TEST_DATABASE_URL=… uv run pytest`.
* Контракт: `uv run python ../../scripts/export_openapi.py [--check]` → `npm run gen:types`.
* ИИ: `uv run python -m oqumap.maintenance check-config | probe-llm | record-live`; сравнение моделей —
  `uv run python ../../scripts/eval_llm_provider.py`.

## 6. Версии окружения
Python 3.13.18 (локально), python:3.12-slim (Docker); uv 0.11.32; Node 22.23.4; PostgreSQL 16.15 / postgres:16-alpine;
Docker 29.9.2. Backend: FastAPI 0.162.4, pydantic 2.13.5, pydantic-settings 2.16.2, SQLAlchemy 2.0.44, Alembic 1.20.1,
psycopg 3.2.13, OR-Tools 9.15.6755, numpy 2.3.5, pandas 2.3.3, scipy 1.16.3, reportlab 4.4.5, pypdf 7.0.1,
pypdfium2 5.0.0, openpyxl 3.1.5, httpx 0.28.1, python-multipart 0.0.33. Frontend: React 19.2.3, react-router-dom 7.18.5,
TanStack Query 5.90.12, Vite 7.3.8, TypeScript 5.9.3, Vitest 4.1.12. E2E: @playwright/test 1.63.0,
@axe-core/playwright 4.14.0.

## 7. Известные ограничения
| Приоритет | Ограничение |
|---|---|
| P1 | live_model и provider eval не запускались на реальных API (§3) |
| P1 | KZ-тексты не проверены носителем; PDF-отчёты только на русском |
| P2 | Точные семейства: дроби, НОК, проценты, десятичные, пропорции, отрицательные числа, линейные уравнения, порядок действий, площадь/периметр. Для других тем генерация отказывает (`no_template_family`) или учитель выбирает семейство; генерации заданий моделью нет (сознательно — ключи только с серверной проверкой) |
| P2 | Парсер намерений песочницы — правила (RU, частично KZ); модель подключается только для нераспознанных фрагментов и при разрешённом live |
| P2 | Критик консилиума — правила; живого «критика-модели» нет (сознательно: воспроизводимость) |
| P2 | Кластеризация по классам при выраженных школьных эффектах может занижать неопределённость (документировано) |
| P3 | Календарь: «действующий календарь» выводится последовательным заполнением по умолчанию (не хранится); каникулы по умолчанию условные; уроки внутри недели не расписываются |
| P3 | Граф в режиме «весь граф» широкий (горизонтальная прокрутка); визуальный редизайн не выполнялся по заданию |

## 8. `git status --short` после финальных проверок
Пусто (проверено после последнего коммита). Временные артефакты не отслеживаются:
`.ca-tmp.pem` (CA для сборки за прокси), `tests/e2e/test-results/`, `*.tsbuildinfo`, `data/demo/generated/` —
в `.gitignore`.
