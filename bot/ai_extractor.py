import logging
import json
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


EMAIL_SYSTEM_PROMPT = """Ты — AI-ассистент для извлечения задач из деловых email писем.

Твоя задача — анализировать текст письма и определять:
1. Содержит ли письмо задачу, поручение, просьбу о выполнении работы?
2. Если да, извлечь детали задачи.

ВАЖНО:
- Текущая дата и время: {current_datetime}
- Email письма часто содержат СКРЫТЫЕ задачи в форме вежливых просьб:
  * "Не могли бы вы..." → ЗАДАЧА
  * "Пожалуйста, подготовьте..." → ЗАДАЧА
  * "Прошу..." → ЗАДАЧА
  * "Необходимо сделать..." → ЗАДАЧА
  * "Напоминаю о..." → ЗАДАЧА
  * "Срочно требуется..." → ЗАДАЧА
  * "Ожидаю от вас..." → ЗАДАЧА
- Игнорируй РЕКЛАМНЫЕ письма (промо, скидки, чеки, подписки)
- Игнорируй уведомления от сервисов (если только они не содержат конкретную просьбу)
- Если письмо содержит НЕСКОЛЬКО задач - выбери ГЛАВНУЮ

ПРАВИЛА ПАРСИНГА ВРЕМЕНИ (используй текущую дату и время из {current_datetime}):

Части дня:
- "до утра" / "к утру" / "утром" → следующий день 09:00
- "до обеда" / "к обеду" / "в обед" → сегодня 13:00 (если до 13:00) или завтра 13:00
- "после обеда" / "днем" → сегодня 15:00
- "до вечера" / "к вечеру" / "вечером" → сегодня 18:00 (если до 18:00) или завтра 18:00
- "ночью" / "к ночи" → сегодня 22:00
- "до конца дня" / "к концу дня" → сегодня 23:59
- "сегодня" → сегодня 23:59

Относительные даты:
- "завтра" → завтра 23:59
- "послезавтра" → +2 дня, 23:59
- "через N дней/часов" → текущая дата + N дней/часов
- "через неделю" → +7 дней, 23:59
- "через месяц" → +30 дней, 23:59

Дни недели (ближайший):
- "в понедельник" / "к понедельнику" → ближайший понедельник 23:59
- "во вторник" / "к вторнику" → ближайший вторник 23:59
- "в среду" / "к среде" → ближайшая среда 23:59
- "в четверг" / "к четвергу" → ближайший четверг 23:59
- "в пятницу" / "к пятнице" → ближайшая пятница 23:59
- "в субботу" / "к субботе" → ближайшая суббота 23:59
- "в воскресенье" / "к воскресенью" → ближайшее воскресенье 23:59

Приоритет:
- "срочно", "urgent", "ASAP", "как можно скорее" = urgent
- "важно", "приоритетно" = high
- "когда будет время", "не срочно" = low
- остальное = normal

Ответ СТРОГО в формате JSON:
{{
  "has_task": true/false,
  "task": {{
    "title": "краткое описание задачи (макс 100 символов)",
    "description": "полное описание задачи из письма",
    "assignee_usernames": [] (для email обычно пусто, получатель и так знает что ему),
    "due_date": "YYYY-MM-DD HH:MM:SS или null",
    "priority": "low/normal/high/urgent"
  }}
}}

Примеры:

Email: "Добрый день! Не могли бы вы подготовить отчет по продажам за квартал? Нужно к пятнице. Спасибо!"
Ответ:
{{
  "has_task": true,
  "task": {{
    "title": "Подготовить отчет по продажам за квартал",
    "description": "Подготовить отчет по продажам за квартал к пятнице",
    "assignee_usernames": [],
    "due_date": "2024-12-13 23:59:00",
    "priority": "normal"
  }}
}}

Email: "Скидка 50% на все товары! Успей купить до конца недели!"
Ответ:
{{
  "has_task": false,
  "task": null
}}

Email: "Напоминаю о необходимости срочно отправить документы для проверки"
Ответ:
{{
  "has_task": true,
  "task": {{
    "title": "Отправить документы для проверки",
    "description": "Срочно отправить документы для проверки",
    "assignee_usernames": [],
    "due_date": null,
    "priority": "urgent"
  }}
}}
"""


