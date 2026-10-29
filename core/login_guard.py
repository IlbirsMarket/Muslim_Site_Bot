"""
Защита от подбора пароля — общая для сайта и Telegram-бота.

Два счётчика неверных паролей (хранятся в общем кэше — в базе, его видят все процессы сервера и бот):
  1. «логин + откуда»: 5 ошибок → пауза 15 минут.
     «Откуда» — IP на сайте или Telegram-аккаунт в боте. Злоумышленник с другого IP не мешает
     настоящему сотруднику войти: у того свой счётчик.
  2. «только логин»: 20 ошибок за час со всех мест вместе → логин закрыт до конца часа.
     Защита от подбора с многих IP сразу.
Каждая неверная попытка записывается в журнал сервера (без пароля): логин и откуда пытались.
"""

import logging                                     # журнал сервера (journalctl -u muslim)

from django.core.cache import cache                # общий кэш (таблица в базе)

logger = logging.getLogger("muslim.security")      # отдельное имя — легко найти в журнале

SOURCE_LIMIT = 5                                   # ошибок с одного места (IP / Telegram)
SOURCE_PAUSE = 15 * 60                             # пауза для этого места — 15 минут (в секундах)
LOGIN_LIMIT = 20                                   # ошибок на один логин со всех мест вместе
LOGIN_WINDOW = 60 * 60                             # окно для общего счётчика — 1 час (в секундах)


def _clean(login: str) -> str:
    """Логин без пробелов и маленькими буквами: «  Cook » и «cook» — один и тот же счётчик."""
    return (login or "").strip().lower()[:150]     # обрезаем — чтобы мусор не раздувал ключ


def _source_key(login: str, source: str) -> str:
    """Имя счётчика «логин + откуда»."""
    return f"login-fails:{_clean(login)}:{source}"


def _login_key(login: str) -> str:
    """Имя общего счётчика логина."""
    return f"login-fails-all:{_clean(login)}"


def wait_minutes(login: str, source: str) -> int:
    """
    0 — можно пробовать войти.
    Больше 0 — вход закрыт, через сколько минут (примерно) попробовать снова.
    """
    if cache.get(_source_key(login, source), 0) >= SOURCE_LIMIT:   # с этого места ошибок уже 5
        return SOURCE_PAUSE // 60                                  # 15 минут
    if cache.get(_login_key(login), 0) >= LOGIN_LIMIT:             # логин подбирают с разных мест
        return LOGIN_WINDOW // 60                                  # 60 минут
    return 0


def _bump(key: str, timeout: int) -> int:
    """Прибавить 1 к счётчику и вернуть новое значение. Счётчик сам исчезнет через timeout секунд."""
    if cache.add(key, 1, timeout):                 # счётчика не было — создали со значением 1
        return 1
    try:
        return cache.incr(key)                     # был — прибавляем 1
    except ValueError:                             # успел исчезнуть между проверками — создаём заново
        cache.set(key, 1, timeout)
        return 1


def record_failure(login: str, source: str) -> int:
    """Записать неверный пароль. Возвращает, сколько попыток осталось с этого места (0 — пауза)."""
    fails = _bump(_source_key(login, source), SOURCE_PAUSE)         # счётчик «логин + откуда»
    _bump(_login_key(login), LOGIN_WINDOW)                          # общий счётчик логина
    logger.warning("Неверный пароль: логин=%r, откуда=%s, ошибка №%s", _clean(login), source, fails)
    return max(SOURCE_LIMIT - fails, 0)


def record_success(login: str, source: str) -> None:
    """Вошёл — обнуляем счётчик этого места. Общий счётчик логина не трогаем: он сам истечёт через час."""
    cache.delete(_source_key(login, source))
