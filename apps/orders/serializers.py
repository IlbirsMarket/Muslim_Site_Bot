"""
Сериализаторы заказов для гостей:
- приём и проверка нового заказа
- показ заказа на странице статуса
- вызов официанта / счёта
"""

from datetime import timedelta                     # промежуток времени (2 минуты)

from django.utils import timezone                  # текущее время
from rest_framework import serializers             # инструменты DRF

from apps.cafe.models import CafeSettings
from apps.menu.models import Dish
from apps.tables.models import Table
from .models import Order, OrderItem, TableCall
from .services import create_order


# ===================== НОВЫЙ ЗАКАЗ =====================

class OrderItemInputSerializer(serializers.Serializer):
    """Одна позиция, как её присылает фронт (без цен!)."""
    dish_id = serializers.IntegerField()                                    # какое блюдо
    size_id = serializers.IntegerField(required=False, allow_null=True)     # какой размер (если у блюда есть размеры)
    extra_ids = serializers.ListField(                                      # какие добавки, список id
        child=serializers.IntegerField(), required=False, default=list
    )
    quantity = serializers.IntegerField(min_value=1, max_value=50)          # сколько штук


class OrderCreateSerializer(serializers.Serializer):
    """Проверяет новый заказ и передаёт его в services.create_order."""

    table_token = serializers.CharField(required=False, allow_blank=True)   # токен из QR стола; пусто — заказ с главной страницы (доставка)                                 # токен из QR (обязателен)
    device_key = serializers.CharField(max_length=64, required=False, allow_blank=True)  # случайный ключ телефона (фронт хранит его в браузере)
    order_type = serializers.ChoiceField(                                   # со стола: takeaway; с главной: delivery или pickup
        choices=[Order.Kind.TAKEAWAY, Order.Kind.DELIVERY, Order.Kind.PICKUP], required=False
    )
    customer_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    apartment = serializers.CharField(max_length=20, required=False, allow_blank=True)
    entrance = serializers.CharField(max_length=20, required=False, allow_blank=True)
    floor = serializers.CharField(max_length=20, required=False, allow_blank=True)
    courier_comment = serializers.CharField(max_length=255, required=False, allow_blank=True)
    payment_method = serializers.ChoiceField(choices=Order.Payment.choices, required=False)
    change_from = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    comment = serializers.CharField(required=False, allow_blank=True)
    items = OrderItemInputSerializer(many=True)                             # список позиций

    def validate(self, attrs):
        """Все проверки заказа перед созданием."""

        # 1. Кафе принимает заказы?
        cafe = CafeSettings.load()
        if not cafe.can_accept_orders():
            raise serializers.ValidationError("Кафе сейчас не принимает заказы.")

        # 2. Откуда заказ: QR стола (есть токен) или главная страница сайта (токена нет → доставка)
        token = (attrs.get("table_token") or "").strip()
        if token:
            table = Table.objects.filter(token=token, is_active=True).first()
            if not table:
                raise serializers.ValidationError({"table_token": "QR-код недействителен."})
        else:
            table = Table.delivery_point()                               # единственная «Доставка»
        attrs["table"] = table

        # 3. Тип заказа: со стола — «в кафе» или «с собой»; с главной страницы — «доставка» или «самовывоз»
        order_type = attrs.get("order_type")
        if table.kind == Table.Kind.HALL:
            if order_type in (Order.Kind.DELIVERY, Order.Kind.PICKUP):
                raise serializers.ValidationError({"order_type": "Со стола можно заказать только «В кафе» или «С собой»."})
            attrs["kind"] = Order.Kind.TAKEAWAY if order_type == Order.Kind.TAKEAWAY else Order.Kind.HALL
        else:
            if order_type == Order.Kind.TAKEAWAY:
                raise serializers.ValidationError({"order_type": "«С собой» заказывают со стола в кафе."})
            attrs["kind"] = Order.Kind.PICKUP if order_type == Order.Kind.PICKUP else Order.Kind.DELIVERY

        # 4. Доставка включена? Контакты заполнены?
        if attrs["kind"] == Order.Kind.DELIVERY:
            if not cafe.is_delivery_enabled:
                raise serializers.ValidationError("Доставка сейчас недоступна.")
            required = {"customer_name": "Укажите имя.", "phone": "Укажите телефон.", "address": "Укажите адрес."}
            
        elif attrs["kind"] == Order.Kind.PICKUP:
            required = {"customer_name": "Укажите имя.", "phone": "Укажите телефон."}   # самовывоз: адрес не нужен
        else:
            required = {}                                          # в зале контакты не нужны
        errors = {field: text for field, text in required.items() if not attrs.get(field, "").strip()}
        if errors:
            raise serializers.ValidationError(errors)

        # 5. Позиции: блюда, размеры, добавки
        attrs["resolved_items"] = self._resolve_items(attrs["items"])
        return attrs

    def _resolve_items(self, items: list) -> list:
        """Находит блюда, размеры и добавки в базе и проверяет, что их можно заказать."""
        if not items:
            raise serializers.ValidationError({"items": "Корзина пуста."})

        dish_ids = {item["dish_id"] for item in items}                     # все id блюд из корзины
        dishes = {                                                          # загружаем блюда одним запросом
            dish.id: dish
            for dish in Dish.objects.filter(id__in=dish_ids, is_active=True).prefetch_related("sizes", "extras")
        }

        resolved = []
        for item in items:
            dish = dishes.get(item["dish_id"])
            if not dish:                                                    # блюда нет или оно скрыто
                raise serializers.ValidationError({"items": "Одно из блюд больше недоступно. Обновите меню."})
            if not dish.is_available:                                       # блюдо в стоп-листе
                raise serializers.ValidationError({"items": f"«{dish.name}» сейчас нет в наличии."})

            sizes = {size.id: size for size in dish.sizes.all()}            # размеры этого блюда
            size_id = item.get("size_id")
            if sizes:                                                       # у блюда есть размеры — выбор обязателен
                if size_id not in sizes:
                    raise serializers.ValidationError({"items": f"Выберите размер для «{dish.name}»."})
                size = sizes[size_id]
            else:                                                           # размеров нет — size_id не нужен
                size = None

            allowed_extras = {e.id: e for e in dish.extras.all() if e.is_available}  # добавки этого блюда в наличии
            extras = []
            for extra_id in item.get("extra_ids", []):
                if extra_id not in allowed_extras:
                    raise serializers.ValidationError({"items": f"Добавка недоступна для «{dish.name}»."})
                extras.append(allowed_extras[extra_id])

            resolved.append((dish, size, extras, item["quantity"]))         # всё проверено
        return resolved

    def create(self, validated_data):
        """serializer.save() → создаём заказ через сервис."""
        return create_order(validated_data)


