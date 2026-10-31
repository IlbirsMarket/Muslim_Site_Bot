"""Сериализаторы столов."""

from rest_framework import serializers  # инструменты DRF

from .models import Floor, Table        # этажи и столы


class TablePublicSerializer(serializers.ModelSerializer):
    """Что видит гость, отсканировав QR: какой это стол, зал это или доставка и какой филиал."""

    branch_name = serializers.CharField(source="branch.name", read_only=True)   # «Филиал 1»
    telegram_url = serializers.SerializerMethodField()                          # «Заказать в Telegram» (только у столов)

    class Meta:
        model = Table
        # токен и id гостю не нужны; freed_at — стол освободили; branch — меню и настройки этого филиала
        fields = ["number", "floor", "name", "kind", "freed_at", "branch", "branch_name", "telegram_url"]

    def get_telegram_url(self, obj) -> str:
        return table_bot_url(obj)


def bot_url(branch_id) -> str:
    """Ссылка на гостевой бот филиала: t.me/бот?start=b<секретный код> (обновляется кнопкой «Обновить QR»)."""
    from django.conf import settings                                   # имя бота из .env
    from apps.cafe.models import Branch
    name = settings.TELEGRAM_GUEST_BOT_USERNAME
    branch = Branch.objects.filter(pk=branch_id).first()
    if not name or branch is None:
        return ""
    if not branch.tg_start_token:                                      # старый филиал без кода — создаём
        branch.save()
    return f"https://t.me/{name}?start=b{branch.tg_start_token}"


def table_bot_url(table) -> str:
    """Ссылка «Заказать в Telegram» со стола: бот откроется сразу с этим столом (start=t<токен стола>)."""
    from django.conf import settings
    name = settings.TELEGRAM_GUEST_BOT_USERNAME
    return f"https://t.me/{name}?start=t{table.token}" if name and table.kind == Table.Kind.HALL else ""


class TableAdminSerializer(serializers.ModelSerializer):
    """Стол для админ-панели. Через API создаются только столы: доставка одна и создаётся сама."""

    qr_url = serializers.CharField(read_only=True)                            # адрес из QR (для показа под картинкой)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)  # "Стол в зале" / "Доставка"
    active_orders = serializers.IntegerField(read_only=True, default=0)   # сколько незакрытых заказов у стола
    bot_url = serializers.SerializerMethodField()                          # у «Доставки»: ссылка на гостевой бот этого филиала

    class Meta:
        model = Table
        fields = ["id", "kind", "kind_display", "floor", "number", "name", "token", "qr_url", "is_active",
                  "active_orders", "occupied_since", "created_at", "bot_url"]
        # kind только для чтения: новый — всегда стол; токен — только перевыпуском; «занят» — по заказам
        read_only_fields = ["kind", "token", "occupied_since", "created_at"]
        validators = []          # номер проверяем сами ниже (иначе DRF потребует номер обязательно)

    def get_bot_url(self, obj) -> str:
        """QR гостевого бота: только у «Доставки» и только если в .env указано имя бота."""
        return bot_url(obj.branch_id) if obj.kind == Table.Kind.DELIVERY else ""

    def validate(self, attrs):
        """Номер можно не указывать — поставится сам. Если указали, он не должен быть занят другим столом на этом этаже."""
        if self.instance and self.instance.kind == Table.Kind.DELIVERY:
            raise serializers.ValidationError("Доставку менять нельзя.")
        if self.instance and "floor" in attrs and attrs["floor"] != self.instance.floor:   # этаж у готового стола не меняем
            raise serializers.ValidationError({"floor": "Этаж стола менять нельзя: удалите стол и добавьте его на нужном этаже."})
        floor = attrs.get("floor", self.instance.floor if self.instance else 1)
        branch = self.instance.branch if self.instance else self.context.get("branch")
        if not self.instance and not Floor.objects.filter(branch=branch, number=floor).exists():   # такого этажа в филиале нет
            raise serializers.ValidationError({"floor": f"{floor} этажа нет. Сначала добавьте этаж кнопкой «+ Этаж»."})
        number = attrs.get("number")
        if number:
            same = Table.objects.filter(branch=branch, kind=Table.Kind.HALL, floor=floor, number=number)   # кто уже с таким номером на этаже филиала
            if self.instance:
                same = same.exclude(pk=self.instance.pk)                            # себя не считаем
            if same.exists():
                raise serializers.ValidationError({"number": f"Стол {number} на {floor} этаже уже есть."})
        return attrs


class StaffTableSerializer(serializers.ModelSerializer):
    """Стол для официанта: занят ли и сколько незакрытых заказов (чтобы закрыть стол, когда гости ушли)."""

    active_orders = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Table
        fields = ["id", "floor", "number", "name", "occupied_since", "active_orders"]


class FloorSerializer(serializers.ModelSerializer):
    """Этаж для вкладок «1 этаж | 2 этаж | …»: номер, сколько столов, можно ли удалить."""

    tables_count = serializers.IntegerField(read_only=True, default=0)   # активных столов на этаже
    can_delete = serializers.SerializerMethodField()                     # кнопка «Удалить этаж»

    class Meta:
        model = Floor
        fields = ["id", "number", "tables_count", "can_delete"]
        read_only_fields = ["number"]                                     # номер ставится сам: следующий по порядку

    def get_can_delete(self, floor) -> bool:
        """Удалить можно только последний этаж, если он пустой и это не 1 этаж."""
        last = self.context.get("last_number")
        return floor.number != 1 and floor.number == last and not getattr(floor, "tables_count", 0)

