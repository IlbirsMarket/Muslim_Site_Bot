"""
Оплата и чеки.
- «К оплате»: неоплаченные заказы; заказы одного стола собираются в один счёт.
- «Оплатить»: отметить оплату (наличные / карта / наличные + карта) и напечатать чек.
- Задания для чекового аппарата: кассовый компьютер забирает их и печатает (сервер принтер не видит).
"""

from datetime import timedelta                                     # промежуток времени

from django.db import transaction                                  # «всё или ничего»
from django.utils import timezone                                  # время по Бишкеку
from rest_framework.exceptions import PermissionDenied, ValidationError   # ошибки 403 и 400

from apps.bot.events import Kind as BotKind, add_event             # событие → панели обновятся сами
from .models import Order, PrintJob, TableCall
from .status_service import at_table, owns_table

UNPAID_HOURS = 24          # «К оплате» показывает заказы за последние сутки (старые не висят вечно)
JOB_HOURS = 6              # задание печати, которое никто не забрал 6 часов, уже не печатаем
THANKS = "ВСЕГДА МЫ РАДЫ ВАМ!!!"   # подпись внизу чека об оплате — как на старом чеке кафе


# ===================== ЧТО ПЕЧАТАТЬ =====================

# Как называть роль на чеке: вместо «Официант:» — роль того, кто обслужил
RECEIPT_ROLES = {"programmer": "Программист", "chef": "Шеф", "admin": "Администратор", "cashier": "Кассир",
                 "waiter": "Официант", "courier": "Курьер", "cook": "Повар"}


def _staff_line(*users) -> dict:
    """Первый, кто есть: {"staff_role": "Официант", "waiter": "Бекзат"} — на чеке «Официант: Бекзат»."""
    user = next((u for u in users if u), None)
    if not user:
        return {"staff_role": "Администратор", "waiter": ""}
    return {"staff_role": RECEIPT_ROLES.get(user.role, "Сотрудник"), "waiter": _person(user)}


def _person(user) -> str:
    """Имя сотрудника для чека."""
    return (user.get_full_name() or user.username) if user else ""


def _place(order) -> str:
    """«Место» на чеке: стол, с собой, доставка или самовывоз."""
    table = str(order.table) if order.table_id else ""
    if order.kind == Order.Kind.HALL:
        return table or "Зал"                                      # «Стол 3 · 1 этаж»
    if order.kind == Order.Kind.TAKEAWAY:
        return "Собой"                                             # как на старом чеке кафе
    return "Доставка" if order.kind == Order.Kind.DELIVERY else "Самовывоз"


def _line(item) -> dict:
    """Одна строка чека: название, размер, добавки, количество, цена, сумма."""
    return {
        "name": item.dish_name + (f" {item.size_name}" if item.size_name else ""),   # «Пицца Пепперони 30 см»
        "extras": [e.get("name", "") for e in (item.extras or [])],                 # «+ сыр, халапеньо»
        "qty": item.quantity,
        "price": item.unit_price,
        "sum": item.unit_price * item.quantity,
    }


def _guest(order) -> dict:
    """Данные гостя — только для доставки и самовывоза (за столом гость и так рядом)."""
    if order.kind not in (Order.Kind.DELIVERY, Order.Kind.PICKUP):
        return {}
    address = ", ".join(x for x in [
        order.address,
        f"кв {order.apartment}" if order.apartment else "",
        f"подъезд {order.entrance}" if order.entrance else "",
        f"этаж {order.floor}" if order.floor else "",
    ] if x)
    return {
        "customer": order.customer_name, "phone": order.phone, "address": address,
        "courier_comment": order.courier_comment,
        "guest_payment": order.get_payment_method_display() + (f", сдача с {order.change_from}" if order.change_from else ""),   # что выбрал гость
    }


