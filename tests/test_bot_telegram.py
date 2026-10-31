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
        """Принятая доставка — у админов, на кухне и у курьеров; кухне — только кухонные кнопки."""
        order, _ = self.bot_order()
        order.status = Order.Status.ACCEPTED
        self.assertEqual(order_places(order), [P.ADMINS, P.KITCHEN, P.DELIVERY])
        self.assertEqual([d.split(":")[2] for _, d in order_buttons(order, P.KITCHEN)], ["cook"])

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
            self.assertEqual(TableAdminSerializer(delivery).data["bot_url"], f"https://t.me/muslim_cafe_bot?start=b{self.b2.id}")
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
                         [(P.ADMINS, False), (P.DELIVERY, True), (P.KITCHEN, True)])
        for step in plan:
            save_message(event, step, -100, None, step["old"].message_id)
        self.assertEqual(list(BotMessage.objects.filter(order=order).values_list("place", flat=True)), [P.ADMINS])

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
