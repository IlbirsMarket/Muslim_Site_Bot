"""Обработчики запросов филиалов и их настроек."""

from rest_framework import generics               # готовые views
from rest_framework.permissions import AllowAny   # доступ для всех

from core.branches import guest_branch, staff_branch   # филиал гостя / сотрудника
from core.permissions import IsCafeAdmin  # наши права
from .models import Branch, CafeSettings
from .serializers import BranchPublicSerializer, CafeAdminSerializer, CafePublicSerializer


class PublicBranchListView(generics.ListAPIView):
    """GET /api/branches/ — список работающих филиалов (переключатель на главной у гостя)."""
    serializer_class = BranchPublicSerializer
    permission_classes = [AllowAny]
    pagination_class = None                        # филиалов мало — все сразу
    queryset = Branch.objects.filter(is_active=True).select_related("settings")


class PublicCafeView(generics.RetrieveAPIView):
    """GET /api/cafe/?branch=<id> или ?token=<QR> — гость: открыт ли филиал, доставка, контакты."""
    serializer_class = CafePublicSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        return CafeSettings.load(guest_branch(self.request))   # настройки филиала гостя


class CafeAdminView(generics.RetrieveUpdateAPIView):
    """
    GET / PATCH /api/admin/cafe/ — настройки текущего филиала (и его название).
    Смотреть и менять: шеф и программист — любой филиал, админ и кассир — свой.
    """
    serializer_class = CafeAdminSerializer

    def get_object(self):
        return CafeSettings.load(staff_branch(self.request))

    permission_classes = [IsCafeAdmin]     # смотреть и менять: шеф, программист, админ и кассир своего филиала
