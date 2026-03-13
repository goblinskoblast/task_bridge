# Архитектура цикла постановки задач через электронную почту

## Содержание
1. [Общий обзор](#общий-обзор)
2. [Визуальная схема процесса](#визуальная-схема-процесса)
3. [Детальное описание этапов](#детальное-описание-этапов)
4. [Сценарии использования](#сценарии-использования)
5. [Обработка ошибок](#обработка-ошибок)
6. [Интеграция с существующими компонентами](#интеграция-с-существующими-компонентами)

---

## Общий обзор

Цикл постановки задач через электронную почту представляет собой автоматизированный процесс преобразования входящих email-сообщений в задачи системы TaskBridge. Процесс включает несколько этапов: получение письма, анализ содержимого, извлечение информации о задаче, создание или предложение задачи, и уведомление участников.

### Основные участники процесса:
- **Отправитель письма** - пользователь, который отправляет письмо с описанием задачи
- **Получатель письма (Email Account)** - настроенный в системе email-аккаунт
- **Владелец аккаунта** - пользователь TaskBridge, к которому привязан email-аккаунт
- **IMAP Client** - компонент для получения писем
- **Email Parser** - компонент для разбора писем
- **AI Analyzer** - AI-модель для извлечения информации о задаче
- **Task Manager** - компонент для создания задач
- **Notification Service** - сервис уведомлений через Telegram

### Ключевые концепции:
- **Автоматическое подтверждение (auto_confirm)** - режим, при котором задачи создаются автоматически без подтверждения
- **Ручное подтверждение** - режим, при котором владелец аккаунта должен подтвердить создание задачи
- **Белый список отправителей** - список email-адресов, письма от которых обрабатываются автоматически

---

## Визуальная схема процесса

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ЦИКЛ ОБРАБОТКИ ПИСЕМ                          │
└─────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐
    │ Отправитель  │
    │   письма     │
    └──────┬───────┘
           │ Отправляет email
           │ с описанием задачи
           ▼
    ┌──────────────────┐
    │  Email Сервер    │
    │ (Gmail, Outlook) │
    └──────┬───────────┘
           │
           │ Периодический опрос (каждые N минут)
           │
    ┌──────▼───────────┐
    │   IMAP Client    │◄──────────────┐
    │  (Подключение    │               │
    │   по IMAP/SSL)   │               │
    └──────┬───────────┘               │
           │                            │
           │ Получает новые письма      │
           │                            │
    ┌──────▼───────────────────────┐   │
    │  Проверка отправителя        │   │
    │  (only_from_addresses)       │   │
    └──────┬───────────────────────┘   │
           │                            │
           ├─ НЕ в белом списке ────────┤ (Пропускаем письмо)
           │                            │
           │ В белом списке или         │
           │ белый список пуст          │
           ▼                            │
    ┌──────────────────┐               │
    │  Email Parser    │               │
    │  - HTML → Text   │               │
    │  - Извлечение    │               │
    │    вложений      │               │
    └──────┬───────────┘               │
           │                            │
           │ Структурированные данные   │
           │ письма                     │
           ▼                            │
    ┌──────────────────────────┐       │
    │     AI Analyzer          │       │
    │  (Claude/GPT API)        │       │
    │                          │       │
    │  Извлекает:              │       │
    │  - Заголовок задачи      │       │
    │  - Описание              │       │
    │  - Приоритет             │       │
    │  - Срок выполнения       │       │
    │  - Категорию             │       │
    │  - Исполнителей          │       │
    └──────┬───────────────────┘       │
           │                            │
           │                            │
    ┌──────▼──────────────────┐        │
    │  Проверка режима        │        │
    │  auto_confirm?          │        │
    └──────┬──────────────────┘        │
           │                            │
           ├─ auto_confirm = true       │
           │                            │
           │      ┌─────────────────┐   │
           │      │ Автоматическое  │   │
           │      │ создание задачи │   │
           │      └────┬────────────┘   │
           │           │                │
           │           ▼                │
           │      ┌──────────────────┐  │
           │      │  Создание Task   │  │
           │      │  в базе данных   │  │
           │      └────┬─────────────┘  │
           │           │                │
           │           ▼                │
           │      ┌──────────────────┐  │
           │      │  Уведомление     │  │
           │      │  исполнителей    │  │
           │      │  в Telegram      │  │
           │      └────┬─────────────┘  │
           │           │                │
           │           └────────────────┼─────► КОНЕЦ
           │                            │
           ├─ auto_confirm = false      │
           │                            │
           ▼                            │
    ┌──────────────────────┐           │
    │  Создание черновика  │           │
    │  задачи (Draft)      │           │
    └──────┬───────────────┘           │
           │                            │
           │                            │
           ▼                            │
    ┌──────────────────────────────┐   │
    │  Уведомление владельца       │   │
    │  аккаунта в Telegram         │   │
    │  с кнопками:                 │   │
    │  - ✅ Подтвердить            │   │
    │  - ✏️ Редактировать          │   │
    │  - ❌ Отклонить              │   │
    └──────┬───────────────────────┘   │
           │                            │
    ┌──────▼──────────┐                │
    │  Ожидание       │                │
    │  решения        │                │
    │  пользователя   │                │
    └──────┬──────────┘                │
           │                            │
           ├──► ✅ Подтверждено         │
           │    │                       │
           │    ▼                       │
           │   ┌──────────────────┐    │
           │   │  Создание Task   │    │
           │   │  в базе данных   │    │
           │   └────┬─────────────┘    │
           │        │                  │
           │        ▼                  │
           │   ┌──────────────────┐    │
           │   │  Уведомление     │    │
           │   │  исполнителей    │    │
           │   └────┬─────────────┘    │
           │        │                  │
           │        └──────────────────┼─────► КОНЕЦ
           │                           │
           ├──► ✏️ Редактировать       │
           │    │                      │
           │    ▼                      │
           │   ┌──────────────────┐    │
           │   │  Открытие формы  │    │
           │   │  редактирования  │    │
           │   │  через WebApp    │    │
           │   └────┬─────────────┘    │
           │        │                  │
           │        ▼                  │
           │   ┌──────────────────┐    │
           │   │  Пользователь    │    │
           │   │  корректирует    │    │
           │   │  данные          │    │
           │   └────┬─────────────┘    │
           │        │                  │
           │        │ Сохраняет        │
           │        │                  │
           │        ├──► Создание Task │
           │        │                  │
           │        └──────────────────┼─────► КОНЕЦ
           │                           │
           └──► ❌ Отклонено            │
                │                      │
                ▼                      │
           ┌──────────────────┐        │
           │  Отметка в БД    │        │
           │  processed=true  │        │
           │  status=rejected │        │
           └────┬─────────────┘        │
                │                      │
                └──────────────────────┼─────► КОНЕЦ
                                       │
    ┌──────────────────────────────────┘
    │  Повтор цикла каждые N минут
    │  (проверка новых писем)
    └────────────────────────────────►

```

---

## Детальное описание этапов

### Этап 1: Получение писем через IMAP

**Что происходит:**
- Фоновый процесс (Background Worker) периодически опрашивает все настроенные email-аккаунты
- Используется IMAP протокол для подключения к почтовому серверу
- Получаются только новые (непрочитанные) письма с момента последней проверки

**Технические детали:**
```python
# Периодичность опроса
CHECK_INTERVAL = 5  # минут

# Подключение
client = IMAPClient(
    server="imap.gmail.com",
    port=993,
    username="user@gmail.com",
    password=decrypt(encrypted_password),
    use_ssl=True
)

# Выборка новых писем
client.select_folder('INBOX')
messages = client.search(['UNSEEN'])
```

**Параметры конфигурации Email Account:**
- `imap_server` - адрес IMAP сервера
- `imap_port` - порт (обычно 993 для SSL)
- `email_address` - адрес почты
- `imap_password_encrypted` - зашифрованный пароль
- `last_check` - временная метка последней проверки
- `enabled` - активен ли аккаунт

**Обработка:**
- Если аккаунт неактивен (`enabled=false`), пропускаем
- Если произошла ошибка подключения, логируем и переходим к следующему аккаунту
- Если новых писем нет, обновляем `last_check` и переходим к следующему аккаунту

---

### Этап 2: Фильтрация по белому списку

**Что происходит:**
- Для каждого полученного письма проверяется адрес отправителя
- Если в аккаунте настроен белый список (`only_from_addresses`), письмо обрабатывается только если отправитель в списке
- Если белый список пуст, обрабатываются письма от всех отправителей

**Логика проверки:**
```python
def should_process_email(email_account, sender_email):
    # Если белый список не настроен, обрабатываем всё
    if not email_account.only_from_addresses:
        return True

    # Проверяем, есть ли отправитель в белом списке
    return sender_email.lower() in [
        addr.lower() for addr in email_account.only_from_addresses
    ]
```

**Примеры использования:**
1. **Личный аккаунт** - белый список пуст, обрабатываются все письма
2. **Корпоративный аккаунт** - в белом списке только внутренние адреса компании
3. **Проектный аккаунт** - в белом списке адреса участников конкретного проекта

**Что происходит с отфильтрованными письмами:**
- Письмо НЕ сохраняется в таблицу `email_messages`
- Письмо НЕ помечается как прочитанное на сервере
- В логах фиксируется информация о пропуске

---

### Этап 3: Парсинг письма (Email Parser)

**Что происходит:**
- Извлекается вся метаинформация письма (отправитель, тема, дата)
- HTML-тело письма конвертируется в plain text
- Извлекаются вложения (если есть)
- Создается структурированный объект с данными письма

**Извлекаемые данные:**
```python
ParsedEmail = {
    "message_id": str,        # Уникальный ID письма
    "from": str,               # Email отправителя
    "from_name": str,          # Имя отправителя
    "subject": str,            # Тема письма
    "date": datetime,          # Дата отправки
    "body_text": str,          # Текст письма (HTML → Text)
    "body_html": str,          # Оригинальный HTML
    "attachments": [
        {
            "filename": str,
            "content_type": str,
            "size": int,
            "data": bytes
        }
    ],
    "in_reply_to": str,        # ID письма, на которое отвечают
    "references": List[str]    # Цепочка переписки
}
```

**Обработка HTML:**
```python
# Используется BeautifulSoup для конвертации HTML → Text
from bs4 import BeautifulSoup

def html_to_text(html_content):
    soup = BeautifulSoup(html_content, 'lxml')

    # Удаляем скрипты и стили
    for script in soup(["script", "style"]):
        script.decompose()

    # Извлекаем текст
    text = soup.get_text()

    # Убираем лишние пробелы и переносы
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)

    return text
```

**Сохранение в БД:**
```python
email_message = EmailMessage(
    email_account_id=account.id,
    message_id=parsed["message_id"],
    sender_email=parsed["from"],
    sender_name=parsed["from_name"],
    subject=parsed["subject"],
    body_text=parsed["body_text"],
    body_html=parsed["body_html"],
    received_at=parsed["date"],
    processed=False,
    processing_status="pending"
)
db.add(email_message)
db.commit()
```

---

### Этап 4: AI-анализ содержимого

**Что происходит:**
- Текст письма отправляется в AI-модель (Claude/GPT)
- AI извлекает структурированную информацию о задаче
- Результат валидируется и дополняется значениями по умолчанию

**Промпт для AI:**
```
Проанализируй следующее email-сообщение и извлеки информацию о задаче.

ПИСЬМО:
От: {sender_name} <{sender_email}>
Тема: {subject}
Дата: {date}

Текст письма:
{body_text}

ЗАДАНИЕ:
Извлеки из письма следующую информацию о задаче в формате JSON:

{
  "title": "Краткое название задачи (макс. 100 символов)",
  "description": "Полное описание задачи",
  "priority": "low | medium | high | urgent",
  "due_date": "YYYY-MM-DD или null если не указан",
  "category": "название категории или null",
  "assignees": ["email1@example.com", "email2@example.com"],
  "confidence": 0.0-1.0  // уверенность в извлеченных данных
}

ПРАВИЛА:
1. Если в письме не указан срок, верни null для due_date
2. Приоритет определяй по содержимому и словам-маркерам (срочно, важно, etc)
3. Исполнителей ищи по упоминаниям имен или email-адресов в тексте
4. Если письмо не содержит описания задачи, верни confidence < 0.5
5. Category старайся подобрать из контекста (разработка, дизайн, тестирование и т.д.)
```

**Пример ответа AI:**
```json
{
  "title": "Исправить баг с авторизацией в мобильном приложении",
  "description": "При попытке войти через Google на iOS приложение вылетает. Нужно исправить обработку callback'а от OAuth провайдера. Проблема появилась после последнего обновления библиотеки react-native-google-signin.",
  "priority": "high",
  "due_date": "2025-12-05",
  "category": "Разработка",
  "assignees": ["developer@company.com"],
  "confidence": 0.92
}
```

**Обработка результата:**
```python
def process_ai_result(ai_response, email_account, email_message):
    # Парсим JSON
    task_data = json.loads(ai_response)

    # Проверка уверенности
    if task_data.get("confidence", 0) < 0.5:
        # Низкая уверенность - требуется ручное подтверждение
        email_account.auto_confirm = False
        logger.warning(f"Low confidence ({task_data['confidence']}) for email {email_message.message_id}")

    # Валидация и значения по умолчанию
    task_data["title"] = task_data.get("title", email_message.subject)[:100]
    task_data["description"] = task_data.get("description", email_message.body_text)
    task_data["priority"] = task_data.get("priority", "medium")

    # Парсинг даты
    if task_data.get("due_date"):
        try:
            task_data["due_date"] = datetime.strptime(task_data["due_date"], "%Y-%m-%d")
        except:
            task_data["due_date"] = None

    # Поиск категории в БД
    if task_data.get("category"):
        category = db.query(Category).filter_by(name=task_data["category"]).first()
        if not category:
            # Создаем новую категорию
            category = Category(name=task_data["category"])
            db.add(category)
            db.commit()
        task_data["category_id"] = category.id

    # Поиск исполнителей
    assignee_ids = []
    for email in task_data.get("assignees", []):
        user = db.query(User).filter_by(email=email).first()
        if user:
            assignee_ids.append(user.id)
        else:
            logger.warning(f"User with email {email} not found in database")

    task_data["assignee_ids"] = assignee_ids

    return task_data
```

**Обработка ошибок AI:**
- Если AI API недоступен, письмо помечается как `processing_status="ai_error"` и будет обработано позже
- Если AI вернул невалидный JSON, используются данные из письма напрямую (тема → title, текст → description)
- Если confidence < 0.5, принудительно включается режим ручного подтверждения

---

### Этап 5: Создание задачи или черновика

**Режим 1: Автоматическое создание (auto_confirm = true)**

```python
def create_task_automatically(task_data, email_account, email_message):
    # Создаем задачу
    task = Task(
        title=task_data["title"],
        description=task_data["description"],
        priority=task_data["priority"],
        due_date=task_data.get("due_date"),
        category_id=task_data.get("category_id"),
        creator_id=email_account.user_id,  # Владелец email-аккаунта
        status="pending",
        created_at=datetime.utcnow()
    )
    db.add(task)
    db.commit()

    # Назначаем исполнителей
    for assignee_id in task_data.get("assignee_ids", []):
        assignment = TaskAssignment(
            task_id=task.id,
            user_id=assignee_id
        )
        db.add(assignment)

    # Прикрепляем вложения
    for attachment in email_message.attachments:
        task_file = TaskFile(
            task_id=task.id,
            file_name=attachment["filename"],
            file_type=attachment["content_type"],
            file_data=attachment["data"],
            uploaded_by_id=email_account.user_id,
            uploaded_at=datetime.utcnow()
        )
        db.add(task_file)

    db.commit()

    # Обновляем статус письма
    email_message.task_id = task.id
    email_message.processed = True
    email_message.processing_status = "completed"
    db.commit()

    return task
```

**Режим 2: Ручное подтверждение (auto_confirm = false)**

```python
def create_task_draft(task_data, email_account, email_message):
    # Создаем черновик задачи (сохраняем в отдельной таблице или JSON)
    task_draft = {
        "title": task_data["title"],
        "description": task_data["description"],
        "priority": task_data["priority"],
        "due_date": task_data.get("due_date").isoformat() if task_data.get("due_date") else None,
        "category_id": task_data.get("category_id"),
        "assignee_ids": task_data.get("assignee_ids", []),
        "email_message_id": email_message.id,
        "created_at": datetime.utcnow().isoformat()
    }

    # Сохраняем черновик в поле email_message
    email_message.draft_task_data = json.dumps(task_draft)
    email_message.processing_status = "awaiting_confirmation"
    db.commit()

    return task_draft
```

---

### Этап 6: Уведомления в Telegram

**Сценарий 1: Автоматическое создание - уведомление исполнителей**

```python
async def notify_new_task_from_email(task_id: int, email_account_id: int):
    task = db.query(Task).get(task_id)
    email_account = db.query(EmailAccount).get(email_account_id)

    # Формируем сообщение
    message = (
        f"📧 <b>Новая задача из письма</b>\n\n"
        f"<b>{task.title}</b>\n\n"
        f"{task.description}\n\n"
        f"📊 Приоритет: {get_priority_text(task.priority)}\n"
    )

    if task.due_date:
        message += f"📅 Срок: {format_date(task.due_date)}\n"

    message += f"\n📨 Создано из письма: {email_account.email_address}"

    # Отправляем всем исполнителям
    for assignment in task.assignments:
        if assignment.user.telegram_id:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text="📋 Открыть задачу",
                    web_app=WebAppInfo(url=f"{WEBAPP_URL}?task_id={task.id}")
                )],
                [InlineKeyboardButton(
                    text="▶️ Начать работу",
                    callback_data=f"task_start_{task.id}"
                )]
            ])

            await bot.send_message(
                chat_id=assignment.user.telegram_id,
                text=message,
                parse_mode="HTML",
                reply_markup=keyboard
            )

    # Уведомляем создателя
    if email_account.user.telegram_id:
        await bot.send_message(
            chat_id=email_account.user.telegram_id,
            text=f"✅ Из письма автоматически создана задача:\n<b>{task.title}</b>",
            parse_mode="HTML"
        )
```

**Сценарий 2: Ручное подтверждение - запрос владельцу аккаунта**

```python
async def request_task_confirmation(email_message_id: int):
    email_message = db.query(EmailMessage).get(email_message_id)
    email_account = email_message.email_account
    task_draft = json.loads(email_message.draft_task_data)

    # Формируем сообщение
    message = (
        f"📧 <b>Новое письмо требует подтверждения</b>\n\n"
        f"От: {email_message.sender_name} <{email_message.sender_email}>\n"
        f"Тема: {email_message.subject}\n\n"
        f"<b>Предлагаемая задача:</b>\n"
        f"📝 Название: {task_draft['title']}\n"
        f"📊 Приоритет: {get_priority_text(task_draft['priority'])}\n"
    )

    if task_draft.get('due_date'):
        message += f"📅 Срок: {task_draft['due_date']}\n"

    message += f"\n{task_draft['description'][:200]}..."

    # Кнопки действий
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Подтвердить",
                callback_data=f"email_confirm_{email_message.id}"
            ),
            InlineKeyboardButton(
                text="✏️ Редактировать",
                callback_data=f"email_edit_{email_message.id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="📄 Показать письмо",
                callback_data=f"email_show_{email_message.id}"
            )
        ],
        [
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"email_reject_{email_message.id}"
            )
        ]
    ])

    # Отправляем владельцу аккаунта
    await bot.send_message(
        chat_id=email_account.user.telegram_id,
        text=message,
        parse_mode="HTML",
        reply_markup=keyboard
    )
