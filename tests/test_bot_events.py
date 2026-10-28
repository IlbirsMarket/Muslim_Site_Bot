"""
Проверка «почтового ящика» бота (шаг 2).
Запуск: python manage.py test tests.test_bot_events -v 2
"""

from django.db import transaction             # «всё или ничего»
from django.test import TestCase              # обычный тест Django

from apps.bot.events import Kind, add_event   # функция, которую вызывает сайт
from apps.bot.models import BotEvent
from apps.orders.models import Order
from apps.tables.models import Table


class BotEventsTest(TestCase):
    """add_event: запись, проверка типа, откат вместе с транзакцией."""

    def setUp(self):
        self.order = Order.objects.create(kind=Order.Kind.DELIVERY, table=Table.delivery_point())  # заказ на доставку

    def test_add_event_saves(self):
        """Событие записано с подробностями и ждёт бота."""
        event = add_event(Kind.ORDER_CHANGED, order=self.order, action="accept", user_id=5)  # сайт записал событие
        event.refresh_from_db()                                              # перечитали из базы
        self.assertEqual(event.kind, Kind.ORDER_CHANGED)                     # тип верный
        self.assertEqual(event.order, self.order)                            # заказ верный
        self.assertEqual(event.payload, {"action": "accept", "user_id": 5})  # подробности сохранились
        self.assertIsNone(event.processed_at)                                # бот ещё не отправил

    def test_unknown_kind_rejected(self):
        """Опечатка в типе — ошибка, в базу ничего не попало."""
        with self.assertRaises(ValueError):                                  # ждём ошибку
            add_event("order_creatd", order=self.order)                      # опечатка
        self.assertEqual(BotEvent.objects.count(), 0)                        # событий нет

    def test_event_rolls_back_with_transaction(self):
        """Если заказ не сохранился (ошибка в транзакции) — события тоже нет."""
        try:
            with transaction.atomic():                                       # как в create_order / change_status
                add_event(Kind.ORDER_CREATED, order=self.order)              # событие записали…
                raise RuntimeError("ошибка дальше по коду")                  # …но потом что-то сломалось
        except RuntimeError:
            pass                                                             # ошибку ожидали
        self.assertEqual(BotEvent.objects.count(), 0)                        # событие откатилось вместе со всем