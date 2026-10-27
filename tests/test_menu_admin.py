"""
Раздел «Блюда и категории»: порядок, число блюд, названия, проверка фото.
Запуск: python manage.py test tests -v 2
"""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile   # «файл» для теста загрузки
from PIL import Image                                          # рисуем маленькую картинку

from apps.menu.models import Category
from tests.test_api import BaseAPITest

CATS = "/api/admin/categories/"


def picture(fmt, name):
    """Маленькая картинка 10×10 в нужном формате, как будто её выбрали на компьютере."""
    buffer = BytesIO()
    Image.new("RGB", (10, 10), "green").save(buffer, fmt)
    return SimpleUploadedFile(name, buffer.getvalue())


class CategoryTests(BaseAPITest):

    def test_count_and_reorder(self):
        self.as_user(self.admin)
        cats = {c["name"]: c for c in self.client.get(CATS).data}
        self.assertEqual(cats["Пиццы"]["dishes_count"], 1)
        self.assertEqual(cats["Бургеры"]["dishes_count"], 2)

        response = self.client.post(f"{CATS}reorder/", {"ids": [self.burgers.id, self.pizzas.id]}, format="json")
        self.assertEqual(response.status_code, 200)
        self.as_user(None)
        names = [c["name"] for c in self.client.get("/api/menu/").data]
        self.assertEqual(names, ["Бургеры", "Пиццы"])                    # гости видят новый порядок

    def test_reorder_needs_all(self):
        self.as_user(self.admin)
        self.assertEqual(self.client.post(f"{CATS}reorder/", {"ids": [self.pizzas.id]}, format="json").status_code, 400)

    def test_new_category_goes_last_and_names_unique(self):
        self.as_user(self.admin)
        created = self.client.post(CATS, {"name": "Супы"}, format="json").data
        self.assertGreater(created["position"], Category.objects.get(name="Бургеры").position)
        self.assertEqual(self.client.post(CATS, {"name": "  супы "}, format="json").status_code, 400)

    def test_waiter_cannot_reorder(self):
        self.as_user(self.waiter)
        self.assertEqual(self.client.post(f"{CATS}reorder/", {"ids": []}, format="json").status_code, 403)


class DishPhotoTests(BaseAPITest):

    def upload(self, file):
        self.as_user(self.admin)
        return self.client.patch(f"/api/admin/dishes/{self.burger.id}/", {"photo": file}, format="multipart")

    def test_png_accepted(self):
        self.assertEqual(self.upload(picture("PNG", "burger.png")).status_code, 200)

    def test_gif_rejected(self):
        response = self.upload(picture("GIF", "burger.gif"))
        self.assertEqual(response.status_code, 400)
        self.assertIn("photo", response.data)

    def test_fake_image_rejected(self):
        response = self.upload(SimpleUploadedFile("virus.jpg", b"not really a picture"))
        self.assertEqual(response.status_code, 400)                       # расширение .jpg, а внутри не картинка