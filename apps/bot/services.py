"""Функции бота, которые не зависят от Telegram (их удобно проверять тестами)."""

import secrets                                   # надёжные случайные коды

from django.contrib.auth import authenticate, get_user_model   # проверка логина и пароля; модель сотрудника
from django.core.cache import cache              # счётчик неверных попыток входа
from django.db import transaction                # «всё или ничего»

from .models import LinkCode                     # таблица кодов привязки (пока не используется)

LOGIN_ATTEMPTS = 5                               # сколько неверных попыток подряд можно
LOGIN_PAUSE_MINUTES = 15                         # пауза после 5 неверных попыток


def create_link_code(user) -> LinkCode:
    """Новый код привязки для сотрудника. Старые неиспользованные коды удаляем — работает только последний."""
    LinkCode.objects.filter(user=user, used_at__isnull=True).delete()          # убираем прежние коды
    return LinkCode.objects.create(user=user, code=secrets.token_urlsafe(16))  # 22 символа: буквы, цифры, - и _


def _fails_key(telegram_id: int) -> str:
    """Имя счётчика неверных попыток для этого Telegram-аккаунта."""
    return f"bot-login-fails:{telegram_id}"


def login_from_telegram(login: str, password: str, telegram_id: int):
    """
    Сотрудник входит в боте своим логином (или email) и паролем с сайта.
    Возвращает (сотрудник, None) при успехе или (None, «текст ошибки для бота»).
    После 5 неверных попыток — пауза 15 минут для этого Telegram-аккаунта.
    """
    key = _fails_key(telegram_id)
    fails = cache.get(key, 0)                                          # сколько раз уже ошибся
    if fails >= LOGIN_ATTEMPTS:                                        # лимит исчерпан — ждём
        return None, f"Слишком много неверных попыток. Попробуйте через {LOGIN_PAUSE_MINUTES} минут."
    user = authenticate(None, username=login, password=password)       # та же проверка, что на сайте (логин или email)
    if not user or not user.role:                                      # неверно, заблокирован или не сотрудник
        fails += 1
        cache.set(key, fails, LOGIN_PAUSE_MINUTES * 60)                # счётчик живёт 15 минут
        left = LOGIN_ATTEMPTS - fails                                  # сколько попыток осталось
        if left <= 0:
            return None, f"Неверный логин или пароль. Вход закрыт на {LOGIN_PAUSE_MINUTES} минут."
        return None, f"Неверный логин или пароль. Осталось попыток: {left}."
    cache.delete(key)                                                  # вошёл — счётчик обнуляем
    bind_telegram(user, telegram_id)                                   # записываем Telegram ID
    return user, None


@transaction.atomic
def bind_telegram(user, telegram_id: int) -> None:
    """Записать Telegram ID сотруднику. Если этот Telegram был у другого сотрудника — у того он отвязывается."""
    get_user_model().objects.filter(telegram_id=telegram_id).exclude(pk=user.pk).update(telegram_id=None)
    user.telegram_id = telegram_id
    user.save(update_fields=["telegram_id"])


def unlink_telegram(user) -> None:
    """«Отвязать Telegram»: кнопки в боте для этого сотрудника перестают работать (например, сменил телефон)."""
    user.telegram_id = None
    user.save(update_fields=["telegram_id"])