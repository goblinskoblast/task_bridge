# TaskBridge

TaskBridge is a Telegram-first task management service with:

- task extraction from Telegram chats
- task extraction from connected email accounts
- Telegram Mini App for task management
- OpenClaw-based AI routing
- calendar sync for tasks with due dates
- phase 4 Browser Agent MVP for `data_agent`
- first restaurant demo scenario for reviews analytics via `review_tool`

## Current modules

- `bot/` - Telegram bot logic, task extraction, notifications, reminders
- `webapp/` - FastAPI API and Mini App frontend
- `db/` - database models and DB helpers
- `email_integration/` - email encryption and IMAP helpers
- `data_agent/` - separate DataAgent service node with Browser Agent MVP and modular tools
- `docs/` - deployment, SDD, and integration documentation

## Main bot commands

- `/start` - start and quick access
- `/panel` - open the task panel
- `/help` - usage help
- `/support` - support chat
- `/agent` - main entrypoint for the orchestrator
- `/dataagent` and `/bigbrother` - hidden compatibility aliases
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
- `dataagent` on port `8010` inside the repo; on Railway it should be created as a separate service inside the same project

## Environment variables

Core variables are documented in `.env.example`.

Important groups:

- bot: `BOT_TOKEN`
- AI: `OPENAI_API_KEY`, `AI_PROVIDER`, `OPENCLAW_*`
- web app: `WEB_APP_DOMAIN`, `MINI_APP_URL`
- database: `DATABASE_URL`
- mail OAuth: `GOOGLE_OAUTH_*`, `YANDEX_OAUTH_*`
- DataAgent: `DATA_AGENT_URL`, `DATA_AGENT_TIMEOUT`, `INTERNAL_API_*`
- reviews demo: `REVIEWS_SHEET_URL`

## DataAgent status

Current status:

- separate FastAPI node
- `/health`, `/chat`, `/systems/connect`, `/systems/{user_id}`
- Telegram integration via `/agent`, `/connect`, `/systems`
- persistent storage for connected systems
- internal email/calendar tools
- AI orchestrator for tool planning and final answer synthesis
- Browser Agent MVP via Playwright for connected systems
- `review_tool` for restaurant review reports from Google Sheets CSV

Not implemented yet:

- secure vault-level credentials storage
- production-grade browser orchestration and Telegram progress streaming
- stoplist and blanks monitoring tools
- scheduler and memory layer for the Big Brother orchestrator

## Notes

- The project currently uses a monorepo structure by design.
- Browser Agent requirements and fixes are tracked separately in `BROWSER_AGENT_FIXES.md` on the Desktop.
- The first business demo scenario is documented in `docs/DEMO_REVIEWS_SCENARIO.md`.
