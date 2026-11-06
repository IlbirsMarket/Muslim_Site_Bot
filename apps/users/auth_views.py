"""Вход, продление и выход сотрудника: /api/auth/login/, /refresh/, /logout/."""

from drf_spectacular.utils import extend_schema                  # описание для Swagger
from rest_framework import serializers, status                   # проверка тела запроса; коды ответов
from rest_framework.permissions import AllowAny                  # выйти может и тот, у кого токен входа уже истёк
from rest_framework.response import Response                     # ответ в JSON
from rest_framework.throttling import ScopedRateThrottle         # ограничение числа запросов
from rest_framework.views import APIView                         # обычный view
from rest_framework_simplejwt.exceptions import TokenError       # испорченный или просроченный ключ
from rest_framework_simplejwt.tokens import RefreshToken         # ключ продления
from rest_framework_simplejwt.views import TokenViewBase         # готовая основа для выдачи токенов

from core.permissions import IsStaffMember                       # только сотрудники

from .auth_serializers import LoginSerializer, RefreshSerializer  # проверка входа и продления


class LoginView(TokenViewBase):
    """
    Вход по email или логину и паролю. На сайте выключен (PASSWORD_LOGIN=0 в .env): в панель входят только по коду.
    Пароль сотрудника по-прежнему нужен для Telegram-бота. Ответ: {"access", "refresh", "remember"}.
    """

    serializer_class = LoginSerializer          # что проверяем
    throttle_classes = [ScopedRateThrottle]     # защита от подбора пароля (вдобавок к счётчику ошибок):
    throttle_scope = "login"                    # лимит берётся из DEFAULT_THROTTLE_RATES["login"]

    def post(self, request, *args, **kwargs):
        from django.conf import settings
        if not settings.PASSWORD_LOGIN:         # вход по паролю на сайте отключён
            return Response({"detail": "Вход по логину и паролю отключён. Войдите по своему коду."}, status=status.HTTP_403_FORBIDDEN)
        return super().post(request, *args, **kwargs)


class RefreshView(TokenViewBase):
    """Продление входа: старый ключ продления меняется на новый, старый больше не работает."""

    serializer_class = RefreshSerializer        # своя проверка: заблокирован? сменили пароль?
    throttle_classes = [ScopedRateThrottle]     # чтобы ключи не перебирали
    throttle_scope = "refresh"                  # лимит в DEFAULT_THROTTLE_RATES["refresh"]


class LogoutSerializer(serializers.Serializer):
    """Тело запроса выхода: {"refresh": "..."}."""

    refresh = serializers.CharField()           # ключ продления, который надо отменить


class LogoutView(APIView):
    """
    POST /api/auth/logout/ {"refresh": "..."} — «Выйти»: ключ продления отменяется на сервере.
    Даже если его кто-то скопировал, продлить вход по нему уже не получится.
    Всегда отвечает 204: уже отменённый или испорченный ключ — тоже «вышел».
    """

    permission_classes = [AllowAny]             # токен входа мог истечь — выйти всё равно можно
    authentication_classes = []                 # кто вошёл, не важно: отменяем именно присланный ключ
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "refresh"                  # тот же лимит, что у продления

    @extend_schema(request=LogoutSerializer, responses={204: None})
    def post(self, request):
        body = LogoutSerializer(data=request.data)
        body.is_valid(raise_exception=True)                       # нет поля refresh — ошибка 400
        try:
            RefreshToken(body.validated_data["refresh"]).blacklist()   # в чёрный список
        except TokenError:                                        # уже отменён, истёк или испорчен
            pass                                                  # результат тот же — вход не действует
        return Response(status=status.HTTP_204_NO_CONTENT)


class TelegramLoginSerializer(serializers.Serializer):
    """Вход в мини-приложении: initData от Telegram; если Telegram ещё не привязан — ещё логин и пароль (один раз)."""
    init_data = serializers.CharField()
    username = serializers.CharField(required=False, allow_blank=True)
    password = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False)


