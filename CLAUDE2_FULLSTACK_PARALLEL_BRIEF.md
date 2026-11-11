# Claude №2 — параллельный full-stack контур OquMap

Это инструкция на реализацию, а не на план или обзор. Построй и проверь большой самостоятельный вертикальный контур OquMap: **качество оценивания → интервенция → контроль выполнения → повторное измерение → организационное обучение**.

## 0. Рабочее окружение и запреты

- Работай только в: `C:\Users\User\Documents\ChatGPT\OquMap-claude2-c2`
- Ветка: `claude/measurement-learning-loop`
- Базовый commit: `cd70f1c7290a09801ddeb7aa19690042056782bf`
- Первый Claude работает отдельно в `C:\Users\User\Documents\ChatGPT\Taraz` на `claude/serene-carson-m1pbvz`.

Не переключай ветки, не редактируй соседний worktree, не делай merge/rebase/push/force-push и не переписывай историю. Делай логические локальные commits в `claude/measurement-learning-loop`.

Перед началом прочитай `README.md`, `docs/METHODOLOGY.md`, `docs/DEMO_SCENARIO.md`, `docs/CLAUDE_HANDOFF.md`, модели, API, аналитику и существующие тесты. Не считай документацию верной без проверки кода.

## 1. Разделение работы

Первый Claude сейчас делает платформенный контур: импорт проекта, provider-agnostic AI, безопасность публичного демо, миграционный старт, CI, evidence map, AI-review, sandbox, diagnostic generation и инфраструктурную надёжность.

Твоя независимая зона:

1. Assessment Quality Lab.
2. Intervention Library и pilot protocol.
3. Implementation Fidelity Tracker.
4. Follow-up / Learning Loop.
5. Portfolio Effectiveness API.
6. Полный backend + DB + API + функциональный frontend + тесты для этих модулей.

Финальный визуальный дизайн, presentation mode и конкурсную упаковку позже делает Codex. Тебе всё равно нужен полноценный, понятный и кликабельный frontend без пустых заглушек, но не трать время на декоративный редизайн и не копируй сгенерированные картинки.

## 2. Стратегия против конфликтов

Создавай новые модули преимущественно в отдельных файлах:

- `apps/api/oqumap/analytics/assessment_quality.py`
- `apps/api/oqumap/services/interventions.py`
- `apps/api/oqumap/services/fidelity.py`
- `apps/api/oqumap/services/learning_loop.py`
- `apps/api/oqumap/schemas/interventions.py`
- `apps/api/oqumap/api/intervention_routes.py`
- `apps/api/tests/test_assessment_quality.py`
- `apps/api/tests/test_interventions.py`
- `apps/api/tests/test_fidelity.py`
- `apps/api/tests/test_learning_loop.py`
- `apps/web/src/features/quality/**`
- `apps/web/src/features/interventions/**`
- `apps/web/src/features/followup/**`
- отдельные frontend tests.

Изменения в общих файлах (`models.py`, `routes.py`, `App.tsx`, API hooks/types, OpenAPI, seed) неизбежны, но держи их минимальными и вынеси в отдельные commits. Не переформатируй чужие файлы целиком. Не меняй существующую семантику scoring/comparison/planning без отдельного обоснованного теста.

## 3. Assessment Quality Lab

Реализуй вычислительное ядро для оценки качества теста и отдельных заданий на существующих `Assessment`, `Sitting`, `Response`, `Item`, `FormItem`.

### 3.1 Метрики формы

- число назначенных, присутствовавших, отсутствовавших;
- completion/omission rate с правильными знаменателями;
- распределение итогового нормированного балла;
- среднее, медиана, SD, floor/ceiling share;
- Cronbach alpha только когда условия и данные достаточны;
- явные `not_available` + reason при недостаточности;
- разрезы по классу/языку только при допустимом минимальном n;
- никаких сравнений групп, раскрывающих маленькие когорты.

### 3.2 Метрики задания

- p-value/difficulty как доля набранных баллов;
- omission rate;
- item-total correlation с corrected total;
- discrimination по верхней/нижней группе с явно описанным правилом;
- distractor analysis по `response_value` и `Item.options`, включая non-functional distractors;
- связь с подтверждёнными objective и misconception;
- флаги: слишком лёгкое/сложное, низкая/отрицательная discrimination, высокая omission, подозрительный distractor;
- флаг — только сигнал для проверки, не автоматический приговор заданию.

### 3.3 Сопоставимость

- не объединяй разные формы/шкалы без anchor/equating основания;
- для формы с partial credit корректно нормируй по max_points;
- отсутствующие learners не равны нулю;
- omitted и wrong не смешиваются;
- multiple attempts обрабатываются по явно выбранному и документированному правилу;
- все denominator и exclusions возвращаются в API.

