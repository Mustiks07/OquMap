# OquMap API (`/api/v1`)

Полная машинная схема — `packages/contracts/openapi.json` (генерируется `scripts/export_openapi.py`; проверка
актуальности `--check`). Фронтенд-типы генерируются из неё: `cd apps/web && npm run gen:types` →
`src/api/schema.d.ts`. Интерактивная документация при локальном запуске API без Docker: `http://localhost:8000/docs` (в Docker порт API наружу не публикуется).

## Общие соглашения
| Область | Контракт |
|---|---|
| Аутентификация | `Authorization: Bearer <token>`; токен из `POST /auth/demo-login {persona}` (`methodist`, `viewer`, `other_org`) или `POST /auth/login {username,password}`. Хранится только SHA-256 токена |
| Изоляция | Все запросы ограничены `org_id` пользователя на сервере. Чужой объект → `404 not_found` (без раскрытия существования) |
| Роли | `methodist` (импорт, анализ, решения), `approver` (утверждение), `teacher` (разметка), `viewer` (чтение) |
| Идентификаторы | Строковые UUID; демо-объекты — стабильные UUIDv5 от кодов (`oqumap.db.stable_id`) |
| Доли | 0..1; проценты только в UI; разницы — доли, в UI подписаны «п.п.» |
| Нет данных | `null` + отдельное поле `*_reason`/`status_reason`; `0` — измеренный ноль. NaN/Infinity не возвращаются |
| Ошибка | `{"error": {"code", "message", "details"}, "request_id"}`; `X-Request-ID` в заголовке |
| Время | ISO 8601 с часовым поясом (UTC) |
| Контекст анализа | `context = {analysis_id, dataset_id, dataset_version, current_dataset_version, is_stale, is_synthetic, filters, method_version, code_version, computed_at, kind}` |

### Filters (единые для обзора, темы, сравнения, плана, ассистента, решения и отчёта)
```json
{"school_ids": [], "cohort_ids": [], "edition_ids": [], "language": null, "outcome_stage": "post",
 "attempt_rule": "first|last", "omitted_policy": "as_incorrect|exclude",
 "aggregation": "learner|class", "mapping_status": "confirmed_only|include_proposed"}
```
Одинаковые (версия данных, фильтры, параметры, версия метода, состояние разметки) → тот же `analysis_id`.

