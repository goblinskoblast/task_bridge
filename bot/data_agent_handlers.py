import logging

import asyncio

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, User as TelegramUser

from bot.data_agent_client import DataAgentClientError, data_agent_client
from bot.report_delivery import (
    build_report_delivery_message,
    trim_telegram_text,
)
from config import DEVELOPER_TELEGRAM_ID
from db.database import get_db_session
from db.models import Chat, DataAgentProfile, Message as MessageModel, SavedPoint, User
from data_agent.saved_points import SavedPointError, saved_point_service

logger = logging.getLogger(__name__)

router = Router()
_BACKGROUND_AGENT_TASKS: set[asyncio.Task] = set()

AGENT_BUTTON_TEXT = "🤖 Агент"
QUICK_REPORTS_BUTTON_TEXT = "⚡ Быстрые отчёты"
MONITORS_BUTTON_TEXT = "📡 Мониторы"
SYSTEMS_BUTTON_TEXT = "🔌 Системы"
POINTS_BUTTON_TEXT = "📍 Точки"
HELP_BUTTON_TEXT = "❓ Помощь"
REPORT_CHAT_CALLBACK_PREFIX = "agent_report_chat_select:"
QUICK_REPORT_CALLBACK_PREFIX = "agent_quick:"
POINT_CALLBACK_PREFIX = "agent_point:"
POINT_REPORT_CALLBACK_PREFIX = "agent_point_report:"
POINT_DELIVERY_CALLBACK_PREFIX = "agent_point_delivery:"
AGENT_WELCOME = (
    "🤖 <b>Агент TaskBridge</b>\n\n"
    "Чем могу помочь:\n"
    "• отзывы по точкам\n"
    "• стоп-лист и бланки\n"
    "• сохранённые точки и отчёты по ним\n"
    "• мониторинги и отчёты в чат\n"
    "• подключённые веб-системы\n\n"
    "Можно нажать готовую кнопку ниже или просто написать задачу обычным сообщением."
)
AGENT_ENTRY_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ Отзывы за сутки", callback_data="agent_quick_reviews_day"),
            InlineKeyboardButton(text="📈 Отзывы за неделю", callback_data="agent_quick_reviews_week"),
        ],
        [
            InlineKeyboardButton(text="🚫 Стоп-лист", callback_data="agent_quick_stoplist"),
            InlineKeyboardButton(text="🧾 Бланки сейчас", callback_data="agent_quick_blanks_current"),
        ],
        [
            InlineKeyboardButton(text="🕒 Бланки 12 часов", callback_data="agent_quick_blanks_12h"),
            InlineKeyboardButton(text="📡 Мониторы", callback_data="agent_show_monitors"),
        ],
        [
            InlineKeyboardButton(text=POINTS_BUTTON_TEXT, callback_data="agent_show_points"),
        ],
        [
            InlineKeyboardButton(text="💬 Чат для отчётов", callback_data="agent_choose_report_chat"),
            InlineKeyboardButton(text="🔌 Системы", callback_data="agent_show_systems"),
        ],
        [InlineKeyboardButton(text="➕ Подключить систему", callback_data="agent_connect_system")],
    ]
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

QUICK_REPORT_PROMPT_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Вернуться в меню", callback_data="agent_quick_cancel")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="agent_quick_cancel")],
    ]
)

_REPORT_FAILURE_MESSAGES = {
    "stoplist_report": "Не удалось получить отчет по стоп-листу. Попробуйте позже.",
    "blanks_report": "Не удалось получить отчет по бланкам. Попробуйте позже.",
    "reviews_report": "Не удалось получить отчет по отзывам. Попробуйте позже.",
}


class ConnectSystemState(StatesGroup):
    waiting_for_url = State()
    waiting_for_login = State()
    waiting_for_password = State()


class QuickReportState(StatesGroup):
    waiting_for_point = State()


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


