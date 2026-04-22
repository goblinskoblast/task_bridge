# Деплой TaskBridge на Northflank

Этот runbook рассчитан на текущую архитектуру TaskBridge:

- публичный сервис `web` с Telegram webhook и Mini App
- внутренний сервис `data_agent` с monitor scheduler и point stats scheduler
- одна PostgreSQL база

## Что уже подготовлено в репозитории

- основной контейнер для `web`: [Dockerfile](../Dockerfile)
- отдельный контейнер для `data_agent`: [Dockerfile.data_agent](../Dockerfile.data_agent)

Это позволяет поднимать сервисы раздельно и не переопределять стартовые команды вручную.

## Целевая схема

1. `taskbridge-web`
   - тип: Service
   - Dockerfile: `Dockerfile`
   - публичный HTTP-порт: `8000`

2. `taskbridge-data-agent`
   - тип: Service
   - Dockerfile: `Dockerfile.data_agent`
   - внутренний HTTP-порт: `8010`

3. `taskbridge-postgres`
   - тип: PostgreSQL addon / database

## Важно про внутренний адрес

После создания каждого сервиса открой его в Northflank и скопируй внутренний endpoint из раздела сети / networking.

Дальше:

- `web` должен ходить в `data_agent` по его внутреннему HTTP endpoint
- `data_agent` должен ходить обратно в `web` по его внутреннему HTTP endpoint с суффиксом `/api/internal/data-agent`

Пример формы значений:

```env
DATA_AGENT_URL=http://<internal-data-agent-endpoint>:8010
INTERNAL_API_URL=http://<internal-web-endpoint>:8000/api/internal/data-agent
```

## Шаг 1. Создать базу

Создай PostgreSQL в этом же проекте Northflank и забери connection string.

Потом подставь её в переменную:

```env
DATABASE_URL=postgresql://...
```

## Шаг 2. Создать сервис `taskbridge-data-agent`

Параметры:

- Source: GitHub repo `task_bridge`
- Build method: Dockerfile
- Dockerfile path: `Dockerfile.data_agent`
- Port: `8010`
- Public networking: `off`

### Env для `taskbridge-data-agent`

Обязательные:

```env
BOT_TOKEN=...
OPENAI_API_KEY=...
AI_PROVIDER=openai
DATABASE_URL=postgresql://...
INTERNAL_API_URL=http://<internal-web-endpoint>:8000/api/internal/data-agent
INTERNAL_API_TOKEN=<shared-random-token>
DATA_AGENT_TIMEOUT=45
TIMEZONE=Asia/Yekaterinburg
```

Если используешь Anthropic / OpenClaw / reviews / OAuth, перенеси и эти переменные тоже.

## Шаг 3. Создать сервис `taskbridge-web`

Параметры:

- Source: GitHub repo `task_bridge`
- Build method: Dockerfile
- Dockerfile path: `Dockerfile`
- Port: `8000`
- Public networking: `on`

После первого деплоя Northflank даст публичный URL вида:

```text
https://taskbridge-web-<slug>.northflank.app
```

### Env для `taskbridge-web`

Минимальный рабочий набор:

```env
BOT_TOKEN=...
OPENAI_API_KEY=...
AI_PROVIDER=openai
DATABASE_URL=postgresql://...
USE_WEBHOOK=true
WEBHOOK_URL=https://taskbridge-web-<slug>.northflank.app
WEBHOOK_PATH=/webhook
WEB_APP_DOMAIN=https://taskbridge-web-<slug>.northflank.app
MINI_APP_URL=https://taskbridge-web-<slug>.northflank.app/webapp/index.html
DATA_AGENT_URL=http://<internal-data-agent-endpoint>:8010
INTERNAL_API_TOKEN=<shared-random-token>
TIMEZONE=Asia/Yekaterinburg
ALLOW_INSECURE_USER_ID_AUTH=true
```

Дополнительно перенеси:

- `OPENAI_MODEL`
- `ANTHROPIC_API_KEY`, если нужен Anthropic
- `GOOGLE_OAUTH_*`
- `YANDEX_OAUTH_*`
- `DEVELOPER_TELEGRAM_ID`
- `REVIEWS_SHEET_URL`
- `ITALIAN_PIZZA_REVIEWS_SHEET_URLS`
- `EMAIL_ENCRYPTION_KEY`
- все остальные реально используемые секреты из текущего `.env`

## Шаг 4. Переключить Telegram webhook

Когда `taskbridge-web` стал зелёным и отвечает, webhook должен смотреть на:

```text
https://taskbridge-web-<slug>.northflank.app/webhook
```

Проверка:

```text
https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo
```

Успешный результат:

- `pending_update_count` не растёт
- `last_error_message` пустой

## Шаг 5. Что проверить сразу после деплоя

1. `/start` у priority user
2. `Покажи подключённые системы`
3. `Покажи мониторинги`
4. `Покажи стоп-лист по всем точкам`
5. `Покажи бланки по всем добавленным точкам`

И отдельно:

- `taskbridge-web` отвечает по HTTPS
- `taskbridge-web` видит `taskbridge-data-agent`
- `taskbridge-data-agent` видит `taskbridge-web`
- scheduler в `data_agent` стартовал без ошибок

## Что может сломаться чаще всего

### 1. `web` не достаёт `data_agent`

Проверь:

```env
DATA_AGENT_URL=http://<internal-data-agent-endpoint>:8010
```

### 2. `data_agent` не достаёт internal API `web`

Проверь:

```env
INTERNAL_API_URL=http://<internal-web-endpoint>:8000/api/internal/data-agent
INTERNAL_API_TOKEN=<тот же токен что и в web>
```

### 3. Telegram webhook не работает

Проверь:

- `USE_WEBHOOK=true`
- `WEBHOOK_URL` без завершающего `/`
- публичный URL Northflank действительно доступен

### 4. Mini App открывается, но auth ломается

Проверь:

- `WEB_APP_DOMAIN`
- `MINI_APP_URL`
- HTTPS обязателен

## Быстрый чек-лист env

Одинаковые у обоих сервисов:

- `BOT_TOKEN`
- `DATABASE_URL`
- `INTERNAL_API_TOKEN`
- `TIMEZONE=Asia/Yekaterinburg`

Только у `web`:

- `USE_WEBHOOK=true`
- `WEBHOOK_URL`
- `WEBHOOK_PATH=/webhook`
- `WEB_APP_DOMAIN`
- `MINI_APP_URL`
- `DATA_AGENT_URL=http://<internal-data-agent-endpoint>:8010`

Только у `data_agent`:

- `INTERNAL_API_URL=http://<internal-web-endpoint>:8000/api/internal/data-agent`

## После миграции

Когда деплой будет поднят, отдельно проверь продовые сценарии priority user `telegram_id=137236883`:

1. stoplist по `Сухой Лог, Белинского 40`
2. blanks по одной точке
3. blanks по всем сохранённым точкам
4. сводку активных мониторингов
5. отсутствие user-facing технички в ошибках
