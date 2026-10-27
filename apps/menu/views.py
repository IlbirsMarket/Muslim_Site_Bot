"""Обработчики запросов меню."""

from django.db import transaction                              # «всё или ничего» при смене порядка
from django.db.models import Count, Prefetch                  # число блюд; заранее подгружаем связанные данные одним запросом
from drf_spectacular.utils import extend_schema                # описание для Swagger                       # заранее подгружаем связанные данные одним запросом
from django_filters.rest_framework import DjangoFilterBackend  # фильтры ?category=1
from rest_framework import filters, generics, viewsets        # поиск, готовые views, наборы CRUD
from rest_framework.decorators import action                   # свои дополнительные адреса во ViewSet
from rest_framework.permissions import AllowAny                # доступ для всех
from rest_framework.response import Response                   # ответ в JSON
from django.db.models import ProtectedError                    # ошибка "нельзя удалить, есть связанные записи"
from rest_framework.exceptions import ValidationError          # ответ 400 с текстом

from core.permissions import CanManageStopList, IsCafeAdmin    # наши права
from .models import Category, Dish, DishSize, Extra
from .serializers import (
    CategoryAdminSerializer,
    CategoryOrderSerializer,
    DishAdminSerializer,
    DishSizeAdminSerializer,
    ExtraAdminSerializer,
    MenuCategorySerializer,
)


# ===================== ДЛЯ ГОСТЕЙ =====================

class PublicMenuView(generics.ListAPIView):
    """GET /api/menu/ — всё меню: категории с блюдами, размерами и добавками."""

    serializer_class = MenuCategorySerializer  # как превращать в JSON
    permission_classes = [AllowAny]            # меню видят все, вход не нужен
    pagination_class = None                    # отдаём всё сразу, без страниц

    def get_queryset(self):
        # Блюда, которые показываем в меню, сразу с размерами и добавками
        dishes = Dish.objects.filter(is_active=True).prefetch_related("sizes", "extras")
        # Активные категории, к каждой прикрепляем её блюда в поле active_dishes
        return Category.objects.filter(is_active=True).prefetch_related(
            Prefetch("dishes", queryset=dishes, to_attr="active_dishes")
        )


# ===================== ДЛЯ АДМИН-ПАНЕЛИ =====================

class CategoryAdminViewSet(viewsets.ModelViewSet):
    """/api/admin/categories/ — список, создание, изменение, удаление категорий."""
    queryset = Category.objects.annotate(dishes_count=Count("dishes"))   # у каждой категории — число блюд
    serializer_class = CategoryAdminSerializer
    permission_classes = [IsCafeAdmin]
    pagination_class = None                                              # категорий немного — все сразу

    @extend_schema(request=CategoryOrderSerializer, responses=CategoryAdminSerializer(many=True))
    @action(detail=False, methods=["post"])
    def reorder(self, request):
        """POST /api/admin/categories/reorder/ {"ids": [3, 1, 2]} — новый порядок после перетаскивания."""
        body = CategoryOrderSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        ids = body.validated_data["ids"]
        known = set(Category.objects.values_list("id", flat=True))
        if set(ids) != known:                                            # прислали не все категории или чужие id
            raise ValidationError({"ids": "Нужно прислать все категории в новом порядке."})
        with transaction.atomic():                                       # всё или ничего
            for index, category_id in enumerate(ids):
                Category.objects.filter(pk=category_id).update(position=(index + 1) * 10)   # 10, 20, 30…
        return Response(self.get_serializer(self.get_queryset(), many=True).data)

    def perform_destroy(self, instance):
        """Категорию с блюдами удалить нельзя — отвечаем понятной ошибкой."""
        try:
            instance.delete()
        except ProtectedError:                                     # в категории есть блюда
            raise ValidationError("Сначала удалите или перенесите блюда из этой категории. Или просто скройте её.")


class ExtraAdminViewSet(viewsets.ModelViewSet):
    """/api/admin/extras/ — добавки."""
    queryset = Extra.objects.all()
    serializer_class = ExtraAdminSerializer
    permission_classes = [IsCafeAdmin]


class DishSizeAdminViewSet(viewsets.ModelViewSet):
    """/api/admin/sizes/ — размеры блюд. Фильтр: ?dish=5."""
    queryset = DishSize.objects.all()
    serializer_class = DishSizeAdminSerializer
    permission_classes = [IsCafeAdmin]
    filterset_fields = ["dish"]  # размеры конкретного блюда


class DishAdminViewSet(viewsets.ModelViewSet):
    """
    /api/admin/dishes/ — блюда.
    Фильтры: ?category=1&is_available=false. Поиск: ?search=пицца.
    """
    queryset = Dish.objects.select_related("category").prefetch_related("sizes", "extras")  # сразу с категорией, размерами и добавками
    serializer_class = DishAdminSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]  # фильтры и поиск
    filterset_fields = ["category", "is_available", "is_active"]   # по чему фильтровать
    search_fields = ["name"]                                       # где искать

    def get_permissions(self):
        """Смотреть блюда и включать стоп-лист может кухня, остальное — только админ и выше."""
        if self.action in ("list", "retrieve", "toggle_available"):  # чтение и стоп-лист
            return [CanManageStopList()]
        return [IsCafeAdmin()]                                       # создание, изменение, удаление

    @action(detail=True, methods=["post"], url_path="toggle-available")
    def toggle_available(self, request, pk=None):
        """POST /api/admin/dishes/{id}/toggle-available/ — включить или выключить «Нет в наличии»."""
        dish = self.get_object()                                       # находим блюдо по id
        dish.is_available = not dish.is_available                      # меняем на противоположное
        dish.save(update_fields=["is_available", "updated_at"])        # сохраняем только эти поля
        return Response({"id": dish.id, "is_available": dish.is_available})  # отвечаем новым состоянием