"""
Telegram-боты: куда идут заказы, кнопки и права, стоп-лист, столы, заказ из гостевого бота.
Запуск: python manage.py test tests.test_bot_telegram -v 2
"""

from apps.bot import guest_services as gs, staff_actions as sa
from apps.bot.models import BotEvent, BotMessage
from apps.bot.notify import build_plan, order_buttons, order_places, pending_events, save_message
from apps.orders.models import Order, TableCall
from apps.tables.models import Table
from apps.users.models import User
from apps.cafe.models import Branch
from tests.test_branches import BranchBase

P = BotMessage.Place


class BotTelegramTest(BranchBase):

    def setUp(self):
        super().setUp()
        self.b2.tg_group_id, self.b2.tg_topic_admins, self.b2.tg_topic_kitchen, self.b2.tg_topic_delivery = -100, 2, 3, 5
        self.b2.save()                                                     # у «Филиала 2» настроена группа
        self.admin2.telegram_id = 111                                      # админ вошёл в бота
        self.admin2.save()
        self.waiter2.telegram_id = 222
        self.waiter2.save()
        self.cook1 = User.objects.create_user("cookx", password="x", role=User.Role.COOK, branch=self.b1, telegram_id=333)

    def bot_order(self, **extra):
        """Заказ на доставку из гостевого бота во «Филиале 2»."""
        data = {"kind": "delivery", "name": "Али", "phone": "+996555000111", "address": "Ленина 1",
                "cart": [{"dish_id": self.lagman.id, "quantity": 3}], **extra}
        return gs.create_bot_order(self.b2.id, 777, data)

    def test_guest_order_and_plan(self):
        """Заказ из бота создаётся через сайт-сериализатор и идёт в тему «Админы» филиала 2."""
        order, error = self.bot_order()
        self.assertIsNone(error)
        order.refresh_from_db()
        self.assertEqual((order.source, order.guest_chat_id, order.branch_id, order.subtotal), ("bot", 777, self.b2.id, 1050))
        event = BotEvent.objects.get(order=order)
        plan = build_plan(event)
        self.assertEqual([(s["place"], s["chat_id"], s["thread_id"]) for s in plan], [(P.ADMINS, -100, 2)])
        self.assertIn("Лагман", plan[0]["text"])
        save_message(event, plan[0], -100, 2, 55)                          # «отправили»
        self.assertEqual(BotMessage.objects.get(order=order).message_id, 55)

    def test_places_follow_status(self):
        """Заказ всегда в одной теме, как колонки на сайте: «Новые» → «Готовятся» → «Готовы и в пути» → исчезает."""
        order, _ = self.bot_order()
        expected = {"new": [P.ADMINS], "accepted": [P.KITCHEN], "cooking": [P.KITCHEN], "ready": [P.DELIVERY],
                    "on_the_way": [P.DELIVERY], "completed": [], "cancelled": []}
        for status, places in expected.items():
            order.status = status
            self.assertEqual(order_places(order), places, status)
        order.status = Order.Status.ACCEPTED
        self.assertIn("cook", [d.split(":")[2] for _, d in order_buttons(order)])

    def test_buttons_check_rights_and_branch(self):
        """Админ филиала 2 подтверждает; повар чужого филиала — «Нет прав»; не вошедший — просьба войти."""
        order, _ = self.bot_order()
        self.assertEqual(sa.order_action(333, order.id, "accept"), sa.NO_RIGHTS)
        self.assertEqual(sa.order_action(999, order.id, "accept"), sa.NO_LOGIN)
        self.assertEqual(sa.order_action(111, order.id, "accept"), "Готово ✅")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.ACCEPTED)
        self.assertEqual(sa.order_action(111, order.id, "cancel"), "ask_reason")   # сначала причина
        self.assertEqual(sa.order_action(111, order.id, "cancel", 0), "Готово ✅")
        order.refresh_from_db()
        self.assertEqual((order.status, order.cancel_reason), (Order.Status.CANCELLED, "Нет продуктов"))

    def test_call_and_free_table(self):
        """Вызов со стола: «Подошёл» → событие; «Освободить стол» — только свой филиал."""
        table = Table.objects.filter(branch=self.b2, kind=Table.Kind.HALL).first()
        call = TableCall.objects.create(table=table, kind=TableCall.Kind.WAITER)
        self.assertEqual(sa.call_done(333, call.id), sa.NO_RIGHTS)        # повар — нет
        self.assertEqual(sa.call_done(222, call.id), "Готово ✅")
        self.assertTrue(BotEvent.objects.filter(call=call, kind="call_done").exists())
        Table.objects.filter(pk=table.pk).update(occupied_since="2026-01-01T10:00:00Z")
        self.assertEqual(sa.busy_tables(self.waiter2), [(table.id, str(table))])
        self.assertIn("свободен", sa.free_table(222, table.id))
        self.assertEqual(sa.busy_tables(self.waiter2), [])

    def test_stop_list_only_own_branch(self):
        """Повар филиала 1 не может выключить блюдо филиала 2."""
        answer, category = sa.toggle_dish(333, self.lagman.id)
        self.assertEqual((answer, category), (sa.NO_RIGHTS, None))

    def test_guest_worker_skips_foreign_events(self):
        """Гостевой бот берёт только события заказов из бота."""
        order, _ = self.bot_order()
        TableCall.objects.create(table=Table.delivery_point(self.b2), kind=TableCall.Kind.WAITER)
        from apps.bot.events import add_event
        add_event("call_created", call=TableCall.objects.first())
        self.assertEqual([e.order_id for e in gs.guest_pending()], [order.id])
        chat, text, old = gs.guest_step(gs.guest_pending()[0])
        self.assertEqual((chat, old), (777, None))
        self.assertIn("Заказ №", text)
        self.assertIn("Новый", gs.my_orders(777))

    def test_report_text(self):
        """Отчёт за день: текст и PDF."""
        text, pdf, name = sa.day_report(self.admin2)
        self.assertIn("Отчёт", text)
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertEqual(len(pending_events()), 0)


