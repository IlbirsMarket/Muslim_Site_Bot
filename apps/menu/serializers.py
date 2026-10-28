"""
Сериализаторы меню.
Public — для гостей (только чтение).
Admin — для админ-панели (создание и редактирование).
"""

from rest_framework import serializers                 # инструменты DRF

from .models import Category, Dish, DishSize, Extra   # модели меню

MAX_PHOTO_BYTES = 5 * 1024 * 1024                      # фото блюда — не больше 5 МБ
ALLOWED_PHOTO_FORMATS = {"JPEG", "PNG", "WEBP"}        # какие картинки принимаем


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
    """Категория: все поля для редактирования + сколько в ней блюд (чтобы знать, можно ли удалить)."""
    dishes_count = serializers.IntegerField(read_only=True, default=0)   # считает сервер

    class Meta:
        model = Category
        fields = ["id", "name", "position", "is_active", "dishes_count"]

    def create(self, validated_data):
        """Новая категория встаёт в конец списка, если порядок не указали."""
        if "position" not in validated_data:
            last = Category.objects.order_by("-position").values_list("position", flat=True).first() or 0
            validated_data["position"] = last + 10
        return super().create(validated_data)

    def validate_name(self, value):
        """Без пустых и повторяющихся названий. «Супы» и « супы » — одно и то же."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Укажите название категории.")
        others = Category.objects.all()
        if self.instance:
            others = others.exclude(pk=self.instance.pk)                 # себя не считаем
        # Сравниваем в Python: SQLite не умеет без учёта регистра сравнивать русские буквы
        if any(name.strip().lower() == value.lower() for name in others.values_list("name", flat=True)):
            raise serializers.ValidationError("Такая категория уже есть.")
        return value


class CategoryOrderSerializer(serializers.Serializer):
    """Новый порядок категорий: {"ids": [3, 1, 2]} — сверху вниз."""
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class DishOrderSerializer(serializers.Serializer):
    """Новый порядок блюд одной категории: {"category": 2, "ids": [7, 5, 6]} — сверху вниз."""
    category = serializers.IntegerField()                                          # в какой категории меняем порядок
    ids = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)  # все блюда категории по порядку


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

    @staticmethod
    def _last_position(category):
        """Место в самом конце категории: последний номер + 10."""
        last = Dish.objects.filter(category=category).order_by("-position").values_list("position", flat=True).first() or 0
        return last + 10

    def create(self, validated_data):
        """Новое блюдо встаёт в конец своей категории, если порядок не указали."""
        if "position" not in validated_data:
            validated_data["position"] = self._last_position(validated_data["category"])
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Блюдо перенесли в другую категорию — ставим его в конец новой категории."""
        category = validated_data.get("category")
        if category is not None and category != instance.category and "position" not in validated_data:
            validated_data["position"] = self._last_position(category)
        return super().update(instance, validated_data)

    def validate_photo(self, value):
        """Фото: только настоящие картинки JPG, PNG или WebP и не больше 5 МБ (проверяем само содержимое файла)."""
        if not value:
            return value
        if value.size > MAX_PHOTO_BYTES:
            raise serializers.ValidationError("Фото больше 5 МБ. Выберите файл поменьше.")
        image = getattr(value, "image", None)                       # Pillow уже открыл файл и проверил, что это картинка
        if image is not None and (image.format or "").upper() not in ALLOWED_PHOTO_FORMATS:
            raise serializers.ValidationError("Подойдёт только JPG, PNG или WebP.")
        return value