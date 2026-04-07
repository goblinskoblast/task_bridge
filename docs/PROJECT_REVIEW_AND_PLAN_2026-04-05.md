# TaskBridge - Project Review and Development Plan

Date: 2026-04-05

## Reviewed sources

- codebase in `task_bridge-main`
- project docs in `docs/`
- analysis reports in `analysis_reports_2026-03-04/`
- notes and reports in `C:\Users\sakla\Desktop\task_bridge наработки и md шки`

## Executive summary

TaskBridge is already a real end-to-end product prototype, not a mock repository. The main user flow works at MVP level: Telegram message -> AI extraction -> pending confirmation -> task lifecycle -> Mini App management. Email intake and DataAgent are also present as working branches of functionality, but both remain uneven in maturity.

Current stage: late MVP / early alpha.

The main blockers before wider pilot usage are not missing screens, but reliability and security:

1. the public API has no real authentication and no ownership checks;
2. email credentials are stored and processed inconsistently with the documented security model;
3. startup/deployment paths are partially broken or contradictory;
4. Telegram task extraction still mixes nearby chat context in ways that can create incorrect tasks.

## Review findings

### Critical

1. Public API allows reading and mutating other users' data by passing arbitrary `user_id` or `account_id`.

Impact:
- any client can request someone else's tasks, comments, assignees, email accounts, email contents, and attachments;
- any client can update task status, add comments on behalf of another user, or edit/delete email accounts without a trusted identity layer.

Evidence:
- `webapp/app.py:485` - `GET /api/tasks/{task_id}` returns task data without permission checks
- `webapp/app.py:548` - `PATCH /api/tasks/{task_id}/status` trusts `user_id` from request
- `webapp/app.py:592` - `DELETE /api/tasks/{task_id}` deletes by id only
- `webapp/app.py:625` - `/api/users` relies on optional `current_user_id`
- `webapp/app.py:654` - insecure fallback returns all users when `current_user_id` is missing
- `webapp/app.py:785` - comment author is taken from request body
- `webapp/app.py:829` and `webapp/app.py:866` - assignee changes have no authorization layer
- `webapp/app.py:1147`, `webapp/app.py:1210`, `webapp/app.py:1276`, `webapp/app.py:1327`, `webapp/app.py:1369`, `webapp/app.py:1419` - email account and email message endpoints are controlled only by ids/query params
- `webapp/src/utils/telegram.js:8`, `webapp/src/utils/telegram.js:12`, `webapp/src/App.jsx:13`, `webapp/src/components/TasksApp.jsx:42`, `webapp/src/components/TaskDetail.jsx:85`, `webapp/src/components/TaskDetail.jsx:130`, `webapp/src/components/EmailAccounts.jsx:68` - frontend identity is driven by URL/local storage, not validated Telegram init data

2. Manual IMAP secrets are stored in plaintext form in the database model, while documentation claims encrypted storage.

Impact:
- compromise of the database leaks mailbox credentials;
- the security model described to stakeholders is not the one implemented in code;
- email module is hard to approve for any real pilot involving non-test mailboxes.

Evidence:
- `db/models.py:221` - `EmailAccount.imap_password = Column(Text, nullable=False)`
- `bot/email_handler.py:213` - IMAP login uses raw secret from `imap_password`
- `webapp/app.py:1253` and `webapp/app.py:1319` - manual password is saved directly
- `docs/EMAIL_INTEGRATION.md:59` - docs describe `imap_password_encrypted`
- `docs/EMAIL_INTEGRATION_PROGRESS.md:166` - docs say passwords are never stored in plaintext
- contrast: DataAgent credentials are stored as `encrypted_password` in `db/models.py:397`

3. Webhook mode in the main entrypoint is broken: the app sets a webhook and still starts polling in the same flow.

Impact:
- Telegram delivery mode becomes ambiguous and likely unstable in production;
- deployment debugging becomes harder because both webhook and polling are mixed.

Evidence:
- `main.py:114` - webhook is set
- `main.py:121` - Uvicorn server is started inside the same flow
- `main.py:125` - polling is started afterward anyway

### High

4. Several startup paths and imports are broken or stale.

Impact:
- clean startup is not reliable;
- onboarding and deployment are harder than necessary.

Evidence:
- `start_all.bat:29` and `start_all.sh:29` start `python bot/main.py`, but `bot/main.py` does not exist
- `main_bot_only.py:15` imports `bot.email_registration`, which does not exist
- `webapp/app.py:850` imports `from bot.main import bot`, but this module path is absent in the repo

5. Telegram task extraction still leaks nearby chat context into a created task.

Impact:
- one user's task can absorb phrases from adjacent messages;
- confidence in automatic task creation drops sharply in active group chats.

Evidence:
- `bot/handlers.py:25` - recent chat context is taken from previous messages
- `bot/handlers.py:868` and `bot/handlers.py:870` - group handler always passes this context into analysis
- `bot/ai_extractor.py:816` - fallback task builder appends `Контекст: {context_text}` to the description
- `bot/ai_extractor.py:1025` - fallback still runs even when AI extraction does not confirm a task

6. FastAPI creates background notification tasks using the current request DB session.

Impact:
- notification jobs can outlive the request lifecycle and try to use a stale SQLAlchemy session;
- intermittent production bugs are likely under load.

Evidence:
- `webapp/app.py:575` - status notification uses `asyncio.create_task(..., db=db)`
- `webapp/app.py:811` - comment notification uses `asyncio.create_task(..., db)`
- `webapp/app.py:853` - assignee notification also reuses request context
- `bot/notifications.py:31` and `bot/notifications.py:103` expect a live session object inside async notification functions

### Medium

7. Reviews scenario in DataAgent bypasses the sheet-based analytics path whenever a specific point is detected.

