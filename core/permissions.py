"""
Общие права доступа для всего проекта.
Подключаем их во views через permission_classes.
"""

from rest_framework.permissions import BasePermission  # базовый класс для своих прав


def _get_user(request):
    """Возвращает сотрудника, если он вошёл в систему, иначе None."""
    user = request.user                       # пользователь из запроса (по токену)
    if user and user.is_authenticated:        # вошёл ли он
        return user
    return None


class IsStaffMember(BasePermission):
    """Любой сотрудник с ролью (программист, шеф, админ, повар, официант)."""
    message = "Нужно войти как сотрудник."    # текст ошибки, если доступа нет

    def has_permission(self, request, view):
        user = _get_user(request)             # берём сотрудника
        return bool(user and user.role)       # доступ есть, если у него есть роль


class IsCafeAdmin(BasePermission):
    """Админ, шеф или программист."""
    message = "Доступно только админу или шефу."

    def has_permission(self, request, view):
        user = _get_user(request)
        return bool(user and user.is_cafe_admin)


class IsChef(BasePermission):
    """Только шеф или программист."""
    message = "Доступно только шефу."

    def has_permission(self, request, view):
        user = _get_user(request)
        return bool(user and user.is_chef)


class CanManageStopList(BasePermission):
    """Стоп-лист: повар, админ, шеф, программист. Официант — нет."""
    message = "Стоп-лист доступен кухне и администрации."

    def has_permission(self, request, view):
        user = _get_user(request)
        return bool(user and (user.is_cafe_admin or user.is_cook))

class IsWaiterOrAdmin(BasePermission):
    """Официант, админ, шеф или программист (вызовы со столов, закрытие стола)."""
    message = "Доступно официантам и администрации."

    def has_permission(self, request, view):
        user = _get_user(request)
        return bool(user and (user.is_cafe_admin or user.is_waiter))