"""
Бот сотрудников: события с сайта → сообщения в темы группы филиала.
Синхронная часть (план: куда, какой текст, какие кнопки) проверяется обычными тестами.
Асинхронная часть (run_notifier) только отправляет / редактирует по плану.
"""

import asyncio                                         # пауза между проверками
import logging                                         # ошибки в журнал

from asgiref.sync import sync_to_async                 # база Django из асинхронного бота
from django.utils import timezone                      # текущее время
from html import escape                                # имена — безопасно для HTML

from apps.orders.models import Order
from apps.orders.status_service import ACTIONS, COURIER_STATUSES, at_table
from .models import BotEvent, BotMessage
from .texts import money

log = logging.getLogger(__name__)
S, K, P = Order.Status, Order.Kind, BotMessage.Place   # короткие имена
MAX_ATTEMPTS = 5                                        # после 5 ошибок событие пропускается
KITCHEN_STATUSES = {S.ACCEPTED, S.COOKING, S.READY}     # пока заказ на кухне — он в теме «Кухня»
CANCEL_REASONS = ["Нет продуктов", "Гость отказался", "Ошибка в заказе", "Не дозвонились"]   # причины отмены кнопками


def topic(branch, place):
    """(ID группы, ID темы) филиала для места. Нет группы — (None, None)."""
    if not branch.tg_group_id:                                           # группа не настроена
        return None, None
    thread = getattr(branch, f"tg_topic_{place}", None)
    return branch.tg_group_id, thread if thread and thread > 0 else None   # без темы (или ошибка в ID темы) — общий чат группы


def order_places(order) -> list:
    """В какие темы должен попасть заказ сейчас."""
    places = [P.HALL if order.kind in (K.HALL, K.TAKEAWAY) else P.ADMINS]   # зал — официантам, доставка/самовывоз — админам
    if order.status in KITCHEN_STATUSES:                                 # принят и ещё не готов до конца — кухне
        places.append(P.KITCHEN)
    if order.kind == K.DELIVERY and order.status not in (S.NEW, S.CANCELLED, S.COMPLETED):   # доставка в работе — курьерам
        places.append(P.DELIVERY)
    return places


def order_buttons(order, place) -> list:
    """Кнопки под заказом: [(текст, callback)]. Права проверяются при нажатии."""
    if place == P.KITCHEN:                                               # на кухне — только «Готовится» / «Готов»
        names = ["cook", "ready"]
    elif place == P.DELIVERY:                                            # курьерам — «В пути» / «Доставлен»
        names = ["send", "complete"]
    else:
        names = list(ACTIONS)                                            # в зале и у админов — всё
    buttons = []
    claimable = (at_table(order) and order.status == S.NEW) or (order.kind == K.DELIVERY and order.status in COURIER_STATUSES)
    if claimable and not order.claimed_by_id and place != P.KITCHEN:     # «Беру стол» / «Беру заказ»
        buttons.append(("🙋 Беру стол" if at_table(order) else "🙋 Беру заказ", f"o:{order.id}:claim"))
    for name in names:
        rule = ACTIONS[name]
        if order.status in rule["from"]:                                 # действие подходит к статусу
            if name == "send" and order.kind != K.DELIVERY:              # «В пути» — только доставка
                continue
            label = order.completed_label if name == "complete" else rule["label"]
            buttons.append((label, f"o:{order.id}:{name}"))
    return buttons


def order_text(order) -> str:
    """Текст заказа для группы."""
    icon = {S.NEW: "🆕", S.CANCELLED: "❌", S.COMPLETED: "✅"}.get(order.status, "🍳")
    lines = [f"{icon} <b>Заказ №{order.id}</b> · {order.get_kind_display()}" + (" · Telegram" if order.source == Order.Source.BOT else "")]
    if order.table and order.kind in (K.HALL, K.TAKEAWAY):
        lines.append(f"Стол: {escape(str(order.table))}")
    lines.append(f"Статус: <b>{order.status_label}</b>")
    for item in order.items.all():                                       # позиции
        extra = f" ({escape(item.size_name)})" if getattr(item, "size_name", "") else ""
        lines.append(f"• {escape(item.dish_name)}{extra} × {item.quantity}")
    lines.append(f"Итого: <b>{money(order.total)}</b> · {order.get_payment_method_display()}")
    if order.kind in (K.DELIVERY, K.PICKUP):                             # контакты гостя
        lines.append(f"👤 {escape(order.customer_name)} · {escape(order.phone)}")
    if order.kind == K.DELIVERY and order.address:
        addr = ", ".join(x for x in [order.address, order.apartment and f"кв. {order.apartment}",
                                     order.entrance and f"подъезд {order.entrance}", order.floor and f"этаж {order.floor}"] if x)
        lines.append(f"📍 {escape(addr)}")
    if order.comment:
        lines.append(f"💬 {escape(order.comment)}")
    if order.claimed_by_id:                                              # кто взял
        who = order.claimed_by.first_name or order.claimed_by.username
        lines.append(("Курьер: " if order.kind == K.DELIVERY else "Стол взял(а): ") + escape(who))
    if order.status == S.CANCELLED and order.cancel_reason:
        lines.append(f"Причина: {escape(order.cancel_reason)}")
    return "\n".join(lines)


def call_text(call) -> str:
    """Текст вызова со стола."""
    head = f"🔔 <b>{escape(str(call.table))}</b>: {call.get_kind_display()}"
    if call.is_done:                                                     # уже подошли
        who = call.done_by.first_name or call.done_by.username if call.done_by else ""
        return f"✅ {head}\nПодошёл(ла): {escape(who)}"
    return head


