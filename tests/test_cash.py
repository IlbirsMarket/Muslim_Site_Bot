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
        self.assertNotIn("accept", [a["action"] for o in orders for a in o["available_actions"]])   # но не подтверждает
        self.assertEqual(self.client.get("/api/admin/reports/day/").status_code, 403)   # отчёты — админу
        self.assertEqual(self.client.get("/api/admin/cafe/").status_code, 403)          # настройки кафе — админу
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
