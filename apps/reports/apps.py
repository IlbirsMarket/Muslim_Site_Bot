from django.apps import AppConfig  # базовый класс настроек приложения


class ReportsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # тип id в таблицах
    name = "apps.reports"       # полный путь к приложению
    verbose_name = "Отчёты"     # название раздела в админке