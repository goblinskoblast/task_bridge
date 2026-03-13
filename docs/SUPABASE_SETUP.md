# Настройка Supabase PostgreSQL для TaskBridge

Этот документ содержит пошаговую инструкцию по подключению TaskBridge к Supabase PostgreSQL базе данных.

## Содержание

1. [Что такое Supabase](#что-такое-supabase)
2. [Создание проекта в Supabase](#создание-проекта-в-supabase)
3. [Получение строки подключения](#получение-строки-подключения)
4. [Настройка проекта TaskBridge](#настройка-проекта-taskbridge)
5. [Инициализация базы данных](#инициализация-базы-данных)
6. [Проверка подключения](#проверка-подключения)
7. [Управление базой данных через Supabase Dashboard](#управление-базой-данных-через-supabase-dashboard)
8. [Решение проблем](#решение-проблем)

---

## Что такое Supabase

Supabase - это open-source альтернатива Firebase, которая предоставляет:
- PostgreSQL базу данных
- Автоматические REST API
- Аутентификацию
- Realtime подписки
- Хранилище файлов

Для TaskBridge мы используем Supabase PostgreSQL в качестве основной базы данных для хранения:
- Пользователей бота
- Чатов, в которых работает бот
- Задач и их статусов
- Комментариев
- Файлов
- Email-сообщений

**Преимущества использования Supabase:**
- ✅ Бесплатный план до 500 МБ базы данных
- ✅ Автоматические бэкапы
- ✅ Удобный веб-интерфейс для управления данными
- ✅ Высокая доступность и надежность
- ✅ Не требуется настройка сервера БД

---

## Создание проекта в Supabase

### Шаг 1: Регистрация

1. Перейдите на [supabase.com](https://supabase.com)
2. Нажмите "Start your project" или "Sign up"
3. Войдите через GitHub account (рекомендуется) или Email

### Шаг 2: Создание нового проекта

1. После входа нажмите "New project"
2. Выберите организацию или создайте новую
3. Заполните форму создания проекта:

   ```
   Name: TaskBridge
   Database Password: [придумайте надежный пароль]
   Region: [выберите ближайший регион, например Europe (Frankfurt)]
   Pricing Plan: Free (для начала достаточно бесплатного плана)
   ```

4. Нажмите "Create new project"
5. Подождите 1-2 минуты, пока Supabase создает проект

**⚠️ ВАЖНО:** Сохраните пароль базы данных в надежном месте! Он понадобится для подключения.

---

## Получение строки подключения

### Способ 1: Через Dashboard (рекомендуется)

1. В левом меню нажмите на иконку "Settings" (⚙️)
2. Выберите "Database"
3. Прокрутите до секции "Connection string"
4. Выберите вкладку "URI"
5. Скопируйте строку подключения, она выглядит так:

   ```
   postgresql://postgres:[YOUR-PASSWORD]@db.xxxxxxxxxxxxx.supabase.co:5432/postgres
   ```

6. Замените `[YOUR-PASSWORD]` на пароль, который вы указали при создании проекта

### Способ 2: Session Mode (для высоконагруженных приложений)

Если ваше приложение создает много подключений, используйте Session Mode:

1. В Settings → Database
2. Найдите "Connection pooling"
3. Включите "Session Mode"
4. Скопируйте строку подключения из "Session Mode Connection String"

---

## Настройка проекта TaskBridge

### Шаг 1: Установка зависимостей

```bash
# Установите необходимые библиотеки для работы с PostgreSQL
pip install -r requirements.txt
```

В `requirements.txt` уже включены:
- `asyncpg>=0.29.0` - асинхронный драйвер PostgreSQL
- `psycopg2-binary>=2.9.9` - синхронный драйвер PostgreSQL
- `sqlalchemy>=2.0.25` - ORM для работы с БД

### Шаг 2: Настройка переменных окружения

1. Скопируйте файл `.env.example` в `.env`:

   ```bash
   copy .env.example .env
   ```

2. Откройте `.env` в текстовом редакторе

3. Найдите строку `DATABASE_URL` и вставьте вашу строку подключения из Supabase:

   ```env
   DATABASE_URL=postgresql://postgres:your_password@db.xxxxxxxxxxxxx.supabase.co:5432/postgres
   ```

4. Замените остальные значения:

   ```env
   # Токен вашего Telegram бота
   BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

   # API ключ OpenAI для AI-анализа задач
   OPENAI_API_KEY=sk-...

   # Строка подключения к Supabase PostgreSQL
   DATABASE_URL=postgresql://postgres:your_password@db.xxxxxxxxxxxxx.supabase.co:5432/postgres
   ```

5. Сохраните файл

### Пример полного `.env` файла:

```env
# Telegram Bot
BOT_TOKEN=6789012345:AAHZxPqYm1B2nC3dE4fG5hI6jK7lM8nO9pQ0

# OpenAI API
OPENAI_API_KEY=sk-proj-abc123def456ghi789jkl012mno345pqr678stu901vwx234yz

# Supabase PostgreSQL
DATABASE_URL=postgresql://postgres:MySecurePassword123!@db.abcdefghijklmnop.supabase.co:5432/postgres

# Server Configuration
HOST=0.0.0.0
PORT=8000
WEB_APP_DOMAIN=http://localhost:8000

# Logging
LOG_LEVEL=INFO
TIMEZONE=Europe/Moscow
```

---

## Инициализация базы данных

После настройки переменных окружения нужно создать таблицы в базе данных.

### Шаг 1: Запуск скрипта инициализации

```bash
python init_db.py
```

Вы увидите вывод:

```
🚀 Инициализация базы данных TaskBridge
============================================================

1️⃣  Проверка подключения к базе данных...
✅ Подключение к PostgreSQL успешно!
📊 Версия PostgreSQL: PostgreSQL 15.1 on x86_64-pc-linux-gnu

2️⃣  Создание таблиц...
📝 Начинаем создание таблиц...
✅ Все таблицы успешно созданы!

📋 Созданные таблицы (11):
   - categories
   - chats
   - comments
   - email_accounts
   - email_messages
   - messages
   - pending_tasks
   - task_assignees
   - task_files
   - tasks
   - users

3️⃣  Проверка созданных таблиц...
✅ Все ожидаемые таблицы присутствуют!

============================================================
🎉 Инициализация базы данных завершена успешно!

📝 Следующие шаги:
   1. Запустите бота: python main.py
   2. Используйте /start в Telegram для начала работы
   3. Добавьте бота в групповые чаты для управления задачами
```

### Шаг 2: Проверка таблиц в Supabase Dashboard

1. Откройте Supabase Dashboard
2. В левом меню выберите "Table Editor"
3. Вы должны увидеть все созданные таблицы:

   - **users** - пользователи бота
   - **chats** - чаты, в которых работает бот
   - **messages** - сообщения из чатов
   - **categories** - категории задач
   - **tasks** - задачи
   - **pending_tasks** - задачи, ожидающие подтверждения
   - **task_assignees** - связь задач с исполнителями (many-to-many)
   - **task_files** - файлы, прикрепленные к задачам
   - **comments** - комментарии к задачам
   - **email_accounts** - email аккаунты для интеграции
   - **email_messages** - полученные email сообщения

---

## Проверка подключения

### Тест 1: Проверка через Python

Создайте файл `test_db.py`:

```python
from sqlalchemy import text
from db.database import sync_engine

# Проверка подключения
with sync_engine.connect() as conn:
    result = conn.execute(text("SELECT version()"))
    print("PostgreSQL версия:", result.scalar())

    # Проверка таблиц
    result = conn.execute(text("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
    """))

    tables = [row[0] for row in result.fetchall()]
    print(f"\nНайдено таблиц: {len(tables)}")
    for table in tables:
        print(f"  - {table}")
```

Запустите:

```bash
python test_db.py
```

### Тест 2: Создание тестового пользователя

```python
from db.database import get_db_session
from db.models import User

db = get_db_session()

# Создаем тестового пользователя
test_user = User(
    telegram_id=12345678,
    username="test_user",
    first_name="Test",
    last_name="User"
)

db.add(test_user)
db.commit()

print(f"✅ Создан пользователь: {test_user.username} (ID: {test_user.id})")

# Проверяем
users = db.query(User).all()
print(f"📊 Всего пользователей в БД: {len(users)}")

db.close()
```

---

## Управление базой данных через Supabase Dashboard

### Просмотр данных

1. Откройте "Table Editor" в левом меню
2. Выберите таблицу (например, `users`)
3. Вы увидите все записи в таблице

### Фильтрация и поиск

1. Используйте поле поиска вверху таблицы
2. Нажмите на иконку фильтра для расширенного поиска
3. Можно фильтровать по любому полю

### Редактирование данных

1. Нажмите на ячейку для редактирования
2. Измените значение
3. Нажмите Enter или кликните вне ячейки для сохранения

### SQL Editor

1. В левом меню выберите "SQL Editor"
2. Напишите SQL запрос, например:

   ```sql
   -- Получить всех пользователей с их задачами
   SELECT
       u.username,
       u.first_name,
       COUNT(t.id) as tasks_count
   FROM users u
   LEFT JOIN task_assignees ta ON u.id = ta.user_id
   LEFT JOIN tasks t ON ta.task_id = t.id
   GROUP BY u.id, u.username, u.first_name
   ORDER BY tasks_count DESC;
   ```

3. Нажмите "Run" или `Ctrl+Enter`

### Полезные SQL запросы

#### 1. Статистика по пользователям

```sql
SELECT
    COUNT(*) as total_users,
    COUNT(CASE WHEN telegram_id != -1 THEN 1 END) as active_users,
    COUNT(CASE WHEN telegram_id = -1 THEN 1 END) as pending_users
FROM users;
```

#### 2. Статистика по задачам

```sql
SELECT
    status,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 2) as percentage
FROM tasks
GROUP BY status
ORDER BY count DESC;
```

#### 3. Топ активных чатов

```sql
SELECT
    c.title,
    c.chat_type,
    COUNT(m.id) as messages_count,
    COUNT(DISTINCT m.user_id) as unique_users
FROM chats c
LEFT JOIN messages m ON c.chat_id = m.chat_id
WHERE c.is_active = true
GROUP BY c.id, c.title, c.chat_type
ORDER BY messages_count DESC
LIMIT 10;
```

#### 4. Задачи с просроченным дедлайном

```sql
SELECT
    t.title,
    t.status,
    t.due_date,
    u.username as creator,
    STRING_AGG(u2.username, ', ') as assignees
FROM tasks t
LEFT JOIN users u ON t.created_by = u.id
LEFT JOIN task_assignees ta ON t.id = ta.task_id
LEFT JOIN users u2 ON ta.user_id = u2.id
WHERE t.due_date < NOW() AND t.status != 'completed'
GROUP BY t.id, t.title, t.status, t.due_date, u.username
ORDER BY t.due_date ASC;
```

---

## Решение проблем

### Проблема 1: "Could not connect to database"

**Симптомы:**
```
❌ Ошибка подключения к базе данных: could not connect to server
```

**Решение:**
1. Проверьте правильность строки подключения в `.env`
2. Убедитесь, что пароль правильный (без специальных символов в начале/конце)
3. Проверьте, что проект в Supabase активен (не приостановлен)
4. Попробуйте пинговать сервер: `ping db.xxxxxxxxxxxxx.supabase.co`

### Проблема 2: "Authentication failed"

**Симптомы:**
```
❌ Ошибка подключения: FATAL: password authentication failed for user "postgres"
```

**Решение:**
1. Сбросьте пароль базы данных:
   - Settings → Database → "Reset database password"
2. Обновите `DATABASE_URL` в `.env` с новым паролем
3. Перезапустите приложение

### Проблема 3: "Too many connections"

**Симптомы:**
```
❌ FATAL: remaining connection slots are reserved for non-replication superuser connections
```

**Решение:**
1. Используйте Connection Pooling:
   - Settings → Database → включите "Connection pooling"
   - Используйте строку подключения из "Session mode"
2. Или обновите plan в Supabase для большего количества соединений

### Проблема 4: Таблицы не создаются

**Симптомы:**
```
⚠️  Отсутствуют таблицы: users, tasks, ...
```

**Решение:**
1. Проверьте права доступа пользователя `postgres`
2. Попробуйте создать таблицы вручную через SQL Editor в Supabase
3. Убедитесь, что в коде нет ошибок в моделях SQLAlchemy
4. Попробуйте удалить все таблицы и пересоздать:

   ```python
   from db.database import sync_engine
   from db.models import Base

   # ВНИМАНИЕ: Это удалит все данные!
   Base.metadata.drop_all(sync_engine)
   Base.metadata.create_all(sync_engine)
   ```

### Проблема 5: Медленная работа базы данных

**Симптомы:**
- Запросы выполняются дольше 1-2 секунд
- Таймауты при больших запросах

**Решение:**
1. Создайте индексы для часто используемых полей:

   ```sql
   CREATE INDEX idx_tasks_status ON tasks(status);
   CREATE INDEX idx_tasks_created_by ON tasks(created_by);
   CREATE INDEX idx_messages_chat_id ON messages(chat_id);
   CREATE INDEX idx_users_telegram_id ON users(telegram_id);
   ```

2. Используйте Connection Pooling (см. Проблему 3)
3. Оптимизируйте запросы (избегайте N+1 запросов)

### Проблема 6: "relation does not exist"

**Симптомы:**
```
ERROR: relation "users" does not exist
```

**Решение:**
1. Убедитесь, что вы запустили `python init_db.py`
2. Проверьте, что используется правильная база данных (не тестовая)
3. В Supabase Dashboard проверьте наличие таблиц в "Table Editor"

---

## Дополнительные ресурсы

- [Документация Supabase](https://supabase.com/docs)
- [Документация SQLAlchemy](https://docs.sqlalchemy.org/)
- [Документация asyncpg](https://magicstack.github.io/asyncpg/)
- [PostgreSQL Tutorial](https://www.postgresqltutorial.com/)

---

## Бэкапы и восстановление

### Автоматические бэкапы (Supabase)

Supabase автоматически создает бэкапы:
- **Free plan**: ежедневные бэкапы, хранятся 7 дней
- **Pro plan**: ежедневные бэкапы, хранятся 30 дней

Для восстановления:
1. Settings → Database → "Point in Time Recovery"
2. Выберите дату и время
3. Создайте новый проект из бэкапа

### Ручной экспорт данных

```bash
# Экспорт всей базы данных
pg_dump -h db.xxxxxxxxxxxxx.supabase.co -U postgres -d postgres > backup.sql

# Экспорт только схемы
pg_dump -h db.xxxxxxxxxxxxx.supabase.co -U postgres -d postgres --schema-only > schema.sql

# Экспорт только данных
pg_dump -h db.xxxxxxxxxxxxx.supabase.co -U postgres -d postgres --data-only > data.sql
```

### Восстановление из бэкапа

```bash
psql -h db.xxxxxxxxxxxxx.supabase.co -U postgres -d postgres < backup.sql
```

---

## Мониторинг и логи

### Просмотр логов в Supabase

1. В Dashboard выберите "Logs" в левом меню
2. Выберите тип логов:
   - **Postgres Logs** - запросы к базе данных
   - **API Logs** - REST API запросы
   - **Function Logs** - логи функций

### Метрики производительности

1. В Dashboard выберите "Reports"
2. Вы увидите графики:
   - Database size
   - Database connections
   - Egress bandwidth
   - API requests

---

## Переход с SQLite на Supabase

Если вы ранее использовали SQLite, вот как мигрировать данные:

### Шаг 1: Экспорт данных из SQLite

```python
import sqlite3
import json

# Подключаемся к SQLite
sqlite_conn = sqlite3.connect('taskbridge.db')
cursor = sqlite_conn.cursor()

# Экспортируем пользователей
cursor.execute("SELECT * FROM users")
users = cursor.fetchall()

with open('users_export.json', 'w', encoding='utf-8') as f:
    json.dump(users, f, ensure_ascii=False, indent=2)

# То же самое для других таблиц...
```

### Шаг 2: Импорт в Supabase

```python
import json
from db.database import get_db_session
from db.models import User

db = get_db_session()

# Импортируем пользователей
with open('users_export.json', 'r', encoding='utf-8') as f:
    users_data = json.load(f)

for user_data in users_data:
    user = User(
        telegram_id=user_data[1],
        username=user_data[2],
        first_name=user_data[3],
        # ... остальные поля
    )
    db.add(user)

db.commit()
db.close()
```

---

## Заключение

Теперь TaskBridge настроен для работы с Supabase PostgreSQL!

**Ключевые преимущества:**
- ✅ Все данные сохраняются между перезапусками
- ✅ Пользователи регистрируются один раз
- ✅ Чаты запоминаются автоматически
- ✅ Задачи хранятся постоянно
- ✅ Удобное управление через веб-интерфейс
- ✅ Автоматические бэкапы

**Следующие шаги:**
1. Запустите бота: `python main.py`
2. Протестируйте в Telegram
3. Проверьте, что данные сохраняются в Supabase Dashboard
4. Настройте дополнительные функции (email integration, reminders)

Удачи! 🚀
