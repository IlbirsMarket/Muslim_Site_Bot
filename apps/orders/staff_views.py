"""Обработчики запросов для сотрудников: заказы, вызовы, закрытие стола."""

from datetime import timedelta                               # промежуток времени

from django.shortcuts import get_object_or_404               # найти запись или 404
from django.utils import timezone                            # текущее время
from drf_spectacular.utils import OpenApiParameter, extend_schema  # описание для Swagger
from rest_framework import viewsets                          # наборы views
from rest_framework.decorators import action                 # свои адреса во ViewSet
from rest_framework.response import Response                 # ответ в JSON
from rest_framework.views import APIView                     # простой view

from apps.tables.models import Table
from core.permissions import IsStaffMember, IsWaiterOrAdmin
from .models import Order, TableCall
from .staff_serializers import OrderStaffSerializer, StatusChangeSerializer, TableCallStaffSerializer
from .status_service import change_status, claim_order, close_visits
from core.pagination import OptionalPageNumberPagination   # страницы по запросу

KITCHEN_STATUSES = [Order.Status.ACCEPTED, Order.Status.COOKING, Order.Status.READY]   # что видит повар
FINISHED_STATUSES = [Order.Status.COMPLETED, Order.Status.CANCELLED]                    # закрытые заказы


@extend_schema(parameters=[
       OpenApiParameter("active", bool, description="true — только незакрытые заказы"),
       OpenApiParameter("date", str, description="Заказы за день: 2026-10-26"),
       OpenApiParameter("page", int, description="Номер страницы (по 30). Без него — весь список"),
   ])
class StaffOrderViewSet(viewsets.ReadOnlyModelViewSet):
    """
    /api/staff/orders/ — заказы для сотрудников.
    Фильтры: ?active=true, ?status=new, ?kind=hall, ?table=3
    """

    serializer_class = OrderStaffSerializer
    permission_classes = [IsStaffMember]
    filterset_fields = ["status", "kind", "table"]
    pagination_class = OptionalPageNumberPagination   # ?page=1 — история по 30 заказов

    def get_queryset(self):
        user = self.request.user
        queryset = Order.objects.select_related("table", "claimed_by", "accepted_by").prefetch_related(
            "items", "status_logs__changed_by",          # всё нужное одним махом
        )
        if user.is_cafe_admin:                            # админ и выше — все заказы
            pass
        elif user.is_waiter:                              # официант — только зал
            queryset = queryset.filter(kind=Order.Kind.HALL)
        elif user.is_cook:                                # повар — только подтверждённые
            queryset = queryset.filter(status__in=KITCHEN_STATUSES)
        else:
            return queryset.none()                        # на всякий случай: ничего

        if self.request.query_params.get("active") in ("1", "true"):   # ?active=true
            queryset = queryset.exclude(status__in=FINISHED_STATUSES)  # убираем завершённые и отменённые

        day = self.request.query_params.get("date")                # ?date=2026-10-26
        if day:
            queryset = queryset.filter(created_at__date=day)       # заказы за этот день

        return queryset

    @extend_schema(request=None, responses=OrderStaffSerializer)
    @action(detail=True, methods=["post"])
    def claim(self, request, pk=None):
        """POST /api/staff/orders/{id}/claim/ — «Беру стол»."""
        order = claim_order(self.get_object(), request.user)
        return Response(self.get_serializer(order).data)

    @extend_schema(request=StatusChangeSerializer, responses=OrderStaffSerializer)
    @action(detail=True, methods=["post"], url_path="status")
    def change(self, request, pk=None):
        """POST /api/staff/orders/{id}/status/ — сменить статус: {"action": "accept", "reason": ""}."""
        body = StatusChangeSerializer(data=request.data)          # проверяем тело запроса
        body.is_valid(raise_exception=True)
        order = change_status(
            self.get_object(), body.validated_data["action"], request.user, body.validated_data.get("reason", ""),
        )
        return Response(self.get_serializer(order).data)


class StaffTableCallViewSet(viewsets.ReadOnlyModelViewSet):
    """/api/staff/table-calls/ — активные вызовы со столов за последние 3 часа."""

    serializer_class = TableCallStaffSerializer
    permission_classes = [IsWaiterOrAdmin]

    def get_queryset(self):
        since = timezone.now() - timedelta(hours=3)                  # старые вызовы не показываем
        return TableCall.objects.select_related("table").filter(is_done=False, created_at__gte=since)

    @extend_schema(request=None, responses=TableCallStaffSerializer)
    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        """POST /api/staff/table-calls/{id}/done/ — официант подошёл, вызов выполнен."""
        call = self.get_object()
        call.is_done = True                                          # отмечаем выполненным
        call.done_by = request.user                                  # кто подошёл
        call.done_at = timezone.now()                                # когда
        call.save(update_fields=["is_done", "done_by", "done_at"])
        return Response(self.get_serializer(call).data)


class CloseTableVisitView(APIView):
    """POST /api/staff/tables/{table_id}/close-visit/ — гости ушли: телефоны за столом больше не доверенные."""

    permission_classes = [IsWaiterOrAdmin]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request, table_id):
        table = get_object_or_404(Table, pk=table_id)               # находим стол
        closed = close_visits(table, request.user)                   # закрываем визиты
        return Response({"table": table.name, "closed_visits": closed})