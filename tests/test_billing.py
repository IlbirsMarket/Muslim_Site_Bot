"""
Оплата и чеки: «К оплате», «Оплатить», задания для чекового аппарата, отчёт по официантам.
Запуск: python manage.py test tests -v 2
"""

from apps.orders.models import Order, PrintJob, TableCall
from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest      # общая подготовка из основного теста


class BillingTests(BaseAPITest):

    def claim(self, user=None):
        """Кассовый компьютер забирает чеки на печать (кухонные — отдельно, их здесь не берём)."""
        self.as_user(user or self.admin)
        return self.client.post("/api/staff/print-jobs/claim/", {"kinds": ["order", "bill", "receipt", "shift"]}, format="json").data

    def bills(self, user=None):
        self.as_user(user or self.admin)
        return self.client.get("/api/staff/bills/").data

    def pay(self, orders, method="cash", user=None, **extra):
        self.as_user(user or self.admin)
        return self.client.post("/api/staff/bills/pay/", {"orders": orders, "method": method, **extra}, format="json")

    def test_order_ticket_printed_after_confirm(self):
        number = self.hall_order().data["number"]
        self.assertEqual(self.claim(), [])                                   # новый — ещё не печатаем
        self.act(self.waiter, number, "accept")
        jobs = self.claim()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["kind"], "order")
        ticket = jobs[0]["payload"]
        self.assertEqual(ticket["title"], "СЧЕТ")
        self.assertEqual(ticket["items"][0]["name"], "Пепперони 30 см")
        self.assertEqual(ticket["items"][0]["extras"], ["Сыр"])
        self.assertEqual(ticket["total"], 730)
        self.assertEqual(self.claim(), [])                                   # второй раз не печатается

    def test_trusted_phone_order_printed_at_once(self):
        first = self.hall_order(device_key="phone-1").data["number"]
        self.act(self.waiter, first, "accept")
        self.claim()
        self.hall_order(device_key="phone-1")                                # повторный заказ — сразу принят
        self.assertEqual([j["kind"] for j in self.claim()], ["order"])

    def test_table_orders_are_one_bill_and_pay_prints_receipt(self):
        a = self.hall_order(device_key="p").data["number"]
        self.act(self.waiter, a, "accept")
        b = self.hall_order(device_key="p").data["number"]                   # второй заказ того же стола
        bills = self.bills()
        self.assertEqual(len(bills), 1)                                      # один счёт на стол
        self.assertEqual(sorted(bills[0]["orders"]), sorted([a, b]))
        self.assertEqual(bills[0]["total"], 1460)
        self.assertEqual(bills[0]["items"][0]["qty"], 2)                     # одинаковые позиции сложились
        self.claim()

        response = self.pay([a, b], "cash", received=2000)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["change"], 540)                       # сдача
        self.assertEqual(self.bills(), [])                                    # больше не к оплате
        receipt = self.claim()[0]
        self.assertEqual(receipt["kind"], "receipt")
        self.assertEqual(receipt["payload"]["payment"]["method"], "Наличные")
        self.assertEqual(Order.objects.get(pk=a).paid_cash + Order.objects.get(pk=b).paid_cash, 1460)
        self.assertEqual(self.pay([a, b]).status_code, 400)                   # второй раз — нельзя

    def test_mixed_payment_split(self):
        number = self.hall_order().data["number"]
        self.assertEqual(self.pay([number], "mixed").status_code, 400)       # не сказали, сколько наличными
        self.assertEqual(self.pay([number], "mixed", cash=230).status_code, 200)
        order = Order.objects.get(pk=number)
        self.assertEqual((order.paid_cash, order.paid_card, order.paid_method), (230, 500, "mixed"))

    def test_bill_request_closed_by_payment(self):
        number = self.hall_order().data["number"]
        self.assertEqual(self.bills(), [])                                   # неподтверждённый — ещё не к оплате
        self.act(self.waiter, number, "accept")
        TableCall.objects.create(table=self.table, kind=TableCall.Kind.BILL, people=3)
        bill = self.bills()[0]
        self.assertTrue(bill["bill_requested"])
        self.assertEqual(bill["people"], 3)
        self.pay([number], "card")
        self.assertTrue(TableCall.objects.get().is_done)                     # просьба о счёте выполнена

    def test_print_bill_without_payment(self):
        number = self.hall_order().data["number"]
        self.as_user(self.admin)
        self.assertEqual(self.client.post("/api/staff/bills/print/", {"orders": [number]}, format="json").status_code, 200)
        job = self.claim()[0]
        self.assertEqual((job["kind"], job["payload"]["title"]), ("bill", "СЧЕТ"))
        self.assertIsNone(Order.objects.get(pk=number).paid_at)              # счёт — ещё не оплата

    def test_cook_cannot_pay_and_waiter_only_own_table(self):
        number = self.hall_order().data["number"]
        self.assertEqual(self.pay([number], user=self.cook).status_code, 403)
        other = User.objects.create_user("waiter2", password=PASSWORD, role=User.Role.WAITER)
        self.table.waiter = self.waiter
        self.table.save()
        self.assertEqual(self.pay([number], user=other).status_code, 403)    # стол ведёт другой официант
        self.assertEqual(self.pay([number], user=self.waiter).status_code, 200)

    def test_delivery_not_paid_until_pay(self):
        self.as_user(None)
        body = {"table_token": self.delivery.token, "items": [{"dish_id": self.burger.id, "quantity": 3}], "order_type": "delivery",
                "customer_name": "Бекзат", "phone": "+996700000000", "address": "Чуй 1", "payment_method": "card"}
        number = self.client.post("/api/orders/", body, format="json").data["number"]
        for user, action in [(self.admin, "accept"), (self.cook, "cook"), (self.cook, "ready"), (self.admin, "send"), (self.admin, "complete")]:
            self.act(user, number, action)
        order = Order.objects.get(pk=number)
        self.assertIsNone(order.paid_at)                                      # «Доставлен» — ещё не оплата
        self.assertIn(number, [n for b in self.bills() for n in b["orders"]])  # ждёт в «К оплате»
        self.assertEqual(self.pay([number], "card").status_code, 200)         # оплатили — тогда чек об оплате
        kinds = [j.kind for j in PrintJob.objects.order_by("id")]
        self.assertEqual(kinds, ["kitchen1", "order", "receipt"])
        receipt = PrintJob.objects.last().payload
        self.assertEqual(receipt["place"], "Доставка")
        self.assertEqual(receipt["address"], "Чуй 1")

    def test_waiters_in_report(self):
        number = self.hall_order().data["number"]
        self.as_user(self.waiter)
        self.client.post(f"/api/staff/orders/{number}/claim/")
        for user, action in [(self.waiter, "accept"), (self.cook, "cook"), (self.cook, "ready"), (self.waiter, "complete")]:
            self.act(user, number, action)
        self.pay([number], "cash")
        self.as_user(self.admin)
        report = self.client.get("/api/admin/reports/day/").data
        waiter = report["waiters"][0]
        self.assertEqual((waiter["name"], waiter["orders"], waiter["revenue"]), ("waiter", 1, 730))
        self.assertEqual(report["by_payment"]["cash"]["revenue"], 730)
        self.assertEqual(self.client.get("/api/admin/reports/day/pdf/").status_code, 200)   # PDF с официантами собирается

    def test_bill_preview_does_not_print(self):
        number = self.hall_order().data["number"]
        self.as_user(self.admin)
        job = self.client.post("/api/staff/bills/preview/", {"orders": [number]}, format="json").data
        self.assertEqual((job["kind"], job["payload"]["title"], job["payload"]["total"]), ("bill", "СЧЕТ", 730))
        self.assertFalse(PrintJob.objects.exists())                          # только показали — на аппарат не ушло

    def test_kitchen_ticket_and_claim_by_kind(self):
        number = self.hall_order().data["number"]
        self.act(self.waiter, number, "accept")
        self.as_user(self.admin)
        kitchen = self.client.post("/api/staff/print-jobs/claim/", {"kinds": ["kitchen1", "kitchen2"]}, format="json").data
        self.assertEqual([j["kind"] for j in kitchen], ["kitchen1"])              # кухня забрала только свой чек
        ticket = kitchen[0]["payload"]
        self.assertEqual((ticket["items"][0]["name"], ticket["items"][0]["qty"], ticket["items"][0]["extras"]), ("Пепперони 30 см", 1, ["Сыр"]))
        self.assertNotIn("total", ticket)                                       # на кухне без цен
        cash = self.client.post("/api/staff/print-jobs/claim/", {"kinds": ["order", "bill", "receipt", "shift"]}, format="json").data
        self.assertEqual([j["kind"] for j in cash], ["order"])                  # касса — чек заказа


    def test_items_split_between_kitchens(self):
        from apps.orders.models import PrintJob
        self.burgers.printer = "kitchen2"                                         # бургеры — фастфуд
        self.burgers.save()
        drinks = self.pizzas.__class__.objects.create(name="Напитки", printer="none")
        tea = self.burger.__class__.objects.create(category=drinks, name="Чай", price=80)
        self.as_user(None)
        body = {"table_token": self.table.token, "items": [
            {"dish_id": self.pizza.id, "size_id": self.size30.id, "quantity": 1},
            {"dish_id": self.burger.id, "quantity": 2}, {"dish_id": tea.id, "quantity": 3}]}
        number = self.client.post("/api/orders/", body, format="json").data["number"]
        self.act(self.waiter, number, "accept")
        jobs = {j.kind: j.payload for j in PrintJob.objects.filter(kind__in=["kitchen1", "kitchen2"])}
        self.assertEqual([i["name"] for i in jobs["kitchen1"]["items"]], ["Пепперони 30 см"])   # пицца — аппарат 1 (по умолчанию)
        self.assertEqual([(i["name"], i["qty"]) for i in jobs["kitchen2"]["items"]], [("Чизбургер", 2)])
        self.assertEqual(jobs["kitchen1"]["number"], jobs["kitchen2"]["number"])   # заказ один
        names = [i["name"] for p in jobs.values() for i in p["items"]]
        self.assertNotIn("Чай", names)                                            # напитки на кухню не идут
