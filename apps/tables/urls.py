"""Адреса столов."""

from django.urls import path                       # описание адресов
from rest_framework.routers import DefaultRouter   # автоматические адреса для ViewSet

from .views import PublicTableView, TableAdminViewSet

router = DefaultRouter()
router.register("admin/tables", TableAdminViewSet, basename="admin-tables")  # /api/admin/tables/

urlpatterns = [
    path("tables/<str:token>/", PublicTableView.as_view(), name="public-table"),  # /api/tables/k8Fq2xLm/
] + router.urls