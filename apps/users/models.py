"""
Модель сотрудника кафе с ролями:
программист, шеф (хозяин), админ, повар, официант.
Гости НЕ хранятся в этой таблице: аккаунт им не нужен.
"""

from django.contrib.auth.models import AbstractUser  # стандартный пользователь Django: логин, пароль и т.д.
from django.db import models                         # поля для таблиц
from django.db.models import Q                       # условие «email не пустой»
from django.db.models.functions import Lower         # сравнение без учёта регистра (A@x.com = a@x.com)


class User(AbstractUser):
    """Сотрудник кафе = стандартный пользователь + роль + Telegram ID + телефон."""

    class Role(models.TextChoices):
        """Список ролей. Слева — что хранится в базе, справа — что видно людям."""
        PROGRAMMER = "programmer", "Программист"  # разработчик системы, все права
        CHEF = "chef", "Шеф"                      # хозяин заведения, главный в кафе
        ADMIN = "admin", "Админ"                  # управляющий, подчиняется шефу
        COOK = "cook", "Повар"                    # кухня
        WAITER = "waiter", "Официант"             # зал
        COURIER = "courier", "Курьер"             # доставка

    # Роль сотрудника. Значения по умолчанию нет: при создании роль нужно выбрать явно
    role = models.CharField("Роль", max_length=20, choices=Role.choices)

    # ID в Telegram (кнопки в группе заказов будут работать по нему). Может быть пустым, но не может повторяться
    telegram_id = models.BigIntegerField("Telegram ID", null=True, blank=True, unique=True)

    # Номер телефона сотрудника
    phone = models.CharField("Телефон", max_length=20, blank=True)

    # Филиал сотрудника. У шефа и программиста пусто — они видят все филиалы
    branch = models.ForeignKey(
        "cafe.Branch", on_delete=models.PROTECT, null=True, blank=True,
        related_name="staff", verbose_name="Филиал",
    )

    class Meta:
        verbose_name = "Сотрудник"          # название в единственном числе (для админки)
        verbose_name_plural = "Сотрудники"  # во множественном

        constraints = [
            # Один email — один сотрудник (иначе непонятно, кого впускать). Пустой email можно у многих
            models.UniqueConstraint(
                Lower("email"),                       # сравниваем email маленькими буквами
                condition=~Q(email=""),               # правило не касается пустых email
                name="unique_user_email_ci",
                violation_error_message="Сотрудник с таким email уже есть.",
            ),
        ]

    def save(self, *args, **kwargs):
        """Перед сохранением: суперпользователь всегда получает роль программиста."""
        if self.is_superuser:                 # если это суперпользователь (создан через createsuperuser)
            self.role = self.Role.PROGRAMMER  # делаем его программистом
        self.email = (self.email or "").strip().lower()  # email храним без пробелов и маленькими буквами
        if self.role in (self.Role.CHEF, self.Role.PROGRAMMER):
            self.branch = None                # шеф и программист — без филиала: видят все
        elif self.role and self.branch_id is None:
            from apps.cafe.models import Branch   # импорт здесь, чтобы модели не ссылались друг на друга по кругу
            self.branch = Branch.default()    # сотрудник без филиала — в первый филиал
        super().save(*args, **kwargs)         # сохраняем как обычно

    # ----- Проверки ролей. Будем использовать в правах доступа -----

    @property
    def is_programmer(self) -> bool:
        """Только программист."""
        return self.role == self.Role.PROGRAMMER

    @property
    def is_chef(self) -> bool:
        """Шеф или программист: настройки кафе, отчёт за 45 дней, назначение админов."""
        return self.role in (self.Role.CHEF, self.Role.PROGRAMMER)

    @property
    def is_cafe_admin(self) -> bool:
        """Админ, шеф или программист: заказы, меню, столы, отчёты."""
        return self.role in (self.Role.ADMIN, self.Role.CHEF, self.Role.PROGRAMMER)

    @property
    def is_cook(self) -> bool:
        """Повар: статусы «Готовится», «Готов», стоп-лист."""
        return self.role == self.Role.COOK

    @property
    def is_waiter(self) -> bool:
        """Официант: заказы зала, вызовы со столов, «Подан на стол»."""
        return self.role == self.Role.WAITER

    @property
    def is_courier(self) -> bool:
        """Курьер: видит доставки, берёт заказ, «В пути», «Доставлен»."""
        return self.role == self.Role.COURIER

        # ----- Смена ролей -----

    def assignable_roles(self) -> list:
        """Какие роли этот сотрудник может назначать другим."""
        R = self.Role
        if self.role == R.PROGRAMMER:
            return [R.CHEF, R.ADMIN, R.COOK, R.WAITER, R.COURIER]
        if self.role == R.CHEF:
            return [R.ADMIN, R.COOK, R.WAITER, R.COURIER]
        if self.role == R.ADMIN:
            return [R.COOK, R.WAITER, R.COURIER]    
        return []                                        # повар, официант и курьер никому роли не назначают                           # повар и официант никому роли не назначают

    def can_manage(self, target: "User") -> bool:
        """
        Может ли редактировать / блокировать сотрудника target: себя нельзя, только тех, чью роль сам назначает,
        и (если сам не шеф) только из своего филиала.
        """
        if target.pk == self.pk or target.role not in self.assignable_roles():
            return False
        return self.is_chef or target.branch_id == self.branch_id     # админ — только своих

    def sees_all_branches(self) -> bool:
        """Шеф и программист видят все филиалы, остальные — только свой."""
        return self.is_chef

    def can_change_role(self, target: "User", new_role: str) -> bool:
        """Может ли поставить сотруднику target роль new_role."""
        return self.can_manage(target) and new_role in self.assignable_roles()
    
    def __str__(self) -> str:
        """Как сотрудник отображается в админке и в логах."""
        return f"{self.username} ({self.get_role_display()})"

class RoleChangeLog(models.Model):
    """Журнал смен ролей: кто, кому, с какой роли на какую и когда."""

    user = models.ForeignKey(                         # кому поменяли роль
        User, on_delete=models.CASCADE, related_name="role_changes", verbose_name="Сотрудник",
    )
    changed_by = models.ForeignKey(                   # кто поменял
        User, on_delete=models.SET_NULL, null=True, related_name="role_changes_made", verbose_name="Кто поменял",
    )
    old_role = models.CharField("Была роль", max_length=20, blank=True)   # пусто — сотрудник только что создан
    new_role = models.CharField("Стала роль", max_length=20)
    created_at = models.DateTimeField("Когда", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]                     # свежие сверху
        verbose_name = "Смена роли"
        verbose_name_plural = "Журнал смен ролей"

    def __str__(self):
        return f"{self.user}: {self.old_role or '—'} → {self.new_role}"