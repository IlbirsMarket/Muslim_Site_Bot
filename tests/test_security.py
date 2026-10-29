"""
Защита: вход и выход, отмена входов, подбор пароля, спам заказами, защита при запуске.
Запуск: python manage.py test tests.test_security -v 2
"""

from datetime import timedelta                                  # промежутки времени

from django.core.cache import cache                             # общий кэш (счётчики)
from django.core.management import call_command                 # запуск команды seed_demo
from django.core.management.base import CommandError            # ошибка команды
from django.test import override_settings                       # временно меняем настройки
from django.utils import timezone                               # текущее время
from rest_framework_simplejwt.tokens import RefreshToken        # прочитать ключ продления

from apps.bot.services import login_from_telegram
from apps.orders.limits import IP_LIMIT, phone_digits
from apps.menu.models import Extra
from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest                # общая подготовка: сотрудники, меню, столы

LOGIN, REFRESH, LOGOUT, ME = "/api/auth/login/", "/api/auth/refresh/", "/api/auth/logout/", "/api/auth/me/"


class SecurityBase(BaseAPITest):
    """Общие помощники: вход, запрос с токеном, продление."""

    def setUp(self):
        super().setUp()
        cache.clear()                                               # счётчики прошлых тестов не мешают

    def login(self, username="cook", password=PASSWORD, ip="10.0.0.1", **extra):
        """Вход с указанного IP. Возвращает ответ сервера."""
        return self.client.post(LOGIN, {"username": username, "password": password, **extra},
                                format="json", REMOTE_ADDR=ip)

    def me(self, access):
        """GET /me с этим токеном входа — код ответа."""
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        code = self.client.get(ME).status_code
        self.client.credentials()                                   # убираем заголовок
        return code

    def refresh(self, token):
        """Продление входа: ответ сервера."""
        return self.client.post(REFRESH, {"refresh": token}, format="json")


class TokenTests(SecurityBase):
    """Короткие токены, новый ключ при продлении, «Выйти», сроки входа."""

    def test_access_token_lives_15_minutes(self):
        data = self.login().data
        access = RefreshToken(data["refresh"]).access_token          # токен входа той же сессии
        minutes = (access["exp"] - timezone.now().timestamp()) / 60
        self.assertLessEqual(minutes, 15)                            # не больше 15 минут
        self.assertGreater(minutes, 14)

    def test_session_lifetimes(self):
        hours = lambda r: (RefreshToken(r.data["refresh"])["exp"] - timezone.now().timestamp()) / 3600
        self.assertLess(hours(self.login()), 12.1)                   # без галочки — смена (12 часов)
        long = hours(self.login(remember=True))                      # «Запомнить меня» — 7 дней
        self.assertGreater(long, 6.9 * 24)
        self.assertLess(long, 7.1 * 24)

    def test_refresh_rotates_and_old_key_dies(self):
        first = self.login(remember=True).data["refresh"]
        response = self.refresh(first)
        self.assertEqual(response.status_code, 200)
        second = response.data["refresh"]
        self.assertNotEqual(first, second)                           # выдан новый ключ
        self.assertEqual(self.me(response.data["access"]), 200)      # новый токен входа работает
        self.assertEqual(self.refresh(first).status_code, 401)       # старый ключ больше не принимают
        self.assertEqual(self.refresh(second).status_code, 200)      # а новый — да

    def test_refresh_keeps_original_expiry(self):
        first = self.login().data["refresh"]                         # вход на смену
        second = self.refresh(first).data["refresh"]
        old_exp = RefreshToken(first, verify=False)["exp"]           # старый ключ уже отменён — читаем без проверки
        self.assertEqual(RefreshToken(second)["exp"], old_exp)       # вход не продлевается бесконечно

    def test_logout_kills_refresh(self):
        token = self.login().data["refresh"]
        self.assertEqual(self.client.post(LOGOUT, {"refresh": token}, format="json").status_code, 204)
        self.assertEqual(self.refresh(token).status_code, 401)       # продлить вход уже нельзя
        self.assertEqual(self.client.post(LOGOUT, {"refresh": token}, format="json").status_code, 204)   # повторно — тоже ок
        self.assertEqual(self.client.post(LOGOUT, {"refresh": "мусор"}, format="json").status_code, 204)

    def test_last_login_recorded(self):
        self.login()
        self.cook.refresh_from_db()
        self.assertIsNotNone(self.cook.last_login)                   # видно в разделе «Сотрудники»


