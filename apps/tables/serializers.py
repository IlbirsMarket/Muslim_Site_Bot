"""Сериализаторы столов."""

from rest_framework import serializers  # инструменты DRF

from .models import Table               # модель стола


class TablePublicSerializer(serializers.ModelSerializer):
    """Что видит гость, отсканировав QR: какой это стол и зал это или доставка."""
    class Meta:
        model = Table
        fields = ["number", "name", "kind", "freed_at"]   # токен и id гостю не нужны; freed_at — стол освободили


class TableAdminSerializer(serializers.ModelSerializer):
    """Стол для админ-панели. Через API создаются только столы: доставка одна и создаётся сама."""

    qr_url = serializers.CharField(read_only=True)                            # адрес из QR (для показа под картинкой)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)  # "Стол в зале" / "Доставка"
    active_orders = serializers.IntegerField(read_only=True, default=0)   # сколько незакрытых заказов у стола

    class Meta:
        model = Table
        fields = ["id", "kind", "kind_display", "number", "name", "token", "qr_url", "is_active",
                  "active_orders", "occupied_since", "created_at"]
        # kind только для чтения: новый — всегда стол; токен — только перевыпуском; «занят» — по заказам
        read_only_fields = ["kind", "token", "occupied_since", "created_at"]
        validators = []          # номер проверяем сами ниже (иначе DRF потребует номер обязательно)

    def validate(self, attrs):
        """Номер можно не указывать — поставится сам. Если указали, он не должен быть занят другим столом."""
        if self.instance and self.instance.kind == Table.Kind.DELIVERY:
            raise serializers.ValidationError("Доставку менять нельзя.")
        number = attrs.get("number")
        if number:
            same = Table.objects.filter(kind=Table.Kind.HALL, number=number)       # кто уже с таким номером
            if self.instance:
                same = same.exclude(pk=self.instance.pk)                            # себя не считаем
            if same.exists():
                raise serializers.ValidationError({"number": f"Стол {number} уже есть."})
        return attrs


class StaffTableSerializer(serializers.ModelSerializer):
    """Стол для официанта: занят ли и сколько незакрытых заказов (чтобы закрыть стол, когда гости ушли)."""

    active_orders = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Table
        fields = ["id", "number", "name", "occupied_since", "active_orders"]