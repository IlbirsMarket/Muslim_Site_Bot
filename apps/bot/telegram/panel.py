"""
Панель кафе в Telegram-боте сотрудников — те же разделы, что в меню панели на сайте:
  🧾 Заказы · 🍽 Блюда и категории (категории, блюда, стоп-лист) · 🪑 Столы и QR ·
  👥 Пользователи и роли · 📊 Отчёты · ⚙️ Настройки.
Карточка (блюдо, сотрудник, стол) показывает данные и кнопки «✏️ Изменить» / «🗑 Удалить»;
«✏️ Изменить» открывает список полей, каждое поле — отдельный вопрос.
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


def grid(items, per_row: int) -> list:
    """Кнопки рядами по per_row (вкладки, столы)."""
    return [items[i:i + per_row] for i in range(0, len(items), per_row)]


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
    "table": ("/admin/tables/{}/", "Ptt:{}"),
    "staff": ("/admin/staff/{}/", "Pu1:{}"),
    "cafe": ("/admin/cafe/", "Pset"),
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
#  🧾 ЗАКАЗЫ И ВЫЗОВЫ
# ===================================================================

STATUS_ICON = {"new": "🆕", "accepted": "✅", "cooking": "🍳", "ready": "🛎", "on_the_way": "🚗"}


def order_title(o) -> str:
    """🆕 №12 · Стол 3 · Новый."""
    where = o.get("table_name") if o["kind"] in ("hall", "takeaway") and o.get("table_name") else o["kind_display"]
    return f"{STATUS_ICON.get(o['status'], '🧾')} №{o['number']} · {where} · {o['status_label']}"


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
    text += (f"Заказов: {len(items)}" + (f" · вызовов: {len(calls)}" if calls else "")) if items or calls else "Сейчас нет заказов в работе."
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
#  🍽 БЛЮДА И КАТЕГОРИИ: категории · блюда · стоп-лист
# ===================================================================

PAGE = 8                                                       # блюд на странице


async def categories_list(user, bid):
    result = await api(user, "get", "/admin/categories/", bid=bid)
    return list(result.data) if result.ok else []


async def dishes_list(user, bid, category=0):
    """Блюда филиала (повару тоже можно — для стоп-листа). category=0 — все."""
    result = await api(user, "get", f"/admin/dishes/?category={category}" if int(category) else "/admin/dishes/", bid=bid)
    return list(result.data) if result.ok else []


def short_price(d) -> str:
    """«от 550» для блюда с размерами, иначе «390»."""
    if d.get("sizes"):
        return "от " + str(min(s["price"] for s in d["sizes"]))
    return str(d.get("price") or 0)


def chips(cats, current, route) -> list:
    """Вкладки категорий «Все · Пиццы · …» (выбранная — в точках). route — «Pb:{}:0»."""
    items = [("• Все •" if str(current) == "0" else "Все", route.format(0))]
    items += [(f"• {name} •" if str(cid) == str(current) else name, route.format(cid)) for cid, name in cats]
    return grid(items, 3)


def pages(items, page, route) -> tuple:
    """Срез страницы и ряд «◀️ 1 / 3 ▶️» (если страниц больше одной)."""
    total = max(1, -(-len(items) // PAGE))
    page = int(page) % total
    nav = [[("◀️", route.format(page - 1)), (f"{page + 1} / {total}", "_"), ("▶️", route.format(page + 1))]] if total > 1 else []
    return items[page * PAGE:(page + 1) * PAGE], nav


@code("Pm")
async def menu_hub(event, state, user, bid, note=""):
    """Раздел «Блюда и категории»: Категории · Блюда · Стоп-лист (повар — только стоп-лист)."""
    dishes = await dishes_list(user, bid)
    stopped = sum(1 for d in dishes if not d["is_available"])
    text = f"🍽 <b>Блюда и категории</b> · {await branch_title(bid)}\n"
    if user.is_cafe_admin:
        cats = await categories_list(user, bid)
        text += f"Категорий: {len(cats)} · блюд: {len(dishes)}\n⛔ в стоп-листе: {stopped}"
        rows = [[("📂 Категории", "Pd"), ("🍽 Блюда", "Pb:0:0")], [("🛑 Стоп-лист", "Pso:0:0")]]
    else:
        text += f"Блюд: {len(dishes)} · ⛔ в стоп-листе: {stopped}"
        rows = [[("🛑 Стоп-лист", "Pso:0:0")]]
    await screen(event, state, head(note) + text, rows + [[CAFE]])


# ----- Категории -----

@code("Pd")
async def categories(event, state, user, bid, note=""):
    if not user.is_cafe_admin:                                 # как на сайте: категории меняет админ и выше
        return "❌ Нет прав: категории меняет админ или шеф."
    cats = await categories_list(user, bid)
    rows = [[(("🙈 " if not c["is_active"] else "") + f"{c['name']} · {c['dishes_count']} блюд", f"Pc:{c['id']}")] for c in cats]
    text = f"📂 <b>Категории</b> · {len(cats)}\n" + ("<i>🙈 — скрыта от гостей</i>" if cats else "Категорий пока нет.")
    await screen(event, state, head(note) + text, rows + [[("➕ Добавить категорию", "Pnc")], [("↩️ Блюда и категории", "Pm")]])


@code("Pc")
async def category(event, state, user, bid, pk, note=""):
    cats = await categories_list(user, bid)
    index = next((n for n, c in enumerate(cats) if str(c["id"]) == str(pk)), None)
    if index is None:
        return await categories(event, state, user, bid, note="❌ Категория не найдена — возможно, уже удалена.")
    cat = cats[index]
    text = (f"📂 <b>{esc(cat['name'])}</b>\nБлюд: {cat['dishes_count']} · {'видна гостям' if cat['is_active'] else '🙈 скрыта от гостей'}\n"
            f"В меню: {index + 1}-я по счёту")
    rows = [[("✏️ Изменить", f"Pe:cat:{pk}:name"), ("🗑 Удалить", f"Pcd:{pk}")],
            [("🙈 Скрыть от гостей" if cat["is_active"] else "👁 Показать гостям", f"Pcv:{pk}")],
            [("⬆️ Выше", f"Pco:{pk}:-1"), ("⬇️ Ниже", f"Pco:{pk}:1")],
            [("🍽 Блюда этой категории", f"Pb:{pk}:0")], [("↩️ Категории", "Pd")]]
    await screen(event, state, head(note) + text, rows)


@code("Pcv")
async def category_visible(event, state, user, bid, pk, note=""):
    cats = await categories_list(user, bid)
    cat = next((c for c in cats if str(c["id"]) == str(pk)), None)
    result = await api(user, "patch", f"/admin/categories/{pk}/", {"is_active": not cat["is_active"]}, bid) if cat else None
    await category(event, state, user, bid, pk, note="✅ Сохранено" if result and result.ok else f"❌ {result.error if result else 'Не найдено'}")


@code("Pco")
async def category_move(event, state, user, bid, pk, step, note=""):
    """Порядок категорий в меню гостей (как перетаскивание на сайте)."""
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


# ----- Блюда -----

@code("Pb")
async def dishes(event, state, user, bid, cat="0", page="0", note=""):
    """Все блюда по страницам, сверху — вкладки категорий."""
    if not user.is_cafe_admin:
        return "❌ Нет прав: блюда меняет админ или шеф."
    cats = [(c["id"], c["name"]) for c in await categories_list(user, bid)]
    items = await dishes_list(user, bid, cat)
    chunk, nav = pages(items, page, f"Pb:{cat}:{{}}")
    await state.update_data(dish_back=f"Pb:{cat}:{page}")      # карточка блюда вернётся сюда
    rows = chips(cats, cat, "Pb:{}:0")
    rows += [[(("⛔ " if not d["is_available"] else "✅ ") + ("🙈 " if not d["is_active"] else "") + f"{d['name']} · {short_price(d)}",
               f"Pi:{d['id']}")] for d in chunk]
    text = f"🍽 <b>Блюда</b> · {len(items)}\n<i>✅ есть · ⛔ стоп-лист · 🙈 скрыто</i>" if items else "🍽 <b>Блюда</b>\nЗдесь пока нет блюд."
    add = f"Pnd:{cat}" if str(cat) != "0" else "Pnd0"
    await screen(event, state, head(note) + text, rows + nav + [[("➕ Добавить блюдо", add)], [("↩️ Блюда и категории", "Pm")]])


def price_text(d) -> str:
    """Цена блюда или цены размеров."""
    if d.get("sizes"):
        return " · ".join(f"{esc(s['name'])} {s['price']}" for s in d["sizes"]) + " сом"
    return money(d.get("price") or 0)


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
    """Карточка блюда: фото и данные + «✏️ Изменить», «🗑 Удалить», стоп-лист."""
    result = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    back = (await state.get_data()).get("dish_back") or "Pb:0:0"
    if not result.ok:
        return await dishes(event, state, user, bid, note=f"❌ {result.error}")
    d = result.data
    text = (f"🍽 <b>{esc(d['name'])}</b>\n📂 {esc(d['category_name'])}\n💰 {price_text(d)}\n"
            f"{'✅ Есть в наличии' if d['is_available'] else '⛔ Нет в наличии (стоп-лист)'} · "
            f"{'видно гостям' if d['is_active'] else '🙈 скрыто от гостей'}")
    if d.get("description"):
        text += f"\n\n<i>{esc(d['description'])[:500]}</i>"
    rows = [[("✏️ Изменить", f"Pie:{pk}"), ("🗑 Удалить", f"Pdd:{pk}")],
            [("⛔ В стоп-лист" if d["is_available"] else "✅ Снова в наличии", f"Pda:{pk}")],
            [("↩️ Блюда", back)]]
    photo, key = await sync_to_async(dish_photo)(pk)
    await screen(event, state, (head(note) + text)[:1024], rows, photo, key)


@code("Pie")
async def dish_edit(event, state, user, bid, pk, note=""):
    """«✏️ Изменить» блюдо: что именно."""
    got = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    d = got.data
    rows = [[("🏷 Название", f"Pe:dish:{pk}:name"), ("💰 Цена", f"Pe:dish:{pk}:price")],
            [("📝 Описание", f"Pe:dish:{pk}:description"), ("📷 Фото", f"Pph:{pk}")],
            [("📏 Размеры", f"Pz:{pk}"), ("📂 Категория", f"Pdk:{pk}")],
            [("🙈 Скрыть от гостей" if d["is_active"] else "👁 Показать гостям", f"Pdv:{pk}")],
            [("⬆️ Выше", f"Pdo:{pk}:-1"), ("⬇️ Ниже", f"Pdo:{pk}:1")],
            [("↩️ Блюдо", f"Pi:{pk}")]]
    await screen(event, state, head(note) + f"✏️ <b>{esc(d['name'])}</b> — что изменить?", rows)


@code("Pda")
async def dish_available(event, state, user, bid, pk, note=""):
    result = await api(user, "post", f"/admin/dishes/{pk}/toggle-available/", bid=bid)
    await dish(event, state, user, bid, pk, note="✅ Сохранено" if result.ok else f"❌ {result.error}")


@code("Pdv")
async def dish_visible(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    result = await api(user, "patch", f"/admin/dishes/{pk}/", {"is_active": not got.data["is_active"]}, bid) if got.ok else got
    await dish_edit(event, state, user, bid, pk, note="✅ Сохранено" if result.ok else f"❌ {result.error}")


@code("Pdo")
async def dish_move(event, state, user, bid, pk, step, note=""):
    """Порядок блюда в его категории."""
    got = await api(user, "get", f"/admin/dishes/{pk}/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    cat = got.data["category"]
    ids = [d["id"] for d in await dishes_list(user, bid, cat)]
    i = ids.index(int(pk))
    j = i + int(step)
    if not 0 <= j < len(ids):
        return "Дальше двигать некуда"
    ids[i], ids[j] = ids[j], ids[i]
    result = await api(user, "post", "/admin/dishes/reorder/", {"category": cat, "ids": ids}, bid)
    await dish_edit(event, state, user, bid, pk, note="✅ Порядок изменён" if result.ok else f"❌ {result.error}")


@code("Pdk")
async def dish_category(event, state, user, bid, pk, note=""):
    cats = await categories_list(user, bid)
    rows = [[(c["name"], f"Pdkc:{pk}:{c['id']}")] for c in cats] + [[("↩️ Изменить", f"Pie:{pk}")]]
    await screen(event, state, "📂 В какую категорию перенести блюдо?", rows)


@code("Pdkc")
async def dish_category_set(event, state, user, bid, pk, cat, note=""):
    result = await api(user, "patch", f"/admin/dishes/{pk}/", {"category": int(cat)}, bid)
    await dish(event, state, user, bid, pk, note="✅ Перенесено" if result.ok else f"❌ {result.error}")


@code("Pdd")
async def dish_delete_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Удалить блюдо? Заказы с ним останутся в истории.", f"Pdy:{pk}", f"Pi:{pk}")


@code("Pdy")
async def dish_delete(event, state, user, bid, pk, note=""):
    result = await api(user, "delete", f"/admin/dishes/{pk}/", bid=bid)
    back = (await state.get_data()).get("dish_back") or "Pb:0:0"
    await go(event, state, user, bid, back, note="🗑 Блюдо удалено" if result.ok else f"❌ {result.error}")


@code("Pnd0")
async def dish_new_category(event, state, user, bid, note=""):
    """«➕ Добавить блюдо» из «Все» — сначала категория."""
    cats = await categories_list(user, bid)
    if not cats:
        return "❌ Сначала добавьте категорию."
    rows = [[(c["name"], f"Pnd:{c['id']}")] for c in cats] + [[("✖️ Отмена", "Pb:0:0")]]
    await screen(event, state, "➕ <b>Новое блюдо</b>\nВ какую категорию?", rows)


@code("Pnd")
async def dish_new(event, state, user, bid, cat, note=""):
    await ask(event, state, "➕ <b>Новое блюдо</b>\nШаг 1 из 2. Напишите название:", f"Pb:{cat}:0", {"do": "new_dish", "cat": cat})


@answers("new_dish")
async def dish_new_name(message, state, user, bid, spec, value):
    """Шаг 1 — название, шаг 2 — цена; потом блюдо создаётся, фото и остальное — через «✏️ Изменить»."""
    if "name" not in spec:
        await ask(message, state, f"➕ <b>{esc(value)}</b>\nШаг 2 из 2. Цена в сомах (если будут размеры — напишите 0):",
                  f"Pb:{spec['cat']}:0", {"do": "new_dish", "cat": spec["cat"], "name": value})
        return ("ask",)
    try:
        price = parse("int", value)
    except ValueError as error:
        return f"❌ {error}"
    result = await api(user, "post", "/admin/dishes/", {"category": int(spec["cat"]), "name": spec["name"], "price": price}, bid)
    return (f"Pi:{result.data['id']}", "✅ Блюдо добавлено. Фото — через «✏️ Изменить» → «📷 Фото».") if result.ok else f"❌ {result.error}"


@code("Pph")
async def dish_photo_ask(event, state, user, bid, pk, note=""):
    await ask(event, state, "📷 <b>Фото блюда</b>\nПришлите фото (картинкой или файлом), до 3,5 МБ.", f"Pie:{pk}",
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
    await screen(event, state, head(note) + text, rows + [[("➕ Добавить размер", f"Pnz:{pk}")], [("↩️ Изменить", f"Pie:{pk}")]])


@code("Pz1")
async def size(event, state, user, bid, pk, note=""):
    got = await api(user, "get", f"/admin/sizes/{pk}/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    s = got.data
    rows = [[("🏷 Название", f"Pe:size:{pk}:name"), ("💰 Цена", f"Pe:size:{pk}:price")],
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


# ----- Стоп-лист (админ и повар) -----

@code("Pso")
async def stop_list(event, state, user, bid, cat="0", page="0", note=""):
    """Нажатие на блюдо: ✅ есть ⇄ ⛔ нет. Вкладки категорий — из самих блюд (повару категории не нужны отдельно)."""
    if not (user.is_cook or user.is_cafe_admin):
        return "❌ Нет прав: стоп-лист — для повара и админа."
    every = [d for d in await dishes_list(user, bid) if d["is_active"]]
    cats = list(dict.fromkeys((d["category"], d["category_name"]) for d in every))   # категории по порядку меню
    items = [d for d in every if str(cat) == "0" or str(d["category"]) == str(cat)]
    chunk, nav = pages(items, page, f"Pso:{cat}:{{}}")
    rows = chips(cats, cat, "Pso:{}:0")
    rows += [[(("✅ " if d["is_available"] else "⛔ ") + d["name"], f"Psot:{d['id']}:{cat}:{page}")] for d in chunk]
    text = "🛑 <b>Стоп-лист</b>\nНажмите на блюдо: ✅ есть → ⛔ нет" if items else "🛑 <b>Стоп-лист</b>\nБлюд пока нет."
    await screen(event, state, head(note) + text, rows + nav + [[("↩️ Блюда и категории", "Pm")]])


@code("Psot")
async def stop_toggle(event, state, user, bid, pk, cat, page, note=""):
    result = await api(user, "post", f"/admin/dishes/{pk}/toggle-available/", bid=bid)
    await stop_list(event, state, user, bid, cat, page, note="" if result.ok else f"❌ {result.error}")
    if result.ok:
        return "✅ Есть в наличии" if result.data["is_available"] else "⛔ В стоп-листе"


# ===================================================================
#  🪑 СТОЛЫ И QR (админ — всё; официант — занятые столы и «Освободить»)
# ===================================================================

async def hall_tables(user, bid):
    """(столы, этажи, доставка). Админу — из /admin/tables/ (с QR), официанту — из /staff/tables/."""
    if user.is_cafe_admin:
        got = await api(user, "get", "/admin/tables/", bid=bid)
        floors = await api(user, "get", "/admin/floors/", bid=bid)
        items = list(got.data) if got.ok else []
        delivery = next((t for t in items if t["kind"] == "delivery"), None)
        return [t for t in items if t["kind"] == "hall"], (list(floors.data) if floors.ok else []), delivery
    got = await api(user, "get", "/staff/tables/", bid=bid)
    items = list(got.data) if got.ok else []
    floors = [{"number": n, "id": None, "can_delete": False} for n in sorted({t["floor"] for t in items})] or [{"number": 1, "id": None, "can_delete": False}]
    return items, floors, None


@code("Pt")
async def tables(event, state, user, bid, number="1", note=""):
    """Этаж: вкладки «Доставка · 1 этаж · 2 этаж», столы сеткой 🟢 / 🔴."""
    if not (user.is_waiter or user.is_cafe_admin):
        return "❌ Нет прав: столы — для официанта и админа."
    items, floors, delivery = await hall_tables(user, bid)
    numbers = [f["number"] for f in floors]
    number = int(number) if int(number) in numbers else (numbers[0] if numbers else 1)
    here = sorted((t for t in items if t["floor"] == number), key=lambda t: t["number"] or 0)
    tabs = ([("🚚 Доставка", f"Ptt:{delivery['id']}")] if delivery else [])
    tabs += [(f"• {n} этаж •" if n == number else f"{n} этаж", f"Pt:{n}") for n in numbers]
    cells = [(("🔴 " if t.get("occupied_since") else "🟢 ") + str(t["number"]), f"Ptt:{t['id']}") for t in here]
    busy = sum(1 for t in here if t.get("occupied_since"))
    text = (f"🪑 <b>Столы и QR</b> · {number} этаж\n🟢 свободен · 🔴 занят\n"
            + (f"Занято: {busy} из {len(here)}" if here else "На этом этаже пока нет столов."))
    rows = grid(tabs, 3) + grid(cells, 4)
    if user.is_cafe_admin:
        rows.append([("➕ Стол", f"Pta:{number}"), ("➕ Этаж", "Pfa")])
        last = floors[-1] if floors else None
        if last and last["number"] == number and last.get("can_delete"):
            rows.append([(f"🗑 Удалить {number} этаж", f"Pfd:{last['id']}")])
        rows.append([("📄 Все QR (PDF)", "Ptp")])
    await screen(event, state, head(note) + text, rows + [[CAFE]])


def table_extra(pk):
    """Кто ведёт стол (официант после «Беру стол»)."""
    from apps.tables.models import Table
    t = Table.objects.select_related("waiter").filter(pk=pk).first()
    return (t.waiter.first_name or t.waiter.username) if t and t.waiter_id else ""


@code("Ptt")
async def table(event, state, user, bid, pk, note=""):
    """Карточка стола: занят ли, QR и кнопки."""
    if user.is_cafe_admin:
        got = await api(user, "get", f"/admin/tables/{pk}/", bid=bid)
        t = got.data if got.ok else None
    else:
        items, _, _ = await hall_tables(user, bid)
        t = next((x for x in items if str(x["id"]) == str(pk)), None)
    if not t:
        return await tables(event, state, user, bid, note="❌ Стол не найден — возможно, уже удалён.")
    delivery = t.get("kind") == "delivery"
    busy = bool(t.get("occupied_since"))
    if delivery:
        text = "🚚 <b>Доставка</b>\nQR для заказов на доставку и самовывоз."
    else:
        text = f"{'🔴' if busy else '🟢'} <b>{esc(t['name'])}</b> · {t['floor']} этаж\n"
        if busy:
            since = str(t["occupied_since"])[11:16]
            text += f"Занят с {since}" + (f" · заказов в работе: {t['active_orders']}" if t.get("active_orders") else "")
            waiter = await sync_to_async(table_extra)(pk)
            text += f"\nВедёт: {esc(waiter)}" if waiter else ""
        else:
            text += "Свободен"
    if t.get("qr_url"):
        text += f"\n\nQR ведёт на:\n{esc(t['qr_url'])}"
    rows = [[("🧹 Освободить стол", f"Ptf:{pk}")]] if busy else []
    if user.is_cafe_admin:
        rows.append([("🖼 QR-код", f"Ptq:{pk}"), ("🔄 Новый QR", f"Ptr:{pk}")])
        if delivery and t.get("bot_url"):
            rows.append([("🤖 QR бота", f"Ptb:{pk}"), ("🔄 Новый QR бота", f"Ptrb:{pk}")])
        if not delivery:
            rows.append([("✏️ Изменить", f"Pte:{pk}"), ("🗑 Удалить", f"Ptd:{pk}")])
    rows.append([("↩️ Столы", "Pt:1")] if delivery else [(f"↩️ {t['floor']} этаж", f"Pt:{t['floor']}")])
    await screen(event, state, head(note) + text, rows)


@code("Pte")
async def table_edit(event, state, user, bid, pk, note=""):
    await screen(event, state, "✏️ Что изменить у стола?",
                 [[("🏷 Название", f"Pe:table:{pk}:name"), ("🔢 Номер", f"Pe:table:{pk}:number")], [("↩️ Стол", f"Ptt:{pk}")]])


@code("Ptf")
async def table_free(event, state, user, bid, pk, note=""):
    """«🧹 Освободить стол» — гости ушли (как на сайте)."""
    result = await api(user, "post", f"/staff/tables/{pk}/close-visit/", bid=bid)
    await table(event, state, user, bid, pk, note="✅ Стол свободен" if result.ok else f"❌ {result.error}")


@code("Pta")
async def table_add(event, state, user, bid, number, note=""):
    result = await api(user, "post", "/admin/tables/", {"floor": int(number)}, bid)
    await tables(event, state, user, bid, number, note=f"✅ Добавлен: {esc(result.data['name'])}" if result.ok else f"❌ {result.error}")


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
    return await send_file(event, state, user, bid, result, "qr-codes.pdf", "Все QR одним файлом — для печати", "Pt:1")


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
        return await tables(event, state, user, bid, got.data["floor"], note="🗑 Стол удалён")
    await table(event, state, user, bid, pk, note=f"❌ {result.error}")


@code("Pfa")
async def floor_add(event, state, user, bid, note=""):
    result = await api(user, "post", "/admin/floors/", bid=bid)
    if result.ok:
        return await tables(event, state, user, bid, result.data["number"], note=f"✅ Добавлен {result.data['number']} этаж")
    await tables(event, state, user, bid, note=f"❌ {result.error}")


@code("Pfd")
async def floor_delete_ask(event, state, user, bid, pk, note=""):
    await confirm(event, state, "Удалить этот этаж? (Только если на нём нет столов.)", f"Pfy:{pk}", "Pt:1")


@code("Pfy")
async def floor_delete(event, state, user, bid, pk, note=""):
    result = await api(user, "delete", f"/admin/floors/{pk}/", bid=bid)
    await tables(event, state, user, bid, note="🗑 Этаж удалён" if result.ok else f"❌ {result.error}")


# ===================================================================
#  👥 ПОЛЬЗОВАТЕЛИ И РОЛИ
# ===================================================================

def person(u) -> str:
    return " ".join(x for x in [u.get("first_name"), u.get("last_name")] if x) or u["username"]


@code("Pu")
async def staff_list(event, state, user, bid, role="all", note=""):
    """Сотрудники с вкладками ролей «Все · Админ · Повар …»."""
    got = await api(user, "get", "/admin/staff/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    people = list(got.data)
    roles = list(dict.fromkeys((u["role"], u["role_display"]) for u in people))
    tabs = [("• Все •" if role == "all" else "Все", "Pu:all")] + [(f"• {label} •" if value == role else label, f"Pu:{value}") for value, label in roles]
    shown = [u for u in people if role == "all" or u["role"] == role]
    rows = grid(tabs, 3) + [[(("🚫 " if not u["is_active"] else "") + f"{person(u)} · {u['role_display']}", f"Pu1:{u['id']}")] for u in shown]
    can_add = await api(user, "get", "/admin/staff/roles/", bid=bid)
    if can_add.ok and can_add.data:
        rows.append([("➕ Добавить сотрудника", "Pun")])
    text = f"👥 <b>Пользователи и роли</b> · {await branch_title(bid)} · {len(people)}\n<i>🚫 — заблокирован</i>"
    await screen(event, state, head(note) + text, rows + [[CAFE]])


@code("Pu1")
async def staff_card(event, state, user, bid, pk, note=""):
    """Карточка сотрудника: данные + «✏️ Изменить» и «🗑 Удалить»."""
    got = await api(user, "get", f"/admin/staff/{pk}/", bid=bid)
    if not got.ok:
        return await staff_list(event, state, user, bid, note=f"❌ {got.error}")
    u = got.data
    text = (f"👤 <b>{esc(person(u))}</b> · {esc(u['role_display'])}\n"
            f"Логин: <code>{esc(u['username'])}</code> · {esc(u.get('branch_name') or 'все филиалы')}\n"
            f"Телефон: {esc(u.get('phone') or '—')}\nEmail: {esc(u.get('email') or '—')}\n"
            f"Telegram: {'привязан' if u.get('telegram_id') else 'не привязан'} · "
            f"{'✅ может входить' if u['is_active'] else '🚫 заблокирован'}")
    rows = [[("✏️ Изменить", f"Pue:{pk}"), ("🗑 Удалить", f"Pud:{pk}")]] if u.get("can_edit") else []
    if not u.get("can_edit"):
        text += "\n\n<i>Менять этого сотрудника вы не можете.</i>"
    await screen(event, state, head(note) + text, rows + [[("↩️ Пользователи и роли", "Pu:all")]])


@code("Pue")
async def staff_edit(event, state, user, bid, pk, note=""):
    """«✏️ Изменить» сотрудника: что именно."""
    got = await api(user, "get", f"/admin/staff/{pk}/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    u = got.data
    rows = [[("👤 Имя", f"Pe:staff:{pk}:first_name"), ("👤 Фамилия", f"Pe:staff:{pk}:last_name")],
            [("🔑 Логин", f"Pe:staff:{pk}:username"), ("🔒 Пароль", f"Pup:{pk}")],
            [("📞 Телефон", f"Pe:staff:{pk}:phone"), ("✉️ Email", f"Pe:staff:{pk}:email")],
            [("🎭 Роль", f"Pur:{pk}")] + ([("🏢 Филиал", f"Pub:{pk}")] if user.sees_all_branches() and u["role"] not in ("chef", "programmer") else []),
            [("💬 Telegram ID", f"Pe:staff:{pk}:telegram_id")],
            [("🚫 Заблокировать" if u["is_active"] else "✅ Разблокировать", f"Pua:{pk}")],
            [("↩️ Сотрудник", f"Pu1:{pk}")]]
    await screen(event, state, head(note) + f"✏️ <b>{esc(person(u))}</b> — что изменить?", rows)


@code("Pur")
async def staff_role(event, state, user, bid, pk, note=""):
    roles = await api(user, "get", "/admin/staff/roles/", bid=bid)
    rows = [[(r["label"], f"Purs:{pk}:{r['value']}")] for r in (roles.data if roles.ok else [])]
    await screen(event, state, "🎭 Какую роль дать?\nПосле смены роли сотрудник выйдет из панели на всех устройствах.",
                 rows + [[("↩️ Изменить", f"Pue:{pk}")]])


@code("Purs")
async def staff_role_set(event, state, user, bid, pk, role, note=""):
    result = await api(user, "post", f"/admin/staff/{pk}/set-role/", {"role": role}, bid)
    await staff_card(event, state, user, bid, pk, note="✅ Роль изменена" if result.ok else f"❌ {result.error}")


@code("Pub")
async def staff_branch(event, state, user, bid, pk, note=""):
    from apps.cafe.models import Branch
    branches = await sync_to_async(lambda: list(Branch.objects.filter(is_active=True).values_list("id", "name")))()
    rows = [[(f"🏢 {name}", f"Pubs:{pk}:{b}")] for b, name in branches] + [[("↩️ Изменить", f"Pue:{pk}")]]
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
    await ask(event, state, "🔒 <b>Новый пароль</b> (не короче 10 символов)\nНапишите пароль — сообщение сразу удалится.",
              f"Pue:{pk}", {"do": "password", "pk": pk})


@answers("password")
async def staff_password_save(message, state, user, bid, spec, value):
    """Пароль дважды (как на сайте): первый раз запоминаем, второй — сравниваем и сохраняем."""
    if "first" not in spec:
        await ask(message, state, "🔒 Повторите пароль ещё раз:", f"Pue:{spec['pk']}", {**spec, "first": value})
        return ("ask",)
    if value != spec["first"]:
        await ask(message, state, "❌ Пароли не совпали.\n\n🔒 Напишите новый пароль ещё раз:", f"Pue:{spec['pk']}", {"do": "password", "pk": spec["pk"]})
        return ("ask",)
    result = await api(user, "post", f"/admin/staff/{spec['pk']}/set-password/", {"password": value}, bid)
    if not result.ok:
        await ask(message, state, f"❌ {esc(result.error)}\n\n🔒 Напишите другой пароль:", f"Pue:{spec['pk']}", {"do": "password", "pk": spec["pk"]})
        return ("ask",)
    return (f"Pu1:{spec['pk']}", "✅ Пароль изменён. Сотрудник вышел из панели на всех устройствах.")


@code("Pun")
async def staff_new(event, state, user, bid, note=""):
    """Новый сотрудник: роль → имя → логин → пароль."""
    roles = await api(user, "get", "/admin/staff/roles/", bid=bid)
    rows = [[(r["label"], f"Punr:{r['value']}")] for r in (roles.data if roles.ok else [])]
    await screen(event, state, f"➕ <b>Новый сотрудник</b> · {await branch_title(bid)}\nШаг 1 из 4. Какая роль?", rows + [[("✖️ Отмена", "Pu:all")]])


@code("Punr")
async def staff_new_role(event, state, user, bid, role, note=""):
    await ask(event, state, "➕ <b>Новый сотрудник</b>\nШаг 2 из 4. Имя:", "Pu:all", {"do": "new_staff", "role": role})


@answers("new_staff")
async def staff_new_step(message, state, user, bid, spec, value):
    if "first_name" not in spec:
        await ask(message, state, "➕ <b>Новый сотрудник</b>\nШаг 3 из 4. Логин для входа (латиницей, без пробелов):", "Pu:all",
                  {**spec, "first_name": value})
        return ("ask",)
    if "username" not in spec:
        await ask(message, state, "➕ <b>Новый сотрудник</b>\nШаг 4 из 4. Пароль (не короче 10 символов) — сообщение сразу удалится:", "Pu:all",
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
    await ask(message, state, f"❌ {esc(result.error)}\n\n➕ <b>Новый сотрудник</b>\n{prompt}", "Pu:all", restart)
    return ("ask",)


# ===================================================================
#  ⚙️ НАСТРОЙКИ ФИЛИАЛА (смотреть — админ, менять — шеф)
# ===================================================================

@code("Pset")
async def settings_screen(event, state, user, bid, note=""):
    got = await api(user, "get", "/admin/cafe/", bid=bid)
    if not got.ok:
        return f"❌ {got.error}"
    c = got.data
    text = (f"⚙️ <b>Настройки</b> · {esc(c.get('branch_name') or '')}\n"
            f"Приём заказов: {'✅' if c['is_accepting_orders'] else '⛔'} · Доставка: {'✅' if c['is_delivery_enabled'] else '⛔'}\n"
            f"Часы: {str(c['opens_at'])[:5]}–{str(c['closes_at'])[:5]}\n"
            f"Доставка {money(c['delivery_fee'])} · от {money(c['delivery_min_sum'])}"
            + (f" · бесплатно от {money(c['free_delivery_from'])}" if c.get("free_delivery_from") else "") + "\n"
            f"Время доставки: {esc(c.get('delivery_time') or '—')}\n"
            f"Адрес: {esc(c.get('address') or '—')}\nТелефон: {esc(c.get('phone') or '—')}")
    rows = []
    if user.is_chef:                                           # менять может шеф и программист (как на сайте)
        rows = [[("⛔ Остановить приём" if c["is_accepting_orders"] else "✅ Принимать заказы", "Pst:is_accepting_orders")],
                [("⛔ Выключить доставку" if c["is_delivery_enabled"] else "✅ Включить доставку", "Pst:is_delivery_enabled")],
                [("✏️ Изменить", "Psete")]]
    else:
        text += "\n\n<i>Менять настройки может шеф.</i>"
    await screen(event, state, head(note) + text, rows + [[CAFE]])


@code("Psete")
async def settings_edit(event, state, user, bid, note=""):
    if not user.is_chef:
        return "❌ Менять настройки может шеф."
    rows = [[("🕙 Открытие", "Pe:cafe:0:opens_at"), ("🕚 Закрытие", "Pe:cafe:0:closes_at")],
            [("🚚 Цена доставки", "Pe:cafe:0:delivery_fee"), ("🧾 Мин. сумма", "Pe:cafe:0:delivery_min_sum")],
            [("🎁 Бесплатно от", "Pe:cafe:0:free_delivery_from"), ("⏱ Время доставки", "Pe:cafe:0:delivery_time")],
            [("📍 Адрес", "Pe:cafe:0:address"), ("📞 Телефон", "Pe:cafe:0:phone")],
            [("🏷 Название филиала", "Pe:cafe:0:branch_name")], [("↩️ Настройки", "Pset")]]
    await screen(event, state, head(note) + "✏️ <b>Настройки</b> — что изменить?", rows)


@code("Pst")
async def settings_toggle(event, state, user, bid, field, note=""):
    got = await api(user, "get", "/admin/cafe/", bid=bid)
    result = await api(user, "patch", "/admin/cafe/", {field: not got.data[field]}, bid) if got.ok else got
    await settings_screen(event, state, user, bid, note="✅ Сохранено" if result.ok else f"❌ {result.error}")


# ===================================================================
#  📊 ОТЧЁТЫ ЗА ПЕРИОД (шеф): текущие 45 дней и архив. «За сегодня» — в staff.py («rpm»)
# ===================================================================

@code("Prp")
async def report_period(event, state, user, bid, note=""):
    result = await api(user, "get", "/admin/reports/period/pdf/", bid=bid)
    return await send_file(event, state, user, bid, result, "otchet-45-dney.pdf", "Отчёт за текущие 45 дней", "Prm")


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


@code("Prm")
async def report_menu(event, state, user, bid, note=""):
    """Экран «Отчёты» (тот же, что по кнопке «📊 Отчёты»)."""
    rows = [[("📅 За сегодня", f"rp:{bid}")]]
    if user.sees_all_branches():
        rows += [[("🏢 Оба филиала — сегодня", "rp:all")], [("🗓 45 дней (PDF)", "Prp"), ("🗂 Архив", "Pra")]]
    await screen(event, state, head(note) + f"📊 <b>Отчёты</b> · {await branch_title(bid)}", rows + [[CAFE]])
