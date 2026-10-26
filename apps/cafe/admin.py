"""Настройки кафе в админке Django."""

from django.contrib import admin   # админка Django

from .models import CafeSettings


@admin.register(CafeSettings)
class CafeSettingsAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        """Кнопка «Добавить» есть, только пока записи ещё нет."""
        return not CafeSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """Удалять настройки нельзя."""
        return False