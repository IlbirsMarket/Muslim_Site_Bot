"""Демо-база (seed_demo): заполняется «как настоящее кафе», фото — со свободной лицензией; на настоящей базе — отказ."""

import json                                                    # поддельный ответ Wikimedia
import tempfile                                                # временная папка для фото
from io import BytesIO
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from PIL import Image

from apps.menu.management.commands.seed_demo import Command
from apps.menu.models import Dish
from apps.orders.models import Order
from apps.tables.models import Table
from apps.users.models import User

MEDIA = tempfile.mkdtemp()


def jpeg() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (8, 8), "orange").save(buffer, "JPEG")
    return buffer.getvalue()


def fake_fetch(url):
    """Wikimedia без интернета: первый результат — несвободная лицензия (пропускается), второй — CC BY-SA."""
    if "api.php" in url:
        return json.dumps({"query": {"pages": {
            "1": {"index": 1, "title": "File:Closed.jpg", "imageinfo": [{"mime": "image/jpeg", "thumburl": "https://x/closed.jpg",
                  "extmetadata": {"LicenseShortName": {"value": "All rights reserved"}}}]},
            "2": {"index": 2, "title": "File:Food.jpg", "imageinfo": [{"mime": "image/jpeg", "thumburl": "https://x/food.jpg", "descriptionurl": "https://commons/Food",
                  "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<a href='#'>Повар</a>"}}}]},
        }}}).encode()
    assert "closed" not in url                                  # несвободное фото не скачиваем
    return jpeg()


@override_settings(DEBUG=True, DEMO=True, MEDIA_ROOT=MEDIA)
class SeedDemoTests(TestCase):

    def test_demo_like_real_cafe(self):
        with mock.patch.object(Command, "fetch", staticmethod(fake_fetch)):
            call_command("seed_demo")
        self.assertEqual(User.objects.filter(username__startswith="demo_").count(), 8)
        self.assertEqual(Order.objects.exclude(status__in=["completed", "cancelled"]).count(), 7)   # во всех колонках
        self.assertGreater(Order.objects.filter(status="completed").count(), 300)               # история для отчётов
        self.assertTrue(Dish.objects.filter(is_available=False).exists())                        # есть стоп-лист
        self.assertTrue(all(d.photo for d in Dish.objects.all()))                                # у всех блюд фото
        self.assertIn("CC BY-SA 4.0", (Path(MEDIA) / "АВТОРЫ-ФОТО.txt").read_text(encoding="utf-8"))
        self.assertTrue(Table.objects.filter(occupied_since__isnull=False).exists())             # заняты столы
        call_command("seed_demo", "--no-photos")                                                  # повторный запуск — с чистого листа
        self.assertEqual(Order.objects.exclude(status__in=["completed", "cancelled"]).count(), 7)

    @override_settings(DEMO=False)
    def test_refuses_on_real_database(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo", "--no-photos")
