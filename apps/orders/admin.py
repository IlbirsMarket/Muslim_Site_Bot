"""Заказы в админке Django."""

from django.contrib import admin   # админка Django

from .models import Order, OrderItem, OrderStatusLog, TableCall, TableVisit


class OrderItemInline(admin.TabularInline):
    """Позиции внутри страницы заказа (только просмотр)."""
    model = OrderItem
    extra = 0                                        # без пустых строк
    readonly_fields = ("dish_name", "size_name", "extras", "unit_price", "quantity")
    can_delete = False


class OrderStatusLogInline(admin.TabularInline):
    """История статусов внутри страницы заказа (только просмотр)."""
    model = OrderStatusLog
    extra = 0
    readonly_fields = ("status", "changed_by", "created_at")
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "table", "status", "total", "created_at")   # колонки
    list_filter = ("kind", "status", "source", "created_at")                  # фильтры
    search_fields = ("id", "phone", "customer_name")                          # поиск
    readonly_fields = ("public_id", "subtotal", "delivery_fee", "total", "created_at", "updated_at")
    inlines = [OrderItemInline, OrderStatusLogInline]


@admin.register(TableCall)
class TableCallAdmin(admin.ModelAdmin):
    list_display = ("table", "kind", "is_done", "created_at")
    list_filter = ("kind", "is_done")


@admin.register(TableVisit)
class TableVisitAdmin(admin.ModelAdmin):
    list_display = ("table", "device_key", "confirmed_by", "started_at", "closed_at")
    list_filter = ("table",)