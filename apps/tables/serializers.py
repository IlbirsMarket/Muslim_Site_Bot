"""Сериализаторы столов."""

from rest_framework import serializers  # инструменты DRF

from .models import Table               # модель стола


class TablePublicSerializer(serializers.ModelSerializer):
    """Что видит гость, отсканировав QR: какой это стол и зал это или доставка."""
    class Meta:
        model = Table
        fields = ["number", "name", "kind"]   # токен и id гостю не нужны


class TableAdminSerializer(serializers.ModelSerializer):
    """Стол для админ-панели."""

    qr_url = serializers.CharField(read_only=True)                            # адрес из QR (для показа под картинкой)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)  # "Стол в зале" / "Доставка"
    active_orders = serializers.IntegerField(read_only=True, default=0)   # сколько незакрытых заказов у стола (0 — свободен)

    class Meta:
        model = Table
        fields = ["id", "kind", "kind_display", "number", "name", "token", "qr_url", "is_active", "active_orders", "created_at"]
        read_only_fields = ["token", "created_at"]   # токен меняется только через перевыпуск

    def validate(self, attrs):
        """У стола в зале обязателен номер."""
        kind = attrs.get("kind", getattr(self.instance, "kind", Table.Kind.HALL))   # тип: из запроса или текущий
        number = attrs.get("number", getattr(self.instance, "number", None))       # номер: из запроса или текущий
        if kind == Table.Kind.HALL and not number:
            raise serializers.ValidationError({"number": "Укажите номер стола."})
        return attrs