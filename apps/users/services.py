"""Бизнес-логика сотрудников: смена роли."""

from django.db import transaction                       # "всё или ничего"
from rest_framework.exceptions import PermissionDenied  # ошибка 403

from .models import RoleChangeLog, User


@transaction.atomic
def change_role(actor: User, target: User, new_role: str, branch=None) -> User:
    """
    actor меняет роль сотруднику target. Проверяет права и пишет в журнал.
    Шеф и программист — без филиала. Если сотрудник был шефом и стал, например, админом, —
    он попадает в филиал branch (тот, что выбран сейчас в панели).
    """
    if not actor.can_change_role(target, new_role):          # нет прав на такую смену
        raise PermissionDenied("Вы не можете поставить эту роль этому сотруднику.")
    if target.role == new_role:                               # роль та же — ничего не делаем
        return target
    old_role = target.role                                    # запоминаем старую роль
    target.role = new_role                                    # ставим новую
    if target.sees_all_branches():                            # стал шефом / программистом — видит все филиалы
        target.branch = None
    elif target.branch_id is None:                            # был шефом — нужен филиал
        target.branch = branch or actor.branch
    target.save(update_fields=["role", "branch"])             # сохраняем роль и филиал
    RoleChangeLog.objects.create(                             # пишем в журнал
        user=target, changed_by=actor, old_role=old_role, new_role=new_role,
    )
    return target


def end_all_sessions(user: User) -> int:
    """
    Отменить все входы сотрудника на всех устройствах: каждый его ключ продления — в чёрный список.
    Токен входа (живёт 15 минут) после блокировки или смены пароля не принимается сразу же
    (проверки в simplejwt), а после смены роли права и так берутся из базы при каждом запросе.
    Возвращает, сколько ключей отменено.
    """
    from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken  # таблицы ключей

    tokens = OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True)   # ещё не отменённые ключи
    BlacklistedToken.objects.bulk_create([BlacklistedToken(token=t) for t in tokens], ignore_conflicts=True)
    return len(tokens)
