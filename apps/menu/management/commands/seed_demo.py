"""
Команда: python manage.py seed_demo --settings=config.settings.demo
Заполняет ДЕМО-базу (demo.sqlite3) так, будто кафе работает уже месяц:
  два филиала, меню с размерами и добавками, столы на двух этажах, сотрудники на каждую роль,
  заказы в работе (во всех колонках), вызов со стола и история заказов за 30 дней (для отчётов).
Фото блюд: свободные фото с Wikimedia Commons, скачиваются при первом запуске (нужен интернет);
авторы и лицензии записываются в demo_media/АВТОРЫ-ФОТО.txt. Нет интернета — блюда будут без фото.

Работает ТОЛЬКО с настройками config.settings.demo: перед заполнением демо-база очищается,
поэтому на настоящей базе (и на сервере) команда откажется работать.
"""

import json                                                        # ответ Wikimedia
import random                                                      # история заказов «как настоящая»
import re                                                          # убрать HTML из имени автора
from datetime import time, timedelta                               # время работы, даты истории
from pathlib import Path                                           # папка с фото
from urllib.parse import urlencode                                 # адрес запроса к Wikimedia
from urllib.request import Request, urlopen                        # скачивание без лишних библиотек

from django.conf import settings
from django.core.files.base import ContentFile                     # картинка из памяти → поле «Фото»
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.cafe.models import Branch, CafeSettings
from apps.menu.models import Category, Dish, DishSize, Extra
from apps.orders.models import CashMove, CashShift, Order, OrderItem, OrderStatusLog, PrintJob, TableCall, TableVisit
from apps.tables.models import Floor, Table
from apps.users.models import User

DEMO_PASSWORD = "demo-muslim-2026"   # пароль всех демо-сотрудников (только для демо-базы на своём компьютере)
S = Order.Status

# Демо-сотрудники: логин, имя, роль, филиал ("k" — Кара-Суу, "t" — Таширов, None — оба)
STAFF = [
    ("demo_chef", "Имрон", User.Role.CHEF, None),
    ("demo_admin", "Азамат", User.Role.ADMIN, "k"),
    ("demo_cook", "Айбек", User.Role.COOK, "k"),
    ("demo_waiter", "Бекзат", User.Role.WAITER, "k"),
    ("demo_waiter2", "Эльмира", User.Role.WAITER, "k"),
    ("demo_courier", "Нурлан", User.Role.COURIER, "k"),
    ("demo_cashier", "Айжан", User.Role.CASHIER, "k"),
    ("demo_admin2", "Фарух", User.Role.ADMIN, "t"),
    ("demo_waiter3", "Тимур", User.Role.WAITER, "t"),
]