```

**Обработка callback'ов:**

```python
# ✅ Подтверждение
@router.callback_query(F.data.startswith("email_confirm_"))
async def handle_confirm_email_task(callback: CallbackQuery):
    email_message_id = int(callback.data.split("_")[2])
    email_message = db.query(EmailMessage).get(email_message_id)

    # Создаем задачу из черновика
    task_draft = json.loads(email_message.draft_task_data)
    task = create_task_from_draft(task_draft)

    # Обновляем статус письма
    email_message.task_id = task.id
    email_message.processed = True
    email_message.processing_status = "completed"
    db.commit()

    # Уведомляем исполнителей
    await notify_new_task_from_email(task.id, email_message.email_account_id)

    await callback.message.edit_text(
        f"✅ Задача создана: <b>{task.title}</b>",
        parse_mode="HTML"
    )

# ✏️ Редактирование
@router.callback_query(F.data.startswith("email_edit_"))
async def handle_edit_email_task(callback: CallbackQuery):
    email_message_id = int(callback.data.split("_")[2])

    # Открываем WebApp с формой редактирования
    webapp_url = f"{WEBAPP_URL}/email-task-editor?email_id={email_message_id}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="✏️ Редактировать задачу",
            web_app=WebAppInfo(url=webapp_url)
        )]
    ])

    await callback.message.edit_reply_markup(reply_markup=keyboard)

