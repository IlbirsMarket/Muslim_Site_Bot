"""
Гостевой бот — всё на инлайн-кнопках и в ОДНОМ сообщении-экране (см. screen.py).
Главная → Меню → категория → блюдо с фото (◀️ ▶️, списком) → размер / добавки / количество → корзина (➖ ➕) →
доставка или самовывоз → телефон → имя → адрес → оплата → «Заказать».
После «Заказать» экран становится сообщением о статусе заказа: бот обновляет его сам (Принят → Готовится → …).
Что гость пишет текстом (телефон, имя, адрес), бот читает и сразу удаляет. Корзина — в памяти бота.
"""

import asyncio                                               # пауза в цикле статусов
import logging

from asgiref.sync import sync_to_async                       # база Django из асинхронного бота
from aiogram import F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext                   # шаги оформления, корзина, где экран
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message, ReplyKeyboardRemove

from apps.bot import guest_services as gs                    # меню, корзина, заказ (без Telegram)
from apps.bot.texts import money
from .screen import delete, drop_user_message, forget_screen, inline, show

log = logging.getLogger(__name__)
guest_router = Router()
guest_router.message.filter(F.chat.type == ChatType.PRIVATE)  # гостевой бот — только личка

LIST_SIZE = 8                                                # блюд на странице «Списком»
STATUS_ROWS = [[("🍽 Новый заказ", "sm"), ("📦 Мои заказы", "so")]]   # кнопки под сообщением о статусе


class Checkout(StatesGroup):
    """Шаги, где гость пишет текстом."""
    phone = State()
    name = State()
    address = State()


async def screen(cb_or_msg, state: FSMContext, text, rows=(), photo=None, key=None, here=True):
    """Показать экран в этом чате. here=False — не трогать сообщение, на котором нажали (статус заказа)."""
    msg = cb_or_msg.message if isinstance(cb_or_msg, CallbackQuery) else cb_or_msg
    current = msg if isinstance(cb_or_msg, CallbackQuery) and here else None
    return await show(msg.bot, msg.chat.id, state, text, rows, photo, key, current)


# ===== Главная и филиал =====

async def home(event, state: FSMContext, note: str = "", here=True):
    """Главный экран."""
    data = await state.get_data()
    branches = await sync_to_async(gs.branches)()
    if not data.get("branch"):                               # филиал ещё не выбран
        if len(branches) == 1:
            await state.update_data(branch=branches[0][0])
            data["branch"] = branches[0][0]
        else:
            return await screen(event, state, (note + "\n\n" if note else "") + "Ассаляму алейкум! Выберите филиал кафе «Муслим»:",
                                [[(n, f"b:{i}")] for i, n in branches], here=here)
    name = dict(branches).get(data["branch"], "")
    count = gs.cart_count(data.get("cart"))
    rows = [[("🍽 Меню", "m")], [(f"🛒 Корзина ({count})" if count else "🛒 Корзина", "c"), ("📦 Мои заказы", "o")]]
    if len(branches) > 1:
        rows.append([("🏠 Сменить филиал", "b")])
    table = data.get("table")
    where = f"\n🍽 Вы за столом: <b>{table['label']}</b>" if table else "\nМеню с фото, доставка и самовывоз."
    text = (note + "\n\n" if note else "") + f"Ассаляму алейкум! Кафе «Муслим» · <b>{name}</b>" + where
    await screen(event, state, text, rows, here=here)


