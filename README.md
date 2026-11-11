# OquMap

Система поддержки решений методиста: связывает результаты школьных проверок с целями программы, учебными
материалами и распределением часов. Методист видит трудные темы и ошибки, сравнивает издания на сопоставимых группах,
получает допустимый план часов в пределах бюджета, сохраняет проверяемое решение, экспортирует отчёт и проверяет
динамику после повторного измерения.

> Демонстрация работает **только на синтетических данных** (ученики, школы и пособия вымышлены). Коды целей
> `DEMO-M6-*` — демонстрационные, не официальная программа. Результаты не являются результатами пилота.

**Для жюри:** «Открыть демо» → пункт меню **«Демо за 3 минуты»** (7 экранов только для просмотра: где проблема →
цепочка доказательств → честное сравнение пособий → консилиум с критиком → сценарии часов → диагностика → решение).
Также: **«Граф доказательств»** (каждый узел открывает расчёт, строки ответов или страницу пособия; пробелы показаны),
**«Песочница решений»** (сценарии часов словами → типизированные ограничения → сравнение с текущим планом),
**«Диагностические задания»** (3–7 заданий на найденные гипотезы ошибок, проверка и утверждение учителем, PDF/CSV/XLSX,
загрузка ответов). Свои данные — «Загрузить свои данные» (шаблоны, проверка, отчёт, загрузка по этапам).

## Быстрый старт (Docker Compose)
```bash
docker compose up --build
```
Откройте http://localhost:8080 → «Открыть демо». API доступен только через веб-сервер: http://localhost:8080/api/v1/…
(порт API наружу не публикуется; схема — `packages/contracts/openapi.json`).
При первом старте применяются миграции и загружается синтетический демо-корпус (≈30–50 с); сервисы стартуют по
готовности (`/health/ready`: БД, миграции, демо-шаблон). По умолчанию режим `OQUMAP_DEPLOYMENT_MODE=public_demo`:
каждый посетитель получает свою одноразовую копию демо-организации (TTL 6 ч, очистка воркером), лимиты частоты в БД.
Режимы: `dev` (QA-персоны, локальная разработка), `public_demo`, `production` (только вход по паролю; организация и
администратор — `OQUMAP_ADMIN_PASSWORD=… docker compose exec -e OQUMAP_ADMIN_PASSWORD api python -m oqumap.admin
create-org --name "…" --admin <логин>`).

Сброс демо до исходного состояния (например, после загрузки повторной проверки):
```bash
docker compose down -v
```
```bash
docker compose up --build
```
Сеть с TLS-прокси (корпоративный прокси подменяет сертификаты) — передайте CA-бандл только на время сборки:
```bash
EXTRA_CA_FILE=./my-ca.pem docker compose -f docker-compose.yml -f docker-compose.ca.yml up --build
```
PowerShell: `$env:EXTRA_CA_FILE="C:\path\ca.pem"; docker compose -f docker-compose.yml -f docker-compose.ca.yml up --build`.

