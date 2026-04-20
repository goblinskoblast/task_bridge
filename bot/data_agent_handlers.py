import logging

import asyncio
import html
import re

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User as TelegramUser
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from bot.data_agent_client import DataAgentClientError, data_agent_client
from bot.report_delivery import (
    build_report_delivery_message,
    is_report_delivery_candidate,
    trim_telegram_text,
)
from bot.voice_transcription import VoiceTranscriptionError, transcribe_telegram_voice
from bot.webapp_links import build_taskbridge_webapp_url
from config import DEVELOPER_TELEGRAM_ID
from db.database import get_db_session
from db.models import Chat, DataAgentProfile, Message as MessageModel, SavedPoint, User
from data_agent.italian_pizza import resolve_italian_pizza_point
from data_agent.monitoring import REPORT_CHAT_FALLBACK_LABEL, resolve_user_facing_chat_title
from data_agent.saved_points import SavedPointError, saved_point_service

logger = logging.getLogger(__name__)

router = Router()
_BACKGROUND_AGENT_TASKS: set[asyncio.Task] = set()
_LONG_AGENT_CHAT_TIMEOUT_SECONDS = max(data_agent_client.chat_timeout_seconds, 300)

AGENT_BUTTON_TEXT = "🤖 Агент"
QUICK_REPORTS_BUTTON_TEXT = "⚡ Быстрые отчёты"
MONITORS_BUTTON_TEXT = "📡 Мониторы"
POINTS_BUTTON_TEXT = "📍 Точки"
HELP_BUTTON_TEXT = "❓ Помощь"
REPORT_CHAT_CALLBACK_PREFIX = "agent_report_chat_select:"
REPORT_CHAT_CATEGORY_CALLBACK_PREFIX = "agent_report_chat_category:"
QUICK_REPORT_CALLBACK_PREFIX = "agent_quick:"
POINT_CALLBACK_PREFIX = "agent_point:"
POINT_REPORT_CALLBACK_PREFIX = "agent_point_report:"
POINT_DELIVERY_CALLBACK_PREFIX = "agent_point_delivery:"
SETTINGS_BUTTON_TEXT = "🔧 Системы и чаты"
SYSTEMS_MENU_BUTTON_TEXT = "🔌 Подключённые системы"
REPORT_CHATS_BUTTON_TEXT = "💬 Чаты отчётов"
CONNECT_SYSTEM_BUTTON_TEXT = "➕ Подключить систему"
MONITORS_MENU_BUTTON_TEXT = "📡 Что включено"

AGENT_WELCOME = (
    "🤖 <b>Агент TaskBridge</b>\n\n"
    "Путь здесь короткий:\n"
    "• сначала подключаете систему\n"
    "• потом добавляете точки\n"
    "• дальше просто пишете запрос обычным сообщением\n\n"
    "Например: пришли стоп-лист по Сухой Лог, Белинского 40."
)

AGENT_HOME_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="↩️ В меню агента", callback_data="agent_open")],
    ]
)

AGENT_REPORTS_MENU_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text=POINTS_BUTTON_TEXT, callback_data="agent_show_points")],
        [InlineKeyboardButton(text=MONITORS_MENU_BUTTON_TEXT, callback_data="agent_show_monitors")],
    ]
)

AGENT_SETTINGS_MENU_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text=SYSTEMS_MENU_BUTTON_TEXT, callback_data="agent_show_systems")],
        [InlineKeyboardButton(text=CONNECT_SYSTEM_BUTTON_TEXT, callback_data="agent_connect_system")],
        [InlineKeyboardButton(text=REPORT_CHATS_BUTTON_TEXT, callback_data="agent_choose_report_chat")],
    ]
)

AGENT_SETTINGS_MENU_TEXT = (
    "🔧 <b>Системы и чаты</b>\n\n"
    "Здесь можно проверить подключённые системы и выбрать чаты для отчётов."
)

QUICK_REPORT_ACTIONS = {
    "reviews_day": {
        "title": "Отзывы за сутки",
        "example": "Артемовский, Гагарина 2А",
        "request_builder": lambda point: f"Собери отчёт по отзывам для точки {point} за сутки",
    },
    "reviews_week": {
        "title": "Отзывы за неделю",
        "example": "Артемовский, Гагарина 2А",
        "request_builder": lambda point: f"Собери отчёт по отзывам для точки {point} за неделю",
    },
    "stoplist": {
        "title": "Стоп-лист по точке",
        "example": "Артемовский, Гагарина 2А",
        "request_builder": lambda point: f"Собери отчёт по стоп-листу для точки {point}",
    },
    "blanks_current": {
        "title": "Текущий бланк",
        "example": "Артемовский, Гагарина 2А",
        "request_builder": lambda point: f"Проверь бланки загрузки для точки {point}, текущий бланк",
    },
    "blanks_12h": {
        "title": "Бланки за 12 часов",
        "example": "Артемовский, Гагарина 2А",
        "request_builder": lambda point: f"Проверь бланки загрузки для точки {point}, за последние 12 часов",
    },
}

_REPORT_FAILURE_MESSAGES = {
    "stoplist_report": "Не удалось получить отчет по стоп-листу. Попробуйте позже.",
    "blanks_report": "Не удалось получить отчет по бланкам. Попробуйте позже.",
    "reviews_report": "Не удалось получить отчет по отзывам. Попробуйте позже.",
}

_INTERNAL_ERROR_MARKERS = (
    "не удалось определить публичную точку",
    "техническая ошибка",
    "page.evaluate",
    "locator.evaluate",
    "playwright",
    "trace:",
    "diagnostics",
)

_MOJIBAKE_MARKERS = (
    "????",
    "Рџ",
    "Рњ",
    "Рќ",
    "РЎ",
    "Р°",
    "СЃ",
    "С‚",
    "вЂ",
    "рџ",
)

REPORT_CATEGORY_META = {
    "reviews": {
        "title": "Отзывы",
        "emoji": "⭐",
    },
    "stoplist": {
        "title": "Стоп-лист",
        "emoji": "🚫",
    },
    "blanks": {
        "title": "Бланки",
        "emoji": "🧾",
    },
}

PROFILE_REPORT_CHAT_FIELDS = {
    "reviews": ("reviews_report_chat_id", "reviews_report_chat_title"),
    "stoplist": ("stoplist_report_chat_id", "stoplist_report_chat_title"),
    "blanks": ("blanks_report_chat_id", "blanks_report_chat_title"),
}


def _with_agent_home(keyboard: InlineKeyboardMarkup | None = None) -> InlineKeyboardMarkup:
    if keyboard is None:
        return AGENT_HOME_KEYBOARD

    rows: list[list[InlineKeyboardButton]] = [list(row) for row in keyboard.inline_keyboard]
    has_home = any(
        getattr(button, "callback_data", None) == "agent_open"
        for row in rows
        for button in row
    )
    if not has_home:
        rows.append([InlineKeyboardButton(text="↩️ В меню агента", callback_data="agent_open")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_agent_reports_menu_keyboard() -> InlineKeyboardMarkup:
    return _with_agent_home(AGENT_REPORTS_MENU_KEYBOARD)


def _build_agent_settings_menu_keyboard() -> InlineKeyboardMarkup:
    return _with_agent_home(AGENT_SETTINGS_MENU_KEYBOARD)


def _build_agent_entry_text(*, has_system: bool, has_points: bool) -> str:
    if not has_system:
        return (
            "🤖 <b>Агент TaskBridge</b>\n\n"
            "Сначала подключите систему Italian Pizza.\n"
            "После этого можно будет добавлять точки и запускать отчёты обычным сообщением."
        )

    if not has_points:
        return (
            "🤖 <b>Агент TaskBridge</b>\n\n"
            "Система уже подключена. Теперь добавьте первую точку.\n"
            "После этого можно будет писать запросы по стоп-листу, бланкам и мониторингу."
        )

    return (
        "🤖 <b>Агент TaskBridge</b>\n\n"
        "Проще всего просто написать запрос обычным сообщением.\n\n"
        "Например:\n"
        "• пришли стоп-лист по Сухой Лог, Белинского 40\n"
        "• покажи бланки по всем добавленным точкам\n"
        "• что у меня включено\n"
        "• присылай бланки по Сухой Лог, Белинского 40 каждые 3 часа"
    )


def _build_agent_entry_keyboard(*, has_system: bool, has_points: bool) -> InlineKeyboardMarkup:
    if not has_system:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=CONNECT_SYSTEM_BUTTON_TEXT, callback_data="agent_connect_system")],
            ]
        )

    if not has_points:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="➕ Добавить точку", callback_data="agent_point_add")],
                [InlineKeyboardButton(text=SETTINGS_BUTTON_TEXT, callback_data="agent_menu_settings")],
            ]
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=POINTS_BUTTON_TEXT, callback_data="agent_show_points")],
            [InlineKeyboardButton(text=MONITORS_MENU_BUTTON_TEXT, callback_data="agent_show_monitors")],
            [InlineKeyboardButton(text=SETTINGS_BUTTON_TEXT, callback_data="agent_menu_settings")],
        ]
    )