class EndSessionsTests(SecurityBase):
    """Блокировка, новый пароль, новая роль — все входы сотрудника отменяются сразу."""

    def setUp(self):
        super().setUp()
        self.session = self.login(remember=True).data                # повар вошёл с «Запомнить меня»
        User.objects.filter(pk=self.cook.pk).update(telegram_id=555) # и привязал Telegram

    def assertLoggedOut(self, access_works=False):
        """Ключ продления не работает; токен входа — как указано."""
        self.assertEqual(self.refresh(self.session["refresh"]).status_code, 401)
        self.assertEqual(self.me(self.session["access"]), 200 if access_works else 401)

    def test_block_ends_sessions_and_telegram(self):
        self.as_user(self.admin)
        self.client.patch(f"/api/admin/staff/{self.cook.id}/", {"is_active": False}, format="json")
        self.as_user(None)
        self.assertLoggedOut()                                       # и токен входа сразу не принимают
        self.cook.refresh_from_db()
        self.assertIsNone(self.cook.telegram_id)                     # бот отвязан
        self.as_user(self.admin)
        self.client.patch(f"/api/admin/staff/{self.cook.id}/", {"is_active": True}, format="json")
        self.as_user(None)
        self.assertEqual(self.refresh(self.session["refresh"]).status_code, 401)   # разблокировали — старый вход не ожил

    def test_new_password_ends_sessions_and_telegram(self):
        self.as_user(self.admin)
        code = self.client.post(f"/api/admin/staff/{self.cook.id}/set-password/",
                                {"password": "Новый-Пароль-2026"}, format="json").status_code
        self.assertEqual(code, 204)
        self.as_user(None)
        self.assertLoggedOut()                                       # токен входа со старым паролем не работает
        self.cook.refresh_from_db()
        self.assertIsNone(self.cook.telegram_id)
        self.assertEqual(self.login(password="Новый-Пароль-2026").status_code, 200)   # с новым — входит

    def test_new_role_ends_sessions_keeps_telegram(self):
        self.as_user(self.chef)
        self.client.post(f"/api/admin/staff/{self.cook.id}/set-role/", {"role": "waiter"}, format="json")
        self.as_user(None)
        self.assertLoggedOut(access_works=True)                      # продлить нельзя; права и так из базы (уже официант)
        self.cook.refresh_from_db()
        self.assertEqual(self.cook.telegram_id, 555)                 # Telegram остаётся: бот берёт роль из базы

    def test_name_change_keeps_sessions(self):
        self.as_user(self.admin)
        self.client.patch(f"/api/admin/staff/{self.cook.id}/", {"first_name": "Азамат"}, format="json")
        self.as_user(None)
        self.assertEqual(self.refresh(self.session["refresh"]).status_code, 200)   # имя — не повод выкидывать


class BruteForceTests(SecurityBase):
    """Подбор пароля: на сайте, в боте и вместе."""

    def test_five_failures_pause_this_ip_only(self):
        codes = [self.login(password="неверно").status_code for _ in range(5)]
        self.assertEqual(codes, [401] * 5)
        response = self.login()                                      # 6-я — даже с верным паролем
        self.assertEqual(response.status_code, 429)
        self.assertIn("Попробуйте через 15 минут", response.data["detail"])
        self.assertEqual(self.login(ip="10.0.0.2").status_code, 200) # повар с другого места входит спокойно

    def test_success_resets_counter(self):
        for _ in range(4):
            self.login(password="неверно")
        self.assertEqual(self.login().status_code, 200)              # вошёл — счётчик обнулился
        for _ in range(4):
            self.login(password="неверно")
        self.assertEqual(self.login().status_code, 200)

    def test_many_places_lock_login(self):
        for i in range(20):                                          # 20 ошибок с разных IP
            self.login(password="неверно", ip=f"10.1.0.{i}")
        response = self.login(ip="10.9.9.9")                         # даже новое место и верный пароль
        self.assertEqual(response.status_code, 429)
        self.assertIn("60 минут", response.data["detail"])
        self.assertEqual(self.login("waiter", ip="10.9.9.9").status_code, 200)   # другие логины не затронуты

    def test_login_case_and_spaces_same_counter(self):
        for name in ["cook", "COOK", " Cook ", "cOOk", "cook "]:
            self.login(name, password="неверно")
        self.assertEqual(self.login().status_code, 429)              # «Cook» и «cook» — один счётчик

    def test_bot_and_site_share_login_counter(self):
        for i in range(10):                                          # 10 ошибок на сайте с разных IP
            self.login("waiter", password="неверно", ip=f"10.2.0.{i}")
        for tg in range(100, 110):                                   # и 10 из разных Telegram
            login_from_telegram("waiter", "неверно", tg)
        user, error = login_from_telegram("waiter", PASSWORD, 999)   # всего 20 — логин закрыт и в боте
        self.assertIsNone(user)
        self.assertIn("60 минут", error)

    def test_bot_switching_logins_still_paused(self):
        for name in ["cook", "waiter", "admin", "chef", "courier"]:  # один Telegram перебирает разные логины
            login_from_telegram(name, "неверно", 777)
        user, error = login_from_telegram("cook", PASSWORD, 777)
        self.assertIsNone(user)                                      # этот Telegram на паузе
        self.assertIn("15 минут", error)

    def test_failures_written_to_log(self):
        with self.assertLogs("muslim.security", level="WARNING") as logs:
            self.login(password="неверно", ip="10.3.3.3")
        self.assertIn("10.3.3.3", logs.output[0])                    # видно, откуда пытались
        self.assertNotIn("неверно", logs.output[0])                  # пароль в журнал не пишется

    def test_short_password_rejected(self):
        self.as_user(self.admin)
        response = self.client.post(f"/api/admin/staff/{self.cook.id}/set-password/",
                                    {"password": "Kafe2026!"}, format="json")   # 9 символов
        self.assertEqual(response.status_code, 400)


