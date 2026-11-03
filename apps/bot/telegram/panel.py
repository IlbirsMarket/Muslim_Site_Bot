"""
Панель кафе в Telegram-боте сотрудников: всё, что умеет панель на сайте, — на инлайн-кнопках в одном экране.
  Заказы и вызовы · Блюда и категории (размеры, добавки, фото, порядок) · Добавки · Столы, этажи и QR ·
  Сотрудники и роли · Настройки филиала · Отчёты за период и архив.
Каждое действие — запрос к тому же API, что у сайта (apps/bot/panel_api.py): права, проверки и база общие.
Шеф и программист работают с филиалом, выбранным в «Кафе».

Кнопки: callback «P<код>:<параметры>», например «Pi:12» — карточка блюда 12. Коды — в словаре SCREENS ниже.
Ввод текста (название, цена, пароль…): экран-вопрос, сотрудник пишет ответ, сообщение сразу удаляется.
"""

import re                                                     # разбор «30 см 650», «10:00»

from asgiref.sync import sync_to_async                        # Django (база) из асинхронного бота
from aiogram import F, Router                                 # фильтры и набор обработчиков
from aiogram.enums import ChatType                            # только личка
from aiogram.fsm.context import FSMContext                    # что сейчас ждём от сотрудника
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, FSInputFile, Message
from django.core.files.uploadedfile import SimpleUploadedFile  # фото из Telegram → файл для API

from apps.bot import texts                                    # escape, money, staff_by_telegram
from apps.bot.notify import CANCEL_REASONS                    # причины отмены — как в группе
from apps.bot.panel_api import call                           # API панели сайта
from .handlers import branch_title, chosen_branch, screen     # выбранный филиал, «один экран»
from .screen import forget_screen

panel_router = Router()                                       # кнопки «P…» и ответы на вопросы
panel_router.message.filter(F.chat.type == ChatType.PRIVATE)
esc, money = texts.escape, texts.money
CAFE = ("↩️ Кафе", "cf")                                       # назад в разделы кафе


class Panel(StatesGroup):
    """Бот ждёт ответ на вопрос (новое название, цену, фото…)."""
    answer = State()


async def api(user, method, path, data=None, bid=None, multipart=False):
    """Запрос к API сайта от имени сотрудника (в отдельном потоке — база синхронная)."""
    return await sync_to_async(call)(user, method, path, data, bid, multipart)


def two(items) -> list:
    """Кнопки по две в ряд."""
    return [items[i:i + 2] for i in range(0, len(items), 2)]


def yes(value) -> str:
    return "да" if value else "нет"


SCREENS = {}                                                  # код → функция экрана или действия


def code(name):
    """Регистрирует экран / действие под кодом: @code("Pd")."""
    def wrap(fn):
        SCREENS[name] = fn
        return fn
    return wrap


async def go(event, state, user, bid, route: str, note: str = ""):
    """Показать экран по маршруту «Pi:12» (после ввода, удаления и т.п.). note — строка сверху («✅ Сохранено»)."""
    name, *args = route.split(":")
    return await SCREENS[name](event, state, user, bid, *args, note=note)


def head(note: str) -> str:
    """Сообщение сверху экрана: «✅ Сохранено» / «❌ …»."""
    return f"{note}\n\n" if note else ""


@panel_router.callback_query(F.data.startswith("P"))
async def panel_button(cb: CallbackQuery, state: FSMContext):
    """Все кнопки панели: найти сотрудника и филиал, выполнить экран / действие, ответить на нажатие."""
    user = await sync_to_async(texts.staff_by_telegram)(cb.from_user.id)
    if user is None:
        return await cb.answer("Сначала войдите: /start → «Войти как сотрудник».", show_alert=True)
    name, *args = cb.data.split(":")
    fn = SCREENS.get(name)
    if fn is None:
        return await cb.answer()
    await state.set_state(None)                               # нажали кнопку — вопрос (если был) отменён
    bid = await chosen_branch(state, user)
    toast = await fn(cb, state, user, bid, *args)
    try:
        await cb.answer(toast or None, show_alert=bool(toast and toast.startswith("❌")))
    except Exception:                                        # на нажатие уже ответили (или оно устарело)
        pass


# ===== Вопросы: экран с вопросом → ответ сотрудника (текст или фото) =====

async def ask(event, state, prompt: str, back: str, spec: dict, extra_rows=()):
    """Задать вопрос. spec — что делать с ответом (см. answer); back — куда вернуться по «Отмена»."""
    await state.set_state(Panel.answer)
    await state.update_data(ask={**spec, "prompt": prompt, "back": back, "extra": [list(map(list, r)) for r in extra_rows]})
    await screen(event, state, prompt, list(extra_rows) + [[("✖️ Отмена", back)]])


@panel_router.message(Panel.answer)
async def answer(message: Message, state: FSMContext):
    """Ответ на вопрос: сообщение сразу удаляем (в нём может быть пароль), применяем, показываем результат."""
    from .screen import drop_user_message
    await drop_user_message(message)
    spec = (await state.get_data()).get("ask") or {}
    user = await sync_to_async(texts.staff_by_telegram)(message.from_user.id)
    if user is None or not spec:
        return await state.set_state(None)
    bid = await chosen_branch(state, user)
    handler = ANSWERS[spec["do"]]
    if spec.get("photo"):                                     # ждём фото
        value = await photo_file(message)
        if value is None:
            return await screen(message, state, "❌ Пришлите фото (картинкой или файлом JPG / PNG).\n\n" + spec["prompt"],
                                spec["extra"] + [[("✖️ Отмена", spec["back"])]])
    else:
        value = (message.text or "").strip()
        if not value:
            return await screen(message, state, "❌ Напишите ответ текстом.\n\n" + spec["prompt"], spec["extra"] + [[("✖️ Отмена", spec["back"])]])
    result = await handler(message, state, user, bid, spec, value)
    if isinstance(result, str) and result.startswith("❌"):   # ошибка — спрашиваем ещё раз
        return await screen(message, state, f"{result}\n\n{spec['prompt']}", spec["extra"] + [[("✖️ Отмена", spec["back"])]])
    if isinstance(result, tuple) and result[0] == "ask":     # следующий вопрос (мастер из нескольких шагов)
        return
    await state.set_state(None)
    route, note = result if isinstance(result, tuple) else (spec["back"], result or "✅ Сохранено")
    await go(message, state, user, bid, route, note)


async def photo_file(message: Message):
    """Фото из сообщения → файл для API (или None, если это не картинка)."""
    if message.photo:
        file_id, name = message.photo[-1].file_id, "photo.jpg"          # самое большое из размеров Telegram
    elif message.document and (message.document.mime_type or "").startswith("image/"):
        file_id, name = message.document.file_id, message.document.file_name or "photo.jpg"
    else:
        return None
    data = await message.bot.download(file_id)
    return SimpleUploadedFile(name, data.read(), content_type="image/jpeg" if name.endswith(".jpg") else "")


