"""Адреса Telegram-бота для панели."""

from django.urls import path               # описание адресов

from .views import TelegramView

urlpatterns = [
    path("staff/telegram/", TelegramView.as_view(), name="staff-telegram"),   # привязан ли Telegram / отвязать
]