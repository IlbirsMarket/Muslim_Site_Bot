"""
Отправить последнюю ночную копию в Telegram (группа / тема «Архив»).
Запуск: python manage.py send_backup  — на сервере сразу после backup-db.sh (в том же cron).
Копия базы — всегда; архив фото — только если меньше 50 МБ (больше Telegram-бот не принимает).
В копии есть телефоны и адреса гостей — группа «Архив» должна быть закрытой: только шеф и программист.
"""

import asyncio                                               # отправка асинхронная
from pathlib import Path                                     # поиск файлов копий

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

TELEGRAM_LIMIT = 50 * 1024 * 1024                            # бот может отправить файл до 50 МБ


def latest(folder: Path, pattern: str):
    """Самый свежий файл по шаблону (или None)."""
    files = sorted(folder.glob(pattern), key=lambda f: f.stat().st_mtime)
    return files[-1] if files else None


class Command(BaseCommand):
    help = "Отправить последнюю копию базы (и фото, если влезает) в Telegram-группу «Архив»"

    def handle(self, *args, **options):
        if not settings.TELEGRAM_STAFF_BOT_TOKEN or not settings.TELEGRAM_ARCHIVE_CHAT_ID:
            raise CommandError("Нужны TELEGRAM_STAFF_BOT_TOKEN и TELEGRAM_ARCHIVE_CHAT_ID в .env.")
        folder = Path(settings.BACKUP_DIR)
        db = latest(folder, "db-*.sqlite3.gz")
        if db is None:
            raise CommandError(f"В {folder} нет копий базы. Сначала запустите backup-db.sh.")
        files = [db]
        media = latest(folder, "media-*.tar.gz")
        note = ""
        if media and media.stat().st_size <= TELEGRAM_LIMIT:
            files.append(media)
        elif media:
            note = f"\nФото ({media.stat().st_size // 1024 // 1024} МБ) больше 50 МБ — остались только на сервере."
        asyncio.run(self.send(files, note))
        self.stdout.write(self.style.SUCCESS("Отправлено: " + ", ".join(f.name for f in files)))

    async def send(self, files, note):
        from aiogram import Bot
        from aiogram.types import FSInputFile
        thread = settings.TELEGRAM_ARCHIVE_TOPIC_ID or None
        async with Bot(settings.TELEGRAM_STAFF_BOT_TOKEN) as bot:
            for n, path in enumerate(files):
                size = path.stat().st_size / 1024 / 1024
                caption = f"🗄 Копия: {path.name} ({size:.1f} МБ)" + (note if n == len(files) - 1 else "")
                await bot.send_document(settings.TELEGRAM_ARCHIVE_CHAT_ID, FSInputFile(path), caption=caption,
                                        message_thread_id=thread, disable_notification=True)   # без звука — ночью
