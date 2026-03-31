import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from bot.data_agent_client import data_agent_client
from db.database import get_db_session
from db.models import DataAgentProfile, User

logger = logging.getLogger(__name__)

router = Router()

AGENT_BUTTON_TEXT = "🤖 Агент"
AGENT_WELCOME = (
    "Я на связи. Могу помочь с отчетами, почтой, календарем и внешними системами.\n\n"
    "Что можно попросить уже сейчас:\n"
    "• собрать отчет по отзывам\n"
    "• посмотреть письма и календарь\n"
    "• пройти в подключенную веб-систему и собрать данные\n\n"
    "Напишите обычным сообщением, что нужно сделать."
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
        await message.answer(result.get("answer", "Не удалось получить ответ от агента."))
    except Exception as exc:
        logger.error("Agent chat error: %s", exc, exc_info=True)
        await message.answer("Агент сейчас недоступен. Проверьте отдельный сервис и попробуйте еще раз.")


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
                "Например: сеть пиццерий, ресторан, e-commerce, агентство."
            )
            return

        summary = AGENT_WELCOME
        if profile.business_context or profile.primary_goal or profile.reporting_frequency:
            details = ["\nТекущий профиль:"]
            if profile.business_context:
                details.append(f"• Контекст: {profile.business_context}")
            if profile.primary_goal:
                details.append(f"• Основные задачи: {profile.primary_goal}")
            if profile.reporting_frequency:
                details.append(f"• Периодичность отчетов: {profile.reporting_frequency}")
            summary += "\n" + "\n".join(details)

        await message.answer(summary)
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
        "Шаг 3 из 3. Как часто вам нужны отчеты и сводки?\n"
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
            "Профиль сохранен. Теперь можно писать обычным сообщением, что нужно сделать.\n\n"
            f"Контекст: {profile.business_context}\n"
            f"Основные задачи: {profile.primary_goal}\n"
            f"Периодичность: {profile.reporting_frequency}"
        )
    finally:
        db.close()


@router.message(Command("systems"))
async def cmd_systems(message: Message) -> None:
    try:
        systems = await data_agent_client.list_systems(message.from_user.id)
    except Exception as exc:
        logger.error("Agent systems error: %s", exc, exc_info=True)
        await message.answer("Не удалось получить список подключенных систем.")
        return

    if not systems:
        await message.answer("Подключенных систем пока нет.")
        return

    lines = ["Подключенные системы:"]
    for item in systems:
        lines.append(f"• {item.get('system_name', 'web-system')} — {item.get('url')}")
    await message.answer("\n".join(lines))


@router.message(Command("connect"))
async def cmd_connect(message: Message, state: FSMContext) -> None:
    await state.set_state(ConnectSystemState.waiting_for_url)
    await message.answer("Введите URL системы, которую нужно подключить.")


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