def _build_agent_systems_keyboard() -> InlineKeyboardMarkup:
    return _with_agent_home(InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=CONNECT_SYSTEM_BUTTON_TEXT, callback_data="agent_connect_system")],
            [InlineKeyboardButton(text=REPORT_CHATS_BUTTON_TEXT, callback_data="agent_choose_report_chat")],
        ]
    ))


def _build_slim_main_reply_keyboard(webapp_url: str) -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Панель задач", web_app=WebAppInfo(url=webapp_url))],
            [KeyboardButton(text=AGENT_BUTTON_TEXT), KeyboardButton(text="💬 Поддержка")],
            [KeyboardButton(text=HELP_BUTTON_TEXT)],
        ],
        resize_keyboard=True,
        persistent=True,
        input_field_placeholder="Напишите задачу или запрос агенту",
    )


async def _refresh_private_main_menu(message: Message, actor_user: TelegramUser | None = None) -> None:
    effective_user = actor_user or message.from_user
    db = get_db_session()
    try:
        user = _get_or_create_user(
            db=db,
            telegram_id=effective_user.id,
            username=effective_user.username,
            first_name=effective_user.first_name,
            last_name=effective_user.last_name,
            is_bot=effective_user.is_bot,
        )
        webapp_url = build_taskbridge_webapp_url(user_id=user.id, mode="executor")
        service_message = await message.answer(
            "Меню обновлено.",
            reply_markup=_build_slim_main_reply_keyboard(webapp_url),
        )
        try:
            await service_message.delete()
        except TelegramBadRequest:
            pass
    finally:
        db.close()


def _sanitize_user_facing_answer(answer: str) -> str:
    text = (answer or "").strip()
    if not text:
        return ""

    hidden_prefixes = ("причина:", "причины:", "этап:", "этапы:")
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        lowered = stripped.lower()
        if lowered.startswith(hidden_prefixes):
            continue
        if any(marker in lowered for marker in _INTERNAL_ERROR_MARKERS):
            continue

        raw_line = re.split(r"\s+(?:Причина|Причины|Этап|Этапы):", raw_line, maxsplit=1, flags=re.IGNORECASE)[0].rstrip()

        if raw_line.strip():
            cleaned_lines.append(raw_line)

    return "\n".join(cleaned_lines).strip()


def _looks_corrupted_user_text(text: str) -> bool:
    normalized = text or ""
    if not normalized:
        return False
    if any(marker in normalized for marker in _MOJIBAKE_MARKERS):
        return True
    question_marks = normalized.count("?")
    letters = sum(1 for char in normalized if char.isalpha())
    return question_marks >= 6 and question_marks >= max(letters // 2, 6)


class ConnectSystemState(StatesGroup):
    waiting_for_url = State()
    waiting_for_login = State()
    waiting_for_password = State()


class PointManagementState(StatesGroup):
    waiting_for_new_point = State()


def _normalize_connect_url(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return raw
    if raw.startswith(("http://", "https://")):
        return raw
    return f"https://{raw}"


def _get_or_create_user(
    db,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
    is_bot: bool,
) -> User:
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_bot=is_bot,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _get_or_create_profile(db, user_id: int) -> DataAgentProfile:
    profile = db.query(DataAgentProfile).filter(DataAgentProfile.user_id == user_id).first()
    if not profile:
        profile = DataAgentProfile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _get_profile_report_chat(profile: DataAgentProfile, category: str) -> tuple[int | None, str | None]:
    fields = PROFILE_REPORT_CHAT_FIELDS.get(category)
    if fields:
        chat_id = getattr(profile, fields[0], None)
        chat_title = getattr(profile, fields[1], None)
        if chat_id:
            return int(chat_id), resolve_user_facing_chat_title(chat_title) or REPORT_CHAT_FALLBACK_LABEL
    if profile.default_report_chat_id:
        return (
            int(profile.default_report_chat_id),
            resolve_user_facing_chat_title(profile.default_report_chat_title) or REPORT_CHAT_FALLBACK_LABEL,
        )
    return None, None


def _set_profile_report_chat(profile: DataAgentProfile, category: str, chat: Chat) -> None:
    fields = PROFILE_REPORT_CHAT_FIELDS[category]
    title = chat.title or chat.username or str(chat.chat_id)
    setattr(profile, fields[0], chat.chat_id)
    setattr(profile, fields[1], title)


def _clear_profile_report_chat(profile: DataAgentProfile, category: str) -> None:
    fields = PROFILE_REPORT_CHAT_FIELDS[category]
    setattr(profile, fields[0], None)
    setattr(profile, fields[1], None)


def _resolve_report_category_from_action(action_key: str) -> str | None:
    if action_key in {"reviews_day", "reviews_week"}:
        return "reviews"
    if action_key == "stoplist":
        return "stoplist"
    if action_key in {"blanks_current", "blanks_12h"}:
        return "blanks"
    return None


def _resolve_report_category_from_result(result: dict) -> str | None:
    scenario = (result.get("scenario") or "").strip()
    if scenario == "reviews_report":
        return "reviews"
    if scenario == "stoplist_report":
        return "stoplist"
    if scenario == "blanks_report":
        return "blanks"
    return None


def _get_user_report_chats(db, user_id: int) -> list[Chat]:
    chat_rows = (
        db.query(Chat)
        .join(MessageModel, MessageModel.chat_id == Chat.chat_id)
        .filter(
            MessageModel.user_id == user_id,
            Chat.is_active.is_(True),
            Chat.chat_type.in_(["group", "supergroup"]),
        )
        .order_by(Chat.updated_at.desc(), Chat.title.asc())
        .all()
    )

    unique_chats: list[Chat] = []
    seen_chat_ids: set[int] = set()
    for item in chat_rows:
        if item.chat_id in seen_chat_ids:
            continue
        unique_chats.append(item)
        seen_chat_ids.add(item.chat_id)
    return unique_chats


def _build_report_chat_categories_keyboard(profile: DataAgentProfile) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []
    for category, meta in REPORT_CATEGORY_META.items():
        current_chat_id, current_title = _get_profile_report_chat(profile, category)
        suffix = f" • {current_title[:24]}" if current_title else " • не выбран"
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{meta['emoji']} {meta['title']}{suffix}",
                    callback_data=f"{REPORT_CHAT_CATEGORY_CALLBACK_PREFIX}{category}",
                )
            ]
        )
    return _with_agent_home(InlineKeyboardMarkup(inline_keyboard=buttons))


def _build_report_chat_keyboard(
    chats: list[Chat],
    selected_chat_id: int | None,
    category: str = "reviews",
) -> InlineKeyboardMarkup:
    buttons = []
    for item in chats[:10]:
        label = item.title or item.username or f"chat {item.chat_id}"
        prefix = "✅ " if selected_chat_id == item.chat_id else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix}{label[:40]}",
                    callback_data=f"{REPORT_CHAT_CALLBACK_PREFIX}{category}:{item.chat_id}",
                )
            ]
        )

    buttons.append(
        [InlineKeyboardButton(text="Отключить доставку в этот чат", callback_data=f"agent_report_chat_clear:{category}")]
    )
    buttons.append([InlineKeyboardButton(text="↩️ К категориям", callback_data="agent_choose_report_chat")])
    return _with_agent_home(InlineKeyboardMarkup(inline_keyboard=buttons))


def _get_requester_name(message: Message) -> str:
    if message.from_user.username:
        return f"@{message.from_user.username}"
    return message.from_user.first_name or "Пользователь"


def _get_requester_name_from_actor(actor_user: TelegramUser | None, fallback_message: Message) -> str:
    if actor_user:
        if actor_user.username:
            return f"@{actor_user.username}"
        return actor_user.first_name or "Пользователь"
    return _get_requester_name(fallback_message)


def _is_developer_telegram_id(telegram_user_id: int | None) -> bool:
    return bool(DEVELOPER_TELEGRAM_ID and telegram_user_id == DEVELOPER_TELEGRAM_ID)


def _build_user_safe_agent_answer(result: dict) -> str:
    scenario = (result.get("scenario") or "").strip()
    status = (result.get("status") or "").strip()
    answer = _sanitize_user_facing_answer((result.get("answer") or "").strip())
    if scenario in _REPORT_FAILURE_MESSAGES and (
        _looks_corrupted_user_text(answer)
        or any(marker in answer.lower() for marker in _INTERNAL_ERROR_MARKERS)
    ):
        return _REPORT_FAILURE_MESSAGES[scenario]
    if status == "failed" and scenario in _REPORT_FAILURE_MESSAGES:
        return _REPORT_FAILURE_MESSAGES[scenario]
    return answer or "Не удалось получить ответ от агента."


