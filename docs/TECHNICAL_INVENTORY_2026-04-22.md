# TaskBridge Technical Inventory, 2026-04-22

Этот inventory нужен как стартовая точка перед сборкой `Agent Platform Foundation`.

Главный продуктовый anchor остаётся тот же:

- priority user: `telegram_id=137236883`
- его production-потоки по `stoplist / blanks / monitor` ломать нельзя

## 1. Текущий стек

- Python backend
- `aiogram` для Telegram-бота
- `FastAPI` + `uvicorn` для web/API
- `SQLAlchemy` sync + async sessions
- `APScheduler` для reminder и monitor job'ов
- `aiohttp` для внутренних и внешних HTTP-запросов
- `openai` / `anthropic` через текущую provider-конфигурацию
- `Playwright` для browser-based data access
- `openpyxl`, `python-docx`, `xlrd` для документов и вложений

## 2. Структура репозитория

- [bot](C:/Users/Владислав/Desktop/task_bridge-main/bot) — Telegram handlers, reminders, support, delivery, agent menu
- [data_agent](C:/Users/Владислав/Desktop/task_bridge-main/data_agent) — отдельный service node для reports, monitors, system connections и browser adapters
- [webapp](C:/Users/Владислав/Desktop/task_bridge-main/webapp) — FastAPI API + Mini App frontend
- [db](C:/Users/Владислав/Desktop/task_bridge-main/db) — модели, engine, init/migration helpers
- [email_integration](C:/Users/Владислав/Desktop/task_bridge-main/email_integration) — email secrets и IMAP helpers
- [scripts](C:/Users/Владислав/Desktop/task_bridge-main/scripts) — operator/debug scripts
- [tests](C:/Users/Владислав/Desktop/task_bridge-main/tests) — регрессии и unit/integration-style тесты
- [docs](C:/Users/Владислав/Desktop/task_bridge-main/docs) — roadmap, deployment notes, product contracts

## 3. Runtime topology

### 3.1 Main bot/web process

- entrypoint: [main.py](C:/Users/Владислав/Desktop/task_bridge-main/main.py:1)
- в webhook mode поднимает `FastAPI` app и Telegram webhook
- в polling mode держит webapp в фоне и отдельно запускает Telegram polling
- reminder scheduler стартует отсюда же

### 3.2 Bot-only fallback

- entrypoint: [main_bot_only.py](C:/Users/Владислав/Desktop/task_bridge-main/main_bot_only.py:1)
- полезен как упрощённый polling-only runtime

### 3.3 DataAgent process

- entrypoint: [data_agent/main.py](C:/Users/Владислав/Desktop/task_bridge-main/data_agent/main.py:1)
- отдельный `FastAPI` node
- поднимает:
  - monitor scheduler
  - point statistics scheduler
- хранит system connections, monitor state и agent-oriented routing

## 4. База данных и модели

### 4.1 DB layer

- engine/session setup: [db/database.py](C:/Users/Владислав/Desktop/task_bridge-main/db/database.py:1)
- поддерживаются `PostgreSQL` и `SQLite`
- schema evolution сейчас partly ad-hoc через `_ensure_*` functions в `init_db()`

### 4.2 Основные сущности

По текущему коду уже существуют модели для:

- пользователей и задач
- сообщений и поддержки
- email accounts/messages
- saved points
- data-agent profiles
- connected systems
- monitor configs
- monitor events
- request logs и sessions

Это значит, что новый `Agent Platform Foundation` не стартует с пустого места. У нас уже есть:

- базовая task model
- persistent storage для connected systems
- persistent storage для monitor state и monitor events
- request/debug traces

### 4.3 Главный разрыв относительно нового плана

Сейчас нет явной production-модели именно `StopListEvent` / `incident lifecycle` для управляющего.

Есть monitor state и delivery events, но нет полного business-level контура:

- событие
- реакция управляющего
- SLA / escalation
- связь события с задачей
- digest over repeated incidents

Именно это — ближайший structural gap для `P0/P1`.

## 5. Где сейчас живёт продовая логика

### 5.1 Telegram UX и agent entry

- handlers / navigation / replies: [bot](C:/Users/Владислав/Desktop/task_bridge-main/bot)
- главный user-facing контур уже сильно смещён в free-text-first agent flow

