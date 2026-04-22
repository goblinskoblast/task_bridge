# Деплой TaskBridge на Railway с OpenClaw

Railway уже используется для деплоя TaskBridge. Этот гайд покажет как обновить проект для работы с OpenClaw.

---

## Стратегия деплоя на Railway

### Вариант 1: Railway + ngrok OpenClaw (для тестирования СЕЙЧАС)

**Схема:**
```
Railway (TaskBridge) → ngrok → Ваш комп (OpenClaw в Docker)
```

**Плюсы:**
- ✅ Быстро протестировать новую версию
- ✅ Не нужно менять Railway setup
- ✅ OpenClaw на вашем мощном компе

**Минусы:**
- ❌ Ваш комп должен быть включен 24/7
- ❌ Нестабильно для production
- ❌ ngrok URL меняется при перезапуске (бесплатный план)

---

### Вариант 2: Railway с Docker OpenClaw (для production ПОТОМ)

**Схема:**
```
Railway (TaskBridge + OpenClaw в одном Dockerfile)
```

**Плюсы:**
- ✅ Все на Railway, стабильно
- ✅ Не зависит от вашего компа
- ✅ Production-ready

**Минусы:**
- ❌ Railway может не поддерживать multi-service (нужна проверка)
- ❌ Возможно нужен более дорогой план

---

## Шаг 1: Тестирование с ngrok (СЕЙЧАС)

### 1.1 Запустите OpenClaw локально с ngrok

**На вашем компе (Windows):**

```powershell
# Запустите OpenClaw
cd C:\openclaws
docker-compose up -d

# Запустите ngrok
ngrok http 3000
```

Скопируйте ngrok URL (например: `https://abc123.ngrok-free.app`)

### 1.2 Обновите переменные на Railway

Зайдите в Railway Dashboard → Ваш проект → Variables:

Добавьте/обновите:
```env
AI_PROVIDER=openclaw
OPENCLAW_BASE_URL=https://abc123.ngrok-free.app
OPENCLAW_MODEL=openai/gpt-4o
OPENCLAW_TIMEOUT=60
OPENAI_API_KEY=ваш_openai_ключ
```

**Важно:** Оставьте старые OpenAI переменные как fallback на случай если ngrok упадет.

### 1.3 Задеплойте обновленный код

```bash
cd C:\Users\Владислав\Desktop\task_bridge-main

# Проверьте что все изменения закоммичены
git status

# Добавьте все новые файлы
git add .

# Закоммитьте
git commit -m "feat: Integrate OpenClaw AI provider with abstraction layer

- Add OpenClaw HTTP client (bot/openclaw_client.py)
- Add AI provider abstraction (bot/ai_provider.py)
- Replace OpenAI calls with provider pattern
- Add Docker Compose with OpenClaw service
- Add deployment documentation
- Remove 1906 lines of dead code

OpenClaw can be used via local Docker, ngrok tunnel, or remote server"

# Запушьте на GitHub
git push origin main
```

Railway автоматически подхватит изменения и передеплоит.

### 1.4 Проверьте деплой

В Railway Dashboard проверьте логи:
```
INFO - Using OpenClaw AI provider
INFO - OpenClawProvider initialized: https://abc123.ngrok-free.app
```

---

## Шаг 2: Production деплой на Railway (ПОТОМ)

После тестирования можно перейти на постоянное решение.

### Опция A: Railway с одним сервисом (если поддерживает)

Проверьте поддерживает ли Railway docker-compose:

```bash
# Railway CLI
railway up
```

Если да - Railway запустит оба сервиса (TaskBridge + OpenClaw) из вашего `docker-compose.yml`.

### Опция B: Два Railway проекта

Если Railway не поддерживает multi-service:

**Проект 1: OpenClaw**
- Создайте новый Railway проект
- Деплой только OpenClaw контейнера
- Получите внутренний URL (типа `openclaw.railway.internal`)

**Проект 2: TaskBridge**
- Ваш текущий проект
- Обновите переменную: `OPENCLAW_BASE_URL=https://openclaw.railway.internal`

### Опция C: Внешний сервер для OpenClaw

Деплой OpenClaw на отдельном VPS:
- DigitalOcean ($6/месяц)
- Hetzner (€4/месяц)
- AWS EC2 Free Tier

