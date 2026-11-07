"""
«Заказ за гостя»: официант / админ / кассир вбивает заказ сам — как в 1С.
Запуск: python manage.py test tests -v 2
"""

from apps.orders.models import Order, PrintJob
from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest      # общая подготовка из основного теста

URL = "/api/staff/quick-order/"


class QuickOrderTests(BaseAPITest):

    def order(self, user, table, items, comment=""):
        self.as_user(user)
        return self.client.post(URL, {"table": table, "items": items, "comment": comment}, format="json")

    def pizza_line(self, qty=1, extras=None):
        return {"dish_id": self.pizza.id, "size_id": self.size30.id, "quantity": qty, "extra_ids": extras or []}

    def test_tables_and_menu_without_photos(self):
        self.as_user(self.waiter)
        data = self.client.get(URL).data
        self.assertEqual([t["id"] for t in data["tables"]], [self.table.id])     # только столы зала, без «Доставки»
        self.assertFalse(data["tables"][0]["busy"])
        dishes = [d for c in data["menu"] for d in c["dishes"]]
        pizza = next(d for d in dishes if d["id"] == self.pizza.id)
        self.assertIn({"id": self.size30.id, "name": "30 см", "price": 650}, pizza["sizes"])   # размеры — отдельными кнопками
        self.assertNotIn("photo", pizza)

    def test_waiter_order_goes_to_kitchen_and_table_is_his(self):
        response = self.order(self.waiter, self.table.id, [self.pizza_line(2, [self.cheese.id])], "без лука")
        self.assertEqual(response.status_code, 201, response.data)
        order = Order.objects.get(pk=response.data["number"] if "number" in response.data else response.data["id"])
        self.assertEqual((order.status, order.kind, order.source, order.total), ("accepted", "hall", "staff", 2 * 730))
        self.assertEqual(order.accepted_by, self.waiter)
        self.assertIn("kitchen1", PrintJob.objects.values_list("kind", flat=True))   # чек на кухню — как после «Подтвердить»
        self.table.refresh_from_db()
        self.assertEqual(self.table.waiter, self.waiter)                       # стол за официантом
        self.assertIsNotNone(self.table.occupied_since)
        self.as_user(self.waiter)
        table = self.client.get(URL).data["tables"][0]
        self.assertEqual((table["busy"], table["total"], table["waiter"]), (True, 1460, "waiter"))

    def test_extra_order_same_bill(self):
        self.order(self.waiter, self.table.id, [self.pizza_line()])
        self.order(self.admin, self.table.id, [{"dish_id": self.burger.id, "quantity": 1}])   # админ дозаказал
        self.as_user(self.admin)
        bills = self.client.get("/api/staff/bills/").data
        self.assertEqual(len(bills), 1)                                        # один счёт на стол
        self.assertEqual(bills[0]["total"], 650 + 390)

    def test_other_waiter_cannot_order_on_busy_table(self):
        self.order(self.waiter, self.table.id, [self.pizza_line()])
        other = User.objects.create_user("waiter2", password=PASSWORD, role=User.Role.WAITER)
        self.assertEqual(self.order(other, self.table.id, [self.pizza_line()]).status_code, 403)

    def test_takeaway_without_table(self):
        cashier = User.objects.create_user("kassa", password=PASSWORD, role=User.Role.CASHIER)
        response = self.order(cashier, None, [{"dish_id": self.burger.id, "quantity": 2}])
        self.assertEqual(response.status_code, 201, response.data)
        order = Order.objects.get()
        self.assertEqual((order.kind, order.table_id, order.status), ("takeaway", None, "accepted"))
        self.as_user(cashier)
        bill = self.client.get("/api/staff/bills/").data[0]
        self.assertEqual(bill["total"], 780)

    def test_waiter_cannot_take_takeaway(self):
        self.assertEqual(self.order(self.waiter, None, [{"dish_id": self.burger.id, "quantity": 1}]).status_code, 403)   # «С собой» — касса
        self.assertEqual(self.order(self.admin, None, [{"dish_id": self.burger.id, "quantity": 1}]).status_code, 201)

    def test_rules(self):
        self.assertEqual(self.order(self.cook, self.table.id, [self.pizza_line()]).status_code, 403)   # повар — нет
        self.assertEqual(self.order(self.waiter, self.table.id, []).status_code, 400)                  # пусто
        self.assertEqual(self.order(self.waiter, self.table.id, [{"dish_id": self.pizza.id, "quantity": 1}]).status_code, 400)  # без размера
        self.burger.is_available = False
        self.burger.save()
        self.assertEqual(self.order(self.waiter, self.table.id, [{"dish_id": self.burger.id, "quantity": 1}]).status_code, 400)   # стоп-лист
        self.assertEqual(self.order(self.waiter, self.delivery.id, [self.pizza_line()]).status_code, 400)   # не стол зала
