"""
Текущий период 45 дней: создание, автоматическое закрытие и архив.
У каждого филиала свои периоды, у общего отчёта «Оба филиала» (branch=None) — свои.
Даты периодов у всех одинаковые: новый филиал начинает с того же дня, что и остальные.
"""

from datetime import timedelta                 # промежуток времени

from django.core.files.base import ContentFile  # сохранить байты как файл
from django.db import transaction               # "всё или ничего"
from django.utils import timezone               # сегодняшняя дата

from .builder import build_period_report
from .models import ReportPeriod
from .pdf import render_period_pdf


def _new_period(start_date, branch=None) -> ReportPeriod:
    """Создать период из 45 дней, начиная с start_date."""
    return ReportPeriod.objects.create(
        branch=branch,
        start_date=start_date,
        end_date=start_date + timedelta(days=ReportPeriod.LENGTH_DAYS - 1),   # 45 дней включительно
    )


def close_period(period: ReportPeriod) -> None:
    """Закрыть период: посчитать итоги, сохранить PDF в архив."""
    data = build_period_report(period)                                 # цифры за весь период
    pdf_bytes = render_period_pdf(data)                                # рисуем PDF
    scope = f"branch{period.branch_id}" if period.branch_id else "all"   # чей отчёт: филиал или оба
    filename = f"period-{scope}-{period.start_date:%Y%m%d}-{period.end_date:%Y%m%d}.pdf"
    period.pdf.save(filename, ContentFile(pdf_bytes), save=False)      # кладём файл в media/reports/
    period.revenue = data["revenue"]                                   # запоминаем итоги
    period.orders_count = data["orders_count"]
    period.is_closed = True
    period.closed_at = timezone.now()
    period.save()
    # Здесь позже будет отправка PDF в Telegram-группу (этап «Бот»)


@transaction.atomic
def get_current_period(branch=None) -> ReportPeriod:
    """
    Текущий открытый период филиала (branch=None — общий «Оба филиала»).
    Если его нет — начинаем с того же дня, что и периоды других филиалов (или с сегодня, если периодов ещё нет).
    Если 45 дней прошли — закрываем и открываем следующий (столько раз, сколько нужно).
    """
    today = timezone.localdate()
    open_periods = ReportPeriod.objects.select_for_update().filter(is_closed=False)
    period = open_periods.filter(branch=branch).order_by("start_date").first()
    if period is None:                                                 # у этого филиала периода ещё нет
        other = open_periods.order_by("start_date").first()            # период другого филиала — берём его даты
        period = _new_period(other.start_date if other else today, branch)
    while today > period.end_date:                                     # период закончился
        close_period(period)                                           # в архив
        period = _new_period(period.end_date + timedelta(days=1), branch)   # следующий начинается на другой день
    return period