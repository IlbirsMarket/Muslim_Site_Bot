"""
Кассир и «Касса»: смена, внесение / изъятие, оплата только в смену, отчёт за смену.
Запуск: python manage.py test tests -v 2
"""

from apps.orders.models import CashShift, PrintJob
from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest      # общая подготовка из основного теста


class CashierTests(BaseAPITest):

    def setUp(self):
        super().setUp()
        self.cashier = User.objects.create_user("cashier", password=PASSWORD, role=User.Role.CASHIER)

    def post(self, path, body=None, user=None):
        self.as_user(user or self.cashier)
        return self.client.post(path, body or {}, format="json")

    def paid_order(self):
        """Заказ со стола, подтверждён официантом."""
        number = self.hall_order().data["number"]
        self.act(self.waiter, number, "accept")
        return number

    def test_pay_only_in_open_shift(self):
        number = self.paid_order()
        response = self.post("/api/staff/bills/pay/", {"orders": [number], "method": "cash"})
        self.assertEqual(response.status_code, 400)                          # смена не открыта
        self.assertIn("смену", str(response.data))
        self.assertEqual(self.post("/api/staff/cash/open/", {"cash": 2000}).status_code, 200)
        self.assertEqual(self.post("/api/staff/cash/open/", {"cash": 1}).status_code, 400)   # вторую не открыть
        self.assertEqual(self.post("/api/staff/bills/pay/", {"orders": [number], "method": "cash"}).status_code, 200)
        self.assertEqual(self.post("/api/staff/bills/pay/", {"orders": [self.paid_order()], "method": "cash"}, user=self.admin).status_code, 200)   # админ — всегда

    def test_shift_flow_and_report(self):
        self.post("/api/staff/cash/open/", {"cash": 2000})
        a, b = self.paid_order(), self.paid_order()
        self.post("/api/staff/bills/pay/", {"orders": [a, b], "method": "mixed", "cash": 1000})
        self.post("/api/staff/cash/move/", {"kind": "in", "amount": 500, "comment": "размен"})
        self.post("/api/staff/cash/move/", {"kind": "out", "amount": 300})
        self.assertEqual(self.post("/api/staff/cash/move/", {"kind": "out", "amount": 999999}).status_code, 400)   # больше, чем в кассе
        self.as_user(self.cashier)
        shift = self.client.get("/api/staff/cash/").data["shift"]
        self.assertEqual((shift["cash"], shift["card"], shift["orders"]), (1000, 460, 2))
        self.assertEqual(shift["expected"], 2000 + 1000 + 500 - 300)
        report = self.post("/api/staff/cash/close/", {"counted": 3150}).data
        self.assertEqual(report["difference"], -50)                           # не хватает 50 сом
        self.assertTrue(PrintJob.objects.filter(kind="shift").exists())       # отчёт на чековый аппарат
        self.as_user(self.cashier)
        self.assertIsNone(self.client.get("/api/staff/cash/").data["shift"])
        self.as_user(self.admin)
        shifts = self.client.get("/api/admin/reports/day/").data["shifts"]
        self.assertEqual((shifts[0]["cashier"], shifts[0]["difference"]), ("cashier", -50))
        self.assertEqual(self.client.get("/api/admin/reports/day/pdf/").status_code, 200)

    def test_cashier_rights(self):
        self.as_user(self.cashier)
        number = self.hall_order().data["number"]
        self.as_user(self.cashier)
        orders = self.client.get("/api/staff/orders/?active=true").data
        self.assertIn(number, [o["number"] for o in orders])                 # видит заказы
        self.assertIn("accept", [a["action"] for o in orders for a in o["available_actions"]])      # подтверждает, как админ
        self.assertEqual(self.client.get("/api/admin/reports/day/").status_code, 200)   # отчёты — как у админа
        self.assertEqual(self.client.get("/api/admin/reports/period/").status_code, 200)  # и 45 дней
        self.assertEqual(self.client.patch("/api/admin/cafe/", {"delivery_fee": 150}, format="json").status_code, 200)   # настройки своего филиала
        self.assertEqual(self.cashier.assignable_roles(), self.admin.assignable_roles())   # сотрудников — как админ
        self.assertNotIn(User.Role.CHEF, self.cashier.assignable_roles())                  # шефа — нет
        self.as_user(self.waiter)
        self.assertEqual(self.client.get("/api/staff/cash/").status_code, 403)          # «Касса» официанту не видна
        self.assertIn(User.Role.CASHIER, self.admin.assignable_roles())                 # админ может назначить кассира
        self.assertTrue(self.cashier.is_cashier)
        self.assertEqual(CashShift.objects.count(), 0)

    def test_cashier_hands_out_pickup(self):
        self.as_user(None)
        body = {"table_token": self.delivery.token, "items": [{"dish_id": self.burger.id, "quantity": 1}], "order_type": "pickup",
                "customer_name": "Бекзат", "phone": "+996700000000"}
        number = self.client.post("/api/orders/", body, format="json").data["number"]
        for user, action in [(self.admin, "accept"), (self.cook, "cook"), (self.cook, "ready")]:
            self.act(user, number, action)
        self.assertEqual(self.act(self.cashier, number, "complete").status_code, 200)   # «Выдан»


