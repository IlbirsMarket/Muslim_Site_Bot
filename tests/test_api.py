"""
Полная проверка API проекта «Муслим».
Запуск: python manage.py test tests -v 2

Тест создаёт свою временную базу (твоя db.sqlite3 не трогается),
проходит все разделы от лица гостя и каждой роли и в конце удаляет базу.
"""

import shutil                    # удаление временной папки
import tempfile                  # временная папка для PDF
from datetime import time, timedelta  # время и промежутки

from django.core.cache import cache            # кэш — в нём хранятся счётчики защиты от спама
from django.test import override_settings      # временно меняем настройки на время теста
from django.utils import timezone              # сегодняшняя дата
from rest_framework.test import APITestCase    # тест-клиент DRF

from apps.cafe.models import CafeSettings
from apps.menu.models import Category, Dish, DishSize, Extra
from apps.orders.models import Order, TableCall
from apps.reports.models import ReportPeriod
from apps.tables.models import Table
from apps.users.models import RoleChangeLog, User

TEMP_MEDIA = tempfile.mkdtemp()   # PDF и картинки во время теста пишем сюда, а не в media/
PASSWORD = "Muslim2026!"          # пароль тестовых сотрудников


@override_settings(MEDIA_ROOT=TEMP_MEDIA, PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])  # быстрые пароли только в тестах
class BaseAPITest(APITestCase):
    """Общая подготовка: сотрудники всех ролей, меню, столы, открытое кафе."""

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)    # удаляем временные файлы

    def setUp(self):
        cache.clear()   # обнуляем счётчики защиты от спама перед каждым тестом

        # ----- Сотрудники -----
        self.programmer = User.objects.create_user("prog", password=PASSWORD, role=User.Role.PROGRAMMER)
        self.chef = User.objects.create_user("chef", password=PASSWORD, role=User.Role.CHEF)
        self.admin = User.objects.create_user("admin", password=PASSWORD, role=User.Role.ADMIN)
        self.cook = User.objects.create_user("cook", password=PASSWORD, role=User.Role.COOK)
        self.waiter = User.objects.create_user("waiter", password=PASSWORD, role=User.Role.WAITER)

        # ----- Кафе открыто круглосуточно -----
        cafe = CafeSettings.load()
        cafe.opens_at = time(0, 0)
        cafe.closes_at = time(23, 59, 59)
        cafe.delivery_fee = 150
        cafe.delivery_min_sum = 800
        cafe.save()

        # ----- Меню -----
        self.cheese = Extra.objects.create(name="Сыр", price=80)
        self.jalapeno = Extra.objects.create(name="Халапеньо", price=50)
        self.hidden_extra = Extra.objects.create(name="Нет в наличии", price=10, is_available=False)
        self.pizzas = Category.objects.create(name="Пиццы", position=10)
        self.burgers = Category.objects.create(name="Бургеры", position=20)

        self.pizza = Dish.objects.create(category=self.pizzas, name="Пепперони")
        self.size25 = DishSize.objects.create(dish=self.pizza, name="25 см", price=550)
        self.size30 = DishSize.objects.create(dish=self.pizza, name="30 см", price=650)
        self.pizza.extras.set([self.cheese, self.hidden_extra])

        self.burger = Dish.objects.create(category=self.burgers, name="Чизбургер", price=390)
        self.burger.extras.set([self.cheese])

        self.stopped = Dish.objects.create(category=self.burgers, name="Стоп-блюдо", price=300, is_available=False)

        # ----- Столы -----
        self.table = Table.objects.create(kind=Table.Kind.HALL, number=7)
        self.delivery = Table.delivery_point()                      # единственная «Доставка» (создаётся сама)

    # ===== Помощники =====

    def as_user(self, user):
        """Дальнейшие запросы — от имени сотрудника (None — как гость)."""
        self.client.force_authenticate(user)

    def hall_order(self, device_key="", **extra):
        """Гость заказывает со стола: Пепперони 30 см + сыр (650 + 80 = 730)."""
        self.as_user(None)
        body = {
            "table_token": self.table.token,
            "device_key": device_key,
            "items": [{"dish_id": self.pizza.id, "size_id": self.size30.id, "extra_ids": [self.cheese.id], "quantity": 1}],
        }
        body.update(extra)
        return self.client.post("/api/orders/", body, format="json")

    def act(self, user, order_id, action, reason=""):
        """Сотрудник нажимает кнопку статуса."""
        self.as_user(user)
        return self.client.post(f"/api/staff/orders/{order_id}/status/", {"action": action, "reason": reason}, format="json")


