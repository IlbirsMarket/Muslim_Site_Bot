"""Филиалы и их настройки в админке Django."""

from django.contrib import admin   # админка Django

from .models import Branch, CafeSettings


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    """Филиалы: название, порядок, работает ли. Удалять нельзя — к филиалу привязаны заказы и отчёты."""
    list_display = ["name", "position", "is_active"]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CafeSettings)
class CafeSettingsAdmin(admin.ModelAdmin):
    """Настройки филиалов: по одной строке на филиал."""
    list_display = ["branch", "opens_at", "closes_at", "is_accepting_orders"]

    def has_add_permission(self, request):
        """Добавить можно, только если у какого-то филиала ещё нет настроек."""
        return Branch.objects.filter(settings__isnull=True).exists()

    def has_delete_permission(self, request, obj=None):
        """Удалять настройки нельзя."""
        return False
