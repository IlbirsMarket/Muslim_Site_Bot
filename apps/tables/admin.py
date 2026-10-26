"""Столы в админке Django."""

from django.contrib import admin   # админка Django

from .models import Table          # модель стола


@admin.register(Table)
class TableAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "number", "token", "is_active")   # колонки
    list_filter = ("kind", "is_active")                               # фильтры
    readonly_fields = ("token", "created_at")                         # показываем, но не даём менять
    actions = ["regenerate_qr"]                                       # своё действие над выбранными столами

    @admin.action(description="Перевыпустить QR у выбранных столов")
    def regenerate_qr(self, request, queryset):
        """Действие в админке: выделил столы галочками → новые токены."""
        for table in queryset:              # для каждого выбранного стола
            table.regenerate_token()        # новый токен
        self.message_user(request, f"QR перевыпущен у {queryset.count()} стол(ов).")  # сообщение вверху страницы