## Разработка без Docker
Требуется PostgreSQL 16, Python 3.11–3.13 с [uv](https://docs.astral.sh/uv/), Node.js 20+ (проверено на 22).

```bash
cp .env.example .env          # укажите OQUMAP_DATABASE_URL на пустую базу
cd apps/api
uv sync
uv run alembic upgrade head
uv run python -m oqumap.demo.seed
uv run uvicorn oqumap.main:app --reload --port 8000
```
Во втором терминале:
```bash
cd apps/web
npm ci
npm run dev                   # http://localhost:5173, /api проксируется на :8000
```
Windows PowerShell: `powershell -ExecutionPolicy Bypass -File scripts\dev.ps1` (выполняет те же шаги).
Linux/macOS: `scripts/dev.sh`.

Фоновые задачи: по умолчанию `OQUMAP_JOB_MODE=inline` (поток в процессе API). Для отдельного процесса задайте
`OQUMAP_JOB_MODE=worker` и запустите `uv run python -m oqumap.worker`.

Сброс локальной базы и повторный seed (кроссплатформенно):
```bash
cd apps/api && uv run python ../../scripts/reset_demo.py
```

## Проверки
```bash
scripts/check.sh              # ruff, pytest, актуальность OpenAPI, tsc, vitest, сборка
```
По отдельности:
```bash
cd apps/api && uv run pytest                                   # SQLite во временном каталоге
cd apps/api && OQUMAP_TEST_DATABASE_URL=postgresql+psycopg://postgres@localhost:5432/postgres uv run pytest   # тот же набор на PostgreSQL (создаёт/удаляет базы oqu_*)
cd apps/web && npm test && npm run typecheck && npm run build
```
Сквозные тесты браузером (`scenario.spec.ts`, `wow.spec.ts`, `a11y.spec.ts` — axe, WCAG 2.1 A/AA). В режиме
`public_demo` каждый тест получает свою одноразовую копию, поэтому повторный запуск не требует сброса:
```bash
cd tests/e2e && npm ci && OQUMAP_WEB_URL=http://localhost:8080 npx playwright test --trace off
```
Холодный старт с пустыми томами (N повторов, здоровье сервисов, рестарты воркера, поиск трейсбеков, selfcheck
образа, затем Playwright):
```bash
scripts/docker_cold_start.sh 2 --e2e
```
CI: `.github/workflows/ci.yml` (ruff, pytest на SQLite и PostgreSQL, дрейф OpenAPI, типы фронтенда, vitest, сборка,
npm audit, pip-audit, LF/shebang скриптов, сборка образа + selfcheck, холодный старт + Playwright; actions закреплены
по SHA).
Типы фронтенда из схемы сервера:
```bash
cd apps/api && uv run python ../../scripts/export_openapi.py && cd ../web && npm run gen:types
```

## Модель и OCR
Без ключа приложение полностью работает: объяснения строятся по шаблону (`template`) или берутся из явно
помеченных записанных примеров (`recorded_demo`). Аналитика (оценки, сравнение, план) от модели не зависит.

Слой модели провайдер-независимый: `none | recorded | gemini | openrouter | openai | anthropic`
(адаптеры поверх HTTP API, структурированный вывод всегда проверяется сервером по JSON Schema, инструменты
типизированы и исполняются сервером). Пример для бесплатного Gemini и **только синтетических** данных:
```
OQUMAP_LLM_PROVIDER=gemini
OQUMAP_LLM_MODEL=gemini-2.5-flash
OQUMAP_GEMINI_API_KEY=<ключ>      # только на сервере; не попадает во frontend, ответы API, логи, экспорт
```
Бесплатный тариф Gemini может использовать запросы для улучшения продуктов Google, поэтому UI показывает
предупреждение, а реальные данные учеников туда не отправляются (`OQUMAP_LLM_REAL_DATA_ALLOWED=false`;
даже при `true` политика `may_train` блокирует отправку). Для реальных данных нужен платный/договорный профиль
или режим шаблонов. Все переменные — в `.env.example`. Проверка конфигурации и возможностей модели:
```bash
cd apps/api && uv run python -m oqumap.maintenance check-config && uv run python -m oqumap.maintenance probe-llm
```
Сравнение моделей на одинаковом синтетическом наборе задач: `uv run python ../../scripts/eval_llm_provider.py`.
Живая модель отключена для анонимного публичного демо; квоты на роль/организацию/пользователя, потолок токенов,
circuit breaker и резервный провайдер только по явной настройке с audit-событием.
OCR: `OQUMAP_OCR_ENGINE=tesseract` и бинарник `tesseract` с языками rus+kaz+eng; без него страницы без
текстового слоя помечаются, текст не выдумывается.

## Структура
```
apps/api/        FastAPI, SQLAlchemy, Alembic, аналитика, CP-SAT, импорт, документы, ИИ, отчёты, тесты
apps/web/        React + TypeScript + Vite, токены дизайна, RU/KZ, страницы сценария
packages/contracts/openapi.json   контракт API (источник типов фронтенда)
data/demo/       фикстуры, файлы для загрузки, демо-пособия, записанные примеры, манифест
data/ai_eval/    результаты оценки связывания
docs/            METHODOLOGY, API, AI_EVAL, DEMO_SCENARIO, CLAUDE_HANDOFF, исходные задания (briefs/)
tests/e2e/       Playwright: сквозной сценарий
scripts/         dev, reset, check, export_openapi, eval_ai_mapping, eval_llm_provider, docker-entrypoint, docker_cold_start
```

Документация: [методика](docs/METHODOLOGY.md) · [API](docs/API.md) · [демо-сценарий](docs/DEMO_SCENARIO.md) ·
[оценка ИИ](docs/AI_EVAL.md) · [передача Codex](docs/CLAUDE_HANDOFF.md) · [демо-данные](data/demo/MANIFEST.md).
