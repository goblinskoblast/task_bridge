"""
Support Chat Handlers - AI-powered support system for TaskBridge
Allows users to ask questions, report bugs, and provide feedback
"""

import logging
import base64
import io
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from datetime import datetime
from openai import AsyncOpenAI

from db.database import AsyncSessionLocal
from db.models import User, SupportSession, SupportMessage, SupportAttachment
from bot.support_ai import get_support_response, format_conversation_history
import config

logger = logging.getLogger(__name__)
router = Router()


class SupportStates(StatesGroup):
    """Состояния FSM для чата поддержки"""
    waiting_for_message = State()


def get_support_keyboard():
    """Клавиатура для управления чатом поддержки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="❌ Завершить чат", callback_data="support_close")
        ]
    ])


def get_main_menu_keyboard():
    """Клавиатура главного меню с кнопкой поддержки"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💬 Чат поддержки", callback_data="support_start")
        ]
    ])


async def get_or_create_user(telegram_user) -> User:
    """Получает или создает пользователя"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_user.id)
        )
        user = result.scalar_one_or_none()

        if not user:
            user = User(
                telegram_id=telegram_user.id,
                username=telegram_user.username,
                first_name=telegram_user.first_name,
                last_name=telegram_user.last_name,
                is_bot=telegram_user.is_bot
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)

        return user


async def get_active_session(user_id: int) -> SupportSession | None:
    """Получает активную сессию поддержки пользователя"""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SupportSession)
            .options(selectinload(SupportSession.messages).selectinload(SupportMessage.attachments))
            .where(
                SupportSession.user_id == user_id,
                SupportSession.status == 'active'
            )
            .order_by(SupportSession.started_at.desc())
        )
        return result.scalar_one_or_none()


async def create_support_session(user_id: int) -> SupportSession:
    """Создает новую сессию поддержки"""
    async with AsyncSessionLocal() as session:
        support_session = SupportSession(
            user_id=user_id,
            status='active',
            started_at=datetime.utcnow(),
            last_message_at=datetime.utcnow()
        )
        session.add(support_session)
        await session.commit()
        await session.refresh(support_session)
        return support_session


async def save_user_message(
    session_id: int,
    message_text: str,
    telegram_message_id: int,
    attachments_data: list = None
) -> SupportMessage:
    """Сохраняет сообщение пользователя в БД"""
    async with AsyncSessionLocal() as session:
        # Сохраняем сообщение
        support_message = SupportMessage(
            session_id=session_id,
            from_user=True,
            message_text=message_text,
            telegram_message_id=telegram_message_id,
            created_at=datetime.utcnow()
        )
        session.add(support_message)
        await session.flush()

        # Сохраняем вложения если есть
        if attachments_data:
            for attachment in attachments_data:
                support_attachment = SupportAttachment(
                    message_id=support_message.id,
                    telegram_file_id=attachment['file_id'],
                    file_type=attachment['file_type'],
                    file_name=attachment.get('file_name'),
                    file_size=attachment.get('file_size'),
                    mime_type=attachment.get('mime_type')
                )
                session.add(support_attachment)

        # Обновляем время последнего сообщения в сессии
        await session.execute(
            update(SupportSession)
            .where(SupportSession.id == session_id)
            .values(last_message_at=datetime.utcnow())
        )

        await session.commit()
        await session.refresh(support_message)
        return support_message


async def save_ai_message(
    session_id: int,
    message_text: str,
    telegram_message_id: int,
    ai_model: str,
    ai_tokens: int,
    category: str = None
) -> SupportMessage:
    """Сохраняет ответ AI в БД"""
    async with AsyncSessionLocal() as session:
        support_message = SupportMessage(
            session_id=session_id,
            from_user=False,
            message_text=message_text,
            telegram_message_id=telegram_message_id,
            ai_model=ai_model,
            ai_tokens=ai_tokens,
            created_at=datetime.utcnow()
        )
        session.add(support_message)

        # Обновляем категорию сессии если определена
        if category:
            await session.execute(
                update(SupportSession)
                .where(SupportSession.id == session_id)
                .values(category=category, last_message_at=datetime.utcnow())
            )
        else:
            await session.execute(
                update(SupportSession)
                .where(SupportSession.id == session_id)
                .values(last_message_at=datetime.utcnow())
            )

        await session.commit()
        await session.refresh(support_message)
        return support_message


async def close_support_session(session_id: int, summary: str = None, resolution: str = None):
    """Закрывает сессию поддержки"""
    async with AsyncSessionLocal() as session:
        await session.execute(
            update(SupportSession)
            .where(SupportSession.id == session_id)
            .values(
                status='closed',
                closed_at=datetime.utcnow(),
                summary=summary,
                resolution=resolution
            )
        )
        await session.commit()


async def analyze_image_with_vision(message: Message, user: User) -> str:
    """
    Анализирует изображение с помощью GPT-4 Vision API
    Возвращает распознанный текст и описание содержимого
    """
    try:
        # Инициализируем OpenAI клиент
        client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)

        # Получаем фото (берем самое большое)
        photo = message.photo[-1]

        # Скачиваем файл
        file = await message.bot.get_file(photo.file_id)
        file_bytes = await message.bot.download_file(file.file_path)

        # Конвертируем в base64
        image_base64 = base64.b64encode(file_bytes.read()).decode('utf-8')

        logger.info(f"Analyzing image from user {user.telegram_id} with GPT-4 Vision")

        # Отправляем в GPT-4 Vision
        response = await client.chat.completions.create(
            model="gpt-4o-mini",  # Поддерживает vision и дешевле
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """Проанализируй это изображение и опиши:
1. Если на скриншоте есть ТЕКСТ - распознай его полностью
2. Опиши что изображено (интерфейс приложения, ошибка, баг, и т.д.)
3. Укажи технические детали если видны (версии, коды ошибок)

