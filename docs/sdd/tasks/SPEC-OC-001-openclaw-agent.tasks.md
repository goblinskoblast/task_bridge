# TASKS for SPEC-OC-001: OpenClaw Agent Integration

## Status legend
- [ ] todo
- [~] in progress
- [x] done
- [!] blocked

## A. Security baseline
- [ ] A1. Добавить Telegram `initData` verification на backend.
- [ ] A2. Убрать доверие к `user_id` из query string.
- [ ] A3. Добавить server-side auth dependency для `/api/*`.
- [ ] A4. Внедрить шифрование `imap_password` + миграцию существующих записей.

## B. AI contracts
- [ ] B1. Ввести pydantic-схему `TaskExtractionV1`.
- [ ] B2. Валидировать ответы OpenClaw/OpenAI перед DB write.
- [ ] B3. Добавить конфиг для retry/fallback policy.

## C. Runtime stability
- [ ] C1. Не передавать request-scoped DB session в фоновые задачи.
- [ ] C2. Исправить источник bot instance для уведомлений из webapp.
- [ ] C3. Исправить runtime-ошибки импортов в webapp API.

## D. Observability
- [ ] D1. Добавить таблицу/модель `ai_audit_logs`.
- [ ] D2. Добавить structured logs и базовые AI-метрики.

## Verification
- [ ] V1. Подмена `user_id` не дает доступа к чужим данным (401/403).
- [ ] V2. Невалидный AI JSON не ломает pipeline.
- [ ] V3. Проверка отсутствия plaintext-паролей в БД.
- [ ] V4. Smoke test: polling + webapp + email flow.
