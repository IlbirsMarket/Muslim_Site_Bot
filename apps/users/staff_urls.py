"""Адреса раздела «Сотрудники и роли»."""

from rest_framework.routers import DefaultRouter   # автоматические адреса для ViewSet

from .staff_views import StaffViewSet

router = DefaultRouter()
router.register("admin/staff", StaffViewSet, basename="admin-staff")   # /api/admin/staff/

urlpatterns = router.urls