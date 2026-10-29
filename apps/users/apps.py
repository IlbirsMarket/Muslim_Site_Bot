from django.apps import AppConfig  # базовый класс настроек приложения


class UsersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # тип id в таблицах
    name = "apps.users"            # полный путь к приложению (оно лежит в папке apps)
    verbose_name = "Пользователи"  # название раздела в админке Django

    def ready(self):
        """Django загрузился — подключаем автоматическую защиту (apps/users/signals.py)."""
        from . import signals  # noqa: F401 — сам импорт подписывает функции на события сохранения
