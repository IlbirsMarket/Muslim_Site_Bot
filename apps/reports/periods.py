"""Текущий период 45 дней: создание, автоматическое закрытие и архив."""

from datetime import timedelta                 # промежуток времени

from django.core.files.base import ContentFile  # сохранить байты как файл
from django.db import transaction               # "всё или ничего"
from django.utils import timezone               # сегодняшняя дата

from .builder import build_period_report
from .models import ReportPeriod
from .pdf import render_period_pdf


def _new_period(start_date) -> ReportPeriod:
    """Создать период из 45 дней, начиная с start_date."""
    return ReportPeriod.objects.create(
        start_date=start_date,
        end_date=start_date + timedelta(days=ReportPeriod.LENGTH_DAYS - 1),   # 45 дней включительно
    )


def close_period(period: ReportPeriod) -> None:
    """Закрыть период: посчитать итоги, сохранить PDF в архив."""
    data = build_period_report(period)                                 # цифры за весь период
    pdf_bytes = render_period_pdf(data)                                # рисуем PDF
    filename = f"period-{period.start_date:%Y%m%d}-{period.end_date:%Y%m%d}.pdf"
    period.pdf.save(filename, ContentFile(pdf_bytes), save=False)      # кладём файл в media/reports/
    period.revenue = data["revenue"]                                   # запоминаем итоги
    period.orders_count = data["orders_count"]
    period.is_closed = True
    period.closed_at = timezone.now()
    period.save()
    # Здесь позже будет отправка PDF в Telegram-группу (этап «Бот»)


@transaction.atomic
def get_current_period() -> ReportPeriod:
    """
    Текущий открытый период. Если его нет — создаём с сегодняшнего дня.
    Если 45 дней прошли — закрываем и открываем следующий (столько раз, сколько нужно).
    """
    today = timezone.localdate()
    period = ReportPeriod.objects.select_for_update().filter(is_closed=False).order_by("start_date").first()
    if period is None:                                                 # самый первый запуск
        return _new_period(today)
    while today > period.end_date:                                     # период закончился
        close_period(period)                                           # в архив
        period = _new_period(period.end_date + timedelta(days=1))      # следующий начинается на другой день
    return period