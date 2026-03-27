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
    "Агент готов к работе.\n\n"
    "Что он уже умеет:\n"
    "• собирать отчёт по отзывам\n"
    "• анализировать почту и календарь\n"
    "• работать с подключёнными веб-системами через Browser Agent\n\n"
    "С чего начать:\n"
    "1. Подключить внешнюю систему\n"
    "2. Описать, какие отчёты и задачи для вас приоритетны\n"
    "3. Написать обычным сообщением, что нужно сделать\n\n"
    "Примеры запросов:\n"
    "• Build restaurant reviews report for current week\n"
    "• show my meetings for this week\n"
    "• collect revenue report from the connected system"
)


class ConnectSystemState(StatesGroup):
    waiting_for_url = State()
    waiting_for_login = State()
    waiting_for_password = State()


class AgentOnboardingState(StatesGroup):
    waiting_for_business_context = State()
    waiting_for_primary_goal = State()
    waiting_for_reporting_frequency = State()


def _get_or_create_user(db, telegram_id: int, username: str | None, first_name: str | None, last_name: str | None, is_bot: bool) -> User:
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
                "Давайте быстро настроим агента под ваш кейс.\n\n"
                "Шаг 1 из 3. Чем вы занимаетесь?\n"
                "Например: сеть пиццерий, ресторан, e-commerce, агентство."
            )
            return

        summary = AGENT_WELCOME
        if profile.business_context or profile.primary_goal or profile.reporting_frequency:
            details = ["\nТекущий профиль:"]
            if profile.business_context:
                details.append(f"• Контекст: {profile.business_context}")
            if profile.primary_goal:
                details.append(f"• Главный запрос: {profile.primary_goal}")
            if profile.reporting_frequency:
                details.append(f"• Периодичность: {profile.reporting_frequency}")
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

    try:
        result = await data_agent_client.chat({
            "user_id": message.from_user.id,
            "message": args[1],
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
        })
        await message.answer(result.get("answer", "Агент не вернул ответ."))
    except Exception as exc:
        logger.error("DataAgent chat error: %s", exc, exc_info=True)
        await message.answer("Агент сейчас недоступен. Проверьте отдельный сервис и попробуйте ещё раз.")


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
        "Шаг 2 из 3. Что для вас сейчас главное?\n"
        "Например: отчёт по отзывам, стоп-листы, мониторинг бланков, выручка по точкам."
    )


@router.message(StateFilter(AgentOnboardingState.waiting_for_primary_goal), F.text)
async def onboarding_primary_goal(message: Message, state: FSMContext) -> None:
    await state.update_data(primary_goal=(message.text or "").strip())
    await state.set_state(AgentOnboardingState.waiting_for_reporting_frequency)
    await message.answer(
        "Шаг 3 из 3. Как часто вам нужны отчёты?\n"
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
            "Профиль агента сохранён.\n\n"
            f"Контекст: {profile.business_context}\n"
            f"Главный запрос: {profile.primary_goal}\n"
            f"Периодичность: {profile.reporting_frequency}\n\n"
            "Теперь можно писать агенту обычным сообщением через /agent."
        )
    finally:
        db.close()


@router.message(Command("systems"))
async def cmd_systems(message: Message) -> None:
    try:
        systems = await data_agent_client.list_systems(message.from_user.id)
    except Exception as exc:
        logger.error("DataAgent systems error: %s", exc, exc_info=True)
        await message.answer("Не удалось получить список подключённых систем агента.")
        return

    if not systems:
        await message.answer("У агента пока нет подключённых систем. Используйте кнопку агента и затем /connect при необходимости.")
        return

    lines = ["Подключённые системы агента:"]
    for item in systems:
        lines.append(f"• {item.get('system_name', 'web-system')} — {item.get('url')}")
    await message.answer("\n".join(lines))


@router.message(Command("connect"))
async def cmd_connect(message: Message, state: FSMContext) -> None:
    await state.set_state(ConnectSystemState.waiting_for_url)
    await message.answer("Введите URL системы, которую нужно подключить для агента.")


@router.message(StateFilter(ConnectSystemState.waiting_for_url))
async def connect_waiting_for_url(message: Message, state: FSMContext) -> None:
    await state.update_data(url=(message.text or "").strip())
    await state.set_state(ConnectSystemState.waiting_for_login)
    await message.answer("Введите логин для этой системы.")


@router.message(StateFilter(ConnectSystemState.waiting_for_login))
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

    waiting = await message.answer("Проверяю подключение системы в агенте...")
    try:
        result = await data_agent_client.connect_system({
            "user_id": message.from_user.id,
            "url": data.get("url", ""),
            "username": data.get("username", ""),
            "password": password,
        })
        if result.get("success"):
            system = result.get("system") or {}
            await waiting.edit_text(
                "Система подключена к агенту.\n"
                f"Тип: {system.get('system_name', 'web-system')}\n"
                f"URL: {system.get('url', '')}\n\n"
                "Следующий этап — реальная проверка логина и работа Browser Tool."
            )
        else:
            await waiting.edit_text(
                "Агент не смог подключить систему.\n"
                f"Причина: {result.get('error', 'неизвестная ошибка')}"
            )
    except Exception as exc:
        logger.error("DataAgent connect error: %s", exc, exc_info=True)
        await waiting.edit_text("Сервис агента сейчас недоступен или вернул ошибку подключения.")
