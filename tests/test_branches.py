"""
Два филиала: у каждого свои меню, столы, сотрудники, заказы, настройки и отчёты.
Шеф и программист видят оба (переключатель → заголовок X-Branch), остальные — только свой.
Запуск: python manage.py test tests.test_branches -v 2
"""

from datetime import timedelta                               # промежутки времени

from django.utils import timezone                            # сегодня

from apps.bot import texts
from apps.cafe.models import Branch, CafeSettings
from apps.menu.models import Category, Dish, Extra
from apps.orders.models import Order
from apps.reports.models import ReportPeriod
from apps.reports.periods import get_current_period
from apps.tables.models import Table
from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest             # общая подготовка: всё в «Филиале 1»


class BranchBase(BaseAPITest):
    """В «Филиале 2» — своё меню (Лагман), свой стол и свои сотрудники."""

    def setUp(self):
        super().setUp()
        self.b1, self.b2 = Branch.objects.order_by("position", "id")[:2]   # оба созданы миграцией
        self.soups = Category.objects.create(branch=self.b2, name="Супы")
        self.lagman = Dish.objects.create(category=self.soups, name="Лагман", price=350)
        self.sauce = Extra.objects.create(branch=self.b2, name="Соус", price=30)
        self.table2 = Table.objects.create(branch=self.b2, kind=Table.Kind.HALL)
        self.delivery2 = Table.delivery_point(self.b2)
        self.admin2 = User.objects.create_user("admin2", password=PASSWORD, role=User.Role.ADMIN, branch=self.b2)
        self.waiter2 = User.objects.create_user("waiter2b", password=PASSWORD, role=User.Role.WAITER, branch=self.b2)

    def get(self, url, branch=None):
        """GET с выбранным филиалом (как переключатель в панели)."""
        headers = {"HTTP_X_BRANCH": str(branch)} if branch is not None else {}
        return self.client.get(url, **headers)

    @staticmethod
    def rows(data):
        """Список из ответа: с разбивкой на страницы ({"results": [...]}) или без."""
        return data["results"] if isinstance(data, dict) else data

    def order2(self, device_key="", **extra):
        """Гость «Филиала 2» заказывает Лагман со стола."""
        body = {"table_token": self.table2.token, "device_key": device_key,
                "items": [{"dish_id": self.lagman.id, "quantity": 1}], **extra}
        return self.client.post("/api/orders/", body, format="json")


class SetupTests(BranchBase):

    def test_two_branches_with_own_settings(self):
        self.assertEqual([b.name for b in (self.b1, self.b2)], ["Филиал 1", "Филиал 2"])
        self.assertNotEqual(CafeSettings.load(self.b1).pk, CafeSettings.load(self.b2).pk)

    def test_staff_get_branch_chef_does_not(self):
        self.assertEqual(self.admin.branch, self.b1)                  # без филиала → первый
        self.assertIsNone(self.chef.branch)                           # шеф — все филиалы
        self.assertIsNone(self.programmer.branch)

    def test_table_numbers_per_branch(self):
        self.assertEqual(self.table2.number, 1)                       # в «Филиале 2» нумерация с 1
        self.assertEqual(self.table2.name, "Стол 1 · 1 этаж")
        self.assertNotEqual(self.delivery.token, self.delivery2.token)   # у каждого филиала своя доставка и свой QR
        self.assertEqual(self.delivery2.branch, self.b2)


