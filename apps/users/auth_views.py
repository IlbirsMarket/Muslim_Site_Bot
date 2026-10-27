"""Адрес входа сотрудника: POST /api/auth/login/."""

from rest_framework.throttling import ScopedRateThrottle      # ограничение числа попыток
from rest_framework_simplejwt.views import TokenViewBase      # готовая основа для выдачи токенов

from .auth_serializers import LoginSerializer                  # проверка email/логина, пароля и галочки


class LoginView(TokenViewBase):
    """Вход по email или логину. Ответ: {"access", "refresh", "remember"}."""

    serializer_class = LoginSerializer          # что проверяем
    throttle_classes = [ScopedRateThrottle]     # защита от подбора пароля:
    throttle_scope = "login"                    # лимит берётся из DEFAULT_THROTTLE_RATES["login"]