"""
Запуск ботов:
  python manage.py runbot                — бот сотрудников (заказы в группу, кнопки, стоп-лист, столы, отчёт)
  python manage.py runbot --bot guest    — бот для гостей (меню, корзина, заказ, статусы)
Каждый бот запускать только в ОДНОМ месте — иначе Telegram выдаст ошибку «Conflict».
"""

import asyncio                                               # боты асинхронные
import logging                                               # сообщения о работе в консоль

from django.conf import settings                             # токены из .env
from django.core.management.base import BaseCommand, CommandError   # своя команда manage.py


class Command(BaseCommand):
    help = "Запустить Telegram-бота кафе «Муслим» (сотрудников или гостей)"

    def add_arguments(self, parser):
        parser.add_argument("--bot", choices=["staff", "guest"], default="staff", help="какой бот запустить")

    def handle(self, *args, **options):
        kind = options["bot"]
        token = settings.TELEGRAM_STAFF_BOT_TOKEN if kind == "staff" else settings.TELEGRAM_GUEST_BOT_TOKEN
        if not token:                                        # без токена бот не запустится
            name = "TELEGRAM_STAFF_BOT_TOKEN" if kind == "staff" else "TELEGRAM_GUEST_BOT_TOKEN"
            raise CommandError(f"Нет {name} в .env. Возьмите токен у @BotFather и впишите в .env.")
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        asyncio.run(self.main(kind, token))

    async def main(self, kind, token):
        from aiogram import Bot, Dispatcher                  # импорт здесь: тестам сайта aiogram не нужен
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.types import BotCommand

        bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))   # жирный текст через <b>
        dp = Dispatcher()                                    # «диспетчер»: раздаёт сообщения обработчикам
        if kind == "staff":
            from apps.bot.notify import run_notifier
            from apps.bot.telegram.handlers import group_router, router
            from apps.bot.telegram.staff import staff_router
            dp.include_routers(staff_router, router, group_router)   # кнопки ролей — раньше «Не понял»
            commands = [("start", "Главное меню"), ("login", "Войти как сотрудник"), ("menu", "Меню кафе"),
                        ("me", "Мой профиль"), ("logout", "Выйти")]
            worker = run_notifier(bot)                       # события сайта → группа
        else:
            from apps.bot.telegram.guest import guest_router, run_guest_notifier
            dp.include_router(guest_router)
            commands = [("start", "Меню и заказ")]
            worker = run_guest_notifier(bot)                 # статусы заказов гостям
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in commands])
        me = await bot.get_me()
        self.stdout.write(self.style.SUCCESS(f"Бот @{me.username} запущен. Остановить — Ctrl+C."))
        task = asyncio.create_task(worker)                   # рассылка работает параллельно с ответами
        try:
            await dp.start_polling(bot)                      # бот сам спрашивает Telegram о новых сообщениях
        finally:
            task.cancel()