### 5.2 Reports / monitors / system connections

- service layer: [data_agent/service.py](C:/Users/Владислав/Desktop/task_bridge-main/data_agent/service.py)
- routing/orchestration: `agent_runtime`, `scenario_engine`
- product contracts по stoplist/blanks/reviews уже partly formalized через tests

### 5.3 Schedulers

- reminders: [bot/reminders.py](C:/Users/Владислав/Desktop/task_bridge-main/bot/reminders.py:255)
- monitor scheduler: [data_agent/monitor_scheduler.py](C:/Users/Владислав/Desktop/task_bridge-main/data_agent/monitor_scheduler.py:689)
- point stats scheduler: [data_agent/point_stats_scheduler.py](C:/Users/Владислав/Desktop/task_bridge-main/data_agent/point_stats_scheduler.py:26)

## 6. Уже сделанные платформенные заготовки

Последние итерации уже подготовили часть основы под новый курс:

- каталог систем
- capability model
- scan contract
- system orientation
- scan plan scaffold
- persisted scan progress scaffold

Это полезно как слой `connector/orientation substrate`, но пока не заменяет:

- Agent Core
- Skill Runtime
- StopListSkill
- Task Engine для manager workflow

## 7. Интеграции

Текущий репозиторий уже тянет несколько направлений интеграций:

- Telegram bot + Mini App
- internal DataAgent HTTP bridge
- email / IMAP
- Google / Yandex OAuth
- reviews sheets
- Italian Pizza public stoplist
- Italian Pizza browser-based blanks
- system catalog scaffolding для `iiko` и `keeper`

## 8. Как запускать локально

### Основной сервис

```bash
python main.py
```

### DataAgent отдельно

```bash
uvicorn data_agent.main:app --host 0.0.0.0 --port 8010
```

### Полный локальный контур через Docker

```bash
docker compose up --build
```

## 9. Как запускать тесты

Полный suite:

```bash
python -m pytest -q
```

Точечные тесты:

```bash
python -m pytest tests/test_priority_user_golden_flows.py -q
python -m pytest tests/test_system_catalog.py tests/test_system_orientation.py -q
```

## 10. Что уже хорошо покрыто

Сильные стороны текущего тестового контура:

- free-text monitor flow
- blanks contracts
- stoplist adapters/helpers
- monitor persistence and alert delivery behavior
- priority user golden flows
- user-facing safety against technical garbage
- system catalog / orientation / scan scaffold

## 11. Основные архитектурные риски

### 11.1 Event model gap

Нет явного business-level `StopListEvent` с lifecycle и reaction statuses.

### 11.2 Task Engine mismatch

Task system в проекте уже есть, но он вырос из общего task management сценария, а не из incident-driven manager workflow.

Нужно аккуратно решить:

- reuse текущих задач
- либо отдельный слой task orchestration поверх существующей модели

### 11.3 Audit/evidence fragmented

Логи, request traces, monitor events и DB state уже есть, но они разрозненны.
Для нового этапа нужен единый контракт evidence/audit по business events.

### 11.4 Scheduler fragmentation

Сейчас job logic живёт в нескольких местах.
Для `Skill Runtime` надо не сломать текущие schedulers, а постепенно привести их к общему job contract.

### 11.5 Schema evolution

`init_db()` уже делает ad-hoc column ensures.
Новый structural слой надо добавлять так, чтобы не получить болезненный prod migration path.

### 11.6 Connector distraction risk

Каталог систем уже есть, и очень легко снова уйти в расширение `iiko/keeper/MAX` раньше, чем будет собран базовый agent platform slice.

## 12. Рекомендуемый ближайший vertical slice

Новый минимальный боевой срез я бы собирал так:

1. Technical inventory и mapping существующих частей к будущим `Agent Core / Skill Runtime / Task Engine`.
2. Явная модель `StopListEvent` / `incident`.
3. Чат-карточка события с реакциями управляющего.
4. SLA / reminder / escalation contract.
5. Weekly digest по recurring incidents.
6. Минимальный `StopListSkill` поверх текущих production data sources.
7. Audit/evidence minimum.

Это даст:

- новый agent-platform contour
- без переписывания всего проекта
- без ломания текущего production stoplist/blanks behavior
