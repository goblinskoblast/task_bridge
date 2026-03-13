# Процесс SDD

## 1. Discovery
- Формулируем проблему, контекст и границы.
- Определяем затронутые модули, API и данные.

## 2. Spec
- Создаем `SPEC-XXXX-*.md` по шаблону.
- Фиксируем goals, non-goals, requirements, risks, acceptance criteria.

## 3. Review
- Спек проходит ревью до начала разработки.
- Неоднозначности закрываются до реализации.

## 4. Tasks
- Создаем task-лист `docs/sdd/tasks/SPEC-XXXX-*.tasks.md`.
- Каждый таск связан с конкретным пунктом спека.

## 5. Implementation
- Код и PR ссылаются на `SPEC-XXXX`.
- Отклонения от спека документируются и согласуются.

## 6. Verification
- Проверяем acceptance criteria из спека.
- Отмечаем статус в task-листе (done/partial/blocked).

## Definition of Done
- Спек согласован.
- Обязательные таски закрыты.
- Acceptance criteria подтверждены.
- Архитектурные решения отражены в ADR (если применимо).
