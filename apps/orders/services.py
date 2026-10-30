"""
Бизнес-логика создания заказа.
Здесь считаются цены и создаётся заказ. Views и сериализаторы только вызывают эти функции.
"""

from django.db import transaction                       # "всё или ничего": если ошибка — в базу ничего не попадёт
from rest_framework.exceptions import ValidationError   # ошибка, которую DRF вернёт фронту как 400

from apps.bot.events import Kind as BotKind, add_event         # «почтовый ящик» для Telegram-бота
from apps.cafe.models import CafeSettings
from .models import Order, OrderItem, OrderStatusLog
from .status_service import active_visit, occupy_table  # доверенный телефон; отметка «стол занят»


def build_line(dish, size, extras, quantity) -> dict:
    """
    Считает одну позицию заказа.
    Цена за 1 шт = цена размера (или блюда, если размеров нет) + сумма добавок.
    """
    base_price = size.price if size else dish.price          # цена размера или самого блюда
    extras_price = sum(extra.price for extra in extras)       # сумма всех добавок
    return {
        "dish": dish,                                         # ссылка на блюдо
        "dish_name": dish.name,                               # копия названия
        "size_name": size.name if size else "",               # копия размера
        "extras": [{"name": e.name, "price": e.price} for e in extras],  # копия добавок
        "unit_price": base_price + extras_price,              # цена за штуку
        "quantity": quantity,                                 # количество
    }


@transaction.atomic   # если на любом шаге ошибка — заказ не создастся наполовину
def create_order(data: dict) -> Order:
    """
    Создаёт заказ из уже проверенных данных (их готовит OrderCreateSerializer).
    data["resolved_items"] — список (блюдо, размер, [добавки], количество).
    """
    kind = data["kind"]                            # hall / takeaway / delivery / pickup
    table = data["table"]                          # стол или точка "Доставка"
    cafe = CafeSettings.load(table.branch)         # настройки филиала этого стола
    device_key = data.get("device_key", "")        # ключ телефона гостя

    # 1. Считаем каждую позицию и сумму блюд
    lines = [build_line(*item) for item in data["resolved_items"]]
    subtotal = sum(line["unit_price"] * line["quantity"] for line in lines)

    # 2. Доставка: минимальная сумма и стоимость
    delivery_fee = 0
    if kind == Order.Kind.DELIVERY:
        if subtotal < cafe.delivery_min_sum:       # заказ слишком маленький
            raise ValidationError({"items": f"Минимальная сумма доставки — {cafe.delivery_min_sum} сом."})
        is_free = cafe.free_delivery_from and subtotal >= cafe.free_delivery_from   # набрал на бесплатную доставку
        delivery_fee = 0 if is_free else cafe.delivery_fee

    at_table = table.kind == table.Kind.HALL        # заказ со стола в кафе («в кафе» или «с собой»)
    is_delivery = kind == Order.Kind.DELIVERY

    # 3. Доверенный телефон за этим столом? Тогда заказ сразу идёт на кухню
    trusted = at_table and active_visit(table, device_key) is not None
    status = Order.Status.ACCEPTED if trusted else Order.Status.NEW

    # 4. Создаём сам заказ
    order = Order.objects.create(
        source=data.get("source", Order.Source.SITE),
        branch_id=table.branch_id,                 # филиал заказа — филиал стола / доставки
        kind=kind,
        status=status,
        table=table,
        device_key=device_key,
        customer_name=data.get("customer_name", ""),
        phone=data.get("phone", ""),
        address=data.get("address", "") if is_delivery else "",
        apartment=data.get("apartment", "") if is_delivery else "",
        entrance=data.get("entrance", "") if is_delivery else "",
        floor=data.get("floor", "") if is_delivery else "",
        courier_comment=data.get("courier_comment", "") if is_delivery else "",
        payment_method=data.get("payment_method", Order.Payment.CASH),
        change_from=data.get("change_from") if is_delivery else None,
        comment=data.get("comment", ""),
        subtotal=subtotal,
        delivery_fee=delivery_fee,
        total=subtotal + delivery_fee,
    )

    # 5. Сохраняем позиции одним запросом
    OrderItem.objects.bulk_create([OrderItem(order=order, **line) for line in lines])

    # 6. История статусов
    OrderStatusLog.objects.create(order=order, status=Order.Status.NEW)           # заказ создан
    if trusted:
        OrderStatusLog.objects.create(order=order, status=Order.Status.ACCEPTED)  # и сразу принят (доверенный телефон)
        occupy_table(order.table_id)                                              # стол занят (если его успели закрыть)

    # 7. Событие для Telegram-бота: он отправит заказ в нужные темы группы
    add_event(BotKind.ORDER_CREATED, order=order, trusted=trusted)

    return order