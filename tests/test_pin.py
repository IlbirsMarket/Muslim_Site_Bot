"""
Вход в панель только по коду сотрудника (от 2 до 8 цифр). Логина и пароля на сайте нет.
Запуск: python manage.py test tests -v 2
"""

from django.core.cache import cache
from django.test import override_settings

from apps.users.models import TrustedDevice, User
from apps.users.pin_login import NEW_DEVICES_LIMIT
from tests.test_api import PASSWORD, BaseAPITest      # общая подготовка из основного теста

POS = "kassa-" + "a" * 40                             # ключ кассового компьютера (в браузере — случайный)


@override_settings(PIN_LOGIN=True)                    # вход по коду пока выключен на сайте — включаем для проверки
class PinLoginTests(BaseAPITest):

    def setUp(self):
        super().setUp()
        cache.clear()                                 # счётчики ошибок с прошлых тестов
        self.waiter.set_pin("77")
        self.waiter.save()
        self.cashier = User.objects.create_user("cashier", password=PASSWORD, role=User.Role.CASHIER)
        self.cashier.set_pin("11")
        self.cashier.save()

    def pin(self, code, device=POS, ip="10.0.0.1"):
        self.as_user(None)
        return self.client.post("/api/auth/pin/", {"device": device, "pin": code}, format="json", REMOTE_ADDR=ip)

    def test_code_works_on_any_device(self):
        response = self.pin("77", device="phone-" + "b" * 40)
        self.assertEqual(response.status_code, 200, response.data)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(self.client.get("/api/auth/me/").data["username"], "waiter")
        self.assertEqual(self.pin("11").status_code, 200)                     # на одном компьютере — разные сотрудники

    def test_code_not_stored_and_not_shown(self):
        self.assertNotEqual(User.objects.get(pk=self.waiter.pk).pin_hash, "77")   # в базе только отпечаток
        self.as_user(self.admin)
        row = next(s for s in self.client.get("/api/admin/staff/").data if s["id"] == self.waiter.id)
        self.assertNotIn("pin", row)                                          # админ кода не видит
        self.assertTrue(row["has_pin"])

    @override_settings(PASSWORD_LOGIN=False)
    def test_password_login_disabled(self):
        self.as_user(None)
        response = self.client.post("/api/auth/login/", {"username": "waiter", "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_code_length_not_revealed(self):
        for code in ["7", "7777", "123456789", "ab"]:
            response = self.pin(code, ip=f"10.0.1.{len(code)}")
            self.assertEqual(response.status_code, 401)                       # всегда просто «Неверный код»
            self.assertTrue(str(response.data["detail"]).startswith("Неверный код"))

    def test_wrong_codes_lock_ip(self):
        for _ in range(5):
            self.assertEqual(self.pin("12", device="new-" + "c" * 40).status_code, 401)
        self.assertEqual(self.pin("77", device="new-" + "c" * 40).status_code, 429)   # 5 ошибок с IP — пауза
        self.assertEqual(self.pin("77", ip="10.0.0.2").status_code, 200)               # с другого места — можно

    def test_mass_guessing_closes_new_devices_only(self):
        self.assertEqual(self.pin("77").status_code, 200)                     # касса — своё устройство
        for i in range(NEW_DEVICES_LIMIT):
            self.pin("12", device=f"bad{i}-" + "d" * 40, ip=f"10.9.{i}.1")
        self.assertEqual(self.pin("77", device="new-" + "e" * 40, ip="10.8.0.1").status_code, 429)   # новые — закрыто
        self.assertEqual(self.pin("11").status_code, 200)                     # своя касса работает
        self.assertTrue(TrustedDevice.objects.exists())

    def test_blocked_staff_cannot_use_code(self):
        self.waiter.is_active = False
        self.waiter.save()
        self.assertEqual(self.pin("77").status_code, 401)

    def test_admin_creates_staff_with_code(self):
        self.as_user(self.admin)
        body = {"username": "cook9", "password": PASSWORD, "role": "cook", "first_name": "Айбек"}
        self.assertEqual(self.client.post("/api/admin/staff/", body, format="json").status_code, 400)            # без кода — нельзя
        self.assertEqual(self.client.post("/api/admin/staff/", {**body, "pin": "77"}, format="json").status_code, 400)   # занят
        created = self.client.post("/api/admin/staff/", {**body, "pin": "583920"}, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        self.assertNotIn("pin", created.data)
        self.assertEqual(self.pin("583920").status_code, 200)

    def test_admin_changes_code_blank_keeps_old(self):
        self.as_user(self.admin)
        url = f"/api/admin/staff/{self.cook.id}/"
        self.assertEqual(self.client.patch(url, {"pin": "1"}, format="json").status_code, 400)       # одна цифра
        self.assertEqual(self.client.patch(url, {"pin": "123456789"}, format="json").status_code, 400)   # 9 цифр
        self.assertEqual(self.client.patch(url, {"pin": "4321"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch(url, {"pin": "", "phone": "+996"}, format="json").status_code, 200)   # пусто — не меняем
        self.assertEqual(self.pin("4321").status_code, 200)

    def test_staff_sets_own_code(self):
        self.as_user(self.chef)
        self.assertEqual(self.client.post("/api/auth/me/pin/", {"pin": "77"}, format="json").status_code, 400)   # занят
        self.assertEqual(self.client.post("/api/auth/me/pin/", {"pin": "9090"}, format="json").status_code, 200)
        self.assertTrue(self.client.get("/api/auth/me/").data["has_pin"])
        self.assertEqual(self.pin("9090").status_code, 200)                   # шеф тоже входит по коду


class PinLoginOffTests(BaseAPITest):
    """Сейчас (по умолчанию) вход по коду выключен: работает только логин и пароль."""

    def test_pin_endpoints_off_and_password_works(self):
        self.waiter.set_pin("77")
        self.waiter.save()
        self.as_user(None)
        self.assertEqual(self.client.post("/api/auth/pin/", {"pin": "77"}, format="json").status_code, 404)
        login = self.client.post("/api/auth/login/", {"username": "waiter", "password": PASSWORD}, format="json")
        self.assertEqual(login.status_code, 200)
        self.as_user(self.admin)
        created = self.client.post("/api/admin/staff/", {"username": "cook9", "password": PASSWORD, "role": "cook"}, format="json")
        self.assertEqual(created.status_code, 201)                            # без кода — можно
