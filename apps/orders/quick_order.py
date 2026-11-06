"""
«Заказ за гостя»: официант, админ или кассир сам вбивает заказ — как в 1С.
Выбрал стол (или «С собой») → меню без фото → «Отправить на кухню».
Заказ сразу «Принят»: чек уходит на кухню, стол закрепляется за тем, кто заказал (если это официант).
Дозаказ на занятый стол попадает в тот же счёт стола (счёт собирается по столу — billing._bill_key).
"""

from django.db import transaction                                   # «всё или ничего»
from django.db.models import Count, Q, Sum                          # суммы счёта стола
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.bot.events import Kind as BotKind, add_event              # бот покажет заказ в группе
from apps.menu.models import Category, Dish, DishSize, Extra
from apps.tables.models import Table

from .models import Order, OrderItem, OrderStatusLog, TableCall
from .services import build_line                                    # цена позиции (размер + добавки)
from .status_service import occupy_table, owns_table


def _person(user) -> str:
    return (user.first_name or user.username) if user else ""


def menu(branch) -> list:
    """Меню филиала без фото: категории → блюда (размеры отдельными кнопками), добавки, стоп-лист."""
    dishes = (Dish.objects.filter(category__branch=branch, category__is_active=True, is_active=True)
              .prefetch_related("sizes", "extras").order_by("position", "id"))
    by_category = {}
    for dish in dishes:
        by_category.setdefault(dish.category_id, []).append({
            "id": dish.id, "name": dish.name, "price": dish.price, "available": dish.is_available,
            "sizes": [{"id": s.id, "name": s.name, "price": s.price} for s in dish.sizes.all()],
            "extras": [{"id": e.id, "name": e.name, "price": e.price} for e in dish.extras.all() if e.is_available],
        })
    return [{"id": c.id, "name": c.name, "dishes": by_category[c.id]}
            for c in Category.objects.filter(branch=branch, is_active=True) if c.id in by_category]


def tables(branch) -> list:
    """Столы зала: свободен / занят (сумма счёта, официант, с какого времени) / просят счёт."""
    rows = Table.objects.filter(branch=branch, kind=Table.Kind.HALL, is_active=True).select_related("waiter").order_by("floor", "number", "id")
    asks = set(TableCall.objects.filter(table__branch=branch, kind=TableCall.Kind.BILL, is_done=False).values_list("table_id", flat=True))
    out = []
    for table in rows:
        orders = Order.objects.filter(table=table).exclude(status=Order.Status.CANCELLED)
        if table.freed_at:                                       # прошлые гости не считаются
            orders = orders.filter(created_at__gt=table.freed_at)
        bill = orders.aggregate(total=Sum("total"), unpaid=Count("id", filter=Q(paid_at__isnull=True)))
        busy = bool(table.occupied_since) or bool(bill["unpaid"])
        out.append({
            "id": table.id, "floor": table.floor, "number": table.number, "name": str(table),
            "busy": busy, "total": (bill["total"] or 0) if busy else 0,
            "since": table.occupied_since, "waiter": _person(table.waiter), "waiter_id": table.waiter_id,
            "bill_requested": table.id in asks,
        })
    return out


def _resolve(branch, items) -> list:
    """Позиции из фронта → (блюдо, размер, добавки, кол-во) с проверкой меню и стоп-листа."""
    if not items:
        raise ValidationError({"items": "Добавьте хотя бы одно блюдо."})
    resolved = []
    for item in items:
        dish = Dish.objects.filter(pk=item.get("dish_id"), is_active=True, category__branch=branch).prefetch_related("sizes", "extras").first()
        if not dish:
            raise ValidationError({"items": "Одно из блюд больше недоступно. Обновите меню."})
        if not dish.is_available:
            raise ValidationError({"items": f"«{dish.name}» — в стоп-листе."})
        sizes = {s.id: s for s in dish.sizes.all()}
        size = None
        if sizes:
            size = sizes.get(item.get("size_id"))
            if size is None:
                raise ValidationError({"items": f"Выберите размер для «{dish.name}»."})
        allowed = {e.id: e for e in dish.extras.all() if e.is_available}
        extras = []
        for extra_id in item.get("extra_ids") or []:
            if extra_id not in allowed:
                raise ValidationError({"items": f"Добавка недоступна для «{dish.name}»."})
            extras.append(allowed[extra_id])
        quantity = int(item.get("quantity") or 0)
        if not 1 <= quantity <= 99:
            raise ValidationError({"items": "Количество — от 1 до 99."})
        resolved.append((dish, size, extras, quantity))
    return resolved


@transaction.atomic
def create(user, branch, table_id, items, comment="") -> Order:
    """Заказ за гостя: table_id — стол зала; None — «С собой» (без стола). Сразу «Принят» + чек на кухню."""
    table = None
    if table_id:
        table = Table.objects.select_for_update().filter(pk=table_id, branch=branch, kind=Table.Kind.HALL, is_active=True).first()
        if table is None:
            raise ValidationError({"table": "Стол не найден."})
        if not owns_table(user, table):                         # стол ведёт другой официант
            raise PermissionDenied(f"Этот стол ведёт {_person(table.waiter)}.")
    lines = [build_line(*item) for item in _resolve(branch, items)]
    subtotal = sum(line["unit_price"] * line["quantity"] for line in lines)
    waiter_id = (table.waiter_id or (user.id if user.is_waiter else None)) if table else user.id   # кто ведёт заказ
    order = Order.objects.create(
        source=Order.Source.STAFF, branch=branch, table=table,
        kind=Order.Kind.HALL if table else Order.Kind.TAKEAWAY,
        status=Order.Status.ACCEPTED, accepted_by=user, claimed_by_id=waiter_id,
        comment=(comment or "").strip()[:1000], subtotal=subtotal, total=subtotal,
    )
    OrderItem.objects.bulk_create([OrderItem(order=order, **line) for line in lines])
    OrderStatusLog.objects.create(order=order, status=Order.Status.NEW, changed_by=user)
    OrderStatusLog.objects.create(order=order, status=Order.Status.ACCEPTED, changed_by=user)
    if table:
        occupy_table(table.id)                                  # стол занят
        if user.is_waiter and not table.waiter_id:              # стол теперь за этим официантом
            Table.objects.filter(pk=table.pk).update(waiter=user)
    from .billing import print_order                            # чек на кухню (кухня 1 / кухня 2 по категориям)
    print_order(order)
    add_event(BotKind.ORDER_CREATED, order=order, trusted=True)  # бот покажет заказ как уже принятый
    return order
