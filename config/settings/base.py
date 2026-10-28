"""
Базовые настройки проекта.
Здесь всё, что одинаково и при разработке, и на сервере.
"""

from pathlib import Path          # удобная работа с путями к файлам
from datetime import timedelta    # нужен, чтобы задать срок жизни токенов
import os                         # чтение переменных окружения
from dotenv import load_dotenv    # загрузка переменных из файла .env

# Корень проекта — папка, где лежит manage.py (поднимаемся на 3 уровня вверх)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Читаем файл .env из корня проекта
load_dotenv(BASE_DIR / ".env")

# Секретный ключ Django (шифрование сессий, токенов). Берём из .env
SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-insecure-key")

# Режим отладки выключен по умолчанию. Включаем его только в dev.py
DEBUG = False

# С каких адресов можно обращаться к серверу (через запятую в .env)
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
# Адрес сайта для гостей (фронтенд). На него ведут QR-коды столов
SITE_URL = os.getenv("SITE_URL", "http://localhost:5173")

# Адрес стандартной Django-админки. На сервере меняем на "django-admin/",
# потому что /admin занят нашей панелью кафе
DJANGO_ADMIN_URL = os.getenv("DJANGO_ADMIN_URL", "admin/")

# ---------- ПРИЛОЖЕНИЯ ----------

# Встроенные приложения Django
DJANGO_APPS = [
    "django.contrib.admin",          # стандартная админка Django
    "django.contrib.auth",           # пользователи и пароли
    "django.contrib.contenttypes",   # служебное: типы моделей
    "django.contrib.sessions",       # сессии (вход в админку)
    "django.contrib.messages",       # всплывающие сообщения в админке
    "django.contrib.staticfiles",    # статические файлы (css, js админки)
]

# Сторонние библиотеки
THIRD_PARTY_APPS = [
    "rest_framework",                # Django REST Framework
    "rest_framework_simplejwt",      # JWT-токены для входа
    "corsheaders",                   # разрешаем запросы от React
    "django_filters",                # фильтры в API (?category=2)
    "drf_spectacular",               # Swagger-документация
]

# Наши приложения (будем добавлять по ходу)
LOCAL_APPS = [
    "apps.users",                    # пользователи и роли
    "apps.menu",                     # меню кафе
    "apps.tables",                   # столы и QR
    "apps.cafe",                     # настройки кафе
    "apps.orders",                   # заказы
    "apps.reports",                  # отчёты
    "apps.bot",                      # Telegram-бот
]

# Итоговый список: Django + библиотеки + наши
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# ---------- MIDDLEWARE (срабатывают на каждый запрос сверху вниз) ----------

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",                    # CORS — должен стоять как можно выше
    "django.middleware.security.SecurityMiddleware",            # базовая защита
    "django.contrib.sessions.middleware.SessionMiddleware",     # сессии
    "django.middleware.common.CommonMiddleware",                # общие обработки (слэши в URL и т.п.)
    "django.middleware.csrf.CsrfViewMiddleware",                # защита форм от подделки
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # определяет, кто вошёл
    "django.contrib.messages.middleware.MessageMiddleware",     # сообщения
    "django.middleware.clickjacking.XFrameOptionsMiddleware",   # защита от встраивания сайта в чужой iframe
]

# Где лежит главный файл с адресами
ROOT_URLCONF = "config.urls"

# Шаблоны HTML — нужны для админки Django
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",  # стандартный движок шаблонов
        "DIRS": [],                                                    # своих шаблонов пока нет
        "APP_DIRS": True,                                              # искать шаблоны внутри приложений
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# Точка входа для веб-сервера
WSGI_APPLICATION = "config.wsgi.application"


# ---------- БАЗА ДАННЫХ ----------

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",  # используем SQLite
        "NAME": BASE_DIR / "db.sqlite3",         # файл базы в корне проекта
    }
}

# Говорим Django: используй НАШУ модель пользователя, а не стандартную
AUTH_USER_MODEL = "users.User"

