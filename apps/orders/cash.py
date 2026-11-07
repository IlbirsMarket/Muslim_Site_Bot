"""
«Касса»: смена кассира.
Открыть смену (наличных на начало) → внесения и изъятия → закрыть смену (посчитали наличные) → отчёт на чековый аппарат.
В итоги смены идут все оплаты филиала за время смены: у кассы, у официантов и доставки.
"""

from django.db import transaction                                  # «всё или ничего»
from django.db.models import Count, Sum                            # подсчёты в базе
from django.utils import timezone                                  # время по Бишкеку
from rest_framework.exceptions import ValidationError              # ошибка 400

from .billing import add_job
from .models import CashMove, CashShift, Order, PrintJob


def _person(user) -> str:
    return (user.get_full_name() or user.username) if user else ""


def current_shift(branch):
    """Открытая смена филиала (или None)."""
    return CashShift.objects.filter(branch=branch, closed_at__isnull=True).select_related("opened_by").first()


def require_shift(branch) -> CashShift:
    """Кассир принимает оплату только в открытую смену."""
    shift = current_shift(branch)
    if not shift:
        raise ValidationError("Сначала откройте смену в разделе «Касса».")
    return shift


def stats(shift) -> dict:
    """Цифры смены: наличные, карта, сколько счетов, внесения / изъятия, сколько должно быть в кассе."""
    end = shift.closed_at or timezone.now()
    paid = Order.objects.filter(branch=shift.branch, paid_at__gte=shift.opened_at, paid_at__lt=end)
    sums = paid.aggregate(cash=Sum("paid_cash"), card=Sum("paid_card"), count=Count("id"))
    moves = list(shift.moves.select_related("created_by"))
    cash_in = sum(m.amount for m in moves if m.kind == CashMove.Kind.IN)
    cash_out = sum(m.amount for m in moves if m.kind == CashMove.Kind.OUT)
    cash = sums["cash"] or 0
    return {
        "cash": cash, "card": sums["card"] or 0, "total": cash + (sums["card"] or 0),
        "orders": sums["count"],
        "cash_in": cash_in, "cash_out": cash_out,
        "expected": shift.opening_cash + cash + cash_in - cash_out,                 # должно быть в кассе
        "moves": [{"kind": m.kind, "label": m.get_kind_display(), "amount": m.amount, "comment": m.comment,
                   "by": _person(m.created_by), "at": m.created_at} for m in moves],
    }


def shift_data(shift) -> dict:
    """Смена для панели."""
    if not shift:
        return {"shift": None}
    return {"shift": {
        "id": shift.id, "opened_at": shift.opened_at, "opened_by": _person(shift.opened_by),
        "opening_cash": shift.opening_cash, "closed_at": shift.closed_at, "counted_cash": shift.counted_cash,
        **stats(shift),
    }}


@transaction.atomic
def open_shift(branch, user, cash) -> CashShift:
    """«Открыть смену»: сколько наличных в кассе на начало."""
    if current_shift(branch):
        raise ValidationError("Смена уже открыта.")
    shift = CashShift.objects.create(branch=branch, opened_by=user, opening_cash=cash or 0)
    return shift


@transaction.atomic
def move(branch, user, kind, amount, comment="") -> CashMove:
    """«Внесение» / «Изъятие» наличных."""
    shift = require_shift(branch)
    if kind not in CashMove.Kind.values:
        raise ValidationError("Внесение или изъятие.")
    if not amount or amount <= 0:
        raise ValidationError("Укажите сумму.")
    if kind == CashMove.Kind.OUT and amount > stats(shift)["expected"]:
        raise ValidationError("В кассе нет столько наличных.")
    return CashMove.objects.create(shift=shift, kind=kind, amount=amount, comment=(comment or "")[:150], created_by=user)


# ===================== ОФИЦИАНТЫ ЗА СМЕНУ =====================

def waiters(shift) -> dict:
    """
    Официанты за смену кассы: оплаченные за смену заказы зала, которые вёл официант (взял стол / вбил заказ),
    сколько столов и на какую сумму, и выплата — процентом от суммы или вписанная вручную.
    """
    end = shift.closed_at or timezone.now()
    rows = (Order.objects.filter(branch=shift.branch, paid_at__gte=shift.opened_at, paid_at__lt=end,
                                 kind=Order.Kind.HALL, claimed_by__isnull=False, claimed_by__role="waiter")
            .values("claimed_by", "claimed_by__first_name", "claimed_by__last_name", "claimed_by__username")
            .annotate(orders=Count("id"), total=Sum("total")).order_by("-total"))
    pay = shift.waiter_pay or {}
    mode, percent, amounts = pay.get("mode", "percent"), pay.get("percent", 0) or 0, pay.get("amounts", {}) or {}
    people = []
    for row in rows:
        name = f"{row['claimed_by__first_name']} {row['claimed_by__last_name']}".strip() or row["claimed_by__username"]
        total = row["total"] or 0
        saved = amounts.get(str(row["claimed_by"]))
        amount = saved if saved is not None else (round(total * percent / 100) if mode == "percent" else 0)
        people.append({"id": row["claimed_by"], "name": name, "orders": row["orders"], "total": total, "amount": amount})
    return {"mode": mode, "percent": percent, "rows": people, "paid_out": bool(pay.get("paid_out")),
            "orders": sum(p["orders"] for p in people), "total": sum(p["total"] for p in people),
            "amount": sum(p["amount"] for p in people)}