# Меню: категория → [(название, состав, цена или [(размер, цена)], добавки, что искать на Wikimedia, есть в наличии)]
MENU = [
    ("Пицца", [
        ("Пепперони", "Халяль-колбаса пепперони, моцарелла, томатный соус", [("25 см", 550), ("30 см", 650), ("35 см", 790)], ["cheese", "jalapeno"], "pepperoni pizza", True),
        ("Маргарита", "Томаты, моцарелла, базилик", [("25 см", 450), ("30 см", 550), ("35 см", 690)], ["cheese"], "pizza margherita", True),
        ("Куриная BBQ", "Курица, соус барбекю, красный лук, моцарелла", [("25 см", 590), ("30 см", 690), ("35 см", 830)], ["cheese", "garlic"], "barbecue chicken pizza", False),
    ]),
    ("Бургеры", [
        ("Чизбургер", "Говяжья котлета, чеддер, маринованные огурцы, фирменный соус", 390, ["cheese", "jalapeno"], "cheeseburger", True),
        ("Двойной бургер", "Две говяжьи котлеты, двойной чеддер, лук, соус", 520, ["cheese", "jalapeno"], "double cheeseburger", True),
        ("Картофель фри", "Хрустящий, с солью", [("Средний", 150), ("Большой", 200)], ["garlic"], "french fries", True),
    ]),
    ("Национальные блюда", [
        ("Плов", "Рис девзира, говядина, морковь, нут, чеснок", 320, [], "uzbek plov", True),
        ("Лагман", "Домашняя лапша, говядина, овощи", 300, [], "lagman noodles", True),
        ("Манты", "5 штук, говядина с луком, сметана", 280, [], "manti dumplings", True),
        ("Шашлык из говядины", "Маринованная говядина, лук, лаваш", 350, [], "shashlik", True),
    ]),
    ("Салаты и супы", [
        ("Цезарь с курицей", "Курица, романо, пармезан, сухарики, соус цезарь", 320, [], "caesar salad", True),
        ("Ачичук", "Помидоры, огурцы, лук, зелень", 150, [], "tomato cucumber salad", True),
        ("Шорпо", "Наваристый бульон, баранина, картофель, морковь", 280, [], "shurpa soup", True),
    ]),
    ("Напитки", [
        ("Чай чёрный", "Чайник 0,8 л", 120, [], "black tea teapot", True),
        ("Лимонад", "Домашний, с мятой и лимоном", [("0,5 л", 130), ("1 л", 220)], [], "lemonade glass", True),
        ("Компот", "Из сухофруктов", 90, [], "kompot", True),
    ]),
    ("Десерты", [
        ("Чак-чак", "С мёдом", 180, [], "chak-chak", True),
        ("Медовик", "Домашний медовый торт", 220, [], "medovik cake", True),
    ]),
]
EXTRAS = {"cheese": ("Сыр моцарелла", 80), "jalapeno": ("Халапеньо", 50), "garlic": ("Чесночный соус", 30)}
CANCEL_REASONS = ["Нет продуктов", "Гость отказался", "Не дозвонились"]
GUESTS = [("Алия", "+996 700 12 34 56", "ул. Ленина 15"), ("Эрлан", "+996 555 98 76 54", "ул. Курманжан Датки 8"),
          ("Мадина", "+996 772 45 67 89", "мкр. Нурсултан, д. 3"), ("Тимур", "+996 707 11 22 33", "ул. Айтматова 41")]


