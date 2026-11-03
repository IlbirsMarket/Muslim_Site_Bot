"""Мини-приложение Telegram: проверка подписи initData, вход персонала по Telegram, статусы гостю в чат."""

import time                                                    # «когда открыли»

from django.core.cache import cache
from django.test import override_settings

from apps.orders.models import Order
from core.telegram_webapp import check_init_data, sign_init_data
from tests.test_api import BaseAPITest

STAFF_TOKEN, GUEST_TOKEN = "111:staff-secret", "222:guest-secret"


def init_data(token, user_id=555, age=0):
    """Строка, какую Telegram даёт мини-приложению (подписана токеном бота)."""
    return sign_init_data({"auth_date": int(time.time()) - age, "query_id": "AAE", "user": {"id": user_id, "first_name": "Азамат"}}, token)


@override_settings(TELEGRAM_STAFF_BOT_TOKEN=STAFF_TOKEN, TELEGRAM_GUEST_BOT_TOKEN=GUEST_TOKEN)
class MiniAppTests(BaseAPITest):

    def test_signature(self):
        """Своя подпись — да; чужой бот, подделка, старые данные — нет."""
        self.assertEqual(check_init_data(init_data(STAFF_TOKEN), STAFF_TOKEN)["user"]["id"], 555)
        self.assertIsNone(check_init_data(init_data(GUEST_TOKEN), STAFF_TOKEN))                # подписано гостевым ботом
        self.assertIsNone(check_init_data(init_data(STAFF_TOKEN).replace("555", "556"), STAFF_TOKEN))   # подменили id
        self.assertIsNone(check_init_data(init_data(STAFF_TOKEN, age=2 * 86400), STAFF_TOKEN))  # двухдневной давности
        self.assertIsNone(check_init_data("", STAFF_TOKEN))

    def login(self, data, **extra):
        self.as_user(None)
        return self.client.post("/api/auth/telegram/", {"init_data": data, **extra}, format="json")

    def test_staff_first_time_then_automatic(self):
        """Первый раз — логин и пароль (Telegram привязывается), потом вход сам."""
        response = self.login(init_data(STAFF_TOKEN, 777))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["detail"], "not_linked")
        response = self.login(init_data(STAFF_TOKEN, 777), username="cook", password="wrong-password")
        self.assertEqual(response.status_code, 401)
        cache.clear()
        from tests.test_api import PASSWORD
        response = self.login(init_data(STAFF_TOKEN, 777), username="cook", password=PASSWORD)
        self.assertEqual(response.status_code, 200, response.data)
        self.cook.refresh_from_db()
        self.assertEqual(self.cook.telegram_id, 777)
        response = self.login(init_data(STAFF_TOKEN, 777))                        # дальше — без пароля
        self.assertEqual(response.status_code, 200)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")
        self.assertEqual(self.client.get("/api/auth/me/").data["username"], "cook")

    def test_bad_signature_and_blocked(self):
        """Подделка — 401; заблокированный сотрудник по Telegram не входит."""
        self.assertEqual(self.login("user=%7B%22id%22%3A1%7D&hash=abc").status_code, 401)
        self.waiter.telegram_id, self.waiter.is_active = 888, False
        self.waiter.save()
        self.assertEqual(self.login(init_data(STAFF_TOKEN, 888)).status_code, 404)

    def test_guest_order_gets_chat(self):
        """Заказ из мини-приложения гостевого бота — статусы пойдут гостю в чат; подделка — нет."""
        response = self.hall_order(telegram_init_data=init_data(GUEST_TOKEN, 4242))
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Order.objects.latest("id").guest_chat_id, 4242)
        cache.clear()
        response = self.hall_order(telegram_init_data=init_data(STAFF_TOKEN, 4243))   # подписано не гостевым ботом
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(Order.objects.latest("id").guest_chat_id)


class MiniAppButtonsTests(BaseAPITest):

    @override_settings(SITE_URL="https://muslim-cafe.com")
    def test_buttons_open_mini_app(self):
        """С https-сайтом бот персонала даёт кнопку «Открыть панель» (мини-приложение)."""
        from apps.bot.telegram.handlers import home_rows
        from apps.bot.telegram.screen import inline
        markup = inline(home_rows(self.admin))
        self.assertEqual(markup.inline_keyboard[0][0].web_app.url, "https://muslim-cafe.com/admin")
        self.assertEqual(inline(home_rows(None)).inline_keyboard[0][0].web_app.url, "https://muslim-cafe.com/admin")

    @override_settings(SITE_URL="http://localhost:5173")
    def test_without_https_old_buttons(self):
        """Без https (на своём компьютере) — бот на кнопках, как раньше."""
        from apps.bot.telegram.handlers import home_rows
        self.assertEqual(home_rows(None), [[("🔑 Войти как сотрудник", "sl")]])
