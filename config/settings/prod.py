"""
Настройки для сервера (DigitalOcean).
Берём всё из base.py и включаем безопасный режим.
Включаются переменной окружения: DJANGO_SETTINGS_MODULE=config.settings.prod
"""

import os                    # чтение переменных окружения
import re                    # проверка адреса Django-админки
import secrets               # пример случайного адреса в подсказке

from .base import *  # noqa: F401,F403 — импортируем все базовые настройки

DEBUG = False                # на сервере подробные ошибки гостям не показываем

# Без настоящего секретного ключа сервер не запустится — так ключ не забудут вписать в .env
# Короткий ключ легче подобрать — а им подписаны все токены входа. Нужно не меньше 50 символов
if SECRET_KEY == "dev-only-insecure-key" or len(SECRET_KEY) < 50:  # noqa: F405
    raise RuntimeError("Впишите в .env SECRET_KEY длиной от 50 символов (как его получить — в .env.example).")

# Django-админка — только на секретном адресе вида manage-<не меньше 12 случайных символов>/.
# Стандартный admin/ подбирают роботы; nginx пропускает к Django-админке только /manage-.../
if not re.fullmatch(r"manage-[A-Za-z0-9_-]{12,}/", DJANGO_ADMIN_URL):  # noqa: F405
    raise RuntimeError(
        "Впишите в .env секретный адрес Django-админки, например DJANGO_ADMIN_URL=manage-" + secrets.token_urlsafe(12) + "/"
    )

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

# ---------- ЗАЩИТА ----------
SECURE_CONTENT_TYPE_NOSNIFF = True              # браузер не «угадывает» тип файла (нельзя выдать картинку за скрипт)
SECURE_REFERRER_POLICY = "same-origin"          # адреса нашего сайта не утекают на чужие сайты
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"                        # сайт нельзя встроить в чужую страницу (защита от «подставных» кнопок)
SESSION_COOKIE_HTTPONLY = True                  # куки входа в Django-админку недоступны скриптам на странице
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"                 # чужой сайт не отправит запрос «от имени» вошедшего админа
SECURE_SSL_REDIRECT = USE_HTTPS                 # с https: все запросы по http автоматически переводим на https
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30 if USE_HTTPS else 0   # браузер 30 дней открывает сайт только по https

# Swagger (документация API) на сервере видят только админы, вошедшие в Django-админку
SPECTACULAR_SETTINGS = {**SPECTACULAR_SETTINGS, "SERVE_PERMISSIONS": ["core.permissions.IsCafeAdmin"]}  # noqa: F405

# Запрос без файлов не больше 2 МБ, фото — до 5 МБ (это же ограничение стоит и в nginx)
DATA_UPLOAD_MAX_MEMORY_SIZE = 2 * 1024 * 1024

# SQLite на сервере: ждём до 20 секунд, если база занята другим запросом, а не падаем с ошибкой
DATABASES["default"]["OPTIONS"] = {"timeout": 20, "transaction_mode": "IMMEDIATE"}  # noqa: F405

# Ошибки сервера пишем в журнал (смотреть: journalctl -u muslim)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "WARNING"},
}