"""
«Изменить сотрудника»: старший меняет младших.
Программист — шефа и всех ниже; шеф — админа и ниже; админ — повара, официанта, курьера.
Повар, официант, курьер — никого (даже себя). Себя не меняет никто.
Запуск: python manage.py test tests.test_staff_edit -v 2
"""

from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest     # общая подготовка: сотрудники всех ролей

STAFF = "/api/admin/staff/"


class StaffEditTests(BaseAPITest):

    def setUp(self):
        super().setUp()
        self.courier = User.objects.create_user("courier", password=PASSWORD, role=User.Role.COURIER)

    def edit(self, actor, target, **fields):
        """actor меняет target → код ответа."""
        self.as_user(actor)
        return self.client.patch(f"{STAFF}{target.id}/", fields, format="json").status_code

    def test_hierarchy(self):
        allowed = [
            (self.programmer, self.chef), (self.programmer, self.admin), (self.programmer, self.cook),
            (self.chef, self.admin), (self.chef, self.waiter), (self.chef, self.courier),
            (self.admin, self.cook), (self.admin, self.waiter), (self.admin, self.courier),
        ]
        for actor, target in allowed:
            self.assertEqual(self.edit(actor, target, first_name="Новое"), 200, f"{actor} → {target}")
        denied = [
            (self.chef, self.programmer), (self.chef, self.chef), (self.admin, self.chef), (self.admin, self.admin),
            (self.programmer, self.programmer), (self.cook, self.cook), (self.cook, self.waiter),
            (self.waiter, self.waiter), (self.courier, self.courier),
        ]
        for actor, target in denied:
            self.assertIn(self.edit(actor, target, first_name="Взлом"), (403, 404), f"{actor} → {target}")

    def test_all_fields_saved(self):
        code = self.edit(self.admin, self.cook, first_name="Азамат", last_name="Токтогулов", username="azamat",
                         email="Azamat@Mail.kg", phone="+996700112233", telegram_id=777, is_active=True)
        self.assertEqual(code, 200)
        self.cook.refresh_from_db()
        self.assertEqual((self.cook.first_name, self.cook.last_name, self.cook.username, self.cook.email,
                          self.cook.phone, self.cook.telegram_id),
                         ("Азамат", "Токтогулов", "azamat", "azamat@mail.kg", "+996700112233", 777))
        self.as_user(None)
        login = self.client.post("/api/auth/login/", {"username": "azamat", "password": PASSWORD}, format="json")
        self.assertEqual(login.status_code, 200)                      # входит по новому логину

    def test_duplicates_rejected(self):
        self.assertEqual(self.edit(self.admin, self.cook, username="WAITER"), 400)        # логин занят (регистр не важен)
        User.objects.filter(pk=self.waiter.pk).update(telegram_id=555)
        self.assertEqual(self.edit(self.admin, self.cook, telegram_id=555), 400)         # Telegram занят
        self.assertEqual(self.edit(self.admin, self.cook, username="  "), 400)          # пустой логин

    def test_denied_sees_no_field_errors(self):
        self.as_user(self.admin)
        response = self.client.patch(f"{STAFF}{self.chef.id}/", {"username": "waiter"}, format="json")
        self.assertEqual(response.status_code, 403)                   # сначала права, потом поля

    def test_role_and_password_through_own_actions(self):
        self.as_user(self.admin)
        self.assertEqual(self.client.patch(f"{STAFF}{self.cook.id}/", {"role": "chef"}, format="json").status_code, 200)
        self.cook.refresh_from_db()
        self.assertEqual(self.cook.role, "cook")                      # роль через PATCH не меняется
        code = self.client.post(f"{STAFF}{self.cook.id}/set-role/", {"role": "waiter"}, format="json").status_code
        self.assertEqual(code, 200)
        code = self.client.post(f"{STAFF}{self.cook.id}/set-password/", {"password": "Новый-пароль-1"}, format="json").status_code
        self.assertEqual(code, 204)
        self.assertEqual(self.client.post(f"{STAFF}{self.chef.id}/set-password/", {"password": "Новый-пароль-1"},
                                          format="json").status_code, 403)   # шефу админ пароль не меняет

    def test_can_edit_flag(self):
        self.as_user(self.admin)
        rows = self.client.get(STAFF).data
        rows = rows["results"] if isinstance(rows, dict) else rows
        flags = {u["username"]: u["can_edit"] for u in rows}
        self.assertEqual((flags["cook"], flags["chef"], flags["admin"]), (True, False, False))
