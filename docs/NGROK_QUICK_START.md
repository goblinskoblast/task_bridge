# Быстрый старт: Удаленное тестирование с ngrok

Этот гайд покажет как протестировать TaskBridge на удаленном сервере, используя OpenClaw на вашем локальном компьютере.

---

## Что нужно

1. ✅ OpenClaw запущен на вашем компьютере (Windows)
2. ✅ Удаленный сервер с Linux (VPS, DigitalOcean, AWS, etc.)
3. ✅ ngrok аккаунт (бесплатный)

---

## Шаг 1: Запустите OpenClaw локально

На вашем компьютере (Windows):

```bash
cd C:\openclaws
docker-compose up -d

# Проверьте что работает
curl http://localhost:3000/health
```

---

## Шаг 2: Установите и настройте ngrok

### 2.1 Скачайте ngrok

Windows: https://ngrok.com/download

Или через PowerShell:
```powershell
choco install ngrok
```

### 2.2 Зарегистрируйтесь на ngrok.com

1. Создайте бесплатный аккаунт на https://ngrok.com/
2. Получите свой authtoken: https://dashboard.ngrok.com/get-started/your-authtoken

### 2.3 Настройте authtoken

```bash
ngrok config add-authtoken YOUR_AUTHTOKEN
```

### 2.4 Запустите ngrok tunnel

```bash
ngrok http 3000
```

Вы увидите:
```
Session Status                online
Account                       your-email@example.com
Forwarding                    https://abc123.ngrok.io -> http://localhost:3000
```

**⚠️ ВАЖНО:** Скопируйте URL `https://abc123.ngrok.io` - это публичный адрес вашего OpenClaw!

---

## Шаг 3: Деплой TaskBridge на сервер

### 3.1 SSH на сервер

```bash
ssh root@your-server-ip
```

### 3.2 Установите Docker

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
apt install docker-compose -y
```

### 3.3 Клонируйте репозиторий

```bash
git clone https://github.com/your-username/taskbridge.git
cd taskbridge
```

### 3.4 Настройте .env для ngrok

```bash
nano .env
```

Установите следующие переменные:

```env
# Telegram Bot
BOT_TOKEN=8082995988:AAHvzDG4Y2v-yQXqXoQOryVEOg4eEYrKiqo

# AI Provider - используем OpenClaw через ngrok
AI_PROVIDER=openclaw
OPENCLAW_BASE_URL=https://abc123.ngrok.io  # <<<< Ваш ngrok URL!
OPENCLAW_MODEL=openai/gpt-4o
OPENCLAW_TIMEOUT=60  # Увеличен для удаленного соединения

# Database
DATABASE_URL=sqlite:///./data/taskbridge.db

# Server
PORT=8000
USE_WEBHOOK=False
```

**⚠️ Важно:** Замените `https://abc123.ngrok.io` на ваш реальный ngrok URL!

### 3.5 Запустите только TaskBridge (без OpenClaw)

Измените `docker-compose.yml` чтобы не запускать OpenClaw:

```bash
nano docker-compose.yml
```

Закомментируйте секцию `openclaw` и уберите `depends_on`:

```yaml
version: '3.8'

services:
  # Закомментируйте OpenClaw - он на вашем компе
  # openclaw:
  #   image: ghcr.io/openclaw/openclaw:latest
  #   ...

  taskbridge:
    build: .
    container_name: taskbridge_bot
    restart: unless-stopped
    environment:
      - BOT_TOKEN=${BOT_TOKEN}
      - AI_PROVIDER=${AI_PROVIDER}
      - OPENCLAW_BASE_URL=${OPENCLAW_BASE_URL}
      - OPENCLAW_TIMEOUT=${OPENCLAW_TIMEOUT}
      # ...
    volumes:
      - ./data:/app/data
    ports:
      - "8000:8000"
    # Уберите depends_on
    # depends_on:
    #   - openclaw
```

### 3.6 Запустите TaskBridge

```bash
docker-compose up -d --build

# Проверьте логи
docker-compose logs -f taskbridge
```

