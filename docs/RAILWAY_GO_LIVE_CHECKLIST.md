# Railway Go-Live Checklist (TaskBridge)

This checklist is optimized for your current repository and Telegram WebApp requirements.

## Target architecture
- Service 1: `taskbridge-app` (this repo, Dockerfile)
- Service 2: `openclaw` (separate Railway service)
- Service 3: `postgres` (Railway PostgreSQL)

## 0) Preflight
- [ ] Repo pushed to `https://github.com/goblinskoblast/task_bridge.git`
- [ ] Telegram bot token is valid
- [ ] You have OpenAI key (for fallback or temporary primary mode)

## 1) Create Railway project
- [ ] New Railway project
- [ ] Add PostgreSQL plugin
- [ ] Add service from GitHub repo: `task_bridge`
- [ ] Ensure service uses project `Dockerfile`

## 2) Configure `taskbridge-app` env
Set these variables in Railway service:

```env
BOT_TOKEN=<your_bot_token>
USE_WEBHOOK=True
WEBHOOK_PATH=/webhook

# Railway public URL of taskbridge-app
WEBHOOK_URL=https://<taskbridge-domain>.up.railway.app
WEB_APP_DOMAIN=https://<taskbridge-domain>.up.railway.app
MINI_APP_URL=https://<taskbridge-domain>.up.railway.app/webapp/index.html

HOST=0.0.0.0
PORT=8000

# Database from Railway Postgres
DATABASE_URL=<railway_postgres_url>

# AI settings (recommended safe start)
AI_PROVIDER=openai
OPENAI_API_KEY=<your_openai_api_key>
OPENAI_MODEL=gpt-4o-mini

# OpenClaw SDD enforcement (kept enabled for when you switch provider)
OPENCLAW_ENFORCE_SDD_SPEC=True
OPENCLAW_SDD_SPEC_PATH=docs/sdd/specs/SPEC-OC-001-openclaw-agent.md
OPENCLAW_SDD_MAX_CHARS=24000
```

## 3) Deploy and verify `taskbridge-app`
- [ ] Deploy completed (green)
- [ ] `GET /health` returns `{"status":"ok"...}`
- [ ] In logs there is no `TelegramConflictError`
- [ ] `/start` works in Telegram
- [ ] `/panel` opens WebApp (HTTPS only)

## 4) Add OpenClaw service (optional in phase 1)
- [ ] Create separate Railway service `openclaw`
- [ ] Expose correct API endpoint for TaskBridge (`/v1/responses`)
- [ ] Verify from inside `taskbridge-app` logs that OpenClaw URL is reachable

Then switch env in `taskbridge-app`:

```env
AI_PROVIDER=openclaw
OPENCLAW_BASE_URL=<openclaw_internal_or_public_url>
OPENCLAW_MODEL=openai/gpt-4o
OPENCLAW_TIMEOUT=60
OPENAI_API_KEY=<same_key_for_fallback_if_needed>
```

## 5) OpenClaw readiness criteria
Switch to `AI_PROVIDER=openclaw` only if all are true:
- [ ] OpenClaw responds to `POST /v1/responses`
- [ ] TaskBridge logs do NOT show `Cannot connect to host ...`
- [ ] Support flow returns AI response

## 6) Final smoke test
- [ ] `/start` and `/panel` work
- [ ] Task list opens in WebApp
- [ ] Status update/comment flows work
- [ ] AI support reply works
- [ ] No critical errors in Railway logs for 15+ minutes

## Known gotchas
- Telegram WebApp rejects non-HTTPS URLs.
- `WEBHOOK_URL` and `WEB_APP_DOMAIN` must be real public HTTPS domain.
- If OpenClaw is unstable, keep `AI_PROVIDER=openai` temporarily and return to OpenClaw after endpoint verification.
