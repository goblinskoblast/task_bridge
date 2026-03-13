# Деплой TaskBridge на Render.com

Это руководство описывает процесс развертывания TaskBridge на платформе Render.com с настройкой автоматического пробуждения через cron-job.org.

## Зачем Render.com?

- ✅ **Бесплатный tier** для развертывания (750 часов в месяц)
- ✅ **Автоматический HTTPS**
- ✅ **Интеграция с GitHub**
- ✅ **PostgreSQL база данных** (опционально)
- ⚠️ **Ограничение**: Приложение "засыпает" после 15 минут неактивности на бесплатном тарифе

## Подготовка к деплою

### 1. Создать аккаунт на Render.com

1. Перейдите на [render.com](https://render.com)
2. Зарегистрируйтесь через GitHub
3. Подтвердите email

### 2. Подготовить репозиторий

Убедитесь что ваш код находится в Git репозитории (GitHub, GitLab, или Bitbucket).

```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/your-username/taskbridge.git
git push -u origin main
```

## Развертывание на Render

### 1. Создать новый Web Service

1. В dashboard Render нажмите **"New +"** → **"Web Service"**
2. Подключите ваш Git репозиторий
3. Выберите репозиторий TaskBridge

### 2. Настроить параметры деплоя

#### Basic Settings:
- **Name**: `taskbridge` (или любое другое имя)
- **Region**: Выберите ближайший регион (Europe для России)
- **Branch**: `main`
- **Root Directory**: оставьте пустым
- **Runtime**: `Python 3`

#### Build & Deploy:
- **Build Command**:
  ```bash
  pip install -r requirements.txt && cd webapp && npm install && npm run build
  ```
- **Start Command**:
  ```bash
  python main.py
  ```

#### Instance Type:
- Выберите **"Free"** (достаточно для разработки)

### 3. Настроить переменные окружения

В разделе **"Environment"** добавьте следующие переменные:

```bash
# Telegram Bot
BOT_TOKEN=your_telegram_bot_token_here

# OpenAI API
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
OPENAI_TEMPERATURE=0.3
OPENAI_MAX_TOKENS=500

# Database (используйте Render PostgreSQL или Supabase)
DATABASE_URL=postgresql://user:password@host:5432/database

# Web Application
WEB_APP_DOMAIN=https://taskbridge.onrender.com
MINI_APP_URL=https://taskbridge.onrender.com/webapp/index.html
USE_WEBHOOK=True
WEBHOOK_URL=https://taskbridge.onrender.com
WEBHOOK_PATH=/webhook

# Server
HOST=0.0.0.0
PORT=8000

# Timezone
TIMEZONE=Europe/Moscow
LOG_LEVEL=INFO

# Email Integration (опционально)
EMAIL_ENCRYPTION_KEY=your_fernet_key_here

# Support Chat (опционально)
DEVELOPER_TELEGRAM_ID=your_telegram_user_id
```

**ВАЖНО**: Замените `your_telegram_bot_token_here` и другие плейсхолдеры на реальные значения!

### 4. Создать PostgreSQL базу данных (опционально)

Если вы не используете Supabase:

1. В Render dashboard нажмите **"New +"** → **"PostgreSQL"**
2. Заполните:
   - **Name**: `taskbridge-db`
   - **Database**: `taskbridge`
   - **User**: `taskbridge_user`
   - **Region**: тот же что и у web service
   - **PostgreSQL Version**: 15
   - **Plan**: Free
3. Нажмите **"Create Database"**
4. Скопируйте **Internal Database URL** и добавьте его в переменную `DATABASE_URL` в web service

### 5. Деплой

1. Нажмите **"Create Web Service"**
2. Дождитесь завершения деплоя (5-10 минут)
3. Render автоматически:
   - Установит зависимости
   - Соберет React приложение
   - Запустит бота и веб-сервер
   - Присвоит публичный URL: `https://taskbridge.onrender.com`

### 6. Настроить Telegram Webhook

После успешного деплоя обновите webhook вашего бота:

```bash
curl -X POST "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://taskbridge.onrender.com/webhook"}'
```

Замените `<YOUR_BOT_TOKEN>` на токен вашего бота.

Проверьте webhook:
```bash
curl "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getWebhookInfo"
```

## Проблема: Приложение "засыпает"

На бесплатном тарифе Render приложение засыпает после **15 минут неактивности**. Это означает:
- ❌ Бот не будет отвечать на сообщения пока спит
- ❌ Напоминания не будут отправляться
- ✅ Первый запрос "разбудит" приложение (займет ~30 секунд)

### Решение: Cron-job для пробуждения

Используем [cron-job.org](https://cron-job.org) для автоматического пинга каждые 5 минут.

## Настройка Cron-job.org

### 1. Создать аккаунт

1. Перейдите на [cron-job.org](https://cron-job.org)
2. Нажмите **"Sign up"**
3. Зарегистрируйтесь через email или Google
4. Подтвердите email

### 2. Создать cron job

1. Войдите в dashboard
2. Нажмите **"Create cronjob"**

#### Настройки:

**General:**
- **Title**: `TaskBridge Keep Alive`
- **Address (URL)**: `https://taskbridge.onrender.com/health`
  - (замените `taskbridge.onrender.com` на ваш URL от Render)

**Schedule:**
- **Every**: `5 minutes`
- Или используйте cron выражение: `*/5 * * * *`

**Advanced:**
- **Enabled**: ✅ (включено)
- **Save responses**: можно отключить для экономии места
- **Execution schedule**: All days, all hours
- **Request method**: `GET`
- **Request timeout**: `30 seconds`

3. Нажмите **"Create cronjob"**

### 3. Добавить health endpoint (если его нет)

Если в вашем `webapp/app.py` нет health endpoint, добавьте его:

```python
@app.get("/health")
async def health_check():
    """Health check endpoint для мониторинга и пробуждения"""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "service": "TaskBridge"
    }
```

### 4. Проверить работу

1. В cron-job.org нажмите **"Run"** рядом с вашим job
2. Проверьте историю выполнений - должен быть статус `200 OK`
3. В Render logs должны появиться запросы к `/health` каждые 5 минут

## Мониторинг

### Render Logs

Просмотр логов в реальном времени:
1. Откройте ваш Web Service в Render dashboard
2. Перейдите в раздел **"Logs"**
3. Вы увидите все логи бота и веб-сервера

### Cron-job History

Проверка пингов:
1. В cron-job.org откройте ваш job
2. Перейдите в **"History"**
3. Вы увидите все выполнения с кодами ответа

## Обновление приложения

Render автоматически деплоит при push в main ветку:

```bash
git add .
git commit -m "Update feature X"
git push origin main
```

Render автоматически:
1. Обнаружит новый коммит
2. Запустит новый build
3. Деплоит обновленную версию
4. Перезапустит сервис

## Стоимость

### Бесплатный tier:
- ✅ **Web Service**: 750 часов/месяц (достаточно для 1 приложения)
- ✅ **PostgreSQL**: 1 БД, 1 GB хранилище
- ✅ **Bandwidth**: 100 GB/месяц

### Платный tier ($7/месяц):
- ✅ **Без засыпания** (always-on)
- ✅ Больше памяти и CPU
- ✅ Больше БД и storage

Для разработки бесплатного tier достаточно. Для production рекомендуется платный tier.

## Альтернативы Render.com

Если нужно больше возможностей:

1. **Railway.app** ($5/месяц после trial)
   - Простой деплой
   - PostgreSQL included
   - Не засыпает

2. **Fly.io** (бесплатный tier, но сложнее)
   - Больше контроля
   - Докер deployment
   - Несколько регионов

3. **VPS (DigitalOcean, Hetzner)** ($4-6/месяц)
   - Полный контроль
   - Требует больше настройки
   - SSH доступ

## Решение проблем

### Приложение не просыпается
- Проверьте что cron-job пингует правильный URL
- Убедитесь что `/health` endpoint возвращает 200
- Проверьте Render logs на ошибки

### Webhook не работает
- Убедитесь что `USE_WEBHOOK=True`
- Проверьте что webhook URL установлен через Telegram API
- Проверьте Render logs на входящие webhook запросы

### База данных не подключается
- Проверьте правильность DATABASE_URL
- Убедитесь что PostgreSQL база создана
- Проверьте что migrations выполнились

### Build fails
- Проверьте requirements.txt на опечатки
- Убедитесь что Python версия совместима (3.10+)
- Проверьте build logs в Render

## Полезные ссылки

- [Render Documentation](https://render.com/docs)
- [Cron-job.org Guide](https://cron-job.org/en/documentation)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [PostgreSQL on Render](https://render.com/docs/databases)