@guest_router.message(CommandStart())
async def start(message: Message, state: FSMContext):
    """/start (и /start b2 из QR филиала): старый экран убираем, показываем новый внизу чата."""
    data = await state.get_data()
    await drop_user_message(message)                          # сам «/start» тоже убираем
    await delete(message.bot, message.chat.id, data.get("screen"))
    keep = {k: data[k] for k in ("branch", "cart", "last") if k in data}   # корзину и контакты не теряем
    await state.clear()
    await state.update_data(**keep)
    tmp = await message.answer("…", reply_markup=ReplyKeyboardRemove())   # убрать старую нижнюю клавиатуру (прошлая версия бота)
    await delete(message.bot, message.chat.id, tmp.message_id)
    arg = (message.text or "").split(maxsplit=1)[1:]
    code = arg[0] if arg else ""
    await state.update_data(table=None)                                  # режим стола — только по кнопке со стола
    if code.startswith("t"):                                             # «Заказать в Telegram» со стола: /start t<токен>
        found = await sync_to_async(gs.table_by_start)(code[1:])
        if found:
            bid, token, label = found
            if keep.get("branch") != bid:
                await state.update_data(branch=bid, cart=[])
            await state.update_data(table={"token": token, "label": label})
            return await home(message, state)
        return await home(message, state, "Этот стол больше не принимает заказы через бота. Отсканируйте QR на столе ещё раз.")
    if code.startswith("b"):                                             # QR бота филиала: /start b<код>
        bid = await sync_to_async(gs.branch_by_start)(code[1:])
        if bid:
            if keep.get("branch") != bid:
                await state.update_data(branch=bid, cart=[])                # другой филиал — другое меню
            return await categories(message, state)
        return await home(message, state, "Этот QR устарел. Выберите филиал ниже.")
    await home(message, state)


