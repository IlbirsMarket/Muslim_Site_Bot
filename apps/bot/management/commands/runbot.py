"""
Запуск Telegram-бота: python manage.py runbot
Бот работает с той же базой, что и сайт. Остановить — Ctrl+C.
Запускать только в ОДНОМ месте (или на сервере, или на компьютере) — иначе Telegram выдаст ошибку «Conflict».
"""

import asyncio                                               # бот асинхронный
import logging                                               # сообщения о работе в консоль

from django.conf import settings                             # токен из .env
from django.core.management.base import BaseCommand, CommandError   # своя команда manage.py


class Command(BaseCommand):
    help = "Запустить Telegram-бота кафе «Муслим»"

    def handle(self, *args, **options):
        if not settings.TELEGRAM_BOT_TOKEN:                  # без токена бот не запустится
            raise CommandError("Нет TELEGRAM_BOT_TOKEN в .env. Возьмите токен у @BotFather и впишите в .env.")
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        asyncio.run(self.main())

    async def main(self):
        from aiogram import Bot, Dispatcher                  # импорт здесь: тестам сайта aiogram не нужен
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.types import BotCommand

        from apps.bot.telegram.handlers import group_router, router

        bot = Bot(settings.TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))   # жирный текст через <b>
        dp = Dispatcher()                                    # «диспетчер»: раздаёт сообщения обработчикам
        dp.include_routers(router, group_router)
        await bot.set_my_commands([                          # меню команд в Telegram (кнопка «/»)
            BotCommand(command="start", description="Главное меню"),
            BotCommand(command="login", description="Войти как сотрудник"),
            BotCommand(command="menu", description="Меню кафе"),
            BotCommand(command="me", description="Мой профиль"),
            BotCommand(command="logout", description="Выйти"),
        ])
        me = await bot.get_me()
        self.stdout.write(self.style.SUCCESS(f"Бот @{me.username} запущен. Остановить — Ctrl+C."))
        await dp.start_polling(bot)                          # бот сам спрашивает Telegram о новых сообщениях