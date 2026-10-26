"""
Таблицы заказов:
Order          — заказ
OrderItem      — позиция заказа (копия названия и цены на момент заказа)
OrderStatusLog — история статусов: кто и когда поменял
TableCall      — вызов официанта или счёта со стола
TableVisit     — доверенный телефон гостя за столом
"""

import uuid                      # генерация уникального секретного id

from django.conf import settings  # чтобы сослаться на модель сотрудника (AUTH_USER_MODEL)
from django.db import models      # поля для таблиц


class Order(models.Model):
    """Заказ гостя."""

    class Kind(models.TextChoices):
        """Тип заказа."""
        HALL = "hall", "В зале"
        DELIVERY = "delivery", "Доставка"
        PICKUP = "pickup", "Самовывоз"

    class Status(models.TextChoices):
        """Статусы заказа по порядку."""
        NEW = "new", "Новый"
        ACCEPTED = "accepted", "Принят"
        COOKING = "cooking", "Готовится"
        READY = "ready", "Готов"
        ON_THE_WAY = "on_the_way", "В пути"     # только для доставки
        COMPLETED = "completed", "Завершён"     # подан / доставлен / выдан
        CANCELLED = "cancelled", "Отменён"

    class Payment(models.TextChoices):
        """Способ оплаты."""
        CASH = "cash", "Наличные"
        CARD = "card", "Картой при получении"

    class Source(models.TextChoices):
        """Откуда пришёл заказ."""
        SITE = "site", "Сайт"
        BOT = "bot", "Telegram-бот"

    # ----- Основное -----
    public_id = models.UUIDField("Секретный id", default=uuid.uuid4, unique=True, editable=False)  # по нему гость смотрит статус
    source = models.CharField("Источник", max_length=10, choices=Source.choices, default=Source.SITE)
    kind = models.CharField("Тип", max_length=10, choices=Kind.choices)
    status = models.CharField("Статус", max_length=20, choices=Status.choices, default=Status.NEW, db_index=True)  # db_index — быстрый поиск по статусу
    table = models.ForeignKey(                       # стол или точка "Доставка", с которой пришёл заказ
        "tables.Table", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="orders", verbose_name="Стол",
    )

    # ----- Данные гостя (для доставки и самовывоза) -----
    customer_name = models.CharField("Имя гостя", max_length=100, blank=True)
    phone = models.CharField("Телефон", max_length=30, blank=True)
    address = models.CharField("Улица и дом", max_length=255, blank=True)
    apartment = models.CharField("Квартира", max_length=20, blank=True)
    entrance = models.CharField("Подъезд", max_length=20, blank=True)
    floor = models.CharField("Этаж", max_length=20, blank=True)
    courier_comment = models.CharField("Комментарий курьеру", max_length=255, blank=True)

    # ----- Оплата и комментарии -----
    payment_method = models.CharField("Оплата", max_length=10, choices=Payment.choices, default=Payment.CASH)
    change_from = models.PositiveIntegerField("Сдача с суммы", null=True, blank=True)
    comment = models.TextField("Комментарий к заказу", blank=True)
    cancel_reason = models.CharField("Причина отмены", max_length=255, blank=True)

    # ----- Суммы (считает сервер) -----
    subtotal = models.PositiveIntegerField("Сумма блюд, сом", default=0)
    delivery_fee = models.PositiveIntegerField("Доставка, сом", default=0)
    total = models.PositiveIntegerField("Итого, сом", default=0)

    # ----- Служебное -----
    device_key = models.CharField("Ключ устройства", max_length=64, blank=True, db_index=True)  # случайный ключ телефона гостя (для доверия)
    claimed_by = models.ForeignKey(                  # официант, который взял стол ("Беру стол")
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="claimed_orders", verbose_name="Взял стол",
    )
    accepted_by = models.ForeignKey(                 # кто подтвердил заказ
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="accepted_orders", verbose_name="Принял",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField("Изменён", auto_now=True)

    class Meta:
        ordering = ["-created_at"]   # новые заказы сверху
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"

    def __str__(self):
        return f"Заказ №{self.pk}"

    @property
    def completed_label(self) -> str:
        """Как назвать статус «Завершён» для этого типа заказа."""
        return {
            self.Kind.HALL: "Подан на стол",
            self.Kind.DELIVERY: "Доставлен",
            self.Kind.PICKUP: "Выдан",
        }.get(self.kind, "Завершён")

    @property
    def status_label(self) -> str:
        """Название текущего статуса для показа людям."""
        if self.status == self.Status.COMPLETED:   # для «Завершён» — понятное слово
            return self.completed_label
        return self.get_status_display()           # для остальных — обычное название


class OrderItem(models.Model):
    """Позиция заказа. Название и цена копируются на момент заказа."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items", verbose_name="Заказ")
    dish = models.ForeignKey(                        # ссылка на блюдо (может пропасть, если блюдо удалят)
        "menu.Dish", on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Блюдо",
    )
    dish_name = models.CharField("Блюдо", max_length=150)                  # копия названия
    size_name = models.CharField("Размер", max_length=50, blank=True)      # копия размера ("30 см")
    extras = models.JSONField("Добавки", default=list, blank=True)        # копия добавок: [{"name": "Сыр", "price": 80}]
    unit_price = models.PositiveIntegerField("Цена за 1 шт, сом")          # цена размера + добавки
    quantity = models.PositiveIntegerField("Количество")

    class Meta:
        verbose_name = "Позиция"
        verbose_name_plural = "Позиции"

    def __str__(self):
        return f"{self.dish_name} × {self.quantity}"

    @property
    def line_total(self) -> int:
        """Сумма строки: цена × количество."""
        return self.unit_price * self.quantity


class OrderStatusLog(models.Model):
    """История статусов: что, кто и когда поменял."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_logs", verbose_name="Заказ")
    status = models.CharField("Статус", max_length=20, choices=Order.Status.choices)
    changed_by = models.ForeignKey(                  # кто поменял (пусто — система или гость)
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Кто",
    )
    created_at = models.DateTimeField("Когда", auto_now_add=True)

    class Meta:
        ordering = ["created_at"]   # от старых к новым
        verbose_name = "Смена статуса"
        verbose_name_plural = "История статусов"


