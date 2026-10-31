"""
Личный чат с ботом сотрудников — всё на инлайн-кнопках в ОДНОМ сообщении-экране (см. screen.py):
вход (логин и пароль удаляются сразу), главная по роли, профиль, меню кафе, выход.
И команда /ids в группе — показывает ID группы и темы для файла .env.
"""

from asgiref.sync import sync_to_async                       # вызывать Django (база) из асинхронного бота
from aiogram import F, Router                                # фильтры и набор обработчиков
from aiogram.enums import ChatType                           # личка или группа
from aiogram.exceptions import TelegramBadRequest            # ошибка Telegram (например, нельзя удалить)
from aiogram.filters import Command, CommandStart            # команды /start, /login ...
from aiogram.fsm.context import FSMContext                   # «на каком шаге входа» сейчас человек
from aiogram.fsm.state import State, StatesGroup             # шаги входа
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message, ReplyKeyboardRemove   # сообщение, кнопка, фото

from apps.bot import guest_services as gs                    # меню с фото — то же, что у гостей
from apps.bot import texts                                   # тексты и данные из базы
from apps.bot.services import login_from_telegram, unlink_telegram
from .screen import delete, drop_user_message, inline, show   # «один экран»

router = Router()                                            # обработчики лички
router.message.filter(F.chat.type == ChatType.PRIVATE)       # всё ниже — только в личном чате с ботом

group_router = Router()                                      # обработчики группы


class Login(StatesGroup):
    """Шаги входа: сначала логин, потом пароль."""
    username = State()
    password = State()


def home_rows(user) -> list:
    """Главная: до входа — «Войти»; после — два раздела: «Кафе» и «Профиль»."""
    if user is None:
        return [[("🔑 Войти как сотрудник", "sl")]]
    return [[("☕ Кафе", "cafe"), ("👤 Профиль", "sp")]]


def cafe_rows(user) -> list:
    """Раздел «Кафе» в две колонки: Меню → Занятые столы → Стоп-лист → Отчёт (только то, что можно роли)."""
    items = [("📋 Меню кафе", "smn")]
    if user.is_waiter or user.is_cafe_admin:
        items.append(("🍽 Занятые столы", "tb"))
    if user.is_cook or user.is_cafe_admin:
        items.append(("🛑 Стоп-лист", "sc:0"))
    if user.is_cafe_admin or user.sees_all_branches():
        items.append(("📊 Отчёт за день", "rpm"))
    return [items[i:i + 2] for i in range(0, len(items), 2)] + [[("↩️ Главная", "sh")]]


async def screen(event, state: FSMContext, text, rows=(), photo=None, key=None):
    """Показать экран лички (на месте старого). photo — экран с картинкой (меню кафе)."""
    msg = event.message if isinstance(event, CallbackQuery) else event
    current = msg if isinstance(event, CallbackQuery) else None
    return await show(msg.bot, msg.chat.id, state, text, rows, photo, key, current=current)


async def current_staff(event):
    """Сотрудник, который пишет боту (или None, если ещё не вошёл)."""
    return await sync_to_async(texts.staff_by_telegram)(event.from_user.id)


async def show_home(event, state: FSMContext, user=None, note=""):
    """Главный экран."""
    await state.set_state(None)
    text = (note + "\n\n" if note else "") + texts.welcome_text(user)
    await screen(event, state, text, home_rows(user))


# ===== /start =====

@router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    """Старый экран убираем, новый — внизу чата."""
    data = await state.get_data()
    await drop_user_message(message)
    await delete(message.bot, message.chat.id, data.get("screen"))
    await state.clear()
    tmp = await message.answer("…", reply_markup=ReplyKeyboardRemove())   # убрать нижнюю клавиатуру прошлой версии
    await delete(message.bot, message.chat.id, tmp.message_id)
    await show_home(message, state, await current_staff(message))


@router.callback_query(F.data == "sh")
async def to_home(cb: CallbackQuery, state: FSMContext):
    await show_home(cb, state, await current_staff(cb))
    await cb.answer()