Ответь КРАТКО и СТРУКТУРИРОВАННО."""
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}"
                            }
                        }
                    ]
                }
            ],
            max_tokens=500,
            temperature=0.3
        )

        analysis = response.choices[0].message.content
        tokens_used = response.usage.total_tokens

        logger.info(f"Vision API analysis completed. Tokens used: {tokens_used}")

        return analysis

    except Exception as e:
        logger.error(f"Failed to analyze image with Vision API: {e}", exc_info=True)
        return None


async def forward_to_developer(message: Message, user: User, message_type: str, vision_analysis: str = None):
    """Пересылает медиафайл разработчику с анализом Vision API"""
    if not config.DEVELOPER_TELEGRAM_ID:
        logger.warning("DEVELOPER_TELEGRAM_ID not set - cannot forward screenshot")
        return False

    try:
        # Формируем текст сообщения для разработчика
        user_info = f"👤 От пользователя: {user.first_name or user.username} (ID: {user.telegram_id})"
        message_text = message.text or message.caption or ""

        forward_text = f"{user_info}\n📎 Тип: {message_type}"

        if message_text:
            forward_text += f"\n\n💬 Сообщение пользователя:\n{message_text}"

        # Добавляем анализ Vision API если есть
        if vision_analysis:
            forward_text += f"\n\n🤖 Анализ GPT-4 Vision:\n{vision_analysis}"

        # Отправляем текстовое сообщение с информацией
        await message.bot.send_message(
            chat_id=config.DEVELOPER_TELEGRAM_ID,
            text=forward_text
        )

        # Пересылаем сам медиафайл
        await message.forward(config.DEVELOPER_TELEGRAM_ID)

        logger.info(f"Forwarded {message_type} from user {user.telegram_id} to developer")
        return True

    except Exception as e:
        logger.error(f"Failed to forward to developer: {e}", exc_info=True)
        return False


@router.message(Command("support"))
async def cmd_support(message: Message, state: FSMContext):
    """Команда /support - начать чат с поддержкой"""
    user = await get_or_create_user(message.from_user)

    # Проверяем есть ли уже активная сессия
    active_session = await get_active_session(user.id)

    if active_session:
        await message.answer(
            "💬 Чат поддержки уже активен!\n\n"
            "Просто напишите ваш вопрос, и я постараюсь помочь.\n"
            "Вы можете отправлять текст, фото, документы и скриншоты.",
            reply_markup=get_support_keyboard()
        )
    else:
        # Создаем новую сессию
        session_obj = await create_support_session(user.id)

        await state.update_data(support_session_id=session_obj.id)
        await state.set_state(SupportStates.waiting_for_message)

        await message.answer(
            "👋 Привет! Я AI-консультант поддержки TaskBridge.\n\n"
            "Я помогу вам:\n"
            "• Ответить на вопросы о функциях бота\n"
            "• Принять сообщение об ошибке\n"
            "• Записать ваши идеи и предложения\n"
            "• Собрать отзыв о работе бота\n\n"
            "Просто напишите ваш вопрос или опишите проблему. "
            "Вы также можете отправить скриншоты или документы.\n\n"
            "Чат поддержки активирован ✅",
            reply_markup=get_support_keyboard()
        )

    logger.info(f"Support chat started for user {user.telegram_id}")


@router.callback_query(F.data == "support_start")
async def callback_support_start(callback: CallbackQuery, state: FSMContext):
    """Callback для кнопки начала чата поддержки"""
    await callback.answer()

    user = await get_or_create_user(callback.from_user)

    # Проверяем есть ли уже активная сессия
    active_session = await get_active_session(user.id)

    if active_session:
        await callback.message.edit_text(
            "💬 Чат поддержки уже активен!\n\n"
            "Просто напишите ваш вопрос, и я постараюсь помочь.\n"
            "Вы можете отправлять текст, фото, документы и скриншоты.",
            reply_markup=get_support_keyboard()
        )
    else:
        # Создаем новую сессию
        session_obj = await create_support_session(user.id)

        await state.update_data(support_session_id=session_obj.id)
        await state.set_state(SupportStates.waiting_for_message)

        await callback.message.edit_text(
            "👋 Привет! Я AI-консультант поддержки TaskBridge.\n\n"
            "Я помогу вам:\n"
            "• Ответить на вопросы о функциях бота\n"
            "• Принять сообщение об ошибке\n"
            "• Записать ваши идеи и предложения\n"
            "• Собрать отзыв о работе бота\n\n"
            "Просто напишите ваш вопрос или опишите проблему. "
            "Вы также можете отправить скриншоты или документы.\n\n"
            "Чат поддержки активирован ✅",
            reply_markup=get_support_keyboard()
        )

    logger.info(f"Support chat started for user {user.telegram_id}")


@router.callback_query(F.data == "support_close")
async def callback_support_close(callback: CallbackQuery, state: FSMContext):
    """Callback для закрытия чата поддержки"""
    await callback.answer()

    user = await get_or_create_user(callback.from_user)
    active_session = await get_active_session(user.id)

    if active_session:
        await close_support_session(
            active_session.id,
            summary="Сессия закрыта пользователем",
            resolution="Пользователь завершил чат"
        )

        await state.clear()

        await callback.message.edit_text(
            "✅ Чат поддержки завершен.\n\n"
            "Спасибо за обращение! Если у вас возникнут еще вопросы, "
            "вы всегда можете снова написать /support или нажать кнопку ниже.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Открыть снова", callback_data="support_start")]
            ])
        )

        logger.info(f"Support chat closed by user {user.telegram_id}")
    else:
        await callback.message.edit_text(
            "У вас нет активного чата поддержки.\n\n"
            "Нажмите кнопку ниже чтобы начать новый чат.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💬 Начать чат", callback_data="support_start")]
            ])
        )


@router.message(StateFilter(SupportStates.waiting_for_message))
async def handle_support_message(message: Message, state: FSMContext):
    """Обработчик сообщений в чате поддержки"""
    user = await get_or_create_user(message.from_user)
    data = await state.get_data()
    session_id = data.get('support_session_id')

    if not session_id:
        # Если нет session_id в state, попробуем найти активную сессию
        active_session = await get_active_session(user.id)
        if active_session:
            session_id = active_session.id
            await state.update_data(support_session_id=session_id)
        else:
            # Если нет активной сессии, создаем новую
            session_obj = await create_support_session(user.id)
            session_id = session_obj.id
            await state.update_data(support_session_id=session_id)

    # Собираем информацию о вложениях
    attachments_data = []
    attachments_description = None
    forwarded_to_dev = False

    if message.photo:
        # Берем самое большое фото
        photo = message.photo[-1]
        attachments_data.append({
            'file_id': photo.file_id,
            'file_type': 'photo',
            'file_size': photo.file_size
        })
        attachments_description = "Фото"

        # Анализируем изображение с помощью GPT-4 Vision
        logger.info("Analyzing screenshot with GPT-4 Vision...")
        vision_analysis = await analyze_image_with_vision(message, user)

        if vision_analysis:
            logger.info(f"Vision analysis result: {vision_analysis[:100]}...")
            # Обновляем описание для AI с результатами Vision
            attachments_description = f"Фото (Распознано: {vision_analysis})"

        # Пересылаем скриншот разработчику с анализом Vision
        forwarded_to_dev = await forward_to_developer(
            message,
            user,
            "Скриншот/Фото",
            vision_analysis=vision_analysis
        )

        # Уведомляем пользователя о пересылке
        if forwarded_to_dev:
            notification_text = "📸 Скриншот получен и отправлен разработчику!"
            if vision_analysis:
                notification_text += "\n🤖 Изображение автоматически проанализировано."
            notification_text += "\n\nСейчас я также попробую ответить на ваш вопрос..."

            await message.answer(
                notification_text,
                reply_markup=get_support_keyboard()
            )

    elif message.document:
        attachments_data.append({
            'file_id': message.document.file_id,
            'file_type': 'document',
            'file_name': message.document.file_name,
            'file_size': message.document.file_size,
            'mime_type': message.document.mime_type
        })
        attachments_description = f"Документ: {message.document.file_name}"

    elif message.video:
        attachments_data.append({
            'file_id': message.video.file_id,
            'file_type': 'video',
            'file_size': message.video.file_size,
            'mime_type': message.video.mime_type
        })
        attachments_description = "Видео"

    elif message.audio:
        attachments_data.append({
            'file_id': message.audio.file_id,
            'file_type': 'audio',
            'file_name': message.audio.file_name,
            'file_size': message.audio.file_size,
            'mime_type': message.audio.mime_type
        })
        attachments_description = "Аудио"

    elif message.voice:
        attachments_data.append({
            'file_id': message.voice.file_id,
            'file_type': 'voice',
            'file_size': message.voice.file_size,
            'mime_type': message.voice.mime_type
        })
        attachments_description = "Голосовое сообщение"

    # Получаем текст сообщения
    user_message_text = message.text or message.caption or ""

    if not user_message_text and not attachments_data:
        await message.answer(
            "Пожалуйста, отправьте текстовое сообщение или файл с описанием.",
            reply_markup=get_support_keyboard()
        )
        return

    # Сохраняем сообщение пользователя в БД
    await save_user_message(
        session_id=session_id,
        message_text=user_message_text,
        telegram_message_id=message.message_id,
        attachments_data=attachments_data if attachments_data else None
    )

    # Получаем историю разговора для контекста
    active_session = await get_active_session(user.id)
    conversation_history = format_conversation_history(active_session.messages) if active_session else None

    # Отправляем индикатор набора текста
    await message.bot.send_chat_action(message.chat.id, "typing")

    try:
        # Получаем ответ от AI
        ai_response = await get_support_response(
            user_message=user_message_text,
            conversation_history=conversation_history,
            attachments_description=attachments_description
        )

        # Отправляем ответ пользователю
        sent_message = await message.answer(
            ai_response['response'],
            reply_markup=get_support_keyboard()
        )

        # Сохраняем ответ AI в БД
        await save_ai_message(
            session_id=session_id,
            message_text=ai_response['response'],
            telegram_message_id=sent_message.message_id,
            ai_model=ai_response.get('model_used', 'unknown'),
            ai_tokens=ai_response.get('tokens_used', 0),
            category=ai_response.get('category')
        )

        # Если требуется внимание разработчиков, логируем это
        if ai_response.get('requires_dev_attention'):
            logger.warning(
                f"Support message requires dev attention: "
                f"user={user.telegram_id}, category={ai_response.get('category')}, "
                f"summary={ai_response.get('summary')}"
            )

    except Exception as e:
        logger.error(f"Error processing support message: {e}", exc_info=True)
        await message.answer(
            "Извините, произошла ошибка при обработке вашего сообщения. "
            "Пожалуйста, попробуйте еще раз или свяжитесь с нами напрямую.",
            reply_markup=get_support_keyboard()
        )
