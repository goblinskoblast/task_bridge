# TaskBridge с OpenClaw - Руководство по деплою

Это краткое руководство по деплою TaskBridge с интегрированным OpenClaw.

---

## 🚀 Быстрый старт

### Вариант 1: Локальная разработка

```bash
# 1. Настройте .env
cp .env.example .env
# Отредактируйте и добавьте BOT_TOKEN и OPENAI_API_KEY

# 2. Запустите через Docker Compose
docker-compose up -d

# 3. Проверьте логи
docker-compose logs -f
```

**Готово!** OpenClaw и TaskBridge запущены локально.

---

### Вариант 2: Production деплой (один сервер)

На вашем Linux сервере:

```bash
# 1. Скачайте и запустите setup скрипт
wget https://raw.githubusercontent.com/your-repo/taskbridge/main/setup_docker_production.sh
chmod +x setup_docker_production.sh
sudo ./setup_docker_production.sh

# Скрипт автоматически:
# - Установит Docker и Docker Compose
# - Клонирует репозиторий
# - Создаст .env файл
# - Запустит OpenClaw и TaskBridge
```

**Готово!** Оба сервиса на одном сервере.

---

### Вариант 3: Тестирование с ngrok (OpenClaw на вашем компе)

**На вашем компьютере (Windows):**

1. Запустите скрипт:
```bash
setup_ngrok_tunnel.bat
```

2. Скопируйте ngrok URL (например: `https://abc123.ngrok.io`)

**На сервере:**

```bash
# Установите OPENCLAW_BASE_URL в .env
nano .env
# OPENCLAW_BASE_URL=https://abc123.ngrok.io

# Закомментируйте openclaw в docker-compose.yml
nano docker-compose.yml

# Запустите
docker-compose up -d --build
```

**Готово!** TaskBridge на сервере использует OpenClaw на вашем компе.

---

## 📚 Подробная документация

- **[docs/DEPLOYMENT_OPENCLAW.md](docs/DEPLOYMENT_OPENCLAW.md)** - Все варианты деплоя с подробными инструкциями
- **[docs/NGROK_QUICK_START.md](docs/NGROK_QUICK_START.md)** - Быстрый старт с ngrok для тестирования

---

## 🔧 Конфигурация

### Основные переменные .env

```env
# Telegram
BOT_TOKEN=your_bot_token

# AI Provider
AI_PROVIDER=openclaw

# OpenClaw
OPENCLAW_BASE_URL=http://openclaw:3000  # или ngrok URL
OPENCLAW_MODEL=openai/gpt-4o
OPENAI_API_KEY=your_openai_key  # для OpenClaw backend
```

### Переключение между локальным и удаленным OpenClaw

**Локальная разработка (вне Docker):**
```env
OPENCLAW_BASE_URL=http://localhost:3000
```

**Docker Compose (оба на одном сервере):**
```env
OPENCLAW_BASE_URL=http://openclaw:3000
```

**ngrok или удаленный сервер:**
```env
OPENCLAW_BASE_URL=https://abc123.ngrok.io
OPENCLAW_TIMEOUT=60  # увеличьте для удаленных запросов
```

---

## 🎯 Сравнение вариантов

| Метод | Сложность | Production | Когда использовать |
|-------|-----------|------------|-------------------|
| Docker Compose (локально) | ⭐ Легко | ✅ Да | Разработка, небольшие проекты |
| ngrok | ⭐⭐ Средне | ❌ Нет | Тестирование на сервере |
| Отдельный сервер | ⭐⭐⭐ Сложно | ✅ Да | Высокая нагрузка, масштабирование |

---

## 🔍 Проверка работоспособности

### 1. Проверьте что OpenClaw запущен

```bash
# Локально
curl http://localhost:3000/health

# В Docker
docker exec taskbridge_openclaw curl http://localhost:3000/health
```

### 2. Проверьте логи TaskBridge

