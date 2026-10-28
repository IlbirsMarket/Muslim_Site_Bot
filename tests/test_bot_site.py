"""
Сайт пишет события для бота + вход сотрудника в боте логином и паролем (шаг 3).
Запуск: python manage.py test tests.test_bot_site -v 2
"""

from django.test import override_settings          # временно задаём имя бота

from apps.bot.models import BotEvent
from apps.bot.services import login_from_telegram
from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest    # общая подготовка: сотрудники, меню, столы

TELEGRAM = "/api/staff/telegram/"                  # привязан ли Telegram / отвязать


class SiteEventsTests(BaseAPITest):
    """Каждое действие на сайте — ровно одно событие для бота."""

    def events(self, kind=None):
        """Список событий (по желанию — только одного типа)."""
        queryset = BotEvent.objects.all()
        return list(queryset.filter(kind=kind) if kind else queryset)

    def test_new_order_event(self):
        order = self.hall_order(device_key="phone-1").data
        [event] = self.events()                                           # ровно одно событие
        self.assertEqual(event.kind, BotEvent.Kind.ORDER_CREATED)
        self.assertEqual(event.order_id, order["number"])
        self.assertEqual(event.payload, {"trusted": False})               # телефон ещё не доверенный

    def test_trusted_order_event(self):
        number = self.hall_order(device_key="phone-1").data["number"]
        self.act(self.waiter, number, "accept")
        self.hall_order(device_key="phone-1")                              # второй заказ с того же телефона
        last = self.events(BotEvent.Kind.ORDER_CREATED)[-1]
        self.assertEqual(last.payload, {"trusted": True})                 # бот поймёт: заказ сразу «Принят»

    def test_status_and_claim_events(self):
        number = self.hall_order().data["number"]
        self.as_user(self.waiter)
        self.client.post(f"/api/staff/orders/{number}/claim/")             # «Беру стол»
        self.act(self.waiter, number, "accept")                            # «Подтвердить»
        changed = self.events(BotEvent.Kind.ORDER_CHANGED)
        self.assertEqual([e.payload["action"] for e in changed], ["claim", "accept"])
        self.assertEqual(changed[1].payload["user_id"], self.waiter.id)    # кто нажал

    def test_forbidden_action_no_event(self):
        number = self.hall_order().data["number"]
        self.assertIn(self.act(self.cook, number, "accept").status_code, (403, 404))   # повару нельзя
        self.assertEqual(self.events(BotEvent.Kind.ORDER_CHANGED), [])     # ничего не случилось — события нет

    def test_call_events(self):
        body = {"table_token": self.table.token, "kind": "waiter"}
        call_id = self.client.post("/api/table-calls/", body, format="json").data["id"]
        self.client.post("/api/table-calls/", body, format="json")         # гость нажал второй раз
        self.assertEqual(len(self.events(BotEvent.Kind.CALL_CREATED)), 1)  # событие одно
        self.as_user(self.waiter)
        self.client.post(f"/api/staff/table-calls/{call_id}/done/")
        self.client.post(f"/api/staff/table-calls/{call_id}/done/")        # «Выполнено» второй раз
        self.assertEqual(len(self.events(BotEvent.Kind.CALL_DONE)), 1)     # событие одно

    def test_table_freed_event(self):
        self.as_user(self.waiter)
        self.client.post(f"/api/staff/tables/{self.table.id}/close-visit/")
        [event] = self.events(BotEvent.Kind.TABLE_FREED)
        self.assertEqual(event.table_id, self.table.id)


class TelegramLoginTests(BaseAPITest):
    """Вход в боте логином и паролем с сайта, отвязка в панели."""

    def test_login_binds_telegram(self):
        user, error = login_from_telegram("waiter", PASSWORD, 555)
        self.assertEqual((user, error), (self.waiter, None))                 # вошёл
        self.waiter.refresh_from_db()
        self.assertEqual(self.waiter.telegram_id, 555)                       # Telegram ID записан

    def test_wrong_password_and_pause(self):
        for left in (4, 3, 2, 1):
            user, error = login_from_telegram("waiter", "неверно", 555)
            self.assertIsNone(user)
            self.assertIn(f"Осталось попыток: {left}", error)
        self.assertIn("закрыт на 15 минут", login_from_telegram("waiter", "неверно", 555)[1])   # 5-я ошибка
        user, error = login_from_telegram("waiter", PASSWORD, 555)           # даже верный пароль — пауза
        self.assertIsNone(user)
        self.assertIn("Попробуйте через 15 минут", error)
        self.assertEqual(login_from_telegram("waiter", PASSWORD, 777)[0], self.waiter)   # другой Telegram — свой счётчик

    def test_blocked_cannot_login(self):
        User.objects.filter(pk=self.cook.pk).update(is_active=False)
        self.assertIsNone(login_from_telegram("cook", PASSWORD, 556)[0])     # заблокированный не входит

    def test_telegram_moves_to_new_owner(self):
        User.objects.filter(pk=self.cook.pk).update(telegram_id=555)         # этот Telegram был у повара
        login_from_telegram("waiter", PASSWORD, 555)                         # теперь вошёл официант
        self.cook.refresh_from_db()
        self.assertIsNone(self.cook.telegram_id)                             # у повара отвязался

    @override_settings(TELEGRAM_BOT_USERNAME="muslim_cafe_bot")
    def test_panel_state_and_unlink(self):
        login_from_telegram("waiter", PASSWORD, 555)
        self.waiter.refresh_from_db()                                        # тест входит «старым» объектом — перечитываем из базы
        self.as_user(self.waiter)
        state = self.client.get(TELEGRAM).data
        self.assertEqual((state["telegram_id"], state["bot_url"]), (555, "https://t.me/muslim_cafe_bot"))
        self.assertIsNone(self.client.delete(TELEGRAM).data["telegram_id"])  # отвязал
        self.assertIsNone(self.client.get("/api/auth/me/").data["telegram_id"])
        self.as_user(None)
        self.assertEqual(self.client.get(TELEGRAM).status_code, 401)         # гостю нельзя