### 3.4 API

Добавь endpoints вида:

- `GET /api/v1/quality/assessments`
- `GET /api/v1/quality/assessments/{assessment_id}`
- `GET /api/v1/quality/assessments/{assessment_id}/items`
- `GET /api/v1/quality/items/{item_id}`

Поддержи `dataset_id`, безопасные фильтры и tenant isolation. Ответы включают method version, dataset version, generated_at, sample/exclusions, limitations и provenance.

## 4. Intervention Library

Добавь версионируемую библиотеку интервенций. Минимальная сущность:

- org/dataset scope;
- title RU/KZ, description RU/KZ;
- target topic/objective/misconception;
- grade/language applicability;
- required minutes/hours, duration weeks, cadence;
- instructions, required resources;
- evidence level: `practice_based | observational | experimental`;
- source/evidence links;
- contraindications/limitations;
- author, version, status `draft|reviewed|archived`;
- timestamps и audit fields.

Поддержи CRUD без физического удаления опубликованной истории: archive/supersede вместо разрушения ссылок. Пользователь не должен иметь возможность подменить версию интервенции в уже запущенном пилоте.

API минимум:

- list/filter/create/get/update/version/archive interventions;
- link intervention to topic/objective/misconception;
- получить подходящие interventions для проблемы, но сортировку называть recommendation только при объяснимом scoring;
- возвращать reasons и limitations.

## 5. Pilot Protocol

Расширь decision workflow полноценным пилотом, не ломая текущие `Decision` и `FollowUp`.

Новые сущности/связи должны фиксировать:

- snapshot версии интервенции;
- target cohorts и единицу назначения;
- baseline assessment и planned outcome assessment;
- start/end dates;
- owner;
- planned cadence/dosage;
- comparison design: `single_group | matched_comparison | cluster_randomized | interrupted_time_series | stepped_wedge`;
- inclusion/exclusion criteria;
- primary outcome/objective;
- analysis plan и causal ceiling;
- status machine: `draft → ready → active → completed|stopped`, с валидными переходами.

Не разрешай `cluster_randomized`, если нет достаточных кластеров и назначения. Не обещай causal effect для single_group. Все проверки должны быть серверными, не только UI.

## 6. Implementation Fidelity Tracker

Реализуй наблюдение за тем, была ли интервенция фактически выполнена.

Минимальные записи:

- pilot, cohort, date;
- planned vs delivered minutes;
- activities/tasks completed;
- reach: присутствовали/назначены;
- adherence checklist;
- adaptation note;
- disruption/cancellation reason;
- recorder и source;
- immutable audit timestamps.

Агрегаты:

- dosage completion;
- session completion;
- reach;
- adherence;
- missing logs;
- overall fidelity classification с прозрачным rule set.

При низкой/неизвестной fidelity результат follow-up не должен автоматически маркировать интервенцию неэффективной. Это ключевой продуктовый принцип и обязательный тест.

## 7. Follow-up и Learning Loop

Создай сервис повторного измерения, который соединяет pilot, fidelity и assessment outcome.

### 7.1 Результаты

- pre/post change с явной шкалой;
- paired analysis только для действительно сопоставленных learners;
- cohort-level summaries и cluster-aware warnings;
- attrition/missingness;
- confidence interval только методом, соответствующим данным;
- raw и adjusted result — только если adjustment заранее определён и воспроизводим;
- status: `positive_signal | mixed | not_confirmed | needs_more_data | invalid_due_to_fidelity | invalid_due_to_comparability`;
- causal ceiling на основании дизайна, а не уверенности LLM.

### 7.2 Learning Loop

После follow-up система должна позволять:

- сохранить вывод с evidence IDs;
- продолжить, изменить или остановить intervention;
- создать следующую version решения;
- обновить intervention evidence summary без перезаписи исторической версии;
- показать, чему организация научилась и какие вопросы остались.

Не делать автоматическое policy learning, которое само меняет рекомендации без human approval.

## 8. Portfolio Effectiveness

Добавь API-агрегацию по активным/завершённым pilots:

- counts by status;
- due/overdue follow-ups;
- fidelity distribution;
- outcome status distribution;
- interventions with repeated signals;
- coverage по topics/objectives;
- данные, которых не хватает для вывода.

Запрещено строить league table школ/учителей. Малые группы скрываются/агрегируются. Вывод «лучшая интервенция» не показывать без сопоставимости и достаточной повторяемости.

## 9. Функциональный frontend

Создай рабочие экраны, подключённые к API:

