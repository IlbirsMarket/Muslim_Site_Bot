"""
«Касса» → «Официанты»: выплата официантам за смену (процент или сумма вручную), изъятие из кассы, печать.
Запуск: python manage.py test tests -v 2
"""

from apps.orders.models import CashMove, PrintJob
from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest      # общая подготовка из основного теста

URL = "/api/staff/cash/waiters/"


class WaiterPayTests(BaseAPITest):

    def setUp(self):
        super().setUp()
        self.cashier = User.objects.create_user("cashier", password=PASSWORD, role=User.Role.CASHIER)
        self.as_user(self.cashier)
        self.client.post("/api/staff/cash/open/", {"cash": 1000}, format="json")

    def table_order(self, waiter, items, pay=True):
        """Официант вбил заказ на стол (он — официант стола), кассир принял оплату."""
        self.as_user(waiter)
        number = self.client.post("/api/staff/quick-order/", {"table": self.table.id, "items": items}, format="json").data["number"]
        if pay:
            self.as_user(self.cashier)
            self.client.post("/api/staff/bills/pay/", {"orders": [number], "method": "cash"}, format="json")
        return number

    def test_percent_and_manual_payout_and_print(self):
        self.table_order(self.waiter, [{"dish_id": self.burger.id, "quantity": 10}])      # 3 900 сом, оплачен
        self.as_user(self.cashier)
        data = self.client.get(URL).data
        self.assertEqual((data["rows"][0]["name"], data["rows"][0]["orders"], data["rows"][0]["total"]), ("waiter", 1, 3900))

        data = self.client.post(URL, {"mode": "percent", "percent": 5, "amounts": {}}, format="json").data
        self.assertEqual(data["rows"][0]["amount"], 195)                                   # 5% от 3 900
        data = self.client.post(URL, {"mode": "percent", "percent": 5, "amounts": {str(self.waiter.id): 300}}, format="json").data
        self.assertEqual(data["amount"], 300)                                              # поправили вручную

        self.assertEqual(self.client.post(URL + "?action=payout").status_code, 200)
        self.assertEqual(CashMove.objects.get().amount, 300)                              # изъятие «Официантам»
        self.assertEqual(self.client.post(URL + "?action=payout").status_code, 400)       # второй раз — нельзя

        self.client.post(URL + "?action=print")
        job = PrintJob.objects.filter(kind="shift").last().payload
        self.assertTrue(job["waiters_only"])
        self.assertEqual(job["waiters"][0]["amount"], 300)

        report = self.client.post("/api/staff/cash/close/", {"counted": 4600}, format="json").data
        self.assertEqual(report["waiters_amount"], 300)                                    # в отчёте смены
        self.assertEqual(report["expected"], 1000 + 3900 - 300)

    def test_only_paid_hall_orders(self):
        self.table_order(self.waiter, [{"dish_id": self.burger.id, "quantity": 1}], pay=False)   # не оплачен
        self.as_user(self.admin)
        self.client.post("/api/staff/quick-order/", {"table": None, "items": [{"dish_id": self.burger.id, "quantity": 1}]}, format="json")   # «С собой»
        self.as_user(self.cashier)
        self.assertEqual(self.client.get(URL).data["rows"], [])

    def test_waiter_cannot_see(self):
        self.as_user(self.waiter)
        self.assertEqual(self.client.get(URL).status_code, 403)