# ===================== ПОКАЗ ЗАКАЗА ГОСТЮ =====================

class OrderItemSerializer(serializers.ModelSerializer):
    """Позиция заказа для показа."""
    line_total = serializers.IntegerField(read_only=True)   # цена × количество

    class Meta:
        model = OrderItem
        fields = ["dish_name", "size_name", "extras", "unit_price", "quantity", "line_total"]


class OrderPublicSerializer(serializers.ModelSerializer):
    """Заказ на странице статуса у гостя."""

    number = serializers.IntegerField(source="id", read_only=True)                       # номер заказа (№124)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)      # "В зале"
    status_label = serializers.CharField(read_only=True)                                  # "Готовится" / "Подан на стол"
    payment_display = serializers.CharField(source="get_payment_method_display", read_only=True)
    table_name = serializers.CharField(source="table.name", read_only=True, default="")  # "Стол 7"
    items = OrderItemSerializer(many=True, read_only=True)                                # позиции
    timeline = serializers.SerializerMethodField()                                        # история статусов

    class Meta:
        model = Order
        fields = [
            "public_id", "number", "kind", "kind_display", "status", "status_label", "table_name",
            "items", "subtotal", "delivery_fee", "total", "payment_method", "payment_display",
            "comment", "cancel_reason", "created_at", "timeline",
        ]

    def get_timeline(self, obj) -> list:
        """Этапы заказа со временем: [{status, label, at}, ...]."""
        return [
            {
                "status": log.status,
                "label": obj.completed_label if log.status == Order.Status.COMPLETED else log.get_status_display(),
                "at": log.created_at,
            }
            for log in obj.status_logs.all()
        ]


# ===================== ВЫЗОВ СО СТОЛА =====================

class TableCallCreateSerializer(serializers.ModelSerializer):
    """Гость нажал «Позвать официанта» или «Попросить счёт»."""

    table_token = serializers.CharField(write_only=True)   # токен стола из QR

    class Meta:
        model = TableCall
        fields = ["id", "table_token", "kind", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_table_token(self, value):
        """Вызов возможен только с настоящего стола в зале."""
        table = Table.objects.filter(token=value, is_active=True, kind=Table.Kind.HALL).first()
        if not table:
            raise serializers.ValidationError("QR-код недействителен.")
        return table   # дальше вместо токена будет сам стол

    def create(self, validated_data):
        """Если такой же вызов уже был меньше 2 минут назад и не выполнен — новый не создаём."""
        table = validated_data.pop("table_token")          # здесь уже лежит объект стола
        kind = validated_data["kind"]
        recent = TableCall.objects.filter(
            table=table, kind=kind, is_done=False,
            created_at__gte=timezone.now() - timedelta(minutes=2),
        ).first()
        if recent:
            return recent                                   # возвращаем существующий вызов
        return TableCall.objects.create(table=table, kind=kind)