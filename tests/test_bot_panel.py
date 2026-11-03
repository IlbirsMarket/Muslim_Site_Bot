"""Бот сотрудников ходит в тот же API, что и панель сайта (apps/bot/panel_api.py): права, филиалы, фото."""

from io import BytesIO                                        # картинка в памяти

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from PIL import Image                                         # нарисовать тестовое фото

from apps.bot.panel_api import call
from apps.bot.telegram.handlers import cafe_rows
from apps.bot.telegram.panel import name_and_price, parse
from apps.cafe.models import Branch
from apps.menu.models import Category
from tests.test_api import TEMP_MEDIA, BaseAPITest


def jpeg() -> SimpleUploadedFile:
    """Маленькое настоящее JPEG-фото (как пришлёт Telegram)."""
    buffer = BytesIO()
    Image.new("RGB", (40, 30), "orange").save(buffer, "JPEG")
    return SimpleUploadedFile("photo.jpg", buffer.getvalue(), content_type="image/jpeg")


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class PanelApiTests(BaseAPITest):

    def setUp(self):
        super().setUp()
        self.b2 = Branch.objects.create(name="Таширов", position=20)
        self.soups = Category.objects.create(branch=self.b2, name="Супы")

    def test_same_rights_as_site(self):
        """Повар не может менять меню, админ — может; ошибки — понятным текстом."""
        result = call(self.cook, "post", "/admin/categories/", {"name": "Салаты"})
        self.assertEqual(result.status, 403)
        result = call(self.admin, "post", "/admin/categories/", {"name": "Салаты"})
        self.assertTrue(result.ok)
        result = call(self.admin, "post", "/admin/categories/", {"name": ""})
        self.assertEqual(result.status, 400)
        self.assertTrue(result.error)

    def test_branch_for_chef(self):
        """Шеф выбирает филиал (как X-Branch на сайте); админ всегда в своём, чужое — «не найдено»."""
        result = call(self.chef, "get", "/admin/categories/", branch=self.b2.id)
        self.assertEqual([c["name"] for c in result.data], ["Супы"])
        result = call(self.chef, "post", "/admin/categories/", {"name": "Плов"}, branch=self.b2.id)
        self.assertEqual(Category.objects.get(pk=result.data["id"]).branch, self.b2)
        result = call(self.admin, "get", f"/admin/categories/{self.soups.id}/", branch=self.b2.id)   # админ Кара-Суу
        self.assertEqual(result.status, 404)
        self.assertIn("Не найдено", result.error)

    def test_photo_upload(self):
        """Фото из Telegram сохраняется так же, как с сайта (в WebP)."""
        result = call(self.admin, "patch", f"/admin/dishes/{self.burger.id}/", {"photo": jpeg()}, multipart=True)
        self.assertTrue(result.ok, result.data)
        self.burger.refresh_from_db()
        self.assertTrue(self.burger.photo.name.endswith(".webp"))

    def test_files(self):
        """QR-картинка и PDF приходят байтами."""
        result = call(self.admin, "get", f"/admin/tables/{self.table.id}/qr/")
        self.assertEqual(result.content_type, "image/png")
        self.assertTrue(result.content.startswith(b"\x89PNG"))
        result = call(self.admin, "get", "/admin/tables/qr-pdf/")
        self.assertTrue(result.content.startswith(b"%PDF"))

    def test_cafe_sections_by_role(self):
        """Разделы «Кафе» — как меню панели на сайте (canAccess в admin.js)."""
        labels = lambda user: [t for row in cafe_rows(user) for t, _ in row]
        main = ["🧾 Заказы", "🍽 Блюда и категории", "🪑 Столы и QR", "👥 Пользователи и роли", "📊 Отчёты", "⚙️ Настройки"]
        self.assertEqual(labels(self.admin)[:6], main)
        self.assertNotIn("⇄ Сменить филиал", labels(self.admin))
        self.assertIn("⇄ Сменить филиал", labels(self.chef))
        self.assertEqual(labels(self.cook)[:2], ["🧾 Заказы", "🍽 Блюда и категории"])      # повар — стоп-лист
        self.assertEqual(labels(self.waiter)[:2], ["🧾 Заказы", "🪑 Столы и QR"])          # официант — столы
        self.assertNotIn("👥 Пользователи и роли", labels(self.waiter))

    def test_parsing(self):
        """Ответы сотрудника: числа, время, «название цена»."""
        self.assertEqual(parse("int", "1 200 сом"), 1200)
        self.assertEqual(parse("time", "9.30"), "09:30")
        self.assertIsNone(parse("tgid", "-"))
        self.assertEqual(name_and_price("30 см 650"), ("30 см", 650))
        self.assertEqual(name_and_price("Сыр — 80"), ("Сыр", 80))
        with self.assertRaises(ValueError):
            parse("time", "25:00")
        with self.assertRaises(ValueError):
            name_and_price("Сыр")
