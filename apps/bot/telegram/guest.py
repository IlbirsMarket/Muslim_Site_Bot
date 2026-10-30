"""
Гостевой бот: филиал → меню → блюдо (размер, добавки) → корзина → доставка/самовывоз →
телефон → имя → адрес → оплата → подтверждение. Статус заказа приходит одним сообщением, которое обновляется.
Корзина хранится в памяти бота (после перезапуска бота — пустая).
"""

import asyncio                                               # пауза в цикле статусов
import logging

from asgiref.sync import sync_to_async                       # база Django из асинхронного бота
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext                   # шаги оформления и корзина
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup)

from apps.bot import guest_services as gs                    # меню, корзина, заказ
from apps.bot.texts import money

log = logging.getLogger(__name__)
guest_router = Router()
guest_router.message.filter(F.chat.type == ChatType.PRIVATE)  # гостевой бот — только личка

MENU, CART, ORDERS, BRANCH = "🍽 Меню", "🛒 Корзина", "📦 Мои заказы", "🏠 Филиал"   # главные кнопки


class Checkout(StatesGroup):
    """Шаги оформления."""
    phone = State()
    name = State()
    address = State()


def inline(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


def home_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=MENU), KeyboardButton(text=CART)],
                                         [KeyboardButton(text=ORDERS), KeyboardButton(text=BRANCH)]], resize_keyboard=True)


async def ask_branch(message: Message, state: FSMContext):
    """Выбор филиала (если он один — выбирается сам)."""
    items = await sync_to_async(gs.branches)()
    if len(items) == 1:
        await state.update_data(branch=items[0][0], cart=[])
        return await message.answer(f"Ассаляму алейкум! Кафе «Муслим», {items[0][1]}.", reply_markup=home_keyboard())
    await message.answer("Ассаляму алейкум! Выберите филиал:", reply_markup=inline([[(n, f"gb:{i}")] for i, n in items]))


@guest_router.message(CommandStart())
@guest_router.message(F.text == BRANCH)
async def start(message: Message, state: FSMContext):
    await state.clear()
    payload = (message.text or "").split(maxsplit=1)[1:] if (message.text or "").startswith("/start") else []
    if payload and payload[0].startswith("b") and payload[0][1:].isdigit():   # QR филиала: /start b2
        items = dict(await sync_to_async(gs.branches)())
        bid = int(payload[0][1:])
        if bid in items:                                     # филиал работает — сразу его меню
            await state.update_data(branch=bid, cart=[])
            await message.answer(f"Ассаляму алейкум! Кафе «Муслим», {items[bid]}.", reply_markup=home_keyboard())
            return await send_categories(message, bid)
    await ask_branch(message, state)


@guest_router.callback_query(F.data.startswith("gb:"))
async def pick_branch(cb: CallbackQuery, state: FSMContext):
    await state.update_data(branch=int(cb.data[3:]), cart=[])   # другой филиал — другое меню, корзина с нуля
    await cb.message.answer("Филиал выбран. Нажмите «🍽 Меню».", reply_markup=home_keyboard())
    await cb.answer()


async def branch_id(event, state: FSMContext):
    """Выбранный филиал или None (тогда просим выбрать)."""
    data = await state.get_data()
    if not data.get("branch"):
        await ask_branch(event if isinstance(event, Message) else event.message, state)
        return None
    return data["branch"]


# ===== Меню =====

async def send_categories(message: Message, bid: int):
    """Список категорий кнопками (по 2 в ряд)."""
    cats = await sync_to_async(gs.categories)(bid)
    rows = [[(n, f"gc:{i}") for i, n in cats[j:j + 2]] for j in range(0, len(cats), 2)]
    await message.answer("🍽 Выберите категорию:" if cats else "Меню пока пустое.", reply_markup=inline(rows))


@guest_router.message(F.text == MENU)
async def menu(message: Message, state: FSMContext):
    bid = await branch_id(message, state)
    if bid:
        await send_categories(message, bid)


PHOTO_IDS = {}                                               # фото уже в Telegram: путь → file_id (второй раз не загружаем)


