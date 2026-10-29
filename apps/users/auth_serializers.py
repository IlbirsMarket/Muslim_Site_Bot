"""
Вход сотрудника: email или логин + пароль + галочка «Запомнить меня».
Отличия от стандартного входа simplejwt:
  - срок входа: без галочки — одна смена (12 часов), с галочкой — 7 дней. Потом снова пароль;
  - защита от подбора пароля (core/login_guard.py): 5 ошибок с одного IP → пауза 15 минут;
  - при каждом продлении выдаётся новый ключ продления, старый сразу перестаёт работать,
    а срок входа не продлевается: через 12 часов / 7 дней всё равно нужен пароль.
"""

from django.conf import settings                                      # наши настройки (сроки входа)
from django.contrib.auth import get_user_model                        # модель сотрудника
from django.contrib.auth.models import update_last_login              # запись «последний вход» в профиль
from rest_framework import serializers                                # инструменты DRF
from rest_framework.exceptions import AuthenticationFailed, Throttled # ошибки 401 и 429
from rest_framework_simplejwt.serializers import TokenObtainSerializer  # базовая проверка логина и пароля
from rest_framework_simplejwt.settings import api_settings            # настройки simplejwt
from rest_framework_simplejwt.tokens import RefreshToken              # токен обновления (ключ продления)
from rest_framework_simplejwt.utils import get_md5_hash_password      # «отпечаток» пароля внутри токена

from core import login_guard                                          # общая защита от подбора пароля
from core.client_ip import client_ip                                  # настоящий IP за nginx


class LoginSerializer(TokenObtainSerializer):
    """Тело запроса: {"username": "email или логин", "password": "...", "remember": true}."""

    token_class = RefreshToken                                          # какой токен выдаём после проверки пароля

    # Сообщение об ошибке по-русски (у simplejwt оно на английском)
    default_error_messages = {"no_active_account": "Неверный email/логин или пароль."}

    # Галочка «Запомнить меня». Если не прислали — считаем, что галочки нет
    remember = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        remember = attrs.pop("remember", False)                         # достаём галочку, дальше она не нужна
        login = attrs.get(self.username_field, "")                      # что ввели в поле «email или логин»
        source = "ip:" + client_ip(self.context.get("request"))         # откуда пытаются войти

        minutes = login_guard.wait_minutes(login, source)               # не закрыт ли вход после ошибок?
        if minutes:
            raise Throttled(detail=f"Слишком много неверных попыток. Попробуйте через {minutes} минут.")

        try:
            data = super().validate(attrs)                              # проверяем логин и пароль → self.user
        except AuthenticationFailed:
            login_guard.record_failure(login, source)                   # считаем ошибку и пишем в журнал
            raise                                                       # ответ 401 «Неверный email/логин или пароль»
        login_guard.record_success(login, source)                       # вошёл — счётчик этого места обнуляем

        refresh = self.get_token(self.user)                             # создаём ключ продления для сотрудника
        lifetime = settings.LOGIN_REMEMBER_LIFETIME if remember else settings.LOGIN_SESSION_LIFETIME
        refresh.set_exp(lifetime=lifetime)                              # срок входа: 7 дней или одна смена

        data["refresh"] = str(refresh)                                  # ключ продления
        data["access"] = str(refresh.access_token)                      # токен входа на 15 минут (им подписываются запросы)
        data["remember"] = remember                                     # фронт по нему решит, где хранить токены

        update_last_login(None, self.user)                              # «последний вход» — виден в разделе сотрудников
        return data


class RefreshSerializer(serializers.Serializer):
    """
    Продление входа: {"refresh": "..."} → {"access": "...", "refresh": "новый"}.
    Старый ключ продления после этого не работает (попадает в чёрный список).
    Срок входа не меняется: новый ключ истекает тогда же, когда истёк бы старый.
    """

    refresh = serializers.CharField()                                   # ключ продления от фронта
    access = serializers.CharField(read_only=True)                      # новый токен входа

    default_error_messages = {"no_active_account": "Вход больше не действует. Войдите снова."}

    def validate(self, attrs):
        refresh = RefreshToken(attrs["refresh"])                        # проверка подписи, срока и чёрного списка (иначе 401)
        user_id = refresh.payload.get(api_settings.USER_ID_CLAIM)       # чей это ключ
        user = get_user_model().objects.filter(**{api_settings.USER_ID_FIELD: user_id}).first()
        password_mark = refresh.payload.get(api_settings.REVOKE_TOKEN_CLAIM)   # отпечаток пароля на момент входа
        if (
            not user                                                    # сотрудника удалили
            or not user.is_active                                       # или заблокировали
            or password_mark != get_md5_hash_password(user.password)    # или сменили ему пароль
        ):
            raise AuthenticationFailed(self.error_messages["no_active_account"], "no_active_account")

        expires = refresh["exp"]                                        # когда истекает вход — запоминаем
        refresh.blacklist()                                             # старый ключ больше не примут
        refresh.set_jti()                                               # у нового ключа — новый номер
        refresh.set_iat()                                               # и новое время выдачи
        refresh["exp"] = expires                                        # срок — прежний (вход не продлевается бесконечно)
        refresh.outstand()                                              # записываем новый ключ в список выданных
        return {"access": str(refresh.access_token), "refresh": str(refresh)}