# ❌ Отклонение
@router.callback_query(F.data.startswith("email_reject_"))
async def handle_reject_email_task(callback: CallbackQuery):
    email_message_id = int(callback.data.split("_")[2])
    email_message = db.query(EmailMessage).get(email_message_id)

    # Помечаем как отклоненное
    email_message.processed = True
    email_message.processing_status = "rejected"
    db.commit()

    await callback.message.edit_text(
        f"❌ Задача из письма отклонена",
        parse_mode="HTML"
    )
```

---

### Этап 7: Фоновый процесс (Background Worker)

**Основной цикл:**

```python
import asyncio
from apscheduler.schedulers.asyncio import AsyncIOScheduler

class EmailWorker:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.running = False

    async def start(self):
        """Запускает фоновый процесс проверки почты"""
        self.running = True

        # Добавляем задачу в планировщик
        self.scheduler.add_job(
            self.check_all_accounts,
            'interval',
            minutes=5,  # Проверка каждые 5 минут
            id='email_check'
        )

        self.scheduler.start()
        logger.info("Email worker started")

    async def check_all_accounts(self):
        """Проверяет все активные email-аккаунты"""
        try:
            db = SessionLocal()

            # Получаем все активные аккаунты
            accounts = db.query(EmailAccount).filter_by(enabled=True).all()

            logger.info(f"Checking {len(accounts)} email accounts")

            # Обрабатываем аккаунты параллельно
            tasks = [
                self.check_account(account)
                for account in accounts
            ]

            await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"Error in check_all_accounts: {e}")
        finally:
            db.close()

    async def check_account(self, account: EmailAccount):
        """Проверяет один email-аккаунт"""
        try:
            logger.info(f"Checking account: {account.email_address}")

            # Подключаемся к IMAP
            client = IMAPClient(
                server=account.imap_server,
                port=account.imap_port,
                username=account.email_address,
                password=decrypt_password(account.imap_password_encrypted),
                use_ssl=account.use_ssl
            )

            if not client.connect():
                logger.error(f"Failed to connect to {account.email_address}")
                return

            # Получаем новые письма
            messages = client.fetch_new_messages(since=account.last_check)

            logger.info(f"Found {len(messages)} new messages in {account.email_address}")

            # Обрабатываем каждое письмо
            for message_data in messages:
                await self.process_message(account, message_data)

            # Обновляем время последней проверки
            account.last_check = datetime.utcnow()
            db.commit()

            client.disconnect()

        except Exception as e:
            logger.error(f"Error checking account {account.email_address}: {e}")

    async def process_message(self, account: EmailAccount, message_data: dict):
        """Обрабатывает одно письмо"""
        try:
            # Проверяем, не обработано ли уже это письмо
            existing = db.query(EmailMessage).filter_by(
                message_id=message_data["message_id"]
            ).first()

            if existing:
                logger.info(f"Message {message_data['message_id']} already processed")
                return

            # Проверяем белый список
            if not should_process_email(account, message_data["from"]):
                logger.info(f"Sender {message_data['from']} not in whitelist, skipping")
                return

            # Парсим письмо
            parsed_email = parse_email(message_data)

            # Сохраняем в БД
            email_message = EmailMessage(
                email_account_id=account.id,
                message_id=parsed_email["message_id"],
                sender_email=parsed_email["from"],
                sender_name=parsed_email["from_name"],
                subject=parsed_email["subject"],
                body_text=parsed_email["body_text"],
                body_html=parsed_email["body_html"],
                received_at=parsed_email["date"],
                processed=False,
                processing_status="pending"
            )
            db.add(email_message)
            db.commit()

            # AI-анализ
            task_data = await analyze_email_with_ai(parsed_email)

            # Создание задачи или черновика
            if account.auto_confirm and task_data.get("confidence", 0) >= 0.5:
                task = create_task_automatically(task_data, account, email_message)
                await notify_new_task_from_email(task.id, account.id)
            else:
                task_draft = create_task_draft(task_data, account, email_message)
                await request_task_confirmation(email_message.id)

            logger.info(f"Successfully processed message {email_message.message_id}")

        except Exception as e:
            logger.error(f"Error processing message: {e}")

            # Помечаем как ошибку
            if 'email_message' in locals():
                email_message.processing_status = "error"
                email_message.error_message = str(e)
                db.commit()

