# DataAgent Phase 1

## Что реализовано

- отдельный сервис `data_agent` на FastAPI
- HTTP-контракты:
  - `GET /health`
  - `POST /chat`
  - `POST /systems/connect`
  - `GET /systems/{user_id}`
- Telegram-команды:
  - `/dataagent`
  - `/connect`
  - `/systems`
- отдельный клиент `bot/data_agent_client.py`
- отдельный router `bot/data_agent_handlers.py`

## Что это даёт

- в проекте появился изолированный контур DataAgent
- бот уже умеет разговаривать с отдельным data-agent node
- подключение внешних систем и chat flow уже имеют стабильные контракты для следующих этапов

## Что пока не реализовано

- реальный OpenClaw orchestrator
- Browser Tool на Playwright
- постоянное хранение подключённых систем в БД
- безопасное хранилище credentials
- internal API tools для почты и календаря

## Следующий этап

1. Перевести `data_agent/service.py` с in-memory storage на БД + secret storage
2. Добавить orchestrator слой и реальный tool routing
3. Подключить internal email/calendar tools
4. После этого переходить к Browser Tool