## Маршруты
| Метод и путь | Назначение |
|---|---|
| `GET /health/live`, `GET /health/ready` (`/health` — алиас ready) | Живость процесса; готовность: БД, миграции = head, шаблон демо, статус LLM |
| `GET /config` | Публичная конфигурация: режим развёртывания, доступные способы входа, провайдер/модель/ошибка конфигурации LLM, политика данных (ключи никогда не возвращаются) |
| `POST /auth/demo-login {persona?}` | Публичное демо: одноразовая копия демо-организации на посетителя (TTL), сразу рекомендованный набор; QA-персоны только в `dev` |
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | Вход по паролю (лимиты частоты), выход, текущий пользователь |
| `POST /demo/scenarios/{code}` | Клонировать лабораторный сценарий в демо-копию по запросу |
| `GET /demo/tour/preflight?dataset_id=` | Проверка готовности «Демо за 3 минуты»: данные, обзор, граф, сравнение, план, режим ИИ |
| `POST /datasets` (ProjectCreate), `GET /datasets/{id}/project` | Пустой проект организации и статус его этапов импорта |
| `GET /imports/templates`, `GET /imports/templates/{kind}?format=csv|xlsx`, `GET /imports/examples/{kind}` | Шаблоны и заполненный пример для программы, изданий, банка заданий, состава, ответов |
| `GET /admin/users`, `POST /admin/users`, `POST /admin/users/{id}` (роли, активность, пароль) | Управление пользователями организации (роль admin) |
| `GET /datasets`, `GET /datasets/{id}` | Наборы организации (с `version`, `is_synthetic`, `data_level`) |
| `GET /datasets/{id}/quality` | Проверки, пропуски, отсутствия, попытки, загрузки, история версий, доступный уровень анализа |
| `POST /datasets/{id}/overview` (body: Filters) | Темы, статусы, покрытие, приоритеты, пробелы измерения, темы × классы |
| `GET /curriculum?dataset_id=` | Программа, темы, цели, связи, издания, школы, классы, проверки |
| `GET /topics/{id}/evidence?dataset_id=&filters=<json>` | Результат темы, цели, задания и дистракторы, гипотезы ошибок, предпосылки, источники, исключения |
| `POST /comparisons` | Сравнение изданий (`ComparisonRequest`: topic, editions, filters, `strata_scheme`, `weight_mode`, `include_topic_table`) |
| `GET /analyses/{id}` | Снимок анализа (с признаком устаревания) |
| `GET /topics/{id}/graph?dataset_id=&filters=` | Граф доказательств темы: узлы (тема, пререквизиты, цели, задания, гипотезы ошибок, страницы, часы, решения, повторные проверки, **пробелы**), рёбра, проверяемый путь; у каждого узла `open` → расчёт (analysis_id + путь), строки ответов, страница, план или решение |
| `POST /graph/validate {dataset_id, topic_id, node_ids}` | Проверка выбора узлов: неизвестные ID → 422 `unknown_evidence_ids`, несмежные шаги перечисляются |
| `GET /fixtures/composition` | Учебная иллюстрация 76/63 → 60/75, вычисленная из фикстуры |
| `POST /imports/validate` (multipart) | Чтение CSV/XLSX, выбор листа, сопоставление колонок, построчный отчёт, предпросмотр, проверка дубликата файла |
| `POST /imports/commit {batch_id, wait?}` | Идемпотентный commit через задачу (`idempotency_key = commit:<batch>`) |
| `GET /imports`, `GET /imports/{id}` | Загрузки и отчёты |
| `GET /jobs/{id}` | Состояние задачи `queued/running/succeeded/failed/cancelled` |
| `GET /documents`, `POST /documents` (multipart), `GET /documents/{id}`, `GET /documents/{id}/file` | Источники: хранение, извлечение (задача), фрагменты, связи |
| `POST /documents/{id}/propose-links` | ИИ/шаблон предлагает связи фрагментов с целями |
| `GET /sources/{id}` | Цитата: документ, версия, sha256, физ./печатная страница или якорь, текст, соседние фрагменты |
| `GET /sources/search?q=` | BM25-поиск по фрагментам с совпавшими терминами |
| `GET /mappings?document_id=&status=` | Связи фрагментов и заданий |
| `POST /mappings/{id}/review {decision: confirm|reject}` | Подтверждение/отклонение (связи заданий → новая версия данных) |
| `POST /items/{id}/suggest-links` | Предложение связей задания с целями |
| `GET /plans/context?dataset_id=&filters=` | Действующий план, приоритеты из анализа, учебный модуль 20 ч |
| `POST /plans/solve` | CP-SAT по сценариям, статус решателя, проверка валидатором, конфликт |
| `POST /sandbox/intent {dataset_id, text}` | Песочница: текст → типизированные операции (`add/remove/set/min/max/fix/max_change/priority/budget`) и diff ограничений; нераспознанное перечисляется; неизвестная тема → 422 |
| `POST /sandbox/run {dataset_id, scenarios[1..3]}` | Решение сценариев CP-SAT + валидатор, сравнение с «было»: часы, покрытие целей, часы на трудные темы, риски, риски пререквизитов; сохраняется как анализ `sandbox` (повтор по отпечатку); `plan_analysis_id` сценария можно передать в решение |
| `POST /decisions`, `GET /decisions`, `GET /decisions/{id}` | Карточки решений (снимок оснований) |
| `POST /decisions/{id}/approve {note}` | Утверждение → новая версия, прежняя `superseded` |
| `POST /decisions/{id}/follow-up {assessment_id?}` | Наблюдаемая динамика на общих заданиях; `design = paired` (те же ID учеников, изменение внутри ученика) или `cohort` (стандартизация по входному уровню), `paired.reason` объясняет выбор |
| `GET /decisions/{id}/report?format=pdf|csv|xlsx` | Экспорт из снимка решения |
| `GET /ai/status?probe=` | Фактический провайдер, model ID, режим `live_model/recorded_demo/template`, ошибка конфигурации, причина блокировки live, возможности (заявленные или проверенные `probe`), политика данных, цепочка резервных провайдеров, OCR |
| `POST /ai/explain-comparison`, `/ai/interpret-misconception`, `/ai/recommend` | Объяснения и рекомендации (режим виден) |
| `POST /ai/council {dataset_id, topic_id, edition_a_id?, edition_b_id?, lang}` | Консилиум: журнал (план, вызовы инструментов с analysis_id/версией данных, факты, утверждения ролей, вердикты критика), согласия/разногласия, итоговая карточка `{claim, evidence_ids, limitations, recommended_action, verification_plan}` — ID и числа проверены сервером |
| `POST /quizzes/generate {dataset_id, topic_id, n_items 3..7}` | Черновик диагностической работы по наблюдаемым гипотезам ошибок + автоматические проверки |
| `POST /quizzes/preview` | То же без сохранения (режим презентации) |
| `GET /quizzes?dataset_id=`, `GET /quizzes/{id}` | Работы, текущая версия, версии, проверки, наборы ответов |
| `PUT /quizzes/{id} {items, note}` | Правка учителя → новая версия (`edited`); проверки перезапускаются |
| `POST /quizzes/{id}/review {action: approve|reject}` | Утверждение только при пройденных обязательных проверках (иначе 422 `quiz_checks_failed`) |
| `GET /quizzes/{id}/export?format=pdf|csv|xlsx&teacher=` | Экспорт (PDF детерминирован; черновик помечен) |
| `POST /quizzes/{id}/responses` (multipart `learner_code,item_code,response`, `decision_id?`) | Ответы на утверждённую работу → сводка по заданиям и гипотезам; в оценки и итоговые проверки не попадают |
| `POST /assistant/query` | Контекстный ассистент с разрешёнными функциями чтения/расчёта |

## Лимиты и ошибки
Лимиты частоты хранятся в БД (общие для процессов API и worker): вход, демо-копии на IP, импорт, документы, ИИ,
расчёты. Превышение → 429 `rate_limited` с заголовком `Retry-After`. Live-модель: квоты на организацию/пользователя,
потолок токенов в сутки, circuit breaker; при блокировке ответ строится по шаблону, причина — в `fallback_reason`.

## Отличия от исходного списка маршрутов задания
Добавлены вспомогательные маршруты (auth, quality, overview, analyses, fixtures, documents/*, search, plans/context,
ai/*). Существующие маршруты задания реализованы без изменения путей. `GET /topics/{id}/evidence` принимает фильтры
как JSON в параметре `filters`. Изменений общих контрактов (§5 задания) нет; уточнено: `dataset_version` — целое,
растущее при каждом commit импорта и при подтверждении/отклонении связи задания с целью.
