"""Функции бота, которые не зависят от Telegram (их удобно проверять тестами)."""

import secrets               # надёжные случайные коды

from .models import LinkCode  # таблица кодов привязки


def create_link_code(user) -> LinkCode:
    """Новый код привязки для сотрудника. Старые неиспользованные коды удаляем — работает только последний."""
    LinkCode.objects.filter(user=user, used_at__isnull=True).delete()          # убираем прежние коды
    return LinkCode.objects.create(user=user, code=secrets.token_urlsafe(16))  # 22 символа: буквы, цифры, - и _