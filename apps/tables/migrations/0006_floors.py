"""
Этажи становятся списком у каждого филиала (вместо «ровно 2 этажа»).
У каждого филиала: 1 этаж + все этажи, на которых уже есть столы. Столы и их QR не меняются.
"""

import django.db.models.deletion
from django.db import migrations, models


def create_floors(apps, schema_editor):
    """Для каждого филиала — 1 этаж и этажи, где сейчас стоят столы."""
    Branch = apps.get_model("cafe", "Branch")
    Floor = apps.get_model("tables", "Floor")
    Table = apps.get_model("tables", "Table")
    for branch in Branch.objects.all():
        used = set(Table.objects.filter(branch=branch, kind="hall").values_list("floor", flat=True))
        for number in sorted(used | {1}):                         # 1 этаж есть всегда
            Floor.objects.get_or_create(branch=branch, number=number)


class Migration(migrations.Migration):

    dependencies = [
        ("tables", "0005_branches"),
        ("cafe", "0002_branches"),
    ]

    operations = [
        migrations.CreateModel(
            name="Floor",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("number", models.PositiveSmallIntegerField(verbose_name="Номер этажа")),
                ("branch", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="floors", to="cafe.branch",
                    verbose_name="Филиал",
                )),
            ],
            options={"verbose_name": "Этаж", "verbose_name_plural": "Этажи", "ordering": ["branch", "number"]},
        ),
        migrations.AddConstraint(
            model_name="floor",
            constraint=models.UniqueConstraint(fields=("branch", "number"), name="unique_floor_per_branch"),
        ),
        migrations.AlterField(
            model_name="table", name="floor",
            field=models.PositiveSmallIntegerField(default=1, verbose_name="Этаж"),
        ),
        migrations.RunPython(create_floors, migrations.RunPython.noop),
    ]