# Запуск worker'а
worker = EmailWorker()
asyncio.create_task(worker.start())
```

---

## Сценарии использования

### Сценарий 1: Личный аккаунт с автоподтверждением

**Настройка:**
- Email: personal@gmail.com
- auto_confirm: true
- only_from_addresses: [] (пусто - принимаем от всех)

**Процесс:**
1. Пользователь получает письмо от друга: "Не забудь купить молоко завтра"
2. Система получает письмо через IMAP
3. AI анализирует:
   ```json
   {
     "title": "Купить молоко",
     "description": "Не забудь купить молоко завтра",
     "priority": "low",
     "due_date": "2025-12-01",
     "confidence": 0.85
   }
   ```
4. Задача создается автоматически
5. Пользователь получает уведомление в Telegram: "✅ Из письма автоматически создана задача: Купить молоко"

---

### Сценарий 2: Корпоративный аккаунт с белым списком

**Настройка:**
- Email: manager@company.com
- auto_confirm: false
- only_from_addresses: ["boss@company.com", "client@partner.com"]

**Процесс:**
1. Босс отправляет письмо:
   ```
   Тема: Срочно подготовить презентацию

   Привет! Нужно подготовить презентацию для клиента к пятнице.
   Включи туда статистику продаж за последний квартал и прогноз на следующий.
   Важно - это критичный клиент.
   ```

2. Система получает письмо (босс в белом списке)

3. AI анализирует:
   ```json
   {
     "title": "Подготовить презентацию для клиента",
     "description": "Включить статистику продаж за последний квартал и прогноз на следующий. Критичный клиент.",
     "priority": "high",
     "due_date": "2025-12-05",
     "category": "Презентации",
     "confidence": 0.95
   }
   ```

4. Создается черновик задачи

5. Менеджер получает уведомление в Telegram с кнопками:
   - ✅ Подтвердить
   - ✏️ Редактировать
   - ❌ Отклонить

6. Менеджер нажимает "✏️ Редактировать"

7. Открывается WebApp с формой, где он:
   - Добавляет исполнителя (коллега из отдела маркетинга)
   - Корректирует срок на четверг (чтобы был запас)
   - Сохраняет

8. Задача создается, исполнитель получает уведомление

---

### Сценарий 3: Проектный аккаунт с вложениями

**Настройка:**
- Email: project-alpha@company.com
- auto_confirm: true
- only_from_addresses: ["dev1@company.com", "dev2@company.com", "qa@company.com"]

**Процесс:**
1. QA-инженер отправляет письмо с багрепортом:
   ```
   Тема: [BUG] Вылетает приложение на iOS

   При попытке войти через Google на iOS 18 приложение крашится.
   Шаги воспроизведения в прикрепленном скриншоте.

   Вложения:
   - crash_screenshot.png
   - crash_log.txt
   ```

2. Система получает письмо и вложения

3. AI анализирует (включая упоминание вложений):
   ```json
   {
     "title": "[BUG] Вылетает приложение на iOS",
     "description": "При попытке войти через Google на iOS 18 приложение крашится. Шаги воспроизведения в прикрепленных файлах.",
     "priority": "high",
     "category": "Баги",
     "assignees": ["dev1@company.com"],
     "confidence": 0.90
   }
   ```

4. Задача создается автоматически с прикрепленными файлами

5. dev1@company.com получает уведомление:
   ```
   📧 Новая задача из письма

   [BUG] Вылетает приложение на iOS

   При попытке войти через Google на iOS 18 приложение крашится.

   📊 Приоритет: Высокий
   📎 Вложения: 2

   📨 Создано из письма: project-alpha@company.com
   ```

---

### Сценарий 4: Цепочка переписки

**Ситуация:**
- В проекте идет обсуждение фичи по email
- Несколько писем туда-обратно
- В последнем письме появляется конкретная задача

**Процесс:**
1. Первое письмо (обсуждение):
   ```
   Тема: Новая фича - dark mode
   Что думаете о добавлении темной темы?
   ```
   AI confidence: 0.3 → не создаем задачу (просто обсуждение)

2. Второе письмо (уточнение):
   ```
   Re: Новая фича - dark mode
   Хорошая идея! Давайте сделаем это в следующем спринте.
   ```
   AI confidence: 0.4 → не создаем задачу

3. Третье письмо (конкретная задача):
   ```
   Re: Новая фича - dark mode
   Отлично! Тогда давай ты сделаешь это к следующей пятнице.
   Нужно:
   - Добавить переключатель в настройках
   - Создать темную цветовую схему
   - Протестировать на всех экранах
   ```

   AI анализирует с учетом контекста цепочки:
   ```json
   {
     "title": "Реализовать dark mode",
     "description": "Нужно:\n- Добавить переключатель в настройках\n- Создать темную цветовую схему\n- Протестировать на всех экранах",
     "priority": "medium",
     "due_date": "2025-12-12",
     "category": "Разработка",
     "confidence": 0.88
   }
   ```

   Задача создается!

---

## Обработка ошибок

### Ошибки подключения к IMAP

**Типы ошибок:**
- Неверный пароль
- Сервер недоступен
- Таймаут подключения
- SSL/TLS ошибки

**Обработка:**
```python
async def check_account_with_error_handling(account: EmailAccount):
    try:
        client = IMAPClient(...)
        if not client.connect():
            raise ConnectionError("Failed to connect")

        # ... обработка писем ...

    except imaplib.IMAP4.error as e:
        # Ошибка аутентификации
        logger.error(f"IMAP auth error for {account.email_address}: {e}")

        account.last_error = "Ошибка аутентификации. Проверьте пароль."
        account.error_count += 1

        # После 5 ошибок подряд - отключаем аккаунт
        if account.error_count >= 5:
            account.enabled = False
            await notify_account_disabled(account)

        db.commit()

    except ConnectionError as e:
        # Сервер недоступен
        logger.warning(f"Connection error for {account.email_address}: {e}")

        account.last_error = "Сервер недоступен. Повторная попытка через 5 минут."
        db.commit()

    except Exception as e:
        # Неожиданная ошибка
        logger.exception(f"Unexpected error for {account.email_address}")

        account.last_error = str(e)
        db.commit()
