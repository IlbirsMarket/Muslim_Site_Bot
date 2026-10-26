"""Адреса для входа сотрудников."""

from django.urls import path                                                      # описание адресов
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView  # готовые views для JWT

from .views import MeView                                                         # "кто я"

urlpatterns = [
    path("login/", TokenObtainPairView.as_view(), name="login"),          # POST логин+пароль → токены access и refresh
    path("refresh/", TokenRefreshView.as_view(), name="token-refresh"),   # POST refresh → новый access
    path("me/", MeView.as_view(), name="me"),                             # GET данные вошедшего сотрудника
]