ANSWERS = {}


def answers(name):
    def wrap(fn):
        ANSWERS[name] = fn
        return fn
    return wrap


async def confirm(event, state, text: str, yes_route: str, no_route: str):
    """«Точно удалить?» — две кнопки."""
    await screen(event, state, f"⚠️ {text}", [[("✅ Да", yes_route), ("✖️ Отмена", no_route)]])


async def send_file(event, state, user, bid, result, filename: str, caption: str, back: str):
    """PNG / PDF из API — файлом в чат (его можно сохранить и распечатать), экран — снова под ним."""
    msg = event.message if isinstance(event, CallbackQuery) else event
    if not result.ok:
        return f"❌ {result.error}"
    file = BufferedInputFile(result.content, filename=filename)
    await msg.bot.send_document(msg.chat.id, file, caption=caption)   # файлом — без сжатия, QR чёткий для печати
    data = await state.get_data()
    from .screen import delete
    await delete(msg.bot, msg.chat.id, data.get("screen"))   # старый экран убираем — новый появится под файлом
    await forget_screen(state)
    await go(msg, state, user, bid, back)
    return "Готово 👇"


# ===== Правка одного поля: «Pe:<что>:<id>:<поле>» =====

OBJ = {                                                        # что → (адрес API, экран после правки)
    "cat": ("/admin/categories/{}/", "Pc:{}"),
    "dish": ("/admin/dishes/{}/", "Pi:{}"),
    "size": ("/admin/sizes/{}/", "Pz1:{}"),
    "extra": ("/admin/extras/{}/", "Pxe:{}"),
    "table": ("/admin/tables/{}/", "Ptt:{}"),
    "staff": ("/admin/staff/{}/", "Pu1:{}"),
    "cafe": ("/admin/cafe/", "Ps"),
}
FIELDS = {                                                     # поле → (вопрос, тип ответа)
    "name": ("Новое название", "text"),
    "price": ("Цена в сомах (только число)", "int"),
    "description": ("Описание (состав). «-» — без описания", "opt"),
    "number": ("Номер стола (число)", "int"),
    "first_name": ("Имя", "text"),
    "last_name": ("Фамилия. «-» — без фамилии", "opt"),
    "username": ("Логин для входа", "text"),
    "phone": ("Телефон. «-» — без телефона", "opt"),
    "email": ("Email. «-» — без email", "opt"),
    "telegram_id": ("Telegram ID (число). «-» — отвязать", "tgid"),
    "opens_at": ("Время открытия, например 10:00", "time"),
    "closes_at": ("Время закрытия, например 23:00", "time"),
    "delivery_fee": ("Стоимость доставки, сом", "int"),
    "delivery_min_sum": ("Минимальная сумма доставки, сом", "int"),
    "free_delivery_from": ("Бесплатная доставка от, сом (0 — нет)", "int"),
    "delivery_time": ("Время доставки текстом, например «40–60 минут»", "text"),
    "address": ("Адрес кафе. «-» — пусто", "opt"),
    "branch_name": ("Название филиала", "text"),
}


def parse(kind: str, value: str):
    """Текст сотрудника → значение для API. Ошибка — ValueError с понятным текстом."""
    if kind == "int":
        digits = re.sub(r"[\s_]", "", value).replace("сом", "")
        if not digits.isdigit():
            raise ValueError("Нужно число, например 450.")
        return int(digits)
    if kind == "time":
        match = re.fullmatch(r"(\d{1,2})[:.](\d{2})", value)
        if not match or int(match[1]) > 23 or int(match[2]) > 59:
            raise ValueError("Время в виде ЧЧ:ММ, например 10:00.")
        return f"{int(match[1]):02d}:{match[2]}"
    if kind == "tgid":
        if value in ("-", "—"):
            return None
        if not value.isdigit():
            raise ValueError("Telegram ID — только цифры (его покажет бот после входа).")
        return int(value)
    if kind == "opt":
        return "" if value in ("-", "—") else value
    return value


@code("Pe")
async def edit_field(event, state, user, bid, obj, pk, field, note=""):
    """Вопрос «новое значение» с текущим значением."""
    path, back = OBJ[obj][0].format(pk), OBJ[obj][1].format(pk)
    result = await api(user, "get", path, bid=bid)
    if not result.ok:
        return f"❌ {result.error}"
    label, _ = FIELDS[field]
    now = result.data.get(field)
    now = "—" if now in (None, "") else esc(str(now))[:300]
    await ask(event, state, f"✏️ <b>{label}</b>\nСейчас: {now}\n\nНапишите новое значение:", back,
              {"do": "field", "obj": obj, "pk": pk, "field": field})


@answers("field")
async def save_field(message, state, user, bid, spec, value):
    try:
        value = parse(FIELDS[spec["field"]][1], value)
    except ValueError as error:
        return f"❌ {error}"
    result = await api(user, "patch", OBJ[spec["obj"]][0].format(spec["pk"]), {spec["field"]: value}, bid)
    return None if result.ok else f"❌ {result.error}"


# ===================================================================
#  ЗАКАЗЫ И ВЫЗОВЫ
# ===================================================================

def order_title(o) -> str:
    """№12 · Стол 3 · Новый."""
    where = o.get("table_name") if o["kind"] in ("hall", "takeaway") and o.get("table_name") else o["kind_display"]
    return f"№{o['number']} · {where} · {o['status_label']}"


@code("Po")
async def orders(event, state, user, bid, note=""):
    """Заказы в работе (каждая роль видит свои — как на сайте) и вызовы со столов."""
    result = await api(user, "get", "/staff/orders/?active=true", bid=bid)
    if not result.ok:
        return f"❌ {result.error}"
    items = list(result.data)[:30]
    rows = [[(order_title(o), f"Po1:{o['id']}")] for o in items]
    calls = []
    if user.is_waiter or user.is_cafe_admin:
        got = await api(user, "get", "/staff/table-calls/", bid=bid)
        calls = list(got.data) if got.ok else []
        rows += [[(f"🔔 {c['table_name']}: {c['kind_display']} — подошёл", f"Pk:{c['id']}")] for c in calls]
    text = f"🧾 <b>Заказы в работе</b> · {await branch_title(bid)}\n"
    text += f"Заказов: {len(items)}" + (f" · вызовов: {len(calls)}" if calls else "") if items or calls else "Сейчас нет заказов в работе."
    await screen(event, state, head(note) + text, rows + [[("🔄 Обновить", "Po"), CAFE]])


@code("Po1")
async def order_card(event, state, user, bid, pk, note=""):
    """Карточка заказа с кнопками статуса (те же, что на сайте)."""
    from apps.bot.notify import order_text
    from apps.orders.models import Order
    result = await api(user, "get", f"/staff/orders/{pk}/", bid=bid)
    if not result.ok:
        return await orders(event, state, user, bid, note=f"❌ {result.error}")
    order = await sync_to_async(lambda: Order.objects.select_related("table", "claimed_by").prefetch_related("items").get(pk=pk))()
    text = await sync_to_async(order_text)(order)
    actions = [(a["label"], f"Pa:{pk}:{a['action']}") for a in result.data.get("available_actions", [])]
    await screen(event, state, head(note) + text, two(actions) + [[("🔄 Обновить", f"Po1:{pk}"), ("↩️ Заказы", "Po")]])