@guest_router.callback_query(F.data == "h")
async def to_home(cb: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await home(cb, state)
    await cb.answer()


@guest_router.callback_query(F.data == "b")
async def branches(cb: CallbackQuery, state: FSMContext):
    items = await sync_to_async(gs.branches)()
    await screen(cb, state, "Выберите филиал:", [[(n, f"b:{i}")] for i, n in items] + [[("↩️ Главная", "h")]])
    await cb.answer()


@guest_router.callback_query(F.data.startswith("b:"))
async def pick_branch(cb: CallbackQuery, state: FSMContext):
    bid = int(cb.data[2:])
    if (await state.get_data()).get("branch") != bid:
        await state.update_data(branch=bid, cart=[], table=None)   # другой филиал — корзина с нуля, стол не тот
    await home(cb, state)
    await cb.answer("Филиал выбран")


async def branch_or_home(cb, state):
    """Филиал из состояния; нет (бот перезапускали) — показываем главную."""
    bid = (await state.get_data()).get("branch")
    if not bid:
        await home(cb, state)
    return bid


# ===== Меню: категории → блюдо с фото → списком =====

async def categories(event, state: FSMContext):
    data = await state.get_data()
    cats = await sync_to_async(gs.categories)(data["branch"])
    count = gs.cart_count(data.get("cart"))
    rows = [[(n, f"v:{i}:0") for i, n in cats[j:j + 2]] for j in range(0, len(cats), 2)]
    rows.append([(f"🛒 Корзина ({count})" if count else "🛒 Корзина", "c"), ("↩️ Главная", "h")])
    await screen(event, state, "🍽 <b>Меню</b>\nВыберите категорию:" if cats else "Меню пока пустое.", rows)


@guest_router.callback_query(F.data == "m")
async def menu(cb: CallbackQuery, state: FSMContext):
    if await branch_or_home(cb, state):
        await categories(cb, state)
    await cb.answer()


def photo_of(page):
    """Фото блюда: файл с диска или нарисованная картинка."""
    if page["photo"]:
        return FSInputFile(page["photo"]), page["photo"]
    return BufferedInputFile(gs.placeholder_photo(page["name"]), filename="dish.jpg"), f"ph:{page['name']}"


async def dish_screen(cb: CallbackQuery, state: FSMContext, category_id: int, index: int):
    """Карточка блюда с листанием — всегда в том же сообщении."""
    bid = await branch_or_home(cb, state)
    if not bid:
        return
    page = await sync_to_async(gs.dish_page)(bid, category_id, index)
    if not page:
        return await cb.answer("В этой категории сейчас нет блюд.", show_alert=True)
    i, total = page["index"], page["total"]
    count = gs.cart_count((await state.get_data()).get("cart"))
    rows = []
    if total > 1:
        rows.append([("◀️", f"v:{category_id}:{i - 1}"), (f"{i + 1} / {total}", "_"), ("▶️", f"v:{category_id}:{i + 1}")])
    rows += [[("➕ В корзину", f"a:{category_id}:{i}:{page['id']}")],
             [("📋 Списком", f"l:{category_id}:{i // LIST_SIZE}"), ("↩️ Категории", "m")],
             [(f"🛒 Корзина ({count})" if count else "🛒 Корзина", "c")]]
    photo, key = photo_of(page)
    await state.update_data(view=[category_id, i])            # где гость сейчас (для «Назад»)
    await screen(cb, state, page["caption"], rows, photo, key)


@guest_router.callback_query(F.data.startswith("v:"))
async def flip(cb: CallbackQuery, state: FSMContext):
    """Открыть категорию, ◀️ / ▶️, выбор из списка."""
    _, category_id, index = cb.data.split(":")
    await dish_screen(cb, state, int(category_id), int(index))
    await cb.answer()


@guest_router.callback_query(F.data.startswith("l:"))
async def as_list(cb: CallbackQuery, state: FSMContext):
    """«📋 Списком»: меняются только кнопки под фото."""
    _, category_id, page = cb.data.split(":")
    category_id, page = int(category_id), int(page)
    bid = await branch_or_home(cb, state)
    if not bid:
        return await cb.answer()
    titles = await sync_to_async(gs.dish_titles)(bid, category_id)
    pages = max(1, -(-len(titles) // LIST_SIZE))
    page %= pages
    first = page * LIST_SIZE
    rows = [[(name, f"v:{category_id}:{first + n}")] for n, name in enumerate(titles[first:first + LIST_SIZE])]
    if pages > 1:
        rows.append([("◀️", f"l:{category_id}:{page - 1}"), (f"{page + 1} / {pages}", "_"), ("▶️", f"l:{category_id}:{page + 1}")])
    rows.append([("↩️ Категории", "m")])
    try:
        await cb.message.edit_reply_markup(reply_markup=inline(rows))
    except TelegramBadRequest:
        pass
    await cb.answer()


@guest_router.callback_query(F.data == "_")
async def nothing(cb: CallbackQuery):
    await cb.answer()                                         # надпись «2 / 8» — не кнопка


# ===== Выбор размера, добавок, количества — в том же сообщении =====

async def config_screen(cb: CallbackQuery, state: FSMContext):
    """Подпись под фото — что выбрано и сумма; кнопки — что можно выбрать."""
    data = await state.get_data()
    item = data["item"]
    sizes, extras = await sync_to_async(gs.dish_options)(item["dish_id"])
    caption = await sync_to_async(gs.config_caption)(item)
    total = await sync_to_async(gs.item_total)(item)
    back = f"v:{item['cat']}:{item['idx']}"
    if sizes and not item.get("size_id"):                     # сначала размер
        rows = [[(f"{n} — {money(p)}", f"z:{i}")] for i, n, p in sizes] + [[("↩️ Назад", back)]]
        caption += "\n\nВыберите размер:"
    else:
        rows = [[(("✅ " if e in item["extra_ids"] else "➕ ") + f"{n} +{money(p)}", f"x:{e}")] for e, n, p in extras]
        rows += [[("➖", "q:-1"), (f"{item['quantity']} шт.", "_"), ("➕", "q:1")],
                 [(f"✅ Добавить · {money(total)}", "ok")],
                 [("↩️ Назад", back)] + ([("📏 Размер", "z:0")] if sizes else [])]
    try:
        await cb.message.edit_caption(caption=caption, reply_markup=inline(rows))
    except TelegramBadRequest as error:
        if "not modified" not in str(error):
            raise


@guest_router.callback_query(F.data.startswith("a:"))
async def add_start(cb: CallbackQuery, state: FSMContext):
    _, cat, idx, dish_id = cb.data.split(":")
    await state.update_data(item={"dish_id": int(dish_id), "size_id": None, "extra_ids": [], "quantity": 1, "cat": int(cat), "idx": int(idx)})
    await config_screen(cb, state)
    await cb.answer()


async def change_item(cb: CallbackQuery, state: FSMContext, change):
    """Поменять выбор и перерисовать подпись."""
    data = await state.get_data()
    if not data.get("item"):
        return await cb.answer("Выберите блюдо заново.", show_alert=True)
    change(data["item"])
    await state.update_data(item=data["item"])
    await config_screen(cb, state)
    await cb.answer()


@guest_router.callback_query(F.data.startswith("z:"))
async def pick_size(cb: CallbackQuery, state: FSMContext):
    size_id = int(cb.data[2:]) or None                        # z:0 — выбрать размер заново
    await change_item(cb, state, lambda item: item.update(size_id=size_id))


@guest_router.callback_query(F.data.startswith("x:"))
async def toggle_extra(cb: CallbackQuery, state: FSMContext):
    eid = int(cb.data[2:])
    await change_item(cb, state, lambda item: item["extra_ids"].remove(eid) if eid in item["extra_ids"] else item["extra_ids"].append(eid))


@guest_router.callback_query(F.data.startswith("q:"))
async def change_qty(cb: CallbackQuery, state: FSMContext):
    step = int(cb.data[2:])
    await change_item(cb, state, lambda item: item.update(quantity=max(1, min(50, item["quantity"] + step))))


@guest_router.callback_query(F.data == "ok")
async def add_to_cart(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    item = data.pop("item", None)
    if not item:
        return await cb.answer()
    cat, idx = item.pop("cat"), item.pop("idx")
    data["cart"] = data.get("cart", []) + [item]
    await state.set_data(data)
    await cb.answer("Добавлено в корзину ✅")
    await dish_screen(cb, state, cat, idx)                    # снова карточка блюда (счётчик корзины обновился)


# ===== Корзина «по одному товару»: фото, 🗑 / ➖ / ➕, ◀️ ▶️ — в том же сообщении =====

async def cart_screen(event, state: FSMContext, index: int = 0, here=True):
    data = await state.get_data()
    bid, cart = data.get("branch"), data.get("cart", [])
    if not bid:
        return await home(event, state, here=here)
    page = await sync_to_async(gs.cart_page)(bid, cart, index)
    if page is None:                                          # пусто — картинка «Корзина пуста», вид экрана не меняется
        photo = BufferedInputFile(gs.placeholder_photo("Корзина пуста"), filename="cart.jpg")
        return await screen(event, state, "🛒 <b>Корзина пуста</b>\nВыберите блюда в меню.",
                            [[("🍽 Меню", "m"), ("↩️ Главная", "h")]], photo, "ph:cart-empty", here=here)
    i, total = page["index"], page["total"]
    rows = [[("🗑 Удалить", f"cd:{i}"), ("➖", f"ci:{i}:-1"), ("➕", f"ci:{i}:1")]]
    if total > 1:
        rows.append([("◀️", f"cp:{i - 1}"), (f"{i + 1} / {total}", "_"), ("▶️", f"cp:{i + 1}")])
    if data.get("table"):                                    # за столом — «в зале» или «с собой»
        rows.append([("🍽 В зале", "k:hall"), ("🥡 С собой", "k:takeaway")])
    else:
        rows.append([("🚚 Доставка", "k:delivery"), ("🏃 Самовывоз", "k:pickup")])
    rows.append([("🍽 Меню", "m"), ("↩️ Главная", "h")])
    photo, key = photo_of(page)
    await screen(event, state, page["caption"], rows, photo, key, here=here)


@guest_router.callback_query(F.data == "c")
async def cart(cb: CallbackQuery, state: FSMContext):
    await state.set_state(None)
    await cart_screen(cb, state)
    await cb.answer()


@guest_router.callback_query(F.data.startswith("cp:"))
async def cart_flip(cb: CallbackQuery, state: FSMContext):
    await cart_screen(cb, state, int(cb.data[3:]))
    await cb.answer()


@guest_router.callback_query(F.data.startswith("ci:"))
async def cart_item(cb: CallbackQuery, state: FSMContext):
    """➖ / ➕ у позиции. ➖ на последней штуке — позиция убирается."""
    _, n, step = cb.data.split(":")
    data = await state.get_data()
    cart, n = data.get("cart", []), int(n)
    if n < len(cart):
        cart[n]["quantity"] = min(50, cart[n]["quantity"] + int(step))
        if cart[n]["quantity"] < 1:
            cart.pop(n)
            n = max(0, n - 1)
        await state.update_data(cart=cart)
    await cart_screen(cb, state, n)
    await cb.answer()


@guest_router.callback_query(F.data.startswith("cd:"))
async def cart_delete(cb: CallbackQuery, state: FSMContext):
    """🗑 Удалить позицию целиком."""
    n = int(cb.data[3:])
    data = await state.get_data()
    cart = data.get("cart", [])
    if n < len(cart):
        cart.pop(n)
        await state.update_data(cart=cart)
    await cart_screen(cb, state, max(0, n - 1))
    await cb.answer("Удалено")


# ===== Оформление: всё в том же сообщении, текст гостя сразу удаляется =====

STEPS = {                                                     # шаг: (вопрос, поле, состояние)
    "phone": ("📱 Ваш номер телефона?\nНапишите сообщением, например <code>+996 555 123 456</code>.", Checkout.phone),
    "name": ("👤 Как к вам обращаться?\nНапишите имя сообщением.", Checkout.name),
    "address": ("📍 Адрес доставки?\nУлица, дом, квартира — одним сообщением.", Checkout.address),
}


async def ask(event, state: FSMContext, step: str, error: str = ""):
    """Экран-вопрос + кнопка «Как в прошлый раз», если гость уже заказывал."""
    question, st = STEPS[step]
    await state.set_state(st)
    last = (await state.get_data()).get("last", {}).get(step)
    rows = [[(f"↩️ Как в прошлый раз: {last}"[:60], f"prev:{step}")]] if last else []
    rows.append([("✖️ Отмена", "c")])
    await screen(event, state, (f"❗ {error}\n\n" if error else "") + question, rows)


async def next_step(event, state: FSMContext, step: str, value: str):
    """Сохранить ответ и перейти к следующему шагу."""
    data = await state.get_data()
    order = data.get("co", {})
    order[step] = value
    await state.update_data(co=order)
    if step == "phone":
        return await ask(event, state, "name")
    if step == "name" and order.get("kind") == "delivery":
        return await ask(event, state, "address")
    await state.set_state(None)                               # текстом больше ничего не нужно
    await screen(event, state, "💳 Как будете платить?",
                 [[("💵 Наличные", "p:cash"), ("💳 Картой при получении", "p:card")], [("✖️ Отмена", "c")]])


@guest_router.callback_query(F.data.startswith("k:"))
async def checkout_start(cb: CallbackQuery, state: FSMContext):
    kind = cb.data[2:]
    table = (await state.get_data()).get("table")
    if kind in ("hall", "takeaway"):                          # со стола: телефон и адрес не нужны
        if not table:
            return await cb.answer("Заказ за столом — по кнопке «Заказать в Telegram» на сайте стола.", show_alert=True)
        await state.update_data(co={"kind": kind, "table": table["token"], "payment": "cash"})
        await confirm_screen(cb, state)
        return await cb.answer()
    await state.update_data(co={"kind": kind})
    await ask(cb, state, "phone")
    await cb.answer()


@guest_router.callback_query(F.data.startswith("prev:"))
async def use_previous(cb: CallbackQuery, state: FSMContext):
    step = cb.data[5:]
    value = (await state.get_data()).get("last", {}).get(step, "")
    await next_step(cb, state, step, value)
    await cb.answer()


@guest_router.message(Checkout.phone)
async def phone(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    await drop_user_message(message)                          # номер прочитали — сообщение убрали
    if len(value) < 6 or not any(ch.isdigit() for ch in value):
        return await ask(message, state, "phone", "Это не похоже на номер телефона.")
    await next_step(message, state, "phone", value[:30])


@guest_router.message(Checkout.name)
async def name(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    await drop_user_message(message)
    if not value:
        return await ask(message, state, "name", "Напишите имя текстом.")
    await next_step(message, state, "name", value[:100])


@guest_router.message(Checkout.address)
async def address(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    await drop_user_message(message)
    if len(value) < 5:
        return await ask(message, state, "address", "Адрес слишком короткий.")
    await next_step(message, state, "address", value[:255])


@guest_router.callback_query(F.data.startswith("p:"))
async def payment(cb: CallbackQuery, state: FSMContext):
    co = (await state.get_data()).get("co", {})
    co["payment"] = cb.data[2:]
    await state.update_data(co=co)
    await confirm_screen(cb, state)
    await cb.answer()


async def confirm_screen(cb: CallbackQuery, state: FSMContext):
    """«Всё верно?» — состав, сумма и куда."""
    data = await state.get_data()
    co = data.get("co", {})
    text, total, fee = await sync_to_async(gs.cart_text)(data["branch"], data.get("cart", []))
    lines = [text, ""]
    if co.get("kind") == "delivery":
        lines += [f"Доставка: {money(fee)}", f"Итого: <b>{money(total + fee)}</b>", f"📍 {co.get('address', '')}"]
    elif co.get("kind") in ("hall", "takeaway"):
        label = (data.get("table") or {}).get("label", "")
        lines += [f"{'🍽 В зале' if co['kind'] == 'hall' else '🥡 С собой'} · {label}", f"Итого: <b>{money(total)}</b>",
                  "Официант подойдёт и подтвердит заказ."]
    else:
        lines += ["🏃 Самовывоз", f"Итого: <b>{money(total)}</b>"]
    if co.get("kind") in ("delivery", "pickup"):
        lines += [f"👤 {co.get('name', '')} · {co.get('phone', '')}",
                  "💵 Наличные" if co.get("payment") == "cash" else "💳 Картой при получении"]
    lines += ["", "Всё верно?"]
    await screen(cb, state, "\n".join(lines), [[("✅ Заказать", "y")], [("✏️ Изменить корзину", "c"), ("✖️ Отмена", "h")]])


@guest_router.callback_query(F.data == "y")
async def confirm(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data.get("cart"):
        return await cb.answer("Корзина пуста.", show_alert=True)
    payload = {**data.get("co", {}), "cart": data["cart"]}
    order, error = await sync_to_async(gs.create_bot_order)(data["branch"], cb.message.chat.id, payload)
    if error:
        return await cb.answer(error, show_alert=True)        # экран остаётся — можно исправить
    co = data.get("co", {})
    last = {**data.get("last", {}), **{k: co[k] for k in ("phone", "name", "address") if co.get(k)}}
    text = await sync_to_async(gs.guest_text)(await sync_to_async(lambda: type(order).objects.prefetch_related("items").get(pk=order.pk))())
    message_id = await screen(cb, state, text, STATUS_ROWS)  # экран превратился в статус заказа
    await sync_to_async(gs.register_status)(order.id, cb.message.chat.id, message_id)
    await forget_screen(state)                                # следующий экран — новым сообщением, статус остаётся
    await state.update_data(cart=[], co={}, last=last)
    await cb.answer(f"Заказ №{order.id} принят!")


# ===== Мои заказы и кнопки под статусом =====

async def orders_screen(event, state: FSMContext, here=True):
    text = await sync_to_async(gs.my_orders)(event.message.chat.id if isinstance(event, CallbackQuery) else event.chat.id)
    await screen(event, state, "📦 <b>Мои заказы</b>\n" + text, [[("🍽 Меню", "m"), ("↩️ Главная", "h")]], here=here)


@guest_router.callback_query(F.data == "o")
async def my_orders(cb: CallbackQuery, state: FSMContext):
    await orders_screen(cb, state)
    await cb.answer()


@guest_router.callback_query(F.data == "sm")
async def status_new_order(cb: CallbackQuery, state: FSMContext):
    """«🍽 Новый заказ» под статусом: статус не трогаем, экран — новым сообщением."""
    await home(cb, state, here=False)
    await cb.answer()


@guest_router.callback_query(F.data == "so")
async def status_orders(cb: CallbackQuery, state: FSMContext):
    await orders_screen(cb, state, here=False)
    await cb.answer()


@guest_router.message()
async def other(message: Message, state: FSMContext):
    """Любой другой текст: убираем, экран остаётся (если его нет — показываем главную)."""
    await drop_user_message(message)
    if not (await state.get_data()).get("screen"):
        await home(message, state)


# ===== Статусы заказов гостям =====

async def run_guest_notifier(bot, pause: float = 3.0) -> None:
    """Одно сообщение на заказ: экран после «Заказать» (или новое) — дальше только редактируется."""
    while True:
        try:
            for event in await sync_to_async(gs.guest_pending)():
                chat_id, text, old = await sync_to_async(gs.guest_step)(event)
                message_id = 0
                try:
                    if old:
                        await bot.edit_message_text(text, chat_id=old.chat_id, message_id=old.message_id, reply_markup=inline(STATUS_ROWS))
                        message_id = old.message_id
                    else:
                        message_id = (await bot.send_message(chat_id, text, reply_markup=inline(STATUS_ROWS))).message_id
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
