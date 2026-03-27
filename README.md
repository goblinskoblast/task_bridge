# TaskBridge

TaskBridge is a Telegram-first task management service with:

- task extraction from Telegram chats
- task extraction from connected email accounts
- Telegram Mini App for task management
- OpenClaw-based AI routing
- calendar sync for tasks with due dates
- phase 1 skeleton of a separate `data_agent` service

## Current modules

- `bot/` - Telegram bot logic, task extraction, notifications, reminders
- `webapp/` - FastAPI API and Mini App frontend
- `db/` - database models and DB helpers
- `email_integration/` - email encryption and IMAP helpers
- `data_agent/` - separate DataAgent service node, phase 1 skeleton
- `docs/` - deployment, SDD, and integration documentation

## Main bot commands

- `/start` - start and quick access
- `/panel` - open the task panel
- `/help` - usage help
- `/support` - support chat
- `/dataagent` - DataAgent dialog entrypoint
- `/connect` - connect an external system for DataAgent
- `/systems` - list connected DataAgent systems

## Local run

### Main service

```bash
python main.py
```

### Docker Compose

```bash
docker compose up --build
```

This starts:

- `taskbridge` on port `8000`
- `dataagent` on port `8010`

## Environment variables

Core variables are documented in [.env.example](C:/Users/Владислав/Desktop/task_bridge-main/.env.example).

Important groups:

- bot: `BOT_TOKEN`
- AI: `OPENAI_API_KEY`, `AI_PROVIDER`, `OPENCLAW_*`
- web app: `WEB_APP_DOMAIN`, `MINI_APP_URL`
- database: `DATABASE_URL`
- mail OAuth: `GOOGLE_OAUTH_*`, `YANDEX_OAUTH_*`
- DataAgent: `DATA_AGENT_URL`, `DATA_AGENT_TIMEOUT`

## DataAgent status

Phase 1 is already added:

- separate FastAPI node
- `/health`, `/chat`, `/systems/connect`, `/systems/{user_id}`
- Telegram integration via `/dataagent`, `/connect`, `/systems`

Not implemented yet:

- real OpenClaw orchestrator for DataAgent
- Browser Tool
- persistent storage for connected systems
- credentials storage
- internal email/calendar tools for DataAgent

## Notes

- The project currently uses a monorepo structure by design.
- Browser Agent requirements and fixes are tracked separately in `BROWSER_AGENT_FIXES.md` on the Desktop and should be applied in the next DataAgent phase.