class BotMenuAndQrTest(BotTelegramTest):
    """Меню с фото и листанием; QR бота у «Доставки» каждого филиала."""

    def test_dish_pages_wrap_and_placeholder(self):
        """Листание по кругу; без фото — нарисованная картинка JPEG."""
        page = gs.dish_page(self.b2.id, self.soups.id, 0)
        self.assertEqual((page["name"], page["total"], page["photo"]), ("Лагман", 1, None))
        self.assertEqual(gs.dish_page(self.b2.id, self.soups.id, 5)["index"], 0)       # 5 % 1 = 0
        self.assertIsNone(gs.dish_page(self.b1.id, self.soups.id, 0))                   # чужой филиал — пусто
        self.assertTrue(gs.placeholder_photo("Лагман по-уйгурски домашний").startswith(b"\xff\xd8"))
        self.assertEqual(gs.dish_titles(self.b2.id, self.soups.id), ["Лагман"])

    def test_bot_qr_for_delivery(self):
        """С именем бота у «Доставки» есть ссылка t.me/...?start=b<филиал> и PNG; без имени — пусто."""
        from django.test import override_settings
        delivery = Table.delivery_point(self.b2)
        with override_settings(TELEGRAM_GUEST_BOT_USERNAME="muslim_cafe_bot"):
            from apps.tables.serializers import TableAdminSerializer
            self.b2.refresh_from_db()
            self.assertEqual(TableAdminSerializer(delivery).data["bot_url"], f"https://t.me/muslim_cafe_bot?start=b{self.b2.tg_start_token}")
        with override_settings(TELEGRAM_GUEST_BOT_USERNAME=""):            # имя бота не указано (не зависит от вашего .env)
            self.assertEqual(TableAdminSerializer(delivery).data["bot_url"], "")


