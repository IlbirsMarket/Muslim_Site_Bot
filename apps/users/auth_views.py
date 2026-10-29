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
