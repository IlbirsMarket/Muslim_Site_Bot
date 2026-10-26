"""Сериализаторы заказов для сотрудников (админ-панель, официанты, кухня)."""

from rest_framework import serializers   # инструменты DRF

from .models import Order, TableCall
from .serializers import OrderItemSerializer          # позиции — как у гостя
from .status_service import ACTIONS, available_actions


def _person(user):
    """Имя сотрудника для показа: имя, а если его нет — логин."""
    if not user:
        return None
    return user.get_full_name() or user.username


class OrderStaffSerializer(serializers.ModelSerializer):
    """Полный заказ для сотрудника."""

    number = serializers.IntegerField(source="id", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(read_only=True)
    payment_display = serializers.CharField(source="get_payment_method_display", read_only=True)
    table_name = serializers.CharField(source="table.name", read_only=True, default="")
    items = OrderItemSerializer(many=True, read_only=True)
    claimed_by_name = serializers.SerializerMethodField()       # кто взял стол
    accepted_by_name = serializers.SerializerMethodField()      # кто подтвердил
    timeline = serializers.SerializerMethodField()              # история: статус, кто, когда
    available_actions = serializers.SerializerMethodField()     # какие кнопки показать

    class Meta:
        model = Order
        fields = [
            "id", "number", "kind", "kind_display", "status", "status_label", "table", "table_name",
            "customer_name", "phone", "address", "apartment", "entrance", "floor", "courier_comment",
            "payment_method", "payment_display", "change_from", "comment", "cancel_reason",
            "items", "subtotal", "delivery_fee", "total",
            "claimed_by_name", "accepted_by_name", "created_at", "timeline", "available_actions",
        ]

    def get_claimed_by_name(self, obj):
        return _person(obj.claimed_by)

    def get_accepted_by_name(self, obj):
        return _person(obj.accepted_by)

    def get_timeline(self, obj) -> list:
        """[{status, label, by, at}, ...]"""
        return [
            {
                "status": log.status,
                "label": obj.completed_label if log.status == Order.Status.COMPLETED else log.get_status_display(),
                "by": _person(log.changed_by),
                "at": log.created_at,
            }
            for log in obj.status_logs.all()
        ]

    def get_available_actions(self, obj) -> list:
        """Кнопки для того сотрудника, который сделал запрос."""
        return available_actions(obj, self.context["request"].user)


class StatusChangeSerializer(serializers.Serializer):
    """Тело запроса на смену статуса: {"action": "accept", "reason": ""}."""
    action = serializers.ChoiceField(choices=list(ACTIONS.keys()))                        # accept, reject, cook, ...
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True)     # причина (для отмены)


class TableCallStaffSerializer(serializers.ModelSerializer):
    """Вызов со стола для официантов."""
    table_name = serializers.CharField(source="table.name", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = TableCall
        fields = ["id", "table", "table_name", "kind", "kind_display", "is_done", "created_at", "done_at"]