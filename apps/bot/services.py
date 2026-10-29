"""Функции бота, которые не зависят от Telegram (их удобно проверять тестами)."""

import secrets                                   # надёжные случайные коды

from django.contrib.auth import authenticate, get_user_model   # проверка логина и пароля; модель сотрудника
from django.core.cache import cache              # счётчик неверных попыток входа
from django.db import transaction                # «всё или ничего»

from core import login_guard                     # общая с сайтом защита от подбора пароля

from .models import LinkCode                     # таблица кодов привязки (пока не используется)

LOGIN_ATTEMPTS = 5                               # сколько неверных попыток подряд можно
LOGIN_PAUSE_MINUTES = 15                         # пауза после 5 неверных попыток


def create_link_code(user) -> LinkCode:
    """Новый код привязки для сотрудника. Старые неиспользованные коды удаляем — работает только последний."""
    LinkCode.objects.filter(user=user, used_at__isnull=True).delete()          # убираем прежние коды
    return LinkCode.objects.create(user=user, code=secrets.token_urlsafe(16))  # 22 символа: буквы, цифры, - и _


def _fails_key(telegram_id: int) -> str:
    """Имя счётчика неверных попыток для этого Telegram-аккаунта (любые логины вместе)."""
    return f"bot-login-fails:{telegram_id}"


def login_from_telegram(login: str, password: str, telegram_id: int):
    """
    Сотрудник входит в боте своим логином (или email) и паролем с сайта.
    Возвращает (сотрудник, None) при успехе или (None, «текст ошибки для бота»).
    Три защиты от подбора пароля:
      - 5 ошибок с этого Telegram-аккаунта (любые логины) → пауза 15 минут;
      - 5 ошибок на этот логин с этого Telegram → пауза 15 минут (общий охранник с сайтом, core/login_guard.py);
      - 20 ошибок на этот логин за час со всех мест (сайт + бот) → логин закрыт до конца часа.
    """
    key = _fails_key(telegram_id)
    source = f"tg:{telegram_id}"                                       # «откуда» для общего охранника
    tg_fails = cache.get(key, 0)                                       # сколько раз ошибся этот Telegram
    if tg_fails >= LOGIN_ATTEMPTS:                                     # лимит этого Telegram исчерпан — ждём
        return None, f"Слишком много неверных попыток. Попробуйте через {LOGIN_PAUSE_MINUTES} минут."
    minutes = login_guard.wait_minutes(login, source)                  # не закрыт ли этот логин?
    if minutes:
        return None, f"Слишком много неверных попыток. Попробуйте через {minutes} минут."
    user = authenticate(None, username=login, password=password)       # та же проверка, что на сайте (логин или email)
    if not user or not user.role:                                      # неверно, заблокирован или не сотрудник
        tg_fails += 1
        cache.set(key, tg_fails, LOGIN_PAUSE_MINUTES * 60)             # счётчик Telegram живёт 15 минут
        login_left = login_guard.record_failure(login, source)         # общий счётчик логина + запись в журнал
        left = min(LOGIN_ATTEMPTS - tg_fails, login_left)              # сколько осталось по самому строгому счётчику
        if left <= 0:
            return None, f"Неверный логин или пароль. Вход закрыт на {LOGIN_PAUSE_MINUTES} минут."
        return None, f"Неверный логин или пароль. Осталось попыток: {left}."
    cache.delete(key)                                                  # вошёл — счётчики обнуляем
    login_guard.record_success(login, source)
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