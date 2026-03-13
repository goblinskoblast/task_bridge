# SPEC-OC-001: OpenClaw Agent Integration for TaskBridge

## 1. Контекст
TaskBridge использует AI для извлечения задач из Telegram и email, а также для поддержки пользователей.
Нужен единый специфицированный слой OpenClaw-агента с устойчивым контрактом результата.

## 2. Проблема
- Нет формально закрепленного контракта AI-ответов.
- Нестабильный формат ответа модели ведет к ошибкам парсинга.
- Есть риски безопасности вокруг идентификации пользователя в webapp.
- Нужна управляемая стратегия retry/fallback и наблюдаемость.

## 3. Goals
1. Унифицировать AI-вызовы через provider layer.
2. Ввести строгую валидацию AI-ответов перед DB write.
3. Зафиксировать retry/fallback-политику.
4. Снизить риски утечки данных и неправильной авторизации.

## 4. Non-goals
1. Обучение собственной модели.
2. Полная переработка UX webapp.
3. Полная миграция legacy-логики в один релиз.

## 5. Functional Requirements
1. Агент поддерживает режимы:
- `analyze_message`
- `analyze_email`
- `get_support_response`
- `analyze_image`

2. Для task extraction результат приводится к схеме `TaskExtractionV1`:
- `is_task: bool`
- `title: str`
- `description: str | null`
- `assignee_usernames: string[]`
- `due_date: ISO8601 | null`
- `priority: low|normal|high|urgent`
- `category: string | null`
- `confidence: float (0..1)`

3. При ошибке OpenClaw:
- retry с exponential backoff;
- fallback на OpenAI только при явном флаге (`AI_PROVIDER_FALLBACK=true`).

4. Невалидный AI-ответ:
- не используется как финальное структурированное решение;
- логируется как validation failure.

## 6. Security Requirements
1. WebApp identity:
- backend валидирует Telegram `initData` подпись;
- `user_id` в query не считается доверенным источником identity.

2. Email credentials:
- `imap_password` хранится только в зашифрованном виде (at rest);
- пароли не выводятся в логи/ошибки.

3. Secrets hygiene:
- токены, ключи и пароли исключаются из payload в LLM и из логов.

## 7. API / Data Contracts
1. Внутренний контракт `TaskExtractionV1` обязателен перед записью в `tasks`.
2. Добавляется аудит AI-вызовов (`ai_audit_logs`):
- `id`, `source_type`, `provider`, `model`, `latency_ms`, `success`, `validation_error`, `created_at`.

## 8. Observability
1. Метрики:
- `ai_requests_total`
- `ai_failures_total`
- `ai_validation_failures_total`
- `ai_latency_ms_p95`

2. Structured logging:
- `request_id`, `source_type`, `provider`, `model`, `result_status`.

## 9. Rollout Plan
1. Phase 1: shadow mode (без влияния на финальное решение).
2. Phase 2: частичное включение (20% релевантного трафика).
3. Phase 3: full rollout + policy для fallback.

## 10. Acceptance Criteria
1. >= 95% AI-ответов валидируются по `TaskExtractionV1`.
2. Webapp API не доверяет `user_id` из query без проверки подписи Telegram.
3. `imap_password` не хранится в plaintext.
4. Ошибки AI не приводят к падению polling/webapp.
5. P95 latency AI-запроса <= 4s при штатной нагрузке.

## 11. Risks
1. Ломающее изменение формата ответа OpenClaw.
2. Рост latency из-за дополнительной валидации и аудита.
3. Ошибки миграции при переходе на шифрование существующих email-паролей.

## 12. Open Questions
1. Нужен ли fallback на OpenAI по умолчанию в production?
2. Нужен ли порог confidence для авто-создания задач?
3. Нужен ли отдельный feature flag для email extraction?