```

**Уведомление пользователя:**
```python
async def notify_account_disabled(account: EmailAccount):
    if account.user.telegram_id:
        message = (
            f"⚠️ <b>Email-аккаунт отключен</b>\n\n"
            f"Аккаунт <code>{account.email_address}</code> был автоматически отключен "
            f"после 5 неудачных попыток подключения.\n\n"
            f"Последняя ошибка: {account.last_error}\n\n"
            f"Пожалуйста, проверьте настройки и включите аккаунт вручную."
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="⚙️ Настройки email",
                web_app=WebAppInfo(url=f"{WEBAPP_URL}/email-accounts")
            )]
        ])

        await bot.send_message(
            chat_id=account.user.telegram_id,
            text=message,
            parse_mode="HTML",
            reply_markup=keyboard
        )
```

---

### Ошибки AI-анализа

**Типы ошибок:**
- API недоступен
- Лимит запросов исчерпан
- Невалидный ответ
- Таймаут

**Обработка:**
```python
async def analyze_email_with_ai(email_data: dict, retry_count: int = 0):
    try:
        response = await ai_client.analyze(email_data)
        return json.loads(response)

    except AIServiceUnavailable:
        # API недоступен - повторим позже
        if retry_count < 3:
            await asyncio.sleep(60)  # Ждем 1 минуту
            return await analyze_email_with_ai(email_data, retry_count + 1)
        else:
            # Фоллбэк - используем простую эвристику
            return fallback_email_analysis(email_data)

    except AIRateLimitError:
        # Исчерпан лимит - используем фоллбэк
        logger.warning("AI rate limit exceeded, using fallback")
        return fallback_email_analysis(email_data)

    except json.JSONDecodeError:
        # Невалидный JSON - используем фоллбэк
        logger.error("AI returned invalid JSON")
        return fallback_email_analysis(email_data)