Impact:
- the documented "review report from Google Sheets" scenario does not run in many natural requests;
- output depends on slot resolution rather than product intent.

Evidence:
- `data_agent/scenario_engine.py:44-49`
- `data_agent/review_report.py` contains the sheet report implementation that is skipped in this branch

8. Review period parsing is much narrower than described in notes and demo expectations.

Impact:
- requests like "за прошлую неделю" or "за март" will not be interpreted correctly;
- demo quality may look inconsistent even when data exists.

Evidence:
- `data_agent/review_report.py:81-100` supports current month/current week only
- `data_agent/review_report.py:102-117` supports only explicit numeric date ranges

9. File attachments from Telegram can be assigned to the wrong task if the user has several active tasks.

Impact:
- evidence and documents may land in the wrong task card;
- mistakes are hard to detect later.

Evidence:
- `bot/handlers.py:963`
- `bot/handlers.py:998` - when several active tasks exist, the most recent one is selected automatically

10. Backend import hard-fails if the React build is absent.

Impact:
- local developer setup is brittle;
- API-only debugging is blocked until frontend assets are built.

Evidence:
- `webapp/app.py:268-283` raises `RuntimeError` if `webapp/dist` or `assets` are missing

11. Documentation is stale and diverges from the real implementation.

Impact:
- planning and stakeholder communication are based on outdated assumptions;
- the gap is especially large for email integration and readiness level.

Examples:
- `docs/EMAIL_INTEGRATION_PROGRESS.md` still describes API/UI as planned, but the repo already contains CRUD endpoints and frontend screens
- security claims in the docs do not match the current model implementation

## Strengths of the current codebase

- There is a real cross-module product, not a disconnected prototype.
- Core task lifecycle already exists: creation, status changes, assignees, comments, attachments, reminders.
- Email-to-task pipeline is partially functional, including account connection, polling, parsing, and task creation.
- DataAgent already has a meaningful structure: orchestration, system connections, browser tooling, scenario engine, and monitoring skeleton.
- The repository contains useful deployment and architecture notes that can be turned into a proper release process.

## Validation performed during review

- `python -m compileall bot data_agent db email_integration webapp main.py main_bot_only.py config.py`
  - passed syntax compilation
- `npm run build` in `webapp`
  - failed in the current environment because local frontend dependencies were not installed yet; `vite` is declared in `webapp/package.json`
- `python -m pytest`
  - unavailable in the current environment because `pytest` is not installed and not listed in `requirements.txt`
- import smoke checks
  - local environment has dependency mismatches: `aiogram` vs installed `pydantic`, and missing `sqlalchemy` for some imports

This means the repo has both code-level issues and environment/setup drift. The review findings above focus only on the code issues that remain even after a correct environment setup.

## Recommended development plan

### Phase 0 - Stabilization and security baseline

Goal: make the project safe enough for continued pilot work.

Tasks:
- validate Telegram Mini App `initData` on the backend
- stop trusting `user_id` from query/body as identity
- add authorization checks for task, comment, assignee, and email endpoints
- replace plaintext IMAP password storage with encrypted storage
- fix `main.py` startup mode separation: polling vs webhook
- fix broken imports and startup scripts
- add one documented local startup path and one documented production path

Expected result:
- the system becomes safe for internal pilot usage and reproducible to run

### Phase 1 - Task core reliability

Goal: make task creation trustworthy in active chats.

Tasks:
- redesign context-passing in Telegram extraction
- forbid fallback from injecting unrelated context into task descriptions
- improve multi-message and reply-chain handling
- make attachment binding explicit when several active tasks exist
- split `bot/handlers.py` into smaller modules by domain
- cover task creation/status/comment flows with smoke tests

Expected result:
- fewer false-positive or merged tasks, easier maintenance of the bot layer

### Phase 2 - Complete the email module

Goal: move email from "interesting branch" to "usable feature".

Tasks:
- finish secure credential handling end-to-end
- enforce account ownership checks for every email endpoint
- improve parsing/error tracking for failed emails
- make email message to task linkage visible and reliable in UI
- add operational logs and a manual resync flow
- refresh outdated email docs to reflect real behavior

Expected result:
- email-to-task becomes pilot-ready and supportable

### Phase 3 - Harden DataAgent for the pilot scenario

Goal: turn the restaurant demo path into a dependable scenario.

Tasks:
- align `scenario_engine.py` with the intended review-report source of truth
- expand period parsing: previous week, month names, arbitrary intervals
- decide which scenarios use browser automation and which use structured data
- finish monitor coverage for agreed report types
- standardize secret handling across DataAgent and email modules
- add scenario-level tests for Italian Pizza flows

Expected result:
- demo scenarios become predictable and repeatable, not heuristic-only

### Phase 4 - Beta preparation

Goal: move from alpha toward controlled beta.

Tasks:
- roles and permissions for manager/executor/admin
- audit log for critical actions
- CI checks: lint, smoke tests, frontend build, backend import smoke
- health checks and better runtime logging
- observability for background jobs and email processing
- cleanup of outdated docs and creation of a single current product status document

Expected result:
- the project can support a broader pilot without depending on tribal knowledge

## Suggested execution order

1. Phase 0 immediately
2. Phase 1 next, in parallel with selected fixes from Phase 2
3. Phase 3 only after auth/security and task-core reliability are stable
4. Phase 4 after the team confirms the pilot scope

## Bottom line

TaskBridge already has strong product substance. The right next step is not adding many new features at once, but closing the structural gaps that currently limit trust: auth, secure storage, startup consistency, and extraction reliability. Once those are addressed, the existing functionality is strong enough to justify finishing email and DataAgent scenarios rather than rebuilding the product from scratch.
