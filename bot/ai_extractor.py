import logging
import json
import re
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from openai import OpenAI
from dateutil import parser as date_parser
import pytz

from config import OPENAI_API_KEY, OPENAI_MODEL, OPENAI_TEMPERATURE, OPENAI_MAX_TOKENS, TIMEZONE

logger = logging.getLogger(__name__)


client = OpenAI(api_key=OPENAI_API_KEY)


def get_current_datetime() -> str:

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    return now.strftime("%Y-%m-%d %H:%M:%S %Z")


EMAIL_SYSTEM_PROMPT = """РўС‹ вЂ” AI-Р°СЃСЃРёСЃС‚РµРЅС‚ РґР»СЏ РёР·РІР»РµС‡РµРЅРёСЏ Р·Р°РґР°С‡ РёР· РґРµР»РѕРІС‹С… email РїРёСЃРµРј.

РўРІРѕСЏ Р·Р°РґР°С‡Р° вЂ” Р°РЅР°Р»РёР·РёСЂРѕРІР°С‚СЊ С‚РµРєСЃС‚ РїРёСЃСЊРјР° Рё РѕРїСЂРµРґРµР»СЏС‚СЊ:
1. РЎРѕРґРµСЂР¶РёС‚ Р»Рё РїРёСЃСЊРјРѕ Р·Р°РґР°С‡Сѓ, РїРѕСЂСѓС‡РµРЅРёРµ, РїСЂРѕСЃСЊР±Сѓ Рѕ РІС‹РїРѕР»РЅРµРЅРёРё СЂР°Р±РѕС‚С‹?
2. Р•СЃР»Рё РґР°, РёР·РІР»РµС‡СЊ РґРµС‚Р°Р»Рё Р·Р°РґР°С‡Рё.

Р’РђР–РќРћ:
- РўРµРєСѓС‰Р°СЏ РґР°С‚Р° Рё РІСЂРµРјСЏ: {current_datetime}
- Email РїРёСЃСЊРјР° С‡Р°СЃС‚Рѕ СЃРѕРґРµСЂР¶Р°С‚ РЎРљР Р«РўР«Р• Р·Р°РґР°С‡Рё РІ С„РѕСЂРјРµ РІРµР¶Р»РёРІС‹С… РїСЂРѕСЃСЊР±:
  * "РќРµ РјРѕРіР»Рё Р±С‹ РІС‹..." в†’ Р—РђР”РђР§Рђ
  * "РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РїРѕРґРіРѕС‚РѕРІСЊС‚Рµ..." в†’ Р—РђР”РђР§Рђ
  * "РџСЂРѕС€Сѓ..." в†’ Р—РђР”РђР§Рђ
  * "РќРµРѕР±С…РѕРґРёРјРѕ СЃРґРµР»Р°С‚СЊ..." в†’ Р—РђР”РђР§Рђ
  * "РќР°РїРѕРјРёРЅР°СЋ Рѕ..." в†’ Р—РђР”РђР§Рђ
  * "РЎСЂРѕС‡РЅРѕ С‚СЂРµР±СѓРµС‚СЃСЏ..." в†’ Р—РђР”РђР§Рђ
  * "РћР¶РёРґР°СЋ РѕС‚ РІР°СЃ..." в†’ Р—РђР”РђР§Рђ
- РРіРЅРѕСЂРёСЂСѓР№ Р Р•РљР›РђРњРќР«Р• РїРёСЃСЊРјР° (РїСЂРѕРјРѕ, СЃРєРёРґРєРё, С‡РµРєРё, РїРѕРґРїРёСЃРєРё)
- РРіРЅРѕСЂРёСЂСѓР№ СѓРІРµРґРѕРјР»РµРЅРёСЏ РѕС‚ СЃРµСЂРІРёСЃРѕРІ (РµСЃР»Рё С‚РѕР»СЊРєРѕ РѕРЅРё РЅРµ СЃРѕРґРµСЂР¶Р°С‚ РєРѕРЅРєСЂРµС‚РЅСѓСЋ РїСЂРѕСЃСЊР±Сѓ)
- Р•СЃР»Рё РїРёСЃСЊРјРѕ СЃРѕРґРµСЂР¶РёС‚ РќР•РЎРљРћР›Р¬РљРћ Р·Р°РґР°С‡ - РІС‹Р±РµСЂРё Р“Р›РђР’РќРЈР®

РџР РђР’РР›Рђ РџРђР РЎРРќР“Рђ Р’Р Р•РњР•РќР (РёСЃРїРѕР»СЊР·СѓР№ С‚РµРєСѓС‰СѓСЋ РґР°С‚Сѓ Рё РІСЂРµРјСЏ РёР· {current_datetime}):

Р§Р°СЃС‚Рё РґРЅСЏ:
- "РґРѕ СѓС‚СЂР°" / "Рє СѓС‚СЂСѓ" / "СѓС‚СЂРѕРј" в†’ СЃР»РµРґСѓСЋС‰РёР№ РґРµРЅСЊ 09:00
- "РґРѕ РѕР±РµРґР°" / "Рє РѕР±РµРґСѓ" / "РІ РѕР±РµРґ" в†’ СЃРµРіРѕРґРЅСЏ 13:00 (РµСЃР»Рё РґРѕ 13:00) РёР»Рё Р·Р°РІС‚СЂР° 13:00
- "РїРѕСЃР»Рµ РѕР±РµРґР°" / "РґРЅРµРј" в†’ СЃРµРіРѕРґРЅСЏ 15:00
- "РґРѕ РІРµС‡РµСЂР°" / "Рє РІРµС‡РµСЂСѓ" / "РІРµС‡РµСЂРѕРј" в†’ СЃРµРіРѕРґРЅСЏ 18:00 (РµСЃР»Рё РґРѕ 18:00) РёР»Рё Р·Р°РІС‚СЂР° 18:00
- "РЅРѕС‡СЊСЋ" / "Рє РЅРѕС‡Рё" в†’ СЃРµРіРѕРґРЅСЏ 22:00
- "РґРѕ РєРѕРЅС†Р° РґРЅСЏ" / "Рє РєРѕРЅС†Сѓ РґРЅСЏ" в†’ СЃРµРіРѕРґРЅСЏ 23:59
- "СЃРµРіРѕРґРЅСЏ" в†’ СЃРµРіРѕРґРЅСЏ 23:59

РћС‚РЅРѕСЃРёС‚РµР»СЊРЅС‹Рµ РґР°С‚С‹:
- "Р·Р°РІС‚СЂР°" в†’ Р·Р°РІС‚СЂР° 23:59
- "РїРѕСЃР»РµР·Р°РІС‚СЂР°" в†’ +2 РґРЅСЏ, 23:59
- "С‡РµСЂРµР· N РґРЅРµР№/С‡Р°СЃРѕРІ" в†’ С‚РµРєСѓС‰Р°СЏ РґР°С‚Р° + N РґРЅРµР№/С‡Р°СЃРѕРІ
- "С‡РµСЂРµР· РЅРµРґРµР»СЋ" в†’ +7 РґРЅРµР№, 23:59
- "С‡РµСЂРµР· РјРµСЃСЏС†" в†’ +30 РґРЅРµР№, 23:59

Р”РЅРё РЅРµРґРµР»Рё (Р±Р»РёР¶Р°Р№С€РёР№):
- "РІ РїРѕРЅРµРґРµР»СЊРЅРёРє" / "Рє РїРѕРЅРµРґРµР»СЊРЅРёРєСѓ" в†’ Р±Р»РёР¶Р°Р№С€РёР№ РїРѕРЅРµРґРµР»СЊРЅРёРє 23:59
- "РІРѕ РІС‚РѕСЂРЅРёРє" / "Рє РІС‚РѕСЂРЅРёРєСѓ" в†’ Р±Р»РёР¶Р°Р№С€РёР№ РІС‚РѕСЂРЅРёРє 23:59
- "РІ СЃСЂРµРґСѓ" / "Рє СЃСЂРµРґРµ" в†’ Р±Р»РёР¶Р°Р№С€Р°СЏ СЃСЂРµРґР° 23:59
- "РІ С‡РµС‚РІРµСЂРі" / "Рє С‡РµС‚РІРµСЂРіСѓ" в†’ Р±Р»РёР¶Р°Р№С€РёР№ С‡РµС‚РІРµСЂРі 23:59
- "РІ РїСЏС‚РЅРёС†Сѓ" / "Рє РїСЏС‚РЅРёС†Рµ" в†’ Р±Р»РёР¶Р°Р№С€Р°СЏ РїСЏС‚РЅРёС†Р° 23:59
- "РІ СЃСѓР±Р±РѕС‚Сѓ" / "Рє СЃСѓР±Р±РѕС‚Рµ" в†’ Р±Р»РёР¶Р°Р№С€Р°СЏ СЃСѓР±Р±РѕС‚Р° 23:59
- "РІ РІРѕСЃРєСЂРµСЃРµРЅСЊРµ" / "Рє РІРѕСЃРєСЂРµСЃРµРЅСЊСЋ" в†’ Р±Р»РёР¶Р°Р№С€РµРµ РІРѕСЃРєСЂРµСЃРµРЅСЊРµ 23:59

РџСЂРёРѕСЂРёС‚РµС‚:
- "СЃСЂРѕС‡РЅРѕ", "urgent", "ASAP", "РєР°Рє РјРѕР¶РЅРѕ СЃРєРѕСЂРµРµ" = urgent
- "РІР°Р¶РЅРѕ", "РїСЂРёРѕСЂРёС‚РµС‚РЅРѕ" = high
- "РєРѕРіРґР° Р±СѓРґРµС‚ РІСЂРµРјСЏ", "РЅРµ СЃСЂРѕС‡РЅРѕ" = low
- РѕСЃС‚Р°Р»СЊРЅРѕРµ = normal

РћС‚РІРµС‚ РЎРўР РћР“Рћ РІ С„РѕСЂРјР°С‚Рµ JSON:
{{
  "has_task": true/false,
  "task": {{
    "title": "РєСЂР°С‚РєРѕРµ РѕРїРёСЃР°РЅРёРµ Р·Р°РґР°С‡Рё (РјР°РєСЃ 100 СЃРёРјРІРѕР»РѕРІ)",
    "description": "РїРѕР»РЅРѕРµ РѕРїРёСЃР°РЅРёРµ Р·Р°РґР°С‡Рё РёР· РїРёСЃСЊРјР°",
    "assignee_usernames": [] (РґР»СЏ email РѕР±С‹С‡РЅРѕ РїСѓСЃС‚Рѕ, РїРѕР»СѓС‡Р°С‚РµР»СЊ Рё С‚Р°Рє Р·РЅР°РµС‚ С‡С‚Рѕ РµРјСѓ),
    "due_date": "YYYY-MM-DD HH:MM:SS РёР»Рё null",
    "priority": "low/normal/high/urgent"
  }}
}}

РџСЂРёРјРµСЂС‹:

Email: "Р”РѕР±СЂС‹Р№ РґРµРЅСЊ! РќРµ РјРѕРіР»Рё Р±С‹ РІС‹ РїРѕРґРіРѕС‚РѕРІРёС‚СЊ РѕС‚С‡РµС‚ РїРѕ РїСЂРѕРґР°Р¶Р°Рј Р·Р° РєРІР°СЂС‚Р°Р»? РќСѓР¶РЅРѕ Рє РїСЏС‚РЅРёС†Рµ. РЎРїР°СЃРёР±Рѕ!"
РћС‚РІРµС‚:
{{
  "has_task": true,
  "task": {{
    "title": "РџРѕРґРіРѕС‚РѕРІРёС‚СЊ РѕС‚С‡РµС‚ РїРѕ РїСЂРѕРґР°Р¶Р°Рј Р·Р° РєРІР°СЂС‚Р°Р»",
    "description": "РџРѕРґРіРѕС‚РѕРІРёС‚СЊ РѕС‚С‡РµС‚ РїРѕ РїСЂРѕРґР°Р¶Р°Рј Р·Р° РєРІР°СЂС‚Р°Р» Рє РїСЏС‚РЅРёС†Рµ",
    "assignee_usernames": [],
    "due_date": "2024-12-13 23:59:00",
    "priority": "normal"
  }}
}}

Email: "РЎРєРёРґРєР° 50% РЅР° РІСЃРµ С‚РѕРІР°СЂС‹! РЈСЃРїРµР№ РєСѓРїРёС‚СЊ РґРѕ РєРѕРЅС†Р° РЅРµРґРµР»Рё!"
РћС‚РІРµС‚:
{{
  "has_task": false,
  "task": null
}}

Email: "РќР°РїРѕРјРёРЅР°СЋ Рѕ РЅРµРѕР±С…РѕРґРёРјРѕСЃС‚Рё СЃСЂРѕС‡РЅРѕ РѕС‚РїСЂР°РІРёС‚СЊ РґРѕРєСѓРјРµРЅС‚С‹ РґР»СЏ РїСЂРѕРІРµСЂРєРё"
РћС‚РІРµС‚:
{{
  "has_task": true,
  "task": {{
    "title": "РћС‚РїСЂР°РІРёС‚СЊ РґРѕРєСѓРјРµРЅС‚С‹ РґР»СЏ РїСЂРѕРІРµСЂРєРё",
    "description": "РЎСЂРѕС‡РЅРѕ РѕС‚РїСЂР°РІРёС‚СЊ РґРѕРєСѓРјРµРЅС‚С‹ РґР»СЏ РїСЂРѕРІРµСЂРєРё",
    "assignee_usernames": [],
    "due_date": null,
    "priority": "urgent"
  }}
}}
"""


