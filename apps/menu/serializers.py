"""
Сериализаторы меню.
Public — для гостей (только чтение).
Admin — для админ-панели (создание и редактирование).
"""

from rest_framework import serializers                 # инструменты DRF

from .models import Category, Dish, DishSize, Extra   # модели меню


# ===================== ДЛЯ ГОСТЕЙ =====================

class DishSizeSerializer(serializers.ModelSerializer):
    """Размер блюда: id, название, цена."""
    class Meta:
        model = DishSize
        fields = ["id", "name", "price"]


class ExtraPublicSerializer(serializers.ModelSerializer):
    """Добавка для гостя: id, название, цена."""
    class Meta:
        model = Extra
        fields = ["id", "name", "price"]


class DishPublicSerializer(serializers.ModelSerializer):
    """Блюдо в меню гостя."""

    sizes = DishSizeSerializer(many=True, read_only=True)   # список размеров
    extras = serializers.SerializerMethodField()            # только добавки в наличии (считаем ниже)
    min_price = serializers.IntegerField(read_only=True)    # "от 550 сом"

    class Meta:
        model = Dish
        fields = ["id", "name", "description", "photo", "price", "min_price", "is_available", "sizes", "extras"]

    def get_extras(self, obj):
        """Отдаём только добавки, которые сейчас в наличии."""
        available = [extra for extra in obj.extras.all() if extra.is_available]  # фильтруем в памяти (данные уже загружены)
        return ExtraPublicSerializer(available, many=True).data


class MenuCategorySerializer(serializers.ModelSerializer):
    """Категория вместе с её блюдами — всё меню одним запросом."""

    dishes = DishPublicSerializer(source="active_dishes", many=True, read_only=True)  # active_dishes готовим во view

    class Meta:
        model = Category
        fields = ["id", "name", "dishes"]


# ===================== ДЛЯ АДМИН-ПАНЕЛИ =====================

class CategoryAdminSerializer(serializers.ModelSerializer):
    """Категория: все поля для редактирования."""
    class Meta:
        model = Category
        fields = ["id", "name", "position", "is_active"]


class ExtraAdminSerializer(serializers.ModelSerializer):
    """Добавка: все поля для редактирования."""
    class Meta:
        model = Extra
        fields = ["id", "name", "price", "is_available"]


class DishSizeAdminSerializer(serializers.ModelSerializer):
    """Размер: создаётся и меняется отдельно, с указанием блюда."""
    class Meta:
        model = DishSize
        fields = ["id", "dish", "name", "price", "position"]


class DishAdminSerializer(serializers.ModelSerializer):
    """Блюдо для админ-панели."""

    category_name = serializers.CharField(source="category.name", read_only=True)  # название категории для таблицы
    sizes = DishSizeSerializer(many=True, read_only=True)                          # размеры (только показать)
    extras = serializers.PrimaryKeyRelatedField(                                    # добавки: фронт присылает список id [1, 3]
        many=True, queryset=Extra.objects.all(), required=False
    )

    class Meta:
        model = Dish
        fields = [
            "id", "category", "category_name", "name", "description", "photo",
            "price", "extras", "sizes", "is_available", "is_active", "position", "updated_at",
        ]
        read_only_fields = ["updated_at"]  # дату изменения ставит сервер