def _normalize_delivery_text(value: str) -> str:
    normalized = (value or "").lower().replace("ё", "е")
    normalized = re.sub(r"[^a-zа-я0-9]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _build_delivery_point_aliases(point: SavedPoint) -> set[str]:
    aliases = {
        _normalize_delivery_text(point.display_name),
        _normalize_delivery_text(f"{point.city} {point.address}"),
    }
    if point.external_point_key:
        aliases.add(_normalize_delivery_text(point.external_point_key))
    return {alias for alias in aliases if alias}


def _find_delivery_points_for_message(
    db,
    telegram_user_id: int,
    user_message: str,
    *,
    require_delivery_enabled: bool = True,
) -> list[SavedPoint]:
    points = saved_point_service.list_points(db, telegram_user_id)
    if require_delivery_enabled:
        points = [item for item in points if item.report_delivery_enabled]
    if not points:
        return []

    normalized_message = _normalize_delivery_text(user_message)
    message_aliases = {normalized_message} if normalized_message else set()

    resolved = resolve_italian_pizza_point(user_message or "")
    if resolved:
        message_aliases.add(_normalize_delivery_text(f"{resolved.city} {resolved.address}"))
        if resolved.public_slug:
            message_aliases.add(_normalize_delivery_text(resolved.public_slug))

    matched: list[SavedPoint] = []
    for point in points:
        aliases = _build_delivery_point_aliases(point)
        if any(
            alias and any(alias in candidate or candidate in alias for candidate in message_aliases if candidate)
            for alias in aliases
        ):
            matched.append(point)
    return matched


def _build_delivery_disabled_notice(points: list[SavedPoint]) -> str:
    if not points:
        return "В чат не отправлено: для выбранной точки выключена отправка."
    if len(points) == 1:
        return (
            f"В чат не отправлено: для точки <b>{points[0].display_name}</b> выключена отправка.\n\n"
            "Откройте точку и включите кнопку «📨 В чат»."
        )
    return (
        "В чат не отправлено: для выбранных точек выключена отправка.\n\n"
        "Откройте нужные точки и включите кнопку «📨 В чат»."
    )


async def _deliver_report_to_selected_chat(
    message: Message,
    user_message: str,
    answer: str,
    *,
    report_category: str | None = None,
    telegram_user_id: int | None = None,
    requester_name: str | None = None,
) -> str | None:
    db = get_db_session()
    try:
        effective_telegram_user_id = telegram_user_id or message.from_user.id
        logger.info(
            "Report delivery requested telegram_user_id=%s category=%s answer_len=%s",
            effective_telegram_user_id,
            report_category,
            len((answer or "").strip()),
        )
        user = db.query(User).filter(User.telegram_id == effective_telegram_user_id).first()
        if not user:
            logger.warning("Report delivery skipped: user not found telegram_user_id=%s", effective_telegram_user_id)
            return None

        profile = _get_or_create_profile(db, user.id)
        target_chat_id, target_chat_title = _get_profile_report_chat(profile, report_category or "")
        if not target_chat_id:
            logger.info(
                "Report delivery skipped: no report chat user_id=%s category=%s",
                user.id,
                report_category,
            )
            return None

        chat = (
            db.query(Chat)
            .filter(
                Chat.chat_id == target_chat_id,
            )
            .first()
        )
        chat_title = (
            (chat.title if chat and chat.title else None)
            or (chat.username if chat and chat.username else None)
            or target_chat_title
            or str(target_chat_id)
        )
        logger.info(
            "Report delivery attempt telegram_user_id=%s user_id=%s category=%s target_chat_id=%s title=%s",
            effective_telegram_user_id,
            user.id,
            report_category,
            target_chat_id,
            chat_title,
        )

        delivery_text = build_report_delivery_message(
            requester_name=requester_name or _get_requester_name(message),
            user_message=user_message,
            answer=answer,
        )
        await message.bot.send_message(
            chat_id=target_chat_id,
            text=trim_telegram_text(delivery_text),
            parse_mode=None,
        )
        logger.info(
            "Report delivery success telegram_user_id=%s user_id=%s category=%s target_chat_id=%s",
            effective_telegram_user_id,
            user.id,
            report_category,
            target_chat_id,
        )
        return chat_title
    except Exception as exc:
        logger.error("Report delivery to selected chat failed: %s", exc, exc_info=True)
        return None
    finally:
        db.close()


def _get_command_args(raw_text: str | None) -> str:
    parts = (raw_text or "").split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def _looks_like_systems_summary_request(text: str) -> bool:
    lowered = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if not lowered or "систем" not in lowered:
        return False
    if any(marker in lowered for marker in ("подключи", "подключить", "добавь", "добавить")):
        return False
    if lowered.startswith(("подключенные системы", "подключённые системы")):
        return True
    return any(
        marker in lowered
        for marker in (
            "какие",
            "какая",
            "покажи",
            "показать",
            "список",
            "что у меня",
            "есть ли",
            "активные",
        )
    )


def _build_quick_report_request(action_key: str, point: str) -> str:
    action = QUICK_REPORT_ACTIONS[action_key]
    return action["request_builder"](point.strip())


def _build_legacy_quick_report_hint(action_key: str, *, point_name: str | None = None) -> str:
    primary_point = point_name or "Сухой Лог, Белинского 40"
    secondary_point = point_name or "Верхний Уфалей"
    examples = {
        "reviews_day": (
            f"собери отзывы по {primary_point} за сутки",
            f"собери отзывы по {primary_point} за неделю" if point_name else f"собери отзывы по {secondary_point} за сутки",
        ),
        "reviews_week": (
            f"собери отзывы по {primary_point} за неделю",
            f"собери отзывы по {primary_point} за сутки" if point_name else f"собери отзывы по {secondary_point} за неделю",
        ),
        "stoplist": (
            f"пришли стоп-лист по {primary_point}",
            f"присылай стоп-лист по {primary_point} каждые 3 часа" if point_name else f"покажи стоп-лист по {secondary_point}",
        ),
        "blanks_current": (
            f"покажи бланки по {primary_point}",
            f"присылай бланки по {primary_point} каждые 3 часа" if point_name else "покажи бланки по всем добавленным точкам",
        ),
        "blanks_12h": (
            f"покажи бланки по {primary_point} за 12 часов",
            f"присылай бланки по {primary_point} каждые 3 часа" if point_name else "покажи бланки по всем добавленным точкам за 12 часов",
        ),
    }
    selected = examples.get(action_key) or (
        f"пришли стоп-лист по {primary_point}",
        "покажи бланки по всем добавленным точкам",
    )
    return (
        "Сейчас проще написать запрос обычным сообщением.\n\n"
        "Например:\n"
        f"• {selected[0]}\n"
        f"• {selected[1]}"
    )


def _resolve_saved_point_name(telegram_user_id: int, point_id: int) -> str | None:
    db = get_db_session()
    try:
        point = saved_point_service.get_point(db, telegram_user_id, point_id)
        if not point or not point.is_active:
            return None
        return point.display_name
    finally:
        db.close()


def _build_voice_request_preview(text: str) -> str:
    normalized = " ".join((text or "").strip().split())
    if len(normalized) > 280:
        normalized = normalized[:277].rstrip() + "..."
    return f"Распознал запрос:\n{normalized}"


def _point_button_label(point: SavedPoint) -> str:
    label = point.display_name
    if len(label) > 34:
        label = label[:31].rstrip() + "..."
    return label


def _build_points_overview_keyboard(points: list[SavedPoint]) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text=_point_button_label(point), callback_data=f"{POINT_CALLBACK_PREFIX}{point.id}")]
        for point in points[:8]
    ]
    if len(points) > 1:
        buttons.append([InlineKeyboardButton(text="🌐 Все точки", callback_data=f"{POINT_CALLBACK_PREFIX}all")])
    buttons.append([InlineKeyboardButton(text="➕ Добавить точку", callback_data="agent_point_add")])
    return _with_agent_home(InlineKeyboardMarkup(inline_keyboard=buttons))


def _build_point_actions_keyboard(point: SavedPoint) -> InlineKeyboardMarkup:
    point_id = point.id
    delivery_label = "📨 В чат: вкл" if point.report_delivery_enabled else "🔕 В чат: выкл"
    return _with_agent_home(InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=delivery_label, callback_data=f"{POINT_DELIVERY_CALLBACK_PREFIX}{point_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"{POINT_CALLBACK_PREFIX}delete:{point_id}"),
            ],
            [InlineKeyboardButton(text="↩️ К списку точек", callback_data="agent_show_points")],
        ]
    ))


def _build_all_points_actions_keyboard() -> InlineKeyboardMarkup:
    return _with_agent_home(InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить точку", callback_data="agent_point_add")],
            [InlineKeyboardButton(text="↩️ К списку точек", callback_data="agent_show_points")],
        ]
    ))


def _build_points_summary_text(points: list[SavedPoint]) -> str:
    if not points:
        return (
            "📍 <b>Сохранённых точек пока нет</b>\n\n"
            "Добавьте первую точку, и дальше сможете писать запросы обычным сообщением без ручного ввода адреса каждый раз."
        )

    lines = ["📍 <b>Ваши точки</b>", ""]
    for index, point in enumerate(points, start=1):
        delivery_mark = " • в чат" if point.report_delivery_enabled else ""
        lines.append(f"• <b>{index}.</b> {point.display_name}{delivery_mark}")
    lines.extend(
        [
            "",
            "Можно открыть одну точку или сразу «Все точки». Для отчётов и мониторинга быстрее всего писать обычным сообщением.",
        ]
    )
    return "\n".join(lines)


