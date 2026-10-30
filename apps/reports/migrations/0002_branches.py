"""Периоды отчёта по филиалам; период без филиала — общий отчёт «Оба филиала»."""

import django.db.models.deletion
from django.db import migrations, models

import apps.cafe.models


def to_first_branch(apps, schema_editor):
    """Всё, что было до филиалов, — первому филиалу."""
    first = apps.get_model("cafe", "Branch").objects.order_by("position", "id").first()
    apps.get_model("reports", "ReportPeriod").objects.update(branch=first)

class Migration(migrations.Migration):

    dependencies = [
        ("reports", "0001_initial"),
        ("cafe", "0002_branches"),
    ]

    operations = [
        migrations.AddField(
            model_name="reportperiod", name="branch",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="report_periods",
                to="cafe.branch", verbose_name="Филиал",
            ),
        ),
        migrations.AlterField(
            model_name="reportperiod", name="start_date", field=models.DateField(verbose_name="Начало"),
        ),
        migrations.RunPython(to_first_branch, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="reportperiod",
            constraint=models.UniqueConstraint(fields=("branch", "start_date"), name="unique_period_per_branch"),
        ),
        migrations.AddConstraint(
            model_name="reportperiod",
            constraint=models.UniqueConstraint(
                condition=models.Q(branch__isnull=True), fields=("start_date",), name="unique_period_all_branches",
            ),
        ),
    ]
