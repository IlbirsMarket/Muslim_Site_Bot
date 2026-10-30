"""
Гостевой бот без Telegram: меню, корзина, оформление заказа, статусы.
Заказ создаётся тем же OrderCreateSerializer, что и на сайте (те же проверки, цены и лимиты).
"""

import os                                                    # есть ли файл фото на диске
from html import escape                                      # названия — безопасно для HTML

from django.db import transaction                            # заказ и chat_id — вместе
from django.utils import timezone                            # время обработки события
from rest_framework.exceptions import ValidationError

from apps.cafe.models import Branch, CafeSettings
from apps.menu.models import Category, Dish
from apps.orders.models import Order
from apps.orders.serializers import OrderCreateSerializer
from apps.tables.models import Table
from .models import BotEvent, BotMessage
from .texts import money

STATUS_EVENTS = [BotEvent.Kind.ORDER_CREATED, BotEvent.Kind.ORDER_CHANGED]   # что интересно гостю


def telegram_request(chat_id):
    """«Запрос» для сериализатора: вместо IP — Telegram гостя (лимит 10 доставок в час на человека)."""
    from django.http import HttpRequest
    from rest_framework.request import Request
    raw = HttpRequest()                                       # пустой запрос Django
    raw.META["REMOTE_ADDR"] = f"tg:{chat_id}"                 # client_ip() прочитает это как IP
    return Request(raw)                                       # как в DRF: есть headers и query_params


def branches() -> list:
    """Активные филиалы [(id, название)]."""
    return list(Branch.objects.filter(is_active=True).values_list("id", "name"))


def categories(branch_id) -> list:
    """Категории, где есть блюда в наличии [(id, название)]."""
    return list(Category.objects.filter(branch_id=branch_id, is_active=True,
                                        dishes__is_active=True, dishes__is_available=True).distinct().values_list("id", "name"))


def dishes(branch_id, category_id) -> list:
    """Блюда категории [(id, название, цена от)]."""
    qs = Dish.objects.filter(category_id=category_id, category__branch_id=branch_id, is_active=True, is_available=True).prefetch_related("sizes")
    return [(d.id, d.name, d.min_price) for d in qs]


def dish_page(branch_id, category_id, index: int):
    """
    Одна «страница» меню: блюдо номер index в категории (листание по кругу).
    Возвращает dict: id, index, total, caption, photo (путь к файлу или None), name — или None, если блюд нет.
    """
    items = list(Dish.objects.filter(category_id=category_id, category__branch_id=branch_id, is_active=True, is_available=True)
                 .select_related("category").prefetch_related("sizes"))
    if not items:
        return None
    index %= len(items)                                       # после последнего — снова первое
    dish = items[index]
    sizes = " · ".join(f"{s.name} — {money(s.price)}" for s in dish.sizes.all())
    caption = (f"<b>{escape(dish.name)}</b>\n{escape(dish.description)[:700]}\n\n"
               + (sizes if sizes else f"Цена: <b>{money(dish.price)}</b>"))
    photo = dish.photo.path if dish.photo and os.path.exists(dish.photo.path) else None   # файл фото на диске
    return {"id": dish.id, "index": index, "total": len(items), "caption": caption, "photo": photo,
            "name": dish.name, "category": dish.category.name}


def dish_titles(branch_id, category_id) -> list:
    """Названия блюд категории по порядку — для «📋 Списком»."""
    return list(Dish.objects.filter(category_id=category_id, category__branch_id=branch_id, is_active=True, is_available=True)
                .values_list("name", flat=True))


def placeholder_photo(name: str) -> bytes:
    """Картинка для блюда без фото: зелёный фон, золотая рамка, название."""
    from io import BytesIO
    from PIL import Image, ImageDraw, ImageFont
    from django.conf import settings
    image = Image.new("RGB", (800, 600), "#1f3d2b")                       # зелёный цвет кафе
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((30, 30, 770, 570), radius=30, outline="#c9a24a", width=6)   # золотая рамка
    font_path = str(settings.BASE_DIR / "core" / "fonts" / "DejaVuSans-Bold.ttf")
    lines, current = [], ""
    for word in name.split():                                              # переносим длинное название по строкам
        if current and len(current) + 1 + len(word) > 18:
            lines.append(current)
            current = word
        else:
            current = (current + " " + word).strip()
    lines.append(current)
    font = ImageFont.truetype(font_path, 56)
    top = 300 - len(lines) * 36
    for i, line in enumerate(lines[:4]):
        width = draw.textlength(line, font=font)
        draw.text(((800 - width) / 2, top + i * 72), line, font=font, fill="white")
    draw.text((400 - draw.textlength("Муслим", font=ImageFont.truetype(font_path, 30)) / 2, 500), "Муслим",
              font=ImageFont.truetype(font_path, 30), fill="#c9a24a")
    out = BytesIO()
    image.save(out, "JPEG", quality=85)
    return out.getvalue()


def cart_count(cart: list) -> int:
    """Сколько штук в корзине (для кнопки «🛒 Корзина (N)»)."""
    return sum(item.get("quantity", 1) for item in cart or [])


