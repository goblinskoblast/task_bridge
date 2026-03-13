# Email Integration (IMAP) - Техническая спецификация

## Обзор

Интеграция с email позволит пользователям создавать задачи, отправляя письма на специальный адрес или подключив свой почтовый ящик. Система будет автоматически анализировать письма с помощью AI и создавать задачи.

## Архитектура

### Компоненты системы

```
┌─────────────────┐
│  Email Server   │
│   (IMAP/SMTP)   │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│   IMAP Client Service   │
│  - Подключение к IMAP   │
│  - Чтение новых писем   │
│  - Парсинг содержимого  │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│   Email Parser (AI)     │
│  - Извлечение задачи    │
│  - Определение приорит. │
│  - Парсинг дедлайна     │
│  - Извлечение вложений  │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│   Task Creation API     │
│  - Создание задачи      │
│  - Уведомления          │
│  - Сохранение вложений  │
└─────────────────────────┘
```

## Модель данных

### EmailAccount (новая таблица)

```python
class EmailAccount(Base):
    __tablename__ = "email_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    email_address = Column(String, nullable=False, unique=True)

    # IMAP настройки
    imap_server = Column(String, nullable=False)
    imap_port = Column(Integer, default=993)
    imap_username = Column(String, nullable=False)
    imap_password_encrypted = Column(String, nullable=False)  # Зашифрован
    use_ssl = Column(Boolean, default=True)

    # Настройки обработки
    folder = Column(String, default="INBOX")
    is_active = Column(Boolean, default=True)
    last_checked = Column(DateTime, nullable=True)
    last_uid = Column(Integer, default=0)  # Последний обработанный UID

    # Фильтры
    only_from_addresses = Column(JSON, nullable=True)  # Список разрешенных отправителей
    subject_keywords = Column(JSON, nullable=True)  # Ключевые слова в теме
    auto_confirm = Column(Boolean, default=False)  # Автоматическое подтверждение

    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="email_accounts")
    tasks_from_email = relationship("Task", back_populates="email_source")
```

### EmailMessage (история обработанных писем)

```python
class EmailMessage(Base):
    __tablename__ = "email_messages"

    id = Column(Integer, primary_key=True)
    email_account_id = Column(Integer, ForeignKey("email_accounts.id"))

    # Email метаданные
    message_id = Column(String, unique=True, nullable=False)
    uid = Column(Integer, nullable=False)
    subject = Column(String)
    from_address = Column(String, nullable=False)
    to_address = Column(String)
    date = Column(DateTime)

    # Содержимое
    body_text = Column(Text)
    body_html = Column(Text)
    has_attachments = Column(Boolean, default=False)

    # Обработка
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    email_account = relationship("EmailAccount")
    task = relationship("Task", back_populates="email_source")
```

### Обновление модели Task

```python
# Добавить в Task
email_source_id = Column(Integer, ForeignKey("email_messages.id"), nullable=True)
email_source = relationship("EmailMessage", back_populates="task")
```

## Функциональность

### 1. Подключение email аккаунта

**Endpoint:** `POST /api/email-accounts`

```json
{
  "email_address": "user@example.com",
  "imap_server": "imap.gmail.com",
  "imap_port": 993,
  "imap_username": "user@example.com",
  "imap_password": "app-password",
  "folder": "INBOX",
  "only_from_addresses": ["boss@company.com"],
  "auto_confirm": false
}
```

**Безопасность:**
- Пароли шифруются с помощью `cryptography.fernet`
- Хранение ключа шифрования в переменных окружения
- Проверка подключения перед сохранением

### 2. IMAP Polling Service

**Реализация:**
- Асинхронный background worker на `asyncio`
- Периодическая проверка новых писем (каждые 1-5 минут)
- Использование IDLE команды для real-time уведомлений (опционально)

**Алгоритм:**
```python
async def check_new_emails(email_account):
    1. Подключиться к IMAP серверу
    2. Выбрать папку (INBOX)
    3. Получить UIDs новых писем (UID > last_uid)
    4. Для каждого письма:
       a. Скачать заголовки и тело
       b. Проверить фильтры (from_address, subject)
       c. Парсить письмо
       d. Отправить на AI анализ
       e. Создать задачу или pending_task
       f. Обновить last_uid
    5. Сохранить last_checked
```

### 3. Email Parser

**HTML to Text:**
- Использование `beautifulsoup4` для извлечения текста из HTML
- Удаление цитирований и подписей
- Сохранение форматирования списков

**Attachments:**
- Скачивание вложений
- Сохранение в `data/email_attachments/`
- Создание записей TaskFile

### 4. AI анализ писем

**Prompt для Claude:**
```
Analyze this email and extract task information.

EMAIL:
From: {from_address}
Subject: {subject}
Date: {date}

{body}

Extract:
1. Task description (clear, concise summary)
2. Assignee (email or name mentioned)
3. Priority (urgent/high/normal/low based on keywords and tone)
4. Deadline (any time references)
5. Category (based on content)

Return JSON format.
```

**Особенности:**
- Распознавание срочности по ключевым словам (ASAP, urgent, срочно)
- Извлечение дедлайнов из естественного языка
- Определение исполнителя по упоминаниям в тексте
- Категоризация на основе содержания

### 5. Создание задач из email

**Режимы работы:**

1. **Автоматическое подтверждение** (`auto_confirm = true`)
   - Задача создается сразу
   - Уведомление отправляется исполнителю
   - Отправителю приходит email с подтверждением

