"""
Столы кафе и QR-коды.
Каждый стол (и отдельно "Доставка") имеет секретный токен — он зашит в QR-код.
"""

import secrets                                  # генерация случайных безопасных строк

from django.conf import settings                # настройки проекта (берём SITE_URL)
from django.core.exceptions import ValidationError  # ошибка проверки данных
from django.db import models                    # поля для таблиц


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
    number = models.PositiveIntegerField("Номер стола", null=True, blank=True, unique=True)  # у доставки номера нет
    name = models.CharField("Название", max_length=50, blank=True)    # "Стол 7" (заполнится сам) или "Доставка"
    token = models.CharField("Токен QR", max_length=32, unique=True, default=generate_token, editable=False)  # секрет в QR
    is_active = models.BooleanField("Активен", default=True)          # выключенный стол не принимает заказы
    created_at = models.DateTimeField("Создан", auto_now_add=True)    # дата создания

    class Meta:
        ordering = ["kind", "number"]   # сначала стол "Доставка" (по алфавиту), потом столы по номерам
        verbose_name = "Стол"
        verbose_name_plural = "Столы"

    def __str__(self):
        return self.name or f"Стол {self.number}"   # как отображается в админке

    def clean(self):
        """Проверка перед сохранением из форм: у стола в зале обязательно должен быть номер."""
        if self.kind == self.Kind.HALL and not self.number:
            raise ValidationError({"number": "Укажите номер стола."})

    def save(self, *args, **kwargs):
        """Если название пустое — ставим его автоматически."""
        if not self.name:                                    # название не задано
            if self.kind == self.Kind.DELIVERY:
                self.name = "Доставка"                       # для доставки
            else:
                self.name = f"Стол {self.number}"            # для стола: "Стол 7"
        super().save(*args, **kwargs)                        # сохраняем как обычно

    @property
    def qr_url(self) -> str:
        """Полный адрес, который зашит в QR: http://сайт/t/k8Fq2xLm"""
        return f"{settings.SITE_URL.rstrip('/')}/t/{self.token}"

    def regenerate_token(self) -> None:
        """Перевыпуск QR: новый токен, старый QR перестаёт работать."""
        self.token = generate_token()                 # новый случайный токен
        self.save(update_fields=["token"])            # сохраняем только токен