def fallback_email_analysis(email_data: dict):
    """Простой анализ без AI"""
    # Используем тему письма как название задачи
    title = email_data["subject"]

    # Определяем приоритет по ключевым словам
    text_lower = email_data["body_text"].lower()
    if any(word in text_lower for word in ["срочно", "urgent", "asap", "критично"]):
        priority = "high"
    elif any(word in text_lower for word in ["важно", "important"]):
        priority = "medium"
    else:
        priority = "low"

    # Ищем дату
    due_date = extract_date_from_text(email_data["body_text"])

    return {
        "title": title,
        "description": email_data["body_text"],
        "priority": priority,
        "due_date": due_date,
        "confidence": 0.4  # Низкая уверенность без AI
    }
```

---

### Ошибки создания задачи

**Типы ошибок:**
- Дублирование задачи
- Невалидные данные
- Несуществующая категория
- Несуществующий исполнитель

**Обработка:**
```python
def create_task_with_validation(task_data: dict, email_message: EmailMessage):
    try:
        # Проверка на дубликаты (по message_id)
        existing_task = db.query(Task).join(EmailMessage).filter(
            EmailMessage.message_id == email_message.message_id
        ).first()

        if existing_task:
            logger.warning(f"Task already exists for email {email_message.message_id}")
            return existing_task

        # Валидация данных
        if not task_data.get("title"):
            raise ValueError("Title is required")

        if len(task_data["title"]) > 200:
            task_data["title"] = task_data["title"][:197] + "..."

        # Проверка категории
        if task_data.get("category_id"):
            category = db.query(Category).get(task_data["category_id"])
            if not category:
                logger.warning(f"Category {task_data['category_id']} not found")
                task_data["category_id"] = None

        # Проверка исполнителей
        valid_assignee_ids = []
        for assignee_id in task_data.get("assignee_ids", []):
            user = db.query(User).get(assignee_id)
            if user:
                valid_assignee_ids.append(assignee_id)
            else:
                logger.warning(f"User {assignee_id} not found")

        task_data["assignee_ids"] = valid_assignee_ids

        # Создание задачи
        task = Task(...)
        db.add(task)
        db.commit()

        return task

    except Exception as e:
        logger.error(f"Error creating task: {e}")
        db.rollback()

        # Помечаем письмо как ошибочное
        email_message.processing_status = "task_creation_error"
        email_message.error_message = str(e)
        db.commit()

        # Уведомляем владельца аккаунта
        asyncio.create_task(
            notify_task_creation_error(email_message.email_account_id, email_message.id, str(e))
        )

        return None