def _is_italian_pizza_system(item: dict | None) -> bool:
    payload = item or {}
    system_name = str(payload.get("system_name") or "").strip().lower()
    url = str(payload.get("url") or "").strip().lower()
    return (
        system_name == "italian_pizza"
        or "italianpizza" in url
        or "tochka.italianpizza" in url
        or ("tochka" in url and "pizza" in url)
    )


async def _user_has_connected_italian_pizza_system(telegram_user_id: int) -> bool:
    try:
        systems = await data_agent_client.list_systems(telegram_user_id)
        if any(_is_italian_pizza_system(item) for item in systems):
            return True
    except Exception as exc:
        logger.error("Italian Pizza system lookup via data-agent failed: %s", exc, exc_info=True)

    db = get_db_session()
    try:
        return saved_point_service.get_system_for_user(db, telegram_user_id) is not None
    finally:
        db.close()


async def _call_agent(
    message: Message,
    text: str,
    *,
    actor_user: TelegramUser | None = None,
    chat_timeout_seconds: int | None = None,
    retry_attempts: int = 2,
) -> dict:
    effective_user = actor_user or message.from_user
    return await data_agent_client.chat(
        {
            "user_id": effective_user.id,
            "message": text,
            "username": effective_user.username,
            "first_name": effective_user.first_name,
        },
        timeout_seconds=chat_timeout_seconds,
        retry_attempts=retry_attempts,
    )


def _looks_like_long_agent_request(text: str) -> bool:
    lowered = (text or "").lower()
    return any(
        marker in lowered
        for marker in [
            "стоп-лист",
            "стоп лист",
            "бланк",
            "бланки",
            "отзывы по точке",
            "отзывы по адресу",
            "проверь точку",
            "мониторь",
        ]
    )


def _build_agent_progress_message(text: str) -> str:
    lowered = (text or "").lower()
    if "все" in lowered and any(marker in lowered for marker in ["точк", "добавлен"]):
        return "⏳ Принял запрос. Собираю отчёт по всем точкам, это может занять пару минут."
    if any(marker in lowered for marker in ["бланк", "стоп-лист", "стоп лист", "отзыв"]):
        return "⏳ Принял запрос. Собираю отчёт, это может занять пару минут."
    return "⏳ Принял запрос. Обрабатываю."


def _schedule_background_agent_request(message: Message, text: str, *, send_progress: bool = True) -> None:
    task = asyncio.create_task(_send_agent_request(message, text, send_progress=send_progress))
    _BACKGROUND_AGENT_TASKS.add(task)

    def _cleanup(done_task: asyncio.Task) -> None:
        _BACKGROUND_AGENT_TASKS.discard(done_task)
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc:
            logger.error("Background agent task failed: %s", exc, exc_info=True)

    task.add_done_callback(_cleanup)


def _resolve_agent_chat_timeout_seconds(text: str, *, send_progress: bool) -> int | None:
    if send_progress or not _looks_like_long_agent_request(text):
        return None
    return _LONG_AGENT_CHAT_TIMEOUT_SECONDS


def _resolve_agent_retry_attempts(text: str, *, send_progress: bool) -> int:
    if send_progress or not _looks_like_long_agent_request(text):
        return 2
    return 1


def _format_agent_debug_message(result: dict) -> str:
    summary = (result.get("summary") or "").strip()
    if summary:
        lines = ["Последняя диагностика агента:", summary]
    else:
        lines = ["Последняя диагностика агента недоступна."]

    user_message = (result.get("user_message") or "").strip()
    if user_message:
        lines.extend(["", f"Последний запрос: {user_message[:500]}"])

    answer = (result.get("answer") or "").strip()
    if answer:
        lines.extend(["", f"Последний ответ: {answer[:700]}"])

    return trim_telegram_text("\n".join(lines))


async def _send_agent_debug_message(message: Message, telegram_user_id: int) -> None:
    try:
        result = await data_agent_client.get_debug(telegram_user_id)
    except Exception as exc:
        logger.error("Agent debug error: %s", exc, exc_info=True)
        await message.answer("Не удалось получить последнюю диагностику агента.")
        return

    if not result.get("found"):
        await message.answer("Для этого пользователя пока нет сохранённой диагностики агента.")
        return

    await message.answer(_format_agent_debug_message(result))


async def _send_quick_report_request(message: Message, command_text: str | None, prefix: str) -> None:
    args = _get_command_args(command_text)
    payload = f"{prefix}. {args}".strip() if args else prefix
    await _dispatch_agent_request(message, payload)


async def _send_systems_summary(message: Message, *, telegram_user_id: int | None = None) -> None:
    effective_user_id = telegram_user_id or message.from_user.id
    try:
        systems = await data_agent_client.list_systems(effective_user_id)
    except Exception as exc:
        logger.error("Agent systems error: %s", exc, exc_info=True)
        await message.answer("Не удалось получить список подключённых систем.", reply_markup=AGENT_HOME_KEYBOARD)
        return

    if not systems:
        await message.answer(
            "🔌 <b>Подключённых систем пока нет</b>\n\n"
            "Сначала подключите систему, потом сможете добавлять точки и настраивать чаты для отчётов.",
            reply_markup=_build_agent_systems_keyboard(),
            parse_mode="HTML",
        )
        return

    lines = ["🔌 <b>Подключённые системы</b>", ""]
    for item in systems:
        lines.append(f"• <b>{item.get('system_name', 'web-system')}</b> — {item.get('url')}")
    lines.extend(["", "Здесь же можно подключить новую систему или выбрать чат для отчётов."])
    await message.answer("\n".join(lines), reply_markup=_build_agent_systems_keyboard(), parse_mode="HTML")


async def _send_monitors_summary(message: Message, *, telegram_user_id: int | None = None) -> None:
    effective_user_id = telegram_user_id or message.from_user.id
    try:
        monitors = await data_agent_client.list_monitors(effective_user_id)
    except Exception as exc:
        logger.error("Agent monitors error: %s", exc, exc_info=True)
        await message.answer("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c \u0441\u043f\u0438\u0441\u043e\u043a \u043c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433\u043e\u0432.", reply_markup=AGENT_HOME_KEYBOARD)
        return

    if not monitors:
        await message.answer(
            "\U0001f4e1 <b>\u0410\u043a\u0442\u0438\u0432\u043d\u044b\u0445 \u043c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433\u043e\u0432 \u043f\u043e\u043a\u0430 \u043d\u0435\u0442</b>\n\n"
            "\u041f\u0440\u0438\u043c\u0435\u0440: <code>\u043f\u0440\u0438\u0441\u044b\u043b\u0430\u0439 \u043c\u043d\u0435 \u0431\u043b\u0430\u043d\u043a\u0438 \u043f\u043e \u0421\u0443\u0445\u043e\u0439 \u041b\u043e\u0433 \u0411\u0435\u043b\u0438\u043d\u0441\u043a\u043e\u0433\u043e 40 \u043a\u0430\u0436\u0434\u044b\u0435 3 \u0447\u0430\u0441\u0430</code>",
            reply_markup=AGENT_HOME_KEYBOARD,
            parse_mode="HTML",
        )
        return

    active_alert_count = sum(1 for item in monitors if item.get("status_tone") == "alert" or item.get("has_active_alert"))
    retry_count = sum(1 for item in monitors if item.get("status_tone") == "retry")
    lines = [f"📡 <b>Активные мониторинги: {len(monitors)}</b>"]
    if active_alert_count:
        lines.append(f"🔴 Красная зона сейчас: {active_alert_count}")
    if retry_count:
        lines.append(f"🟡 Нужна повторная проверка: {retry_count}")
    lines.append("")
    for item in monitors:
        monitor_label = {
            "blanks": "Бланки",
            "stoplist": "Стоп-лист",
            "reviews": "Отзывы",
        }.get(item.get("monitor_type"), item.get("monitor_type"))
        interval_label = item.get("interval_label") or f"\u043a\u0430\u0436\u0434\u044b\u0435 {item.get('check_interval_minutes')} \u043c\u0438\u043d."
        details = [str(interval_label)]
        if item.get("window_label"):
            details.append(str(item.get("window_label")))

        status_icon = item.get("status_icon") or ("🔴" if item.get("has_active_alert") else "ℹ️")
        status_label = item.get("status_label") or item.get("last_status") or "\u0435\u0449\u0451 \u043d\u0435 \u0431\u044b\u043b\u043e"
        last_checked_label = item.get("last_checked_label") or "\u0435\u0449\u0451 \u043d\u0435 \u0431\u044b\u043b\u043e"
        next_check_label = item.get("next_check_label") or "\u0432 \u0431\u043b\u0438\u0436\u0430\u0439\u0448\u0438\u0439 \u0446\u0438\u043a\u043b"
        last_event_title = item.get("last_event_title") or "Последнее уведомление"
        last_event_label = item.get("last_event_label") or "\u043f\u043e\u043a\u0430 \u043d\u0435 \u0431\u044b\u043b\u043e"
        delivery_label = item.get("delivery_label")
        behavior_label = item.get("behavior_label")
        point_name = html.escape(str(item.get("point_name") or ""))

        lines.append(f"{status_icon} <b>{html.escape(str(monitor_label))}</b> — {point_name}")
        lines.append(f"  {html.escape('; '.join(details))}")
        lines.append(f"  сейчас: {html.escape(str(status_label))}")
        lines.append(
            f"  проверка: {html.escape(str(last_checked_label))}; дальше: {html.escape(str(next_check_label))}"
        )
        if behavior_label:
            lines.append(f"  пришлю: {html.escape(str(behavior_label))}")
        lines.append(f"  {html.escape(str(last_event_title).lower())}: {html.escape(str(last_event_label))}")
        if delivery_label:
            lines.append(f"  куда: {html.escape(str(delivery_label))}")
        lines.append("")

    lines.extend(
        [
            "Изменить: <code>присылай бланки по Сухой Лог Белинского 40 каждые 2 часа с 11 до 21</code>",
            "Отключить: <code>не присылай бланки по Сухой Лог Белинского 40</code>",
        ]
    )
    await message.answer("\n".join(lines), reply_markup=AGENT_HOME_KEYBOARD, parse_mode="HTML")


