import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.data_agent_client import data_agent_client
from bot.report_delivery import (
    build_report_delivery_message,
    is_report_delivery_candidate,
    trim_telegram_text,
)
from db.database import get_db_session
from db.models import Chat, DataAgentProfile, Message as MessageModel, User

logger = logging.getLogger(__name__)

router = Router()

AGENT_BUTTON_TEXT = "🤖 Агент"
REPORT_CHAT_CALLBACK_PREFIX = "agent_report_chat_select:"
AGENT_WELCOME = (
    "Я на связи. Могу помочь с отзывами, почтой, календарём и внешними системами.\n\n"
    "Что можно попросить уже сейчас:\n"
    "• собрать отчёт по отзывам\n"
    "• посмотреть письма и календарь\n"
    "• зайти в подключённую веб-систему и собрать данные\n\n"
    "Напишите обычным сообщением, что нужно сделать."
)

AGENT_ENTRY_KEYBOARD = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(text="Подключить свою систему", callback_data="agent_connect_system")],
        [InlineKeyboardButton(text="Выбрать чат для отчётов", callback_data="agent_choose_report_chat")],
    ]
)


class ConnectSystemState(StatesGroup):
    waiting_for_url = State()
    waiting_for_login = State()
    waiting_for_password = State()


class AgentOnboardingState(StatesGroup):
    waiting_for_business_context = State()
    waiting_for_primary_goal = State()
    waiting_for_reporting_frequency = State()


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
        profile = DataAgentProfile(user_id=user_id, onboarding_completed=False)
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


async def _deliver_report_to_selected_chat(message: Message, user_message: str, answer: str) -> str | None:
    db = get_db_session()
    try:
        user = db.query(User).filter(User.telegram_id == message.from_user.id).first()
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
            requester_name=_get_requester_name(message),
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


async def _send_agent_request(message: Message, text: str) -> None:
    try:
        result = await data_agent_client.chat(
            {
                "user_id": message.from_user.id,
                "message": text,
                "username": message.from_user.username,
                "first_name": message.from_user.first_name,
            }
        )
        answer = result.get("answer", "Не удалось получить ответ от агента.")
        await message.answer(answer)

        if is_report_delivery_candidate(result):
            delivered_to = await _deliver_report_to_selected_chat(message, text, answer)
            if delivered_to:
                await message.answer(f"Этот отчёт также отправил в чат: {delivered_to}")
    except Exception as exc:
        logger.error("Agent chat error: %s", exc, exc_info=True)
        await message.answer("Агент сейчас недоступен. Проверьте отдельный сервис и попробуйте ещё раз.")


async def _open_agent_entry(message: Message, state: FSMContext) -> None:
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

        if not profile.onboarding_completed:
            await state.set_state(AgentOnboardingState.waiting_for_business_context)
            await message.answer(
                "Давайте быстро настроим ассистента под ваш кейс.\n\n"
                "Шаг 1 из 3. Чем вы занимаетесь и какой у вас бизнес-контекст?\n"
                "Например: сеть пиццерий, ресторан, e-commerce, агентство.",
                reply_markup=AGENT_ENTRY_KEYBOARD,
            )
            return

        summary = AGENT_WELCOME
        if (
            profile.business_context
            or profile.primary_goal
            or profile.reporting_frequency
            or profile.default_report_chat_title
        ):
            details = ["\nТекущий профиль:"]
            if profile.business_context:
                details.append(f"• Контекст: {profile.business_context}")
            if profile.primary_goal:
                details.append(f"• Основные задачи: {profile.primary_goal}")
            if profile.reporting_frequency:
                details.append(f"• Периодичность отчётов: {profile.reporting_frequency}")
            if profile.default_report_chat_title:
                details.append(f"• Чат для отчётов: {profile.default_report_chat_title}")
            summary += "\n" + "\n".join(details)

        await message.answer(summary, reply_markup=AGENT_ENTRY_KEYBOARD)
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
    await _send_agent_request(message, args[1].strip())


@router.message(F.text == AGENT_BUTTON_TEXT)
async def open_agent_from_button(message: Message, state: FSMContext) -> None:
    await _open_agent_entry(message, state)


