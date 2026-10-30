"""Сериализаторы филиалов и их настроек."""

from rest_framework import serializers  # инструменты DRF

from .models import Branch, CafeSettings


class BranchPublicSerializer(serializers.ModelSerializer):
    """Филиал для переключателя: id, название, адрес."""

    address = serializers.CharField(source="settings.address", read_only=True, default="")   # адрес из настроек

    class Meta:
        model = Branch
        fields = ["id", "name", "address"]


class CafePublicSerializer(serializers.ModelSerializer):
    """Что видит гость: какой филиал, открыт ли он, условия доставки, контакты."""

    is_open = serializers.SerializerMethodField()   # можно ли сейчас заказать (считаем ниже)
    branch = serializers.IntegerField(source="branch_id", read_only=True)          # id филиала
    branch_name = serializers.CharField(source="branch.name", read_only=True)      # «Филиал 1»

    class Meta:
        model = CafeSettings
        fields = [
            "branch", "branch_name",
            "is_open", "is_delivery_enabled", "opens_at", "closes_at",
            "delivery_fee", "delivery_min_sum", "free_delivery_from", "delivery_time",
            "address", "phone",
        ]

    def get_is_open(self, obj) -> bool:
        return obj.can_accept_orders()   # приём включён и сейчас рабочее время


class CafeAdminSerializer(serializers.ModelSerializer):
    """Все настройки филиала для страницы «Настройки» + название филиала (меняет шеф)."""

    branch_name = serializers.CharField(source="branch.name", max_length=60, required=False)   # «Филиал 1» → «Джал»

    class Meta:
        model = CafeSettings
        exclude = ["id"]                 # все поля, кроме id
        read_only_fields = ["updated_at", "branch"]

    def validate_branch_name(self, value):
        """Название филиала: не пустое и не такое же, как у другого филиала."""
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Укажите название филиала.")
        others = Branch.objects.exclude(pk=self.instance.branch_id) if self.instance else Branch.objects.all()
        if any(name.strip().lower() == value.lower() for name in others.values_list("name", flat=True)):
            raise serializers.ValidationError("Филиал с таким названием уже есть.")
        return value

    def update(self, instance, validated_data):
        """Название филиала сохраняем в самом филиале, остальное — в настройках."""
        branch_data = validated_data.pop("branch", {})
        if "name" in branch_data:
            instance.branch.name = branch_data["name"]
            instance.branch.save(update_fields=["name"])
        return super().update(instance, validated_data)
