from django.contrib import admin                                  # админка Django
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin  # готовая страница пользователей

from .models import RoleChangeLog, User # наша модель


@admin.register(User)  # регистрируем модель в админке
class UserAdmin(BaseUserAdmin):
    # Колонки в списке пользователей
    list_display = ("username", "first_name", "role", "telegram_id", "phone", "is_active")
    # Фильтры справа
    list_filter = ("role", "is_active")
    # Поиск по этим полям
    search_fields = ("username", "first_name", "telegram_id", "phone")

    # Поля на странице редактирования сотрудника: стандартные + наш блок
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Роль и контакты", {"fields": ("role", "telegram_id", "phone")}),
    )

    # Поля на странице "Добавить сотрудника": логин, пароль и сразу роль
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Роль и контакты", {"fields": ("role", "first_name", "phone", "telegram_id")}),
    )

@admin.register(RoleChangeLog)
class RoleChangeLogAdmin(admin.ModelAdmin):
    list_display = ("user", "old_role", "new_role", "changed_by", "created_at")
    list_filter = ("new_role",)
    readonly_fields = ("user", "changed_by", "old_role", "new_role", "created_at")   # журнал не редактируется