# DataAgent Phase 2

## Что добавлено
- Постоянное хранение подключённых внешних систем в БД.
- Логирование запросов пользователя в DataAgent.
- Внутренние контракты для почты и календаря через Internal API.
- DB-backed `data_agent` service вместо phase-1 in-memory заглушки.

## Новые модели
- `DataAgentSystem`
- `DataAgentRequestLog`

## Internal API
- `GET /api/internal/data-agent/email/summary`
- `GET /api/internal/data-agent/calendar/events`

## Новые переменные окружения
- `INTERNAL_API_URL`
- `INTERNAL_API_TOKEN`

## Что умеет phase 2
- сохранять подключение внешней системы пользователя;
- возвращать список подключённых систем;
- логировать каждый запрос `chat`;
- получать краткую сводку по почте и дедлайнам задач через internal API.

## Что ещё не входит в phase 2
- OpenClaw orchestrator;
- Browser Tool;
- secure vault для внешних секретов;
- полноценные internal tools с action-операциями.

## Следующий этап
Phase 3:
- OpenClaw orchestrator;
- tool routing;
- интеграция internal email/calendar tools в реальный agent loop.
