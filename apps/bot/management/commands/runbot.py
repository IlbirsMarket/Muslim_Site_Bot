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
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", force=True)   # force — поверх настроек Django: запуск и ошибки бота видны в journalctl
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
            from apps.bot.telegram.panel import panel_router
            dp.include_routers(panel_router, staff_router, router, group_router)   # панель и кнопки ролей — раньше «Не понял»
            commands = [("start", "Главное меню")]
            worker = run_notifier(bot)                       # события сайта → группа
        else:
            from apps.bot.telegram.guest import guest_router, run_guest_notifier
            dp.include_router(guest_router)
            commands = [("start", "Меню и заказ")]
            worker = run_guest_notifier(bot, storage=dp.storage)   # статусы заказов гостям и «стол освобождён»
        await bot.set_my_commands([BotCommand(command=c, description=d) for c, d in commands])
        await self.menu_button(bot, kind)
        me = await bot.get_me()
        self.stdout.write(self.style.SUCCESS(f"Бот @{me.username} запущен. Остановить — Ctrl+C."))
        self.stdout.flush()                                  # сразу в журнал (иначе systemd покажет строку только при остановке)
        task = asyncio.create_task(worker)                   # рассылка работает параллельно с ответами
        try:
            await dp.start_polling(bot)                      # бот сам спрашивает Telegram о новых сообщениях
        finally:
            task.cancel()

    async def menu_button(self, bot, kind):
        """Кнопка слева от поля ввода в чате бота: открывает мини-приложение (панель персонала / меню гостя). Без https — обычное меню команд."""
        from aiogram.types import MenuButtonCommands, MenuButtonWebApp, WebAppInfo
        from apps.bot.telegram.screen import mini_app_url
        url = mini_app_url("/admin" if kind == "staff" else "/")
        try:
            if url:
                await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(text="Панель" if kind == "staff" else "Меню", web_app=WebAppInfo(url=url)))
            else:
                await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
        except Exception as error:                            # кнопка — удобство, бот работает и без неё
            self.stderr.write(f"Кнопка мини-приложения не установлена: {error}")
