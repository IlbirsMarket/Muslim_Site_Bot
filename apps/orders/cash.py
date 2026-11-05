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
