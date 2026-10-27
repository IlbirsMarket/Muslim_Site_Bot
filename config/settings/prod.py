"""
Настройки для сервера (DigitalOcean).
Берём всё из base.py и включаем безопасный режим.
Включаются переменной окружения: DJANGO_SETTINGS_MODULE=config.settings.prod
"""

import os                    # чтение переменных окружения

from .base import *  # noqa: F401,F403 — импортируем все базовые настройки

DEBUG = False                # на сервере подробные ошибки гостям не показываем

# Без настоящего секретного ключа сервер не запустится — так ключ не забудут вписать в .env
if SECRET_KEY == "dev-only-insecure-key":  # noqa: F405
    raise RuntimeError("Впишите SECRET_KEY в .env на сервере.")

# Адреса, с которых открывают сайт (IP сервера или домен), и откуда можно отправлять формы Django-админки
CSRF_TRUSTED_ORIGINS = [o for o in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

# Перед Django стоит nginx: настоящий IP гостя берём из заголовка, который он передаёт.
# Нужно для ограничения частоты (заказы, вызовы, попытки входа) — иначе все гости «с одного IP»
REST_FRAMEWORK = {**REST_FRAMEWORK, "NUM_PROXIES": 1}  # noqa: F405

# nginx сообщает, пришёл ли запрос по https (когда подключим домен и сертификат)
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_HTTPS = os.getenv("USE_HTTPS", "0") == "1"      # 1 — когда будет домен с https
SESSION_COOKIE_SECURE = USE_HTTPS                   # куки входа в Django-админку только по https
CSRF_COOKIE_SECURE = USE_HTTPS

# SQLite на сервере: ждём до 20 секунд, если база занята другим запросом, а не падаем с ошибкой
DATABASES["default"]["OPTIONS"] = {"timeout": 20, "transaction_mode": "IMMEDIATE"}  # noqa: F405

# Ошибки сервера пишем в журнал (смотреть: journalctl -u muslim)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}