def _build_report_chat_keyboard(chats: list[Chat], selected_chat_id: int | None) -> InlineKeyboardMarkup:
    buttons = []
    for item in chats[:10]:
        label = item.title or item.username or f"chat {item.chat_id}"
        prefix = "✅ " if selected_chat_id == item.chat_id else ""
        buttons.append(
            [
                InlineKeyboardButton(
                    text=f"{prefix}{label[:40]}",
                    callback_data=f"{REPORT_CHAT_CALLBACK_PREFIX}{item.chat_id}",
                )
            ]
        )

    buttons.append([InlineKeyboardButton(text="Отключить доставку в чат", callback_data="agent_report_chat_clear")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


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
    answer = (result.get("answer") or "").strip()
    if status == "failed" and scenario in _REPORT_FAILURE_MESSAGES:
        if answer and not answer.startswith("DataAgent не смог обработать запрос:"):
            return answer
        return _REPORT_FAILURE_MESSAGES[scenario]
    return answer or "Не удалось получить ответ от агента."


async def _deliver_report_to_selected_chat(
    message: Message,
    user_message: str,
    answer: str,
    *,
    telegram_user_id: int | None = None,
    requester_name: str | None = None,
) -> str | None:
    db = get_db_session()
    try:
        effective_telegram_user_id = telegram_user_id or message.from_user.id
        user = db.query(User).filter(User.telegram_id == effective_telegram_user_id).first()
        if not user:
            return None

        profile = _get_or_create_profile(db, user.id)
        if not profile.default_report_chat_id:
            return None

        chat = (
            db.query(Chat)
            .filter(
                Chat.chat_id == profile.default_report_chat_id,
                Chat.is_active.is_(True),
            )
            .first()
        )
        if not chat:
            return None

        delivery_text = build_report_delivery_message(
            requester_name=requester_name or _get_requester_name(message),
            user_message=user_message,
            answer=answer,
        )
        await message.bot.send_message(
            chat_id=chat.chat_id,
            text=trim_telegram_text(delivery_text),
        )
        return chat.title or chat.username or str(chat.chat_id)
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


def _build_quick_report_prompt(action_key: str) -> str:
    action = QUICK_REPORT_ACTIONS[action_key]
    return (
        f"⚡ <b>{action['title']}</b>\n\n"
        "Пришлите только точку одним сообщением.\n"
        f"Например: <code>{action['example']}</code>"
    )


def _build_quick_report_request(action_key: str, point: str) -> str:
    action = QUICK_REPORT_ACTIONS[action_key]
    return action["request_builder"](point.strip())


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
    buttons.append([InlineKeyboardButton(text="↩️ В меню агента", callback_data="agent_open")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_point_actions_keyboard(point: SavedPoint) -> InlineKeyboardMarkup:
    point_id = point.id
    delivery_label = "📨 В чат: вкл" if point.report_delivery_enabled else "🔕 В чат: выкл"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ Отзывы", callback_data=f"{POINT_REPORT_CALLBACK_PREFIX}{point_id}:reviews_day"),
                InlineKeyboardButton(text="🚫 Стоп-лист", callback_data=f"{POINT_REPORT_CALLBACK_PREFIX}{point_id}:stoplist"),
            ],
            [
                InlineKeyboardButton(text="🧾 Бланки сейчас", callback_data=f"{POINT_REPORT_CALLBACK_PREFIX}{point_id}:blanks_current"),
                InlineKeyboardButton(text="🕒 Бланки 12 ч", callback_data=f"{POINT_REPORT_CALLBACK_PREFIX}{point_id}:blanks_12h"),
            ],
            [
                InlineKeyboardButton(text=delivery_label, callback_data=f"{POINT_DELIVERY_CALLBACK_PREFIX}{point_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"{POINT_CALLBACK_PREFIX}delete:{point_id}"),
            ],
            [InlineKeyboardButton(text="↩️ К списку точек", callback_data="agent_show_points")],
        ]
    )


def _build_all_points_actions_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⭐ Отзывы", callback_data=f"{POINT_REPORT_CALLBACK_PREFIX}all:reviews_day"),
                InlineKeyboardButton(text="🚫 Стоп-лист", callback_data=f"{POINT_REPORT_CALLBACK_PREFIX}all:stoplist"),
            ],
            [
                InlineKeyboardButton(text="🧾 Бланки сейчас", callback_data=f"{POINT_REPORT_CALLBACK_PREFIX}all:blanks_current"),
                InlineKeyboardButton(text="🕒 Бланки 12 ч", callback_data=f"{POINT_REPORT_CALLBACK_PREFIX}all:blanks_12h"),
            ],
            [InlineKeyboardButton(text="↩️ К списку точек", callback_data="agent_show_points")],
        ]
    )