2. **Ручное подтверждение** (`auto_confirm = false`)
   - Создается PendingTask
   - Владельцу email аккаунта отправляется уведомление в Telegram
   - Кнопки подтверждения/редактирования/отклонения

**Уведомления:**
- Email отправителю с подтверждением создания задачи
- Telegram уведомление владельцу аккаунта
- Telegram уведомление исполнителю

## API Endpoints

### Email Accounts

```
POST   /api/email-accounts          - Создать email аккаунт
GET    /api/email-accounts          - Список аккаунтов пользователя
GET    /api/email-accounts/{id}     - Получить аккаунт
PATCH  /api/email-accounts/{id}     - Обновить настройки
DELETE /api/email-accounts/{id}     - Удалить аккаунт
POST   /api/email-accounts/{id}/test - Проверить подключение
POST   /api/email-accounts/{id}/sync - Ручная синхронизация
```

### Email Messages

```
GET    /api/email-messages          - История обработанных писем
GET    /api/email-messages/{id}     - Детали письма
POST   /api/email-messages/{id}/retry - Повторная обработка
```

## UI Components

### 1. Страница настроек Email

**Компоненты:**
- Список подключенных email аккаунтов
- Форма добавления нового аккаунта
- Настройки фильтров и автоподтверждения
- Статус последней синхронизации
- Кнопка тестирования подключения

### 2. История обработанных писем

**Таблица с колонками:**
- Дата получения
- Отправитель
- Тема
- Статус обработки
- Созданная задача (ссылка)
- Ошибки (если были)

### 3. Карточка задачи из email

**Дополнительная информация:**
- Бейдж "Создано из email"
- Ссылка на исходное письмо
- Отправитель письма
- Время получения

## Безопасность

### 1. Шифрование паролей

```python
from cryptography.fernet import Fernet

# В config.py
EMAIL_ENCRYPTION_KEY = os.getenv("EMAIL_ENCRYPTION_KEY")
cipher = Fernet(EMAIL_ENCRYPTION_KEY)

def encrypt_password(password: str) -> str:
    return cipher.encrypt(password.encode()).decode()

def decrypt_password(encrypted: str) -> str:
    return cipher.decrypt(encrypted.encode()).decode()
```

### 2. Rate Limiting

- Ограничение частоты проверки писем (не чаще 1 раз в минуту)
- Ограничение количества email аккаунтов на пользователя (5-10)

### 3. Валидация

- Проверка IMAP подключения перед сохранением
- Валидация email адресов
- Санитизация HTML содержимого

## Настройки для популярных провайдеров

### Gmail

```
IMAP Server: imap.gmail.com
Port: 993
SSL: Yes
Note: Требуется App Password (не обычный пароль)
```

### Outlook/Hotmail

```
IMAP Server: outlook.office365.com
Port: 993
SSL: Yes
```

### Mail.ru

```
IMAP Server: imap.mail.ru
Port: 993
SSL: Yes
```

### Yandex

```
IMAP Server: imap.yandex.ru
Port: 993
SSL: Yes
Note: Требуется включить IMAP в настройках
```

## Технические зависимости

```python
# requirements.txt
imapclient==3.0.1         # IMAP клиент
email-validator==2.1.0    # Валидация email
beautifulsoup4==4.12.3    # Парсинг HTML
lxml==5.1.0               # Парсер для beautifulsoup
cryptography==42.0.0      # Шифрование паролей
python-dateutil==2.8.2    # Парсинг дат из писем
```

## Дополнительные возможности (Future)

### 1. SMTP для отправки

- Отправка уведомлений через email
- Ответы на письма с обновлениями задачи
- Еженедельные дайджесты

### 2. Умные правила

- Автоматическое назначение исполнителя по домену email
- Автоматическая категоризация по папкам IMAP
- Шаблоны обработки для разных типов писем

### 3. OAuth интеграция

- Gmail OAuth 2.0
- Microsoft OAuth 2.0
- Более безопасная авторизация без паролей

### 4. Email -> Task conversation threading

- Ответы на email обновляют задачу
- Комментарии в задаче отправляются как reply на email
- Полная двусторонняя синхронизация

## План реализации

### Фаза 1: Основа (1-2 недели)
- [ ] Модели данных (EmailAccount, EmailMessage)
- [ ] Миграции БД
- [ ] Шифрование паролей
- [ ] Базовый IMAP клиент

### Фаза 2: AI парсинг (1 неделя)
- [ ] Email parser (HTML -> Text)
- [ ] AI prompt для анализа писем
- [ ] Извлечение вложений
- [ ] Создание задач из писем

### Фаза 3: Background Service (1 неделя)
- [ ] Асинхронный polling service
- [ ] Обработка очереди писем
- [ ] Error handling и retry логика
- [ ] Логирование и мониторинг

### Фаза 4: API и UI (1-2 недели)
- [ ] REST API endpoints
- [ ] Страница настроек email
- [ ] История обработанных писем
- [ ] Тестирование подключений

### Фаза 5: Тестирование и доработки (1 неделя)
- [ ] Unit тесты
- [ ] Integration тесты
- [ ] Тестирование с разными провайдерами
- [ ] Документация

**Общее время:** 5-7 недель

## Метрики успеха

- Успешная обработка 95%+ писем
- Создание задач в течение 5 минут после получения письма
- Точность AI извлечения > 80%
- Отсутствие дубликатов задач
- Безопасное хранение credentials
