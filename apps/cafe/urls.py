"""Адреса настроек кафе."""

from django.urls import path   # описание адресов

from .views import CafeAdminView, PublicCafeView

urlpatterns = [
    path("cafe/", PublicCafeView.as_view(), name="public-cafe"),        # /api/cafe/
    path("admin/cafe/", CafeAdminView.as_view(), name="admin-cafe"),    # /api/admin/cafe/
]