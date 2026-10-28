"""
«Почтовый ящик» для бота: сайт вызывает add_event, бот потом забирает события.
Вызывать внутри той же транзакции, где меняется заказ, — тогда изменение и событие сохраняются вместе.
"""

from .models import BotEvent   # таблица событий

Kind = BotEvent.Kind           # короткое имя: Kind.ORDER_CREATED, Kind.CALL_DONE и т.д.


def add_event(kind, order=None, call=None, table=None, **payload) -> BotEvent:
    """
    Записать событие для бота.
    payload — мелкие подробности, только числа и строки: action="accept", user_id=3.
    """
    if kind not in Kind.values:                                   # опечатка в типе события — сразу ошибка
        raise ValueError(f"Неизвестный тип события: {kind}")
    return BotEvent.objects.create(                               # одна строка в «почтовом ящике»
        kind=kind, order=order, call=call, table=table, payload=payload,
    )