# Как проверять вход: по логину ИЛИ по email (вместо стандартной проверки только по логину)
AUTHENTICATION_BACKENDS = ["apps.users.auth_backends.EmailOrUsernameBackend"]

# Проверки надёжности паролей
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},  # не похож на логин
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},            # минимум 8 символов
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},           # не "123456"
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},           # не только цифры
]


# ---------- ЯЗЫК И ВРЕМЯ ----------

LANGUAGE_CODE = "ru"          # язык админки и сообщений об ошибках
TIME_ZONE = "Asia/Bishkek"    # часовой пояс кафе
USE_I18N = True               # включить переводы
USE_TZ = True                 # хранить время с учётом часового пояса


# ---------- ФАЙЛЫ ----------

STATIC_URL = "static/"                  # адрес статики (css/js админки)
STATIC_ROOT = BASE_DIR / "staticfiles"  # куда собирать статику на сервере
MEDIA_URL = "media/"                    # адрес загруженных файлов (фото блюд)
MEDIA_ROOT = BASE_DIR / "media"         # папка, куда сохраняются фото

# Тип id по умолчанию для всех таблиц
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------- DJANGO REST FRAMEWORK ----------

REST_FRAMEWORK = {
    # Как определяем пользователя: по JWT-токену или по сессии (для просмотра API в браузере)
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    # По умолчанию всё закрыто. Открытые адреса (меню, заказ) откроем явно
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Включаем фильтры для всех списков
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
    ],
    # Схема для Swagger-документации
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",

    # Лимиты частоты запросов (защита от спама)
    # "DEFAULT_THROTTLE_RATES": {
    #     "orders": "10/min",   # не больше 10 заказов в минуту с одного устройства
    #     "calls": "5/min",     # не больше 5 вызовов официанта в минуту
    # },

        "DEFAULT_THROTTLE_RATES": {
        "orders": "60/min",   # гости в кафе сидят на одном Wi-Fi (один IP), поэтому лимит с запасом
        "calls": "30/min",    # от повторных нажатий и так защищает правило «не чаще раза в 2 минуты со стола»
        "login": "10/min",    # не больше 10 попыток входа в минуту с одного IP (защита от подбора пароля)
    },
}

# Настройки JWT-токенов
SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=12),  # токен входа живёт 12 часов (смена в кафе)
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),   # токен обновления — 7 дней
}

# Сколько держится вход сотрудника (см. apps/users/auth_serializers.py)
LOGIN_SESSION_LIFETIME = timedelta(hours=12)   # без галочки «Запомнить меня» — одна смена
LOGIN_REMEMBER_LIFETIME = timedelta(days=30)   # с галочкой — 30 дней, потом снова ввести пароль


# Настройки Swagger-документации
SPECTACULAR_SETTINGS = {
    "TITLE": "Муслим — API",                                      # заголовок документации
    "DESCRIPTION": "API для сайта-меню, заказов и админ-панели",  # описание
    "VERSION": "1.0.0",                                           # версия API
    "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"], # документацию видят все
}

# Каким адресам фронтенда разрешено обращаться к API (через запятую в .env)
CORS_ALLOWED_ORIGINS = [
    origin for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if origin
]


# ===== Telegram-бот (всё из .env; если пусто — бот выключен, сайт работает как обычно) =====
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")                       # токен от @BotFather — секрет, только в .env
TELEGRAM_BOT_USERNAME = os.getenv("TELEGRAM_BOT_USERNAME", "").lstrip("@")     # имя бота без @: для ссылки привязки
TELEGRAM_GROUP_ID = int(os.getenv("TELEGRAM_GROUP_ID") or 0)                   # ID группы «Муслим — смена» (отрицательное число)
TELEGRAM_TOPICS = {                                                            # ID тем группы; 0 — тема не настроена
    place: int(os.getenv(f"TELEGRAM_TOPIC_{place.upper()}") or 0)
    for place in ("admins", "kitchen", "hall", "delivery", "reports")
}