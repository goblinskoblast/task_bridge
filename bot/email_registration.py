# -*- coding: utf-8 -*-
"""
Email Registration Flow
Обработка регистрации email аккаунтов для IMAP интеграции
"""

import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from db.database import get_db_session
from db.models import User, EmailAccount
from bot.email_handler import get_imap_server, test_imap_connection

logger = logging.getLogger(__name__)

router = Router()


class EmailRegistrationStates(StatesGroup):
    """Состояния FSM для регистрации email"""
    waiting_for_email = State()
    waiting_for_password = State()
    confirming_settings = State()


@router.callback_query(F.data == "register_email")
async def start_email_registration(callback: CallbackQuery, state: FSMContext):
    """
    Начало регистрации email аккаунта
    """
    await callback.answer()

    try:
        # Проверяем существующие email аккаунты пользователя
        db = get_db_session()
        user = db.query(User).filter(User.telegram_id == callback.from_user.id).first()

        if not user:
            await callback.message.answer("❌ Ошибка: пользователь не найден. Попробуйте /start")
            db.close()
            return

        # Проверяем количество аккаунтов
        existing_accounts = db.query(EmailAccount).filter(EmailAccount.user_id == user.id).count()

        if existing_accounts >= 5:
            await callback.message.answer("❌ Вы уже зарегистрировали максимальное количество email аккаунтов (5)")
            db.close()
            return

        db.close()

        # Начинаем процесс регистрации
        await callback.message.answer(
            "📧 <b>Регистрация Email аккаунта</b>\n\n"
            "Для интеграции с email мне потребуются данные для подключения к вашему почтовому ящику.\n\n"
            "<b>Шаг 1/2:</b> Введите ваш email адрес\n\n"
            "Пример: <code>example@gmail.com</code>\n\n"
            "💡 <i>Поддерживаются: Gmail, Outlook, Yandex, Mail.ru и другие IMAP серверы</i>",
            parse_mode="HTML"
        )

        await state.set_state(EmailRegistrationStates.waiting_for_email)

    except Exception as e:
        logger.error(f"Error starting email registration: {e}", exc_info=True)
        await callback.message.answer("❌ Произошла ошибка. Попробуйте позже")


@router.message(EmailRegistrationStates.waiting_for_email)
async def process_email_address(message: Message, state: FSMContext):
    """
    Обработка введенного email адреса
    """
    email_address = message.text.strip().lower()

    # Валидация email
    import re
    email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'

    if not re.match(email_pattern, email_address):
        await message.answer("❌ Неверный формат email. Попробуйте ещё раз:\n\nПример: <code>example@gmail.com</code>", parse_mode="HTML")
        return

    # Проверяем не зарегистрирован ли уже этот email
    db = get_db_session()
    existing_account = db.query(EmailAccount).filter(EmailAccount.email_address == email_address).first()

    if existing_account:
        await message.answer("❌ Этот email уже зарегистрирован в TaskBridge")
        db.close()
        await state.clear()
        return

    db.close()

    # Автоопределение IMAP сервера
    imap_settings = get_imap_server(email_address)

    # Сохраняем данные в FSM
    await state.update_data(
        email_address=email_address,
        imap_server=imap_settings['server'],
        imap_port=imap_settings['port']
    )

    # Определяем провайдера для инструкций
    domain = email_address.split('@')[-1]

    instructions = ""
    if "gmail.com" in domain:
        instructions = (
            "\n\n📝 <b>Инструкция для Gmail:</b>\n"
            "1. Откройте: https://myaccount.google.com/apppasswords\n"
            "2. Выберите приложение и устройство\n"
            "3. Скопируйте сгенерированный пароль\n"
            "4. Вставьте его в следующем сообщении"
        )
    elif "yandex" in domain:
        instructions = (
            "\n\n📝 <b>Инструкция для Yandex:</b>\n"
            "1. Откройте: https://passport.yandex.ru/profile\n"
            "2. Перейдите в 'Безопасность'\n"
            "3. Включите 'Пароли приложений'\n"
            "4. Создайте новый пароль для 'Почта'\n"
            "5. Вставьте его в следующем сообщении"
        )
    elif "outlook.com" in domain or "hotmail.com" in domain:
        instructions = (
            "\n\n📝 <b>Инструкция для Outlook/Hotmail:</b>\n"
            "1. Откройте: https://account.microsoft.com/security\n"
            "2. Перейдите в 'Дополнительные параметры безопасности'\n"
            "3. Создайте 'Пароль приложения'\n"
            "4. Вставьте его в следующем сообщении"
        )
    elif "mail.ru" in domain:
        instructions = (
            "\n\n📝 <b>Инструкция для Mail.ru:</b>\n"
            "1. Откройте: https://account.mail.ru/user/2-step-auth/passwords/\n"
            "2. Создайте пароль для внешнего приложения\n"
            "3. Вставьте его в следующем сообщении"
        )
    else:
        instructions = (
            "\n\n💡 <i>Если ваш провайдер требует двухфакторную аутентификацию, "
            "используйте пароль приложения вместо обычного пароля</i>"
        )

    await message.answer(
        f"✅ Email: <code>{email_address}</code>\n"
        f"🔌 IMAP сервер: <code>{imap_settings['server']}:{imap_settings['port']}</code>\n\n"
        f"<b>Шаг 2/2:</b> Введите пароль от вашего email\n\n"
        f"⚠️ <b>Важно:</b> Для большинства провайдеров нужен <b>пароль приложения</b>, а не обычный пароль!{instructions}\n\n"
        f"🔐 Ваш пароль будет сохранён в зашифрованном виде",
        parse_mode="HTML"
    )

    await state.set_state(EmailRegistrationStates.waiting_for_password)