SYSTEM_PROMPT = """РўС‹ вЂ” AI-Р°СЃСЃРёСЃС‚РµРЅС‚ РґР»СЏ РёР·РІР»РµС‡РµРЅРёСЏ Р·Р°РґР°С‡ РёР· СЃРѕРѕР±С‰РµРЅРёР№ РІ Telegram С‡Р°С‚Р°С….

РўРІРѕСЏ Р·Р°РґР°С‡Р° вЂ” Р°РЅР°Р»РёР·РёСЂРѕРІР°С‚СЊ С‚РµРєСЃС‚ СЃРѕРѕР±С‰РµРЅРёСЏ Рё РѕРїСЂРµРґРµР»СЏС‚СЊ:
1. РЎРѕРґРµСЂР¶РёС‚ Р»Рё СЃРѕРѕР±С‰РµРЅРёРµ Р·Р°РґР°С‡Сѓ (РїРѕСЂСѓС‡РµРЅРёРµ)?
2. Р•СЃР»Рё РґР°, РёР·РІР»РµС‡СЊ РґРµС‚Р°Р»Рё Р·Р°РґР°С‡Рё.

Р’РђР–РќРћ:
- РўРµРєСѓС‰Р°СЏ РґР°С‚Р° Рё РІСЂРµРјСЏ: {current_datetime}
- РћС‚РЅРѕСЃРёС‚РµР»СЊРЅС‹Рµ РґР°С‚С‹ РїСЂРµРѕР±СЂР°Р·СѓР№ РІ Р°Р±СЃРѕР»СЋС‚РЅС‹Рµ РґР°С‚С‹ РІ С„РѕСЂРјР°С‚Рµ "YYYY-MM-DD HH:MM:SS"
- Username РћР‘РЇР—РђРўР•Р›Р¬РќРћ РёР·РІР»РµРєР°Р№ РµСЃР»Рё СѓРєР°Р·Р°РЅ С‡РµСЂРµР· @username РёР»Рё РїРѕ РёРјРµРЅРё
- Р•СЃР»Рё СЃРѕРѕР±С‰РµРЅРёРµ РЅР°С‡РёРЅР°РµС‚СЃСЏ СЃ @username - СЌС‚Рѕ Р’РЎР•Р“Р”Рђ РёСЃРїРѕР»РЅРёС‚РµР»СЊ Р·Р°РґР°С‡Рё
- assignee_usernames РІРѕР·РІСЂР°С‰Р°Р№ Р‘Р•Р— СЃРёРјРІРѕР»Р° @ (С‚РѕР»СЊРєРѕ username) РІ РІРёРґРµ СЃРїРёСЃРєР° ["user1", "user2"]
- Р•СЃР»Рё РЅРµСЃРєРѕР»СЊРєРѕ РёСЃРїРѕР»РЅРёС‚РµР»РµР№ (@alex @maria РёР»Рё "РЎР°С€Р° Рё РњР°С€Р°") - РІРєР»СЋС‡Рё РІСЃРµС… РІ СЃРїРёСЃРѕРє
- РџСЂРёРѕСЂРёС‚РµС‚: "СЃСЂРѕС‡РЅРѕ", "РІР°Р¶РЅРѕ", "urgent" = high; "РєРѕРіРґР° Р±СѓРґРµС‚ РІСЂРµРјСЏ" = low; РѕСЃС‚Р°Р»СЊРЅРѕРµ = normal

РџР РђР’РР›Рђ РџРђР РЎРРќР“Рђ Р’Р Р•РњР•РќР (РёСЃРїРѕР»СЊР·СѓР№ С‚РµРєСѓС‰СѓСЋ РґР°С‚Сѓ Рё РІСЂРµРјСЏ РёР· {current_datetime}):

Р§Р°СЃС‚Рё РґРЅСЏ:
- "РґРѕ СѓС‚СЂР°" / "Рє СѓС‚СЂСѓ" / "СѓС‚СЂРѕРј" в†’ СЃР»РµРґСѓСЋС‰РёР№ РґРµРЅСЊ 09:00
- "РґРѕ РѕР±РµРґР°" / "Рє РѕР±РµРґСѓ" / "РІ РѕР±РµРґ" в†’ СЃРµРіРѕРґРЅСЏ 13:00 (РµСЃР»Рё РґРѕ 13:00) РёР»Рё Р·Р°РІС‚СЂР° 13:00
- "РїРѕСЃР»Рµ РѕР±РµРґР°" / "РґРЅРµРј" в†’ СЃРµРіРѕРґРЅСЏ 15:00
- "РґРѕ РІРµС‡РµСЂР°" / "Рє РІРµС‡РµСЂСѓ" / "РІРµС‡РµСЂРѕРј" в†’ СЃРµРіРѕРґРЅСЏ 18:00 (РµСЃР»Рё РґРѕ 18:00) РёР»Рё Р·Р°РІС‚СЂР° 18:00
- "РЅРѕС‡СЊСЋ" / "Рє РЅРѕС‡Рё" в†’ СЃРµРіРѕРґРЅСЏ 22:00
- "РґРѕ РєРѕРЅС†Р° РґРЅСЏ" / "Рє РєРѕРЅС†Сѓ РґРЅСЏ" в†’ СЃРµРіРѕРґРЅСЏ 23:59
- "СЃРµРіРѕРґРЅСЏ" в†’ СЃРµРіРѕРґРЅСЏ 23:59

РћС‚РЅРѕСЃРёС‚РµР»СЊРЅС‹Рµ РґР°С‚С‹:
- "Р·Р°РІС‚СЂР°" в†’ Р·Р°РІС‚СЂР° 23:59
- "РїРѕСЃР»РµР·Р°РІС‚СЂР°" в†’ +2 РґРЅСЏ, 23:59
- "С‡РµСЂРµР· N РґРЅРµР№/С‡Р°СЃРѕРІ" в†’ С‚РµРєСѓС‰Р°СЏ РґР°С‚Р° + N РґРЅРµР№/С‡Р°СЃРѕРІ
- "С‡РµСЂРµР· РЅРµРґРµР»СЋ" в†’ +7 РґРЅРµР№, 23:59
- "С‡РµСЂРµР· РјРµСЃСЏС†" в†’ +30 РґРЅРµР№, 23:59

Р”РЅРё РЅРµРґРµР»Рё (Р±Р»РёР¶Р°Р№С€РёР№):
- "РІ РїРѕРЅРµРґРµР»СЊРЅРёРє" / "Рє РїРѕРЅРµРґРµР»СЊРЅРёРєСѓ" в†’ Р±Р»РёР¶Р°Р№С€РёР№ РїРѕРЅРµРґРµР»СЊРЅРёРє 23:59
- "РІРѕ РІС‚РѕСЂРЅРёРє" / "Рє РІС‚РѕСЂРЅРёРєСѓ" в†’ Р±Р»РёР¶Р°Р№С€РёР№ РІС‚РѕСЂРЅРёРє 23:59
- "РІ СЃСЂРµРґСѓ" / "Рє СЃСЂРµРґРµ" в†’ Р±Р»РёР¶Р°Р№С€Р°СЏ СЃСЂРµРґР° 23:59
- "РІ С‡РµС‚РІРµСЂРі" / "Рє С‡РµС‚РІРµСЂРіСѓ" в†’ Р±Р»РёР¶Р°Р№С€РёР№ С‡РµС‚РІРµСЂРі 23:59
- "РІ РїСЏС‚РЅРёС†Сѓ" / "Рє РїСЏС‚РЅРёС†Рµ" в†’ Р±Р»РёР¶Р°Р№С€Р°СЏ РїСЏС‚РЅРёС†Р° 23:59
- "РІ СЃСѓР±Р±РѕС‚Сѓ" / "Рє СЃСѓР±Р±РѕС‚Рµ" в†’ Р±Р»РёР¶Р°Р№С€Р°СЏ СЃСѓР±Р±РѕС‚Р° 23:59
- "РІ РІРѕСЃРєСЂРµСЃРµРЅСЊРµ" / "Рє РІРѕСЃРєСЂРµСЃРµРЅСЊСЋ" в†’ Р±Р»РёР¶Р°Р№С€РµРµ РІРѕСЃРєСЂРµСЃРµРЅСЊРµ 23:59

РџРµСЂРёРѕРґС‹:
- "РЅР° СЌС‚РѕР№ РЅРµРґРµР»Рµ" в†’ Р±Р»РёР¶Р°Р№С€Р°СЏ РїСЏС‚РЅРёС†Р° 23:59
- "РЅР° СЃР»РµРґСѓСЋС‰РµР№ РЅРµРґРµР»Рµ" в†’ СЃР»РµРґСѓСЋС‰РёР№ РїРѕРЅРµРґРµР»СЊРЅРёРє 23:59
- "РІ СЌС‚РѕРј РјРµСЃСЏС†Рµ" в†’ РїРѕСЃР»РµРґРЅРёР№ РґРµРЅСЊ С‚РµРєСѓС‰РµРіРѕ РјРµСЃСЏС†Р° 23:59
- "РІ СЃР»РµРґСѓСЋС‰РµРј РјРµСЃСЏС†Рµ" в†’ 1-Рµ С‡РёСЃР»Рѕ СЃР»РµРґСѓСЋС‰РµРіРѕ РјРµСЃСЏС†Р° 23:59

РљРѕРЅРєСЂРµС‚РЅРѕРµ РІСЂРµРјСЏ:
- "Рє 10:00" / "РґРѕ 10" / "РІ 10 СѓС‚СЂР°" в†’ СЃРµРіРѕРґРЅСЏ 10:00 (РµСЃР»Рё РµС‰Рµ РЅРµ 10:00) РёР»Рё Р·Р°РІС‚СЂР° 10:00
- "Рє 15:30" / "РІ 15:30" в†’ СЃРµРіРѕРґРЅСЏ 15:30 РёР»Рё Р·Р°РІС‚СЂР° 15:30
- "23 РЅРѕСЏР±СЂСЏ" / "23.11" в†’ 23 РЅРѕСЏР±СЂСЏ С‚РµРєСѓС‰РµРіРѕ РіРѕРґР° 23:59
- "23 РЅРѕСЏР±СЂСЏ РІ 14:00" в†’ 23 РЅРѕСЏР±СЂСЏ 14:00

Р’РђР–РќРћ:
- Р•СЃР»Рё СѓРєР°Р·Р°РЅРЅРѕРµ РІСЂРµРјСЏ СѓР¶Рµ РїСЂРѕС€Р»Рѕ СЃРµРіРѕРґРЅСЏ, РїРµСЂРµРЅРѕСЃРё РЅР° Р·Р°РІС‚СЂР°
- Р’СЃРµРіРґР° РІРѕР·РІСЂР°С‰Р°Р№ РІ С„РѕСЂРјР°С‚Рµ "YYYY-MM-DD HH:MM:SS"
- РЈС‡РёС‚С‹РІР°Р№ РєРѕРЅС‚РµРєСЃС‚ ("СЃСЂРѕС‡РЅРѕ" РѕР±С‹С‡РЅРѕ = СЃРµРіРѕРґРЅСЏ, "РєРѕРіРґР° Р±СѓРґРµС‚ РІСЂРµРјСЏ" = С‡РµСЂРµР· РЅРµСЃРєРѕР»СЊРєРѕ РґРЅРµР№)

РћС‚РІРµС‚ РЎРўР РћР“Рћ РІ С„РѕСЂРјР°С‚Рµ JSON:
{{
  "has_task": true/false,
  "task": {{
    "title": "РєСЂР°С‚РєРѕРµ РѕРїРёСЃР°РЅРёРµ Р·Р°РґР°С‡Рё (РјР°РєСЃ 100 СЃРёРјРІРѕР»РѕРІ)",
    "description": "РїРѕР»РЅРѕРµ РѕРїРёСЃР°РЅРёРµ Р·Р°РґР°С‡Рё",
    "assignee_usernames": ["username1", "username2"] РёР»Рё [] РµСЃР»Рё РЅРµ СѓРєР°Р·Р°РЅС‹,
    "due_date": "YYYY-MM-DD HH:MM:SS РёР»Рё null",
    "priority": "low/normal/high/urgent"
  }}
}}

РџСЂРёРјРµСЂС‹:

РЎРѕРѕР±С‰РµРЅРёРµ: "@alex СЃРґРµР»Р°Р№ РѕС‚С‡РµС‚ РїРѕ РїСЂРѕРґР°Р¶Р°Рј РґРѕ Р·Р°РІС‚СЂР°"
РћС‚РІРµС‚:
{{
  "has_task": true,
  "task": {{
    "title": "РЎРґРµР»Р°С‚СЊ РѕС‚С‡РµС‚ РїРѕ РїСЂРѕРґР°Р¶Р°Рј",
    "description": "РЎРґРµР»Р°С‚СЊ РѕС‚С‡РµС‚ РїРѕ РїСЂРѕРґР°Р¶Р°Рј РґРѕ Р·Р°РІС‚СЂР°",
    "assignee_usernames": ["alex"],
    "due_date": "2025-11-19 23:59:59",
    "priority": "normal"
  }}
}}

РЎРѕРѕР±С‰РµРЅРёРµ: "@alex @maria РїРѕРґРіРѕС‚РѕРІСЊС‚Рµ РїСЂРµР·РµРЅС‚Р°С†РёСЋ Рє СЃСЂРµРґРµ"
РћС‚РІРµС‚:
{{
  "has_task": true,
  "task": {{
    "title": "РџРѕРґРіРѕС‚РѕРІРёС‚СЊ РїСЂРµР·РµРЅС‚Р°С†РёСЋ",
    "description": "РџРѕРґРіРѕС‚РѕРІРёС‚СЊ РїСЂРµР·РµРЅС‚Р°С†РёСЋ Рє СЃСЂРµРґРµ",
    "assignee_usernames": ["alex", "maria"],
    "due_date": "2025-11-20 23:59:59",
    "priority": "normal"
  }}
}}

РЎРѕРѕР±С‰РµРЅРёРµ: "РЎР°С€Р° Рё РњР°С€Р°, СЃСЂРѕС‡РЅРѕ РёСЃРїСЂР°РІСЊС‚Рµ Р±Р°Рі СЃ Р°РІС‚РѕСЂРёР·Р°С†РёРµР№ Рє РІРµС‡РµСЂСѓ"
РћС‚РІРµС‚:
{{
  "has_task": true,
  "task": {{
    "title": "РСЃРїСЂР°РІРёС‚СЊ Р±Р°Рі СЃ Р°РІС‚РѕСЂРёР·Р°С†РёРµР№",
    "description": "РЎСЂРѕС‡РЅРѕ РёСЃРїСЂР°РІРёС‚СЊ Р±Р°Рі СЃ Р°РІС‚РѕСЂРёР·Р°С†РёРµР№ Рє РІРµС‡РµСЂСѓ",
    "assignee_usernames": ["РЎР°С€Р°", "РњР°С€Р°"],
    "due_date": "2025-11-26 18:00:00",
    "priority": "high"
  }}
}}

РЎРѕРѕР±С‰РµРЅРёРµ: "@john РїРѕРґРіРѕС‚РѕРІСЊ РґРѕРєСѓРјРµРЅС‚С‹ Рє РїРѕРЅРµРґРµР»СЊРЅРёРєСѓ Рє 10 СѓС‚СЂР°"
РћС‚РІРµС‚:
{{
  "has_task": true,
  "task": {{
    "title": "РџРѕРґРіРѕС‚РѕРІРёС‚СЊ РґРѕРєСѓРјРµРЅС‚С‹",
    "description": "РџРѕРґРіРѕС‚РѕРІРёС‚СЊ РґРѕРєСѓРјРµРЅС‚С‹ Рє РїРѕРЅРµРґРµР»СЊРЅРёРєСѓ Рє 10 СѓС‚СЂР°",
    "assignee_usernames": ["john"],
    "due_date": "2025-12-02 10:00:00",
    "priority": "normal"
  }}
}}

РЎРѕРѕР±С‰РµРЅРёРµ: "@team РїСЂРѕРІРµСЂСЊС‚Рµ С‚РµСЃС‚С‹ С‡РµСЂРµР· 2 С‡Р°СЃР°"
РћС‚РІРµС‚:
{{
  "has_task": true,
  "task": {{
    "title": "РџСЂРѕРІРµСЂРёС‚СЊ С‚РµСЃС‚С‹",
    "description": "РџСЂРѕРІРµСЂРёС‚СЊ С‚РµСЃС‚С‹ С‡РµСЂРµР· 2 С‡Р°СЃР°",
    "assignee_usernames": ["team"],
    "due_date": "2025-11-26 16:30:00",
    "priority": "normal"
  }}
}}

РЎРѕРѕР±С‰РµРЅРёРµ: "РҐРѕСЂРѕС€Р°СЏ РїРѕРіРѕРґР° СЃРµРіРѕРґРЅСЏ"
РћС‚РІРµС‚:
{{
  "has_task": false,
  "task": null
}}

РћС‚РІРµС‡Р°Р№ РўРћР›Р¬РљРћ JSON, Р±РµР· РґРѕРїРѕР»РЅРёС‚РµР»СЊРЅС‹С… РєРѕРјРјРµРЅС‚Р°СЂРёРµРІ!
"""

