"""Обработчики запросов для сотрудников: заказы, вызовы, закрытие стола."""

from datetime import timedelta                               # промежуток времени

from django.db.models import Q                               # «или» в фильтре
from django.shortcuts import get_object_or_404               # найти запись или 404
from django.utils import timezone                            # текущее время
from drf_spectacular.utils import OpenApiParameter, extend_schema  # описание для Swagger
from rest_framework import viewsets                          # наборы views
from rest_framework.decorators import action                 # свои адреса во ViewSet
from rest_framework.response import Response                 # ответ в JSON
from rest_framework.views import APIView                     # простой view
from datetime import date                                      # проверка формата даты
from rest_framework.exceptions import PermissionDenied, ValidationError   # ответ 403 и 400

from django.db import transaction                            # «всё или ничего»
from apps.bot.events import Kind as BotKind, add_event       # «почтовый ящик» для Telegram-бота
from apps.tables.models import Table
from core.branches import staff_branch                       # текущий филиал запроса
from core.permissions import CanTakePayment, IsCashierOrAdmin, IsStaffMember, IsWaiterOrAdmin
from .models import Order, TableCall
from .staff_serializers import OrderStaffSerializer, StatusChangeSerializer, TableCallStaffSerializer
from .status_service import owns_table, change_status, claim_order, close_visits
from core.pagination import OptionalPageNumberPagination   # страницы по запросу

KITCHEN_STATUSES = [Order.Status.ACCEPTED, Order.Status.COOKING, Order.Status.READY]   # что видит повар
COURIER_STATUSES = KITCHEN_STATUSES + [Order.Status.ON_THE_WAY, Order.Status.COMPLETED, Order.Status.CANCELLED]   # курьер: доставки после подтверждения
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
        if getattr(self, "swagger_fake_view", False):     # Swagger строит документацию без пользователя
            return Order.objects.none()
        user = self.request.user
        queryset = Order.objects.filter(branch=staff_branch(self.request)).select_related(   # только свой филиал
            "table", "claimed_by", "accepted_by",
        ).prefetch_related(
            "items", "status_logs__changed_by",          # всё нужное одним махом
        )
        if user.is_cafe_admin or user.is_cashier:         # админ, кассир и выше — все заказы
            pass
        elif user.is_waiter:                              # официант — только зал
            queryset = queryset.filter(                   # заказы со столов + свои «С собой» из «Заказа за гостя»
                Q(table__kind=Table.Kind.HALL) | Q(table__isnull=True, kind=Order.Kind.TAKEAWAY, claimed_by=user))
        elif user.is_cook:                                # повар — только подтверждённые
            queryset = queryset.filter(status__in=KITCHEN_STATUSES)
        elif user.is_courier:                             # курьер — только доставки, уже подтверждённые админом
            queryset = queryset.filter(kind=Order.Kind.DELIVERY, status__in=COURIER_STATUSES)
        else:
            return queryset.none()                        # на всякий случай: ничего

        if self.request.query_params.get("active") in ("1", "true"):   # ?active=true
            queryset = queryset.exclude(status__in=FINISHED_STATUSES)  # убираем завершённые и отменённые

        day = self.request.query_params.get("date")                # ?date=2026-10-26
        if day:
            try:
                day = date.fromisoformat(day)                      # проверяем формат
            except ValueError:
                raise ValidationError({"date": "Формат даты: ГГГГ-ММ-ДД, например 2026-10-26."})
            queryset = queryset.filter(created_at__date=day)       # заказы за этот день    # заказы за этот день

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
        return TableCall.objects.select_related("table").filter(
            is_done=False, created_at__gte=since, table__branch=staff_branch(self.request),   # вызовы своего филиала
        )

    @extend_schema(request=None, responses=TableCallStaffSerializer)
    @action(detail=True, methods=["post"])
    def done(self, request, pk=None):
        """POST /api/staff/table-calls/{id}/done/ — официант подошёл, вызов выполнен."""
        call = self.get_object()
        if not owns_table(request.user, call.table):                 # стол ведёт другой официант
            raise PermissionDenied("Этот стол ведёт другой официант.")
        if not call.is_done:                                         # повторное «Выполнено» ничего не меняет
            with transaction.atomic():                               # отметка и событие для бота — вместе
                call.is_done = True                                  # отмечаем выполненным
                call.done_by = request.user                          # кто подошёл
                call.done_at = timezone.now()                        # когда
                call.save(update_fields=["is_done", "done_by", "done_at"])
                add_event(BotKind.CALL_DONE, call=call, user_id=request.user.id)   # бот отметит вызов в «Зал»
        return Response(self.get_serializer(call).data)