# ===== Вход сотрудника: всё в одном экране, сообщения с логином и паролем сразу удаляются =====

@router.callback_query(F.data == "sl")
async def login_start(cb: CallbackQuery, state: FSMContext):
    user = await current_staff(cb)
    if user:                                                 # уже вошёл
        await show_home(cb, state, user)
        return await cb.answer("Вы уже вошли")
    await state.set_state(Login.username)
    await screen(cb, state, "🔑 <b>Вход</b>\nНапишите <b>логин</b> или email — тот же, что в панели на сайте.", [[("✖️ Отмена", "sh")]])
    await cb.answer()


@router.message(Login.username, F.text)
async def login_username(message: Message, state: FSMContext):
    await state.update_data(username=message.text.strip())   # запомнили логин
    await drop_user_message(message)                          # и убрали из чата
    await state.set_state(Login.password)
    await screen(message, state, f"🔑 <b>Вход</b>\nЛогин: {texts.escape(message.text.strip())}\nТеперь напишите <b>пароль</b> — сообщение сразу удалится.",
                 [[("✖️ Отмена", "sh")]])


@router.message(Login.password, F.text)
async def login_password(message: Message, state: FSMContext):
    password = message.text                                  # пароль берём…
    await drop_user_message(message)                          # …и сразу удаляем сообщение из чата
    username = (await state.get_data()).get("username", "")
    user, error = await sync_to_async(login_from_telegram)(username, password, message.from_user.id)
    if error:                                                # неверно или пауза после 5 попыток
        await state.set_state(Login.username)
        return await screen(message, state, f"❌ {error}\n\nНапишите <b>логин</b> ещё раз.", [[("✖️ Отмена", "sh")]])
    await show_home(message, state, user, f"✅ Готово! Вы вошли как <b>{user.get_role_display()}</b>.")


# ===== Профиль, меню, выход =====

@router.callback_query(F.data == "sp")
async def profile(cb: CallbackQuery, state: FSMContext):
    """Профиль: всё о сотруднике и кнопка «Выйти»."""
    user = await current_staff(cb)
    if not user:
        return await show_home(cb, state, None, "Вы ещё не вошли.")
    await screen(cb, state, "👤 " + await sync_to_async(texts.profile_text)(user), [[("🚪 Выйти", "so"), ("↩️ Главная", "sh")]])
    await cb.answer()


@router.callback_query(F.data == "cafe")
async def cafe(cb: CallbackQuery, state: FSMContext):
    """Раздел «Кафе»."""
    user = await current_staff(cb)
    if not user:
        return await show_home(cb, state, None, "Вы ещё не вошли.")
    branch = f" · {texts.escape(user.branch.name)}" if user.branch_id else ""
    await screen(cb, state, f"☕ <b>Кафе</b>{branch}\nВыберите раздел:", cafe_rows(user))
    await cb.answer()


# ===== Меню кафе с картинками: категории → блюдо с фото (◀️ ▶️, списком) — в одном сообщении =====

LIST_SIZE = 8                                                # блюд на странице «Списком»


async def staff_branch_id(cb):
    """Филиал сотрудника (шеф / программист — первый)."""
    from apps.cafe.models import Branch
    user = await current_staff(cb)
    if user is None:
        return None
    return user.branch_id or (await sync_to_async(Branch.default)()).id


@router.callback_query(F.data == "smn")
async def menu(cb: CallbackQuery, state: FSMContext):
    bid = await staff_branch_id(cb)
    if not bid:
        return await show_home(cb, state, None, "Вы ещё не вошли.")
    cats = await sync_to_async(gs.categories)(bid, True)
    rows = [[(n, f"smv:{i}:0") for i, n in cats[j:j + 2]] for j in range(0, len(cats), 2)] + [[("↩️ Кафе", "cafe")]]
    await screen(cb, state, "📋 <b>Меню кафе</b>\nВыберите категорию:" if cats else "Меню пока пустое.", rows)
    await cb.answer()


