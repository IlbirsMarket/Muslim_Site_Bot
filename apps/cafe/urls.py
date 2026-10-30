"""Адреса филиалов и их настроек."""

from django.urls import path   # описание адресов

from .views import CafeAdminView, PublicBranchListView, PublicCafeView

urlpatterns = [
    path("branches/", PublicBranchListView.as_view(), name="public-branches"),   # /api/branches/ — филиалы
    path("cafe/", PublicCafeView.as_view(), name="public-cafe"),        # /api/cafe/
    path("admin/cafe/", CafeAdminView.as_view(), name="admin-cafe"),    # /api/admin/cafe/
]