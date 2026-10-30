"""
Отчёт за сегодня (текст + PDF) в тему «Отчёты» группы каждого филиала.
Запуск: python manage.py send_day_report  (на сервере — каждый вечер, таймер systemd muslim-day-report.timer)
"""

import asyncio                                               # отправка асинхронная

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def collect() -> list:
    """[(группа, тема, текст, pdf, имя файла)] для филиалов с настроенной группой."""
    from django.utils import timezone
    from apps.bot.texts import money
    from apps.cafe.models import Branch
    from apps.reports.builder import build_day_report
    from apps.reports.pdf import render_day_pdf
    result = []
    for branch in Branch.objects.filter(is_active=True).exclude(tg_group_id=None):
        data = build_day_report(timezone.localdate(), branch)
        text = (f"📊 <b>Отчёт за {data['date']:%d.%m.%Y}</b> · {data['branch_name']}\n"
                f"Выручка: <b>{money(data['revenue'])}</b>\nЗаказов: {data['orders_count']} · средний чек {money(data['avg_check'])}\n"
                f"Отменено: {data['cancelled_count']}")
        result.append((branch.tg_group_id, branch.tg_topic_reports, text, render_day_pdf(data), f"otchet-{data['date']:%Y-%m-%d}.pdf"))
    return result


class Command(BaseCommand):
    help = "Отправить отчёт за день в Telegram (тема «Отчёты» каждого филиала)"

    def handle(self, *args, **options):
        if not settings.TELEGRAM_STAFF_BOT_TOKEN:
            raise CommandError("Нет TELEGRAM_STAFF_BOT_TOKEN в .env.")
        reports = collect()
        asyncio.run(self.send(reports))
        self.stdout.write(self.style.SUCCESS(f"Отправлено отчётов: {len(reports)}"))

    async def send(self, reports):
        from aiogram import Bot
        from aiogram.client.default import DefaultBotProperties
        from aiogram.enums import ParseMode
        from aiogram.types import BufferedInputFile
        async with Bot(settings.TELEGRAM_STAFF_BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)) as bot:
            for chat, thread, text, pdf, name in reports:
                await bot.send_document(chat, BufferedInputFile(pdf, filename=name), caption=text, message_thread_id=thread)