class OrderSpamTests(SecurityBase):
    """Не больше 3 заказов ждут подтверждения; не больше 10 доставок в час с одного IP."""

    def remote_order(self, phone="+996 700 111 222", device="dev-1", ip="10.5.0.1", kind="pickup"):
        """Самовывоз (или доставка) по QR доставки."""
        body = {
            "table_token": self.delivery.token, "order_type": kind, "device_key": device,
            "customer_name": "Гость", "phone": phone, "address": "ул. Ленина 1",
            "items": [{"dish_id": self.pizza.id, "size_id": self.size25.id, "quantity": 1}],
        }
        return self.client.post("/api/orders/", body, format="json", REMOTE_ADDR=ip)

    def test_three_waiting_per_phone(self):
        for device in ["a", "b", "c"]:
            self.assertEqual(self.remote_order(device=device).status_code, 201)
        response = self.remote_order(phone="0700111222", device="d")   # тот же номер, записан иначе
        self.assertEqual(response.status_code, 400)
        self.assertIn("ждут подтверждения", str(response.data))
        self.assertEqual(self.remote_order(phone="+996 555 000 111", device="e").status_code, 201)   # другой номер — можно

    def test_three_waiting_per_device(self):
        for phone in ["+996700000001", "+996700000002", "+996700000003"]:
            self.remote_order(phone=phone, device="same")
        self.assertEqual(self.remote_order(phone="+996700000004", device="same").status_code, 400)

    def test_confirmed_orders_free_the_slot(self):
        numbers = [self.remote_order(device=d).data["number"] for d in "abc"]
        self.act(self.admin, numbers[0], "accept")                   # кафе подтвердило один заказ
        self.assertEqual(self.remote_order(device="d").status_code, 201)   # место освободилось

    def test_ip_limit_per_hour(self):
        for i in range(IP_LIMIT):
            self.assertEqual(self.remote_order(phone=f"+99670000{i:04d}", device=f"d{i}").status_code, 201)
        response = self.remote_order(phone="+996709999999", device="new")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Слишком много заказов", str(response.data))
        self.assertEqual(self.remote_order(phone="+996709999999", device="new", ip="10.5.0.2").status_code, 201)

    def test_table_three_waiting_per_device(self):
        for _ in range(3):
            self.assertEqual(self.hall_order(device_key="phone-x").status_code, 201)
        self.assertEqual(self.hall_order(device_key="phone-x").status_code, 400)
        self.assertEqual(self.hall_order(device_key="phone-y").status_code, 201)   # сосед за столом заказывает

    def test_phone_digits(self):
        self.assertEqual(phone_digits("+996 (700) 12-34-56"), phone_digits("0700123456"))


class StartupGuardTests(SecurityBase):
    """Защита от ошибок при запуске."""

    @override_settings(DEBUG=False)
    def test_seed_demo_refuses_on_server(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo")
        self.assertFalse(Extra.objects.filter(name="Сыр моцарелла").exists())   # ничего не создано