class BotCleanupTest(BotTelegramTest):
    """Ненужные сообщения в группе удаляются: заказ ушёл с кухни / доставлен, вызов выполнен."""

    def test_kitchen_and_delivery_messages_deleted(self):
        order, _ = self.bot_order()
        for place, mid in ((P.ADMINS, 1), (P.KITCHEN, 2), (P.DELIVERY, 3)):
            BotMessage.objects.create(order=order, place=place, chat_id=-100, message_id=mid)
        Order.objects.filter(pk=order.pk).update(status=Order.Status.COMPLETED)
        event = BotEvent.objects.create(kind="order_changed", order=order)
        plan = build_plan(event)
        self.assertEqual(sorted((s["place"], bool(s.get("delete"))) for s in plan),
                         [(P.ADMINS, True), (P.DELIVERY, True), (P.KITCHEN, True)])   # закрытый заказ исчезает из всех тем
        for step in plan:
            save_message(event, step, -100, None, step["old"].message_id)
        self.assertFalse(BotMessage.objects.filter(order=order).exists())

    def test_done_call_deleted(self):
        table = Table.objects.filter(branch=self.b2, kind=Table.Kind.HALL).first()
        self.b2.tg_topic_hall = 4
        self.b2.save()
        call = TableCall.objects.create(table=table, kind=TableCall.Kind.WAITER)
        BotMessage.objects.create(call=call, place=P.HALL, chat_id=-100, message_id=9)
        sa.call_done(222, call.id)
        plan = build_plan(BotEvent.objects.get(call=call, kind="call_done"))
        self.assertTrue(plan[0]["delete"])

    def test_cart_helpers(self):
        item = {"dish_id": self.lagman.id, "size_id": None, "extra_ids": [], "quantity": 2}
        self.assertEqual(gs.item_total(item), 700)
        self.assertIn("Лагман", gs.short_title(item))
        self.assertIn("700", gs.config_caption(item).replace(" ", " ").replace(" ", ""))

    def test_cart_page(self):
        """Корзина по одному товару: подпись с ценой × количеством, номер позиции и итог; пустая — None."""
        cart = [{"dish_id": self.lagman.id, "quantity": 2}, {"dish_id": self.lagman.id, "quantity": 1}]
        page = gs.cart_page(self.b2.id, cart, 3)                       # 3 % 2 = 1 — листание по кругу
        self.assertEqual((page["index"], page["total"]), (1, 2))
        self.assertIn("Позиция 2 из 2", page["caption"])
        self.assertIn("1 050", page["caption"])                        # итог корзины: 3 × 350
        self.assertIsNone(gs.cart_page(self.b2.id, [], 0))


class BotStartCodesTest(BotTelegramTest):
    """Секретный код QR бота, «Обновить QR», заказ со стола из бота, проверка ID тем в админке."""

    def test_branch_code_and_regenerate(self):
        self.b2.refresh_from_db()
        old = self.b2.tg_start_token
        self.assertTrue(old)
        self.assertNotEqual(old, Branch.objects.get(pk=self.b1.pk).tg_start_token)     # у каждого филиала свой
        self.assertEqual(gs.branch_by_start(old), self.b2.id)
        self.b2.regenerate_start_token()
        self.assertIsNone(gs.branch_by_start(old))                                     # старый QR больше не работает

    def test_table_order_from_bot(self):
        table = Table.objects.filter(branch=self.b2, kind=Table.Kind.HALL).first()
        bid, token, label = gs.table_by_start(table.token)
        self.assertEqual((bid, token), (self.b2.id, table.token))
        order, error = gs.create_bot_order(self.b2.id, 778, {"kind": "hall", "table": token, "cart": [{"dish_id": self.lagman.id, "quantity": 1}]})
        self.assertIsNone(error)
        self.assertEqual((order.kind, order.table_id, order.source), ("hall", table.id, "bot"))
        order2, _ = gs.create_bot_order(self.b2.id, 778, {"kind": "takeaway", "table": token, "cart": [{"dish_id": self.lagman.id, "quantity": 1}]})
        self.assertEqual(order2.kind, "takeaway")

    def test_topic_ids_validated(self):
        from django.core.exceptions import ValidationError
        self.b2.tg_topic_kitchen = -100123                                              # вписали ID группы вместо темы
        with self.assertRaises(ValidationError):
            self.b2.full_clean()
        from apps.bot.notify import topic
        self.assertEqual(topic(self.b2, "kitchen"), (-100, None))                       # бот шлёт в общий чат, а не падает