@code("Pa")
async def order_do(event, state, user, bid, pk, action, note=""):
    """Кнопка статуса заказа. «Отменить» — сначала причина."""
    if action == "cancel":
        rows = [[(r, f"Pr:{pk}:{i}")] for i, r in enumerate(CANCEL_REASONS)] + [[("↩️ Назад", f"Po1:{pk}")]]
        return await screen(event, state, f"❌ Отмена заказа №{pk}\nВыберите причину:", rows)
    if action == "claim":
        result = await api(user, "post", f"/staff/orders/{pk}/claim/", bid=bid)
    else:
        result = await api(user, "post", f"/staff/orders/{pk}/status/", {"action": action}, bid)
    await order_card(event, state, user, bid, pk, note="✅ Готово" if result.ok else f"❌ {result.error}")
    return None if result.ok else f"❌ {result.error}"


@code("Pr")
async def order_cancel(event, state, user, bid, pk, index, note=""):
    result = await api(user, "post", f"/staff/orders/{pk}/status/", {"action": "cancel", "reason": CANCEL_REASONS[int(index)]}, bid)
    await order_card(event, state, user, bid, pk, note="✅ Заказ отменён" if result.ok else f"❌ {result.error}")


@code("Pk")
async def call_done(event, state, user, bid, pk, note=""):
    """«Подошёл(ла)» к столу."""
    result = await api(user, "post", f"/staff/table-calls/{pk}/done/", bid=bid)
    await orders(event, state, user, bid, note="✅ Вызов закрыт" if result.ok else f"❌ {result.error}")


# ===================================================================
#  БЛЮДА И КАТЕГОРИИ
# ===================================================================

async def categories_list(user, bid):
    result = await api(user, "get", "/admin/categories/", bid=bid)
    return list(result.data) if result.ok else []


@code("Pd")
async def categories(event, state, user, bid, note=""):
    if not user.is_cafe_admin:                                 # как на сайте: редактор меню — админ и выше
        return "❌ Нет прав: редактор меню — для админа и шефа."
    cats = await categories_list(user, bid)
    rows = [[(("" if c["is_active"] else "🙈 ") + f"{c['name']} · {c['dishes_count']}", f"Pc:{c['id']}")] for c in cats]
    text = f"🍽 <b>Блюда и категории</b> · {await branch_title(bid)}\n" + ("Выберите категорию (🙈 — скрыта от гостей):" if cats else "Категорий пока нет.")
    await screen(event, state, head(note) + text, rows + [[("➕ Категория", "Pnc")], [CAFE]])


def price_text(d) -> str:
    """Цена блюда или цены размеров."""
    if d.get("sizes"):
        return " / ".join(f"{esc(s['name'])} {money(s['price'])}" for s in d["sizes"])
    return money(d.get("price") or 0)


@code("Pc")
async def category(event, state, user, bid, pk, note=""):
    cats = await categories_list(user, bid)
    cat = next((c for c in cats if str(c["id"]) == str(pk)), None)
    if cat is None:
        return await categories(event, state, user, bid, note="❌ Категория не найдена — возможно, уже удалена.")
    got = await api(user, "get", f"/admin/dishes/?category={pk}", bid=bid)
    dishes = list(got.data) if got.ok else []
    rows = [[(("✅ " if d["is_available"] else "⛔ ") + ("" if d["is_active"] else "🙈 ") + d["name"], f"Pi:{d['id']}")] for d in dishes]
    text = (f"📂 <b>{esc(cat['name'])}</b>\nБлюд: {len(dishes)} · {'видна гостям' if cat['is_active'] else '🙈 скрыта от гостей'}\n"
            "✅ есть · ⛔ нет в наличии · 🙈 скрыто")
    rows += [[("➕ Блюдо", f"Pnd:{pk}")],
             [("✏️ Название", f"Pe:cat:{pk}:name"), ("🙈 Скрыть" if cat["is_active"] else "👁 Показать", f"Pcv:{pk}")],
             [("⬆️ Выше", f"Pco:{pk}:-1"), ("⬇️ Ниже", f"Pco:{pk}:1")],
             [("🗑 Удалить категорию", f"Pcd:{pk}")], [("↩️ Категории", "Pd")]]
    await screen(event, state, head(note) + text, rows)


@code("Pcv")
async def category_visible(event, state, user, bid, pk, note=""):
    cats = await categories_list(user, bid)
    cat = next((c for c in cats if str(c["id"]) == str(pk)), None)
    result = await api(user, "patch", f"/admin/categories/{pk}/", {"is_active": not cat["is_active"]}, bid) if cat else None
    await category(event, state, user, bid, pk, note="✅ Сохранено" if result and result.ok else f"❌ {result.error if result else 'Не найдено'}")


@code("Pco")
async def category_move(event, state, user, bid, pk, step, note=""):
    """Поменять порядок категорий в меню гостей (как перетаскивание на сайте)."""
    ids = [c["id"] for c in await categories_list(user, bid)]
    i = next((n for n, x in enumerate(ids) if str(x) == str(pk)), None)
    j = i + int(step) if i is not None else -1
    if i is None or not 0 <= j < len(ids):
        return "Дальше двигать некуда"
    ids[i], ids[j] = ids[j], ids[i]
    result = await api(user, "post", "/admin/categories/reorder/", {"ids": ids}, bid)
    await category(event, state, user, bid, pk, note="✅ Порядок изменён" if result.ok else f"❌ {result.error}")


@code("Pcd")
async def category_delete_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Удалить категорию? Удалить можно только пустую категорию.", f"Pcy:{pk}", f"Pc:{pk}")


@code("Pcy")
async def category_delete(event, state, user, bid, pk, note=""):
    result = await api(user, "delete", f"/admin/categories/{pk}/", bid=bid)
    if result.ok:
        return await categories(event, state, user, bid, note="🗑 Категория удалена")
    await category(event, state, user, bid, pk, note=f"❌ {result.error}")


@code("Pnc")
async def category_new(event, state, user, bid, note=""):
    await ask(event, state, "➕ <b>Новая категория</b>\nНапишите название:", "Pd", {"do": "new_cat"})


@answers("new_cat")
async def category_create(message, state, user, bid, spec, value):
    result = await api(user, "post", "/admin/categories/", {"name": value}, bid)
    return (f"Pc:{result.data['id']}", "✅ Категория добавлена") if result.ok else f"❌ {result.error}"


async def extras_list(user, bid):
    result = await api(user, "get", "/admin/extras/", bid=bid)
    return list(result.data) if result.ok else []


