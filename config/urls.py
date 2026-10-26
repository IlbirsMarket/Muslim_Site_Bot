"""
Главный файл адресов проекта.
Сюда будем подключать адреса каждого приложения.
"""

from django.conf import settings                    # настройки проекта
from django.conf.urls.static import static          # раздача загруженных фото при разработке
from django.contrib import admin                    # админка Django
from django.urls import path, include              # описание адресов | include — подключить адреса приложения
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView  # Swagger

urlpatterns = [
    path("admin/", admin.site.urls),  
    path("api/", include("apps.menu.urls")),         # меню: /api/menu/, /api/admin/dishes/ ...                                                  # админка Django: /admin/
    path("api/auth/", include("apps.users.urls")),   # вход: /api/auth/login/, /api/auth/me/
    path("api/", include("apps.users.staff_urls")),  # сотрудники: /api/admin/staff/
    path("api/", include("apps.tables.urls")),       # столы: /api/tables/{token}/, /api/admin/tables/
    path("api/", include("apps.cafe.urls")),         # настройки: /api/cafe/, /api/admin/cafe/
    path("api/", include("apps.orders.urls")),       # заказы: /api/orders/, /api/staff/orders/ ...
    path("api/", include("apps.reports.urls")),      # отчёты: /api/admin/reports/day/, /api/admin/reports/periods/
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),                   # схема API (OpenAPI)
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),  # страница Swagger
]

# При разработке Django сам раздаёт фото из папки media
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)