def page_photo(page):
    """Фото блюда для Telegram: file_id, файл с диска или нарисованная заглушка."""
    from aiogram.types import BufferedInputFile, FSInputFile
    if page["photo"]:
        return PHOTO_IDS.get(page["photo"]) or FSInputFile(page["photo"])
    return BufferedInputFile(gs.placeholder_photo(page["name"]), filename="dish.jpg")


def page_keyboard(page, category_id, count):
    """Кнопки под фото: листание, в корзину, списком, категории, корзина."""
    i, total = page["index"], page["total"]
    rows = []
    if total > 1:
        rows.append([("◀️", f"gv:{category_id}:{i - 1}"), (f"{i + 1} / {total}", "gnop"), ("▶️", f"gv:{category_id}:{i + 1}")])
    rows.append([("➕ В корзину", f"gd:{page['id']}")])
    rows.append([("📋 Списком", f"gl:{category_id}:{i // LIST_SIZE}"), ("↩️ Категории", "gcats")])
    rows.append([(f"🛒 Корзина ({count})" if count else "🛒 Корзина", "gcart")])
    return inline(rows)


LIST_SIZE = 8                                                # блюд на одной странице списка


async def show_page(cb: CallbackQuery, state: FSMContext, category_id: int, index: int, new: bool):
    """Показать блюдо: новым сообщением (из категорий) или заменой фото в том же сообщении (листание)."""
    from aiogram.types import InputMediaPhoto
    bid = await branch_id(cb, state)
    page = await sync_to_async(gs.dish_page)(bid, category_id, index) if bid else None
    if not page:
        return await cb.answer("В этой категории сейчас нет блюд.", show_alert=True)
    count = gs.cart_count((await state.get_data()).get("cart"))
    markup = page_keyboard(page, category_id, count)
    if new:
        sent = await cb.message.answer_photo(page_photo(page), caption=page["caption"], reply_markup=markup)
    else:
        sent = await cb.message.edit_media(InputMediaPhoto(media=page_photo(page), caption=page["caption"]), reply_markup=markup)
    if page["photo"] and getattr(sent, "photo", None):       # запоминаем file_id — дальше листается мгновенно
        PHOTO_IDS[page["photo"]] = sent.photo[-1].file_id
    await cb.answer()


@guest_router.callback_query(F.data.startswith("gc:"))
async def category(cb: CallbackQuery, state: FSMContext):
    await show_page(cb, state, int(cb.data[3:]), 0, new=True)


@guest_router.callback_query(F.data.startswith("gv:"))
async def flip(cb: CallbackQuery, state: FSMContext):
    """◀️ / ▶️ и выбор из списка."""
    _, category_id, index = cb.data.split(":")
    await show_page(cb, state, int(category_id), int(index), new=False)