def build_plan(event) -> list:
    """
    План для события: список словарей {place, chat_id, thread_id, text, buttons, old}.
    old — BotMessage, который нужно отредактировать (или None — отправить новое).
    """
    plan = []
    if event.order_id:                                                   # заказ
        order = Order.objects.select_related("branch", "table", "claimed_by").prefetch_related("items").get(pk=event.order_id)
        old = {m.place: m for m in order.bot_messages.exclude(place=P.GUEST)}   # уже отправленные сообщения
        places = list(dict.fromkeys(order_places(order) + list(old)))   # нужные + те, где уже было (там обновим)
        text = order_text(order)
        now = order_places(order)
        for place in places:
            if place not in now and place in (P.KITCHEN, P.DELIVERY) and old.get(place):   # ушёл с кухни / доставлен — убираем
                plan.append({"place": place, "delete": True, "old": old[place]})
                continue
            chat, thread = topic(order.branch, place)
            if old.get(place) or chat:                                   # есть куда
                buttons = order_buttons(order, place) if place in order_places(order) else []
                plan.append({"place": place, "chat_id": chat, "thread_id": thread, "text": text, "buttons": buttons, "old": old.get(place)})
    elif event.call_id:                                                  # вызов со стола
        call = event.call
        old = call.bot_messages.filter(place=P.HALL).first()
        chat, thread = topic(call.table.branch, P.HALL)
        if call.is_done and old:                                         # подошли — вызов из «Зала» убираем
            plan.append({"place": P.HALL, "delete": True, "old": old})
        elif chat and not call.is_done:
            buttons = [("✅ Подошёл(ла)", f"c:{call.id}:done")]
            plan.append({"place": P.HALL, "chat_id": chat, "thread_id": thread, "text": call_text(call), "buttons": buttons, "old": old})
    elif event.table_id:                                                 # стол освободили
        chat, thread = topic(event.table.branch, P.HALL)
        if chat:
            plan.append({"place": P.HALL, "chat_id": chat, "thread_id": thread,
                         "text": f"🧹 {escape(str(event.table))} свободен", "buttons": [], "old": None, "once": True})
    return plan


def pending_events(limit=20) -> list:
    """Неотправленные события по порядку."""
    return list(BotEvent.objects.filter(processed_at__isnull=True).select_related("call__table__branch", "table__branch")[:limit])


def save_message(event, step, chat_id, thread_id, message_id) -> None:
    """Запомнить отправленное сообщение — потом его будем редактировать. Удалённое — забыть."""
    if step.get("delete"):
        step["old"].delete()
        return
    if step.get("once"):                                                 # «стол свободен» не редактируется
        return
    BotMessage.objects.update_or_create(
        order_id=event.order_id if event.order_id else None, call_id=None if event.order_id else event.call_id, place=step["place"],
        defaults={"chat_id": chat_id, "thread_id": thread_id, "message_id": message_id},
    )


def mark_done(event, error: str = "") -> None:
    """Событие обработано (или ошибка: +1 попытка, после MAX_ATTEMPTS — пропускаем)."""
    if error:
        event.attempts += 1
        event.last_error = error[:1000]
        if event.attempts >= MAX_ATTEMPTS:
            event.processed_at = timezone.now()
    else:
        event.processed_at = timezone.now()
    event.save(update_fields=["attempts", "last_error", "processed_at"])


def markup(buttons):
    """Кнопки → клавиатура Telegram (по 2 в ряд)."""
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    if not buttons:
        return None
    rows = [[InlineKeyboardButton(text=t, callback_data=d) for t, d in buttons[i:i + 2]] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def deliver(bot, step) -> int:
    """Отправить или отредактировать одно сообщение. Возвращает message_id."""
    from aiogram.exceptions import TelegramBadRequest
    old = step["old"]
    if step.get("delete"):                                               # больше не нужно в этой теме — удаляем
        try:
            await bot.delete_message(old.chat_id, old.message_id)
        except TelegramBadRequest:
            pass                                                         # уже удалено вручную или старше 48 часов
        return old.message_id
    if old:                                                              # уже есть — редактируем
        try:
            await bot.edit_message_text(step["text"], chat_id=old.chat_id, message_id=old.message_id, reply_markup=markup(step["buttons"]))
        except TelegramBadRequest as error:
            if "not modified" not in str(error):                         # «ничего не изменилось» — не ошибка
                raise
        return old.message_id
    sent = await bot.send_message(step["chat_id"], step["text"], message_thread_id=step["thread_id"], reply_markup=markup(step["buttons"]))
    return sent.message_id


async def run_notifier(bot, pause: float = 2.0) -> None:
    """Бесконечный цикл: забрать события → отправить → отметить."""
    while True:
        for event in await sync_to_async(pending_events)():
            try:
                for step in await sync_to_async(build_plan)(event):
                    message_id = await deliver(bot, step)
                    chat = step["old"].chat_id if step["old"] else step["chat_id"]
                    thread = step["old"].thread_id if step["old"] else step.get("thread_id")
                    await sync_to_async(save_message)(event, step, chat, thread, message_id)
                await sync_to_async(mark_done)(event)
            except Exception as error:                                  # сеть, Telegram, база — пробуем позже
                log.exception("Событие %s не отправлено", event.pk)
                await sync_to_async(mark_done)(event, str(error) or error.__class__.__name__)
        await asyncio.sleep(pause)