_TASK_VERBS_PATTERN = re.compile(
    r"\b(сделать|выполнить|подготовить|выставить|настроить|проверить|исправить|создать|написать|обновить|"
    r"собрать|проанализировать|отправить|внедрить|запустить|добавить|удалить|закрыть)\b[^?.!\n]*",
    re.IGNORECASE,
)
_RELATIVE_DAYS_PATTERN = re.compile(
    r"(?:через|за|в течение|хватит)\s*(\d+)\s*(?:-|\s)?(?:х|x)?\s*(?:дн(?:я|ей)?|день|сут(?:ки|ок)?)",
    re.IGNORECASE,
)
_RELATIVE_HOURS_PATTERN = re.compile(
    r"(?:через|за|в течение|хватит)\s*(\d+)\s*(?:-|\s)?(?:х|x)?\s*(?:час(?:а|ов)?)",
    re.IGNORECASE,
)
_VOCATIVE_PREFIX_PATTERN = re.compile(
    r"^\s*[а-яa-zё][а-яa-zё-]{1,30}\s+(?=нужно|надо|необходимо|сделай|сделать|выполни|подготовь|"
    r"подготовить|проверь|исправь|выставить)",
    re.IGNORECASE,
)


def _build_short_title(source_text: str) -> str:
    text = (source_text or "").strip()
    if not text:
        return "Задача"

    text = re.sub(r"^\s*@\w+[,:\s-]*", "", text)
    text = _VOCATIVE_PREFIX_PATTERN.sub("", text)
    text = text.replace("\n", " ").strip()

    verb_match = _TASK_VERBS_PATTERN.search(text)
    if verb_match:
        title = verb_match.group(0)
    else:
        title = re.split(r"[?.!]", text)[0]

    title = re.split(r",\s*(?:вам|тебе)\s+хватит", title, maxsplit=1, flags=re.IGNORECASE)[0]
    title = re.sub(r"\s+", " ", title).strip(" ,:-")

    if not title:
        title = text[:100]

    return title[:100]


