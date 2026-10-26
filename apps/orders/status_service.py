"""
Смена статусов заказа сотрудниками.
Здесь собраны все правила: какое действие, из какого статуса и кто может его сделать.
"""

from datetime import timedelta                                     # промежуток времени

from django.db import transaction                                  # "всё или ничего"
from django.utils import timezone                                  # текущее время
from rest_framework.exceptions import PermissionDenied, ValidationError  # ошибки 403 и 400

from .models import Order, OrderStatusLog, TableVisit

S = Order.Status   # короткие имена, чтобы правила ниже читались легче
K = Order.Kind

VISIT_HOURS = 4    # сколько часов телефон остаётся доверенным, если стол не закрыли вручную
REJECT_DEFAULT_REASON = "Стол не подтвердил заказ"


# ===================== ДОВЕРЕННЫЙ ТЕЛЕФОН =====================

def active_visit(table, device_key):
    """Открытый визит этого телефона за этим столом (или None)."""
    if not table or not device_key:                                 # нет стола или ключа — доверия нет
        return None
    since = timezone.now() - timedelta(hours=VISIT_HOURS)           # визиты старше 4 часов не считаем
    return TableVisit.objects.filter(
        table=table, device_key=device_key, closed_at__isnull=True, started_at__gte=since,
    ).first()


def close_visits(table, user) -> int:
    """Закрыть стол: все телефоны за этим столом перестают быть доверенными. Возвращает количество."""
    return TableVisit.objects.filter(table=table, closed_at__isnull=True).update(
        closed_at=timezone.now(), closed_by=user,
    )


# ===================== КТО ЧТО МОЖЕТ =====================

def _can_confirm(user, order) -> bool:
    """Подтвердить / отклонить новый заказ."""
    if order.kind != K.HALL:                                        # доставка и самовывоз — только админ (звонит гостю)
        return user.is_cafe_admin
    if user.is_cafe_admin:                                          # админ может всегда
        return True
    if not user.is_waiter:                                          # остальные — нет
        return False
    return order.claimed_by_id in (None, user.id)                   # официант: если стол никто не взял или взял он сам


def _can_cook(user, order) -> bool:
    """Кухонные статусы: «Готовится», «Готов»."""
    return user.is_cafe_admin or user.is_cook


def _can_send(user, order) -> bool:
    """«В пути» — только доставка, только админ."""
    return order.kind == K.DELIVERY and user.is_cafe_admin


def _can_complete(user, order) -> bool:
    """Завершить: подан / доставлен / выдан."""
    if order.kind == K.DELIVERY:                                    # доставку завершаем только после «В пути»
        return order.status == S.ON_THE_WAY and user.is_cafe_admin
    if order.status != S.READY:                                     # зал и самовывоз — после «Готов»
        return False
    if order.kind == K.HALL:
        return user.is_cafe_admin or user.is_waiter                 # в зале подаёт официант
    return user.is_cafe_admin                                       # самовывоз выдаёт админ


def _can_cancel(user, order) -> bool:
    """Отменить уже принятый заказ — только админ."""
    return user.is_cafe_admin


# Таблица действий: из каких статусов, в какой статус, кто может, нужна ли причина
ACTIONS = {
    "accept":   {"from": [S.NEW], "to": S.ACCEPTED, "check": _can_confirm, "label": "Подтвердить", "reason": False},
    "reject":   {"from": [S.NEW], "to": S.CANCELLED, "check": _can_confirm, "label": "Отклонить", "reason": False},
    "cook":     {"from": [S.ACCEPTED], "to": S.COOKING, "check": _can_cook, "label": "Готовится", "reason": False},
    "ready":    {"from": [S.COOKING], "to": S.READY, "check": _can_cook, "label": "Готов", "reason": False},
    "send":     {"from": [S.READY], "to": S.ON_THE_WAY, "check": _can_send, "label": "В пути", "reason": False},
    "complete": {"from": [S.READY, S.ON_THE_WAY], "to": S.COMPLETED, "check": _can_complete, "label": "Завершить", "reason": False},
    "cancel":   {"from": [S.ACCEPTED, S.COOKING, S.READY, S.ON_THE_WAY], "to": S.CANCELLED, "check": _can_cancel, "label": "Отменить", "reason": True},
}


def available_actions(order, user) -> list:
    """Какие кнопки показать этому сотруднику для этого заказа."""
    result = []
    for name, rule in ACTIONS.items():                              # перебираем все действия
        if order.status in rule["from"] and rule["check"](user, order):   # статус подходит и права есть
            label = order.completed_label if name == "complete" else rule["label"]  # "Подан на стол" вместо "Завершить"
            result.append({"action": name, "label": label, "needs_reason": rule["reason"]})
    if order.kind == K.HALL and order.status == S.NEW and not order.claimed_by_id and (user.is_waiter or user.is_cafe_admin):
        result.insert(0, {"action": "claim", "label": "Беру стол", "needs_reason": False})  # кнопка "Беру стол" первой
    return result


# ===================== ДЕЙСТВИЯ =====================

@transaction.atomic
def claim_order(order, user) -> Order:
    """Официант нажал «Беру стол»: остальные видят, что стол уже взят."""
    order = Order.objects.select_for_update().get(pk=order.pk)      # блокируем строку: два официанта не возьмут одновременно
    if order.kind != K.HALL or order.status != S.NEW:
        raise ValidationError({"action": "Взять можно только новый заказ в зале."})
    if not (user.is_waiter or user.is_cafe_admin):
        raise PermissionDenied("Брать стол может только официант или админ.")
    if order.claimed_by_id and order.claimed_by_id != user.id:      # уже взял кто-то другой
        name = order.claimed_by.first_name or order.claimed_by.username
        raise ValidationError({"action": f"Этот стол уже взял(а) {name}."})
    order.claimed_by = user                                         # записываем, кто взял
    order.save(update_fields=["claimed_by", "updated_at"])
    return order


@transaction.atomic
def change_status(order, action: str, user, reason: str = "") -> Order:
    """Меняет статус заказа по правилам из ACTIONS."""
    rule = ACTIONS.get(action)
    if not rule:                                                    # такого действия нет
        raise ValidationError({"action": "Неизвестное действие."})

    order = Order.objects.select_for_update().get(pk=order.pk)      # свежие данные + блокировка от одновременных нажатий
    if order.status not in rule["from"]:                            # из этого статуса так нельзя
        raise ValidationError({"action": f"Нельзя «{rule['label']}», когда заказ «{order.status_label}»."})
    if not rule["check"](user, order):                              # нет прав
        raise PermissionDenied("У вас нет прав на это действие.")

    reason = (reason or "").strip()
    if rule["reason"] and not reason:                               # для отмены причина обязательна
        raise ValidationError({"reason": "Укажите причину."})

    order.status = rule["to"]                                       # новый статус
    fields = ["status", "updated_at"]                               # какие поля сохраняем

    if action == "accept":
        order.accepted_by = user                                    # кто подтвердил
        fields.append("accepted_by")
        if order.kind == K.HALL and order.table_id and order.device_key and not active_visit(order.table, order.device_key):
            TableVisit.objects.create(                              # телефон гостя становится доверенным
                table=order.table, device_key=order.device_key, confirmed_by=user,
            )

    if rule["to"] == S.CANCELLED:                                   # отклонение или отмена
        order.cancel_reason = reason or REJECT_DEFAULT_REASON
        fields.append("cancel_reason")

    order.save(update_fields=fields)                                # сохраняем
    OrderStatusLog.objects.create(order=order, status=order.status, changed_by=user)  # пишем в историю
    return order