def _build_points_summary_text(points: list[SavedPoint]) -> str:
    if not points:
        return (
            "📍 <b>Сохранённых точек пока нет</b>\n\n"
            "Добавьте первую точку, и дальше бот будет предлагать её в кнопках вместо ручного ввода адреса."
        )

    lines = ["📍 <b>Ваши точки</b>", ""]
    for point in points:
        delivery_mark = " • в чат" if point.report_delivery_enabled else ""
        lines.append(f"• <b>#{point.id}</b> {point.display_name}{delivery_mark}")
    if len(points) > 1:
        lines.extend(["", "Можно выбрать одну точку или сразу «Все точки»."])
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


async def _call_agent(message: Message, text: str, *, actor_user: TelegramUser | None = None) -> dict:
    effective_user = actor_user or message.from_user
    return await data_agent_client.chat(
        {
            "user_id": effective_user.id,
            "message": text,
            "username": effective_user.username,
            "first_name": effective_user.first_name,
        }
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


def _schedule_background_agent_request(message: Message, text: str) -> None:
    task = asyncio.create_task(_send_agent_request(message, text))
    _BACKGROUND_AGENT_TASKS.add(task)

    def _cleanup(done_task: asyncio.Task) -> None:
        _BACKGROUND_AGENT_TASKS.discard(done_task)
        if done_task.cancelled():
            return
        exc = done_task.exception()
        if exc:
            logger.error("Background agent task failed: %s", exc, exc_info=True)

    task.add_done_callback(_cleanup)


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


async def _prompt_quick_report_action(
    message: Message,
    state: FSMContext,
    action_key: str,
    *,
    telegram_user_id: int | None = None,
) -> None:
    effective_user_id = telegram_user_id or message.from_user.id
    has_system = await _user_has_connected_italian_pizza_system(effective_user_id)
    db = get_db_session()
    try:
        saved_points = saved_point_service.list_points(db, effective_user_id)
    finally:
        db.close()

    if action_key in {"blanks_current", "blanks_12h"} and not has_system:
        await state.clear()
        await message.answer(
            "Для бланков сначала нужно подключить систему Italian Pizza.\n\n"
            "Откройте «🔌 Системы» или нажмите «➕ Подключить систему»."
        )
        return

    if saved_points:
        await state.clear()
        lines = [
            f"⚡ <b>{QUICK_REPORT_ACTIONS[action_key]['title']}</b>",
            "",
            "Выберите сохранённую точку кнопкой ниже.",
        ]
        if len(saved_points) > 1:
            lines.append("Можно выбрать и «Все точки».")
        await message.answer(
            "\n".join(lines),
            reply_markup=_build_points_overview_keyboard(saved_points),
            parse_mode="HTML",
        )
        await state.update_data(quick_report_action=action_key)
        return

    await state.set_state(QuickReportState.waiting_for_point)
    await state.update_data(quick_report_action=action_key)
    await message.answer(
        _build_quick_report_prompt(action_key),
        reply_markup=QUICK_REPORT_PROMPT_KEYBOARD,
        parse_mode="HTML",
    )


async def _send_systems_summary(message: Message, *, telegram_user_id: int | None = None) -> None:
    effective_user_id = telegram_user_id or message.from_user.id
    try:
        systems = await data_agent_client.list_systems(effective_user_id)
    except Exception as exc:
        logger.error("Agent systems error: %s", exc, exc_info=True)
        await message.answer("Не удалось получить список подключённых систем.")
        return

    if not systems:
        await message.answer(
            "🔌 <b>Подключённых систем пока нет</b>\n\nНажмите «Подключить систему», чтобы добавить новую.",
            reply_markup=AGENT_ENTRY_KEYBOARD,
            parse_mode="HTML",
        )
        return

    lines = ["🔌 <b>Подключённые системы</b>", ""]
    for item in systems:
        lines.append(f"• <b>{item.get('system_name', 'web-system')}</b> — {item.get('url')}")
    await message.answer("\n".join(lines), reply_markup=AGENT_ENTRY_KEYBOARD, parse_mode="HTML")


async def _send_monitors_summary(message: Message, *, telegram_user_id: int | None = None) -> None:
    effective_user_id = telegram_user_id or message.from_user.id
    try:
        monitors = await data_agent_client.list_monitors(effective_user_id)
    except Exception as exc:
        logger.error("Agent monitors error: %s", exc, exc_info=True)
        await message.answer("Не удалось получить список мониторингов.")
        return

    if not monitors:
        await message.answer(
            "📡 <b>Активных мониторингов пока нет</b>\n\n"
            "Пример: <code>/monitorblanks Артемовский, Гагарина 2А каждый час</code>",
            reply_markup=AGENT_ENTRY_KEYBOARD,
            parse_mode="HTML",
        )
        return

    lines = ["📡 <b>Активные мониторинги</b>", ""]
    for item in monitors:
        lines.append(
            f"• <b>#{item.get('id')}</b> {item.get('monitor_type')} — {item.get('point_name')} "
            f"(каждые {item.get('check_interval_minutes')} мин., статус: {item.get('last_status') or 'new'})"
        )
    lines.extend(["", "Отключение: <code>/unmonitor ID</code>"])
    await message.answer("\n".join(lines), reply_markup=AGENT_ENTRY_KEYBOARD, parse_mode="HTML")


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
                reply_markup=AGENT_ENTRY_KEYBOARD,
                parse_mode="HTML",
            )
            return
        if not points:
            await message.answer(
                "📍 <b>Точки пока не добавлены</b>\n\n"
                "Система уже подключена. Теперь добавьте первую точку, и дальше будете выбирать её кнопками.",
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


async def _send_point_details(message: Message, telegram_user_id: int, point_id: int) -> None:
    db = get_db_session()
    try:
        point = saved_point_service.get_point(db, telegram_user_id, point_id)
        if not point or not point.is_active:
            await message.answer("Точка не найдена или уже удалена.")
            return
        await message.answer(
            "📍 <b>Точка</b>\n\n"
            f"<b>{point.display_name}</b>\n"
            f"Поставщик: {point.provider}\n"
            f"Отправка отчётов в чат: {'включена' if point.report_delivery_enabled else 'выключена'}",
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
            await message.answer("Сначала добавьте хотя бы одну точку.")
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
    waiting = await message.answer(
        f"⏳ Собираю отчёт «{QUICK_REPORT_ACTIONS[action_key]['title']}» по {len(points)} "
        f"{'точке' if len(points) == 1 else 'точкам'}..."
    )
    sections: list[str] = []
    delivered_to_chat: str | None = None
    requester_name = _get_requester_name_from_actor(actor_user, message)
    for point in points:
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
            current_chat = await _deliver_report_to_selected_chat(
                message,
                _build_quick_report_request(action_key, point.display_name),
                answer,
                telegram_user_id=actor_user.id if actor_user else message.from_user.id,
                requester_name=requester_name,
            )
            if current_chat and delivered_to_chat is None:
                delivered_to_chat = current_chat

    final_text = "\n\n".join(sections)
    if len(final_text) > 3900:
        final_text = final_text[:3890].rstrip() + "…"
    await waiting.edit_text(final_text, parse_mode=None)
    if delivered_to_chat:
        await message.answer(f"Отчёт также отправлен в чат: {delivered_to_chat}")


async def _dispatch_agent_request(message: Message, text: str) -> None:
    if _looks_like_long_agent_request(text):
        _schedule_background_agent_request(message, text)
        return

    await _send_agent_request(message, text)


async def _send_agent_request(message: Message, text: str) -> None:
    try:
        result = await _call_agent(message, text)
    except DataAgentClientError as exc:
        logger.error(
            "Agent chat transport error type=%s user_id=%s message=%s detail=%s",
            type(exc).__name__,
            message.from_user.id,
            text[:300],
            exc,
            exc_info=True,
        )
        await message.answer(exc.user_message)
        return
    except Exception as exc:
        logger.error(
            "Agent chat unexpected error user_id=%s message=%s detail=%s",
            message.from_user.id,
            text[:300],
            exc,
            exc_info=True,
        )
        await message.answer("Агент сейчас недоступен. Проверьте отдельный сервис и попробуйте ещё раз.")
        return

    answer = _build_user_safe_agent_answer(result)
    await message.answer(answer)


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
        await message.answer(AGENT_WELCOME, reply_markup=AGENT_ENTRY_KEYBOARD, parse_mode="HTML")
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
    await _open_agent_entry(message, state)


@router.message(F.chat.type == "private", F.text == QUICK_REPORTS_BUTTON_TEXT)
async def open_quick_reports_from_button(message: Message, state: FSMContext) -> None:
    await _open_agent_entry(message, state)


@router.message(F.chat.type == "private", F.text == MONITORS_BUTTON_TEXT)
async def open_monitors_from_button(message: Message) -> None:
    await _send_monitors_summary(message)


@router.message(F.chat.type == "private", F.text == POINTS_BUTTON_TEXT)
async def open_points_from_button(message: Message) -> None:
    await _send_points_summary(message)


@router.callback_query(F.data == "agent_open")
async def callback_agent_open(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await _open_agent_entry(callback.message, state, actor_user=callback.from_user)


@router.callback_query(F.data == "agent_connect_system")
async def callback_agent_connect_system(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ConnectSystemState.waiting_for_url)
    if callback.message:
        await callback.message.answer(
            "🔗 <b>Подключение системы</b>\n\n"
            "Пришлите URL системы одним сообщением.\n"
            "Например: <code>https://portal.example.com</code>",
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
                "Сначала подключите систему Italian Pizza. После этого можно будет добавлять точки."
            )
        return
    await state.set_state(PointManagementState.waiting_for_new_point)
    if callback.message:
        await callback.message.answer(
            "📍 <b>Новая точка</b>\n\n"
            "Точка будет привязана к подключённой системе Italian Pizza.\n\n"
            "Пришлите город и адрес одним сообщением.\n"
            "Например: <code>Сухой Лог, Белинского 40</code>",
            parse_mode="HTML",
        )


@router.callback_query(F.data.startswith(POINT_CALLBACK_PREFIX))
async def callback_agent_point(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.message:
        return

    payload = callback.data[len(POINT_CALLBACK_PREFIX):]
    if payload == "all":
        data = await state.get_data()
        action_key = data.get("quick_report_action")
        if action_key in QUICK_REPORT_ACTIONS:
            db = get_db_session()
            try:
                points = saved_point_service.list_points(db, callback.from_user.id)
            finally:
                db.close()
            await state.clear()
            if not points:
                await callback.message.answer("Сначала добавьте хотя бы одну точку.")
                return
            await _send_saved_points_report(callback.message, action_key, points, actor_user=callback.from_user)
            return

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
        await callback.message.answer(f"🗑 Точка отключена: {point.display_name}")
        await _send_points_summary(callback.message, telegram_user_id=callback.from_user.id)
        return

    if not payload.isdigit():
        await callback.message.answer("Не удалось определить точку.")
        return

    point_id = int(payload)
    data = await state.get_data()
    action_key = data.get("quick_report_action")
    if action_key in QUICK_REPORT_ACTIONS:
        db = get_db_session()
        try:
            point = saved_point_service.get_point(db, callback.from_user.id, point_id)
        finally:
            db.close()
        await state.clear()
        if not point or not point.is_active:
            await callback.message.answer("Точка не найдена.")
            return
        await _send_saved_points_report(callback.message, action_key, [point], actor_user=callback.from_user)
        return

    await _send_point_details(callback.message, callback.from_user.id, point_id)


@router.callback_query(F.data.startswith(POINT_REPORT_CALLBACK_PREFIX))
async def callback_agent_point_report(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return
    payload = callback.data[len(POINT_REPORT_CALLBACK_PREFIX):]
    point_ref, action_key = payload.split(":", 1)
    if action_key not in QUICK_REPORT_ACTIONS:
        await callback.message.answer("Не удалось определить тип отчёта.")
        return

    db = get_db_session()
    try:
        points = (
            saved_point_service.list_points(db, callback.from_user.id)
            if point_ref == "all"
            else [saved_point_service.get_point(db, callback.from_user.id, int(point_ref))]
        )
        points = [item for item in points if item and item.is_active]
    finally:
        db.close()

    if not points:
        await callback.message.answer("Точки не найдены.")
        return

    await _send_saved_points_report(callback.message, action_key, points, actor_user=callback.from_user)


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
    if callback.message:
        await _prompt_quick_report_action(callback.message, state, "reviews_day", telegram_user_id=callback.from_user.id)


@router.callback_query(F.data == "agent_quick_reviews_week")
async def callback_agent_quick_reviews_week(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await _prompt_quick_report_action(callback.message, state, "reviews_week", telegram_user_id=callback.from_user.id)


@router.callback_query(F.data == "agent_quick_stoplist")
async def callback_agent_quick_stoplist(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await _prompt_quick_report_action(callback.message, state, "stoplist", telegram_user_id=callback.from_user.id)


@router.callback_query(F.data == "agent_quick_blanks_current")
async def callback_agent_quick_blanks_current(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await _prompt_quick_report_action(callback.message, state, "blanks_current", telegram_user_id=callback.from_user.id)


@router.callback_query(F.data == "agent_quick_blanks_12h")
async def callback_agent_quick_blanks_12h(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await _prompt_quick_report_action(callback.message, state, "blanks_12h", telegram_user_id=callback.from_user.id)


@router.callback_query(F.data == "agent_hint_reviews")
async def callback_agent_hint_reviews(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Для отчёта по отзывам можно написать, например:\n"
            "/reviews за неделю\n"
            "/reviews Екатеринбург, Малышева 5 за сутки"
        )


@router.callback_query(F.data == "agent_hint_stoplist")
async def callback_agent_hint_stoplist(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Для стоп-листа напишите, например:\n"
            "/stoplist Екатеринбург, Малышева 5\n"
            "или обычным текстом: пришли стоп-лист по точке Екатеринбург, Малышева 5"
        )


@router.callback_query(F.data == "agent_hint_blanks")
async def callback_agent_hint_blanks(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Для бланков напишите, например:\n"
            "/blanks Екатеринбург, Малышева 5 текущий бланк\n"
            "/blanks Екатеринбург, Малышева 5 за 12 часов"
        )


@router.callback_query(F.data == "agent_hint_monitors")
async def callback_agent_hint_monitors(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Для мониторинга можно написать, например:\n"
            "/monitorblanks Екатеринбург, Малышева 5 каждый час\n"
            "/monitorstoplist Екатеринбург, Малышева 5 каждые 3 часа\n\n"
            "/monitorreviews каждый час\n"
            "Посмотреть активные мониторинги: /monitors\n"
            "Отключить: /unmonitor 12"
        )


@router.callback_query(F.data == "agent_show_debug")
async def callback_agent_show_debug(callback: CallbackQuery) -> None:
    if not _is_developer_telegram_id(callback.from_user.id):
        await callback.answer("Команда недоступна.", show_alert=False)
        return
    await callback.answer()
    if callback.message:
        await _send_agent_debug_message(callback.message, callback.from_user.id)


@router.message(StateFilter(QuickReportState.waiting_for_point), F.text)
async def handle_quick_report_point(message: Message, state: FSMContext) -> None:
    point = (message.text or "").strip()
    if not point:
        await message.answer("Пришлите точку одним сообщением.")
        return

    data = await state.get_data()
    action_key = data.get("quick_report_action")
    if action_key not in QUICK_REPORT_ACTIONS:
        await state.clear()
        await _open_agent_entry(message, state)
        return

    await state.clear()
    await _dispatch_agent_request(message, _build_quick_report_request(action_key, point))


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
        "Теперь её можно выбирать в кнопках отчётов и отдельно настроить отправку отчётов в чат.",
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
        await message.answer("Укажите ID точки, например: <code>/delpoint 3</code>", parse_mode="HTML")
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
    monitor_id_raw = _get_command_args(message.text)
    if not monitor_id_raw.isdigit():
        await message.answer("Укажите ID мониторинга, например: <code>/unmonitor 12</code>", parse_mode="HTML")
        return

    try:
        result = await data_agent_client.delete_monitor(message.from_user.id, int(monitor_id_raw))
    except Exception as exc:
        logger.error("Agent delete monitor error: %s", exc, exc_info=True)
        await message.answer("Не удалось отключить мониторинг.")
        return

    if result.get("success"):
        await message.answer(f"✅ Мониторинг <b>#{monitor_id_raw}</b> отключён.", parse_mode="HTML")
    else:
        await message.answer(
            f"Не удалось отключить мониторинг <b>#{monitor_id_raw}</b>: "
            f"{result.get('error', 'неизвестная ошибка')}",
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
                "Напишите что-нибудь в нужном чате с TaskBridge и повторите команду."
            )
            return

        await message.answer(
            "💬 <b>Чат для отчётов</b>\n\nВыберите, куда дублировать отчёты по отзывам, стоп-листам и бланкам.",
            reply_markup=_build_report_chat_keyboard(chats, profile.default_report_chat_id),
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
                "Напишите сообщение в нужном чате с TaskBridge и попробуйте снова."
            )
            return

        await callback.message.answer(
            "💬 <b>Чат для отчётов</b>\n\nВыберите, куда дублировать отчёты по отзывам, стоп-листам и бланкам.",
            reply_markup=_build_report_chat_keyboard(chats, profile.default_report_chat_id),
            parse_mode="HTML",
        )
    finally:
        db.close()


@router.callback_query(F.data.startswith(REPORT_CHAT_CALLBACK_PREFIX))
async def callback_agent_report_chat_select(callback: CallbackQuery) -> None:
    await callback.answer("Чат для отчётов обновлён")
    if not callback.message:
        return

    selected_chat_id = int(callback.data.split(":")[-1])
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
            await callback.message.answer("Этот чат недоступен для выбора. Попробуйте обновить список.")
            return

        profile.default_report_chat_id = selected_chat.chat_id
        profile.default_report_chat_title = selected_chat.title or selected_chat.username or str(selected_chat.chat_id)
        db.commit()

        await callback.message.answer(
            f"✅ Готово. Новые отчёты буду дублировать в чат:\n<b>{profile.default_report_chat_title}</b>",
            parse_mode="HTML",
        )
    finally:
        db.close()


@router.callback_query(F.data == "agent_report_chat_clear")
async def callback_agent_report_chat_clear(callback: CallbackQuery) -> None:
    await callback.answer("Доставка в чат отключена")
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
        profile.default_report_chat_id = None
        profile.default_report_chat_title = None
        db.commit()
        await callback.message.answer("✅ Дублирование отчётов в групповой чат отключено.")
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
            await waiting.edit_text(
                f"Не удалось подключить систему: {result.get('error', 'неизвестная ошибка')}"
            )
    except Exception as exc:
        logger.error("Agent connect error: %s", exc, exc_info=True)
        await waiting.edit_text(
            "Не удалось подключиться к сервису агента. Проверьте DATA_AGENT_URL и INTERNAL_API_URL."
        )


@router.message(
    StateFilter(None),
    F.chat.type == "private",
    F.text,
    ~F.text.startswith("/"),
    F.text != AGENT_BUTTON_TEXT,
    F.text != HELP_BUTTON_TEXT,
)
async def handle_private_agent_message(message: Message, state: FSMContext) -> None:
    await _dispatch_agent_request(message, (message.text or "").strip())