def order_payload(order) -> dict:
    """Чек «ЗАКАЗ» — печатается сразу после подтверждения (не чек об оплате)."""
    now = timezone.localtime(order.created_at)
    return {
        "title": "СЧЕТ", "number": order.id, "branch": order.branch.name,
        "date": f"{now:%d.%m.%Y}", "time": f"{now:%H:%M}",
        "place": _place(order), "kind": order.kind,
        "type": {Order.Kind.HALL: "В КАФЕ", Order.Kind.TAKEAWAY: "С СОБОЙ",
                 Order.Kind.DELIVERY: "ДОСТАВКА", Order.Kind.PICKUP: "САМОВЫВОЗ"}.get(order.kind, ""),   # крупно на чеке
        **_staff_line(order.claimed_by, order.accepted_by),           # «Официант: Бекзат» / «Администратор: Азамат»
        "accepted_by": _person(order.accepted_by),
        "takeaway": order.kind == Order.Kind.TAKEAWAY,                       # «УПАКОВАТЬ С СОБОЙ»
        "items": [_line(item) for item in order.items.all()],
        "comment": order.comment,
        "subtotal": order.subtotal, "delivery_fee": order.delivery_fee, "total": order.total,
        "note": "Это не чек об оплате",
        **_guest(order),
    }


def _merged_lines(orders) -> list:
    """Позиции нескольких заказов одним списком: одинаковые блюда складываем («Чай чёрный 3 * 80»)."""
    lines = {}
    for order in orders:
        for item in order.items.all():
            line = _line(item)
            key = (line["name"], tuple(line["extras"]), line["price"])     # то же блюдо, размер, добавки и цена
            if key in lines:
                lines[key]["qty"] += line["qty"]
                lines[key]["sum"] += line["sum"]
            else:
                lines[key] = line
    return list(lines.values())


def bill_payload(orders, payment=None) -> dict:
    """Чек «СЧЕТ»: без payment — счёт гостю, с payment — чек об оплате."""
    orders = sorted(orders, key=lambda o: o.created_at)
    first = orders[0]
    opened = timezone.localtime(first.created_at)
    closed = timezone.localtime()
    waiter = next((o.claimed_by for o in orders if o.claimed_by_id), None)
    accepted = next((o.accepted_by for o in orders if o.accepted_by_id), None)
    paid_by = next((o.paid_by for o in orders if o.paid_by_id), None)
    data = {
        "title": "СЧЕТ", "number": first.id, "branch": first.branch.name,
        "date": f"{opened:%d.%m.%Y}", "opened": f"{opened:%H:%M}",
        "place": _place(first) if len(orders) == 1 or at_table(first) else "Несколько заказов",
        **_staff_line(waiter, accepted, paid_by),                       # кто обслужил: официант, иначе кто принял / оплатил
        "orders": [o.id for o in orders],
        "items": _merged_lines(orders),
        "subtotal": sum(o.subtotal for o in orders),
        "delivery_fee": sum(o.delivery_fee for o in orders),
        "total": sum(o.total for o in orders),
        **_guest(first),
    }
    if payment:                                                       # чек об оплате
        data.update(closed=f"{closed:%H:%M}", payment=payment, thanks=THANKS)
    else:
        data["note"] = "Счёт к оплате"
    return data


def add_job(branch, kind, payload) -> PrintJob:
    """Новое задание для чекового аппарата этого филиала."""
    return PrintJob.objects.create(branch=branch, kind=kind, payload=payload)


def kitchen_payload(order, items=None) -> dict:
    """Кухонный чек: место, № заказа, кто принял, дата / время, блюда с количеством, добавки и комментарий. Без цен."""
    now = timezone.localtime(order.created_at)
    place = _place(order).upper()
    return {
        "number": order.id, "place": place, "date": f"{now:%d.%m.%Y}", "time": f"{now:%H:%M}",
        **_staff_line(order.claimed_by, order.accepted_by),
        "items": [{"name": item.dish_name + (f" {item.size_name}" if item.size_name else ""),
                   "extras": [e.get("name", "") for e in (item.extras or [])], "qty": item.quantity}
                  for item in (order.items.all() if items is None else items)],
        "comment": order.comment,
    }


