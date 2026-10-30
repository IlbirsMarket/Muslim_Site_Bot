"""
Бот сотрудников: кнопки под заказами и вызовами в группе + меню по ролям в личке
(стоп-лист, занятые столы, отчёт за день). Логика и права — в apps/bot/staff_actions.py.
"""

from asgiref.sync import sync_to_async                       # база Django из асинхронного бота
from aiogram import F, Router                                # фильтры и набор обработчиков
from aiogram.enums import ChatType                           # личка
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from apps.bot import staff_actions as sa                     # действия и права
from apps.bot.notify import CANCEL_REASONS                   # причины отмены
from apps.bot.texts import staff_by_telegram
from . import keyboards as kb

staff_router = Router()                                      # кнопки работают и в группе, и в личке
Btn = InlineKeyboardButton                                   # короткое имя


def inline(rows) -> InlineKeyboardMarkup:
    """[[(текст, данные)]] → клавиатура."""
    return InlineKeyboardMarkup(inline_keyboard=[[Btn(text=t, callback_data=d) for t, d in row] for row in rows])


# ===== Кнопки под заказами и вызовами (группа) =====

@staff_router.callback_query(F.data.startswith("o:"))
async def order_button(cb: CallbackQuery):
    """o:<id>:<действие>."""
    _, order_id, action = cb.data.split(":")
    answer = await sync_to_async(sa.order_action)(cb.from_user.id, int(order_id), action)
    if answer == "ask_reason":                               # отмена — сначала причина
        rows = [[(r, f"r:{order_id}:{i}")] for i, r in enumerate(CANCEL_REASONS)] + [[("↩️ Назад", f"b:{order_id}")]]
        await cb.message.edit_reply_markup(reply_markup=inline(rows))
        return await cb.answer("Выберите причину отмены")
    await cb.answer(answer, show_alert=answer != "Готово ✅")   # ошибка / нет прав — окном


@staff_router.callback_query(F.data.startswith("r:"))
async def cancel_reason(cb: CallbackQuery):
    """r:<id>:<номер причины> — отмена с причиной."""
    _, order_id, index = cb.data.split(":")
    answer = await sync_to_async(sa.order_action)(cb.from_user.id, int(order_id), "cancel", int(index))
    await cb.answer(answer, show_alert=answer != "Готово ✅")


@staff_router.callback_query(F.data.startswith("b:"))
async def cancel_back(cb: CallbackQuery):
    """«Назад» из выбора причины — вернуть обычные кнопки."""
    from apps.bot.models import BotMessage
    from apps.bot.notify import markup, order_buttons
    from apps.orders.models import Order

    def buttons():
        msg = BotMessage.objects.filter(chat_id=cb.message.chat.id, message_id=cb.message.message_id).first()
        order = Order.objects.filter(pk=int(cb.data[2:])).first()
        return markup(order_buttons(order, msg.place)) if msg and order else None

    await cb.message.edit_reply_markup(reply_markup=await sync_to_async(buttons)())
    await cb.answer()


@staff_router.callback_query(F.data.startswith("c:"))
async def call_button(cb: CallbackQuery):
    """c:<id>:done — подошёл к столу."""
    answer = await sync_to_async(sa.call_done)(cb.from_user.id, int(cb.data.split(":")[1]))
    await cb.answer(answer, show_alert=answer != "Готово ✅")


# ===== Личка: стоп-лист =====

async def staff(message_or_cb):
    """Вошедший сотрудник или None."""
    return await sync_to_async(staff_by_telegram)(message_or_cb.from_user.id)


@staff_router.message(F.chat.type == ChatType.PRIVATE, F.text == kb.STOP)
async def stop_list(message: Message):
    user = await staff(message)
    if not user or not (user.is_cook or user.is_cafe_admin):
        return await message.answer(sa.NO_RIGHTS)
    cats = await sync_to_async(sa.stop_categories)(user)
    if not cats:
        return await message.answer("Категорий пока нет.")
    await message.answer("🛑 Стоп-лист. Выберите категорию:", reply_markup=inline([[(name, f"sc:{cid}")] for cid, name in cats]))