```

---

## Интеграция с существующими компонентами

### 1. Интеграция с Telegram Bot

**Компонент:** `bot/handlers.py`

**Новые команды:**
```python
@router.message(Command("email"))
async def cmd_email_settings(message: Message):
    """Управление email-аккаунтами"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="⚙️ Настроить email",
            web_app=WebAppInfo(url=f"{WEBAPP_URL}/email-accounts")
        )],
        [InlineKeyboardButton(
            text="📊 Статистика обработки",
            callback_data="email_stats"
        )]
    ])

    await message.answer(
        "📧 <b>Управление email-интеграцией</b>\n\n"
        "Настройте email-аккаунты для автоматического создания задач из писем.",
        parse_mode="HTML",
        reply_markup=keyboard
    )

@router.callback_query(F.data == "email_stats")
async def show_email_stats(callback: CallbackQuery):
    """Показывает статистику обработки писем"""
    user = db.query(User).filter_by(telegram_id=callback.from_user.id).first()

    stats = db.query(EmailMessage).join(EmailAccount).filter(
        EmailAccount.user_id == user.id
    ).count()

    processed = db.query(EmailMessage).join(EmailAccount).filter(
        EmailAccount.user_id == user.id,
        EmailMessage.processed == True
    ).count()

    tasks_created = db.query(Task).join(EmailMessage).join(EmailAccount).filter(
        EmailAccount.user_id == user.id
    ).count()

    message = (
        f"📊 <b>Статистика обработки писем</b>\n\n"
        f"📨 Всего получено: {stats}\n"
        f"✅ Обработано: {processed}\n"
        f"📋 Создано задач: {tasks_created}\n"
    )

    await callback.message.edit_text(message, parse_mode="HTML")
```

**Уведомления:**
- При создании задачи из письма (автоматически)
- При запросе подтверждения задачи (ручной режим)
- При ошибке обработки письма
- При отключении email-аккаунта из-за ошибок

---

### 2. Интеграция с WebApp

**Компонент:** `webapp/src/`

**Новые страницы:**

1. **Email Accounts Management** (`/email-accounts`)
   - Список email-аккаунтов
   - Добавление нового аккаунта
   - Редактирование настроек
   - Включение/отключение аккаунтов

2. **Email Task Editor** (`/email-task-editor`)
   - Форма редактирования задачи из письма
   - Предпросмотр письма
   - Выбор исполнителей, категории, приоритета

3. **Email Statistics** (`/email-stats`)
   - График обработки писем
   - Список последних писем
   - Фильтры по статусу обработки

**Новые API endpoints:**

```python
# Управление email-аккаунтами
@app.get("/api/email-accounts")
async def get_email_accounts(user_id: int):
    """Получить список email-аккаунтов пользователя"""
    pass

@app.post("/api/email-accounts")
async def create_email_account(account_data: dict):
    """Создать новый email-аккаунт"""
    pass

@app.patch("/api/email-accounts/{account_id}")
async def update_email_account(account_id: int, updates: dict):
    """Обновить настройки email-аккаунта"""
    pass

@app.delete("/api/email-accounts/{account_id}")
async def delete_email_account(account_id: int):
    """Удалить email-аккаунт"""
    pass

# Работа с письмами
@app.get("/api/email-messages")
async def get_email_messages(user_id: int, filters: dict):
    """Получить список писем"""
    pass

@app.get("/api/email-messages/{message_id}")
async def get_email_message(message_id: int):
    """Получить детали письма"""
    pass

@app.post("/api/email-messages/{message_id}/create-task")
async def create_task_from_email(message_id: int, task_data: dict):
    """Создать задачу из письма"""
    pass

@app.post("/api/email-messages/{message_id}/reject")
async def reject_email(message_id: int):
    """Отклонить создание задачи из письма"""
    pass

# Статистика
@app.get("/api/email-stats")
async def get_email_stats(user_id: int):
    """Получить статистику обработки писем"""
    pass
```

---

### 3. Интеграция с базой данных

**Компонент:** `db/models.py`

**Новые модели:**
- `EmailAccount` - настройки email-аккаунтов
- `EmailMessage` - полученные письма

**Связи с существующими моделями:**
```
EmailAccount.user_id → User.id
EmailMessage.email_account_id → EmailAccount.id
EmailMessage.task_id → Task.id
Task.creator_id → User.id (владелец email-аккаунта)
```

**Миграции:**
```bash
# Создание таблиц
alembic revision --autogenerate -m "Add email integration tables"
alembic upgrade head
```

---

### 4. Интеграция с системой уведомлений

**Компонент:** `bot/notifications.py`

**Новые функции уведомлений:**
```python
# Уведомление о новой задаче из письма
async def notify_new_task_from_email(task_id, email_account_id)

# Запрос подтверждения задачи
async def request_task_confirmation(email_message_id)

# Уведомление об ошибке обработки
async def notify_task_creation_error(account_id, message_id, error)

# Уведомление об отключении аккаунта
async def notify_account_disabled(account)
```

---

### 5. Фоновые процессы

**Новый компонент:** `email_integration/worker.py`

**Запуск:**
```python
# В main.py или отдельном процессе
from email_integration.worker import EmailWorker

async def start_email_worker():
    worker = EmailWorker()
    await worker.start()

# При старте приложения
asyncio.create_task(start_email_worker())
```

**Мониторинг:**
- Логирование всех операций
- Метрики (количество обработанных писем, ошибки, время обработки)
- Health check endpoint для проверки работоспособности

---

## Диаграмма состояний письма

```
┌──────────┐
│  НОВОЕ   │  (письмо получено)
│ ПИСЬМО   │
└────┬─────┘
     │
     ▼
┌──────────────┐
│   pending    │  (ожидает обработки)
└────┬─────────┘
     │
     ├─► NOT IN WHITELIST ──► (пропускается, не сохраняется)
     │
     ▼
┌──────────────┐
│   parsing    │  (парсинг HTML, вложений)
└────┬─────────┘
     │
     ├─► PARSE ERROR ──► error (сохраняется для повторной попытки)
     │
     ▼
┌──────────────┐
│ ai_analysis  │  (анализ AI)
└────┬─────────┘
     │
     ├─► AI ERROR ──► ai_error (повторная попытка через 5 мин)
     │
     ▼
┌───────────────────┐
│  Проверка режима  │
└────┬──────────────┘
     │
     ├─► auto_confirm = true ────────┐
     │                                │
     │                                ▼
     │                       ┌──────────────┐
     │                       │ auto_created │
     │                       └──────┬───────┘
     │                              │
     │                              ▼
     │                       ┌──────────────┐
     │                       │  completed   │ ✅
     │                       └──────────────┘
     │
     ├─► auto_confirm = false
     │
     ▼
┌────────────────────┐
│ awaiting_confirmation │  (ждет решения пользователя)
└────┬────────────────┘
     │
     ├─► ✅ Подтверждено ────────► confirmed ──► completed ✅
     │
     ├─► ✏️ Редактирование ──► editing ──► confirmed ──► completed ✅
     │
     └─► ❌ Отклонено ────────────► rejected ❌
```

---

## Заключение

Цикл постановки задач через электронную почту представляет собой полностью автоматизированный процесс, который:

1. **Непрерывно мониторит** настроенные email-аккаунты через IMAP
2. **Фильтрует** письма по белому списку отправителей
3. **Анализирует** содержимое с помощью AI для извлечения информации о задаче
4. **Создает** задачи автоматически или предлагает на подтверждение
5. **Уведомляет** всех участников процесса через Telegram
6. **Обрабатывает ошибки** на каждом этапе с механизмами повторных попыток

Этот процесс интегрируется со всеми существующими компонентами TaskBridge:
- Telegram Bot для уведомлений и управления
- WebApp для настройки и редактирования
- База данных для хранения писем и связи с задачами
- Система уведомлений для информирования пользователей

Гибкая настройка (белый список, автоподтверждение, категории) позволяет адаптировать процесс под различные сценарии использования - от личного планирования до корпоративного управления задачами.
