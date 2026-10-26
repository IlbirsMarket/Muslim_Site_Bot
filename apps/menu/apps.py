from django.apps import AppConfig  # базовый класс настроек приложения


class MenuConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # тип id в таблицах
    name = "apps.menu"       # полный путь к приложению
    verbose_name = "Меню"    # название раздела в админке