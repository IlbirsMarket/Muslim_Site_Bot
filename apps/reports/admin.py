"""Периоды отчётов в админке Django."""

from django.contrib import admin   # админка Django

from .models import ReportPeriod


@admin.register(ReportPeriod)
class ReportPeriodAdmin(admin.ModelAdmin):
    list_display = ("start_date", "end_date", "is_closed", "revenue", "orders_count", "pdf")
    list_filter = ("is_closed",)
    readonly_fields = ("closed_at", "revenue", "orders_count", "pdf")   # итоги считает система