class HistoryAndFreeTableTests(BaseAPITest):

    def setUp(self):
        super().setUp()
        self.cashier = User.objects.create_user("cashier", password=PASSWORD, role=User.Role.CASHIER)
        self.as_user(self.cashier)
        self.client.post("/api/staff/cash/open/", {"cash": 0}, format="json")

    def serve(self, number):
        """Подтвердить, приготовить и подать на стол."""
        for user, action in [(self.waiter, "accept"), (self.cook, "cook"), (self.cook, "ready"), (self.waiter, "complete")]:
            self.act(user, number, action)

    def pay(self, numbers):
        self.as_user(self.cashier)
        return self.client.post("/api/staff/bills/pay/", {"orders": numbers, "method": "cash"}, format="json")

    def test_paid_and_served_table_is_freed(self):
        number = self.hall_order(device_key="p").data["number"]
        self.serve(number)
        self.table.refresh_from_db()
        self.assertIsNotNone(self.table.occupied_since)                       # гости сидят
        self.assertTrue(self.pay([number]).data["table_freed"])
        self.table.refresh_from_db()
        self.assertIsNone(self.table.occupied_since)                          # стол свободен
        self.assertIsNotNone(self.table.freed_at)
        from apps.bot.models import BotEvent
        self.assertTrue(BotEvent.objects.filter(kind="table_freed", table=self.table).exists())   # гостю в Telegram — «стол освобождён»

    def test_prepaid_table_freed_after_last_order_served(self):
        number = self.hall_order(device_key="p").data["number"]
        self.act(self.waiter, number, "accept")
        self.assertFalse(self.pay([number]).data["table_freed"])             # заплатили заранее, еду ещё не подали
        self.table.refresh_from_db()
        self.assertIsNotNone(self.table.occupied_since)
        for user, action in [(self.cook, "cook"), (self.cook, "ready"), (self.waiter, "complete")]:
            self.act(user, number, action)
        self.table.refresh_from_db()
        self.assertIsNone(self.table.occupied_since)                          # подали — стол свободен

    def test_history_and_receipt_copy(self):
        a = self.hall_order().data["number"]
        self.act(self.waiter, a, "accept")
        self.pay([a])
        self.as_user(self.cashier)
        rows = self.client.get("/api/staff/cash/").data["history"]
        self.assertEqual((rows[0]["orders"], rows[0]["total"], rows[0]["method"], rows[0]["by"]), ([a], 730, "Наличные", "cashier"))
        self.assertEqual(self.client.post("/api/staff/cash/receipt-copy/", {"orders": [a]}, format="json").status_code, 200)
        copy = PrintJob.objects.filter(kind="receipt").last().payload
        self.assertEqual(copy["title"], "СЧЕТ (КОПИЯ)")
        self.assertEqual(copy["payment"]["cash"], 730)


class CourierAndAutoFreeTests(BaseAPITest):

    def test_courier_sees_and_pays_own_delivery(self):
        courier = User.objects.create_user("courier", password=PASSWORD, role=User.Role.COURIER)
        self.as_user(None)
        body = {"table_token": self.delivery.token, "items": [{"dish_id": self.burger.id, "quantity": 3}], "order_type": "delivery",
                "customer_name": "Бекзат", "phone": "+996700000000", "address": "Чуй 1"}
        number = self.client.post("/api/orders/", body, format="json").data["number"]
        self.act(self.admin, number, "accept")
        self.as_user(courier)
        self.assertEqual([b["orders"] for b in self.client.get("/api/staff/bills/").data], [[number]])   # курьер видит доставку в «К оплате»
        hall = self.hall_order().data["number"]
        self.act(self.waiter, hall, "accept")
        self.as_user(courier)
        self.assertEqual(len(self.client.get("/api/staff/bills/").data), 1)                              # зал курьеру не виден
        self.assertEqual(self.client.post("/api/staff/bills/pay/", {"orders": [hall], "method": "cash"}, format="json").status_code, 403)
        self.assertEqual(self.client.post("/api/staff/bills/pay/", {"orders": [number], "method": "cash"}, format="json").status_code, 200)

    def test_table_freed_after_4_hours(self):
        from datetime import timedelta
        from django.core.cache import cache
        from django.utils import timezone
        from apps.tables.models import Table
        number = self.hall_order(device_key="p").data["number"]
        self.act(self.waiter, number, "accept")
        Table.objects.filter(pk=self.table.pk).update(occupied_since=timezone.now() - timedelta(hours=4, minutes=5))
        cache.delete("free-stale-tables")
        self.as_user(None)
        self.client.get("/api/version/")                                       # панели спрашивают каждые 1–2 секунды
        self.table.refresh_from_db()
        self.assertIsNone(self.table.occupied_since)                          # стол освободился сам
        self.assertIsNotNone(self.table.freed_at)


class PastShiftsTests(BaseAPITest):

    def test_past_shifts_and_copy(self):
        cashier = User.objects.create_user("cashier", password=PASSWORD, role=User.Role.CASHIER)
        self.as_user(cashier)
        self.client.post("/api/staff/cash/open/", {"cash": 1000}, format="json")
        self.client.post("/api/staff/cash/close/", {"counted": 950}, format="json")
        rows = self.client.get("/api/staff/cash/").data["past_shifts"]
        self.assertEqual((rows[0]["opened_by"], rows[0]["closed_by"], rows[0]["opening_cash"], rows[0]["difference"]), ("cashier", "cashier", 1000, -50))
        self.assertEqual(self.client.post("/api/staff/cash/shift-copy/", {"id": rows[0]["id"]}, format="json").status_code, 200)
        self.assertEqual(PrintJob.objects.filter(kind="shift").last().payload["title"], "ОТЧЁТ ЗА СМЕНУ (КОПИЯ)")
