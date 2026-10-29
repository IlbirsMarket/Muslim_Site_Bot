"""Адреса для входа сотрудников."""

from django.urls import path                                     # описание адресов

from .auth_views import LoginView, LogoutView, RefreshView      # вход, продление, выход
from .views import MeView                                        # "кто я"

urlpatterns = [
    path("login/", LoginView.as_view(), name="login"),                    # POST email/логин + пароль (+ remember) → токены
    path("refresh/", RefreshView.as_view(), name="token-refresh"),        # POST refresh → новый access и новый refresh
    path("logout/", LogoutView.as_view(), name="logout"),                 # POST refresh → ключ отменён («Выйти»)
    path("me/", MeView.as_view(), name="me"),                             # GET данные вошедшего сотрудника
]
