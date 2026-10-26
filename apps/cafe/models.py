"""
Настройки кафе: часы работы, доставка, контакты.
В таблице всегда ровно одна строка (id = 1).
"""

from datetime import time            # время без даты (10:00)

from django.db import models         # поля для таблиц
from django.utils import timezone    # текущее время с учётом часового пояса


class CafeSettings(models.Model):
    """Единственная запись с настройками кафе."""

    is_accepting_orders = models.BooleanField("Принимать заказы", default=True)       # общий выключатель приёма
    is_delivery_enabled = models.BooleanField("Принимать доставку", default=True)     # выключатель доставки
    opens_at = models.TimeField("Открываемся", default=time(10, 0))                   # начало работы
    closes_at = models.TimeField("Закрываемся", default=time(23, 0))                  # конец работы
    delivery_fee = models.PositiveIntegerField("Стоимость доставки, сом", default=150)
    delivery_min_sum = models.PositiveIntegerField("Мин. сумма доставки, сом", default=800)
    free_delivery_from = models.PositiveIntegerField("Бесплатная доставка от, сом (0 — нет)", default=0)
    delivery_time = models.CharField("Время доставки (текст)", max_length=50, default="40–60 минут")
    address = models.CharField("Адрес кафе", max_length=200, blank=True)
    phone = models.CharField("Телефон кафе", max_length=30, blank=True)
    updated_at = models.DateTimeField("Изменено", auto_now=True)

    class Meta:
        verbose_name = "Настройки кафе"
        verbose_name_plural = "Настройки кафе"

    def __str__(self):
        return "Настройки кафе"

    def save(self, *args, **kwargs):
        """Всегда сохраняем в строку с id = 1, чтобы вторая запись не появилась."""
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls) -> "CafeSettings":
        """Получить настройки. Если их ещё нет — создать со значениями по умолчанию."""
        settings_obj, _ = cls.objects.get_or_create(pk=1)   # берём строку id=1 или создаём её
        return settings_obj

    def is_open_now(self) -> bool:
        """Открыто ли кафе прямо сейчас (учитываем работу через полночь, например 10:00–02:00)."""
        now = timezone.localtime().time()                   # текущее время в Бишкеке
        if self.opens_at <= self.closes_at:                 # обычный режим: 10:00–23:00
            return self.opens_at <= now < self.closes_at
        return now >= self.opens_at or now < self.closes_at  # режим через полночь

    def can_accept_orders(self) -> bool:
        """Можно ли сейчас оформить заказ: приём включён и кафе открыто."""
        return self.is_accepting_orders and self.is_open_now()