class GuestTests(BranchBase):

    def menu_names(self, query=""):
        return [c["name"] for c in self.client.get("/api/menu/" + query).data]

    def test_menu_by_branch_and_token(self):
        self.assertIn("Пиццы", self.menu_names())                     # без выбора — первый филиал
        self.assertEqual(self.menu_names(f"?branch={self.b2.id}"), ["Супы"])
        self.assertEqual(self.menu_names(f"?token={self.table2.token}"), ["Супы"])   # QR сам знает филиал
        self.assertEqual(self.client.get("/api/menu/?branch=999").status_code, 400)

    def test_branch_list_and_table_info(self):
        names = [b["name"] for b in self.client.get("/api/branches/").data]
        self.assertEqual(names, ["Филиал 1", "Филиал 2"])
        info = self.client.get(f"/api/tables/{self.table2.token}/").data
        self.assertEqual((info["branch"], info["branch_name"]), (self.b2.id, "Филиал 2"))

    def test_order_goes_to_table_branch(self):
        response = self.order2()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Order.objects.get(pk=response.data["number"]).branch, self.b2)

    def test_cannot_order_other_branch_dish(self):
        body = {"table_token": self.table2.token, "items": [{"dish_id": self.burger.id, "quantity": 1}]}
        response = self.client.post("/api/orders/", body, format="json")   # бургер — из меню «Филиала 1»
        self.assertEqual(response.status_code, 400)

    def test_closed_branch_does_not_close_other(self):
        CafeSettings.objects.filter(branch=self.b2).update(is_accepting_orders=False)
        self.assertEqual(self.order2().status_code, 400)               # «Филиал 2» не принимает
        self.assertEqual(self.hall_order().status_code, 201)           # «Филиал 1» работает
        cafe = self.client.get(f"/api/cafe/?branch={self.b2.id}").data
        self.assertFalse(cafe["is_open"])
        self.assertEqual(cafe["branch_name"], "Филиал 2")


class StaffIsolationTests(BranchBase):

    def test_admin_sees_only_own_branch(self):
        number1 = self.hall_order().data["number"]
        number2 = self.order2().data["number"]
        self.as_user(self.admin2)
        ids = [o["number"] for o in self.rows(self.get("/api/staff/orders/").data)]
        self.assertEqual(ids, [number2])
        self.assertEqual(self.get(f"/api/staff/orders/{number1}/").status_code, 404)   # чужой заказ не найти
        self.assertEqual(self.client.post(f"/api/staff/orders/{number1}/status/", {"action": "accept"},
                                          format="json").status_code, 404)
        self.assertEqual([c["name"] for c in self.rows(self.get("/api/admin/categories/").data)], ["Супы"])
        tables = [t["name"] for t in self.rows(self.get("/api/admin/tables/").data)]
        self.assertEqual(sorted(tables), ["Доставка", "Стол 1 · 1 этаж"])

    def test_header_ignored_for_branch_staff(self):
        self.as_user(self.admin2)
        names = [c["name"] for c in self.rows(self.get("/api/admin/categories/", branch=self.b1.id).data)]
        self.assertEqual(names, ["Супы"])                              # подставить чужой филиал нельзя

    def test_chef_switches_branch(self):
        self.as_user(self.chef)
        self.assertIn("Пиццы", [c["name"] for c in self.rows(self.get("/api/admin/categories/").data)])   # по умолчанию первый
        self.assertEqual([c["name"] for c in self.rows(self.get("/api/admin/categories/", self.b2.id).data)], ["Супы"])
        self.assertEqual(self.get("/api/admin/categories/", "abc").status_code, 400)

    def test_waiter_tables_and_calls_own_branch(self):
        self.client.post("/api/table-calls/", {"table_token": self.table.token, "kind": "waiter"}, format="json")
        self.as_user(self.waiter2)
        self.assertEqual(self.rows(self.get("/api/staff/table-calls/").data), [])   # вызов со стола «Филиала 1» не виден
        self.assertEqual([t["name"] for t in self.rows(self.get("/api/staff/tables/").data)], ["Стол 1 · 1 этаж"])
        code = self.client.post(f"/api/staff/tables/{self.table.id}/close-visit/").status_code
        self.assertEqual(code, 404)                                    # чужой стол не освободить

    def test_create_in_current_branch(self):
        self.as_user(self.chef)
        body = {"name": "Напитки"}
        created = self.client.post("/api/admin/categories/", body, format="json", HTTP_X_BRANCH=str(self.b2.id))
        self.assertEqual(Category.objects.get(pk=created.data["id"]).branch, self.b2)
        self.client.post("/api/admin/floors/", {}, format="json", HTTP_X_BRANCH=str(self.b2.id))   # «+ Этаж» во втором филиале
        table = self.client.post("/api/admin/tables/", {"floor": 2}, format="json", HTTP_X_BRANCH=str(self.b2.id))
        self.assertEqual(Table.objects.get(pk=table.data["id"]).branch, self.b2)
        self.assertEqual(table.data["number"], 1)                      # своя нумерация

    def test_same_category_name_allowed_in_other_branch(self):
        self.as_user(self.admin2)
        self.assertEqual(self.client.post("/api/admin/categories/", {"name": "Пиццы"}, format="json").status_code, 201)
        self.assertEqual(self.client.post("/api/admin/categories/", {"name": "супы"}, format="json").status_code, 400)

    def test_no_cross_branch_links(self):
        self.as_user(self.admin2)
        bad_category = self.client.post("/api/admin/dishes/", {"category": self.pizzas.id, "name": "X", "price": 1},
                                        format="json")
        self.assertEqual(bad_category.status_code, 400)                # категория из «Филиала 1»
        bad_extra = self.client.post("/api/admin/dishes/", {"category": self.soups.id, "name": "Y", "price": 1,
                                                            "extras": [self.cheese.id]}, format="json")
        self.assertEqual(bad_extra.status_code, 400)                   # добавка из «Филиала 1»
        bad_size = self.client.post("/api/admin/sizes/", {"dish": self.pizza.id, "name": "40 см", "price": 900},
                                    format="json")
        self.assertEqual(bad_size.status_code, 400)                    # блюдо из «Филиала 1»
        self.assertEqual(self.client.post(f"/api/admin/dishes/{self.pizza.id}/toggle-available/").status_code, 404)

    def test_settings_per_branch_and_rename(self):
        self.as_user(self.chef)
        self.client.patch("/api/admin/cafe/", {"delivery_fee": 99, "branch_name": "Джал"}, format="json",
                          HTTP_X_BRANCH=str(self.b2.id))
        self.assertEqual(CafeSettings.load(self.b2).delivery_fee, 99)
        self.assertNotEqual(CafeSettings.load(self.b1).delivery_fee, 99)   # первый филиал не изменился
        self.b2.refresh_from_db()
        self.assertEqual(self.b2.name, "Джал")
        same = self.client.patch("/api/admin/cafe/", {"branch_name": "филиал 1"}, format="json",
                                 HTTP_X_BRANCH=str(self.b2.id))
        self.assertEqual(same.status_code, 400)                        # имя чужого филиала нельзя


