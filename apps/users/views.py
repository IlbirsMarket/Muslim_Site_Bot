"""Представления (обработчики запросов) для сотрудников."""

from rest_framework import generics            # готовые классы для типовых запросов

from core.permissions import IsStaffMember     # право: только сотрудник
from .serializers import MeSerializer          # сериализатор "кто я"


class MeView(generics.RetrieveAPIView):
    """GET /api/auth/me/ — данные вошедшего сотрудника (фронт узнаёт роль и показывает нужное меню)."""

    serializer_class = MeSerializer            # как превращать в JSON
    permission_classes = [IsStaffMember]       # только сотрудники

    def get_object(self):
        return self.request.user               # отдаём того, кто сделал запрос