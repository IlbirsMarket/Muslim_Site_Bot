"""Адреса отчётов."""

from django.urls import path   # описание адресов

from .views import (
    DayReportPdfView,
    DayReportView,
    PeriodArchivePdfView,
    PeriodArchiveView,
    PeriodReportPdfView,
    PeriodReportView,
)

urlpatterns = [
    path("admin/reports/day/", DayReportView.as_view(), name="report-day"),                       # отчёт за день
    path("admin/reports/day/pdf/", DayReportPdfView.as_view(), name="report-day-pdf"),            # PDF за день
    path("admin/reports/period/", PeriodReportView.as_view(), name="report-period"),              # текущие 45 дней
    path("admin/reports/period/pdf/", PeriodReportPdfView.as_view(), name="report-period-pdf"),   # PDF текущего периода
    path("admin/reports/periods/", PeriodArchiveView.as_view(), name="report-archive"),           # архив
    path("admin/reports/periods/<int:pk>/pdf/", PeriodArchivePdfView.as_view(), name="report-archive-pdf"),  # PDF из архива
]