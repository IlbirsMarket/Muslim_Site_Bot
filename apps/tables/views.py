"""Обработчики запросов для столов."""

from django.http import HttpResponse                   # ответ с картинкой (не JSON)
from django.shortcuts import get_object_or_404         # найти запись или вернуть ошибку 404
from rest_framework import generics, viewsets          # готовые views и наборы CRUD
from rest_framework.exceptions import ValidationError  # ошибка 400 с понятным текстом
from rest_framework.decorators import action           # дополнительные адреса во ViewSet
from rest_framework.permissions import AllowAny        # доступ для всех
from rest_framework.response import Response           # ответ в JSON
from drf_spectacular.utils import OpenApiTypes, extend_schema  # описание ответов для Swagger
from django.db.models import Count, Q                  # подсчёт заказов с условием


from apps.orders.models import Order                   # чтобы посчитать активные заказы
from .services import build_qr_png, build_qr_sheet_pdf  # (замени старую строку импорта services)
from core.permissions import IsCafeAdmin, IsWaiterOrAdmin   # права: админ и выше / официант и выше
from .models import Table
from .serializers import StaffTableSerializer, TableAdminSerializer, TablePublicSerializer


class PublicTableView(generics.RetrieveAPIView):
    """GET /api/tables/{token}/ — гость отсканировал QR, фронт узнаёт, что это за стол."""

    serializer_class = TablePublicSerializer
    permission_classes = [AllowAny]    # вход не нужен

    def get_object(self):
        # Ищем активный стол с таким токеном. Нет такого — ошибка 404 ("QR недействителен")
        return get_object_or_404(Table, token=self.kwargs["token"], is_active=True)


# Какие заказы считаются «ещё в работе»
ACTIVE_STATUSES = [
    Order.Status.NEW, Order.Status.ACCEPTED, Order.Status.COOKING,
    Order.Status.READY, Order.Status.ON_THE_WAY,
]


def with_active_orders(queryset):
    """Добавляет к каждому столу счётчик незакрытых заказов (active_orders)."""
    return queryset.annotate(active_orders=Count("orders", filter=Q(orders__status__in=ACTIVE_STATUSES)))


class TableAdminViewSet(viewsets.ModelViewSet):
    """/api/admin/tables/ — список, создание, изменение, удаление столов."""

    queryset = with_active_orders(Table.objects.filter(is_active=True))   # каждый стол сразу со счётчиком незакрытых заказов
    serializer_class = TableAdminSerializer
    permission_classes = [IsCafeAdmin]

    def list(self, request, *args, **kwargs):
        """GET: доставка должна быть всегда — если её нет, создаём перед показом списка."""
        Table.delivery_point()
        return super().list(request, *args, **kwargs)

    def perform_destroy(self, instance):
        """Удалить можно только свободный стол без заказов в работе. Доставку — никогда."""
        if instance.kind == Table.Kind.DELIVERY:
            raise ValidationError("Доставку удалить нельзя — она нужна всегда.")
        if instance.occupied_since:
            raise ValidationError(f"{instance.name} сейчас занят. Сначала освободите стол.")
        if instance.orders.filter(status__in=ACTIVE_STATUSES).exists():
            raise ValidationError(f"У стола «{instance.name}» есть заказы в работе. Сначала завершите их.")
        instance.delete()

    @action(detail=True, methods=["post"], url_path="regenerate-qr")
    def regenerate_qr(self, request, pk=None):
        """POST /api/admin/tables/{id}/regenerate-qr/ — перевыпустить QR (старый перестанет работать)."""
        table = self.get_object()                 # находим стол
        if table.kind == Table.Kind.DELIVERY:     # QR доставки — это главная страница сайта, менять нечего
            raise ValidationError("QR доставки ведёт на главную страницу сайта — обновлять его не нужно.")
        table.regenerate_token()                  # новый токен
        return Response(self.get_serializer(table).data)  # возвращаем стол с новым токеном и адресом

    @extend_schema(responses={(200, "image/png"): OpenApiTypes.BINARY})  # для Swagger: ответ — PNG-картинка
    @action(detail=True, methods=["get"], url_path="qr")
    def qr(self, request, pk=None):
        """GET /api/admin/tables/{id}/qr/ — скачать картинку QR-кода (PNG)."""
        table = self.get_object()                 # находим стол
        png = build_qr_png(table.qr_url)          # рисуем QR с адресом стола
        filename = "qr-delivery.png" if table.kind == Table.Kind.DELIVERY else f"qr-table-{table.number}.png"
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


class StaffTableListView(generics.ListAPIView):
    """GET /api/staff/tables/ — столы в зале для официанта: кто занят, с какого времени, сколько заказов в работе."""

    serializer_class = StaffTableSerializer
    permission_classes = [IsWaiterOrAdmin]
    pagination_class = None                                   # столов немного — отдаём все сразу

    def get_queryset(self):
        return with_active_orders(Table.objects.filter(kind=Table.Kind.HALL, is_active=True))