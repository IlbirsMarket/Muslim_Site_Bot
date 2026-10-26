"""Раздел «Сотрудники и роли» в админ-панели."""

from django_filters.rest_framework import DjangoFilterBackend   # фильтры ?role=cook
from drf_spectacular.utils import extend_schema                 # описание для Swagger
from rest_framework import filters, mixins, status, viewsets    # поиск, части CRUD, коды ответов
from rest_framework.decorators import action                    # свои адреса во ViewSet
from rest_framework.exceptions import PermissionDenied          # ошибка 403
from rest_framework.response import Response                    # ответ в JSON

from core.permissions import IsCafeAdmin                        # только админ, шеф, программист
from .models import RoleChangeLog, User
from .serializers import (
    PasswordSetSerializer,
    RoleChangeLogSerializer,
    RoleChangeSerializer,
    StaffCreateSerializer,
    StaffSerializer,
)
from .services import change_role


class StaffViewSet(
    mixins.ListModelMixin,      # GET список
    mixins.RetrieveModelMixin,  # GET один
    mixins.CreateModelMixin,    # POST создать
    mixins.UpdateModelMixin,    # PATCH изменить (удаления нет — только блокировка)
    viewsets.GenericViewSet,
):
    """
    /api/admin/staff/ — сотрудники.
    Фильтры: ?role=cook&is_active=true. Поиск: ?search=азамат
    """

    permission_classes = [IsCafeAdmin]
    queryset = User.objects.exclude(role="").order_by("username")   # только сотрудники с ролью
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["role", "is_active"]
    search_fields = ["username", "first_name", "last_name", "phone"]

    def get_serializer_class(self):
        if self.action == "create":
            return StaffCreateSerializer      # при создании нужен пароль и роль
        return StaffSerializer                # в остальных случаях — обычный

    def _check_can_manage(self, target):
        """Ошибка 403, если текущий сотрудник не может управлять target."""
        if not self.request.user.can_manage(target):
            raise PermissionDenied("Вы не можете изменять этого сотрудника.")

    @extend_schema(request=StaffCreateSerializer, responses={201: StaffSerializer})
    def create(self, request, *args, **kwargs):
        """POST /api/admin/staff/ — добавить сотрудника."""
        serializer = StaffCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        data = StaffSerializer(user, context=self.get_serializer_context()).data   # отвечаем без пароля
        return Response(data, status=status.HTTP_201_CREATED)

    def perform_update(self, serializer):
        """PATCH: имя, телефон, Telegram ID, блокировка (is_active)."""
        self._check_can_manage(serializer.instance)
        serializer.save()

    @extend_schema(request=RoleChangeSerializer, responses=StaffSerializer)
    @action(detail=True, methods=["post"], url_path="set-role")
    def set_role(self, request, pk=None):
        """POST /api/admin/staff/{id}/set-role/ — сменить роль: {"role": "cook"}."""
        body = RoleChangeSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        user = change_role(request.user, self.get_object(), body.validated_data["role"])
        return Response(StaffSerializer(user, context=self.get_serializer_context()).data)

    @extend_schema(request=PasswordSetSerializer, responses={204: None})
    @action(detail=True, methods=["post"], url_path="set-password")
    def set_password(self, request, pk=None):
        """POST /api/admin/staff/{id}/set-password/ — задать новый пароль: {"password": "..."}."""
        target = self.get_object()
        self._check_can_manage(target)
        body = PasswordSetSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        target.set_password(body.validated_data["password"])      # шифруем и сохраняем
        target.save(update_fields=["password"])
        return Response(status=status.HTTP_204_NO_CONTENT)        # 204 — успешно, без тела ответа

    @extend_schema(responses={200: dict})
    @action(detail=False, methods=["get"])
    def roles(self, request):
        """GET /api/admin/staff/roles/ — какие роли я могу назначать (для выпадающего списка)."""
        return Response([
            {"value": role, "label": User.Role(role).label}
            for role in request.user.assignable_roles()
        ])

    @extend_schema(responses=RoleChangeLogSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="role-log")
    def role_log(self, request):
        """GET /api/admin/staff/role-log/ — последние 100 смен ролей."""
        logs = RoleChangeLog.objects.select_related("user", "changed_by")[:100]
        return Response(RoleChangeLogSerializer(logs, many=True).data)