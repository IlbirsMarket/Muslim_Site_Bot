"""Адреса Telegram-бота для панели."""

from django.urls import path               # описание адресов

from .push_views import PushInboxView, PushKeyView, PushSubscribeView
from .views import TelegramView

urlpatterns = [
    path("staff/telegram/", TelegramView.as_view(), name="staff-telegram"),   # привязан ли Telegram / отвязать
    path("push/key/", PushKeyView.as_view(), name="push-key"),                 # ключ для push-уведомлений
    path("push/subscribe/", PushSubscribeView.as_view(), name="push-subscribe"),   # телефон разрешил уведомления
    path("push/inbox/", PushInboxView.as_view(), name="push-inbox"),           # тексты уведомлений для телефона
]