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
    """Вход по email или логину. Ответ: {"access", "refresh", "remember"}."""

    serializer_class = LoginSerializer          # что проверяем
    throttle_classes = [ScopedRateThrottle]     # защита от подбора пароля (вдобавок к счётчику ошибок):
    throttle_scope = "login"                    # лимит берётся из DEFAULT_THROTTLE_RATES["login"]


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
    """Тело запроса: {"device": "ключ устройства из браузера", "pin": "66"}."""
    device = serializers.CharField(max_length=128)
    pin = serializers.CharField(max_length=2)


class PinLoginView(APIView):
    """
    POST /api/auth/pin/ — быстрый вход по коду из 2 цифр (как в 1С). Работает только на устройстве,
    где этот сотрудник уже входил по логину и паролю (apps/users/pin_login.py).
    Вход — на одну смену (12 часов), как без «Запомнить меня». 5 неверных кодов с устройства → пауза 15 минут.
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"                                     # тот же лимит, что у входа по паролю

    @extend_schema(request=PinLoginSerializer, responses={200: dict})
    def post(self, request):
        from django.conf import settings
        from django.contrib.auth.models import update_last_login
        from core import login_guard
        from core.client_ip import client_ip
        from . import pin_login

        body = PinLoginSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        device, pin = body.validated_data["device"], body.validated_data["pin"]
        if not pin_login.valid_device(device) or not pin_login.known_device(device):   # здесь ещё никто не входил по паролю
            return Response({"detail": "Вход по коду на этом устройстве ещё не включён. Войдите один раз по логину и паролю."},
                            status=status.HTTP_403_FORBIDDEN)
        guard = "pin:" + pin_login.device_hash(device)[:16]      # счётчик ошибок — на устройство
        source = "ip:" + client_ip(request)
        minutes = login_guard.wait_minutes(guard, source)
        if minutes:
            return Response({"detail": f"Слишком много неверных кодов. Попробуйте через {minutes} минут."},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)
        user, error = pin_login.find_user(device, pin) if pin_login.PIN_RE.match(pin) else (None, "wrong")
        if error == "not_here":                                   # код верный, но на этом устройстве не было входа по паролю
            return Response({"detail": "На этом устройстве войдите один раз по логину и паролю — потом хватит кода."},
                            status=status.HTTP_403_FORBIDDEN)
        if user is None:
            left = login_guard.record_failure(guard, source)
            return Response({"detail": "Неверный код." + (f" Осталось попыток: {left}." if left else " Вход по коду закрыт на 15 минут.")},
                            status=status.HTTP_401_UNAUTHORIZED)
        login_guard.record_success(guard, source)
        refresh = RefreshToken.for_user(user)
        refresh.set_exp(lifetime=settings.LOGIN_SESSION_LIFETIME)  # одна смена
        update_last_login(None, user)
        return Response({"access": str(refresh.access_token), "refresh": str(refresh), "remember": False})


class MyPinSerializer(serializers.Serializer):
    """{"pin": "66"} — свой код; пустая строка — убрать код."""
    pin = serializers.CharField(max_length=2, allow_blank=True)


class MyPinView(APIView):
    """POST /api/auth/me/pin/ — сотрудник сам ставит себе код входа (шефу его больше никто не поставит)."""
    permission_classes = [IsStaffMember]

    @extend_schema(request=MyPinSerializer, responses={200: dict})
    def post(self, request):
        from .serializers import check_pin
        body = MyPinSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        request.user.pin = check_pin(body.validated_data["pin"], request.user)
        request.user.save(update_fields=["pin"])
        return Response({"pin": request.user.pin})
