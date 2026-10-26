"""Адреса заказов: для гостей и для сотрудников."""

from django.urls import path                       # описание адресов
from rest_framework.routers import DefaultRouter   # автоматические адреса для ViewSet

from .staff_views import CloseTableVisitView, StaffOrderViewSet, StaffTableCallViewSet
from .views import OrderCreateView, OrderPublicDetailView, TableCallCreateView

router = DefaultRouter()
router.register("staff/orders", StaffOrderViewSet, basename="staff-orders")             # /api/staff/orders/
router.register("staff/table-calls", StaffTableCallViewSet, basename="staff-calls")     # /api/staff/table-calls/

urlpatterns = [
    # ----- Гости -----
    path("orders/", OrderCreateView.as_view(), name="order-create"),                           # POST новый заказ
    path("orders/<uuid:public_id>/", OrderPublicDetailView.as_view(), name="order-public"),    # GET статус заказа
    path("table-calls/", TableCallCreateView.as_view(), name="table-call-create"),             # POST вызов официанта / счёта
    # ----- Сотрудники -----
    path("staff/tables/<int:table_id>/close-visit/", CloseTableVisitView.as_view(), name="close-visit"),  # закрыть стол
] + router.urls