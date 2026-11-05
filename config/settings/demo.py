"""
Демо-версия на своём компьютере: ОТДЕЛЬНАЯ база demo.sqlite3 и папка фото demo_media/.
Настоящая база (db.sqlite3) и сервер muslim-cafe.com не затрагиваются.
Запуск — двойной щелчок по demo.bat (или: python manage.py runserver 127.0.0.1:8001 --settings=config.settings.demo).
"""

from .dev import *  # noqa: F401,F403 — всё как при разработке

DEMO = True                                            # seed_demo работает только при этом флаге (защита настоящей базы)
DATABASES["default"]["NAME"] = BASE_DIR / "demo.sqlite3"   # noqa: F405 — отдельный файл базы
MEDIA_ROOT = BASE_DIR / "demo_media"                   # noqa: F405 — отдельная папка фото
TELEGRAM_STAFF_BOT_TOKEN = ""                          # демо не пишет в настоящие Telegram-группы
TELEGRAM_GUEST_BOT_TOKEN = ""
TELEGRAM_BOT_TOKEN = ""
