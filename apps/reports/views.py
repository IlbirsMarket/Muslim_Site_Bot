"""Обработчики запросов отчётов."""

from datetime import date                                         # дата

from django.http import FileResponse, HttpResponse                # ответы с файлами
from django.shortcuts import get_object_or_404                    # найти запись или 404
from django.utils import timezone                                 # сегодняшняя дата
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema  # описание для Swagger
from rest_framework.exceptions import ValidationError             # ошибка 400
from rest_framework.response import Response                      # ответ в JSON
from rest_framework.views import APIView                          # простой view

from core.permissions import IsCafeAdmin, IsChef
from .builder import build_day_report, build_period_report
from .models import ReportPeriod
from .pdf import render_day_pdf, render_period_pdf
from .periods import get_current_period

DATE_PARAM = OpenApiParameter("date", OpenApiTypes.DATE, description="Дата в формате 2026-10-26. Без неё — сегодня.")
PDF_RESPONSE = {(200, "application/pdf"): OpenApiTypes.BINARY}


def _parse_date(value):
    """Строка '2026-10-26' → дата. Пусто — сегодня."""
    if not value:
        return timezone.localdate()
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValidationError({"date": "Формат даты: ГГГГ-ММ-ДД, например 2026-10-26."})


def _pdf_response(content: bytes, filename: str) -> HttpResponse:
    """Отдать PDF на скачивание."""
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class DayReportView(APIView):
    """GET /api/admin/reports/day/?date=2026-10-26 — отчёт за день."""
    permission_classes = [IsCafeAdmin]

    @extend_schema(parameters=[DATE_PARAM], responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(build_day_report(_parse_date(request.query_params.get("date"))))


class DayReportPdfView(APIView):
    """GET /api/admin/reports/day/pdf/?date=2026-10-26 — отчёт за день в PDF."""
    permission_classes = [IsCafeAdmin]

    @extend_schema(parameters=[DATE_PARAM], responses=PDF_RESPONSE)
    def get(self, request):
        day = _parse_date(request.query_params.get("date"))
        return _pdf_response(render_day_pdf(build_day_report(day)), f"report-{day:%Y%m%d}.pdf")


class PeriodReportView(APIView):
    """GET /api/admin/reports/period/ — текущий период 45 дней."""
    permission_classes = [IsChef]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response(build_period_report(get_current_period()))


class PeriodReportPdfView(APIView):
    """GET /api/admin/reports/period/pdf/ — текущий период в PDF."""
    permission_classes = [IsChef]

    @extend_schema(responses=PDF_RESPONSE)
    def get(self, request):
        period = get_current_period()
        return _pdf_response(render_period_pdf(build_period_report(period)), f"period-{period.start_date:%Y%m%d}.pdf")


class PeriodArchiveView(APIView):
    """GET /api/admin/reports/periods/ — архив закрытых периодов."""
    permission_classes = [IsChef]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        get_current_period()                                   # заодно закрываем период, если 45 дней уже прошли
        periods = ReportPeriod.objects.filter(is_closed=True)
        return Response([
            {
                "id": p.id,
                "start_date": p.start_date,
                "end_date": p.end_date,
                "revenue": p.revenue,
                "orders_count": p.orders_count,
                "has_pdf": bool(p.pdf),
            }
            for p in periods
        ])


class PeriodArchivePdfView(APIView):
    """GET /api/admin/reports/periods/{id}/pdf/ — скачать PDF закрытого периода."""
    permission_classes = [IsChef]

    @extend_schema(responses=PDF_RESPONSE)
    def get(self, request, pk):
        period = get_object_or_404(ReportPeriod, pk=pk, is_closed=True)
        if not period.pdf:
            raise ValidationError("Для этого периода нет PDF.")
        return FileResponse(period.pdf.open("rb"), as_attachment=True, filename=f"period-{period.start_date:%Y%m%d}.pdf")