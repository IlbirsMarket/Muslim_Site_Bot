"""
Таблицы Telegram-бота:
BotEvent   — «почтовый ящик»: события с сайта, которые бот должен отправить
BotMessage — какие сообщения в Telegram принадлежат заказу или вызову (чтобы их редактировать)
LinkCode   — одноразовый код для привязки Telegram сотрудника
"""

from datetime import timedelta     # промежуток времени

from django.conf import settings   # чтобы сослаться на модель сотрудника (AUTH_USER_MODEL)
from django.db import models       # поля для таблиц
from django.db.models import Q     # условия для ограничений
from django.utils import timezone  # текущее время

LINK_CODE_MINUTES = 10             # сколько минут живёт код привязки


class BotEvent(models.Model):
    """Событие с сайта. Бот забирает неотправленные (processed_at пусто) и шлёт в Telegram."""

    class Kind(models.TextChoices):
        """Что случилось на сайте."""
        ORDER_CREATED = "order_created", "Новый заказ"        # гость оформил заказ
        ORDER_CHANGED = "order_changed", "Заказ изменён"      # статус, «Беру стол», «Беру заказ»
        CALL_CREATED = "call_created", "Вызов со стола"       # «Позвать официанта» или «Счёт»
        CALL_DONE = "call_done", "Вызов выполнен"             # официант нажал «Выполнено»
        TABLE_FREED = "table_freed", "Стол освобождён"        # «Освободить стол»

    kind = models.CharField("Что случилось", max_length=20, choices=Kind.choices)  # тип события
    order = models.ForeignKey(                                # заказ (если событие про заказ)
        "orders.Order", on_delete=models.CASCADE, null=True, blank=True,
        related_name="bot_events", verbose_name="Заказ",
    )
    call = models.ForeignKey(                                 # вызов (если событие про вызов)
        "orders.TableCall", on_delete=models.CASCADE, null=True, blank=True,
        related_name="bot_events", verbose_name="Вызов",
    )
    table = models.ForeignKey(                                # стол (если событие про стол)
        "tables.Table", on_delete=models.CASCADE, null=True, blank=True,
        related_name="bot_events", verbose_name="Стол",
    )
    payload = models.JSONField("Подробности", default=dict, blank=True)              # мелочи: причина отмены и т.п.
    created_at = models.DateTimeField("Создано", auto_now_add=True)                  # когда сайт записал событие
    processed_at = models.DateTimeField("Отправлено", null=True, blank=True, db_index=True)  # пусто — бот ещё не отправил
    attempts = models.PositiveSmallIntegerField("Попыток", default=0)                # сколько раз бот пробовал отправить
    last_error = models.TextField("Последняя ошибка", blank=True)                    # текст ошибки, если не получилось

    class Meta:
        ordering = ["id"]                       # от старых к новым — бот шлёт по порядку
        verbose_name = "Событие для бота"
        verbose_name_plural = "События для бота"

    def __str__(self):
        return f"{self.get_kind_display()} #{self.pk}"   # например: «Новый заказ #15»


class BotMessage(models.Model):
    """Сообщение в Telegram, которое принадлежит заказу или вызову. По нему бот редактирует, а не шлёт новое."""

    class Place(models.TextChoices):
        """Куда отправлено сообщение."""
        ADMINS = "admins", "Тема «Админы»"
        KITCHEN = "kitchen", "Тема «Кухня»"
        HALL = "hall", "Тема «Зал»"
        DELIVERY = "delivery", "Тема «Доставка»"
        GUEST = "guest", "Гостю в личку"

    order = models.ForeignKey(                                # заказ (или пусто, если это вызов)
        "orders.Order", on_delete=models.CASCADE, null=True, blank=True,
        related_name="bot_messages", verbose_name="Заказ",
    )
    call = models.ForeignKey(                                 # вызов (или пусто, если это заказ)
        "orders.TableCall", on_delete=models.CASCADE, null=True, blank=True,
        related_name="bot_messages", verbose_name="Вызов",
    )
    place = models.CharField("Куда", max_length=10, choices=Place.choices)  # тема группы или гость
    chat_id = models.BigIntegerField("ID чата")                             # группа или личка гостя
    thread_id = models.BigIntegerField("ID темы", null=True, blank=True)    # тема форума (у лички пусто)
    message_id = models.BigIntegerField("ID сообщения")                     # какое сообщение редактировать
    created_at = models.DateTimeField("Создано", auto_now_add=True)         # когда отправили
    updated_at = models.DateTimeField("Изменено", auto_now=True)            # когда последний раз редактировали

    class Meta:
        verbose_name = "Сообщение в Telegram"
        verbose_name_plural = "Сообщения в Telegram"
        constraints = [
            models.CheckConstraint(                           # ровно одно из двух: или заказ, или вызов
                condition=(Q(order__isnull=False) & Q(call__isnull=True)) | (Q(order__isnull=True) & Q(call__isnull=False)),
                name="bot_message_order_or_call",
            ),
            models.UniqueConstraint(                          # у заказа одно сообщение в каждой теме
                fields=["order", "place"], condition=Q(order__isnull=False),
                name="unique_bot_message_order_place",
            ),
            models.UniqueConstraint(                          # у вызова одно сообщение в каждой теме
                fields=["call", "place"], condition=Q(call__isnull=False),
                name="unique_bot_message_call_place",
            ),
        ]

    def __str__(self):
        return f"{self.get_place_display()} — сообщение {self.message_id}"   # например: «Тема «Кухня» — сообщение 52»


class LinkCode(models.Model):
    """Одноразовый код «Привязать Telegram». Ссылка: t.me/<бот>?start=link_<код>."""

    user = models.ForeignKey(                                 # чей код
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="telegram_link_codes", verbose_name="Сотрудник",
    )
    code = models.CharField("Код", max_length=32, unique=True)              # случайный код, не повторяется
    created_at = models.DateTimeField("Создан", auto_now_add=True)          # когда выдали
    used_at = models.DateTimeField("Использован", null=True, blank=True)    # пусто — ещё не использован

    class Meta:
        verbose_name = "Код привязки Telegram"
        verbose_name_plural = "Коды привязки Telegram"

    def __str__(self):
        return f"Код для {self.user}"                         # код не показываем — он секретный

    def is_valid(self) -> bool:
        """Код годен: ещё не использован и ему меньше 10 минут."""
        if self.used_at:                                      # уже использовали — второй раз нельзя
            return False
        return timezone.now() - self.created_at < timedelta(minutes=LINK_CODE_MINUTES)  # не просрочен