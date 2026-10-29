"""
Проверка входа сотрудника: email или логин, «Запомнить меня», защита от подбора.
Запуск: python manage.py test tests -v 2
"""

from django.utils import timezone                          # текущее время
from rest_framework_simplejwt.tokens import RefreshToken   # чтобы прочитать срок токена

from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest           # общая подготовка из основного теста

LOGIN = "/api/auth/login/"                                 # адрес входа


class LoginTests(BaseAPITest):

    def setUp(self):
        super().setUp()
        self.cook.email = "Cook@Muslim.kg"                 # сохранится как cook@muslim.kg
        self.cook.save()

    def login(self, username, password=PASSWORD, **extra):
        """Пробуем войти и возвращаем ответ сервера."""
        return self.client.post(LOGIN, {"username": username, "password": password, **extra}, format="json")

    @staticmethod
    def hours_left(response):
        """Сколько часов осталось жить токену обновления."""
        exp = RefreshToken(response.data["refresh"])["exp"]
        return (exp - timezone.now().timestamp()) / 3600

    def test_email_saved_lowercase(self):
        self.cook.refresh_from_db()
        self.assertEqual(self.cook.email, "cook@muslim.kg")

    def test_login_by_email_any_case(self):
        response = self.login("  COOK@muslim.KG ")                  # пробелы и большие буквы не мешают
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        me = self.client.get("/api/auth/me/").data
        self.assertEqual(me["role"], "cook")
        self.assertEqual(me["email"], "cook@muslim.kg")

    def test_login_by_username_still_works(self):
        self.assertEqual(self.login("cook").status_code, 200)

    def test_wrong_password_russian_message(self):
        response = self.login("cook@muslim.kg", "wrong-password")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.data["detail"], "Неверный email/логин или пароль.")
        self.assertEqual(self.login("nobody@muslim.kg").status_code, 401)   # такого email нет

    def test_blocked_user_cannot_login_by_email(self):
        self.cook.is_active = False
        self.cook.save()
        self.assertEqual(self.login("cook@muslim.kg").status_code, 401)

    def test_remember_me_lifetime(self):
        short = self.login("cook")                                     # без галочки
        self.assertFalse(short.data["remember"])
        self.assertLess(self.hours_left(short), 13)                    # около 12 часов
        long = self.login("cook", remember=True)                       # с галочкой
        self.assertTrue(long.data["remember"])
        self.assertGreater(self.hours_left(long), 6.9 * 24)            # около 7 дней

    def test_refresh_works(self):
        refresh = self.login("cook", remember=True).data["refresh"]
        response = self.client.post("/api/auth/refresh/", {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)

    def test_too_many_attempts(self):
        codes = [self.login("cook", "wrong-password").status_code for _ in range(6)]
        self.assertEqual(codes[-1], 429)                               # после 5 ошибок — «подождите 15 минут»

    def test_email_must_be_unique(self):
        self.as_user(self.admin)
        response = self.client.post("/api/admin/staff/", {
            "username": "cook2", "email": "COOK@muslim.kg", "password": PASSWORD, "role": "cook",
        }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("email", response.data)
        ok = self.client.post("/api/admin/staff/", {                   # пустой email можно у многих
            "username": "cook3", "password": PASSWORD, "role": "cook",
        }, format="json")
        self.assertEqual(ok.status_code, 201)
        self.assertGreaterEqual(User.objects.filter(email="").count(), 2)