@router.callback_query(F.data == "agent_open")
async def callback_agent_open(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.message:
        await _open_agent_entry(callback.message, state)


@router.callback_query(F.data == "agent_connect_system")
async def callback_agent_connect_system(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(ConnectSystemState.waiting_for_url)
    target = callback.message or callback
    if callback.message:
        await callback.message.answer("Введите URL системы, которую нужно подключить.")


@router.message(StateFilter(AgentOnboardingState.waiting_for_business_context), F.text)
async def onboarding_business_context(message: Message, state: FSMContext) -> None:
    await state.update_data(business_context=(message.text or "").strip())
    await state.set_state(AgentOnboardingState.waiting_for_primary_goal)
    await message.answer(
        "Шаг 2 из 3. Какие задачи для вас сейчас главные?\n"
        "Например: отзывы по точкам, стоп-листы, мониторинг бланков, выручка по точкам."
    )


@router.message(StateFilter(AgentOnboardingState.waiting_for_primary_goal), F.text)
async def onboarding_primary_goal(message: Message, state: FSMContext) -> None:
    await state.update_data(primary_goal=(message.text or "").strip())
    await state.set_state(AgentOnboardingState.waiting_for_reporting_frequency)
    await message.answer(
        "Шаг 3 из 3. Как часто вам нужны отчёты и сводки?\n"
        "Например: ежедневно, раз в неделю, по запросу."
    )


@router.message(StateFilter(AgentOnboardingState.waiting_for_reporting_frequency), F.text)
async def onboarding_reporting_frequency(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()

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
        profile.business_context = data.get("business_context")
        profile.primary_goal = data.get("primary_goal")
        profile.reporting_frequency = (message.text or "").strip()
        profile.onboarding_completed = True
        db.commit()

        await message.answer(
            "Профиль сохранён. Теперь можно писать обычным сообщением, что нужно сделать.\n\n"
            f"Контекст: {profile.business_context}\n"
            f"Основные задачи: {profile.primary_goal}\n"
            f"Периодичность: {profile.reporting_frequency}",
            reply_markup=AGENT_ENTRY_KEYBOARD,
        )
    finally:
        db.close()


@router.message(Command("systems"))
async def cmd_systems(message: Message) -> None:
    try:
        systems = await data_agent_client.list_systems(message.from_user.id)
    except Exception as exc:
        logger.error("Agent systems error: %s", exc, exc_info=True)
        await message.answer("Не удалось получить список подключённых систем.")
        return

    if not systems:
        await message.answer("Подключённых систем пока нет.", reply_markup=AGENT_ENTRY_KEYBOARD)
        return

    lines = ["Подключённые системы:"]
    for item in systems:
        lines.append(f"• {item.get('system_name', 'web-system')} — {item.get('url')}")
    await message.answer("\n".join(lines), reply_markup=AGENT_ENTRY_KEYBOARD)


@router.message(Command("connect"))
async def cmd_connect(message: Message, state: FSMContext) -> None:
    await state.set_state(ConnectSystemState.waiting_for_url)
    await message.answer("Введите URL системы, которую нужно подключить.")


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
                "Я пока не вижу групповых чатов, где вы уже писали и где активен TaskBridge.\n"
                "Напишите что-нибудь в нужном чате и повторите команду."
            )
            return

        await message.answer(
            "Выберите чат, куда нужно дублировать отчёты по отзывам, стоп-листам и бланкам.",
            reply_markup=_build_report_chat_keyboard(chats, profile.default_report_chat_id),
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
                "Я пока не вижу подходящих групповых чатов.\n"
                "Напишите сообщение в нужном чате с TaskBridge и попробуйте снова."
            )
            return

        await callback.message.answer(
            "Выберите чат, куда нужно дублировать отчёты по отзывам, стоп-листам и бланкам.",
            reply_markup=_build_report_chat_keyboard(chats, profile.default_report_chat_id),
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
            f"Готово. Новые отчёты по отзывам, стоп-листам и бланкам буду дублировать в чат: {profile.default_report_chat_title}"
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
        await callback.message.answer("Отключил дублирование отчётов в групповой чат.")
    finally:
        db.close()


@router.message(StateFilter(ConnectSystemState.waiting_for_url), F.text)
async def connect_waiting_for_url(message: Message, state: FSMContext) -> None:
    normalized_url = _normalize_connect_url(message.text or "")
    await state.update_data(url=normalized_url)
    await state.set_state(ConnectSystemState.waiting_for_login)
    await message.answer(f"URL сохранён: {normalized_url}\nТеперь введите логин для этой системы.")


@router.message(StateFilter(ConnectSystemState.waiting_for_login), F.text)
async def connect_waiting_for_login(message: Message, state: FSMContext) -> None:
    await state.update_data(username=(message.text or "").strip())
    await state.set_state(ConnectSystemState.waiting_for_password)
    await message.answer("Введите пароль. Сообщение будет удалено после отправки.")


@router.message(StateFilter(ConnectSystemState.waiting_for_password), F.text)
async def connect_waiting_for_password(message: Message, state: FSMContext) -> None:
    password = (message.text or "").strip()
    data = await state.get_data()
    await state.clear()

    try:
        await message.delete()
    except Exception:
        pass

    waiting = await message.answer("Проверяю подключение системы...")
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
                "Система подключена.\n"
                f"Тип: {system.get('system_name', 'web-system')}\n"
                f"URL: {system.get('url', data.get('url', ''))}"
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
)
async def handle_private_agent_message(message: Message, state: FSMContext) -> None:
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
        onboarding_completed = profile.onboarding_completed
    finally:
        db.close()

    if not onboarding_completed:
        await _open_agent_entry(message, state)
        return

    await _send_agent_request(message, (message.text or "").strip())
