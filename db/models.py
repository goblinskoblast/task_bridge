from sqlalchemy import Column, Integer, BigInteger, String, Text, DateTime, Boolean, ForeignKey, JSON, Table, LargeBinary
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


# Промежуточная таблица для связи многие-ко-многим между Task и User (исполнители)
task_assignees = Table(
    'task_assignees',
    Base.metadata,
    Column('task_id', Integer, ForeignKey('tasks.id', ondelete='CASCADE'), primary_key=True),
    Column('user_id', Integer, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
    Column('assigned_at', DateTime, default=datetime.utcnow)
)


class Chat(Base):
    """Модель чата, в котором работает бот"""
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, unique=True, nullable=False, index=True)
    chat_type = Column(String(50), nullable=False)  # private, group, supergroup, channel
    title = Column(String(500), nullable=True)  # Название группы/канала
    username = Column(String(255), nullable=True)  # Username чата (если есть)

    # Метаданные
    is_active = Column(Boolean, default=True)  # Активен ли бот в этом чате
    added_at = Column(DateTime, default=datetime.utcnow)  # Когда бот был добавлен
    removed_at = Column(DateTime, nullable=True)  # Когда бот был удален (если был)

    # Настройки чата
    auto_confirm_tasks = Column(Boolean, default=False)  # Автоподтверждение задач для этого чата

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Chat(chat_id={self.chat_id}, type={self.chat_type}, title={self.title})>"


class User(Base):

    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    is_bot = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Связи
    messages = relationship("Message", back_populates="user")
    assigned_tasks = relationship("Task", secondary=task_assignees, back_populates="assignees")
    created_tasks = relationship("Task", foreign_keys="Task.created_by", back_populates="creator")

    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, username={self.username})>"