- `/quality` — список assessment и сигналы качества;
- `/quality/:assessmentId` — form/item diagnostics, exclusions, limitations;
- `/interventions` — library с фильтрами и версионированием;
- `/interventions/:id` — evidence, instructions, versions;
- `/pilots/new` и `/pilots/:id` — protocol, cohorts, design, status;
- `/pilots/:id/fidelity` — журнал и агрегаты выполнения;
- `/pilots/:id/follow-up` — измерение, ограничения и решение следующего цикла;
- `/portfolio/interventions` — агрегаты и очередь действий.

Требования:

- все действия реально работают;
- loading/error/empty/partial/forbidden states;
- RU/KZ через существующую i18n-систему;
- клавиатурная доступность и семантические таблицы/формы;
- никакого декоративного AI-чата;
- не трать время на финальный стиль: используй существующие компоненты и чистую структуру.

## 10. Данные и demo scenario

Расширь synthetic demo так, чтобы были:

- минимум две assessment forms и item-response данные;
- задания с хорошими и проблемными характеристиками;
- 4–7 interventions разных evidence levels;
- минимум три pilots: active, completed-positive-signal, invalid/needs-more-data;
- fidelity logs с полной и неполной реализацией;
- follow-up outcome с известным ожидаемым поведением.

Seed должен быть детерминированным и идемпотентным. Synthetic данные явно маркируются. Не меняй пользовательские документы или финальные материалы.

## 11. Миграции и контракты

- Создай новую Alembic revision поверх своей базы; не переписывай initial migration.
- Проверяй upgrade на чистой БД и на БД с текущей схемой.
- Все таблицы tenant-scoped там, где это нужно.
- Foreign keys, indexes, unique constraints и status validation должны соответствовать invariants.
- Обнови Pydantic schemas, OpenAPI и generated frontend types.
- OpenAPI drift test обязателен.
- Даты timezone-aware; NaN/Infinity не попадают в JSON.

## 12. Безопасность и права

- analyst: просмотр quality и portfolio;
- methodist: создание draft intervention/pilot и fidelity logs;
- approver/admin: review/archive intervention, activate/stop pilot;
- teacher-level/raw learner data не показывать без нужной роли;
- tenant isolation тестировать для каждого нового семейства endpoints;
- notes очищаются/ограничиваются по длине;
- audit trail не содержит секретов и лишних персональных данных.

Если текущая модель ролей отличается, адаптируй права к фактической архитектуре и документируй решение.

## 13. Тестирование

Обязательны:

- unit tests статистических функций на вручную проверяемых массивах;
- zero variance, all omitted, partial credit, tiny n, multiple attempts;
- distractor analysis и отрицательная discrimination;
- deterministic seed;
- state machine pilot и запрещённые переходы;
- version immutability intervention;
- fidelity aggregation и missing logs;
- низкая fidelity не превращается в «интервенция не работает»;
- comparability/attrition/causal ceiling;
- tenant isolation и permissions;
- API flow от intervention до follow-up;
- frontend rendering/actions/RU-KZ/empty-error states;
- migration upgrade и OpenAPI drift.

Запусти фактические команды проекта. Минимум:

```text
cd apps/api
uv run ruff check .
uv run pytest

cd apps/web
npm ci
npm test
npm run typecheck
npm run build
```

Не удаляй существующие тесты ради зелёного результата. Не отмечай тест как пройденный, если команда не выполнялась.

## 14. Документация

Добавь:

- `docs/ASSESSMENT_QUALITY.md` — определения, знаменатели, ограничения;
- `docs/INTERVENTION_AND_PILOT_PROTOCOL.md`;
- `docs/LEARNING_LOOP.md`;
- обновления `docs/API.md` и `docs/METHODOLOGY.md` только по фактической реализации;
- `docs/CLAUDE2_HANDOFF.md`.

Handoff обязан содержать:

- branch/base и список commits;
- реализованные модели/endpoints/screens;
- migration revision;
- изменённые общие файлы и потенциальные конфликты;
- результаты всех тест-команд;
- API assumptions;
- известные ограничения;
- точный порядок интеграции;
- что проверить вручную после merge.

## 15. Commit plan

Делай логические commits примерно так:

1. `Add assessment quality analytics and tests`
2. `Add intervention library models and API`
3. `Add pilot protocol and state machine`
4. `Add fidelity tracking and learning loop`
5. `Add intervention portfolio API`
6. `Add functional frontend for quality and interventions`
7. `Extend deterministic demo and end-to-end tests`
8. `Document measurement and intervention workflow`
9. `Prepare Claude2 integration handoff`

Работа завершена только когда вертикальный сценарий проходит end-to-end: методист видит проблему качества → выбирает/создаёт интервенцию → запускает валидный pilot → фиксирует fidelity → добавляет follow-up assessment → получает честный вывод → сохраняет следующую версию решения.

