"""Обработчики запросов настроек кафе."""

from rest_framework import generics               # готовые views
from rest_framework.permissions import AllowAny   # доступ для всех

from core.permissions import IsCafeAdmin, IsChef  # наши права
from .models import CafeSettings
from .serializers import CafeAdminSerializer, CafePublicSerializer


class PublicCafeView(generics.RetrieveAPIView):
    """GET /api/cafe/ — гость: открыто ли кафе, доставка, контакты."""
    serializer_class = CafePublicSerializer
    permission_classes = [AllowAny]

    def get_object(self):
        return CafeSettings.load()   # единственная запись настроек


class CafeAdminView(generics.RetrieveUpdateAPIView):
    """GET / PATCH /api/admin/cafe/ — смотреть может админ, менять — только шеф и программист."""
    serializer_class = CafeAdminSerializer

    def get_object(self):
        return CafeSettings.load()

    def get_permissions(self):
        if self.request.method == "GET":   # просмотр
            return [IsCafeAdmin()]
        return [IsChef()]                  # изменение