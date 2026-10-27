"""
Вход сотрудника: email или логин + пароль + галочка «Запомнить меня».
Отличие от стандартного входа simplejwt — срок жизни токена обновления:
  - без галочки: на одну смену (по умолчанию 12 часов);
  - с галочкой: надолго (по умолчанию 30 дней).
"""

from django.conf import settings                                      # наши настройки (сроки входа)
from django.contrib.auth.models import update_last_login              # запись «последний вход» в профиль
from rest_framework import serializers                                # инструменты DRF
from rest_framework_simplejwt.serializers import TokenObtainSerializer  # базовая проверка логина и пароля
from rest_framework_simplejwt.settings import api_settings            # настройки simplejwt
from rest_framework_simplejwt.tokens import RefreshToken              # токен обновления


class LoginSerializer(TokenObtainSerializer):
    """Тело запроса: {"username": "email или логин", "password": "...", "remember": true}."""

    token_class = RefreshToken                                          # какой токен выдаём после проверки пароля

    # Сообщение об ошибке по-русски (у simplejwt оно на английском)
    default_error_messages = {"no_active_account": "Неверный email/логин или пароль."}

    # Галочка «Запомнить меня». Если не прислали — считаем, что галочки нет
    remember = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        remember = attrs.pop("remember", False)                         # достаём галочку, дальше она не нужна
        data = super().validate(attrs)                                  # проверяем логин и пароль → self.user (иначе ошибка 401)

        refresh = self.get_token(self.user)                             # создаём токен обновления для сотрудника
        lifetime = settings.LOGIN_REMEMBER_LIFETIME if remember else settings.LOGIN_SESSION_LIFETIME
        refresh.set_exp(lifetime=lifetime)                              # ставим срок: надолго или на одну смену

        data["refresh"] = str(refresh)                                  # токен обновления
        data["access"] = str(refresh.access_token)                      # токен входа (им подписываются запросы)
        data["remember"] = remember                                     # фронт по нему решит, где хранить токены

        if api_settings.UPDATE_LAST_LOGIN:                              # если включено в настройках —
            update_last_login(None, self.user)                          # обновляем «последний вход»
        return data