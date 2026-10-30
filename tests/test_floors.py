"""
Этажи филиала: 1 этаж есть всегда, «+ Этаж» добавляет следующий, удалить — только последний пустой (не 1-й).
Запуск: python manage.py test tests.test_floors -v 2
"""

from apps.cafe.models import Branch
from apps.tables.models import Floor, Table
from apps.users.models import User
from tests.test_api import PASSWORD, BaseAPITest     # общая подготовка: сотрудники, стол 7 на 1 этаже

FLOORS = "/api/admin/floors/"


class FloorTests(BaseAPITest):

    def setUp(self):
        super().setUp()
        self.b1, self.b2 = Branch.objects.order_by("position", "id")[:2]
        self.as_user(self.admin)

    def numbers(self):
        """Номера этажей, которые видит панель."""
        return [f["number"] for f in self.client.get(FLOORS).data]

    def test_first_floor_always_exists(self):
        Floor.objects.all().delete()                                      # даже если этажей нет вовсе
        self.assertEqual(self.numbers(), [1])

    def test_add_next_number(self):
        self.assertEqual(self.client.post(FLOORS, {}, format="json").data["number"], 2)
        self.assertEqual(self.client.post(FLOORS, {}, format="json").data["number"], 3)
        self.assertEqual(self.numbers(), [1, 2, 3])
        table = self.client.post("/api/admin/tables/", {"floor": 3}, format="json").data
        self.assertEqual(table["name"], "Стол 1 · 3 этаж")               # стол на новом этаже с номером 1

    def test_delete_rules(self):
        two = self.client.post(FLOORS, {}, format="json").data
        three = self.client.post(FLOORS, {}, format="json").data
        rows = {f["number"]: f for f in self.client.get(FLOORS).data}
        self.assertEqual((rows[1]["can_delete"], rows[2]["can_delete"], rows[3]["can_delete"]), (False, False, True))
        self.assertEqual(self.client.delete(f"{FLOORS}{two['id']}/").status_code, 400)    # не последний
        one = Floor.objects.get(branch=self.b1, number=1)
        self.assertEqual(self.client.delete(f"{FLOORS}{one.id}/").status_code, 400)       # 1 этаж — никогда
        self.client.post("/api/admin/tables/", {"floor": 3}, format="json")
        self.assertEqual(self.client.delete(f"{FLOORS}{three['id']}/").status_code, 400)  # на этаже стол
        Table.objects.filter(floor=3).delete()
        self.assertEqual(self.client.delete(f"{FLOORS}{three['id']}/").status_code, 204)
        self.assertEqual(self.numbers(), [1, 2])
        self.assertEqual(self.client.post(FLOORS, {}, format="json").data["number"], 3)   # снова 3, без дыр

    def test_tables_count(self):
        rows = self.client.get(FLOORS).data
        self.assertEqual(rows[0]["tables_count"], 1)                      # «Стол 7» из подготовки

    def test_floors_per_branch(self):
        self.client.post(FLOORS, {}, format="json")                       # у «Филиала 1» теперь 2 этажа
        admin2 = User.objects.create_user("admin2", password=PASSWORD, role=User.Role.ADMIN, branch=self.b2)
        self.as_user(admin2)
        self.assertEqual(self.numbers(), [1])                             # у «Филиала 2» — только 1 этаж
        mine = self.client.post(FLOORS, {}, format="json").data
        self.assertEqual(mine["number"], 2)
        other = Floor.objects.get(branch=self.b1, number=2)
        self.assertEqual(self.client.delete(f"{FLOORS}{other.id}/").status_code, 404)    # чужой этаж не найти

    def test_staff_cannot_manage_floors(self):
        self.as_user(self.waiter)
        self.assertEqual(self.client.post(FLOORS, {}, format="json").status_code, 403)
        self.as_user(self.cook)
        self.assertEqual(self.client.get(FLOORS).status_code, 403)
