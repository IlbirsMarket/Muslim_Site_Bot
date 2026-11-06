"""
Вход в панель только по коду сотрудника (от 2 до 8 цифр, как в 1С). Логина и пароля на сайте нет.

Код не хранится: в базе только его отпечаток HMAC-SHA256 с SECRET_KEY (одинаковый код → одинаковый отпечаток,
поэтому можно проверить, что код ни у кого не повторяется). Админ задаёт код при создании сотрудника и больше его не видит.

Защита от подбора (короткий код угадать легко, поэтому её несколько слоёв):
  1. Свои устройства кафе (здесь уже входили по коду): 5 ошибок → пауза 15 минут только для этого устройства.
  2. Новые устройства: 5 ошибок с одного IP → пауза 15 минут для этого IP.
  3. Всего 20 ошибок с новых устройств за час → вход с новых устройств закрыт до конца часа,
     свои устройства кафе работают как обычно. Всё пишется в журнал сервера (muslim.security).
Сколько цифр в коде, сайт не подсказывает: любой неверный набор — просто «Неверный код».
"""

import hashlib                                                    # отпечаток ключа устройства
import hmac                                                       # отпечаток кода
import logging                                                    # журнал подбора
import re                                                         # проверка формата

from django.conf import settings                                  # SECRET_KEY
from django.core.cache import cache                               # общий счётчик ошибок
from django.utils import timezone                                 # время последнего входа

from core import login_guard                                      # счётчики «5 ошибок → 15 минут»

logger = logging.getLogger("muslim.security")
DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")               # ключ устройства: длинная случайная строка
PIN_RE = re.compile(r"^\d{2,8}$")                                 # код: от 2 до 8 цифр
NEW_DEVICES_LIMIT = 20                                            # ошибок со всех новых устройств за час
NEW_DEVICES_WINDOW = 60 * 60                                      # час (в секундах)
NEW_DEVICES_KEY = "pin-fails-new-devices"


def pin_hash(code: str) -> str:
    """Отпечаток кода (сам код в базе не храним)."""
    return hmac.new(settings.SECRET_KEY.encode(), f"pin:{code}".encode(), hashlib.sha256).hexdigest()


def device_hash(device: str) -> str:
    """Отпечаток ключа устройства — в базе храним только его."""
    return hashlib.sha256(device.encode()).hexdigest()


def valid_device(device) -> bool:
    """Похоже ли на ключ устройства из браузера."""
    return bool(device) and bool(DEVICE_RE.match(str(device)))


def known_device(device) -> bool:
    """Своё устройство кафе: здесь уже кто-то входил по коду."""
    from .models import TrustedDevice
    return valid_device(device) and TrustedDevice.objects.filter(key_hash=device_hash(device)).exists()


def _guard(device: str, ip: str, known: bool):
    """Имя счётчика ошибок и «откуда» для login_guard: своё устройство — по устройству, новое — по IP."""
    return ("pin-device", "dev:" + device_hash(device)[:16]) if known else ("pin-new", "ip:" + ip)


def wait_minutes(device: str, ip: str) -> int:
    """0 — можно пробовать; больше 0 — через сколько минут."""
    known = known_device(device)
    if not known and cache.get(NEW_DEVICES_KEY, 0) >= NEW_DEVICES_LIMIT:   # идёт подбор — новые устройства закрыты
        return NEW_DEVICES_WINDOW // 60
    return login_guard.wait_minutes(*_guard(device, ip, known))


def check(device: str, ip: str, code: str):
    """Проверить код. (сотрудник, 0) — входим; (None, сколько попыток осталось) — неверный код."""
    from .models import TrustedDevice, User
    known = known_device(device)
    user = None
    if PIN_RE.match(code or ""):
        user = User.objects.filter(pin_hash=pin_hash(code), is_active=True).exclude(role="").first()
    if user is None:
        if not known:
            if cache.add(NEW_DEVICES_KEY, 1, NEW_DEVICES_WINDOW) is False:   # общий счётчик новых устройств
                try:
                    cache.incr(NEW_DEVICES_KEY)
                except ValueError:
                    cache.set(NEW_DEVICES_KEY, 1, NEW_DEVICES_WINDOW)
        left = login_guard.record_failure(*_guard(device, ip, known))
        return None, left
    login_guard.record_success(*_guard(device, ip, known))
    if valid_device(device):                                       # запоминаем: это своё устройство кафе
        TrustedDevice.objects.update_or_create(user=user, key_hash=device_hash(device),
                                               defaults={"password_mark": "", "last_used_at": timezone.now()})
    return user, 0
