from django.apps import AppConfig  # базовый класс настроек приложения


class BotConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"  # тип id в таблицах
    name = "apps.bot"              # полный путь к приложению
    verbose_name = "Telegram-бот"  # название раздела в админке