@router.callback_query(F.data.startswith("smv:"))
async def menu_dish(cb: CallbackQuery, state: FSMContext):
    """Блюдо с фото; ◀️ ▶️ меняют его в том же сообщении."""
    _, cat, index = cb.data.split(":")
    cat = int(cat)
    bid = await staff_branch_id(cb)
    page = await sync_to_async(gs.dish_page)(bid, cat, int(index), True) if bid else None
    if not page:
        return await cb.answer("В этой категории нет блюд.", show_alert=True)
    i, total = page["index"], page["total"]
    rows = [[("◀️", f"smv:{cat}:{i - 1}"), (f"{i + 1} / {total}", "_"), ("▶️", f"smv:{cat}:{i + 1}")]] if total > 1 else []
    rows += [[("📋 Списком", f"sml:{cat}:{i // LIST_SIZE}"), ("↩️ Категории", "smn")]]
    if page["photo"]:
        photo, key = FSInputFile(page["photo"]), page["photo"]
    else:
        photo, key = BufferedInputFile(gs.placeholder_photo(page["name"]), filename="dish.jpg"), f"ph:{page['name']}"
    await screen(cb, state, page["caption"], rows, photo, key)
    await cb.answer()


@router.callback_query(F.data.startswith("sml:"))
async def menu_list(cb: CallbackQuery, state: FSMContext):
    """«📋 Списком»: меняются только кнопки под фото."""
    _, cat, page = cb.data.split(":")
    cat, page = int(cat), int(page)
    bid = await staff_branch_id(cb)
    titles = await sync_to_async(gs.dish_titles)(bid, cat, True) if bid else []
    pages = max(1, -(-len(titles) // LIST_SIZE))
    page %= pages
    first = page * LIST_SIZE
    rows = [[(name, f"smv:{cat}:{first + n}")] for n, name in enumerate(titles[first:first + LIST_SIZE])]
    if pages > 1:
        rows.append([("◀️", f"sml:{cat}:{page - 1}"), (f"{page + 1} / {pages}", "_"), ("▶️", f"sml:{cat}:{page + 1}")])
    rows.append([("↩️ Категории", "smn")])
    try:
        await cb.message.edit_reply_markup(reply_markup=inline(rows))
    except TelegramBadRequest:
        pass
    await cb.answer()


@router.callback_query(F.data == "so")
async def logout(cb: CallbackQuery, state: FSMContext):
    user = await current_staff(cb)
    if user:
        await sync_to_async(unlink_telegram)(user)           # Telegram ID в базе стирается
    await show_home(cb, state, None, "Вы вышли. Этот Telegram больше не привязан к аккаунту.")
    await cb.answer()


@router.callback_query(F.data == "_")
async def nothing(cb: CallbackQuery):
    await cb.answer()                                        # надпись «2 / 5» — не кнопка


@router.message()
async def unknown(message: Message, state: FSMContext):
    """Любой другой текст убираем; экрана нет — показываем главную."""
    await drop_user_message(message)
    if not (await state.get_data()).get("screen"):
        await show_home(message, state, await current_staff(message))


# ===== Группа: /ids =====

@group_router.message(Command("ids"))
async def ids(message: Message):
    """В группе: ID группы и этой темы — их нужно вписать в .env на сервере."""
    thread = message.message_thread_id if message.is_topic_message else None
    if thread:
        text = (f"✅ Это тема. Впишите в админке сайта (Филиалы → ваш филиал → Telegram):\n"
                f"• ID группы: <code>{message.chat.id}</code>\n"
                f"• ID этой темы: <code>{thread}</code> — в поле этой темы (Админы, Кухня, Зал, Доставка или Отчёты)")
    else:
        text = (f"ID группы: <code>{message.chat.id}</code>\n\n"
                "⚠️ Это общий чат, а не тема. Напишите /ids внутри каждой темы (Админы, Кухня, Зал, Доставка, Отчёты) — "
                "у каждой свой небольшой номер.")
    await message.reply(text)
