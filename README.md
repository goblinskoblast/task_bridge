# TaskBridge

TaskBridge is a Telegram-first task management service with:

- task extraction from Telegram chats
- task extraction from connected email accounts
- Telegram Mini App for task management
- OpenClaw-based AI routing
- calendar sync for tasks with due dates
- phase 4 Browser Agent MVP for `data_agent`

## Current modules

- `bot/` - Telegram bot logic, task extraction, notifications, reminders
- `webapp/` - FastAPI API and Mini App frontend
- `db/` - database models and DB helpers
- `email_integration/` - email encryption and IMAP helpers
- `data_agent/` - separate DataAgent service node with phase 4 Browser Agent MVP
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

Phase 4 is already added:

- separate FastAPI node
- `/health`, `/chat`, `/systems/connect`, `/systems/{user_id}`
- Telegram integration via `/dataagent`, `/connect`, `/systems`
- persistent storage for connected systems
- internal email/calendar tools
- AI orchestrator for tool planning and final answer synthesis
- Browser Agent MVP via Playwright for connected systems

Not implemented yet:

- secure vault-level credentials storage
- production-grade browser orchestration and Telegram progress streaming

## Notes

- The project currently uses a monorepo structure by design.
- Browser Agent requirements and fixes are tracked separately in `BROWSER_AGENT_FIXES.md` on the Desktop and should be applied in the next DataAgent phase.