async def _send_points_summary(message: Message, *, telegram_user_id: int | None = None) -> None:
    effective_user_id = telegram_user_id or message.from_user.id
    has_system = await _user_has_connected_italian_pizza_system(effective_user_id)
    db = get_db_session()
    try:
        points = saved_point_service.list_points(db, effective_user_id)
        if not points and not has_system:
            await message.answer(
                "📍 <b>Точки пока недоступны</b>\n\n"
                "Сначала подключите систему Italian Pizza, а затем добавьте точки к этой системе.",
                reply_markup=_build_agent_systems_keyboard(),
                parse_mode="HTML",
            )
            return
        if not points:
            await message.answer(
                "📍 <b>Точки пока не добавлены</b>\n\n"
                "Система уже подключена. Теперь добавьте первую точку, и дальше можно будет запрашивать стоп-лист, бланки и мониторинги обычным сообщением.",
                reply_markup=_build_points_overview_keyboard(points),
                parse_mode="HTML",
            )
            return
        await message.answer(
            _build_points_summary_text(points),
            reply_markup=_build_points_overview_keyboard(points),
            parse_mode="HTML",
        )
    finally:
        db.close()


async def _send_agent_reports_menu(message: Message) -> None:
    await message.answer(
        "💬 <b>Сейчас быстрее так</b>\n\n"
        "Если система и точки уже добавлены, просто напишите запрос обычным сообщением.\n\n"
        "Например:\n"
        "• пришли стоп-лист по Сухой Лог, Белинского 40\n"
        "• покажи бланки по всем добавленным точкам\n"
        "• собери отзывы по Верхнему Уфалею за неделю\n"
        "• что у меня включено",
        reply_markup=_build_agent_reports_menu_keyboard(),
        parse_mode="HTML",
    )


async def _send_agent_settings_menu(message: Message) -> None:
    await message.answer(
        AGENT_SETTINGS_MENU_TEXT,
        reply_markup=_build_agent_settings_menu_keyboard(),
        parse_mode="HTML",
    )


async def _send_point_details(message: Message, telegram_user_id: int, point_id: int) -> None:
    db = get_db_session()
    try:
        point = saved_point_service.get_point(db, telegram_user_id, point_id)
        if not point or not point.is_active:
            await message.answer("Точка не найдена или уже удалена.", reply_markup=AGENT_HOME_KEYBOARD)
            return
        await message.answer(
            "📍 <b>Точка</b>\n\n"
            f"<b>{point.display_name}</b>\n"
            f"Отправка отчётов в чат: {'включена' if point.report_delivery_enabled else 'выключена'}\n\n"
            f"Эту точку можно использовать в обычном сообщении, например: <code>пришли стоп-лист по {point.display_name}</code>",
            reply_markup=_build_point_actions_keyboard(point),
            parse_mode="HTML",
        )
    finally:
        db.close()


async def _send_all_points_details(message: Message, telegram_user_id: int) -> None:
    db = get_db_session()
    try:
        points = saved_point_service.list_points(db, telegram_user_id)
        if not points:
            await message.answer("Сначала добавьте хотя бы одну точку.", reply_markup=AGENT_HOME_KEYBOARD)
            return
        await message.answer(
            _build_points_summary_text(points),
            reply_markup=_build_all_points_actions_keyboard(),
            parse_mode="HTML",
        )
    finally:
        db.close()


async def _send_saved_points_report(
    message: Message,
    action_key: str,
    points: list[SavedPoint],
    *,
    actor_user: TelegramUser | None = None,
) -> None:
    report_category = _resolve_report_category_from_action(action_key)
    waiting = await message.answer(
        f"⏳ Собираю отчёт «{QUICK_REPORT_ACTIONS[action_key]['title']}» по {len(points)} "
        f"{'точке' if len(points) == 1 else 'точкам'}..."
    )
    sections: list[str] = []
    delivered_to_chat: str | None = None
    attempted_delivery = False
    failed_delivery = False
    requester_name = _get_requester_name_from_actor(actor_user, message)
    for point in points:
        logger.info(
            "Saved point report started point_id=%s point=%s delivery_enabled=%s category=%s actor_telegram_id=%s",
            point.id,
            point.display_name,
            point.report_delivery_enabled,
            report_category,
            actor_user.id if actor_user else message.from_user.id,
        )
        try:
            result = await _call_agent(
                message,
                _build_quick_report_request(action_key, point.display_name),
                actor_user=actor_user,
            )
            answer = _build_user_safe_agent_answer(result)
        except DataAgentClientError as exc:
            answer = exc.user_message
        except Exception as exc:
            logger.error("Saved points report failed point=%s error=%s", point.display_name, exc, exc_info=True)
            answer = "Не удалось получить отчёт по этой точке."
        sections.append(f"{point.display_name}\n{answer}")
        if point.report_delivery_enabled:
            attempted_delivery = True
            logger.info(
                "Saved point report delivery attempt point_id=%s point=%s category=%s",
                point.id,
                point.display_name,
                report_category,
            )
            current_chat = await _deliver_report_to_selected_chat(
                message,
                _build_quick_report_request(action_key, point.display_name),
                answer,
                report_category=report_category,
                telegram_user_id=actor_user.id if actor_user else message.from_user.id,
                requester_name=requester_name,
            )
            if current_chat and delivered_to_chat is None:
                delivered_to_chat = current_chat
            if not current_chat:
                logger.warning(
                    "Saved point report delivery failed point_id=%s point=%s category=%s",
                    point.id,
                    point.display_name,
                    report_category,
                )
                failed_delivery = True
        else:
            logger.info(
                "Saved point report delivery skipped point_id=%s point=%s category=%s reason=point_disabled",
                point.id,
                point.display_name,
                report_category,
            )

    final_text = "\n\n".join(sections)
    if len(final_text) > 3900:
        final_text = final_text[:3890].rstrip() + "…"
    await waiting.edit_text(final_text, parse_mode=None, reply_markup=AGENT_HOME_KEYBOARD)
    if delivered_to_chat:
        await message.answer(f"Отчёт также отправлен в чат: {delivered_to_chat}", reply_markup=AGENT_HOME_KEYBOARD)
    elif attempted_delivery and failed_delivery:
        await message.answer("Не удалось продублировать отчёт в выбранный чат.", reply_markup=AGENT_HOME_KEYBOARD)
    elif any(not point.report_delivery_enabled for point in points):
        disabled_points = [point for point in points if not point.report_delivery_enabled]
        await message.answer(
            _build_delivery_disabled_notice(disabled_points),
            reply_markup=AGENT_HOME_KEYBOARD,
            parse_mode="HTML",
        )


async def _dispatch_agent_request(message: Message, text: str) -> None:
    if _looks_like_long_agent_request(text):
        await message.answer(_build_agent_progress_message(text), reply_markup=AGENT_HOME_KEYBOARD)
        _schedule_background_agent_request(message, text, send_progress=False)
        return

    await _send_agent_request(message, text)


