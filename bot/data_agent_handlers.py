import logging

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from bot.data_agent_client import data_agent_client

logger = logging.getLogger(__name__)

router = Router()


class ConnectSystemState(StatesGroup):
    waiting_for_url = State()
    waiting_for_login = State()
    waiting_for_password = State()


@router.message(Command("dataagent"))
async def cmd_dataagent(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    if len(args) == 1:
        await message.answer(
            "DataAgent подключён как отдельный модуль.\n\n"
            "Что уже доступно на этом этапе:\n"
            "• /connect — подключить внешнюю систему\n"
            "• /systems — список подключённых систем\n"
            "• /reviews — отчёт по отзывам\n"
            "• /dataagent <запрос> — отправить запрос в DataAgent\n\n"
            "Пример:\n"
            "/dataagent show my meetings for this week"
        )
        return

    try:
        result = await data_agent_client.chat({
            "user_id": message.from_user.id,
            "message": args[1],
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
        })
        await message.answer(result.get("answer", "DataAgent не вернул ответ."))
    except Exception as exc:
        logger.error("DataAgent chat error: %s", exc, exc_info=True)
        await message.answer("DataAgent сейчас недоступен. Проверьте отдельный сервис и попробуйте ещё раз.")


@router.message(Command("reviews"))
async def cmd_reviews(message: Message) -> None:
    args = (message.text or "").split(maxsplit=1)
    period = (args[1] if len(args) > 1 else "week").strip().lower()

    if period in {"month", "месяц", "monthly"}:
        prompt = "Build restaurant reviews report for current month"
    else:
        prompt = "Build restaurant reviews report for current week"

    try:
        result = await data_agent_client.chat({
            "user_id": message.from_user.id,
            "message": prompt,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
        })
        await message.answer(result.get("answer", "Не удалось собрать отчёт по отзывам."))
    except Exception as exc:
        logger.error("DataAgent reviews error: %s", exc, exc_info=True)
        await message.answer("Отчёт по отзывам сейчас недоступен. Проверьте сервис DataAgent и источник CSV.")


@router.message(Command("systems"))
async def cmd_systems(message: Message) -> None:
    try:
        systems = await data_agent_client.list_systems(message.from_user.id)
    except Exception as exc:
        logger.error("DataAgent systems error: %s", exc, exc_info=True)
        await message.answer("Не удалось получить список подключённых систем DataAgent.")
        return

    if not systems:
        await message.answer("У DataAgent пока нет подключённых систем. Используйте /connect.")
        return

    lines = ["Подключённые системы DataAgent:"]
    for item in systems:
        lines.append(f"• {item.get('system_name', 'web-system')} — {item.get('url')}")
    await message.answer("\n".join(lines))


@router.message(Command("connect"))
async def cmd_connect(message: Message, state: FSMContext) -> None:
    await state.set_state(ConnectSystemState.waiting_for_url)
    await message.answer("Введите URL системы, которую нужно подключить для DataAgent.")


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

    waiting = await message.answer("Проверяю подключение системы в DataAgent...")
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
                "Система подключена к DataAgent.\n"
                f"Тип: {system.get('system_name', 'web-system')}\n"
                f"URL: {system.get('url', '')}\n\n"
                "Следующий этап — реальная проверка логина и работа Browser Tool."
            )
        else:
            await waiting.edit_text(
                "DataAgent не смог подключить систему.\n"
                f"Причина: {result.get('error', 'неизвестная ошибка')}"
            )
    except Exception as exc:
        logger.error("DataAgent connect error: %s", exc, exc_info=True)
        await waiting.edit_text("Сервис DataAgent сейчас недоступен или вернул ошибку подключения.")
