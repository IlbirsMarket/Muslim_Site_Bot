"""
Ключи для push-уведомлений. Запуск один раз: python manage.py make_vapid_keys
Две строки из вывода вписать в .env на сервере и перезапустить сайт и бота. Приватный ключ никому не показывать.
"""

from django.core.management.base import BaseCommand

from apps.bot.push import make_keys


class Command(BaseCommand):
    help = "Создать ключи VAPID для push-уведомлений (вписать в .env)"

    def handle(self, *args, **options):
        public, private = make_keys()
        self.stdout.write(f"VAPID_PUBLIC_KEY={public}\nVAPID_PRIVATE_KEY={private}")