async def _send_agent_request(message: Message, text: str, *, send_progress: bool = True) -> None:
    if send_progress:
        await message.answer(_build_agent_progress_message(text), reply_markup=AGENT_HOME_KEYBOARD)

    try:
        result = await _call_agent(
            message,
            text,
            chat_timeout_seconds=_resolve_agent_chat_timeout_seconds(text, send_progress=send_progress),
            retry_attempts=_resolve_agent_retry_attempts(text, send_progress=send_progress),
        )
    except DataAgentClientError as exc:
        logger.error(
            "Agent chat transport error type=%s user_id=%s message=%s detail=%s",
            type(exc).__name__,
            message.from_user.id,
            text[:300],
            exc,
            exc_info=True,
        )
        await message.answer(exc.user_message, reply_markup=AGENT_HOME_KEYBOARD)
        return
    except Exception as exc:
        logger.error(
            "Agent chat unexpected error user_id=%s message=%s detail=%s",
            message.from_user.id,
            text[:300],
            exc,
            exc_info=True,
        )
        await message.answer(
            "Сейчас не удалось обработать запрос. Попробуйте ещё раз чуть позже.",
            reply_markup=AGENT_HOME_KEYBOARD,
        )
        return

    answer = trim_telegram_text(_build_user_safe_agent_answer(result))
    await message.answer(answer, reply_markup=AGENT_HOME_KEYBOARD, parse_mode=None)

    if is_report_delivery_candidate(result):
        report_category = _resolve_report_category_from_result(result)
        db = get_db_session()
        try:
            matched_points = _find_delivery_points_for_message(
                db,
                message.from_user.id,
                text,
                require_delivery_enabled=False,
            )
            delivery_points = [point for point in matched_points if point.report_delivery_enabled]
        finally:
            db.close()

        logger.info(
            "Agent request delivery candidate telegram_user_id=%s category=%s matched_points=%s enabled_points=%s",
            message.from_user.id,
            report_category,
            [point.display_name for point in matched_points],
            [point.display_name for point in delivery_points],
        )
        if delivery_points:
            delivered_to_chat = await _deliver_report_to_selected_chat(
                message,
                text,
                answer,
                report_category=report_category,
                telegram_user_id=message.from_user.id,
                requester_name=_get_requester_name(message),
            )
            if delivered_to_chat:
                await message.answer(
                    f"Отчёт также отправлен в чат: {delivered_to_chat}",
                    reply_markup=AGENT_HOME_KEYBOARD,
                )
            else:
                await message.answer(
                    "Не удалось продублировать отчёт в выбранный чат.",
                    reply_markup=AGENT_HOME_KEYBOARD,
                )
        elif matched_points:
            logger.info(
                "Agent request delivery skipped telegram_user_id=%s category=%s reason=all_points_disabled",
                message.from_user.id,
                report_category,
            )
            await message.answer(
                _build_delivery_disabled_notice(matched_points),
                reply_markup=AGENT_HOME_KEYBOARD,
                parse_mode="HTML",
            )
        else:
            logger.info(
                "Agent request delivery skipped telegram_user_id=%s category=%s reason=no_matched_points",
                message.from_user.id,
                report_category,
            )


async def _open_agent_entry(message: Message, state: FSMContext, *, actor_user: TelegramUser | None = None) -> None:
    effective_user = actor_user or message.from_user
    db = get_db_session()
    try:
        user = _get_or_create_user(
            db=db,
            telegram_id=effective_user.id,
            username=effective_user.username,
            first_name=effective_user.first_name,
            last_name=effective_user.last_name,
            is_bot=effective_user.is_bot,
        )
        _get_or_create_profile(db, user.id)
        await state.clear()
        has_system = saved_point_service.get_system_for_user(db, effective_user.id) is not None
        has_points = bool(saved_point_service.list_points(db, effective_user.id))
        await message.answer(
            _build_agent_entry_text(has_system=has_system, has_points=has_points),
            reply_markup=_build_agent_entry_keyboard(has_system=has_system, has_points=has_points),
            parse_mode="HTML",
        )
    finally:
        db.close()


@router.message(Command("agent"))
@router.message(Command("bigbrother"))
@router.message(Command("dataagent"))
async def cmd_agent(message: Message, state: FSMContext) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) == 1:
        await _open_agent_entry(message, state)
        return
    await _dispatch_agent_request(message, args[1].strip())


@router.message(F.text == AGENT_BUTTON_TEXT)
async def open_agent_from_button(message: Message, state: FSMContext) -> None:
    await _refresh_private_main_menu(message)
    await _open_agent_entry(message, state)


@router.message(F.chat.type == "private", F.text == QUICK_REPORTS_BUTTON_TEXT)
async def open_quick_reports_from_button(message: Message, state: FSMContext) -> None:
    await _refresh_private_main_menu(message)
    await state.clear()
    await _send_agent_reports_menu(message)


@router.message(F.chat.type == "private", F.text == MONITORS_BUTTON_TEXT)
async def open_monitors_from_button(message: Message, state: FSMContext) -> None:
    await _refresh_private_main_menu(message)
    await state.clear()
    await _send_monitors_summary(message)


@router.message(F.chat.type == "private", F.text == POINTS_BUTTON_TEXT)
async def open_points_from_button(message: Message) -> None:
    await _send_points_summary(message)


