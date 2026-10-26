"""Сериализаторы настроек кафе."""

from rest_framework import serializers  # инструменты DRF

from .models import CafeSettings


class CafePublicSerializer(serializers.ModelSerializer):
    """Что видит гость: открыто ли кафе, условия доставки, контакты."""

    is_open = serializers.SerializerMethodField()   # можно ли сейчас заказать (считаем ниже)

    class Meta:
        model = CafeSettings
        fields = [
            "is_open", "is_delivery_enabled", "opens_at", "closes_at",
            "delivery_fee", "delivery_min_sum", "free_delivery_from", "delivery_time",
            "address", "phone",
        ]

    def get_is_open(self, obj) -> bool:
        return obj.can_accept_orders()   # приём включён и сейчас рабочее время


class CafeAdminSerializer(serializers.ModelSerializer):
    """Все настройки для страницы «Настройки» в админ-панели."""
    class Meta:
        model = CafeSettings
        exclude = ["id"]                 # все поля, кроме id
        read_only_fields = ["updated_at"]