"""Обработчики запросов заказов для гостей."""

from drf_spectacular.utils import extend_schema          # описание для Swagger
from rest_framework import generics, status              # готовые views и коды ответов
from rest_framework.permissions import AllowAny          # доступ для всех
from rest_framework.response import Response             # ответ в JSON
from rest_framework.throttling import ScopedRateThrottle # ограничение частоты запросов

from .models import Order
from .serializers import OrderCreateSerializer, OrderPublicSerializer, TableCallCreateSerializer


class OrderCreateView(generics.CreateAPIView):
    """POST /api/orders/ — гость оформляет заказ."""

    serializer_class = OrderCreateSerializer
    permission_classes = [AllowAny]               # вход не нужен
    throttle_classes = [ScopedRateThrottle]       # защита от спама
    throttle_scope = "orders"                     # лимит берём из настроек (10 в минуту)

    @extend_schema(responses={201: OrderPublicSerializer})   # для Swagger: в ответ придёт заказ
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)   # данные от фронта
        serializer.is_valid(raise_exception=True)             # проверка; при ошибке — ответ 400 с текстом
        order = serializer.save()                             # создаём заказ
        data = OrderPublicSerializer(order).data              # готовим ответ
        return Response(data, status=status.HTTP_201_CREATED) # 201 — создано


class OrderPublicDetailView(generics.RetrieveAPIView):
    """GET /api/orders/{public_id}/ — гость смотрит статус своего заказа."""

    serializer_class = OrderPublicSerializer
    permission_classes = [AllowAny]
    lookup_field = "public_id"                    # ищем по секретному id, а не по номеру
    queryset = Order.objects.select_related("table").prefetch_related("items", "status_logs")


class TableCallCreateView(generics.CreateAPIView):
    """POST /api/table-calls/ — «Позвать официанта» или «Попросить счёт»."""

    serializer_class = TableCallCreateSerializer
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "calls"                      # лимит из настроек (5 в минуту)

class ChangesVersionView(generics.GenericAPIView):
    """
    GET /api/version/ — номер последнего изменения (заказ, статус, вызов, стол).
    Панель и сайт гостя спрашивают его раз в 1–2 секунды: ответ крошечный, а полный список
    заказов загружается только когда номер поменялся. Так изменения видны всем почти сразу.
    """

    permission_classes = [AllowAny]

    @extend_schema(responses={200: {"type": "object", "properties": {"v": {"type": "integer"}}}})
    def get(self, request):
        from apps.bot.models import BotEvent                       # каждое изменение записывается событием для бота
        last = BotEvent.objects.order_by("-id").values_list("id", flat=True).first() or 0
        response = Response({"v": last})
        response["Cache-Control"] = "no-store"                     # всегда свежий ответ
        return response


class TelegramGuestContactView(generics.GenericAPIView):
    """
    POST /api/telegram/guest/ {"init_data": "…"} — мини-приложение гостевого бота: имя и телефон из прошлого заказа.
    Telegram сам номер телефона не отдаёт (его можно только попросить у гостя). Поэтому номер, который гость
    уже указывал в прошлом заказе из Telegram, подставляем сразу — как имя; поменять его можно.
    Подпись initData проверяется токеном гостевого бота: видны только СВОИ прошлые данные.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "calls"

    @extend_schema(request=None, responses={200: dict})
    def post(self, request):
        from django.conf import settings
        from core.telegram_webapp import check_init_data
        data = check_init_data(str(request.data.get("init_data") or ""), settings.TELEGRAM_GUEST_BOT_TOKEN)
        if data is None:
            return Response({"detail": "Откройте меню заново из бота."}, status=status.HTTP_401_UNAUTHORIZED)
        last = (Order.objects.filter(guest_chat_id=data["user"]["id"]).exclude(phone="")
                .order_by("-created_at").values("customer_name", "phone").first()) or {}
        return Response({"name": last.get("customer_name") or data["user"].get("first_name", ""), "phone": last.get("phone", "")})
