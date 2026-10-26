"""Адреса меню."""

from django.urls import path                       # описание адресов
from rest_framework.routers import DefaultRouter   # автоматически создаёт адреса для ViewSet

from .views import (
    CategoryAdminViewSet,
    DishAdminViewSet,
    DishSizeAdminViewSet,
    ExtraAdminViewSet,
    PublicMenuView,
)

router = DefaultRouter()  # создаём роутер
router.register("admin/categories", CategoryAdminViewSet, basename="admin-categories")  # /api/admin/categories/
router.register("admin/dishes", DishAdminViewSet, basename="admin-dishes")              # /api/admin/dishes/
router.register("admin/sizes", DishSizeAdminViewSet, basename="admin-sizes")            # /api/admin/sizes/
router.register("admin/extras", ExtraAdminViewSet, basename="admin-extras")             # /api/admin/extras/

urlpatterns = [
    path("menu/", PublicMenuView.as_view(), name="public-menu"),  # /api/menu/ — меню для гостей
] + router.urls                                                    # плюс все адреса роутера