# TaskBridge

TaskBridge is a Telegram-first task management service with:

- task extraction from Telegram chats
- task extraction from connected email accounts
- Telegram Mini App for task management
- OpenClaw-based AI routing
- calendar sync for tasks with due dates
- DataAgent for restaurant reports, saved points, and monitoring
- restaurant scenarios for stop-list, blanks, and reviews analytics

## Current modules

- `bot/` - Telegram bot logic, task extraction, notifications, reminders
- `webapp/` - FastAPI API and Mini App frontend
- `db/` - database models and DB helpers
- `email_integration/` - email encryption and IMAP helpers
- `data_agent/` - separate DataAgent service node with Browser Agent MVP and modular tools
- `docs/` - deployment, SDD, and integration documentation

## Telegram UX

The primary user path is intentionally simple:

- `/start` opens the main reply buttons: task panel, agent, support, and help.
- The agent menu is the main place to connect systems, add points, and inspect active monitoring.
- Reports and monitor settings should be requested in plain text, for example:
  - `пришли стоп-лист по Сухой Лог, Белинского 40`
  - `покажи бланки по всем добавленным точкам`
  - `присылай бланки по Сухой Лог, Белинского 40 каждые 3 часа`
  - `покажи мониторинги`

Legacy slash commands are kept only for compatibility and are not shown in the Telegram command menu.

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
- `/health`, `/chat`, `/systems/connect`, `/systems/{user_id}`, `/monitors/{user_id}`
- Telegram integration through the agent menu and plain-text requests
- persistent storage for connected systems
- internal email/calendar tools
- AI orchestrator for tool planning and final answer synthesis
- Playwright adapter for Italian Pizza blanks
- public Italian Pizza stop-list adapter
- reviews reports from configured review sources
- scheduled monitoring for stop-list, blanks, and reviews

Not implemented yet:

- secure vault-level credentials storage
- broader production-grade browser orchestration beyond current restaurant flows
- richer operator dashboards and adoption metrics

## Notes

- The project currently uses a monorepo structure by design.
- Browser Agent requirements and fixes are tracked separately in `BROWSER_AGENT_FIXES.md` on the Desktop.
- The first business demo scenario is documented in `docs/DEMO_REVIEWS_SCENARIO.md`.
