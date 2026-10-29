"""
Курьер, причины отклонения, «Освободить стол» для гостя, большой QR.
Запуск: python manage.py test tests -v 2
"""

from io import BytesIO

from PIL import Image                                  # проверяем размер картинки QR

from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest      # общая подготовка из основного теста


class CourierTests(BaseAPITest):

    def setUp(self):
        super().setUp()
        self.courier = User.objects.create_user("courier", password=PASSWORD, role=User.Role.COURIER)
        self.courier2 = User.objects.create_user("courier2", password=PASSWORD, role=User.Role.COURIER)

    def delivery_order(self):
        """Гость заказал доставку с главной страницы."""
        self.as_user(None)
        body = {"table_token": self.delivery.token, "items": [{"dish_id": self.burger.id, "quantity": 3}], "order_type": "delivery",
                "customer_name": "Бекзат", "phone": "+996700000000", "address": "Чуй 1"}
        return self.client.post("/api/orders/", body, format="json").data["number"]

    def courier_sees(self, user, number):
        self.as_user(user)
        return {o["number"]: o for o in self.client.get("/api/staff/orders/?active=true").data}.get(number)

    def actions(self, user, number):
        return [a["action"] for a in self.courier_sees(user, number)["available_actions"]]

    def test_sees_delivery_only_after_confirm(self):
        number = self.delivery_order()
        self.assertIsNone(self.courier_sees(self.courier, number))        # новую доставку курьер не видит
        self.act(self.admin, number, "accept")
        order = self.courier_sees(self.courier, number)
        self.assertEqual(order["address"], "Чуй 1")                        # адрес и телефон на месте
        self.assertEqual(order["phone"], "+996700000000")
        hall = self.hall_order().data["number"]
        self.act(self.waiter, hall, "accept")
        self.assertIsNone(self.courier_sees(self.courier, hall))          # заказы зала курьер не видит

    def test_full_delivery_by_courier(self):
        number = self.delivery_order()
        self.act(self.admin, number, "accept")
        self.assertEqual(self.actions(self.courier, number), ["claim"])    # только «Беру заказ»
        self.as_user(self.courier)
        self.assertEqual(self.client.post(f"/api/staff/orders/{number}/claim/").status_code, 200)
        self.as_user(self.courier2)
        self.assertEqual(self.client.post(f"/api/staff/orders/{number}/claim/").status_code, 400)   # уже взял другой
        self.assertEqual(self.courier_sees(self.courier2, number)["claimed_by_name"], "courier")
        self.act(self.cook, number, "cook")
        self.act(self.cook, number, "ready")
        self.assertEqual(self.act(self.courier2, number, "send").status_code, 403)   # чужой заказ не везёт
        self.assertEqual(self.act(self.courier, number, "send").status_code, 200)    # «В пути»
        self.assertEqual(self.act(self.courier, number, "complete").data["status"], "completed")   # «Доставлен»

    def test_courier_cannot_confirm_cook_or_cancel(self):
        number = self.delivery_order()
        self.assertIn(self.act(self.courier, number, "accept").status_code, (403, 404))   # новый заказ курьеру даже не виден
        self.act(self.admin, number, "accept")
        self.assertEqual(self.act(self.courier, number, "cook").status_code, 403)
        self.assertEqual(self.act(self.courier, number, "cancel", "x").status_code, 403)

    def test_who_can_make_courier(self):
        self.as_user(self.admin)
        roles = [r["value"] for r in self.client.get("/api/admin/staff/roles/").data]
        self.assertIn("courier", roles)                                    # админ может назначить курьера
        self.assertIn(User.Role.COURIER, self.chef.assignable_roles())
        self.assertEqual(self.waiter.assignable_roles(), [])
        self.assertEqual(self.courier.assignable_roles(), [])


class RejectReasonTests(BaseAPITest):

    def test_reason_depends_on_place(self):
        self.as_user(None)
        body = {"table_token": self.delivery.token, "items": [{"dish_id": self.burger.id, "quantity": 1}], "order_type": "pickup",
                "customer_name": "Айгуль", "phone": "+996555000000"}
        number = self.client.post("/api/orders/", body, format="json").data["number"]
        self.assertEqual(self.act(self.admin, number, "reject").data["cancel_reason"], "Кафе не смогло принять заказ")
        number = self.hall_order().data["number"]
        self.assertEqual(self.act(self.waiter, number, "reject", "Гость ушёл").data["cancel_reason"], "Гость ушёл")


class FreeTableTests(BaseAPITest):

    def test_guest_sees_table_freed(self):
        url = f"/api/tables/{self.table.token}/"
        self.as_user(None)
        self.assertIsNone(self.client.get(url).data["freed_at"])          # стол ещё не освобождали
        self.as_user(self.waiter)
        self.client.post(f"/api/staff/tables/{self.table.id}/close-visit/")
        self.as_user(None)
        self.assertIsNotNone(self.client.get(url).data["freed_at"])       # гость по этому полю выходит из режима стола

    def test_qr_is_big_enough_to_print(self):
        self.as_user(self.admin)
        response = self.client.get(f"/api/admin/tables/{self.table.id}/qr/")
        width, height = Image.open(BytesIO(response.content)).size
        self.assertGreaterEqual(width, 900)                                # ~1000 px — чётко печатается