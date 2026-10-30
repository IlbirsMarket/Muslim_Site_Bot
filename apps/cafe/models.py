"""
Филиалы кафе и их настройки: часы работы, доставка, контакты.
У каждого филиала — свои меню, столы, сотрудники, заказы, отчёты и одна строка настроек.
"""

from datetime import time            # время без даты (10:00)

from django.db import models         # поля для таблиц
from django.utils import timezone    # текущее время с учётом часового пояса


class Branch(models.Model):
    """Филиал кафе: «Филиал 1», «Филиал 2». Название меняет шеф в настройках."""

    name = models.CharField("Название", max_length=60)                     # «Филиал 1» или, например, «Джал»
    position = models.PositiveIntegerField("Порядок", default=0)           # порядок в переключателе
    is_active = models.BooleanField("Работает", default=True)              # выключенный филиал не видят гости

    # ----- Telegram: группа филиала с темами (ID узнать командой /ids в группе) -----
    tg_group_id = models.BigIntegerField("Telegram: ID группы", null=True, blank=True)        # «Муслим — смена · филиал»
    tg_topic_admins = models.BigIntegerField("Тема «Админы»", null=True, blank=True)          # доставки и самовывозы
    tg_topic_kitchen = models.BigIntegerField("Тема «Кухня»", null=True, blank=True)          # подтверждённые заказы
    tg_topic_hall = models.BigIntegerField("Тема «Зал»", null=True, blank=True)               # заказы со столов, вызовы
    tg_topic_delivery = models.BigIntegerField("Тема «Доставка»", null=True, blank=True)      # курьеры
    tg_topic_reports = models.BigIntegerField("Тема «Отчёты»", null=True, blank=True)         # отчёт за день

    class Meta:
        ordering = ["position", "id"]
        verbose_name = "Филиал"
        verbose_name_plural = "Филиалы"

    def __str__(self):
        return self.name

    @classmethod
    def default(cls) -> "Branch":
        """Первый филиал — к нему относится всё, что было до появления филиалов. Если филиалов нет — создаём."""
        branch = cls.objects.order_by("position", "id").first()
        return branch or cls.objects.create(name="Филиал 1", position=10)


def default_branch_id() -> int:
    """id первого филиала — значение по умолчанию для поля «Филиал» у меню, столов и заказов."""
    pk = Branch.objects.order_by("position", "id").values_list("pk", flat=True).first()   # только id: работает и во время миграций
    return pk or Branch.default().pk


class CafeSettings(models.Model):
    """Настройки одного филиала (у каждого филиала — ровно одна строка)."""

    branch = models.OneToOneField(                                   # чьи это настройки
        Branch, on_delete=models.CASCADE, related_name="settings", verbose_name="Филиал",
        default=default_branch_id,
    )

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
        return f"Настройки: {self.branch}"

    @classmethod
    def load(cls, branch=None) -> "CafeSettings":
        """Настройки филиала (без филиала — первого). Если их ещё нет — создать со значениями по умолчанию."""
        branch = branch or Branch.default()
        settings_obj, _ = cls.objects.get_or_create(branch=branch)   # строка этого филиала или новая
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
