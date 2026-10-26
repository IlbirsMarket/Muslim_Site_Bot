"""Обработчики запросов для столов."""

from django.http import HttpResponse                   # ответ с картинкой (не JSON)
from django.shortcuts import get_object_or_404         # найти запись или вернуть ошибку 404
from rest_framework import generics, viewsets          # готовые views и наборы CRUD
from rest_framework.decorators import action           # дополнительные адреса во ViewSet
from rest_framework.permissions import AllowAny        # доступ для всех
from rest_framework.response import Response           # ответ в JSON
from drf_spectacular.utils import OpenApiTypes, extend_schema  # описание ответов для Swagger
from django.db.models import Count, Q                  # подсчёт заказов с условием


from apps.orders.models import Order                   # чтобы посчитать активные заказы
from .services import build_qr_png, build_qr_sheet_pdf  # (замени старую строку импорта services)
from core.permissions import IsCafeAdmin               # право: админ и выше
from .models import Table
from .serializers import TableAdminSerializer, TablePublicSerializer
from .services import build_qr_png                     # создание картинки QR


class PublicTableView(generics.RetrieveAPIView):
    """GET /api/tables/{token}/ — гость отсканировал QR, фронт узнаёт, что это за стол."""

    serializer_class = TablePublicSerializer
    permission_classes = [AllowAny]    # вход не нужен

    def get_object(self):
        # Ищем активный стол с таким токеном. Нет такого — ошибка 404 ("QR недействителен")
        return get_object_or_404(Table, token=self.kwargs["token"], is_active=True)


class TableAdminViewSet(viewsets.ModelViewSet):
    """/api/admin/tables/ — список, создание, изменение, удаление столов."""

    # Каждый стол сразу со счётчиком незакрытых заказов
    queryset = Table.objects.annotate(
           active_orders=Count(
               "orders",
               filter=Q(orders__status__in=[
                   Order.Status.NEW, Order.Status.ACCEPTED, Order.Status.COOKING,
                   Order.Status.READY, Order.Status.ON_THE_WAY,
               ]),
           )
       )
    serializer_class = TableAdminSerializer
    permission_classes = [IsCafeAdmin]

    @action(detail=True, methods=["post"], url_path="regenerate-qr")
    def regenerate_qr(self, request, pk=None):
        """POST /api/admin/tables/{id}/regenerate-qr/ — перевыпустить QR (старый перестанет работать)."""
        table = self.get_object()                 # находим стол
        table.regenerate_token()                  # новый токен
        return Response(self.get_serializer(table).data)  # возвращаем стол с новым токеном и адресом

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})  # для Swagger: ответ — PNG-картинка
    @action(detail=True, methods=["get"], url_path="qr")
    def qr(self, request, pk=None):
        """GET /api/admin/tables/{id}/qr/ — скачать картинку QR-кода (PNG)."""
        table = self.get_object()                 # находим стол
        png = build_qr_png(table.qr_url)          # рисуем QR с адресом стола
        filename = f"qr-{table.kind}-{table.number or 'delivery'}.png"   # имя файла: qr-hall-7.png
        response = HttpResponse(png, content_type="image/png")            # отдаём как картинку
        response["Content-Disposition"] = f'attachment; filename="{filename}"'  # браузер скачает файл
        return response

    @extend_schema(responses={(200, "application/pdf"): OpenApiTypes.BINARY})
    @action(detail=False, methods=["get"], url_path="qr-pdf")
    def qr_pdf(self, request):
           """GET /api/admin/tables/qr-pdf/ — все активные QR одним PDF для печати."""
           tables = Table.objects.filter(is_active=True)                    # только активные столы
           response = HttpResponse(build_qr_sheet_pdf(tables), content_type="application/pdf")
           response["Content-Disposition"] = 'attachment; filename="qr-codes.pdf"'
           return response