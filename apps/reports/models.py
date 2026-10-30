"""Периоды отчёта по 45 дней и их архив."""

from django.db import models   # поля для таблиц


class ReportPeriod(models.Model):
    """Один период отчёта. Открытый период — текущий, закрытые — архив."""

    LENGTH_DAYS = 45   # длина периода в днях

    branch = models.ForeignKey(                                       # филиал; пусто — общий отчёт «Оба филиала»
        "cafe.Branch", on_delete=models.CASCADE, null=True, blank=True,
        related_name="report_periods", verbose_name="Филиал",
    )
    start_date = models.DateField("Начало")                           # первый день периода
    end_date = models.DateField("Конец")                              # последний день (начало + 44 дня)
    is_closed = models.BooleanField("Закрыт", default=False)          # True — период в архиве
    closed_at = models.DateTimeField("Когда закрыт", null=True, blank=True)
    revenue = models.PositiveBigIntegerField("Выручка, сом", default=0)        # итог, сохраняется при закрытии
    orders_count = models.PositiveIntegerField("Заказов", default=0)           # итог, сохраняется при закрытии
    pdf = models.FileField("PDF-отчёт", upload_to="reports/", blank=True)      # файл в media/reports/

    class Meta:
        ordering = ["-start_date"]   # свежие периоды сверху
        constraints = [
            # У филиала (и у общего отчёта) периоды не повторяются
            models.UniqueConstraint(fields=["branch", "start_date"], name="unique_period_per_branch"),
            models.UniqueConstraint(fields=["start_date"], condition=models.Q(branch__isnull=True), name="unique_period_all_branches"),
        ]
        verbose_name = "Период отчёта"
        verbose_name_plural = "Периоды отчётов (45 дней)"

    def __str__(self):
        return f"{self.start_date:%d.%m.%Y} — {self.end_date:%d.%m.%Y}"