class Command(BaseCommand):
    help = "Демо-база «как настоящая»: меню с фото, столы, сотрудники, заказы и отчёты за месяц."

    def add_arguments(self, parser):
        parser.add_argument("--no-photos", action="store_true", help="Не скачивать фото (без интернета)")

    def handle(self, *args, **options):
        if not settings.DEBUG or not getattr(settings, "DEMO", False):
            raise CommandError("seed_demo работает только с демо-базой: python manage.py seed_demo --settings=config.settings.demo")
        random.seed(2026)                                              # каждый раз одна и та же «история»
        with transaction.atomic():
            self.clear()
            branches = self.branches()
            people = self.staff(branches)
            for key, branch in branches.items():
                dishes = self.menu(branch, full=(key == "k"))
                tables = self.tables(branch, full=(key == "k"))
                self.history(branch, dishes, tables, people)
                if key == "k":
                    self.active_orders(branch, dishes, tables, people)
                    self.cash_shifts(branch, people["demo_cashier"])
        photos = 0 if options["no_photos"] else self.photos()
        self.stdout.write(self.style.SUCCESS(
            f"Демо готово. Фото блюд: {photos}. Вход в демо-панель — кнопками на странице входа "
            f"(пароль всех демо-сотрудников: {DEMO_PASSWORD}). Коды входа: шеф 11, админ 22, повар 33, "
            f"официант 44, официант 55, курьер 66, кассир 77, админ Таширова 88, официант Таширова 99."))

    # ----- Очистка демо-базы -----
    def clear(self):
        for model in (OrderStatusLog, OrderItem, TableCall, TableVisit, PrintJob, CashMove, CashShift, Order, DishSize, Dish, Extra, Category, Table):
            model.objects.all().delete()
        Floor.objects.all().delete()
        User.objects.all().delete()

    # ----- Филиалы и настройки: открыты круглосуточно, чтобы демо работало в любое время -----
    def branches(self):
        names = {"k": "Кара-Суу", "t": "Таширов"}
        addresses = {"k": "г. Кара-Суу, ул. Ленина 5", "t": "г. Кара-Суу, ул. Таширова 12"}
        result = {}
        for position, key in enumerate(("k", "t")):
            existing = list(Branch.objects.order_by("position", "id"))
            branch = existing[position] if len(existing) > position else Branch.objects.create(name=names[key])
            branch.name, branch.position, branch.is_active = names[key], (position + 1) * 10, True
            branch.tg_group_id = None                                  # демо не пишет в Telegram
            branch.save()
            cafe = CafeSettings.load(branch)
            cafe.is_accepting_orders = cafe.is_delivery_enabled = True
            cafe.opens_at, cafe.closes_at = time(0, 0), time(23, 59, 59)
            cafe.delivery_fee, cafe.delivery_min_sum, cafe.free_delivery_from = 150, 600, 3000
            cafe.delivery_time, cafe.address, cafe.phone = "40–60 минут", addresses[key], "+996 555 00 00 00"
            cafe.save()
            result[key] = branch
        return result

    def staff(self, branches):
        people = {}
        for number, (username, name, role, key) in enumerate(STAFF, start=1):
            user = User(username=username, first_name=name, role=role, branch=branches[key] if key else None)
            user.set_password(DEMO_PASSWORD)
            user.set_pin(f"{number}{number}")                         # код входа в демо: 11, 22, 33… (по порядку в STAFF)
            user.save()
            people[username] = user
        return people

    # ----- Меню -----
    def menu(self, branch, full):
        extras = {key: Extra.objects.create(branch=branch, name=name, price=price) for key, (name, price) in EXTRAS.items()}
        dishes = []
        for c_pos, (cat_name, items) in enumerate(MENU):
            if not full and cat_name == "Десерты":                      # у второго филиала меню чуть короче
                continue
            printer = {"Пицца": "kitchen2", "Бургеры": "kitchen2", "Напитки": "none", "Десерты": "none"}.get(cat_name, "kitchen1")   # фастфуд — аппарат 2
            category = Category.objects.create(branch=branch, name=cat_name, position=(c_pos + 1) * 10, printer=printer)
            for d_pos, (name, description, price, extra_keys, query, available) in enumerate(items):
                sized = isinstance(price, list)
                dish = Dish.objects.create(category=category, name=name, description=description, price=0 if sized else price,
                                           is_available=available, position=(d_pos + 1) * 10)
                if sized:
                    for s_pos, (size, size_price) in enumerate(price):
                        DishSize.objects.create(dish=dish, name=size, price=size_price, position=s_pos)
                dish.extras.set([extras[k] for k in extra_keys])
                dishes.append(dish)
        return dishes

    # ----- Этажи и столы -----
    def tables(self, branch, full):
        Floor.for_branch(branch)                                       # 1 этаж
        Table.delivery_point(branch)                                   # «Доставка»
        hall = [Table.objects.create(branch=branch, kind=Table.Kind.HALL, floor=1) for _ in range(8 if full else 6)]
        if full:
            Floor.add_next(branch)                                     # 2 этаж
            hall += [Table.objects.create(branch=branch, kind=Table.Kind.HALL, floor=2) for _ in range(4)]
        return hall

    # ----- Заказы -----
    def make_order(self, branch, kind, items, status, when, table=None, guest=None, by=None, reason="", paid=True):
        """Заказ с позициями и историей статусов; created_at — когда был сделан."""
        lines = []
        for dish, qty in items:
            size = dish.sizes.order_by("position").first()
            lines.append((dish, size, qty, size.price if size else dish.price))
        subtotal = sum(price * qty for _, _, qty, price in lines)
        fee = 150 if kind == Order.Kind.DELIVERY and subtotal < 3000 else 0
        name, phone, address = guest or ("", "", "")
        order = Order.objects.create(
            branch=branch, kind=kind, status=status, table=table or Table.delivery_point(branch),
            customer_name=name if kind in (Order.Kind.DELIVERY, Order.Kind.PICKUP) else "",
            phone=phone if kind in (Order.Kind.DELIVERY, Order.Kind.PICKUP) else "",
            address=address if kind == Order.Kind.DELIVERY else "",
            payment_method=random.choice([Order.Payment.CASH, Order.Payment.CASH, Order.Payment.CARD]),
            subtotal=subtotal, delivery_fee=fee, total=subtotal + fee, cancel_reason=reason,
            accepted_by=by.get("accept") if by else None, claimed_by=by.get("claim") if by else None,
        )
        for dish, size, qty, price in lines:
            OrderItem.objects.create(order=order, dish=dish, dish_name=dish.name, size_name=size.name if size else "",
                                     unit_price=price, quantity=qty)
        steps = {S.NEW: [S.NEW], S.ACCEPTED: [S.NEW, S.ACCEPTED], S.COOKING: [S.NEW, S.ACCEPTED, S.COOKING],
                 S.READY: [S.NEW, S.ACCEPTED, S.COOKING, S.READY],
                 S.ON_THE_WAY: [S.NEW, S.ACCEPTED, S.COOKING, S.READY, S.ON_THE_WAY],
                 S.COMPLETED: [S.NEW, S.ACCEPTED, S.COOKING, S.READY, S.COMPLETED], S.CANCELLED: [S.NEW, S.CANCELLED]}[status]
        for n, step in enumerate(steps):
            log = OrderStatusLog.objects.create(order=order, status=step)
            OrderStatusLog.objects.filter(pk=log.pk).update(created_at=when + timedelta(minutes=4 * n))
        finished = when + timedelta(minutes=4 * len(steps))
        Order.objects.filter(pk=order.pk).update(created_at=when, updated_at=finished)
        if status == S.COMPLETED and paid:                             # завершённые — уже оплачены (как гость выбрал)
            card = order.payment_method == Order.Payment.CARD
            Order.objects.filter(pk=order.pk).update(
                paid_at=finished, paid_method=Order.PaidMethod.CARD if card else Order.PaidMethod.CASH,
                paid_cash=0 if card else order.total, paid_card=order.total if card else 0,
            )
        return order

    def history(self, branch, dishes, tables, people):
        """Завершённые заказы за 30 дней — для отчётов (вечером больше, в выходные ещё больше)."""
        now = timezone.localtime()
        popular = dishes[:4] + dishes[6:10]                            # пицца, бургеры, плов, лагман — чаще
        waiters = [u for u in people.values() if u.role == User.Role.WAITER and u.branch_id == branch.id]
        weights = [5, 3, 2][:len(waiters)]                               # кто-то работает больше — отчёт интереснее
        for day in range(30, 0, -1):
            date = now - timedelta(days=day)
            count = random.randint(14, 22) + (8 if date.weekday() >= 5 else 0)
            for _ in range(count):
                hour = random.choice([11, 12, 13, 13, 14, 17, 18, 19, 19, 20, 20, 21, 22])
                when = date.replace(hour=hour, minute=random.randint(0, 59), second=0, microsecond=0)
                items = [(random.choice(popular if random.random() < .7 else dishes), random.choice([1, 1, 2])) for _ in range(random.randint(1, 3))]
                kind = random.choice([Order.Kind.HALL] * 5 + [Order.Kind.DELIVERY] * 3 + [Order.Kind.PICKUP] * 2)
                cancelled = random.random() < .04
                waiter = random.choices(waiters, weights)[0] if waiters and kind == Order.Kind.HALL else None
                table = random.choice(tables) if kind == Order.Kind.HALL else None
                self.make_order(branch, kind, items, S.CANCELLED if cancelled else S.COMPLETED, when,
                                table=table, guest=random.choice(GUESTS),
                                by={"accept": waiter, "claim": waiter} if waiter else None,
                                reason=random.choice(CANCEL_REASONS) if cancelled else "")
                if waiter and random.random() < .35:                       # гость звал официанта — тот подошёл
                    call = TableCall.objects.create(table=table, kind=random.choice(TableCall.Kind.values), is_done=True, done_by=waiter)
                    TableCall.objects.filter(pk=call.pk).update(
                        created_at=when + timedelta(minutes=20), done_at=when + timedelta(minutes=20, seconds=random.randint(30, 240)),
                    )

    def active_orders(self, branch, dishes, tables, people):
        """Заказы прямо сейчас — во всех колонках панели и темах Telegram."""
        d = {dish.name: dish for dish in dishes}
        now = timezone.now()
        waiter, courier, admin = people["demo_waiter"], people["demo_courier"], people["demo_admin"]
        plan = [
            (Order.Kind.HALL, [(d["Плов"], 2), (d["Чай чёрный"], 1)], S.NEW, 2, tables[2], None),
            (Order.Kind.DELIVERY, [(d["Пепперони"], 1), (d["Лимонад"], 2)], S.NEW, 4, None, None),
            (Order.Kind.HALL, [(d["Лагман"], 1), (d["Манты"], 1), (d["Ачичук"], 1)], S.ACCEPTED, 7, tables[4], {"accept": waiter, "claim": waiter}),
            (Order.Kind.PICKUP, [(d["Чизбургер"], 2), (d["Картофель фри"], 1)], S.COOKING, 11, None, {"accept": admin}),
            (Order.Kind.HALL, [(d["Шашлык из говядины"], 2), (d["Цезарь с курицей"], 1)], S.COOKING, 14, tables[1], {"accept": waiter, "claim": waiter}),
            (Order.Kind.HALL, [(d["Маргарита"], 1), (d["Компот"], 2)], S.READY, 19, tables[0], {"accept": waiter, "claim": waiter}),
            (Order.Kind.DELIVERY, [(d["Двойной бургер"], 1), (d["Медовик"], 1)], S.ON_THE_WAY, 26, None, {"accept": admin, "claim": courier}),
        ]
        waiter2 = people["demo_waiter2"]
        # Уже поели, но ещё не заплатили — для вкладки «К оплате»
        self.make_order(branch, Order.Kind.HALL, [(d["Плов"], 2), (d["Чай чёрный"], 3)], S.COMPLETED, now - timedelta(minutes=48),
                        table=tables[3], by={"accept": waiter2, "claim": waiter2}, paid=False)
        self.make_order(branch, Order.Kind.TAKEAWAY, [(d["Манты"], 2), (d["Компот"], 1)], S.COMPLETED, now - timedelta(minutes=33),
                        table=tables[3], by={"accept": waiter2, "claim": waiter2}, paid=False)
        for n, (kind, items, status, minutes_ago, table, by) in enumerate(plan):
            self.make_order(branch, kind, items, status, now - timedelta(minutes=minutes_ago), table=table, guest=GUESTS[n % len(GUESTS)], by=by)
        for n, table in enumerate([tables[0], tables[1], tables[2], tables[4]]):   # эти столы заняты гостями
            Table.objects.filter(pk=table.pk).update(occupied_since=now - timedelta(minutes=30 - n * 5),
                                                     waiter=waiter if table != tables[2] else None)
        Table.objects.filter(pk=tables[3].pk).update(occupied_since=now - timedelta(minutes=50), waiter=waiter2)
        TableCall.objects.create(table=tables[4], kind=TableCall.Kind.BILL, people=3)   # «Попросить счёт» на троих

    def cash_shifts(self, branch, cashier):
        """Касса: вчерашняя смена закрыта (с разницей −50), сегодняшняя открыта с утра."""
        from apps.orders.cash import _payload, stats
        now = timezone.localtime()
        yesterday = (now - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
        shift = CashShift.objects.create(branch=branch, opened_by=cashier, opening_cash=2000)
        CashShift.objects.filter(pk=shift.pk).update(opened_at=yesterday)
        shift.refresh_from_db()
        CashMove.objects.create(shift=shift, kind=CashMove.Kind.OUT, amount=5000, comment="Инкассация", created_by=cashier)
        shift.closed_at, shift.closed_by = yesterday.replace(hour=22, minute=10), cashier
        shift.counted_cash = stats(shift)["expected"] - 50
        shift.report = _payload(shift, stats(shift))
        shift.save()
        today = CashShift.objects.create(branch=branch, opened_by=cashier, opening_cash=2000)
        CashShift.objects.filter(pk=today.pk).update(opened_at=now - timedelta(hours=3))

    # ----- Фото с Wikimedia Commons -----
    def photos(self):
        folder = Path(settings.MEDIA_ROOT)
        folder.mkdir(parents=True, exist_ok=True)
        credits, cache, saved = [], {}, 0
        for dish in Dish.objects.order_by("id"):
            query = self.query_for(dish.name)
            if query not in cache:
                cache[query] = self.find_photo(query)
            found = cache[query]
            if found == "offline":                                     # нет интернета — дальше не пробуем
                self.stderr.write("Нет связи с Wikimedia Commons — блюда остаются без фото. Запустите seed_demo позже с интернетом.")
                break
            if not found:
                continue
            content, filename, credit = found
            dish.photo.save(filename, ContentFile(content), save=True)
            saved += 1
            if credit not in credits:
                credits.append(credit)
        (folder / "АВТОРЫ-ФОТО.txt").write_text(
            "Фото блюд в демо — Wikimedia Commons (свободные лицензии). Авторы и лицензии:\n\n" + "\n".join(credits) + "\n",
            encoding="utf-8")
        return saved

    @staticmethod
    def query_for(name):
        for _, items in MENU:
            for item in items:
                if item[0] == name:
                    return item[4]
        return name

    def find_photo(self, query):
        """Первое подходящее фото по запросу: JPEG/PNG со свободной лицензией. Возвращает (байты, имя файла, «автор · лицензия · ссылка»)."""
        params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": 10,
                  "gsrsearch": f"{query} filetype:bitmap", "prop": "imageinfo", "iiprop": "url|mime|extmetadata", "iiurlwidth": 800}
        try:
            data = self.fetch("https://commons.wikimedia.org/w/api.php?" + urlencode(params))
            pages = sorted(json.loads(data).get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        except Exception as error:                                     # нет интернета — без фото
            self.stderr.write(f"Фото «{query}» не найдено: {error}")
            return "offline"
        for page in pages:
            info = (page.get("imageinfo") or [{}])[0]
            meta = info.get("extmetadata", {})
            license_name = meta.get("LicenseShortName", {}).get("value", "")
            if info.get("mime") not in ("image/jpeg", "image/png") or not info.get("thumburl"):
                continue
            if not re.search(r"CC0|CC BY|Public domain|PD", license_name, re.I):   # только свободные лицензии
                continue
            try:
                content = self.fetch(info["thumburl"])
            except Exception:
                continue
            artist = re.sub(r"<[^>]+>", "", meta.get("Artist", {}).get("value", "")).strip() or "неизвестен"
            extension = ".png" if info["mime"] == "image/png" else ".jpg"
            slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
            return content, f"demo-{slug}{extension}", f"{page.get('title', '')} — {artist} · {license_name} · {info.get('descriptionurl', '')}"
        self.stderr.write(f"Для «{query}» нет фото со свободной лицензией")
        return None

    @staticmethod
    def fetch(url):
        request = Request(url, headers={"User-Agent": "MuslimCafeDemo/1.0 (demo menu photos; python urllib)"})
        with urlopen(request, timeout=20) as response:
            return response.read()