def waiter_orders(shift, waiter_id) -> list:
    """Заказы одного официанта за смену (те же, что в его сумме): стол, когда открыт и оплачен, что заказали, чек."""
    from .billing import paid_receipt
    end = shift.closed_at or timezone.now()
    orders = (Order.objects.filter(branch=shift.branch, paid_at__gte=shift.opened_at, paid_at__lt=end,
                                   kind=Order.Kind.HALL, claimed_by_id=waiter_id)
              .select_related("table", "branch", "claimed_by", "accepted_by", "paid_by").prefetch_related("items").order_by("-paid_at"))
    return [{
        "id": o.id, "table": str(o.table) if o.table_id else "", "created_at": o.created_at, "paid_at": o.paid_at,
        "total": o.total, "method": o.get_paid_method_display(),
        "items": [{"name": i.dish_name + (f" {i.size_name}" if i.size_name else ""), "extras": [e.get("name", "") for e in (i.extras or [])],
                   "qty": i.quantity, "sum": i.unit_price * i.quantity} for i in o.items.all()],
        "receipt": paid_receipt([o]),                                          # чек об оплате — показать и напечатать копию
    } for o in orders]


@transaction.atomic
def save_waiters(branch, mode, percent, amounts) -> dict:
    """«Сохранить»: способ (процент / вручную), процент и суммы каждому официанту."""
    shift = CashShift.objects.select_for_update().filter(branch=branch, closed_at__isnull=True).first()
    if not shift:
        raise ValidationError("Откройте смену в «Кассе».")
    if mode not in ("percent", "manual"):
        raise ValidationError("Выберите: процент или сумма вручную.")
    try:
        percent = float(percent or 0)
        clean = {str(int(k)): int(v) for k, v in (amounts or {}).items() if v not in (None, "")}
    except (TypeError, ValueError):
        raise ValidationError("Суммы и процент — только числа.")
    if not 0 <= percent <= 100 or any(v < 0 for v in clean.values()):
        raise ValidationError("Процент — от 0 до 100, суммы — не меньше 0.")
    shift.waiter_pay = {**(shift.waiter_pay or {}), "mode": mode, "percent": percent, "amounts": clean}
    shift.save(update_fields=["waiter_pay"])
    return waiters(shift)


@transaction.atomic
def pay_out_waiters(branch, user) -> dict:
    """«Выдать из кассы»: общая сумма выплат — изъятие «Официантам» (один раз за смену)."""
    shift = CashShift.objects.select_for_update().filter(branch=branch, closed_at__isnull=True).first()
    if not shift:
        raise ValidationError("Откройте смену в «Кассе».")
    data = waiters(shift)
    if data["paid_out"]:
        raise ValidationError("Официантам уже выдано из кассы в эту смену.")
    if data["amount"] <= 0:
        raise ValidationError("Сначала посчитайте и сохраните выплаты.")
    move(branch, user, CashMove.Kind.OUT, data["amount"], "Официантам")
    shift.waiter_pay = {**(shift.waiter_pay or {}), "paid_out": True}
    shift.save(update_fields=["waiter_pay"])
    return waiters(shift)


def _waiters_print(data) -> dict:
    """Блок «ОФИЦИАНТЫ» для чека: кто, сколько столов, сумма, выплата."""
    return {"waiters": [{"name": r["name"], "orders": r["orders"], "total": r["total"], "amount": r["amount"]} for r in data["rows"]],
            "waiters_percent": data["percent"] if data["mode"] == "percent" else None, "waiters_amount": data["amount"]}


def print_waiters(branch) -> None:
    """«Напечатать»: список официантов за смену на чековый аппарат зала."""
    shift = current_shift(branch)
    if not shift:
        raise ValidationError("Откройте смену в «Кассе».")
    now = timezone.localtime()
    add_job(branch, PrintJob.Kind.SHIFT, {"title": "ОФИЦИАНТЫ ЗА СМЕНУ", "waiters_only": True, "branch": branch.name,
                                          "date": f"{now:%d.%m.%Y}", "opened": f"{timezone.localtime(shift.opened_at):%H:%M}",
                                          "closed": f"{now:%H:%M}", "cashier": _person(shift.opened_by), **_waiters_print(waiters(shift))})