```bash
docker-compose logs -f taskbridge
```

Должно быть:
```
INFO - Using OpenClaw AI provider
INFO - OpenClawProvider initialized: http://openclaw:3000
```

### 3. Отправьте тестовое сообщение

В Telegram:
```
@username сделай отчет до завтра
```

Проверьте логи - должно быть:
```
INFO - Calling AI API to analyze message...
INFO - AI response: {...}
```

---

## 🐛 Troubleshooting

### OpenClaw не отвечает

```bash
# Проверьте статус контейнера
docker ps | grep openclaw

# Проверьте логи
docker-compose logs openclaw

# Перезапустите
docker-compose restart openclaw
```

### Connection refused

1. Проверьте `OPENCLAW_BASE_URL` в .env
2. Для Docker используйте `http://openclaw:3000` (не localhost!)
3. Для локальной разработки используйте `http://localhost:3000`

### Медленные ответы

1. Увеличьте timeout:
   ```env
   OPENCLAW_TIMEOUT=60
   ```

2. Проверьте сетевую латентность (для ngrok/удаленных серверов)

---

## 📦 Структура проекта

```
taskbridge/
├── bot/
│   ├── openclaw_client.py      # HTTP клиент для OpenClaw
│   ├── ai_provider.py          # Абстракция AI провайдеров
│   ├── ai_extractor.py         # Извлечение задач (использует OpenClaw)
│   ├── support_ai.py           # Support чат (использует OpenClaw)
│   └── support_handlers.py     # Vision API (использует OpenClaw)
├── docs/
│   ├── DEPLOYMENT_OPENCLAW.md  # Подробный гайд по деплою
│   └── NGROK_QUICK_START.md    # Быстрый старт с ngrok
├── docker-compose.yml          # OpenClaw + TaskBridge
├── .env                        # Конфигурация
├── setup_ngrok_tunnel.bat      # Windows скрипт для ngrok
└── setup_docker_production.sh  # Linux setup скрипт
```

---

## 🔄 Обновление проекта

```bash
# На сервере
cd taskbridge
git pull
docker-compose down
docker-compose up -d --build
docker-compose logs -f
```

---

## ❓ FAQ

**Q: Можно ли использовать другие AI модели?**
A: Да! Настройте `OPENCLAW_MODEL`:
- `openai/gpt-4o` (рекомендуется, vision support)
- `openai/gpt-4o-mini` (дешевле)
- `anthropic/claude-sonnet-3.5` (нужен Anthropic ключ)

**Q: Как переключиться обратно на OpenAI?**
A: Измените в .env:
```env
AI_PROVIDER=openai
OPENAI_API_KEY=your_key
```

**Q: Безопасно ли expose OpenClaw в интернет?**
A: Для production используйте:
- Вариант 1 (Docker Compose) - OpenClaw не expose наружу
- Если нужен удаленный доступ - используйте HTTPS + authentication (см. DEPLOYMENT_OPENCLAW.md)

**Q: Сколько стоит OpenClaw?**
A: OpenClaw бесплатен (open-source), но нужен OpenAI/Anthropic API ключ для backend модели.

**Q: Один OpenClaw для нескольких ботов?**
A: Да! Просто настройте одинаковый `OPENCLAW_BASE_URL` на всех ботах.

---

## 📞 Поддержка

Если возникли проблемы:

1. Проверьте [docs/DEPLOYMENT_OPENCLAW.md](docs/DEPLOYMENT_OPENCLAW.md) - подробный troubleshooting
2. Проверьте логи: `docker-compose logs -f`
3. Создайте issue на GitHub

---

## 🎉 Готово!

Ваш TaskBridge с OpenClaw готов к работе!

**Следующие шаги:**
- Добавьте бота в Telegram группу
- Отправьте тестовую задачу
- Настройте email интеграцию (опционально)
- Настройте напоминания (опционально)

Подробности в основном [README.md](README.md).