# =====================================================================
#  МЕНЮ
# =====================================================================

class MenuTests(BaseAPITest):

    def test_public_menu(self):
        """Гость видит меню: размеры, «от» цена, стоп-лист, только доступные добавки."""
        response = self.client.get("/api/menu/")
        self.assertEqual(response.status_code, 200)
        names = [c["name"] for c in response.data]
        self.assertEqual(names, ["Пиццы", "Бургеры"])                         # порядок по position
        pizza = response.data[0]["dishes"][0]
        self.assertEqual(pizza["min_price"], 550)                             # «от 550 сом»
        self.assertEqual(len(pizza["sizes"]), 2)
        self.assertEqual([e["name"] for e in pizza["extras"]], ["Сыр"])       # недоступная добавка скрыта
        stopped = [d for d in response.data[1]["dishes"] if d["name"] == "Стоп-блюдо"][0]
        self.assertFalse(stopped["is_available"])                             # в стоп-листе, но видно

    def test_admin_menu_crud_and_permissions(self):
        """Админ управляет меню, повар — только стоп-лист, официант — ничего."""
        self.as_user(self.admin)
        self.assertEqual(self.client.post("/api/admin/categories/", {"name": "Супы"}, format="json").status_code, 201)

        self.as_user(self.cook)
        response = self.client.post(f"/api/admin/dishes/{self.burger.id}/toggle-available/")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["is_available"])                       # повар поставил в стоп-лист
        self.assertEqual(self.client.post("/api/admin/dishes/", {"name": "x"}, format="json").status_code, 403)

        self.as_user(self.waiter)
        self.assertEqual(self.client.post(f"/api/admin/dishes/{self.burger.id}/toggle-available/").status_code, 403)

    def test_delete_category_with_dishes(self):
        """Удалить категорию с блюдами нельзя — понятная ошибка 400, а не падение сервера."""
        self.as_user(self.admin)
        response = self.client.delete(f"/api/admin/categories/{self.pizzas.id}/")
        self.assertEqual(response.status_code, 400)


# =====================================================================
#  СТОЛЫ И QR
# =====================================================================

class TableTests(BaseAPITest):

    def test_public_table(self):
        """QR стола и QR доставки узнаются, неверный — 404."""
        self.assertEqual(self.client.get(f"/api/tables/{self.table.token}/").data["kind"], "hall")
        self.assertEqual(self.client.get(f"/api/tables/{self.delivery.token}/").data["kind"], "delivery")
        self.assertEqual(self.client.get("/api/tables/wrong-token/").status_code, 404)

    def test_admin_tables_qr_and_status(self):
        """Счётчик активных заказов, картинка QR, PDF всех QR, перевыпуск."""
        self.hall_order()
        self.as_user(self.admin)
        tables = {t["id"]: t for t in self.client.get("/api/admin/tables/").data}
        self.assertEqual(tables[self.table.id]["active_orders"], 1)          # у стола есть заказ
        self.assertEqual(tables[self.delivery.id]["active_orders"], 0)

        png = self.client.get(f"/api/admin/tables/{self.table.id}/qr/")
        self.assertEqual(png["Content-Type"], "image/png")
        pdf = self.client.get("/api/admin/tables/qr-pdf/")
        self.assertEqual(pdf["Content-Type"], "application/pdf")

        old_token = self.table.token
        new = self.client.post(f"/api/admin/tables/{self.table.id}/regenerate-qr/").data
        self.assertNotEqual(new["token"], old_token)
        self.as_user(None)
        self.assertEqual(self.client.get(f"/api/tables/{old_token}/").status_code, 404)   # старый QR не работает

        self.as_user(self.cook)
        self.assertEqual(self.client.get("/api/admin/tables/").status_code, 403)


# =====================================================================
#  ЗАКАЗЫ ГОСТЯ: ПРОВЕРКИ
# =====================================================================