def _payload(shift, data) -> dict:
    """Отчёт за смену для чекового аппарата."""
    opened = timezone.localtime(shift.opened_at)
    closed = timezone.localtime(shift.closed_at)
    return {
        "title": "ОТЧЁТ ЗА СМЕНУ", "branch": shift.branch.name,
        "date": f"{opened:%d.%m.%Y}", "opened": f"{opened:%H:%M}", "closed": f"{closed:%H:%M}",
        "cashier": _person(shift.opened_by), "closed_by": _person(shift.closed_by),
        "opening_cash": shift.opening_cash, "counted": shift.counted_cash,
        "difference": shift.counted_cash - data["expected"],
        **{k: data[k] for k in ("cash", "card", "total", "orders", "cash_in", "cash_out", "expected")},
        **_waiters_print(waiters(shift)),                                          # официанты и их выплаты
    }


@transaction.atomic
def close_shift(branch, user, counted) -> dict:
    """«Закрыть смену»: посчитали наличные → итоги в смене → отчёт на чековый аппарат."""
    shift = CashShift.objects.select_for_update().filter(branch=branch, closed_at__isnull=True).first()
    if not shift:
        raise ValidationError("Открытой смены нет.")
    if counted is None:
        raise ValidationError("Посчитайте наличные в кассе и укажите сумму.")
    shift.closed_at, shift.closed_by, shift.counted_cash = timezone.now(), user, counted
    data = stats(shift)
    report = _payload(shift, data)
    shift.report = report
    shift.save(update_fields=["closed_at", "closed_by", "counted_cash", "report"])
    add_job(branch, PrintJob.Kind.SHIFT, report)
    return report


def shifts_report(start, end, branch=None) -> list:
    """Закрытые смены за период — для отчётов админа."""
    shifts = CashShift.objects.filter(closed_at__isnull=False, opened_at__gte=start, opened_at__lt=end)
    if branch is not None:
        shifts = shifts.filter(branch=branch)
    result = []
    for shift in shifts.select_related("opened_by", "branch").order_by("opened_at"):
        r = shift.report or {}
        result.append({
            "id": shift.id, "cashier": _person(shift.opened_by), "branch": shift.branch.name,
            "opened_at": shift.opened_at, "closed_at": shift.closed_at,
            "cash": r.get("cash", 0), "card": r.get("card", 0), "orders": r.get("orders", 0),
            "expected": r.get("expected", 0), "counted": shift.counted_cash, "difference": r.get("difference", 0),
        })
    return result


def past_shifts(branch, limit=15) -> list:
    """«Прошлые смены» в «Кассе»: последние закрытые смены — кто открыл, кто закрыл, суммы и разница."""
    rows = []
    for shift in CashShift.objects.filter(branch=branch, closed_at__isnull=False).select_related("opened_by", "closed_by").order_by("-opened_at")[:limit]:
        r = shift.report or {}
        rows.append({
            "id": shift.id, "opened_at": shift.opened_at, "closed_at": shift.closed_at,
            "opened_by": _person(shift.opened_by), "closed_by": _person(shift.closed_by),
            "opening_cash": shift.opening_cash, "cash": r.get("cash", 0), "card": r.get("card", 0),
            "orders": r.get("orders", 0), "cash_in": r.get("cash_in", 0), "cash_out": r.get("cash_out", 0),
            "expected": r.get("expected", 0), "counted": shift.counted_cash, "difference": r.get("difference", 0),
            "report": r,                                                           # отчёт — показать и напечатать копию
        })
    return rows


def shift_copy(branch, shift_id) -> None:
    """Копия отчёта закрытой смены на чековый аппарат."""
    shift = CashShift.objects.filter(branch=branch, pk=shift_id, closed_at__isnull=False).first()
    if not shift or not shift.report:
        raise ValidationError("Смена не найдена.")
    add_job(branch, PrintJob.Kind.SHIFT, {**shift.report, "title": "ОТЧЁТ ЗА СМЕНУ (КОПИЯ)"})


def history(branch, shift=None, limit=60) -> list:
    """
    «История оплат» внизу «Кассы»: оплаты за смену (без смены — за сегодня), новые сверху.
    Заказы, оплаченные одним нажатием «Оплачено», — одна строка.
    """
    from .billing import bill_title, paid_receipt
    if shift:
        start = shift.opened_at
    else:
        start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    paid = (Order.objects.filter(branch=branch, paid_at__gte=start)
            .select_related("table", "paid_by", "claimed_by", "branch").prefetch_related("items").order_by("-paid_at"))
    groups = {}
    for order in paid[:limit * 3]:
        groups.setdefault((order.paid_at, order.paid_by_id), []).append(order)
    rows = []
    for (paid_at, _), orders in list(groups.items())[:limit]:
        first = orders[0]
        rows.append({
            "orders": sorted(o.id for o in orders), "title": bill_title(orders), "kind": first.kind,
            "paid_at": paid_at, "method": first.get_paid_method_display(),
            "cash": sum(o.paid_cash for o in orders), "card": sum(o.paid_card for o in orders),
            "total": sum(o.total for o in orders), "by": _person(first.paid_by),
            "receipt": paid_receipt(orders),                                       # чек — показать по нажатию на строку
        })
    return rows
