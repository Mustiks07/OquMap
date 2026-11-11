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
| `GET /calendar/context?dataset_id=` | Календарь по неделям: параметры по умолчанию (начало, недели, часы в неделю, условные каникулы), пререквизиты тем, действующий календарь |
| `POST /calendar/solve` (`CalendarRequest`: `start_date`, `n_weeks`, `weekly_hours`, `week_hours`, `unavailable_weeks`, `topic_hours`, `plan_analysis_id`+`plan_preset`, `fixed[{topic, from_week, to_week}]`, `keep_order`) | Предлагаемый календарь vs действующий, недельная нагрузка, причины каждого переноса или проверенный минимальный конфликт с арифметикой; сохраняется как анализ `calendar` |
| `POST /decisions`, `GET /decisions`, `GET /decisions/{id}` | Карточки решений (снимок оснований) |
| `POST /decisions/{id}/approve {note}` | Утверждение → новая версия, прежняя `superseded` |
| `POST /decisions/{id}/follow-up {assessment_id?}` | Наблюдаемая динамика на общих заданиях; `design = paired` (те же ID учеников, изменение внутри ученика) или `cohort` (стандартизация по входному уровню), `paired.reason` объясняет выбор |
| `GET /decisions/{id}/report?format=pdf|csv|xlsx` | Экспорт из снимка решения |
| `GET /ai/status?probe=` | Фактический провайдер, model ID, режим `live_model/recorded_demo/template`, ошибка конфигурации, причина блокировки live, возможности (заявленные или проверенные `probe`), политика данных, цепочка резервных провайдеров, OCR |
| `POST /ai/explain-comparison`, `/ai/interpret-misconception`, `/ai/recommend` | Объяснения и рекомендации (режим виден) |
| `POST /ai/council {dataset_id, topic_id, edition_a_id?, edition_b_id?, lang}` | Консилиум: журнал (план, вызовы инструментов с analysis_id/версией данных, факты, утверждения ролей, вердикты критика), согласия/разногласия, итоговая карточка `{claim, evidence_ids, limitations, recommended_action, verification_plan}` — ID и числа проверены сервером |
| `GET /quizzes/families` | Точные семейства заданий и правила ошибок, которые применяют их дистракторы |
| `POST /quizzes/generate {dataset_id, topic_id, n_items 3..7, families?, objective_id?}` | Черновик диагностической работы: семейства по наблюдаемым гипотезам темы или выбранные учителем (например, для неизмеренной темы) + автоматические проверки |
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

## Измерение и организационное обучение (Claude №2)
Подробно: [ASSESSMENT_QUALITY.md](ASSESSMENT_QUALITY.md), [INTERVENTION_AND_PILOT_PROTOCOL.md](INTERVENTION_AND_PILOT_PROTOCOL.md),
[LEARNING_LOOP.md](LEARNING_LOOP.md). Чтение — любой участник организации; права на изменения — в протоколе (§3).

