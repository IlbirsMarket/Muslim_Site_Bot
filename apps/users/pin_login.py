"""
Быстрый вход по коду из 2 цифр (как в 1С) — только на «запомненном» устройстве.

Как это работает:
  1. Браузер один раз создаёт случайный ключ устройства (64 знака) и хранит его у себя.
  2. Сотрудник входит на этом устройстве по логину и паролю — сервер запоминает пару «сотрудник + отпечаток ключа».
  3. Дальше на этом устройстве ему хватает своего кода: «66» → сразу в панели.
С чужого телефона или компьютера код не работает: ключа устройства там нет, а угадать 64 знака нельзя.
Неверные коды считает та же защита от подбора, что и пароли: 5 ошибок с устройства → пауза 15 минут.
"""

import hashlib                                                    # отпечаток ключа устройства
import re                                                         # проверка формата

from django.utils import timezone                                 # время «последнего входа по коду»
from rest_framework_simplejwt.utils import get_md5_hash_password  # отпечаток пароля (как в токенах)

DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")               # ключ устройства: длинная случайная строка
PIN_RE = re.compile(r"^\d{2}$")                                   # код: ровно 2 цифры


def device_hash(device: str) -> str:
    """Отпечаток ключа устройства — в базе храним только его."""
    return hashlib.sha256(device.encode()).hexdigest()


def valid_device(device) -> bool:
    """Похоже ли на ключ устройства из браузера."""
    return bool(device) and bool(DEVICE_RE.match(str(device)))


def remember_device(user, device) -> None:
    """После входа по паролю: запомнить это устройство для сотрудника (или обновить отпечаток пароля)."""
    from .models import TrustedDevice
    if not valid_device(device) or not user.role:
        return
    TrustedDevice.objects.update_or_create(
        user=user, key_hash=device_hash(device),
        defaults={"password_mark": get_md5_hash_password(user.password)},
    )


def known_device(device) -> bool:
    """Запомнено ли устройство хоть для кого-то (тогда на нём показываем ввод кода)."""
    from .models import TrustedDevice
    return valid_device(device) and TrustedDevice.objects.filter(key_hash=device_hash(device)).exists()


def find_user(device: str, pin: str):
    """
    (сотрудник, None) — код верный и сотрудник уже входил на этом устройстве по паролю.
    (None, "wrong") — такого кода нет; (None, "not_here") — код есть, но на этом устройстве ещё не было входа по паролю.
    """
    from .models import TrustedDevice, User
    user = User.objects.filter(pin=pin, is_active=True).exclude(role="").first()
    if user is None:
        return None, "wrong"
    trusted = TrustedDevice.objects.filter(user=user, key_hash=device_hash(device)).first()
    if trusted is None or trusted.password_mark != get_md5_hash_password(user.password):   # не входил или сменили пароль
        return None, "not_here"
    trusted.last_used_at = timezone.now()
    trusted.save(update_fields=["last_used_at"])
    return user, None