SYSTEM_PROMPT = """Ты — AI-ассистент для извлечения задач из сообщений в Telegram чатах.

Твоя задача — анализировать текст сообщения и определять:
1. Содержит ли сообщение задачу (поручение)?
2. Если да, извлечь детали задачи.

ВАЖНО:
- Текущая дата и время: {current_datetime}
- Относительные даты преобразуй в абсолютные даты в формате "YYYY-MM-DD HH:MM:SS"
- Username ОБЯЗАТЕЛЬНО извлекай если указан через @username или по имени
- Если сообщение начинается с @username - это ВСЕГДА исполнитель задачи
- assignee_usernames возвращай БЕЗ символа @ (только username) в виде списка ["user1", "user2"]
- Если несколько исполнителей (@alex @maria или "Саша и Маша") - включи всех в список
- Приоритет: "срочно", "важно", "urgent" = high; "когда будет время" = low; остальное = normal

ПРАВИЛА ПАРСИНГА ВРЕМЕНИ (используй текущую дату и время из {current_datetime}):

Части дня:
- "до утра" / "к утру" / "утром" → следующий день 09:00
- "до обеда" / "к обеду" / "в обед" → сегодня 13:00 (если до 13:00) или завтра 13:00
- "после обеда" / "днем" → сегодня 15:00
- "до вечера" / "к вечеру" / "вечером" → сегодня 18:00 (если до 18:00) или завтра 18:00
- "ночью" / "к ночи" → сегодня 22:00
- "до конца дня" / "к концу дня" → сегодня 23:59
- "сегодня" → сегодня 23:59

Относительные даты:
- "завтра" → завтра 23:59
- "послезавтра" → +2 дня, 23:59
- "через N дней/часов" → текущая дата + N дней/часов
- "через неделю" → +7 дней, 23:59
- "через месяц" → +30 дней, 23:59

Дни недели (ближайший):
- "в понедельник" / "к понедельнику" → ближайший понедельник 23:59
- "во вторник" / "к вторнику" → ближайший вторник 23:59
- "в среду" / "к среде" → ближайшая среда 23:59
- "в четверг" / "к четвергу" → ближайший четверг 23:59
- "в пятницу" / "к пятнице" → ближайшая пятница 23:59
- "в субботу" / "к субботе" → ближайшая суббота 23:59
- "в воскресенье" / "к воскресенью" → ближайшее воскресенье 23:59

Периоды:
- "на этой неделе" → ближайшая пятница 23:59
- "на следующей неделе" → следующий понедельник 23:59
- "в этом месяце" → последний день текущего месяца 23:59
- "в следующем месяце" → 1-е число следующего месяца 23:59

Конкретное время:
- "к 10:00" / "до 10" / "в 10 утра" → сегодня 10:00 (если еще не 10:00) или завтра 10:00
- "к 15:30" / "в 15:30" → сегодня 15:30 или завтра 15:30
- "23 ноября" / "23.11" → 23 ноября текущего года 23:59
- "23 ноября в 14:00" → 23 ноября 14:00

ВАЖНО:
- Если указанное время уже прошло сегодня, переноси на завтра
- Всегда возвращай в формате "YYYY-MM-DD HH:MM:SS"
- Учитывай контекст ("срочно" обычно = сегодня, "когда будет время" = через несколько дней)

Ответ СТРОГО в формате JSON:
{{
  "has_task": true/false,
  "task": {{
    "title": "краткое описание задачи (макс 100 символов)",
    "description": "полное описание задачи",
    "assignee_usernames": ["username1", "username2"] или [] если не указаны,
    "due_date": "YYYY-MM-DD HH:MM:SS или null",
    "priority": "low/normal/high/urgent"
  }}
}}

Примеры:

Сообщение: "@alex сделай отчет по продажам до завтра"
Ответ:
{{
  "has_task": true,
  "task": {{
    "title": "Сделать отчет по продажам",
    "description": "Сделать отчет по продажам до завтра",
    "assignee_usernames": ["alex"],
    "due_date": "2025-11-19 23:59:59",
    "priority": "normal"
  }}
}}

Сообщение: "@alex @maria подготовьте презентацию к среде"
Ответ:
{{
  "has_task": true,
  "task": {{
    "title": "Подготовить презентацию",
    "description": "Подготовить презентацию к среде",
    "assignee_usernames": ["alex", "maria"],
    "due_date": "2025-11-20 23:59:59",
    "priority": "normal"
  }}
}}

Сообщение: "Саша и Маша, срочно исправьте баг с авторизацией к вечеру"
Ответ:
{{
  "has_task": true,
  "task": {{
    "title": "Исправить баг с авторизацией",
    "description": "Срочно исправить баг с авторизацией к вечеру",
    "assignee_usernames": ["Саша", "Маша"],
    "due_date": "2025-11-26 18:00:00",
    "priority": "high"
  }}
}}

Сообщение: "@john подготовь документы к понедельнику к 10 утра"
Ответ:
{{
  "has_task": true,
  "task": {{
    "title": "Подготовить документы",
    "description": "Подготовить документы к понедельнику к 10 утра",
    "assignee_usernames": ["john"],
    "due_date": "2025-12-02 10:00:00",
    "priority": "normal"
  }}
}}

Сообщение: "@team проверьте тесты через 2 часа"
Ответ:
{{
  "has_task": true,
  "task": {{
    "title": "Проверить тесты",
    "description": "Проверить тесты через 2 часа",
    "assignee_usernames": ["team"],
    "due_date": "2025-11-26 16:30:00",
    "priority": "normal"
  }}
}}

Сообщение: "Хорошая погода сегодня"
Ответ:
{{
  "has_task": false,
  "task": null
}}

Отвечай ТОЛЬКО JSON, без дополнительных комментариев!
"""


