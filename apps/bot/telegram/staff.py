"""
Бот сотрудников: кнопки под заказами и вызовами в группе + меню по ролям в личке
(стоп-лист, занятые столы, отчёт за день). Логика и права — в apps/bot/staff_actions.py.
"""

from asgiref.sync import sync_to_async                       # база Django из асинхронного бота
from aiogram import F, Router                                # фильтры и набор обработчиков
from aiogram.fsm.context import FSMContext                   # где экран лички
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from apps.bot import staff_actions as sa                     # действия и права
from apps.bot.notify import CANCEL_REASONS                   # причины отмены
from apps.bot.texts import staff_by_telegram
from .handlers import screen                                 # экран лички (одно сообщение)
from .screen import add_trash

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


# ===== Личка: стоп-лист (всё в одном экране) =====

HOME = ("↩️ Кафе", "cafe")                                   # разделы кафе возвращают в «Кафе»


async def staff(event):
    """Вошедший сотрудник или None."""
    return await sync_to_async(staff_by_telegram)(event.from_user.id)


async def show_categories(cb: CallbackQuery, state: FSMContext, user):
    cats = await sync_to_async(sa.stop_categories)(user)
    rows = [[(name, f"sc:{cid}")] for cid, name in cats] + [[HOME]]
    await screen(cb, state, "🛑 <b>Стоп-лист</b>\nВыберите категорию:" if cats else "Категорий пока нет.", rows)


async def show_dishes(cb: CallbackQuery, state: FSMContext, user, category_id: int):
    """Блюда категории с переключателями ✅ / ⛔."""
    dishes = await sync_to_async(sa.stop_dishes)(user, category_id)
    rows = [[(("✅ " if ok else "⛔ ") + name, f"st:{did}")] for did, name, ok in dishes] + [[("↩️ Категории", "sc:0"), HOME]]
    await screen(cb, state, "🛑 <b>Стоп-лист</b>\nНажмите на блюдо: ✅ есть · ⛔ нет в наличии", rows)


@staff_router.callback_query(F.data.startswith("sc:"))
async def stop_category(cb: CallbackQuery, state: FSMContext):
    user = await staff(cb)
    if not user or not (user.is_cook or user.is_cafe_admin):
        return await cb.answer(sa.NO_RIGHTS, show_alert=True)
    category_id = int(cb.data[3:])
    if category_id:
        await show_dishes(cb, state, user, category_id)
    else:
        await show_categories(cb, state, user)
    await cb.answer()


@staff_router.callback_query(F.data.startswith("st:"))
async def stop_toggle(cb: CallbackQuery, state: FSMContext):
    answer, category_id = await sync_to_async(sa.toggle_dish)(cb.from_user.id, int(cb.data[3:]))
    if category_id:
        await show_dishes(cb, state, await staff(cb), category_id)   # перерисовать список в том же сообщении
    await cb.answer(answer, show_alert=category_id is None)


# ===== Личка: занятые столы =====

async def show_tables(cb: CallbackQuery, state: FSMContext, user):
    tables = await sync_to_async(sa.busy_tables)(user)
    rows = [[(f"🧹 Освободить: {name}", f"ft:{tid}")] for tid, name in tables] + [[("🔄 Обновить", "tb"), HOME]]
    await screen(cb, state, "🍽 <b>Занятые столы</b>" if tables else "🍽 Все столы свободны.", rows)


@staff_router.callback_query(F.data == "tb")
async def tables(cb: CallbackQuery, state: FSMContext):
    user = await staff(cb)
    if not user or not (user.is_waiter or user.is_cafe_admin):
        return await cb.answer(sa.NO_RIGHTS, show_alert=True)
    await show_tables(cb, state, user)
    await cb.answer()


@staff_router.callback_query(F.data.startswith("ft:"))
async def free_table(cb: CallbackQuery, state: FSMContext):
    answer = await sync_to_async(sa.free_table)(cb.from_user.id, int(cb.data[3:]))
    user = await staff(cb)
    if user:
        await show_tables(cb, state, user)
    await cb.answer(answer)


# ===== Личка: отчёт за день (PDF удаляется, когда уходите с экрана) =====

async def send_report(cb: CallbackQuery, state: FSMContext, user, key: str = ""):
    text, pdf, name = await sync_to_async(sa.day_report)(user, key)
    back = [("↩️ Филиалы", "rpm")] if user.sees_all_branches() else []
    await screen(cb, state, text + "\n\nPDF — ниже 👇", [back + [HOME]])
    doc = await cb.message.bot.send_document(cb.message.chat.id, BufferedInputFile(pdf, filename=name))
    await add_trash(state, doc.message_id)                   # PDF уберётся при следующей смене экрана


@staff_router.callback_query(F.data == "rpm")
async def report(cb: CallbackQuery, state: FSMContext):
    user = await staff(cb)
    if not sa.can_see_report(user):
        return await cb.answer(sa.NO_RIGHTS, show_alert=True)
    if user.sees_all_branches():                             # шеф выбирает филиал
        from apps.cafe.models import Branch
        branches = await sync_to_async(lambda: list(Branch.objects.filter(is_active=True).values_list("id", "name")))()
        rows = [[(name, f"rp:{bid}")] for bid, name in branches] + [[("Оба филиала", "rp:all")], [HOME]]
        await screen(cb, state, "📊 Отчёт за сегодня — какой филиал?", rows)
        return await cb.answer()
    await cb.answer("Готовлю отчёт…")
    await send_report(cb, state, user)


@staff_router.callback_query(F.data.startswith("rp:"))
async def report_branch(cb: CallbackQuery, state: FSMContext):
    user = await staff(cb)
    if not sa.can_see_report(user):
        return await cb.answer(sa.NO_RIGHTS, show_alert=True)
    await cb.answer("Готовлю отчёт…")
    await send_report(cb, state, user, cb.data[3:])