def print_order(order) -> PrintJob:
    """
    Заказ подтверждён (или пришёл с доверенного телефона). Блюда расходятся по аппаратам своих категорий:
    кухонный аппарат 1 / 2 — каждому свой чек только с его блюдами; «не печатать» (напитки, десерты) — только в чеке оплаты.
    """
    groups = {}
    for item in order.items.select_related("dish__category"):
        where = item.dish.category.printer if item.dish_id and item.dish.category_id else "kitchen1"   # блюдо удалили — на аппарат 1
        if where in (PrintJob.Kind.KITCHEN1, PrintJob.Kind.KITCHEN2):
            groups.setdefault(where, []).append(item)
    for kind in (PrintJob.Kind.KITCHEN1, PrintJob.Kind.KITCHEN2):
        if groups.get(kind):
            add_job(order.branch, kind, kitchen_payload(order, groups[kind]))
    return add_job(order.branch, PrintJob.Kind.ORDER, order_payload(order))


def claim_jobs(branch, kinds=None) -> list:
    """
    Компьютер с аппаратом забирает новые задания нужных видов (касса — чеки, кухня — кухонные).
    Забранное помечаем — второй раз не напечатается.
    """
    since = timezone.now() - timedelta(hours=JOB_HOURS)
    with transaction.atomic():
        jobs = PrintJob.objects.select_for_update().filter(branch=branch, printed_at__isnull=True, created_at__gte=since)
        if kinds:
            jobs = jobs.filter(kind__in=kinds)
        jobs = list(jobs[:20])
        PrintJob.objects.filter(pk__in=[j.pk for j in jobs]).update(printed_at=timezone.now())
    return [{"id": j.id, "kind": j.kind, "payload": j.payload} for j in jobs]


# ===================== «К ОПЛАТЕ» =====================

def unpaid_orders(branch, user):
    """Подтверждённые, неоплаченные и неотменённые заказы филиала за последние сутки. Официант видит только зал."""
    since = timezone.now() - timedelta(hours=UNPAID_HOURS)
    orders = (
        Order.objects.filter(branch=branch, paid_at__isnull=True, created_at__gte=since)
        .exclude(status__in=[Order.Status.CANCELLED, Order.Status.NEW])            # неподтверждённые ещё могут отклонить
        .select_related("table", "claimed_by", "branch").prefetch_related("items")
    )
    if user.is_courier:                                               # курьер — свои доставки (и ещё не взятые)
        from django.db.models import Q
        orders = orders.filter(Q(claimed_by=user) | Q(claimed_by__isnull=True), kind=Order.Kind.DELIVERY)
    elif not (user.is_cafe_admin or user.is_cashier):               # кассир и админ видят все счета филиала
        orders = orders.filter(table__kind="hall", kind__in=[Order.Kind.HALL, Order.Kind.TAKEAWAY])
    return list(orders)


def _bill_key(order):
    """Заказы одного стола (одних гостей — после последнего «Освободить стол») — один счёт."""
    if at_table(order):
        table = order.table
        fresh = not table.freed_at or order.created_at > table.freed_at    # нынешние гости или прошлые
        return ("table", table.id, fresh)
    return ("order", order.id)


def bill_title(orders) -> str:
    """«Стол 3 · 1 этаж», «С собой · Стол 4», «Доставка №12», «Самовывоз №15»."""
    first = min(orders, key=lambda o: o.created_at)
    if first.kind == Order.Kind.DELIVERY:
        return f"Доставка №{first.id}"
    if first.kind == Order.Kind.PICKUP:
        return f"Самовывоз №{first.id}"
    if all(o.kind == Order.Kind.TAKEAWAY for o in orders):
        return f"С собой · {first.table}" if first.table_id else f"С собой №{first.id}"
    return str(first.table)


def free_if_settled(table, user) -> bool:
    """
    Все заказы гостей за столом поданы и оплачены — стол освобождается сам (как «Освободить стол»):
    сайт гостя и Telegram-бот увидят, что стол свободен.
    """
    from .status_service import close_visits
    if not table or table.kind != "hall":
        return False
    orders = Order.objects.filter(table=table).exclude(status=Order.Status.CANCELLED)
    if table.freed_at:
        orders = orders.filter(created_at__gt=table.freed_at)
    if not orders.exists():
        return False
    if orders.filter(paid_at__isnull=True).exists() or orders.exclude(status=Order.Status.COMPLETED).exists():
        return False                                                  # кто-то ещё не заплатил или ещё не подали
    close_visits(table, user)
    return True