def _parse_relative_due_date(text: str) -> Optional[datetime]:
    if not text:
        return None

    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    lowered = text.lower()

    if "послезавтра" in lowered:
        return (now + timedelta(days=2)).replace(hour=23, minute=59, second=59, microsecond=0)

    if "завтра" in lowered:
        return (now + timedelta(days=1)).replace(hour=23, minute=59, second=59, microsecond=0)

    days_match = _RELATIVE_DAYS_PATTERN.search(text)
    if days_match:
        days = int(days_match.group(1))
        return (now + timedelta(days=days)).replace(hour=23, minute=59, second=59, microsecond=0)

    hours_match = _RELATIVE_HOURS_PATTERN.search(text)
    if hours_match:
        hours = int(hours_match.group(1))
        return (now + timedelta(hours=hours)).replace(second=0, microsecond=0)

    return None


def _normalize_task_payload(task: Dict[str, Any], source_text: str) -> None:
    description = (task.get("description") or "").strip()
    if not description:
        description = (source_text or "").strip()

    title = (task.get("title") or "").strip()
    if not title or title == description or len(title) > 100:
        title = _build_short_title(description or source_text)

    if not description:
        description = title

    task["title"] = title[:100]
    task["description"] = description

    due_date_parsed = None
    due_date_str = task.get("due_date")
    if due_date_str:
        try:
            due_date_parsed = date_parser.parse(due_date_str)
        except Exception as date_error:
            logger.warning(f"Failed to parse due_date: {task.get('due_date')}, error: {date_error}")

    if due_date_parsed is None:
        due_date_parsed = _parse_relative_due_date(source_text)
        if due_date_parsed:
            task["due_date"] = due_date_parsed.strftime("%Y-%m-%d %H:%M:%S")

    task["due_date_parsed"] = due_date_parsed

