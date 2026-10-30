"""Филиалы и их настройки в админке Django."""

from django.contrib import admin   # админка Django

from .models import Branch, CafeSettings


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    """Филиалы: название, порядок, работает ли. Удалять нельзя — к филиалу привязаны заказы и отчёты."""
    list_display = ["name", "position", "is_active", "tg_group_id"]
    fieldsets = [
        (None, {"fields": ["name", "position", "is_active"]}),
        ("Telegram-группа филиала (ID — командой /ids в группе и в каждой теме)", {"fields": [
            "tg_group_id", "tg_topic_admins", "tg_topic_kitchen", "tg_topic_hall", "tg_topic_delivery", "tg_topic_reports",
        ]}),
    ]

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