def bills(branch, user) -> list:
    """Список счетов для вкладки «К оплате»."""
    groups = {}
    for order in unpaid_orders(branch, user):
        groups.setdefault(_bill_key(order), []).append(order)
    since = timezone.now() - timedelta(hours=3)
    asks = {c.table_id: c for c in TableCall.objects.filter(                       # гость нажал «Попросить счёт»
        kind=TableCall.Kind.BILL, is_done=False, created_at__gte=since, table__branch=branch,
    )}
    result = []
    for key, orders in groups.items():
        orders.sort(key=lambda o: o.created_at)
        first = orders[0]
        waiter = next((o.claimed_by for o in orders if o.claimed_by_id), None)
        staff = _staff_line(waiter, next((o.accepted_by for o in orders if o.accepted_by_id), None))   # кто ведёт счёт и его роль
        ask = asks.get(first.table_id) if key[0] == "table" else None
        title = bill_title(orders)                                                 # заголовок карточки
        result.append({
            "key": "-".join(str(x) for x in key),
            "kind": first.kind,
            "title": title,
            "orders": [o.id for o in orders],
            "opened_at": first.created_at,
            "waiter": _person(waiter),
            "staff_role": staff["staff_role"], "staff": staff["waiter"],       # «Официант: Азамат» / «Программист: Muslim»
            "customer": first.customer_name if not at_table(first) else "",
            "phone": first.phone if not at_table(first) else "",
            "payment_method": first.payment_method,                                # что гость выбрал при заказе
            "in_progress": sum(o.status != Order.Status.COMPLETED for o in orders),   # ещё готовятся / не поданы
            "items": _merged_lines(orders),
            "total": sum(o.total for o in orders),
            "bill_requested": bool(ask),
            "people": ask.people if ask else None,
        })
    result.sort(key=lambda b: (not b["bill_requested"], b["opened_at"]))           # просят счёт — сверху
    return result


def _load(branch, user, order_ids) -> list:
    """Заказы для счёта / оплаты с проверкой: свой филиал, не отменены, есть права."""
    ids = sorted({int(x) for x in order_ids or []})
    if not ids:
        raise ValidationError("Не выбраны заказы.")
    orders = list(
        Order.objects.select_for_update().filter(pk__in=ids, branch=branch)
        .exclude(status=Order.Status.CANCELLED)
    )
    if len(orders) != len(ids):
        raise ValidationError("Некоторые заказы не найдены или отменены.")
    for order in orders:
        if user.is_cafe_admin or user.is_cashier:                     # кассир закрывает любой счёт филиала
            continue
        if user.is_courier and order.kind == Order.Kind.DELIVERY and order.claimed_by_id in (None, user.id):
            continue                                                  # курьер — оплату своей доставки
        if not (user.is_waiter and at_table(order) and owns_table(user, order.table)):
            raise PermissionDenied("Этот счёт закрывает админ, кассир, официант этого стола или курьер доставки.")
    return orders


def preview_bill(branch, user, order_ids) -> dict:
    """Кнопка «Счёт»: сначала показать счёт в панели (без печати)."""
    with transaction.atomic():
        orders = _load(branch, user, order_ids)
    return {"kind": "bill", "payload": bill_payload(orders)}


@transaction.atomic
def print_bill(branch, user, order_ids) -> PrintJob:
    """Кнопка «Счёт»: напечатать счёт без оплаты — отнести гостю."""
    orders = _load(branch, user, order_ids)
    return add_job(branch, PrintJob.Kind.BILL, bill_payload(orders))


def _split(total, method, cash):
    """Сколько наличными и сколько картой."""
    if method == Order.PaidMethod.CASH:
        return total, 0
    if method == Order.PaidMethod.CARD:
        return 0, total
    if cash is None or not 0 < cash < total:                          # смешанная: наличных больше 0 и меньше суммы
        raise ValidationError("Укажите, сколько наличными (меньше общей суммы), остальное — картой.")
    return cash, total - cash


