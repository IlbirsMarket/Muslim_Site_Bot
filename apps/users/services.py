"""Бизнес-логика сотрудников: смена роли."""

from django.db import transaction                       # "всё или ничего"
from rest_framework.exceptions import PermissionDenied  # ошибка 403

from .models import RoleChangeLog, User


@transaction.atomic
def change_role(actor: User, target: User, new_role: str) -> User:
    """actor меняет роль сотруднику target. Проверяет права и пишет в журнал."""
    if not actor.can_change_role(target, new_role):          # нет прав на такую смену
        raise PermissionDenied("Вы не можете поставить эту роль этому сотруднику.")
    if target.role == new_role:                               # роль та же — ничего не делаем
        return target
    old_role = target.role                                    # запоминаем старую роль
    target.role = new_role                                    # ставим новую
    target.save(update_fields=["role"])                       # сохраняем только роль
    RoleChangeLog.objects.create(                             # пишем в журнал
        user=target, changed_by=actor, old_role=old_role, new_role=new_role,
    )
    return target