class StaffManagementTests(BranchBase):

    def test_staff_list_per_branch(self):
        self.as_user(self.admin2)
        names = {u["username"] for u in self.rows(self.get("/api/admin/staff/").data)}
        self.assertIn("waiter2b", names)
        self.assertIn("chef", names)                                   # шеф общий — виден везде
        self.assertNotIn("waiter", names)                              # официант «Филиала 1» — нет

    def test_admin_cannot_touch_other_branch(self):
        self.as_user(self.admin2)
        self.assertEqual(self.client.patch(f"/api/admin/staff/{self.waiter.id}/", {"first_name": "x"},
                                           format="json").status_code, 404)
        self.assertFalse(self.admin2.can_manage(self.waiter))

    def test_new_staff_go_to_current_branch(self):
        self.as_user(self.admin2)
        new = self.client.post("/api/admin/staff/", {"username": "cook-b2", "password": PASSWORD, "role": "cook"},
                               format="json")
        self.assertEqual(User.objects.get(pk=new.data["id"]).branch, self.b2)
        self.as_user(self.programmer)
        chef2 = self.client.post("/api/admin/staff/", {"username": "chef2", "password": PASSWORD, "role": "chef"},
                                 format="json", HTTP_X_BRANCH=str(self.b2.id))
        self.assertIsNone(User.objects.get(pk=chef2.data["id"]).branch)   # шеф — без филиала

    def test_only_chef_moves_staff(self):
        self.as_user(self.admin)
        self.assertEqual(self.client.patch(f"/api/admin/staff/{self.waiter.id}/", {"branch": self.b2.id},
                                           format="json").status_code, 400)
        self.as_user(self.chef)
        self.client.patch(f"/api/admin/staff/{self.waiter.id}/", {"branch": self.b2.id}, format="json")
        self.waiter.refresh_from_db()
        self.assertEqual(self.waiter.branch, self.b2)

    def test_role_change_keeps_branch_rules(self):
        self.as_user(self.programmer)
        self.client.post(f"/api/admin/staff/{self.admin2.id}/set-role/", {"role": "chef"}, format="json",
                         HTTP_X_BRANCH=str(self.b2.id))
        self.admin2.refresh_from_db()
        self.assertIsNone(self.admin2.branch)                          # стал шефом — видит все
        self.client.post(f"/api/admin/staff/{self.admin2.id}/set-role/", {"role": "admin"}, format="json",
                         HTTP_X_BRANCH=str(self.b2.id))
        self.admin2.refresh_from_db()
        self.assertEqual(self.admin2.branch, self.b2)                  # снова админ — в выбранный филиал

    def test_me_lists_branches(self):
        self.as_user(self.chef)
        self.assertEqual(len(self.client.get("/api/auth/me/").data["branches"]), 2)
        self.as_user(self.admin2)
        me = self.client.get("/api/auth/me/").data
        self.assertEqual((me["branch"], me["branch_name"], len(me["branches"])), (self.b2.id, "Филиал 2", 1))