def dish_card(branch_id, dish_id):
    """Карточка блюда: (текст, размеры [(id, название, цена)], добавки [(id, название, цена)]) или None."""
    dish = Dish.objects.filter(pk=dish_id, category__branch_id=branch_id, is_active=True, is_available=True).first()
    if dish is None:
        return None
    sizes = [(s.id, s.name, s.price) for s in dish.sizes.all()]
    extras = [(e.id, e.name, e.price) for e in dish.extras.filter(is_available=True)]
    text = f"<b>{escape(dish.name)}</b>\n{escape(dish.description)}\n\nЦена: {money(dish.min_price)}" + (" и выше" if len(sizes) > 1 else "")
    return text, sizes, extras


def item_line(item) -> tuple:
    """Позиция корзины {dish_id, size_id, extra_ids, quantity} → (текст, сумма). Пропавшее блюдо — (None, 0)."""
    dish = Dish.objects.filter(pk=item["dish_id"], is_active=True, is_available=True).first()
    if dish is None:
        return None, 0
    size = dish.sizes.filter(pk=item.get("size_id")).first() if item.get("size_id") else None
    extras = list(dish.extras.filter(pk__in=item.get("extra_ids") or [], is_available=True))
    price = (size.price if size else dish.price) + sum(e.price for e in extras)
    name = dish.name + (f" ({size.name})" if size else "") + ("".join(f" + {e.name}" for e in extras))
    return f"{escape(name)} × {item['quantity']} = {money(price * item['quantity'])}", price * item["quantity"]


def cart_text(branch_id, cart: list) -> tuple:
    """(текст корзины, сумма блюд, доставка)."""
    lines, total = [], 0
    for item in cart:
        line, amount = item_line(item)
        if line:
            lines.append("• " + line)
            total += amount
    fee = CafeSettings.load(Branch.objects.get(pk=branch_id)).delivery_fee
    if not lines:
        return "🛒 Корзина пуста.", 0, fee
    return "🛒 <b>Корзина</b>\n" + "\n".join(lines) + f"\n\nБлюда: <b>{money(total)}</b>", total, fee


def create_bot_order(branch_id, chat_id, data: dict) -> tuple:
    """Создать заказ. Возвращает (заказ, None) или (None, текст ошибки)."""
    branch = Branch.objects.get(pk=branch_id)
    payload = {
        "table_token": Table.delivery_point(branch).token,      # QR доставки этого филиала
        "device_key": f"tg:{chat_id}",                          # «телефон» гостя — его Telegram
        "order_type": data["kind"], "customer_name": data.get("name", ""), "phone": data.get("phone", ""),
        "address": data.get("address", ""), "payment_method": data.get("payment", Order.Payment.CASH),
        "comment": data.get("comment", ""),
        "items": [{"dish_id": i["dish_id"], "size_id": i.get("size_id"), "extra_ids": i.get("extra_ids") or [], "quantity": i["quantity"]}
                  for i in data["cart"]],
    }
    serializer = OrderCreateSerializer(data=payload, context={"request": telegram_request(chat_id)})
    try:
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():                              # событие «новый заказ» и chat_id сохраняются вместе
            order = serializer.save(source=Order.Source.BOT)
            Order.objects.filter(pk=order.pk).update(guest_chat_id=chat_id)
    except ValidationError as error:
        from .staff_actions import _error_text
        return None, _error_text(error)
    order.guest_chat_id = chat_id
    return order, None


def guest_text(order) -> str:
    """Сообщение гостю о его заказе."""
    lines = [f"🧾 <b>Заказ №{order.id}</b> · {order.get_kind_display()}", f"Статус: <b>{order.status_label}</b>"]
    lines += [f"• {escape(i.dish_name)}{' (' + escape(i.size_name) + ')' if i.size_name else ''} × {i.quantity}" for i in order.items.all()]
    lines.append(f"Итого: <b>{money(order.total)}</b>")
    if order.status == Order.Status.CANCELLED and order.cancel_reason:
        lines.append(f"Причина: {escape(order.cancel_reason)}")
    return "\n".join(lines)


def guest_pending(limit=20) -> list:
    """События для гостевого бота. Ненужные (не про заказы из бота) сразу отмечаются."""
    BotEvent.objects.filter(guest_processed_at__isnull=True).exclude(kind__in=STATUS_EVENTS, order__guest_chat_id__isnull=False) \
        .update(guest_processed_at=timezone.now())
    return list(BotEvent.objects.filter(guest_processed_at__isnull=True)[:limit])


def guest_step(event):
    """(chat_id, текст, старый BotMessage или None) для события."""
    order = Order.objects.prefetch_related("items").get(pk=event.order_id)
    return order.guest_chat_id, guest_text(order), order.bot_messages.filter(place=BotMessage.Place.GUEST).first()


def guest_saved(event, chat_id, message_id) -> None:
    """Запомнить сообщение гостю и отметить событие."""
    BotMessage.objects.update_or_create(order_id=event.order_id, place=BotMessage.Place.GUEST,
                                        defaults={"chat_id": chat_id, "message_id": message_id})
    BotEvent.objects.filter(pk=event.pk).update(guest_processed_at=timezone.now())


def my_orders(chat_id) -> str:
    """«Мои заказы»: последние 5."""
    orders = Order.objects.filter(guest_chat_id=chat_id).order_by("-created_at")[:5]
    if not orders:
        return "У вас пока нет заказов."
    return "\n".join(f"№{o.id} · {o.created_at:%d.%m %H:%M} · {money(o.total)} · <b>{o.status_label}</b>" for o in orders)
