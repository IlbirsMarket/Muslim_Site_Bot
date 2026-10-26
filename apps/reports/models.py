"""Периоды отчёта по 45 дней и их архив."""

from django.db import models   # поля для таблиц


class ReportPeriod(models.Model):
    """Один период отчёта. Открытый период — текущий, закрытые — архив."""

    LENGTH_DAYS = 45   # длина периода в днях

    start_date = models.DateField("Начало", unique=True)              # первый день периода
    end_date = models.DateField("Конец")                              # последний день (начало + 44 дня)
    is_closed = models.BooleanField("Закрыт", default=False)          # True — период в архиве
    closed_at = models.DateTimeField("Когда закрыт", null=True, blank=True)
    revenue = models.PositiveBigIntegerField("Выручка, сом", default=0)        # итог, сохраняется при закрытии
    orders_count = models.PositiveIntegerField("Заказов", default=0)           # итог, сохраняется при закрытии
    pdf = models.FileField("PDF-отчёт", upload_to="reports/", blank=True)      # файл в media/reports/

    class Meta:
        ordering = ["-start_date"]   # свежие периоды сверху
        verbose_name = "Период отчёта"
        verbose_name_plural = "Периоды отчётов (45 дней)"

    def __str__(self):
        return f"{self.start_date:%d.%m.%Y} — {self.end_date:%d.%m.%Y}"