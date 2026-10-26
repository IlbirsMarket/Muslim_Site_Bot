from django.apps import AppConfig  # базовый класс настроек приложения


class CafeConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # тип id в таблицах
    name = "apps.cafe"                  # полный путь к приложению
    verbose_name = "Настройки кафе"     # название раздела в админке