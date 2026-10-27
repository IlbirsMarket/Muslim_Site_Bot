"""Адреса для входа сотрудников."""

from django.urls import path                                     # описание адресов
from rest_framework_simplejwt.views import TokenRefreshView      # готовый view: продление входа

from .auth_views import LoginView                                # вход по email или логину
from .views import MeView                                        # "кто я"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),                    # POST email/логин + пароль (+ remember) → токены
    path("refresh/", TokenRefreshView.as_view(), name="token-refresh"),   # POST refresh → новый access
    path("me/", MeView.as_view(), name="me"),                             # GET данные вошедшего сотрудника
]