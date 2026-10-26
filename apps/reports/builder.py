"""
Подсчёт цифр для отчётов.
Все функции возвращают обычные словари — их отдаём в JSON и рисуем из них PDF.
"""

from datetime import datetime, time, timedelta            # даты и время

from django.db.models import Count, F, Sum                # подсчёты в базе: количество, сумма, поле
from django.db.models.functions import ExtractHour, TruncDate  # час из даты, дата без времени
from django.utils import timezone                         # часовой пояс

from apps.cafe.models import CafeSettings
from apps.orders.models import Order, OrderItem

S = Order.Status   # короткое имя


def _range(start_date, end_date):
    """Превращает даты «с … по …» (включительно) во время начала и конца по Бишкеку."""
    tz = timezone.get_current_timezone()                                                # Asia/Bishkek
    start = timezone.make_aware(datetime.combine(start_date, time.min), tz)            # 00:00 первого дня
    end = timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min), tz)  # 00:00 дня после последнего
    return start, end


def _orders(start_date, end_date):
    """Все заказы за период (по дате создания)."""
    start, end = _range(start_date, end_date)
    return Order.objects.filter(created_at__gte=start, created_at__lt=end)


def _percent(current, previous):
    """Изменение в процентах: +8.3 или -4.0. Если сравнивать не с чем — None."""
    if not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def revenue_for(start_date, end_date) -> int:
    """Выручка (только завершённые заказы) за период."""
    return _orders(start_date, end_date).filter(status=S.COMPLETED).aggregate(s=Sum("total"))["s"] or 0


def build_summary(start_date, end_date) -> dict:
    """Общие цифры за период: выручка, заказы, средний чек, разбивки, топ блюд."""
    orders = _orders(start_date, end_date)                    # все заказы периода
    done = orders.filter(status=S.COMPLETED)                  # завершённые — из них выручка

    totals = done.aggregate(revenue=Sum("total"), count=Count("id"))   # сумма и количество одним запросом
    revenue = totals["revenue"] or 0
    count = totals["count"]

    # Отменённые и причины отмены
    cancelled = orders.filter(status=S.CANCELLED)
    reasons = [
        {"reason": row["cancel_reason"] or "Без причины", "count": row["count"]}
        for row in cancelled.values("cancel_reason").annotate(count=Count("id")).order_by("-count")
    ]

    # Разбивка по типу: зал / доставка / самовывоз
    by_kind = {value: {"label": label, "count": 0, "revenue": 0} for value, label in Order.Kind.choices}
    for row in done.values("kind").annotate(count=Count("id"), revenue=Sum("total")):
        by_kind[row["kind"]].update(count=row["count"], revenue=row["revenue"] or 0)

    # Разбивка по оплате: наличные / карта
    by_payment = {value: {"label": label, "count": 0, "revenue": 0} for value, label in Order.Payment.choices}
    for row in done.values("payment_method").annotate(count=Count("id"), revenue=Sum("total")):
        by_payment[row["payment_method"]].update(count=row["count"], revenue=row["revenue"] or 0)

    # Топ-10 блюд по выручке
    top_dishes = [
        {"name": row["dish_name"], "quantity": row["total_qty"], "revenue": row["total_revenue"]}
        for row in OrderItem.objects.filter(order__in=done)
        .values("dish_name")                                                       # группируем по названию
        .annotate(total_qty=Sum("quantity"), total_revenue=Sum(F("unit_price") * F("quantity")))  # штуки и деньги (имена не совпадают с полями модели)
        .order_by("-total_revenue")[:10]
    ]

    return {
        "revenue": revenue,
        "orders_count": count,
        "avg_check": round(revenue / count) if count else 0,                   # средний чек
        "cancelled_count": cancelled.count(),
        "cancel_reasons": reasons,
        "in_progress_count": orders.exclude(status__in=[S.COMPLETED, S.CANCELLED]).count(),  # ещё в работе
        "by_kind": by_kind,
        "by_payment": by_payment,
        "top_dishes": top_dishes,
    }


def _hours_series(day) -> list:
    """Выручка по часам за один день (для графика)."""
    rows = (
        _orders(day, day).filter(status=S.COMPLETED)
        .annotate(hour=ExtractHour("created_at"))                  # час по Бишкеку
        .values("hour").annotate(revenue=Sum("total"), count=Count("id"))
    )
    data = {row["hour"]: row for row in rows}                      # {13: {...}, 19: {...}}

    cafe = CafeSettings.load()
    if cafe.opens_at <= cafe.closes_at:                            # обычный режим — часы работы
        hours = set(range(cafe.opens_at.hour, max(cafe.closes_at.hour, cafe.opens_at.hour + 1)))
    else:                                                          # работа через полночь — все 24 часа
        hours = set(range(24))
    hours |= set(data)                                             # плюс часы, где реально были заказы

    return [
        {
            "hour": hour,
            "label": f"{hour:02d}:00",
            "revenue": (data.get(hour) or {}).get("revenue") or 0,
            "count": (data.get(hour) or {}).get("count") or 0,
        }
        for hour in sorted(hours)
    ]


def _days_series(start_date, end_date) -> list:
    """Выручка по дням за период (для графика за 45 дней)."""
    rows = (
        _orders(start_date, end_date).filter(status=S.COMPLETED)
        .annotate(day=TruncDate("created_at"))                     # дата по Бишкеку
        .values("day").annotate(revenue=Sum("total"), count=Count("id"))
    )
    data = {row["day"]: row for row in rows}
    result = []
    current = start_date
    while current <= end_date:                                     # каждый день периода, даже без заказов
        row = data.get(current) or {}
        result.append({"date": current, "revenue": row.get("revenue") or 0, "count": row.get("count") or 0})
        current += timedelta(days=1)
    return result


def build_day_report(day) -> dict:
    """Отчёт за один день + сравнение с тем же днём неделю назад."""
    summary = build_summary(day, day)
    week_ago = day - timedelta(days=7)                             # тот же день недели прошлой недели
    previous = revenue_for(week_ago, week_ago)
    return {
        "date": day,
        **summary,
        "by_hour": _hours_series(day),
        "compare": {"date": week_ago, "revenue": previous, "change_percent": _percent(summary["revenue"], previous)},
    }


def build_period_report(period) -> dict:
    """Отчёт за период 45 дней (по сегодняшний день или по конец периода)."""
    from .models import ReportPeriod                               # импорт здесь, чтобы не было круговых импортов

    until = min(timezone.localdate(), period.end_date)             # считаем до сегодня или до конца периода
    summary = build_summary(period.start_date, until)
    previous = (                                                   # прошлый закрытый период для сравнения
        ReportPeriod.objects.filter(is_closed=True, end_date__lt=period.start_date).order_by("-end_date").first()
    )
    previous_revenue = previous.revenue if previous else None
    return {
        "period": {
            "id": period.id,
            "start_date": period.start_date,
            "end_date": period.end_date,
            "day_number": (until - period.start_date).days + 1,    # какой сейчас день периода (1–45)
            "days_total": period.LENGTH_DAYS,
            "is_closed": period.is_closed,
            "next_start": period.end_date + timedelta(days=1),     # когда начнётся новый период
        },
        **summary,
        "by_day": _days_series(period.start_date, until),
        "compare": {"previous_revenue": previous_revenue, "change_percent": _percent(summary["revenue"], previous_revenue)},
    }