@router.message(EmailRegistrationStates.waiting_for_password)
async def process_password(message: Message, state: FSMContext):
    """
    Обработка пароля и тестирование подключения
    """
    password = message.text.strip()

    # Удаляем сообщение с паролем для безопасности
    try:
        await message.delete()
    except:
        pass

    if len(password) < 6:
        await message.answer("❌ Пароль слишком короткий. Попробуйте ещё раз")
        return

    # Получаем сохраненные данные
    data = await state.get_data()
    email_address = data['email_address']
    imap_server = data['imap_server']
    imap_port = data['imap_port']

    # Отправляем сообщение о тестировании
    testing_msg = await message.answer("⏳ Тестирую подключение к почтовому серверу...")

    # Тестируем подключение
    success, error_message = test_imap_connection(
        server=imap_server,
        port=imap_port,
        username=email_address,
        password=password,
        use_ssl=True
    )

    if not success:
        await testing_msg.edit_text(
            f"❌ <b>Ошибка подключения к почтовому серверу:</b>\n\n"
            f"<code>{error_message}</code>\n\n"
            f"Проверьте:\n"
            f"• Правильность email адреса\n"
            f"• Используете ли вы пароль приложения (не обычный пароль)\n"
            f"• Включен ли IMAP в настройках почты\n\n"
            f"Попробуйте ещё раз или отправьте /cancel для отмены",
            parse_mode="HTML"
        )
        return

    # Подключение успешно - сохраняем в БД
    db = get_db_session()

    try:
        user = db.query(User).filter(User.telegram_id == message.from_user.id).first()

        if not user:
            await testing_msg.edit_text("❌ Ошибка: пользователь не найден")
            await state.clear()
            db.close()
            return

        # Создаем новый EmailAccount
        email_account = EmailAccount(
            user_id=user.id,
            email_address=email_address,
            imap_server=imap_server,
            imap_port=imap_port,
            imap_username=email_address,
            imap_password=password,
            use_ssl=True,
            folder="INBOX",
            is_active=True,
            last_uid=0,
            auto_confirm=False  # По умолчанию требуем подтверждение задач
        )

        db.add(email_account)
        db.commit()
        db.refresh(email_account)

        logger.info(f"✅ Email account registered: {email_address} for user {user.telegram_id}")

        # Создаем кнопки управления
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Настроить фильтры",
                    callback_data=f"email_filters:{email_account.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Автоподтверждение: Выкл",
                    callback_data=f"email_autoconfirm:{email_account.id}:on"
                )
            ]
        ])

        await testing_msg.edit_text(
            f"✅ <b>Email успешно зарегистрирован!</b>\n\n"
            f"📧 <b>Email:</b> <code>{email_address}</code>\n"
            f"🔌 <b>IMAP:</b> <code>{imap_server}:{imap_port}</code>\n"
            f"📂 <b>Папка:</b> INBOX\n"
            f"✅ <b>Автоподтверждение:</b> Выключено\n\n"
            f"📬 Теперь я буду проверять вашу почту каждые 10 минут и создавать задачи из писем!\n\n"
            f"💡 Письма от незарегистрированных в TaskBridge пользователей будут требовать подтверждения.\n\n"
            f"Вы можете настроить фильтры и автоподтверждение ниже:",
            parse_mode="HTML",
            reply_markup=keyboard
        )

        await state.clear()

    except Exception as e:
        logger.error(f"Error saving email account: {e}", exc_info=True)
        await testing_msg.edit_text("❌ Ошибка при сохранении настроек. Попробуйте позже")
        db.rollback()

    finally:
        db.close()


@router.callback_query(F.data.startswith("email_autoconfirm:"))
async def toggle_autoconfirm(callback: CallbackQuery):
    """
    Переключение режима автоподтверждения
    """
    try:
        _, account_id, action = callback.data.split(":")
        account_id = int(account_id)

        db = get_db_session()
        email_account = db.query(EmailAccount).filter(EmailAccount.id == account_id).first()

        if not email_account:
            await callback.answer("Email аккаунт не найден", show_alert=True)
            db.close()
            return

        # Проверяем что это аккаунт текущего пользователя
        user = db.query(User).filter(User.telegram_id == callback.from_user.id).first()
        if not user or email_account.user_id != user.id:
            await callback.answer("Это не ваш email аккаунт", show_alert=True)
            db.close()
            return

        # Переключаем автоподтверждение
        email_account.auto_confirm = (action == "on")
        db.commit()

        # Обновляем кнопки
        new_action = "off" if action == "on" else "on"
        status_text = "Вкл" if action == "on" else "Выкл"

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚙️ Настроить фильтры",
                    callback_data=f"email_filters:{email_account.id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"🔄 Автоподтверждение: {status_text}",
                    callback_data=f"email_autoconfirm:{email_account.id}:{new_action}"
                )
            ]
        ])

        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await callback.answer(f"Автоподтверждение: {status_text}", show_alert=False)

        db.close()

    except Exception as e:
        logger.error(f"Error toggling autoconfirm: {e}", exc_info=True)
        await callback.answer("Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("email_filters:"))
async def show_email_filters(callback: CallbackQuery):
    """
    Показать настройки фильтров email (TODO: implement)
    """
    await callback.answer("Настройка фильтров будет доступна в следующей версии", show_alert=True)


@router.message(F.text == "/cancel")
async def cancel_registration(message: Message, state: FSMContext):
    """
    Отмена регистрации email
    """
    current_state = await state.get_state()

    if current_state is None:
        await message.answer("Нет активной регистрации")
        return

    await state.clear()
    await message.answer("❌ Регистрация email отменена")