class TableWaiterAndBillTest(BotTelegramTest):
    """Стол за официантом после «Беру стол»; счёт стола и деление на людей."""

    def test_table_owned_by_waiter(self):
        from apps.orders.status_service import claim_order, close_visits, owns_table
        table = Table.objects.filter(branch=self.b2, kind=Table.Kind.HALL).first()
        order, _ = gs.create_bot_order(self.b2.id, 900, {"kind": "hall", "table": table.token, "cart": [{"dish_id": self.lagman.id, "quantity": 1}]})
        claim_order(order, self.waiter2)
        table.refresh_from_db()
        self.assertEqual(table.waiter_id, self.waiter2.id)                     # стол за официантом
        other = User.objects.create_user("waiter2c", password="x", role=User.Role.WAITER, branch=self.b2, telegram_id=444)
        self.assertFalse(owns_table(other, table))
        self.assertIn("ведёт", sa.free_table(444, table.id))                   # чужой официант не освободит
        order2, _ = gs.create_bot_order(self.b2.id, 901, {"kind": "hall", "table": table.token, "cart": [{"dish_id": self.lagman.id, "quantity": 1}]})
        self.assertEqual(order2.claimed_by_id, self.waiter2.id)                # новый заказ стола — сразу его
        close_visits(table, self.waiter2)
        table.refresh_from_db()
        self.assertIsNone(table.waiter_id)                                     # освободил — стол ничей

    def test_bill_split(self):
        from apps.bot.notify import call_text
        table = Table.objects.filter(branch=self.b2, kind=Table.Kind.HALL).first()
        gs.create_bot_order(self.b2.id, 902, {"kind": "hall", "table": table.token, "cart": [{"dish_id": self.lagman.id, "quantity": 3}]})
        resp = self.client.get(f"/api/tables/{table.token}/bill/")
        self.assertEqual(resp.json()["total"], 1050)
        call = TableCall.objects.create(table=table, kind=TableCall.Kind.BILL, people=4)
        text = call_text(call).replace(" ", " ")
        self.assertIn("4 чел.", text)
        self.assertIn("263", text)                                             # 1050 / 4 = 262.5 → 263


class SyncFixesTest(BotTelegramTest):
    """Порядок столов, главная без QR, «Освободить стол» для гостей бота."""

    def test_tables_in_order_after_readd(self):
        self.as_user(self.chef) if hasattr(self, "as_user") else self.client.force_authenticate(self.admin2)
        for _ in range(3):
            self.client.post("/api/admin/tables/", {"floor": 1}, format="json", HTTP_X_BRANCH=str(self.b2.id))
        numbers = [t["number"] for t in self.client.get("/api/admin/tables/", HTTP_X_BRANCH=str(self.b2.id)).json() if t["kind"] == "hall" and t["floor"] == 1]
        self.assertEqual(numbers, sorted(numbers))

    def test_branch_list_has_order_token(self):
        data = self.client.get("/api/branches/").json()
        self.assertTrue(all(b["order_token"] for b in data))
        self.assertEqual(Table.objects.get(token=data[1]["order_token"]).kind, Table.Kind.DELIVERY)

    def test_freed_table_ends_bot_table_mode(self):
        from django.utils import timezone
        from apps.orders.status_service import close_visits
        table = Table.objects.filter(branch=self.b2, kind=Table.Kind.HALL).first()
        since = timezone.now().isoformat()
        self.assertTrue(gs.table_active(table.token, since))
        gs.create_bot_order(self.b2.id, 905, {"kind": "hall", "table": table.token, "cart": [{"dish_id": self.lagman.id, "quantity": 1}]})
        close_visits(table, self.admin2)
        self.assertFalse(gs.table_active(table.token, since))
        event = [e for e in gs.guest_pending() if e.kind == "table_freed"][0]
        token, chats = gs.freed_table_chats(event)
        self.assertEqual((token, chats), (table.token, [905]))


