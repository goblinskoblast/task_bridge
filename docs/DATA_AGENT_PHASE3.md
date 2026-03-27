# DataAgent Phase 3

## Что добавлено
- Отдельный orchestrator слой для `data_agent`.
- AI-based tool planning через существующий provider abstraction (`OpenClaw` или `OpenAI`).
- Синтез финального ответа поверх результатов internal tools.
- Fallback routing и fallback answer, если AI недоступен.

## Новые файлы
- `data_agent/orchestrator.py`
- `data_agent/prompts.py`

## Что изменено
- `data_agent/service.py`
  - `/chat` теперь работает через orchestrator plan -> tool execution -> answer synthesis.
  - `health.mode` переключён на `phase_3_orchestrated`.

## Логика phase 3
1. Пользователь отправляет запрос в `data_agent`.
2. Orchestrator определяет набор инструментов:
   - `email_tool`
   - `calendar_tool`
   - `browser_tool`
   - `orchestrator`
3. Service собирает результаты internal tools.
4. Orchestrator формирует финальный ответ на русском языке.

## Ограничения phase 3
- `browser_tool` пока не выполняет реальную browser automation.
- Внешние системы пока только участвуют в plan/answer layer.
- Реальный browser execution переносится на phase 4.