class CloseTableVisitView(APIView):
    """POST /api/staff/tables/{table_id}/close-visit/ — гости ушли: телефоны за столом больше не доверенные."""

    permission_classes = [IsWaiterOrAdmin]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request, table_id):
        table = get_object_or_404(Table, pk=table_id, branch=staff_branch(request))   # стол своего филиала
        if not owns_table(request.user, table):                       # освобождает тот, кто ведёт стол (или админ)
            raise PermissionDenied("Этот стол ведёт другой официант.")
        closed = close_visits(table, request.user)                   # закрываем визиты
        return Response({"table": table.name, "closed_visits": closed})


# ===================== ОПЛАТА И ЧЕКИ =====================

class BillListView(APIView):
    """GET /api/staff/bills/ — «К оплате»: неоплаченные счета (заказы одного стола — один счёт)."""

    permission_classes = [CanTakePayment]

    @extend_schema(responses={200: dict})
    def get(self, request):
        from .billing import bills
        return Response(bills(staff_branch(request), request.user))


class BillPreviewView(APIView):
    """POST /api/staff/bills/preview/ {"orders": [1, 2]} — счёт для просмотра в панели (ничего не печатает)."""

    permission_classes = [CanTakePayment]

    @extend_schema(request=dict, responses={200: dict})
    def post(self, request):
        from .billing import preview_bill
        return Response(preview_bill(staff_branch(request), request.user, request.data.get("orders")))


class BillPrintView(APIView):
    """POST /api/staff/bills/print/ {"orders": [1, 2]} — напечатать счёт без оплаты."""

    permission_classes = [CanTakePayment]

    @extend_schema(request=dict, responses={200: dict})
    def post(self, request):
        from .billing import print_bill
        print_bill(staff_branch(request), request.user, request.data.get("orders"))
        return Response({"ok": True})


class BillPayView(APIView):
    """
    POST /api/staff/bills/pay/ — «Оплачено».
    {"orders": [1, 2], "method": "cash|card|mixed", "cash": 1000 (для mixed), "received": 2000 (сколько дал гость)}
    """

    permission_classes = [CanTakePayment]

    @extend_schema(request=dict, responses={200: dict})
    def post(self, request):
        from .billing import pay

        def number(name):                                            # число или пусто
            value = request.data.get(name)
            if value in (None, ""):
                return None
            try:
                return max(0, int(value))
            except (TypeError, ValueError):
                raise ValidationError({name: "Нужно число."})

        result = pay(staff_branch(request), request.user, request.data.get("orders"),
                     request.data.get("method", ""), number("cash"), number("received"))
        return Response(result)


class PrintJobClaimView(APIView):
    """POST /api/staff/print-jobs/claim/ — кассовый компьютер забирает чеки на печать (каждый — один раз)."""

    permission_classes = [CanTakePayment]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        from .billing import claim_jobs
        from .models import PrintJob
        kinds = [k for k in (request.data.get("kinds") or []) if k in PrintJob.Kind.values]   # какие чеки печатает этот компьютер
        return Response(claim_jobs(staff_branch(request), kinds or None))


class OrderReprintView(APIView):
    """POST /api/staff/orders/{id}/print/ — ещё раз напечатать чек «ЗАКАЗ»."""

    permission_classes = [CanTakePayment]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request, pk):
        from .billing import print_order
        order = get_object_or_404(Order, pk=pk, branch=staff_branch(request))
        print_order(order)
        return Response({"ok": True})


# ===================== КАССА (смена) =====================

def _int(request, name, required=False):
    """Число из тела запроса (или None)."""
    value = request.data.get(name)
    if value in (None, ""):
        if required:
            raise ValidationError({name: "Укажите сумму."})
        return None
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        raise ValidationError({name: "Нужно число."})