class PushTest(BotTelegramTest):
    """Push на телефон: подписка, кому уходит, «ящик» для телефона, подпись VAPID."""

    def test_push_flow(self):
        from unittest import mock
        from django.test import override_settings
        from apps.bot import push
        from apps.bot.models import PushSubscription
        public, private = push.make_keys()
        with override_settings(VAPID_PUBLIC_KEY=public, VAPID_PRIVATE_KEY=private):
            self.assertEqual(self.client.get("/api/push/key/").json()["key"], public)
            self.assertTrue(push.vapid_header("https://fcm.googleapis.com/fcm/send/x").startswith("vapid t="))
            self.client.force_authenticate(self.admin2)
            self.client.post("/api/push/subscribe/", {"endpoint": "https://push.example/admin2"}, format="json")
            self.client.force_authenticate(None)
            order, _ = self.bot_order()
            Order.objects.filter(pk=order.pk).update(device_key="dev-guest")
            self.client.post("/api/push/subscribe/", {"endpoint": "https://push.example/guest", "device_key": "dev-guest"}, format="json")
            with mock.patch("urllib.request.urlopen") as sent:
                push.push_event(BotEvent.objects.get(order=order, kind="order_created"))     # новый заказ → админу
                self.assertEqual(sent.call_count, 1)
                sa.order_action(111, order.id, "accept")
                push.push_event(BotEvent.objects.filter(order=order, kind="order_changed").last())   # статус → гостю
                self.assertEqual(sent.call_count, 2)
            items = self.client.post("/api/push/inbox/", {"endpoint": "https://push.example/guest"}, format="json").json()["items"]
            self.assertIn("Принят", items[0]["body"])
            self.assertEqual(self.client.post("/api/push/inbox/", {"endpoint": "https://push.example/guest"}, format="json").json()["items"], [])
            self.assertEqual(PushSubscription.objects.count(), 2)

    def test_version_endpoint(self):
        v1 = self.client.get("/api/version/").json()["v"]
        self.bot_order()
        self.assertGreater(self.client.get("/api/version/").json()["v"], v1)


class PhotoWebpTest(BotTelegramTest):
    """Фото блюда при загрузке уменьшается и становится WebP; для Telegram — JPEG."""

    def test_upload_becomes_small_webp(self):
        import os
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.images import jpeg_bytes
        raw = BytesIO()
        size = (2560, 1440)                                                                # «тяжёлое» фото 2К (~2 МБ)
        Image.merge("RGB", [Image.linear_gradient("L").resize(size), Image.effect_noise(size, 30),
                            Image.linear_gradient("L").rotate(90).resize(size)]).save(raw, "JPEG", quality=92)
        self.client.force_authenticate(self.admin2)
        resp = self.client.patch(f"/api/admin/dishes/{self.lagman.id}/", {"photo": SimpleUploadedFile("big.jpg", raw.getvalue(), "image/jpeg")},
                                 format="multipart", HTTP_X_BRANCH=str(self.b2.id))
        self.assertEqual(resp.status_code, 200, resp.content[:200])
        self.lagman.refresh_from_db()
        self.assertTrue(self.lagman.photo.name.endswith(".webp"))
        with Image.open(self.lagman.photo.path) as image:
            self.assertEqual(max(image.size), 1400)                                         # уменьшено
        self.assertLess(self.lagman.photo.size, len(raw.getvalue()) // 4)                   # в разы легче оригинала
        self.assertTrue(jpeg_bytes(self.lagman.photo.path).startswith(b"\xff\xd8"))         # для Telegram
        os.remove(self.lagman.photo.path)