@transaction.atomic
def pay(branch, user, order_ids, method, cash=None, received=None) -> dict:
    """«Оплачено»: отмечаем заказы оплаченными, закрываем «Попросить счёт» и печатаем чек об оплате."""
    if method not in Order.PaidMethod.values:
        raise ValidationError("Выберите: наличные, карта или наличные + карта.")
    if user.is_cashier:                                               # кассир — только в открытую смену
        from .cash import require_shift
        require_shift(branch)
    orders = _load(branch, user, order_ids)
    if any(o.paid_at for o in orders):
        raise ValidationError("Этот счёт уже оплачен.")
    total = sum(o.total for o in orders)
    cash_sum, card_sum = _split(total, method, cash)
    if received is not None and received < cash_sum:
        raise ValidationError(f"Получено меньше, чем нужно наличными ({cash_sum} сом).")

    now = timezone.now()
    left = cash_sum                                                   # наличные раскладываем по заказам по очереди
    for order in sorted(orders, key=lambda o: o.created_at):
        part = min(left, order.total)
        left -= part
        order.paid_at, order.paid_method, order.paid_by = now, method, user
        order.paid_cash, order.paid_card = part, order.total - part
        order.save(update_fields=["paid_at", "paid_method", "paid_by", "paid_cash", "paid_card", "updated_at"])

    first = min(orders, key=lambda o: o.created_at)
    if at_table(first):                                               # гость просил счёт — просьба выполнена
        TableCall.objects.filter(table=first.table, kind=TableCall.Kind.BILL, is_done=False).update(
            is_done=True, done_by=user, done_at=now,
        )
    payment = {
        "method": Order.PaidMethod(method).label, "cash": cash_sum, "card": card_sum,
        "received": received, "change": (received - cash_sum) if received is not None else None,
    }
    add_job(branch, PrintJob.Kind.RECEIPT, bill_payload(orders, payment))   # чек об оплате
    add_event(BotKind.ORDER_CHANGED, order=first, action="pay", user_id=user.id)   # панели обновятся у всех
    freed = at_table(first) and free_if_settled(first.table, user)   # всё подано и оплачено — стол свободен
    return {"orders": [o.id for o in orders], "total": total, "table_freed": bool(freed), **payment}


def receipt_copy(branch, order_ids) -> PrintJob:
    """«🖨 Чек» в истории оплат: копия чека об оплате."""
    ids = sorted({int(x) for x in order_ids or []})
    orders = list(Order.objects.filter(pk__in=ids, branch=branch, paid_at__isnull=False).select_related("table", "claimed_by", "branch"))
    if not orders or len(orders) != len(ids):
        raise ValidationError("Оплата не найдена.")
    data = paid_receipt(orders)
    data["title"] = "СЧЕТ (КОПИЯ)"
    return add_job(branch, PrintJob.Kind.RECEIPT, data)


def paid_receipt(orders) -> dict:
    """Чек об оплате уже оплаченных заказов (для просмотра в «Истории оплат» и копии)."""
    payment = {
        "method": Order.PaidMethod(orders[0].paid_method).label if orders[0].paid_method else "",
        "cash": sum(o.paid_cash for o in orders), "card": sum(o.paid_card for o in orders), "received": None, "change": None,
    }
    data = bill_payload(orders, payment)
    data["closed"] = f"{timezone.localtime(orders[0].paid_at):%H:%M}"   # время оплаты, а не печати
    return data


def pay_on_delivery(order, user) -> None:
    """Доставка доставлена: курьер взял деньги тем способом, что выбрал гость. Сразу чек об оплате."""
    if order.paid_at:
        return
    method = Order.PaidMethod.CARD if order.payment_method == Order.Payment.CARD else Order.PaidMethod.CASH
    order.paid_at, order.paid_method, order.paid_by = timezone.now(), method, user
    order.paid_cash = order.total if method == Order.PaidMethod.CASH else 0
    order.paid_card = order.total - order.paid_cash
    order.save(update_fields=["paid_at", "paid_method", "paid_by", "paid_cash", "paid_card", "updated_at"])
    payment = {"method": Order.PaidMethod(method).label, "cash": order.paid_cash, "card": order.paid_card,
               "received": None, "change": None}
    add_job(order.branch, PrintJob.Kind.RECEIPT, bill_payload([order], payment))