class OrderValidationTests(BaseAPITest):

    def post(self, body):
        self.as_user(None)
        return self.client.post("/api/orders/", body, format="json")

    def test_hall_order_price_counted_by_server(self):
        response = self.hall_order()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["total"], 730)                          # 650 + 80
        self.assertEqual(response.data["status"], "new")

    def test_validation_errors(self):
        token = self.table.token
        cases = {
            "без размера": {"table_token": token, "items": [{"dish_id": self.pizza.id, "quantity": 1}]},
            "несуществующий размер": {"table_token": token, "items": [{"dish_id": self.pizza.id, "size_id": 99999, "quantity": 1}]},
            "чужая добавка": {"table_token": token, "items": [{"dish_id": self.burger.id, "extra_ids": [self.jalapeno.id], "quantity": 1}]},
            "недоступная добавка": {"table_token": token, "items": [{"dish_id": self.pizza.id, "size_id": self.size25.id, "extra_ids": [self.hidden_extra.id], "quantity": 1}]},
            "стоп-лист": {"table_token": token, "items": [{"dish_id": self.stopped.id, "quantity": 1}]},
            "неверный QR": {"table_token": "nope", "items": [{"dish_id": self.burger.id, "quantity": 1}]},
            "пустая корзина": {"table_token": token, "items": []},
            "доставка без типа": {"table_token": self.delivery.token, "items": [{"dish_id": self.burger.id, "quantity": 3}]},
            "доставка без адреса": {"table_token": self.delivery.token, "order_type": "delivery", "customer_name": "А",
                                    "phone": "1", "items": [{"dish_id": self.burger.id, "quantity": 3}]},
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.assertEqual(self.post(body).status_code, 400, name)

    def test_delivery_min_sum_and_closed_cafe(self):
        body = {"table_token": self.delivery.token, "order_type": "delivery", "customer_name": "Бекзат",
                "phone": "+996700", "address": "Киевская 95", "items": [{"dish_id": self.burger.id, "quantity": 1}]}
        self.assertEqual(self.post(body).status_code, 400)                    # 390 < 800

        cafe = CafeSettings.load()
        cafe.is_accepting_orders = False
        cafe.save()
        self.assertEqual(self.hall_order().status_code, 400)                  # кафе закрыто


# =====================================================================
#  ЗАКАЗЫ: ПОЛНЫЙ ЦИКЛ И ПРАВА
# =====================================================================

class OrderFlowTests(BaseAPITest):

    def test_hall_full_flow(self):
        """Зал: гость → официант берёт и подтверждает → кухня → официант подаёт."""
        order = self.hall_order(device_key="phone-1").data
        oid = order["number"]

        # Повар новый заказ не видит и подтвердить не может
        self.as_user(self.cook)
        self.assertEqual(self.client.get("/api/staff/orders/").data, [])
        self.assertIn(self.act(self.cook, oid, "accept").status_code, (403, 404))

        # Официант: видит, кнопка «Беру стол», берёт, подтверждает
        self.as_user(self.waiter)
        listed = self.client.get("/api/staff/orders/?active=true").data
        self.assertEqual(listed[0]["available_actions"][0]["action"], "claim")
        self.assertEqual(self.client.post(f"/api/staff/orders/{oid}/claim/").status_code, 200)
        self.assertEqual(self.act(self.waiter, oid, "accept").data["status"], "accepted")

        # Повар: готовится → готов; подать не может
        self.assertEqual(self.act(self.cook, oid, "cook").data["status"], "cooking")
        self.assertEqual(self.act(self.cook, oid, "ready").data["status"], "ready")
        self.assertEqual(self.act(self.cook, oid, "complete").status_code, 403)

        # Официант подаёт
        done = self.act(self.waiter, oid, "complete").data
        self.assertEqual(done["status_label"], "Подан на стол")

        # Гость видит всю историю
        self.as_user(None)
        public = self.client.get(f"/api/orders/{order['public_id']}/").data
        self.assertEqual([s["status"] for s in public["timeline"]], ["new", "accepted", "cooking", "ready", "completed"])

    def test_second_waiter_cannot_take_claimed_table(self):
        waiter2 = User.objects.create_user("waiter2", password=PASSWORD, role=User.Role.WAITER)
        oid = self.hall_order().data["number"]
        self.as_user(self.waiter)
        self.client.post(f"/api/staff/orders/{oid}/claim/")
        self.as_user(waiter2)
        self.assertEqual(self.client.post(f"/api/staff/orders/{oid}/claim/").status_code, 400)
        self.assertEqual(self.act(waiter2, oid, "accept").status_code, 403)

    def test_reject_and_cancel(self):
        oid = self.hall_order().data["number"]
        rejected = self.act(self.waiter, oid, "reject").data
        self.assertEqual(rejected["status"], "cancelled")
        self.assertEqual(rejected["cancel_reason"], "Стол не подтвердил заказ")

        oid2 = self.hall_order().data["number"]
        self.act(self.waiter, oid2, "accept")
        self.assertEqual(self.act(self.waiter, oid2, "cancel", "x").status_code, 403)   # официант не отменяет принятый
        self.assertEqual(self.act(self.admin, oid2, "cancel").status_code, 400)         # без причины нельзя
        self.assertEqual(self.act(self.admin, oid2, "cancel", "Нет продуктов").data["status"], "cancelled")

    def test_trusted_device(self):
        """Подтверждённый телефон: следующие заказы сразу на кухню, пока стол не закрыт."""
        oid = self.hall_order(device_key="phone-1").data["number"]
        self.act(self.waiter, oid, "accept")
        self.assertEqual(self.hall_order(device_key="phone-1").data["status"], "accepted")   # доверенный
        self.assertEqual(self.hall_order(device_key="phone-2").data["status"], "new")        # чужой телефон

        self.as_user(self.waiter)
        self.assertEqual(self.client.post(f"/api/staff/tables/{self.table.id}/close-visit/").status_code, 200)
        self.assertEqual(self.hall_order(device_key="phone-1").data["status"], "new")        # стол закрыт

    def test_delivery_flow(self):
        """Доставка: официант не видит, админ ведёт до «Доставлен», цена с доставкой."""
        self.as_user(None)
        order = self.client.post("/api/orders/", {
            "table_token": self.delivery.token, "order_type": "delivery",
            "customer_name": "Бекзат", "phone": "+996700123456", "address": "Киевская 95",
            "items": [{"dish_id": self.pizza.id, "size_id": self.size30.id, "quantity": 2}],
        }, format="json").data
        self.assertEqual(order["total"], 650 * 2 + 150)
        oid = order["number"]

        self.as_user(self.waiter)
        self.assertEqual(self.client.get(f"/api/staff/orders/{oid}/").status_code, 404)   # официант доставку не видит

        self.assertEqual(self.act(self.admin, oid, "accept").data["status"], "accepted")
        self.act(self.cook, oid, "cook")
        self.act(self.cook, oid, "ready")
        self.assertEqual(self.act(self.admin, oid, "complete").status_code, 403)          # сначала «В пути»
        self.assertEqual(self.act(self.admin, oid, "send").data["status"], "on_the_way")
        self.assertEqual(self.act(self.admin, oid, "complete").data["status_label"], "Доставлен")

    def test_history_pagination_and_date(self):
        self.hall_order()
        self.as_user(self.admin)
        page = self.client.get("/api/staff/orders/?page=1").data
        self.assertEqual(page["count"], 1)                                                  # с ?page — страницы
        today = timezone.localdate().isoformat()
        self.assertEqual(len(self.client.get(f"/api/staff/orders/?date={today}").data), 1)
        self.assertEqual(self.client.get("/api/staff/orders/?date=неверно").status_code, 400)


# =====================================================================
#  ВЫЗОВЫ СО СТОЛА
# =====================================================================

class TableCallTests(BaseAPITest):

    def test_calls(self):
        body = {"table_token": self.table.token, "kind": "waiter"}
        first = self.client.post("/api/table-calls/", body, format="json")
        second = self.client.post("/api/table-calls/", body, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(first.data["id"], second.data["id"])                               # повтор не плодит вызовы
        self.assertEqual(TableCall.objects.count(), 1)
        self.assertEqual(self.client.post("/api/table-calls/", {"table_token": self.delivery.token, "kind": "bill"},
                                          format="json").status_code, 400)                   # с QR доставки нельзя

        self.as_user(self.cook)
        self.assertEqual(self.client.get("/api/staff/table-calls/").status_code, 403)
        self.as_user(self.waiter)
        call_id = self.client.get("/api/staff/table-calls/").data[0]["id"]
        self.assertTrue(self.client.post(f"/api/staff/table-calls/{call_id}/done/").data["is_done"])
        self.assertEqual(self.client.get("/api/staff/table-calls/").data, [])


# =====================================================================
#  ВХОД, СОТРУДНИКИ И РОЛИ
# =====================================================================

class StaffTests(BaseAPITest):

    def test_login_and_me(self):
        tokens = self.client.post("/api/auth/login/", {"username": "cook", "password": PASSWORD}, format="json").data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        self.assertEqual(self.client.get("/api/auth/me/").data["role"], "cook")

    def test_roles_rules(self):
        self.as_user(self.admin)
        self.assertEqual(len(self.client.get("/api/admin/staff/roles/").data), 2)          # повар, официант
        new_cook = self.client.post("/api/admin/staff/", {"username": "cook2", "password": PASSWORD, "role": "cook"},
                                    format="json")
        self.assertEqual(new_cook.status_code, 201)
        self.assertEqual(self.client.post("/api/admin/staff/", {"username": "adm2", "password": PASSWORD, "role": "admin"},
                                          format="json").status_code, 400)                  # админ не создаёт админов
        cook_id = new_cook.data["id"]
        self.assertEqual(self.client.post(f"/api/admin/staff/{cook_id}/set-role/", {"role": "waiter"},
                                          format="json").status_code, 200)
        self.assertEqual(self.client.post(f"/api/admin/staff/{cook_id}/set-role/", {"role": "admin"},
                                          format="json").status_code, 403)
        self.assertEqual(self.client.patch(f"/api/admin/staff/{self.chef.id}/", {"first_name": "x"},
                                           format="json").status_code, 403)                 # шефа не трогает
        self.assertGreaterEqual(RoleChangeLog.objects.count(), 2)

        self.as_user(self.chef)
        self.assertEqual(len(self.client.get("/api/admin/staff/roles/").data), 3)          # админ, повар, официант
        self.as_user(self.programmer)
        self.assertEqual(len(self.client.get("/api/admin/staff/roles/").data), 4)
        self.as_user(self.cook)
        self.assertEqual(self.client.get("/api/admin/staff/").status_code, 403)

    def test_block_user(self):
        self.as_user(self.admin)
        self.client.patch(f"/api/admin/staff/{self.waiter.id}/", {"is_active": False}, format="json")
        self.as_user(None)
        response = self.client.post("/api/auth/login/", {"username": "waiter", "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 401)                                        # заблокирован — не войти


# =====================================================================
#  НАСТРОЙКИ КАФЕ
# =====================================================================

class CafeTests(BaseAPITest):

    def test_cafe_settings(self):
        self.assertTrue(self.client.get("/api/cafe/").data["is_open"])
        self.as_user(self.admin)
        self.assertEqual(self.client.get("/api/admin/cafe/").status_code, 200)
        self.assertEqual(self.client.patch("/api/admin/cafe/", {"delivery_fee": 200}, format="json").status_code, 403)
        self.as_user(self.chef)
        self.assertEqual(self.client.patch("/api/admin/cafe/", {"delivery_fee": 200}, format="json").data["delivery_fee"], 200)


# =====================================================================
#  ОТЧЁТЫ
# =====================================================================

class ReportTests(BaseAPITest):

    def complete_one_order(self):
        oid = self.hall_order().data["number"]
        for user, action in [(self.waiter, "accept"), (self.cook, "cook"), (self.cook, "ready"), (self.waiter, "complete")]:
            self.act(user, oid, action)

    def test_day_report_and_pdf(self):
        self.complete_one_order()
        self.hall_order()                                                    # второй заказ — ещё в работе
        self.as_user(self.admin)
        report = self.client.get("/api/admin/reports/day/").data
        self.assertEqual(report["revenue"], 730)
        self.assertEqual(report["orders_count"], 1)
        self.assertEqual(report["in_progress_count"], 1)
        self.assertEqual(report["top_dishes"][0]["name"], "Пепперони")
        self.assertEqual(self.client.get("/api/admin/reports/day/?date=2026-13-40").status_code, 400)
        pdf = self.client.get("/api/admin/reports/day/pdf/")
        self.assertEqual(pdf["Content-Type"], "application/pdf")

    def test_period_report_rollover_and_archive(self):
        self.complete_one_order()
        self.as_user(self.admin)
        self.assertEqual(self.client.get("/api/admin/reports/period/").status_code, 403)   # 45 дней — только шеф

        self.as_user(self.chef)
        current = self.client.get("/api/admin/reports/period/").data
        self.assertEqual(current["period"]["day_number"], 1)

        # Делаем вид, что период закончился неделю назад
        today = timezone.localdate()
        ReportPeriod.objects.filter(pk=current["period"]["id"]).update(
            start_date=today - timedelta(days=50), end_date=today - timedelta(days=6),
        )
        new = self.client.get("/api/admin/reports/period/").data
        self.assertNotEqual(new["period"]["id"], current["period"]["id"])                 # открылся новый период
        archive = self.client.get("/api/admin/reports/periods/").data
        self.assertEqual(len(archive), 1)
        self.assertTrue(archive[0]["has_pdf"])
        pdf = self.client.get(f"/api/admin/reports/periods/{archive[0]['id']}/pdf/")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(self.client.get("/api/admin/reports/period/pdf/")["Content-Type"], "application/pdf")


# =====================================================================
#  SWAGGER
# =====================================================================

class SchemaTests(BaseAPITest):

    def test_schema_builds(self):
        """Схема для Swagger собирается без ошибок."""
        self.assertEqual(self.client.get("/api/schema/").status_code, 200)