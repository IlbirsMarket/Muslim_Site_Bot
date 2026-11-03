"""
Бот сотрудников работает через ТЕ ЖЕ адреса API, что и панель на сайте (/api/admin/…, /api/staff/…).
Запрос не уходит в интернет: мы вызываем view Django прямо внутри процесса бота, от имени сотрудника.
Поэтому права, проверки полей, ошибки и база — одни и те же у сайта и у бота.
"""

from urllib.parse import urlsplit                                # разобрать адрес на путь и ?параметры

from django.conf import settings                                 # ALLOWED_HOSTS, SITE_URL
from django.http import QueryDict                                # ?active=true → словарь параметров
from django.urls import Resolver404, resolve                     # адрес → нужный view
from rest_framework.test import APIRequestFactory, force_authenticate   # «запрос» без сети, вход без пароля


def _host() -> str:
    """Имя сайта для запроса: первое из ALLOWED_HOSTS (иначе Django отклонит «чужой» адрес)."""
    for host in settings.ALLOWED_HOSTS:
        host = host.strip()
        if host and host != "*" and not host.startswith("."):
            return host
    return "localhost"


def _factory() -> APIRequestFactory:
    """Фабрика запросов: тот же домен и https, что у сайта (ссылки на фото и QR получаются правильные)."""
    secure = settings.SITE_URL.startswith("https")
    return APIRequestFactory(SERVER_NAME=_host(), SERVER_PORT="443" if secure else "80",
                             **({"wsgi.url_scheme": "https"} if secure else {}))


class Result:
    """Ответ API: status (200, 201, 400…), data (JSON) или content (PNG / PDF), ok — всё хорошо."""

    def __init__(self, status: int, data=None, content: bytes = b"", content_type: str = ""):
        self.status, self.data, self.content, self.content_type = status, data, content, content_type

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    @property
    def error(self) -> str:
        """Понятный текст ошибки: {"name": ["Укажите название."]} → «Укажите название.»"""
        if self.status == 404:                                    # «No Dish matches the given query» — по-русски
            return "Не найдено — возможно, уже удалено или это другой филиал."
        detail = self.data
        while isinstance(detail, (dict, list)) and detail:
            detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
        if not detail:
            return "Нет прав." if self.status == 403 else f"Ошибка {self.status}."
        return str(detail)


def call(user, method: str, path: str, data=None, branch=None, multipart: bool = False) -> Result:
    """
    Вызвать API панели от имени сотрудника.
      path — как на сайте, без /api: "/admin/dishes/5/", "/staff/orders/?active=true"
      branch — id филиала (как переключатель на сайте, заголовок X-Branch); у админа, повара и т.д. сервер всё равно берёт свой филиал
      multipart — отправка файла (фото блюда)
    """
    url = "/api" + path
    parts = urlsplit(url)
    try:
        match = resolve(parts.path)                              # какой view отвечает за этот адрес
    except Resolver404:
        return Result(404)
    headers = {"HTTP_X_BRANCH": str(branch)} if branch else {}
    factory = _factory()
    method = method.lower()
    if method == "get":
        request = factory.get(parts.path, QueryDict(parts.query).dict(), **headers)
    else:
        request = getattr(factory, method)(url, data or {}, format="multipart" if multipart else "json", **headers)
    force_authenticate(request, user=user)                       # «вошёл» тот сотрудник, который нажал кнопку
    response = match.func(request, *match.args, **match.kwargs)
    content_type = response.get("Content-Type", "")
    if hasattr(response, "data"):                                 # обычный ответ DRF (JSON)
        return Result(response.status_code, response.data)
    if getattr(response, "streaming", False):                     # файл из архива отдаётся «потоком» — собираем целиком
        content = b"".join(response.streaming_content)
    else:
        content = response.content
    return Result(response.status_code, content=content, content_type=content_type)   # картинка или PDF