Затем на Railway:
```env
OPENCLAW_BASE_URL=http://ваш-vps-ip:3000
```

---

## Текущая конфигурация для тестов

### .env (локально для разработки)
```env
BOT_TOKEN=your_telegram_bot_token
AI_PROVIDER=openclaw
OPENCLAW_BASE_URL=http://localhost:3000
OPENCLAW_MODEL=openai/gpt-4o
OPENAI_API_KEY=ваш_ключ
```

### Railway Variables (для тестирования с ngrok)
```env
BOT_TOKEN=your_telegram_bot_token
AI_PROVIDER=openclaw
OPENCLAW_BASE_URL=https://abc123.ngrok-free.app  # <<<< ngrok URL
OPENCLAW_MODEL=openai/gpt-4o
OPENCLAW_TIMEOUT=60
OPENAI_API_KEY=ваш_ключ
```

---

## Мониторинг и отладка

### Проверка работы OpenClaw через ngrok

**1. На вашем компе - ngrok dashboard:**
Откройте http://127.0.0.1:4040

Вы увидите все HTTP запросы от Railway в реальном времени.

**2. Railway logs:**
Railway Dashboard → Deployments → Latest → Logs

Ищите:
```
INFO - Calling AI API to analyze message...
INFO - OpenClaw API request...
INFO - AI response: {...}
```

**3. Локальные логи OpenClaw:**
```bash
cd C:\openclaws
docker-compose logs -f openclaw
```

---

## Troubleshooting

### Railway не может подключиться к ngrok

**Проблема:** Timeout или Connection refused

**Решения:**
1. Проверьте ngrok запущен (окно не закрыто)
2. Проверьте firewall на вашем компе
3. Используйте ngrok платный план (статичный URL)
4. Увеличьте `OPENCLAW_TIMEOUT=120` на Railway

### ngrok URL изменился

**Проблема:** Вы перезапустили ngrok и URL изменился

**Решение:**
1. Скопируйте новый URL из ngrok
2. Railway Dashboard → Variables → обновите `OPENCLAW_BASE_URL`
3. Railway автоматически передеплоит

### Медленные ответы на Railway

**Причина:** Запрос идет: Railway → ngrok → ваш комп → OpenClaw → обратно

**Решения:**
1. Это нормально (~2-5 секунд latency)
2. Для production переходите на Вариант 2 (OpenClaw на Railway/VPS)

---

## Следующие шаги

### После тестирования ngrok:

1. **Если все работает хорошо:**
   - Оцените latency
   - Проверьте quality AI ответов
   - Если устраивает - можно использовать временно

2. **Для production:**
   - Решите какую опцию использовать (A, B или C)
   - Деплой OpenClaw на постоянное место
   - Обновите `OPENCLAW_BASE_URL` на Railway
   - Выключите ngrok

3. **Rollback при проблемах:**
   - На Railway измените: `AI_PROVIDER=openai`
   - Вернется на старую версию с OpenAI
   - Исправьте проблемы
   - Переключите обратно на OpenClaw

---

## Преимущества Railway

- ✅ Автоматический деплой при git push
- ✅ Бесплатный план для тестирования
- ✅ Легко управлять переменными окружения
- ✅ Встроенные логи и мониторинг
- ✅ HTTPS из коробки

---

## Стоимость

**Текущая схема (ngrok):**
- Railway: $0-5/месяц (зависит от usage)
- ngrok: $0 (бесплатный план, но URL меняется)
- OpenClaw: $0 (open-source)
- OpenAI API: ~$1-10/месяц (зависит от использования)

**Production схема (все на Railway):**
- Railway: $5-20/месяц
- OpenClaw: $0
- OpenAI API: ~$1-10/месяц

**Production схема (OpenClaw на VPS):**
- Railway: $0-5/месяц
- VPS: $4-6/месяц
- OpenClaw: $0
- OpenAI API: ~$1-10/месяц

---

## Рекомендация

**Сейчас:**
- ✅ Используйте ngrok для быстрого тестирования
- ✅ Проверьте качество работы OpenClaw
- ✅ Убедитесь что все функции работают

**Через неделю (если тесты ОК):**
- ✅ Перейдите на production setup (Вариант 2 или VPS)
- ✅ Выключите ngrok
- ✅ Наслаждайтесь стабильной работой!
