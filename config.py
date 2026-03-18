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

def _ensure_url_scheme(value: str, default_scheme: str = "https") -> str:
    value = (value or "").strip()
    if not value:
        return value
    if value.startswith(("http://", "https://")):
        return value
    return f"{default_scheme}://{value.lstrip('/')}"


_raw_web_app_domain = os.getenv("WEB_APP_DOMAIN", f"http://{HOST}:{PORT}")
WEB_APP_DOMAIN = _ensure_url_scheme(_raw_web_app_domain).rstrip("/")

_raw_mini_app_url = os.getenv("MINI_APP_URL", f"{WEB_APP_DOMAIN}/webapp/index.html").strip()
if _raw_mini_app_url.startswith("/"):
    MINI_APP_URL = f"{WEB_APP_DOMAIN}{_raw_mini_app_url}"
else:
    MINI_APP_URL = _ensure_url_scheme(_raw_mini_app_url)

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

OPENAI_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.3"))

OPENAI_MAX_TOKENS = int(os.getenv("OPENAI_MAX_TOKENS", "500"))
GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
GOOGLE_OAUTH_REDIRECT_URI = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
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

