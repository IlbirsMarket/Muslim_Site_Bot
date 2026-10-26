from django.apps import AppConfig  # базовый класс настроек приложения


class TablesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # тип id в таблицах
    name = "apps.tables"          # полный путь к приложению
    verbose_name = "Столы и QR"   # название раздела в админке