class CashView(APIView):
    """GET /api/staff/cash/ — открытая смена филиала и её цифры ({"shift": null} — смены нет)."""

    permission_classes = [IsCashierOrAdmin]

    @extend_schema(responses={200: dict})
    def get(self, request):
        from .cash import current_shift, history, past_shifts, shift_data
        branch = staff_branch(request)
        shift = current_shift(branch)
        return Response({**shift_data(shift), "history": history(branch, shift), "past_shifts": past_shifts(branch)})   # смена, оплаты, прошлые смены


class CashOpenView(APIView):
    """POST /api/staff/cash/open/ {"cash": 2000} — открыть смену."""

    permission_classes = [IsCashierOrAdmin]

    @extend_schema(request=dict, responses={200: dict})
    def post(self, request):
        from .cash import open_shift, shift_data
        return Response(shift_data(open_shift(staff_branch(request), request.user, _int(request, "cash"))))


class CashMoveView(APIView):
    """POST /api/staff/cash/move/ {"kind": "in|out", "amount": 1000, "comment": ""} — внесение / изъятие."""

    permission_classes = [IsCashierOrAdmin]

    @extend_schema(request=dict, responses={200: dict})
    def post(self, request):
        from .cash import current_shift, move, shift_data
        branch = staff_branch(request)
        move(branch, request.user, request.data.get("kind"), _int(request, "amount", True), request.data.get("comment", ""))
        return Response(shift_data(current_shift(branch)))


class CashCloseView(APIView):
    """POST /api/staff/cash/close/ {"counted": 19350} — закрыть смену и напечатать отчёт."""

    permission_classes = [IsCashierOrAdmin]

    @extend_schema(request=dict, responses={200: dict})
    def post(self, request):
        from .cash import close_shift
        return Response(close_shift(staff_branch(request), request.user, _int(request, "counted", True)))


class ShiftCopyView(APIView):
    """POST /api/staff/cash/shift-copy/ {"id": 5} — копия отчёта закрытой смены на чековый аппарат."""

    permission_classes = [IsCashierOrAdmin]

    @extend_schema(request=dict, responses={200: dict})
    def post(self, request):
        from .cash import shift_copy
        shift_copy(staff_branch(request), request.data.get("id"))
        return Response({"ok": True})


class ReceiptCopyView(APIView):
    """POST /api/staff/cash/receipt-copy/ {"orders": [1, 2]} — копия чека об оплате из «Истории оплат»."""

    permission_classes = [CanTakePayment]

    @extend_schema(request=dict, responses={200: dict})
    def post(self, request):
        from .billing import receipt_copy
        receipt_copy(staff_branch(request), request.data.get("orders"))
        return Response({"ok": True})


class OrderTicketView(APIView):
    """GET /api/staff/orders/{id}/ticket/ — чек «ЗАКАЗ» этого заказа (посмотреть в панели перед печатью)."""

    permission_classes = [IsStaffMember]

    @extend_schema(responses={200: dict})
    def get(self, request, pk):
        from .billing import order_payload
        order = get_object_or_404(Order.objects.select_related("table", "branch", "claimed_by", "accepted_by"),
                                  pk=pk, branch=staff_branch(request))
        return Response({"kind": "order", "payload": order_payload(order)})


# ===================== «ЗАКАЗ ЗА ГОСТЯ» (как в 1С) =====================

class QuickOrderView(APIView):
    """
    GET  /api/staff/quick-order/ — столы зала (свободен / занят / просят счёт) и меню без фото — одним запросом.
    POST /api/staff/quick-order/ {"table": id или null («С собой»), "items": [...], "comment": ""} — заказ сразу «Принят»,
         чек уходит на кухню. Могут: официант, админ, кассир (и шеф, программист).
    """
    permission_classes = [IsWaiterOrAdmin]

    @extend_schema(responses={200: dict})
    def get(self, request):
        from . import quick_order
        branch = staff_branch(request)
        return Response({"tables": quick_order.tables(branch), "menu": quick_order.menu(branch)})

    @extend_schema(request=dict, responses={201: OrderStaffSerializer})
    def post(self, request):
        from . import quick_order
        data = request.data if isinstance(request.data, dict) else {}
        items = data.get("items") if isinstance(data.get("items"), list) else []
        order = quick_order.create(request.user, staff_branch(request), data.get("table"), items, str(data.get("comment") or ""))
        return Response(OrderStaffSerializer(order, context={"request": request}).data, status=201)