async def show_dishes(cb: CallbackQuery, category_id: int):
    """Блюда категории с переключателями ✅ / ⛔."""
    user = await staff(cb)
    dishes = await sync_to_async(sa.stop_dishes)(user, category_id) if user else []
    rows = [[(("✅ " if ok else "⛔ ") + name, f"st:{did}")] for did, name, ok in dishes] + [[("↩️ Категории", "sc:0")]]
    await cb.message.edit_text("Нажмите на блюдо: ✅ есть · ⛔ в стоп-листе", reply_markup=inline(rows))


@staff_router.callback_query(F.data.startswith("sc:"))
async def stop_category(cb: CallbackQuery):
    category_id = int(cb.data[3:])
    if category_id == 0:                                     # назад к категориям
        user = await staff(cb)
        cats = await sync_to_async(sa.stop_categories)(user) if user else []
        await cb.message.edit_text("🛑 Стоп-лист. Выберите категорию:", reply_markup=inline([[(n, f"sc:{c}")] for c, n in cats]))
    else:
        await show_dishes(cb, category_id)
    await cb.answer()


@staff_router.callback_query(F.data.startswith("st:"))
async def stop_toggle(cb: CallbackQuery):
    answer, category_id = await sync_to_async(sa.toggle_dish)(cb.from_user.id, int(cb.data[3:]))
    if category_id:
        await show_dishes(cb, category_id)                   # перерисовать список
    await cb.answer(answer, show_alert=category_id is None)


# ===== Личка: занятые столы =====

async def tables_markup(user):
    tables = await sync_to_async(sa.busy_tables)(user)
    return inline([[(f"🧹 Освободить: {name}", f"ft:{tid}")] for tid, name in tables]) if tables else None


@staff_router.message(F.chat.type == ChatType.PRIVATE, F.text == kb.TABLES)
async def tables(message: Message):
    user = await staff(message)
    if not user or not (user.is_waiter or user.is_cafe_admin):
        return await message.answer(sa.NO_RIGHTS)
    markup = await tables_markup(user)
    await message.answer("🍽 Занятые столы:" if markup else "Все столы свободны.", reply_markup=markup)


@staff_router.callback_query(F.data.startswith("ft:"))
async def free_table(cb: CallbackQuery):
    answer = await sync_to_async(sa.free_table)(cb.from_user.id, int(cb.data[3:]))
    user = await staff(cb)
    if user:
        markup = await tables_markup(user)
        await cb.message.edit_text("🍽 Занятые столы:" if markup else "Все столы свободны.", reply_markup=markup)
    await cb.answer(answer)


# ===== Личка: отчёт за день =====

async def send_report(message: Message, user, key: str = ""):
    text, pdf, name = await sync_to_async(sa.day_report)(user, key)
    await message.answer(text)
    await message.answer_document(BufferedInputFile(pdf, filename=name))


@staff_router.message(F.chat.type == ChatType.PRIVATE, F.text == kb.REPORT)
async def report(message: Message):
    user = await staff(message)
    if not sa.can_see_report(user):
        return await message.answer(sa.NO_RIGHTS)
    if user.sees_all_branches():                             # шеф выбирает филиал
        from apps.cafe.models import Branch
        branches = await sync_to_async(lambda: list(Branch.objects.filter(is_active=True).values_list("id", "name")))()
        rows = [[(name, f"rp:{bid}")] for bid, name in branches] + [[("Оба филиала", "rp:all")]]
        return await message.answer("Отчёт за сегодня — какой филиал?", reply_markup=inline(rows))
    await send_report(message, user)


@staff_router.callback_query(F.data.startswith("rp:"))
async def report_branch(cb: CallbackQuery):
    user = await staff(cb)
    if not sa.can_see_report(user):
        return await cb.answer(sa.NO_RIGHTS, show_alert=True)
    await cb.answer("Готовлю отчёт…")
    await send_report(cb.message, user, cb.data[3:])
