"""Сериализаторы сотрудников — что отдаём в JSON."""

from django.contrib.auth.password_validation import validate_password  # проверка надёжности пароля
from rest_framework import serializers                                 # инструменты DRF

from apps.cafe.models import Branch                                    # филиалы
from .models import RoleChangeLog, User                                # модели



class UniqueEmailMixin:
    """Проверка email: убираем пробелы, приводим к маленьким буквам и не даём повторять чужой."""

    def validate_email(self, value):
        value = (value or "").strip().lower()                              # " Ali@Mail.com " → "ali@mail.com"
        if value:                                                          # пустой email можно у многих
            same = User.objects.filter(email__iexact=value)                # кто уже с таким email
            if getattr(self, "instance", None):                            # при редактировании —
                same = same.exclude(pk=self.instance.pk)                   # самого себя не считаем
            if same.exists():
                raise serializers.ValidationError("Сотрудник с таким email уже есть.")
        return value


class MeSerializer(serializers.ModelSerializer):
    """Данные о сотруднике, который сейчас вошёл в систему."""

    # Название роли на русском ("Повар"), берём из метода get_role_display
    role_display = serializers.CharField(source="get_role_display", read_only=True)
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)   # свой филиал (у шефа — пусто)
    branches = serializers.SerializerMethodField()                                           # какие филиалы видит

    class Meta:
        model = User  # с какой моделью работаем
        fields = ["id", "username", "email", "first_name", "last_name", "role", "role_display", "phone", "telegram_id",
                  "branch", "branch_name", "branches"]  # какие поля отдаём

    def get_branches(self, obj) -> list:
        """Шеф и программист — все работающие филиалы (для переключателя), остальные — только свой."""
        if obj.sees_all_branches():
            rows = Branch.objects.filter(is_active=True)
        else:
            rows = Branch.objects.filter(pk=(obj.branch or Branch.default()).pk)
        return [{"id": b.id, "name": b.name} for b in rows]

class StaffSerializer(UniqueEmailMixin, serializers.ModelSerializer):
    """Сотрудник в списке и на странице редактирования."""

    role_display = serializers.CharField(source="get_role_display", read_only=True)   # "Повар"
    telegram_id = serializers.IntegerField(required=False, allow_null=True)          # можно очистить (null)
    can_edit = serializers.SerializerMethodField()                                    # может ли текущий сотрудник его редактировать
    branch_name = serializers.CharField(source="branch.name", read_only=True, default=None)   # у шефа — пусто: «Все филиалы»

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name", "role", "role_display",
            "phone", "telegram_id", "is_active", "last_login", "date_joined", "can_edit", "branch", "branch_name",
        ]
        read_only_fields = ["role", "last_login", "date_joined"]  # роль меняется через set-role, пароль — через set-password

    def validate_username(self, value):
        """Логин: без пробелов, не пустой и не такой же, как у другого сотрудника (без учёта регистра)."""
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError("Укажите логин.")
        same = User.objects.filter(username__iexact=value)
        if self.instance:
            same = same.exclude(pk=self.instance.pk)                       # себя не считаем
        if same.exists():
            raise serializers.ValidationError("Сотрудник с таким логином уже есть.")
        return value

    def validate_telegram_id(self, value):
        """Один Telegram — один сотрудник."""
        if value is not None:
            same = User.objects.filter(telegram_id=value)
            if self.instance:
                same = same.exclude(pk=self.instance.pk)
            if same.exists():
                raise serializers.ValidationError("Этот Telegram уже привязан к другому сотруднику.")
        return value

    def validate_branch(self, branch):
        """Перевести сотрудника в другой филиал может только шеф (или программист). У шефа филиала нет."""
        if not self.context["request"].user.sees_all_branches():
            raise serializers.ValidationError("Переводить сотрудников между филиалами может только шеф.")
        if self.instance and self.instance.sees_all_branches():
            return None                                                   # шеф и программист — без филиала
        if branch is None:
            raise serializers.ValidationError("Выберите филиал.")
        return branch

    def get_can_edit(self, obj) -> bool:
        return self.context["request"].user.can_manage(obj)


class StaffCreateSerializer(UniqueEmailMixin, serializers.ModelSerializer):
    """Добавление нового сотрудника."""

    password = serializers.CharField(write_only=True)                          # пароль не возвращаем
    telegram_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = ["username", "email", "password", "first_name", "last_name", "phone", "telegram_id", "role"]

    def validate_role(self, value):
        """Создатель может дать только ту роль, которую ему разрешено назначать."""
        if value not in self.context["request"].user.assignable_roles():
            raise serializers.ValidationError("Вы не можете назначить эту роль.")
        return value

    def validate_password(self, value):
        """Пароль проверяем по правилам из настроек (минимум 8 символов и т.д.)."""
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")       # достаём пароль отдельно
        user = User(**validated_data)                   # создаём сотрудника без пароля
        user.set_password(password)                     # пароль сохраняется в зашифрованном виде
        user.save()
        RoleChangeLog.objects.create(                   # первая запись в журнале
            user=user, changed_by=self.context["request"].user, old_role="", new_role=user.role,
        )
        return user


class RoleChangeSerializer(serializers.Serializer):
    """Тело запроса смены роли: {"role": "cook"}."""
    role = serializers.ChoiceField(choices=User.Role.choices)


class PasswordSetSerializer(serializers.Serializer):
    """Тело запроса смены пароля: {"password": "..."}."""
    password = serializers.CharField(write_only=True)

    def validate_password(self, value):
        validate_password(value)                        # те же правила надёжности
        return value


class RoleChangeLogSerializer(serializers.ModelSerializer):
    """Запись журнала смен ролей."""

    user_name = serializers.SerializerMethodField()            # кому
    changed_by_name = serializers.SerializerMethodField()      # кто
    old_role_display = serializers.SerializerMethodField()     # "Повар"
    new_role_display = serializers.SerializerMethodField()     # "Админ"

    class Meta:
        model = RoleChangeLog
        fields = ["id", "user", "user_name", "changed_by_name", "old_role", "old_role_display",
                  "new_role", "new_role_display", "created_at"]

    @staticmethod
    def _name(user):
        return (user.get_full_name() or user.username) if user else None

    @staticmethod
    def _role_label(value):
        return User.Role(value).label if value else None   # "cook" → "Повар"

    def get_user_name(self, obj):
        return self._name(obj.user)

    def get_changed_by_name(self, obj):
        return self._name(obj.changed_by)

    def get_old_role_display(self, obj):
        return self._role_label(obj.old_role)

    def get_new_role_display(self, obj):
        return self._role_label(obj.new_role)