async def analyze_message_with_ai(text: str) -> Optional[Dict[str, Any]]:
  
    if not text or len(text.strip()) == 0:
        return None

    try:
        # РџРѕР»СѓС‡Р°РµРј С‚РµРєСѓС‰СѓСЋ РґР°С‚Сѓ Рё РІСЂРµРјСЏ
        current_dt = get_current_datetime()

        # Р¤РѕСЂРјРёСЂСѓРµРј РїСЂРѕРјРїС‚ СЃ С‚РµРєСѓС‰РµР№ РґР°С‚РѕР№
        system_prompt = SYSTEM_PROMPT.format(current_datetime=current_dt)

        # Р’С‹Р·С‹РІР°РµРј OpenAI API
        logger.info(f"Calling OpenAI API to analyze message: {text[:50]}...")

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS,
            response_format={"type": "json_object"}
        )

        
        result_text = response.choices[0].message.content
        logger.info(f"OpenAI response: {result_text}")

        
        result = json.loads(result_text)

        
        if not isinstance(result, dict) or "has_task" not in result:
            logger.error(f"Invalid AI response format: {result}")
            return None

        
        if not result.get("has_task", False):
            return result

        
        task = result.get("task")
        if task:
            _normalize_task_payload(task, text)

        return result

    except Exception as e:
        logger.error(f"Error in AI analysis: {e}", exc_info=True)
        return None


