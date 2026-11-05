"""Адреса заказов: для гостей и для сотрудников."""

from django.urls import path                       # описание адресов
from rest_framework.routers import DefaultRouter   # автоматические адреса для ViewSet

from .staff_views import (
    BillListView, BillPayView, BillPrintView, CashCloseView, CashMoveView, CashOpenView, CashView, CloseTableVisitView, OrderTicketView, ReceiptCopyView, OrderReprintView, PrintJobClaimView,
    StaffOrderViewSet, StaffTableCallViewSet,
)
from .views import ChangesVersionView, OrderCreateView, OrderPublicDetailView, TableCallCreateView, TelegramGuestContactView

router = DefaultRouter()
router.register("staff/orders", StaffOrderViewSet, basename="staff-orders")             # /api/staff/orders/
router.register("staff/table-calls", StaffTableCallViewSet, basename="staff-calls")     # /api/staff/table-calls/

urlpatterns = [
    # ----- Гости -----
    path("orders/", OrderCreateView.as_view(), name="order-create"),                           # POST новый заказ
    path("orders/<uuid:public_id>/", OrderPublicDetailView.as_view(), name="order-public"),    # GET статус заказа
    path("table-calls/", TableCallCreateView.as_view(), name="table-call-create"),             # POST вызов официанта / счёта
    path("version/", ChangesVersionView.as_view(), name="changes-version"),                    # GET номер последнего изменения
    path("telegram/guest/", TelegramGuestContactView.as_view(), name="telegram-guest"),        # POST мини-приложение: имя и телефон из прошлого заказа
    # ----- Сотрудники -----
    path("staff/bills/", BillListView.as_view(), name="bills"),                                  # GET «К оплате»
    path("staff/bills/print/", BillPrintView.as_view(), name="bill-print"),                      # POST счёт без оплаты
    path("staff/bills/pay/", BillPayView.as_view(), name="bill-pay"),                            # POST «Оплачено»
    path("staff/cash/", CashView.as_view(), name="cash"),                                        # GET «Касса»: смена
    path("staff/cash/open/", CashOpenView.as_view(), name="cash-open"),                          # POST открыть смену
    path("staff/cash/move/", CashMoveView.as_view(), name="cash-move"),                          # POST внесение / изъятие
    path("staff/cash/close/", CashCloseView.as_view(), name="cash-close"),                       # POST закрыть смену
    path("staff/cash/receipt-copy/", ReceiptCopyView.as_view(), name="receipt-copy"),            # POST копия чека
    path("staff/print-jobs/claim/", PrintJobClaimView.as_view(), name="print-claim"),            # POST чеки на печать
    path("staff/orders/<int:pk>/print/", OrderReprintView.as_view(), name="order-reprint"),      # POST повторить чек заказа
    path("staff/orders/<int:pk>/ticket/", OrderTicketView.as_view(), name="order-ticket"),       # GET чек заказа (просмотр)
    path("staff/tables/<int:table_id>/close-visit/", CloseTableVisitView.as_view(), name="close-visit"),  # закрыть стол
] + router.urls