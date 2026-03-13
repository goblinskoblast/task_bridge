# Деплой TaskBridge с OpenClaw

Документация по различным вариантам развертывания TaskBridge с OpenClaw.

---

## Варианты деплоя

### 🎯 Вариант 1: OpenClaw в одном Docker Compose (Рекомендуется)

**Плюсы:**
- Простота развертывания (один `docker-compose up`)
- OpenClaw и TaskBridge в одной сети
- Автоматическое управление зависимостями
- Работает локально и на удаленном сервере

**Минусы:**
- OpenClaw и TaskBridge на одном сервере (больше нагрузка)

#### Настройка

**1. Для локальной разработки:**

`.env`:
```env
AI_PROVIDER=openclaw
OPENCLAW_BASE_URL=http://localhost:3000
OPENAI_API_KEY=ваш_openai_ключ
```

Запуск:
```bash
docker-compose up -d
```

**2. Для деплоя на сервер:**

`.env`:
```env
AI_PROVIDER=openclaw
OPENCLAW_BASE_URL=http://openclaw:3000  # имя сервиса из docker-compose
OPENAI_API_KEY=ваш_openai_ключ
```

Запуск:
```bash
docker-compose up -d
```

OpenClaw будет доступен внутри Docker сети по имени `openclaw:3000`.

---

### 🌐 Вариант 2: Удаленный OpenClaw через ngrok (для тестирования)

**Плюсы:**
- OpenClaw на вашем локальном компе
- TaskBridge может быть на удаленном сервере
- Бесплатно для тестирования

**Минусы:**
- Не для production (нестабильно, медленно)
- Требует чтобы ваш комп был постоянно включен
- Публичный URL меняется при перезапуске (в бесплатной версии)

#### Настройка

**Шаг 1: Запустите OpenClaw локально**

```bash
cd C:\openclaws
docker-compose up -d
```

**Шаг 2: Установите ngrok**

Скачайте с https://ngrok.com/download

**Шаг 3: Expose OpenClaw через ngrok**

```bash
ngrok http 3000
```

Вы получите публичный URL типа:
```
https://abc123.ngrok.io -> http://localhost:3000
```

**Шаг 4: Настройте TaskBridge на сервере**

`.env` на сервере:
```env
AI_PROVIDER=openclaw
OPENCLAW_BASE_URL=https://abc123.ngrok.io  # URL из ngrok
OPENCLAW_TIMEOUT=60  # Увеличьте timeout для удаленного соединения
```

**Важно:**
- При каждом перезапуске ngrok URL меняется (платная версия дает статичный URL)
- Латентность будет выше (запрос идет: сервер → ваш комп → OpenClaw)

---

### 🚀 Вариант 3: OpenClaw на отдельном сервере

**Плюсы:**
- Масштабируемость (разные серверы)
- Можно использовать мощный сервер для OpenClaw
- Несколько TaskBridge могут использовать один OpenClaw

**Минусы:**
- Нужен еще один сервер (дополнительные расходы)
- Нужно настроить сетевую безопасность

#### Настройка

**Сервер 1 (OpenClaw):**

1. Установите Docker
2. Создайте `docker-compose.yml`:

```yaml
version: '3.8'

services:
  openclaw:
    image: ghcr.io/openclaw/openclaw:latest
    restart: unless-stopped
    environment:
      - OPENAI_API_KEY=ваш_openai_ключ
      - OPENCLAW_MODEL=openai/gpt-4o
    ports:
      - "3000:3000"  # Expose наружу
    volumes:
      - ./openclaw_data:/root/.openclaw
```

3. Запустите:
```bash
docker-compose up -d
```

4. **Настройте firewall** (разрешите порт 3000 только для IP вашего сервера TaskBridge):

```bash
# Ubuntu/Debian
sudo ufw allow from <IP_TASKBRIDGE_СЕРВЕРА> to any port 3000
```

**Сервер 2 (TaskBridge):**

`.env`:
```env
AI_PROVIDER=openclaw
OPENCLAW_BASE_URL=http://<IP_OPENCLAW_СЕРВЕРА>:3000
OPENCLAW_TIMEOUT=60
```

---

### 🔒 Вариант 4: OpenClaw за HTTPS + Authentication

**Плюсы:**
- Безопасность (HTTPS + токен аутентификации)
- Production-ready
- Можно expose в интернет безопасно

**Минусы:**
- Сложнее настройка (нужен Nginx, SSL сертификат)

#### Настройка

**Сервер OpenClaw:**

1. Настройте Nginx как reverse proxy с SSL:

`/etc/nginx/sites-available/openclaw`:
```nginx
server {
    listen 443 ssl http2;
    server_name openclaw.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/openclaw.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/openclaw.yourdomain.com/privkey.pem;

    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;

        # Проверка токена
        if ($http_authorization != "Bearer YOUR_SECRET_TOKEN") {
            return 401;
        }
    }
}
```