def dish_photo(pk):
    """Фото блюда для Telegram: (файл, ключ) или (None, None)."""
    from apps.menu.models import Dish
    dish = Dish.objects.filter(pk=pk).first()
    if not dish or not dish.photo:
        return None, None
    try:
        path = dish.photo.path
        if path.endswith(".webp"):                             # WebP Telegram показывает плохо — отдаём JPEG
            from core.images import jpeg_bytes
            return BufferedInputFile(jpeg_bytes(path), filename="dish.jpg"), path
        return FSInputFile(path), path
    except (OSError, ValueError):                             # файла нет на диске
        return None, None


@code("Pi")
async def dish(event, state, user, bid, pk, note=""):
    """Карточка блюда: фото, цены, добавки и все кнопки редактора."""
    result = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    if not result.ok:
        return await categories(event, state, user, bid, note=f"❌ {result.error}")
    d = result.data
    names = {e["id"]: e["name"] for e in await extras_list(user, bid)}
    extras = ", ".join(esc(names.get(e, "?")) for e in d.get("extras", [])) or "нет"
    text = (f"🍽 <b>{esc(d['name'])}</b>\n📂 {esc(d['category_name'])}\n💰 {price_text(d)}\n🧩 Добавки: {extras}\n"
            f"{'✅ Есть в наличии' if d['is_available'] else '⛔ Нет в наличии (стоп-лист)'} · "
            f"{'видно гостям' if d['is_active'] else '🙈 скрыто от гостей'}")
    if d.get("description"):
        text += f"\n\n<i>{esc(d['description'])[:500]}</i>"
    rows = [[("✏️ Название", f"Pe:dish:{pk}:name"), ("💰 Цена", f"Pe:dish:{pk}:price")],
            [("📝 Описание", f"Pe:dish:{pk}:description"), ("📷 Фото", f"Pph:{pk}")],
            [("📏 Размеры", f"Pz:{pk}"), ("🧩 Добавки", f"Pdx:{pk}")],
            [("📂 Категория", f"Pdk:{pk}"), ("⛔ В стоп-лист" if d["is_available"] else "✅ Есть в наличии", f"Pda:{pk}")],
            [("🙈 Скрыть" if d["is_active"] else "👁 Показать", f"Pdv:{pk}"), ("🗑 Удалить", f"Pdd:{pk}")],
            [("⬆️ Выше", f"Pdo:{pk}:-1"), ("⬇️ Ниже", f"Pdo:{pk}:1")],
            [(f"↩️ {d['category_name']}", f"Pc:{d['category']}")]]
    photo, key = await sync_to_async(dish_photo)(pk)
    await screen(event, state, (head(note) + text)[:1024], rows, photo, key)


@code("Pda")
async def dish_available(event, state, user, bid, pk, note=""):
    result = await api(user, "post", f"/admin/dishes/{pk}/toggle-available/", bid=bid)
    await dish(event, state, user, bid, pk, note="✅ Сохранено" if result.ok else f"❌ {result.error}")


