"""
Личный чат с ботом: приветствие, вход сотрудника (логин + пароль с сайта), профиль, меню, выход.
И команда /ids в группе — показывает ID группы и темы для файла .env.
"""

from asgiref.sync import sync_to_async                       # вызывать Django (база) из асинхронного бота
from aiogram import F, Router                                # фильтры и набор обработчиков
from aiogram.enums import ChatType                           # личка или группа
from aiogram.exceptions import TelegramBadRequest            # ошибка Telegram (например, нельзя удалить)
from aiogram.filters import Command, CommandStart            # команды /start, /login ...
from aiogram.fsm.context import FSMContext                   # «на каком шаге входа» сейчас человек
from aiogram.fsm.state import State, StatesGroup             # шаги входа
from aiogram.types import Message                            # сообщение

from apps.bot import texts                                   # тексты и данные из базы
from apps.bot.services import login_from_telegram, unlink_telegram
from . import keyboards as kb                                # кнопки

router = Router()                                            # обработчики лички
router.message.filter(F.chat.type == ChatType.PRIVATE)       # всё ниже — только в личном чате с ботом

group_router = Router()                                      # обработчики группы


class Login(StatesGroup):
    """Шаги входа: сначала логин, потом пароль."""
    username = State()
    password = State()


async def current_staff(message: Message):
    """Сотрудник, который пишет боту (или None, если ещё не вошёл)."""
    return await sync_to_async(texts.staff_by_telegram)(message.from_user.id)


async def show_home(message: Message, user=None, text=None):
    """Главный экран: приветствие и кнопки."""
    await message.answer(text or texts.welcome_text(user), reply_markup=kb.main_keyboard(user is not None))


# ===== /start =====

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()                                      # начали сначала — забываем незаконченный вход
    await show_home(message, await current_staff(message))


# ===== Вход сотрудника =====

@router.message(Command("login"))
@router.message(F.text == kb.LOGIN)
async def login_start(message: Message, state: FSMContext):
    user = await current_staff(message)
    if user:                                                 # уже вошёл — повторно не нужно
        await show_home(message, user, f"Вы уже вошли как {texts.person(user)}. Чтобы сменить аккаунт, нажмите «{kb.LOGOUT}».")
        return
    await state.set_state(Login.username)
    await message.answer("Введите <b>логин</b> или email — тот же, что в панели на сайте.", reply_markup=kb.cancel_keyboard())


@router.message(F.text == kb.CANCEL)
async def login_cancel(message: Message, state: FSMContext):
    await state.clear()
    await show_home(message, await current_staff(message), "Вход отменён.")


@router.message(Login.username, F.text)
async def login_username(message: Message, state: FSMContext):
    await state.update_data(username=message.text.strip())   # запомнили логин до следующего сообщения
    await state.set_state(Login.password)
    await message.answer("Теперь <b>пароль</b>. Сообщение с паролем я сразу удалю из чата.")


@router.message(Login.password, F.text)
async def login_password(message: Message, state: FSMContext):
    password = message.text                                  # пароль берём…
    try:
        await message.delete()                               # …и сразу удаляем сообщение из чата
    except TelegramBadRequest:
        pass                                                 # не получилось удалить — вход всё равно продолжаем
    username = (await state.get_data()).get("username", "")
    await state.clear()
    user, error = await sync_to_async(login_from_telegram)(username, password, message.from_user.id)
    if error:                                                # неверно или пауза после 5 попыток
        await show_home(message, None, f"❌ {error}")
        return
    await show_home(message, user, f"✅ Готово, {texts.person(user)}! Вы вошли как <b>{user.get_role_display()}</b>.\n"
                                   "Этот Telegram привязан к вашему аккаунту — на сайте в панели появится «Telegram ✓».")


# ===== Профиль, меню, выход =====

@router.message(Command("me"))
@router.message(F.text == kb.PROFILE)
async def profile(message: Message):
    user = await current_staff(message)
    if not user:
        await show_home(message, None, "Вы ещё не вошли.")
        return
    await message.answer(await sync_to_async(texts.profile_text)(user), reply_markup=kb.main_keyboard(True))


@router.message(Command("menu"))
@router.message(F.text == kb.MENU)
async def menu(message: Message):
    for part in await sync_to_async(texts.menu_parts)():     # меню может прийти несколькими сообщениями
        await message.answer(part)


@router.message(Command("logout"))
@router.message(F.text == kb.LOGOUT)
async def logout(message: Message):
    user = await current_staff(message)
    if user:
        await sync_to_async(unlink_telegram)(user)           # Telegram ID в базе стирается
    await show_home(message, None, "Вы вышли. Этот Telegram больше не привязан к аккаунту.")


@router.message()
async def unknown(message: Message, state: FSMContext):
    """Любое другое сообщение — показываем главные кнопки."""
    await show_home(message, await current_staff(message), "Не понял. Выберите кнопку ниже 👇")


# ===== Группа: /ids =====

@group_router.message(Command("ids"))
async def ids(message: Message):
    """В группе: ID группы и этой темы — их нужно вписать в .env на сервере."""
    thread = message.message_thread_id if message.is_topic_message else None
    await message.reply(
        f"ID группы: <code>{message.chat.id}</code>\n"
        f"ID этой темы: <code>{thread or 'это общая тема'}</code>\n\n"
        "Напишите /ids в каждой теме (Админы, Кухня, Зал, Доставка, Отчёты) и впишите номера в .env."
    )