Вы должны увидеть:
```
INFO - Using OpenClaw AI provider
INFO - OpenClawProvider initialized: https://abc123.ngrok.io, model=openai/gpt-4o
```

---

## Шаг 4: Тестирование

### 4.1 Отправьте тестовое сообщение в Telegram

```
@username сделай отчет до завтра
```

### 4.2 Проверьте логи

**На сервере (TaskBridge):**
```bash
docker-compose logs -f taskbridge
```

Должно быть:
```
INFO - Calling AI API to analyze message...
INFO - OpenClaw API request...
```

**На вашем компе (ngrok):**

В окне ngrok вы увидите HTTP запросы:
```
POST /v1/responses          200 OK
```

**На вашем компе (OpenClaw):**
```bash
cd C:\openclaws
docker-compose logs -f openclaw
```

---

## Шаг 5: Мониторинг ngrok

### Web интерфейс ngrok

Откройте http://127.0.0.1:4040 в браузере - вы увидите все HTTP запросы в реальном времени!

Это полезно для отладки:
- Request/Response bodies
- Timing
- Errors

---

## Ограничения бесплатного ngrok

⚠️ **Бесплатный план:**
- URL меняется при каждом перезапуске ngrok
- Максимум 40 запросов/минуту
- Не для production использования

💰 **Платный план ($8/месяц):**
- Статичный URL (не меняется)
- Больше лимитов
- Custom domain

---

## Troubleshooting

### Ошибка "Connection timeout"

**Проблема:** TaskBridge не может достучаться до ngrok URL

**Решения:**
1. Проверьте что ngrok запущен (окно не закрыто)
2. Проверьте firewall на вашем компе
3. Увеличьте timeout в `.env`:
   ```env
   OPENCLAW_TIMEOUT=120
   ```

### ngrok URL изменился

**Проблема:** Вы перезапустили ngrok и URL изменился

**Решение:**
1. Скопируйте новый URL из ngrok
2. Обновите `.env` на сервере:
   ```bash
   nano .env
   # Измените OPENCLAW_BASE_URL на новый URL
   ```
3. Перезапустите TaskBridge:
   ```bash
   docker-compose restart taskbridge
   ```

**Лучшее решение:** Используйте платный ngrok с статичным URL или деплойте OpenClaw на сервер.

### Медленные ответы

**Причина:** Запрос идет: Сервер → ngrok → Ваш комп → OpenClaw → обратно

**Решения:**
1. Это нормально для ngrok (латентность ~1-3 секунды)
2. Для production деплойте OpenClaw на сервер (Вариант 1 из DEPLOYMENT_OPENCLAW.md)

---

## После тестирования: Миграция на production

Когда тестирование завершено, переключитесь на **Вариант 1** (Docker Compose):

1. Раскомментируйте `openclaw` в `docker-compose.yml`
2. Измените `.env`:
   ```env
   OPENCLAW_BASE_URL=http://openclaw:3000
   OPENCLAW_TIMEOUT=30
   ```
3. Перезапустите:
   ```bash
   docker-compose down
   docker-compose up -d --build
   ```

Теперь OpenClaw будет на том же сервере что и TaskBridge!

---

## Резюме команд

**На вашем компе (Windows):**
```bash
# 1. Запустите OpenClaw
cd C:\openclaws
docker-compose up -d

# 2. Запустите ngrok
ngrok http 3000

# Скопируйте URL: https://abc123.ngrok.io
```

**На сервере (Linux):**
```bash
# 1. Клонируйте и настройте
git clone https://github.com/your-repo/taskbridge.git
cd taskbridge
nano .env  # Установите OPENCLAW_BASE_URL=https://abc123.ngrok.io

# 2. Закомментируйте OpenClaw в docker-compose.yml
nano docker-compose.yml

# 3. Запустите
docker-compose up -d --build

# 4. Проверьте
docker-compose logs -f taskbridge
```

**Готово!** 🎉

Теперь TaskBridge на сервере использует OpenClaw на вашем компьютере через ngrok.