class Message(Base):
    
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    message_id = Column(BigInteger, nullable=False)
    chat_id = Column(BigInteger, nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    text = Column(Text, nullable=True)
    date = Column(DateTime, nullable=False)
    has_task = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    
    user = relationship("User", back_populates="messages")
    tasks = relationship("Task", back_populates="message")

    def __repr__(self):
        return f"<Message(message_id={self.message_id}, chat_id={self.chat_id})>"


class Category(Base):
    """Модель категории задач"""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    keywords = Column(JSON, nullable=True)  # Список ключевых слов для автоматической классификации
    created_at = Column(DateTime, default=datetime.utcnow)

    
    tasks = relationship("Task", back_populates="category")

    def __repr__(self):
        return f"<Category(name={self.name})>"


class Task(Base):
    """Модель задачи"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)  # Кто создал задачу
    assigned_to = Column(Integer, ForeignKey("users.id"), nullable=True)  # DEPRECATED: используйте assignees
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), default="pending")  # pending, in_progress, completed, cancelled
    priority = Column(String(50), default="normal")  # low, normal, high, urgent
    due_date = Column(DateTime, nullable=True)
    reminder_interval_hours = Column(Integer, nullable=True)  # NULL = default by priority
    last_assignee_reminder_sent_at = Column(DateTime, nullable=True)
    last_creator_reminder_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связи
    message = relationship("Message", back_populates="tasks")
    category = relationship("Category", back_populates="tasks")
    assignees = relationship("User", secondary=task_assignees, back_populates="assigned_tasks")  # Множественные исполнители
    creator = relationship("User", foreign_keys=[created_by], back_populates="created_tasks")
    files = relationship("TaskFile", backref="task", cascade="all, delete-orphan")
    comments = relationship("Comment", backref="task", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Task(id={self.id}, title={self.title}, status={self.status})>"


class PendingTask(Base):
    """Модель задачи, ожидающей подтверждения руководителем"""
    __tablename__ = "pending_tasks"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False)
    chat_id = Column(BigInteger, nullable=False)  # ID группового чата
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # Кто написал сообщение

    # Данные задачи
    title = Column(String(500), nullable=False)
    description = Column(Text, nullable=True)
    assignee_username = Column(String(255), nullable=True)  # DEPRECATED: один исполнитель
    assignee_usernames = Column(JSON, nullable=True)  # Список username исполнителей ["user1", "user2"]
    due_date = Column(DateTime, nullable=True)
    priority = Column(String(50), default="normal")

    # Статус подтверждения
    status = Column(String(50), default="pending")  # pending, confirmed, rejected
    telegram_message_id = Column(BigInteger, nullable=True)  # ID сообщения с кнопками подтверждения

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<PendingTask(id={self.id}, title={self.title}, status={self.status})>"


class TaskFile(Base):
    """Модель файла, прикрепленного к задаче (отчёт исполнителя)"""
    __tablename__ = "task_files"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    
    file_type = Column(String(50), nullable=False)  # photo, document, video
    file_id = Column(String(500), nullable=False)  # Telegram file_id
    file_name = Column(String(500), nullable=True)  # Имя файла (для документов)
    file_size = Column(Integer, nullable=True)  # Размер в байтах
    mime_type = Column(String(100), nullable=True)  # MIME type

    
    caption = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<TaskFile(id={self.id}, task_id={self.task_id}, type={self.file_type})>"


class Comment(Base):
    """Модель комментария к задаче"""
    __tablename__ = "comments"

    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey("tasks.id", ondelete='CASCADE'), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Связи
    user = relationship("User", backref="comments")

    def __repr__(self):
        return f"<Comment(id={self.id}, task_id={self.task_id}, user_id={self.user_id})>"


class EmailAccount(Base):
    """Модель email аккаунта для IMAP интеграции"""
    __tablename__ = "email_accounts"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete='CASCADE'), nullable=False)
    email_address = Column(String(255), nullable=False, unique=True)

    # IMAP настройки
    imap_server = Column(String(255), nullable=False)
    imap_port = Column(Integer, default=993)
    imap_username = Column(String(255), nullable=False)
    imap_password = Column(Text, nullable=False)  # Пароль приложения (App Password)
    use_ssl = Column(Boolean, default=True)

    # Настройки обработки
    folder = Column(String(100), default="INBOX")
    is_active = Column(Boolean, default=True)
    last_checked = Column(DateTime, nullable=True)
    last_uid = Column(Integer, default=0)  # Последний обработанный UID

    # Фильтры
    only_from_addresses = Column(JSON, nullable=True)  # Список разрешенных отправителей
    subject_keywords = Column(JSON, nullable=True)  # Ключевые слова в теме
    auto_confirm = Column(Boolean, default=False)  # Автоматическое подтверждение задач

    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Связи
    user = relationship("User", backref="email_accounts")
    email_messages = relationship("EmailMessage", back_populates="email_account", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<EmailAccount(id={self.id}, email={self.email_address}, user_id={self.user_id})>"


class EmailMessage(Base):
    """Модель обработанного email сообщения"""
    __tablename__ = "email_messages"

    id = Column(Integer, primary_key=True)
    email_account_id = Column(Integer, ForeignKey("email_accounts.id", ondelete='CASCADE'), nullable=False)

    # Email метаданные
    message_id = Column(String(255), unique=True, nullable=False, index=True)
    uid = Column(Integer, nullable=False)
    subject = Column(String(500))
    from_address = Column(String(255), nullable=False)
    to_address = Column(String(255))
    date = Column(DateTime)

    # Содержимое
    body_text = Column(Text)
    body_html = Column(Text)
    has_attachments = Column(Boolean, default=False)

    # Обработка
    processed = Column(Boolean, default=False)
    processed_at = Column(DateTime, nullable=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Связи
    email_account = relationship("EmailAccount", back_populates="email_messages")
    task = relationship("Task", backref="email_source")
    attachments = relationship("EmailAttachment", back_populates="email_message", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<EmailMessage(id={self.id}, from={self.from_address}, subject={self.subject})>"


class EmailAttachment(Base):
    """РњРѕРґРµР»СЊ РІР»РѕР¶РµРЅРёСЏ email СЃРѕРѕР±С‰РµРЅРёСЏ"""
    __tablename__ = "email_attachments"

    id = Column(Integer, primary_key=True)
    email_message_id = Column(Integer, ForeignKey("email_messages.id", ondelete='CASCADE'), nullable=False, index=True)
    filename = Column(String(500), nullable=False)
    content_type = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=True)
    extracted_text = Column(Text, nullable=True)
    file_data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    email_message = relationship("EmailMessage", back_populates="attachments")

    def __repr__(self):
        return f"<EmailAttachment(id={self.id}, filename={self.filename})>"


class SupportSession(Base):
    """Модель сессии чата поддержки"""
    __tablename__ = "support_sessions"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete='CASCADE'), nullable=False)

    # Статус сессии
    status = Column(String(50), default='active')  # active, closed, resolved
    category = Column(String(100), nullable=True)  # bug, feature, question, feedback

    # Метаданные
    started_at = Column(DateTime, default=datetime.utcnow, index=True)
    closed_at = Column(DateTime, nullable=True)
    last_message_at = Column(DateTime, default=datetime.utcnow)

    # AI summary (создается при закрытии)
    summary = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)

    # Связи
    user = relationship("User", backref="support_sessions")
    messages = relationship("SupportMessage", back_populates="session", cascade="all, delete-orphan", order_by="SupportMessage.created_at")

    def __repr__(self):
        return f"<SupportSession(id={self.id}, user_id={self.user_id}, status={self.status})>"


class SupportMessage(Base):
    """Модель сообщения в чате поддержки"""
    __tablename__ = "support_messages"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("support_sessions.id", ondelete='CASCADE'), nullable=False, index=True)

    # Отправитель
    from_user = Column(Boolean, default=True)  # True = от пользователя, False = от AI
    message_text = Column(Text, nullable=False)

    # Telegram метаданные
    telegram_message_id = Column(BigInteger, nullable=True)

    # AI метаданные (если сообщение от AI)
    ai_model = Column(String(100), nullable=True)
    ai_tokens = Column(Integer, nullable=True)

    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Связи
    session = relationship("SupportSession", back_populates="messages")
    attachments = relationship("SupportAttachment", back_populates="message", cascade="all, delete-orphan")

    def __repr__(self):
        sender = "User" if self.from_user else "AI"
        return f"<SupportMessage(id={self.id}, session_id={self.session_id}, from={sender})>"


class SupportAttachment(Base):
    """Модель вложения к сообщению поддержки"""
    __tablename__ = "support_attachments"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("support_messages.id", ondelete='CASCADE'), nullable=False, index=True)

    # Telegram file info
    telegram_file_id = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # photo, document, video, audio, voice
    file_name = Column(String(500), nullable=True)
    file_size = Column(Integer, nullable=True)  # в байтах
    mime_type = Column(String(100), nullable=True)

    # Извлеченный текст (если применимо)
    extracted_text = Column(Text, nullable=True)

    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow)

    # Связи
    message = relationship("SupportMessage", back_populates="attachments")

    def __repr__(self):
        return f"<SupportAttachment(id={self.id}, file_type={self.file_type}, file_name={self.file_name})>"
