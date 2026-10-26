"""
Команда: python manage.py seed_demo
Заполняет базу тестовыми данными. Можно запускать много раз — дубликатов не будет.
"""

from django.core.management.base import BaseCommand   # базовый класс команд

from apps.menu.models import Category, Dish, DishSize, Extra
from apps.tables.models import Table
from apps.users.models import User

DEMO_PASSWORD = "Muslim2026!"   # пароль всех тестовых сотрудников


class Command(BaseCommand):
    help = "Тестовое меню, столы и сотрудники всех ролей."

    def handle(self, *args, **options):
        # ----- Добавки -----
        cheese, _ = Extra.objects.get_or_create(name="Сыр моцарелла", defaults={"price": 80})
        jalapeno, _ = Extra.objects.get_or_create(name="Халапеньо", defaults={"price": 50})
        garlic, _ = Extra.objects.get_or_create(name="Чесночный соус", defaults={"price": 40})

        # ----- Категории -----
        pizza, _ = Category.objects.get_or_create(name="Пиццы", defaults={"position": 10})
        burgers, _ = Category.objects.get_or_create(name="Бургеры", defaults={"position": 20})
        drinks, _ = Category.objects.get_or_create(name="Напитки", defaults={"position": 30})

        # ----- Блюда: (категория, название, состав, цена без размеров, [(размер, цена)], [добавки]) -----
        dishes = [
            (pizza, "Пепперони", "Халяль-колбаса, моцарелла, томатный соус", 0,
             [("25 см", 550), ("30 см", 650), ("35 см", 790)], [cheese, jalapeno]),
            (pizza, "Маргарита", "Томаты, моцарелла, базилик", 0,
             [("25 см", 450), ("30 см", 550), ("35 см", 690)], [cheese]),
            (pizza, "Куриная BBQ", "Курица, соус барбекю, красный лук", 0,
             [("25 см", 590), ("30 см", 690), ("35 см", 830)], [cheese, garlic]),
            (burgers, "Чизбургер", "Говяжья котлета, чеддер, соус", 390, [], [cheese, jalapeno]),
            (burgers, "Чикенбургер", "Куриное филе, салат, соус", 350, [], [garlic]),
            (drinks, "Кола", "", 0, [("0,5 л", 80), ("1 л", 130)], []),
            (drinks, "Лимонад мятный", "Домашний", 130, [], []),
        ]
        for position, (category, name, description, price, sizes, extras) in enumerate(dishes):
            dish, created = Dish.objects.get_or_create(
                name=name,                                          # ищем блюдо по названию
                defaults={                                          # если нет — создаём с этими данными
                    "category": category,
                    "description": description,
                    "price": price,
                    "position": position * 10,
                },
            )
            if created:                                             # размеры и добавки — только для нового блюда
                for size_position, (size_name, size_price) in enumerate(sizes):
                    DishSize.objects.create(dish=dish, name=size_name, price=size_price, position=size_position)
                dish.extras.set(extras)                             # привязываем добавки

        # ----- Столы: «Доставка» + столы 1–10 -----
        if not Table.objects.filter(kind=Table.Kind.DELIVERY).exists():   # точка доставки нужна одна
            Table.objects.create(kind=Table.Kind.DELIVERY, name="Доставка")
        for number in range(1, 11):
            Table.objects.get_or_create(number=number, defaults={"kind": Table.Kind.HALL})  # "Стол 1" ... "Стол 10"

        # ----- Сотрудники всех ролей -----
        staff = [
            ("chef1", "Шеф", User.Role.CHEF),
            ("admin1", "Админ", User.Role.ADMIN),
            ("cook1", "Повар", User.Role.COOK),
            ("waiter1", "Официант", User.Role.WAITER),
        ]
        for username, first_name, role in staff:
            if not User.objects.filter(username=username).exists():   # не создаём повторно
                user = User(username=username, first_name=first_name, role=role)
                user.set_password(DEMO_PASSWORD)                       # пароль сохраняется зашифрованным
                user.save()

        self.stdout.write(self.style.SUCCESS(f"Готово. Пароль сотрудников: {DEMO_PASSWORD}"))  # зелёное сообщение