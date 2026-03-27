# DataAgent Phase 4

## Что добавлено
- Browser Agent MVP для `data_agent`.
- Реальный Playwright-based browser execution слой.
- Generic login flow через common selectors.
- Agentic navigation loop с AI action planning и fallback.
- Safe wait без `networkidle`.
- Координатные клики с fallback на selector и JS click.
- Детектор зависшей страницы по хэшам скриншотов.
- Поддержка скачивания Excel и парсинга `.xlsx` / `.xls`.

## Новые файлы
- `data_agent/browser_agent.py`

## Что изменено
- `data_agent/service.py`
  - `browser_tool` теперь реально пытается открыть подключённую систему.
- `data_agent/orchestrator.py`
  - fallback answer учитывает успешный результат browser tool.
- `requirements.txt`
  - добавлены `playwright` и `Pillow`

## Ограничения текущего MVP
- Browser Agent берёт первую активную подключённую систему пользователя.
- Progress callback в Telegram пока не прокинут через `data_agent_client`.
- Для production потребуется `playwright install chromium` на deploy target.
