# DataAgent Runtime V2

## Goal

Replace fragile message-by-message routing with a session-centered runtime that preserves state and executes tasks through scenario-specific adapters.

## Principles

1. LLM is used for interpretation and synthesis, not for primary browser execution.
2. Session state is structured and persisted.
3. Scenario execution is deterministic where the target system is known.
4. Site adapters are first-class modules, not generic browser prompts.
5. Missing data is handled explicitly.

## Runtime Layers

### 1. Session Layer
Stores per-user state:
- active scenario
- structured slots
- last selected tools
- last user message
- last answer
- runtime status

DB entity: `DataAgentSession`

### 2. Interpreter Layer
Hybrid routing:
- rule-based high-confidence scenario detection
- LLM-based extraction fallback
- slot merge with previous session state

Current scenarios:
- `general`
- `browser_report`
- `reviews_report`
- `stoplist_report`
- `blanks_report`

### 3. Scenario Executor Layer
Service routes to a concrete tool based on scenario:
- `reviews_report` -> `review_tool`
- `stoplist_report` -> `stoplist_tool`
- `blanks_report` -> `blanks_tool`
- `browser_report` -> `browser_tool`

### 4. Adapter Layer
Scenario tools must be migrated toward explicit adapters:
- `ItalianPizzaPublicAdapter`
- `ItalianPizzaPortalAdapter`

This layer should own selectors, modal flows, validation, retries, and success detection.

## Why The Previous Design Failed

The previous service had three systemic problems:
- every message was replanned almost from scratch
- state was inferred indirectly from request logs instead of persisted as agent state
- browser work was too generic for site-specific flows

This caused:
- broken follow-up handling
- unstable point and period extraction
- heavy dependence on prompt quality for deterministic browser tasks

## Migration Plan

### Stage 1
Done in this refactor:
- add `DataAgentSession`
- add `agent_runtime.py`
- route `service.chat()` through session-aware decision making
- preserve point and period slots across turns

### Stage 2
Next implementation step:
- move `stoplist_tool` into a dedicated public-site adapter
- move `blanks_tool` into a dedicated portal adapter
- add adapter-level structured results

### Stage 3
Then:
- add monitor scenario creation/update via chat
- persist monitor intent separately from one-off reports
- add explicit confirmation only for risky or destructive actions

## Constraints

- Keep current public API stable: `/chat`, `/systems/connect`, `/systems/{user_id}`
- Keep existing tools callable during migration
- Do not block business scenarios on a generic agent loop
