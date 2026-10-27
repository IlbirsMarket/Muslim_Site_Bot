"""
Добавление и удаление сотрудников из панели.
Запуск: python manage.py test tests -v 2
"""

from apps.orders.models import Order
from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest           # общая подготовка из основного теста

STAFF = "/api/admin/staff/"                                # адрес раздела «Сотрудники»


class StaffManageTests(BaseAPITest):

    def delete(self, who, target):
        """Сотрудник who пытается удалить сотрудника target. Возвращаем код ответа."""
        self.as_user(who)
        return self.client.delete(f"{STAFF}{target.id}/").status_code

    def test_add_staff_with_all_fields(self):
        self.as_user(self.chef)
        response = self.client.post(STAFF, {
            "first_name": "Азамат", "last_name": "Алиев", "username": "azamat", "email": "Azamat@Muslim.kg",
            "phone": "+996700000000", "telegram_id": 123456, "role": "admin", "password": PASSWORD,
        }, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["email"], "azamat@muslim.kg")           # email в маленьких буквах
        self.assertNotIn("password", response.data)                             # пароль не возвращаем
        login = self.client.post("/api/auth/login/", {"username": "azamat@muslim.kg", "password": PASSWORD}, format="json")
        self.assertEqual(login.status_code, 200)                               # новый сотрудник сразу может войти

    def test_cook_and_waiter_cannot_add(self):
        for user in (self.cook, self.waiter):
            self.as_user(user)
            response = self.client.post(STAFF, {"username": "x1", "password": PASSWORD, "role": "waiter"}, format="json")
            self.assertEqual(response.status_code, 403)

    def test_chef_deletes_admin_cook_waiter(self):
        self.assertEqual(self.delete(self.chef, self.admin), 204)
        self.assertEqual(self.delete(self.chef, self.cook), 204)
        self.assertEqual(self.delete(self.chef, self.waiter), 204)
        self.assertFalse(User.objects.filter(username__in=["admin", "cook", "waiter"]).exists())

    def test_admin_deletes_only_cook_and_waiter(self):
        self.assertEqual(self.delete(self.admin, self.chef), 403)               # шефа — нельзя
        self.assertEqual(self.delete(self.admin, self.programmer), 403)         # программиста — нельзя
        other_admin = User.objects.create_user("admin2", password=PASSWORD, role=User.Role.ADMIN)
        self.assertEqual(self.delete(self.admin, other_admin), 403)             # другого админа — нельзя
        self.assertEqual(self.delete(self.admin, self.cook), 204)
        self.assertEqual(self.delete(self.admin, self.waiter), 204)

    def test_nobody_deletes_himself(self):
        self.assertEqual(self.delete(self.chef, self.chef), 403)
        self.assertEqual(self.delete(self.admin, self.admin), 403)

    def test_cook_and_waiter_cannot_delete(self):
        self.assertEqual(self.delete(self.cook, self.waiter), 403)
        self.assertEqual(self.delete(self.waiter, self.cook), 403)

    def test_orders_stay_after_delete(self):
        number = self.hall_order().data["number"]
        self.as_user(self.waiter)
        self.client.post(f"/api/staff/orders/{number}/claim/")                 # официант взял стол
        self.assertEqual(Order.objects.get(pk=number).claimed_by, self.waiter)
        self.assertEqual(self.delete(self.chef, self.waiter), 204)
        order = Order.objects.get(pk=number)                                    # заказ на месте («номер» = id)
        self.assertIsNone(order.claimed_by)                                     # просто без имени официанта

    def test_admin_changes_roles_only_of_cook_and_waiter(self):
        self.as_user(self.admin)
        ok = self.client.post(f"{STAFF}{self.cook.id}/set-role/", {"role": "waiter"}, format="json")
        self.assertEqual(ok.status_code, 200)
        denied = self.client.post(f"{STAFF}{self.chef.id}/set-role/", {"role": "cook"}, format="json")
        self.assertEqual(denied.status_code, 403)

    def test_chef_changes_admin_role(self):
        self.as_user(self.chef)
        response = self.client.post(f"{STAFF}{self.admin.id}/set-role/", {"role": "cook"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, "cook")