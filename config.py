import os
from dotenv import load_dotenv


load_dotenv()



BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required")

BOT_TOKEN = BOT_TOKEN.strip()


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY environment variable is required")

OPENAI_API_KEY = OPENAI_API_KEY.strip()

USE_WEBHOOK = os.getenv("USE_WEBHOOK", "False").lower() == "true"

WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://your-domain.com")

WEBHOOK_PATH = os.getenv("WEBHOOK_PATH", "/webhook")

HOST = os.getenv("HOST", "0.0.0.0")

PORT = int(os.getenv("PORT", "8000"))

# Нормализация WEB_APP_DOMAIN - убираем слеш в конце, если есть
WEB_APP_DOMAIN = os.getenv("WEB_APP_DOMAIN", f"http://{HOST}:{PORT}").rstrip("/")

MINI_APP_URL = os.getenv("MINI_APP_URL", f"{WEB_APP_DOMAIN}/webapp/index.html")

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))

OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "500"))

AI_PROVIDER = os.getenv("AI_PROVIDER", "openai").strip().lower()
OPENCLAW_BASE_URL = os.getenv("OPENCLAW_BASE_URL", "http://localhost:3000").strip()
OPENCLAW_MODEL = os.getenv("OPENCLAW_MODEL", "openai/gpt-4o").strip()
OPENCLAW_TIMEOUT = int(os.getenv("OPENCLAW_TIMEOUT", "60"))
OPENCLAW_ENFORCE_SDD_SPEC = os.getenv("OPENCLAW_ENFORCE_SDD_SPEC", "true").lower() == "true"
OPENCLAW_SDD_SPEC_PATH = os.getenv(
    "OPENCLAW_SDD_SPEC_PATH",
    "docs/sdd/specs/SPEC-OC-001-openclaw-agent.md"
).strip()
OPENCLAW_SDD_MAX_CHARS = int(os.getenv("OPENCLAW_SDD_MAX_CHARS", "24000"))

# Google OAuth (Gmail one-click connect)
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
YANDEX_OAUTH_CLIENT_ID = os.getenv("YANDEX_OAUTH_CLIENT_ID", "").strip()
YANDEX_OAUTH_CLIENT_SECRET = os.getenv("YANDEX_OAUTH_CLIENT_SECRET", "").strip()
YANDEX_OAUTH_REDIRECT_URI = os.getenv("YANDEX_OAUTH_REDIRECT_URI", "").strip()
OAUTH_STATE_SECRET = os.getenv("OAUTH_STATE_SECRET", BOT_TOKEN)

# Database
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///taskbridge.db")


TASK_KEYWORDS = [
    # Действия
    "сделать", "нужно", "необходимо", "надо", "требуется",
    "выполни", "подготовь", "создай", "напиши", "исправь",
    "проверь", "убедись", "организуй", "настрой",

    # Сроки
    "до", "к", "срочно", "важно", "deadline",

    # Английские
    "need", "should", "must", "todo", "task",
    "please", "fix", "create", "update", "check"
]


# Напоминания для исполнителей (дни до дедлайна)
# По умолчанию: за 3 дня, за 1 день, в день дедлайна
ASSIGNEE_REMINDER_INTERVALS = [3, 1, 0]

# Напоминания для постановщиков (дни после создания задачи)
# По умолчанию: через 1 день, через 3 дня, через 7 дней
CREATOR_REMINDER_INTERVALS = [1, 3, 7]

# Legacy поддержка старого названия
REMINDER_INTERVALS = ASSIGNEE_REMINDER_INTERVALS


REMINDER_TIME_HOUR = 9

# Интервал проверки напоминаний (в минутах)
REMINDER_CHECK_INTERVAL = 60  

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

TIMEZONE = os.getenv("TIMEZONE", "Europe/Moscow")

# Developer telegram ID for forwarding support screenshots and critical issues
DEVELOPER_TELEGRAM_ID = os.getenv("DEVELOPER_TELEGRAM_ID")
if DEVELOPER_TELEGRAM_ID:
    DEVELOPER_TELEGRAM_ID = int(DEVELOPER_TELEGRAM_ID.strip())

MAX_TASK_DESCRIPTION_LENGTH = 2000

TASK_STATUSES = ["pending", "in_progress", "completed", "cancelled"]

TASK_PRIORITIES = ["low", "normal", "high", "urgent"]
