"""
Столы и доставка: два этажа, номера ставятся сами на каждом этаже, доставка одна и всегда есть,
статус «Занят / Свободен», заказы «в кафе», «с собой», доставка и самовывоз.
Запуск: python manage.py test tests -v 2
"""

from apps.orders.models import Order
from apps.tables.models import Table
from tests.test_api import BaseAPITest           # общая подготовка из основного теста

TABLES = "/api/admin/tables/"


class TableNumberTests(BaseAPITest):

    def add(self, floor=None):
        """Админ нажал «+ Добавить стол» на вкладке этажа (без формы)."""
        self.as_user(self.admin)
        return self.client.post(TABLES, {"floor": floor} if floor else {}, format="json")

    def test_names(self):
        self.assertEqual(self.table.name, "Стол 7 · 1 этаж")              # стол из подготовки — 1 этаж
        self.assertEqual(self.delivery.name, "Доставка")

    def test_add_takes_smallest_free_number(self):
        self.assertEqual(self.add().data["name"], "Стол 1 · 1 этаж")      # есть только 7 → свободен 1
        self.assertEqual(self.add().data["name"], "Стол 2 · 1 этаж")
        second = Table.objects.get(kind=Table.Kind.HALL, floor=1, number=2)
        self.client.delete(f"{TABLES}{second.id}/")                       # удалили «Стол 2»
        self.assertEqual(self.add().data["name"], "Стол 2 · 1 этаж")      # номер 2 снова занят новым столом

    def test_floors_have_own_numbers(self):
        self.assertEqual(self.add(floor=2).data["name"], "Стол 1 · 2 этаж")   # на 2 этаже своя нумерация
        self.assertEqual(self.add(floor=2).data["name"], "Стол 2 · 2 этаж")
        self.assertEqual(self.add(floor=1).data["name"], "Стол 1 · 1 этаж")   # на 1 этаже тоже есть «Стол 1»
        self.assertEqual(self.add(floor=3).status_code, 400)                  # третьего этажа нет
        self.as_user(self.admin)
        response = self.client.post(TABLES, {"floor": 1, "number": 7}, format="json")
        self.assertEqual(response.status_code, 400)                           # «Стол 7» на 1 этаже уже есть
        second_floor = Table.objects.get(floor=2, number=1)
        moved = self.client.patch(f"{TABLES}{second_floor.id}/", {"floor": 1}, format="json")
        self.assertEqual(moved.status_code, 400)                              # этаж готового стола не меняем

    def test_cannot_create_second_delivery(self):
        self.as_user(self.admin)
        created = self.client.post(TABLES, {"kind": "delivery"}, format="json").data
        self.assertEqual(created["kind"], "hall")                         # через API создаются только столы
        self.assertEqual(Table.objects.filter(kind=Table.Kind.DELIVERY).count(), 1)

    def test_delivery_always_in_list(self):
        self.delivery.delete()
        self.as_user(self.admin)
        kinds = [t["kind"] for t in self.client.get(TABLES).data]
        self.assertIn("delivery", kinds)                                  # пропала — создаётся заново

    def test_delivery_protected(self):
        self.as_user(self.admin)
        self.assertEqual(self.client.delete(f"{TABLES}{self.delivery.id}/").status_code, 400)
        self.assertIn("/t/", self.delivery.qr_url)                        # у доставки тоже секретный QR
        self.assertIn("/t/", self.table.qr_url)                           # QR стола — с секретным токеном
        old = self.delivery.token
        self.assertEqual(self.client.post(f"{TABLES}{self.delivery.id}/regenerate-qr/").status_code, 200)   # QR доставки можно перевыпустить
        self.as_user(None)
        self.assertEqual(self.client.get(f"/api/tables/{old}/").status_code, 404)   # старый QR доставки больше не работает

    def test_duplicate_number_rejected(self):
        self.as_user(self.admin)
        response = self.client.post(TABLES, {"number": 7}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_cannot_delete_busy_table(self):
        number = self.hall_order(device_key="phone-1").data["number"]
        self.as_user(self.admin)
        self.assertEqual(self.client.delete(f"{TABLES}{self.table.id}/").status_code, 400)   # есть заказ в работе
        self.act(self.waiter, number, "accept")
        self.act(self.cook, number, "cook")
        self.act(self.cook, number, "ready")
        self.act(self.waiter, number, "complete")
        self.as_user(self.admin)
        self.assertEqual(self.client.delete(f"{TABLES}{self.table.id}/").status_code, 400)   # стол ещё занят
        self.as_user(self.waiter)
        self.client.post(f"/api/staff/tables/{self.table.id}/close-visit/")                   # «Освободить стол»
        self.as_user(self.admin)
        self.assertEqual(self.client.delete(f"{TABLES}{self.table.id}/").status_code, 204)   # теперь можно

    def test_waiter_cannot_manage_tables(self):
        self.as_user(self.waiter)
        self.assertEqual(self.client.post(TABLES, {}, format="json").status_code, 403)
        self.assertEqual(self.client.delete(f"{TABLES}{self.table.id}/").status_code, 403)
        self.assertEqual(self.client.get("/api/staff/tables/").status_code, 200)              # но видит столы


class TableOccupancyTests(BaseAPITest):

    def occupied(self):
        self.table.refresh_from_db()
        return self.table.occupied_since is not None

    def test_occupied_until_freed(self):
        number = self.hall_order(device_key="phone-1").data["number"]
        self.assertFalse(self.occupied())                                 # неподтверждённый заказ стол не занимает
        self.act(self.waiter, number, "accept")
        self.assertTrue(self.occupied())                                  # официант подтвердил — занят
        self.act(self.cook, number, "cook")
        self.act(self.cook, number, "ready")
        self.act(self.waiter, number, "complete")
        self.assertTrue(self.occupied())                                  # еду подали, гости ещё сидят — занят

        self.as_user(self.waiter)
        self.client.post(f"/api/staff/tables/{self.table.id}/close-visit/")   # «Освободить стол»
        self.assertFalse(self.occupied())
        self.assertEqual(self.hall_order(device_key="phone-1").data["status"], "new")   # телефон больше не доверенный

    def test_only_waiter_and_admin_see_tables(self):
        self.as_user(self.cook)
        self.assertEqual(self.client.get("/api/staff/tables/").status_code, 403)


class OrderPlaceTests(BaseAPITest):
    """Откуда заказ: стол («в кафе», «с собой») или главная страница («доставка», «самовывоз»)."""

    def order(self, **body):
        """Гость заказывает. Без table_token в аргументах — по QR доставки."""
        self.as_user(None)
        body.setdefault("table_token", self.delivery.token)                         # QR доставки
        body.setdefault("items", [{"dish_id": self.burger.id, "quantity": 3}])   # 3 × 390 = 1170 (больше минимальной суммы доставки)
        return self.client.post("/api/orders/", body, format="json")

    def waiter_sees(self, number):
        self.as_user(self.waiter)
        return number in [o["number"] for o in self.client.get("/api/staff/orders/").data]

    def test_no_token_no_order(self):
        """Просто сайт без QR — только меню: заказ не принимается."""
        response = self.order(table_token="", customer_name="Бекзат", phone="+996700000000", address="Чуй 1")
        self.assertEqual(response.status_code, 400)
        self.assertIn("table_token", response.data)

    def test_delivery_by_delivery_qr(self):
        response = self.order(customer_name="Бекзат", phone="+996700000000", address="Чуй 1")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["kind"], "delivery")
        self.assertFalse(self.waiter_sees(response.data["number"]))       # доставку ведёт админ

    def test_pickup_from_main_page_needs_only_contacts(self):
        response = self.order(order_type="pickup", customer_name="Айгуль", phone="+996555000000")
        self.assertEqual(response.status_code, 201)                       # адрес не нужен
        self.assertEqual(response.data["kind"], "pickup")
        self.assertEqual(response.data["delivery_fee"], 0)                # за самовывоз доставку не берём
        self.assertFalse(self.waiter_sees(response.data["number"]))       # самовывоз ведёт админ
        self.assertEqual(self.order(order_type="pickup", customer_name="Айгуль").status_code, 400)   # без телефона нельзя

    def test_takeaway_from_table(self):
        response = self.order(table_token=self.table.token, order_type="takeaway", device_key="phone-9")
        self.assertEqual(response.status_code, 201)                       # контакты не нужны: гость за столом
        self.assertEqual(response.data["kind"], "takeaway")
        number = response.data["number"]
        self.assertTrue(self.waiter_sees(number))                         # официант видит заказ «с собой»
        self.assertEqual(self.act(self.waiter, number, "accept").status_code, 200)
        self.table.refresh_from_db()
        self.assertIsNotNone(self.table.occupied_since)                   # стол занят

    def test_wrong_combinations(self):
        token = self.table.token
        self.assertEqual(self.order(table_token=token, order_type="delivery").status_code, 400)   # доставка со стола
        self.assertEqual(self.order(table_token=token, order_type="pickup").status_code, 400)     # самовывоз со стола
        self.assertEqual(self.order(order_type="takeaway").status_code, 400)                      # «с собой» с главной

    def test_labels(self):
        self.assertEqual(Order.Kind.TAKEAWAY.label, "С собой")
        self.assertEqual(Order.Kind.PICKUP.label, "Самовывоз")