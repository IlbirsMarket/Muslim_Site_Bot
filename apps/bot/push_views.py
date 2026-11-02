"""
Push-уведомления: ключ для браузера, подписка телефона, «ящик» с текстами для сервис-воркера.
  GET  /api/push/key/        — публичный ключ VAPID (пусто — push не настроен)
  POST /api/push/subscribe/  — {endpoint, device_key}: сотрудник (с входом) или гость (по ключу устройства)
  POST /api/push/inbox/      — {endpoint}: тексты, которые ждут показа (и очистить)
"""

from django.conf import settings
from drf_spectacular.utils import OpenApiTypes, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import PushSubscription


def _endpoint(request) -> str:
    """Адрес подписки из запроса: только https и разумной длины."""
    value = str(request.data.get("endpoint") or "").strip()
    return value if value.startswith("https://") and len(value) <= 600 else ""


class PushKeyView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def get(self, request):
        return Response({"key": settings.VAPID_PUBLIC_KEY})


class PushSubscribeView(APIView):
    permission_classes = [AllowAny]                       # гость тоже может подписаться на статус своего заказа

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        endpoint = _endpoint(request)
        if not endpoint:
            return Response({"detail": "Неверная подписка."}, status=400)
        user = request.user if request.user.is_authenticated and getattr(request.user, "role", "") else None
        device_key = str(request.data.get("device_key") or "")[:64]
        if user is None and not device_key:
            return Response({"detail": "Нужен ключ устройства."}, status=400)
        PushSubscription.objects.update_or_create(endpoint=endpoint, defaults={"user": user, "device_key": "" if user else device_key})
        return Response({"ok": True})


class PushInboxView(APIView):
    permission_classes = [AllowAny]                       # знает только тот, у кого есть адрес подписки (он секретный)
    authentication_classes = []                           # сервис-воркер ходит без входа

    @extend_schema(request=OpenApiTypes.OBJECT, responses={200: OpenApiTypes.OBJECT})
    def post(self, request):
        sub = PushSubscription.objects.filter(endpoint=_endpoint(request)).first()
        if sub is None:
            return Response({"items": []})
        items, sub.pending = sub.pending or [], []
        sub.save(update_fields=["pending"])
        return Response({"items": items})