async def analyze_email_with_ai(text: str) -> Optional[Dict[str, Any]]:
    """
    РђРЅР°Р»РёР·РёСЂСѓРµС‚ email РїРёСЃСЊРјРѕ СЃ РїРѕРјРѕС‰СЊСЋ AI Рё РёР·РІР»РµРєР°РµС‚ Р·Р°РґР°С‡Сѓ.
    РСЃРїРѕР»СЊР·СѓРµС‚ СЃРїРµС†РёР°Р»СЊРЅС‹Р№ РїСЂРѕРјРїС‚ РґР»СЏ email, РєРѕС‚РѕСЂС‹Р№ Р±РѕР»РµРµ С‡СѓРІСЃС‚РІРёС‚РµР»РµРЅ Рє РґРµР»РѕРІС‹Рј РїРёСЃСЊРјР°Рј.
    """
    if not text or len(text.strip()) == 0:
        return None

    try:
        # РџРѕР»СѓС‡Р°РµРј С‚РµРєСѓС‰СѓСЋ РґР°С‚Сѓ Рё РІСЂРµРјСЏ
        current_dt = get_current_datetime()

        # Р¤РѕСЂРјРёСЂСѓРµРј РїСЂРѕРјРїС‚ СЃ С‚РµРєСѓС‰РµР№ РґР°С‚РѕР№ (РёСЃРїРѕР»СЊР·СѓРµРј EMAIL_SYSTEM_PROMPT)
        system_prompt = EMAIL_SYSTEM_PROMPT.format(current_datetime=current_dt)

        # Р’С‹Р·С‹РІР°РµРј OpenAI API
        logger.info(f"Calling OpenAI API to analyze email: {text[:50]}...")

        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            temperature=OPENAI_TEMPERATURE,
            max_tokens=OPENAI_MAX_TOKENS,
            response_format={"type": "json_object"}
        )

        # РџР°СЂСЃРёРј РѕС‚РІРµС‚
        result_text = response.choices[0].message.content
        logger.info(f"OpenAI response for email: {result_text}")

        # РџСЂРµРѕР±СЂР°Р·СѓРµРј РІ dict
        result = json.loads(result_text)

        # Р’Р°Р»РёРґР°С†РёСЏ С„РѕСЂРјР°С‚Р°
        if not isinstance(result, dict) or "has_task" not in result:
            logger.error(f"Invalid AI response format: {result}")
            return None

        # Р•СЃР»Рё Р·Р°РґР°С‡Рё РЅРµС‚ - РІРѕР·РІСЂР°С‰Р°РµРј СЂРµР·СѓР»СЊС‚Р°С‚
        if not result.get("has_task", False):
            return result

        # РџР°СЂСЃРёРј due_date РµСЃР»Рё РµСЃС‚СЊ
        task = result.get("task")
        if task:
            _normalize_task_payload(task, text)

        return result

    except Exception as e:
        logger.error(f"Error in AI email analysis: {e}", exc_info=True)
        return None


