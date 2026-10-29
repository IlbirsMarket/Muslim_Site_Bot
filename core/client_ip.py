"""Настоящий IP посетителя — для защиты от подбора пароля и спама заказами."""

from rest_framework.throttling import BaseThrottle          # умеет учитывать nginx перед Django (NUM_PROXIES)


def client_ip(request) -> str:
    """IP посетителя. За nginx берётся из заголовка X-Forwarded-For (настройка NUM_PROXIES в prod.py)."""
    return BaseThrottle().get_ident(request) if request else "unknown"
