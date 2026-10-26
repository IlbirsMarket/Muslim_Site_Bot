from django.apps import AppConfig  # базовый класс настроек приложения


class OrdersConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # тип id в таблицах
    name = "apps.orders"        # полный путь к приложению
    verbose_name = "Заказы"     # название раздела в админке