def extract_task_simple(text: str) -> bool:
    
    if not text:
        return False

    text_lower = text.lower()

    
    task_keywords = [
        "СЃРґРµР»Р°С‚СЊ", "РЅСѓР¶РЅРѕ", "РЅРµРѕР±С…РѕРґРёРјРѕ", "РЅР°РґРѕ", "С‚СЂРµР±СѓРµС‚СЃСЏ",
        "РІС‹РїРѕР»РЅРё", "РїРѕРґРіРѕС‚РѕРІСЊ", "СЃРѕР·РґР°Р№", "РЅР°РїРёС€Рё", "РёСЃРїСЂР°РІСЊ",
        "РїСЂРѕРІРµСЂСЊ", "СѓР±РµРґРёСЃСЊ", "РѕСЂРіР°РЅРёР·СѓР№", "РЅР°СЃС‚СЂРѕР№",
        "РґРѕ", "Рє", "СЃСЂРѕС‡РЅРѕ", "РІР°Р¶РЅРѕ", "deadline",
        "need", "should", "must", "todo", "task",
        "please", "fix", "create", "update", "check"
    ]

    for keyword in task_keywords:
        if keyword in text_lower:
            return True

    
    if '@' in text:
        return True

    return False


async def analyze_message(text: str, use_ai: bool = True) -> Optional[Dict[str, Any]]:
    
    if not text:
        return None

    # Р•СЃР»Рё AI РІРєР»СЋС‡РµРЅ, РїСЂРѕР±СѓРµРј РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ РµРіРѕ
    if use_ai:
        try:
            result = await analyze_message_with_ai(text)
            if result is not None:
                return result
            else:
                
                logger.warning("AI returned None, using simple extraction")
        except Exception as e:
            logger.error(f"AI analysis failed: {e}, using simple extraction")

    
    has_task = extract_task_simple(text)

    if has_task:
        task = {
            "title": text[:100],
            "description": text,
            "assignee_usernames": [],
            "assignee_username": None,
            "due_date": None,
            "due_date_parsed": None,
            "priority": "normal"
        }
        _normalize_task_payload(task, text)
        return {
            "has_task": True,
            "task": task
        }
    else:
        return {
            "has_task": False,
            "task": None
        }