@guest_router.callback_query(F.data.startswith("gl:"))
async def as_list(cb: CallbackQuery, state: FSMContext):
    """«📋 Списком»: названия блюд кнопками, по 8 на странице."""
    _, category_id, page = cb.data.split(":")
    category_id, page = int(category_id), int(page)
    bid = await branch_id(cb, state)
    titles = await sync_to_async(gs.dish_titles)(bid, category_id) if bid else []
    pages = max(1, -(-len(titles) // LIST_SIZE))
    page %= pages
    start = page * LIST_SIZE
    rows = [[(name, f"gv:{category_id}:{start + i}")] for i, name in enumerate(titles[start:start + LIST_SIZE])]
    if pages > 1:
        rows.append([("◀️", f"gl:{category_id}:{page - 1}"), (f"{page + 1} / {pages}", "gnop"), ("▶️", f"gl:{category_id}:{page + 1}")])
    rows.append([("↩️ Категории", "gcats")])
    await cb.message.edit_reply_markup(reply_markup=inline(rows))
    await cb.answer()


@guest_router.callback_query(F.data == "gcats")
async def back_to_categories(cb: CallbackQuery, state: FSMContext):
    bid = await branch_id(cb, state)
    if bid:
        await send_categories(cb.message, bid)
    await cb.answer()


@guest_router.callback_query(F.data == "gnop")
async def nothing(cb: CallbackQuery):
    await cb.answer()                                        # кнопка «2 / 8» — просто надпись


async def show_extras(message: Message, state: FSMContext):
    """Добавки с галочками + «В корзину»."""
    data = await state.get_data()
    item = data["item"]
    rows = [[(("☑️ " if e in item["extra_ids"] else "➕ ") + f"{n} +{money(p)}", f"gx:{e}")] for e, n, p in data["extras"]]
    rows += [[("➖", "gq:-1"), (f"{item['quantity']} шт.", "gq:0"), ("➕", "gq:1")], [("🛒 В корзину", "ga")]]
    await message.edit_reply_markup(reply_markup=inline(rows))


@guest_router.callback_query(F.data.startswith("gd:"))
async def dish(cb: CallbackQuery, state: FSMContext):
    bid = await branch_id(cb, state)
    card = await sync_to_async(gs.dish_card)(bid, int(cb.data[3:])) if bid else None
    if not card:
        return await cb.answer("Блюдо закончилось.", show_alert=True)
    text, sizes, extras = card
    await state.update_data(item={"dish_id": int(cb.data[3:]), "size_id": None, "extra_ids": [], "quantity": 1}, extras=extras)
    if sizes:                                                 # сначала размер
        msg = await cb.message.answer(text + "\n\nВыберите размер:", reply_markup=inline([[(f"{n} — {money(p)}", f"gs:{i}")] for i, n, p in sizes]))
    else:
        msg = await cb.message.answer(text)
        await show_extras(msg, state)
    await cb.answer()


@guest_router.callback_query(F.data.startswith("gs:"))
async def size(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("item"):
        data["item"]["size_id"] = int(cb.data[3:])
        await state.update_data(item=data["item"])
        await show_extras(cb.message, state)
    await cb.answer("Размер выбран")


@guest_router.callback_query(F.data.startswith("gx:"))
async def extra(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if data.get("item"):
        eid, chosen = int(cb.data[3:]), data["item"]["extra_ids"]
        chosen.remove(eid) if eid in chosen else chosen.append(eid)   # галочка вкл/выкл
        await state.update_data(item=data["item"])
        await show_extras(cb.message, state)
    await cb.answer()


@guest_router.callback_query(F.data.startswith("gq:"))
async def quantity(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    step = int(cb.data[3:])
    if data.get("item") and step:
        data["item"]["quantity"] = max(1, min(50, data["item"]["quantity"] + step))
        await state.update_data(item=data["item"])
        await show_extras(cb.message, state)
    await cb.answer()


@guest_router.callback_query(F.data == "ga")
async def add_to_cart(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item = data.pop("item", None)                             # собранная позиция
    if not item:
        return await cb.answer()
    data["cart"] = data.get("cart", []) + [item]              # кладём в корзину
    await state.set_data(data)
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("Добавлено в корзину ✅")


# ===== Корзина и оформление =====

async def show_cart(message: Message, state: FSMContext):
    bid = await branch_id(message, state)
    if not bid:
        return
    text, total, _ = await sync_to_async(gs.cart_text)(bid, (await state.get_data()).get("cart", []))
    buttons = inline([[("🚚 Доставка", "gk:delivery"), ("🏃 Самовывоз", "gk:pickup")], [("🗑 Очистить", "gclr")]]) if total else None
    await message.answer(text, reply_markup=buttons)


@guest_router.message(F.text == CART)
async def cart(message: Message, state: FSMContext):
    await show_cart(message, state)


@guest_router.callback_query(F.data == "gcart")
async def cart_button(cb: CallbackQuery, state: FSMContext):
    await show_cart(cb.message, state)
    await cb.answer()


@guest_router.callback_query(F.data == "gclr")
async def clear(cb: CallbackQuery, state: FSMContext):
    await state.update_data(cart=[])
    await cb.message.edit_text("🛒 Корзина пуста.")
    await cb.answer()


@guest_router.callback_query(F.data.startswith("gk:"))
async def kind(cb: CallbackQuery, state: FSMContext):
    await state.update_data(kind=cb.data[3:])
    await state.set_state(Checkout.phone)
    contact = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)]], resize_keyboard=True)
    await cb.message.answer("Ваш номер телефона (кнопкой ниже или текстом):", reply_markup=contact)
    await cb.answer()


@guest_router.message(Checkout.phone)
async def phone(message: Message, state: FSMContext):
    value = message.contact.phone_number if message.contact else (message.text or "").strip()
    if len(value) < 6:
        return await message.answer("Напишите номер телефона, например +996 555 123 456.")
    await state.update_data(phone=value[:30])
    await state.set_state(Checkout.name)
    await message.answer("Как к вам обращаться?", reply_markup=home_keyboard())


@guest_router.message(Checkout.name)
async def name(message: Message, state: FSMContext):
    await state.update_data(name=(message.text or "").strip()[:100])
    if (await state.get_data()).get("kind") == "delivery":
        await state.set_state(Checkout.address)
        return await message.answer("Адрес доставки (улица, дом, квартира):")
    await ask_payment(message, state)


@guest_router.message(Checkout.address)
async def address(message: Message, state: FSMContext):
    await state.update_data(address=(message.text or "").strip()[:255])
    await ask_payment(message, state)


async def ask_payment(message: Message, state: FSMContext):
    await state.set_state(None)                               # шаги ввода закончились (данные остаются)
    await message.answer("Оплата:", reply_markup=inline([[("💵 Наличные", "gp:cash"), ("💳 Картой при получении", "gp:card")]]))


@guest_router.callback_query(F.data.startswith("gp:"))
async def payment(cb: CallbackQuery, state: FSMContext):
    await state.update_data(payment=cb.data[3:])
    data = await state.get_data()
    text, total, fee = await sync_to_async(gs.cart_text)(data["branch"], data.get("cart", []))
    delivery = data.get("kind") == "delivery"
    summary = (f"{text}\n" + (f"Доставка: {money(fee)}\nИтого: <b>{money(total + fee)}</b>\n📍 {data.get('address', '')}\n" if delivery else "Самовывоз\n")
               + f"👤 {data.get('name', '')} · {data.get('phone', '')}")
    await cb.message.answer(summary + "\n\nВсё верно?", reply_markup=inline([[("✅ Заказать", "gy"), ("✖️ Отмена", "gn")]]))
    await cb.answer()


@guest_router.callback_query(F.data == "gn")
async def cancel(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_reply_markup(reply_markup=None)
    await cb.answer("Оформление отменено. Корзина сохранена.")


@guest_router.callback_query(F.data == "gy")
async def confirm(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("cart"):
        return await cb.answer("Корзина пуста.", show_alert=True)
    order, error = await sync_to_async(gs.create_bot_order)(data["branch"], cb.message.chat.id, data)
    await cb.message.edit_reply_markup(reply_markup=None)
    if error:
        return await cb.answer(error, show_alert=True)
    await state.update_data(cart=[])
    await cb.answer(f"Заказ №{order.id} принят!")                 # статус придёт отдельным сообщением


@guest_router.message(F.text == ORDERS)
async def orders(message: Message):
    await message.answer(await sync_to_async(gs.my_orders)(message.chat.id))


@guest_router.message()
async def other(message: Message):
    await message.answer("Выберите кнопку ниже 👇", reply_markup=home_keyboard())


# ===== Статусы заказов гостям =====

async def run_guest_notifier(bot, pause: float = 3.0) -> None:
    """Одно сообщение на заказ: первое отправляется, дальше — редактируется."""
    from aiogram.exceptions import TelegramBadRequest
    while True:
        try:
            for event in await sync_to_async(gs.guest_pending)():
                chat_id, text, old = await sync_to_async(gs.guest_step)(event)
                try:
                    if old:
                        await bot.edit_message_text(text, chat_id=old.chat_id, message_id=old.message_id)
                        message_id = old.message_id
                    else:
                        message_id = (await bot.send_message(chat_id, text)).message_id
                except TelegramBadRequest as error:            # «не изменилось» или гость удалил чат — пропускаем
                    log.info("Гостю %s: %s", chat_id, error)
                    message_id = old.message_id if old else 0
                if message_id:
                    await sync_to_async(gs.guest_saved)(event, chat_id, message_id)
                else:
                    await sync_to_async(gs.BotEvent.objects.filter(pk=event.pk).update)(guest_processed_at=gs.timezone.now())
        except Exception:                                      # сеть / Telegram — попробуем позже
            log.exception("Статусы гостям")
        await asyncio.sleep(pause)