2. Получите SSL сертификат (Let's Encrypt):
```bash
sudo certbot --nginx -d openclaw.yourdomain.com
```

**TaskBridge:**

Обновите `bot/openclaw_client.py` для поддержки authentication:

```python
class OpenClawClient:
    def __init__(self, base_url: str, model: str, timeout: int = 30, auth_token: str = None):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.auth_token = auth_token  # Добавить
```

`.env`:
```env
OPENCLAW_BASE_URL=https://openclaw.yourdomain.com
OPENCLAW_AUTH_TOKEN=YOUR_SECRET_TOKEN
```

---

## Сравнение вариантов

| Вариант | Сложность | Стоимость | Production | Скорость |
|---------|-----------|-----------|------------|----------|
| 1. Docker Compose | ⭐ Легко | 💰 Один сервер | ✅ Да | ⚡⚡⚡ Быстро |
| 2. ngrok | ⭐⭐ Средне | 💰 Бесплатно* | ❌ Нет | ⚡ Медленно |
| 3. Отдельный сервер | ⭐⭐⭐ Сложно | 💰💰 Два сервера | ✅ Да | ⚡⚡ Средне |
| 4. HTTPS + Auth | ⭐⭐⭐⭐ Очень сложно | 💰💰 Два сервера + домен | ✅✅ Максимум | ⚡⚡ Средне |

*ngrok бесплатен для тестирования, но для production нужен платный план

---

## Рекомендации

### Для локальной разработки:
✅ **Вариант 1** (Docker Compose) с `OPENCLAW_BASE_URL=http://localhost:3000`

### Для тестового деплоя:
✅ **Вариант 2** (ngrok) - быстро проверить работу на сервере

### Для production (один сервер):
✅ **Вариант 1** (Docker Compose) с `OPENCLAW_BASE_URL=http://openclaw:3000`

### Для production (высокая нагрузка):
✅ **Вариант 3 или 4** - отдельный сервер для OpenClaw

---

## Инструкции по запуску

### Локальная разработка

```bash
# 1. Настройте .env
cp .env.example .env
nano .env  # установите BOT_TOKEN и OPENAI_API_KEY

# 2. Запустите
docker-compose up -d

# 3. Проверьте логи
docker-compose logs -f taskbridge
```

### Деплой на VPS (DigitalOcean, AWS, etc.)

```bash
# 1. SSH на сервер
ssh root@your-server-ip

# 2. Установите Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# 3. Установите Docker Compose
sudo apt install docker-compose

# 4. Клонируйте репозиторий
git clone https://github.com/your-repo/taskbridge.git
cd taskbridge

# 5. Настройте .env
nano .env
# Установите:
# - BOT_TOKEN
# - OPENAI_API_KEY
# - OPENCLAW_BASE_URL=http://openclaw:3000  # для Docker

# 6. Запустите
docker-compose up -d

# 7. Проверьте статус
docker-compose ps
docker-compose logs -f
```

---

## Troubleshooting

### OpenClaw не отвечает

**Проверка 1:** OpenClaw запущен?
```bash
docker ps | grep openclaw
```

**Проверка 2:** OpenClaw доступен?
```bash
# Внутри Docker сети:
docker exec taskbridge_bot curl http://openclaw:3000/health

# Снаружи:
curl http://localhost:3000/health
```

**Проверка 3:** Логи OpenClaw
```bash
docker-compose logs openclaw
```

### Ошибка "Connection refused"

Убедитесь что:
1. `OPENCLAW_BASE_URL` правильно настроен
2. OpenClaw контейнер запущен
3. Используете правильный URL:
   - `http://localhost:3000` - для локальной разработки (вне Docker)
   - `http://openclaw:3000` - внутри Docker сети

### Медленные ответы

1. Увеличьте timeout:
```env
OPENCLAW_TIMEOUT=60
```

2. Проверьте сетевую латентность:
```bash
ping <openclaw-server-ip>
```

---

## Миграция с локального на production

**Шаг 1:** Тестируйте локально с Docker Compose
```env
OPENCLAW_BASE_URL=http://localhost:3000
```

**Шаг 2:** Перед деплоем измените на Docker сеть
```env
OPENCLAW_BASE_URL=http://openclaw:3000
```

**Шаг 3:** Деплой
```bash
git push origin main
# На сервере:
git pull
docker-compose down
docker-compose up -d --build
```

---

## Мониторинг

### Проверка здоровья OpenClaw

Добавьте healthcheck в `docker-compose.yml`:

```yaml
openclaw:
  image: ghcr.io/openclaw/openclaw:latest
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
    interval: 30s
    timeout: 10s
    retries: 3
    start_period: 40s
```

### Логирование

```bash
# Все логи
docker-compose logs -f

# Только OpenClaw
docker-compose logs -f openclaw

# Только TaskBridge
docker-compose logs -f taskbridge
```

---

## Вопросы и ответы

**Q: Можно ли использовать один OpenClaw для нескольких ботов?**
A: Да! Просто настройте `OPENCLAW_BASE_URL` на всех ботах на один и тот же OpenClaw сервер.

**Q: Сколько стоит OpenClaw?**
A: OpenClaw бесплатен (open-source), но нужен OpenAI API ключ для backend модели.

**Q: Можно ли использовать другие модели кроме GPT-4o?**
A: Да! Настройте `OPENCLAW_MODEL`:
- `openai/gpt-4o` (рекомендуется)
- `openai/gpt-4o-mini` (дешевле)
- `anthropic/claude-sonnet-3.5` (нужен Anthropic ключ)
- `local/llama-3` (локальные модели)

**Q: Безопасно ли expose OpenClaw в интернет?**
A: Используйте **Вариант 4** (HTTPS + Authentication) для production. Никогда не expose порт 3000 напрямую!