@code("Pdv")
async def dish_visible(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    result = await api(user, "patch", f"/admin/dishes/{pk}/", {"is_active": not got.data["is_active"]}, bid) if got.ok else got
    await dish(event, state, user, bid, pk, note="✅ Сохранено" if result.ok else f"❌ {result.error}")


@code("Pdo")
async def dish_move(event, state, user, bid, pk, step, note=""):
    got = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    cat = got.data["category"]
    ids = [d["id"] for d in (await api(user, "get", f"/admin/dishes/?category={cat}", bid=bid)).data]
    i = ids.index(int(pk))
    j = i + int(step)
    if not 0 <= j < len(ids):
        return "Дальше двигать некуда"
    ids[i], ids[j] = ids[j], ids[i]
    result = await api(user, "post", "/admin/dishes/reorder/", {"category": cat, "ids": ids}, bid)
    await dish(event, state, user, bid, pk, note="✅ Порядок изменён" if result.ok else f"❌ {result.error}")


@code("Pdk")
async def dish_category(event, state, user, bid, pk, note=""):
    cats = await categories_list(user, bid)
    rows = [[(c["name"], f"Pdkc:{pk}:{c['id']}")] for c in cats] + [[("↩️ Блюдо", f"Pi:{pk}")]]
    await screen(event, state, "📂 В какую категорию перенести блюдо?", rows)


@code("Pdkc")
async def dish_category_set(event, state, user, bid, pk, cat, note=""):
    result = await api(user, "patch", f"/admin/dishes/{pk}/", {"category": int(cat)}, bid)
    await dish(event, state, user, bid, pk, note="✅ Перенесено" if result.ok else f"❌ {result.error}")


@code("Pdx")
async def dish_extras(event, state, user, bid, pk, note=""):
    """Добавки блюда: нажатие включает / выключает."""
    got = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    chosen = set(got.data.get("extras", []))
    extras = await extras_list(user, bid)
    rows = [[(("✅ " if e["id"] in chosen else "▫️ ") + f"{e['name']} +{e['price']}", f"Pdxt:{pk}:{e['id']}")] for e in extras]
    text = f"🧩 <b>Добавки к «{esc(got.data['name'])}»</b>\nНажмите, чтобы включить ✅ или выключить ▫️." if extras else "Добавок пока нет — создайте их в разделе «🧩 Добавки»."
    await screen(event, state, head(note) + text, rows + [[("↩️ Блюдо", f"Pi:{pk}")]])


@code("Pdxt")
async def dish_extra_toggle(event, state, user, bid, pk, extra, note=""):
    got = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    chosen = set(got.data.get("extras", []))
    chosen ^= {int(extra)}                                     # было — убираем, не было — добавляем
    result = await api(user, "patch", f"/admin/dishes/{pk}/", {"extras": sorted(chosen)}, bid)
    await dish_extras(event, state, user, bid, pk, note="" if result.ok else f"❌ {result.error}")


@code("Pdd")
async def dish_delete_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Удалить блюдо? Заказы с ним останутся в истории.", f"Pdy:{pk}", f"Pi:{pk}")


@code("Pdy")
async def dish_delete(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    result = await api(user, "delete", f"/admin/dishes/{pk}/", bid=bid)
    if result.ok and got.ok:
        return await category(event, state, user, bid, got.data["category"], note="🗑 Блюдо удалено")
    await categories(event, state, user, bid, note=f"❌ {result.error}")


@code("Pnd")
async def dish_new(event, state, user, bid, cat, note=""):
    await ask(event, state, "➕ <b>Новое блюдо</b>\nШаг 1 из 2. Напишите название:", f"Pc:{cat}", {"do": "new_dish", "cat": cat})


@answers("new_dish")
async def dish_new_name(message, state, user, bid, spec, value):
    """Шаг 1 — название, шаг 2 — цена; потом блюдо создаётся, фото и остальное — в карточке."""
    if "name" not in spec:
        await ask(message, state, f"➕ <b>{esc(value)}</b>\nШаг 2 из 2. Цена в сомах (если будут размеры — напишите 0):",
                  f"Pc:{spec['cat']}", {"do": "new_dish", "cat": spec["cat"], "name": value})
        return ("ask",)
    try:
        price = parse("int", value)
    except ValueError as error:
        return f"❌ {error}"
    result = await api(user, "post", "/admin/dishes/", {"category": int(spec["cat"]), "name": spec["name"], "price": price}, bid)
    return (f"Pi:{result.data['id']}", "✅ Блюдо добавлено. Добавьте фото кнопкой «📷 Фото».") if result.ok else f"❌ {result.error}"


@code("Pph")
async def dish_photo_ask(event, state, user, bid, pk, note=""):
    await ask(event, state, "📷 <b>Фото блюда</b>\nПришлите фото (картинкой или файлом), до 3,5 МБ.", f"Pi:{pk}",
              {"do": "photo", "pk": pk, "photo": True})


@answers("photo")
async def dish_photo_save(message, state, user, bid, spec, value):
    result = await api(user, "patch", f"/admin/dishes/{spec['pk']}/", {"photo": value}, bid, multipart=True)
    return (f"Pi:{spec['pk']}", "✅ Фото обновлено") if result.ok else f"❌ {result.error}"


# ----- Размеры блюда -----

@code("Pz")
async def sizes(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    rows = [[(f"{s['name']} — {money(s['price'])}", f"Pz1:{s['id']}")] for s in got.data.get("sizes", [])]
    text = (f"📏 <b>Размеры «{esc(got.data['name'])}»</b>\n"
            + ("Гость выбирает размер, цена берётся из размера." if rows else "Размеров нет — у блюда одна цена."))
    await screen(event, state, head(note) + text, rows + [[("➕ Размер", f"Pnz:{pk}")], [("↩️ Блюдо", f"Pi:{pk}")]])


@code("Pz1")
async def size(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/sizes/{pk}/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    s = got.data
    rows = [[("✏️ Название", f"Pe:size:{pk}:name"), ("💰 Цена", f"Pe:size:{pk}:price")],
            [("🗑 Удалить размер", f"Pzd:{pk}")], [("↩️ Размеры", f"Pz:{s['dish']}")]]
    await screen(event, state, head(note) + f"📏 <b>{esc(s['name'])}</b> — {money(s['price'])}", rows)


@code("Pzd")
async def size_delete_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Удалить размер?", f"Pzy:{pk}", f"Pz1:{pk}")


@code("Pzy")
async def size_delete(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/sizes/{pk}/", bid=bid)
    result = await api(user, "delete", f"/admin/sizes/{pk}/", bid=bid)
    if got.ok:
        return await sizes(event, state, user, bid, got.data["dish"], note="🗑 Размер удалён" if result.ok else f"❌ {result.error}")
    return f"❌ {got.error}"


@code("Pnz")
async def size_new(event, state, user, bid, pk, note=""):
    await ask(event, state, "➕ <b>Новый размер</b>\nНапишите название и цену, например: <code>30 см 650</code>", f"Pz:{pk}",
              {"do": "new_size", "dish": pk})


def name_and_price(value: str):
    """«30 см 650» → («30 см», 650). Ошибка — ValueError."""
    match = re.fullmatch(r"(.+?)\s*[—–-]?\s*(\d[\d\s]*)\s*(сом)?", value.strip())
    if not match or not match[1].strip():
        raise ValueError("Напишите название и цену через пробел, например: 30 см 650")
    return match[1].strip(), int(re.sub(r"\s", "", match[2]))


@answers("new_size")
async def size_create(message, state, user, bid, spec, value):
    try:
        name, price = name_and_price(value)
    except ValueError as error:
        return f"❌ {error}"
    result = await api(user, "post", "/admin/sizes/", {"dish": int(spec["dish"]), "name": name, "price": price}, bid)
    return (f"Pz:{spec['dish']}", "✅ Размер добавлен") if result.ok else f"❌ {result.error}"


# ===================================================================
#  ДОБАВКИ
# ===================================================================

@code("Px")
async def extras(event, state, user, bid, note=""):
    if not user.is_cafe_admin:
        return "❌ Нет прав: добавки меняет админ или шеф."
    items = await extras_list(user, bid)
    rows = [[(("✅ " if e["is_available"] else "⛔ ") + f"{e['name']} · {money(e['price'])}", f"Pxe:{e['id']}")] for e in items]
    text = f"🧩 <b>Добавки</b> · {await branch_title(bid)}\n" + ("✅ есть · ⛔ нет в наличии" if items else "Добавок пока нет.")
    await screen(event, state, head(note) + text, rows + [[("➕ Добавка", "Pnx")], [CAFE]])


@code("Pxe")
async def extra(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/extras/{pk}/", bid=bid)
    if not got.ok:
        return await extras(event, state, user, bid, note=f"❌ {got.error}")
    e = got.data
    rows = [[("✏️ Название", f"Pe:extra:{pk}:name"), ("💰 Цена", f"Pe:extra:{pk}:price")],
            [("⛔ Нет в наличии" if e["is_available"] else "✅ Есть в наличии", f"Pxa:{pk}"), ("🗑 Удалить", f"Pxd:{pk}")],
            [("↩️ Добавки", "Px")]]
    await screen(event, state, head(note) + f"🧩 <b>{esc(e['name'])}</b> — {money(e['price'])}\n"
                 f"{'✅ Есть в наличии' if e['is_available'] else '⛔ Нет в наличии'}", rows)


@code("Pxa")
async def extra_available(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/extras/{pk}/", bid=bid)
    result = await api(user, "patch", f"/admin/extras/{pk}/", {"is_available": not got.data["is_available"]}, bid) if got.ok else got
    await extra(event, state, user, bid, pk, note="✅ Сохранено" if result.ok else f"❌ {result.error}")


@code("Pxd")
async def extra_delete_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Удалить добавку? Она пропадёт у всех блюд.", f"Pxy:{pk}", f"Pxe:{pk}")


@code("Pxy")
async def extra_delete(event, state, user, bid, pk, note=""):
    result = await api(user, "delete", f"/admin/extras/{pk}/", bid=bid)
    await extras(event, state, user, bid, note="🗑 Добавка удалена" if result.ok else f"❌ {result.error}")


@code("Pnx")
async def extra_new(event, state, user, bid, note=""):
    await ask(event, state, "➕ <b>Новая добавка</b>\nНапишите название и цену, например: <code>Сыр 80</code>", "Px", {"do": "new_extra"})


@answers("new_extra")
async def extra_create(message, state, user, bid, spec, value):
    try:
        name, price = name_and_price(value)
    except ValueError as error:
        return f"❌ {error}"
    result = await api(user, "post", "/admin/extras/", {"name": name, "price": price}, bid)
    return ("Px", "✅ Добавка создана") if result.ok else f"❌ {result.error}"


# ===================================================================
#  СТОЛЫ, ЭТАЖИ И QR
# ===================================================================

async def tables_and_floors(user, bid):
    tables = await api(user, "get", "/admin/tables/", bid=bid)
    floors = await api(user, "get", "/admin/floors/", bid=bid)
    return (list(tables.data) if tables.ok else []), (list(floors.data) if floors.ok else [])


@code("Pt")
async def tables(event, state, user, bid, note=""):
    if not user.is_cafe_admin:
        return "❌ Нет прав: столы и QR — для админа и шефа."
    items, floors = await tables_and_floors(user, bid)
    delivery = next((t for t in items if t["kind"] == "delivery"), None)
    rows = [[("🚚 Доставка (QR)", f"Ptt:{delivery['id']}")]] if delivery else []
    rows += [[(f"{f['number']} этаж · столов: {f['tables_count']}", f"Ptf:{f['number']}") for f in floors[i:i + 2]] for i in range(0, len(floors), 2)]
    rows.append([("➕ Этаж", "Pfa")] + ([("🗑 Последний этаж", f"Pfd:{floors[-1]['id']}")] if floors and floors[-1].get("can_delete") else []))
    rows.append([("📄 Все QR одним PDF", "Ptp")])
    await screen(event, state, head(note) + f"🪑 <b>Столы и QR</b> · {await branch_title(bid)}\nВыберите этаж или «Доставку»:", rows + [[CAFE]])


@code("Ptf")
async def floor(event, state, user, bid, number, note=""):
    items, _ = await tables_and_floors(user, bid)
    hall = sorted((t for t in items if t["kind"] == "hall" and str(t["floor"]) == str(number)), key=lambda t: t["number"] or 0)
    rows = [[(t["name"] + (" · 🍽 занят" if t.get("occupied_since") else ""), f"Ptt:{t['id']}") for t in hall[i:i + 2]] for i in range(0, len(hall), 2)]
    text = f"🪑 <b>{number} этаж</b> · столов: {len(hall)}" + ("" if hall else "\nСтолов пока нет.")
    await screen(event, state, head(note) + text, rows + [[("➕ Стол", f"Pta:{number}")], [("↩️ Этажи", "Pt")]])


@code("Pta")
async def table_add(event, state, user, bid, number, note=""):
    result = await api(user, "post", "/admin/tables/", {"floor": int(number)}, bid)
    if result.ok:
        return await table(event, state, user, bid, result.data["id"], note=f"✅ Добавлен: {esc(result.data['name'])}")
    await floor(event, state, user, bid, number, note=f"❌ {result.error}")


@code("Ptt")
async def table(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/tables/{pk}/", bid=bid)
    if not got.ok:
        return await tables(event, state, user, bid, note=f"❌ {got.error}")
    t = got.data
    delivery = t["kind"] == "delivery"
    text = f"{'🚚' if delivery else '🪑'} <b>{esc(t['name'])}</b>"
    if not delivery:
        text += f"\n{t['floor']} этаж · номер {t['number']}" + (" · 🍽 занят" if t.get("occupied_since") else " · свободен")
        if t.get("active_orders"):
            text += f"\nЗаказов в работе: {t['active_orders']}"
    text += f"\n\nQR ведёт на:\n{esc(t['qr_url'])}"
    if t.get("bot_url"):
        text += f"\n\nQR Telegram-бота:\n{esc(t['bot_url'])}"
    rows = [[("🖼 QR-картинка", f"Ptq:{pk}")] + ([("🤖 QR бота", f"Ptb:{pk}")] if t.get("bot_url") else [])]
    if not delivery:
        rows.append([("✏️ Название", f"Pe:table:{pk}:name"), ("🔢 Номер", f"Pe:table:{pk}:number")])
    rows.append([("🔄 Новый QR", f"Ptr:{pk}")] + ([("🔄 Новый QR бота", f"Ptrb:{pk}")] if delivery and t.get("bot_url") else []))
    if not delivery:
        rows.append([("🗑 Удалить стол", f"Ptd:{pk}")])
    rows.append([("↩️ Этажи", "Pt")] if delivery else [(f"↩️ {t['floor']} этаж", f"Ptf:{t['floor']}")])
    await screen(event, state, head(note) + text, rows)


@code("Ptq")
async def table_qr(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/tables/{pk}/", bid=bid)
    result = await api(user, "get", f"/admin/tables/{pk}/qr/", bid=bid)
    name = got.data["name"] if got.ok else "QR"
    return await send_file(event, state, user, bid, result, f"qr-{pk}.png", f"QR: {name}", f"Ptt:{pk}")


@code("Ptb")
async def table_bot_qr(event, state, user, bid, pk, note=""):
    result = await api(user, "get", f"/admin/tables/{pk}/bot-qr/", bid=bid)
    return await send_file(event, state, user, bid, result, "qr-telegram-bot.png", "QR Telegram-бота", f"Ptt:{pk}")


@code("Ptp")
async def tables_pdf(event, state, user, bid, note=""):
    result = await api(user, "get", "/admin/tables/qr-pdf/", bid=bid)
    return await send_file(event, state, user, bid, result, "qr-codes.pdf", "Все QR одним файлом — для печати", "Pt")


@code("Ptr")
async def table_new_qr_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Сделать новый QR? Старый QR (уже напечатанный) перестанет работать.", f"Ptry:{pk}", f"Ptt:{pk}")


@code("Ptry")
async def table_new_qr(event, state, user, bid, pk, note=""):
    result = await api(user, "post", f"/admin/tables/{pk}/regenerate-qr/", bid=bid)
    await table(event, state, user, bid, pk, note="✅ Новый QR готов — распечатайте его" if result.ok else f"❌ {result.error}")


@code("Ptrb")
async def table_new_bot_qr_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Сделать новый QR бота? Старый QR бота перестанет работать.", f"Ptby:{pk}", f"Ptt:{pk}")


@code("Ptby")
async def table_new_bot_qr(event, state, user, bid, pk, note=""):
    result = await api(user, "post", f"/admin/tables/{pk}/regenerate-bot-qr/", bid=bid)
    await table(event, state, user, bid, pk, note="✅ Новый QR бота готов" if result.ok else f"❌ {result.error}")


@code("Ptd")
async def table_delete_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Удалить стол? Его QR перестанет работать.", f"Ptdy:{pk}", f"Ptt:{pk}")


@code("Ptdy")
async def table_delete(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/tables/{pk}/", bid=bid)
    result = await api(user, "delete", f"/admin/tables/{pk}/", bid=bid)
    if result.ok and got.ok:
        return await floor(event, state, user, bid, got.data["floor"], note="🗑 Стол удалён")
    await table(event, state, user, bid, pk, note=f"❌ {result.error}")


@code("Pfa")
async def floor_add(event, state, user, bid, note=""):
    result = await api(user, "post", "/admin/floors/", bid=bid)
    await tables(event, state, user, bid, note=f"✅ Добавлен {result.data['number']} этаж" if result.ok else f"❌ {result.error}")


@code("Pfd")
async def floor_delete_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Удалить последний этаж? (Только если на нём нет столов.)", f"Pfy:{pk}", "Pt")


@code("Pfy")
async def floor_delete(event, state, user, bid, pk, note=""):
    result = await api(user, "delete", f"/admin/floors/{pk}/", bid=bid)
    await tables(event, state, user, bid, note="🗑 Этаж удалён" if result.ok else f"❌ {result.error}")


# ===================================================================
#  СОТРУДНИКИ И РОЛИ
# ===================================================================

def person(u) -> str:
    return " ".join(x for x in [u.get("first_name"), u.get("last_name")] if x) or u["username"]


@code("Pu")
async def staff_list(event, state, user, bid, note=""):
    got = await api(user, "get", "/admin/staff/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    people = list(got.data)
    rows = [[(("🚫 " if not u["is_active"] else "") + f"{person(u)} · {u['role_display']}", f"Pu1:{u['id']}")] for u in people]
    roles = await api(user, "get", "/admin/staff/roles/", bid=bid)
    if roles.ok and roles.data:
        rows.append([("➕ Сотрудник", "Pun")])
    text = f"👥 <b>Сотрудники</b> · {await branch_title(bid)} · {len(people)}\n🚫 — заблокирован"
    await screen(event, state, head(note) + text, rows + [[CAFE]])


@code("Pu1")
async def staff_card(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/staff/{pk}/", bid=bid)
    if not got.ok:
        return await staff_list(event, state, user, bid, note=f"❌ {got.error}")
    u = got.data
    text = (f"👤 <b>{esc(person(u))}</b> · {esc(u['role_display'])}\n"
            f"Логин: <code>{esc(u['username'])}</code>\n"
            f"Филиал: {esc(u.get('branch_name') or 'все филиалы')}\n"
            f"Телефон: {esc(u.get('phone') or '—')}\nEmail: {esc(u.get('email') or '—')}\n"
            f"Telegram: {'привязан' if u.get('telegram_id') else 'не привязан'}\n"
            f"{'✅ Может входить' if u['is_active'] else '🚫 Заблокирован'}")
    rows = []
    if u.get("can_edit"):
        rows = [[("✏️ Имя", f"Pe:staff:{pk}:first_name"), ("✏️ Фамилия", f"Pe:staff:{pk}:last_name")],
                [("👤 Логин", f"Pe:staff:{pk}:username"), ("📞 Телефон", f"Pe:staff:{pk}:phone")],
                [("✉️ Email", f"Pe:staff:{pk}:email"), ("💬 Telegram ID", f"Pe:staff:{pk}:telegram_id")],
                [("🎭 Роль", f"Pur:{pk}"), ("🔑 Пароль", f"Pup:{pk}")]]
        if user.sees_all_branches() and u["role"] not in ("chef", "programmer"):
            rows.append([("🏢 Перевести в другой филиал", f"Pub:{pk}")])
        rows.append([("🚫 Заблокировать" if u["is_active"] else "✅ Разблокировать", f"Pua:{pk}"), ("🗑 Удалить", f"Pud:{pk}")])
    else:
        text += "\n\nМенять этого сотрудника вы не можете."
    await screen(event, state, head(note) + text, rows + [[("↩️ Сотрудники", "Pu")]])


@code("Pur")
async def staff_role(event, state, user, bid, pk, note=""):
    roles = await api(user, "get", "/admin/staff/roles/", bid=bid)
    rows = [[(r["label"], f"Purs:{pk}:{r['value']}")] for r in (roles.data if roles.ok else [])]
    await screen(event, state, "🎭 Какую роль дать?\nПосле смены роли сотрудник выйдет из панели на всех устройствах.",
                 rows + [[("↩️ Сотрудник", f"Pu1:{pk}")]])


@code("Purs")
async def staff_role_set(event, state, user, bid, pk, role, note=""):
    result = await api(user, "post", f"/admin/staff/{pk}/set-role/", {"role": role}, bid)
    await staff_card(event, state, user, bid, pk, note="✅ Роль изменена" if result.ok else f"❌ {result.error}")


@code("Pub")
async def staff_branch(event, state, user, bid, pk, note=""):
    from apps.cafe.models import Branch
    branches = await sync_to_async(lambda: list(Branch.objects.filter(is_active=True).values_list("id", "name")))()
    rows = [[(f"🏢 {name}", f"Pubs:{pk}:{b}")] for b, name in branches] + [[("↩️ Сотрудник", f"Pu1:{pk}")]]
    await screen(event, state, "🏢 В какой филиал перевести сотрудника?", rows)


@code("Pubs")
async def staff_branch_set(event, state, user, bid, pk, branch, note=""):
    result = await api(user, "patch", f"/admin/staff/{pk}/", {"branch": int(branch)}, bid)
    await staff_list(event, state, user, bid, note="✅ Сотрудник переведён" if result.ok else f"❌ {result.error}")


@code("Pua")
async def staff_active(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/staff/{pk}/", bid=bid)
    result = await api(user, "patch", f"/admin/staff/{pk}/", {"is_active": not got.data["is_active"]}, bid) if got.ok else got
    await staff_card(event, state, user, bid, pk, note="✅ Сохранено" if result.ok else f"❌ {result.error}")


@code("Pud")
async def staff_delete_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Удалить сотрудника навсегда? Он больше не сможет войти. Его заказы останутся в истории.", f"Pudy:{pk}", f"Pu1:{pk}")


@code("Pudy")
async def staff_delete(event, state, user, bid, pk, note=""):
    result = await api(user, "delete", f"/admin/staff/{pk}/", bid=bid)
    await staff_list(event, state, user, bid, note="🗑 Сотрудник удалён" if result.ok else f"❌ {result.error}")


@code("Pup")
async def staff_password(event, state, user, bid, pk, note=""):
    await ask(event, state, "🔑 <b>Новый пароль</b> (не короче 10 символов)\nНапишите пароль — сообщение сразу удалится.",
              f"Pu1:{pk}", {"do": "password", "pk": pk})


@answers("password")
async def staff_password_save(message, state, user, bid, spec, value):
    """Пароль дважды (как на сайте): первый раз запоминаем, второй — сравниваем и сохраняем."""
    if "first" not in spec:
        await ask(message, state, "🔑 Повторите пароль ещё раз:", f"Pu1:{spec['pk']}", {**spec, "first": value})
        return ("ask",)
    if value != spec["first"]:
        await ask(message, state, "❌ Пароли не совпали.\n\n🔑 Напишите новый пароль ещё раз:", f"Pu1:{spec['pk']}", {"do": "password", "pk": spec["pk"]})
        return ("ask",)
    result = await api(user, "post", f"/admin/staff/{spec['pk']}/set-password/", {"password": value}, bid)
    if not result.ok:
        await ask(message, state, f"❌ {esc(result.error)}\n\n🔑 Напишите другой пароль:", f"Pu1:{spec['pk']}", {"do": "password", "pk": spec["pk"]})
        return ("ask",)
    return (f"Pu1:{spec['pk']}", "✅ Пароль изменён. Сотрудник вышел из панели на всех устройствах.")


@code("Pun")
async def staff_new(event, state, user, bid, note=""):
    """Новый сотрудник: роль → имя → логин → пароль."""
    roles = await api(user, "get", "/admin/staff/roles/", bid=bid)
    rows = [[(r["label"], f"Punr:{r['value']}")] for r in (roles.data if roles.ok else [])]
    await screen(event, state, f"➕ <b>Новый сотрудник</b> · {await branch_title(bid)}\nШаг 1 из 4. Какая роль?", rows + [[("✖️ Отмена", "Pu")]])


@code("Punr")
async def staff_new_role(event, state, user, bid, role, note=""):
    await ask(event, state, "➕ <b>Новый сотрудник</b>\nШаг 2 из 4. Имя:", "Pu", {"do": "new_staff", "role": role})


@answers("new_staff")
async def staff_new_step(message, state, user, bid, spec, value):
    if "first_name" not in spec:
        await ask(message, state, "➕ <b>Новый сотрудник</b>\nШаг 3 из 4. Логин для входа (латиницей, без пробелов):", "Pu",
                  {**spec, "first_name": value})
        return ("ask",)
    if "username" not in spec:
        await ask(message, state, "➕ <b>Новый сотрудник</b>\nШаг 4 из 4. Пароль (не короче 10 символов) — сообщение сразу удалится:", "Pu",
                  {**spec, "username": value})
        return ("ask",)
    body = {"role": spec["role"], "first_name": spec["first_name"], "username": spec["username"], "password": value}
    result = await api(user, "post", "/admin/staff/", body, bid)
    if result.ok:
        return (f"Pu1:{result.data['id']}", f"✅ Сотрудник добавлен. Логин: <code>{esc(spec['username'])}</code>. Пароль передайте ему лично.")
    field = next(iter(result.data), "") if isinstance(result.data, dict) else ""
    restart = {"do": "new_staff", "role": spec["role"], "first_name": spec["first_name"]}   # ошибка в логине или пароле — с этого шага
    prompt = "Шаг 3 из 4. Логин для входа:" if field == "username" else "Шаг 4 из 4. Пароль:"
    if field != "username":
        restart["username"] = spec["username"]
    await ask(message, state, f"❌ {esc(result.error)}\n\n➕ <b>Новый сотрудник</b>\n{prompt}", "Pu", restart)
    return ("ask",)


# ===================================================================
#  НАСТРОЙКИ ФИЛИАЛА
# ===================================================================

@code("Ps")
async def settings_screen(event, state, user, bid, note=""):
    got = await api(user, "get", "/admin/cafe/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    c = got.data
    text = (f"⚙️ <b>Настройки</b> · {esc(c.get('branch_name') or '')}\n"
            f"Приём заказов: {'✅ вкл' if c['is_accepting_orders'] else '⛔ выкл'}\n"
            f"Доставка: {'✅ вкл' if c['is_delivery_enabled'] else '⛔ выкл'}\n"
            f"Часы работы: {str(c['opens_at'])[:5]}–{str(c['closes_at'])[:5]}\n"
            f"Доставка: {money(c['delivery_fee'])} · от {money(c['delivery_min_sum'])}"
            + (f" · бесплатно от {money(c['free_delivery_from'])}" if c.get("free_delivery_from") else "") + "\n"
            f"Время доставки: {esc(c.get('delivery_time') or '—')}\n"
            f"Адрес: {esc(c.get('address') or '—')}\nТелефон: {esc(c.get('phone') or '—')}")
    rows = []
    if user.is_chef:                                           # менять может шеф и программист (как на сайте)
        rows = [[("⛔ Остановить приём" if c["is_accepting_orders"] else "✅ Принимать заказы", "Pst:is_accepting_orders"),
                 ("⛔ Выключить доставку" if c["is_delivery_enabled"] else "✅ Включить доставку", "Pst:is_delivery_enabled")],
                [("🕙 Открытие", "Pe:cafe:0:opens_at"), ("🕚 Закрытие", "Pe:cafe:0:closes_at")],
                [("🚚 Цена доставки", "Pe:cafe:0:delivery_fee"), ("🧾 Мин. сумма", "Pe:cafe:0:delivery_min_sum")],
                [("🎁 Бесплатно от", "Pe:cafe:0:free_delivery_from"), ("⏱ Время доставки", "Pe:cafe:0:delivery_time")],
                [("📍 Адрес", "Pe:cafe:0:address"), ("📞 Телефон", "Pe:cafe:0:phone")],
                [("🏷 Название филиала", "Pe:cafe:0:branch_name")]]
    else:
        text += "\n\nМенять настройки может шеф."
    await screen(event, state, head(note) + text, rows + [[CAFE]])


@code("Pst")
async def settings_toggle(event, state, user, bid, field, note=""):
    got = await api(user, "get", "/admin/cafe/", bid=bid)
    result = await api(user, "patch", "/admin/cafe/", {field: not got.data[field]}, bid) if got.ok else got
    await settings_screen(event, state, user, bid, note="✅ Сохранено" if result.ok else f"❌ {result.error}")


# ===================================================================
#  ОТЧЁТЫ ЗА ПЕРИОД (шеф): текущие 45 дней и архив
# ===================================================================

@code("Prp")
async def report_period(event, state, user, bid, note=""):
    result = await api(user, "get", "/admin/reports/period/pdf/", bid=bid)
    return await send_file(event, state, user, bid, result, "otchet-45-dney.pdf", "Отчёт за текущие 45 дней", "rpm_back")


@code("Pra")
async def report_archive(event, state, user, bid, note=""):
    got = await api(user, "get", "/admin/reports/periods/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    rows = [[(f"{p['start_date']} — {p['end_date']} · {money(p['revenue'])}", f"Pra1:{p['id']}")] for p in got.data if p.get("has_pdf")]
    text = "🗂 <b>Архив отчётов</b> (по 45 дней)\nНажмите — пришлю PDF." if rows else "🗂 В архиве пока нет закрытых периодов."
    await screen(event, state, head(note) + text, rows + [[("↩️ Отчёты", "rpm"), CAFE]])


@code("Pra1")
async def report_archive_pdf(event, state, user, bid, pk, note=""):
    result = await api(user, "get", f"/admin/reports/periods/{pk}/pdf/", bid=bid)
    return await send_file(event, state, user, bid, result, f"period-{pk}.pdf", "Отчёт за период", "Pra")


@code("rpm_back")
async def report_menu_again(event, state, user, bid, note=""):
    """После PDF — снова экран «Отчёты» (он живёт в staff.py)."""
    from .handlers import branch_title as title
    rows = [[("📅 За сегодня", f"rp:{bid}")], [("🏢 Оба филиала — сегодня", "rp:all")],
            [("🗓 Период 45 дней (PDF)", "Prp"), ("🗂 Архив периодов", "Pra")], [CAFE]]
    await screen(event, state, head(note) + f"📊 <b>Отчёты</b> · {await title(bid)}", rows)
