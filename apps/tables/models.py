"""
Столы кафе и QR-коды.
Этажи у каждого филиала свои: новый филиал начинает с «1 этаж», кнопка «+ Этаж» добавляет следующий.
Номера столов свои на каждом этаже: «Стол 1 · 1 этаж», «Стол 1 · 2 этаж».
У каждого стола секретный токен в QR. Доставка — одна, создаётся сама, у неё тоже свой секретный QR.
Без токена сайт показывает только меню — заказать нельзя.
"""

import re                                       # проверка «автоматического» названия
import secrets                                  # генерация случайных безопасных строк

from django.conf import settings                # настройки проекта (берём SITE_URL)
from django.db import models                    # поля для таблиц
from django.db.models import Max                # самый большой номер

from apps.cafe.models import Branch, default_branch_id   # филиал стола (по умолчанию — первый)

AUTO_NAME = re.compile(r"^Стол( \d+)?( · \d этаж)?$")   # «Стол 7 · 2 этаж» — название, которое ставится само


def generate_token() -> str:
    """Создаёт случайный токен из 8–9 символов, например 'k8Fq2xLm'."""
    return secrets.token_urlsafe(6)


class Floor(models.Model):
    """Этаж филиала: 1, 2, 3… Добавляется кнопкой «+ Этаж», удаляется — только последний и пустой (кроме 1-го)."""

    branch = models.ForeignKey(                                  # чей этаж
        Branch, on_delete=models.CASCADE, related_name="floors", verbose_name="Филиал",
    )
    number = models.PositiveSmallIntegerField("Номер этажа")     # 1, 2, 3…

    class Meta:
        ordering = ["branch", "number"]                          # по порядку
        verbose_name = "Этаж"
        verbose_name_plural = "Этажи"
        constraints = [
            models.UniqueConstraint(fields=["branch", "number"], name="unique_floor_per_branch"),   # этаж не повторяется
        ]

    def __str__(self):
        return f"{self.number} этаж · {self.branch}"

    @classmethod
    def for_branch(cls, branch) -> list:
        """Этажи филиала по порядку. 1 этаж есть всегда — если его нет, создаём."""
        cls.objects.get_or_create(branch=branch, number=1)
        return list(cls.objects.filter(branch=branch))

    @classmethod
    def add_next(cls, branch) -> "Floor":
        """«+ Этаж»: следующий номер после самого большого (был 2 → станет 3)."""
        last = cls.objects.filter(branch=branch).aggregate(top=Max("number"))["top"] or 0
        return cls.objects.create(branch=branch, number=last + 1)


class Table(models.Model):
    """Стол в зале или специальная точка «Доставка»."""

    class Kind(models.TextChoices):
        """Тип точки заказа."""
        HALL = "hall", "Стол в зале"       # гость сидит в кафе
        DELIVERY = "delivery", "Доставка"  # гость заказывает домой

    branch = models.ForeignKey(                                       # филиал: у каждого свои столы и своя доставка
        Branch, on_delete=models.PROTECT, related_name="tables", verbose_name="Филиал",
        default=default_branch_id,
    )
    kind = models.CharField("Тип", max_length=20, choices=Kind.choices, default=Kind.HALL)  # зал или доставка
    floor = models.PositiveSmallIntegerField("Этаж", default=1)   # номер этажа филиала (у доставки — 1)
    number = models.PositiveIntegerField("Номер", null=True, blank=True)  # Стол 1, 2, 3… на своём этаже (ставится сам); у доставки — 1
    name = models.CharField("Название", max_length=50, blank=True)    # "Стол 7" / "Доставка" (заполнится само)
    token = models.CharField("Токен QR", max_length=32, unique=True, default=generate_token, editable=False)  # секрет в QR
    is_active = models.BooleanField("Активен", default=True)          # выключенный стол не принимает заказы
    created_at = models.DateTimeField("Создан", auto_now_add=True)    # дата создания
    # С какого времени стол занят: ставится, когда официант подтвердил первый заказ,
    # и очищается кнопкой «Гости ушли — закрыть стол». Пусто — стол свободен
    occupied_since = models.DateTimeField("Занят с", null=True, blank=True)
    freed_at = models.DateTimeField("Освобождён", null=True, blank=True)   # когда последний раз нажали «Освободить стол»

    class Meta:
        ordering = ["kind", "floor", "number"]   # сначала доставка, потом столы по этажам и номерам
        verbose_name = "Стол"
        verbose_name_plural = "Столы"
        constraints = [
            # Номер не повторяется на одном этаже филиала (и доставка в филиале одна — у неё всегда этаж 1, номер 1)
            models.UniqueConstraint(fields=["branch", "kind", "floor", "number"], name="unique_table_number_per_branch_floor"),
        ]

    def __str__(self):
        return self.name or f"Стол {self.number}"   # как отображается в админке

    @classmethod
    def next_number(cls, floor: int = 1, branch=None) -> int:
        """Самый маленький свободный номер на этаже филиала: есть 1, 3, 4 → вернёт 2; есть 1–7 → вернёт 8."""
        branch = branch or Branch.default()
        used = set(cls.objects.filter(branch=branch, kind=cls.Kind.HALL, floor=floor).values_list("number", flat=True))
        number = 1
        while number in used:
            number += 1
        return number

    @classmethod
    def delivery_point(cls, branch=None) -> "Table":
        """«Доставка» филиала (без филиала — первого). Если её почему-то нет — создаём."""
        branch = branch or Branch.default()
        point, _ = cls.objects.get_or_create(branch=branch, kind=cls.Kind.DELIVERY, number=1, defaults={"name": "Доставка"})
        return point

    def save(self, *args, **kwargs):
        """Номер и название ставим сами. Своё название стола (например, «Стол у окна») не трогаем."""
        if self.kind == self.Kind.DELIVERY:                         # доставка всегда одна: этаж 1, номер 1, «Доставка»
            self.floor = 1
            self.number = 1
            self.name = "Доставка"
        else:
            if not self.number:                                     # номер не указали —
                self.number = self.next_number(self.floor, self.branch)   # берём самый маленький свободный на этаже филиала
            if not self.name or AUTO_NAME.match(self.name):         # пустое или автоматическое название —
                self.name = f"Стол {self.number} · {self.floor} этаж"   # «Стол 8 · 2 этаж»
        super().save(*args, **kwargs)                               # сохраняем как обычно

    @property
    def qr_url(self) -> str:
        """Адрес в QR: http://сайт/t/k8Fq2xLm — и у стола, и у доставки (без токена заказать нельзя)."""
        return f"{settings.SITE_URL.rstrip('/')}/t/{self.token}"

    def regenerate_token(self) -> None:
        """Перевыпуск QR: новый токен, старый QR перестаёт работать."""
        self.token = generate_token()                 # новый случайный токен
        self.save(update_fields=["token"])            # сохраняем только токен