class TelegramLoginView(APIView):
    """
    POST /api/auth/telegram/ — вход в панель, открытую как мини-приложение из бота сотрудников.
      Telegram уже привязан к сотруднику → сразу токены (как «Запомнить меня»), пароль не нужен.
      Не привязан → 404 {"detail": "not_linked"}; фронт показывает форму, присылает логин и пароль —
      проверяем их (с той же защитой от подбора, что в боте), привязываем Telegram и выдаём токены.
    Подпись initData проверяется токеном бота сотрудников (core/telegram_webapp.py).
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"                                     # тот же лимит, что у обычного входа

    @extend_schema(request=TelegramLoginSerializer, responses={200: dict})
    def post(self, request):
        from django.conf import settings
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import update_last_login
        from core.telegram_webapp import check_init_data
        from apps.bot.services import login_from_telegram

        body = TelegramLoginSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = check_init_data(body.validated_data["init_data"], settings.TELEGRAM_STAFF_BOT_TOKEN)
        if data is None:                                         # подпись не сошлась или данные устарели
            return Response({"detail": "Откройте панель заново из бота сотрудников."}, status=status.HTTP_401_UNAUTHORIZED)
        telegram_id = data["user"]["id"]
        user = get_user_model().objects.filter(telegram_id=telegram_id, is_active=True).exclude(role="").first()
        if user is None:
            login, password = body.validated_data.get("username", ""), body.validated_data.get("password", "")
            if not login or not password:                        # первый раз — нужен пароль
                return Response({"detail": "not_linked"}, status=status.HTTP_404_NOT_FOUND)
            user, error = login_from_telegram(login.strip(), password, telegram_id)   # проверка + привязка Telegram
            if error:
                return Response({"detail": error}, status=status.HTTP_401_UNAUTHORIZED)
        refresh = RefreshToken.for_user(user)                    # ключ продления (попадает в список выданных)
        refresh.set_exp(lifetime=settings.LOGIN_REMEMBER_LIFETIME)   # как «Запомнить меня»: телефон сотрудника
        update_last_login(None, user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh), "remember": True})


class PinLoginSerializer(serializers.Serializer):
    """Тело запроса: {"device": "ключ устройства из браузера", "pin": "код сотрудника"}."""
    device = serializers.CharField(max_length=128, required=False, allow_blank=True)
    pin = serializers.CharField(max_length=32)                   # длину кода не выдаём: любой неверный набор — «Неверный код»


class PinLoginView(APIView):
    """
    POST /api/auth/pin/ — вход в панель по коду сотрудника (единственный вход на сайте).
    Вход — на одну смену (12 часов). Защита от подбора — apps/users/pin_login.py.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"                                     # не больше 10 попыток в минуту с одного IP

    @extend_schema(request=PinLoginSerializer, responses={200: dict})
    def post(self, request):
        from django.conf import settings
        from django.contrib.auth.models import update_last_login
        from core.client_ip import client_ip
        from . import pin_login

        if not settings.PIN_LOGIN:                                # вход по коду пока выключен
            return Response({"detail": "Вход по коду выключен."}, status=status.HTTP_404_NOT_FOUND)
        body = PinLoginSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        device, ip = body.validated_data.get("device", ""), client_ip(request)
        minutes = pin_login.wait_minutes(device, ip)
        if minutes:
            return Response({"detail": f"Слишком много неверных кодов. Попробуйте через {minutes} минут."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        user, left = pin_login.check(device, ip, body.validated_data["pin"].strip())
        if user is None:
            return Response({"detail": "Неверный код." + (f" Осталось попыток: {left}." if left else " Вход по коду закрыт на 15 минут.")},
                            status=status.HTTP_401_UNAUTHORIZED)
        refresh = RefreshToken.for_user(user)
        refresh.set_exp(lifetime=settings.LOGIN_SESSION_LIFETIME)  # одна смена
        update_last_login(None, user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh), "remember": False})


class MyPinSerializer(serializers.Serializer):
    """{"pin": "новый код"} — от 2 до 8 цифр."""
    pin = serializers.CharField(max_length=8)


class MyPinView(APIView):
    """POST /api/auth/me/pin/ — сотрудник сам меняет свой код (старый никто не видит, даже админ)."""
    permission_classes = [IsStaffMember]

    @extend_schema(request=MyPinSerializer, responses={200: dict})
    def post(self, request):
        from django.conf import settings
        from .serializers import check_pin
        if not settings.PIN_LOGIN:                                # вход по коду пока выключен
            return Response({"detail": "Вход по коду выключен."}, status=status.HTTP_404_NOT_FOUND)
        body = MyPinSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        code = check_pin(body.validated_data["pin"], request.user, required=True)
        request.user.set_pin(code)
        request.user.save(update_fields=["pin_hash"])
        return Response({"has_pin": True})