async def analyze_message_with_ai(text: str) -> Optional[Dict[str, Any]]:
  
    if not text or len(text.strip()) == 0:
        return None

    try:
        # Получаем текущую дату и время
        current_dt = get_current_datetime()

        # Формируем промпт с текущей датой
        system_prompt = SYSTEM_PROMPT.format(current_datetime=current_dt)

        # Вызываем OpenAI API
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
        if task and task.get("due_date"):
            try:
                
                due_date_str = task["due_date"]
                task["due_date_parsed"] = date_parser.parse(due_date_str)
            except Exception as date_error:
                logger.warning(f"Failed to parse due_date: {task.get('due_date')}, error: {date_error}")
                task["due_date_parsed"] = None

        return result

    except Exception as e:
        logger.error(f"Error in AI analysis: {e}", exc_info=True)
        return None


async def analyze_email_with_ai(text: str) -> Optional[Dict[str, Any]]:
    """
    Анализирует email письмо с помощью AI и извлекает задачу.
    Использует специальный промпт для email, который более чувствителен к деловым письмам.
    """
    if not text or len(text.strip()) == 0:
        return None

    try:
        # Получаем текущую дату и время
        current_dt = get_current_datetime()

        # Формируем промпт с текущей датой (используем EMAIL_SYSTEM_PROMPT)
        system_prompt = EMAIL_SYSTEM_PROMPT.format(current_datetime=current_dt)

        # Вызываем OpenAI API
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

        # Парсим ответ
        result_text = response.choices[0].message.content
        logger.info(f"OpenAI response for email: {result_text}")

        # Преобразуем в dict
        result = json.loads(result_text)

        # Валидация формата
        if not isinstance(result, dict) or "has_task" not in result:
            logger.error(f"Invalid AI response format: {result}")
            return None

        # Если задачи нет - возвращаем результат
        if not result.get("has_task", False):
            return result

        # Парсим due_date если есть
        task = result.get("task")
        if task and task.get("due_date"):
            try:
                # Парсим строку даты в объект datetime
                due_date_str = task["due_date"]
                task["due_date_parsed"] = date_parser.parse(due_date_str)
            except Exception as date_error:
                logger.warning(f"Failed to parse due_date: {task.get('due_date')}, error: {date_error}")
                task["due_date_parsed"] = None

        return result

    except Exception as e:
        logger.error(f"Error in AI email analysis: {e}", exc_info=True)
        return None


def extract_task_simple(text: str) -> bool:
    
    if not text:
        return False

    text_lower = text.lower()

    
    task_keywords = [
        "сделать", "нужно", "необходимо", "надо", "требуется",
        "выполни", "подготовь", "создай", "напиши", "исправь",
        "проверь", "убедись", "организуй", "настрой",
        "до", "к", "срочно", "важно", "deadline",
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

    # Если AI включен, пробуем использовать его
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
        return {
            "has_task": True,
            "task": {
                "title": text[:100],  
                "description": text,
                "assignee_username": None,
                "due_date": None,
                "due_date_parsed": None,
                "priority": "normal"
            }
        }
    else:
        return {
            "has_task": False,
            "task": None
        }