@router.callback_query(F.data == "agent_open")
async def callback_agent_open(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await _open_agent_entry(callback.message, state, actor_user=callback.from_user)


@router.callback_query(F.data == "agent_menu_reports")
async def callback_agent_menu_reports(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await _send_agent_reports_menu(callback.message)


@router.callback_query(F.data == "agent_menu_settings")
async def callback_agent_menu_settings(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await _send_agent_settings_menu(callback.message)


@router.callback_query(F.data == "agent_connect_system")
async def callback_agent_connect_system(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ConnectSystemState.waiting_for_url)
    if callback.message:
        await callback.message.answer(
            "🔗 <b>Подключение системы</b>\n\n"
            "Пришлите URL системы одним сообщением.\n"
            "Например: <code>https://portal.example.com</code>",
            reply_markup=AGENT_HOME_KEYBOARD,
            parse_mode="HTML",
        )


@router.callback_query(F.data == "agent_show_systems")
async def callback_agent_show_systems(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await _send_systems_summary(callback.message, telegram_user_id=callback.from_user.id)


@router.callback_query(F.data == "agent_show_monitors")
async def callback_agent_show_monitors(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await _send_monitors_summary(callback.message, telegram_user_id=callback.from_user.id)


@router.callback_query(F.data == "agent_show_points")
async def callback_agent_show_points(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await _send_points_summary(callback.message, telegram_user_id=callback.from_user.id)


@router.callback_query(F.data == "agent_point_add")
async def callback_agent_point_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    has_system = await _user_has_connected_italian_pizza_system(callback.from_user.id)
    if not has_system:
        if callback.message:
            await callback.message.answer(
                "Сначала подключите систему Italian Pizza. После этого можно будет добавлять точки.",
                reply_markup=AGENT_HOME_KEYBOARD,
            )
        return
    await state.set_state(PointManagementState.waiting_for_new_point)
    if callback.message:
        await callback.message.answer(
            "📍 <b>Новая точка</b>\n\n"
            "Точка будет привязана к подключённой системе Italian Pizza.\n\n"
            "Пришлите город и адрес одним сообщением.\n"
            "Например: <code>Сухой Лог, Белинского 40</code>",
            reply_markup=AGENT_HOME_KEYBOARD,
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith(POINT_CALLBACK_PREFIX))
async def callback_agent_point(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return

    payload = callback.data[len(POINT_CALLBACK_PREFIX):]
    if payload == "all":
        await _send_all_points_details(callback.message, callback.from_user.id)
        return

    if payload.startswith("delete:"):
        point_id = int(payload.split(":", 1)[1])
        db = get_db_session()
        try:
            point = saved_point_service.deactivate_point(db, callback.from_user.id, point_id)
        except SavedPointError as exc:
            await callback.message.answer(str(exc))
            return
        finally:
            db.close()
        await callback.message.answer(f"🗑 Точка отключена: {point.display_name}", reply_markup=AGENT_HOME_KEYBOARD)
        await _send_points_summary(callback.message, telegram_user_id=callback.from_user.id)
        return

    if not payload.isdigit():
        await callback.message.answer("Не удалось определить точку.", reply_markup=AGENT_HOME_KEYBOARD)
        return

    point_id = int(payload)
    await _send_point_details(callback.message, callback.from_user.id, point_id)


@router.callback_query(F.data.startswith(POINT_REPORT_CALLBACK_PREFIX))
async def callback_agent_point_report(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    payload = callback.data[len(POINT_REPORT_CALLBACK_PREFIX):]
    payload_parts = payload.split(":", 1)
    point_name: str | None = None
    if len(payload_parts) == 2 and payload_parts[0].isdigit():
        point_name = _resolve_saved_point_name(callback.from_user.id, int(payload_parts[0]))
    action_key = payload_parts[1] if len(payload_parts) == 2 else ""
    if action_key not in QUICK_REPORT_ACTIONS:
        await callback.message.answer("Не удалось определить тип отчёта.", reply_markup=AGENT_HOME_KEYBOARD)
        return

    await callback.message.answer(
        _build_legacy_quick_report_hint(action_key, point_name=point_name),
        reply_markup=AGENT_HOME_KEYBOARD,
    )


@router.callback_query(F.data.startswith(POINT_DELIVERY_CALLBACK_PREFIX))
async def callback_agent_point_delivery(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    point_id_raw = callback.data[len(POINT_DELIVERY_CALLBACK_PREFIX):]
    if not point_id_raw.isdigit():
        await callback.message.answer("Не удалось обновить настройки точки.")
        return
    db = get_db_session()
    try:
        current = saved_point_service.get_point(db, callback.from_user.id, int(point_id_raw))
        if not current:
            await callback.message.answer("Точка не найдена.")
            return
        point = saved_point_service.set_report_delivery(
            db,
            callback.from_user.id,
            int(point_id_raw),
            not current.report_delivery_enabled,
        )
    except SavedPointError as exc:
        await callback.message.answer(str(exc))
        return
    finally:
        db.close()
    await callback.message.answer(
        f"✅ Для точки <b>{point.display_name}</b> отправка отчётов в чат "
        f"{'включена' if point.report_delivery_enabled else 'выключена'}.",
        parse_mode="HTML",
    )
    await _send_point_details(callback.message, callback.from_user.id, point.id)


@router.callback_query(F.data == "agent_quick_cancel")
async def callback_agent_quick_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Отменено")
    await state.clear()
    if callback.message:
        await _open_agent_entry(callback.message, state, actor_user=callback.from_user)


@router.callback_query(F.data == "agent_quick_reviews_day")
async def callback_agent_quick_reviews_day(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer(_build_legacy_quick_report_hint("reviews_day"), reply_markup=AGENT_HOME_KEYBOARD)


@router.callback_query(F.data == "agent_quick_reviews_week")
async def callback_agent_quick_reviews_week(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer(_build_legacy_quick_report_hint("reviews_week"), reply_markup=AGENT_HOME_KEYBOARD)


@router.callback_query(F.data == "agent_quick_stoplist")
async def callback_agent_quick_stoplist(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer(_build_legacy_quick_report_hint("stoplist"), reply_markup=AGENT_HOME_KEYBOARD)


@router.callback_query(F.data == "agent_quick_blanks_current")
async def callback_agent_quick_blanks_current(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer(_build_legacy_quick_report_hint("blanks_current"), reply_markup=AGENT_HOME_KEYBOARD)


@router.callback_query(F.data == "agent_quick_blanks_12h")
async def callback_agent_quick_blanks_12h(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if callback.message:
        await callback.message.answer(_build_legacy_quick_report_hint("blanks_12h"), reply_markup=AGENT_HOME_KEYBOARD)


@router.callback_query(F.data == "agent_hint_reviews")
async def callback_agent_hint_reviews(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Для отчёта по отзывам можно написать, например:\n"
            "собери отзывы по Сухой Лог, Белинского 40 за неделю\n"
            "покажи отзывы по Верхнему Уфалею за сутки"
        )


@router.callback_query(F.data == "agent_hint_stoplist")
async def callback_agent_hint_stoplist(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Для стоп-листа напишите, например:\n"
            "пришли стоп-лист по Сухой Лог, Белинского 40\n"
            "покажи стоп-лист по Верхнему Уфалею"
        )


@router.callback_query(F.data == "agent_hint_blanks")
async def callback_agent_hint_blanks(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Для бланков напишите, например:\n"
            "покажи бланки по Сухой Лог, Белинского 40\n"
            "покажи бланки по всем добавленным точкам за 3 часа"
        )


@router.callback_query(F.data == "agent_hint_monitors")
async def callback_agent_hint_monitors(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Для мониторинга можно написать, например:\n"
            "присылай стоп-лист по Сухой Лог, Белинского 40\n"
            "присылай бланки по Сухой Лог, Белинского 40 каждые 3 часа\n"
            "присылай бланки по Сухой Лог, Белинского 40 каждые 2 часа с 11 до 21\n"
            "не присылай бланки по Сухой Лог, Белинского 40\n"
            "покажи мониторинги\n\n"
            "Если время не указать, возьму окно 10:00–22:00 по Екатеринбургу."
        )


@router.callback_query(F.data == "agent_show_debug")
async def callback_agent_show_debug(callback: CallbackQuery) -> None:
    if not _is_developer_telegram_id(callback.from_user.id):
        await callback.answer("Команда недоступна.", show_alert=False)
        return
    await callback.answer()
    if callback.message:
        await _send_agent_debug_message(callback.message, callback.from_user.id)


@router.message(StateFilter(PointManagementState.waiting_for_new_point), F.text)
async def handle_new_saved_point(message: Message, state: FSMContext) -> None:
    db = get_db_session()
    try:
        point = saved_point_service.save_point(db, message.from_user.id, (message.text or "").strip())
    except SavedPointError as exc:
        await message.answer(str(exc))
        return
    finally:
        db.close()

    await state.clear()
    await message.answer(
        "✅ <b>Точка сохранена</b>\n\n"
        f"{point.display_name}\n"
        "Теперь можно запрашивать по ней стоп-лист, бланки и мониторинг обычным сообщением. Отправку отчётов в чат при необходимости можно включить отдельно.",
        parse_mode="HTML",
    )
    await _send_points_summary(message)


@router.message(Command("systems"))
async def cmd_systems(message: Message) -> None:
    await _send_systems_summary(message)


@router.message(Command("points"))
async def cmd_points(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _send_points_summary(message)


@router.message(Command("addpoint"))
async def cmd_addpoint(message: Message, state: FSMContext) -> None:
    has_system = await _user_has_connected_italian_pizza_system(message.from_user.id)
    if not has_system:
        await message.answer(
            "Сначала подключите систему Italian Pizza. После этого можно будет добавлять точки."
        )
        return
    await state.set_state(PointManagementState.waiting_for_new_point)
    await message.answer(
        "📍 <b>Новая точка</b>\n\n"
        "Точка будет привязана к подключённой системе Italian Pizza.\n\n"
        "Пришлите город и адрес одним сообщением.\n"
        "Например: <code>Сухой Лог, Белинского 40</code>",
        parse_mode="HTML",
    )


@router.message(Command("delpoint"))
async def cmd_delpoint(message: Message) -> None:
    point_id_raw = _get_command_args(message.text)
    if not point_id_raw.isdigit():
        await message.answer(
            "Точки теперь удобнее отключать из меню агента.\n"
            "Откройте <b>Агент → Точки</b>, выберите нужную точку и нажмите «Удалить».",
            reply_markup=AGENT_HOME_KEYBOARD,
            parse_mode="HTML",
        )
        return
    db = get_db_session()
    try:
        point = saved_point_service.deactivate_point(db, message.from_user.id, int(point_id_raw))
    except SavedPointError as exc:
        await message.answer(str(exc))
        return
    finally:
        db.close()
    await message.answer(f"🗑 Точка отключена: {point.display_name}")


@router.message(Command("reviews"))
async def cmd_reviews(message: Message, state: FSMContext) -> None:
    await _send_quick_report_request(message, message.text, "Собери отчёт по отзывам")


@router.message(Command("stoplist"))
async def cmd_stoplist(message: Message, state: FSMContext) -> None:
    await _send_quick_report_request(message, message.text, "Собери отчёт по стоп-листу")


@router.message(Command("blanks"))
async def cmd_blanks(message: Message, state: FSMContext) -> None:
    await _send_quick_report_request(message, message.text, "Проверь бланки загрузки")


@router.message(Command("monitorblanks"))
async def cmd_monitorblanks(message: Message, state: FSMContext) -> None:
    await _send_quick_report_request(message, message.text, "Мониторь бланки загрузки")


@router.message(Command("monitorstoplist"))
async def cmd_monitorstoplist(message: Message, state: FSMContext) -> None:
    await _send_quick_report_request(message, message.text, "Мониторь стоп-лист")


@router.message(Command("monitorreviews"))
async def cmd_monitorreviews(message: Message, state: FSMContext) -> None:
    await _send_quick_report_request(message, message.text, "Мониторь отзывы")


@router.message(Command("monitors"))
async def cmd_monitors(message: Message) -> None:
    await _send_monitors_summary(message)


@router.message(Command("unmonitor"))
async def cmd_unmonitor(message: Message) -> None:
    await message.answer(
        "Мониторинг теперь отключается обычным текстом.\n"
        "Например: <code>не присылай бланки по Сухой Лог, Белинского 40</code>\n"
        "Если по точке включено несколько проверок, уточните: бланки или стоп-лист.",
        parse_mode="HTML",
    )


@router.message(Command("agentdebug"))
async def cmd_agentdebug(message: Message) -> None:
    if not _is_developer_telegram_id(message.from_user.id):
        await message.answer("Команда недоступна.")
        return
    await _send_agent_debug_message(message, message.from_user.id)


@router.message(Command("connect"))
async def cmd_connect(message: Message, state: FSMContext) -> None:
    await state.set_state(ConnectSystemState.waiting_for_url)
    await message.answer(
        "🔗 <b>Подключение системы</b>\n\n"
        "Пришлите URL системы одним сообщением.\n"
        "Например: <code>https://portal.example.com</code>",
        parse_mode="HTML",
    )


@router.message(Command("reportchat"))
async def cmd_reportchat(message: Message) -> None:
    db = get_db_session()
    try:
        user = _get_or_create_user(
            db=db,
            telegram_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            last_name=message.from_user.last_name,
            is_bot=message.from_user.is_bot,
        )
        profile = _get_or_create_profile(db, user.id)
        chats = _get_user_report_chats(db, user.id)
        if not chats:
            await message.answer(
                "💬 Я пока не вижу подходящих групповых чатов.\n\n"
                "Напишите что-нибудь в нужном чате с TaskBridge и повторите команду.",
                reply_markup=AGENT_HOME_KEYBOARD,
            )
            return

        await message.answer(
            "💬 <b>Чаты для отчётов</b>\n\nВыберите категорию и укажите, в какой чат отправлять её отчёты.",
            reply_markup=_build_report_chat_categories_keyboard(profile),
            parse_mode="HTML",
        )
    finally:
        db.close()


@router.callback_query(F.data == "agent_choose_report_chat")
async def callback_agent_choose_report_chat(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return

    db = get_db_session()
    try:
        user = _get_or_create_user(
            db=db,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            is_bot=callback.from_user.is_bot,
        )
        profile = _get_or_create_profile(db, user.id)
        chats = _get_user_report_chats(db, user.id)
        if not chats:
            await callback.message.answer(
                "💬 Я пока не вижу подходящих групповых чатов.\n\n"
                "Напишите сообщение в нужном чате с TaskBridge и попробуйте снова.",
                reply_markup=AGENT_HOME_KEYBOARD,
            )
            return

        await callback.message.answer(
            "💬 <b>Чаты для отчётов</b>\n\nВыберите категорию и укажите, в какой чат отправлять её отчёты.",
            reply_markup=_build_report_chat_categories_keyboard(profile),
            parse_mode="HTML",
        )
    finally:
        db.close()


@router.callback_query(F.data.startswith(REPORT_CHAT_CATEGORY_CALLBACK_PREFIX))
async def callback_agent_report_chat_category(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return

    category = callback.data[len(REPORT_CHAT_CATEGORY_CALLBACK_PREFIX):]
    if category not in REPORT_CATEGORY_META:
        await callback.message.answer("Не удалось определить категорию отчёта.", reply_markup=AGENT_HOME_KEYBOARD)
        return

    db = get_db_session()
    try:
        user = _get_or_create_user(
            db=db,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            is_bot=callback.from_user.is_bot,
        )
        profile = _get_or_create_profile(db, user.id)
        chats = _get_user_report_chats(db, user.id)
        if not chats:
            await callback.message.answer(
                "💬 Я пока не вижу подходящих групповых чатов.\n\n"
                "Напишите сообщение в нужном чате с TaskBridge и попробуйте снова.",
                reply_markup=AGENT_HOME_KEYBOARD,
            )
            return

        selected_chat_id, _ = _get_profile_report_chat(profile, category)
        meta = REPORT_CATEGORY_META[category]
        await callback.message.answer(
            f"💬 <b>{meta['title']}</b>\n\nВыберите чат для этой категории отчётов.",
            reply_markup=_build_report_chat_keyboard(chats, selected_chat_id, category),
            parse_mode="HTML",
        )
    finally:
        db.close()


@router.callback_query(F.data.startswith(REPORT_CHAT_CALLBACK_PREFIX))
async def callback_agent_report_chat_select(callback: CallbackQuery) -> None:
    await callback.answer("Чат для отчётов обновлён")
    if not callback.message:
        return

    payload = callback.data[len(REPORT_CHAT_CALLBACK_PREFIX):]
    category, chat_id_raw = payload.split(":", 1)
    if category not in REPORT_CATEGORY_META or not chat_id_raw.lstrip("-").isdigit():
        await callback.message.answer("Не удалось сохранить настройки чата.", reply_markup=AGENT_HOME_KEYBOARD)
        return

    selected_chat_id = int(chat_id_raw)
    db = get_db_session()
    try:
        user = _get_or_create_user(
            db=db,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            is_bot=callback.from_user.is_bot,
        )
        profile = _get_or_create_profile(db, user.id)
        available_chats = _get_user_report_chats(db, user.id)
        selected_chat = next((item for item in available_chats if item.chat_id == selected_chat_id), None)

        if not selected_chat:
            await callback.message.answer(
                "Этот чат недоступен для выбора. Попробуйте обновить список.",
                reply_markup=AGENT_HOME_KEYBOARD,
            )
            return

        _set_profile_report_chat(profile, category, selected_chat)
        db.commit()

        category_title = REPORT_CATEGORY_META[category]["title"]
        _, chat_title = _get_profile_report_chat(profile, category)
        await callback.message.answer(
            f"✅ Готово. Отчёты категории <b>{category_title}</b> буду дублировать в чат:\n<b>{chat_title}</b>",
            reply_markup=AGENT_HOME_KEYBOARD,
            parse_mode="HTML",
        )
    finally:
        db.close()


@router.callback_query(F.data.startswith("agent_report_chat_clear"))
async def callback_agent_report_chat_clear(callback: CallbackQuery) -> None:
    await callback.answer("Доставка в чат отключена")
    if not callback.message:
        return

    parts = callback.data.split(":", 1)
    category = parts[1] if len(parts) > 1 else ""
    if category not in REPORT_CATEGORY_META:
        await callback.message.answer("Не удалось определить категорию отчёта.", reply_markup=AGENT_HOME_KEYBOARD)
        return

    db = get_db_session()
    try:
        user = _get_or_create_user(
            db=db,
            telegram_id=callback.from_user.id,
            username=callback.from_user.username,
            first_name=callback.from_user.first_name,
            last_name=callback.from_user.last_name,
            is_bot=callback.from_user.is_bot,
        )
        profile = _get_or_create_profile(db, user.id)
        _clear_profile_report_chat(profile, category)
        db.commit()
        category_title = REPORT_CATEGORY_META[category]["title"]
        await callback.message.answer(
            f"✅ Дублирование отчётов категории <b>{category_title}</b> в чат отключено.",
            reply_markup=AGENT_HOME_KEYBOARD,
            parse_mode="HTML",
        )
    finally:
        db.close()


@router.message(StateFilter(ConnectSystemState.waiting_for_url), F.text)
async def connect_waiting_for_url(message: Message, state: FSMContext) -> None:
    normalized_url = _normalize_connect_url(message.text or "")
    await state.update_data(url=normalized_url)
    await state.set_state(ConnectSystemState.waiting_for_login)
    await message.answer(
        f"✅ URL сохранён:\n<code>{normalized_url}</code>\n\nТеперь введите логин для этой системы.",
        parse_mode="HTML",
    )


@router.message(StateFilter(ConnectSystemState.waiting_for_login), F.text)
async def connect_waiting_for_login(message: Message, state: FSMContext) -> None:
    await state.update_data(username=(message.text or "").strip())
    await state.set_state(ConnectSystemState.waiting_for_password)
    await message.answer("🔒 Теперь введите пароль. Сообщение будет удалено после отправки.")


@router.message(StateFilter(ConnectSystemState.waiting_for_password), F.text)
async def connect_waiting_for_password(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    data = await state.get_data()
    await state.clear()

    try:
        await message.delete()
    except Exception:
        pass

    waiting = await message.answer("⏳ Проверяю подключение системы...")
    try:
        result = await data_agent_client.connect_system(
            {
                "user_id": message.from_user.id,
                "url": data.get("url", ""),
                "username": data.get("username", ""),
                "password": password,
            }
        )
        if result.get("success"):
            system = result.get("system") or {}
            await waiting.edit_text(
                "✅ <b>Система подключена</b>\n\n"
                f"<b>Тип:</b> {system.get('system_name', 'web-system')}\n"
                f"<b>URL:</b> {system.get('url', data.get('url', ''))}",
                parse_mode="HTML",
            )
        else:
            logger.warning(
                "Agent connect rejected user_id=%s error=%s",
                message.from_user.id,
                result.get("error"),
            )
            await waiting.edit_text("Не удалось подключить систему. Проверьте адрес и логин/пароль, затем попробуйте ещё раз.")
    except Exception as exc:
        logger.error("Agent connect error: %s", exc, exc_info=True)
        await waiting.edit_text("Не удалось проверить подключение. Попробуйте ещё раз чуть позже.")


@router.message(
    StateFilter(None),
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    F.text != AGENT_BUTTON_TEXT,
    F.text != HELP_BUTTON_TEXT,
)
async def handle_private_agent_message(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if _looks_like_systems_summary_request(text):
        await _send_systems_summary(message)
        return
    await _dispatch_agent_request(message, text)


@router.message(
    StateFilter(None),
    F.chat.type == "private",
    F.voice,
)
async def handle_private_agent_voice(message: Message, state: FSMContext) -> None:
    waiting_message = await message.answer("Распознаю голосовое сообщение...")
    try:
        request_text = await transcribe_telegram_voice(message)
    except VoiceTranscriptionError:
        await waiting_message.edit_text(
            "Не удалось распознать голосовое сообщение. Попробуйте ещё раз или отправьте запрос текстом."
        )
        return

    await waiting_message.edit_text(_build_voice_request_preview(request_text))
    await _dispatch_agent_request(message, request_text)