class TableCall(models.Model):
    """Вызов со стола: «Позвать официанта» или «Попросить счёт»."""

    class Kind(models.TextChoices):
        WAITER = "waiter", "Позвать официанта"
        BILL = "bill", "Попросить счёт"

    table = models.ForeignKey("tables.Table", on_delete=models.CASCADE, related_name="calls", verbose_name="Стол")
    kind = models.CharField("Что нужно", max_length=10, choices=Kind.choices)
    is_done = models.BooleanField("Выполнено", default=False)
    done_by = models.ForeignKey(                     # кто из официантов отреагировал
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Кто выполнил",
    )
    created_at = models.DateTimeField("Создан", auto_now_add=True)
    done_at = models.DateTimeField("Выполнен", null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Вызов со стола"
        verbose_name_plural = "Вызовы со столов"

    def __str__(self):
        return f"{self.table} — {self.get_kind_display()}"


class TableVisit(models.Model):
    """
    Визит за столом: телефон гостя, который официант уже подтвердил.
    Пока визит открыт, заказы с этого телефона за этим столом сразу идут на кухню.
    """

    table = models.ForeignKey("tables.Table", on_delete=models.CASCADE, related_name="visits", verbose_name="Стол")
    device_key = models.CharField("Ключ устройства", max_length=64, db_index=True)      # какой телефон доверенный
    confirmed_by = models.ForeignKey(                 # официант, который подтвердил
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="confirmed_visits", verbose_name="Подтвердил",
    )
    started_at = models.DateTimeField("Начало", auto_now_add=True)
    closed_at = models.DateTimeField("Закрыт", null=True, blank=True)                     # пусто — визит ещё идёт
    closed_by = models.ForeignKey(                    # кто закрыл стол
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="closed_visits", verbose_name="Закрыл",
    )

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "Визит за столом"
        verbose_name_plural = "Визиты за столами"

    def __str__(self):
        return f"{self.table} — {self.started_at:%d.%m %H:%M}"