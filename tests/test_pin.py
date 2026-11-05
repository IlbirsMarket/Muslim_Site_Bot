"""
Вход по коду из 2 цифр (как в 1С) — только на «запомненном» устройстве.
Запуск: python manage.py test tests -v 2
"""

from django.core.cache import cache

from apps.users.models import TrustedDevice
from tests.test_api import PASSWORD, BaseAPITest      # общая подготовка из основного теста

POS = "kassa-" + "a" * 40                             # ключ кассового компьютера (в браузере — случайный)
PHONE = "phone-" + "b" * 40                           # чужой телефон


class PinLoginTests(BaseAPITest):

    def setUp(self):
        super().setUp()
        cache.clear()                                 # счётчики ошибок с прошлых тестов
        self.waiter.pin = "66"
        self.waiter.save()

    def login(self, user, device=POS):
        """Вход по логину и паролю на устройстве — после него устройство запомнено."""
        self.as_user(None)
        return self.client.post("/api/auth/login/", {"username": user.username, "password": PASSWORD, "device": device}, format="json")

    def pin(self, code, device=POS):
        self.as_user(None)
        return self.client.post("/api/auth/pin/", {"device": device, "pin": code}, format="json")

    def test_pin_works_only_after_password_on_this_device(self):
        self.assertEqual(self.pin("66").status_code, 403)                     # тут ещё никто не входил по паролю
        self.assertEqual(self.login(self.waiter).status_code, 200)
        response = self.pin("66")
        self.assertEqual(response.status_code, 200, response.data)            # теперь хватает кода
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(self.client.get("/api/auth/me/").data["username"], "waiter")
        self.assertEqual(self.pin("66", PHONE).status_code, 403)              # с чужого телефона — нет

    def test_code_of_someone_who_never_logged_in_here(self):
        self.login(self.waiter)
        self.admin.pin = "77"
        self.admin.save()
        self.assertEqual(self.pin("77").status_code, 403)                     # админ здесь по паролю не входил

    def test_wrong_codes_lock_device(self):
        self.login(self.waiter)
        for _ in range(5):
            self.assertEqual(self.pin("12").status_code, 401)
        self.assertEqual(self.pin("66").status_code, 429)                     # 5 ошибок — пауза, даже верный код

    def test_password_change_forgets_devices(self):
        self.login(self.waiter)
        self.waiter.set_password("NewPass2026!")
        self.waiter.save()
        self.assertEqual(self.pin("66").status_code, 403)                     # сменили пароль — снова пароль
        self.assertEqual(TrustedDevice.objects.count(), 1)

    def test_blocked_waiter_cannot_use_code(self):
        self.login(self.waiter)
        self.waiter.is_active = False
        self.waiter.save()
        self.assertEqual(self.pin("66").status_code, 401)

    def test_admin_sets_code_unique_two_digits(self):
        self.as_user(self.admin)
        url = f"/api/admin/staff/{self.cook.id}/"
        self.assertEqual(self.client.patch(url, {"pin": "66"}, format="json").status_code, 400)    # занят официантом
        self.assertEqual(self.client.patch(url, {"pin": "7"}, format="json").status_code, 400)     # одна цифра
        self.assertEqual(self.client.patch(url, {"pin": "77"}, format="json").status_code, 200)
        self.cook.refresh_from_db()
        self.assertEqual(self.cook.pin, "77")
        self.assertEqual(self.client.patch(url, {"pin": ""}, format="json").status_code, 200)      # убрать код
        self.cook.refresh_from_db()
        self.assertIsNone(self.cook.pin)
        chef = next(s for s in self.client.get("/api/admin/staff/").data if s["id"] == self.chef.id)
        self.assertIsNone(chef["pin"])                                        # код шефа админу не виден

    def test_chef_sets_own_code(self):
        self.as_user(self.chef)
        self.assertEqual(self.client.post("/api/auth/me/pin/", {"pin": "66"}, format="json").status_code, 400)
        self.assertEqual(self.client.post("/api/auth/me/pin/", {"pin": "99"}, format="json").data["pin"], "99")
        self.assertEqual(self.client.get("/api/auth/me/").data["pin"], "99")
        self.login(self.chef)
        self.assertEqual(self.pin("99").status_code, 200)                     # шеф тоже входит по коду
