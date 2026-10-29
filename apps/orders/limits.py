"""
Защита от спама заказами.
  - не больше 3 заказов, которые ждут подтверждения («Новый»), с одного телефона (доставка, самовывоз);
  - не больше 3 таких заказов с одного устройства (браузера гостя) — и за столом, и на доставке;
  - не больше 10 заказов на доставку / самовывоз в час с одного IP (дома у гостя свой IP;
    за столами лимита по IP нет — в кафе все гости сидят на одном Wi-Fi).
Как только кафе подтвердит или отклонит заказ, он перестаёт считаться «ждущим».
"""

from datetime import timedelta                       # промежуток времени

from django.core.cache import cache                  # общий кэш (таблица в базе) — счётчик по IP
from django.utils import timezone                    # текущее время
from rest_framework import serializers               # ошибка 400 с понятным текстом

from .models import Order

MAX_WAITING = 3                                      # сколько заказов могут одновременно ждать подтверждения
IP_LIMIT = 10                                        # заказов на доставку / самовывоз в час с одного IP
IP_WINDOW = 60 * 60                                  # «в час» — в секундах
REMOTE_KINDS = (Order.Kind.DELIVERY, Order.Kind.PICKUP)   # заказы не со стола

WAITING_TEXT = (
    f"У вас уже {MAX_WAITING} заказа ждут подтверждения. "
    "Подождите ответа кафе — потом можно будет заказать ещё."
)
IP_TEXT = "Слишком много заказов с этого устройства. Попробуйте через час или позвоните в кафе."


def phone_digits(phone: str) -> str:
    """Последние 9 цифр телефона: «+996 700 12-34-56» и «0700123456» — один и тот же номер."""
    return "".join(ch for ch in phone or "" if ch.isdigit())[-9:]


def _ip_key(ip: str) -> str:
    """Имя счётчика заказов с этого IP."""
    return f"orders-ip:{ip}"


def check_order_limits(kind: str, table, phone: str, device_key: str, ip: str) -> None:
    """Проверка перед созданием заказа. Лимит превышен — ошибка 400 с текстом для гостя."""
    waiting = Order.objects.filter(                                  # заказы, которые ещё ждут подтверждения
        status=Order.Status.NEW,
        created_at__gte=timezone.now() - timedelta(hours=24),        # совсем старые забытые не считаем
    )
    if kind in REMOTE_KINDS:                                         # доставка или самовывоз
        if cache.get(_ip_key(ip), 0) >= IP_LIMIT:                    # с этого IP уже 10 заказов за час
            raise serializers.ValidationError(IP_TEXT)
        remote = waiting.filter(kind__in=REMOTE_KINDS)
        digits = phone_digits(phone)
        same_phone = sum(1 for p in remote.values_list("phone", flat=True) if digits and phone_digits(p) == digits)
        same_device = remote.filter(device_key=device_key).count() if device_key else 0
        if same_phone >= MAX_WAITING or same_device >= MAX_WAITING:
            raise serializers.ValidationError(WAITING_TEXT)
    elif waiting.filter(table=table, device_key=device_key).count() >= MAX_WAITING:   # со стола: этот телефон за этим столом
        raise serializers.ValidationError(WAITING_TEXT)


def count_order(kind: str, ip: str) -> None:
    """Заказ создан — считаем его в лимит по IP (только доставка и самовывоз)."""
    if kind not in REMOTE_KINDS:
        return
    if not cache.add(_ip_key(ip), 1, IP_WINDOW):                     # счётчика не было — создан со значением 1
        try:
            cache.incr(_ip_key(ip))                                  # был — прибавляем 1
        except ValueError:                                           # успел истечь — начинаем заново
            cache.set(_ip_key(ip), 1, IP_WINDOW)
