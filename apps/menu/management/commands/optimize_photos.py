"""
Перевести уже загруженные фото блюд в лёгкий WebP (один раз после обновления).
Запуск: python manage.py optimize_photos  — старые тяжёлые файлы удаляются, в меню подставляются новые.
"""

from django.core.management.base import BaseCommand

from apps.menu.models import Dish
from core.images import to_webp


class Command(BaseCommand):
    help = "Уменьшить и перевести фото блюд в WebP"

    def handle(self, *args, **options):
        done = saved = 0
        for dish in Dish.objects.exclude(photo="").exclude(photo__endswith=".webp"):
            try:
                old_name, old_size = dish.photo.name, dish.photo.size
                with dish.photo.open("rb") as source:
                    new = to_webp(source)
                dish.photo.save(new.name, new, save=True)               # новый файл и ссылка в базе
                dish.photo.storage.delete(old_name)                     # старый тяжёлый файл больше не нужен
                done += 1
                saved += old_size - dish.photo.size
                self.stdout.write(f"✓ {dish.name}: {old_size // 1024} КБ → {dish.photo.size // 1024} КБ")
            except (OSError, ValueError) as error:                      # файла нет на диске или он испорчен
                self.stdout.write(self.style.WARNING(f"✗ {dish.name}: {error}"))
        self.stdout.write(self.style.SUCCESS(f"Готово: {done} фото, сэкономлено {saved // 1024} КБ"))
