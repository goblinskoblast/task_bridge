# Unified Task Extraction Architecture

## Purpose

This document defines the target architecture for task extraction in TaskBridge.
The goal is to keep a single extraction core for all inbound channels and avoid divergence between Telegram and Email logic.

## Design Principle

Task understanding must be unified.
Telegram and Email are different sources of context, but not different kinds of reasoning.
The system should therefore use:

- one extraction core
- one AI spec / OpenClaw instruction set
- one deterministic fallback layer
- separate source adapters only for data collection and normalization

## High-Level Flow

1. Source adapter receives inbound communication.
2. Adapter normalizes the input into a common extraction package.
3. Unified extraction core evaluates the package.
4. AI extraction runs first.
5. Deterministic fallback rules run if AI returns `has_task=false`, malformed JSON, or no response.
6. The result is normalized into one task schema.
7. Channel-specific post-processing creates `PendingTask`, `Task`, or a confirmation request.

## Common Extraction Package

All channels should be reduced to a normalized structure:

```json
{
  "source": "telegram | email",
  "current_text": "trigger message or email body",
  "subject": "optional subject",
  "context_messages": [
    {
      "sender": "name or username",
      "date": "YYYY-MM-DD HH:MM:SS",
      "text": "context fragment"
    }
  ],
  "attachments_text": "optional extracted text from files",
  "participants": ["optional actor hints"]
}
```

## Source Adapters

### Telegram Adapter

Responsibilities:

- store incoming message in DB
- gather recent chat context
- pass the current message as the trigger
- include sender / thread metadata when available

Important rule:

- the current message must trigger task creation
- context may only complete missing details

### Email Adapter

Responsibilities:

- gather subject, body, quoted thread, and attachment text
- normalize extracted attachment text
- pass the entire message package into the same extraction core

Important rule:

- email subject and body are both first-class signals
- attachment text may refine title, deliverable, or deadline

## Unified Extraction Core

### AI Layer

The AI layer must operate on the same schema and the same extraction rules for both Telegram and Email.

Core expectations:

- detect explicit tasks
- detect indirect tasks
- resolve references using context
- compress verbose formulations into a short title
- extract due date and priority when possible
- extract assignee usernames or plain names when available

### Deterministic Fallback Layer

Fallback is required because obvious tasks cannot be dropped just because the model returned `has_task=false`.

Fallback must recognize imperative and operational patterns such as:

- `пришлите`
- `отправьте`
- `подготовьте`
- `проверьте`
- `согласуйте`
- `заполните`
- `обновите`
- `тебе нужно`
- `вам нужно`
- `прошу`
- `нужно`
- `надо`
- `please send`
- `prepare`
- `review`
- `check`
- `fill`
- `update`

Fallback policy:

- if there is a directed imperative or expected deliverable, create a task candidate
- if due date is missing, do not reject the task
- if assignee is missing, leave it empty and send the task to pending confirmation
- if only part of the data is known, preserve the uncertainty instead of dropping the task

## Imperative Detection Policy

The extractor should treat the following as valid task signals:

- direct commands
- polite requests
- operational instructions
- deliverable-oriented questions
- indirect commitments tied to an expected result

Examples:

- `Пришлите файлы CSV, TXT, MD.`
- `Подготовьте архитектуру проекта до субботы.`
- `Нужно выставить метрики по проекту.`
- `Вам хватит двух дней на подготовку отчета?`
- `Please send the updated contract by Friday.`

These are all task candidates because they imply an expected action or result.

## Due Date Resolution

The unified layer should resolve both explicit and relative dates.

Minimum supported relative patterns:

- `сегодня`
- `завтра`
- `через N дней`
- `за N дней`
- `хватит двух дней`
- `до субботы`
- `до этой субботы`
- `к пятнице`

If the exact time is unknown, the system may normalize to end-of-day business time.

## Title Generation Rules

The title should be concise and action-oriented.

Rules:

- remove greetings
- remove direct address prefixes
- remove filler words
- keep the core action and object
- if email subject already matches the task, prefer the subject

Examples:

- `владислав нужно выставить метрики по проекту, вам хватит 2-х дней?`
  -> `Выставить метрики по проекту`
- `Пришлите файлы CSV, TXT, MD.`
  -> `Прислать файлы CSV, TXT, MD`
- subject `Создание архитектуры проекта`
  -> `Создание архитектуры проекта`

## Output Contract

The unified extraction core returns one normalized payload:

```json
{
  "has_task": true,
  "task": {
    "title": "short task title",
    "description": "full actionable description",
    "assignee_usernames": [],
    "due_date": "YYYY-MM-DD HH:MM:SS or null",
    "priority": "low | normal | high | urgent"
  }
}
```

Additional internal normalization may populate `due_date_parsed`.

## Channel Post-Processing

The output of the extractor should remain channel-agnostic.
Channel-specific behavior happens after extraction.

### Telegram Post-Processing

- create `PendingTask`
- if assignee missing, ask in group chat
- if assignee known, send confirmation to the user

### Email Post-Processing

- create `Task` or `PendingTask` depending on account settings
- bind email message and attachments to the task
- keep extraction history for debugging

## OpenClaw Alignment

OpenClaw should use one extraction spec for both Telegram and Email.
The spec should describe:

- what counts as a task
- how to use context
- how to treat indirect requests
- how to compress titles
- how to handle uncertain assignee / due date fields

This keeps behavior stable across channels and reduces prompt drift.

## Debugging Requirements

For every analyzed item, logs should make it possible to answer:

- what package was sent to the extraction core
- whether AI returned a valid task
- whether fallback was used
- why a candidate was rejected
- what final normalized task payload was produced

## Future Extensions

Recommended next steps:

1. Move extraction package creation into dedicated adapter classes.
2. Store extraction traces for model QA.
3. Add confidence score and fallback reason.
4. Add attachment-type specific parsers for DOCX, PDF, XLSX.
5. Add a review queue for low-confidence extracted tasks.
