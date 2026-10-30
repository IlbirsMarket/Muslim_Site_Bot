"""
Нажатия кнопок сотрудниками в Telegram — без Telegram, только база.
Каждая функция возвращает текст ответа (всплывающее окно). Права — те же, что на сайте.
"""



from django.db import transaction                               # отметка и событие — вместе
from django.utils import timezone                               # текущее время
from rest_framework.exceptions import PermissionDenied, ValidationError   # ошибки правил заказа

from apps.cafe.models import Branch
from apps.menu.models import Category, Dish
from apps.orders.models import Order, TableCall
from apps.orders.status_service import available_actions, change_status, claim_order, close_visits
from apps.tables.models import Table
from .events import Kind, add_event
from .notify import CANCEL_REASONS
from .texts import staff_by_telegram

NO_LOGIN = "Сначала войдите: откройте бота в личке и нажмите «Войти как сотрудник»."
NO_RIGHTS = "Нет прав."


def _error_text(error) -> str:
    """Текст из ошибки DRF: {"action": "..."} или ["..."] → строка."""
    detail = getattr(error, "detail", str(error))
    while isinstance(detail, (dict, list)) and detail:
        detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
    return str(detail)


def _same_branch(user, branch_id) -> bool:
    """Шеф и программист — везде, остальные — только свой филиал."""
    return user.sees_all_branches() or user.branch_id == branch_id


def order_action(telegram_id: int, order_id: int, action: str, reason_index=None) -> str:
    """Кнопка под заказом: claim / accept / … / cancel (с причиной). Возвращает ответ или 'ask_reason'."""
    user = staff_by_telegram(telegram_id)
    if user is None:
        return NO_LOGIN
    order = Order.objects.select_related("claimed_by").filter(pk=order_id).first()
    if order is None or not _same_branch(user, order.branch_id):
        return NO_RIGHTS
    allowed = {a["action"] for a in available_actions(order, user)}      # что можно этому сотруднику
    if action not in allowed:
        return NO_RIGHTS
    if action == "cancel" and reason_index is None:                      # сначала спросим причину
        return "ask_reason"
    try:
        if action == "claim":
            claim_order(order, user)
        else:
            reason = CANCEL_REASONS[reason_index] if action == "cancel" else ""
            change_status(order, action, user, reason)
    except (ValidationError, PermissionDenied) as error:
        return _error_text(error)
    return "Готово ✅"


def call_done(telegram_id: int, call_id: int) -> str:
    """«Подошёл(ла)» под вызовом со стола."""
    user = staff_by_telegram(telegram_id)
    if user is None:
        return NO_LOGIN
    call = TableCall.objects.select_related("table").filter(pk=call_id).first()
    if call is None or not (user.is_waiter or user.is_cafe_admin or user.sees_all_branches()) or not _same_branch(user, call.table.branch_id):
        return NO_RIGHTS
    if not call.is_done:                                                 # повторное нажатие ничего не меняет
        with transaction.atomic():
            call.is_done, call.done_by, call.done_at = True, user, timezone.now()
            call.save(update_fields=["is_done", "done_by", "done_at"])
            add_event(Kind.CALL_DONE, call=call, user_id=user.id)       # бот обновит сообщение
    return "Готово ✅"


# ===== Меню по ролям (личка) =====

def user_branch(user):
    """Филиал сотрудника; у шефа / программиста — первый (для стоп-листа и столов)."""
    return user.branch or Branch.default()


def stop_categories(user) -> list:
    """Повар: категории своего филиала [(id, название)]."""
    return list(Category.objects.filter(branch=user_branch(user), is_active=True).values_list("id", "name"))


def stop_dishes(user, category_id) -> list:
    """Блюда категории [(id, название, в наличии)] — только своего филиала."""
    return list(Dish.objects.filter(category_id=category_id, category__branch=user_branch(user), is_active=True)
                .values_list("id", "name", "is_available"))


def toggle_dish(telegram_id: int, dish_id: int):
    """Включить / выключить блюдо в стоп-листе. Возвращает (ответ, id категории или None)."""
    user = staff_by_telegram(telegram_id)
    if user is None:
        return NO_LOGIN, None
    if not (user.is_cook or user.is_cafe_admin or user.sees_all_branches()):
        return NO_RIGHTS, None
    dish = Dish.objects.filter(pk=dish_id, category__branch=user_branch(user)).first()
    if dish is None:
        return NO_RIGHTS, None
    dish.is_available = not dish.is_available                            # переключаем
    dish.save(update_fields=["is_available", "updated_at"])
    return ("Снова в наличии" if dish.is_available else "В стоп-листе"), dish.category_id


def busy_tables(user) -> list:
    """Официант: занятые столы своего филиала [(id, название)]."""
    tables = Table.objects.filter(branch=user_branch(user), kind=Table.Kind.HALL, occupied_since__isnull=False).order_by("floor", "number")
    return [(t.id, str(t)) for t in tables]


def free_table(telegram_id: int, table_id: int) -> str:
    """«Освободить стол»."""
    user = staff_by_telegram(telegram_id)
    if user is None:
        return NO_LOGIN
    table = Table.objects.filter(pk=table_id, kind=Table.Kind.HALL).first()
    if table is None or not (user.is_waiter or user.is_cafe_admin or user.sees_all_branches()) or not _same_branch(user, table.branch_id):
        return NO_RIGHTS
    close_visits(table, user)
    return f"{table} свободен"


def can_see_report(user) -> bool:
    """Отчёт за день: админ, шеф, программист."""
    return bool(user) and (user.is_cafe_admin or user.sees_all_branches())


def day_report(user, branch_key: str = ""):
    """(текст, pdf-байты, имя файла) отчёта за сегодня. Шеф: branch_key = id или 'all'."""
    from apps.reports.builder import build_day_report
    from apps.reports.pdf import render_day_pdf
    from .texts import money
    if user.sees_all_branches():
        branch = None if branch_key == "all" else Branch.objects.filter(pk=int(branch_key or 0)).first() or Branch.default()
    else:
        branch = user.branch or Branch.default()                         # админ — только свой
    data = build_day_report(timezone.localdate(), branch)
    text = (f"📊 <b>Отчёт за {data['date']:%d.%m.%Y}</b> · {data['branch_name']}\n"
            f"Выручка: <b>{money(data['revenue'])}</b>\nЗаказов: {data['orders_count']} · средний чек {money(data['avg_check'])}\n"
            f"Отменено: {data['cancelled_count']} · в работе: {data['in_progress_count']}")
    return text, render_day_pdf(data), f"otchet-{data['date']:%Y-%m-%d}.pdf"