class ReportTests(BranchBase):

    def complete(self, order_number):
        Order.objects.filter(pk=order_number).update(status=Order.Status.COMPLETED)

    def test_day_report_per_branch_and_all(self):
        self.complete(self.hall_order().data["number"])
        self.complete(self.order2().data["number"])
        self.as_user(self.chef)
        one = self.get("/api/admin/reports/day/", self.b1.id).data
        two = self.get("/api/admin/reports/day/", self.b2.id).data
        both = self.get("/api/admin/reports/day/", "all").data
        self.assertEqual((one["orders_count"], two["orders_count"], both["orders_count"]), (1, 1, 2))
        self.assertEqual(both["revenue"], one["revenue"] + two["revenue"])
        self.assertEqual(both["branch_name"], "Оба филиала")
        self.assertEqual(self.client.get("/api/admin/reports/day/pdf/", HTTP_X_BRANCH="all").status_code, 200)

    def test_admin_cannot_see_all(self):
        self.complete(self.hall_order().data["number"])
        self.as_user(self.admin2)
        data = self.get("/api/admin/reports/day/", "all").data
        self.assertEqual((data["branch_name"], data["orders_count"]), ("Филиал 2", 0))   # только свой филиал

    def test_periods_per_branch_aligned(self):
        self.as_user(self.chef)
        first = self.get("/api/admin/reports/period/", self.b1.id).data["period"]
        both = self.get("/api/admin/reports/period/", "all").data
        self.assertEqual(both["period"]["start_date"], first["start_date"])   # общий период — с тех же дат
        self.assertEqual(ReportPeriod.objects.filter(is_closed=False).count(), 2)

    def test_period_closes_per_branch(self):
        old = timezone.localdate() - timedelta(days=50)
        ReportPeriod.objects.create(branch=self.b2, start_date=old, end_date=old + timedelta(days=44))
        current = get_current_period(self.b2)
        self.assertEqual(ReportPeriod.objects.filter(branch=self.b2, is_closed=True).count(), 1)
        self.assertEqual(current.branch, self.b2)
        self.assertFalse(ReportPeriod.objects.filter(branch=self.b1, is_closed=True).exists())


class BotTests(BranchBase):

    def test_bot_menu_per_branch(self):
        self.assertIn("Пиццы", "\n".join(texts.menu_parts()))
        second = "\n".join(texts.menu_parts(self.b2))
        self.assertIn("Лагман", second)
        self.assertNotIn("Пиццы", second)
        self.assertIn("Филиал 2", second)
        self.assertIn("Филиал: Филиал 2", texts.profile_text(self.admin2))
