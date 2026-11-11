# OquMap API (`/api/v1`)

Полная машинная схема — `packages/contracts/openapi.json` (генерируется `scripts/export_openapi.py`; проверка
актуальности `--check`). Фронтенд-типы генерируются из неё: `cd apps/web && npm run gen:types` →
`src/api/schema.d.ts`. Интерактивная документация при запущенном API: `http://localhost:8000/docs`.

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
| `GET /health` | Состояние API и БД |
| `POST /auth/demo-login`, `POST /auth/login`, `GET /auth/me` | Вход |
| `GET /datasets`, `GET /datasets/{id}` | Наборы организации (с `version`, `is_synthetic`, `data_level`) |
| `GET /datasets/{id}/quality` | Проверки, пропуски, отсутствия, попытки, загрузки, история версий, доступный уровень анализа |
| `POST /datasets/{id}/overview` (body: Filters) | Темы, статусы, покрытие, приоритеты, пробелы измерения, темы × классы |
| `GET /curriculum?dataset_id=` | Программа, темы, цели, связи, издания, школы, классы, проверки |
| `GET /topics/{id}/evidence?dataset_id=&filters=<json>` | Результат темы, цели, задания и дистракторы, гипотезы ошибок, предпосылки, источники, исключения |
| `POST /comparisons` | Сравнение изданий (`ComparisonRequest`: topic, editions, filters, `strata_scheme`, `weight_mode`, `include_topic_table`) |
| `GET /analyses/{id}` | Снимок анализа (с признаком устаревания) |
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
| `POST /decisions`, `GET /decisions`, `GET /decisions/{id}` | Карточки решений (снимок оснований) |
| `POST /decisions/{id}/approve {note}` | Утверждение → новая версия, прежняя `superseded` |
| `POST /decisions/{id}/follow-up {assessment_id?}` | Наблюдаемая динамика на общих заданиях |
| `GET /decisions/{id}/report?format=pdf|csv|xlsx` | Экспорт из снимка решения |
| `GET /ai/status` | Провайдер модели, доступность live-режима и OCR |
| `POST /ai/explain-comparison`, `/ai/interpret-misconception`, `/ai/recommend` | Объяснения и рекомендации (режим виден) |
| `POST /assistant/query` | Контекстный ассистент с разрешёнными функциями чтения/расчёта |

## Измерение и организационное обучение (Claude №2)
Подробно: [ASSESSMENT_QUALITY.md](ASSESSMENT_QUALITY.md), [INTERVENTION_AND_PILOT_PROTOCOL.md](INTERVENTION_AND_PILOT_PROTOCOL.md),
[LEARNING_LOOP.md](LEARNING_LOOP.md). Чтение — любой участник организации; права на изменения — в протоколе (§3).

| Метод и путь | Назначение |
|---|---|
| `GET /quality/assessments?dataset_id=&attempt_rule=&omitted_policy=` | Сводка качества по проверкам (знаменатели, пропуски, α, число заданий с сигналами) |
| `GET /quality/assessments/{id}` | Форма: знаменатели, распределение, надёжность, разрезы со скрытием, задания, исключения, ограничения, происхождение |
| `GET /quality/assessments/{id}/items?flag=` | Задания проверки (p, r, D, дистракторы, сигналы) |
| `GET /quality/items/{id}?dataset_id=` | Задание во всех проверках, без объединения |
| `GET /interventions?status=&evidence_level=&topic_id=&objective_id=&misconception=&grade=&language=&q=` | Библиотека |
| `POST /interventions` | Новая интервенция (черновик v1) |
| `GET /interventions/{id}`, `PATCH /interventions/{id}` | Карточка с версиями и доказательной базой; правка черновика (`expected_version`) |
| `POST /interventions/{id}/versions` | Новая версия (если последняя рецензирована) |
| `POST /interventions/{id}/versions/{v}/review` | Рецензирование (approver) |
| `DELETE /interventions/{id}/versions/{v}` | Удаление неиспользуемого черновика |
| `POST /interventions/{id}/archive {reason}` | Архив (approver) |
| `POST /interventions/{id}/targets` | Связь черновика с темой/целью/ошибкой |
| `GET /interventions/suggest?topic_id=&objective_id=&misconception=&grade=&language=&dataset_id=` | Подбор с объяснённым баллом |
| `GET /interventions/{id}/evidence`, `POST /intervention-evidence/{entry}/review {accept, note}` | Доказательная база; принятие записи (approver) |
| `GET /pilots?dataset_id=&status=&intervention_id=`, `POST /pilots` | Пилоты, создание черновика протокола |
| `GET /pilots/{id}`, `PATCH /pilots/{id}` | Протокол с проверкой и допустимыми переходами; правка только в `draft` |
| `POST /pilots/{id}/randomize {seed, cohort_ids}` | Серверная рандомизация кластеров/волн |
| `POST /pilots/{id}/transition {to_status, note}` | Машина статусов |
| `GET /pilots/{id}/fidelity?as_of=`, `POST /pilots/{id}/fidelity-logs` | Агрегаты реализации; запись/исправление журнала |
| `POST /pilots/{id}/follow-up {outcome_assessment_id?, as_of?}`, `GET /pilots/{id}/outcomes` | Повторное измерение (неизменяемый результат) |
| `POST /pilots/{id}/conclusions`, `GET /pilots/{id}/conclusions` | Вывод, следующая версия решения, предложение записи доказательной базы |
| `GET /learning/summary?dataset_id=` | Чему научилась организация |
| `GET /portfolio/interventions?dataset_id=&as_of=` | Портфель без рейтингов |

Коды ошибок модуля: `version_immutable`, `draft_exists`, `intervention_archived`, `version_in_use`, `version_conflict`,
`incomplete_for_review`, `protocol_locked`, `protocol_invalid` (`details.errors` — список проверок), `invalid_transition`,
`snapshot_mismatch`, `randomization_not_applicable`, `pilot_not_running`, `cohort_not_in_pilot`, `date_outside_pilot`,
`date_in_future`, `already_corrected`, `outcome_before_start`, `conclusion_misreads_fidelity`, `invalid_state`.

## Отличия от исходного списка маршрутов задания
Добавлены вспомогательные маршруты (auth, quality, overview, analyses, fixtures, documents/*, search, plans/context,
ai/*). Существующие маршруты задания реализованы без изменения путей. `GET /topics/{id}/evidence` принимает фильтры
как JSON в параметре `filters`. Изменений общих контрактов (§5 задания) нет; уточнено: `dataset_version` — целое,
растущее при каждом commit импорта и при подтверждении/отклонении связи задания с целью.
