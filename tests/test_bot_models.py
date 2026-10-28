"""
Проверка таблиц Telegram-бота (шаг 1).
Запуск: python manage.py test tests.test_bot_models -v 2
"""

from datetime import timedelta                # промежуток времени

from django.db import IntegrityError, transaction  # ошибка базы; «откат» внутри теста
from django.test import TestCase              # обычный тест Django
from django.utils import timezone             # текущее время

from apps.bot.models import BotEvent, BotMessage, LinkCode
from apps.bot.services import create_link_code
from apps.orders.models import Order, TableCall
from apps.tables.models import Table
from apps.users.models import User


class BotModelsTest(TestCase):
    """Коды привязки, события и сообщения бота."""

    def setUp(self):
        self.waiter = User.objects.create_user("waiter", password="x", role=User.Role.WAITER)       # сотрудник
        self.table = Table.objects.create(kind=Table.Kind.HALL, number=7)                            # стол 7
        self.order = Order.objects.create(kind=Order.Kind.DELIVERY, table=Table.delivery_point())    # заказ на доставку
        self.call = TableCall.objects.create(table=self.table, kind=TableCall.Kind.WAITER)           # вызов официанта

    # ===== Коды привязки =====

    def test_link_code_is_valid(self):
        """Новый код: 22 символа и годен."""
        link = create_link_code(self.waiter)          # выдаём код
        self.assertEqual(len(link.code), 22)          # длина кода
        self.assertTrue(link.is_valid())              # годен

    def test_new_link_code_removes_old(self):
        """Второй код заменяет первый."""
        first = create_link_code(self.waiter)         # первый код
        second = create_link_code(self.waiter)        # второй код
        self.assertNotEqual(first.code, second.code)  # коды разные
        self.assertEqual(LinkCode.objects.filter(user=self.waiter).count(), 1)  # остался только один

    def test_link_code_expires(self):
        """Через 10 минут код не годен."""
        link = create_link_code(self.waiter)          # выдаём код
        LinkCode.objects.filter(pk=link.pk).update(created_at=timezone.now() - timedelta(minutes=11))  # «состарили» на 11 минут
        link.refresh_from_db()                        # перечитали из базы
        self.assertFalse(link.is_valid())             # просрочен

    def test_used_link_code_invalid(self):
        """Использованный код второй раз не годен."""
        link = create_link_code(self.waiter)          # выдаём код
        link.used_at = timezone.now()                 # отметили «использован»
        link.save()                                   # сохранили
        self.assertFalse(link.is_valid())             # больше не годен

    # ===== События =====

    def test_event_waits_for_bot(self):
        """Новое событие ждёт бота: не отправлено, попыток 0."""
        event = BotEvent.objects.create(kind=BotEvent.Kind.ORDER_CREATED, order=self.order)  # сайт записал событие
        self.assertIsNone(event.processed_at)         # ещё не отправлено
        self.assertEqual(event.attempts, 0)           # попыток не было
        self.assertEqual(list(BotEvent.objects.filter(processed_at__isnull=True)), [event])  # бот его найдёт

    # ===== Сообщения =====

    def test_one_message_per_order_and_place(self):
        """У заказа одно сообщение в теме, в разных темах — можно."""
        BotMessage.objects.create(order=self.order, place=BotMessage.Place.ADMINS, chat_id=-100, message_id=1)   # «Админы»
        BotMessage.objects.create(order=self.order, place=BotMessage.Place.KITCHEN, chat_id=-100, message_id=2)  # «Кухня» — можно
        with self.assertRaises(IntegrityError), transaction.atomic():           # второе в «Админы» — ошибка
            BotMessage.objects.create(order=self.order, place=BotMessage.Place.ADMINS, chat_id=-100, message_id=3)

    def test_message_needs_order_or_call(self):
        """Сообщение принадлежит или заказу, или вызову — ровно одному."""
        BotMessage.objects.create(call=self.call, place=BotMessage.Place.HALL, chat_id=-100, message_id=4)  # вызов — можно
        with self.assertRaises(IntegrityError), transaction.atomic():           # ни заказа, ни вызова — ошибка
            BotMessage.objects.create(place=BotMessage.Place.HALL, chat_id=-100, message_id=5)
        with self.assertRaises(IntegrityError), transaction.atomic():           # и заказ, и вызов сразу — ошибка
            BotMessage.objects.create(order=self.order, call=self.call, place=BotMessage.Place.GUEST, chat_id=-100, message_id=6)