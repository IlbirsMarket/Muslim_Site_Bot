"""
Push-уведомления на телефон без сторонних библиотек: стандарт Web Push (VAPID) + пустое уведомление.
Телефон получает «пинок», сервис-воркер (sw.js) сам забирает текст по адресу /api/push/inbox/ и показывает его.
Ключи VAPID — в .env (VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY), создать: python manage.py make_vapid_keys
"""

import base64                                    # base64url для ключей и подписи
import json                                      # части подписи (JWT)
import logging                                   # ошибки отправки — в журнал
import time                                      # срок действия подписи
import urllib.error                              # ответы push-сервиса с ошибкой
import urllib.request                            # отправка без сторонних библиотек
from urllib.parse import urlsplit                # адрес push-сервиса → его «origin»

from django.conf import settings

log = logging.getLogger(__name__)


def b64(data: bytes) -> str:
    """base64url без «=» — так требуют стандарты Web Push."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_keys() -> tuple:
    """Новая пара ключей VAPID: (публичный, приватный) в base64url."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64(public), b64(private.private_numbers().private_value.to_bytes(32, "big"))


def enabled() -> bool:
    """Push включён, если в .env есть оба ключа."""
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def vapid_header(endpoint: str) -> str:
    """Подпись сервера (JWT, ES256): push-сервис знает, что уведомление от нас."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
    url = urlsplit(endpoint)
    head = b64(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    body = b64(json.dumps({"aud": f"{url.scheme}://{url.netloc}", "exp": int(time.time()) + 12 * 3600,
                           "sub": settings.VAPID_SUBJECT}).encode())
    raw = settings.VAPID_PRIVATE_KEY + "=" * (-len(settings.VAPID_PRIVATE_KEY) % 4)
    private = ec.derive_private_key(int.from_bytes(base64.urlsafe_b64decode(raw), "big"), ec.SECP256R1())
    r, s = decode_dss_signature(private.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256())))
    signature = b64(r.to_bytes(32, "big") + s.to_bytes(32, "big"))
    return f"vapid t={head}.{body}.{signature}, k={settings.VAPID_PUBLIC_KEY}"


def send(subscription, title: str, body: str, url: str = "/") -> bool:
    """Положить текст в «ящик» подписки и «пнуть» телефон. Подписка устарела (404/410) — удаляем."""
    if not enabled():
        return False
    subscription.pending = (subscription.pending or [])[-4:] + [{"title": title, "body": body, "url": url}]   # не больше 5 в очереди
    subscription.save(update_fields=["pending"])
    request = urllib.request.Request(subscription.endpoint, data=b"", method="POST", headers={
        "Authorization": vapid_header(subscription.endpoint), "TTL": "3600", "Urgency": "high", "Content-Length": "0",
    })
    try:
        urllib.request.urlopen(request, timeout=8).close()
        return True
    except urllib.error.HTTPError as error:
        if error.code in (404, 410):                       # телефон отписался или приложение удалили
            subscription.delete()
        else:
            log.warning("Push %s: %s", error.code, error.read()[:200])
    except OSError as error:                                # нет сети — не страшно, следующий раз
        log.warning("Push: %s", error)
    return False


# ===== Кому что слать (по событию бота — те же события, что и для Telegram) =====

def _staff(branch_id, roles):
    """Подписки сотрудников филиала с этими ролями (шеф и программист — во всех филиалах получают новые заказы)."""
    from django.db.models import Q
    from .models import PushSubscription
    if "admin" in roles:
        roles = list(roles) + ["cashier"]                        # кассир получает всё, что админ
    query = Q(user__role__in=roles, user__branch_id=branch_id)
    if "admin" in roles:
        query |= Q(user__role__in=["chef", "programmer"])
    return PushSubscription.objects.filter(query, user__is_active=True).select_related("user")


def recipients(event) -> list:
    """[(подписки, заголовок, текст, адрес)] для события."""
    from apps.orders.models import Order
    from apps.orders.status_service import at_table
    from .models import BotEvent, PushSubscription
    from django.conf import settings
    PANEL = settings.STAFF_PANEL_PATH                               # секретный адрес панели персонала
    K, S, out = BotEvent.Kind, Order.Status, []
    if event.order_id:
        order = Order.objects.select_related("table", "claimed_by").get(pk=event.order_id)
        place = str(order.table) if at_table(order) else order.get_kind_display()
        head = f"Заказ №{order.id} · {place}"
        action = (event.payload or {}).get("action")
        if event.kind == K.ORDER_CREATED:
            if order.status == S.NEW:                                    # ждёт подтверждения
                who = ["admin"] + (["waiter"] if at_table(order) else [])
                subs = _staff(order.branch_id, who)
                if at_table(order) and order.table and order.table.waiter_id:   # стол ведёт официант — только ему из официантов
                    subs = [x for x in subs if x.user.role != "waiter"] + list(PushSubscription.objects.filter(user_id=order.table.waiter_id))
                out.append((subs, "🆕 Новый заказ", head, PANEL))
            elif order.status == S.ACCEPTED:                             # доверенный стол — сразу на кухню
                out.append((_staff(order.branch_id, ["cook"]), "🍳 На кухню", head, PANEL))
        elif event.kind == K.ORDER_CHANGED and action not in ("claim", "pay"):   # оплата — не новость для push
            if action == "accept":
                out.append((_staff(order.branch_id, ["cook"]), "🍳 На кухню", head, PANEL))
            if action == "ready":
                if order.claimed_by_id:
                    subs = PushSubscription.objects.filter(user_id=order.claimed_by_id)
                elif order.kind == Order.Kind.DELIVERY:
                    subs = _staff(order.branch_id, ["courier"])
                else:
                    subs = _staff(order.branch_id, ["waiter" if at_table(order) else "admin"])
                out.append((subs, "✅ Готов", head, PANEL))
            if order.device_key:                                         # гостю — его статус
                out.append((PushSubscription.objects.filter(user__isnull=True, device_key=order.device_key),
                            f"Заказ №{order.id}", f"Статус: {order.status_label}", "/"))
    elif event.call_id and event.kind == K.CALL_CREATED:
        call = event.call
        if call.table.waiter_id:
            subs = list(PushSubscription.objects.filter(user_id=call.table.waiter_id))   # официант этого стола
            if call.kind == call.Kind.BILL:                                       # счёт — ещё и админам (касса)
                subs += list(_staff(call.table.branch_id, ["admin"]))
        else:
            subs = _staff(call.table.branch_id, ["waiter", "admin"])
        body = call.get_kind_display() + (f" · {call.people} чел." if call.people else "")   # «Попросить счёт · 3 чел.»
        out.append((subs, f"🔔 {call.table}", body, PANEL))
    return out


def push_event(event) -> int:
    """Отправить push по событию. Возвращает, сколько уведомлений ушло."""
    if not enabled():
        return 0
    sent = 0
    for subs, title, body, url in recipients(event):
        for sub in {s.pk: s for s in subs}.values():
            sent += send(sub, title, body, url)
    return sent
