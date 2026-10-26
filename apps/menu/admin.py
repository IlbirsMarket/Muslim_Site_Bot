"""Меню в админке Django."""

from django.contrib import admin                       # админка Django

from .models import Category, Dish, DishSize, Extra   # наши модели


class DishSizeInline(admin.TabularInline):
    """Размеры редактируются прямо на странице блюда, таблицей."""
    model = DishSize   # какая модель
    extra = 1          # одна пустая строка для нового размера


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "position", "is_active")   # колонки списка
    list_editable = ("position", "is_active")          # можно менять прямо в списке


@admin.register(Extra)
class ExtraAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "is_available")
    list_editable = ("price", "is_available")


@admin.register(Dish)
class DishAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price", "is_available", "is_active", "position")
    list_filter = ("category", "is_available", "is_active")   # фильтры справа
    list_editable = ("is_available", "is_active", "position")  # стоп-лист одним кликом
    search_fields = ("name",)                                   # поиск по названию
    filter_horizontal = ("extras",)                             # удобный выбор добавок
    inlines = [DishSizeInline]                                  # размеры на странице блюда