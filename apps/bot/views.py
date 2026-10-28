"""Адрес для панели: привязан ли Telegram у сотрудника и кнопка «Отвязать»."""

from django.conf import settings                       # имя бота из .env
from drf_spectacular.utils import extend_schema        # описание для Swagger
from rest_framework.response import Response           # ответ в JSON
from rest_framework.views import APIView               # простой view

from core.permissions import IsStaffMember             # любой сотрудник с ролью
from .services import unlink_telegram


def _state(user) -> dict:
    """Что показать в панели: привязан ли Telegram и где наш бот."""
    username = settings.TELEGRAM_BOT_USERNAME                               # имя бота без @ (пусто — бот не настроен)
    return {
        "telegram_id": user.telegram_id,                                    # пусто — не привязан
        "bot_username": username,
        "bot_url": f"https://t.me/{username}" if username else "",          # ссылка на бота
    }


class TelegramView(APIView):
    """
    GET    /api/staff/telegram/ — привязан ли мой Telegram и ссылка на бота.
    DELETE /api/staff/telegram/ — отвязать мой Telegram.
    Привязка — входом в боте: логин и пароль с сайта.
    """

    permission_classes = [IsStaffMember]

    @extend_schema(responses={200: dict})
    def get(self, request):
        return Response(_state(request.user))

    @extend_schema(request=None, responses={200: dict})
    def delete(self, request):
        unlink_telegram(request.user)                                       # убираем Telegram ID
        return Response(_state(request.user))