| Метод и путь | Назначение |
|---|---|
| `GET /quality/assessments?dataset_id=&attempt_rule=&omitted_policy=&limit=&offset=` | Сводка качества по проверкам (знаменатели, пропуски, α, сигналы); `total/limit/offset`, вычисляется только страница |
| `GET /quality/assessments/{id}` | Форма: знаменатели, распределение, надёжность, разрезы со скрытием, задания, исключения, ограничения, происхождение |
| `GET /quality/assessments/{id}/items?flag=` | Задания проверки (p, r, D, дистракторы, сигналы) |
| `GET /quality/items/{id}?dataset_id=` | Задание во всех проверках, без объединения |
| `GET /interventions?status=&evidence_level=&topic_id=&objective_id=&misconception=&grade=&language=&q=&limit=&offset=` | Библиотека: страница `{items,total,limit,offset}`, порядок код → id |
| `POST /interventions` | Новая интервенция (черновик v1) |
| `GET /interventions/{id}`, `PATCH /interventions/{id}` | Карточка с версиями и доказательной базой; правка черновика (`expected_version`) |
| `POST /interventions/{id}/versions` | Новая версия (если последняя рецензирована) |
| `POST /interventions/{id}/versions/{v}/review` | Рецензирование (approver) |
| `DELETE /interventions/{id}/versions/{v}` | Удаление неиспользуемого черновика |
| `POST /interventions/{id}/archive {reason}` | Архив (approver) |
| `POST /interventions/{id}/targets` | Связь черновика с темой/целью/ошибкой |
| `GET /interventions/suggest?topic_id=&objective_id=&misconception=&grade=&language=&dataset_id=` | Подбор с объяснённым баллом |
| `GET /interventions/{id}/evidence`, `POST /intervention-evidence/{entry}/review {accept, note}` | Доказательная база; принятие записи (approver) |
| `GET /pilots?dataset_id=&status=&intervention_id=&limit=&offset=`, `POST /pilots` | Пилоты (страница `{items,total,limit,offset}`), создание черновика протокола |
| `GET /pilots/{id}`, `PATCH /pilots/{id}` | Протокол с проверкой и допустимыми переходами; правка только в `draft` |
| `POST /pilots/{id}/randomize {seed, cohort_ids}` | Серверная рандомизация кластеров/волн |
| `POST /pilots/{id}/transition {to_status, note}` | Машина статусов |
| `GET /pilots/{id}/fidelity?as_of=`, `POST /pilots/{id}/fidelity-logs` | Агрегаты реализации; запись/исправление журнала |
| `POST /pilots/{id}/follow-up {outcome_assessment_id?, as_of?}`, `GET /pilots/{id}/outcomes` | Повторное измерение (неизменяемый результат) |
| `POST /pilots/{id}/conclusions`, `GET /pilots/{id}/conclusions` | Вывод, следующая версия решения, предложение записи доказательной базы |
| `GET /learning/summary?dataset_id=` | Чему научилась организация |
| `GET /portfolio/interventions?dataset_id=&as_of=` | Портфель без рейтингов |

**Раунд 2**

| Метод и путь | Назначение |
|---|---|
| `GET/PUT /quality/assessments/{id}/assignments` | Явное назначение проверки классам (`assignment_scope`) |
| `GET /quality/assessments/{id}/dif?reference=ru&focal=kz` | Языковой DIF screening (Mantel–Haenszel) |
| `POST /design-studio/evaluate` | Experiment Design Studio (детерминированный расчёт, без утверждения) |
| `GET/POST /pilots/{id}/sessions`, `POST /pilots/{id}/sessions/generate`, `PATCH/DELETE /pilots/{id}/sessions/{sid}` | Календарь занятий пилота |

Изменения контрактов раунда 2: `as_of` в результате повторного измерения и в запросе (`as_of` в будущем → 422);
`TransitionRequest.override_future_end`; `AnalysisPlan.external_analysis_acknowledged`; `PilotOut.analysis_mode`;
`ConclusionCreate.decision_basis / stop_reason_code / acknowledged_limitation_codes`; `EvidenceSummary` с
`accepted_synthetic_entries`, `by_status_synthetic`, `synthetic_comparable_positive_signals`;
`PortfolioOut.learners_by_outcome_status`, `synthetic_evidence`; `FidelityOut.expected_source`; поле `suppression` в
результате повторного измерения; знаменатели качества с `assignment_scope`, `assigned_is_exact`,
`present_outside_assignment`. Списки `/interventions` и `/pilots` теперь страницы.

Коды ошибок модуля: `version_immutable`, `draft_exists`, `intervention_archived`, `version_in_use`, `version_conflict`,
`incomplete_for_review`, `protocol_locked`, `protocol_invalid` (`details.errors` — список проверок), `invalid_transition`,
`snapshot_mismatch`, `randomization_not_applicable`, `pilot_not_running`, `cohort_not_in_pilot`, `date_outside_pilot`,
`date_in_future`, `already_corrected`, `outcome_before_start`, `invalid_state`; раунд 2: `as_of_in_future`,
`outcome_after_as_of`, `end_date_in_future`, `protocol_only_external_analysis`, `stop_requires_operational_basis`,
`stop_reason_required`, `basis_inconsistent_with_outcome`, `unknown_limitation_code`, `concurrent_modification`,
`integrity_conflict`, `calendar_locked`, `session_exists` (`conclusion_misreads_fidelity` удалён).

## Отличия от исходного списка маршрутов задания
Добавлены вспомогательные маршруты (auth, quality, overview, analyses, fixtures, documents/*, search, plans/context,
ai/*). Существующие маршруты задания реализованы без изменения путей. `GET /topics/{id}/evidence` принимает фильтры
как JSON в параметре `filters`. Изменений общих контрактов (§5 задания) нет; уточнено: `dataset_version` — целое,
растущее при каждом commit импорта и при подтверждении/отклонении связи задания с целью.
