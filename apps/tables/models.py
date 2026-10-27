"""
Столы кафе и QR-коды.
Столы: «Стол 1», «Стол 2»… — у каждого секретный токен в QR.
Доставка: одна-единственная, создаётся сама, её QR ведёт на главную страницу сайта.
"""

import re                                       # проверка «автоматического» названия
import secrets                                  # генерация случайных безопасных строк

from django.conf import settings                # настройки проекта (берём SITE_URL)
from django.db import models                    # поля для таблиц
from django.db.models import Max                # самый большой номер

AUTO_NAME = re.compile(r"^Стол( \d+)?$")   # «Стол 7» — название, которое ставится само


def generate_token() -> str:
    """Создаёт случайный токен из 8–9 символов, например 'k8Fq2xLm'."""
    return secrets.token_urlsafe(6)


class Table(models.Model):
    """Стол в зале или специальная точка «Доставка»."""

    class Kind(models.TextChoices):
        """Тип точки заказа."""
        HALL = "hall", "Стол в зале"       # гость сидит в кафе
        DELIVERY = "delivery", "Доставка"  # гость заказывает домой

    kind = models.CharField("Тип", max_length=20, choices=Kind.choices, default=Kind.HALL)  # зал или доставка
    number = models.PositiveIntegerField("Номер", null=True, blank=True)  # Стол 1, 2, 3… (ставится сам); у доставки — 1
    name = models.CharField("Название", max_length=50, blank=True)    # "Стол 7" / "Доставка" (заполнится само)
    token = models.CharField("Токен QR", max_length=32, unique=True, default=generate_token, editable=False)  # секрет в QR
    is_active = models.BooleanField("Активен", default=True)          # выключенный стол не принимает заказы
    created_at = models.DateTimeField("Создан", auto_now_add=True)    # дата создания
    # С какого времени стол занят: ставится, когда официант подтвердил первый заказ,
    # и очищается кнопкой «Гости ушли — закрыть стол». Пусто — стол свободен
    occupied_since = models.DateTimeField("Занят с", null=True, blank=True)

    class Meta:
        ordering = ["kind", "number"]   # сначала доставка, потом столы по номерам
        verbose_name = "Стол"
        verbose_name_plural = "Столы"
        constraints = [
            # Номер не повторяется внутри своего типа (и доставка может быть только одна — у неё всегда номер 1)
            models.UniqueConstraint(fields=["kind", "number"], name="unique_table_number_per_kind"),
        ]

    def __str__(self):
        return self.name or f"Стол {self.number}"   # как отображается в админке

    @classmethod
    def next_number(cls) -> int:
        """Самый маленький свободный номер стола: есть 1, 3, 4 → вернёт 2; есть 1–7 → вернёт 8."""
        used = set(cls.objects.filter(kind=cls.Kind.HALL).values_list("number", flat=True))
        number = 1
        while number in used:
            number += 1
        return number

    @classmethod
    def delivery_point(cls) -> "Table":
        """Единственная «Доставка». Если её почему-то нет — создаём."""
        point, _ = cls.objects.get_or_create(kind=cls.Kind.DELIVERY, number=1, defaults={"name": "Доставка"})
        return point

    def save(self, *args, **kwargs):
        """Номер и название ставим сами. Своё название стола (например, «Стол у окна») не трогаем."""
        if self.kind == self.Kind.DELIVERY:                         # доставка всегда одна: номер 1, «Доставка»
            self.number = 1
            self.name = "Доставка"
        else:
            if not self.number:                                     # номер не указали —
                self.number = self.next_number()                    # берём самый маленький свободный
            if not self.name or AUTO_NAME.match(self.name):         # пустое или автоматическое название —
                self.name = f"Стол {self.number}"                   # «Стол 8»
        super().save(*args, **kwargs)                               # сохраняем как обычно

    @property
    def qr_url(self) -> str:
        """Адрес в QR. Стол: http://сайт/t/k8Fq2xLm. Доставка: просто главная страница http://сайт/"""
        if self.kind == self.Kind.DELIVERY:
            return f"{settings.SITE_URL.rstrip('/')}/"
        return f"{settings.SITE_URL.rstrip('/')}/t/{self.token}"

    def regenerate_token(self) -> None:
        """Перевыпуск QR: новый токен, старый QR перестаёт работать."""
        self.token = generate_token()                 # новый случайный токен
        self.save(update_fields=["token"])            # сохраняем только токен