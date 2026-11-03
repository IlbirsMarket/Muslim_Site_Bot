"""
Проверка данных мини-приложения Telegram (initData).

Когда сайт открыт внутри Telegram как мини-приложение, Telegram передаёт ему строку initData:
кто открыл (id, имя), когда, и подпись. Подпись делается токеном НАШЕГО бота — подделать её нельзя.
Порядок проверки — из документации Telegram (core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app):
  secret = HMAC_SHA256(ключ="WebAppData", данные=токен_бота)
  hash   = HMAC_SHA256(ключ=secret, данные="ключ=значение" всех полей кроме hash, по алфавиту, через \\n)
"""

import hashlib                                                    # SHA-256
import hmac                                                       # подпись и безопасное сравнение
import json                                                       # поле user — это JSON
import time                                                       # не слишком ли старые данные
from urllib.parse import parse_qsl                                # «a=1&b=2» → пары

MAX_AGE = 24 * 60 * 60                                            # данные старше суток не принимаем


def check_init_data(init_data: str, bot_token: str, max_age: int = MAX_AGE):
    """
    Вернёт данные Telegram {"user": {"id": …, "first_name": …}, "auth_date": …, …}
    или None, если подпись неверная, данные устарели или бот не настроен.
    """
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError:                                            # строка испорчена
        return None
    their_hash = pairs.pop("hash", "")
    check = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    our_hash = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not their_hash or not hmac.compare_digest(our_hash, their_hash):
        return None                                              # подпись не сходится — подделка или чужой бот
    try:
        if time.time() - int(pairs.get("auth_date", 0)) > max_age:
            return None                                          # слишком старые данные (могли скопировать)
        pairs["user"] = json.loads(pairs.get("user") or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(pairs["user"], dict) or not isinstance(pairs["user"].get("id"), int):
        return None
    return pairs


def sign_init_data(fields: dict, bot_token: str) -> str:
    """Подписать данные так же, как Telegram (нужно для тестов и проверки на своём компьютере)."""
    from urllib.parse import urlencode
    fields = {k: (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else str(v)) for k, v in fields.items()}
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)
