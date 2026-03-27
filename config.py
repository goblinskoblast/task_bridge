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

# РќРѕСЂРјР°Р»РёР·Р°С†РёСЏ WEB_APP_DOMAIN - СѓР±РёСЂР°РµРј СЃР»РµС€ РІ РєРѕРЅС†Рµ, РµСЃР»Рё РµСЃС‚СЊ
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

DATA_AGENT_URL = os.getenv("DATA_AGENT_URL", "http://localhost:8010").strip()
DATA_AGENT_TIMEOUT = int(os.getenv("DATA_AGENT_TIMEOUT", "45"))
INTERNAL_API_URL = os.getenv("INTERNAL_API_URL", "http://localhost:8000/api/internal/data-agent").strip().rstrip("/")
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "").strip()
REVIEWS_SHEET_URL = os.getenv("REVIEWS_SHEET_URL", "").strip()

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
    # Р”РµР№СЃС‚РІРёСЏ
    "СЃРґРµР»Р°С‚СЊ", "РЅСѓР¶РЅРѕ", "РЅРµРѕР±С…РѕРґРёРјРѕ", "РЅР°РґРѕ", "С‚СЂРµР±СѓРµС‚СЃСЏ",
    "РІС‹РїРѕР»РЅРё", "РїРѕРґРіРѕС‚РѕРІСЊ", "СЃРѕР·РґР°Р№", "РЅР°РїРёС€Рё", "РёСЃРїСЂР°РІСЊ",
    "РїСЂРѕРІРµСЂСЊ", "СѓР±РµРґРёСЃСЊ", "РѕСЂРіР°РЅРёР·СѓР№", "РЅР°СЃС‚СЂРѕР№",

    # РЎСЂРѕРєРё
    "РґРѕ", "Рє", "СЃСЂРѕС‡РЅРѕ", "РІР°Р¶РЅРѕ", "deadline",

    # РђРЅРіР»РёР№СЃРєРёРµ
    "need", "should", "must", "todo", "task",
    "please", "fix", "create", "update", "check"
]


# РќР°РїРѕРјРёРЅР°РЅРёСЏ РґР»СЏ РёСЃРїРѕР»РЅРёС‚РµР»РµР№ (РґРЅРё РґРѕ РґРµРґР»Р°Р№РЅР°)
# РџРѕ СѓРјРѕР»С‡Р°РЅРёСЋ: Р·Р° 3 РґРЅСЏ, Р·Р° 1 РґРµРЅСЊ, РІ РґРµРЅСЊ РґРµРґР»Р°Р№РЅР°
ASSIGNEE_REMINDER_INTERVALS = [3, 1, 0]

# РќР°РїРѕРјРёРЅР°РЅРёСЏ РґР»СЏ РїРѕСЃС‚Р°РЅРѕРІС‰РёРєРѕРІ (РґРЅРё РїРѕСЃР»Рµ СЃРѕР·РґР°РЅРёСЏ Р·Р°РґР°С‡Рё)
# РџРѕ СѓРјРѕР»С‡Р°РЅРёСЋ: С‡РµСЂРµР· 1 РґРµРЅСЊ, С‡РµСЂРµР· 3 РґРЅСЏ, С‡РµСЂРµР· 7 РґРЅРµР№
CREATOR_REMINDER_INTERVALS = [1, 3, 7]

# Legacy РїРѕРґРґРµСЂР¶РєР° СЃС‚Р°СЂРѕРіРѕ РЅР°Р·РІР°РЅРёСЏ
REMINDER_INTERVALS = ASSIGNEE_REMINDER_INTERVALS


REMINDER_TIME_HOUR = 9

# РРЅС‚РµСЂРІР°Р» РїСЂРѕРІРµСЂРєРё РЅР°РїРѕРјРёРЅР°РЅРёР№ (РІ РјРёРЅСѓС‚Р°С…)
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


